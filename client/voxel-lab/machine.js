import * as THREE from '/three.module.js';
import {mergeFrame, family, materialColor, heatTint, focusPoint, stationPoint, describeTime} from '/machine-view.mjs';

// The machine page. It asks the server to build a declaration, then shows
// what the engine measures, frame by frame. It never moves a body itself.
const $ = id => document.getElementById(id);
const view = $('view');
const renderer = new THREE.WebGLRenderer({antialias: true});
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
view.prepend(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x11222d);
scene.add(new THREE.HemisphereLight(0xdfefff, 0x2a3a2a, 1.1));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(4, 8, 5);
scene.add(sun);
const ground = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), new THREE.MeshStandardMaterial({color: 0x2b3a32, roughness: 1}));
ground.rotation.x = -Math.PI / 2;
scene.add(ground);
const grid = new THREE.GridHelper(40, 80, 0x46604f, 0x34483c);
grid.position.y = 0.0005;
scene.add(grid);
const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 200);
const target = new THREE.Vector3(1, 0.4, 0), goal = target.clone();
let azimuth = -0.55, elevation = 0.42, distance = 6.5;

let spec = null, machine = null, session = null, world = {seq: 0, t: 0, bodies: new Map()};
let playing = false, follow = true, readouts = {}, polling = 0, history = [], undo = [], lastFrame = null;
const meshes = new Map(), wires = [];
const materials = new Map();

function material(hex, kind) {
  const key = hex + ':' + kind;
  if (!materials.has(key)) materials.set(key, new THREE.MeshStandardMaterial(kind === 'glass' || kind === 'ice'
    ? {color: hex, roughness: .1, metalness: 0, transparent: true, opacity: .55}
    : {color: hex, roughness: kind === 'iron' || kind === 'aluminum' ? .45 : .8, metalness: kind === 'iron' || kind === 'aluminum' ? .5 : .02}));
  return materials.get(key);
}

function api(body) {
  return fetch('/api/machine', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)})
    .then(async r => {
      if (r.status === 401) { location.href = '/login'; throw Error('Log in first'); }
      const data = await r.json().catch(() => ({ok: false, error: 'The server answered with something that is not JSON'}));
      if (!r.ok || data.ok === false) { const e = Error(data.error || 'Request failed'); e.data = data; e.status = r.status; throw e; }
      return data;
    });
}

// ---- meshes: one per body, drawn from the engine's own record --------------
function makeMesh(b) {
  const hex = materialColor(b.material, b.color_rgba);
  const look = () => material(hex, b.material).clone();
  let mesh;
  if (b.shape === 'sphere') mesh = new THREE.Mesh(new THREE.SphereGeometry(b.dimensions_m[0] / 2, 28, 18), look());
  else if (b.shape === 'cone') mesh = new THREE.Mesh(new THREE.ConeGeometry(b.dimensions_m[0] / 2, b.dimensions_m[1], 24), look());
  else if (b.shape === 'compound' && Array.isArray(b.rigid_parts_local)) {
    // An exact rigid body made of boxes and cylinders, each about its centre
    // of mass, as the engine sends it.
    mesh = new THREE.Group();
    for (const part of b.rigid_parts_local) {
      const piece = new THREE.Mesh(part.shape === 'cylinder'
        ? new THREE.CylinderGeometry(part.dimensions_m[0] / 2, part.dimensions_m[0] / 2, part.dimensions_m[1], 20)
        : new THREE.BoxGeometry(...part.dimensions_m), look());
      piece.position.set(...part.center_local_m);
      const r = part.rotation_wxyz;
      piece.quaternion.set(r[1], r[2], r[3], r[0]);
      mesh.add(piece);
    }
    mesh.material = mesh.children[0].material;
    mesh.geometry = {dispose() { for (const c of mesh.children) c.geometry.dispose(); }};
  }
  else if (b.shape === 'hull' && b.cells_local_m && b.cells_local_m.length) {
    const cell = machine ? machine.cell_m : .02;
    mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(cell, cell, cell), look(), b.cells_local_m.length);
    const m = new THREE.Matrix4();
    b.cells_local_m.forEach((c, i) => mesh.setMatrixAt(i, m.makeTranslation(c[0], c[1], c[2])));
  } else mesh = new THREE.Mesh(new THREE.BoxGeometry(...b.dimensions_m), look());
  mesh.userData = {revision: b.revision, cells: b.cells_local_m ? b.cells_local_m.length : 0, base: hex};
  scene.add(mesh);
  return mesh;
}

