// A room made of real matter, that you stand in.
//
// The playground's other stage is a thing you look at from outside, on an orbit
// camera. This one you are inside: W A S D walks, the mouse looks, and what you
// are pointing at is whatever the middle of the screen is on. That last part is
// not a convention, it is the reason this page can exist at all -- the engine
// answers "what does this ray hit" against the shapes it is really colliding,
// so the browser never has to keep its own copy of the world to point at.
//
// Everything physical here goes through the same HTTP API any other program
// would use. This page has no special access: it opens a world, steps it, asks
// what a ray hits, takes hold of things and lets go of them. If it can be done
// from here it can be done from anything.
import * as THREE from "/vendor/three.module.js";
import { rememberBlades, bladeFor, STANCES, takeHold, handTarget, dressBlades, showKerfs,
         narrateCuts } from "/blades.js";

const $ = (id) => document.getElementById(id);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

// What has gone wrong on this page, for whoever checks it from outside
// (banjoRoom.status()). A QA pass that photographs the room has to be able to
// say a picture was taken over an error, not only that it was taken.
const errorsSeen = [];
function noteError(what) {
  errorsSeen.push({ at_s: +(performance.now() / 1000).toFixed(2), what: String(what).slice(0, 400) });
  if (errorsSeen.length > 40) errorsSeen.shift();
}
addEventListener("error", (e) => noteError(e.message || e.error || "an error"));
addEventListener("unhandledrejection", (e) =>
  noteError(`unhandled: ${(e.reason && e.reason.message) || e.reason}`));

// ---------------------------------------------------------------------------
// Talking to the engine
// ---------------------------------------------------------------------------

// The server hands out a token so that only this machine's browser can drive
// it. Same handshake the other page uses.
let token = null;
async function api(path, body) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["X-Banjo-Token"] = token;
  const res = await fetch(path, body === undefined
    ? { headers }
    : { method: "POST", headers, body: JSON.stringify(body) });
  if (res.status === 403 && !token) {
    // The server hands the token out with its status rather than minting one on
    // demand, so this is where it comes from.
    const status = await (await fetch("/api/status")).json();
    token = status.csrf_token;
    if (!token) throw new Error("the server would not hand out a session token");
    return api(path, body);
  }
  const text = await res.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = { error: text.slice(0, 300) }; }
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

const world = {
  session: null,
  bodies: new Map(),      // name -> { mesh, material, dims, anchored }
  fading: [],             // pieces on their way out, being collected
  stock: new Map(),       // material -> { kg, pieces }
  sweptSince: new Map(),  // material -> kg, waiting to be announced
  workingOn: "",          // what the engine is working out, for the frame record
  held: null,             // { name, distance }
  aim: null,              // what the crosshair is on, from the engine
  busy: false,
  lastTick: 0,
  clock: 0,
  cellSize: 0.02,
  // What has happened, in the order it happened, for the model to read. A
  // model asked to change a room it cannot see has to be told what the person
  // has been doing in it, or every answer starts from the room as authored.
  story: [],
  // Why each pending fracture was started, kept until its answer lands. The
  // contact is gone from the engine by then -- the body it was about has been
  // replaced by its pieces.
  why: new Map(),
  // The pins in the room, as the engine last reported them. Only sent when the
  // SET of them changes -- one hung, one taken out, one that came off because
  // its wood was smashed -- because the angle is already in the bodies' poses
  // and sending it again sixty times a second is the traffic that was trimmed
  // out of the step reply in the first place.
  joints: [],
  // What is being drawn, and what is being loosed. See "Latches" below: a
  // thing held by ropes with a latch on it is a drawn bow, and nothing here
  // knows the word.
  drawn: null,            // { name, from: Vector3, latch, asked }
  loosing: null,          // { name, home: Vector3, latch, best }
  // For banjoRoom.ready(): whether a room is being opened, why the last attempt
  // failed, and how many frames have been drawn since one opened.
  opening: false,
  openError: null,
  framesSinceOpen: 0,
};

function remember(what) {
  world.story.push(what);
  if (world.story.length > 60) world.story.shift();
}

async function act(op, extra) {
  return api("/api/live/act", Object.assign({ session: world.session, op }, extra || {}));
}

// ---------------------------------------------------------------------------
// The room
// ---------------------------------------------------------------------------

const canvas = $("stage");
// A lost context never draws again, and nothing else on the page would say so.
canvas.addEventListener("webglcontextlost", () => noteError("the WebGL context was lost"));
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x070b0d);
scene.fog = new THREE.Fog(0x0a1116, 18, 55);

const camera = new THREE.PerspectiveCamera(72, 1, 0.05, 300);
// Eye height. A person, not a drone: the scale of the room reads wrong from
// anywhere else, and a 60 mm ball looks like a boulder from 300 mm up.
const EYE = 1.62;
camera.position.set(0, EYE, 2.6);

// Lit so that a dark rubber ball on a dark floor is still an object. The sky
// light does most of it, because a room lit by one lamp has half of every
// object in shadow and the shape of a thing is what you are trying to see.
scene.add(new THREE.HemisphereLight(0xcfe3f2, 0x1a2830, 1.5));
const key = new THREE.DirectionalLight(0xfff2dd, 1.6);
key.position.set(4, 8, 5);
scene.add(key);
const rim = new THREE.DirectionalLight(0x8cc0ff, 0.6);
rim.position.set(-6, 4, -5);
scene.add(rim);
const fill = new THREE.DirectionalLight(0xffffff, 0.35);
fill.position.set(0, 2, 8);
scene.add(fill);

// The floor the engine actually uses is a plane at y = 0. This draws it.
const grid = new THREE.GridHelper(60, 60, 0x24424f, 0x152229);
grid.material.transparent = true;
grid.material.opacity = 0.5;
scene.add(grid);
const floor = new THREE.Mesh(
  new THREE.PlaneGeometry(60, 60),
  new THREE.MeshStandardMaterial({ color: 0x1b2429, roughness: 0.95, metalness: 0.0 }));
floor.rotation.x = -Math.PI / 2;
floor.position.y = -0.002;   // just under the grid, so the lines stay visible
scene.add(floor);

// ---------------------------------------------------------------------------
// The ground and the water, as the engine reports them
// ---------------------------------------------------------------------------
//
// Both are drawn from the engine's own numbers and nothing else: the ground's
// heights and what each column is made of, sent whole when the room opens and
// afterwards only where they change; the water's surface, a few times a world
// second, over the box that holds all of it. Between two reports the surface is
// eased from one to the next -- a picture of the water moving, never a second
// opinion about where it is. The foam on the river is carried by the engine's
// own velocity field: it decorates the flow and cannot contradict it.
const GROUND_COLOURS = [new THREE.Color(0x7b776f),   // rock
                        new THREE.Color(0x6b4f32),   // soil
                        new THREE.Color(0xc9ad7c)];  // sand
const WATER_SHALLOW = new THREE.Color(0x58a7ad), WATER_DEEP = new THREE.Color(0x163f63);
const FOAM_COUNT = 700;
const WATER_EASE_MS = 260;
const ground = {
  grid: null, heights: null, surfaces: null, view: null,
  mesh: null, water: null, foam: null,
  was: null, next: null, arrived: 0, flow: null, flowBox: [0, 0, 0, 0], last: null,
};

function bytesOf(b64) {
  const s = atob(b64 || "");
  const out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; ++i) out[i] = s.charCodeAt(i);
  return out;
}

// The ground under a point, interpolated on the same diagonal as the collider.
function groundAt(x, z) {
  const g = ground.grid;
  if (!g) return 0;
  const fx = clamp((x - g.x0) / g.dx, 0, g.nx - 1), fz = clamp((z - g.z0) / g.dx, 0, g.nz - 1);
  const i = Math.min(g.nx - 2, Math.floor(fx)), j = Math.min(g.nz - 2, Math.floor(fz));
  const u = fx - i, v = fz - j, H = ground.heights, n = g.nx;
  const h00 = H[j * n + i], h10 = H[j * n + i + 1], h01 = H[(j + 1) * n + i], h11 = H[(j + 1) * n + i + 1];
  return u >= v ? h00 + u * (h10 - h00) + v * (h11 - h10) : h00 + v * (h01 - h00) + u * (h11 - h01);
}

// The water at a point from the last report: level, depth, velocity.
function waterAt(x, z) {
  const g = ground.grid;
  if (!g || !ground.next) return null;
  const i = Math.round((x - g.x0) / g.dx), j = Math.round((z - g.z0) / g.dx);
  if (i < 0 || j < 0 || i >= g.nx || j >= g.nz) return null;
  const level = ground.next[j * g.nx + i];
  if (!Number.isFinite(level)) return null;
  const [bi, bj, bn] = ground.flowBox;
  let u = 0, w = 0;
  if (ground.flow && i >= bi && j >= bj && i < bi + bn && j < bj + ground.flowBox[3]) {
    const k = (j - bj) * bn + (i - bi);
    u = ground.flow[2 * k] * 0.05; w = ground.flow[2 * k + 1] * 0.05;
  }
  return { level, depth: level - ground.heights[j * g.nx + i], u, w };
}

function clearGround() {
  for (const key of ["mesh", "water", "foam"]) {
    const thing = ground[key];
    if (!thing) continue;
    scene.remove(thing);
    thing.geometry.dispose();
    thing.material.dispose();
    ground[key] = null;
  }
  Object.assign(ground, { grid: null, heights: null, surfaces: null, view: null, was: null,
                          next: null, flow: null, last: null });
  floor.visible = true;
  grid.visible = true;
  scene.fog.near = 18;
  scene.fog.far = 55;
  $("water").hidden = true;
}

function paintGround(colours, index) {
  const c = GROUND_COLOURS[ground.surfaces[index]] || GROUND_COLOURS[1];
  colours[3 * index] = c.r; colours[3 * index + 1] = c.g; colours[3 * index + 2] = c.b;
}

function drawTerrain(block) {
  clearGround();
  const { nx, nz, cell_m: dx, x0_m: x0, z0_m: z0 } = block.grid;
  ground.grid = { nx, nz, dx, x0, z0 };
  ground.heights = new Float32Array(bytesOf(block.heights_b64).buffer);
  ground.surfaces = bytesOf(block.ground_b64);
  ground.view = block.view;
  const count = nx * nz;
  const positions = new Float32Array(3 * count), colours = new Float32Array(3 * count);
  for (let j = 0; j < nz; ++j)
    for (let i = 0; i < nx; ++i) {
      const k = j * nx + i;
      positions[3 * k] = x0 + i * dx;
      positions[3 * k + 1] = ground.heights[k];
      positions[3 * k + 2] = z0 + j * dx;
      paintGround(colours, k);
    }
  // Two triangles a quad, split along the diagonal from (i, j) to
  // (i + 1, j + 1): the split the engine's collider uses, so what is drawn is
  // the surface things actually stand on.
  const indices = new Uint32Array(6 * (nx - 1) * (nz - 1));
  let n = 0;
  for (let j = 0; j < nz - 1; ++j)
    for (let i = 0; i < nx - 1; ++i) {
      const a = j * nx + i, b = a + 1, c = a + nx, d = c + 1;
      indices[n++] = a; indices[n++] = c; indices[n++] = d;
      indices[n++] = a; indices[n++] = d; indices[n++] = b;
    }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("color", new THREE.BufferAttribute(colours, 3));
  geometry.setIndex(new THREE.BufferAttribute(indices, 1));
  geometry.computeVertexNormals();
  ground.mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
    vertexColors: true, roughness: 0.96, metalness: 0.0 }));
  scene.add(ground.mesh);

  // The water: the same points, lifted to the surface where there is water
  // and tucked under the ground where there is none.
  const wet = new THREE.BufferGeometry();
  wet.setAttribute("position", new THREE.BufferAttribute(new Float32Array(positions), 3));
  wet.setAttribute("color", new THREE.BufferAttribute(new Float32Array(3 * count), 3));
  wet.setIndex(new THREE.BufferAttribute(indices, 1));
  const wetY = wet.attributes.position.array;
  for (let k = 0; k < count; ++k) wetY[3 * k + 1] = ground.heights[k] - 0.3;
  ground.water = new THREE.Mesh(wet, new THREE.MeshStandardMaterial({
    vertexColors: true, transparent: true, opacity: 0.8, roughness: 0.1, metalness: 0.05,
    depthWrite: false }));
  ground.water.renderOrder = 2;
  scene.add(ground.water);

  // Foam carried by the flow.
  const foam = new THREE.BufferGeometry();
  foam.setAttribute("position", new THREE.BufferAttribute(new Float32Array(3 * FOAM_COUNT), 3));
  ground.foam = new THREE.Points(foam, new THREE.PointsMaterial({
    color: 0xeef7f9, size: 0.07, sizeAttenuation: true, transparent: true, opacity: 0.85,
    depthWrite: false }));
  ground.foam.renderOrder = 3;
  ground.foam.frustumCulled = false;
  for (let p = 0; p < FOAM_COUNT; ++p) foam.attributes.position.array[3 * p + 1] = -100;
  scene.add(ground.foam);

  // The flat floor is the rock's safety net far below: not a thing to draw.
  floor.visible = false;
  grid.visible = false;
  scene.fog.near = 32;
  scene.fog.far = 95;
}

