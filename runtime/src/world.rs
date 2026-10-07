//! Single mutable world owner. Time advances only through its fixed native
//! batch, never through player requests. This is an experimental host slice;
//! durable economy/inventory operations are deliberately not admitted yet.
use crate::contracts::{Action, Command, Id, Outcome, Refusal, Status, ToolUse};
use crate::native::Kernel;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

pub const DT_S: f64 = 1.0 / 240.0;
pub const STEPS_PER_BATCH: u32 = 4;
pub const COMMAND_CAPACITY: usize = 64;
const MAX_RECEIPTS: usize = 4096;

/// Supplied by a trusted host connection, not derived from command.actor_id.
/// A future HTTP gateway authenticates principal and restricts host_action.
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TrustedRequest {
    pub principal: Id,
    #[serde(default)]
    pub host_action: bool,
    pub command: Command,
}

struct Receipt {
    digest: Vec<u8>,
    status: Status,
    reason: Option<Refusal>,
    revision: u64,
    tick: u64,
    simulation_s: f64,
    tool_use_result: Option<ToolUse>,
}

struct PendingPickup {
    instance: String,
    started_attempted_ticks: u64,
}

#[derive(Clone)]
struct PendingToolUse {
    tool: String,
    point_id: u32,
    started_s: f64,
    started_attempted_ticks: u64,
}

impl PendingToolUse {
    fn matches(&self, state: &ToolUse) -> bool {
        state.tool == self.tool
            && state.point_id == self.point_id
            && state.started_s == self.started_s
    }
}

#[derive(Debug, Serialize)]
pub struct ClockState {
    pub tick: u64,
    pub attempted_ticks: u64,
    pub simulation_s: f64,
    pub dt_s: f64,
    pub steps_per_batch: u32,
    pub fault: Option<Refusal>,
}

pub struct World<K: Kernel> {
    id: Id,
    allowed: BTreeSet<String>,
    joined: BTreeSet<String>,
    sequences: BTreeMap<String, u64>,
    receipts: BTreeMap<(String, String), Receipt>,
    pending_pickups: BTreeMap<(String, String), PendingPickup>,
    pending_tool_uses: BTreeMap<(String, String), PendingToolUse>,
    completions: Vec<Outcome>,
    kernel: K,
    revision: u64,
    clock: ClockState,
}

impl<K: Kernel> World<K> {
    pub fn new(id: Id, allowed: Vec<Id>, kernel: K) -> Result<Self, Refusal> {
        let time = kernel.state()["t"]
            .as_f64()
            .ok_or(Refusal::KernelUnavailable)?;
        if !time.is_finite()
            || time != 0.0
            || allowed.is_empty()
            || allowed.len() > 64
            || kernel.state()["native_players"]
                .as_object()
                .is_some_and(|p| !p.is_empty())
        {
            return Err(Refusal::InvalidInput);
        }
        Ok(Self {
            id,
            allowed: allowed.iter().map(|a| a.as_str().to_owned()).collect(),
            joined: BTreeSet::new(),
            sequences: BTreeMap::new(),
            receipts: BTreeMap::new(),
            pending_pickups: BTreeMap::new(),
            pending_tool_uses: BTreeMap::new(),
            completions: Vec::new(),
            kernel,
            revision: 0,
            clock: ClockState {
                tick: 0,
                attempted_ticks: 0,
                simulation_s: time,
                dt_s: DT_S,
                steps_per_batch: STEPS_PER_BATCH,
                fault: None,
            },
        })
    }

    pub fn clock(&self) -> &ClockState {
        &self.clock
    }

    pub fn advance(&mut self) -> Result<(), Refusal> {
        if let Some(fault) = self.clock.fault {
            return Err(fault);
        }
        let before_tick = self.clock.tick;
        self.clock.attempted_ticks += u64::from(STEPS_PER_BATCH);
        let result = self.kernel.advance(DT_S, STEPS_PER_BATCH).and_then(|()| {
            let time = self.kernel.state()["t"]
                .as_f64()
                .ok_or(Refusal::KernelUnavailable)?;
            let ticks = (time - self.clock.simulation_s) / DT_S;
            // Rollback/short native batches do not count as accepted time.
            if !ticks.is_finite()
                || ticks < -1e-6
                || ticks > f64::from(STEPS_PER_BATCH) + 1e-6
                || (ticks - ticks.round()).abs() > 1e-6
            {
                return Err(Refusal::KernelUnavailable);
            }
            self.clock.tick += ticks.round().max(0.0) as u64;
            self.clock.simulation_s = time;
            Ok(())
        });
        if let Err(reason) = result {
            self.clock.fault = Some(reason);
        } else if !self.pending_pickups.is_empty() {
            // Confirm after an accepted physical batch, not wield's boolean.
            // A rollback keeps the request pending instead of granting it.
            {
                for ((actor, command_id), pending) in std::mem::take(&mut self.pending_pickups) {
                    if (self.clock.tick == before_tick
                        || self.kernel.state()["stepped_back"] == true)
                        && self.clock.attempted_ticks - pending.started_attempted_ticks < 480
                    {
                        self.pending_pickups.insert((actor, command_id), pending);
                        continue;
                    }
                    let confirmed = self.kernel.state()["player_hands"][&actor]["holding"].as_str()
                        == Some(pending.instance.as_str())
                        && self.clock.tick > before_tick
                        && self.kernel.state()["stepped_back"] != true;
                    let status = if confirmed {
                        Status::Applied
                    } else {
                        Status::Rejected
                    };
                    let mut reason = if confirmed {
                        None
                    } else {
                        Some(Refusal::NativeRefused)
                    };
                    if !confirmed
                        && self.kernel.state()["player_hands"][&actor]["holding"].as_str()
                            == Some(pending.instance.as_str())
                    {
                        // An expired unconfirmed hold cannot retain custody.
                        if let Err(fault) = self.kernel.release(&actor) {
                            reason = Some(fault);
                            self.clock.fault = Some(fault);
                        }
                    }
                    let receipt = self
                        .receipts
                        .get_mut(&(actor.clone(), command_id.clone()))
                        .expect("pending receipt");
                    receipt.status = status.clone();
                    receipt.reason = reason;
                    receipt.tick = self.clock.tick;
                    receipt.simulation_s = self.clock.simulation_s;
                    let revision = receipt.revision;
                    let snapshot = self.observation(&actor);
                    self.completions.push(Outcome {
                        schema: "banjo.outcome.v1".into(),
                        command_id: Id::new(command_id).expect("validated id"),
                        actor_id: Id::new(actor).expect("validated actor"),
                        status,
                        reason,
                        revision,
                        tick: self.clock.tick,
                        simulation_s: self.clock.simulation_s,
                        snapshot,
                        tool_use_result: None,
                    });
                }
            }
        }
        if let Err(fault) = result {
            self.fault_tool_uses(fault);
            return Err(fault);
        }
        self.resolve_tool_uses(before_tick)
    }

