import * as THREE from '/three.module.js';
import {mergeFrame, family, materialColor, heatTint, focusPoint, stationPoint, describeTime, beamSegments} from '/machine-view.mjs';

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
// Shadows from the key light: where the machine has a sun, the shade its
// parts cast is where the engine's sunlight does not reach (drawn, not
// measured: the panel readings are the engine's).
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, {left: -5, right: 5, top: 5, bottom: -5, near: .5, far: 40});
sun.shadow.bias = -.0005; sun.shadow.normalBias = .02;
// The machine's sun itself, low or high in the sky where it stands.
const sunDisc = new THREE.Mesh(new THREE.SphereGeometry(.9, 24, 16), new THREE.MeshBasicMaterial({color: 0xffe9a0, fog: false}));
sunDisc.visible = false;
scene.add(sunDisc);
const ground = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), new THREE.MeshStandardMaterial({color: 0x2b3a32, roughness: 1}));
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
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
const stripeLook = new THREE.MeshStandardMaterial({color: 0xf1d38a, roughness: .7, metalness: 0});

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
      if (part.shape === 'cylinder') {
        // A pale stripe from the hub to the rim, through both faces, so a
        // turning wheel shows how far it has turned.
        const radius = part.dimensions_m[0] / 2;
        const stripe = new THREE.Mesh(new THREE.BoxGeometry(.85 * radius, part.dimensions_m[1] * 1.04, .14 * radius), stripeLook);
        stripe.position.x = .45 * radius;
        piece.add(stripe);
      }
      mesh.add(piece);
    }
    mesh.material = mesh.children[0].material;
    mesh.geometry = {dispose() { mesh.traverse(c => { if (c !== mesh && c.geometry) c.geometry.dispose(); }); }};
  }
  else if (b.shape === 'hull' && b.cells_local_m && b.cells_local_m.length) {
    const cell = machine ? machine.cell_m : .02;
    mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(cell, cell, cell), look(), b.cells_local_m.length);
    const m = new THREE.Matrix4();
    b.cells_local_m.forEach((c, i) => mesh.setMatrixAt(i, m.makeTranslation(c[0], c[1], c[2])));
  } else mesh = new THREE.Mesh(new THREE.BoxGeometry(...b.dimensions_m), look());
  mesh.userData = {revision: b.revision, cells: b.cells_local_m ? b.cells_local_m.length : 0, base: hex};
  mesh.traverse(o => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
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
// is wound on or the motor's hinge. Bright while the engine reports the
// switch closed.
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
    const driven = c.motor ? machine.joints.find(j => j.name === c.motor.hinge) : null;
    wires.push({line, from: battery && battery.in, via: hinge && hinge.at_m,
                to: c.coil ? c.coil.heats : null, toPoint: driven && driven.at_m, name: c.name});
  }
}

// Light (docs/optics-checkpoint.md): the rays the engine last traced, as lines
// as bright as the power it measured on them, and each light sensor as a small
// disc that glows with what it reads. The key light comes from where the
// machine's sun is.
let beams = null;
const sensors = new Map();
function syncLight() {
  const light = readouts.light;
  const {positions, colors, legs} = beamSegments(light && light.paths);
  if (!beams) {
    // Opaque, so the glass is drawn over them and they show through it.
    beams = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({vertexColors: true}));
    beams.frustumCulled = false;
    scene.add(beams);
  }
  beams.geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  beams.geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  beams.geometry.setDrawRange(0, legs * 2);
  beams.visible = legs > 0;
  const seen = new Set();
  for (const c of (light && light.photocells) || []) {
    if (!c.at_m) continue;
    seen.add(c.name);
    let disc = sensors.get(c.name);
    if (!disc) {
      const r = Math.max(.006, Math.sqrt((c.area_m2 || 1e-4) / Math.PI));
      disc = new THREE.Mesh(new THREE.CircleGeometry(r, 20), new THREE.MeshBasicMaterial({color: 0x334455, side: THREE.DoubleSide}));
      scene.add(disc); sensors.set(c.name, disc);
    }
    const n = new THREE.Vector3(...(c.normal || [0, 1, 0])).normalize();
    disc.position.set(...c.at_m).addScaledVector(n, .002);
    disc.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), n);
    disc.material.color.setHex(c.power_w > 0 ? 0xffe066 : 0x334455);
  }
  for (const [name, disc] of sensors) if (!seen.has(name)) { scene.remove(disc); disc.geometry.dispose(); sensors.delete(name); }
}
function placeSun() {
  const s = machine && (machine.sun || (machine.light && machine.light.sun));
  if (!s) { sun.position.set(4, 8, 5); sunDisc.visible = false; return; }
  const el = s.elevation_deg * Math.PI / 180, az = s.azimuth_deg * Math.PI / 180;
  const toward = [Math.cos(el) * Math.sin(az), Math.sin(el), Math.cos(el) * Math.cos(az)];
  sun.position.set(...toward.map(v => 12 * v));
  sunDisc.position.set(...toward.map(v => 30 * v));
  sunDisc.visible = true;
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
    if (j.kind !== 'tie' && j.kind !== 'spring' && j.kind !== 'pulley') continue;
    const a = local(j.a, j.at_m), b = local(j.b, j.at_b_m);
    if (!a || !b) continue;
    const line = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({color: j.kind === 'spring' ? 0x9fd3ff : 0xd8c9a3}));
    scene.add(line);
    // A pulley's rope runs up over its two fixed points.
    const over = j.kind === 'pulley' ? [new THREE.Vector3(...j.over_a_m), new THREE.Vector3(...j.over_b_m)] : [];
    ropes.push({line, name: j.name, a: j.a, b: j.b, localA: a, localB: b, over});
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
    if (r.line.visible) r.line.geometry.setFromPoints([pa, ...r.over, pb]);
  }
}

