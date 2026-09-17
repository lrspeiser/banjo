// Workshop Mode: one browser state for selection, component edits, bounded chat,
// reusable library items, functional tests, whole-design variants, and live material cost.
import * as THREE from "/vendor/three.module.js";

const $ = (q) => document.querySelector(q);
let token = "";
async function api(path, body) {
  if (!token) {
    const status = await fetch("/api/status").then((r) => r.json());
    token = status.csrf_token || "";
  }
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Banjo-Token": token },
    body: JSON.stringify(body || {}),
  });
  const answer = await response.json().catch(() => ({ error: "the bench gave no answer" }));
  if (!response.ok) throw new Error(answer.error || `${path} failed (${response.status})`);
  return answer;
}

// ---------------------------------------------------------------------------
// Three.js view and selection
// ---------------------------------------------------------------------------
const stage = $("#workshop-stage");
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 100);
const renderer = new THREE.WebGLRenderer({ canvas: stage, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
scene.add(new THREE.HemisphereLight(0xffffff, 0x45505c, 2.1));
const sun = new THREE.DirectionalLight(0xffffff, 2.8);
sun.position.set(3, 5, 4);
scene.add(sun);
const grid = new THREE.GridHelper(4, 20, 0x596777, 0x313b47);
scene.add(grid);
const group = new THREE.Group();
scene.add(group);
const balance = new THREE.Mesh(
  new THREE.SphereGeometry(0.025, 16, 12),
  new THREE.MeshBasicMaterial({ color: 0xffd166 }));
scene.add(balance);
const support = new THREE.LineSegments(
  new THREE.BufferGeometry(),
  new THREE.LineBasicMaterial({ color: 0xffd166, transparent: true, opacity: 0.55 }));
scene.add(support);
const raycaster = new THREE.Raycaster();
raycaster.params.Line.threshold = 0.045;
const pointer = new THREE.Vector2();

const SKIN = {
  oak: 0x9a704d, pine: 0xc0a072, iron: 0x8d939b, steel: 0x9aa2ab,
  aluminium: 0xb8bfc6, aluminum: 0xb8bfc6, glass: 0x9fc6d8,
  concrete: 0x9a9a95, rubber: 0x3c3c42, ice: 0xcde8f1,
  "alumina ceramic": 0xd9d4c8,
};
let view = "wire";
let yaw = 0.72, pitch = 0.42, distance = 3;
let dragging = false, dragged = false, px = 0, py = 0, reach = 1.5;
const target = new THREE.Vector3(0, 0.42, 0);

const bench = {
  kind: "table", generation: 0, candidates: [], selected: 0, plans: {},
  session: null, savedDesigns: [], personalLibrary: [], pricebook: null,
  selectedPart: null, forcePoint: null, openedLibraryItem: null,
  benchTests: [], benchPresets: [], selectedBenchTest: null,
};
function chosen() { return bench.candidates[bench.selected]; }
function selectedPart() {
  const candidate = chosen();
  return candidate && candidate.parts.find((p) => p.name === bench.selectedPart);
}

function placeCamera() {
  pitch = Math.max(-0.15, Math.min(1.25, pitch));
  camera.position.set(
    target.x + distance * Math.cos(pitch) * Math.sin(yaw),
    target.y + distance * Math.sin(pitch),
    target.z + distance * Math.cos(pitch) * Math.cos(yaw));
  camera.lookAt(target);
}
function frameCandidate() {
  const up = THREE.MathUtils.degToRad(camera.fov) / 2;
  const across = Math.atan(Math.tan(up) * Math.max(0.2, camera.aspect));
  distance = Math.max(0.6, reach * 1.15 / Math.sin(Math.min(up, across)));
  placeCamera();
}
function shapeFor(part) {
  const [w, h, d] = part.size_m;
  if (part.shape === "tapered") return new THREE.CylinderGeometry(w * 0.4, d * 0.62, h, 5, 1);
  if (part.shape === "cylinder") return new THREE.CylinderGeometry(w / 2, d / 2, h, 20, 1);
  return new THREE.BoxGeometry(w, h, d);
}
function clearGroup() {
  for (const child of [...group.children]) {
    group.remove(child);
    if (child.geometry) child.geometry.dispose();
    if (child.material) child.material.dispose();
  }
}
function draw(candidate) {
  clearGroup();
  for (const part of candidate.parts) {
    const geometry = shapeFor(part);
    const spin = new THREE.Euler(
      THREE.MathUtils.degToRad(part.rotation_deg[0]),
      THREE.MathUtils.degToRad(part.rotation_deg[1]),
      THREE.MathUtils.degToRad(part.rotation_deg[2]), "XYZ");
    const selected = part.name === bench.selectedPart;
    if (view === "wire") {
      const line = new THREE.LineSegments(
        new THREE.EdgesGeometry(geometry),
        new THREE.LineBasicMaterial({ color: selected ? 0xffd166 : 0xdce7f5 }));
      line.position.set(...part.center_m);
      line.rotation.copy(spin);
      line.userData.partName = part.name;
      group.add(line);
      geometry.dispose();
      continue;
    }
    const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
      color: selected ? 0xd9a441 : (view === "skin" ? (SKIN[part.material] ?? 0x9a704d) : 0x6f8194),
      emissive: selected ? 0x3d2b0d : 0x000000,
      roughness: view === "skin" ? 0.72 : 0.45,
      metalness: 0,
      transparent: view === "matter",
      opacity: view === "matter" ? 0.72 : 1,
    }));
    mesh.position.set(...part.center_m);
    mesh.rotation.copy(spin);
    mesh.userData.partName = part.name;
    group.add(mesh);
    if (view === "matter") {
      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(geometry),
        new THREE.LineBasicMaterial({
          color: selected ? 0xffd166 : 0xd9e3ed,
          transparent: true, opacity: selected ? 1 : 0.45,
        }));
      edges.position.copy(mesh.position);
      edges.rotation.copy(mesh.rotation);
      edges.userData.partName = part.name;
      group.add(edges);
    }
  }

  const m = candidate.measured;
  balance.position.set(...m.centre_of_mass_m);
  const feet = m.ground_contacts_m || [];
  const ring = [];
  if (feet.length) {
    const xs = feet.map((f) => f[0]), zs = feet.map((f) => f[1]);
    const box = [
      [Math.min(...xs), Math.min(...zs)], [Math.max(...xs), Math.min(...zs)],
      [Math.max(...xs), Math.max(...zs)], [Math.min(...xs), Math.max(...zs)],
    ];
    for (let i = 0; i < 4; i++) {
      const a = box[i], b = box[(i + 1) % 4];
      ring.push(a[0], m.lowest_m + 0.002, a[1], b[0], m.lowest_m + 0.002, b[1]);
    }
  }
  support.geometry.dispose();
  support.geometry = new THREE.BufferGeometry();
  support.geometry.setAttribute("position", new THREE.Float32BufferAttribute(ring, 3));
  grid.position.y = m.lowest_m;
  target.set(0, m.lowest_m + m.bounding_box_m[1] * 0.5, 0);
  reach = 0.5 * Math.hypot(...m.bounding_box_m);
}
// Where the last click landed on the product, in world metres. The force is
// applied HERE rather than at the part's middle, so pushing the rim of a shelf
// and pushing its centre are different questions with different answers.
const forceArrow = new THREE.ArrowHelper(
  new THREE.Vector3(0, -1, 0), new THREE.Vector3(), 0.3, 0xffb347, 0.08, 0.05);
