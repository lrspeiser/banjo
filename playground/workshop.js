// Workshop Mode's view. It draws what the server's model returns and decides
// no geometry of its own: every size, centre and rotation in here came from
// mcp/workshop.py through /api/workshop/* (docs/workshop-next.md stage 1).
//
// This file used to be an inline module inside world.html with a second, private
// implementation of the whole design model. The two drifted -- the page dropped
// rotation at materialization, splayed its legs the wrong way and measured the
// support footprint from the leg centres -- which is why there is now one model
// and this is only its renderer.

import * as THREE from "/vendor/three.module.js";

const $ = (q) => document.querySelector(q);

// ---------------------------------------------------------------------------
// Talking to the model
// ---------------------------------------------------------------------------

let token = "";

async function api(path, body) {
  if (!token) {
    const status = await fetch("/api/status").then((r) => r.json());
    token = status.csrf_token || "";
  }
  const answer = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Banjo-Token": token },
    body: JSON.stringify(body || {}),
  });
  const said = await answer.json().catch(() => ({ error: "the bench gave no answer" }));
  if (!answer.ok) throw new Error(said.error || `${path} failed (${answer.status})`);
  return said;
}

// ---------------------------------------------------------------------------
// The scene
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
// The balance point, drawn where the model says it is rather than at a guessed
// fraction of the height, and a ring showing what holds the design up.
const balance = new THREE.Mesh(
  new THREE.SphereGeometry(0.025, 16, 12),
  new THREE.MeshBasicMaterial({ color: 0xffd166 }));
scene.add(balance);
const support = new THREE.LineSegments(
  new THREE.BufferGeometry(),
  new THREE.LineBasicMaterial({ color: 0xffd166, transparent: true, opacity: 0.55 }));
scene.add(support);

let yaw = 0.72, pitch = 0.42, distance = 3, dragging = false, px = 0, py = 0;
const target = new THREE.Vector3(0, 0.42, 0);

function place() {
  pitch = Math.max(-0.15, Math.min(1.25, pitch));
  camera.position.set(
    target.x + distance * Math.cos(pitch) * Math.sin(yaw),
    target.y + distance * Math.sin(pitch),
    target.z + distance * Math.cos(pitch) * Math.cos(yaw));
  camera.lookAt(target);
}

let reach = 1.5;  // the radius the current candidate needs on screen

// Pull back far enough for the whole candidate to fit, ACROSS as well as up:
// this pane is taller than it is wide, so its horizontal field of view is the
// narrower of the two and a wide table overflows if only the vertical is used.
function frame_it() {
  const up = THREE.MathUtils.degToRad(camera.fov) / 2;
  const across = Math.atan(Math.tan(up) * Math.max(0.2, camera.aspect));
  distance = Math.max(0.6, reach * 1.15 / Math.sin(Math.min(up, across)));
  place();
}

stage.addEventListener("pointerdown", (e) => {
  dragging = true; px = e.clientX; py = e.clientY; stage.setPointerCapture(e.pointerId);
});
stage.addEventListener("pointermove", (e) => {
  if (!dragging) return;
  yaw -= (e.clientX - px) * 0.008;
  pitch += (e.clientY - py) * 0.008;
  px = e.clientX; py = e.clientY;
  place();
});
stage.addEventListener("pointerup", () => { dragging = false; });
stage.addEventListener("pointercancel", () => { dragging = false; });
stage.addEventListener("wheel", (e) => {
  e.preventDefault();
  distance = Math.max(0.6, Math.min(9, distance * Math.exp(e.deltaY * 0.001)));
  place();
}, { passive: false });

// ---------------------------------------------------------------------------
// Drawing one candidate
// ---------------------------------------------------------------------------

const SKIN = { oak: 0x9a704d, pine: 0xc0a072, iron: 0x8d939b, steel: 0x9aa2ab,
  aluminium: 0xb8bfc6, glass: 0x9fc6d8, concrete: 0x9a9a95, rubber: 0x3c3c42,
  "alumina ceramic": 0xd9d4c8 };

let view = "wire";

function shapeFor(part) {
  const [w, h, d] = part.size_m;
  if (part.shape === "tapered") return new THREE.CylinderGeometry(w * 0.4, d * 0.62, h, 5, 1);
  if (part.shape === "cylinder") return new THREE.CylinderGeometry(w / 2, d / 2, h, 20, 1);
  return new THREE.BoxGeometry(w, h, d);
}

function clear() {
  for (const child of [...group.children]) {
    group.remove(child);
    if (child.geometry) child.geometry.dispose();
    if (child.material) child.material.dispose();
  }
}

