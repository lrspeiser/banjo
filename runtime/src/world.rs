//! Single mutable world owner. Time advances only through its fixed native
//! batch, never through player requests. This is an experimental host slice;
//! durable economy/inventory operations are deliberately not admitted yet.
use crate::contracts::{Action, Command, Id, Outcome, Refusal, Status};
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
    kernel: K,
    revision: u64,
    clock: ClockState,
}

impl<K: Kernel> World<K> {
    pub fn new(id: Id, allowed: Vec<Id>, kernel: K) -> Result<Self, Refusal> {
        let time = kernel.state()["t"]
            .as_f64()
            .ok_or(Refusal::KernelUnavailable)?;
        if !time.is_finite() || time != 0.0 || allowed.is_empty() || allowed.len() > 64 {
            return Err(Refusal::InvalidInput);
        }
        Ok(Self {
            id,
            allowed: allowed.iter().map(|a| a.as_str().to_owned()).collect(),
            joined: BTreeSet::new(),
            sequences: BTreeMap::new(),
            receipts: BTreeMap::new(),
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
        }
        result
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
                },
                receipt.reason,
                true,
            );
            result.revision = receipt.revision;
            result.tick = receipt.tick;
            result.simulation_s = receipt.simulation_s;
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
        let (status, reason) = match result {
            Ok(()) if matches!(command.payload, Action::Inspect) => (Status::Observed, None),
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
            Action::Inspect => Ok(()),
            Action::Move {
                velocity_m_s,
                heading_rad,
                jump,
            } => self.kernel.walk(actor, *velocity_m_s, *heading_rad, *jump),
            // Native read-only admission and grip confirmation are W05.
            // Forwarding wield blindly would recreate the false pickup ack.
            Action::Pickup { .. } => Err(Refusal::UnsupportedCapability),
            Action::Drop => {
                self.kernel.release(actor)?;
                if self.kernel.state()["player_hands"][actor]["holding"].as_str() == Some("") {
                    Ok(())
                } else {
                    Err(Refusal::NativeRefused)
                }
            }
            Action::Leave => {
                self.kernel.release(actor)?;
                self.kernel.remove(actor)?;
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
        fn release(&mut self, _: &str) -> Result<(), Refusal> {
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
        Reference{state:json!({"t":0.0,"native_players":{},"player_hands":{"bob":{"holding":"private-fixture"}},"player_carried":{"bob":{"secret":17}}}),steps:0,accepted:4}).unwrap()
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
}