    fn resolve_tool_uses(&mut self, before_tick: u64) -> Result<(), Refusal> {
        let keys: Vec<_> = self.pending_tool_uses.keys().cloned().collect();
        for key in keys {
            let pending = self
                .pending_tool_uses
                .get(&key)
                .expect("pending tool key")
                .clone();
            let state = self
                .kernel
                .tool_use(&key.0)
                .and_then(|s| s.ok_or(Refusal::KernelUnavailable));
            let state = match state {
                Ok(s) if pending.matches(&s) => s,
                _ => {
                    self.clock.fault = Some(Refusal::KernelUnavailable);
                    self.fault_tool_uses(Refusal::KernelUnavailable);
                    return Err(Refusal::KernelUnavailable);
                }
            };
            if self.clock.attempted_ticks - pending.started_attempted_ticks >= 2400 {
                // No synthetic completion or recovery pose on a stalled solver.
                self.pending_tool_uses.remove(&key);
                self.complete_tool_use(key, Some(Refusal::NativeRefused), Some(state));
                self.clock.fault = Some(Refusal::NativeRefused);
                self.fault_tool_uses(Refusal::NativeRefused);
                return Err(Refusal::NativeRefused);
            }
            if state.active
                || state.contact_pending
                || self.clock.tick == before_tick
                || self.kernel.state()["stepped_back"] == true
            {
                continue;
            }
            let reason = state.refusal()?.or_else(|| {
                (state.loosened_m3.total() == 0.0).then_some(if state.contacted {
                    Refusal::InsufficientWork
                } else {
                    Refusal::NoContact
                })
            });
            self.pending_tool_uses.remove(&key);
            self.complete_tool_use(key, reason, Some(state));
        }
        Ok(())
    }

    fn fault_tool_uses(&mut self, reason: Refusal) {
        for (key, _) in std::mem::take(&mut self.pending_tool_uses) {
            self.complete_tool_use(key, Some(reason), None);
        }
    }

    fn complete_tool_use(
        &mut self,
        key: (String, String),
        reason: Option<Refusal>,
        result: Option<ToolUse>,
    ) {
        self.revision += 1;
        let receipt = self.receipts.get_mut(&key).expect("pending tool receipt");
        receipt.status = if reason.is_some() {
            Status::Rejected
        } else {
            Status::Applied
        };
        receipt.reason = reason;
        receipt.revision = self.revision;
        receipt.tick = self.clock.tick;
        receipt.simulation_s = self.clock.simulation_s;
        receipt.tool_use_result = result.clone();
        self.completions.push(Outcome {
            schema: "banjo.outcome.v1".into(),
            command_id: Id::new(key.1).expect("validated command"),
            actor_id: Id::new(key.0.clone()).expect("validated actor"),
            status: receipt.status.clone(),
            reason,
            revision: self.revision,
            tick: self.clock.tick,
            simulation_s: self.clock.simulation_s,
            snapshot: self.observation(&key.0),
            tool_use_result: result,
        });
    }

    pub fn take_completions(&mut self) -> Vec<Outcome> {
        std::mem::take(&mut self.completions)
    }

    fn cancel_pending(&mut self, actor: &str) {
        let keys: Vec<_> = self
            .pending_pickups
            .keys()
            .filter(|(a, _)| a == actor)
            .cloned()
            .collect();
        for key in keys {
            self.pending_pickups.remove(&key);
            let receipt = self.receipts.get_mut(&key).expect("pending receipt");
            receipt.status = Status::Rejected;
            receipt.reason = Some(Refusal::Cancelled);
            receipt.tick = self.clock.tick;
            receipt.simulation_s = self.clock.simulation_s;
            let revision = receipt.revision;
            self.completions.push(Outcome {
                schema: "banjo.outcome.v1".into(),
                command_id: Id::new(key.1).expect("validated id"),
                actor_id: Id::new(actor).expect("validated actor"),
                status: Status::Rejected,
                reason: Some(Refusal::Cancelled),
                revision,
                tick: self.clock.tick,
                simulation_s: self.clock.simulation_s,
                snapshot: self.observation(actor),
                tool_use_result: None,
            });
        }
    }