function draw(candidate) {
  clear();
  for (const part of candidate.parts) {
    const geometry = shapeFor(part);
    // The server's rotation is Banjo's own convention -- built z first, so
    // Rx.Ry.Rz -- which is three.js's default Euler order, so these are the
    // same three numbers with no second convention in between.
    const spin = new THREE.Euler(
      THREE.MathUtils.degToRad(part.rotation_deg[0]),
      THREE.MathUtils.degToRad(part.rotation_deg[1]),
      THREE.MathUtils.degToRad(part.rotation_deg[2]), "XYZ");
    if (view === "wire") {
      const line = new THREE.LineSegments(
        new THREE.EdgesGeometry(geometry),
        new THREE.LineBasicMaterial({ color: 0xdce7f5 }));
      line.position.set(...part.center_m);
      line.rotation.copy(spin);
      group.add(line);
      geometry.dispose();
      continue;
    }
    const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
      color: view === "skin" ? (SKIN[part.material] ?? 0x9a704d) : 0x6f8194,
      roughness: view === "skin" ? 0.72 : 0.45,
      metalness: 0,
      transparent: view === "matter",
      opacity: view === "matter" ? 0.72 : 1,
    }));
    mesh.position.set(...part.center_m);
    mesh.rotation.copy(spin);
    group.add(mesh);
    if (view === "matter") {
      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(geometry),
        new THREE.LineBasicMaterial({ color: 0xd9e3ed, transparent: true, opacity: 0.45 }));
      edges.position.copy(mesh.position);
      edges.rotation.copy(mesh.rotation);
      group.add(edges);
    }
  }
  const m = candidate.measured;
  balance.position.set(...m.centre_of_mass_m);
  const feet = m.ground_contacts_m;
  const ring = [];
  const xs = feet.map((f) => f[0]), zs = feet.map((f) => f[1]);
  if (feet.length) {
    const box = [[Math.min(...xs), Math.min(...zs)], [Math.max(...xs), Math.min(...zs)],
                 [Math.max(...xs), Math.max(...zs)], [Math.min(...xs), Math.max(...zs)]];
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
  frame_it();
}

// ---------------------------------------------------------------------------
// The panes
// ---------------------------------------------------------------------------

let bench = { kind: "table", generation: 0, candidates: [], selected: 0, plans: {} };

function chosen() { return bench.candidates[bench.selected]; }

function cards() {
  const root = $("#variant-list");
  root.replaceChildren();
  const twins = {};
  for (const [id, fingerprint] of Object.entries(bench.plans)) {
    (twins[fingerprint] ||= []).push(id);
  }
  bench.candidates.forEach((candidate, i) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ws-card" + (i === bench.selected ? " selected" : "");
    const m = candidate.measured;
    const name = document.createElement("strong");
    name.textContent = candidate.label || candidate.design_id;
    const facts = document.createElement("small");
    const shared = twins[bench.plans[candidate.design_id]] || [];
    facts.textContent = `${m.mass_kg} kg · base ${m.support_footprint_m[0].toFixed(2)}`
      + ` × ${m.support_footprint_m[1].toFixed(2)} m · tips at ${m.tip_angle_deg}°`
      + (shared.length > 1 ? " · same object as a sibling once snapped" : "");
    if (shared.length > 1) button.classList.add("same-plan");
    button.append(name, facts);
    button.onclick = () => { bench.selected = i; cards(); show(); };
    root.append(button);
  });
}

function show() {
  const candidate = chosen();
  if (!candidate) return;
  draw(candidate);
  const m = candidate.measured;
  $("#ws-name").textContent = candidate.label || candidate.design_id;
  $("#ws-purpose").textContent = candidate.purpose;
  $("#ws-part-count").textContent = candidate.parts.length;
  $("#ws-mass").textContent = `${m.mass_kg} kg`;
  $("#ws-base").textContent =
    `${m.support_footprint_m[0].toFixed(2)} × ${m.support_footprint_m[1].toFixed(2)} m`;
  $("#ws-tip").textContent = `${m.tip_angle_deg}°`;

  const parts = $("#ws-parts");
  parts.replaceChildren();
  for (const part of candidate.parts) {
    const row = document.createElement("li");
    const name = document.createElement("strong");
    name.textContent = part.name;
    row.append(name, document.createTextNode(
      ` · ${part.role}${part.family ? ` · family ${part.family}` : ""}`
      + ` · ${part.mass_kg} kg`));
    parts.append(row);
  }

  const checks = $("#ws-checks");
  checks.className = "ws-note";
  const said = [];
  if (!m.stands_up) { checks.classList.add("bad"); said.push("It does not stand: its balance point is outside what holds it up."); }
  else said.push(`Balanced ${m.smallest_tip_margin_m} m inside its nearest edge, so it tips at ${m.tip_angle_deg}°.`);
  if (m.legs_not_under_the_top.length) {
    checks.classList.add("warn");
    said.push(`${m.legs_not_under_the_top.join(", ")} meet nothing: their heads are off the top.`);
  }
  said.push("Static-load and tip physics are specified but not yet measured by a trial.");
  checks.textContent = said.join(" ");
  $("#ws-plan").hidden = true;
}