// Goal zones (a station done when a part is inside a box): drawn as a
// translucent green box where the engine will look.
const zones = [];
function syncZones() {
  for (const z of zones) { scene.remove(z); z.geometry.dispose(); }
  zones.length = 0;
  for (const s of machine?.stations || []) {
    const z = s.done_when && s.done_when.in_zone;
    if (!z) continue;
    const box = new THREE.Mesh(new THREE.BoxGeometry(...z.size_m),
      new THREE.MeshStandardMaterial({color: 0x3fbf6f, transparent: true, opacity: .22, depthWrite: false}));
    box.position.set(...z.at_m);
    box.add(new THREE.LineSegments(new THREE.EdgesGeometry(box.geometry), new THREE.LineBasicMaterial({color: 0x5fe08f})));
    scene.add(box); zones.push(box);
  }
}

// Gas pushing a piston (steam under a piston, a cannon's breech): its column,
// where the engine says it is, tinted by its measured temperature. Not drawn
// once it is open to the air.
const gasColumns = new Map();
function updateGas() {
  const live = new Set();
  for (const g of readouts.gas || []) {
    if (!g.piston || g.vent_open || !(g.area_m2 > 0) || !(g.volume_m3 > 0) || !g.axis) continue;
    live.add(g.name);
    let mesh = gasColumns.get(g.name);
    if (!mesh) {
      mesh = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1),
        new THREE.MeshStandardMaterial({color: 0xdfe8f0, transparent: true, opacity: .35, roughness: .9, depthWrite: false}));
      scene.add(mesh); gasColumns.set(g.name, mesh);
    }
    const side = Math.sqrt(g.area_m2), length = g.volume_m3 / g.area_m2;
    const axis = new THREE.Vector3(...g.axis).normalize();
    mesh.scale.set(side, length, side);
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), axis);
    mesh.position.copy(new THREE.Vector3(...g.base_m).addScaledVector(axis, length / 2));
    mesh.material.color.setHex(heatTint(0xdfe8f0, g.temperature_k || 293));
  }
  for (const [name, mesh] of gasColumns) if (!live.has(name)) { scene.remove(mesh); mesh.geometry.dispose(); gasColumns.delete(name); }
}