    /// Trusted host read: no receipt, sequence, world revision or physical step.
    /// Uses the same actor projection as command responses.
    pub fn observe(&mut self, actor: &str) -> Result<Value, Refusal> {
        if !self.joined.contains(actor) {
            return Err(Refusal::InvalidInput);
        }
        if let Some(fault) = self.clock.fault {
            return Err(fault);
        }
        self.kernel.observe()?;
        Ok(self.observation(actor))
    }

    fn observation(&self, actor: &str) -> Value {
        let state = self.kernel.state();
        // Explicit projection: never return another actor's hands, cargo,
        // private carried accounts or a raw native snapshot.
        let mut visible = serde_json::Map::new();
        for key in [
            "t",
            "bodies",
            "geometry",
            "partial",
            "gone",
            "count",
            "stepped_back",
        ] {
            if let Some(value) = state.get(key) {
                visible.insert(key.into(), value.clone());
            }
        }
        visible.insert("own_hand".into(), state["player_hands"][actor].clone());
        // Terrain's native wire also embeds carried accounts. Only geometry
        // needed to draw the actual collision columns crosses this boundary.
        if let Some(terrain) = state["terrain"].as_object() {
            let mut public = serde_json::Map::new();
            for key in [
                "grid",
                "surface",
                "heights_b64",
                "ground_b64",
                "runs_b64",
                "floor_m",
            ] {
                if let Some(value) = terrain.get(key) {
                    public.insert(key.into(), value.clone());
                }
            }
            visible.insert("terrain".into(), Value::Object(public));
        }
        visible.insert(
            "own_tool_use".into(),
            self.kernel
                .tool_use(actor)
                .ok()
                .flatten()
                .map(|s| serde_json::to_value(s).expect("validated tool state"))
                .unwrap_or(Value::Null),
        );
        visible.insert(
            "own_tool_preview".into(),
            if state["tool_use_preview"]["actor"] == actor {
                state["tool_use_preview"].clone()
            } else {
                Value::Null
            },
        );
        visible.insert("observed_tick".into(), self.clock.tick.into());
        visible.insert(
            "observed_simulation_s".into(),
            self.clock.simulation_s.into(),
        );
        let mut players = serde_json::Map::new();
        if let Some(native) = state["native_players"].as_object() {
            for (id, body) in native {
                let mut public = serde_json::Map::new();
                for key in [
                    "body_id",
                    "model",
                    "dimensions_m",
                    "mass_kg",
                    "position_m",
                    "orientation_wxyz",
                    "velocity_m_s",
                    "angular_velocity_rad_s",
                ] {
                    if let Some(value) = body.get(key) {
                        public.insert(key.into(), value.clone());
                    }
                }
                players.insert(id.clone(), Value::Object(public));
            }
        }
        visible.insert("native_players".into(), Value::Object(players));
        Value::Object(visible)
    }

    fn outcome(
        &self,
        command: &Command,
        status: Status,
        reason: Option<Refusal>,
        authorized: bool,
    ) -> Outcome {
        Outcome {
            schema: "banjo.outcome.v1".into(),
            command_id: command.command_id.clone(),
            actor_id: command.actor_id.clone(),
            status,
            reason,
            revision: self.revision,
            tick: self.clock.tick,
            simulation_s: self.clock.simulation_s,
            tool_use_result: None,
            snapshot: if authorized {
                self.observation(command.actor_id.as_str())
            } else {
                Value::Null
            },
        }
    }