// Only the rectangle that changed: a spade, a bank slumping into its trench.
function patchTerrain(changed) {
  if (!ground.mesh) return;
  const [i0, j0, ni, nj] = changed.box;
  const heights = new Float32Array(bytesOf(changed.heights_b64).buffer);
  const surfaces = bytesOf(changed.ground_b64);
  const g = ground.grid;
  const pos = ground.mesh.geometry.attributes.position, col = ground.mesh.geometry.attributes.color;
  for (let j = 0; j < nj; ++j)
    for (let i = 0; i < ni; ++i) {
      const k = (j0 + j) * g.nx + (i0 + i);
      ground.heights[k] = heights[j * ni + i];
      ground.surfaces[k] = surfaces[j * ni + i];
      pos.array[3 * k + 1] = ground.heights[k];
      paintGround(col.array, k);
    }
  pos.needsUpdate = true;
  col.needsUpdate = true;
  ground.mesh.geometry.computeVertexNormals();
}

// A surface for every point: the level where there is water, and where there
// is none but water is next door, the neighbour's level -- so a lake meets its
// shore flat and the ground cuts the waterline, rather than the water sloping
// down into the bank.
function extendShore(surface) {
  const g = ground.grid, out = new Float32Array(surface);
  for (let j = 0; j < g.nz; ++j)
    for (let i = 0; i < g.nx; ++i) {
      const k = j * g.nx + i;
      if (Number.isFinite(surface[k])) continue;
      let best = -Infinity;
      for (let dj = -1; dj <= 1; ++dj)
        for (let di = -1; di <= 1; ++di) {
          const x = i + di, z = j + dj;
          if (x < 0 || z < 0 || x >= g.nx || z >= g.nz) continue;
          const s = surface[z * g.nx + x];
          if (Number.isFinite(s) && s > best) best = s;
        }
      out[k] = best > -Infinity ? best : NaN;
    }
  return out;
}

function drawWater(block) {
  if (!ground.water || !block) return;
  const g = ground.grid;
  const surface = new Float32Array(g.nx * g.nz).fill(NaN);
  const [i0, j0, ni, nj] = block.box;
  if (ni > 0 && block.surface_mm_b64) {
    const mm = new Uint16Array(bytesOf(block.surface_mm_b64).buffer);
    for (let j = 0; j < nj; ++j)
      for (let i = 0; i < ni; ++i) {
        const v = mm[j * ni + i];
        if (v) surface[(j0 + j) * g.nx + (i0 + i)] = block.base_m + v / 1000;
      }
    ground.flow = new Int8Array(bytesOf(block.flow_b64).buffer);
    ground.flowBox = block.box;
  } else {
    ground.flow = null;
  }
  const extended = extendShore(surface);
  // Ease from where the drawing is now to the new report.
  ground.was = ground.next ? currentSurface() : extended;
  ground.next = extended;
  ground.raw = surface;
  ground.arrived = performance.now();
  // Deeper is darker.
  const col = ground.water.geometry.attributes.color.array;
  const c = new THREE.Color();
  for (let k = 0; k < g.nx * g.nz; ++k) {
    const depth = Number.isFinite(extended[k]) ? extended[k] - ground.heights[k] : 0;
    c.copy(WATER_SHALLOW).lerp(WATER_DEEP, clamp(depth / 0.9, 0, 1));
    col[3 * k] = c.r; col[3 * k + 1] = c.g; col[3 * k + 2] = c.b;
  }
  ground.water.geometry.attributes.color.needsUpdate = true;
  ground.last = block;
  showWater(block);
}

function currentSurface() {
  const pos = ground.water.geometry.attributes.position.array;
  const out = new Float32Array(ground.grid.nx * ground.grid.nz);
  for (let k = 0; k < out.length; ++k) {
    const y = pos[3 * k + 1];
    out[k] = y > ground.heights[k] - 0.25 ? y : NaN;
  }
  return out;
}

function animateWater(now) {
  if (!ground.water || !ground.next) return;
  const t = clamp((now - ground.arrived) / WATER_EASE_MS, 0, 1);
  const pos = ground.water.geometry.attributes.position.array;
  const was = ground.was, next = ground.next, H = ground.heights;
  for (let k = 0; k < next.length; ++k) {
    const a = was[k], b = next[k];
    let y;
    if (Number.isFinite(a) && Number.isFinite(b)) y = a + (b - a) * t;
    else if (Number.isFinite(b)) y = b;
    else y = H[k] - 0.3;
    pos[3 * k + 1] = y;
  }
  ground.water.geometry.attributes.position.needsUpdate = true;
  ground.water.geometry.computeBoundingSphere();
}

function stepFoam(dt) {
  if (!ground.foam || !ground.flow || !ground.raw) return;
  const g = ground.grid, [bi, bj, bn, bm] = ground.flowBox;
  const pos = ground.foam.geometry.attributes.position.array;
  const respawn = (p) => {
    for (let tries = 0; tries < 12; ++tries) {
      const i = bi + Math.floor(Math.random() * bn), j = bj + Math.floor(Math.random() * bm);
      const k = (j - bj) * bn + (i - bi);
      const speed = Math.hypot(ground.flow[2 * k], ground.flow[2 * k + 1]) * 0.05;
      if (speed < 0.06 || !Number.isFinite(ground.raw[j * g.nx + i])) continue;
      pos[3 * p] = g.x0 + (i + Math.random() - 0.5) * g.dx;
      pos[3 * p + 2] = g.z0 + (j + Math.random() - 0.5) * g.dx;
      pos[3 * p + 1] = ground.raw[j * g.nx + i] + 0.012;
      return;
    }
    pos[3 * p + 1] = -100;
  };
  for (let p = 0; p < FOAM_COUNT; ++p) {
    const x = pos[3 * p], z = pos[3 * p + 2];
    const at = pos[3 * p + 1] > -50 ? waterAt(x, z) : null;
    if (!at || at.depth < 0.01 || Math.hypot(at.u, at.w) < 0.03 || Math.random() < dt * 0.15) {
      respawn(p);
      continue;
    }
    pos[3 * p] = x + at.u * dt;
    pos[3 * p + 2] = z + at.w * dt;
    pos[3 * p + 1] = at.level + 0.012;
  }
  ground.foam.geometry.attributes.position.needsUpdate = true;
}

function showWater(block) {
  const box = $("water");
  box.hidden = false;
  const cells = ground.grid.nx * ground.grid.nz;
  $("water-line").textContent =
    `${block.volume_m3.toFixed(2)} m³ standing · river in ${block.in_m3_s.toFixed(2)} m³/s,`
    + ` out ${block.out_m3_s.toFixed(2)} m³/s`;
  $("water-cost").textContent =
    `${block.active_cells} of ${cells} columns computed (${block.wet_cells} wet)`
    + ` · unaccounted ${Number(block.residual_m3).toExponential(1)} m³`;
}

function placeCamera(view) {
  if (!view) return;
  const [ex, ey, ez] = view.eye_m, [lx, ly, lz] = view.look_m;
  camera.position.set(ex, ey, ez);
  window.banjoRoom?.lookAt(lx, ly, lz);
}

