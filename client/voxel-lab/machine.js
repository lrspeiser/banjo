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
  const shown = (machine?.stations || []).map(s => s.done_when && s.done_when.in_zone).filter(Boolean);
  // A level's goal zone is drawn even before the piece it is about is placed
  // (the goal is then left out of the run): it is where to build.
  const goalZone = LEVEL_MODE && level && level.goal.station.done_when.in_zone;
  if (goalZone && !shown.some(z => z.at_m.every((v, i) => v === goalZone.at_m[i]))) shown.push(goalZone);
  for (const z of shown) {
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
  // A level runs at real time, so its clock leaves the speed out.
  let text = `World ${describeTime(frame.t)} · ` + (LEVEL_MODE ? '' : `${frame.speed}× · `) + (frame.error ? 'stopped: ' + frame.error :
    frame.playing ? 'calculating live' : frame.t > 0 ? (LEVEL_MODE && scored ? 'run over' : 'paused')
    : LEVEL_MODE ? 'ready: press Run it' : 'ready: press Start');
  if (frame.playing && behind > .25) text += ` · ${behind.toFixed(1)} s behind real time while the engine works`;
  $('clock').textContent = text;
  $('start').textContent = frame.playing ? 'Pause' : !LEVEL_MODE ? (frame.t > 0 ? 'Continue' : 'Start')
    : frame.t > 0 ? (scored ? 'Run again' : 'Continue') : 'Run it';
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
    $('title').textContent = LEVEL_MODE && level ? `${levels.indexOf(level) + 1}. ${level.title}` : machine.title;
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
  // A level whose world the server closed while it sat idle is built again
  // and started, as Run it would: the pieces are kept here, in the page.
  if (!session) { if (LEVEL_MODE && run && level) await rebuildLevel(true); return; }
  let frame;
  try { frame = await api({op: 'play', session, running: run, speed: Number($('speed').value)}); }
  catch (e) {
    if (e.status === 410 && LEVEL_MODE && run && level) { session = null; await rebuildLevel(true); return; }
    throw e;
  }
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
      if (e.status === 410) {
        $('clock').textContent = LEVEL_MODE ? 'The server closed this level while it sat idle; press Run it to build it again'
          : 'This machine stopped running on the server; press Set up again';
        session = null; return;
      }
      $('clock').textContent = 'Connection problem: ' + e.message;
      await new Promise(r => setTimeout(r, 1500));
    }
  }
}

// ---- camera -------------------------------------------------------------------
function frameCamera() {
  const pts = [...world.bodies.values()].map(b => b.position_m);
  // A level's goal zone is in the picture too, and the ground under it:
  // where the player is to build, even before anything stands there.
  const zone = LEVEL_MODE && level && level.goal.station.done_when.in_zone;
  if (zone) pts.push(zone.at_m, [zone.at_m[0], 0, zone.at_m[2]]);
  if (!pts.length) return;
  const lo = [0, 1, 2].map(i => Math.min(...pts.map(p => p[i]))), hi = [0, 1, 2].map(i => Math.max(...pts.map(p => p[i])));
  // A level is looked at from half its height (its goal zone is often high), a little further back.
  goal.set((lo[0] + hi[0]) / 2, Math.max(.3, (lo[1] + hi[1]) / (zone ? 2 : 3)), (lo[2] + hi[2]) / 2);
  target.copy(goal);
  const span = Math.max(hi[0] - lo[0], hi[2] - lo[2], hi[1] - lo[1]);
  // Far enough that the whole width fits the narrower of the two view angles.
  const half = Math.min(camera.fov * Math.PI / 360, Math.atan(Math.tan(camera.fov * Math.PI / 360) * camera.aspect));
  distance = Math.min(40, Math.max(zone ? 2.2 : 1.6, (zone ? .8 : .6) * span / Math.tan(half)));
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
  const last = pointers.get(e.pointerId); if (!last || draggingGhost || pulling) return;
  if (pointers.size === 2) {
    // Two fingers: apart and together zoom, moved together turn the view
    // (one finger moves a piece being placed, on a touch screen).
    const [p0, q0] = [...pointers.values()];
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
    const [a, b] = [...pointers.values()], gap = Math.hypot(a[0] - b[0], a[1] - b[1]);
    if (pinch) distance = Math.min(40, Math.max(.4, distance * pinch / gap));
    azimuth -= ((a[0] + b[0]) - (p0[0] + q0[0])) / 2 * .006;
    elevation = Math.min(1.45, Math.max(.05, elevation + ((a[1] + b[1]) - (p0[1] + q0[1])) / 2 * .006));
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
  if (LEVEL_MODE) { for (const [name, mesh] of meshes) mesh.visible = !hiddenPiece(name); updateGuides(); syncMovePad(); }
  drawPull();
  renderer.render(scene, camera);
  renderLabels();
}

// ---- controls -----------------------------------------------------------------
$('start').addEventListener('click', () => {
  if (LEVEL_MODE && level) { runLevel(); return; }
  setPlaying(!playing).catch(e => { $('clock').textContent = e.message; });
});
// A level is set up again as a level (its pieces, not running), not as a sandbox machine.
$('reset').addEventListener('click', () => (LEVEL_MODE && level ? rebuildLevel(false) : build(spec)).catch(() => {}));
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
let levels = [], level = null, placements = [], placedCost = [], placedEnergy = {}, helped = false, scored = false, lastRun = null, rebuildTimer = null;

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
  // On its step counted from its minimum, as the slider steps.
  const step = r.step || 0.01;
  const next = Number(Math.min(r.max, Math.max(r.min, r.min + Math.round((v - r.min) / step) * step)).toFixed(4));
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

// Moving it as it is seen: left, right, away from you and toward you go
// along whichever of the level's ground directions (x, the red guide line;
// z, the blue) is nearest that way on the screen, so a press moves it along
// one guide line; up and down move whatever sets its height, all together
// or not at all (a ramp keeps its slope). A piece with no height of its own
// rests on what is under it.
const HEIGHT_KNOBS = ['height_m', 'pivot_height_m', 'bore_height_m', 'drop_from_m', 'top_height_m', 'foot_height_m'];
function heightKnobs(p) {
  const knobs = trayItem(p.piece).knobs;
  return HEIGHT_KNOBS.filter(k => knobs[k] && !knobs[k].choices);
}
function viewAxis(dir) {
  // The camera looks along (-sin a, -cos a) on the ground; its right is (cos a, -sin a).
  const [dx, dz] = {right: [Math.cos(azimuth), -Math.sin(azimuth)], left: [-Math.cos(azimuth), Math.sin(azimuth)],
                    forward: [-Math.sin(azimuth), -Math.cos(azimuth)], back: [Math.sin(azimuth), Math.cos(azimuth)]}[dir];
  return Math.abs(dx) >= Math.abs(dz) ? ['x_m', Math.sign(dx)] : ['z_m', Math.sign(dz)];
}
function moveGhostBy(dir, metres) {
  if (!ghost) return false;
  const knobs = trayItem(ghost.p.piece).knobs;
  let moved = false;
  if (dir === 'up' || dir === 'down') {
    const keys = heightKnobs(ghost.p), by = dir === 'up' ? metres : -metres;
    if (!keys.length || keys.some(k => (ghost.p[k] ?? 0) + by > knobs[k].max + 1e-9 || (ghost.p[k] ?? 0) + by < knobs[k].min - 1e-9)) return false;
    for (const k of keys) moved = setKnob(ghost.p, k, (ghost.p[k] ?? 0) + by) || moved;
  } else {
    const [key, sign] = viewAxis(dir);
    if (!knobs[key]) return false;
    moved = setKnob(ghost.p, key, (ghost.p[key] ?? 0) + sign * metres);
  }
  if (moved) { followGhost(); showGhostKnobs(); askGhost(); }
  return moved;
}

// The arrows, over the scene while a piece is placed. Each is drawn in the
// colour of the guide line it moves along, which changes as the view turns.
// Held, an arrow keeps moving it.
const MOVE_STEP_M = 0.02;
const PAD = [['forward', '↑', 'Move it away from you'], ['left', '←', 'Move it left'], ['right', '→', 'Move it right'],
             ['back', '↓', 'Move it toward you'], ['up', '▲', 'Raise it'], ['down', '▼', 'Lower it']];
let padAxes = '';
// Looking around while a piece is placed: every drag and tap turns the view
// and none moves the piece (the arrows still do). The switch in the middle
// of the arrows, or Esc, goes back and forth; a new piece starts in the hand.
let looking = false;
function setLooking(on) {
  looking = Boolean(on && ghost);
  draggingGhost = null;
  view.classList.toggle('looking', looking);
  view.classList.remove('grab');
  if (ghost) renderGhostBar();
}
function renderMovePad() {
  const pad = $('move-pad');
  pad.hidden = !LEVEL_MODE || !ghost;
  padAxes = '';
  if (pad.hidden) { pad.replaceChildren(); return; }
  const high = heightKnobs(ghost.p).length > 0;
  pad.replaceChildren(...PAD.filter(([dir]) => high || (dir !== 'up' && dir !== 'down')).map(([dir, glyph, say]) => {
    const b = holdButton(glyph, () => moveGhostBy(dir, MOVE_STEP_M), {ariaLabel: say, title: say});
    b.dataset.dir = dir;
    return b;
  }), button(looking ? '👁' : '✋', () => setLooking(!looking), {
    className: 'mode', ariaLabel: looking ? 'Looking around: press to move the piece' : 'Moving the piece: press to look around',
    title: looking ? 'Looking around (Esc): press to move the piece again' : 'Moving the piece (Esc): press to look around'}));
  syncMovePad();
}
function syncMovePad() {
  const pad = $('move-pad');
  if (pad.hidden) return;
  const axes = ['left', 'right', 'forward', 'back'].map(dir => viewAxis(dir)[0]).join();
  if (axes === padAxes) return;
  padAxes = axes;
  // A piece kept in line (level 8's counterweight, under its beam) has no z:
  // an arrow that would move it that way is greyed out.
  const knobs = trayItem(ghost.p.piece).knobs;
  for (const b of pad.querySelectorAll('button[data-dir]')) {
    const dir = b.dataset.dir;
    b.dataset.axis = dir === 'up' || dir === 'down' ? 'y' : viewAxis(dir)[0] === 'x_m' ? 'x' : 'z';
    if (b.dataset.axis !== 'y') b.disabled = !knobs[viewAxis(dir)[0]];
  }
}

// A button that acts when pressed, and again and again while it is held.
function holdButton(text, act, extra = {}) {
  const b = Object.assign(document.createElement('button'), {type: 'button', textContent: text}, extra);
  let wait = null, again = null;
  const stop = () => { clearTimeout(wait); clearInterval(again); wait = again = null; };
  const tick = () => { if (!b.isConnected || b.disabled) stop(); else act(); };
  b.addEventListener('pointerdown', e => {
    e.preventDefault(); stop(); tick();
    wait = setTimeout(() => { again = setInterval(tick, 80); }, 350);
  });
  for (const end of ['pointerup', 'pointerleave', 'pointercancel', 'blur']) b.addEventListener(end, stop);
  // From the keyboard (or a script) a press is a click with no pointer: once.
  b.addEventListener('click', e => { if (e.detail === 0) act(); });
  return b;
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

// A piece's parts as the ghost op sends them, built into `into`: each in the
// look lookOf(material) gives it, with its edges drawn when there is an edge.
function buildParts(into, parts, lookOf, edge) {
  const turn = (o, deg) => o.rotation.set(...deg.map(d => d * Math.PI / 180), 'XYZ');   // R = Rx Ry Rz, as the engine turns
  const solid = (geometry, at, deg, kind) => {
    const mesh = new THREE.Mesh(geometry, lookOf(kind));
    if (edge) mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 30), edge));
    mesh.position.set(...at); turn(mesh, deg);
    return mesh;
  };
  for (const part of parts) {
    if (part.shape === 'compound') {
      const body = new THREE.Group();
      body.position.set(...part.at_m); turn(body, part.turn_deg);
      for (const sub of part.parts) body.add(solid(sub.shape === 'cylinder'
        ? new THREE.CylinderGeometry(sub.size_m[0] / 2, sub.size_m[0] / 2, sub.size_m[1], 20)
        : new THREE.BoxGeometry(...sub.size_m), sub.at_m, sub.turn_deg, sub.material || part.material));
      into.add(body);
    } else if (part.shape === 'sphere') into.add(solid(new THREE.SphereGeometry(part.size_m[0] / 2, 24, 16), part.at_m, part.turn_deg, part.material));
    else if (part.shape === 'cone') into.add(solid(new THREE.ConeGeometry(part.size_m[0] / 2, part.size_m[1], 24), part.at_m, part.turn_deg, part.material));
    else into.add(solid(new THREE.BoxGeometry(...part.size_m), part.at_m, part.turn_deg, part.material));
  }
}

