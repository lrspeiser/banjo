import "/scene.js";
const $ = (id) => document.getElementById(id);
let catalog, token, runId = "", report, selected = "", viewer, requestSerial = 0, refreshingRun = null, impactFrame = 0;
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
  const demo = catalog.demonstrations?.find(d => d.id === $("demonstration").value);
  return catalog.cases.filter(c => (!demo || demo.case_ids.includes(c.id)) && (!$("material").value || c.material === $("material").value)
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
  $("run-filtered").textContent = "Run these " + filtered().length + " impacts";
  $("run-filtered").disabled = $("run-all").disabled || !filtered().length;
  $("demo-about").textContent = (catalog.demonstrations?.find(d => d.id === $("demonstration").value)?.about || "All conditions in the regression matrix.") + " Each run starts at impact speed, 2 mm above the center; the free fall is not recorded. Select a result to replay it.";
}
function buttons() {
  $("run-all").disabled = active() || !catalog?.engine_available || !catalog?.baseline_available;
  $("run-filtered").disabled = $("run-all").disabled || !filtered().length;
  $("cancel").disabled = !active();
}
async function runs(preferred) {
  const data = await api("/api/material-qa/runs");
  $("runs").replaceChildren();
  if (!data.runs.length) option($("runs"), "", "No saved runs");
  for (const r of data.runs) {
    const date = r.started_unix_s ? new Date(r.started_unix_s * 1000).toLocaleString() : r.id.slice(0, 8);
    option($("runs"), r.id, date + " · " + r.completed + "/" + r.total + " · " + r.status);
  }
  // Open the newest full matrix first, so a later one-case check does not
  // hide the rest of the material range. Explicit user selections still win.
  const complete = data.runs.find(r => r.total === catalog.cases.length && r.completed === r.total);
  runId = preferred || runId || complete?.id || data.runs[0]?.id || "";
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
    if (runOption) runOption.textContent = runOption.textContent.replace(/ · \d+\/\d+ · [^·]*$/, " · " + report.completed + "/" + report.total + " · " + report.status);
    const changed = report.results?.filter(r => r.status === "review_required").length || 0;
    const failed = report.results?.filter(r => ["failed", "error"].includes(r.status)).length || 0;
    $("progress").textContent = report.completed + "/" + report.total + " · " + report.status.replaceAll("_", " ")
      + (changed ? " · " + changed + " changed" : "") + (failed ? " · " + failed + " failed" : "")
      + (!report.baseline_checked && ["passed", "failed"].includes(report.status) ? " · initial measurement" : "");
    rows(); buttons();
    if (report.control_note) $("progress").textContent += " · runner not attached";
    if (!selected) {
      const ids = new Set(filtered().map(c => c.id));
      const first = report.results?.find(r => r.metrics && ids.has(r.id));
      if (first) await show(first.id);
    } else if (!viewer && report.results?.some(r => r.id === selected && r.metrics)) {
      await show(selected);
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
  for (const key of ["play", "back", "next", "frame", "impact"]) $(key).disabled = true;
  $("metrics").replaceChildren();
  $("response").textContent = $("alignment").textContent = "";
  $("report-link").hidden = $("recording-link").hidden = true;
  const c = catalog.cases.find(c => c.id === id);
  $("case-title").textContent = c.material + " / " + c.thickness_mm + " mm / " + c.speed_m_s + " m/s";
  const result = report?.results?.find(r => r.id === id);
  $("verdict").textContent = result ? "Checks: " + result.status.replaceAll("_", " ") : "Not run";
  $("notes").textContent = result
    ? [...(result.issues || []), ...(result.changes || []), ...(result.warnings || [])].join("\n")
    : "Run this selection to record its physical response.";
  if (!result?.metrics) { if (viewer) viewer.dispose(); viewer = null; $("stage").replaceChildren(); return; }
  const m = result.metrics;
  $("response").textContent = !(m.contact_events > 0)
    ? "No contact was recorded. This run does not establish whether the specimen survives a strike."
    : m.components > 1
    ? `The specimen separated into ${m.components} pieces; ${number(m.largest_mass_fraction * 100, 1)}% of its mass remains in the largest piece.`
    : m.broken_bonds > 0
      ? `${m.broken_bonds} bonds broke, but the specimen remains one connected piece.`
      : `Contact occurred. No bonds broke under this strike; the specimen stayed connected.`;
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
    frameAllPoses: true,
    onFrame: ({index, count, frame}) => {
      $("frame").max = Math.max(0, count - 1); $("frame").value = index;
      $("clock").textContent = frame.time_s.toFixed(4) + " s · " + frame.phase;
    },
    onPlayState: playing => { $("play").textContent = playing ? "Pause" : "Play"; },
  });
  viewer.load(recording); viewer.setGrabMode(false); viewer.showBonds($("damage").checked);
  viewer.holdFracture($("slow").checked);
  viewer.setSpeed(Number($("playback-speed").value));
  const a = m.alignment;
  $("alignment").textContent = a?.valid
    ? `Centered strike verified · horizontal offset ${number(Math.hypot(...a.offset_xz_m)*1000, 3)} mm · initial clearance ${number(a.initial_gap_m*1000, 3)} mm. Camera includes the full recorded motion.`
    : a ? "Fixture alignment needs review. See the native report." : "Older recording: alignment was not checked when this run was saved. Rerun to verify the fixture.";
  impactFrame = Math.max(0, recording.frames.findIndex(f => f.time_s > 0));
  for (const key of ["play", "back", "next", "frame", "impact"]) $(key).disabled = false;
  viewer.play(true);
}
function clearInspection() {
  ++requestSerial;
  selected = "";
  viewer?.dispose(); viewer = null;
  $("stage").replaceChildren();
  $("case-title").textContent = "Waiting for a recorded impact";
  $("verdict").textContent = "";
  $("metrics").replaceChildren(); $("notes").textContent = $("response").textContent = $("alignment").textContent = "";
  $("report-link").hidden = $("recording-link").hidden = true;
  for (const key of ["play", "back", "next", "frame", "impact"]) $(key).disabled = true;
}
async function start(ids) {
  const data = await api("/api/material-qa/run", ids ? {case_ids: ids} : {});
  clearInspection(); report = data; runId = data.id;
  await runs(runId); await refresh(); buttons();
}
$("runs").onchange = async () => { runId = $("runs").value; clearInspection(); await refresh().catch(say); };
for (const key of ["material", "thickness", "speed"]) $(key).onchange = rows;
$("demonstration").onchange = () => {
  for (const key of ["material", "thickness", "speed"]) $(key).value = "";
  clearInspection(); rows(); refresh().catch(say);
};
$("run-all").onclick = () => start().catch(say);
$("run-filtered").onclick = () => start(filtered().map(c => c.id)).catch(say);
$("cancel").onclick = async () => {
  try { await api("/api/material-qa/cancel", {run_id: runId}); $("cancel").disabled = true; $("progress").textContent = "Cancelling…"; }
  catch (e) { say(e); }
};
$("play").onclick = () => { if (viewer.frame === viewer.frameCount - 1) viewer.reset(); viewer.play(); };
$("back").onclick = () => viewer.step(-1); $("next").onclick = () => viewer.step(1);
$("frame").oninput = () => viewer.setFrame(Number($("frame").value));
$("impact").onclick = () => viewer?.setFrame(impactFrame);
$("playback-speed").onchange = () => viewer?.setSpeed(Number($("playback-speed").value));
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
