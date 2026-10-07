//! Experimental trusted-host pipe. Not an Internet/authentication gateway.
use banjo_runtime::contracts::{Id, MAX_COMMAND_BYTES, Refusal};
use banjo_runtime::native::NativeProcess;
use banjo_runtime::world::{COMMAND_CAPACITY, DT_S, STEPS_PER_BATCH, TrustedRequest, World};
use serde_json::{Value, json};
use std::io::{BufRead, BufReader, Read, Write};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, mpsc};
use std::thread;
use std::time::{Duration, Instant};

const MAX_OUTPUT_BYTES: usize = 2 * 1024 * 1024;

struct Configuration {
    native: PathBuf,
    scene: PathBuf,
    cell: f64,
    world: Id,
    actors: Vec<Id>,
    initial_snapshot: Option<PathBuf>,
}

fn configuration() -> Result<Configuration, String> {
    let mut options = std::collections::BTreeMap::new();
    let mut args = std::env::args().skip(1);
    while let Some(key) = args.next() {
        if ![
            "--native",
            "--scene",
            "--cell",
            "--world",
            "--actors",
            "--initial-snapshot",
        ]
        .contains(&key.as_str())
        {
            return Err(
                "Use --native PATH --scene PATH --cell METRES --world ID --actors ID,ID [--initial-snapshot PATH]".into(),
            );
        }
        let value = args.next().ok_or("Missing option value")?;
        if options.insert(key, value).is_some() {
            return Err("Duplicate option".into());
        }
    }
    let required = |key: &str| options.get(key).ok_or_else(|| format!("Missing {key}"));
    let native = PathBuf::from(required("--native")?);
    let scene = PathBuf::from(required("--scene")?);
    let cell = required("--cell")?
        .parse::<f64>()
        .map_err(|_| "Invalid --cell")?;
    let world = Id::new(required("--world")?.clone()).map_err(|_| "Invalid world ID")?;
    let actors = required("--actors")?
        .split(',')
        .map(Id::new)
        .collect::<Result<Vec<_>, _>>()
        .map_err(|_| "Invalid actors")?;
    Ok(Configuration {
        native,
        scene,
        cell,
        world,
        actors,
        initial_snapshot: options.get("--initial-snapshot").map(PathBuf::from),
    })
}

fn run() -> Result<(), String> {
    let Configuration {
        native,
        scene,
        cell,
        world: id,
        actors,
        initial_snapshot,
    } = configuration()?;
    let kernel = NativeProcess::open(&native, &scene, cell, initial_snapshot.as_deref())
        .map_err(|r| format!("Native open: {r:?}"))?;
    let native_identity = kernel.identity();
    let mut world = World::new(id, actors, kernel).map_err(|r| format!("World open: {r:?}"))?;
    let (sender, input) = mpsc::sync_channel(COMMAND_CAPACITY);
    thread::spawn(move || {
        let mut stream = BufReader::new(std::io::stdin());
        loop {
            let mut line = Vec::new();
            match (&mut stream)
                .take(MAX_COMMAND_BYTES as u64 + 1)
                .read_until(b'\n', &mut line)
            {
                Ok(0) | Err(_) => break,
                Ok(_) => {
                    let invalid = line.len() > MAX_COMMAND_BYTES || !line.ends_with(b"\n");
                    if invalid && !line.ends_with(b"\n") {
                        // Discard the rest without allocating it. One overlong
                        // input becomes one refusal, not several commands.
                        if stream.skip_until(b'\n').is_err() {
                            break;
                        }
                    }
                    let request = if invalid {
                        Err(Refusal::InvalidInput)
                    } else {
                        serde_json::from_slice::<TrustedRequest>(&line)
                            .map_err(|_| Refusal::InvalidInput)
                    };
                    if sender.send(request).is_err() {
                        break;
                    }
                }
            }
        }
    });
    let (output, responses) = mpsc::sync_channel::<Vec<u8>>(8);
    let disconnected = Arc::new(AtomicBool::new(false));
    let writer_disconnected = disconnected.clone();
    let (finished, writer_finished) = mpsc::sync_channel(1);
    thread::spawn(move || {
        let mut stream = std::io::stdout().lock();
        for bytes in responses {
            if stream
                .write_all(&bytes)
                .and_then(|()| stream.flush())
                .is_err()
            {
                writer_disconnected.store(true, Ordering::Release);
                break;
            }
        }
        let _ = finished.try_send(());
    });
    let send = |frame: Value| -> Result<(), String> {
        let mut bytes = serde_json::to_vec(&frame).map_err(|_| "Invalid output")?;
        if bytes.len() > MAX_OUTPUT_BYTES {
            return Err("Observation exceeds output budget".into());
        }
        bytes.push(b'\n');
        output
            .try_send(bytes)
            .map_err(|_| "Output stalled; stopping owned world".into())
    };
    send(
        json!({"schema":"banjo.worker.v1","status":"ready","clock":world.clock(),
        "authority":"trusted-host-stdin","queue_capacity":COMMAND_CAPACITY,"native":native_identity,
        "pickup":"requires native pickup_admission_version=1 and native_carry_version=1; pending until a physical batch confirms the grip"}),
    )?;
    let period = Duration::from_secs_f64(DT_S * f64::from(STEPS_PER_BATCH));
    let mut deadline = Instant::now() + period;
    let mut missed_deadlines = 0_u64;
    loop {
        if disconnected.load(Ordering::Acquire) {
            return Err("Output disconnected".into());
        }
        let now = Instant::now();
        if now >= deadline {
            world
                .advance()
                .map_err(|r| format!("World clock fault: {r:?}"))?;
            for completion in world.take_completions() {
                send(
                    json!({"schema":"banjo.worker-completion.v1","outcome":completion,"clock":world.clock()}),
                )?;
            }
            deadline += period;
            // No large-dt jump or unbounded catch-up loop on a slow kernel.
            let after = Instant::now();
            if after >= deadline {
                missed_deadlines +=
                    (after.duration_since(deadline).as_nanos() / period.as_nanos() + 1) as u64;
                deadline = after + period;
            }
        }
        match input.recv_timeout(deadline.saturating_duration_since(Instant::now())) {
            Ok(Ok(request)) => {
                let result = world.execute(request);
                send(json!({"schema":"banjo.worker-result.v1","outcome":result,
                    "clock":world.clock(),"missed_deadlines":missed_deadlines}))?;
            }
            Ok(Err(reason)) => {
                send(json!({"schema":"banjo.worker-input-refusal.v1","reason":reason}))?
            }
            Err(mpsc::RecvTimeoutError::Timeout) => (),
            Err(mpsc::RecvTimeoutError::Disconnected) => break,
        }
    }
    // NativeProcess drops and stops its own child. Do not wait indefinitely
    // for a stdout writer whose consumer has abandoned the pipe.
    drop(world);
    drop(output);
    writer_finished
        .recv_timeout(Duration::from_secs(2))
        .map_err(|_| "Output did not finish")?;
    Ok(())
}

fn main() {
    if let Err(reason) = run() {
        eprintln!("Banjo runtime: {reason}");
        std::process::exit(1);
    }
}