function resize() {
  const w = innerWidth, h = innerHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
addEventListener("resize", resize);
resize();

// ---------------------------------------------------------------------------
// Drawing what the engine reports
// ---------------------------------------------------------------------------

const MATERIAL_LOOK = {
  "iron":            { color: 0x8d949c, rough: 0.42, metal: 0.92 },
  "aluminum":        { color: 0xc6ccd2, rough: 0.34, metal: 0.88 },
  "glass":           { color: 0x9fd3ff, rough: 0.06, metal: 0.0, clear: 0.55 },
  "alumina ceramic": { color: 0xeee6da, rough: 0.30, metal: 0.0 },
  "oak":             { color: 0xb07a43, rough: 0.78, metal: 0.0 },
  "rubber":          { color: 0x2b2f33, rough: 0.97, metal: 0.0 },
  "ice":             { color: 0xcfeaf5, rough: 0.12, metal: 0.0, clear: 0.45 },
  "concrete":        { color: 0x9a9285, rough: 0.92, metal: 0.0 },
};

// One material per substance, not one per body.
//
// This used to build a fresh MeshStandardMaterial on every call, and buildMesh
// called it twice per body. A pane that comes apart into seventy-four shards
// arrives in a single reply, so that was about a hundred and fifty new
// materials in one frame -- and a material three.js has not seen before is a
// shader program to look up, compile and upload the first time it is drawn.
// That is the lurch when something breaks, and it is not in the engine, the
// wire or the clock: it is the frame that has to draw the pieces.
//
// Glass is glass. Two shards off the same pane want the same material object,
// and then they also batch instead of forcing a state change between them.
const MATERIALS = new Map();
function look(material) {
  const had = MATERIALS.get(material);
  if (had) return had;
  const m = MATERIAL_LOOK[material] || { color: 0x9aa6ae, rough: 0.6, metal: 0.1 };
  const options = { color: m.color, roughness: m.rough, metalness: m.metal };
  if (m.clear) { options.transparent = true; options.opacity = 1 - m.clear * 0.55; }
  const made = new THREE.MeshStandardMaterial(options);
  MATERIALS.set(material, made);
  return made;
}

// Every cell in the room is the same cube, so there is one of it. Building a
// BoxGeometry per shard meant seventy-four identical vertex buffers uploaded to
// the card to draw one broken pane.
let cellGeometry = null;
let cellGeometryFor = 0;
function cellCube() {
  if (!cellGeometry || cellGeometryFor !== world.cellSize) {
    if (cellGeometry) cellGeometry.dispose();
    cellGeometry = new THREE.BoxGeometry(world.cellSize, world.cellSize, world.cellSize);
    cellGeometryFor = world.cellSize;
  }
  return cellGeometry;
}

// A body is drawn as what it is. A box is a box and a sphere is a sphere; a
// hull is a piece that broke or bent off something, and its cells ARE its
// surface, so it is drawn as those cells rather than as a box around them --
// a box around a shard is a lie about its shape and its size.
// Press a dent into the surface of an authored shape.
//
// A dent is real and it is SMALL: an iron ball driven into an anvil takes a
// permanent set of about a tenth of a millimetre on a 120 mm ball. Drawn to
// scale that is nothing at all, and the engine used to "show" it by rebuilding
// the ball out of its cells -- which threw away a smooth sphere for a
// 136-cube staircase that displayed no dent either, because the cells had moved
// ninety micrometres.
//
// So the shape stays the shape and the hollow is pressed into it here, deep
// enough to see. The label says the true depth, which is what keeps it honest:
// the picture is legible, the number is not exaggerated.
// Drawn deeper than it is, but not all the same depth.
//
// This used to floor every hollow at a twentieth of the radius, so a dent of a
// tenth of a millimetre and one of a millimetre were drawn identically -- and a
// picture that makes every dent look the same makes every dent look like it
// ought to matter. It does not: a millimetre on a 140 mm ball does not stop it
// rolling, and the engine is right to keep rolling it.
//
// So the hollow follows the real depth, three times over, between a floor deep
// enough to notice and a cap shallow enough not to claim the ball was staved
// in. A deeper dent now looks deeper, which is the only thing a drawing like
// this can honestly promise.
const DENT_SCALE = 3;           // times the true depth
const DENT_FLOOR = 0.006;       // of the object's own radius
const DENT_CAP = 0.05;          // of the object's own radius
const DENT_WIDTH = 0.45;        // how much of the face it spreads over

function pressDent(geometry, body) {
    const at = body.dent_at_m;
    if (!at) return;
    const here = new THREE.Vector3(at[0], at[1], at[2]);
    if (here.lengthSq() < 1e-12) return;
    const half = Math.max(...body.dimensions_m) / 2;
    const truly = (body.dent_mm || 0) / 1000;
    const deep = Math.min(DENT_CAP * half,
                          Math.max(DENT_FLOOR * half, truly * DENT_SCALE));
    const toward = here.clone().normalize();
    const spread = Math.cos(DENT_WIDTH);

    const at_v = geometry.attributes.position;
    const v = new THREE.Vector3();
    for (let i = 0; i < at_v.count; ++i) {
        v.fromBufferAttribute(at_v, i);
        const out = v.clone().normalize();
        const facing = out.dot(toward);
        if (facing <= spread) continue;
        // Smooth across the hollow rather than a cone, or the rim shows as a
        // crease and reads as damage of a different kind.
        const t = (facing - spread) / (1 - spread);
        const fall = t * t * (3 - 2 * t);
        v.addScaledVector(out, -deep * fall);
        at_v.setXYZ(i, v.x, v.y, v.z);
    }
    at_v.needsUpdate = true;
    geometry.computeVertexNormals();
}

const placing = new THREE.Object3D();

function buildMesh(body) {
  // Cells first. This used to build a box or a sphere and a material before
  // asking, then throw both away for anything drawn from its cells -- which is
  // every piece of everything that ever breaks.
  if (Array.isArray(body.cells_local_m) && body.cells_local_m.length) {
    // Drawn from its cells: one instanced cube per cell, carried by the body's
    // own pose, so it stays one pose on the wire and one draw call on screen.
    const cloud = new THREE.InstancedMesh(cellCube(), look(body.material),
                                          body.cells_local_m.length);
    for (let i = 0; i < body.cells_local_m.length; ++i) {
      const c = body.cells_local_m[i];
      placing.position.set(c[0], c[1], c[2]);
      placing.updateMatrix();
      cloud.setMatrixAt(i, placing.matrix);
    }
    cloud.instanceMatrix.needsUpdate = true;
    return cloud;
  }
  const [w, h, d] = body.dimensions_m;
  const dented = (body.dent_mm || 0) > 0;
  // A dented box needs somewhere to put the hollow, so it is built with enough
  // vertices to have a surface rather than eight corners.
  const geometry = body.shape === "sphere"
    ? new THREE.SphereGeometry(w / 2, dented ? 48 : 24, dented ? 32 : 16)
    : new THREE.BoxGeometry(Math.max(w, 1e-4), Math.max(h, 1e-4), Math.max(d, 1e-4),
                            dented ? 12 : 1, dented ? 12 : 1, dented ? 12 : 1);
  if (dented) pressDent(geometry, body);
  return new THREE.Mesh(geometry, look(body.material));
}

// Take a mesh out of the scene and give back what only it was using.
//
// The material is shared and the cell cube is shared, so neither is this
// mesh's to dispose -- but an authored body's own box or sphere is, and a
// room where things break and are swept up builds and drops these all day.
function forget(mesh) {
  scene.remove(mesh);
  if (mesh.geometry && mesh.geometry !== cellGeometry) mesh.geometry.dispose();
}

function place(mesh, body) {
  mesh.position.set(body.position_m[0], body.position_m[1], body.position_m[2]);
  const q = body.orientation_wxyz;
  mesh.quaternion.set(q[1], q[2], q[3], q[0]);
}

// Rebuild whatever changed.
//
// A step reply is `partial`: it carries only the bodies that are not identical
// to the last ones sent, and names the ones that have gone in `gone`. That is
// worth the care it costs. A room that has shattered holds two hundred and
// fifty bodies and four of them are moving; sending the other two hundred and
// forty-six thirty times a second was six megabytes a second for this to fetch,
// parse and walk, to be told nothing happened -- and that showed up as the room
// stuttering, which reads exactly like the physics being slow. It is not.
//
// A full reply (the scene opening, or one carrying geometry) is not partial,
// and then anything it leaves out really has gone.
function draw(state) {
  if (state.cell_size_m) world.cellSize = state.cell_size_m;
  rememberBlades(state);
  const seen = new Set();
  for (const body of state.bodies) {
    seen.add(body.name);
    let held = world.bodies.get(body.name);
    // Geometry only travels when the set of bodies can have changed, so a
    // body already on screen keeps its mesh and only moves.
    // A body that has just taken a dent needs its mesh made again: the hollow
    // is pressed into the geometry, not painted on.
    const dentChanged = held && (body.dent_mm || 0) !== (held.dentMm || 0);
    if (!held || dentChanged || (body.cells_local_m && !held.fromCells)) {
      if (held) forget(held.mesh);
      const mesh = buildMesh(body);
      scene.add(mesh);
      held = { mesh, fromCells: !!(body.cells_local_m && body.cells_local_m.length),
               dentMm: body.dent_mm || 0 };
      world.bodies.set(body.name, held);
    }
    held.material = body.material || "";
    held.dentMm = body.dent_mm || 0;
    held.dims = body.dimensions_m;
    held.anchored = !!body.anchored;
    held.shape = body.shape;
    place(held.mesh, body);
    showKerfs(held, body);
  }
  const drop = state.partial
    ? (state.gone || [])
    : [...world.bodies.keys()].filter((name) => !seen.has(name));
  for (const name of drop) {
    const entry = world.bodies.get(name);
    if (!entry) continue;
    forget(entry.mesh);
    world.bodies.delete(name);
  }
  dressBlades(world.bodies);
  $("panel-count").textContent = `${world.bodies.size} objects`;
}

// The pins, drawn as pins.
//
// A hinge has no body of its own -- the gate's pose already carries where it
// has swung to, and that is what you actually see. What you cannot see from the
// bodies alone is the pin itself: where a thing is hung, which way its axis
// runs, and, the moment it matters, that it has come OFF. A gate whose jamb was
// smashed away stops being hinged and starts being a plank leaning on the
// floor, and those two look identical for the second before it falls over.
const pinGroup = new THREE.Group();
scene.add(pinGroup);
const PIN_SOLID = new THREE.MeshStandardMaterial({
  color: 0x9fb4c4, roughness: 0.35, metalness: 0.8 });
const PIN_GONE = new THREE.MeshStandardMaterial({
  color: 0xd06a4a, roughness: 0.6, metalness: 0.1,
  transparent: true, opacity: 0.55 });

// A rope is drawn between the two things it ties, every frame, because unlike
// a pin or a groove it MOVES: its whole point is that the two ends are somewhere
// different from moment to moment. Kept as a separate list from the static
// joint stubs so the per-frame work is only the ropes.
const ropeGroup = new THREE.Group();
scene.add(ropeGroup);
const ROPE_MATERIAL = new THREE.LineBasicMaterial({ color: 0xd9c9a8 });
// An elastic is not a rope and must not look like one: a rope goes slack and
// does nothing, and this pushes as well as pulls. Drawn darker and warmer,
// because what it is is a bent limb.
const LIMB_MATERIAL = new THREE.LineBasicMaterial({ color: 0xc4703a });
const ROPE_PARTED = new THREE.LineBasicMaterial({ color: 0xd06a4a });

function drawRopes() {
  while (ropeGroup.children.length) {
    const child = ropeGroup.children.pop();
    child.geometry.dispose();
  }
  for (const joint of world.joints) {
    if (!joint.attached) continue;    // parted: there is no rope to draw
    const a = world.bodies.get(joint.a);
    const b = world.bodies.get(joint.b);
    if (!a || !b) continue;
    if (joint.kind === "link") {
      ropeGroup.add(new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([a.mesh.position.clone(),
                                                  b.mesh.position.clone()]),
        ROPE_MATERIAL));
    } else if (joint.kind === "elastic") {
      // From where it is anchored on `a` -- which the engine reports, worked
      // out from where `a` now stands -- to `b`'s middle. A bow limb is
      // anchored to a point on the grip that is nowhere near the grip's own
      // centre, and drawing it centre to centre would show a different machine
      // from the one being simulated. The far end is `b`'s centre because that
      // is what the joint report carries; when a spring is made off somewhere
      // other than the middle of `b`, this line is short by that much.
      const at = joint.at || [0, 0, 0];
      ropeGroup.add(new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(at[0], at[1], at[2]), b.mesh.position.clone()]),
        LIMB_MATERIAL));
    } else if (joint.kind === "pulley") {
      // Three runs, not one: up from the first body to its sheave, across
      // between the sheaves, and down to the second. Drawing it as a straight
      // line between the two bodies would show a rope passing through the
      // lintel, which is the one thing a pulley exists to avoid.
      const over = (p) => new THREE.Vector3(p[0], p[1], p[2]);
      ropeGroup.add(new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([
          a.mesh.position.clone(),
          over(joint.over_a || [0, 0, 0]),
          over(joint.over_b || [0, 0, 0]),
          b.mesh.position.clone()]),
        ROPE_MATERIAL));
    }
  }
}

function drawJoints(pins) {
  if (!pins) return;                  // not in this reply: nothing changed
  world.joints = pins;
  while (pinGroup.children.length) {
    const child = pinGroup.children.pop();
    child.geometry.dispose();
  }
  for (const pin of pins) {
    // A rope has no stub to draw: it is a line between two bodies and it is
    // drawn every frame by drawRopes, because both of its ends move. So is a
    // limb, for the same reason and in a different colour.
    if (pin.kind === "link" || pin.kind === "pulley" ||
        pin.kind === "elastic") continue;
    const at = pin.at || [0, 0, 0];
    const axis = pin.axis || [0, 1, 0];
    const along = new THREE.Vector3(axis[0], axis[1], axis[2]).normalize();
    // A pin is a short stub across the joint; a groove is a thin rail running
    // the length of the travel, so you can see how far the thing can go before
    // you start hauling on it. They are drawn differently because they ARE
    // different: one turns, one slides, and a rail that looked like a pin
    // would say the portcullis pivots.
    const sliding = pin.kind === "slider";
    const span = sliding
      ? Math.max(0.2, (pin.upper_m || 0) - (pin.lower_m || 0))
      : 0.34;
    const rod = new THREE.Mesh(
      new THREE.CylinderGeometry(sliding ? 0.018 : 0.028,
                                 sliding ? 0.018 : 0.028, span, 10),
      pin.attached ? PIN_SOLID : PIN_GONE);
    // A groove's rail runs from the bottom of the travel to the top, measured
    // from where the thing was BUILT -- which is what `at` is for a slider.
    const middle = sliding
      ? new THREE.Vector3(at[0], at[1], at[2]).addScaledVector(
          along, ((pin.upper_m || 0) + (pin.lower_m || 0)) / 2)
      : new THREE.Vector3(at[0], at[1], at[2]);
    rod.position.copy(middle);
    // A cylinder is made standing up the y axis; point it along the joint.
    rod.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), along);
    pinGroup.add(rod);
  }
}

// How close you have to be, and how big a thing can be and still be debris.
// A cell is 20 mm, so 64 cells is a fragment you could hold in one hand; a
// plate that broke in half is not something you pocket by walking past it.
const REACH_M = 1.2;
const DEBRIS_CELLS = 64;

// Walking over the pieces picks them up.
//
// A room that shatters fills with debris that will lie there for as long as the
// world is open, and the engine cannot take a step back past a couple of
// thousand bodies -- which is what breaking depends on. So sweeping the floor
// is not only how you get materials, it is how the room stays able to break
// things at all.
// Is there anything underfoot worth asking about?
//
// The engine decides what can be collected -- this only decides whether it is
// worth a round trip. Asking every tick regardless would be thirty requests a
// second to be told "nothing", which is the cost that trimming the step reply
// just removed.
function debrisUnderfoot() {
  const p = camera.position;
  for (const entry of world.bodies.values()) {
    if (entry.shape !== "hull" || entry.anchored) continue;
    if (entry.mesh.position.distanceTo(p) <= REACH_M) return true;
  }
  return false;
}

async function sweep() {
  const p = camera.position;
  const got = await act("collect", { at: [p.x, p.y, p.z], radius_m: REACH_M,
                                     largest_cells: DEBRIS_CELLS });
  const haul = got.collected || [];
  if (haul.length) {
    for (const lot of haul) {
      // Out of the world's hands and into the fade, BEFORE draw runs: the
      // reply no longer carries them, and draw deletes whatever a reply leaves
      // out, so without this they would blink out between two frames.
      for (const name of lot.took || []) {
        const entry = world.bodies.get(name);
        if (!entry) continue;
        world.bodies.delete(name);
        world.fading.push({ mesh: entry.mesh, until: performance.now() + 260 });
      }
      const have = world.stock.get(lot.material) || { kg: 0, pieces: 0 };
      have.kg += lot.kg;
      have.pieces += lot.pieces;
      world.stock.set(lot.material, have);
      world.sweptSince.set(lot.material,
        (world.sweptSince.get(lot.material) || 0) + lot.kg);
    }
    showStock();
  }
  return got;
}

// Say what was picked up -- but not once per step.
//
// Walking across a shattered pane collects a few shards every tick, and a line
// in the chat for each would bury everything else that is said. They are added
// up and announced once the sweeping stops.
let tellTimer = null;
function tellLater() {
  if (tellTimer || !world.sweptSince.size) return;
  tellTimer = setTimeout(() => {
    tellTimer = null;
    const lots = [...world.sweptSince];
    world.sweptSince.clear();
    if (!lots.length) return;
    const said = lots.map(([what, kg]) => `${grams(kg)} of ${what}`).join(", ");
    say("world", `Collected ${said}.`);
  }, 700);
}

// Grams below a kilogram, kilograms above it. Nobody says "0.042 kilograms".
function grams(kg) {
  return kg < 1 ? `${Math.round(kg * 1000)} g` : `${kg.toFixed(2)} kg`;
}

function showStock() {
  const list = $("stock-list");
  const rows = [...world.stock].sort((a, b) => b[1].kg - a[1].kg);
  $("stock").hidden = rows.length === 0;
  list.replaceChildren(...rows.map(([what, have]) => {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.className = "what";
    name.textContent = what;
    const much = document.createElement("span");
    much.className = "much";
    much.textContent = grams(have.kg);
    li.append(name, much);
    if (world.sweptSince.has(what)) li.className = "just-in";
    return li;
  }));
}