function place(mesh, b) {
  mesh.position.set(...b.position_m);
  const q = b.orientation_wxyz;
  mesh.quaternion.set(q[1], q[2], q[3], q[0]);
}

function syncMeshes(changed) {
  for (const [name, mesh] of meshes) if (!world.bodies.has(name)) { scene.remove(mesh); mesh.geometry.dispose(); meshes.delete(name); }
  for (const b of changed) {
    let mesh = meshes.get(b.name);
    const cells = b.cells_local_m ? b.cells_local_m.length : 0;
    if (mesh && (mesh.userData.revision !== b.revision || mesh.userData.cells !== cells)) {
      scene.remove(mesh); mesh.geometry.dispose(); meshes.delete(b.name); mesh = null;
    }
    if (!mesh) { mesh = makeMesh(b); meshes.set(b.name, mesh); }
    place(mesh, b);
  }
  const heat = new Map((readouts.heat || []).map(h => [h.name, h.temperature_k]));
  $('heat-legend').hidden = !(readouts.heat || []).some(h => h.temperature_k > 320);
  for (const [name, mesh] of meshes) {
    const k = heat.get(name) ?? heat.get(family(name));
    mesh.material.color.setHex(heatTint(mesh.userData.base, k));
    mesh.material.emissive?.setHex(k > 600 ? heatTint(0x000000, k) & 0x7f3f1f : 0);
  }
}

// Wires: from the battery's part, past the switch's pin, to the part the coil
// is wound on. Bright while the engine reports the switch closed.
function syncWires() {
  for (const w of wires) { scene.remove(w.line); w.line.geometry.dispose(); }
  wires.length = 0;
  if (!machine) return;
  for (const c of machine.circuits) {
    const battery = machine.batteries.find(b => b.name === c.battery);
    const hinge = c.switch ? machine.joints.find(j => j.name === c.switch.hinge) : null;
    const geometry = new THREE.BufferGeometry();
    const line = new THREE.Line(geometry, new THREE.LineBasicMaterial({color: 0x6b7680}));
    scene.add(line);
    wires.push({line, from: battery && battery.in, via: hinge && hinge.at_m, to: c.coil.heats, name: c.name});
  }
}

