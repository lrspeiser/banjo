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
    UnsupportedCapability,
    NativeRefused,
    KernelUnavailable,
    CapacityExceeded,
    HostActionRequired,
    Cancelled,
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
                let norm = ray.direction.iter().map(|v| v * v).sum::<f64>().sqrt();
                if instance_id.is_empty()
                    || instance_id.len() > 120
                    || instance_id.chars().any(char::is_control)
                    || !finite(&ray.from_m)
                    || !finite(&ray.direction)
                    || (norm - 1.0).abs() > 1e-6
                    || !ray.max_distance_m.is_finite()
                    || !(0.0..=2.0).contains(&ray.max_distance_m)
                    || ray.max_distance_m == 0.0
                {
                    Err(Refusal::InvalidInput)
                } else {
                    Ok(())
                }
            }
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
}
