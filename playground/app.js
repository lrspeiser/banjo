(() => {
  "use strict";

  const state = {
    status: null,
    goal: null,
    job: null,
    jobId: null,
    pollTimer: null,
    selectedCase: 0,
    followup: true,
    messages: [],
    history: [],
  };

  const $ = (id) => document.getElementById(id);
  const terminalStatuses = new Set(["complete", "blocked", "error"]);
  const activeStatuses = new Set(["planning", "validating", "running"]);
  const promptExamples = [
    "Compare glass, oak, and iron ball drops at 2 m/s.",
    "Compare the fixed spatial quasistatic pressure response of glass, oak, and iron.",
    "Test a knife cutting a tomato proxy and report unresolved limits.",
    "Measure a ground-supported mixed-material contact scene.",
  ];

  function text(value, fallback = "—") {
    if (value === null || value === undefined || value === "") return fallback;
    if (typeof value === "string") return value;
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    return JSON.stringify(value);
  }

  function pretty(value) {
    if (value === null || value === undefined) return "No data.";
    try { return JSON.stringify(value, null, 2); } catch { return "Unable to serialize this response."; }
  }

  function setText(node, value, fallback) {
    if (node) node.textContent = text(value, fallback);
  }

  function showToast(message, isError = false) {
    const node = $("toast");
    node.textContent = message;
    node.classList.toggle("toast-error", isError);
    node.hidden = false;
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => { node.hidden = true; }, 4200);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, options);
    let data = null;
    try { data = await response.json(); } catch { data = null; }
    if (!response.ok) {
      const detail = data && (data.error || data.message);
      throw new Error(detail ? text(detail) : `Request failed (${response.status})`);
    }
    return data;
  }

  function tokenHeaders() {
    const token = state.status && state.status.csrf_token;
    return token ? { "X-Banjo-Token": token } : {};
  }

  function setPill(id, label, kind = "neutral") {
    const node = $(id);
    node.className = `status-pill status-${kind}`;
    const dot = document.createElement("i");
    dot.setAttribute("aria-hidden", "true");
    node.replaceChildren(dot, document.createTextNode(label));
  }

  function renderStatus() {
    const status = state.status || {};
    if (status.engine_ready) setPill("engine-status", "Engine ready", "ready");
    else setPill("engine-status", "Engine unavailable", "error");
    if (status.studio_ready) setPill("studio-status", "Native studio ready", "ready");
    else setPill("studio-status", "Studio unavailable", "warn");

    const capabilities = Array.isArray(status.capabilities) ? status.capabilities.filter((capability) => capability !== "unsupported") : [];
    const capList = $("capability-list");
    capList.replaceChildren();
    if (!capabilities.length) {
      const tag = document.createElement("span");
      tag.className = "tag muted-tag";
      tag.textContent = "No capabilities reported";
      capList.append(tag);
    } else {
      capabilities.forEach((capability) => {
        const tag = document.createElement("span");
        tag.className = "tag";
        tag.textContent = capability === "continuum_pressure_reference" ? "Spatial pressure reference" : text(capability);
        capList.append(tag);
      });
    }
    const limitations = Array.isArray(status.limitations) ? status.limitations : [];
    setText($("limitation-note"), limitations.length ? limitations.join(" · ") : "No limitations reported.");
    renderPromptChips(Array.isArray(status.examples) && status.examples.length ? status.examples : promptExamples);
  }

  function renderPromptChips(items) {
    const chips = $("prompt-chips");
    chips.replaceChildren();
    items.slice(0, 6).forEach((item) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.textContent = text(item);
      chip.addEventListener("click", () => { $("prompt-input").value = text(item, ""); $("prompt-input").focus(); });
      chips.append(chip);
    });
  }

  function addMessage(author, message) {
    state.messages.push({ author, message });
    renderConversation();
  }

  function renderConversation() {
    const conversation = $("conversation");
    conversation.replaceChildren();
    if (!state.messages.length) {
      const empty = document.createElement("div");
      empty.className = "empty-conversation";
      const orb = document.createElement("span");
      orb.className = "empty-orb";
      orb.setAttribute("aria-hidden", "true");
      orb.textContent = "✦";
      const copy = document.createElement("p");
      copy.append(document.createTextNode("Start with a measurable question."));
      const sub = document.createElement("span");
      sub.textContent = "Try one of the prompts below.";
      copy.append(document.createElement("br"), sub);
      empty.append(orb, copy);
      conversation.append(empty);
      return;
    }
    state.messages.forEach((item) => {
      const row = document.createElement("div");
      row.className = `message ${item.author === "You" ? "user" : "assistant"}`;
      const mark = document.createElement("span");
      mark.className = "message-mark";
      mark.setAttribute("aria-hidden", "true");
      mark.textContent = item.author === "You" ? "YOU" : "B";
      const body = document.createElement("div");
      body.className = "message-body";
      const author = document.createElement("div");
      author.className = "message-author";
      author.textContent = item.author;
      const copy = document.createElement("p");
      copy.className = "message-copy";
      copy.textContent = item.message;
      body.append(author, copy);
      row.append(mark, body);
      conversation.append(row);
    });
    conversation.scrollTop = conversation.scrollHeight;
  }

  function renderPlan(plan) {
    const content = $("plan-content");
    content.replaceChildren();
    if (!plan) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      ["wide", "", "short"].forEach((kind) => { const line = document.createElement("span"); line.className = `empty-line ${kind}`; empty.append(line); });
      content.append(empty);
      setText($("plan-badge"), "Awaiting prompt");
      return;
    }
    setText($("plan-badge"), "Generated proposal");
    const provenance = document.createElement("p");
    provenance.className = "muted";
    provenance.textContent = "Generated proposal; engine evidence appears in Results.";
    const stats = document.createElement("div");
    stats.className = "plan-summary";
    const experimentNames = {
      panel_impact: "Panel impact",
      plate_drop: "Plate drop",
      rigid_drop: "Rigid drop control",
      knife_cut: "Knife / tomato cut",
      custom_objects: "Custom objects",
      thermal_frontier: "Thermal frontier",
      material_state_reference: "Material-state reference",
      continuum_pressure_reference: "Spatial pressure reference",
      glass_reference: "Published glass reference",
      unsupported: "Unsupported request",
    };
    const sweep = Array.isArray(plan.speeds_m_s) && plan.speeds_m_s.length
      ? `${plan.speeds_m_s.length} speed case(s)`
      : Array.isArray(plan.heights_m) && plan.heights_m.length
        ? `${plan.heights_m.length} height case(s)`
        : Array.isArray(plan.objects) && plan.objects.length
          ? `${plan.objects.length} authored object(s)`
          : "Fixed reference";
    const continuum = plan.experiment === "continuum_pressure_reference";
    const values = [
      ["Experiment", experimentNames[plan.experiment] || plan.experiment],
      ...(continuum
        ? [["Loading", "32 up / 32 down"], ["Fixed setup", "40 × 20 × 40 mm · 800 MPa peak"]]
        : [["Simulated time", plan.duration_s !== undefined ? `${plan.duration_s} s` : undefined]]),
      ["Sweeps / cases", sweep],
      ["Name", plan.name],
    ];
    values.forEach(([label, value]) => {
      const stat = document.createElement("div"); stat.className = "plan-stat";
      const key = document.createElement("span"); key.className = "stat-label"; key.textContent = label;
      const val = document.createElement("strong"); val.className = "stat-value"; val.textContent = text(value, "Declared in plan");
      stat.append(key, val); stats.append(stat);
    });
    content.append(provenance, stats);
    const list = document.createElement("ul"); list.className = "plan-list";
    const steps = Array.isArray(plan.steps) ? plan.steps : Array.isArray(plan.acceptance) ? plan.acceptance : [];
    steps.slice(0, 5).forEach((step) => { const item = document.createElement("li"); item.textContent = text(typeof step === "object" ? (step.name || step.description || step.check) : step); list.append(item); });
    if (list.children.length) content.append(list);
    const raw = document.createElement("pre"); raw.className = "plan-json"; raw.textContent = pretty(plan); content.append(raw);
  }

  function jobPhaseIndex(status) { return ["planning", "validating", "running", "complete"].indexOf(status); }

  function renderJob(job) {
    if (!job) {
      setText($("job-badge"), "Idle");
      $("job-content").replaceChildren();
      const p = document.createElement("p"); p.className = "muted"; p.textContent = "No active job. Results appear here after a prompt is accepted."; $("job-content").append(p);
      renderPlan(null);
      return;
    }
    const status = text(job.status, "unknown");
    setText($("job-badge"), status);
    $("job-content").replaceChildren();
    const track = document.createElement("div"); track.className = "job-track";
    const phase = jobPhaseIndex(status);
    ["Planning", "Validating", "Running", "Complete"].forEach((_, index) => { const segment = document.createElement("span"); if (phase >= index && phase >= 0) segment.className = "done"; if (phase === index) segment.className = "current"; track.append(segment); });
    const message = document.createElement("p"); message.className = "job-message"; message.textContent = text(job.message, status === "error" ? "The backend returned an error." : "Working…");
    const meta = document.createElement("div"); meta.className = "job-meta";
    const left = document.createElement("span"); left.textContent = `Job ${text(job.id, "unknown")}`;
    const right = document.createElement("span"); right.textContent = `${Array.isArray(job.cases) ? job.cases.length : 0} case(s)`;
    meta.append(left, right); $("job-content").append(track, message, meta);
    renderPlan(job.plan);
    const send = $("send-button");
    const active = activeStatuses.has(status);
    send.disabled = active;
    send.classList.toggle("is-busy", active);
    setText($("composer-hint"), active ? "A job is running; follow-ups unlock when it finishes." : "Enter to send · Shift+Enter for a new line");
    if (job.error) showToast(text(job.error), true);
  }

  function flatten(value, prefix = "", result = {}) {
    if (value === null || value === undefined) { result[prefix || "value"] = value; return result; }
    if (Array.isArray(value)) { result[prefix || "value"] = `[${value.length} items]`; return result; }
    if (typeof value === "object") { Object.keys(value).forEach((key) => flatten(value[key], prefix ? `${prefix}.${key}` : key, result)); return result; }
    result[prefix || "value"] = value;
    return result;
  }

  function renderCaseSelect() {
    const select = $("language-case-select"); select.replaceChildren();
    const cases = state.job && Array.isArray(state.job.cases) ? state.job.cases : [];
    cases.forEach((item, index) => { const option = document.createElement("option"); option.value = String(index); option.textContent = `${index + 1}. ${text(item.name, `Case ${index + 1}`)}`; select.append(option); });
    select.disabled = !cases.length;
    if (cases.length) select.value = String(Math.min(state.selectedCase, cases.length - 1));
  }

  function selectedCase() { return state.job && Array.isArray(state.job.cases) ? state.job.cases[state.selectedCase] : null; }

  function canOpenCase(item) {
    if (!item || !item.package) return false;
    if (item.native_scene === true) return true;
    if (item.native_scene === false) return false;
    return (item.status === "validated" || item.status === "complete") &&
      typeof item.package.physics_abi === "string" && item.package.physics_abi.length > 0;
  }

  function renderLanguage() {
    renderCaseSelect();
    const item = selectedCase();
    setText($("package-json"), item && item.package ? pretty(item.package) : "No generated package yet.");
    setText($("report-json"), item && item.report ? pretty(item.report) : "No report yet.");
    renderJsonAccordion(item && item.report ? item.report : null);
    $("download-package-language").disabled = !(state.job && state.job.id && item && item.package);
  }

  function renderJsonAccordion(value) {
    const root = $("report-accordion");
    root.replaceChildren();
    if (value === null || value === undefined) return;
    const maxChildren = 200;
    const addNode = (parent, key, current, depth) => {
      const isObject = current !== null && typeof current === "object" && !Array.isArray(current);
      const isArray = Array.isArray(current);
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = `${key}${isArray ? ` · ${current.length} items` : isObject ? " · object" : ""}`;
      details.append(summary);
      if (isObject || isArray) {
        const populate = () => {
          if (details.dataset.loaded === "true") return;
          details.dataset.loaded = "true";
          const entries = isArray ? current.map((entry, index) => [String(index), entry]) : Object.entries(current);
          const children = document.createElement("div");
          children.className = "json-children";
          entries.slice(0, maxChildren).forEach(([childKey, childValue]) => addNode(children, childKey, childValue, depth + 1));
          details.append(children);
          if (entries.length > maxChildren) {
            const notice = document.createElement("p");
            notice.className = "json-more";
            notice.textContent = `Showing ${maxChildren} of ${entries.length} entries here; the complete report remains in raw JSON above.`;
            details.append(notice);
          }
        };
        details.addEventListener("toggle", () => { if (details.open) populate(); });
        if (depth === 0) { details.open = true; populate(); }
      } else {
        const leaf = document.createElement("p"); leaf.className = "json-leaf"; leaf.textContent = text(current, "null"); details.append(leaf);
      }
      parent.append(details);
    };
    addNode(root, "report", value, 0);
  }

  function reportSummary(item) {
    if (!item || !item.report) return "Report pending";
    const report = item.report;
    if (report.schema === "banjo.continuum-patch-trial.v1" && Array.isArray(item.inner_cases)) {
      return item.inner_cases.map((entry) => `${text(entry.material_id)}: ${text(entry.status)} (${text(entry.computed_frames)} frames)`).join(" · ");
    }
    const keys = ["fracture_count", "broken_bonds", "elapsed_s", "wall_ms", "mass_kg", "energy_j", "status"];
    const found = keys.find((key) => report[key] !== undefined);
    return found ? `${found}: ${text(report[found])}` : `${Object.keys(report).length} report field(s)`;
  }

  function physicalValidationLabel(item) {
    const value = item && item.report && item.report.physical_response_validated;
    if (value === false) return "Experimental / not validated";
    if (value === true) return "Validated for reported scope";
    return "See reference scope";
  }

  function needsMaterialValidationNote(job) {
    return Boolean(job && Array.isArray(job.cases) && job.cases.some((item) =>
      item && item.report && item.report.physical_response_validated === false));
  }

  function renderResults() {
    const cases = state.job && Array.isArray(state.job.cases) ? state.job.cases : [];
    setText($("results-summary"), cases.length ? `${cases.length} case(s) · ${text(state.job.status)}` : "No completed job");
    const grid = $("case-results"); grid.replaceChildren();
    if (!cases.length) {
      const empty = document.createElement("div"); empty.className = "card empty-results";
      const orb = document.createElement("span"); orb.className = "empty-orb"; orb.setAttribute("aria-hidden", "true"); orb.textContent = "◌";
      const heading = document.createElement("h2"); heading.textContent = "Nothing measured yet";
      const copy = document.createElement("p"); copy.textContent = "Run an experiment to see cases, package data, and report values here.";
      empty.append(orb, heading, copy); grid.append(empty);
    } else cases.forEach((item, index) => {
      const card = document.createElement("article"); card.className = "card case-card";
      const top = document.createElement("div"); top.className = "case-card-top";
      const heading = document.createElement("h2"); heading.textContent = text(item.name, `Case ${index + 1}`);
      const status = document.createElement("span"); const limited = typeof item.status === "string" && item.status.includes("limit"); status.className = `case-status ${item.error || limited ? "error" : ""}`; status.textContent = text(item.status, item.error ? "error" : "ready"); top.append(heading, status);
      const details = document.createElement("div"); details.className = "case-details";
      [["Outcome", reportSummary(item)], ["Physical validation", physicalValidationLabel(item)], ["Package", item.package ? "Generated" : "Pending"], ["Report", item.report ? "Available" : "Pending"]].forEach(([label, value]) => { const row = document.createElement("div"); row.className = "case-detail"; const a = document.createElement("span"); a.textContent = label; const b = document.createElement("strong"); b.textContent = value; row.append(a, b); details.append(row); });
      const actions = document.createElement("div"); actions.className = "case-actions";
      const open = document.createElement("button"); open.type = "button"; open.textContent = item.package && item.package.native_view_mode === "solved_load_sequence_playback" ? "Open solved sequence" : "Open native studio"; open.disabled = !(state.job && state.job.id && canOpenCase(item)); open.addEventListener("click", () => openStudio(index));
      const inspect = document.createElement("button"); inspect.type = "button"; inspect.textContent = "Inspect JSON"; inspect.addEventListener("click", () => { state.selectedCase = index; renderLanguage(); activateTab("language"); });
      actions.append(open, inspect); card.append(top, details, actions); grid.append(card);
    });

    const table = $("compare-table"); const body = table.querySelector("tbody"); body.replaceChildren();
    const reports = cases.map((item) => item.report || {}); const rows = {};
    reports.forEach((report) => Object.assign(rows, flatten(report)));
    const keys = Object.keys(rows).sort().slice(0, 120);
    if (!keys.length) { const row = document.createElement("tr"); const cell = document.createElement("td"); cell.colSpan = 2; cell.className = "muted"; cell.textContent = "No report fields yet."; row.append(cell); body.append(row); return; }
    keys.forEach((key) => { const row = document.createElement("tr"); const field = document.createElement("td"); field.textContent = key; const values = document.createElement("td"); values.textContent = reports.map((report, index) => `${index + 1}: ${text(flatten(report)[key])}`).join("  ·  "); row.append(field, values); body.append(row); });
  }

  async function openStudio(index) {
    if (!state.jobId) return;
    const item = state.job && Array.isArray(state.job.cases) ? state.job.cases[index] : null;
    if (!canOpenCase(item)) { showToast("This result has no native scene to open.", true); return; }
    try {
      await api(`/api/jobs/${encodeURIComponent(state.jobId)}/open`, { method: "POST", headers: { "Content-Type": "application/json", ...tokenHeaders() }, body: JSON.stringify({ case_index: index }) });
      showToast("Native studio opened for this case.");
    } catch (error) { showToast(error.message, true); }
  }

  async function downloadPackage() {
    const item = selectedCase();
    if (!state.jobId || !item) return;
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(state.jobId)}/package/${state.selectedCase}`);
      if (!response.ok) throw new Error(`Download failed (${response.status})`);
      const blob = await response.blob(); const url = URL.createObjectURL(blob);
      const link = document.createElement("a"); link.href = url; link.download = `banjo-case-${state.selectedCase + 1}.json`; link.click(); URL.revokeObjectURL(url);
    } catch (error) { showToast(error.message, true); }
  }

  function addHistory(job) {
    if (!job || job.status !== "complete") return;
    const title = job.plan && (job.plan.goal || job.plan.objective || job.plan.name) || (job.cases && job.cases[0] && job.cases[0].name) || "Completed experiment";
    state.history = state.history.filter((item) => item.id !== job.id);
    state.history.unshift({ id: job.id, title: text(title), cases: Array.isArray(job.cases) ? job.cases.length : 0, timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) });
    state.history = state.history.slice(0, 6); renderHistory();
  }

  function renderHistory() {
    const list = $("history-list"); list.replaceChildren();
    if (!state.history.length) { const p = document.createElement("p"); p.className = "muted"; p.textContent = "Your completed experiments will be collected here."; list.append(p); return; }
    state.history.forEach((item) => { const card = document.createElement("article"); card.className = "history-card"; const h = document.createElement("h3"); h.textContent = item.title; const p = document.createElement("p"); p.textContent = `${item.cases} case(s) · ${item.timestamp}`; const button = document.createElement("button"); button.type = "button"; button.textContent = "Inspect result →"; button.addEventListener("click", async () => {
      if (activeStatuses.has(state.job && state.job.status)) return showToast("Wait for the current experiment to finish.");
      try { const job = await api(`/api/jobs/${encodeURIComponent(item.id)}`); state.job = job; state.jobId = job.id; state.selectedCase = 0; state.latestPlan = job.plan; renderJob(job); renderLanguage(); renderResults(); activateTab("results"); }
      catch (error) { showToast(error.message, true); }
    }); card.append(h, p, button); list.append(card); });
  }

  function stopPolling() { if (state.pollTimer) { window.clearTimeout(state.pollTimer); state.pollTimer = null; } }

  async function pollJob() {
    if (!state.jobId) return;
    try {
      const job = await api(`/api/jobs/${encodeURIComponent(state.jobId)}`);
      state.job = job;
      if (job.status === "complete" && job.plan) state.latestPlan = job.plan;
      renderJob(job); renderLanguage(); renderResults();
      if (terminalStatuses.has(job.status)) { stopPolling(); addHistory(job); const validationNote = needsMaterialValidationNote(job) ? " Material realism is not yet validated." : ""; addMessage("Banjo", text(job.message) + validationNote); if (job.status === "complete") showToast("Experiment complete. Results are ready to inspect."); else showToast(text(job.message, "Experiment did not complete."), true); return; }
      state.pollTimer = window.setTimeout(pollJob, 1000);
    } catch (error) { stopPolling(); renderJob({ id: state.jobId, status: "error", message: error.message, cases: [] }); showToast(error.message, true); }
  }

  async function submitPrompt(event) {
    event.preventDefault();
    const input = $("prompt-input"); const message = input.value.trim();
    if (!message || activeStatuses.has(state.job && state.job.status)) return;
    addMessage("You", message); input.value = "";
    const send = $("send-button"); send.disabled = true; send.classList.add("is-busy");
    try {
      const response = await api("/api/chat", { method: "POST", headers: { "Content-Type": "application/json", ...tokenHeaders() }, body: JSON.stringify({ message, previous_plan: state.followup ? (state.latestPlan || null) : null, request_id: window.crypto && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`, auto_open: $("auto-open").checked }) });
      state.jobId = response && response.job_id; state.job = { id: state.jobId, status: "planning", message: "Planning the experiment…", cases: [] }; state.followup = true;
      addMessage("Banjo", "I’m preparing a bounded experiment plan. I’ll keep the generated package and report visible for review."); renderJob(state.job); renderResults(); stopPolling(); pollJob();
    } catch (error) { send.disabled = false; send.classList.remove("is-busy"); addMessage("Banjo", `The request could not start: ${error.message}`); showToast(error.message, true); }
  }

  function activateTab(name) {
    document.querySelectorAll(".tab").forEach((tab) => { const active = tab.dataset.tab === name; tab.classList.toggle("is-active", active); tab.setAttribute("aria-selected", String(active)); });
    document.querySelectorAll(".tab-panel").forEach((panel) => { const active = panel.id === `panel-${name}`; panel.classList.toggle("is-visible", active); panel.hidden = !active; });
    if (name === "language") renderLanguage(); if (name === "results") renderResults();
  }

  async function loadGoal() {
    try { state.goal = await api("/api/goal"); setText($("goal-markdown"), state.goal && state.goal.markdown, "No project goal returned."); setText($("goal-state"), "Fetched"); }
    catch (error) { setText($("goal-markdown"), `Project goal unavailable: ${error.message}`); setText($("goal-state"), "Unavailable"); }
  }

  async function loadStatus() {
    try { state.status = await api("/api/status"); renderStatus(); }
    catch (error) { state.status = {}; renderStatus(); showToast(`Status unavailable: ${error.message}`, true); }
  }

  function resetExperiment() {
    stopPolling(); state.job = null; state.jobId = null; state.latestPlan = null; state.followup = false; state.messages = []; $("prompt-input").value = ""; renderConversation(); renderJob(null); renderLanguage(); renderResults(); showToast("New experiment ready. Follow-up context cleared.");
  }

  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => activateTab(tab.dataset.tab)));
  $("chat-form").addEventListener("submit", submitPrompt);
  $("new-experiment").addEventListener("click", resetExperiment);
  $("language-case-select").addEventListener("change", (event) => { state.selectedCase = Number(event.target.value); renderLanguage(); });
  $("download-package-language").addEventListener("click", downloadPackage);
  $("prompt-input").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); $("chat-form").requestSubmit(); } });
  renderConversation(); renderHistory(); renderJob(null); renderStatus(); loadStatus(); loadGoal();
})();