function drawGhost(parts, fits) {
  clearGhostMeshes();
  const look = fits ? ghostLook.fits : ghostLook.refused;
  buildParts(ghostGroup, parts, () => look, fits ? ghostEdge.fits : ghostEdge.refused);
  followGhost();
}

// A picture of each piece in the tray, as it comes: the ghost op's parts for
// it, drawn in their materials by a small renderer of its own, once a level.
const pictures = new Map();
let pictureRenderer = null;
function trayPicture(t) {
  const key = level.id + ':' + t.piece;
  if (!pictures.has(key)) pictures.set(key, (async () => {
    const p = {piece: t.piece};
    for (const [knob, rule] of Object.entries(t.knobs)) p[knob] = knobDefault(rule);
    const r = await api({op: 'level_ghost', level: level.id, placements: [p], index: 0});
    const shot = new THREE.Scene(), piece = new THREE.Group();
    buildParts(piece, r.parts, kind => material(materialColor(kind), kind), null);
    shot.add(piece, new THREE.HemisphereLight(0xdfefff, 0x334455, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.8);
    sun.position.set(2, 3, 4); shot.add(sun);
    // Looked at from the front, a little above and to one side, filling the frame.
    const box = new THREE.Box3().setFromObject(piece), mid = box.getCenter(new THREE.Vector3());
    const reach = box.getSize(new THREE.Vector3()).length() / 2;
    const eye = new THREE.PerspectiveCamera(30, 1, .001, 100);
    eye.position.copy(mid).add(new THREE.Vector3(.55, .45, 1).normalize().multiplyScalar(reach / Math.sin(15 * Math.PI / 180) * 1.05));
    eye.lookAt(mid);
    if (!pictureRenderer) {
      pictureRenderer = new THREE.WebGLRenderer({antialias: true, alpha: true, preserveDrawingBuffer: true});
      pictureRenderer.setSize(160, 160, false);
    }
    pictureRenderer.render(shot, eye);
    piece.traverse(o => { if (o.geometry) o.geometry.dispose(); });
    // A blob, not a data: URL, which the page's security policy refuses for images.
    const png = await new Promise(done => pictureRenderer.domElement.toBlob(done, 'image/png'));
    return png ? URL.createObjectURL(png) : null;
  })().catch(() => { pictures.delete(key); return null; }));
  return pictures.get(key);
}
function pictureInto(img, t) {
  trayPicture(t).then(url => { if (url) { img.src = url; img.hidden = false; } });
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
    Object.assign(g, {fits: r.fits, problems: r.problems, cost: r.cost, sun: r.sun || [], energy: r.energy, drawnAt: sent, answered: true});
    drawGhost(r.parts, r.fits);
    schedulePreview();
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
  ghost = {p, index, was: index < placements.length ? placements[index] : null, follow: false, fits: true, problems: [],
           drawnAt: null, busy: false, again: false, cost: null, answered: false, inputs: {}};
  view.classList.add('placing'); view.classList.remove('pickable', 'looking');
  looking = false;
  renderTray(); renderPlaced(); renderGhostBar();
  // Where the ghost is: in sight (a phone's page has scrolled down to the tray).
  sceneIntoView();
  if (!ghost.was) {
    const rect = renderer.domElement.getBoundingClientRect();
    const at = sceneHit(rect.left + rect.width / 2, rect.top + rect.height / 2);
    if (at) { setKnob(ghost.p, 'x_m', at.x); setKnob(ghost.p, 'z_m', at.z); showGhostKnobs(); }
  }
  askGhost();
}

// A piece set down, made a ghost again to move, change or turn it (from the
// panel, or by clicking it in the scene). After a run, or during one, the
// level goes back to its start first: pieces are placed there.
function pickUp(i) {
  if (!placements[i]) return;
  if (playing || world.t > 0) rebuildLevel(false).catch(() => {});
  startGhost({...placements[i]}, i);
}

function endGhost() {
  ghost = null; draggingGhost = null;
  clearGhostMeshes(); ghostGroup.position.set(0, 0, 0);
  view.classList.remove('placing', 'looking');
  looking = false;
  renderGhostBar();
}

function cancelGhost() { if (!ghost) return; endGhost(); renderTray(); renderPlaced(); schedulePreview(200); }

function setGhostDown() {
  if (!ghost || !ghost.fits || ghost.busy || !ghost.answered) return;
  if (ghost.was) placements[ghost.index] = ghost.p; else placements.push(ghost.p);
  endGhost(); renderTray(); renderPlaced(); scheduleRebuild(0);
}

// The ghost's own controls, just below the scene and out of its way (the top
// of the side panel, kept in sight as the panel scrolls): on a phone the list
// of pieces is a scroll away. One knob at a time -- its chip picks which --
// with - and + either side of its slider, and Set down.
function knobName(rule, key) { return (rule.label || key).replace(/\s*\(.*\)\s*$/, ''); }

function nudgeKnob(key, by) {
  if (ghost && setKnob(ghost.p, key, (ghost.p[key] ?? 0) + by)) { followGhost(); showGhostKnobs(); askGhost(); }
}

function renderGhostBar() {
  renderMovePad();
  const card = $('ghost-bar');
  card.hidden = !ghost;
  ghost && (ghost.cardInput = null);
  if (!ghost) { card.replaceChildren(); return; }
  const throwAway = button('✕', cancelGhost, {ariaLabel: 'Throw the ghost away', title: 'Throw the ghost away'});
  const head = Object.assign(document.createElement('p'), {className: 'head',
    textContent: looking ? `Looking around: drag to turn the view; ✋ (or Esc) to move your ${ghost.p.piece} again`
      : `Your ${ghost.p.piece}: drag it, use the arrows, or ${matchMedia('(pointer: coarse)').matches ? 'tap' : 'click'} where it goes; 👁 (or Esc) to look around`});
  // Where it stands is the arrows' and the drag's; the chips change the rest.
  const knobs = trayItem(ghost.p.piece).knobs, keys = Object.keys(knobs).filter(k => k !== 'x_m' && k !== 'z_m');
  if (!keys.includes(ghost.card)) ghost.card = keys[0];
  const chips = Object.assign(document.createElement('div'), {className: 'chips'});
  for (const key of keys) {
    const chip = button(knobName(knobs[key], key), () => { ghost.card = key; renderGhostBar(); },
                        {ariaLabel: `Change its ${knobName(knobs[key], key)}`});
    chip.setAttribute('aria-pressed', String(key === ghost.card));
    chips.append(chip);
  }
  const key = ghost.card, rule = knobs[key], name = knobName(rule, key);
  const row = Object.assign(document.createElement('div'), {className: 'knob-row'});
  if (rule.choices) {
    const select = document.createElement('select');
    for (const c of rule.choices) select.append(Object.assign(document.createElement('option'), {value: c, textContent: c}));
    select.value = ghost.p[key];
    select.setAttribute('aria-label', `Its ${name}`);
    select.addEventListener('change', () => {
      ghost.p[key] = rule.choices.find(c => String(c) === select.value) ?? select.value;
      showGhostKnobs(); askGhost();
    });
    row.append(select);
  } else {
    const step = rule.turning ? 15 : (rule.step || 0.01) * 5;
    const input = Object.assign(document.createElement('input'), {type: 'range', min: rule.min, max: rule.max,
      step: rule.step || 0.01, value: ghost.p[key]});
    input.setAttribute('aria-label', `Its ${name}`);
    input.addEventListener('input', () => { if (setKnob(ghost.p, key, Number(input.value))) { followGhost(); showGhostKnobs(); askGhost(); } });
    const shown = document.createElement('output');
    row.append(button('−', () => nudgeKnob(key, -step), {ariaLabel: `Less ${name}`}), input,
               button('+', () => nudgeKnob(key, step), {ariaLabel: `More ${name}`}), shown);
    ghost.cardInput = [input, shown, key];
  }
  const state = Object.assign(document.createElement('p'), {className: 'state'});
  const actions = Object.assign(document.createElement('div'), {className: 'actions'});
  actions.append(button('✓ Set down', setGhostDown, {className: 'down', disabled: !ghost.fits || ghost.busy}), throwAway);
  card.replaceChildren(head, chips, row, state, actions);
  showGhostKnobs(); showGhostState();
}

// What the pieces take to make with the ghost as it is, against the level's
// par: said while it is changed, so cutting a plank shorter shows the
// number fall. (Par is for the whole win, the run's energy too; on most
// levels that is next to nothing.)
function madeAgainstPar() {
  const mine = `your ${ghost.p.piece} ${ghost.index + 1}`;
  const others = Object.entries(placedEnergy).filter(([name]) => name !== mine).reduce((a, [, e]) => a + (e.j || 0), 0);
  const it = ghost.energy.j, all = others + it, par = level && level.par_energy_j;
  let said = `It takes ${energyText(it)} to make`;
  if (others) said += `; with your other pieces, ${energyText(all)}`;
  if (!par) return said + '.';
  return said + (all <= par ? `: under par (${energyText(par)}).` : `: ${energyText(all - par)} over par (${energyText(par)}).`);
}

function showGhostState() {
  const bar = document.querySelector('#ghost-bar .down');
  if (bar && ghost) bar.disabled = !ghost.fits || ghost.busy || !ghost.answered;
  const said = document.querySelector('#ghost-bar .state');
  if (said && ghost) {
    said.className = 'state ' + (ghost.fits ? 'fits' : 'refused');
    said.textContent = (ghost.follow ? 'It follows the pointer: click where it should go. ' : '') + (ghost.fits ? (ghost.sun && ghost.sun.length
      ? `Faces ${ghost.sun[0].off_sun_deg}° off the sun: about ${Math.round(ghost.sun[0].sunlight_w)} W.` : 'It fits here.')
      : ghost.problems.join('; ')) + (ghost.fits && ghost.energy ? ' ' + madeAgainstPar() : '');
  }
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
  if (head && ghost.energy) head.textContent = ` · ${energyText(ghost.energy.j)} to make`;
}

function showGhostKnobs() {
  if (!ghost) return;
  const knobs = trayItem(ghost.p.piece).knobs;
  for (const [key, [input, shown]] of Object.entries(ghost.inputs)) {
    if (String(input.value) !== String(ghost.p[key])) input.value = ghost.p[key];
    shown.textContent = String(ghost.p[key]) + (knobs[key].turning ? '°' : '');
  }
  if (ghost.cardInput) {
    const [input, shown, key] = ghost.cardInput;
    if (String(input.value) !== String(ghost.p[key])) input.value = ghost.p[key];
    shown.textContent = String(ghost.p[key]) + (knobs[key].turning ? '°' : '');
  }
}

window.machineGhostState = () => ghost ? {p: {...ghost.p}, index: ghost.index, fits: ghost.fits, problems: ghost.problems,
  follow: ghost.follow, busy: ghost.busy, answered: ghost.answered, parts: ghostGroup.children.length} : null;

// ---- the preview: where things will go ----------------------------------------------
// Before a run (and while it plays), the engine's own rehearsal of the level
// as it stands -- with a ghost as if it were set down -- drawn see-through:
// each loose thing's path, blue while it moves freely, green inside the goal
// zone, and after it hits something, that thing's colour, with a dot where it
// hit. A see-through copy of the goal's thing stands where it ends up.
const previewGroup = new THREE.Group();
scene.add(previewGroup);
const HIT_COLOURS = [0xffb347, 0xff6bd6, 0xc38bff, 0xffe066, 0x7cf0e0, 0xff8080];
const FREE_COLOUR = 0x9fdcff, GOAL_COLOUR = 0x5fe08f;
const PREVIEW_DOT = new THREE.SphereGeometry(.02, 12, 8);
const previewEndLook = new THREE.MeshStandardMaterial({color: 0xcdeeff, transparent: true, opacity: .3, depthWrite: false});
let previewAsk = 0, previewTimer = null, previewOn = true, previewShown = null;

function clearPreview() {
  for (const c of [...previewGroup.children]) {
    previewGroup.remove(c);
    c.traverse(o => { if (o.geometry && !o.userData.shared) o.geometry.dispose(); });
  }
  previewShown = null;
  showPreviewLegend(null);
}

function schedulePreview(ms = 700) {
  clearTimeout(previewTimer);
  if (!LEVEL_MODE || !level || !previewOn) return;
  previewTimer = setTimeout(() => askPreview().catch(() => {}), ms);
}

async function askPreview() {
  if (!LEVEL_MODE || !level || !previewOn || playing) return;
  // A ghost that does not fit, or is still being worked out: nothing to rehearse.
  if (ghost && (!ghost.answered || !ghost.fits)) { clearPreview(); return; }
  const mine = ++previewAsk, list = ghost ? ghostPlacements() : placements;
  try {
    const r = await api({op: 'level_preview', level: level.id, placements: list});
    if (mine === previewAsk && !playing) drawPreview(r);
  } catch (e) {
    if (mine !== previewAsk) return;
    clearPreview();                     // a piece the goal needs is not placed yet, or it cannot be built
    if (e.status === 503 && previewOn) previewTimer = setTimeout(() => askPreview().catch(() => {}), 2500);
  }
}

function drawPreview(r) {
  clearPreview();
  previewShown = r;
  const zone = level.goal.station.done_when.in_zone;
  const inZone = p => Boolean(zone) && [0, 1, 2].every(i => Math.abs(p[i] - zone.at_m[i]) <= zone.size_m[i] / 2);
  const colourOf = new Map(), dotShape = PREVIEW_DOT;
  for (const path of r.paths) {
    const hits = r.hits.filter(h => h.body === path.name).sort((a, b) => a.t - b.t);
    const positions = [], colours = [];
    let current = new THREE.Color(FREE_COLOUR), k = 0;
    for (const [t, x, y, z] of path.points) {
      for (; k < hits.length && hits[k].t <= t; k++) {
        const other = hits[k].other;
        if (!colourOf.has(other)) colourOf.set(other, HIT_COLOURS[colourOf.size % HIT_COLOURS.length]);
        current = new THREE.Color(colourOf.get(other));
        const dot = new THREE.Mesh(dotShape, new THREE.MeshBasicMaterial({color: current, transparent: true, opacity: .9}));
        dot.userData.shared = true;
        dot.position.set(x, y, z);
        previewGroup.add(dot);
      }
      const c = inZone([x, y, z]) ? new THREE.Color(GOAL_COLOUR) : current;
      positions.push(x, y, z); colours.push(c.r, c.g, c.b);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(colours, 3));
    previewGroup.add(new THREE.Line(geometry, new THREE.LineBasicMaterial({vertexColors: true, transparent: true,
      opacity: path.goal ? .95 : .6})));
    const dots = new THREE.Points(geometry, new THREE.PointsMaterial({vertexColors: true, size: path.goal ? .045 : .025,
      transparent: true, opacity: .75}));
    dots.userData.shared = true;                 // the line's geometry: disposed once, with it
    previewGroup.add(dots);
    const mesh = path.goal && meshes.get(path.name);
    if (mesh && path.points.length) {
      // Where the goal's thing comes to rest (or is at the end), see-through.
      const end = mesh.clone(true), last = path.points[path.points.length - 1];
      end.traverse(o => { if (o.isMesh) { o.material = previewEndLook; o.castShadow = false; o.userData.shared = true; } });
      end.userData.shared = true;
      end.position.set(last[1], last[2], last[3]);
      const q = path.turn_wxyz;
      if (q) end.quaternion.set(q[1], q[2], q[3], q[0]);
      previewGroup.add(end);
    }
  }
  showPreviewLegend(r, colourOf);
}

function showPreviewLegend(r, colourOf) {
  const box = $('preview-legend');
  box.replaceChildren();
  box.hidden = !r;
  if (!r) return;
  box.append(Object.assign(document.createElement('p'), {className: 'head',
    textContent: r.goal_at_s != null ? `Predicted: the goal at ${describeTime(r.goal_at_s)}` : 'Predicted: the goal does not happen'}));
  const chip = (colour, text) => {
    const s = Object.assign(document.createElement('span'), {className: 'chip', textContent: text});
    s.style.setProperty('--c', '#' + new THREE.Color(colour).getHexString());
    return s;
  };
  const row = Object.assign(document.createElement('p'), {className: 'chips'});
  row.append(chip(FREE_COLOUR, 'moving'), chip(GOAL_COLOUR, 'in the goal'));
  for (const [name, colour] of colourOf) row.append(chip(colour, `after it hits ${name}`));
  box.append(row);
}

window.machinePreviewState = () => previewShown && {paths: previewShown.paths.map(p => ({name: p.name, goal: p.goal,
  points: p.points.length})), hits: previewShown.hits.length, goal_at_s: previewShown.goal_at_s,
  legend: $('preview-legend').textContent};

$('path-toggle').addEventListener('click', () => {
  previewOn = !previewOn;
  $('path-toggle').setAttribute('aria-pressed', String(previewOn));
  if (previewOn) schedulePreview(0); else { clearTimeout(previewTimer); previewAsk++; clearPreview(); }
});

// Moving a piece, as 3D builders do it. A press near it -- anywhere within a
// generous margin of it on the screen, not only on its few pixels -- takes
// hold of it; on a touch screen one finger anywhere does (two fingers turn
// and zoom the view). It then slides on a level plane at the height it
// stands, by however far the pointer moves over that plane: it never jumps
// onto whatever is behind the pointer. A tap or click that does not move
// puts it there, unless it was on the piece itself. Any other drag turns the
// view.
const ghostBox = new THREE.Box3(), boxCorner = new THREE.Vector3(), slidePlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
function ghostScreenBox() {
  if (!ghost || !ghostGroup.children.length) return null;
  ghostBox.setFromObject(ghostGroup);
  if (ghostBox.isEmpty()) return null;
  const rect = renderer.domElement.getBoundingClientRect();
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (let i = 0; i < 8; i++) {
    boxCorner.set(i & 1 ? ghostBox.max.x : ghostBox.min.x, i & 2 ? ghostBox.max.y : ghostBox.min.y,
                  i & 4 ? ghostBox.max.z : ghostBox.min.z).project(camera);
    const sx = rect.left + (boxCorner.x + 1) / 2 * rect.width, sy = rect.top + (1 - boxCorner.y) / 2 * rect.height;
    x0 = Math.min(x0, sx); x1 = Math.max(x1, sx); y0 = Math.min(y0, sy); y1 = Math.max(y1, sy);
  }
  return {x0, x1, y0, y1, bottom: ghostBox.min.y};
}
function nearGhost(clientX, clientY, margin) {
  const b = ghostScreenBox();
  return Boolean(b) && clientX >= b.x0 - margin && clientX <= b.x1 + margin && clientY >= b.y0 - margin && clientY <= b.y1 + margin;
}
function slidePoint(clientX, clientY, y) {
  const rect = renderer.domElement.getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2((clientX - rect.left) / rect.width * 2 - 1, -(clientY - rect.top) / rect.height * 2 + 1), camera);
  slidePlane.constant = -y;
  return raycaster.ray.intersectPlane(slidePlane, new THREE.Vector3());
}
const GRAB_MARGIN_PX = 40;
// Which of the player's pieces (its index), if any, is the first thing under
// the pointer in the scene.
function placedAt(clientX, clientY) {
  if (!LEVEL_MODE || !level || !placements.length) return -1;
  const rect = renderer.domElement.getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2((clientX - rect.left) / rect.width * 2 - 1, -(clientY - rect.top) / rect.height * 2 + 1), camera);
  const nameOf = new Map([...meshes].map(([name, m]) => [m, name]));
  const hit = raycaster.intersectObjects([...nameOf.keys()].filter(m => m.visible), true).find(h => h.object.isMesh);
  let o = hit && hit.object;
  while (o && !nameOf.has(o)) o = o.parent;
  const m = o && nameOf.get(o).match(/^your (\S+) (\d+)(?: |$)/);
  const i = m ? Number(m[2]) - 1 : -1;
  return i >= 0 && placements[i] && placements[i].piece === m[1] ? i : -1;
}
// For tests: where a body is on the page (the middle of its mesh).
window.machineBodyScreen = name => {
  const mesh = meshes.get(name);
  if (!mesh) return null;
  const c = new THREE.Box3().setFromObject(mesh).getCenter(new THREE.Vector3()).project(camera), rect = renderer.domElement.getBoundingClientRect();
  return [rect.left + (c.x + 1) / 2 * rect.width, rect.top + (1 - c.y) / 2 * rect.height];
};
// For tests: where the piece being placed is on the screen, and the view.
window.machineGhostScreen = () => ghostScreenBox();
window.machineCamera = () => ({azimuth, elevation, distance, guides: guides.visible});
renderer.domElement.addEventListener('pointerdown', e => {
  pressedAt = [e.clientX, e.clientY];
  draggingGhost = null;
  // A second finger: the view, not the piece.
  if (!ghost || ghost.follow || pointers.size > 1 || looking) return;
  if (e.pointerType === 'touch' || nearGhost(e.clientX, e.clientY, GRAB_MARGIN_PX)) {
    const box = ghostScreenBox(), y = box ? box.bottom : 0, from = slidePoint(e.clientX, e.clientY, y);
    if (from) draggingGhost = {y, from, x: ghost.p.x_m ?? 0, z: ghost.p.z_m ?? 0};
    view.classList.add('grabbing');
  }
});
renderer.domElement.addEventListener('pointermove', e => {
  if (!ghost) {
    view.classList.remove('grab');
    // A piece of yours under the mouse can be clicked to pick it up.
    if (!e.buttons && e.pointerType === 'mouse') view.classList.toggle('pickable', !pullMode && placedAt(e.clientX, e.clientY) >= 0);
    return;
  }
  if (draggingGhost && pointers.size <= 1) {
    const at = slidePoint(e.clientX, e.clientY, draggingGhost.y);
    if (!at) return;
    const moved = [setKnob(ghost.p, 'x_m', draggingGhost.x + at.x - draggingGhost.from.x),
                   setKnob(ghost.p, 'z_m', draggingGhost.z + at.z - draggingGhost.from.z)].some(Boolean);
    if (moved) { followGhost(); showGhostKnobs(); askGhost(); }
  } else if (ghost.follow && !e.buttons) moveGhostTo(e.clientX, e.clientY);
  else if (!e.buttons) view.classList.toggle('grab', !ghost.follow && !looking && nearGhost(e.clientX, e.clientY, GRAB_MARGIN_PX));
});
renderer.domElement.addEventListener('pointerup', e => {
  const click = pressedAt && Math.hypot(e.clientX - pressedAt[0], e.clientY - pressedAt[1]) < 6;
  if (ghost && click && !looking && (ghost.follow || !nearGhost(e.clientX, e.clientY, 0))) {
    moveGhostTo(e.clientX, e.clientY);
    if (ghost.follow) { ghost.follow = false; renderPlaced(); renderGhostBar(); showGhostState(); }
  } else if (!ghost && click && !pullMode) {
    const i = placedAt(e.clientX, e.clientY);
    if (i >= 0) pickUp(i);
  }
  draggingGhost = null; pressedAt = null;
  view.classList.remove('grabbing');
});