// A piece being collected shrinks away over a quarter of a second rather than
// vanishing. A thing that disappears between two frames reads as a glitch; a
// thing that shrinks reads as being picked up.
function fadePieces(now) {
  if (!world.fading.length) return;
  world.fading = world.fading.filter((going) => {
    const left = (going.until - now) / 260;
    if (left <= 0) {
      forget(going.mesh);
      return false;
    }
    going.mesh.scale.setScalar(Math.max(0.01, left));
    return true;
  });
}

// ---------------------------------------------------------------------------
// What the room actually did, written down where somebody else can read it
// ---------------------------------------------------------------------------
//
// Every lag in this thing so far has been invisible from the outside. The
// engine ran at 99% of real time while the world clock stood still; it ran at
// 99% again while the pieces of a broken pane turned up most of a second after
// the impact. Each was found only by measuring the right thing, and each time
// the right thing was something only this page could see.
//
// So the page writes down what it did and posts it to the server, which puts it
// in the log. The two clocks are what matter -- wall against world -- because
// that pair has caught two of these on its own. The frame interval is what the
// eye actually sees. And a break is timed end to end: the contact, and the
// moment the pieces appear.
//
// The cost is one small POST every few seconds, and only when there is
// something to say.

const TRACE_EVERY_MS = 4000;     // how often a summary goes out
const SLOW_FRAME_MS = 60;        // a frame worth naming individually
const KEEP_SLOW = 12;            // at most this many named per report

const trace = {
  frames: [],          // frame intervals since the last report
  slow: [],            // the individual bad ones, with what was happening
  ticks: [],           // round trip of each step
  bytes: [],           // and how big the reply was
  breaks: [],          // { name, pieces, impact_to_pieces_ms }
  awaiting: new Map(), // name -> when the impact was seen
  startedWall: 0,
  startedWorld: 0,
  sentAt: 0,
  marked: false,       // the reader pressed L, meaning "that lagged"
};

function traceFrame(dt) {
  trace.frames.push(dt);
  if (dt >= SLOW_FRAME_MS && trace.slow.length < KEEP_SLOW) {
    trace.slow.push({
      ms: Math.round(dt),
      at_s: +world.clock.toFixed(2),
      objects: world.bodies.size,
      fading: world.fading.length,
      // What the room was in the middle of. A slow frame while a break is
      // landing means something different from a slow frame while walking.
      doing: world.workingOn ? "a break is being worked out"
           : world.held ? "carrying something"
           : "nothing in particular",
    });
  }
}

// The impact, and the pieces. This is the measurement that found the last one:
// the room can be running perfectly and the EVENT still be most of a second
// late, which is what a person actually sees.
function traceImpact(name) {
  if (!trace.awaiting.has(name)) trace.awaiting.set(name, performance.now());
}
function tracePieces(name, outcome, pieces) {
  const began = trace.awaiting.get(name);
  trace.awaiting.delete(name);
  trace.breaks.push({
    name, outcome, pieces,
    impact_to_pieces_ms: began ? Math.round(performance.now() - began) : null,
  });
}

function quantile(sorted, at) {
  if (!sorted.length) return null;
  return +sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * at))].toFixed(1);
}

// Post what happened, and start again. Sent through the same guarded endpoint
// everything else uses, so it needs no new way in.
async function sendTrace(why) {
  const now = performance.now();
  const wall_s = (now - trace.startedWall) / 1000;
  if (wall_s <= 0) return;
  const frames = trace.frames.slice().sort((a, b) => a - b);
  const ticks = trace.ticks.slice().sort((a, b) => a - b);
  const report = {
    why,
    // Whether anybody was looking. A browser throttles a tab it is not showing
    // to about one frame a second, which reads in these numbers as a
    // catastrophic lag and is nothing of the kind -- it cost this project two
    // wrong diagnoses before it was written down.
    watched: !document.hidden,
    wall_s: +wall_s.toFixed(2),
    // The pair that catches a stopped world: how much of the scene's own clock
    // went by against how much real time did.
    world_s: +(world.clock - trace.startedWorld).toFixed(2),
    realtime_pct: Math.round((world.clock - trace.startedWorld) / wall_s * 100),
    frames: frames.length,
    fps: +(frames.length / wall_s).toFixed(1),
    frame_ms: { median: quantile(frames, 0.5), p95: quantile(frames, 0.95),
                worst: frames.length ? +frames[frames.length - 1].toFixed(1) : null },
    // Copied, not handed over. These two were passed by reference and then
    // emptied a few lines below, before the request was serialised -- so every
    // report went out with no slow frames and no breaks in it, which is exactly
    // the half worth reading.
    slow_frames: trace.slow.slice(),
    step_ms: { median: quantile(ticks, 0.5), p95: quantile(ticks, 0.95),
               worst: ticks.length ? +ticks[ticks.length - 1].toFixed(1) : null },
    reply_kb: trace.bytes.length
      ? +(trace.bytes.reduce((a, b) => a + b, 0) / trace.bytes.length / 1024).toFixed(2) : null,
    worst_reply_kb: trace.bytes.length ? +(Math.max(...trace.bytes) / 1024).toFixed(0) : null,
    breaks: trace.breaks.slice(),
    objects: world.bodies.size,
  };
  trace.frames.length = 0; trace.slow.length = 0; trace.ticks.length = 0;
  trace.bytes.length = 0; trace.breaks.length = 0;
  trace.startedWall = now;
  trace.startedWorld = world.clock;
  trace.sentAt = now;
  try { await api("/api/trace", report); } catch (e) { /* a lost report is not worth a bad frame */ }
}

// L for "that lagged". Marks the moment and sends everything immediately, so
// there is a report in the log that lines up with what was just seen.
function markLag() {
  say("world", "Noted — the last few seconds are in the server log.");
  sendTrace("somebody said it lagged");
}

// ---------------------------------------------------------------------------
// Standing in it: W A S D, and the mouse
// ---------------------------------------------------------------------------

const keys = new Set();
let yaw = 0, pitch = 0, looking = false;

addEventListener("keydown", (e) => {
  if (e.target instanceof HTMLInputElement) return;
  keys.add(e.code);
  if (e.code === "KeyF" && world.held) intend("throw");
  if (e.code === "KeyR") unlatch();
  if (e.code === "KeyL") markLag();
  if (["KeyW","KeyA","KeyS","KeyD","KeyQ","KeyE","Space",
       "ArrowUp","ArrowDown","ArrowLeft","ArrowRight"].includes(e.code)) e.preventDefault();
});
addEventListener("keyup", (e) => keys.delete(e.code));
addEventListener("blur", () => keys.clear());

// Right-click releases a latch on whatever is under the crosshair: the bar off
// the gate, the nock off the string. On the mouse as well as on R because a
// latch is a second thing to do to the object you are already pointing at, and
// reaching for a key to do it is one hand too many.
canvas.addEventListener("contextmenu", (e) => {
  e.preventDefault();
  // With a blade in hand it turns the edge instead, a quarter about the
  // blade's own length: left, down, right, up.
  if (world.held && world.held.blade) {
    world.held.stance = (world.held.stance + 1) % STANCES.length;
    say("you", `Turned the edge to face ${STANCES[world.held.stance].name}.`);
    return;
  }
  unlatch();
});

let drag = null;
canvas.addEventListener("pointerdown", (e) => {
  // The LEFT button only. The right one releases a latch, and it used to do
  // that and then pick the thing up as well, because a pointerup is a
  // pointerup whichever button made it.
  if (e.button !== 0) return;
  if (looking) return;           // captured: the move handler has it
  drag = { x: e.clientX, y: e.clientY, moved: false };
  canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener("pointermove", (e) => {
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
  drag.x = e.clientX; drag.y = e.clientY;
  turn(dx, dy);
});
canvas.addEventListener("pointerup", (e) => {
  if (e.button !== 0) return;
  const was = drag;
  drag = null;
  try { canvas.releasePointerCapture(e.pointerId); } catch { /* already gone */ }
  if (was && was.moved) return;          // that was a look, not a click
  if (!looking) {
    // Ask for the mouse. If the browser says no, dragging still works and the
    // click below still does what a click does.
    const asked = canvas.requestPointerLock?.();
    if (asked && typeof asked.catch === "function") asked.catch(() => {});
  }
  intend(world.held ? "drop" : "pick");
});

document.addEventListener("pointerlockchange", () => {
  looking = document.pointerLockElement === canvas;
  $("hud-hint").style.opacity = looking ? "0.5" : "1";
});

function turn(dx, dy) {
  yaw -= dx * 0.0022;
  // Stop just short of straight up and straight down: at exactly vertical the
  // forward direction has no horizontal part and walking stops meaning
  // anything.
  pitch = clamp(pitch - dy * 0.0022, -Math.PI / 2 + 0.05, Math.PI / 2 - 0.05);
}

addEventListener("mousemove", (e) => {
  if (looking) turn(e.movementX, e.movementY);
});

// Arrow keys look, for anyone who would rather not drag and for a keyboard on
// its own.
function lookFromKeys(dt) {
  const rate = 90 * dt;
  if (keys.has("ArrowLeft")) turn(-rate, 0);
  if (keys.has("ArrowRight")) turn(rate, 0);
  if (keys.has("ArrowUp")) turn(0, -rate);
  if (keys.has("ArrowDown")) turn(0, rate);
}

function walk(dt) {
  const speed = (keys.has("ShiftLeft") || keys.has("ShiftRight") ? 5.6 : 2.4) * dt;
  const forward = new THREE.Vector3(-Math.sin(yaw), 0, -Math.cos(yaw));
  const right = new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw));
  const move = new THREE.Vector3();
  if (keys.has("KeyW")) move.add(forward);
  if (keys.has("KeyS")) move.sub(forward);
  if (keys.has("KeyD")) move.add(right);
  if (keys.has("KeyA")) move.sub(right);
  if (move.lengthSq() > 0) move.normalize().multiplyScalar(speed);
  if (keys.has("KeyE") || keys.has("Space")) move.y += speed;
  if (keys.has("KeyQ")) move.y -= speed;
  camera.position.add(move);
  // Not below the floor, and not so high the room is a map. On uneven ground
  // the floor is the ground under you.
  const under = ground.heights ? groundAt(camera.position.x, camera.position.z) : 0;
  camera.position.y = clamp(camera.position.y, under + 0.25, under + 12);
  camera.position.x = clamp(camera.position.x, -28, 28);
  camera.position.z = clamp(camera.position.z, -28, 28);
  camera.quaternion.setFromEuler(new THREE.Euler(pitch, yaw, 0, "YXZ"));
}

function forwardVector() {
  const v = new THREE.Vector3(0, 0, -1);
  v.applyQuaternion(camera.quaternion);
  return v;
}

// ---------------------------------------------------------------------------
// The hand
// ---------------------------------------------------------------------------

// What the crosshair is on, asked of the engine. One question in flight at a
// time: the answer is worth about a millisecond and the view moves faster than
// that, so the newest question wins and the rest are dropped.
let aimBusy = false;
async function aim() {
  if (!world.session || aimBusy || world.held) return;
  aimBusy = true;
  try {
    const from = camera.position;
    const dir = forwardVector();
    const found = await act("pick", { from: [from.x, from.y, from.z],
                                      dir: [dir.x, dir.y, dir.z], max_m: 40 });
    world.aim = found.hit && found.name ? found : null;
    // Where the crosshair meets the ground, when it is the ground it meets:
    // that is where a spade goes in.
    world.groundAim = found.hit && !found.name ? found.point_m : null;
    showLabel(world.aim);
  } catch { /* the next frame asks again */ } finally { aimBusy = false; }
}

