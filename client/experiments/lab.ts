import {
  validateRecording,
  validateRequest,
  validateResult,
  type Cell,
  type Frame,
  type Run,
  type Recording,
} from "./contract.js";
const element = <T extends HTMLElement>(id: string): T => {
  const node = document.getElementById(id);
  if (!node) throw new Error(`Missing control ${id}`);
  return node as T;
};
const scenes = element("scenes"),
  status = element("status"),
  slider = element<HTMLInputElement>("frame");
const play = element<HTMLButtonElement>("play"),
  material = element<HTMLSelectElement>("material");
const magnification = element<HTMLSelectElement>("magnification");
const runButton = element<HTMLButtonElement>("run"),
  forceScale = element<HTMLSelectElement>("force-scale"),
  runStatus = element("run-status");
let recording: Recording | null = null,
  interaction = "load",
  index = 0,
  timer: ReturnType<typeof setInterval> | null = null;
const names: Record<string, string> = {
  glass: "Glass",
  oak: "Oak",
  iron: "Iron",
};
const fmt = (n: number, d = 2) =>
  new Intl.NumberFormat("en-US", { maximumFractionDigits: d }).format(n);
function runs(): Run[] {
  return (
    recording?.experiments.filter(
      (r) =>
        r.interaction === interaction &&
        (material.value === "all" || r.material === material.value),
    ) ?? []
  );
}
function stop() {
  if (timer !== null) clearInterval(timer);
  timer = null;
  play.textContent =
    index === 20 ? "Replay response" : "Play recorded response";
}
function projected(cell: Cell): [number, number] {
  const m = Number(magnification.value),
    p = cell.position_m.map(
      (v, a) => v + (m - 1) * (cell.displacement_m[a] ?? 0),
    );
  const x = p[0] ?? 0,
    y = p[1] ?? 0,
    z = p[2] ?? 0;
  return [0.866 * (x - z), 0.43 * (x + z) - y];
}
function bounds(): [number, number, number, number] {
  let minX = Infinity,
    maxX = -Infinity,
    minY = Infinity,
    maxY = -Infinity;
  for (const run of recording?.experiments.filter(
    (r) => r.interaction === interaction,
  ) ?? [])
    for (const f of run.frames)
      for (const c of f.nodes) {
        const [x, y] = projected(c);
        minX = Math.min(minX, x);
        maxX = Math.max(maxX, x);
        minY = Math.min(minY, y);
        maxY = Math.max(maxY, y);
      }
  return [minX - 0.04, maxX + 0.04, minY - 0.04, maxY + 0.04];
}
function draw(
  canvas: HTMLCanvasElement,
  run: Run,
  frame: Frame,
  box: [number, number, number, number],
) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const width = canvas.clientWidth,
    height = canvas.clientHeight,
    dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  ctx.scale(dpr, dpr);
  const [minX, maxX, minY, maxY] = box,
    scale = Math.min(
      (width - 44) / (maxX - minX),
      (height - 40) / (maxY - minY),
    );
  const point = (node: Cell): [number, number] => {
    const [x, y] = projected(node);
    return [
      width / 2 + (x - (minX + maxX) / 2) * scale,
      height / 2 + (y - (minY + maxY) / 2) * scale,
    ];
  };
  const positions = frame.nodes.map(point);
  ctx.strokeStyle = "#6093bb50";
  ctx.lineWidth = 0.65;
  ctx.beginPath();
  for (let i = 0; i < run.bond_topology.length; i++)
    if (frame.bond_state[i]?.[0]) {
      const pair = run.bond_topology[i];
      if (!pair) continue;
      const a = positions[pair[0]],
        b = positions[pair[1]];
      if (a && b) {
        ctx.moveTo(...a);
        ctx.lineTo(...b);
      }
    }
  ctx.stroke();
  const sorted = frame.nodes
    .map((c, i) => ({ c, i }))
    .sort(
      (a, b) =>
        a.c.position_m[2] +
        a.c.position_m[0] -
        (b.c.position_m[2] + b.c.position_m[0]),
    );
  for (const { c, i } of sorted) {
    const p = positions[i];
    if (!p) continue;
    ctx.fillStyle = c.clamped ? "#dee8f4" : c.attached ? "#78b9ed" : "#ffbf70";
    ctx.beginPath();
    ctx.arc(
      ...p,
      Math.max(2.5, Math.min(6, run.cell_m * scale * 0.15)),
      0,
      Math.PI * 2,
    );
    ctx.fill();
  }
  const loaded = positions[run.loaded_node];
  if (loaded && frame.step <= 512) {
    ctx.strokeStyle = "#b3e5fa";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(...loaded, 10, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = "#b3e5fa";
    ctx.font = "11px system-ui";
    ctx.fillText("Load", loaded[0] + 13, loaded[1] - 8);
  }
  ctx.fillStyle = "#9aa9bb";
  ctx.font = "11px system-ui";
  ctx.fillText(
    `${magnification.value}× displacement · cell centres`,
    14,
    height - 10,
  );
}
function render() {
  const selected = runs(),
    box = bounds();
  scenes.classList.toggle("single", selected.length === 1);
  scenes.replaceChildren();
  for (const run of selected) {
    const f = run.frames[index];
    if (!f) continue;
    const card = document.createElement("article");
    card.className = "scene";
    const header = document.createElement("header"),
      title = document.createElement("h2"),
      mass = document.createElement("span");
    title.textContent = names[run.material] ?? run.material;
    mass.className = "mass";
    mass.textContent = `${fmt(f.mass_kg)} kg${run.material === "oak" ? " · lab only" : ""}`;
    header.append(title, mass);
    const canvas = document.createElement("canvas");
    canvas.setAttribute("role", "img");
    canvas.setAttribute(
      "aria-label",
      `${title.textContent}: ${f.components} component(s), ${f.broken_bonds} broken bonds at ${fmt(f.time_s * 1e6)} microseconds`,
    );
    const metrics = document.createElement("div");
    metrics.className = "metrics";
    const free = f.nodes.filter((c) => !c.attached).length;
    for (const [label, value] of [
      ["Work supplied", `${fmt(f.work_j)} J`],
      ["Broken bonds", String(f.broken_bonds)],
      ["Free cells", String(free)],
    ]) {
      const item = document.createElement("div"),
        name = document.createElement("span"),
        valueNode = document.createElement("strong");
      name.textContent = label ?? "";
      valueNode.textContent = value ?? "";
      item.append(name, valueNode);
      metrics.append(item);
    }
    card.append(header, canvas, metrics);
    scenes.append(card);
    draw(canvas, run, f, box);
  }
  slider.value = String(index);
  element("time").textContent = `${fmt(index * 3.2, 1)} μs`;
  element("phase").textContent =
    index <= 16 ? "Load applied" : "Load removed · motion continues";
  const load = recording?.request.force_scale ?? 1;
  status.textContent = `${interaction === "pull" ? `Upward pull: ${fmt(load)} MN` : `Force: (${fmt(10 * load)}, ${fmt(-20 * load)}, ${fmt(30 * load)}) kN`} · 25 cm block · 125 cells · ${magnification.value}× displacement`;
  const conditions = element("conditions");
  conditions.textContent =
    "50 mm cells · 100 ns steps · 25 fixed bottom cells · no gravity or damping. Same input, geometry and time for all materials. The existing isotropic elastic/strength reference drives damage. Grain, plasticity and calibrated crack work are unsupported in this wrapper. The laboratory force is not a human tool rating.";
  const table = document.createElement("table");
  const row = (values: string[], head = false) => {
    const tr = document.createElement("tr");
    for (const value of values) {
      const td = document.createElement(head ? "th" : "td");
      td.textContent = value;
      tr.append(td);
    }
    table.append(tr);
  };
  row(
    [
      "Material",
      "Density kg/m³",
      "Stiffness GPa",
      "Stored energy J",
      "Numerical error J",
      "Balance residual J",
      "Run + capture ms",
    ],
    true,
  );
  for (const run of selected) {
    const f = run.frames[index];
    if (f)
      row([
        names[run.material] ?? run.material,
        fmt(run.density_kg_m3),
        fmt(run.young_modulus_pa / 1e9),
        fmt(f.elastic_j, 6),
        f.integration_error_j.toExponential(3),
        f.energy_residual_j.toExponential(3),
        fmt(run.solver_wall_s * 1000),
      ]);
  }
  element("measurements").replaceChildren(table);
  document.body.dataset["frame"] = String(index);
  document.body.dataset["interaction"] = interaction;
}
document
  .querySelectorAll<HTMLButtonElement>("[data-interaction]")
  .forEach((button) =>
    button.addEventListener("click", () => {
      interaction = button.dataset["interaction"] ?? "load";
      index = 0;
      stop();
      magnification.value = interaction === "pull" ? "1" : "1000";
      document
        .querySelectorAll<HTMLButtonElement>("[data-interaction]")
        .forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
      render();
    }),
  );