// Guides through the piece being placed, as 3D editors draw them: a line
// along x (red) and along z (blue) through it to the horizon at the height
// it stands, the same on the ground beneath when it stands above it, and a
// vertical line (green) down to a mark on the ground under it.
const guides = new THREE.Group();
guides.visible = false;
scene.add(guides);
// Bars, not lines: a WebGL line is one pixel whatever the distance, too thin
// to see; a bar is kept two or three pixels thick by the camera's distance.
const barShape = new THREE.BoxGeometry(1, 1, 1);
function guideBar(colour, opacity) {
  const bar = new THREE.Mesh(barShape, new THREE.MeshBasicMaterial({color: colour, transparent: true, opacity, depthWrite: false}));
  bar.frustumCulled = false;
  guides.add(bar);
  return bar;
}
const guideX = guideBar(0xff5c5c, .85), guideZ = guideBar(0x4d9dff, .85), guideY = guideBar(0x6fe08a, .9);
const guideGroundX = guideBar(0xff5c5c, .4), guideGroundZ = guideBar(0x4d9dff, .4);
const guideFoot = new THREE.Mesh(new THREE.RingGeometry(.035, .05, 28),
  new THREE.MeshBasicMaterial({color: 0x6fe08f, transparent: true, opacity: .9, side: THREE.DoubleSide}));