function families(described) {
  const root = $("#ws-library");
  root.replaceChildren();
  for (const family of described) {
    const box = document.createElement("details");
    box.className = "ws-family";
    const head = document.createElement("summary");
    head.textContent = `${family.family} · ${family.parameters.length} settings`;
    const about = document.createElement("p");
    about.textContent = family.about;
    const list = document.createElement("dl");
    for (const p of family.parameters) {
      const dt = document.createElement("dt");
      dt.textContent = p.name;
      const dd = document.createElement("dd");
      dd.textContent = p.choices
        ? p.choices.join(", ")
        : `${p.low ?? "—"} to ${p.high ?? "—"} ${p.unit}`.trim();
      list.append(dt, dd);
    }
    box.append(head, about, list);
    root.append(box);
  }
}

async function fingerprints() {
  // Ask the model which candidates arrive as the same object once snapped, so
  // the bench can say so instead of offering six choices that make two things.
  bench.plans = {};
  await Promise.all(bench.candidates.map(async (candidate) => {
    try {
      const plan = await api("/api/workshop/plan", {
        kind: bench.kind, design_id: candidate.design_id,
        parameters: candidate.parameters,
      });
      bench.plans[candidate.design_id] = plan.fingerprint;
    } catch { /* a fingerprint is a nicety; the bench still works without it */ }
  }));
  cards();
}

function took(answer) {
  bench.kind = answer.kind;
  bench.generation = answer.generation;
  bench.candidates = answer.candidates;
  bench.selected = 0;
  bench.plans = {};
  cards();
  show();
  fingerprints();
}

async function guard(button, work) {
  const was = button && button.textContent;
  if (button) { button.disabled = true; }
  try {
    await work();
  } catch (err) {
    const checks = $("#ws-checks");
    checks.className = "ws-note bad";
    checks.textContent = String(err.message || err);
  } finally {
    if (button) { button.disabled = false; button.textContent = was; }
  }
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

document.querySelectorAll(".ws-viewbar button").forEach((button) => {
  button.onclick = () => {
    view = button.dataset.view;
    document.querySelectorAll(".ws-viewbar button")
      .forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
    show();
  };
});

$("#ws-more").onclick = (e) => guard(e.currentTarget, async () => {
  took(await api("/api/workshop/more", {
    kind: bench.kind, generation: bench.generation,
    parameters: chosen() ? chosen().parameters : {},
  }));
});

$("#ws-reset-variants").onclick = (e) => guard(e.currentTarget, async () => {
  took(await api("/api/workshop/candidates",
                 { kind: bench.kind, generation: bench.generation + 1 }));
});

$("#ws-archetype").onchange = (e) => guard(null, async () => {
  took(await api("/api/workshop/candidates",
                 { kind: e.target.value, generation: bench.generation + 1 }));
});

$("#ws-materialize").onclick = (e) => guard(e.currentTarget, async () => {
  const candidate = chosen();
  const plan = await api("/api/workshop/plan", {
    kind: bench.kind, design_id: candidate.design_id, parameters: candidate.parameters,
  });
  view = "matter";
  document.querySelectorAll(".ws-viewbar button")
    .forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === view)));
  show();
  $("#ws-plan").hidden = false;
  $("#ws-plan").textContent = JSON.stringify(plan, null, 2);
  const checks = $("#ws-checks");
  const snap = plan.snapping;
  if (snap.members_changed) {
    checks.className = "ws-note warn";
    checks.textContent = `${snap.members_changed} of ${plan.objects.length} members moved`
      + ` to land on the ${snap.cell_size_m * 1000} mm cell, the largest by`
      + ` ${(snap.largest_change_m * 1000).toFixed(0)} mm. Still ${plan.commit.status}.`;
  }
});

$("#ws-save-feedback").onclick = (e) => guard(e.currentTarget, async () => {
  const candidate = chosen();
  const answer = await api("/api/workshop/feedback", {
    kind: bench.kind, design_id: candidate.design_id, parameters: candidate.parameters,
    rating: $("#ws-rating").value || null, note: $("#ws-note").value.trim(), selected: true,
  });
  $("#ws-note").value = "";
  $("#ws-rating").value = "";
  $("#ws-feedback-count").textContent = `${answer.kept} kept on this bench`;
});

function resize() {
  const box = stage.getBoundingClientRect();
  if (!box.width || !box.height) return;
  renderer.setSize(box.width, box.height, false);
  camera.aspect = box.width / box.height;
  camera.updateProjectionMatrix();
  frame_it();
}
new ResizeObserver(resize).observe(stage);
addEventListener("resize", resize);

function frame() {
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}

async function start() {
  const answer = await api("/api/workshop/open", { kind: "table" });
  const picker = $("#ws-archetype");
  picker.replaceChildren();
  for (const made of answer.assemblies) {
    const option = document.createElement("option");
    option.value = made.assembly;
    option.textContent = made.assembly.replace("-", " ");
    option.title = made.about;
    picker.append(option);
  }
  picker.value = answer.kind;
  families(answer.families);
  took(answer);
  try {
    const kept = await api("/api/workshop/remembered", {});
    $("#ws-feedback-count").textContent = kept.kept ? `${kept.kept} kept on this bench` : "";
  } catch { /* the bench works without its history */ }
}

place();
resize();
frame();
guard(null, start);