function showLabel(found) {
  const box = $("label");
  const cross = $("crosshair");
  if (!found && world.groundAim && ground.grid) {
    // The ground itself: what it is made of there, and the water on it --
    // from the engine's own numbers, already here, so no question is asked.
    const [x, , z] = world.groundAim;
    const g = ground.grid;
    const i = Math.round((x - g.x0) / g.dx), j = Math.round((z - g.z0) / g.dx);
    const made = ["rock", "soil", "sand"][ground.surfaces[j * g.nx + i]] || "ground";
    const water = waterAt(x, z);
    box.hidden = false;
    $("label-name").textContent = "the ground";
    $("label-material").textContent = made;
    $("label-size").textContent = water && water.depth > 0.005
      ? `under ${(water.depth * 100).toFixed(0)} cm of water flowing ${Math.hypot(water.u, water.w).toFixed(2)} m/s`
      : `${groundAt(x, z).toFixed(2)} m up`;
    cross.classList.toggle("on", false);
    return;
  }
  if (!found) {
    box.hidden = true;
    cross.classList.toggle("on", false);
    return;
  }
  const entry = world.bodies.get(found.name);
  box.hidden = false;
  $("label-name").textContent = found.name;
  $("label-material").textContent = entry?.material || "";
  const d = entry?.dims;
  $("label-size").textContent = d
    ? `${Math.round(d[0]*1000)} × ${Math.round(d[1]*1000)} × ${Math.round(d[2]*1000)} mm`
      + (entry.anchored ? " · fixed in place" : "")
      // The true depth, beside a hollow drawn deeper than that so it can be
      // seen at all. Saying so is what makes the drawing honest rather than a
      // claim about the shape.
      // The true depth, beside a hollow drawn deeper than that so it can be
      // seen at all. Saying so is what makes the drawing honest rather than a
      // claim about the shape -- and a dent this shallow does not stop the
      // thing rolling, which is why it is worth being plain about the size.
      + (entry.dentMm > 0
          ? ` · dented ${entry.dentMm < 1 ? entry.dentMm.toFixed(2) : entry.dentMm.toFixed(1)} mm`
            + ` (drawn deeper so you can see it)` : "")
      + ` · ${found.distance_m.toFixed(2)} m away`
      + (bladeFor(found.name) ? " · has an edge: click to take it by the grip" : "")
    : "";
  cross.classList.toggle("on", !entry?.anchored);
}

// A click always lands.
//
// These used to give up when a step was already in flight, which is most of the
// time: the world ticks thirty times a second and a person clicks whenever they
// like. The click did nothing and said nothing, which reads exactly like the
// object refusing to be picked up. So an intent is remembered and carried out
// at the top of the next tick instead.
let wants = null;
function intend(what) {
  if (world.busy) { wants = what; return; }
  if (what === "pick") pickUp();
  else if (what === "drop") dropIt();
  else if (what === "throw") throwIt();
}

// ---------------------------------------------------------------------------
// Latches, and letting one go
// ---------------------------------------------------------------------------
//
// A fixing holds two things as one piece until somebody releases it. The gate's
// locking bar is one; so is the nock that holds an arrow to a bowstring. There
// is no bow here and no archery: what there is is a thing you can take hold of,
// and a latch that may be on it.
//
// Releasing one is `unhinge`, which is a public call -- the same one the C API,
// the bindings and the MCP server all offer. Nothing in this file is a
// capability; it is a pair of hands deciding WHEN.

function latchOn(name) {
  return world.joints.find((j) => j.kind === "fixing" && j.attached &&
                                  (j.a === name || j.b === name));
}

function ropedTo(name) {
  return world.joints.some((j) => j.kind === "link" && j.attached &&
                                  (j.a === name || j.b === name));
}

// Let go of a latch by hand: whatever is held, or whatever is under the
// crosshair. This is how the bar comes off the gate.
async function unlatch() {
  const name = world.held ? world.held.name : world.aim && world.aim.name;
  if (!name) return;
  const latch = latchOn(name);
  if (!latch) {
    say("world", `nothing is latched to ${name}.`);
    return;
  }
  try {
    await act("unhinge", { joint: latch.id });
    say("you", `Released the fixing between ${latch.a} and ${latch.b}.`);
    remember(`released the fixing holding ${latch.b} to ${latch.a}`);
  } catch (error) { say("bad", String(error.message || error)); }
}

// What the limbs are holding, in joules, asked for rather than pushed: joints
// only come with a step when the SET of them changes, because sending every
// angle sixty times a second is the traffic that was trimmed out of the reply
// in the first place. Four times a second is enough to watch a draw.
async function refreshJoints() {
  const got = await act("joints", {});
  if (got && got.joints) drawJoints(got.joints);
  return got && got.joints;
}

function storedInElastics() {
  return world.joints.reduce(
    (sum, j) => sum + (j.kind === "elastic" && j.attached ? (j.stored_j || 0) : 0), 0);
}

async function pickUp() {
  if (!world.aim) return;
  const name = world.aim.name;
  const entry = world.bodies.get(name);
  if (entry?.anchored) {
    say("world", `${name} is fixed in place — it is the room, not a prop.`);
    return;
  }
  try {
    // A thing with an edge is taken by its grip and held the way a blade is:
    // the hand drives the grip with bounded force and turns it with bounded
    // torque, and whatever it meets can slow it, turn it or stop it.
    const blade = bladeFor(name);
    if (blade && entry) {
      await act("wield", { name });
      const reach = clamp(world.aim.distance_m, 0.45, 1.1);
      world.held = Object.assign({ name, blade, distance: reach },
                                 takeHold(camera, entry, blade, reach));
      $("crosshair").classList.add("holding");
      $("label").hidden = true;
      remember(`took up the ${name} by its grip`);
      say("you", `Took up ${name} by the grip, its edge facing ${STANCES[0].name}. Turn to`
        + ` swing it; right-click turns the edge.`);
      return;
    }
    await act("grab", { name });
    world.held = { name, distance: clamp(world.aim.distance_m, 0.6, 4.0) };
    // Where the hand is, relative to where the view says it is.
    //
    // The crosshair ray stops at a SURFACE and the hand pulls on a CENTRE OF
    // MASS, so taking hold of anything put the hand a hand's width away from
    // the thing it was holding -- and the hand pulls with everything it has at
    // anything past 50 mm of error. On a gate that is a shove nobody asked for.
    // On a bowstring it was 800 N of yank on 179 g: the arrow was flung
    // backwards into the portcullis jamb at 16.5 m/s by the act of picking the
    // string up. Remembering the offset means the hand starts exactly where
    // the thing already is, and moves from there.
    if (entry) {
      const from = camera.position.clone()
        .add(forwardVector().multiplyScalar(world.held.distance));
      world.held.offset = entry.mesh.position.clone().sub(from);
    }
    // Taking hold of something that hangs on ropes AND carries a latch is
    // taking hold of a drawn thing. Where it is NOW is where it comes back to,
    // which is all the geometry the release needs to know -- no brace height,
    // no bow, no names.
    if (entry && latchOn(name) && ropedTo(name)) {
      world.drawn = { name, from: entry.mesh.position.clone(),
                      latch: latchOn(name).id, asked: 0 };
    }
    $("crosshair").classList.add("holding");
    $("label").hidden = true;
    $("carry").hidden = false;
    remember(`picked up the ${entry?.material || ""} ${name}`.replace(/\s+/g, " "));
    say("you", `Picked up ${name}.`);
  } catch (error) { say("bad", String(error.message || error)); }
}

async function dropIt() {
  if (!world.held) return;
  const name = world.held.name;
  const entry = world.bodies.get(name);
  const at = entry ? entry.mesh.position.clone() : null;
  // Letting go of a drawn string. The latch comes off when the string gets
  // back to where it was taken hold of, because that is where the string stops
  // and the arrow does not -- which is where an arrow leaves a real one.
  if (world.drawn && world.drawn.name === name) {
    const stored = storedInElastics();
    world.loosing = { name, home: world.drawn.from, latch: world.drawn.latch,
                      best: 0, stored };
    world.drawn = null;
    if (stored > 0.05) {
      say("you", `Loosed. The limbs were holding ${stored.toFixed(1)} J.`);
      remember(`loosed ${name} with ${stored.toFixed(1)} J in the limbs`);
    }
  }
  world.drawn = null;
  world.held = null;
  $("crosshair").classList.remove("holding");
  $("carry").hidden = true;
  clearGuides();
  try {
    await act("release");
    remember(at ? `let go of ${name} at ${at.x.toFixed(2)}, ${at.y.toFixed(2)}, ${at.z.toFixed(2)} m`
                : `let go of ${name}`);
    say("you", at ? `Let go of ${name} at ${at.y.toFixed(2)} m up.` : `Let go of ${name}.`);
  } catch (error) { say("bad", String(error.message || error)); }
}

// Throwing is letting go with the hand still moving. The engine takes a pose,
// not a velocity, so the throw is three fast moves along the view and then a
// release -- the object keeps the speed those moves gave it.
async function throwIt() {
  if (!world.held) return;
  const held = world.held;
  const dir = forwardVector();
  try {
    for (let i = 1; i <= 3; i++) {
      const d = held.distance + i * 0.55;
      const p = camera.position.clone().add(dir.clone().multiplyScalar(d));
      await act("move", { to: [p.x, p.y, p.z] });
      await act("step", { dt: 1 / 240, n: 1 });
    }
    remember(`threw ${held.name}`);
    say("you", `Threw ${held.name}.`);
  } catch { /* the release below still has to happen */ }
  await dropIt();
}

// ---------------------------------------------------------------------------
// Seeing where it will land
// ---------------------------------------------------------------------------
//
// Carrying something and not knowing what is under it is the whole difficulty
// of placing anything by hand. Three lines to the axes say where it IS; a line
// straight down, and a ring where that line lands, say where it WILL BE.

// ---------------------------------------------------------------------------
// Heat, fire and gas
// ---------------------------------------------------------------------------
//
// Everything here is drawn from the "heat" block the engine puts on its step
// replies -- what is hot, what is burning, what the gas is doing -- and nothing
// on this page decides a temperature, a flame or a pressure. The glow, the
// flames and the gas column are pictures OF those numbers. They are never the
// source of any heat or force: a flame drawn here warms nothing, and the
// panel says so.

const heatGroup = new THREE.Group();
scene.add(heatGroup);
const heat = {
  last: null,             // the last heat block, as the engine sent it
  glowing: new Map(),     // body name -> the material of its own it glows with
  flames: new Map(),      // body name -> { group, outer, inner, height, rx, rz }
  columns: new Map(),     // gas region name -> the column drawn for it
  burning: new Set(),     // what was burning at the last reply, to say when it changes
};

const FLAME_CONE = new THREE.ConeGeometry(1, 1, 16, 1, true);
FLAME_CONE.translate(0, 0.5, 0);           // its base at the origin, its tip up
const FLAME_OUTER = new THREE.MeshBasicMaterial({
  color: 0xff7a24, transparent: true, opacity: 0.45, depthWrite: false,
  blending: THREE.AdditiveBlending, side: THREE.DoubleSide });
const FLAME_INNER = new THREE.MeshBasicMaterial({
  color: 0xffd27a, transparent: true, opacity: 0.55, depthWrite: false,
  blending: THREE.AdditiveBlending, side: THREE.DoubleSide });
const COLUMN_BOX = new THREE.BoxGeometry(1, 1, 1);
COLUMN_BOX.translate(0, 0.5, 0);            // from its base up the axis
const GAS_COOL = new THREE.Color(0x6aa8ff), GAS_HOT = new THREE.Color(0xff5a1f);

// The colour a surface at this temperature is drawn with.
//
// Below the Draper point, about 798 K, a surface gives off almost no light you
// could see, so warming is shown as a faint heat TINT -- a picture of a number,
// and the panel says it is one. From there up the colour follows incandescence
// roughly: dull red, cherry, orange, towards yellow-white.
function glowOf(tK, ambientK) {
  if (!(tK > ambientK + 25)) return null;
  if (tK < 798) {
    const s = clamp((tK - ambientK - 25) / (798 - ambientK - 25), 0, 1);
    return { color: new THREE.Color(0xff5a1f), intensity: 0.05 + 0.25 * s };
  }
  const s = clamp((tK - 798) / 900, 0, 1);
  return { color: new THREE.Color().setHSL(0.015 + 0.12 * s, 1, 0.42 + 0.3 * s),
           intensity: 0.7 + 2.3 * s };
}

function glow(name, tK) {
  const entry = world.bodies.get(name);
  const own = heat.glowing.get(name);
  const g = entry ? glowOf(tK, heat.last ? heat.last.ambient_k : 293.15) : null;
  if (!g) {
    if (own) {
      if (entry && entry.mesh.material === own) entry.mesh.material = look(entry.material);
      own.dispose();
      heat.glowing.delete(name);
    }
    return;
  }
  // A glowing thing needs a material of its own. The shared ones are shared by
  // every body of that substance, and one burning log must not light them all.
  let mine = own;
  if (!mine || entry.mesh.material !== mine) {
    if (mine) mine.dispose();
    mine = look(entry.material).clone();
    entry.mesh.material = mine;
    heat.glowing.set(name, mine);
  }
  mine.emissive.copy(g.color);
  mine.emissiveIntensity = g.intensity;
}

// A flame over whatever is releasing heat, sized by Heskestad's flame height,
// L = 0.235 Q^(2/5) - 1.02 D, with Q in kW and D the burning area's equivalent
// diameter: a correlation for real fires, used here only to DRAW one. The
// engine has no flame and no hot gas above a fire; the heat it releases goes
// where its heat paths say.
function flameFor(name, powerW) {
  const entry = world.bodies.get(name);
  if (!entry || !(powerW > 300)) { dropFlame(name); return; }
  const d = entry.dims || [0.2, 0.2, 0.2];
  const across = Math.sqrt(4 * d[0] * d[2] / Math.PI);
  const height = clamp(0.235 * Math.pow(powerW / 1000, 0.4) - 1.02 * across, 0.15, 2.5);
  let flame = heat.flames.get(name);
  if (!flame) {
    const group = new THREE.Group();
    const outer = new THREE.Mesh(FLAME_CONE, FLAME_OUTER);
    const inner = new THREE.Mesh(FLAME_CONE, FLAME_INNER);
    group.add(outer, inner);
    heatGroup.add(group);
    flame = { group, outer, inner, seed: Math.random() * 100 };
    heat.flames.set(name, flame);
  }
  flame.height = height;
  flame.rx = 0.45 * d[0];
  flame.rz = 0.45 * d[2];
}