guideFoot.rotation.x = -Math.PI / 2;
guides.add(guideFoot);
function updateGuides() {
  guides.visible = Boolean(ghost && ghostGroup.children.length);
  if (!guides.visible) return;
  ghostBox.setFromObject(ghostGroup);
  if (ghostBox.isEmpty()) { guides.visible = false; return; }
  const cx = (ghostBox.min.x + ghostBox.max.x) / 2, cz = (ghostBox.min.z + ghostBox.max.z) / 2;
  const base = Math.max(.004, ghostBox.min.y), top = ghostBox.max.y + .4, far = 50;
  const t = Math.max(.004, .0025 * camera.position.distanceTo(new THREE.Vector3(cx, base, cz)));
  guideX.position.set(cx, base, cz); guideX.scale.set(far, t, t);
  guideZ.position.set(cx, base, cz); guideZ.scale.set(t, t, far);
  guideY.position.set(cx, top / 2, cz); guideY.scale.set(t, top, t);
  const raised = base > .03;
  guideGroundX.visible = guideGroundZ.visible = raised;
  guideGroundX.position.set(cx, .004, cz); guideGroundX.scale.set(far, .002, t);
  guideGroundZ.position.set(cx, .004, cz); guideGroundZ.scale.set(t, .002, far);
  guideFoot.position.set(cx, .005, cz);
}
// ---- testing a part: a pull ----------------------------------------------------
// With Pull on, pressing a loose part and dragging pulls it that way -- the
// engine's own force at that point of it, no hand in the world -- harder the
// further the pointer goes from the point (PULL_N_PER_M), up to PULL_MAX_N.
// A line is the string. Letting go lets go. The work the pull does counts in
// what the run took (the win card says so). It pulls while the world runs, and
// starts it if it is not running.
const PULL_N_PER_M = 400, PULL_MAX_N = 200;
let pullMode = false, pulling = null;
const pullLine = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
                                new THREE.LineBasicMaterial({color: 0xffd34d}));
