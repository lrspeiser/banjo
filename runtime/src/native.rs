//! Transitional adapter to the existing native JSON process. Only the world
//! owner calls it; no browser/native operation pass-through is exposed.
use crate::contracts::{Ray, Refusal, ToolPhase, ToolPreview, ToolUse};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::io::{BufRead, BufReader, Read, Write};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{Receiver, SyncSender, sync_channel};
use std::thread::{self, JoinHandle};
use std::time::Duration;

const MAX_REPLY_BYTES: u64 = 32 * 1024 * 1024;
const REPLY_TIMEOUT: Duration = Duration::from_secs(10);

pub trait Kernel {
    fn state(&self) -> &Value;
    fn spawn(&mut self, actor: &str, feet: [f64; 3]) -> Result<(), Refusal>;
    fn walk(
        &mut self,
        actor: &str,
        velocity: [f64; 3],
        heading: f64,
        jump: bool,
    ) -> Result<(), Refusal>;
    fn release(&mut self, actor: &str) -> Result<(), Refusal>;
    fn pickup(&mut self, actor: &str, instance: &str, ray: &Ray) -> Result<(), Refusal>;
    fn preview_tool_use(&mut self, _actor: &str, _ray: &Ray) -> Result<(), Refusal> {
        Err(Refusal::UnsupportedCapability)
    }
    fn begin_tool_use(&mut self, _actor: &str, _ray: &Ray) -> Result<(), Refusal> {
        Err(Refusal::UnsupportedCapability)
    }
    fn cancel_tool_use(&mut self, _actor: &str) -> Result<(), Refusal> {
        Err(Refusal::UnsupportedCapability)
    }
    fn tool_use(&self, actor: &str) -> Result<Option<ToolUse>, Refusal> {
        let value = &self.state()["player_tool_uses"][actor];
        if value.is_null() {
            return Ok(None);
        }
        let use_state: ToolUse =
            serde_json::from_value(value.clone()).map_err(|_| Refusal::KernelUnavailable)?;
        use_state.validate(
            self.state()["t"]
                .as_f64()
                .ok_or(Refusal::KernelUnavailable)?,
        )?;
        Ok(Some(use_state))
    }
    fn remove(&mut self, actor: &str) -> Result<(), Refusal>;
    fn advance(&mut self, dt: f64, steps: u32) -> Result<(), Refusal>;
}

pub struct NativeProcess {
    child: Child,
    input: Option<SyncSender<Vec<u8>>>,
    replies: Receiver<Result<Value, Refusal>>,
    readers: Vec<JoinHandle<()>>,
    state: Value,
    failed: bool,
    selected_file_sha256: String,
}