// The ground the engine built: its own heights, one per column.
let terrain = null, water = null, parcels = null;
// Poured water in the air: one small sphere per parcel the engine carries,
// where the engine says it is (millimetres).
function syncParcels(p) {
  if (!p) return;
  const xyz = p.xyz_mm || [], count = Math.floor(xyz.length / 3);
  if (!parcels || parcels.instanceMatrix.count < count) {
    if (parcels) { scene.remove(parcels); parcels.geometry.dispose(); }
    const capacity = Math.max(256, 2 * count);
    parcels = new THREE.InstancedMesh(new THREE.SphereGeometry(p.r_m || .018, 10, 8),
      new THREE.MeshStandardMaterial({color: 0x3f8fd8, transparent: true, opacity: .85, roughness: .15}), capacity);
    parcels.frustumCulled = false;
    scene.add(parcels);
  }
  const m = new THREE.Matrix4();
  for (let k = 0; k < count; k++) parcels.setMatrixAt(k, m.makeTranslation(xyz[3 * k] / 1000, xyz[3 * k + 1] / 1000, xyz[3 * k + 2] / 1000));
  parcels.count = count;
  parcels.instanceMatrix.needsUpdate = true;
}
function decodeFloats(b64) {
  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  return new Float32Array(bytes.buffer, 0, bytes.length / 4);
}
function syncGround(view) {
  if (terrain) { scene.remove(terrain); terrain.geometry.dispose(); terrain = null; }
  ground.visible = grid.visible = !view;
  if (!view || !view.grid) return;
  const g = view.grid, heights = decodeFloats(view.heights_b64);
  const width = (g.nx - 1) * g.cell_m, depth = (g.nz - 1) * g.cell_m;
  const geometry = new THREE.PlaneGeometry(width, depth, g.nx - 1, g.nz - 1);
  geometry.rotateX(-Math.PI / 2);
  const pos = geometry.attributes.position;
  // After the turn, vertex (i, j) is column i along x and row j along z.
  for (let j = 0; j < g.nz; j++) for (let i = 0; i < g.nx; i++) pos.setY(j * g.nx + i, heights[j * g.nx + i]);
  geometry.computeVertexNormals();
  terrain = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({color: 0x4a5b3c, roughness: 1, flatShading: true}));
  terrain.position.set(g.x0_m + width / 2, 0, g.z0_m + depth / 2);
  scene.add(terrain);
  terrain.userData.grid = g;
}
// The water: each wet column's surface, in millimetres above base_m.
function syncWater(w) {
  if (water) { scene.remove(water); water.geometry.dispose(); water = null; }
  if (!w || !terrain || !w.box || !w.box[2] || !w.surface_mm_b64) return;
  const g = terrain.userData.grid, [i0, j0, ni, nj] = w.box;
  const bytes = Uint8Array.from(atob(w.surface_mm_b64), c => c.charCodeAt(0));
  const mm = new Uint16Array(bytes.buffer, 0, bytes.length / 2);
  const wet = [];
  for (let j = 0; j < nj; j++) for (let i = 0; i < ni; i++) {
    const v = mm[j * ni + i];
    if (v) wet.push([g.x0_m + (i0 + i) * g.cell_m, w.base_m + v / 1000, g.z0_m + (j0 + j) * g.cell_m]);
  }
  if (!wet.length) return;
  const tile = new THREE.PlaneGeometry(g.cell_m, g.cell_m);
  tile.rotateX(-Math.PI / 2);
  water = new THREE.InstancedMesh(tile, new THREE.MeshStandardMaterial({color: 0x3f8fd8, transparent: true, opacity: .72, roughness: .15}), wet.length);
  const m = new THREE.Matrix4();
  wet.forEach((p, k) => water.setMatrixAt(k, m.makeTranslation(p[0], p[1], p[2])));
  scene.add(water);
}

// Ropes and springs: a line between their two attachment points, each fixed
// in its body's own frame and carried by that body's measured pose. Hidden
// once the engine reports the joint gone.
const ropes = [];
function syncRopes() {
  for (const r of ropes) { scene.remove(r.line); r.line.geometry.dispose(); }
  ropes.length = 0;
  if (!machine) return;
  const local = (name, at) => {
    const b = world.bodies.get(name); if (!b) return null;
    const q = new THREE.Quaternion(b.orientation_wxyz[1], b.orientation_wxyz[2], b.orientation_wxyz[3], b.orientation_wxyz[0]);
    return new THREE.Vector3(...at).sub(new THREE.Vector3(...b.position_m)).applyQuaternion(q.invert());
  };
  for (const j of machine.joints) {
    if (j.kind !== 'tie' && j.kind !== 'spring') continue;
    const a = local(j.a, j.at_m), b = local(j.b, j.at_b_m);
    if (!a || !b) continue;
    const line = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({color: j.kind === 'tie' ? 0xd8c9a3 : 0x9fd3ff}));
    scene.add(line);
    ropes.push({line, name: j.name, a: j.a, b: j.b, localA: a, localB: b});
  }
}
const drumLines = new Map();
function updateRopes() {
  // A rope on a drum: from where the engine says it leaves the drum to where
  // it meets its load.
  for (const j of (readouts.joints || []).filter(j => j.kind === 'drum' && j.leaves && j.meets)) {
    let line = drumLines.get(j.name);
    if (!line) { line = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({color: 0xd8c9a3})); scene.add(line); drumLines.set(j.name, line); }
    line.geometry.setFromPoints([new THREE.Vector3(...j.leaves), new THREE.Vector3(...j.meets)]);
    line.visible = j.attached !== false;
  }
  const gone = new Set((readouts.joints || []).filter(j => j.attached === false).map(j => j.name));
  const at = (name, v) => {
    const b = world.bodies.get(name); if (!b) return null;
    const q = new THREE.Quaternion(b.orientation_wxyz[1], b.orientation_wxyz[2], b.orientation_wxyz[3], b.orientation_wxyz[0]);
    return v.clone().applyQuaternion(q).add(new THREE.Vector3(...b.position_m));
  };
  for (const r of ropes) {
    const pa = at(r.a, r.localA), pb = at(r.b, r.localB);
    r.line.visible = Boolean(pa && pb) && !gone.has(r.name);
    if (r.line.visible) r.line.geometry.setFromPoints([pa, pb]);
  }
}