function updateWires() {
  updateRopes();
  updateGas();
  for (const w of wires) {
    const at = name => { const b = world.bodies.get(name); return b ? b.position_m : null; };
    const pts = [at(w.from), w.via, w.to ? at(w.to) : w.toPoint].filter(Boolean).map(p => new THREE.Vector3(...p));
    w.line.geometry.setFromPoints(pts);
    const live = (readouts.circuits || []).find(c => c.name === w.name);
    const flowing = live && (live.closed || (live.closed === null && Math.abs(live.current_a || 0) > 1e-3));
    w.line.material.color.setHex(flowing ? 0xffd34d : 0x6b7680);
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
    pair(dl, `${c.name}: current`, `${(c.current_a || 0).toFixed(2)} A` + (c.heats ? ` · ${(c.coil_w || 0).toFixed(0)} W into ${c.heats}` : '') +
      (c.drives ? ` · driving the motor on ${c.drives}` : ''));
    pair(dl, `${c.name}: energy`, `${((c.source_j || 0) / 1000).toFixed(2)} kJ from the battery` +
      (c.heats ? `, ${((c.into_body_j || 0) / 1000).toFixed(1)} kJ into ${c.heats}` : ''));
  }
  for (const h of (readouts.heat || []).slice(0, 4))
    pair(dl, h.name, `${h.temperature_k.toFixed(0)} K` + (h.reacting ? ' · burning' : '') + (h.heater_w ? ` · ${h.heater_w.toFixed(0)} W in` : ''));
  for (const c of readouts.cuts || [])
    pair(dl, `${c.blade} → ${c.target}`, c.through ? `cut through: ${(c.area_mm2 || 0).toFixed(0)} mm² for ${(c.work_j || 0).toFixed(2)} J`
      : `${c.kind}: ${(c.area_mm2 || 0).toFixed(0)} mm² cut, ${(c.work_j || 0).toFixed(2)} J`);
  for (const g of readouts.gas || [])
    pair(dl, g.name, `${(g.pressure_kpa || 0).toFixed(0)} kPa · ${(g.temperature_k || 0).toFixed(0)} K` +
      (g.piston ? ` · ${g.piston} pushed ${((g.stroke_m || 0) * 1000).toFixed(0)} mm` : ''));
  for (const b of readouts.machines?.batteries || [])
    pair(dl, b.name, `${((b.charge_j || 0) / 1000).toFixed(1)} kJ of ${((b.capacity_j || 0) / 1000).toFixed(0)} kJ`);
  for (const s of readouts.machines?.solar_panels || [])
    pair(dl, s.name, s.shaded ? `in shadow (${s.shaded_by || 'something'})` : `${(s.sunlight_w || 0).toFixed(0)} W of sunlight, ${(s.power_w || 0).toFixed(1)} W into the battery`);
  for (const m of readouts.machines?.motors || [])
    pair(dl, `Motor ${m.id}`, `${(m.speed_rad_s || 0).toFixed(1)} rad/s · ${(m.torque_n_m || 0).toFixed(2)} N·m · ${(m.power_w || 0).toFixed(0)} W`);
  if (readouts.light) {
    const l = readouts.light;
    pair(dl, 'Light', `${(l.sent_w || 0).toFixed(1)} W traced, ${(l.heated_w || 0).toFixed(1)} W of it warming parts`);
    for (const c of l.photocells || []) pair(dl, `${c.name} (light sensor)`, `${(c.power_w || 0).toFixed(3)} W`);
  }
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
async function build(next, start, request) {
  const mine = ++polling;
  if (session) api({op: 'close', session}).catch(() => {});
  session = null; playing = false;
  $('clock').textContent = 'Building in the engine…';
  for (const [, mesh] of meshes) { scene.remove(mesh); mesh.geometry.dispose(); }
  meshes.clear(); $('events').replaceChildren();
  try {
    const opened = await api(request || {op: 'open', spec: next});
    if (mine !== polling) { api({op: 'close', session: opened.session}).catch(() => {}); return opened; }
    spec = request ? opened.machine : next; machine = opened.machine; session = opened.session; readouts = opened.readouts || {};
    world = mergeFrame({seq: 0, t: 0, bodies: new Map()}, opened);
    $('title').textContent = machine.title;
    $('spec').value = JSON.stringify(spec, null, 1);
    const notes = $('notes'); notes.replaceChildren();
    for (const n of machine.notes || []) { const li = document.createElement('li'); li.textContent = n; notes.append(li); }
    for (const [, line] of drumLines) { scene.remove(line); line.geometry.dispose(); }
    drumLines.clear();
    if (parcels) { scene.remove(parcels); parcels.geometry.dispose(); parcels = null; }
    syncGround(opened.ground); syncWater(opened.water); syncParcels(opened.parcels);
    syncMeshes([...world.bodies.values()]); syncWires(); syncRopes(); syncZones(); updateWires(); placeSun(); syncLight(); renderStations(); renderReadings(opened); renderClock(opened);
    frameCamera();
    if (start) await setPlaying(true);
    poll(mine);
    return opened;
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
      updateWires(); syncLight(); addEvents(frame.events); renderStations(); renderReadings(frame); renderClock(frame);
      watchGoal(frame);
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
  distance = Math.min(40, Math.max(1.6, .6 * span / Math.tan(half)));
  azimuth = -.25; elevation = .38;
}

// A scripted view, for scripts/film_machine.py: where the camera looks from
// (azimuth and elevation in radians, distance in metres) and at what point.
// It stops following, as dragging the view does.
window.machineView = ({azimuth: a, elevation: e, distance: d, at} = {}) => {
  follow = false; $('follow').setAttribute('aria-pressed', 'false');
  if (Number.isFinite(a)) azimuth = a;
  if (Number.isFinite(e)) elevation = e;
  if (Number.isFinite(d)) distance = d;
  if (Array.isArray(at) && at.length === 3) { goal.set(...at); target.copy(goal); }
};

// And where a point in the world is on the page, for a script that clicks
// where a person would (tests of placing a piece by clicking).
window.machineScreenPoint = point => {
  const p = new THREE.Vector3(...point).project(camera), rect = renderer.domElement.getBoundingClientRect();
  return [rect.left + (p.x + 1) / 2 * rect.width, rect.top + (1 - p.y) / 2 * rect.height];
};

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
  const last = pointers.get(e.pointerId); if (!last || draggingGhost) return;
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
renderer.domElement.addEventListener('wheel', e => { e.preventDefault(); if (ghost && (e.shiftKey || e.altKey)) return; distance =Math.min(40, Math.max(.4, distance * Math.exp(e.deltaY * .001))); }, {passive: false});

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
  if (LEVEL_MODE) for (const [name, mesh] of meshes) mesh.visible = !hiddenPiece(name);
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
  if (LEVEL_MODE) { askLevel('hint'); return; }
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


// ---- the puzzles (/play) ---------------------------------------------------------
// A level is a fixed machine, a goal and a tray. The player adds pieces from
// the tray and turns their knobs; the server composes the machine and the
// engine runs it. The stars come from what the engine measured.
const params = new URLSearchParams(location.search);
const LEVEL_MODE = location.pathname === '/play' || params.has('level');
let levels = [], level = null, placements = [], placedCost = [], helped = false, scored = false, lastRun = null, rebuildTimer = null;

// ---- the ghost: a piece before it is set down ------------------------------------
// A see-through copy of a piece. It follows the pointer over the scene until
// a click pins it; pinned, it can be dragged, its knobs changed and turned
// any way, and then set down. It is nothing in the engine meanwhile: the
// server compiles it where it would go (set down on what is there, turned as
// it is turned) and says why it could not go there. Blue fits, red does not
// (green is the level's own: where the goal is).
// Only when it is set down does the engine build it.
let ghost = null, pressedAt = null, draggingGhost = null;
const raycaster = new THREE.Raycaster();
const ghostLook = {
  fits: new THREE.MeshStandardMaterial({color: 0x6cc6ff, transparent: true, opacity: .35, depthWrite: false, roughness: .6}),
  refused: new THREE.MeshStandardMaterial({color: 0xff5f5f, transparent: true, opacity: .4, depthWrite: false, roughness: .6})};
const ghostEdge = {fits: new THREE.LineBasicMaterial({color: 0xcdeeff}), refused: new THREE.LineBasicMaterial({color: 0xffc2c2})};
const ghostGroup = new THREE.Group();
scene.add(ghostGroup);
const TURN_KEYS = {q: ['yaw_deg', 1], e: ['yaw_deg', -1], r: ['pitch_deg', 1], f: ['pitch_deg', -1], z: ['roll_deg', -1], c: ['roll_deg', 1]};

function ghostName() { return ghost ? `your ${ghost.p.piece} ${ghost.index + 1}` : ''; }
// The piece picked up is hidden while its ghost is out; Cancel shows it again.
function hiddenPiece(name) { return Boolean(ghost && ghost.was) && (name === ghostName() || name.startsWith(ghostName() + ' ')); }
function ghostPlacements() { const list = placements.slice(); list[ghost.index] = ghost.p; return list; }

// A knob set as its slider would set it: on its step, within its range.
function setKnob(p, key, v) {
  const r = trayItem(p.piece).knobs[key];
  if (!r || r.choices || !Number.isFinite(v)) return false;
  if (r.turning) v = ((v + 180) % 360 + 360) % 360 - 180;
  const step = r.step || 0.01;
  const next = Number(Math.min(r.max, Math.max(r.min, Math.round(v / step) * step)).toFixed(4));
  if (next === p[key]) return false;
  p[key] = next;
  return true;
}

function sceneHit(clientX, clientY) {
  const rect = renderer.domElement.getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2((clientX - rect.left) / rect.width * 2 - 1, -(clientY - rect.top) / rect.height * 2 + 1), camera);
  const solid = [ground, ...[...meshes].filter(([name, m]) => m.visible && !hiddenPiece(name)).map(([, m]) => m)];
  const hits = raycaster.intersectObjects(solid, true);
  return hits.length ? hits[0].point : null;
}

function ghostHit(clientX, clientY) {
  const rect = renderer.domElement.getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2((clientX - rect.left) / rect.width * 2 - 1, -(clientY - rect.top) / rect.height * 2 + 1), camera);
  return raycaster.intersectObjects(ghostGroup.children, true).some(h => h.object.isMesh);
}