function dropFlame(name) {
  const flame = heat.flames.get(name);
  if (!flame) return;
  heatGroup.remove(flame.group);
  heat.flames.delete(name);
}

// The gas, as a column from where it starts to the piston it pushes on: blue
// when cool, orange then red as it heats. Its height is the engine's volume
// over its area, so the column rising is the gas's own state rising, and the
// piston rides on it because that is where the force is.
function gasColumn(region) {
  let column = heat.columns.get(region.name);
  if (!column) {
    column = new THREE.Mesh(COLUMN_BOX, new THREE.MeshStandardMaterial({
      color: GAS_COOL, transparent: true, opacity: 0.32, depthWrite: false,
      roughness: 0.3, metalness: 0 }));
    heatGroup.add(column);
    heat.columns.set(region.name, column);
  }
  const side = Math.sqrt(Math.max(region.area_m2 || 0, 1e-6));
  column.position.set(region.base_m[0], region.base_m[1], region.base_m[2]);
  const axis = new THREE.Vector3(region.axis[0], region.axis[1], region.axis[2]);
  if (axis.lengthSq() > 0) column.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0),
                                                                axis.normalize());
  column.scale.set(side, Math.max(region.height_m || 0, 1e-3), side);
  const s = clamp((region.t_k - 293) / 300, 0, 1);
  column.material.color.copy(GAS_COOL).lerp(GAS_HOT, s);
  column.material.emissive.copy(GAS_HOT).multiplyScalar(0.4 * s);
}

// Said once when something catches and once when it goes out, with a gap
// between the two thresholds so a fire hovering at the edge does not chatter.
function narrateHeat(block) {
  const now = new Set();
  for (const b of block.bodies) {
    const was = heat.burning.has(b.name);
    if (b.reacting && b.power_w > (was ? 500 : 1500)) now.add(b.name);
  }
  for (const b of block.bodies) {
    if (!now.has(b.name) || heat.burning.has(b.name)) continue;
    say("world", `${b.name} has caught: its surface is at ${Math.round(b.t_k)} K and it is`
      + ` releasing ${(b.power_w / 1000).toFixed(1)} kW.`
      + (b.remaining_s ? ` At that rate its fuel would last about`
                         + ` ${Math.round(b.remaining_s / 60)} min.` : ""));
    remember(`${b.name} caught fire`);
  }
  for (const name of heat.burning) {
    if (now.has(name)) continue;
    say("world", `${name} is no longer burning.`);
    remember(`${name} stopped burning`);
  }
  heat.burning = now;
}

function showHeat(block) {
  const rows = [];
  const row = (what, much) => {
    const li = document.createElement("li");
    const a = document.createElement("span");
    a.className = "what";
    a.textContent = what;
    const b = document.createElement("span");
    b.className = "much";
    b.textContent = much;
    li.append(a, b);
    rows.push(li);
  };
  for (const b of block.bodies.slice(0, 8)) {
    let text = `${Math.round(b.t_k)} K`;
    if (b.reacting && b.power_w > 0) text += ` · ${(b.power_w / 1000).toFixed(1)} kW`;
    if (b.reacting && b.power_w < 0) text += " · drying";
    if (b.reacting && b.power_w > 0 && b.remaining_s)
      text += ` · ~${Math.round(b.remaining_s / 60)} min at this rate`;
    if (b.heater_w > 0) text += ` · heated ${(b.heater_w / 1000).toFixed(1)} kW`;
    row(b.name, text);
  }
  for (const r of block.regions) {
    let text = `${Math.round(r.t_k)} K · ${(r.p_pa / 1000).toFixed(1)} kPa`;
    if (r.piston) text += ` · ${r.piston} ${r.stroke_m >= 0 ? "up" : "down"}`
                       + ` ${Math.abs(Math.round(r.stroke_m * 1000))} mm`;
    if (r.heater_w > 0) text += ` · heated ${(r.heater_w / 1000).toFixed(1)} kW`;
    row(r.name, text);
  }
  $("heat-list").replaceChildren(...rows);
  $("heat-note").textContent =
    `unaccounted energy ${Number(block.ledger.residual_j).toExponential(1)} J`
    + " · glow below 800 K is a tint, and flames are drawn from the heat released:"
    + " pictures of these numbers, not sources of heat";
  $("heat").hidden = rows.length === 0;
}

function drawHeat(block) {
  if (!block) return;
  heat.last = block;
  const listed = new Set();
  for (const b of block.bodies) {
    listed.add(b.name);
    glow(b.name, b.t_k);
    flameFor(b.name, b.reacting ? b.power_w : 0);
  }
  // What has cooled back to the room is no longer listed: its glow and its
  // flame go with it.
  for (const name of [...heat.glowing.keys()]) if (!listed.has(name)) glow(name, 0);
  for (const name of [...heat.flames.keys()]) if (!listed.has(name)) dropFlame(name);
  const regions = new Set();
  for (const r of block.regions) {
    regions.add(r.name);
    if (r.piston) gasColumn(r);
  }
  for (const [name, column] of heat.columns) {
    if (regions.has(name)) continue;
    heatGroup.remove(column);
    column.material.dispose();
    heat.columns.delete(name);
  }
  narrateHeat(block);
  showHeat(block);
}

// Every frame: each flame sits on its body and flickers. The body's pose is
// the engine's; the flicker is only drawing.
function animateHeat(now) {
  const t = now / 1000;
  for (const [name, flame] of heat.flames) {
    const entry = world.bodies.get(name);
    if (!entry) { dropFlame(name); continue; }
    const p = entry.mesh.position;
    flame.group.position.set(p.x, p.y + 0.35 * (entry.dims ? entry.dims[1] : 0.1), p.z);
    const flicker = 0.86 + 0.1 * Math.sin(t * 13 + flame.seed)
                  + 0.06 * Math.sin(t * 29 + 2 * flame.seed);
    flame.outer.scale.set(flame.rx, flame.height * flicker, flame.rz);
    flame.inner.scale.set(0.55 * flame.rx, 0.6 * flame.height * flicker, 0.55 * flame.rz);
  }
}

function clearHeat() {
  heat.glowing.forEach((material) => material.dispose());
  heat.glowing.clear();
  heat.flames.forEach((flame) => heatGroup.remove(flame.group));
  heat.flames.clear();
  heat.columns.forEach((column) => { heatGroup.remove(column); column.material.dispose(); });
  heat.columns.clear();
  heat.burning = new Set();
  heat.last = null;
  $("heat").hidden = true;
}

const guides = new THREE.Group();
scene.add(guides);
const guideLine = (color) => {
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(6), 3));
  return new THREE.Line(g, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.7 }));
};
const lineX = guideLine(0xff7a6b), lineY = guideLine(0x7ee08a), lineZ = guideLine(0x6ba8ff);
const dropLine = guideLine(0xf0b429);
dropLine.material.opacity = 0.95;
const landing = new THREE.Mesh(
  new THREE.RingGeometry(0.055, 0.075, 28),
  new THREE.MeshBasicMaterial({ color: 0xf0b429, side: THREE.DoubleSide,
                                transparent: true, opacity: 0.9 }));
landing.rotation.x = -Math.PI / 2;
guides.add(lineX, lineY, lineZ, dropLine, landing);
guides.visible = false;

function setLine(line, a, b) {
  const p = line.geometry.attributes.position;
  p.setXYZ(0, a.x, a.y, a.z);
  p.setXYZ(1, b.x, b.y, b.z);
  p.needsUpdate = true;
  line.geometry.computeBoundingSphere();
}

function clearGuides() { guides.visible = false; }

// Where the held thing would come down, asked of the engine: a ray straight
// down from it. Whatever that ray meets is what it will hit, which is exactly
// the question someone holding it is asking.
let dropBusy = false, dropOnto = { name: "the floor", y: 0 };
// How far under the held object's centre its own underside is. The ray has to
// start below that, or the first thing it meets is the object it was fired
// from -- which reads as "this lands on itself, zero metres down" and is the
// one answer that cannot possibly help.
function underside(entry) {
  const d = entry?.dims;
  if (!d) return 0.05;
  return (entry.shape === "sphere" ? d[0] / 2 : d[1] / 2) + 0.005;
}

async function askWhatIsBelow(at, clear) {
  if (dropBusy || !world.session) return;
  dropBusy = true;
  try {
    const from = at.y - clear;
    const found = await act("pick", { from: [at.x, from, at.z],
                                      dir: [0, -1, 0], max_m: 60 });
    dropOnto = found.hit
      ? { name: found.name || "the floor", y: from - found.distance_m }
      : { name: "nothing below", y: 0, empty: true };
  } catch { /* keep the last answer */ } finally { dropBusy = false; }
}

function updateGuides() {
  if (!world.held) return;
  const entry = world.bodies.get(world.held.name);
  if (!entry) return;
  const at = entry.mesh.position;
  guides.visible = true;

  // Where it is, as three runs to the axes.
  setLine(lineX, new THREE.Vector3(0, 0, at.z), new THREE.Vector3(at.x, 0, at.z));
  setLine(lineZ, new THREE.Vector3(at.x, 0, 0), new THREE.Vector3(at.x, 0, at.z));
  setLine(lineY, new THREE.Vector3(at.x, 0, at.z), at);

  // Where it lands: from its underside, not its middle.
  const bottom = at.y - underside(entry) + 0.005;
  setLine(dropLine, new THREE.Vector3(at.x, bottom, at.z),
                    new THREE.Vector3(at.x, dropOnto.y, at.z));
  landing.position.set(at.x, dropOnto.y + 0.004, at.z);
  landing.visible = !dropOnto.empty;

  $("carry-x").textContent = at.x.toFixed(2);
  $("carry-y").textContent = at.y.toFixed(2);
  $("carry-z").textContent = at.z.toFixed(2);
  $("carry-onto").textContent = dropOnto.name;
  $("carry-fall").textContent = Math.max(0, bottom - dropOnto.y).toFixed(2);
}

// ---------------------------------------------------------------------------
// Time
// ---------------------------------------------------------------------------

// A 240th, not a 120th, and it is a stiffness question rather than a taste
// one. A bow limb here is a 45 g tip on a 6 kN/m spring, which rings at 58 Hz;
// stepped at 120 that is above half the sample rate and the solver does not
// damp it, it AMPLIFIES it. Watched in the room: a limb tip left the bow at
// 92 m/s and hit the portcullis eight hundred millimetres away, out of an
// assembly that was holding fifteen joules. At a 240th the same bow throws its
// arrow at 3.7 m/s and the tips stay on.
//
// The cost is one more step per frame of a 36-body room, which is 0.03 ms of
// physics against a 14.9 ms round trip. It was never the steps.
const LIVE_DT = 1 / 240;
const MAX_STEPS = 240;