pullLine.visible = false;
pullLine.frustumCulled = false;
scene.add(pullLine);
$('pull-tool').addEventListener('click', () => {
  pullMode = !pullMode;
  $('pull-tool').setAttribute('aria-pressed', String(pullMode));
  view.classList.toggle('pulling-mode', pullMode);
});
// The loose part under the pointer, and the point of it there.
function pullTarget(clientX, clientY) {
  const rect = renderer.domElement.getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2((clientX - rect.left) / rect.width * 2 - 1, -(clientY - rect.top) / rect.height * 2 + 1), camera);
  const nameOf = new Map([...meshes].map(([name, m]) => [m, name]));
  const hit = raycaster.intersectObjects([...nameOf.keys()].filter(m => m.visible), true).find(h => h.object.isMesh);
  let o = hit && hit.object;
  while (o && !nameOf.has(o)) o = o.parent;
  const name = o && nameOf.get(o), body = name && world.bodies.get(name);
  if (!body || body.anchored) return null;
  return {name, mesh: o, local: o.worldToLocal(hit.point.clone()), plane: new THREE.Plane().setFromNormalAndCoplanarPoint(
    camera.getWorldDirection(new THREE.Vector3()).negate(), hit.point)};
}
function pullForce(clientX, clientY) {
  const rect = renderer.domElement.getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2((clientX - rect.left) / rect.width * 2 - 1, -(clientY - rect.top) / rect.height * 2 + 1), camera);
  const to = raycaster.ray.intersectPlane(pulling.plane, new THREE.Vector3());
  const at = pulling.mesh.localToWorld(pulling.local.clone());
  if (!to) return {at, to: at, force: new THREE.Vector3()};
  const force = to.clone().sub(at).multiplyScalar(PULL_N_PER_M);
  if (force.length() > PULL_MAX_N) force.setLength(PULL_MAX_N);
  return {at, to, force};
}
let pullSent = 0;
function sendPull(force, at, now = false) {
  if (!pulling || !session) return;
  const stamp = performance.now();
  if (!now && stamp - pullSent < 100) return;
  pullSent = stamp;
  api({op: 'pull', session, body: pulling.name, at: at.toArray().map(v => +v.toFixed(4)),
       force: force.toArray().map(v => +v.toFixed(2))}).catch(() => {});
}
renderer.domElement.addEventListener('pointerdown', e => {
  if (!pullMode || ghost || pointers.size > 1) return;
  const target = pullTarget(e.clientX, e.clientY);
  if (!target) return;
  pulling = {...target, clientX: e.clientX, clientY: e.clientY};
  pullLine.visible = true;
  if (!playing) setPlaying(true).catch(() => {});
});
renderer.domElement.addEventListener('pointermove', e => {
  if (!pulling) return;
  pulling.clientX = e.clientX; pulling.clientY = e.clientY;
  const {at, force} = pullForce(e.clientX, e.clientY);
  sendPull(force, at);
});
const letGo = () => {
  if (!pulling) return;
  const {at} = pullForce(pulling.clientX, pulling.clientY);
  sendPull(new THREE.Vector3(), at, true);
  pulling = null;
  pullLine.visible = false;
  $('clock').title = '';
};
renderer.domElement.addEventListener('pointerup', letGo);
renderer.domElement.addEventListener('pointercancel', letGo);
// Each frame: the string from the point of the part to the pointer, and the
// force sent again as the part moves under it.
function drawPull() {
  if (!pulling) return;
  const {at, to, force} = pullForce(pulling.clientX, pulling.clientY);
  pullLine.geometry.setFromPoints([at, to]);
  pullLine.material.color.setHSL(0.14 - 0.14 * force.length() / PULL_MAX_N, 1, 0.55);
  sendPull(force, at);
  $('clock').title = `Pulling ${pulling.name} with ${Math.round(force.length())} N`;
}
window.machinePullState = () => pulling && {body: pulling.name, force_n: Math.round(pullForce(pulling.clientX, pulling.clientY).force.length())};