// Put the ghost's middle where the pointer meets the scene (less where on
// the ghost it was taken hold of, when it is dragged).
function moveGhostTo(clientX, clientY, hold = {x: 0, z: 0}) {
  const at = ghost && sceneHit(clientX, clientY);
  if (!at) return;
  const moved = [setKnob(ghost.p, 'x_m', at.x - hold.x), setKnob(ghost.p, 'z_m', at.z - hold.z)].some(Boolean);
  if (moved) { followGhost(); showGhostKnobs(); askGhost(); }
}

// The knob that turns a piece about an axis: the free one, or for the turn
// about the vertical a piece's own (a mirror's angle).
function turnKnob(p, key) {
  const knobs = trayItem(p.piece).knobs;
  if (knobs[key]) return key;
  return key === 'yaw_deg' ? Object.keys(knobs).find(k => knobs[k].turning && k !== 'pitch_deg' && k !== 'roll_deg') : undefined;
}

function turnGhost(key, by) {
  const k = ghost && turnKnob(ghost.p, key);
  if (k && setKnob(ghost.p, k, (ghost.p[k] || 0) + by)) { showGhostKnobs(); askGhost(); }
}

// The ghost as last compiled, moved at once by however far its knobs have
// moved since; the server's answer then sets it down again.
function followGhost() {
  if (!ghost || !ghost.drawnAt) return;
  ghostGroup.position.set((ghost.p.x_m ?? 0) - ghost.drawnAt.x, 0, (ghost.p.z_m ?? 0) - ghost.drawnAt.z);
}

function clearGhostMeshes() {
  for (const c of [...ghostGroup.children]) { ghostGroup.remove(c); c.traverse(o => { if (o.geometry) o.geometry.dispose(); }); }
}

function drawGhost(parts, fits) {
  clearGhostMeshes();
  const look = fits ? ghostLook.fits : ghostLook.refused, edge = fits ? ghostEdge.fits : ghostEdge.refused;
  const turn = (o, deg) => o.rotation.set(...deg.map(d => d * Math.PI / 180), 'XYZ');   // R = Rx Ry Rz, as the engine turns
  const solid = (geometry, at, deg) => {
    const mesh = new THREE.Mesh(geometry, look);
    mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 30), edge));
    mesh.position.set(...at); turn(mesh, deg);
    return mesh;
  };
  for (const part of parts) {
    if (part.shape === 'compound') {
      const body = new THREE.Group();
      body.position.set(...part.at_m); turn(body, part.turn_deg);
      for (const sub of part.parts) body.add(solid(sub.shape === 'cylinder'
        ? new THREE.CylinderGeometry(sub.size_m[0] / 2, sub.size_m[0] / 2, sub.size_m[1], 20)
        : new THREE.BoxGeometry(...sub.size_m), sub.at_m, sub.turn_deg));
      ghostGroup.add(body);
    } else if (part.shape === 'sphere') ghostGroup.add(solid(new THREE.SphereGeometry(part.size_m[0] / 2, 24, 16), part.at_m, part.turn_deg));
    else if (part.shape === 'cone') ghostGroup.add(solid(new THREE.ConeGeometry(part.size_m[0] / 2, part.size_m[1], 24), part.at_m, part.turn_deg));
    else ghostGroup.add(solid(new THREE.BoxGeometry(...part.size_m), part.at_m, part.turn_deg));
  }
  followGhost();
}

// One question to the server at a time; a change made meanwhile asks again
// when the answer comes.
async function askGhost() {
  if (!ghost) return;
  if (ghost.busy) { ghost.again = true; return; }
  const g = ghost, sent = {x: g.p.x_m ?? 0, z: g.p.z_m ?? 0};
  g.busy = true; g.again = false;
  try {
    const r = await api({op: 'level_ghost', level: level.id, placements: ghostPlacements(), index: g.index});
    if (ghost !== g) return;
    Object.assign(g, {fits: r.fits, problems: r.problems, cost: r.cost, sun: r.sun || [], drawnAt: sent, answered: true});
    drawGhost(r.parts, r.fits);
  } catch (e) {
    if (ghost === g) Object.assign(g, {fits: false, problems: e.data && e.data.problems ? e.data.problems : [e.message], answered: true});
  } finally {
    g.busy = false;
    if (ghost === g) { showGhostState(); if (g.again) askGhost(); }
  }
}