async function tick() {
  if (!world.session || world.busy || world.paused) return;
  world.busy = true;
  // Which world this tick is driving. The chat can rebuild the room while a
  // tick is in flight -- a rebuild opens a NEW world and closes the old one --
  // and the tick then fails, correctly, on a world that no longer exists. What
  // it must not do is take the new one down with it: it used to set
  // world.session to null on any failure, which landed a moment after the chat
  // had handed over the new world and left "the room stopped" on screen over a
  // castle gate that had just been built.
  // Switching rooms does the same thing: a step for the old room comes
  // back "that live world is no longer open", which is true of the OLD
  // room only, and must not stop the new one.
  const driving = world.session;
  try {
    // Whatever was clicked for while the last step was in flight.
    if (wants) { const what = wants; wants = null; 
      if (what === "pick") await pickUp();
      else if (what === "drop") await dropIt();
      else if (what === "throw") await throwIt();
    }
    // Where the hand is, sent WITH the step rather than before it.
    //
    // A round trip to the server is 14.9 ms and four steps of physics are
    // 0.5 ms, so moving the hand in its own call pays the transport twice to do
    // one frame's work -- which halved the frame rate for as long as you were
    // carrying anything, which is the whole of pushing a gate open.
    let hand = null, hand_q = null;
    const now = performance.now();
    const elapsed = world.lastTick ? (now - world.lastTick) / 1000 : LIVE_DT;
    world.lastTick = now;
    if (world.held && world.held.blade) {
      // A blade in hand: where the grip should be and which way the blade
      // should face, from the view and the stance.
      ({ hand, hand_q } = handTarget(camera, world.held.blade, world.held, elapsed));
    } else if (world.held) {
      const dir = forwardVector();
      const p = camera.position.clone().add(dir.multiplyScalar(world.held.distance));
      if (world.held.offset) p.add(world.held.offset);
      hand = [p.x, p.y, p.z];
    }
    const steps = clamp(Math.round(elapsed / LIVE_DT), 1, MAX_STEPS);
    const asked = performance.now();
    const ask = { dt: LIVE_DT, n: steps, moved: true };
    if (hand) ask.hand = hand;
    if (hand_q) ask.hand_q = hand_q;
    let state = await act("step", ask);
    trace.ticks.push(+(performance.now() - asked).toFixed(1));
    // Roughly, and without stringifying it twice: bodies are what a reply is
    // made of, and they are all about the same size.
    trace.bytes.push(200 + (state.bodies ? state.bodies.length * 190 : 0));
    world.workingOn = state.working_on || "";

    // Anything loose underfoot comes with you. Done after the step so it acts
    // on where things have just landed, and before draw so the pieces it takes
    // are moved into the fade rather than deleted outright.
    if (!world.held && debrisUnderfoot()) {
      const swept = await sweep();
      if (swept.collected && swept.collected.length) tellLater();
    }

    // Something is about to break. The engine has taken the step back and is
    // waiting to be told what to do, and until it is told, time does not move.
    //
    // Working it out costs a third of a second to a second and that cannot be
    // made smaller -- every way of shortening the run changes the answer. So it
    // is started and NOT waited for: `wait: false` puts the run on a worker,
    // pins the pair where they are, and comes straight back. The room carries
    // on, you carry on, and a later step brings the answer.
    // Time every impact the engine reports, not just the one being asked
    // about. A cascade queues most of them, and those are the ones that were
    // coming back with no time at all against them -- which is the half of the
    // log worth having, because a queued break waits for the one in front.
    for (const coming of state.breakable || []) traceImpact(coming);
    if (state.breakable && state.breakable.length && !state.working_on) {
      const name = state.breakable[0];
      const hit = (state.impacts || []).filter((i) => i.struck === name)
        .sort((a, b) => b.closing_speed_m_s - a.closing_speed_m_s)[0];
      if (hit) world.why.set(name, hit);
      // Offered because of what it is carrying rather than a blow -- a plank
      // notched beside its load, say. Said as that, not as a hit.
      const sagging = hit ? null : (state.overloaded || []).find((o) => o.name === name);
      if (sagging) {
        say("world", `${name} is carrying more than it can hold up: `
          + `${Math.round(sagging.stress_mpa)} MPa where it can take ${Math.round(sagging.holds_mpa)}.`);
      }
      $("panel-state").textContent = sagging
        ? `${name} is overloaded — working out whether it gives…`
        : `${name} was hit hard enough to break — working it out…`;
      await act("fracture", { name, wait: false });
    }
    // The answer to one started earlier.
    if (state.finished) {
      const name = state.finished;
      tracePieces(name, state.outcome, state.pieces);
      const hit = world.why.get(name);
      world.why.delete(name);
      const bars = hit
        ? ` (it bends above ${Number.isFinite(hit.dent_speed_m_s)
              ? hit.dent_speed_m_s.toFixed(1) + " m/s" : "no speed — it is brittle"}`
          + `, breaks above ${hit.threshold_speed_m_s.toFixed(1)} m/s)`
        : "";
      const how = hit
        ? `${hit.by || "the ground"} hit ${name} at ${hit.closing_speed_m_s.toFixed(1)} m/s`
        : `${name} was struck`;
      if (state.outcome === "broke") {
        say("world", `${how}${bars}. It broke into ${state.pieces} pieces.`);
        remember(`${name} broke into ${state.pieces} pieces`);
      } else if (state.outcome === "dented") {
        say("world", `${how}${bars}. It held together and came out a different shape.`);
        remember(`${name} was dented`);
      } else if (hit) {
        say("world", `${how}${bars} and it held. A threshold is the speed below which`
          + ` nothing CAN happen; above it, it is possible and not certain.`);
      }
    }

    draw(state);
    drawRopes();
    drawHeat(state.heat);
    narrateCuts(state.cuts, say, remember);
    if (state.terrain) drawTerrain(state.terrain);
    if (state.terrain_changed) patchTerrain(state.terrain_changed);
    if (state.water) drawWater(state.water);
    if (state.joints) {
        const wasAttached = new Map(world.joints.map((p) => [p.id, p.attached]));
        for (const pin of state.joints) {
          if (wasAttached.get(pin.id) && !pin.attached) {
            if (pin.kind === "link" || pin.kind === "pulley") {
              const load = pin.tension_n ? ` at ${Math.round(pin.tension_n)} N` : "";
              // A rope that can never part under load, and still came off, was
              // cut -- saying it "parted, rated for 0 N" says the wrong thing.
              if (!(pin.breaks_at_n > 0)) say("world", `the rope from ${pin.a} to ${pin.b} was cut through.`);
              else say("world", `the rope from ${pin.a} to ${pin.b} parted${load} —`
                + ` it was rated for ${Math.round(pin.breaks_at_n || 0)} N.`);
              remember(`the rope to ${pin.b} parted`);
              continue;
            }
            const how = pin.kind === "slider" ? "out of its groove" : "off its hinge";
            say("world", `${pin.b} has come ${how} — there is nothing left`
              + ` of ${pin.a} around the joint to hold it.`);
            remember(`${pin.b} came ${how}`);
          } else if (wasAttached.has(pin.id) && pin.b !== world.joints.find(
                       (p) => p.id === pin.id).b) {
            remember(`the pin moved into ${pin.b}`);
          }
        }
        drawJoints(state.joints);
    }
    // Past 250 bodies the engine stops using the reversible trial, and with it
    // goes the step-back that fracture depends on -- impacts are still
    // reported, but they describe collisions that have already been resolved
    // and nothing can break any more. That is a cliff worth seeing coming
    // rather than discovering by wondering why the room went inert.
    const here = state.count ?? state.bodies.length;
    if (here > 200 && !world.warnedFull) {
      world.warnedFull = true;
      say("world", `${here} pieces in the room. Past about 250 the engine`
        + ` stops being able to break anything — there is a limit on how many bodies it`
        + ` can take back a step for. Start the room again to clear it.`);
    }
    if (here < 150) world.warnedFull = false;
    world.clock = state.t;
    $("hud-clock").textContent = `${state.t.toFixed(1)} s · ${steps} steps`;
    $("panel-state").textContent = world.held
      ? `Holding ${world.held.name}.` : "Live.";
    // After the line above, not before it: a draw has something better to say
    // than "holding", and saying it first only to be overwritten is how it
    // came to say "Holding bowstring." through an entire draw.
    await watchTheDraw();
    if (world.held) {
      const entry = world.bodies.get(world.held.name);
      if (entry) askWhatIsBelow(entry.mesh.position, underside(entry));
    }
    // The coordinates and the drop line come from the engine's answer, so they
    // are updated here rather than in the render loop. A browser stops giving a
    // hidden tab animation frames altogether -- so tying the numbers to drawing
    // meant they froze at whatever they last were, while the world underneath
    // carried on moving. Numbers that have stopped and do not say so are worse
    // than no numbers.
    updateGuides();
  } catch (error) {
    // While another room is being opened the server closes this one, and a
    // step already on its way comes back "no longer open": that is the switch
    // happening, not the room stopping, and open() is about to hand over the
    // new world.
    if (world.session === driving && !world.opening) {
      $("panel-state").textContent = `The room stopped: ${error.message || error}`;
      noteError(`the room stopped: ${error.message || error}`);
      world.session = null;
    }
  } finally { world.busy = false; }
}

// A draw in progress, and a loose in flight.
//
// Both are hands rather than physics. The world does not know that a string is
// being drawn: it knows a body is being hauled against whatever it is attached
// to, and what makes that a draw is that the thing has ropes and a latch.
async function watchTheDraw() {
  // Drawing: ask what the limbs are holding, a few times a second, so the
  // number on screen is the one the engine has rather than one worked out here.
  if (world.drawn) {
    const now = performance.now();
    if (now - world.drawn.asked > 250) {
      world.drawn.asked = now;
      await refreshJoints();
      const entry = world.bodies.get(world.drawn.name);
      const back = entry
        ? entry.mesh.position.distanceTo(world.drawn.from) : 0;
      const stored = storedInElastics();
      if (stored > 0.05)
        $("panel-state").textContent =
          `Drawing ${world.drawn.name} — ${(back * 1000).toFixed(0)} mm back,`
          + ` ${stored.toFixed(1)} J in the limbs.`;
    }
    return;
  }
  if (!world.loosing) return;

  // Loosed: the latch comes off when the string gets back to where it was
  // taken hold of. Measured along the line it was drawn out on, so that a
  // string swinging sideways is not mistaken for one coming home -- and with a
  // stall as the other way out, because a limb tip that lags can stop the
  // string short of its own brace and it is still the moment the arrow leaves.
  const loose = world.loosing;
  const entry = world.bodies.get(loose.name);
  if (!entry) { world.loosing = null; return; }
  const back = entry.mesh.position.distanceTo(loose.home);
  loose.best = Math.max(loose.best, loose.was === undefined ? 0 : loose.was - back);
  const closing = loose.was === undefined ? 0 : loose.was - back;
  loose.was = back;
  const home = back < 0.02;
  const stalled = loose.best > 0.005 && closing < 0.2 * loose.best && back < 0.08;
  if (!home && !stalled) return;
  world.loosing = null;
  try {
    await act("unhinge", { joint: loose.latch });
    const pins = await refreshJoints();
    const off = (pins || []).find((p) => p.id === loose.latch);
    say("world", `the nock let go ${(back * 1000).toFixed(0)} mm from brace.`
      + ` Nothing chose a speed for what was on it: it left with whatever the`
      + ` ${loose.stored.toFixed(1)} J in the limbs could give it, less what the`
      + ` string and the tips kept.`);
    remember(`the latch on ${loose.name} let go`);
    if (off && off.attached) say("bad", "the latch would not come off.");
  } catch (error) { say("bad", String(error.message || error)); }
}

let last = performance.now();
function frame() {
  const now = performance.now();
  const gap = now - last;
  const dt = Math.min(0.1, gap / 1000);
  last = now;
  traceFrame(gap);
  lookFromKeys(dt);
  walk(dt);
  updateGuides();
  fadePieces(now);
  animateHeat(now);
  animateWater(now);
  stepFoam(dt);
  renderer.render(scene, camera);
  world.framesSinceOpen++;
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// ---------------------------------------------------------------------------
// The panel
// ---------------------------------------------------------------------------

function say(who, text, did) {
  if (who === "bad") noteError(text);
  const turn = document.createElement("div");
  turn.className = `turn ${who}`;
  const label = document.createElement("span");
  label.className = "who";
  label.textContent = who === "you" ? "You" : who === "bad" ? "Trouble" : "The room";
  const body = document.createElement("p");
  body.textContent = text;
  turn.append(label, body);
  if (did && did.length) {
    const list = document.createElement("p");
    list.className = "did";
    list.append(document.createTextNode("did: "));
    did.forEach((d, i) => {
      if (i) list.append(document.createTextNode(", "));
      const code = document.createElement("code");
      code.textContent = d;
      list.append(code);
    });
    turn.append(list);
  }
  $("chat").append(turn);
  $("chat").scrollTop = $("chat").scrollHeight;
  return turn;
}

// The room is working on it, and looks like it.
//
// The model takes anywhere from a couple of seconds to half a minute -- it
// reads the room before it answers, and that is a round trip of its own. A
// static line saying "Thinking..." for twenty-six seconds is indistinguishable
// from a page that has stopped, so this moves, and past a few seconds it starts
// saying how long it has been.
function waitingFor(what) {
  const turn = document.createElement("div");
  turn.className = "turn world thinking";
  const label = document.createElement("span");
  label.className = "who";
  label.textContent = "The room";
  const body = document.createElement("p");
  body.append(document.createTextNode(what));
  const dots = document.createElement("span");
  dots.className = "dots";
  dots.append(document.createElement("i"), document.createElement("i"),
              document.createElement("i"));
  const waited = document.createElement("span");
  waited.className = "waited";
  body.append(dots, waited);
  turn.append(label, body);
  $("chat").append(turn);
  $("chat").scrollTop = $("chat").scrollHeight;

  const began = performance.now();
  const tick = setInterval(() => {
    const s = (performance.now() - began) / 1000;
    // Nothing for the first few seconds: a number that appears instantly makes
    // a fast answer look slow.
    waited.textContent = s >= 3 ? `${s.toFixed(0)} s` : "";
  }, 250);
  return { turn, done() { clearInterval(tick); turn.remove(); } };
}

$("ask").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("ask-text");
  const text = input.value.trim();
  if (!text || !world.session) return;
  input.value = "";
  // What was asked, said back straight away, before anything is waited on.
  say("you", text);
  const waiting = waitingFor("Reading the room and thinking it over");
  $("ask-send").disabled = true;
  try {
    const answer = await api("/api/world/ask", {
      session: world.session,
      message: text,
      // What the person has been doing. A model asked to change a room it
      // cannot see has to be told what has happened in it.
      story: world.story.slice(-24),
    });
    waiting.done();
    say("world", answer.reply || "(nothing to say)", answer.did);
    if (answer.reopened) {
      world.session = answer.session;
      world.bodies.forEach((e) => forget(e.mesh));
      world.bodies.clear();
      world.fading.forEach((f) => forget(f.mesh));
      world.fading.length = 0;
      world.stock.clear();
      world.sweptSince.clear();
      showStock();
      draw(answer.state);
      // And its joints. The room that comes back can have hinges, ropes and
      // springs the chat just made -- and the list held here is the OLD room's,
      // naming bodies that may be gone. Without this a gate the chat hung is
      // drawn with no pin, and a sign with no ropes.
      world.joints = [];
      drawJoints(answer.state.joints || []);
      drawRopes();
      clearHeat();
      // The ground and the water of the room as it now is. The camera stays
      // where the person is standing.
      if (answer.state.terrain) {
        drawTerrain(answer.state.terrain);
        if (answer.state.water) drawWater(answer.state.water);
      } else {
        clearGround();
      }
      if (answer.joint_problems && answer.joint_problems.length)
        say("bad", "Some joints would not hang: " + answer.joint_problems.join("; "));
      remember("the room was rebuilt: " + (answer.did || []).join(", "));
    }
  } catch (error) {
    waiting.done();
    say("bad", String(error.message || error));
  } finally { $("ask-send").disabled = false; input.focus(); }
});