slider.addEventListener("input", () => {
  index = Number(slider.value);
  stop();
  render();
});
material.addEventListener("change", render);
magnification.addEventListener("change", render);
play.addEventListener("click", () => {
  if (timer !== null) {
    stop();
    return;
  }
  if (index === 20) index = 0;
  render();
  play.textContent = "Pause replay";
  timer = setInterval(() => {
    index = Math.min(20, index + 1);
    render();
    if (index === 20) stop();
  }, 180);
});
window.addEventListener("resize", () => {
  if (recording) render();
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) stop();
});
forceScale.addEventListener("change", () => {
  runStatus.textContent = `Ready to run at ${Number(forceScale.value) * 100}%. Displayed results stay unchanged until completion.`;
});
runButton.addEventListener("click", async () => {
  const request = validateRequest({
    schema: "banjo.material-lab-request.v1",
    force_scale: Number(forceScale.value),
  });
  stop();
  runButton.disabled = true;
  forceScale.disabled = true;
  runStatus.textContent = "Running six fresh CPU experiments…";
  document.body.dataset["execution"] = "running";
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch("api/experiments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
    if (!response.ok) {
      const error: unknown = await response.json();
      const message =
        typeof error === "object" &&
        error !== null &&
        "error" in error &&
        typeof error.error === "string"
          ? error.error
          : `Experiment unavailable (${response.status})`;
      throw new Error(message);
    }
    const text = await response.text();
    if (text.length > 10_000_000)
      throw new Error("Experiment exceeds viewer budget");
    const result = validateResult(JSON.parse(text), request);
    recording = result.recording;
    index = 0;
    stop();
    render();
    play.disabled = false;
    slider.disabled = false;
    runStatus.textContent = `Completed · ${fmt(request.force_scale * 100)}% load · ${fmt(result.elapsed_wall_s, 2)} s. Play or scrub the response.`;
    runStatus.title = `Execution ${result.execution_id}\nNative ${result.identity.native_sha256}\nRequest ${result.identity.request_sha256}\nRecording ${result.identity.recording_sha256}`;
    document.body.dataset["execution"] = "completed";
    document.body.dataset["executionId"] = result.execution_id;
    document.body.dataset["state"] = "ready";
  } catch (error) {
    const reason =
      error instanceof Error && error.name === "AbortError"
        ? "Request timed out"
        : error instanceof Error
          ? error.message
          : "Experiment failed";
    runStatus.textContent = `${reason}. Previous results retained. Try again.`;
    document.body.dataset["execution"] = "refused";
  } finally {
    clearTimeout(timeout);
    runButton.disabled = false;
    forceScale.disabled = false;
  }
});
async function load() {
  try {
    const response = await fetch("material.json", { cache: "no-store" });
    if (!response.ok)
      throw new Error(`Recording unavailable (${response.status})`);
    const text = await response.text();
    if (text.length > 10_000_000)
      throw new Error("Recording exceeds viewer budget");
    recording = validateRecording(JSON.parse(text));
    render();
    play.disabled = false;
    slider.disabled = false;
    document.body.dataset["state"] = "ready";
    runStatus.textContent =
      "Baseline · 100% load. Choose a strength and run a fresh experiment.";
  } catch (error) {
    document.body.dataset["state"] = "error";
    status.textContent = `Cannot open experiment: ${error instanceof Error ? error.message : "invalid recording"}`;
    play.disabled = true;
    slider.disabled = true;
    runStatus.textContent =
      "Baseline unavailable. You can still run a fresh experiment.";
  } finally {
    runButton.disabled = false;
  }
}
void load();