function updateWires() {
  updateRopes();
  for (const w of wires) {
    const at = name => { const b = world.bodies.get(name); return b ? b.position_m : null; };
    const pts = [at(w.from), w.via, at(w.to)].filter(Boolean).map(p => new THREE.Vector3(...p));
    w.line.geometry.setFromPoints(pts);
    const live = (readouts.circuits || []).find(c => c.name === w.name);
    w.line.material.color.setHex(live && live.closed ? 0xffd34d : 0x6b7680);
  }
}

// ---- the panel ---------------------------------------------------------------
function renderStations() {
  const list = $('stations'); list.replaceChildren();
  const live = readouts.stations || [];
  const current = live.findIndex((s, i) => !s.done && machine.stations[i] && machine.stations[i].done_when);
  machine.stations.forEach((s, i) => {
    const li = document.createElement('li');
    li.dataset.index = String(i); li.title = 'Look at this station';
    const state = live[i];
    if (state && state.done) li.className = 'done'; else if (i === current && playing) li.className = 'current';
    const head = document.createElement('div'); head.className = 'head';
    const title = document.createElement('span');
    title.textContent = `${i + 1}. ${s.title}` + (state && state.done ? ` ✓ ${describeTime(state.at_s)}` : '');
    const badge = document.createElement('span');
    const kind = (s.maturity || 'calculated').replace(' ', '-');
    badge.className = 'badge ' + kind; badge.textContent = s.maturity || 'calculated';
    head.append(title, badge);
    const shows = document.createElement('div'); shows.className = 'shows'; shows.textContent = s.shows || '';
    const law = document.createElement('div'); law.className = 'law'; law.textContent = s.law || '';
    li.append(head, shows, law);
    list.append(li);
  });
}

function pair(dl, label, value) {
  const div = document.createElement('div'), dt = document.createElement('dt'), dd = document.createElement('dd');
  dt.textContent = label; dd.textContent = value; div.append(dt, dd); dl.append(div);
}

function renderReadings(frame) {
  const dl = $('readings'); dl.replaceChildren();
  pair(dl, 'World time', describeTime(frame.t));
  for (const c of readouts.circuits || []) {
    pair(dl, `${c.name}: switch`, c.closed === null ? 'always closed' : c.closed ? 'closed' : 'open');
    pair(dl, `${c.name}: current`, `${(c.current_a || 0).toFixed(1)} A · ${(c.coil_w || 0).toFixed(0)} W into ${c.heats}`);
    pair(dl, `${c.name}: energy`, `${((c.source_j || 0) / 1000).toFixed(1)} kJ from the battery, ${((c.into_body_j || 0) / 1000).toFixed(1)} kJ into ${c.heats}`);
  }
  for (const h of (readouts.heat || []).slice(0, 4))
    pair(dl, h.name, `${h.temperature_k.toFixed(0)} K` + (h.reacting ? ' · burning' : '') + (h.heater_w ? ` · ${h.heater_w.toFixed(0)} W in` : ''));
  if (readouts.pour)
    pair(dl, 'Poured water', `${readouts.pour.poured_l.toFixed(1)} L poured, ${readouts.pour.landed_l.toFixed(1)} L in the stream, ${readouts.pour.in_air_l.toFixed(1)} L falling`);
  for (const j of (readouts.joints || []).filter(j => j.kind === 'hinge').slice(0, 3))
    pair(dl, j.name, `${(j.degrees || 0).toFixed(1)}°`);
  const pieces = [...world.bodies.keys()].filter(n => n.includes(' piece ')).length;
  if (pieces) pair(dl, 'Broken pieces', String(pieces));
  pair(dl, 'Calculation', `${frame.pace.compute_s.toFixed(1)} s of engine time, ${frame.pace.fracture_s.toFixed(1)} s of it breaking`);
}