// Turning by hand: Shift and the wheel turns it, Alt and the wheel tips it.
renderer.domElement.addEventListener('wheel', e => {
  if (!ghost || !(e.shiftKey || e.altKey)) return;
  e.preventDefault();
  turnGhost(e.altKey ? 'pitch_deg' : 'yaw_deg', Math.sign(e.deltaY || e.deltaX) * -15);
}, {passive: false});
document.addEventListener('keydown', e => {
  if (!ghost || e.ctrlKey || e.metaKey || e.target.closest('input, textarea, select')) return;
  const key = e.key.toLowerCase(), step = e.shiftKey ? 1 : 15;
  const nudge = {arrowleft: 'left', arrowright: 'right', arrowup: 'forward', arrowdown: 'back', pageup: 'up', pagedown: 'down'}[key];
  if (TURN_KEYS[key]) turnGhost(TURN_KEYS[key][0], TURN_KEYS[key][1] * step);
  else if (nudge) moveGhostBy(nudge, e.shiftKey ? 0.1 : 0.01);
  else if (key === 'enter' && !e.target.closest('button')) setGhostDown();
  else if (key === 'escape') setLooking(!looking);
  else return;
  e.preventDefault();
});

// ---- who is playing, and how far each has got --------------------------------------
// Kept in this browser: a record per player (by name) of, for each level, the
// best stars, the least energy a win took and when it was first won. Stars
// kept the old way (one key a level) belong to the first player.
const SAVE_KEY = 'banjo-play-save';
function loadSave() {
  let s = null;
  try { s = JSON.parse(localStorage.getItem(SAVE_KEY) || 'null'); } catch { /* private window */ }
  if (!s || typeof s !== 'object' || !s.players || !Object.keys(s.players).length)
    s = {current: 'Player 1', players: {'Player 1': {levels: {}}}};
  if (!s.players[s.current]) s.current = Object.keys(s.players)[0];
  try {
    const first = s.players[Object.keys(s.players)[0]];
    for (let i = 0; i < localStorage.length; i++) {
      const m = (localStorage.key(i) || '').match(/^banjo-level-(.+)$/);
      if (!m) continue;
      const row = first.levels[m[1]] || (first.levels[m[1]] = {});
      row.stars = Math.max(row.stars || 0, Number(localStorage.getItem(m[0])) || 0);
    }
  } catch { /* private window */ }
  return s;
}
let save = loadSave();
function persist() { try { localStorage.setItem(SAVE_KEY, JSON.stringify(save)); } catch { /* private window */ } }
function me() { return save.players[save.current] || (save.players[save.current] = {levels: {}}); }
function record(id) { return me().levels[id] || {}; }
function bestStars(id) { return record(id).stars || 0; }
// A run's result, kept where it is better: more stars, or a win on less energy.
// The tools a player has won with -- a plank, a cannon, a steam engine --
// each first win with one an achievement. A player whose wins were kept
// before tools were counted has the tools of the levels they won.
const TOOL_NAMES = {plank: 'plank', knife: 'knife', cannon: 'cannon', steam: 'steam engine', ramp: 'ramp',
                    mirror: 'mirror', solar: 'solar panel', tackle: 'block and tackle', lens: 'lens'};
function toolsOf(player) {
  if (!player.tools) {
    player.tools = {};
    for (const [id, row] of Object.entries(player.levels || {})) {
      const won = levels.find(l => l.id === id);
      if (won && (row.won_at || row.stars)) for (const t of won.tray) player.tools[t.piece] ??= id;
    }
  }
  return player.tools;
}
function toolName(piece) { return TOOL_NAMES[piece] || piece; }

function keepResult(id, r) {
  const tools = toolsOf(me()), unlocked = [];
  if (r.earned.goal) for (const piece of new Set(placements.map(p => p.piece)))
    if (!tools[piece]) { tools[piece] = id; unlocked.push(piece); }
  const row = me().levels[id] || (me().levels[id] = {}), was = {...row};
  const lessEnergy = r.earned.goal && r.energy_j != null && (row.energy_j == null || r.energy_j < row.energy_j);
  if (r.stars > (row.stars || 0)) row.stars = r.stars;
  if (lessEnergy) row.energy_j = r.energy_j;
  if (r.earned.goal && !row.won_at) row.won_at = new Date().toISOString();
  me().last = id;
  persist();
  return {was, better: lessEnergy || r.stars > (was.stars || 0), unlocked};
}
window.machineSave = () => JSON.parse(JSON.stringify(save));

// Energy as a person reads it: joules, kilo-, mega-, giga-.
function energyText(j) {
  if (j == null || !Number.isFinite(j)) return '—';
  const [div, unit] = [[1e9, 'GJ'], [1e6, 'MJ'], [1e3, 'kJ'], [1, 'J']].find(([d]) => Math.abs(j) >= d) || [1, 'J'];
  const v = j / div;
  return `${v >= 100 ? Math.round(v) : v >= 10 ? v.toFixed(1) : v.toFixed(2)} ${unit}`;
}

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

// Pieces are added from the scene: a button each, with its picture, over the
// 3D view, so a piece is added, placed and set down without leaving it.
function renderSceneTray() {
  const bar = $('scene-tray');
  bar.hidden = !LEVEL_MODE || !level || Boolean(ghost);
  if (bar.hidden) return;
  bar.replaceChildren(...level.tray.map(t => {
    const left = (t.count || 1) - placements.filter(p => p.piece === t.piece).length;
    const b = button(`+ ${t.piece}`, () => {
      const p = {piece: t.piece};
      for (const [key, rule] of Object.entries(t.knobs)) p[key] = knobDefault(rule);
      startGhost(p, placements.length);
    }, {ariaLabel: `Add a ${t.piece}`, disabled: left <= 0, title: left > 0 ? `${left} left` : 'none left'});
    const img = Object.assign(document.createElement('img'), {alt: '', hidden: true});
    b.prepend(img); pictureInto(img, t);
    b.append(Object.assign(document.createElement('small'), {textContent: left > 0 ? `${left} left` : 'none left'}));
    return b;
  }));
}