// A piece from the tray (index after the rest) or one picked up (its own
// index): a ghost of it, following the pointer, starting where the middle of
// the view meets the scene.
function startGhost(p, index) {
  endGhost();
  ghost = {p, index, was: index < placements.length ? placements[index] : null, follow: true, fits: true, problems: [],
           drawnAt: null, busy: false, again: false, cost: null, answered: false, inputs: {}};
  view.classList.add('placing');
  renderTray(); renderPlaced(); renderGhostBar();
  // Where the ghost is: in sight (a phone's page has scrolled down to the tray).
  const seen = view.getBoundingClientRect();
  if (seen.top < -40 || seen.bottom > innerHeight + 40) view.scrollIntoView({block: 'start'});
  if (!ghost.was) {
    const rect = renderer.domElement.getBoundingClientRect();
    const at = sceneHit(rect.left + rect.width / 2, rect.top + rect.height / 2);
    if (at) { setKnob(ghost.p, 'x_m', at.x); setKnob(ghost.p, 'z_m', at.z); showGhostKnobs(); }
  }
  askGhost();
}

function endGhost() {
  ghost = null; draggingGhost = null;
  clearGhostMeshes(); ghostGroup.position.set(0, 0, 0);
  view.classList.remove('placing');
  renderGhostBar();
}

function cancelGhost() { if (!ghost) return; endGhost(); renderTray(); renderPlaced(); }

function setGhostDown() {
  if (!ghost || !ghost.fits || ghost.busy || !ghost.answered) return;
  if (ghost.was) placements[ghost.index] = ghost.p; else placements.push(ghost.p);
  endGhost(); renderTray(); renderPlaced(); scheduleRebuild(0);
}

// The same controls over the scene, next to the ghost: on a phone the list
// of pieces is a scroll away from the scene.
function renderGhostBar() {
  const bar = $('ghost-bar');
  bar.hidden = !ghost;
  if (!ghost) { bar.replaceChildren(); return; }
  const turns = [['yaw_deg', '⟲ turn', '⟳ turn'], ['pitch_deg', 'tip ▲', 'tip ▼'], ['roll_deg', '⟲ roll', '⟳ roll']]
    .filter(([key]) => turnKnob(ghost.p, key));
  const row = [];
  for (const [key, up, down] of turns) {
    const word = key === 'yaw_deg' ? 'Turn' : key === 'pitch_deg' ? 'Tip' : 'Roll';
    row.push(button(up, () => turnGhost(key, 15), {ariaLabel: `${word} it on 15 degrees`}),
             button(down, () => turnGhost(key, -15), {ariaLabel: `${word} it back 15 degrees`}));
  }
  row.push(button('✓ Set down', setGhostDown, {className: 'down', disabled: !ghost.fits || ghost.busy}),
           button('✕', cancelGhost, {ariaLabel: 'Throw the ghost away', title: 'Throw the ghost away'}));
  bar.replaceChildren(...row);
}

function showGhostState() {
  const bar = document.querySelector('#ghost-bar .down');
  if (bar && ghost) bar.disabled = !ghost.fits || ghost.busy || !ghost.answered;
  const state = $('ghost-state'), down = $('ghost-down');
  if (!ghost || !state) return;
  state.className = 'ghost-state ' + (ghost.fits ? 'fits' : 'refused');
  state.textContent = ghost.follow ? 'Move the pointer over the scene; click to put it there. '
    : '';
  state.textContent += ghost.fits ? 'It fits here.' : ghost.problems.join('; ');
  // A panel: how squarely it faces the sun (the engine decides shade).
  for (const s of ghost.sun || []) state.textContent += ` It faces ${s.off_sun_deg}° off the sun: about ` +
    `${Math.round(s.sunlight_w)} W of sunlight on it, if nothing shades it.`;
  if (down) down.disabled = !ghost.fits || ghost.busy;
  const head = $('ghost-cost');
  if (head && ghost.cost != null) head.textContent = ` · costs ${ghost.cost}`;
}

function showGhostKnobs() {
  if (!ghost) return;
  for (const [key, [input, shown]] of Object.entries(ghost.inputs)) {
    if (String(input.value) !== String(ghost.p[key])) input.value = ghost.p[key];
    shown.textContent = String(ghost.p[key]) + (trayItem(ghost.p.piece).knobs[key].turning ? '°' : '');
  }
}

window.machineGhostState = () => ghost ? {p: {...ghost.p}, index: ghost.index, fits: ghost.fits, problems: ghost.problems,
  follow: ghost.follow, busy: ghost.busy, answered: ghost.answered, parts: ghostGroup.children.length} : null;