forceArrow.visible = false;
scene.add(forceArrow);

function showForceAt(point, force_n) {
  if (!point) { forceArrow.visible = false; return; }
  // Length carries the magnitude: the slider's range maps onto a span that
  // stays readable beside the product it is pushing.
  const span = Math.max(0.12, reach * 0.9);
  const size = span * (0.25 + 0.75 * Math.min(1, (Number(force_n) || 0) / 5000));
  forceArrow.position.set(point[0], point[1] + size, point[2]);
  forceArrow.setDirection(new THREE.Vector3(0, -1, 0));
  forceArrow.setLength(size, size * 0.28, size * 0.16);
  forceArrow.visible = true;
}

function pickPart(event) {
  const rect = stage.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hit = raycaster.intersectObjects(group.children, false)
    .find((item) => item.object.userData && item.object.userData.partName);
  bench.selectedPart = hit ? hit.object.userData.partName : null;
  bench.forcePoint = hit ? [hit.point.x, hit.point.y, hit.point.z] : null;
  show(false);
  // Clicking the product IS the test, when the probe is the chosen one: the
  // answer should arrive from the click, not from hunting for a Run button.
  if (bench.selectedPart && bench.selectedBenchTest === "force_probe") reprobe();
  else showForceAt(null);
}

// Re-run the point force probe for the current part, point and slider values.
let probing = false;
function reprobe() {
  if (bench.selectedBenchTest !== "force_probe" || !bench.selectedPart || probing) return;
  probing = true;
  const config = benchConfig();
  showForceAt(bench.forcePoint, config.force_n);
  guard(null, async () => {
    try {
      const answer = await api("/api/workshop/plan", {
        ...candidateBody(), bench_test: { test: "force_probe", config },
      });
      renderBenchResult(answer.bench);
      // Draw the arrow where the probe says it pushed, so the picture and the
      // numbers cannot disagree.
      showForceAt(answer.bench?.target?.point_m || bench.forcePoint, config.force_n);
    } finally { probing = false; }
  });
}
stage.addEventListener("pointerdown", (event) => {
  dragging = true; dragged = false; px = event.clientX; py = event.clientY;
  stage.setPointerCapture(event.pointerId);
});
stage.addEventListener("pointermove", (event) => {
  if (!dragging) return;
  const dx = event.clientX - px, dy = event.clientY - py;
  if (Math.abs(dx) + Math.abs(dy) > 3) dragged = true;
  yaw -= dx * 0.008; pitch += dy * 0.008; px = event.clientX; py = event.clientY;
  placeCamera();
});
stage.addEventListener("pointerup", (event) => {
  dragging = false;
  if (!dragged) pickPart(event);
});
stage.addEventListener("pointercancel", () => { dragging = false; });
stage.addEventListener("wheel", (event) => {
  event.preventDefault();
  distance = Math.max(0.6, Math.min(9, distance * Math.exp(event.deltaY * 0.001)));
  placeCamera();
}, { passive: false });
stage.addEventListener("dragover", (event) => {
  event.preventDefault(); stage.classList.add("ws-drop-target");
});
stage.addEventListener("dragleave", () => stage.classList.remove("ws-drop-target"));
stage.addEventListener("drop", (event) => {
  event.preventDefault(); stage.classList.remove("ws-drop-target");
  const itemId = event.dataTransfer.getData("application/x-banjo-library-item");
  if (!itemId) return;
  if (!bench.selectedPart) {
    say("Select the component the saved item should replace, then drop it again.", true);
    return;
  }
  guard(null, () => reuseLibraryComponent(itemId));
});