function addEvents(events) {
  const ol = $('events');
  for (const e of events) {
    const li = document.createElement('li');
    li.textContent = `${describeTime(e.t)} · ${e.text}`;
    ol.prepend(li);
  }
  while (ol.children.length > 80) ol.lastChild.remove();
}

function renderClock(frame) {
  const behind = frame.pace.behind_s;
  let text = `World ${describeTime(frame.t)} · ${frame.speed}× · ` + (frame.error ? 'stopped: ' + frame.error :
    frame.playing ? 'calculating live' : frame.t > 0 ? 'paused' : 'ready: press Start');
  if (frame.playing && behind > .25) text += ` · ${behind.toFixed(1)} s behind real time while the engine works`;
  $('clock').textContent = text;
  $('start').textContent = frame.playing ? 'Pause' : frame.t > 0 ? 'Continue' : 'Start';
}

// Station labels float over the parts each station watches.
function renderLabels() {
  const box = $('labels'); box.replaceChildren();
  if (!machine) return;
  const rect = renderer.domElement.getBoundingClientRect();
  const live = readouts.stations || [];
  machine.stations.forEach((s, i) => {
    const names = new Set(s.focus || []);
    const pts = [...world.bodies.values()].filter(b => names.has(b.name) || names.has(family(b.name))).map(b => b.position_m);
    if (!pts.length) return;
    const p = new THREE.Vector3(...pts[0]).add(new THREE.Vector3(0, .35, 0)).project(camera);
    if (p.z > 1 || Math.abs(p.x) > 1.1 || Math.abs(p.y) > 1.1) return;
    const el = document.createElement('div');
    el.className = 'station-label' + (live[i] && live[i].done ? ' done' : '');
    el.textContent = `${i + 1} ${s.title}`;
    el.style.left = `${(p.x + 1) / 2 * rect.width}px`;
    el.style.top = `${(1 - p.y) / 2 * rect.height}px`;
    box.append(el);
  });
}

// ---- building and running --------------------------------------------------------
async function build(next, start) {
  const mine = ++polling;
  if (session) api({op: 'close', session}).catch(() => {});
  session = null; playing = false;
  $('clock').textContent = 'Building in the engine…';
  for (const [, mesh] of meshes) { scene.remove(mesh); mesh.geometry.dispose(); }
  meshes.clear(); $('events').replaceChildren();
  try {
    const opened = await api({op: 'open', spec: next});
    if (mine !== polling) { api({op: 'close', session: opened.session}).catch(() => {}); return; }
    spec = next; machine = opened.machine; session = opened.session; readouts = opened.readouts || {};
    world = mergeFrame({seq: 0, t: 0, bodies: new Map()}, opened);
    $('title').textContent = machine.title;
    $('spec').value = JSON.stringify(spec, null, 1);
    const notes = $('notes'); notes.replaceChildren();
    for (const n of machine.notes || []) { const li = document.createElement('li'); li.textContent = n; notes.append(li); }
    for (const [, line] of drumLines) { scene.remove(line); line.geometry.dispose(); }
    drumLines.clear();
    if (parcels) { scene.remove(parcels); parcels.geometry.dispose(); parcels = null; }
    syncGround(opened.ground); syncWater(opened.water); syncParcels(opened.parcels);
    syncMeshes([...world.bodies.values()]); syncWires(); syncRopes(); updateWires(); renderStations(); renderReadings(opened); renderClock(opened);
    frameCamera();
    if (start) await setPlaying(true);
    poll(mine);
  } catch (e) {
    $('clock').textContent = 'Could not build: ' + e.message;
    if (e.data && e.data.problems) addEvents(e.data.problems.map(text => ({t: 0, text})));
    throw e;
  }
}

async function setPlaying(run) {
  if (!session) return;
  const frame = await api({op: 'play', session, running: run, speed: Number($('speed').value)});
  playing = frame.playing; renderClock(frame);
  if (wake) wake();
}