// Over the scene: a ghost that follows goes where the pointer is; a press on
// a pinned ghost drags it; a click (a press that does not move) pins a
// following ghost, or moves a pinned one there. Any other drag turns the view.
renderer.domElement.addEventListener('pointerdown', e => {
  pressedAt = [e.clientX, e.clientY];
  if (ghost && !ghost.follow && ghostHit(e.clientX, e.clientY)) {
    const at = sceneHit(e.clientX, e.clientY);
    draggingGhost = at ? {x: at.x - (ghost.p.x_m ?? 0), z: at.z - (ghost.p.z_m ?? 0)} : {x: 0, z: 0};
  }
});
renderer.domElement.addEventListener('pointermove', e => {
  if (!ghost) return;
  if (draggingGhost) moveGhostTo(e.clientX, e.clientY, draggingGhost);
  else if (ghost.follow && !e.buttons) moveGhostTo(e.clientX, e.clientY);
});
renderer.domElement.addEventListener('pointerup', e => {
  const click = pressedAt && Math.hypot(e.clientX - pressedAt[0], e.clientY - pressedAt[1]) < 6;
  if (ghost && click && !draggingGhost) {
    moveGhostTo(e.clientX, e.clientY);
    if (ghost.follow) { ghost.follow = false; renderPlaced(); showGhostState(); }
  }
  draggingGhost = null; pressedAt = null;
});
// Turning by hand: Shift and the wheel turns it, Alt and the wheel tips it.
renderer.domElement.addEventListener('wheel', e => {
  if (!ghost || !(e.shiftKey || e.altKey)) return;
  e.preventDefault();
  turnGhost(e.altKey ? 'pitch_deg' : 'yaw_deg', Math.sign(e.deltaY || e.deltaX) * -15);
}, {passive: false});
document.addEventListener('keydown', e => {
  if (!ghost || e.ctrlKey || e.metaKey || e.target.closest('input, textarea, select')) return;
  const key = e.key.toLowerCase(), step = e.shiftKey ? 1 : 15;
  const nudge = {arrowleft: ['x_m', -1], arrowright: ['x_m', 1], arrowup: ['z_m', -1], arrowdown: ['z_m', 1]}[key];
  if (TURN_KEYS[key]) turnGhost(TURN_KEYS[key][0], TURN_KEYS[key][1] * step);
  else if (nudge) {
    const rule = trayItem(ghost.p.piece).knobs[nudge[0]];
    if (rule && setKnob(ghost.p, nudge[0], (ghost.p[nudge[0]] ?? 0) + nudge[1] * (rule.step || 0.01) * (e.shiftKey ? 10 : 1))) {
      followGhost(); showGhostKnobs(); askGhost();
    }
  } else if (key === 'enter' && !e.target.closest('button')) setGhostDown();
  else if (key === 'escape') cancelGhost();
  else return;
  e.preventDefault();
});

function bestStars(id) { try { return Number(localStorage.getItem('banjo-level-' + id) || 0); } catch { return 0; } }
function keepStars(id, n) { try { if (n > bestStars(id)) localStorage.setItem('banjo-level-' + id, String(n)); } catch { /* private window */ } }

function renderLevels() {
  const nav = $('levels'); nav.replaceChildren();
  levels.forEach((l, i) => {
    const b = document.createElement('button'); b.type = 'button';
    const best = bestStars(l.id);
    b.textContent = `${i + 1}. ${l.title}${best ? ' ' + '★'.repeat(best) : ''}`;
    b.setAttribute('aria-current', String(Boolean(level) && l.id === level.id));
    b.addEventListener('click', () => chooseLevel(l.id).catch(() => {}));
    nav.append(b);
  });
}

function knobDefault(rule) { return rule.default ?? (rule.choices ? rule.choices[0] : rule.min); }
function trayItem(piece) { return level.tray.find(t => t.piece === piece); }

function renderTray() {
  const ul = $('tray'); ul.replaceChildren();
  for (const t of level.tray) {
    const used = placements.filter(p => p.piece === t.piece).length + (ghost && !ghost.was && ghost.p.piece === t.piece ? 1 : 0);
    const count = t.count || 1, li = document.createElement('li');
    const per = t.cost_per ? (t.cost_per.say || `${t.cost_per.each} per ${t.cost_per.unit} of ${t.cost_per.knob}`) : '';
    const price = t.cost_per ? (t.cost ? `${t.cost} + ${per}` : per) : `${t.cost}`;
    li.append(Object.assign(document.createElement('span'), {textContent: `${t.piece} — costs ${price} · ${count - used} of ${count} left`}));
    const add = Object.assign(document.createElement('button'), {type: 'button', textContent: 'Add', disabled: used >= count});
    add.addEventListener('click', () => {
      const p = {piece: t.piece};
      for (const [key, rule] of Object.entries(t.knobs)) p[key] = knobDefault(rule);
      startGhost(p, placements.length);
    });
    li.append(add); ul.append(li);
  }
}

function button(text, onClick, extra = {}) {
  const b = Object.assign(document.createElement('button'), {type: 'button', textContent: text}, extra);
  b.addEventListener('click', onClick);
  return b;
}

// A knob's control: a slider (or a list of choices) that changes the piece
// and then calls changed().
function knobControl(p, key, rule, what, changed) {
  const label = Object.assign(document.createElement('label'), {className: 'knob'});
  label.append(Object.assign(document.createElement('span'), {textContent: rule.label || key}));
  let input;
  const shown = Object.assign(document.createElement('output'), {textContent: String(p[key]) + (rule.turning ? '°' : '')});
  if (rule.choices) {
    input = document.createElement('select');
    for (const c of rule.choices) input.append(Object.assign(document.createElement('option'), {value: c, textContent: c}));
    input.value = p[key];
    // A choice keeps its own type: a number of pulleys stays a number.
    input.addEventListener('change', () => {
      p[key] = rule.choices.find(c => String(c) === input.value) ?? input.value;
      shown.textContent = input.value; changed();
    });
  } else {
    input = Object.assign(document.createElement('input'), {type: 'range', min: rule.min, max: rule.max, step: rule.step || 0.01, value: p[key]});
    input.addEventListener('input', () => { p[key] = Number(input.value); shown.textContent = input.value + (rule.turning ? '°' : ''); changed(); });
  }
  input.setAttribute('aria-label', `${rule.label || key} of ${what}`);
  label.append(input, shown);
  return {label, input, shown};
}