    pub fn execute(&mut self, request: TrustedRequest) -> Outcome {
        let command = request.command;
        let actor = request.principal.as_str();
        if let Err(reason) = command.authorize(&self.id, &request.principal) {
            return self.outcome(&command, Status::Rejected, Some(reason), false);
        }
        if !self.allowed.contains(actor) {
            return self.outcome(&command, Status::Rejected, Some(Refusal::WrongActor), false);
        }
        let key = (actor.to_owned(), command.command_id.as_str().to_owned());
        // Include host authority in the identity: toggling it cannot turn an
        // already refused client join into an accepted retry.
        let digest = Sha256::digest(
            serde_json::to_vec(&(request.host_action, &command)).expect("validated command"),
        )
        .to_vec();
        if let Some(receipt) = self.receipts.get(&key) {
            if receipt.digest != digest {
                return self.outcome(
                    &command,
                    Status::Rejected,
                    Some(Refusal::ConflictingCommandId),
                    true,
                );
            }
            let mut result = self.outcome(
                &command,
                match receipt.status {
                    Status::Applied | Status::AlreadyApplied => Status::AlreadyApplied,
                    Status::Observed => Status::Observed,
                    Status::Rejected => Status::Rejected,
                    Status::Pending => Status::Pending,
                },
                receipt.reason,
                true,
            );
            result.revision = receipt.revision;
            result.tick = receipt.tick;
            result.simulation_s = receipt.simulation_s;
            result.tool_use_result = receipt.tool_use_result.clone();
            // Receipt time is original; snapshot explicitly observes now.
            return result;
        }
        let reason = if self.receipts.len() >= MAX_RECEIPTS {
            Some(Refusal::CapacityExceeded)
        } else if command.input_sequence <= *self.sequences.get(actor).unwrap_or(&0) {
            Some(Refusal::StaleInput)
        } else if command
            .expected_revision
            .is_some_and(|r| r != self.revision)
        {
            Some(Refusal::StaleRevision)
        } else {
            None
        };
        if let Some(reason) = reason {
            return self.outcome(&command, Status::Rejected, Some(reason), true);
        }
        self.sequences.insert(actor.into(), command.input_sequence);
        let result = self.apply(actor, &command.payload, request.host_action);
        if result == Err(Refusal::KernelUnavailable) {
            self.clock.fault = Some(Refusal::KernelUnavailable);
            self.fault_tool_uses(Refusal::KernelUnavailable);
        }
        let (status, reason) = match result {
            Ok(())
                if matches!(
                    command.payload,
                    Action::Inspect | Action::PreviewToolUse { .. }
                ) =>
            {
                (Status::Observed, None)
            }
            Ok(()) if matches!(command.payload, Action::Pickup { .. }) => {
                self.revision += 1;
                if let Action::Pickup { instance_id, .. } = &command.payload {
                    self.pending_pickups.insert(
                        key.clone(),
                        PendingPickup {
                            instance: instance_id.clone(),
                            started_attempted_ticks: self.clock.attempted_ticks,
                        },
                    );
                }
                (Status::Pending, None)
            }
            Ok(()) if matches!(command.payload, Action::BeginToolUse { .. }) => {
                self.revision += 1;
                let state = self
                    .kernel
                    .tool_use(actor)
                    .expect("validated native use")
                    .expect("started use");
                self.pending_tool_uses.insert(
                    key.clone(),
                    PendingToolUse {
                        tool: state.tool,
                        point_id: state.point_id,
                        started_s: state.started_s,
                        started_attempted_ticks: self.clock.attempted_ticks,
                    },
                );
                (Status::Pending, None)
            }
            Ok(()) => {
                self.revision += 1;
                (Status::Applied, None)
            }
            Err(reason) => (Status::Rejected, Some(reason)),
        };
        let outcome = self.outcome(&command, status, reason, true);
        self.receipts.insert(
            key,
            Receipt {
                digest,
                status: outcome.status.clone(),
                reason,
                revision: outcome.revision,
                tick: outcome.tick,
                simulation_s: outcome.simulation_s,
                tool_use_result: None,
            },
        );
        outcome
    }

