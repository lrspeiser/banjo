import "/scene.js";
const $ = (id) => document.getElementById(id);
let catalog, token, runId = "", report, selected = "", viewer, requestSerial = 0, refreshingRun = null;
const active = () => ["starting", "running"].includes(report?.status);
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json", "X-Banjo-Token": token}, body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "HTTP " + response.status);
  return data;
}
function say(error) { $("progress").textContent = String(error.message || error); }
function option(select, value, text) {
  const o = document.createElement("option"); o.value = value; o.textContent = text; select.append(o);
}
function filtered() {
  return catalog.cases.filter(c => (!$("material").value || c.material === $("material").value)
    && (!$("thickness").value || String(c.thickness_mm) === $("thickness").value)
    && (!$("speed").value || String(c.speed_m_s) === $("speed").value));
}
function rows() {
  const done = new Map((report?.results || []).map(r => [r.id, r]));
  $("cases").replaceChildren();
  for (const c of filtered()) {
    const r = done.get(c.id), tr = document.createElement("tr");
    if (c.id === selected) tr.className = "selected";
    const name = document.createElement("td"), button = document.createElement("button");
    button.textContent = c.material[0].toUpperCase() + c.material.slice(1);
    const thickness = document.createElement("small"); thickness.textContent = c.thickness_mm + " mm thick";
    button.append(thickness); button.onclick = () => show(c.id).catch(say); name.append(button);
    const speed = document.createElement("td"); speed.textContent = c.speed_m_s + " m/s";
    const status = document.createElement("td"); status.className = "status " + (r?.status || "");
    status.textContent = r ? (r.metrics?.outcome || r.status) : (report?.active_case === c.id ? "Running…" : "Not run");
    if (r && r.status !== "passed" && r.metrics) status.textContent += " · review";
    tr.append(name, speed, status); $("cases").append(tr);
  }
  $("run-filtered").textContent = "Run filtered (" + filtered().length + ")";
}
function buttons() {
  $("run-all").disabled = active() || !catalog?.engine_available || !catalog?.baseline_available;
  $("run-filtered").disabled = $("run-all").disabled;
  $("cancel").disabled = !active();
}
async function runs(preferred) {
  const data = await api("/api/material-qa/runs");
  $("runs").replaceChildren();
  if (!data.runs.length) option($("runs"), "", "No saved runs");
  for (const r of data.runs) {
    const date = r.started_unix_s ? new Date(r.started_unix_s * 1000).toLocaleString() : r.id.slice(0, 8);
    option($("runs"), r.id, date + " · " + r.status);
  }
  runId = preferred || runId || data.runs[0]?.id || "";
  $("runs").value = runId;
}
async function refresh() {
  if (!runId || refreshingRun === runId) return;
  const requestedRun = runId;
  refreshingRun = requestedRun;
  try {
    const nextReport = await api("/api/material-qa/runs/" + requestedRun);
    if (requestedRun !== runId) return;
    report = nextReport;
    const runOption = [...$("runs").options].find(o => o.value === runId);
    if (runOption) runOption.textContent = runOption.textContent.replace(/ · [^·]*$/, " · " + report.status);
    const changed = report.results?.filter(r => r.status === "review_required").length || 0;
    const failed = report.results?.filter(r => ["failed", "error"].includes(r.status)).length || 0;
    $("progress").textContent = report.completed + "/" + report.total + " · " + report.status.replaceAll("_", " ")
      + (changed ? " · " + changed + " changed" : "") + (failed ? " · " + failed + " failed" : "")
      + (!report.baseline_checked && ["passed", "failed"].includes(report.status) ? " · initial measurement" : "");
    rows(); buttons();
    if (report.control_note) $("progress").textContent += " · runner not attached";
    if (!selected) {
      const first = report.results?.find(r => r.metrics);
      if (first) await show(first.id);
    }
  } finally { if (refreshingRun === requestedRun) refreshingRun = null; }
}
function metric(title, value) {
  const cell = document.createElement("div"); cell.className = "metric";
  const label = document.createElement("small"); label.textContent = title;
  const amount = document.createElement("strong"); amount.textContent = value;
  cell.append(label, amount); $("metrics").append(cell);
}
const number = (n, digits=3) => Number.isFinite(n) ? n.toLocaleString(undefined, {maximumFractionDigits: digits}) : "—";
async function show(id) {
  const serial = ++requestSerial;
  selected = id; rows();
  viewer?.play(false);
  for (const key of ["play", "back", "next", "frame"]) $(key).disabled = true;
  $("metrics").replaceChildren();
  $("report-link").hidden = $("recording-link").hidden = true;
  const c = catalog.cases.find(c => c.id === id);
  $("case-title").textContent = c.material + " / " + c.thickness_mm + " mm / " + c.speed_m_s + " m/s";
  const result = report?.results?.find(r => r.id === id);
  $("verdict").textContent = result?.status.replaceAll("_", " ") || "Not run";
  $("notes").textContent = result
    ? [...(result.issues || []), ...(result.changes || []), ...(result.warnings || [])].join("\n")
    : "Run this selection to record its physical response.";
  if (!result?.metrics) { if (viewer) viewer.dispose(); viewer = null; $("stage").replaceChildren(); return; }
  const m = result.metrics;
  metric("Fragments", number(m.components, 0)); metric("Broken bonds", number(m.broken_bonds, 0));
  metric("Initial energy", number(m.initial_kinetic_j) + " J"); metric("Contact impulse", number(m.impulse_n_s) + " N·s");
  metric("Specimen mass", number(m.tile_mass_kg) + " kg"); metric("Largest piece", number(m.largest_mass_fraction * 100, 1) + "%");
  metric("Removed bond energy", number(m.removed_energy_j) + " J"); metric("Compute time", number(result.wall_s, 2) + " s");
  const base = "/api/material-qa/runs/" + runId + "/" + id;
  $("report-link").href = base + "/native"; $("report-link").hidden = false;
  $("recording-link").href = base + "/playback"; $("recording-link").hidden = false;
  const recording = await api(base + "/playback");
  if (serial !== requestSerial) return;
  if (!viewer) viewer = window.BanjoScene.create($("stage"), {
    onFrame: ({index, count, frame}) => {
      $("frame").max = Math.max(0, count - 1); $("frame").value = index;
      $("clock").textContent = frame.time_s.toFixed(4) + " s · " + frame.phase;
    },
    onPlayState: playing => { $("play").textContent = playing ? "Pause" : "Play"; },
  });
  viewer.load(recording); viewer.setGrabMode(false); viewer.showBonds($("damage").checked);
  viewer.holdFracture($("slow").checked);
  for (const key of ["play", "back", "next", "frame"]) $(key).disabled = false;
}
function clearInspection() {
  ++requestSerial;
  selected = "";
  viewer?.dispose(); viewer = null;
  $("stage").replaceChildren();
  $("case-title").textContent = "Waiting for a recorded impact";
  $("verdict").textContent = "";
  $("metrics").replaceChildren(); $("notes").textContent = "";
  $("report-link").hidden = $("recording-link").hidden = true;
  for (const key of ["play", "back", "next", "frame"]) $(key).disabled = true;
}
async function start(ids) {
  const data = await api("/api/material-qa/run", ids ? {case_ids: ids} : {});
  clearInspection(); report = data; runId = data.id;
  await runs(runId); await refresh(); buttons();
}
$("runs").onchange = async () => { runId = $("runs").value; clearInspection(); await refresh().catch(say); };
for (const key of ["material", "thickness", "speed"]) $(key).onchange = rows;
$("run-all").onclick = () => start().catch(say);
$("run-filtered").onclick = () => start(filtered().map(c => c.id)).catch(say);
$("cancel").onclick = async () => {
  try { await api("/api/material-qa/cancel", {run_id: runId}); $("cancel").disabled = true; $("progress").textContent = "Cancelling…"; }
  catch (e) { say(e); }
};
$("play").onclick = () => { if (viewer.frame === viewer.frameCount - 1) viewer.reset(); viewer.play(); };
$("back").onclick = () => viewer.step(-1); $("next").onclick = () => viewer.step(1);
$("frame").oninput = () => viewer.setFrame(Number($("frame").value));
$("damage").onchange = () => viewer?.showBonds($("damage").checked);
$("slow").onchange = () => viewer?.holdFracture($("slow").checked);
try {
  const status = await api("/api/status"); token = status.csrf_token;
  catalog = await api("/api/material-qa");
  for (const m of catalog.materials) option($("material"), m, m[0].toUpperCase() + m.slice(1));
  for (const t of catalog.thicknesses_mm) option($("thickness"), t, t + " mm");
  for (const s of catalog.speeds_m_s) option($("speed"), s, s + " m/s");
  await runs(); rows(); buttons();
  if (runId) await refresh();
  else $("progress").textContent = catalog.engine_available ? "Ready to record the range." : "Build the native fracture runner to enable recording.";
  setInterval(() => { if (active() || report?.status === "unattached") refresh().catch(say); }, 2000);
} catch (e) { say(e); }