// ---------------------------------------------------------------------------
// DOM helpers, component editor and general functional test bench
// ---------------------------------------------------------------------------
function make(tag, attrs = {}, text = "") {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") element.className = value;
    else if (key === "id") element.id = value;
    else element.setAttribute(key, value);
  }
  if (text) element.textContent = text;
  return element;
}
function say(message, bad = false) {
  const checks = $("#ws-checks");
  checks.className = "ws-note" + (bad ? " bad" : "");
  checks.textContent = message;
}
async function guard(button, work) {
  const original = button && button.textContent;
  if (button) button.disabled = true;
  try { await work(); }
  catch (err) { say(String(err.message || err), true); }
  finally {
    if (button) { button.disabled = false; button.textContent = original; }
  }
}
function candidateBody() {
  const candidate = chosen();
  return {
    kind: bench.kind,
    generation: bench.generation,
    design_id: candidate.design_id,
    purpose: candidate.purpose,
    parameters: candidate.parameters,
    component_overrides: candidate.component_overrides || {},
  };
}
function installEditor() {
  const left = $(".ws-left"), right = $(".ws-right"), builtIn = $("#ws-library");
  const builtInHeading = builtIn.previousElementSibling && builtIn.previousElementSibling.previousElementSibling;
  const libraryBox = make("section", { id: "ws-personal-library-box" });
  libraryBox.append(
    make("h2", {}, "My library"),
    make("p", {}, "Reusable components and assemblies. Select a part, then click or drag a component onto it."),
    make("div", { id: "ws-user-library" }));
  left.insertBefore(libraryBox, builtInHeading || builtIn);

  const editor = make("section", { id: "ws-component-editor", class: "ws-component-editor" });
  editor.append(make("h3", {}, "Selected component"));
  editor.append(make("p", { id: "ws-selected-part", class: "ws-note" }, "Click a part of the object to edit it."));
  const scope = make("select", { id: "ws-edit-scope", "aria-label": "Edit scope" });
  for (const [value, label] of [["this", "This part"], ["similar", "Similar parts"], ["all", "Whole object"]]) {
    scope.append(make("option", { value }, label));
  }
  const scopeLabel = make("label", { class: "ws-field" }, "Change");
  scopeLabel.append(scope); editor.append(scopeLabel);
  const actions = make("div", { class: "ws-edit-actions" });
  for (const [action, label] of [["longer", "Longer"], ["shorter", "Shorter"], ["thicker", "Thicker"], ["thinner", "Thinner"]]) {
    actions.append(make("button", { type: "button", class: "ws-action", "data-component-edit": action }, label));
  }
  editor.append(actions);
  const material = make("select", { id: "ws-part-material" });
  const materialLabel = make("label", { class: "ws-field" }, "Material");
  materialLabel.append(material); editor.append(materialLabel);
  const saveName = make("input", { id: "ws-component-name", type: "text", maxlength: "120", placeholder: "My tapered leg" });
  const saveLabel = make("label", { class: "ws-field" }, "Save component as");
  saveLabel.append(saveName); editor.append(saveLabel);
  editor.append(make("button", { id: "ws-save-component", type: "button", class: "ws-action" }, "Save to my library"));
  editor.append(make("h3", {}, "Tell Workshop"));
  const chat = make("form", { id: "ws-component-chat", class: "ws-component-chat" });
  chat.append(
    make("input", { id: "ws-component-chat-text", type: "text", placeholder: "make all the legs thinner" }),
    make("button", { type: "submit", class: "ws-action" }, "Change"));
  editor.append(chat);
  right.insertBefore(editor, right.querySelector("h3"));

  const bom = make("section", { id: "ws-bom-box" });
  bom.append(make("h3", {}, "Materials"), make("div", { id: "ws-bom" }));
  right.insertBefore(bom, $("#ws-checks").previousElementSibling);

  const testBox = make("section", { id: "ws-test-bench" });
  testBox.append(
    make("h3", {}, "Test bench"),
    make("p", { class: "ws-feedback-count" }, "Run the selected object beside an isolated functional fixture. The outside world does not advance."));
  const testPicker = make("select", { id: "ws-bench-test", "aria-label": "Functional test" });
  const pickerLabel = make("label", { class: "ws-field" }, "Test");
  pickerLabel.append(testPicker); testBox.append(pickerLabel);
  testBox.append(make("div", { id: "ws-bench-controls" }));
  const testActions = make("div", { class: "ws-row" });
  testActions.append(
    make("button", { id: "ws-run-bench", type: "button", class: "ws-action primary" }, "Run test"),
    make("button", { id: "ws-save-bench-preset", type: "button", class: "ws-action" }, "Save preset"));
  testBox.append(testActions);
  const presetName = make("input", { id: "ws-bench-preset-name", type: "text", maxlength: "120", placeholder: "Half-speed lift" });
  const presetLabel = make("label", { class: "ws-field" }, "Preset name");
  presetLabel.append(presetName); testBox.append(presetLabel);
  testBox.append(make("div", { id: "ws-bench-presets" }), make("div", { id: "ws-bench-result" }));
  right.insertBefore(testBox, $("#ws-save-design").parentElement.previousElementSibling || $("#ws-save-design").parentElement);

  actions.querySelectorAll("button").forEach((button) => {
    button.onclick = () => guard(button, () => editSelected(button.dataset.componentEdit));
  });
  material.onchange = () => guard(null, () => editSelected("material", material.value));
  $("#ws-save-component").onclick = (event) => guard(event.currentTarget, saveSelectedComponent);
  chat.onsubmit = (event) => {
    event.preventDefault(); guard(chat.querySelector("button"), chatEdit);
  };
  testPicker.onchange = () => {
    bench.selectedBenchTest = testPicker.value;
    renderBenchControls();
    $("#ws-bench-result").replaceChildren();
  };
  $("#ws-run-bench").onclick = (event) => guard(event.currentTarget, runBenchTest);
  $("#ws-save-bench-preset").onclick = (event) => guard(event.currentTarget, saveBenchPreset);
}
installEditor();

