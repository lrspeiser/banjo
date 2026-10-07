use serde::{Deserialize, Serialize};

pub const PROTOCOL: &str = "banjo.command.v1";
pub const MAX_COMMAND_BYTES: usize = 16 * 1024;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(transparent)]
pub struct Id(String);

impl Id {
    pub fn new(value: impl Into<String>) -> Result<Self, Refusal> {
        let id = Self(value.into());
        id.validate()?;
        Ok(id)
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    fn validate(&self) -> Result<(), Refusal> {
        if self.0.is_empty()
            || self.0.len() > 80
            || !self
                .0
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
        {
            return Err(Refusal::InvalidInput);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Ray {
    pub from_m: [f64; 3],
    pub direction: [f64; 3],
    pub max_distance_m: f64,
}

impl Ray {
    fn validate(&self) -> Result<(), Refusal> {
        let finite = |v: &[f64; 3]| v.iter().all(|x| x.is_finite() && x.abs() <= 1e6);
        let norm = self.direction.iter().map(|v| v * v).sum::<f64>().sqrt();
        if !finite(&self.from_m)
            || !finite(&self.direction)
            || (norm - 1.0).abs() > 1e-6
            || !self.max_distance_m.is_finite()
            || self.max_distance_m <= 0.0
            || self.max_distance_m > 2.0
        {
            Err(Refusal::InvalidInput)
        } else {
            Ok(())
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Command {
    pub schema: String,
    pub world_id: Id,
    pub actor_id: Id,
    pub command_id: Id,
    pub input_sequence: u64,
    pub expected_revision: Option<u64>,
    pub payload: Action,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Action {
    /// A trusted host chooses the opening spawn; this is not a client teleport.
    Join {
        feet_m: [f64; 3],
    },
    Inspect,
    Move {
        velocity_m_s: [f64; 3],
        heading_rad: f64,
        jump: bool,
    },
    Pickup {
        instance_id: String,
        ray: Ray,
    },
    PreviewToolUse {
        ray: Ray,
    },
    BeginToolUse {
        ray: Ray,
    },
    PreviewHit {
        ray: Ray,
    },
    Hit {
        ray: Ray,
    },
    CancelToolUse {
        use_command_id: Id,
    },
    Drop,
    Leave,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Refusal {
    InvalidInput,
    UnsupportedProtocol,
    WrongWorld,
    WrongActor,
    StaleRevision,
    StaleInput,
    ConflictingCommandId,
    NotJoined,
    AlreadyHolding,
    HeldByAnotherActor,
    TargetChanged,
    OutOfReach,
    InsufficientStrength,
    NotHolding,
    ActionInProgress,
    AmbiguousCapability,
    NoContact,
    TargetBlocked,
    UnsupportedLaw,
    MaterialTooHard,
    UnsupportedCapability,
    NativeRefused,
    KernelUnavailable,
    CapacityExceeded,
    HostActionRequired,
    Cancelled,
    BlockedPath,
    InsufficientWork,
    GripReleased,
    CapabilityChanged,
    RecoveryBlocked,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ToolPhase {
    Preparing,
    Acting,
    Recovering,
    Finished,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReleasedVolumes {
    pub rock: f64,
    pub soil: f64,
    pub sand: f64,
}

impl ReleasedVolumes {
    pub fn total(&self) -> f64 {
        self.rock + self.soil + self.sand
    }
}

/// Native measurements, not client-supplied tool settings or a yield promise.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ToolUse {
    pub schema: String,
    pub active: bool,
    pub phase: ToolPhase,
    pub reason: String,
    pub tool: String,
    pub point_id: u32,
    pub target_m: [f64; 3],
    pub started_s: f64,
    pub phase_started_s: f64,
    pub ended_s: f64,
    pub hand_work_j: f64,
    pub contact_work_j: f64,
    pub contact_impulse_n_s: f64,
    pub peak_contact_force_n: f64,
    pub contacted: bool,
    pub contact_pending: bool,
    pub loosened_m3: ReleasedVolumes,
}

impl ToolUse {
    pub fn refusal(&self) -> Result<Option<Refusal>, Refusal> {
        if self.reason.is_empty() {
            Ok(None)
        } else {
            serde_json::from_value(serde_json::Value::String(self.reason.clone()))
                .map(Some)
                .map_err(|_| Refusal::KernelUnavailable)
        }
    }

    pub fn validate(&self, native_s: f64) -> Result<(), Refusal> {
        let positive = |v: f64| v.is_finite() && (0.0..=1e12).contains(&v);
        if self.schema != "banjo.native-tool-use.v1"
            || self.active == (self.phase == ToolPhase::Finished)
            || self.tool.is_empty()
            || self.tool.len() > 120
            || self.tool.chars().any(char::is_control)
            || self.point_id == 0
            || self
                .target_m
                .iter()
                .any(|x| !x.is_finite() || x.abs() > 1e6)
            || !native_s.is_finite()
            || !positive(self.started_s)
            || !positive(self.phase_started_s)
            || self.phase_started_s < self.started_s
            || self.phase_started_s > native_s + 1e-6
            || !positive(self.ended_s)
            || (self.active && self.ended_s != 0.0)
            || (!self.active
                && (self.ended_s < self.phase_started_s || self.ended_s > native_s + 1e-6))
            || !self.hand_work_j.is_finite()
            || self.hand_work_j.abs() > 1e12
            || [
                self.contact_work_j,
                self.contact_impulse_n_s,
                self.peak_contact_force_n,
                self.loosened_m3.rock,
                self.loosened_m3.soil,
                self.loosened_m3.sand,
            ]
            .iter()
            .any(|v| !positive(*v))
            || ((!self.contacted)
                && (self.contact_pending
                    || self.contact_work_j != 0.0
                    || self.loosened_m3.total() != 0.0))
        {
            return Err(Refusal::KernelUnavailable);
        }
        self.refusal()?;
        Ok(())
    }
}

/// Eligibility is an observation, never a promise of physical contact or yield.
/// Missing hit/terrain data stays absent instead of inventing a target at zero.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "snake_case")]
pub enum EntryObstructionKind {
    Ground,
    Body,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EntryObstruction {
    pub kind: EntryObstructionKind,
    pub tool_part_id: u64,
    pub blocking_body_id: Option<u64>,
    pub witness_m: [f64; 3],
    pub overlap_m: f64,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EntryClearance {
    pub clear: bool,
    pub parts_checked: u32,
    pub obstruction: Option<EntryObstruction>,
}
impl EntryClearance {
    fn validate(&self) -> Result<(), Refusal> {
        if self.parts_checked == 0
            || self.parts_checked > 64
            || self.clear != self.obstruction.is_none()
        {
            return Err(Refusal::KernelUnavailable);
        }
        if let Some(o) = &self.obstruction
            && (!o.overlap_m.is_finite()
                || o.tool_part_id == 0
                || o.blocking_body_id == Some(0)
                || o.overlap_m <= 0.003
                || o.overlap_m > 1e6
                || o.witness_m.iter().any(|x| !x.is_finite() || x.abs() > 1e6)
                || matches!(o.kind, EntryObstructionKind::Ground) != o.blocking_body_id.is_none())
        {
            return Err(Refusal::KernelUnavailable);
        }
        Ok(())
    }
}
/// Admission is an actuator intention, never evidence of material removal.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HitPreview {
    pub schema: String,
    pub actor: Id,
    pub admitted: bool,
    pub reason: Option<Refusal>,
    pub tool: String,
    pub target: String,
    pub point_id: u32,
    pub target_m: Option<[f64; 3]>,
}
impl HitPreview {
    pub fn validate(&self, actor: &str) -> Result<(), Refusal> {
        if self.schema != "banjo.physical-hit-preview.v1"
            || self.actor.as_str() != actor
            || self.admitted == self.reason.is_some()
            || self.tool.len() > 120
            || self.target.len() > 120
            || self
                .target_m
                .is_some_and(|p| p.iter().any(|v| !v.is_finite() || v.abs() > 1e6))
            || (self.admitted
                && (self.tool.is_empty()
                    || self.target.is_empty()
                    || self.point_id == 0
                    || self.target_m.is_none()))
        {
            return Err(Refusal::KernelUnavailable);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ToolPreview {
    pub schema: String,
    pub actor: Id,
    pub admitted: bool,
    pub reason: Option<Refusal>,
    pub tool: String,
    pub point_id: u32,
    pub target_m: Option<[f64; 3]>,
    pub terrain_region: Option<i32>,
    pub terrain_column: Option<u64>,
    pub matter_revision: Option<u64>,
    pub ground_height_m: Option<f64>,
    pub desired_path_points: u32,
    pub measured_yield: bool,
    pub entry_clearance: Option<EntryClearance>,
}

impl ToolPreview {
    pub fn validate(&self, actor: &str) -> Result<(), Refusal> {
        self.actor
            .validate()
            .map_err(|_| Refusal::KernelUnavailable)?;
        let terrain_complete = self.terrain_region.is_some()
            && self.terrain_column.is_some()
            && self.matter_revision.is_some()
            && self.ground_height_m.is_some();
        let terrain_absent = self.terrain_region.is_none()
            && self.terrain_column.is_none()
            && self.matter_revision.is_none()
            && self.ground_height_m.is_none();
        if let Some(entry) = &self.entry_clearance {
            entry.validate()?;
        }

        if self.schema != "banjo.tool-preview.v2"
            || self.actor.as_str() != actor
            || self.measured_yield
            || self.admitted == self.reason.is_some()
            || self.tool.len() > 120
            || self.tool.chars().any(char::is_control)
            || self.desired_path_points > 1024
            || self
                .target_m
                .is_some_and(|v| v.iter().any(|x| !x.is_finite() || x.abs() > 1e6))
            || self
                .ground_height_m
                .is_some_and(|v| !v.is_finite() || v.abs() > 1e6)
            || !(terrain_complete || terrain_absent)
            || (terrain_complete && (self.target_m.is_none() || self.terrain_region.unwrap() < -1))
            || (self.admitted
                && (self.target_m.is_none()
                    || self.entry_clearance.is_none()
                    || !terrain_complete
                    || self.tool.is_empty()
                    || self.point_id == 0
                    || self.desired_path_points == 0))
        {
            return Err(Refusal::KernelUnavailable);
        }
        if self.entry_clearance.is_some() && !terrain_complete {
            return Err(Refusal::KernelUnavailable);
        }
        Ok(())
    }
}

impl Command {
    pub fn parse(bytes: &[u8]) -> Result<Self, Refusal> {
        if bytes.len() > MAX_COMMAND_BYTES {
            return Err(Refusal::InvalidInput);
        }
        let command: Self = serde_json::from_slice(bytes).map_err(|_| Refusal::InvalidInput)?;
        command.validate()?;
        Ok(command)
    }

    pub fn validate(&self) -> Result<(), Refusal> {
        if self.schema != PROTOCOL {
            return Err(Refusal::UnsupportedProtocol);
        }
        for id in [&self.world_id, &self.actor_id, &self.command_id] {
            id.validate()?;
        }
        let finite = |v: &[f64; 3]| v.iter().all(|x| x.is_finite() && x.abs() <= 1e6);
        match &self.payload {
            Action::Join { feet_m } if !finite(feet_m) => Err(Refusal::InvalidInput),
            Action::Move {
                velocity_m_s,
                heading_rad,
                ..
            } if !finite(velocity_m_s)
                || velocity_m_s[1] != 0.0
                || velocity_m_s[0].hypot(velocity_m_s[2]) > 6.0
                || !heading_rad.is_finite()
                || heading_rad.abs() > std::f64::consts::TAU =>
            {
                Err(Refusal::InvalidInput)
            }
            Action::Pickup { instance_id, ray } => {
                if instance_id.is_empty()
                    || instance_id.len() > 120
                    || instance_id.chars().any(char::is_control)
                {
                    Err(Refusal::InvalidInput)
                } else {
                    ray.validate()
                }
            }
            Action::PreviewToolUse { ray }
            | Action::BeginToolUse { ray }
            | Action::PreviewHit { ray }
            | Action::Hit { ray } => ray.validate(),
            Action::CancelToolUse { use_command_id } => use_command_id.validate(),
            _ => Ok(()),
        }
    }

    /// Call only after the ingress authenticates the actor. Payload cannot
    /// grant an actor/world scope; both must match the trusted connection.
    pub fn authorize(&self, world: &Id, actor: &Id) -> Result<(), Refusal> {
        self.validate()?;
        if &self.world_id != world {
            return Err(Refusal::WrongWorld);
        }
        if &self.actor_id != actor {
            return Err(Refusal::WrongActor);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Pending,
    Applied,
    Observed,
    Rejected,
    AlreadyApplied,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Outcome {
    pub schema: String,
    pub command_id: Id,
    pub actor_id: Id,
    pub status: Status,
    pub reason: Option<Refusal>,
    pub revision: u64,
    pub tick: u64,
    pub simulation_s: f64,
    pub snapshot: serde_json::Value,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tool_use_result: Option<ToolUse>,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn command() -> Command {
        Command::parse(br#"{"schema":"banjo.command.v1","world_id":"world-1","actor_id":"actor-1","command_id":"request-1","input_sequence":1,"expected_revision":null,"payload":{"kind":"move","velocity_m_s":[2,0,0],"heading_rad":0,"jump":false}}"#).unwrap()
    }

    #[test]
    fn authority_cannot_be_changed_by_payload() {
        let command = command();
        assert_eq!(
            command.authorize(&Id::new("other").unwrap(), &command.actor_id),
            Err(Refusal::WrongWorld)
        );
        assert_eq!(
            command.authorize(&command.world_id, &Id::new("other").unwrap()),
            Err(Refusal::WrongActor)
        );
        assert!(
            command
                .authorize(&command.world_id, &command.actor_id)
                .is_ok()
        );
    }

    #[test]
    fn movement_is_an_intent_with_finite_bounded_si_units() {
        let mut command = command();
        command.payload = Action::Move {
            velocity_m_s: [4.0, 0.0, 5.0],
            heading_rad: 0.0,
            jump: false,
        };
        assert_eq!(command.validate(), Err(Refusal::InvalidInput));
        command.payload = Action::Join {
            feet_m: [f64::NAN, 0.0, 0.0],
        };
        assert_eq!(command.validate(), Err(Refusal::InvalidInput));
    }

    #[test]
    fn no_arbitrary_native_operation_or_simulation_step_can_be_supplied() {
        let encoded = serde_json::to_value(command()).unwrap();
        let mut bad = encoded.clone();
        bad["payload"] = serde_json::json!({"kind":"step", "dt":1, "n":10000});
        assert!(Command::parse(&serde_json::to_vec(&bad).unwrap()).is_err());
        let mut bad = encoded;
        bad["payload"]["teleport"] = serde_json::json!([100, 0, 0]);
        assert!(Command::parse(&serde_json::to_vec(&bad).unwrap()).is_err());
    }

    #[test]
    fn ids_and_input_bytes_are_bounded() {
        assert!(Id::new("../../private").is_err());
        assert!(Id::new("x".repeat(81)).is_err());
        assert!(Command::parse(&vec![b' '; MAX_COMMAND_BYTES + 1]).is_err());
    }

    #[test]
    fn preview_rays_cannot_grant_work_or_override_capabilities() {
        let mut c = command();
        let ray = Ray {
            from_m: [0.0, 1.62, 0.0],
            direction: [0.0, -1.0, 0.0],
            max_distance_m: 2.0,
        };
        c.payload = Action::PreviewToolUse { ray: ray.clone() };
        assert_eq!(c.validate(), Ok(()));
        for bad in [
            Ray {
                direction: [0.0, -2.0, 0.0],
                ..ray.clone()
            },
            Ray {
                max_distance_m: 3.0,
                ..ray.clone()
            },
            Ray {
                from_m: [f64::INFINITY, 0.0, 0.0],
                ..ray.clone()
            },
        ] {
            c.payload = Action::PreviewToolUse { ray: bad };
            assert_eq!(c.validate(), Err(Refusal::InvalidInput));
        }
        c.payload = Action::PreviewToolUse { ray };
        let mut encoded = serde_json::to_value(c).unwrap();
        encoded["payload"]["ray"]["work_j"] = serde_json::json!(10000);
        assert_eq!(
            Command::parse(&serde_json::to_vec(&encoded).unwrap()).unwrap_err(),
            Refusal::InvalidInput
        );
    }

    #[test]
    fn physical_hit_preview_is_scoped_bounded_and_not_a_damage_receipt() {
        let mut p: HitPreview = serde_json::from_value(serde_json::json!({
            "schema":"banjo.physical-hit-preview.v1","actor":"alice","admitted":true,
            "reason":null,"tool":"novel-tool","target":"grain","point_id":1,
            "target_m":[0.,0.,0.]}))
        .unwrap();
        assert_eq!(p.validate("alice"), Ok(()));
        assert_eq!(p.validate("bob"), Err(Refusal::KernelUnavailable));
        p.target_m = Some([f64::INFINITY, 0., 0.]);
        assert_eq!(p.validate("alice"), Err(Refusal::KernelUnavailable));
        p.target_m = None;
        assert_eq!(p.validate("alice"), Err(Refusal::KernelUnavailable));
        p.admitted = false;
        p.reason = Some(Refusal::NotHolding);
        assert_eq!(p.validate("alice"), Ok(()));
    }

    #[test]
    fn native_preview_is_typed_scoped_and_does_not_promise_yield() {
        let mut p = ToolPreview {
            schema: "banjo.tool-preview.v2".into(),
            actor: Id::new("alice").unwrap(),
            admitted: false,
            reason: Some(Refusal::NotHolding),
            tool: String::new(),
            point_id: 0,
            target_m: None,
            terrain_region: None,
            terrain_column: None,
            matter_revision: None,
            ground_height_m: None,
            desired_path_points: 0,
            measured_yield: false,
            entry_clearance: None,
        };
        assert_eq!(p.validate("alice"), Ok(()));
        assert_eq!(p.validate("bob"), Err(Refusal::KernelUnavailable));
        p.admitted = true;
        p.reason = None;
        assert_eq!(p.validate("alice"), Err(Refusal::KernelUnavailable));
        p.target_m = Some([0.0, 0.0, 1.0]);
        p.terrain_region = Some(-1);
        p.terrain_column = Some(3);
        p.matter_revision = Some(0);
        p.ground_height_m = Some(0.0);
        p.tool = "handle".into();
        p.point_id = 1;
        p.desired_path_points = 13;
        p.entry_clearance = Some(EntryClearance {
            clear: true,
            parts_checked: 2,
            obstruction: None,
        });
        assert_eq!(p.validate("alice"), Ok(()));
        p.measured_yield = true;
        assert_eq!(p.validate("alice"), Err(Refusal::KernelUnavailable));
        p.measured_yield = false;
        let good = p.clone();
        p.entry_clearance = None;
        assert_eq!(p.validate("alice"), Err(Refusal::KernelUnavailable));
        p = good.clone();
        p.entry_clearance = Some(EntryClearance {
            clear: false,
            parts_checked: 2,
            obstruction: Some(EntryObstruction {
                kind: EntryObstructionKind::Ground,
                tool_part_id: 1,
                blocking_body_id: None,
                witness_m: [0.0, 0.7, 1.0],
                overlap_m: 0.01,
            }),
        });
        assert_eq!(p.validate("alice"), Ok(())); // a predicted meeting is not a proved failed stroke
        let blocked = p.clone();
        p.entry_clearance
            .as_mut()
            .unwrap()
            .obstruction
            .as_mut()
            .unwrap()
            .blocking_body_id = Some(2);
        assert_eq!(p.validate("alice"), Err(Refusal::KernelUnavailable));
        p = blocked.clone();
        p.entry_clearance
            .as_mut()
            .unwrap()
            .obstruction
            .as_mut()
            .unwrap()
            .overlap_m = 0.001;
        assert_eq!(p.validate("alice"), Err(Refusal::KernelUnavailable));
        p = blocked.clone();
        p.entry_clearance
            .as_mut()
            .unwrap()
            .obstruction
            .as_mut()
            .unwrap()
            .witness_m[0] = f64::NAN;
        assert_eq!(p.validate("alice"), Err(Refusal::KernelUnavailable));
        p = good;
        p.schema = "banjo.tool-preview.v1".into();
        assert_eq!(p.validate("alice"), Err(Refusal::KernelUnavailable));
        p.schema = "banjo.tool-preview.v2".into();
        p.target_m = Some([f64::NAN, 0.0, 0.0]);
        assert_eq!(p.validate("alice"), Err(Refusal::KernelUnavailable));
    }

    #[test]
    fn use_and_cancel_cannot_supply_physics_settings_or_snapshot_paths() {
        let mut c = command();
        c.payload = Action::BeginToolUse {
            ray: Ray {
                from_m: [0.0, 1.62, 0.0],
                direction: [0.0, -1.0, 0.0],
                max_distance_m: 2.0,
            },
        };
        assert_eq!(c.validate(), Ok(()));
        for field in ["work_j", "tool_point", "initial_snapshot", "path_m"] {
            let mut encoded = serde_json::to_value(&c).unwrap();
            encoded["payload"][field] = serde_json::json!(1000);
            assert_eq!(
                Command::parse(&serde_json::to_vec(&encoded).unwrap()).unwrap_err(),
                Refusal::InvalidInput
            );
        }
        c.payload = Action::CancelToolUse {
            use_command_id: Id::new("use-1").unwrap(),
        };
        let mut encoded = serde_json::to_value(&c).unwrap();
        encoded["payload"]["use_command_id"] = serde_json::json!("../other");
        assert_eq!(
            Command::parse(&serde_json::to_vec(&encoded).unwrap()).unwrap_err(),
            Refusal::InvalidInput
        );
    }

    #[test]
    fn tool_measurements_reject_inconsistent_phase_quantity_time_and_unrecognized_reason() {
        let encoded = serde_json::json!({"schema":"banjo.native-tool-use.v1","active":true,"phase":"preparing",
            "reason":"","tool":"unfamiliar-tool","point_id":1,"target_m":[0.0,0.0,1.0],
            "started_s":1.0,"phase_started_s":1.0,"ended_s":0.0,"hand_work_j":-2.0,
            "contact_work_j":0.0,"contact_impulse_n_s":0.0,"peak_contact_force_n":0.0,
            "contacted":false,"contact_pending":false,"loosened_m3":{"rock":0.0,"soil":0.0,"sand":0.0}});
        let valid: ToolUse = serde_json::from_value(encoded.clone()).unwrap();
        assert_eq!(valid.validate(1.0), Ok(()));
        for (field, value) in [
            ("active", serde_json::json!(false)),
            ("phase_started_s", serde_json::json!(2.0)),
            ("contact_pending", serde_json::json!(true)),
            ("reason", serde_json::json!("invented_success")),
            ("contact_work_j", serde_json::json!(-1.0)),
        ] {
            let mut bad = encoded.clone();
            bad[field] = value;
            assert_eq!(
                serde_json::from_value::<ToolUse>(bad)
                    .unwrap()
                    .validate(1.0),
                Err(Refusal::KernelUnavailable)
            );
        }
        let mut bad = encoded;
        bad["loosened_m3"]["soil"] = serde_json::json!(-1.0);
        assert_eq!(
            serde_json::from_value::<ToolUse>(bad)
                .unwrap()
                .validate(1.0),
            Err(Refusal::KernelUnavailable)
        );
    }
}
