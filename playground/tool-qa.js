import "/scene.js";
const $ = id => document.getElementById(id);
let catalog, token, report, runId = "", selected = "", viewer, serial = 0, refreshing = null, contactFrame = 0;
const active = () => ["starting", "running"].includes(report?.status);
const tell = e => { $("progress").textContent = e.message || String(e); };
const number = n => Number.isFinite(n) ? n.toLocaleString(undefined, {maximumFractionDigits: 3}) : "—";
async function api(path, body) {
  const r = await fetch("/api/tool-qa" + path, body === undefined ? {} : {method: "POST",
    headers: {"Content-Type": "application/json", "X-Banjo-Token": token}, body: JSON.stringify(body)});
  const data = await r.json();
  if (!r.ok || data.error) throw Error(data.error || "Request failed");
  return data;
}
function controls() {
  $("run-all").disabled = active() || !catalog?.engine_available;
  $("cancel").disabled = !active();
}
function rows() {
  $("cases").replaceChildren();
  for (const c of catalog.cases) {
    const result = report?.results?.find(r => r.id === c.id);
    const row = document.createElement("tr"), name = document.createElement("td"), status = document.createElement("td");
    const button = document.createElement("button"); button.textContent = c.title;
    button.onclick = () => inspect(c.id).catch(tell); name.append(button);
    row.className = selected === c.id ? "selected" : "";
    status.className = "status " + (result?.status || "");
    status.textContent = result?.outcome || result?.status || (report?.active_case === c.id ? "Running…" : "Not run");
    row.append(name, status); $("cases").append(row);
  }
}
function clear() {
  ++serial; selected = "";
  viewer?.dispose(); viewer = null;
  $("stage").replaceChildren(); $("metrics").replaceChildren();
  $("notes").textContent = $("response").textContent = $("verdict").textContent = "";
  for (const id of ["play", "start", "contact", "frame"]) $(id).disabled = true;
  $("request-link").hidden = $("recording-link").hidden = true;
}
function metric(title, value) {
  const cell = document.createElement("div"); cell.className = "metric";
  const label = document.createElement("small"), amount = document.createElement("strong");
  label.textContent = title; amount.textContent = value; cell.append(label, amount); $("metrics").append(cell);
}
async function runs(preferred) {
  const current = runId, data = await api("/runs");
  if (current !== runId) return;
  $("runs").replaceChildren();
  for (const r of data.runs) {
    const o = document.createElement("option"); o.value = r.id;
    o.textContent = (r.started_unix_s ? new Date(r.started_unix_s * 1000).toLocaleString() : r.id.slice(0,8)) + ` · ${r.completed}/${r.total} · ${r.status}`;
    $("runs").append(o);
  }
  runId = preferred || runId || data.runs[0]?.id || ""; $("runs").value = runId;
}
async function inspect(id) {
  clear(); selected = id; rows();
  const request = serial, run = runId, c = catalog.cases.find(c => c.id === id);
  $("case-title").textContent = c.title;
  const result = report?.results?.find(r => r.id === id);
  if (!result) { $("response").textContent = "Run the trials to record this use case."; return; }
  $("verdict").textContent = result.status === "passed" ? "Checks passed" : result.status;
  const m = result.measured;
  $("response").textContent = result.error || (result.status === "unsupported"
    ? "The point met rock, but the engine has no law for excavating it. This trial cannot establish mining performance."
    : m.depth_m > 0 ? `The point entered ${number(m.depth_m * 1000)} mm into soil. No soil was collected in this bite-only trial.`
    : "The point hit rock and stopped. It did not excavate material.");
  if (m) {
    metric("Penetration", number(m.depth_m * 1000) + " mm");
    metric("Impact speed", number(m.closing_speed_m_s) + " m/s");
    metric("Ground work", number(m.work_j) + " J");
    metric("Tool condition", m.tool_whole ? (m.tool_dent_mm > 0 ? "Dented" : "Whole in this trial") : "Damaged");
    metric("Tool mass", number(m.tool_mass_kg) + " kg");
    metric("Peak hand force", number(m.max_hand_force_n) + " N");
    metric("Mass residual", number(m.mass_residual_kg) + " kg");
    metric("Compute time", number(result.wall_s) + " s");
  }
  $("notes").textContent = (result.meetings || []).map(w => w.why).filter(Boolean).join("\n");
  const base = `/runs/${run}/${id}`, playback = await api(base + "/playback");
  if (request !== serial || run !== runId || !playback.frames?.length) return;
  viewer = window.BanjoScene.create($("stage"), {frameAllPoses: true, view: "front",
    onFrame: ({index, frame}) => { $("frame").value = index; $("clock").textContent = frame.time_s.toFixed(3) + " s"; },
    onPlayState: playing => { $("play").textContent = playing ? "Pause" : "Play"; }});
  viewer.load(playback); viewer.setGrabMode(false); viewer.setSpeed(Number($("speed").value));
  $("frame").max = playback.frames.length - 1;
  const at = result.meetings?.[0]?.at_s;
  contactFrame = Number.isFinite(at) ? playback.frames.findIndex(f => f.time_s >= at) : -1;
  for (const key of ["play", "start", "frame"]) $(key).disabled = false;
  $("contact").disabled = contactFrame < 0;
  $("request-link").href = "/api/tool-qa" + base + "/request";
  $("recording-link").href = "/api/tool-qa" + base + "/playback";
  $("request-link").hidden = $("recording-link").hidden = false;
  viewer.play(true);
}
async function refresh() {
  if (!runId || refreshing === runId) return;
  const run = runId; refreshing = run;
  try {
    const next = await api("/runs/" + run);
    if (run !== runId) return;
    const wasActive = active(); report = next;
    if (wasActive && !active()) await runs(run);
    if (run !== runId) return;
    const unsupported = report.results?.filter(r => r.status === "unsupported").length || 0;
    $("progress").textContent = `${report.completed}/${report.total} · ${report.status}`
      + (unsupported ? ` · ${unsupported} outside the supported model` : "") + (report.error ? " · " + report.error : "");
    rows(); controls();
    if (!selected && report.results?.length) await inspect(report.results[0].id);
    else if (selected && !viewer && report.results?.some(r => r.id === selected)) await inspect(selected);
  } finally { if (refreshing === run) refreshing = null; }
}
$("run-all").onclick = async () => {
  try { const r = await api("/run", {}); clear(); report = r; runId = r.id; controls(); await runs(runId); await refresh(); }
  catch (e) { tell(e); }
};
$("cancel").onclick = () => api("/cancel", {run_id: runId}).then(() => { $("cancel").disabled = true; }).catch(tell);
$("runs").onchange = () => { clear(); report = null; runId = $("runs").value; refresh().catch(tell); };
$("play").onclick = () => { if (viewer.frame === viewer.frameCount - 1) viewer.reset(); viewer.play(); };
$("start").onclick = () => viewer?.reset();
$("contact").onclick = () => viewer?.setFrame(contactFrame);
$("frame").oninput = () => viewer?.setFrame(Number($("frame").value));
$("speed").onchange = () => viewer?.setSpeed(Number($("speed").value));
try {
  const response = await fetch("/api/status"); token = (await response.json()).csrf_token;
  catalog = await api(""); await runs(); rows(); controls(); await refresh();
  if (!runId) $("progress").textContent = "Run the six trials, then select a use case to replay.";
  setInterval(() => { if (active() || report?.status === "unattached") refresh().catch(tell); }, 1000);
} catch (e) { tell(e); }