async function editSelected(action, material = null) {
  if (!bench.selectedPart) throw new Error("Click a component first.");
  const selected = bench.selectedPart;
  const answer = await api("/api/workshop/candidates", {
    ...candidateBody(),
    component_edit: {
      part_name: selected,
      action,
      scope: $("#ws-edit-scope").value,
      amount: 0.12,
      ...(material ? { material } : {}),
    },
  });
  took(answer, selected);
}
async function chatEdit() {
  if (!bench.selectedPart) throw new Error("Click the part you want to talk about first.");
  const input = $("#ws-component-chat-text");
  const message = input.value.trim();
  if (!message) throw new Error("Tell Workshop what to change.");
  const selected = bench.selectedPart;
  const answer = await api("/api/workshop/candidates", {
    ...candidateBody(),
    component_chat: { part_name: selected, message },
  });
  took(answer, selected);
  if (answer.workshop_chat && answer.workshop_chat.scope) $("#ws-edit-scope").value = answer.workshop_chat.scope;
  if (answer.workshop_chat && answer.workshop_chat.reply) say(answer.workshop_chat.reply);
  input.value = "";
}
async function saveSelectedComponent() {
  const part = selectedPart();
  if (!part) throw new Error("Click the component you want to save first.");
  const name = $("#ws-component-name").value.trim() || `${part.material} ${part.role}`;
  const answer = await api("/api/workshop/library", {
    action: "save_component", ...candidateBody(), part_name: part.name, name,
  });
  bench.personalLibrary = answer.personal_library || [];
  bench.pricebook = answer.pricebook || bench.pricebook;
  renderUserLibrary();
  $("#ws-component-name").value = "";
  say(`Saved ${name} to My Library.`);
}
async function reuseLibraryComponent(itemId) {
  if (!bench.selectedPart) throw new Error("Click a target component first.");
  const selected = bench.selectedPart;
  const answer = await api("/api/workshop/candidates", {
    ...candidateBody(),
    reuse_library_item: { item_id: itemId, part_name: selected, scope: $("#ws-edit-scope").value },
  });
  took(answer, selected);
}