// At most 20 frame requests a second while running and one a second while
// paused: each request is its own connection to this server, and asking as
// fast as frames arrive exhausted the machine's sockets.
const RUNNING_MS = 50, PAUSED_MS = 1000;
let wake = null;
async function poll(mine) {
  let last = 0;
  while (mine === polling && session) {
    const gap = (playing ? RUNNING_MS : PAUSED_MS) - (performance.now() - last);
    if (gap > 0) await new Promise(r => { wake = r; setTimeout(r, gap); });
    wake = null;
    if (mine !== polling || !session) return;
    last = performance.now();
    try {
      const frame = await api({op: 'frame', session, after: world.seq, wait_ms: playing ? 120 : 0});
      if (mine !== polling) return;
      const changed = frame.bodies;
      world = mergeFrame(world, frame);
      readouts = frame.readouts || readouts; playing = frame.playing; lastFrame = frame;
      syncMeshes(changed.map(b => world.bodies.get(b.name)));
      if (frame.water) syncWater(frame.water);
      if (frame.parcels) syncParcels(frame.parcels);
      updateWires(); addEvents(frame.events); renderStations(); renderReadings(frame); renderClock(frame);
    } catch (e) {
      if (e.status === 410) { $('clock').textContent = 'This machine stopped running on the server; press Set up again'; session = null; return; }
      $('clock').textContent = 'Connection problem: ' + e.message;
      await new Promise(r => setTimeout(r, 1500));
    }
  }
}

// ---- camera -------------------------------------------------------------------
function frameCamera() {
  const pts = [...world.bodies.values()].map(b => b.position_m);
  if (!pts.length) return;
  const lo = [0, 1, 2].map(i => Math.min(...pts.map(p => p[i]))), hi = [0, 1, 2].map(i => Math.max(...pts.map(p => p[i])));
  goal.set((lo[0] + hi[0]) / 2, Math.max(.3, (lo[1] + hi[1]) / 3), (lo[2] + hi[2]) / 2);
  target.copy(goal);
  const span = Math.max(hi[0] - lo[0], hi[2] - lo[2], hi[1] - lo[1]);
  // Far enough that the whole width fits the narrower of the two view angles.
  const half = Math.min(camera.fov * Math.PI / 360, Math.atan(Math.tan(camera.fov * Math.PI / 360) * camera.aspect));
  distance = Math.min(40, Math.max(3, .6 * span / Math.tan(half)));
  azimuth = -.25; elevation = .38;
}

function resize() {
  const w = view.clientWidth, h = view.clientHeight;
  renderer.setSize(w, h, false); camera.aspect = w / Math.max(1, h); camera.updateProjectionMatrix();
}
addEventListener('resize', resize);

const pointers = new Map();
let pinch = 0;
renderer.domElement.addEventListener('pointerdown', e => { pointers.set(e.pointerId, [e.clientX, e.clientY]); renderer.domElement.setPointerCapture(e.pointerId); });
renderer.domElement.addEventListener('pointerup', e => { pointers.delete(e.pointerId); pinch = 0; });
renderer.domElement.addEventListener('pointercancel', e => { pointers.delete(e.pointerId); pinch = 0; });
renderer.domElement.addEventListener('pointermove', e => {
  const last = pointers.get(e.pointerId); if (!last) return;
  if (pointers.size === 2) {
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
    const [a, b] = [...pointers.values()], gap = Math.hypot(a[0] - b[0], a[1] - b[1]);
    if (pinch) distance = Math.min(40, Math.max(.4, distance * pinch / gap));
    pinch = gap; return;
  }
  azimuth -= (e.clientX - last[0]) * .006;
  elevation = Math.min(1.45, Math.max(.05, elevation + (e.clientY - last[1]) * .006));
  pointers.set(e.pointerId, [e.clientX, e.clientY]);
});
renderer.domElement.addEventListener('wheel', e => { e.preventDefault(); distance = Math.min(40, Math.max(.4, distance * Math.exp(e.deltaY * .001))); }, {passive: false});