    fn apply(&mut self, actor: &str, action: &Action, host_action: bool) -> Result<(), Refusal> {
        if let Some(reason) = self.clock.fault {
            return Err(reason);
        }
        match action {
            Action::Join { feet_m } => {
                if !host_action {
                    return Err(Refusal::HostActionRequired);
                }
                if self.joined.contains(actor) {
                    return Err(Refusal::InvalidInput);
                }
                self.kernel.spawn(actor, *feet_m)?;
                if !self.kernel.state()["native_players"][actor].is_object() {
                    return Err(Refusal::NativeRefused);
                }
                self.joined.insert(actor.into());
                Ok(())
            }
            _ if !self.joined.contains(actor) => Err(Refusal::NotJoined),
            Action::Inspect => self.kernel.observe(),
            Action::PreviewToolUse { ray } => self.kernel.preview_tool_use(actor, ray),
            Action::BeginToolUse { ray } => {
                if self.pending_tool_uses.keys().any(|(a, _)| a == actor)
                    || self.pending_pickups.keys().any(|(a, _)| a == actor)
                {
                    return Err(Refusal::ActionInProgress);
                }
                if self.completions.len()
                    + self.pending_pickups.len()
                    + self.pending_tool_uses.len()
                    >= 64
                {
                    return Err(Refusal::CapacityExceeded);
                }
                self.kernel.begin_tool_use(actor, ray)?;
                let state = self
                    .kernel
                    .tool_use(actor)?
                    .ok_or(Refusal::KernelUnavailable)?;
                if !state.active {
                    return Err(Refusal::KernelUnavailable);
                }
                Ok(())
            }
            Action::CancelToolUse { use_command_id } => {
                let pending = self
                    .pending_tool_uses
                    .get(&(actor.to_owned(), use_command_id.as_str().to_owned()))
                    .ok_or(Refusal::TargetChanged)?;
                let state = self
                    .kernel
                    .tool_use(actor)?
                    .ok_or(Refusal::KernelUnavailable)?;
                if !pending.matches(&state) {
                    return Err(Refusal::TargetChanged);
                }
                self.kernel.cancel_tool_use(actor)
            }
            Action::Move {
                velocity_m_s,
                heading_rad,
                jump,
            } => self.kernel.walk(actor, *velocity_m_s, *heading_rad, *jump),
            Action::Pickup { instance_id, ray } => {
                if self.completions.len()
                    + self.pending_pickups.len()
                    + self.pending_tool_uses.len()
                    >= 64
                {
                    return Err(Refusal::CapacityExceeded);
                }
                self.kernel.pickup(actor, instance_id, ray)
            }
            Action::Drop => {
                self.kernel.release(actor)?;
                self.cancel_pending(actor);
                if self.kernel.state()["player_hands"][actor]["holding"].as_str() == Some("") {
                    Ok(())
                } else {
                    Err(Refusal::NativeRefused)
                }
            }
            Action::Leave => {
                // Keep this actor's contact result until the accepted-step
                // closure is observed. Cancel/drop then leave after completion.
                if self.pending_tool_uses.keys().any(|(a, _)| a == actor) {
                    return Err(Refusal::ActionInProgress);
                }
                self.kernel.release(actor)?;
                self.kernel.remove(actor)?;
                self.cancel_pending(actor);
                if self.kernel.state()["native_players"][actor].is_object() {
                    return Err(Refusal::NativeRefused);
                }
                self.joined.remove(actor);
                Ok(())
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    struct Reference {
        state: Value,
        steps: u32,
        accepted: u32,
    }
    impl Kernel for Reference {
        fn state(&self) -> &Value {
            &self.state
        }
        fn spawn(&mut self, a: &str, p: [f64; 3]) -> Result<(), Refusal> {
            self.state["native_players"][a] = json!({"position_m":p});
            Ok(())
        }
        fn walk(&mut self, _: &str, _: [f64; 3], _: f64, _: bool) -> Result<(), Refusal> {
            Ok(())
        }
        fn release(&mut self, actor: &str) -> Result<(), Refusal> {
            self.state["player_hands"][actor] = json!({"holding":""});
            Ok(())
        }
        fn pickup(
            &mut self,
            actor: &str,
            instance: &str,
            _: &crate::contracts::Ray,
        ) -> Result<(), Refusal> {
            self.state["player_hands"][actor] = json!({"holding":instance});
            Ok(())
        }
        fn preview_tool_use(
            &mut self,
            actor: &str,
            _: &crate::contracts::Ray,
        ) -> Result<(), Refusal> {
            let queries = self.state["preview_queries"].as_u64().unwrap_or(0);
            self.state["preview_queries"] = json!(queries + 1);
            self.state["tool_use_preview"] =
                json!({"actor":actor,"admitted":false,"reason":"not_holding"});
            Ok(())
        }
        fn begin_tool_use(
            &mut self,
            actor: &str,
            _: &crate::contracts::Ray,
        ) -> Result<(), Refusal> {
            let t = self.state["t"].as_f64().unwrap();
            let count = self.state["use_requests"].as_u64().unwrap_or(0);
            self.state["use_requests"] = json!(count + 1);
            self.state["player_tool_uses"][actor] = json!({
                "schema":"banjo.native-tool-use.v1","active":true,"phase":"preparing","reason":"",
                "tool":"fixture-tool","point_id":3,"target_m":[0.65,0.75,0.2],"started_s":t,
                "phase_started_s":t,"ended_s":0,"hand_work_j":0,"contact_work_j":0,
                "contact_impulse_n_s":0,"peak_contact_force_n":0,"contacted":false,
                "contact_pending":false,"loosened_m3":{"rock":0,"soil":0,"sand":0}
            });
            Ok(())
        }
        fn cancel_tool_use(&mut self, actor: &str) -> Result<(), Refusal> {
            self.state["player_tool_uses"][actor]["phase"] = json!("recovering");
            self.state["player_tool_uses"][actor]["reason"] = json!("cancelled");
            Ok(())
        }
        fn remove(&mut self, a: &str) -> Result<(), Refusal> {
            self.state["native_players"]
                .as_object_mut()
                .unwrap()
                .remove(a);
            Ok(())
        }
        fn advance(&mut self, dt: f64, n: u32) -> Result<(), Refusal> {
            self.steps += n;
            self.state["t"] =
                json!(self.state["t"].as_f64().unwrap() + dt * f64::from(self.accepted));
            Ok(())
        }
    }
    fn world() -> World<Reference> {
        World::new(Id::new("world").unwrap(),vec![Id::new("alice").unwrap(),Id::new("bob").unwrap()],
        Reference{state:json!({"t":0.0,"native_players":{},"player_hands":{"bob":{"holding":"private-fixture"}},"player_tool_uses":{"bob":{"tool":"private-fixture"}},"player_carried":{"bob":{"secret":17}}}),steps:0,accepted:4}).unwrap()
    }
    fn request(id: &str, n: u64, action: Action) -> TrustedRequest {
        TrustedRequest {
            principal: Id::new("alice").unwrap(),
            host_action: true,
            command: Command {
                schema: crate::contracts::PROTOCOL.into(),
                world_id: Id::new("world").unwrap(),
                actor_id: Id::new("alice").unwrap(),
                command_id: Id::new(id).unwrap(),
                input_sequence: n,
                expected_revision: None,
                payload: action,
            },
        }
    }
    #[test]
    fn host_observation_is_private_and_does_not_fill_mutation_receipts() {
        let mut w = world();
        assert_eq!(w.observe("alice"), Err(Refusal::InvalidInput));
        w.execute(request("join", 1, Action::Join { feet_m: [0.0; 3] }));
        w.kernel.state["terrain"] = json!({"grid":{"nx":32},"heights_b64":"geometry",
            "carried":{"secret":19},"regions":[{"secret":23}],"view":{"secret":29}});
        for _ in 0..5000 {
            let observed = w.observe("alice").unwrap();
            assert_eq!(observed["terrain"]["heights_b64"], "geometry");
            assert!(!observed.to_string().contains("secret"));
            assert!(!observed.to_string().contains("private-fixture"));
        }
        assert_eq!(w.receipts.len(), 1);
        assert_eq!(w.sequences["alice"], 1);
        assert_eq!(w.clock.tick, 0);
        assert_eq!(w.kernel.steps, 0);
        assert_eq!(w.revision, 1);
    }

    #[test]
    fn requests_do_not_advance_time_and_retries_do_not_mutate() {
        let mut w = world();
        let r = w.execute(request("join", 1, Action::Join { feet_m: [0.0; 3] }));
        assert!(matches!(r.status, Status::Applied));
        w.advance().unwrap();
        let r = w.execute(request("join", 1, Action::Join { feet_m: [0.0; 3] }));
        assert!(matches!(r.status, Status::AlreadyApplied));
        assert_eq!(r.tick, 0);
        assert_eq!(r.snapshot["observed_tick"], 4);
        assert_eq!(w.clock.tick, 4);
        assert_eq!(w.revision, 1);
        let r = w.execute(request("join", 2, Action::Inspect));
        assert_eq!(r.reason, Some(Refusal::ConflictingCommandId));
    }
    #[test]
    fn authorization_and_private_projection_hold() {
        let mut w = world();
        w.execute(request("join", 1, Action::Join { feet_m: [0.0; 3] }));
        let observed = w.execute(request("inspect", 2, Action::Inspect));
        assert!(!observed.snapshot.to_string().contains("private-fixture"));
        assert!(!observed.snapshot.to_string().contains("secret"));
        let mut bad = request("bad", 3, Action::Inspect);
        bad.principal = Id::new("bob").unwrap();
        let result = w.execute(bad);
        assert_eq!(result.reason, Some(Refusal::WrongActor));
        assert!(result.snapshot.is_null());
    }

    #[test]
    fn preview_is_read_only_idempotent_and_private_to_its_actor() {
        let mut w = world();
        w.execute(request("join", 1, Action::Join { feet_m: [0.0; 3] }));
        let action = Action::PreviewToolUse {
            ray: crate::contracts::Ray {
                from_m: [0.0, 1.62, 0.0],
                direction: [0.0, -1.0, 0.0],
                max_distance_m: 2.0,
            },
        };
        let preview = w.execute(request("preview", 2, action.clone()));
        assert!(matches!(preview.status, Status::Observed));
        assert_eq!(
            preview.snapshot["own_tool_preview"]["reason"],
            "not_holding"
        );
        assert_eq!(w.clock.tick, 0);
        assert_eq!(w.revision, 1);
        assert_eq!(w.kernel.steps, 0);
        w.execute(request("preview", 2, action.clone()));
        assert_eq!(w.kernel.state["preview_queries"], 1);
        let mut bob_join = request("join", 1, Action::Join { feet_m: [0.0; 3] });
        bob_join.principal = Id::new("bob").unwrap();
        bob_join.command.actor_id = Id::new("bob").unwrap();
        w.execute(bob_join);
        let mut bob_preview = request("preview", 2, action);
        bob_preview.principal = Id::new("bob").unwrap();
        bob_preview.command.actor_id = Id::new("bob").unwrap();
        let seen = w.execute(bob_preview);
        assert_eq!(seen.snapshot["own_tool_preview"]["actor"], "bob");
        let alice = w.execute(request("inspect", 3, Action::Inspect));
        assert!(alice.snapshot["own_tool_preview"].is_null());
        assert_eq!(w.revision, 2);
        assert_eq!(w.clock.tick, 0);
    }
    #[test]
    fn client_join_and_stale_inputs_are_explicitly_refused() {
        let mut w = world();
        let mut client = request("client", 1, Action::Join { feet_m: [0.0; 3] });
        client.host_action = false;
        assert_eq!(w.execute(client).reason, Some(Refusal::HostActionRequired));
        assert_eq!(
            w.execute(request("old", 1, Action::Inspect)).reason,
            Some(Refusal::StaleInput)
        );
        assert_eq!(
            w.execute(request("not-joined", 2, Action::Inspect)).reason,
            Some(Refusal::NotJoined)
        );
    }
    #[test]
    fn revision_and_physics_time_have_distinct_owners() {
        let mut w = world();
        w.execute(request("join", 1, Action::Join { feet_m: [0.0; 3] }));
        for _ in 0..10 {
            w.advance().unwrap();
        }
        let mut current = request("current", 2, Action::Inspect);
        current.command.expected_revision = Some(1);
        assert!(matches!(w.execute(current).status, Status::Observed));
        let mut stale = request("stale", 3, Action::Inspect);
        stale.command.expected_revision = Some(0);
        assert_eq!(w.execute(stale).reason, Some(Refusal::StaleRevision));
        assert_eq!(w.clock.tick, 40);
    }
    #[test]
    fn native_rollback_and_clock_fault_are_not_reported_as_accepted_time() {
        let mut w = world();
        w.kernel.accepted = 0;
        w.advance().unwrap();
        assert_eq!(w.clock.tick, 0);
        assert_eq!(w.clock.attempted_ticks, 4);
        w.kernel.accepted = 5;
        assert_eq!(w.advance(), Err(Refusal::KernelUnavailable));
        assert_eq!(w.clock.tick, 0);
        assert_eq!(w.clock.attempted_ticks, 8);
        assert_eq!(w.advance(), Err(Refusal::KernelUnavailable));
        assert_eq!(w.clock.attempted_ticks, 8);
    }
    #[test]
    fn bounded_receipts_never_evict_a_committed_command() {
        let mut w = world();
        w.execute(request("join", 1, Action::Join { feet_m: [0.0; 3] }));
        for n in 2..=MAX_RECEIPTS as u64 {
            w.execute(request(&format!("inspect-{n}"), n, Action::Inspect));
        }
        assert_eq!(
            w.execute(request("full", MAX_RECEIPTS as u64 + 1, Action::Inspect))
                .reason,
            Some(Refusal::CapacityExceeded)
        );
        assert!(matches!(
            w.execute(request("join", 1, Action::Join { feet_m: [0.0; 3] }))
                .status,
            Status::AlreadyApplied
        ));
        assert_eq!(w.revision, 1);
    }
    fn take_request(n: u64) -> TrustedRequest {
        request(
            &format!("pickup-{n}"),
            n,
            Action::Pickup {
                instance_id: "fixture-tool".into(),
                ray: crate::contracts::Ray {
                    from_m: [0.0, 1.62, 0.0],
                    direction: [0.0, 0.0, 1.0],
                    max_distance_m: 2.0,
                },
            },
        )
    }
    #[test]
    fn pickup_requires_accepted_time_and_cancellation_cannot_be_acknowledged_as_success() {
        let mut w = world();
        w.execute(request("join", 1, Action::Join { feet_m: [0.0; 3] }));
        assert!(matches!(w.execute(take_request(2)).status, Status::Pending));
        w.kernel.accepted = 0;
        w.advance().unwrap();
        assert!(w.take_completions().is_empty());
        w.kernel.accepted = 4;
        w.advance().unwrap();
        let done = w.take_completions();
        assert!(matches!(done[0].status, Status::Applied));
        w.execute(request("drop", 3, Action::Drop));
        assert!(matches!(w.execute(take_request(4)).status, Status::Pending));
        w.execute(request("cancel", 5, Action::Drop));
        let done = w.take_completions();
        assert_eq!(done[0].reason, Some(Refusal::Cancelled));
        w.advance().unwrap();
        assert!(w.take_completions().is_empty());
        assert_eq!(w.execute(take_request(4)).reason, Some(Refusal::Cancelled));
    }
    #[test]
    fn a_lost_grip_or_repeated_rollback_ends_in_refusal() {
        let mut w = world();
        w.execute(request("join", 1, Action::Join { feet_m: [0.0; 3] }));
        w.execute(take_request(2));
        w.kernel.state["player_hands"]["alice"]["holding"] = Value::String("".into());
        w.advance().unwrap();
        assert_eq!(w.take_completions()[0].reason, Some(Refusal::NativeRefused));
        w.execute(take_request(3));
        w.kernel.accepted = 0;
        for _ in 0..120 {
            w.advance().unwrap();
        }
        assert_eq!(w.take_completions()[0].reason, Some(Refusal::NativeRefused));
        assert_eq!(w.kernel.state["player_hands"]["alice"]["holding"], "");
    }

    fn use_request(id: &str, n: u64) -> TrustedRequest {
        request(
            id,
            n,
            Action::BeginToolUse {
                ray: crate::contracts::Ray {
                    from_m: [0., 2.37, 0.],
                    direction: [0., -1., 0.],
                    max_distance_m: 2.,
                },
            },
        )
    }
    fn finish_use(w: &mut World<Reference>, reason: &str, volume: f64, pending: bool) {
        let t = w.kernel.state["t"].clone();
        let s = &mut w.kernel.state["player_tool_uses"]["alice"];
        s["active"] = json!(false);
        s["phase"] = json!("finished");
        s["ended_s"] = t;
        s["reason"] = json!(reason);
        s["contacted"] = json!(true);
        s["contact_pending"] = json!(pending);
        s["contact_work_j"] = json!(3);
        s["loosened_m3"]["soil"] = json!(volume);
    }

    #[test]
    fn use_waits_for_native_closure_and_retries_keep_the_original_result() {
        let mut w = world();
        w.execute(request("join", 1, Action::Join { feet_m: [0.; 3] }));
        let first = use_request("first-use", 2);
        assert!(matches!(
            w.execute(use_request("first-use", 2)).status,
            Status::Pending
        ));
        assert!(matches!(w.execute(first).status, Status::Pending));
        assert_eq!(w.kernel.state["use_requests"], 1);
        assert_eq!(
            w.execute(use_request("tap", 3)).reason,
            Some(Refusal::ActionInProgress)
        );
        w.kernel.accepted = 0;
        w.advance().unwrap();
        assert!(w.take_completions().is_empty());
        w.kernel.accepted = 4;
        w.advance().unwrap();
        finish_use(&mut w, "", 0.001, true);
        w.advance().unwrap();
        assert!(w.take_completions().is_empty());
        w.kernel.state["player_tool_uses"]["alice"]["contact_pending"] = json!(false);
        w.advance().unwrap();
        let finished = w.take_completions();
        assert_eq!(finished.len(), 1);
        assert!(matches!(finished[0].status, Status::Applied));
        assert_eq!(
            finished[0]
                .tool_use_result
                .as_ref()
                .unwrap()
                .loosened_m3
                .soil,
            0.001
        );
        w.execute(use_request("later-use", 4));
        let retry = w.execute(use_request("first-use", 2));
        assert!(matches!(retry.status, Status::AlreadyApplied));
        assert_eq!(retry.tool_use_result.unwrap().loosened_m3.soil, 0.001);
        assert_eq!(retry.snapshot["own_tool_use"]["phase"], "preparing");
    }

    #[test]
    fn cancel_is_scoped_to_the_original_use_and_completion_reports_native_failure() {
        let mut w = world();
        w.execute(request("join", 1, Action::Join { feet_m: [0.; 3] }));
        w.execute(use_request("first-use", 2));
        let mut peer = request(
            "peer-cancel",
            1,
            Action::CancelToolUse {
                use_command_id: Id::new("first-use").unwrap(),
            },
        );
        peer.principal = Id::new("bob").unwrap();
        peer.command.actor_id = peer.principal.clone();
        w.execute(TrustedRequest {
            principal: peer.principal.clone(),
            host_action: true,
            command: Command {
                schema: crate::contracts::PROTOCOL.into(),
                world_id: Id::new("world").unwrap(),
                actor_id: peer.principal.clone(),
                command_id: Id::new("bob-join").unwrap(),
                input_sequence: 1,
                expected_revision: None,
                payload: Action::Join {
                    feet_m: [1., 0., 0.],
                },
            },
        });
        peer.command.input_sequence = 2;
        assert_eq!(w.execute(peer).reason, Some(Refusal::TargetChanged));
        assert_eq!(
            w.execute(request("leave", 3, Action::Leave)).reason,
            Some(Refusal::ActionInProgress)
        );
        assert!(matches!(
            w.execute(request(
                "cancel",
                4,
                Action::CancelToolUse {
                    use_command_id: Id::new("first-use").unwrap()
                }
            ))
            .status,
            Status::Applied
        ));
        assert!(w.take_completions().is_empty());
        assert_eq!(
            w.kernel.state["player_tool_uses"]["alice"]["phase"],
            "recovering"
        );
        w.advance().unwrap();
        finish_use(&mut w, "cancelled", 0.001, false);
        w.advance().unwrap();
        let done = w.take_completions();
        assert_eq!(done[0].reason, Some(Refusal::Cancelled));
        assert_eq!(
            done[0].tool_use_result.as_ref().unwrap().loosened_m3.soil,
            0.001
        );
        w.execute(use_request("second-use", 5));
        assert_eq!(
            w.execute(request(
                "stale-cancel",
                6,
                Action::CancelToolUse {
                    use_command_id: Id::new("first-use").unwrap()
                }
            ))
            .reason,
            Some(Refusal::TargetChanged)
        );
        assert_eq!(
            w.kernel.state["player_tool_uses"]["alice"]["phase"],
            "preparing"
        );
    }

    #[test]
    fn malformed_or_overwritten_native_use_faults_instead_of_granting_yield() {
        let mut w = world();
        w.execute(request("join", 1, Action::Join { feet_m: [0.; 3] }));
        w.execute(use_request("use", 2));
        w.kernel.state["player_tool_uses"]["alice"]["point_id"] = json!(9);
        assert_eq!(w.advance(), Err(Refusal::KernelUnavailable));
        assert_eq!(
            w.take_completions()[0].reason,
            Some(Refusal::KernelUnavailable)
        );
        assert_eq!(
            w.execute(use_request("use", 2)).reason,
            Some(Refusal::KernelUnavailable)
        );
    }

    #[test]
    fn a_native_fault_completes_every_actors_pending_use() {
        let mut w = world();
        w.execute(request("join", 1, Action::Join { feet_m: [0.; 3] }));
        let mut peer = request(
            "bob-join",
            1,
            Action::Join {
                feet_m: [1., 0., 0.],
            },
        );
        peer.principal = Id::new("bob").unwrap();
        peer.command.actor_id = peer.principal.clone();
        w.execute(peer);
        w.execute(use_request("alice-use", 2));
        let mut peer_use = use_request("bob-use", 2);
        peer_use.principal = Id::new("bob").unwrap();
        peer_use.command.actor_id = peer_use.principal.clone();
        assert!(matches!(w.execute(peer_use).status, Status::Pending));
        w.kernel.state["player_tool_uses"]["alice"]["point_id"] = json!(9);
        assert_eq!(w.advance(), Err(Refusal::KernelUnavailable));
        let done = w.take_completions();
        assert_eq!(done.len(), 2);
        for outcome in done {
            assert_eq!(outcome.reason, Some(Refusal::KernelUnavailable));
            assert!(outcome.tool_use_result.is_none());
        }
        assert!(w.pending_tool_uses.is_empty());
        assert_eq!(w.advance(), Err(Refusal::KernelUnavailable));
        assert!(w.take_completions().is_empty());
    }

    #[test]
    fn prepared_initialization_does_not_resume_time_or_existing_actors() {
        let mut w = world();
        w.kernel.state["t"] = json!(1.0);
        assert!(matches!(
            World::new(
                Id::new("world").unwrap(),
                vec![Id::new("alice").unwrap()],
                w.kernel
            ),
            Err(Refusal::InvalidInput)
        ));
        let mut w = world();
        w.kernel.state["native_players"]["alice"] = json!({"body_id":1});
        assert!(matches!(
            World::new(
                Id::new("world").unwrap(),
                vec![Id::new("alice").unwrap()],
                w.kernel
            ),
            Err(Refusal::InvalidInput)
        ));
    }

    #[test]
    fn a_stalled_use_has_a_bounded_fault_not_a_simulated_success() {
        let mut w = world();
        w.execute(request("join", 1, Action::Join { feet_m: [0.; 3] }));
        w.execute(use_request("use", 2));
        w.kernel.accepted = 0;
        for _ in 0..599 {
            w.advance().unwrap();
        }
        assert_eq!(w.advance(), Err(Refusal::NativeRefused));
        let done = w.take_completions();
        assert_eq!(done[0].reason, Some(Refusal::NativeRefused));
        assert!(done[0].tool_use_result.as_ref().unwrap().active);
    }
}