impl NativeProcess {
    pub fn open(
        executable: &Path,
        scene: &Path,
        cell_m: f64,
        initial_snapshot: Option<&Path>,
    ) -> Result<Self, Refusal> {
        if !cell_m.is_finite() || !(0.01..=1.0).contains(&cell_m) {
            return Err(Refusal::InvalidInput);
        }
        let mut artifact =
            std::fs::File::open(executable).map_err(|_| Refusal::KernelUnavailable)?;
        let mut hash = Sha256::new();
        let mut buffer = [0_u8; 65536];
        loop {
            let count = artifact
                .read(&mut buffer)
                .map_err(|_| Refusal::KernelUnavailable)?;
            if count == 0 {
                break;
            }
            hash.update(&buffer[..count]);
        }
        let selected_file_sha256 = format!("{:x}", hash.finalize());
        let mut command = Command::new(executable);
        command.args([
            "--scene",
            &scene.to_string_lossy(),
            "--cell",
            &cell_m.to_string(),
        ]);
        if let Some(snapshot) = initial_snapshot {
            command.arg("--snapshot").arg(snapshot);
        }
        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .env_remove("OPENAI_API_KEY")
            .spawn()
            .map_err(|_| Refusal::KernelUnavailable)?;
        let mut stdin = child.stdin.take().expect("piped stdin");
        let stdout = child.stdout.take().expect("piped stdout");
        let (input, requests) = sync_channel::<Vec<u8>>(1);
        let writer = thread::spawn(move || {
            for bytes in requests {
                if stdin
                    .write_all(&bytes)
                    .and_then(|()| stdin.flush())
                    .is_err()
                {
                    break;
                }
            }
        });
        let (send, replies) = sync_channel(1);
        let reader = thread::spawn(move || {
            let mut stream = BufReader::new(stdout);
            loop {
                let mut line = Vec::new();
                // take() bounds allocation even if a broken native process
                // produces a line without a newline.
                let result = (&mut stream)
                    .take(MAX_REPLY_BYTES + 1)
                    .read_until(b'\n', &mut line);
                let reply = match result {
                    Ok(0) | Err(_) => Err(Refusal::KernelUnavailable),
                    Ok(_) if line.len() as u64 > MAX_REPLY_BYTES || !line.ends_with(b"\n") => {
                        Err(Refusal::KernelUnavailable)
                    }
                    Ok(_) => serde_json::from_slice(&line).map_err(|_| Refusal::KernelUnavailable),
                };
                let failed = reply.is_err();
                if send.try_send(reply).is_err() || failed {
                    break;
                }
            }
        });
        let mut process = Self {
            child,
            input: Some(input),
            replies,
            readers: vec![writer, reader],
            state: Value::Null,
            failed: false,
            selected_file_sha256,
        };
        process.state = process.receive()?;
        if process.state["ok"] != true || !process.state["t"].is_number() {
            return Err(Refusal::KernelUnavailable);
        }
        if initial_snapshot.is_some() && process.state["restored"]["tier"] != "whole" {
            return Err(Refusal::NativeRefused);
        }
        Ok(process)
    }

    pub fn identity(&self) -> Value {
        json!({"pid":self.child.id(),"selected_file_sha256":self.selected_file_sha256,
            "build_provenance":"unrecorded","actual_abi":null,
            "pickup_admission_version":self.state["pickup_admission_version"],
            "native_carry_version":self.state["native_carry_version"],
            "tool_use_admission_version":self.state["tool_use_admission_version"],
            "native_tool_use_version":self.state["native_tool_use_version"]})
    }

    fn receive(&mut self) -> Result<Value, Refusal> {
        match self.replies.recv_timeout(REPLY_TIMEOUT) {
            Ok(Ok(value)) => Ok(value),
            _ => {
                self.failed = true;
                let _ = self.child.kill();
                Err(Refusal::KernelUnavailable)
            }
        }
    }

    fn call(&mut self, operation: Value) -> Result<(), Refusal> {
        if self.failed {
            return Err(Refusal::KernelUnavailable);
        }
        let mut bytes = serde_json::to_vec(&operation).map_err(|_| Refusal::InvalidInput)?;
        bytes.push(b'\n');
        if self
            .input
            .as_ref()
            .expect("open input")
            .try_send(bytes)
            .is_err()
        {
            self.failed = true;
            let _ = self.child.kill();
            return Err(Refusal::KernelUnavailable);
        }
        let reply = self.receive()?;
        if reply["ok"] != true {
            return Err(Refusal::NativeRefused);
        }
        if !reply["t"].is_number() || (operation["op"] != "step" && reply["t"] != self.state["t"]) {
            self.failed = true;
            return Err(Refusal::KernelUnavailable);
        }
        self.state = reply;
        Ok(())
    }
}