// ---------------------------------------------------------------------------
// Functional bench controls/results
// ---------------------------------------------------------------------------
function benchDefinition(name = bench.selectedBenchTest) {
  return bench.benchTests.find((item) => item.test === name) || null;
}
function renderBenchCatalog() {
  const picker = $("#ws-bench-test");
  picker.replaceChildren();
  for (const test of bench.benchTests) picker.append(make("option", { value: test.test }, test.name));
  if (!bench.selectedBenchTest || !benchDefinition(bench.selectedBenchTest)) {
    bench.selectedBenchTest = bench.benchTests[0] ? bench.benchTests[0].test : null;
  }
  if (bench.selectedBenchTest) picker.value = bench.selectedBenchTest;
  picker.disabled = !bench.benchTests.length;
  $("#ws-run-bench").disabled = !bench.benchTests.length;
  $("#ws-save-bench-preset").disabled = !bench.benchTests.length;
  renderBenchControls();
  renderBenchPresets();
}
function renderBenchControls(values = null) {
  const root = $("#ws-bench-controls");
  root.replaceChildren();
  const definition = benchDefinition();
  if (!definition) {
    root.append(make("p", { class: "ws-feedback-count" }, "No functional tests are available."));
    return;
  }
  root.append(make("p", { class: "ws-feedback-count" }, definition.about));
  for (const control of definition.controls || []) {
    const label = make("label", { class: "ws-field" }, `${control.label}${control.unit ? ` (${control.unit})` : ""}`);
    let input;
    const chosenValue = values && Object.prototype.hasOwnProperty.call(values, control.name)
      ? values[control.name] : control.default;
    if (control.type === "boolean") {
      input = make("input", { type: "checkbox", "data-bench-control": control.name });
      input.checked = Boolean(chosenValue);
    } else if (control.type === "select") {
      input = make("select", { "data-bench-control": control.name });
      (control.choices || []).forEach((choice, index) => {
        const option = make("option", { value: String(choice) },
          (control.choice_labels || [])[index] || String(choice));
        option.selected = String(choice) === String(chosenValue);
        input.append(option);
      });
      input.dataset.valueType = typeof control.default;
    } else if (control.type === "range") {
      // A slider, with its value shown and the test re-run as it moves, so the
      // arrow in the 3D view answers "how hard" while you are still dragging.
      input = make("input", {
        type: "range", min: String(control.min ?? 0), max: String(control.max ?? 100),
        step: String(control.step ?? "any"), "data-bench-control": control.name,
      });
      // Value AFTER the bounds: a range input clamps whatever it is given to
      // the range it has at the time, and the default range is 0-100, so
      // setting it first turned a 500 N default into 100 N.
      input.value = String(chosenValue ?? control.min ?? 0);
      input.dataset.valueType = "number";
      const shown = make("output", { class: "ws-range-value" }, String(chosenValue ?? ""));
      const say = () => { shown.textContent = input.value; };
      input.addEventListener("input", say);
      input.addEventListener("change", () => { say(); reprobe(); });
      label.append(input, shown); root.append(label);
      continue;
    } else {
      input = make("input", {
        type: "number", value: String(chosenValue ?? ""),
        min: String(control.min ?? ""), max: String(control.max ?? ""), step: String(control.step ?? "any"),
        "data-bench-control": control.name,
      });
      input.dataset.valueType = "number";
    }
    label.append(input); root.append(label);
  }
  for (const limitation of definition.limitations || []) {
    root.append(make("p", { class: "ws-feedback-count" }, `Limit: ${limitation}`));
  }
}
function benchConfig() {
  const definition = benchDefinition();
  if (!definition) throw new Error("Choose a test first.");
  const out = {};
  for (const control of definition.controls || []) {
    const input = document.querySelector(`[data-bench-control="${control.name}"]`);
    if (!input) continue;
    if (control.type === "boolean") out[control.name] = input.checked;
    else if (control.type === "number") out[control.name] = Number(input.value);
    else if (typeof control.default === "number") out[control.name] = Number(input.value);
    else out[control.name] = input.value;
  }
  // A test that pushes on one part (the point force probe) offers no control
  // to name it, because the part is chosen by clicking the product. Hand the
  // chosen part over, so clicking a leg and pressing Run just works instead of
  // asking the server to guess.
  if (bench.selectedPart && out.component === undefined) out.component = bench.selectedPart;
  if (bench.forcePoint && out.point_m === undefined) out.point_m = bench.forcePoint;
  return out;
}
function renderBenchPresets() {
  const root = $("#ws-bench-presets"); root.replaceChildren();
  const relevant = bench.benchPresets.filter((preset) => preset.test === bench.selectedBenchTest);
  if (!relevant.length) return;
  root.append(make("p", { class: "ws-feedback-count" }, "Saved test controls"));
  const row = make("div", { class: "ws-row" });
  for (const preset of relevant) {
    const button = make("button", { type: "button", class: "ws-action" }, preset.name);
    button.onclick = () => {
      renderBenchControls(preset.config || {});
      $("#ws-bench-preset-name").value = preset.name;
    };
    row.append(button);
  }
  root.append(row);
}
function celsius(k) {
  return k == null ? "—" : `${(Number(k) - 273.15).toFixed(1)} °C`;
}
function renderBenchResult(result) {
  const root = $("#ws-bench-result"); root.replaceChildren();
  if (!result) return;
  const card = make("div", { class: "ws-note" });
  if (result.test === "kettle_heat") {
    const m = result.measured || {};
    card.append(
      make("strong", {}, `Water: ${celsius(m.water_start_k)} → ${celsius(m.water_end_k)}`),
      make("p", {}, `Kettle bottom ${celsius(m.kettle_bottom_k)} · heater plate ${celsius(m.heater_plate_k)}`));
    const heaterIn = m.ledger && m.ledger.heater_in_j;
    if (heaterIn != null) card.append(make("p", {}, `External heat added: ${(Number(heaterIn) / 1000).toFixed(1)} kJ`));
  } else if (result.test === "machine_control") {
    const m = result.measured || {}, control = m.control || {}, motor = m.motor || {}, battery = m.battery || {};
    card.append(
      make("strong", {}, `Controller: ${control.condition || "—"}`),
      make("p", {}, `Power ${control.power ? "on" : "off"} · direction ${control.direction ?? "—"} · setting ${control.setting == null ? "—" : `${(Number(control.setting) * 100).toFixed(0)}%`}`),
      make("p", {}, `Speed ${Number(control.speed_rpm || 0).toFixed(1)} rpm · load moved ${Number(m.load_delta_y_m || 0).toFixed(3)} m`),
      make("p", {}, `Motor ${Number(motor.power_w || 0).toFixed(1)} W · battery supplied ${Number(battery.given_j || 0).toFixed(1)} J`));
  }
  root.append(card);
  for (const limitation of result.limitations || []) root.append(make("p", { class: "ws-feedback-count" }, limitation));
  const details = make("details", { class: "ws-family" });
  details.append(make("summary", {}, "Measured evidence"));
  const pre = make("pre"); pre.textContent = JSON.stringify(result, null, 2); details.append(pre);
  root.append(details);
}
async function runBenchTest() {
  const definition = benchDefinition();
  if (!definition) throw new Error("Choose a test first.");
  const answer = await api("/api/workshop/plan", {
    ...candidateBody(),
    bench_test: { test: definition.test, config: benchConfig() },
  });
  renderBenchResult(answer.bench);
}
async function saveBenchPreset() {
  const definition = benchDefinition();
  if (!definition) throw new Error("Choose a test first.");
  const name = $("#ws-bench-preset-name").value.trim() || `${definition.name} preset`;
  const answer = await api("/api/workshop/library", {
    action: "save_bench_preset", name, test: definition.test, config: benchConfig(),
  });
  bench.benchPresets = answer.bench_presets || [];
  renderBenchPresets();
  say(`Saved test preset ${name}.`);
}

