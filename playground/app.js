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
    scene: null,
    sceneMetadata: null,
    playbackCache: new (class extends Map { set(key,value){super.set(key,value);while(this.size>2)this.delete(this.keys().next().value);return this;} })(),
    loadedPlaybackKey: null,
    playbackRequest: 0,
  };

  const $ = (id) => document.getElementById(id);
  const latestJobStorageKey = "banjo.playground.latestJobId";
  const validJobId = (value) => typeof value === "string" && /^[0-9a-f]{32}$/i.test(value);
  function rememberJob(jobId) {
    if (!validJobId(jobId)) return;
    localStorage.setItem(latestJobStorageKey, jobId);
    const url = new URL(window.location.href); url.searchParams.set("job", jobId); history.replaceState(null, "", url);
  }
  function forgetJob() { localStorage.removeItem(latestJobStorageKey); const url=new URL(window.location.href);url.searchParams.delete("job");history.replaceState(null,"",url); }
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
        tag.textContent = capability === "continuum_pressure_reference" ? "Spatial pressure reference" : capability === "dynamic_material_impact" ? "Dynamic material impact" : text(capability);
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
    const nativeReference = state.job?.authoring_source === "native_development_reference";
    setText($("plan-badge"), nativeReference ? "Engine development reference" : "Generated proposal");
    const provenance = document.createElement("p");
    provenance.className = "muted";
    provenance.textContent = nativeReference ? "Native solver reference, not an LLM-generated experiment. Accepted states and limits appear in Results." : "Generated proposal; engine evidence appears in Results.";
    const stats = document.createElement("div");
    stats.className = "plan-summary";
    const experimentNames = {
      drop_test: "Configurable comparative drop",
      scene_test: "Composed scene",
      panel_impact: "Panel impact",
      plate_drop: "Plate drop",
      rigid_drop: "Rigid drop control",
      knife_cut: "Knife / tomato cut",
      custom_objects: "Custom objects",
      thermal_frontier: "Thermal frontier",
      material_state_reference: "Material-state reference",
      continuum_pressure_reference: "Spatial pressure reference",
      dynamic_material_impact: "Dynamic material impact",
      thermal_material_experiment: "Thermal material experiment",
      cohesive_sphere_reference: "Cohesive impact development reference",
      glass_reference: "Published glass reference",
      unsupported: "Unsupported request",
    };
    const sweep = plan.experiment === "thermal_material_experiment" && plan.thermal ? `${plan.thermal.cells.length} cell(s), ${plan.thermal.materials.length} material(s)` : plan.experiment === "dynamic_material_impact" && plan.impact ? `${plan.impact.materials.length} material case(s): ${plan.impact.materials.map(material => material.name || material.material_id).join(", ")}` : plan.drop ? `${plan.drop.heights_m.length} height case(s)` : plan.scene ? `${plan.scene.objects.length} authored object(s)` : Array.isArray(plan.speeds_m_s) && plan.speeds_m_s.length
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
        ? [["Loading", `${plan.pressure?.increments ?? 32} up / down`], ["Setup", `40 × 20 × 40 mm · ${(plan.pressure?.peak_pressure_pa ?? 800000000)/1e6} MPa peak`]]
        : [["Simulated time", plan.duration_s !== undefined ? `${plan.duration_s} s` : undefined]]),
      ["Sweeps / cases", sweep],
      ...(plan.drop ? [["Target dimensions (m)",plan.drop.target_dimensions_m.join(" × ")],["Support",plan.drop.support],["Impact offset (m)",plan.drop.impact_offset_m.join(", ")],["Representation",plan.drop.representation]] : []),
      ...(plan.experiment === "dynamic_material_impact" && plan.impact ? [["Target dimensions (m)", plan.impact.dimensions_m.join(" × ")], ["Sphere radius (m)", plan.impact.sphere.radius_m], ["Impact offset (m)", plan.impact.sphere.offset_xz_m.join(", ")], ["Initial speed (m/s)", plan.impact.sphere.speed_m_s]] : []),
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
    const admission = renderAdmission(job);
    if (admission) $("job-content").append(admission);
    renderPlan(job.plan);
    const send = $("send-button");
    const active = activeStatuses.has(status);
    send.disabled = active;
    send.classList.toggle("is-busy", active);
    setText($("composer-hint"), active ? "A job is running; follow-ups unlock when it finishes." : "Enter to send · Shift+Enter for a new line");
    $("builder-run").disabled = active || builder.busy || !(builder.preview && builder.preview.admissible);
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
    if (item.report?.schema === "banjo.dynamic-material-playback.v1") return false;
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
    if (report.schema === "banjo.dynamic-material-playback.v1" && Array.isArray(report.cases)) {
      return report.cases.map((entry, index) => `${text(entry.material_id)}: ${text(entry.status)} (${entry.frames?.length ?? item.inner_cases?.[index]?.computed_frames ?? "unavailable"} frames)`).join(" · ");
    }
    if (report.schema === "banjo.thermal-experiment-response.v1")
      return `${report.frames?.length ?? 0} accepted frame(s) · ${Number(report.completed_time_s?.toPrecision?.(6) ?? report.completed_time_s)} s · ${thermalTemperature(report.final_ledger?.temperature_min_k)}–${thermalTemperature(report.final_ledger?.temperature_max_k)}`;
    const keys = ["fracture_count", "broken_bonds", "elapsed_s", "wall_ms", "mass_kg", "energy_j", "status"];
    const found = keys.find((key) => report[key] !== undefined);
    return found ? `${found}: ${text(report[found])}` : `${Object.keys(report).length} report field(s)`;
  }

  function physicalValidationLabel(item) {
    const limited = item && Array.isArray(item.inner_cases) && item.inner_cases.filter((entry) => entry.status === "solver_limit");
    if (limited && limited.length) return `Solver limit: ${limited.map((entry) => entry.material_id).join(", ")}`;
    if (item?.report?.schema === "banjo.thermal-experiment-response.v1")
      return "Experimental / not physically validated";
    const value = item && item.report && item.report.physical_response_validated;
    if (value === false) return "Experimental / not validated";
    if (value === true) return "Validated for reported scope";
    return "See reference scope";
  }

  function playbackAvailable(item) { return Boolean(item && item.playback_available); }

  function setPlaybackEnabled(enabled) {
    document.querySelectorAll(".viewer-toolbar button, .viewer-field input, .viewer-field select, .viewer-toggles input").forEach(node => { node.disabled = !enabled; });
  }

  function clearViewer(message = "Select a completed case with playback data.") {
    setPlaybackEnabled(false);
    $("viewer-review").replaceChildren();$("viewer-evidence").textContent="";
    state.playbackRequest += 1; state.scene?.dispose(); state.scene = null; state.sceneMetadata = null; state.loadedPlaybackKey = null;
    const stage = $("viewer-stage"); stage.replaceChildren();
    const empty = document.createElement("div"); empty.className = "viewer-empty"; empty.textContent = message; stage.append(empty);
    $("viewer-play").textContent = "Play"; $("viewer-frame").max = "0"; $("viewer-frame").value = "0"; $("viewer-frame-output").textContent = "0 / 0";
    $("viewer-validity").className = "viewer-validity"; $("viewer-validity").textContent = message; $("viewer-native").disabled = true; $("viewer-custom").replaceChildren();
  }

  function showUnavailablePlayback(job) {
    const failure = job?.failure_detail && typeof job.failure_detail === "object" ? job.failure_detail : {};
    const requirements = (job?.plan?.requirements || []).filter(r => r.status !== "supported");
    const fallback = text(job?.error, text(job?.message, requirements[0]?.reason || "No failure detail was returned."));
    const summary = text(failure.summary, fallback);
    const detail = text(failure.detail, "");
    clearViewer(summary);
    $("viewer-title").textContent = "No recording generated";
    const stage = $("viewer-stage"); stage.replaceChildren();
    const panel = document.createElement("div"); panel.className = "viewer-unavailable";
    const label = document.createElement("strong"); label.textContent = "No recording generated";
    const heading = document.createElement("h2"); heading.textContent = summary; panel.append(label, heading);
    if (detail) { const explanation = document.createElement("p"); explanation.textContent = detail; panel.append(explanation); }
    if (failure.code || failure.scope) { const context = document.createElement("p"); context.className = "muted"; context.textContent = [failure.scope, failure.code].filter(Boolean).join(" · "); panel.append(context); }
    if (requirements.length) {
      const list = document.createElement("ul");
      requirements.forEach(r => { const li = document.createElement("li"); const name = document.createElement("strong"); name.textContent = r.description; const reason = document.createElement("p"); reason.textContent = r.reason; li.append(name, reason); list.append(li); });
      panel.append(list);
    }
    const edit = document.createElement("button"); edit.type = "button"; edit.textContent = "Edit request";
    edit.addEventListener("click", () => { const input = $("prompt-input"); if (!input.value.trim() && job?.request_text) input.value = job.request_text; if (job?.status === "error") state.followup = false; activateTab("experiment"); input.focus(); }); panel.append(edit); stage.append(panel);
    $("viewer-validity").className = "viewer-validity warning";
    $("viewer-validity").textContent = `No recording generated · ${summary}${detail ? ` · ${detail}` : ""}`;
  }

  function validityMessage(item, playback) {
    const report = playback?.schema === "banjo.dynamic-material-playback.v1" ? playback : playback && playback.report || item && item.report || {};
    const unresolved = report.temporal_resolution && report.temporal_resolution.resolved === false;
    const invalid = report.physical_response_validated === false;
    const limited = playback?.status === "solver_limit" || String(item?.status || "").includes("limit");
    const limitedMaterials = (item?.inner_cases || playback?.cases || []).filter((entry) => entry.status === "solver_limit").map((entry) => entry.material_id);
    const materialStatus = (item?.inner_cases || playback?.cases || []).map((entry) => `${text(entry.material_id)}: ${text(entry.status)}`).join(" · ");
    if (playback?.native_schema === "banjo.cohesive-sphere-probe.v1") return ["warning", "Development reference: a launched sphere hits a fictional material. Colors show actual connected components; surfaces follow solved interface separation. The high-speed case stops at the small-rotation model limit. This is not the calibrated glass-drop experiment."];
    if (playback?.schema === "banjo.thermal-experiment-response.v1") return [limited ? "warning" : "ready", limited ? `Thermal solver limit: showing ${text(playback.completed_time_s)} s of ${text(playback.requested_horizon_s)} s and the last accepted cell states. No flame, smoke, airflow, radiation, or mechanical motion is rendered.` : "Accepted fixed-grid thermal states. Color shows temperature; cells do not move. No flame, smoke, airflow, radiation, or mechanical motion is rendered."];
    if (playback?.schema === "banjo.dynamic-material-playback.v1" && invalid) return ["warning", `Dynamic material impact is experimental and not physically validated.${materialStatus ? ` ${materialStatus}.` : ""}`];
    if (limitedMaterials.length) return ["warning", `Solver limit: ${limitedMaterials.join(", ")}. Showing each material's last accepted sampled frame; response remains experimental.${materialStatus ? ` ${materialStatus}.` : ""}`];
    if (limited) return ["warning", `Solver stopped after ${playback?.completed_steps ?? "some"} of ${playback?.requested_steps ?? "requested"} steps. ${text(playback?.error,item?.error || "Last accepted states only.")}${unresolved ? " Temporal resolution is also unresolved." : ""}`];
    if (unresolved) return ["warning", "Temporal resolution is unresolved. Inspect the sampled sequence as experimental evidence."];
    if (invalid) return ["warning", "Material response is not validated for this scope. This is experimental engine output."];
    if (limited) return ["warning", "Solver limit reached. Showing the last accepted sampled frame and preceding computed states."];
    return ["ready", "Computed sampled sequence. No live physics and no interpolation are running in this view."];
  }

  function ensureScene() {
    if (state.scene) return state.scene;
    if (!window.BanjoScene) throw new Error("The local 3D renderer is still loading.");
    state.scene = window.BanjoScene.create($("viewer-stage"), {
      onFrame: ({index, count, frame, continuum, dynamic, thermal}) => { $("viewer-frame").max = String(Math.max(0,count-1)); $("viewer-frame").value=String(index); syncCustomDisplay("frame",count>1?index/(count-1):0); const stopped=dynamic ? frame?.material_states?.filter(x=>x.stopped).map(x=>x.material_id) || [] : []; const shownTime=(dynamic||thermal)&&Number.isFinite(frame?.time_s) ? Number(frame.time_s.toPrecision(9)) : frame?.time_s; const thermalPhase=thermal&&frame?.cells?.some(cell=>cell.phase_change); const thermalDetail=thermal&&frame?.ledger ? thermalPhase ? ` · ${thermalTemperature(frame.ledger.temperature_min_k)}–${thermalTemperature(frame.ledger.temperature_max_k)} · liquid ${thermalMass(frame.ledger.liquid_mass_kg)} · enthalpy ${thermalEnergy(frame.ledger.thermal_enthalpy_j)}` : ` · ${thermalTemperature(frame.ledger.temperature_min_k)}–${thermalTemperature(frame.ledger.temperature_max_k)} · fuel ${thermalMass(frame.ledger.fuel_kg)} · products ${thermalMass(frame.ledger.products_kg)}` : ""; const detail=continuum ? ` · ${text(frame?.phase,"load")} · load ${frame?.load_fraction !== undefined ? `${Math.round(frame.load_fraction*100)}%` : `frame ${index+1}`}` : shownTime !== undefined ? ` · ${text(shownTime)} s${stopped.length ? ` · stopped: ${stopped.join(", ")}` : ""}${thermalDetail}` : ""; $("viewer-frame-output").textContent=`${index+1} / ${count || 0}${detail}`; $("viewer-magnification").disabled=!continuum;if(!continuum)$("viewer-magnification").value="1"; $("viewer-bonds").closest("label").hidden=!!dynamic||!!thermal; },
      onPlayState: (playing) => { $("viewer-play").textContent=playing?"Pause":"Play"; },
      onInspect: (data) => { $("viewer-inspect").textContent = data ? Object.entries(data).filter(([k,v]) => k !== "source" && typeof v !== "object").slice(0,16).map(([k,v])=>`${k}: ${text(v)}`).join(" · ") : "Nothing selected."; },
    });
    return state.scene;
  }

  function renderViewerCaseSelect() {
    const select=$("viewer-case-select"), cases=state.job?.cases || []; select.replaceChildren();
    cases.forEach((item,index)=>{const o=document.createElement("option");o.value=String(index);o.textContent=`${index+1}. ${text(item.name,`Case ${index+1}`)}`;o.disabled=!playbackAvailable(item);select.append(o);});
    select.disabled=!cases.some(playbackAvailable); if(cases.length) select.value=String(state.selectedCase);
  }

  async function rerun(action, value) {
    if (!state.jobId) return;
    try { clearViewer("A new native run is being prepared."); const response=await api(`/api/jobs/${encodeURIComponent(state.jobId)}/rerun`,{method:"POST",headers:{"Content-Type":"application/json",...tokenHeaders()},body:JSON.stringify({case_index:state.selectedCase,action,value,request_id:crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`})}); state.jobId=response.job_id;localStorage.setItem(latestJobStorageKey,state.jobId);state.job={id:state.jobId,status:"planning",message:"Re-running the native engine with the updated validated plan…",cases:[]};activateTab("experiment");renderJob(state.job);pollJob(); }
    catch(error){showToast(error.message,true);}
  }

  function renderCustomControls(ui) {
    const root=$("viewer-custom");root.replaceChildren(); if(!ui || !Array.isArray(ui.controls) || !ui.controls.length)return;
    const heading=document.createElement("h3");heading.textContent=text(ui.title,"Experiment controls");root.append(heading);
    const formatValue=(action,value)=>{const n=Number(value);if(action==="pressure_pa")return `${(n/1e6).toLocaleString(undefined,{maximumFractionDigits:3})} MPa`;if(action==="height_m")return `${n.toLocaleString()} m`;if(action==="speed_m_s")return `${n.toLocaleString()} m/s`;if(action==="playback_speed"||action==="magnification")return `${n.toLocaleString()}×`;if(action==="frame")return `${Math.round(n*100)}%`;return text(value);};
    const displayAction=(action,value)=>{if(action==="playback_speed"){$("viewer-speed").value=String(value);state.scene?.setSpeed(value);}if(action==="magnification"){$("viewer-magnification").value=String(value);state.scene?.setMagnification(value);}if(action==="frame"){$("viewer-frame").value=String(Math.round(value*Math.max(0,(state.scene?.frameCount||1)-1)));state.scene?.setFrame(value*Math.max(0,(state.scene?.frameCount||1)-1));}if(action==="components"){$("viewer-components").checked=Boolean(value);state.scene?.showComponents(value);}if(action==="reference"){$("viewer-reference").checked=Boolean(value);state.scene?.showReference(value);}};
    ui.controls.forEach((control)=>{ const row=document.createElement("div");row.className="custom-control";row.dataset.action=control.action; const label=document.createElement("label");label.textContent=text(control.label,control.id);row.append(label); const local={play_pause:()=>$("viewer-play").click(),reset:()=>$("viewer-reset").click(),step_forward:()=>$("viewer-forward").click(),step_back:()=>$("viewer-back").click(),components:()=>$("viewer-components").click(),reference:()=>$("viewer-reference").click()};
      if(control.kind==="button"){const b=document.createElement("button");b.type="button";b.textContent=text(control.label,control.id);b.addEventListener("click",()=>{if(local[control.action])local[control.action]();else rerun(control.action,control.value);});row.append(b);} else {const input=document.createElement("input");input.type=control.kind==="toggle"?"checkbox":"range";if(input.type==="range"){input.min=control.min;input.max=control.max;input.step=control.step;input.value=control.value;}else input.checked=Boolean(control.value);const output=document.createElement("output");output.textContent=input.type==="checkbox"?(input.checked?"On":"Off"):formatValue(control.action,input.value);row.append(output,input);const update=()=>{const value=input.type==="checkbox"?input.checked:Number(input.value);output.textContent=input.type==="checkbox"?(value?"On":"Off"):formatValue(control.action,value);displayAction(control.action,value);};input.addEventListener("input",update);if(["height_m","speed_m_s","pressure_pa"].includes(control.action)){const apply=document.createElement("button");apply.type="button";apply.textContent="Apply and rerun";apply.title="Runs the native engine with a new validated plan.";apply.addEventListener("click",()=>rerun(control.action,Number(input.value)));row.append(apply);}else displayAction(control.action,input.type==="checkbox"?input.checked:Number(input.value));} root.append(row); });
  }

  function syncCustomDisplay(action, value) {
    const row=[...document.querySelectorAll("#viewer-custom .custom-control")].find(
      (item)=>item.dataset.action===action);
    if(!row)return;
    const input=row.querySelector("input"), output=row.querySelector("output");
    if(!input||!output)return;
    if(input.type==="checkbox"){input.checked=Boolean(value);output.textContent=input.checked?"On":"Off";return;}
    input.value=String(value);
    const numeric=Number(value);
    output.textContent=action==="frame"?`${Math.round(numeric*100)}%`:
      action==="playback_speed"?`${numeric.toLocaleString()}×`:text(value);
  }

  function thermalTemperature(value) {
    return Number.isFinite(value) ? `${value.toFixed(1)} K` : "—";
  }

  function thermalMass(value) {
    if (!Number.isFinite(value)) return "—";
    if (Math.abs(value) < .01) return `${Number((value * 1e6).toPrecision(3))} mg`;
    return `${Number(value.toPrecision(3))} kg`;
  }

  function thermalEnergy(value) {
    return Number.isFinite(value) ? `${Number(value.toPrecision(4))} J` : "—";
  }

  function renderThermalLegend(metadata) {
    if (!metadata?.thermal || !metadata.thermalRange) return;
    const root=$("viewer-custom"), heading=document.createElement("h3");
    heading.textContent="Temperature color legend"; root.append(heading);
    const row=document.createElement("div"); row.className="custom-control";
    const low=document.createElement("span"), scale=document.createElement("span"), high=document.createElement("span");
    low.textContent=`Cool · ${thermalTemperature(metadata.thermalRange.minimum_temperature_k)}`;
    high.textContent=`Hot · ${thermalTemperature(metadata.thermalRange.maximum_temperature_k)}`;
    scale.textContent="blue → cyan → yellow → red";
    scale.setAttribute("aria-label","Temperature increases from blue through cyan and yellow to red");
    row.append(low,scale,high); root.append(row);
  }

  async function inspectEvidence(analyze=false) {
    const jobId=state.jobId, index=state.selectedCase, key=`${jobId}:${index}`;
    if(!jobId)return;
    const button=$(analyze ? "viewer-analyze" : "viewer-evidence-button");button.disabled=true;const label=button.textContent;button.textContent=analyze ? "Analyzing…" : "Loading evidence…";
    try {
      const result=await api(`/api/jobs/${encodeURIComponent(jobId)}/${analyze ? "analyze" : `diagnostics/${index}`}`, analyze ? {method:"POST",headers:{"Content-Type":"application/json",...tokenHeaders()},body:JSON.stringify({case_index:index})} : {});
      if(key!==`${state.jobId}:${state.selectedCase}`)return;
      if(analyze){renderReview(result);}
      else {$("viewer-evidence").textContent=JSON.stringify(result,null,2);$("viewer-evidence-details").open=true;if(result.llm_review)renderReview(result.llm_review);}
    } catch(error){showToast(error.message,true);}
    finally {if(key===`${state.jobId}:${state.selectedCase}`){button.disabled=false;button.textContent=label;}}
  }

  function renderReview(result) {
    const root=$("viewer-review");root.replaceChildren();const review=result.review;
    const title=document.createElement("strong");title.textContent=`GPT interpretation: ${review.verdict.replaceAll("_"," ")}`;root.append(title);
    const summary=document.createElement("p");summary.textContent=review.summary;root.append(summary);
    for(const [label,items] of [["Findings",review.findings],["Next steps",review.next_steps]]){const heading=document.createElement("strong");heading.textContent=label;root.append(heading);const list=document.createElement("ul");for(const item of items){const li=document.createElement("li");li.textContent=item;list.append(li);}root.append(list);}
  }

  async function loadPlayback(index=state.selectedCase, auto=false) {
    $("viewer-analyze").textContent="Analyze this run with GPT";$("viewer-evidence-button").textContent="View measured evidence";
    const item=state.job?.cases?.[index]; if(!state.jobId || !playbackAvailable(item)){if(auto)return;showToast("This case has no embedded playback data.",true);return;}
    $("viewer-review").replaceChildren();$("viewer-evidence").textContent="";$("viewer-evidence-details").open=false;state.selectedCase=index;renderLanguage();renderViewerCaseSelect();activateTab("viewer");$("viewer-title").textContent=text(state.job?.plan?.ui?.title,item.name || "Computed sequence.");
    const key=`${state.jobId}:${index}`, request=++state.playbackRequest;
    try { let playback=state.playbackCache.get(key);if(!playback){playback=await api(`/api/jobs/${encodeURIComponent(state.jobId)}/playback/${index}`);state.playbackCache.set(key,playback);}if(request!==state.playbackRequest||key!==`${state.jobId}:${state.selectedCase}`)return; setPlaybackEnabled(true); if(state.loadedPlaybackKey!==key){state.sceneMetadata=ensureScene().load(playback);if(playback.native_schema === "banjo.cohesive-sphere-probe.v1"){$("viewer-speed").value="0.001";state.scene.setSpeed(0.001);}state.loadedPlaybackKey=key;} const [kind,message]=validityMessage(item,playback), validity=$("viewer-validity");validity.className=`viewer-validity ${kind}`;validity.textContent=message;renderCustomControls(state.job?.plan?.ui);renderThermalLegend(state.sceneMetadata);$("viewer-native").disabled=!canOpenCase(item); }
    catch(error){state.scene?.dispose();state.scene=null;state.sceneMetadata=null;$("viewer-stage").replaceChildren();const p=document.createElement("p");p.className="viewer-error";p.textContent=error.message;$("viewer-stage").append(p);state.loadedPlaybackKey=null;showToast(error.message,true);}
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
      const open = document.createElement("button"); open.type = "button"; open.textContent = playbackAvailable(item) ? "View 3D playback" : "Open native studio"; open.disabled = !(state.job && state.job.id && (playbackAvailable(item) || canOpenCase(item))); open.addEventListener("click", () => playbackAvailable(item) ? loadPlayback(index) : openStudio(index));
      const inspect = document.createElement("button"); inspect.type = "button"; inspect.textContent = "Inspect JSON"; inspect.addEventListener("click", () => { state.selectedCase = index; renderLanguage(); activateTab("language"); });
      const control = document.createElement("button"); control.type = "button"; control.textContent = "Run at-rest control";
      control.title = "Re-run this exact scene with no gravity, no ground, no striker and zero velocity. Anything it reports was manufactured by the solver.";
      control.disabled = !(state.job && state.job.id && item.package);
      control.addEventListener("click", () => runAtRestControl(index, control));
      actions.append(open, inspect, control); card.append(top, details, trustPanel(item), actions); grid.append(card);
    });

    const table = $("compare-table"); const body = table.querySelector("tbody"); body.replaceChildren();
    const reports = cases.map((item) => item.report || {}); const rows = {};
    reports.forEach((report) => Object.assign(rows, flatten(report)));
    const keys = Object.keys(rows).sort().slice(0, 120);
    if (!keys.length) { const row = document.createElement("tr"); const cell = document.createElement("td"); cell.colSpan = 2; cell.className = "muted"; cell.textContent = "No report fields yet."; row.append(cell); body.append(row); return; }
    keys.forEach((key) => { const row = document.createElement("tr"); const field = document.createElement("td"); field.textContent = key; const values = document.createElement("td"); values.textContent = reports.map((report, index) => `${index + 1}: ${text(flatten(report)[key])}`).join("  ·  "); row.append(field, values); body.append(row); });
  }

  function trustPanel(item) {
    const box = document.createElement("div"); box.className = "trust-panel";
    const resolution = item.trust && item.trust.resolution;
    const row = (label, value, kind) => {
      const line = document.createElement("div"); line.className = `trust-row${kind ? ` trust-${kind}` : ""}`;
      const a = document.createElement("span"); a.textContent = label;
      const b = document.createElement("strong"); b.textContent = value;
      line.append(a, b); box.append(line); return line;
    };
    if (resolution && Number.isFinite(resolution.shortfall)) {
      const factor = resolution.shortfall;
      const kind = factor <= 1 ? "ok" : factor < 10 ? "warn" : "bad";
      row("Timestep vs. required", factor <= 1
        ? `resolved (${factor.toFixed(2)}x)`
        : `${factor >= 100 ? Math.round(factor) : factor.toFixed(1)}x too coarse`, kind);
      row("Step used / needed", `${resolution.used_dt_s.toExponential(3)} s / ${resolution.required_dt_s.toExponential(3)} s`);
      if (resolution.reachable_in_schema === false) {
        row("Schema floor", "1/4800 s is still too coarse for this material", "bad");
      }
    } else {
      row("Timestep vs. required", "not reported for this case");
    }
    const stepping = item.trust && item.trust.substepping;
    if (stepping && Number.isFinite(stepping.substeps)) {
      const limited = stepping.limited_by_budget === true;
      row("Solver substeps / tick", limited
        ? `${stepping.substeps} of ${stepping.required_substeps} needed`
        : `${stepping.substeps} (fully resolved)`, limited ? "bad" : "ok");
      if (limited) row("Under-resolved", "material state is not trustworthy", "bad");
    }
    if (stepping && stepping.refused_bond_updates > 0) {
      row("Refused bond updates", `${stepping.refused_bond_updates} (solver residual too large)`, "bad");
    }
    const energy = (item.trust && item.trust.energy) || {};
    if (Number.isFinite(energy.change_fraction_of_initial)) {
      const pct = energy.change_fraction_of_initial * 100;
      row("Unexplained energy change", `${pct.toFixed(1)}% of initial`, pct > 5 ? "bad" : pct > 1 ? "warn" : "ok");
    }
    const cost = item.cost;
    if (cost && Number.isFinite(cost.estimated_wall_s)) {
      // An estimate nobody checks is a guess. Show it against what it predicted.
      row("Cost estimate", Number.isFinite(cost.measured_wall_s)
        ? `${Math.round(cost.estimated_wall_s)} s predicted, ${Math.round(cost.measured_wall_s)} s measured (${cost.wall_error >= 0 ? "+" : ""}${Math.round(cost.wall_error * 100)}%)`
        : `${Math.round(cost.estimated_wall_s)} s predicted`,
        Number.isFinite(cost.wall_error) && Math.abs(cost.wall_error) <= .35 ? "ok" : Number.isFinite(cost.wall_error) ? "warn" : "");
      if (Number.isFinite(cost.realtime_ratio)) {
        // The owner's rule: wall time within 1.1x of the simulated interaction.
        row("Realtime", `${cost.realtime_ratio.toFixed(2)}x of ${cost.simulated_s.toFixed(3)} s simulated (limit ${cost.realtime_limit}x)`,
          cost.realtime_ratio <= cost.realtime_limit ? "ok" : "bad");
      }
      if (Number.isFinite(cost.measured_substeps_per_tick)) {
        row("Substeps predicted / used", `${cost.substeps_per_host_tick} / ${cost.measured_substeps_per_tick}`,
          cost.substeps_per_host_tick === cost.measured_substeps_per_tick ? "ok" : "bad");
      }
    }
    // Imported recordings (the fracture lanes run outside the playground) carry
    // their timing in the case report rather than in a cost estimate. Show the
    // same rule against the same limit, and the fracture window on its own,
    // because a short window inside seconds of settling can pass the rule
    // while being hundreds of times slower than realtime itself.
    const report = item.report || {};
    const realtime = report.realtime || {};
    // Lanes name their totals differently (the GPU lane writes them at the top
    // of its report); the most inclusive figure wins, because recording time
    // is time the owner waits too.
    const pick = (...values) => values.find(Number.isFinite);
    const ratio = pick(realtime.ratio, realtime.ratio_with_recording, realtime.ratio_pipeline, report.realtime_ratio);
    if (!(cost && Number.isFinite(cost.realtime_ratio)) && Number.isFinite(ratio)) {
      const limit = Number.isFinite(realtime.limit) ? realtime.limit : 1.1;
      const simulatedS = pick(realtime.simulated_s, report.simulated_total_s);
      const simulated = Number.isFinite(simulatedS) ? `${simulatedS.toFixed(3)} s simulated` : "simulated time";
      const wallS = pick(realtime.compute_wall_s, realtime.wall_with_recording_s, realtime.wall_pipeline_s, report.wall_total_s);
      const wall = Number.isFinite(wallS) ? `${wallS.toFixed(3)} s wall, ` : "";
      row("Realtime", `${wall}${ratio.toFixed(2)}x of ${simulated} (limit ${limit}x)`,
        ratio <= limit ? "ok" : "bad");
      const stageTimes = realtime.stages_s || report.phase_seconds;
      if (stageTimes && typeof stageTimes === "object") {
        const stages = Object.entries(stageTimes).filter(([, v]) => Number.isFinite(v))
          .map(([k, v]) => `${k} ${v.toFixed(3)} s`).join(", ");
        if (stages) row("Wall by stage", stages, "");
      }
      if (Number.isFinite(realtime.fracture_window_ratio)) {
        const window = Number.isFinite(realtime.window_simulated_s) ? ` of the ${(realtime.window_simulated_s * 1000).toFixed(1)} ms fracture window` : " over the fracture window";
        row("Fracture window", `${realtime.fracture_window_ratio.toFixed(0)}x realtime${window}`,
          realtime.fracture_window_ratio <= limit ? "ok" : "warn");
      }
    }
    const control = item.at_rest_control;
    if (control) {
      row("At-rest control", control.clean ? "clean" : "CONTAMINATED", control.clean ? "ok" : "bad");
      const note = document.createElement("p"); note.className = "trust-note"; note.textContent = control.summary; box.append(note);
    } else {
      const note = document.createElement("p"); note.className = "trust-note muted";
      note.textContent = "Run the at-rest control to find out whether this result comes from the impact or from the lattice shaking itself apart.";
      box.append(note);
    }
    return box;
  }

  async function runAtRestControl(index, button) {
    if (!state.jobId) return;
    const label = button.textContent;
    button.disabled = true; button.textContent = "Running control...";
    try {
      const verdict = await api(`/api/jobs/${encodeURIComponent(state.jobId)}/control`, {
        method: "POST", headers: { "Content-Type": "application/json", ...tokenHeaders() },
        body: JSON.stringify({ case_index: index }),
      });
      const item = state.job && Array.isArray(state.job.cases) ? state.job.cases[index] : null;
      if (item) item.at_rest_control = verdict;
      renderResults();
      showToast(verdict.clean ? "At-rest control is clean." : "At-rest control is CONTAMINATED - see the case card.", !verdict.clean);
    } catch (error) {
      showToast(error.message, true);
      button.disabled = false; button.textContent = label;
    }
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
      try { const job = await api(`/api/jobs/${encodeURIComponent(item.id)}`); state.job = job; state.jobId = job.id; localStorage.setItem(latestJobStorageKey,state.jobId); state.selectedCase = Math.max(0,job.cases?.findIndex(playbackAvailable) ?? 0); state.latestPlan = job.plan; renderJob(job); renderLanguage(); renderResults(); if(job.cases?.some(playbackAvailable))loadPlayback(state.selectedCase,true);else { clearViewer("This result has no embedded playback."); activateTab("results"); } }
      catch (error) { showToast(error.message, true); }
    }); card.append(h, p, button); list.append(card); });
  }

  function stopPolling() { if (state.pollTimer) { window.clearTimeout(state.pollTimer); state.pollTimer = null; } }

  async function pollJob() {
    if (!state.jobId) return;
    try {
      const job = await api(`/api/jobs/${encodeURIComponent(state.jobId)}`);
      state.job = job;
      rememberJob(job.id);
      if (job.status === "complete" && job.plan) state.latestPlan = job.plan;
      renderJob(job); renderLanguage(); renderResults();
      if (terminalStatuses.has(job.status)) { stopPolling(); addHistory(job); const validationNote = needsMaterialValidationNote(job) ? " Material realism is not yet validated." : ""; addMessage("Banjo", text(job.message) + validationNote); const playable=job.cases?.findIndex(playbackAvailable) ?? -1;if(job.status==="complete" && playable>=0 && $("auto-open").checked)loadPlayback(playable,true);else if (job.status === "complete") { if(playable<0)clearViewer("This completed result has no embedded playback."); showToast("Experiment complete. Results are ready to inspect."); } else { showUnavailablePlayback(job); if ($("auto-open").checked) activateTab("viewer"); showToast(text(job.message, "Experiment did not complete."), true); } return; }
      state.pollTimer = window.setTimeout(pollJob, 1000);
    } catch (error) { stopPolling(); clearViewer("The latest request did not produce playback geometry."); renderJob({ id: state.jobId, status: "error", message: error.message, cases: [] }); showToast(error.message, true); }
  }

  async function submitPrompt(event) {
    event.preventDefault();
    const input = $("prompt-input"); const message = input.value.trim();
    if (!message || activeStatuses.has(state.job && state.job.status)) return;
    addMessage("You", message); input.value = "";
    clearViewer("A new experiment is being prepared.");
    const send = $("send-button"); send.disabled = true; send.classList.add("is-busy");
    try {
      const response = await api("/api/chat", { method: "POST", headers: { "Content-Type": "application/json", ...tokenHeaders() }, body: JSON.stringify({ message, previous_plan: state.followup ? (state.latestPlan || null) : null, request_id: window.crypto && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`, auto_open: false }) });
      state.jobId = response && response.job_id; if(state.jobId)localStorage.setItem(latestJobStorageKey,state.jobId); state.job = { id: state.jobId, status: "planning", message: "Planning the experiment…", cases: [] }; state.followup = true;
      addMessage("Banjo", "I’m preparing a bounded experiment plan. I’ll keep the generated package and report visible for review."); renderJob(state.job); renderResults(); stopPolling(); pollJob();
    } catch (error) { send.disabled = false; send.classList.remove("is-busy"); addMessage("Banjo", `The request could not start: ${error.message}`); showToast(error.message, true); }
  }

  // ---------------------------------------------------------------------
  // Builder panel: the admissible parameter space, checked by the server.
  //
  // Every number shown here comes from /api/builder/preview rather than from a
  // copy of the rules in this file, so the panel cannot drift away from what
  // the engine enforces, and the Run button is enabled only for a setup the
  // same code path has already accepted.
  // ---------------------------------------------------------------------
  const builder = { meta: null, spec: null, preview: null, timer: null, pending: 0, busy: false };
  const mm = (metres) => Math.round(metres * 1000 * 1000) / 1000;

  function builderInputs() {
    return {
      material: $("b-material").value,
      dimensions_m: [Number($("b-dx").value) / 1000, Number($("b-dy").value) / 1000, Number($("b-dz").value) / 1000],
      resolution: [Number($("b-rx").value), Number($("b-ry").value), Number($("b-rz").value)],
      support: $("b-support").value,
      projectile: $("b-projectile").value,
      projectile_size_m: Number($("b-psize").value) / 1000,
      impact_speed_m_s: Number($("b-speed").value),
      impact_offset_m: [Number($("b-ox").value) / 1000, Number($("b-oz").value) / 1000],
      duration_s: Number($("b-duration").value) / 1000,
      tick_rate_hz: Number($("b-tick").value),
    };
  }

  function writeBuilder(spec) {
    $("b-material").value = spec.material;
    $("b-support").value = spec.support;
    ["b-dx", "b-dy", "b-dz"].forEach((id, i) => { $(id).value = String(mm(spec.dimensions_m[i])); });
    ["b-rx", "b-ry", "b-rz"].forEach((id, i) => { $(id).value = String(spec.resolution[i]); });
    $("b-projectile").value = spec.projectile;
    $("b-psize").value = String(mm(spec.projectile_size_m));
    $("b-speed").value = String(spec.impact_speed_m_s);
    $("b-ox").value = String(mm(spec.impact_offset_m[0]));
    $("b-oz").value = String(mm(spec.impact_offset_m[1]));
    $("b-duration").value = String(Math.round(spec.duration_s * 1000));
    $("b-tick").value = String(spec.tick_rate_hz);
    $("b-speed-out").textContent = `${Number(spec.impact_speed_m_s).toLocaleString()} m/s`;
    $("b-duration-out").textContent = `${Math.round(spec.duration_s * 1000)} ms`;
  }

  async function initBuilder() {
    try { builder.meta = await api("/api/builder"); }
    catch (error) { setText($("builder-verdict"), `Builder unavailable: ${error.message}`); return; }
    const materials = $("b-material"); materials.replaceChildren();
    builder.meta.materials.forEach((id) => { const o = document.createElement("option"); o.value = id; o.textContent = id; materials.append(o); });
    const ticks = $("b-tick"); ticks.replaceChildren();
    builder.meta.tick_rates_hz.forEach((hz) => { const o = document.createElement("option"); o.value = String(hz); o.textContent = `${hz} Hz`; ticks.append(o); });
    const limits = builder.meta.limits || {};
    const rows = [
      ["Cells per axis", `${limits.resolution_per_axis?.[0]} to ${limits.resolution_per_axis?.[1]}`,
        "Bounded by the engine's own resolution check."],
      ["Cell aspect ratio", `${limits.cell_aspect_ratio}:1 at most`,
        "Each cell collides as a sphere of radius 0.49 x the smallest spacing while carrying the whole box's mass. Cubic cells cover 98% of the cell and neighbours just touch; stretched cells let fragments pass through each other."],
      ["Face : thickness", `${limits.slenderness_face_over_thickness}:1 at most`,
        `A consequence of the two rules above: 16 cells on the long axis, 2 on the short one, times the ${limits.cell_aspect_ratio}:1 cell tolerance (${limits.slenderness_with_strictly_cubic_cells}:1 if you want strictly cubic cells). A real windowpane is 30:1 or more and cannot be expressed here.`],
      ["Cells", `${limits.object_cells} per object, ${limits.world_cells} per world, ${limits.playground_cells} here`,
        "Hard engine budgets; the playground keeps a tighter one."],
      ["Smallest cell", `${(limits.minimum_cell_spacing_m * 1000).toFixed(2)} mm spacing`,
        "Below this the collision proxy drops under the engine's 1 mm floor."],
      ["Substeps per tick", `${limits.maximum_substeps_per_tick} at most`,
        "The solver runs the lattice on its own stability clock. Cost is set by the smallest cell: halving a spacing roughly doubles the run."],
    ];
    const root = $("builder-limits"); root.replaceChildren();
    rows.forEach(([label, value, why]) => {
      const row = document.createElement("div"); row.className = "limit-row";
      const head = document.createElement("div"); head.className = "limit-head";
      const a = document.createElement("span"); a.textContent = label;
      const b = document.createElement("strong"); b.textContent = value;
      head.append(a, b);
      const p = document.createElement("p"); p.textContent = why;
      row.append(head, p); root.append(row);
    });
    writeBuilder(builder.meta.default);
    document.querySelectorAll("#builder-controls input, #builder-controls select")
      .forEach((node) => node.addEventListener("input", scheduleBuilderPreview));
    $("builder-reset").addEventListener("click", () => { writeBuilder(builder.meta.default); scheduleBuilderPreview(); });
    $("builder-run").addEventListener("click", runBuilder);
    scheduleBuilderPreview();
  }

  function scheduleBuilderPreview() {
    $("b-speed-out").textContent = `${Number($("b-speed").value).toLocaleString()} m/s`;
    $("b-duration-out").textContent = `${$("b-duration").value} ms`;
    setText($("builder-badge"), "Checking");
    $("builder-run").disabled = true;
    window.clearTimeout(builder.timer);
    builder.timer = window.setTimeout(previewBuilder, 180);
  }

  async function previewBuilder() {
    const request = ++builder.pending;
    let spec;
    try { spec = builderInputs(); } catch { return; }
    try {
      const preview = await api("/api/builder/preview", { method: "POST", headers: { "Content-Type": "application/json", ...tokenHeaders() }, body: JSON.stringify(spec) });
      if (request !== builder.pending) return;
      builder.spec = preview.spec; builder.preview = preview;
      renderBuilderPreview(preview);
    } catch (error) {
      if (request !== builder.pending) return;
      builder.preview = null;
      setText($("builder-badge"), "Out of bounds");
      $("builder-verdict").className = "builder-verdict bad";
      setText($("builder-verdict"), error.message);
      $("builder-repair").replaceChildren();
      $("builder-metrics").replaceChildren();
      setText($("builder-package"), "No admissible package yet.");
    }
  }

  function metricRow(root, label, value, kind) {
    const row = document.createElement("div"); row.className = `metric-row${kind ? ` metric-${kind}` : ""}`;
    const a = document.createElement("span"); a.textContent = label;
    const b = document.createElement("strong"); b.textContent = value;
    row.append(a, b); root.append(row); return row;
  }

  function renderBuilderPreview(preview) {
    const geometry = preview.geometry, cost = preview.cost;
    const verdict = $("builder-verdict"); verdict.replaceChildren();
    setText($("builder-badge"), preview.admissible ? "Admissible" : "Refused");
    verdict.className = `builder-verdict ${preview.admissible ? "ok" : "bad"}`;
    if (preview.admissible) {
      const line = document.createElement("p");
      line.textContent = `The engine will accept this scene: ${geometry.cells} cells of ${geometry.spacing_mm.map((v) => `${v}`).join(" x ")} mm at ${geometry.aspect_ratio.toFixed(2)}:1, collision proxies ${(geometry.collision_radius_m * 1000).toFixed(2)} mm across.`;
      verdict.append(line);
      (preview.notes || []).forEach((note) => { const p = document.createElement("p"); p.className = "verdict-note"; p.textContent = note.message; verdict.append(p); });
    } else {
      preview.problems.forEach((problem) => {
        const p = document.createElement("p"); const tag = document.createElement("strong");
        tag.textContent = `${problem.limit}: `; p.append(tag, document.createTextNode(problem.message)); verdict.append(p);
      });
    }
    const repair = $("builder-repair"); repair.replaceChildren();
    if (!preview.admissible && preview.repair && preview.repair.resolution) {
      const p = document.createElement("p");
      p.textContent = `Nearest admissible mesh: ${JSON.stringify(preview.repair.resolution)} (${preview.repair.cost.network_cells} cells, about ${preview.repair.cost.estimated_wall_text}).`;
      const apply = document.createElement("button"); apply.type = "button"; apply.className = "quiet-button";
      apply.textContent = "Use this resolution";
      apply.addEventListener("click", () => {
        ["b-rx", "b-ry", "b-rz"].forEach((id, i) => { $(id).value = String(preview.repair.resolution[i]); });
        scheduleBuilderPreview();
      });
      repair.append(p, apply);
    } else if (!preview.admissible && preview.repair && preview.repair.dimensions) {
      const d = preview.repair.dimensions;
      const p = document.createElement("p");
      p.textContent = `This object is ${d.slenderness.toFixed(1)}:1 face to thickness and no mesh in range can build it. The nearest buildable versions keep this face at ${(d.thicken_to_m * 1000).toFixed(0)} mm thick, or keep this thickness with a ${(d.shrink_face_to_m * 1000).toFixed(0)} mm face.`;
      const thicken = document.createElement("button"); thicken.type = "button"; thicken.className = "quiet-button";
      thicken.textContent = `Thicken to ${(d.thicken_to_m * 1000).toFixed(0)} mm`;
      thicken.addEventListener("click", () => { $("b-dz").value = String(Math.ceil(d.thicken_to_m * 1000)); scheduleBuilderPreview(); });
      repair.append(p, thicken);
    }
    const metrics = $("builder-metrics"); metrics.replaceChildren();
    metricRow(metrics, "Cells", `${geometry.cells}`, geometry.cells_ok ? "ok" : "bad");
    metricRow(metrics, "Cell size", `${geometry.spacing_mm.join(" x ")} mm`);
    metricRow(metrics, "Cell aspect", `${geometry.aspect_ratio.toFixed(2)}:1`, geometry.cubic ? "ok" : "bad");
    metricRow(metrics, "Collision coverage", `${Math.round(geometry.collision_coverage * 100)}% of the widest side`, geometry.cubic ? "ok" : "bad");
    metricRow(metrics, "Face : thickness", `${geometry.slenderness.toFixed(1)}:1`,
      geometry.slenderness <= (builder.meta?.limits?.slenderness_face_over_thickness ?? 16) ? "ok" : "bad");
    if (cost) {
      metricRow(metrics, "Substeps per tick", `${cost.substeps_per_host_tick}${cost.limited_by_budget ? ` of ${cost.required_substeps} needed` : ""}`, cost.limited_by_budget ? "bad" : "ok");
      metricRow(metrics, "Host ticks", `${cost.steps} (${(cost.simulated_s * 1000).toFixed(0)} ms simulated)`);
      metricRow(metrics, "Internal solves", cost.total_substeps.toLocaleString());
      metricRow(metrics, "Estimated wall time", `${cost.estimated_wall_text} (${Math.round(cost.estimated_wall_low_s)}–${Math.round(cost.estimated_wall_high_s)} s)`,
        cost.estimated_wall_s > 900 ? "bad" : cost.estimated_wall_s > 240 ? "warn" : "ok");
      metricRow(metrics, "Recording size", `${cost.estimated_recording_mb.toFixed(1)} MB`, cost.recording_over_budget ? "bad" : "ok");
      setText($("builder-cost-badge"), cost.estimated_wall_text);
      setText($("builder-cost-basis"), cost.basis);
    } else {
      setText($("builder-cost-badge"), "—");
      setText($("builder-cost-basis"), "Cost is computed once the setup is admissible.");
    }
    setText($("builder-package"), preview.package ? pretty(preview.package) : "No admissible package yet.");
    $("builder-run").disabled = !preview.admissible || builder.busy || activeStatuses.has(state.job && state.job.status);
  }

  async function runBuilder() {
    if (!builder.preview || !builder.preview.admissible) return;
    const button = $("builder-run"); button.disabled = true; builder.busy = true;
    const cost = builder.preview.cost;
    if (cost && cost.estimated_wall_s > 240 &&
        !window.confirm(`This scene is estimated at ${cost.estimated_wall_text} of computation (${cost.total_substeps.toLocaleString()} internal solves). Run it?`)) {
      builder.busy = false; button.disabled = false; return;
    }
    try {
      clearViewer("The authored package is being recorded.");
      const response = await api("/api/packages/run", { method: "POST", headers: { "Content-Type": "application/json", ...tokenHeaders() }, body: JSON.stringify({ builder: builder.spec, steps: builder.preview.steps, request_id: crypto.randomUUID?.() || `${Date.now()}-${Math.random()}` }) });
      state.jobId = response.job_id; rememberJob(state.jobId);
      state.job = { id: state.jobId, status: "running", message: `Recording the authored package; estimated ${cost ? cost.estimated_wall_text : "unknown"}.`, cases: [] };
      state.selectedCase = 0; state.followup = false;
      addMessage("You", `Builder: ${builder.preview.package.name}`);
      activateTab("experiment"); renderJob(state.job); stopPolling(); pollJob();
    } catch (error) {
      showToast(error.message, true);
      setText($("builder-verdict"), error.message);
      $("builder-verdict").className = "builder-verdict bad";
    } finally { builder.busy = false; button.disabled = !(builder.preview && builder.preview.admissible); }
  }

  function renderAdmission(job) {
    const notes = job?.admission?.notes || [];
    const cost = job?.admission?.cost;
    if (!notes.length && !cost) return null;
    const box = document.createElement("div"); box.className = "admission-panel";
    if (cost) {
      const line = document.createElement("div"); line.className = "admission-cost";
      const a = document.createElement("span"); a.textContent = "Estimated computation";
      const b = document.createElement("strong");
      b.textContent = `${cost.estimated_wall_text} · up to ${cost.worst_substeps_per_tick} internal solves per tick`;
      line.append(a, b); box.append(line);
    }
    notes.forEach((note) => {
      const p = document.createElement("p"); p.className = "admission-note";
      const tag = document.createElement("strong"); tag.textContent = `${note.action} · ${note.limit}: `;
      p.append(tag, document.createTextNode(note.message)); box.append(p);
    });
    return box;
  }

  function activateTab(name) {
    document.querySelectorAll(".tab").forEach((tab) => { const active = tab.dataset.tab === name; tab.classList.toggle("is-active", active); tab.setAttribute("aria-selected", String(active)); });
    document.querySelectorAll(".tab-panel").forEach((panel) => { const active = panel.id === `panel-${name}`; panel.classList.toggle("is-visible", active); panel.hidden = !active; });
    if (name === "language") renderLanguage(); if (name === "results") renderResults(); if(name === "viewer") renderViewerCaseSelect();
    if (name === "builder" && !builder.meta) initBuilder();
  }

  async function loadGoal() {
    try { state.goal = await api("/api/goal"); setText($("goal-markdown"), state.goal && state.goal.markdown, "No project goal returned."); setText($("goal-state"), "Fetched"); }
    catch (error) { setText($("goal-markdown"), `Project goal unavailable: ${error.message}`); setText($("goal-state"), "Unavailable"); }
    try { state.goals = await api("/api/goals"); renderGoalsBoard(); setText($("goals-state"), "Fetched"); }
    catch (error) { setText($("goals-board"), `Execution goals unavailable: ${error.message}`); setText($("goals-state"), "Unavailable"); }
  }

  // The stage board: every goal's stages with their status, what to look for
  // in 3D, the realtime gate, and links to the recordings that exist. Statuses
  // are the file's own words; nothing is promoted here.
  function renderGoalsBoard() {
    const board = $("goals-board"); board.textContent = "";
    const goals = (state.goals && state.goals.goals) || [];
    if (!goals.length) { board.textContent = "No execution goals in the file."; return; }
    const jobUrl = (url) => { const m = /job=([0-9a-f]{32})/.exec(url || ""); return m ? `?job=${m[1]}` : url; };
    const badge = (status) => {
      const b = document.createElement("span"); b.className = "small-badge goal-status"; b.dataset.status = status || "";
      b.textContent = (status || "unknown").replace(/_/g, " "); return b;
    };
    goals.forEach((goal) => {
      const section = document.createElement("section"); section.className = "goal-block";
      const head = document.createElement("div"); head.className = "goal-block-head";
      const title = document.createElement("h3"); title.textContent = `${goal.id}: ${goal.title}`; head.append(title, badge(goal.status)); section.append(head);
      if (goal.rule) { const rule = document.createElement("p"); rule.className = "goal-rule"; rule.textContent = goal.rule; section.append(rule); }
      (goal.stages || []).forEach((stage) => {
        const card = document.createElement("div"); card.className = "goal-stage"; card.dataset.status = stage.status || "";
        const line = document.createElement("div"); line.className = "goal-stage-head";
        const name = document.createElement("strong"); name.textContent = `${stage.id}. ${stage.title}`; line.append(name, badge(stage.status)); card.append(line);
        const rows = [["Scene", stage.scene], ["Watch for", stage.visual_confirmation], ["Realtime gate", stage.realtime_gate], ["Risk", stage.risk]];
        Object.keys(stage).filter((k) => k.startsWith("note_")).forEach((k) => rows.push(["Note", stage[k]]));
        rows.forEach(([label, value]) => {
          if (!value) return; const p = document.createElement("p"); p.className = "goal-stage-row";
          const l = document.createElement("span"); l.className = "goal-stage-label"; l.textContent = `${label}: `; p.append(l, document.createTextNode(value)); card.append(p);
        });
        const evidence = Object.keys(stage).filter((k) => k.startsWith("evidence")).map((k) => stage[k]).filter((e) => e && typeof e === "object");
        evidence.forEach((e) => {
          const urls = Array.isArray(e.urls) ? e.urls : (e.url ? [e.url] : []);
          const summary = e.summary || (e.measured && Number.isFinite(e.measured.realtime_ratio) ? `${e.measured.realtime_ratio.toFixed(3)}x realtime, ${e.measured.simulated_s} s simulated` : "");
          const p = document.createElement("p"); p.className = "goal-stage-row goal-evidence";
          const l = document.createElement("span"); l.className = "goal-stage-label"; l.textContent = "Recording: "; p.append(l);
          if (summary) p.append(document.createTextNode(summary + " "));
          urls.forEach((url, i) => { const a = document.createElement("a"); a.href = jobUrl(url); a.textContent = `open ${i + 1}`; a.className = "goal-link"; p.append(a, document.createTextNode(" ")); });
          if (e.limits) { const lim = document.createElement("span"); lim.className = "goal-limits"; lim.textContent = `Limits: ${e.limits}`; p.append(lim); }
          card.append(p);
        });
        section.append(card);
      });
      board.append(section);
    });
  }

  async function loadStatus() {
    try { state.status = await api("/api/status"); renderStatus(); }
    catch (error) { state.status = {}; renderStatus(); showToast(`Status unavailable: ${error.message}`, true); }
  }

  async function restoreLatestJob() {
    const requested = new URLSearchParams(window.location.search).get("job"); const jobId = validJobId(requested) ? requested : localStorage.getItem(latestJobStorageKey); if (!validJobId(jobId)) return;
    try {
      const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`); state.job = job; state.jobId = job.id; rememberJob(job.id); state.latestPlan = job.plan || null; state.followup = true;
      const playable = job.cases?.findIndex(playbackAvailable) ?? -1; state.selectedCase = Math.max(0, playable);
      renderJob(job); renderLanguage(); renderResults(); addHistory(job);
      if (!state.messages.length && job.request_text) { addMessage("You", job.request_text); addMessage("Banjo",job.message); }
      if (activeStatuses.has(job.status)) pollJob(); else if (job.status === "complete" && playable >= 0) loadPlayback(playable, true); else { showUnavailablePlayback(job); activateTab("viewer"); }
    } catch {
      if(localStorage.getItem(latestJobStorageKey)===jobId)localStorage.removeItem(latestJobStorageKey); const url=new URL(window.location.href);if(url.searchParams.get("job")===jobId){url.searchParams.delete("job");history.replaceState(null,"",url);} clearViewer();
    }
  }

  function resetExperiment() {
    forgetJob();
    stopPolling(); clearViewer(); localStorage.removeItem(latestJobStorageKey); state.job = null; state.jobId = null; state.latestPlan = null; state.followup = false; state.messages = []; $("prompt-input").value = ""; renderConversation(); renderJob(null); renderLanguage(); renderResults(); renderViewerCaseSelect(); showToast("New experiment ready. Follow-up context cleared.");
  }

  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => activateTab(tab.dataset.tab)));
  $("chat-form").addEventListener("submit", submitPrompt);
  $("new-experiment").addEventListener("click", resetExperiment);
  $("language-case-select").addEventListener("change", (event) => { state.selectedCase = Number(event.target.value); renderLanguage(); });
  $("download-package-language").addEventListener("click", downloadPackage);
  $("viewer-evidence-button").addEventListener("click",()=>inspectEvidence());
  $("viewer-analyze").addEventListener("click",()=>inspectEvidence(true));
  $("viewer-case-select").addEventListener("change",(event)=>loadPlayback(Number(event.target.value)));
  $("viewer-play").addEventListener("click",()=>{const playing=state.scene?.play();$("viewer-play").textContent=playing?"Pause":"Play";});
  $("viewer-reset").addEventListener("click",()=>{state.scene?.reset();$("viewer-play").textContent="Play";});
  $("viewer-back").addEventListener("click",()=>state.scene?.step(-1));$("viewer-forward").addEventListener("click",()=>state.scene?.step(1));
  $("viewer-frame").addEventListener("input",e=>state.scene?.setFrame(Number(e.target.value)));$("viewer-speed").addEventListener("change",e=>{state.scene?.setSpeed(e.target.value);syncCustomDisplay("playback_speed",Number(e.target.value));});$("viewer-magnification").addEventListener("change",e=>state.scene?.setMagnification(e.target.value));
  $("viewer-components").addEventListener("change",e=>state.scene?.showComponents(e.target.checked));$("viewer-reference").addEventListener("change",e=>state.scene?.showReference(e.target.checked));$("viewer-bonds").addEventListener("change",e=>state.scene?.showBonds(e.target.checked));$("viewer-xray").addEventListener("change",e=>state.scene?.setXray(e.target.checked));$("viewer-native").addEventListener("click",()=>openStudio(state.selectedCase));
  $("prompt-input").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); $("chat-form").requestSubmit(); } });
  renderConversation(); renderHistory(); renderJob(null); renderStatus(); loadGoal(); restoreLatestJob();
  // The builder posts to the server for every check, so it needs the session
  // token that /api/status hands out before it can preview anything.
  loadStatus().then(initBuilder);
})();