function render() {
  requestAnimationFrame(render);
  if (follow && machine && playing) {
    const f = focusPoint(readouts.stations, machine.stations, world.bodies);
    if (f) { goal.set(f.at[0], Math.max(.25, f.at[1]), f.at[2]); distance += (Math.max(2.2, Math.min(distance, 3.4)) - distance) * .02; }
  }
  target.lerp(goal, .05);
  camera.position.set(target.x + distance * Math.cos(elevation) * Math.sin(azimuth), target.y + distance * Math.sin(elevation),
                      target.z + distance * Math.cos(elevation) * Math.cos(azimuth));
  camera.lookAt(target);
  renderer.render(scene, camera);
  renderLabels();
}

// ---- controls -----------------------------------------------------------------
$('start').addEventListener('click', () => setPlaying(!playing).catch(e => { $('clock').textContent = e.message; }));
$('reset').addEventListener('click', () => build(spec).catch(() => {}));
$('speed').addEventListener('change', () => { if (session) api({op: 'play', session, running: playing, speed: Number($('speed').value)}).catch(() => {}); });
$('follow').addEventListener('click', () => { follow = !follow; $('follow').setAttribute('aria-pressed', String(follow)); if (!follow) goal.copy(target); });
// Press a station to look at it. The list is drawn again with every frame, so
// the press is taken on the list itself, as it starts, not as a click.
$('stations').addEventListener('pointerdown', e => {
  const li = e.target.closest('li[data-index]');
  const at = li && machine ? stationPoint(machine.stations[Number(li.dataset.index)], world.bodies) : null;
  if (!at) return;
  follow = false; $('follow').setAttribute('aria-pressed', 'false');
  goal.set(at[0], Math.max(.25, at[1]), at[2]); distance = 2.6;
});
$('build-json').addEventListener('click', () => {
  let next;
  try { next = JSON.parse($('spec').value); } catch (e) { $('clock').textContent = 'That is not valid JSON: ' + e.message; return; }
  undo.push(spec); $('undo').disabled = false;
  build(next).catch(() => {});
});
$('undo').addEventListener('click', () => {
  const back = undo.pop(); $('undo').disabled = !undo.length;
  if (back) build(back).catch(() => {});
});

function say(kind, text) {
  const li = document.createElement('li'); li.className = kind; li.textContent = text; $('chat-log').prepend(li);
}

$('chat-form').addEventListener('submit', async e => {
  e.preventDefault();
  const message = $('message').value.trim();
  if (!message) return;
  $('send').disabled = true; $('chat-status').textContent = 'The model is writing a declaration; the server checks it and rehearses it once in the engine. This takes up to a few minutes…';
  say('you', message);
  try {
    const r = await api({op: 'chat', message, spec, history});
    history.push({role: 'user', text: message}, {role: 'assistant', text: r.reply});
    history = history.slice(-6);
    if (!r.buildable) {
      say('refused', r.reply + ' — The server could not build it: ' + r.problems.join('; '));
      $('chat-status').textContent = 'Nothing was built. You can rephrase, or edit the machine as data.';
      $('spec').value = JSON.stringify(r.spec, null, 1);
      return;
    }
    say('model', r.reply + ` (${r.parts} parts, checked in ${r.attempts} ${r.attempts === 1 ? 'try' : 'tries'})`);
    if (r.rehearsal && r.rehearsal.new_stations.length) say(r.rehearsal.new_stations.every(s => s.happened) ? 'model' : 'refused',
      'Rehearsed once in the engine: ' + r.rehearsal.new_stations.map(s => s.title + (s.happened ? ` happened at ${describeTime(s.at_s)}` : ' did not happen')).join('; ') + '.');
    undo.push(spec); $('undo').disabled = false;
    $('message').value = '';
    $('chat-status').textContent = 'Building it in the engine…';
    await build(r.spec, true);
    $('chat-status').textContent = 'Built. The engine is calculating it now.';
  } catch (err) {
    say('refused', err.message);
    $('chat-status').textContent = '';
  } finally { $('send').disabled = false; }
});

fetch('/api/checkpoint').then(r => r.ok ? r.json() : null).then(c => {
  if (!c) return;
  $('build').textContent = `${(c.website_revision || 'unknown').slice(0, 7)}${c.local_changes ? ' + local edits' : ''}`;
}).catch(() => {});

resize(); render();
fetch('/machine-default.json').then(r => r.json()).then(d => build(d)).catch(e => { $('clock').textContent = 'Could not load the machine: ' + e.message; });