$("reset").addEventListener("click", () => open());

// A gas is seen through its window. The crosshair's first body is then the pane
// of glass, but what the person is looking at -- and means to heat -- is the
// column behind it; a cylinder with a window in front can otherwise only have
// its gas heated by walking round to look down its open top. Only glass: through
// concrete there is no gas to be seen.
function gasBehindGlass(name) {
  const entry = world.bodies.get(name);
  if (!entry || entry.material !== "glass" || !heat.last || heat.columns.size === 0) return null;
  const ray = new THREE.Raycaster(camera.position.clone(), forwardVector().normalize());
  const hit = ray.intersectObjects([...heat.columns.values()], false)[0];
  if (!hit) return null;
  for (const [regionName, column] of heat.columns) {
    if (column === hit.object) {
      return (heat.last.regions || []).find((r) => r.name === regionName) || null;
    }
  }
  return null;
}

// Heat what the crosshair is on: 10 kW for a minute, like a bundle of kindling
// held to it -- or, when it is a piston or a window with gas behind it, the gas
// at 800 W for half a minute. External work, and the engine counts it; whether
// it lights anything is the engine's answer, and two presses are twice the heat.
$("heat-it").addEventListener("click", async () => {
  if (!world.session) return;
  const name = world.held ? world.held.name : world.aim && world.aim.name;
  if (!name) {
    say("world", "Point the crosshair at something first: the heat goes into whatever it is on.");
    return;
  }
  const region = heat.last && ((heat.last.regions || []).find((r) => r.piston === name)
                               || (!world.held && gasBehindGlass(name)));
  const target = region ? region.name : name;
  const power = region ? 800 : 10000;
  const seconds = region ? 30 : 60;
  try {
    await act("heat", { target, power_w: power, seconds });
    say("you", `Heating ${target} at ${power / 1000} kW for ${seconds} s.`);
    remember(`heated ${target} at ${power / 1000} kW for ${seconds} s`);
  } catch (error) { say("bad", String(error.message || error)); }
});
$("scene").addEventListener("change", () => {
  // Choosing a room leaves the QA build: the link stops naming it, so a reload
  // opens the room that was chosen rather than the build again.
  if ($("scene").value !== QA_OPTION && qaBuild() !== null) {
    const url = new URL(location.href);
    url.searchParams.delete("qa");
    history.replaceState(history.state, "", url);
    showBuild(null);
  }
  open();
});

// A spade, where the crosshair meets the ground: a pit 0.8 m across and 0.4 m
// deep. The engine takes the ground down, rebuilds the colliders it changed and
// wakes whatever they held -- dig beside a boulder and it falls in -- and loose
// sides slump into the hole over the next second. What is drawn is what it says.
async function digAt(x, z, width = 0.8, depth = 0.4) {
  const answer = await act("dig", { from: [x, z], to: [x, z], width_m: width, depth_m: depth });
  draw(answer);
  if (answer.terrain_changed) patchTerrain(answer.terrain_changed);
  if (answer.water) drawWater(answer.water);
  return answer;
}
$("dig-it").addEventListener("click", async () => {
  if (!world.session) return;
  if (!ground.grid) {
    say("world", "This room's floor is flat concrete: there is nothing to dig. The valley has ground.");
    return;
  }
  const at = world.groundAim;
  if (!at) {
    say("world", "Point the crosshair at the ground first: the spade goes in where it is.");
    return;
  }
  try {
    const answer = await digAt(at[0], at[2]);
    const d = answer.dug || {};
    say("you", `Dug ${((d.sand_m3 || 0) + (d.soil_m3 || 0)).toFixed(2)} m³ at`
      + ` [${at[0].toFixed(1)}, ${at[2].toFixed(1)}]: ${(d.sand_m3 || 0).toFixed(2)} of sand,`
      + ` ${(d.soil_m3 || 0).toFixed(2)} of soil; ${d.chunks_rebuilt} collider(s) rebuilt,`
      + ` ${d.bodies_woken} thing(s) woken.`);
    remember(`dug a pit at [${at[0].toFixed(1)}, ${at[2].toFixed(1)}]`);
  } catch (error) { say("bad", String(error.message || error)); }
});

// ---------------------------------------------------------------------------
// Opening
// ---------------------------------------------------------------------------

// A saved build, by its QA id: /world?qa=20260912-101201/hinged-gate-1 opens the
// room a QA trial left behind (build/agent-regression/<id>.spec.json) instead of
// one of the authored rooms, so a build the chat made can be looked at in the
// real engine by anyone with the link. Whether the id is one is the server's to
// say; the page passes it on, and says which build is open.
const QA_OPTION = "qa-build";
function qaBuild() {
  return new URLSearchParams(location.search).get("qa");
}
// Held: the room opens and is drawn, and its clock waits until it is let go.
// /world?qa=<id>&hold=1 is how the QA's pictures begin at the moment the build
// does -- otherwise a ball dropped from two metres has landed before a camera
// can be pointed at it.
world.paused = new URLSearchParams(location.search).get("hold") === "1";
function qaParts(id) {
  const m = /^(\d{8}-\d{6})\/([a-z0-9-]+)-(\d+)$/.exec(id || "");
  return m ? { run: m[1], name: m[2], trial: m[3] } : null;
}
// Which build is open, in the panel and in the dropdown. Without an entry of its
// own a QA build would sit under whichever room the dropdown last showed, and
// choosing that room would then change nothing.
function showBuild(id) {
  const parts = qaParts(id);
  const label = $("panel-build");
  label.hidden = id === null;
  label.textContent = id === null ? ""
    : parts ? `QA build ${parts.name} #${parts.trial}, run ${parts.run}` : `QA build ${id}`;
  let option = $("scene").querySelector(`option[value="${QA_OPTION}"]`);
  if (id === null) {
    if (option) option.remove();
    return;
  }
  if (!option) {
    option = document.createElement("option");
    option.value = QA_OPTION;
    $("scene").prepend(option);
  }
  option.textContent = parts ? `QA: ${parts.name} #${parts.trial}` : "QA build";
  $("scene").value = QA_OPTION;
}

async function open() {
  world.opening = true;
  $("panel-state").textContent = "Opening the room…";
  const qa = qaBuild();
  showBuild(qa);
  try {
    const data = await api("/api/world/open", qa !== null ? { qa } : { scene: $("scene").value });
    world.session = data.session;
    world.scene = data.scene || null;   // what the server says it opened
    world.openError = null;
    world.lastTick = 0;
    // This room's own clock. Left at the last room's, the first frame report
    // after a reopen measured one room's seconds against the other's.
    world.clock = Number(data.t) || 0;
    trace.startedWorld = world.clock;
    world.story = [];
    world.held = null;
    $("carry").hidden = true;
    world.bodies.forEach((e) => forget(e.mesh));
    world.bodies.clear();
    world.joints = [];
    draw(data);
    drawJoints(data.joints);
    drawRopes();
    clearHeat();
    if (data.terrain) {
      drawTerrain(data.terrain);
      if (data.water) drawWater(data.water);
      // Somewhere to stand that looks at something: the valley says where.
      placeCamera(data.terrain.view);
    } else {
      clearGround();
    }
    world.framesSinceOpen = 0;
    $("panel-state").textContent = "Live.";
    $("chat").replaceChildren();
    say("world",
      `${data.bodies.length} things, made of ${
        [...new Set(data.bodies.map((b) => b.material).filter(Boolean))].join(", ")
      }. Click the room to look around, walk with W A S D, and click again to pick`
      + ` something up. Ask me to change anything.`);
    // Said, not dropped, as when the chat rebuilds the room: a gate that does
    // not swing reads as broken physics rather than as a pin in the wrong place.
    if (data.joint_problems && data.joint_problems.length)
      say("bad", "Some joints would not hang: " + data.joint_problems.join("; "));
    const edged = (data.blades || []).map((b) => b.body);
    if (edged.length) {
      say("world", `${edged.join(", ")} ${edged.length > 1 ? "have edges" : "has an edge"}.`
        + ` Click it to take it by the grip; turn to swing it, and right-click to turn the`
        + ` edge (left, down, right, up). It cuts what its edge meets hard enough, and`
        + ` nothing else.`);
    }
  } catch (error) {
    world.openError = String(error.message || error);
    $("panel-state").textContent = `Could not open the room: ${world.openError}`;
    noteError(`could not open the room: ${world.openError}`);
  } finally {
    world.opening = false;
  }
}

// Up and on screen: opened, its bodies drawn, and two frames rendered since.
function roomReady() {
  return !!world.session && !world.opening && !world.openError
    && world.bodies.size > 0 && world.framesSinceOpen >= 2;
}

// One handle onto the running room, so that what is on screen can be checked
// from outside it rather than by taking a picture and squinting. The other
// stage in this playground exposes the same thing for the same reason.
window.banjoRoom = {
  world, camera, scene,
  lookAt(x, y, z) {
    const to = new THREE.Vector3(x, y, z).sub(camera.position);
    yaw = Math.atan2(-to.x, -to.z);
    pitch = Math.atan2(to.y, Math.hypot(to.x, to.z));
    camera.quaternion.setFromEuler(new THREE.Euler(pitch, yaw, 0, "YXZ"));
  },
  standAt(x, y, z) { camera.position.set(x, y, z); },
  aim, pickUp, dropIt, throwIt, intend,
  // For measuring what a frame costs: building the meshes for a shattered pane
  // is the expensive part of a break, and it cannot be seen from outside.
  buildMesh, renderer, THREE, MATERIALS,
  // What the heat drawing was last given, and what it drew from it.
  heatState: () => heat.last,
  heatDrawn: () => ({ glowing: [...heat.glowing.keys()], flames: [...heat.flames.keys()],
                      columns: [...heat.columns.keys()] }),
  // The ground and the water as drawn, for checking what is on screen against
  // what the engine said -- and a spade, for driving the room from outside.
  groundAt, waterAt, digAt,
  groundDrawn: () => ground.grid && ({ ...ground.grid, water: ground.last,
                                       wetPoints: ground.raw ? ground.raw.filter(Number.isFinite).length : 0 }),
  // Whether the room is up and on screen. Anything checking it from outside --
  // tests/qa_browser.py photographs it -- waits on this rather than on a delay.
  ready: roomReady,
  // Hold the room's clock, and let it go again (see ?hold=1). Letting go
  // restarts the step timing, as opening a room does, so the room does not
  // try to catch up on the time it was held.
  hold() { world.paused = true; return true; },
  resume() { world.paused = false; world.lastTick = 0; return true; },
  // What the page knows, in one call: which world, how many bodies, the world
  // clock, what the panel says, and every error it has seen.
  status: () => ({
    session: world.session,
    paused: !!world.paused,
    scene: world.scene || null,
    ready: roomReady(),
    bodies: world.bodies.size,
    time_s: world.clock,
    frames: world.framesSinceOpen,
    panel: $("panel-state").textContent,
    build: $("panel-build").hidden ? null : $("panel-build").textContent,
    said: [...$("chat").querySelectorAll(".turn")].slice(-6)
      .map((turn) => (turn.querySelector("p") || turn).textContent),
    errors: errorsSeen.slice(),
  }),
};

// Reported on its own timer rather than from the frame loop, because a room
// that has stopped drawing is exactly the case worth hearing about and it
// would never send anything. "0 frames in four seconds" is a report.
setInterval(() => sendTrace("routine"), TRACE_EVERY_MS);
setInterval(tick, 33);
setInterval(aim, 90);
open();