// ---------------------------------------------------------------------------
// Panels
// ---------------------------------------------------------------------------
function cards() {
  const root = $("#variant-list"); root.replaceChildren();
  const twins = {};
  for (const [id, fingerprint] of Object.entries(bench.plans)) (twins[fingerprint] ||= []).push(id);
  bench.candidates.forEach((candidate, index) => {
    const button = make("button", {
      type: "button",
      class: "ws-card" + (index === bench.selected ? " selected" : ""),
    });
    const m = candidate.measured;
    const shared = twins[bench.plans[candidate.design_id]] || [];
    button.append(
      make("strong", {}, candidate.label || candidate.design_id),
      make("small", {}, `${m.mass_kg} kg · base ${m.support_footprint_m[0].toFixed(2)} × ${m.support_footprint_m[1].toFixed(2)} m · tips ${m.tip_angle_deg}°`
        + (shared.length > 1 ? " · same snapped object" : "")));
    if (shared.length > 1) button.classList.add("same-plan");
    button.onclick = () => {
      bench.selected = index; bench.selectedPart = null; cards(); show(false);
    };
    root.append(button);
  });
}
function savedDesigns(rows) {
  bench.savedDesigns = Array.isArray(rows) ? rows : [];
  const root = $("#ws-saved-designs"); root.replaceChildren();
  if (!bench.savedDesigns.length) {
    root.append(make("p", { class: "ws-feedback-count" }, "No legacy saved designs."));
    return;
  }
  for (const saved of bench.savedDesigns) {
    const button = make("button", { type: "button", class: "ws-card" });
    button.append(
      make("strong", {}, saved.label || saved.design_id),
      make("small", {}, `${saved.kind} · revision ${saved.revision}${saved.measured ? ` · ${saved.measured.mass_kg} kg` : ""}`));
    button.onclick = () => guard(button, async () => {
      const answer = await api("/api/workshop/open", { saved_design_id: saved.design_id });
      bench.openedLibraryItem = null;
      took(answer); $("#ws-archetype").value = answer.kind;
    });
    root.append(button);
  }
}
function renderUserLibrary() {
  const root = $("#ws-user-library"); root.replaceChildren();
  if (!bench.personalLibrary.length) {
    root.append(make("p", { class: "ws-feedback-count" }, "Nothing saved yet. Select a part and save it."));
    return;
  }
  for (const item of bench.personalLibrary) {
    const card = make("button", {
      type: "button", class: "ws-card ws-library-item", draggable: "true",
    });
    card.append(
      make("strong", {}, item.name),
      make("small", {}, `${item.item_type}${item.family ? ` · ${item.family}` : ""} · v${item.version}`));
    card.ondragstart = (event) => {
      event.dataTransfer.setData("application/x-banjo-library-item", item.item_id);
      event.dataTransfer.effectAllowed = "copy";
    };
    card.onclick = () => guard(card, async () => {
      if (item.item_type === "assembly") {
        const answer = await api("/api/workshop/open", { library_item_id: item.item_id });
        bench.openedLibraryItem = item.item_id;
        took(answer); $("#ws-archetype").value = answer.kind;
      } else if (bench.selectedPart) {
        await reuseLibraryComponent(item.item_id);
      } else {
        say("Select a component, then click or drag this saved component onto it.");
      }
    });
    root.append(card);
  }
}
function families(described) {
  const root = $("#ws-library"); root.replaceChildren();
  for (const family of described) {
    const box = make("details", { class: "ws-family" });
    const list = make("dl");
    for (const p of family.parameters) {
      list.append(
        make("dt", {}, p.name),
        make("dd", {}, p.choices ? p.choices.join(", ") : `${p.low ?? "—"} to ${p.high ?? "—"} ${p.unit}`.trim()));
    }
    box.append(
      make("summary", {}, `${family.family} · ${family.parameters.length} settings`),
      make("p", {}, family.about),
      list);
    root.append(box);
  }
}
function renderBom(candidate) {
  const root = $("#ws-bom"); root.replaceChildren();
  const bom = candidate.bom;
  if (!bom) {
    root.append(make("p", { class: "ws-feedback-count" }, "No material estimate."));
    return;
  }
  const table = make("table", { class: "ws-bom-table" });
  for (const row of bom.materials || []) {
    const tr = make("tr");
    tr.append(
      make("td", {}, row.material),
      make("td", {}, `${row.mass_kg} kg`),
      make("td", {}, row.cost == null ? "unpriced" : `${row.cost} cr`));
    table.append(tr);
  }
  root.append(
    table,
    make("p", { class: "ws-bom-total" }, `Material cost: ${bom.material_cost} credits`),
    make("p", { class: "ws-feedback-count" }, bom.basis));
}
function renderSelected() {
  const part = selectedPart();
  const status = $("#ws-selected-part"), material = $("#ws-part-material");
  document.querySelectorAll("[data-component-edit], #ws-save-component, #ws-part-material")
    .forEach((element) => { element.disabled = !part; });
  if (!part) {
    status.textContent = "Click a part of the object to edit it.";
    material.replaceChildren();
    return;
  }
  status.textContent = `${part.name} · ${part.role}${part.family ? ` · ${part.family}` : ""} · ${part.material} · ${(part.size_m[0] * 1000).toFixed(0)} × ${(part.size_m[1] * 1000).toFixed(0)} × ${(part.size_m[2] * 1000).toFixed(0)} mm`;
  material.replaceChildren();
  const names = (bench.pricebook && bench.pricebook.materials || []).map((item) => item.material);
  if (!names.includes(part.material)) names.push(part.material);
  names.sort().forEach((name) => {
    const option = make("option", { value: name }, name);
    option.selected = name === part.material;
    material.append(option);
  });
}
function show(reframe = true) {
  const candidate = chosen();
  if (!candidate) return;
  if (bench.selectedPart && !candidate.parts.some((part) => part.name === bench.selectedPart)) bench.selectedPart = null;
  draw(candidate);
  if (reframe) frameCandidate();
  const m = candidate.measured;
  $("#ws-name").textContent = candidate.label || candidate.design_id;
  $("#ws-purpose").textContent = candidate.purpose;
  $("#ws-part-count").textContent = candidate.parts.length;
  $("#ws-mass").textContent = `${m.mass_kg} kg`;
  $("#ws-base").textContent = `${m.support_footprint_m[0].toFixed(2)} × ${m.support_footprint_m[1].toFixed(2)} m`;
  $("#ws-tip").textContent = `${m.tip_angle_deg}°`;

  const parts = $("#ws-parts"); parts.replaceChildren();
  for (const part of candidate.parts) {
    const row = make("li");
    const button = make("button", { type: "button", class: "ws-part-link" }, part.name);
    button.onclick = () => { bench.selectedPart = part.name; show(false); };
    row.append(button, document.createTextNode(` · ${part.role} · ${part.material} · ${part.mass_kg} kg`));
    parts.append(row);
  }
  renderSelected();
  renderBom(candidate);

  const checks = $("#ws-checks"); checks.className = "ws-note";
  const said = [];
  if (!m.stands_up) {
    checks.classList.add("bad");
    said.push("It does not stand: its balance point is outside its supports.");
  } else {
    said.push(`Balanced ${m.smallest_tip_margin_m} m inside its nearest edge; geometric tip angle ${m.tip_angle_deg}°.`);
  }
  if (m.legs_not_under_the_top.length) {
    checks.classList.add("warn");
    said.push(`${m.legs_not_under_the_top.join(", ")} meet nothing.`);
  }
  const stat = ((candidate.analytical || {}).static_loads || [])[0];
  if (stat) said.push(`Analytical ${stat.external_load_kg} kg load: ${stat.max_support.name} carries about ${stat.max_support.equivalent_load_kg} kg equivalent.`);
  checks.textContent = said.join(" ");
  $("#ws-plan").hidden = true;
}