impl Kernel for NativeProcess {
    fn state(&self) -> &Value {
        &self.state
    }
    fn spawn(&mut self, actor: &str, feet: [f64; 3]) -> Result<(), Refusal> {
        self.call(json!({"op":"player-spawn","actor":actor,"feet_m":feet}))
    }
    fn walk(
        &mut self,
        actor: &str,
        velocity: [f64; 3],
        heading: f64,
        jump: bool,
    ) -> Result<(), Refusal> {
        let mut op = json!({"op":"player-walk","actor":actor,"velocity_m_s":velocity,
            "heading_rad":heading,"duration_s":0.25});
        if jump {
            op["jump_m_s"] = json!(4.0);
        }
        self.call(op)
    }
    fn release(&mut self, actor: &str) -> Result<(), Refusal> {
        self.call(json!({"op":"release","actor":actor}))
    }
    fn pickup(&mut self, actor: &str, instance: &str, ray: &Ray) -> Result<(), Refusal> {
        if self.state["pickup_admission_version"] != 1 || self.state["native_carry_version"] != 1 {
            return Err(Refusal::UnsupportedCapability);
        }
        self.call(json!({"op":"pickup","actor":actor,"name":instance,
            "from":ray.from_m,"dir":ray.direction,"max_m":ray.max_distance_m}))?;
        if self.state["pickup"]["admitted"] == true {
            if self.state["player_hands"][actor]["holding"].as_str() == Some(instance) {
                Ok(())
            } else {
                Err(Refusal::NativeRefused)
            }
        } else {
            Err(
                serde_json::from_value(self.state["pickup"]["reason"].clone())
                    .unwrap_or(Refusal::NativeRefused),
            )
        }
    }
    fn remove(&mut self, actor: &str) -> Result<(), Refusal> {
        self.call(json!({"op":"player-remove","actor":actor}))
    }
    fn preview_tool_use(&mut self, actor: &str, ray: &Ray) -> Result<(), Refusal> {
        if self.state["tool_use_admission_version"] != 1 {
            return Err(Refusal::UnsupportedCapability);
        }
        self.call(
            json!({"op":"tool-use-preview","actor":actor,"from":ray.from_m,
            "dir":ray.direction,"max_m":ray.max_distance_m}),
        )?;
        let preview: ToolPreview = serde_json::from_value(self.state["tool_use_preview"].clone())
            .map_err(|_| Refusal::KernelUnavailable)?;
        preview.validate(actor)
    }
    fn advance(&mut self, dt: f64, steps: u32) -> Result<(), Refusal> {
        self.call(json!({"op":"step","dt":dt,"n":steps}))
    }
    fn begin_tool_use(&mut self, actor: &str, ray: &Ray) -> Result<(), Refusal> {
        if self.state["native_tool_use_version"] != 1 {
            return Err(Refusal::UnsupportedCapability);
        }
        self.call(
            json!({"op":"tool-use-begin","actor":actor,"from":ray.from_m,
            "dir":ray.direction,"max_m":ray.max_distance_m}),
        )?;
        match self.state["tool_use_start"]["started"].as_bool() {
            Some(false) => Err(serde_json::from_value(
                self.state["tool_use_start"]["reason"].clone(),
            )
            .unwrap_or(Refusal::NativeRefused)),
            Some(true) => {
                let use_state = self.tool_use(actor)?.ok_or(Refusal::KernelUnavailable)?;
                if use_state.phase != ToolPhase::Preparing
                    || !use_state.active
                    || use_state.started_s
                        != self.state["t"].as_f64().ok_or(Refusal::KernelUnavailable)?
                {
                    return Err(Refusal::KernelUnavailable);
                }
                Ok(())
            }
            None => Err(Refusal::KernelUnavailable),
        }
    }
    fn cancel_tool_use(&mut self, actor: &str) -> Result<(), Refusal> {
        if self.state["native_tool_use_version"] != 1 {
            return Err(Refusal::UnsupportedCapability);
        }
        let before = self.tool_use(actor)?.ok_or(Refusal::TargetChanged)?;
        if !before.active {
            return Err(Refusal::TargetChanged);
        }
        self.call(json!({"op":"tool-use-cancel","actor":actor}))?;
        let after = self.tool_use(actor)?.ok_or(Refusal::KernelUnavailable)?;
        if after.phase != ToolPhase::Recovering
            || after.started_s != before.started_s
            || after.point_id != before.point_id
        {
            return Err(Refusal::KernelUnavailable);
        }
        Ok(())
    }
}

impl Drop for NativeProcess {
    fn drop(&mut self) {
        // This handle owns exactly this child. Never kill by executable name.
        let _ = self.child.kill();
        self.input.take();
        let _ = self.child.wait();
        for reader in self.readers.drain(..) {
            let _ = reader.join();
        }
    }
}