function describeKnobs(p, t) {
  const turned = Object.entries(t.knobs).filter(([k, r]) => r.turning && p[k]).map(([k, r]) => `${r.label || k} ${p[k]}°`);
  const rest = Object.entries(t.knobs).filter(([k, r]) => !r.turning && p[k] != null && !(r.free && !p[k]))
    .map(([k, r]) => `${(r.label || k).replace(/ \(.*\)$/, '')} ${p[k]}`);
  return [...rest, ...turned].join(' · ');
}

// The ghost, in the list where the piece is (or will be): its knobs, its
// turning, and Set it down / Cancel.
function ghostItem() {
  const p = ghost.p, t = trayItem(p.piece), what = ghostName();
  const li = Object.assign(document.createElement('li'), {className: 'ghost-piece'});
  const head = Object.assign(document.createElement('div'), {className: 'piece-head'});
  const title = Object.assign(document.createElement('strong'), {textContent: `${what} — ghost, not set down yet`});
  title.append(Object.assign(document.createElement('span'), {id: 'ghost-cost'}));
  head.append(title);
  const follow = button(ghost.follow ? 'Following the pointer' : 'Follow the pointer', () => {
    ghost.follow = !ghost.follow; renderPlaced(); showGhostState();
  });
  follow.setAttribute('aria-pressed', String(ghost.follow));
  const actions = Object.assign(document.createElement('div'), {className: 'ghost-actions'});
  actions.append(follow, button('Set it down', setGhostDown, {id: 'ghost-down', disabled: true}), button('Cancel', cancelGhost));
  li.append(head, actions, Object.assign(document.createElement('p'), {id: 'ghost-state', className: 'ghost-state'}));
  ghost.inputs = {};
  const turning = Object.assign(document.createElement('fieldset'), {className: 'turning'});
  turning.append(Object.assign(document.createElement('legend'), {textContent: 'Turn it (degrees)'}));
  for (const [key, rule] of Object.entries(t.knobs)) {
    const c = knobControl(p, key, rule, what, () => { followGhost(); askGhost(); });
    ghost.inputs[key] = [c.input, c.shown];
    if (!rule.turning) { li.append(c.label); continue; }
    // − and + by 15 degrees either side of the slider; the slider for the rest.
    const row = Object.assign(document.createElement('div'), {className: 'turn-row'});
    const word = rule.label.split(' ')[0];
    row.append(button('−15°', () => turnGhost(key, -15), {ariaLabel: `${word} back 15 degrees`}), c.label,
               button('+15°', () => turnGhost(key, 15), {ariaLabel: `${word} on 15 degrees`}));
    turning.append(row);
  }
  if (turning.children.length > 1) {
    turning.append(button('Square it up', () => {
      for (const [key, rule] of Object.entries(t.knobs)) if (rule.turning) setKnob(p, key, 0);
      showGhostKnobs(); askGhost();
    }), Object.assign(document.createElement('p'), {className: 'legend',
      textContent: 'Keys: Q/E turn · R/F tip · Z/C roll (with Shift, 1°) · arrows move it · Enter sets it down · Esc cancels. ' +
                   'Shift+wheel turns it, Alt+wheel tips it. Drag the pinned ghost to move it; click anywhere to put it there.'}));
    li.append(turning);
  }
  return li;
}

function renderPlaced() {
  const ol = $('placed'); ol.replaceChildren();
  placements.forEach((p, i) => {
    if (ghost && ghost.was && ghost.index === i) { ol.append(ghostItem()); return; }
    const t = trayItem(p.piece), li = document.createElement('li');
    const head = Object.assign(document.createElement('div'), {className: 'piece-head'});
    head.append(Object.assign(document.createElement('strong'), {textContent: `your ${p.piece} ${i + 1}${placedCost[i] != null ? ' · costs ' + placedCost[i] : ''}`}));
    const actions = Object.assign(document.createElement('div'), {className: 'ghost-actions'});
    // Picked up, it becomes a ghost again: moved, changed, turned, set down.
    actions.append(button('Pick up', () => startGhost({...p}, i), {ariaLabel: `Pick up your ${p.piece} ${i + 1}`}),
                   button('Remove', () => {
                     if (ghost) endGhost();
                     placements.splice(i, 1); renderTray(); renderPlaced(); scheduleRebuild(0);
                   }, {ariaLabel: `Remove your ${p.piece} ${i + 1}`}));
    head.append(actions);
    li.append(head, Object.assign(document.createElement('p'), {className: 'knob-summary', textContent: describeKnobs(p, t)}));
    ol.append(li);
  });
  if (ghost && !ghost.was) ol.append(ghostItem());
  if (ghost) { showGhostKnobs(); showGhostState(); }
  const total = placedCost.reduce((a, b) => a + (b || 0), 0);
  $('cost-line').textContent = placements.length ? `Cost ${Math.round(total * 10) / 10} of a budget of ${level.budget} (par ${level.par}).` : 'Add a piece from the tray.';
}

function scheduleRebuild(ms = 350) { clearTimeout(rebuildTimer); rebuildTimer = setTimeout(() => rebuildLevel(false).catch(() => {}), ms); }