async function fingerprints() {
  bench.plans = {};
  await Promise.all(bench.candidates.map(async (candidate) => {
    try {
      const plan = await api("/api/workshop/plan", {
        kind: bench.kind, design_id: candidate.design_id, parameters: candidate.parameters,
        component_overrides: candidate.component_overrides || {},
      });
      bench.plans[candidate.design_id] = plan.fingerprint;
    } catch { /* fingerprints are optional UI evidence */ }
  }));
  cards();
}
function took(answer, keepPart = null) {
  bench.kind = answer.kind;
  bench.generation = answer.generation;
  bench.candidates = answer.candidates;
  bench.selected = 0;
  bench.plans = {};
  bench.selectedPart = keepPart;
  if (answer.session) bench.session = answer.session;
  if (answer.saved_designs) savedDesigns(answer.saved_designs);
  if (answer.personal_library) {
    bench.personalLibrary = answer.personal_library;
    renderUserLibrary();
  }
  if (answer.pricebook) bench.pricebook = answer.pricebook;
  if (answer.bench_tests) bench.benchTests = answer.bench_tests;
  if (answer.bench_presets) bench.benchPresets = answer.bench_presets;
  renderBenchCatalog();
  cards();
  show();
  fingerprints();
}

// ---------------------------------------------------------------------------
// Whole-design controls
// ---------------------------------------------------------------------------
document.querySelectorAll(".ws-viewbar button").forEach((button) => {
  button.onclick = () => {
    view = button.dataset.view;
    document.querySelectorAll(".ws-viewbar button")
      .forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
    show(false);
  };
});
$("#ws-more").onclick = (event) => guard(event.currentTarget, async () => {
  took(await api("/api/workshop/more", candidateBody()));
});
$("#ws-reset-variants").onclick = (event) => guard(event.currentTarget, async () => {
  bench.openedLibraryItem = null;
  took(await api("/api/workshop/candidates", { kind: bench.kind, generation: bench.generation + 1 }));
});
$("#ws-archetype").onchange = (event) => guard(null, async () => {
  bench.openedLibraryItem = null;
  took(await api("/api/workshop/candidates", { kind: event.target.value, generation: bench.generation + 1 }));
});
$("#ws-materialize").onclick = (event) => guard(event.currentTarget, async () => {
  const plan = await api("/api/workshop/plan", candidateBody());
  view = "matter";
  document.querySelectorAll(".ws-viewbar button")
    .forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.view === view)));
  show(false);
  $("#ws-plan").hidden = false;
  $("#ws-plan").textContent = JSON.stringify(plan, null, 2);
});
$("#ws-save-design").onclick = (event) => guard(event.currentTarget, async () => {
  const candidate = chosen();
  const label = $("#ws-save-name").value.trim() || candidate.label || candidate.design_id;
  const answer = await api("/api/workshop/feedback", {
    ...candidateBody(), save_design: true, label,
    library_item_id: bench.openedLibraryItem || null,
    world_revision: bench.session && bench.session.world_revision !== "unopened-world"
      ? bench.session.world_revision : null,
  });
  if (answer.personal_library) {
    bench.personalLibrary = answer.personal_library;
    renderUserLibrary();
  }
  if (answer.bench_presets) bench.benchPresets = answer.bench_presets;
  const saved = answer.library_item || answer.design;
  if (answer.library_item) bench.openedLibraryItem = answer.library_item.item_id;
  $("#ws-save-status").textContent = saved ? `saved v${saved.version || saved.revision}` : "saved";
});
$("#ws-save-feedback").onclick = (event) => guard(event.currentTarget, async () => {
  const answer = await api("/api/workshop/feedback", {
    ...candidateBody(), rating: $("#ws-rating").value || null,
    note: $("#ws-note").value.trim(), selected: true,
  });
  $("#ws-note").value = "";
  $("#ws-rating").value = "";
  $("#ws-feedback-count").textContent = `${answer.kept} feedback records kept`;
});