// The panel's tray: a picture of each piece the level gives and how many are
// left to place (they are added with the buttons over the scene).
function renderTray() {
  renderSceneTray();
  const ul = $('tray'); ul.replaceChildren();
  for (const t of level.tray) {
    const used = placements.filter(p => p.piece === t.piece).length + (ghost && !ghost.was && ghost.p.piece === t.piece ? 1 : 0);
    const count = t.count || 1, li = document.createElement('li');
    li.className = used >= count ? 'used-up' : '';
    const img = Object.assign(document.createElement('img'), {alt: '', hidden: true});
    li.append(img, Object.assign(document.createElement('span'), {className: 'tray-name', textContent: t.piece}),
              Object.assign(document.createElement('span'), {className: 'tray-left', textContent: `${count - used} of ${count} left`}));
    pictureInto(img, t);
    ul.append(li);
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
    ghost.follow = !ghost.follow; renderPlaced(); renderGhostBar(); showGhostState();
  });
  follow.setAttribute('aria-pressed', String(ghost.follow));
  const actions = Object.assign(document.createElement('div'), {className: 'ghost-actions'});
  actions.append(follow, button('Set it down', setGhostDown, {id: 'ghost-down', disabled: true}), button('Cancel', cancelGhost));
  li.append(head, actions, Object.assign(document.createElement('p'), {id: 'ghost-state', className: 'ghost-state'}));
  ghost.inputs = {};
  const turning = Object.assign(document.createElement('fieldset'), {className: 'turning'});
  turning.append(Object.assign(document.createElement('legend'), {textContent: 'Turn it (degrees)'}));
  for (const [key, rule] of Object.entries(t.knobs)) {
    const c = knobControl(p, key, rule, what, () => { followGhost(); showGhostKnobs(); askGhost(); });
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
      textContent: 'Keys: Q/E turn · R/F tip · Z/C roll (with Shift, 1°) · arrows move it as you see it, Page Up/Down raise and lower it · Enter sets it down · Esc switches between moving it and looking around. ' +
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
    const made = placedEnergy[`your ${p.piece} ${i + 1}`];
    head.append(Object.assign(document.createElement('strong'), {textContent: `your ${p.piece} ${i + 1}${made ? ' · ' + energyText(made.j) + ' to make' : ''}`}));
    const actions = Object.assign(document.createElement('div'), {className: 'ghost-actions'});
    // Picked up, it becomes a ghost again: moved, changed, turned, set down.
    actions.append(button('Pick up', () => pickUp(i), {ariaLabel: `Pick up your ${p.piece} ${i + 1}`}),
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
  const made = Object.values(placedEnergy).reduce((a, b) => a + (b.j || 0), 0);
  $('cost-line').textContent = placements.length
    ? `Your pieces take ${energyText(made)} to make. Par for the whole win, pieces and run: ${energyText(level.par_energy_j)}.`
    : '';
  $('placed-head').hidden = !placements.length && !ghost;
}

function scheduleRebuild(ms = 350) { clearTimeout(rebuildTimer); rebuildTimer = setTimeout(() => rebuildLevel(false).catch(() => {}), ms); }

async function rebuildLevel(start) {
  // A rebuild still waiting to start would come after this one and undo it
  // (a Run pressed just after setting a piece down stayed unstarted).
  clearTimeout(rebuildTimer);
  scored = false; $('verdict').replaceChildren(); closeDone();
  try {
    const opened = await build(null, false, {op: 'level_open', level: level.id, placements, helped});
    placedCost = (opened.placements || []).map(p => p.cost);
    placedEnergy = opened.energy || {};
    renderPlaced();
    // Its goal is about a piece not placed yet: shown, not run.
    if (opened.needs) $('verdict').textContent = opened.needs;
    else if (start) await setPlaying(true);
    if (!start) schedulePreview(200);
  } catch (e) {
    const problems = e.data && e.data.problems ? e.data.problems.join('; ') : e.message;
    $('verdict').textContent = problems;
    // Still show the level as it stands, without the pieces that do not fit.
    if (placements.length && e.status === 422)
      await build(null, false, {op: 'level_open', level: level.id, placements: [], helped}).catch(() => {});
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
  const said = [r.earned.goal ? `Goal at ${describeTime(r.goal_at_s)}, on ${energyText(r.energy_j)} (par ${energyText(r.par_energy_j)}).`
                              : `The goal did not happen within ${level.time_s} s.`];
  if (r.helped) said.push('The chat placed the pieces, so one star at most.');
  v.append(' ' + said.join(' '));
  // A run pulled by hand is a test: nothing is kept for it.
  const kept = r.tested ? {was: record(level.id), better: false, unlocked: []} : keepResult(level.id, r);
  renderLevels();
  showDone(r, kept);
  // The goal happened: let what follows settle for a moment, then stop.
  const ran = session;
  if (r.earned.goal) setTimeout(() => { if (session === ran && playing) setPlaying(false).catch(() => {}); }, 1500);
}

// How the run went, over the scene: on the goal, congratulations and on to
// the next level (by itself in a few seconds, unless the player stays);
// without it, a way to try again.
let advanceTimer = null;
// Back to the level's beginning, not running: with the same pieces (to move
// or change them) or with none.
function startOver(keep) {
  endGhost();
  if (!keep) { placements = []; placedCost = []; placedEnergy = {}; helped = false; }
  renderTray(); renderPlaced();
  rebuildLevel(false).then(() => {
    if (!$('verdict').textContent) $('verdict').textContent = keep
      ? 'Back to the start, with your pieces: pick one up to move or change it, then Run it.'
      : 'Back to the start: add a piece from your tray.';
    sceneIntoView();
  }).catch(() => {});
}

function closeDone() {
  clearInterval(advanceTimer); advanceTimer = null;
  $('level-done').hidden = true; $('level-done').replaceChildren();
}
function showDone(r, kept = {was: {}, better: false, unlocked: []}) {
  closeDone();
  const box = $('level-done'), next = levels[levels.indexOf(level) + 1];
  const add = (tag, props) => box.appendChild(Object.assign(document.createElement(tag), props));
  const allLevels = button('All levels', () => { closeDone(); showLevelsScreen(true); });
  if (r.tested) {
    // Pulled by hand: what happened, and that it is a test, not a win.
    add('h2', {textContent: 'A test run'});
    add('p', {textContent: r.earned.goal ? `With your pull, the goal happened at ${describeTime(r.goal_at_s)}.`
                                         : `With your pull, the goal did not happen within ${level.time_s} s.`});
    add('p', {className: 'hint', textContent: 'A run you pull by hand tests the parts. To win, let the machine do it: run it without pulling.'});
    const actions = add('div', {className: 'actions'});
    actions.append(button('Play again', () => { closeDone(); startOver(true); }, {className: 'primary', ariaLabel: 'Play this level again'}),
                   allLevels);
  } else if (r.earned.goal) {
    // The win, and what it took: less energy is better.
    // A first win with a tool is an achievement; a win again is the level.
    const unlocked = (kept.unlocked || []).map(toolName);
    if (unlocked.length) {
      add('h2', {textContent: 'Achievement Unlocked'});
      add('p', {className: 'unlocked', textContent: `Your first win with ${unlocked.map(t => (/^[aeiou]/.test(t) ? 'an ' : 'a ') + t)
        .join(' and ')}!` + (next ? '' : ' And you finished every level!')});
    } else add('h2', {textContent: next ? 'Level complete!' : 'You finished every level!'});
    add('p', {className: 'stars', textContent: '★'.repeat(r.stars) + '☆'.repeat(3 - r.stars)});
    const e = r.energy || {}, run = e.run || {};
    add('p', {className: 'energy', textContent: `Energy used: ${energyText(r.energy_j)}`});
    add('p', {className: 'breakdown', textContent: `${energyText(e.pieces_j)} to make your pieces, ` +
      (run.j ? `${energyText(run.j)} in the run` : 'nothing used in the run') + (run.j ? ` (${[['heat', run.heat_j], ['powder', run.powder_j],
      ['electricity', run.electric_j], ['your pulls', run.pull_j]].filter(([, j]) => j).map(([w, j]) => `${w} ${energyText(j)}`).join(', ')})` : '') + '.'});
    // Par is the level's own solution's energy, rounded up: within 1% of it is on par.
    const par = r.par_energy_j, verdict = r.energy_j < 0.99 * par ? `Under par (${energyText(par)})!`
      : r.energy_j <= par ? `At par (${energyText(par)}).` : `Par is ${energyText(par)}.`;
    const best = kept.was.energy_j != null
      ? (r.energy_j < kept.was.energy_j ? ` New best for ${save.current}!` : ` Your best: ${energyText(kept.was.energy_j)}.`) : '';
    add('p', {textContent: `Goal at ${describeTime(r.goal_at_s)}. ${verdict}${best}`});
    // What each piece took, and how far from par: a piece made of the same
    // stuff takes energy in proportion to its weight.
    const pieces = Object.entries(e.pieces || {});
    if (pieces.length) add('p', {className: 'breakdown', textContent: pieces.map(([name, m]) =>
      `${name[0].toUpperCase() + name.slice(1)}: ${Number(Number(m.kg).toPrecision(3))} kg, ${energyText(m.j)}`).join('; ') + '.'});
    if (r.stars < 3) {
      const over = r.energy_j - par, heavy = pieces.sort((a, b) => b[1].j - a[1].j)[0];
      add('p', {className: 'hint', textContent: r.helped ? 'Place the pieces yourself for more stars.'
        : heavy && over > 0 && over < heavy[1].j
          ? `To reach par, take ${energyText(over)} off: ${heavy[0]} about ${Math.ceil(100 * over / heavy[1].j)}% lighter ` +
            '(shorter, smaller or a cheaper material) and still reaching the goal.'
          : 'Win on less energy for more stars: smaller or lighter pieces, cheaper materials, less fuel.'});
    }
    const actions = add('div', {className: 'actions'});
    if (next) actions.append(button('Next level ▶', () => { closeDone(); chooseLevel(next.id).catch(() => {}); },
                                    {className: 'primary', ariaLabel: 'Next level'}));
    actions.append(button('Play again', () => { closeDone(); startOver(true); }, {ariaLabel: 'Play this level again'}),
                   allLevels);
  } else {
    // Running the same pieces again does the same thing: start the level
    // over, with no pieces or with the same ones to change.
    add('h2', {textContent: 'Not this time'});
    add('p', {textContent: `The goal did not happen within ${level.time_s} s.`});
    const actions = add('div', {className: 'actions'});
    actions.append(button('Start over', () => { closeDone(); startOver(false); }, {className: 'primary'}),
                   button('Keep my pieces', () => { closeDone(); startOver(true); }), allLevels);
  }
  box.hidden = false;
  sceneIntoView();
}

// ---- the levels screen: every level, and how far this player has got --------------------
function showLevelsScreen(show) {
  const box = $('levels-screen');
  box.hidden = !show;
  document.body.classList.toggle('on-levels', show);
  if (!show) { resize(); return; }
  box.replaceChildren();
  const add = (parent, tag, props) => parent.appendChild(Object.assign(document.createElement(tag), props));
  const head = add(box, 'div', {className: 'ls-head'});
  add(head, 'h1', {textContent: 'Levels'});
  if (level) head.append(button(`Back to ${levels.indexOf(level) + 1}. ${level.title}`, () => showLevelsScreen(false)));
  // Who is playing: each name keeps its own progress, in this browser.
  const who = add(box, 'form', {className: 'ls-player'});
  add(who, 'label', {textContent: 'Player', htmlFor: 'player-pick'});
  const pick = add(who, 'select', {id: 'player-pick'});
  for (const name of Object.keys(save.players)) pick.append(new Option(name, name, false, name === save.current));
  pick.addEventListener('change', () => { save.current = pick.value; persist(); renderLevels(); showLevelsScreen(true); });
  const fresh = add(who, 'input', {type: 'text', maxLength: 24, placeholder: 'New player’s name'});
  fresh.setAttribute('aria-label', 'New player’s name');
  who.append(button('Add player', () => {
    const name = fresh.value.trim();
    if (!name) { fresh.focus(); return; }
    if (!save.players[name]) save.players[name] = {levels: {}};
    save.current = name; persist(); renderLevels(); showLevelsScreen(true);
  }, {type: 'submit'}));
  who.addEventListener('submit', e => e.preventDefault());
  const won = levels.filter(l => bestStars(l.id) > 0).length, starsAll = levels.reduce((s, l) => s + bestStars(l.id), 0);
  const nextUp = levels.find(l => !bestStars(l.id));
  add(box, 'p', {className: 'ls-summary', textContent: `${save.current}: ${won} of ${levels.length} levels won, ` +
    `${starsAll} of ${levels.length * 3} stars.` + (nextUp ? ` Next up: ${levels.indexOf(nextUp) + 1}. ${nextUp.title}.` : ' Every level won!')});
  const list = add(box, 'ol', {className: 'ls-list'});
  levels.forEach((l, i) => {
    const row = record(l.id), li = add(list, 'li', {});
    li.classList.toggle('won', Boolean(row.stars)); li.classList.toggle('next', l === nextUp);
    const card = button('', () => { showLevelsScreen(false); chooseLevel(l.id).catch(() => {}); },
                        {className: 'ls-card', ariaLabel: `Play level ${i + 1}, ${l.title}`});
    add(card, 'strong', {textContent: `${i + 1}. ${l.title}`});
    add(card, 'span', {className: 'stars', textContent: '★'.repeat(row.stars || 0) + '☆'.repeat(3 - (row.stars || 0))});
    add(card, 'span', {className: 'teaches', textContent: l.teaches});
    add(card, 'span', {className: 'status', textContent: row.energy_j != null
      ? `Best win: ${energyText(row.energy_j)} (par ${energyText(l.par_energy_j)})`
      : row.stars ? 'Won' : l === nextUp ? 'Next up' : 'Not won yet'});
    li.append(card);
  });
}
$('levels-open').addEventListener('click', e => {
  if (!LEVEL_MODE || !levels.length) return;
  e.preventDefault(); showLevelsScreen(true);
});
// Looking around the scene while it counts down: stay, and look.
renderer.domElement.addEventListener('pointerdown', () => {
  if (!advanceTimer) return;
  clearInterval(advanceTimer); advanceTimer = null;
  const count = document.querySelector('#level-done .count');
  if (count) count.textContent = '';
});

async function chooseLevel(id) {
  level = levels.find(l => l.id === id) || levels[0];
  endGhost(); closeDone(); previewAsk++; clearPreview();
  placements = []; placedCost = []; placedEnergy = {}; helped = false; lastRun = null;
  history_.replaceState(null, '', '/play?level=' + level.id);
  $('title').textContent = `${levels.indexOf(level) + 1}. ${level.title}`;
  $('brief').textContent = level.brief;
  $('goal-line').textContent = `Goal: ${level.goal.title.toLowerCase()} within ${level.time_s} s, on as little energy as you can `+
    `(par ${energyText(level.par_energy_j)}, pieces and run). It teaches ${level.teaches}.`;
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

// How to play: shown on a first visit, and again from the header's link.
function showGuide(show) {
  $('guide').hidden = !show;
  if (!show) { try { localStorage.setItem('banjo-play-guide-seen', '1'); } catch { /* private window */ } }
}
$('guide-done').addEventListener('click', () => showGuide(false));
$('guide-open').addEventListener('click', e => {
  if (!LEVEL_MODE) return;
  e.preventDefault(); showGuide(true); $('guide').scrollIntoView({block: 'nearest'});
});

// What a player tells us: with the level and pieces it is about, to the
// server's log. Nothing that names them is sent.
$('feedback-form').addEventListener('submit', async e => {
  e.preventDefault();
  const text = $('feedback-text').value.trim();
  if (!text) return;
  $('feedback-send').disabled = true;
  try {
    await api({op: 'feedback', text, level: level && level.id, placements, last_run: lastRun,
               screen: [innerWidth, innerHeight], touch: matchMedia('(pointer: coarse)').matches});
    $('feedback-text').value = '';
    $('feedback-status').textContent = 'Thank you: it is with us.';
  } catch (err) { $('feedback-status').textContent = err.message; }
  finally { $('feedback-send').disabled = false; }
});

async function startGame() {
  document.body.classList.add('playing-level');
  // A level plays at real time, the camera following what moves, its path
  // shown: the sandbox's switches for those are not on the game page.
  for (const id of ['follow', 'path-toggle']) $(id).hidden = true;
  document.querySelector('#scene-actions .speed').hidden = true;
  // What the player works with, together at the top of the scene: the
  // pieces to add (the arrows while one is placed), Run it and Set up again,
  // and the prediction's key. The scene below is left to watch.
  const top = Object.assign(document.createElement('div'), {className: 'scene-top'});
  top.append($('scene-tray'), $('move-pad'), $('scene-actions'), $('preview-legend'));
  view.append(top);
  $('scene-note').textContent = 'Drag to turn the view · Wheel or pinch to zoom · Click one of your pieces to pick it up';
  let seen = false;
  try { seen = Boolean(localStorage.getItem('banjo-play-guide-seen')); } catch { /* private window */ }
  showGuide(!seen);
  $('game').hidden = false; $('solve').hidden = false; $('undo').hidden = true;
  document.querySelector('.lede').hidden = true;
  for (const d of document.querySelectorAll('aside details:not(#feedback)')) d.hidden = true;
  // The levels have their own screen, and the engine's readings are the
  // sandbox's: a player sees the scene, the goal and the result.
  $('levels').hidden = true;
  for (const label of ['Stations', 'Measured now', 'What happened']) {
    const part = document.querySelector(`aside section[aria-label="${label}"]`);
    if (part) part.hidden = true;
  }
  $('send').textContent = 'Ask for a hint';
  $('message').placeholder = 'Ask about this level, e.g. “Why does my ball fall short?”';
  document.querySelector('.chat h2').textContent = 'Ask for help';
  const r = await api({op: 'levels'});
  levels = r.levels;
  // /play on its own opens the levels screen, over the level this player is up to.
  const upTo = levels.find(l => !bestStars(l.id)) || levels[0];
  await chooseLevel(params.get('level') || me().last || upTo.id);
  if (!params.get('level')) showLevelsScreen(true);
}
// The scene in sight: on a phone the panel below it (the tray, Run it) is a
// scroll away, and what happens -- a ghost, a run, how it went -- is up here.
function sceneIntoView() {
  const seen = view.getBoundingClientRect();
  if (seen.top < -40 || seen.bottom > innerHeight + 40) view.scrollIntoView({block: 'start'});
}

// A ghost is not in the machine yet: set it down (or cancel it) before a run.
// Said in the panel and on the ghost's own bar, which is in sight on a phone.
function ghostInTheWay() {
  if (!ghost) return false;
  const said = `Set your ${ghost.p.piece} down first (or cancel it): a ghost is not part of the machine yet.`;
  $('verdict').textContent = said;
  const bar = document.querySelector('#ghost-bar .state');
  if (bar) { bar.className = 'state refused'; bar.textContent = said; }
  return true;
}
// A level's one button, over the scene: Run it builds the level afresh with
// the pieces and plays it; while it plays it pauses, then continues; after
// the run, Run again.
function runLevel() {
  const failed = e => { $('clock').textContent = e.message; };
  if (playing) { setPlaying(false).catch(failed); return; }
  if (ghostInTheWay()) return;
  if (session && world.t > 0 && !scored) { setPlaying(true).catch(failed); return; }
  sceneIntoView(); rebuildLevel(true).catch(() => {});
}
$('solve').addEventListener('click', () => askLevel('build'));

// Leaving the page: the server is told at once, so its world makes room for
// someone else instead of waiting to notice that the page has gone quiet.
addEventListener('pagehide', () => {
  if (session) navigator.sendBeacon('/api/machine', new Blob([JSON.stringify({op: 'close', session})], {type: 'application/json'}));
});

const history_ = window.history;
resize(); render();
if (LEVEL_MODE) startGame().catch(e => { $('clock').textContent = 'Could not load the levels: ' + e.message; });
else fetch('/machine-default.json').then(r => r.json()).then(d => build(d)).catch(e => { $('clock').textContent = 'Could not load the machine: ' + e.message; });