async function rebuildLevel(start) {
  scored = false; $('verdict').replaceChildren();
  try {
    const opened = await build(null, start, {op: 'level_open', level: level.id, placements, helped});
    placedCost = (opened.placements || []).map(p => p.cost);
    renderPlaced();
  } catch (e) {
    const problems = e.data && e.data.problems ? e.data.problems.join('; ') : e.message;
    $('verdict').textContent = problems;
    // Still show the level as it stands, without the pieces that do not fit.
    if (!placements.length || e.status === 422) await build(level.machine).catch(() => {});
  }
}

function watchGoal(frame) {
  if (!LEVEL_MODE || !level || scored || !frame || !session || !(world.t > 0)) return;
  const row = (readouts.stations || [])[0];
  if ((row && row.done) || world.t > level.time_s + 0.3) { scored = true; score(row).catch(() => {}); }
}

async function score(row) {
  lastRun = {goal_at_s: row && row.done ? row.at_s : null, world_t: world.t,
             events: [...$('events').children].slice(0, 20).map(li => li.textContent)};
  const r = await api({op: 'level_score', session});
  const v = $('verdict'); v.replaceChildren();
  v.append(Object.assign(document.createElement('span'), {className: 'stars', textContent: '★'.repeat(r.stars) + '☆'.repeat(3 - r.stars)}));
  const said = [r.earned.goal ? `Goal at ${describeTime(r.goal_at_s)}.` : `The goal did not happen within ${level.time_s} s.`,
                `Cost ${r.cost} (par ${r.par})${r.earned.budget ? '' : ', over par'}.`];
  if (r.helped) said.push('The chat placed the pieces, so one star at most.');
  v.append(' ' + said.join(' '));
  keepStars(level.id, r.stars); renderLevels();
}

async function chooseLevel(id) {
  level = levels.find(l => l.id === id) || levels[0];
  endGhost();
  placements = []; placedCost = []; helped = false; lastRun = null;
  history_.replaceState(null, '', '/play?level=' + level.id);
  $('title').textContent = `${levels.indexOf(level) + 1}. ${level.title}`;
  $('brief').textContent = level.brief;
  $('goal-line').textContent = `Goal: ${level.goal.title.toLowerCase()} within ${level.time_s} s. Budget ${level.budget}, par ${level.par}. It teaches ${level.teaches}.`;
  $('chat-log').replaceChildren();
  renderLevels(); renderTray(); renderPlaced();
  await rebuildLevel(false);
}

async function askLevel(mode) {
  const message = $('message').value.trim() || (mode === 'hint' ? 'Give me a hint.' : 'Place the pieces for me.');
  $('send').disabled = $('solve').disabled = true;
  $('chat-status').textContent = mode === 'hint' ? 'Thinking about your last run…' : 'Placing pieces from your tray, then rehearsing them once in the engine…';
  say('you', message);
  try {
    const r = await api({op: 'chat', level: level.id, placements, mode, message, last_run: lastRun});
    say('model', r.reply);
    if (mode === 'build' && Array.isArray(r.placements)) {
      endGhost();
      placements = r.placements.map(p => { const q = {...p}; delete q.cost; return q; });
      helped = true; renderTray(); renderPlaced();
      if (r.rehearsal) say(r.rehearsal.goal_at_s != null ? 'model' : 'refused', r.rehearsal.goal_at_s != null
        ? `Rehearsed once in the engine: the goal happened at ${describeTime(r.rehearsal.goal_at_s)}.`
        : 'Rehearsed once in the engine: the goal did not happen. Try moving the pieces.');
      await rebuildLevel(false);
    }
    $('message').value = '';
  } catch (err) { say('refused', err.message); }
  finally { $('send').disabled = $('solve').disabled = false; $('chat-status').textContent = ''; }
}

async function startGame() {
  document.body.classList.add('playing-level');
  $('game').hidden = false; $('solve').hidden = false; $('undo').hidden = true;
  document.querySelector('.lede').hidden = true;
  for (const d of document.querySelectorAll('aside details')) d.hidden = true;
  $('send').textContent = 'Ask for a hint';
  $('message').placeholder = 'Ask about this level, e.g. “Why does my ball fall short?”';
  document.querySelector('.chat h2').textContent = 'Ask for help';
  const r = await api({op: 'levels'});
  levels = r.levels;
  await chooseLevel(params.get('level'));
}
// A ghost is not in the machine yet: set it down (or cancel it) before a run.
function ghostInTheWay() {
  if (!ghost) return false;
  $('verdict').textContent = `Set your ${ghost.p.piece} down first (or cancel it): a ghost is not part of the machine yet.`;
  return true;
}
$('run').addEventListener('click', () => { if (!ghostInTheWay()) rebuildLevel(true).catch(() => {}); });
$('trial').addEventListener('click', async () => {
  if (ghostInTheWay()) return;
  $('trial').disabled = true;
  $('verdict').textContent = 'Running it three times, each loose part nudged by a millimetre or two…';
  try {
    const r = await api({op: 'trial', level: level.id, placements});
    $('verdict').textContent = `Works ${r.worked} of ${r.runs}: ` + r.results.map(x => x.goal_at_s != null ? `goal at ${describeTime(x.goal_at_s)}` : 'missed').join(', ') + '.';
  } catch (e) { $('verdict').textContent = e.data && e.data.problems ? e.data.problems.join('; ') : e.message; }
  finally { $('trial').disabled = false; }
});
$('solve').addEventListener('click', () => askLevel('build'));

const history_ = window.history;
resize(); render();
if (LEVEL_MODE) startGame().catch(e => { $('clock').textContent = 'Could not load the levels: ' + e.message; });
else fetch('/machine-default.json').then(r => r.json()).then(d => build(d)).catch(e => { $('clock').textContent = 'Could not load the machine: ' + e.message; });