function resize() {
  const rect = stage.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  renderer.setSize(rect.width, rect.height, false);
  camera.aspect = rect.width / rect.height;
  camera.updateProjectionMatrix();
  placeCamera();
}
new ResizeObserver(resize).observe(stage);
addEventListener("resize", resize);
function frame() { renderer.render(scene, camera); requestAnimationFrame(frame); }

async function start() {
  const params = new URLSearchParams(location.search);
  const libraryItem = params.get("library"), saved = params.get("design");
  const answer = await api("/api/workshop/open",
    libraryItem ? { library_item_id: libraryItem }
      : saved ? { saved_design_id: saved }
        : { kind: "table" });
  if (answer.library_item) bench.openedLibraryItem = answer.library_item.item_id;

  const picker = $("#ws-archetype");
  picker.replaceChildren();
  for (const made of answer.assemblies) {
    const option = make("option", { value: made.assembly }, made.assembly.replace("-", " "));
    option.title = made.about;
    picker.append(option);
  }
  picker.value = answer.kind;
  families(answer.families);
  savedDesigns(answer.saved_designs || []);
  bench.personalLibrary = answer.personal_library || [];
  bench.pricebook = answer.pricebook || null;
  bench.benchTests = answer.bench_tests || [];
  bench.benchPresets = answer.bench_presets || [];
  renderUserLibrary();
  took(answer);

  try {
    const remembered = await api("/api/workshop/remembered", {});
    $("#ws-feedback-count").textContent = remembered.kept ? `${remembered.kept} feedback records kept` : "";
    bench.personalLibrary = remembered.personal_library || bench.personalLibrary;
    bench.pricebook = remembered.pricebook || bench.pricebook;
    // Not the test list. This call is the saved history, which knows nothing
    // about which product is on the bench, so its catalog is the general one;
    // taking it here overwrote the product's own tests a moment after they
    // arrived, and the first thing you saw was a table offering to roll a cart.
    bench.benchPresets = remembered.bench_presets || bench.benchPresets;
    renderUserLibrary();
    renderBenchCatalog();
    show(false);
  } catch { /* history is optional */ }
}

placeCamera();
resize();
frame();
guard(null, start);
