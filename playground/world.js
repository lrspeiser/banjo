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
import { BINDINGS, isKey, isButton, keyOf, controlsHint, holdPoint, windUpPoint,
         windUpReached, throwStroke, placeStroke, throwable, helpFor, AimArc,
         WIND_UP_S, TURNS, TURN_KEY_RATE, HOLD_RANGE_M, holdDistanceFor, radiusOf,
         turnPace, askTowards, uprightTurn } from "/interaction.js";
import { makePicks } from "/picks.js";
import { makeWorkbench } from "/workbench.js";

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

// A request can fail in two ways, and they want opposite answers.
//
// The engine REFUSING something comes back as a 400 with its reason, and that
// is final: the same request gets the same answer. A request that got no
// answer at all -- the fetch rejects -- or that the server fell over handling
// -- a 5xx -- says nothing about the world, and the same request a moment
// later usually goes through. On 2026-09-12 a room stopped for good five
// minutes in because Windows had no socket buffer left to send one step with
// (ERR_NO_BUFFER_SPACE), while the server and the world were both fine. So the
// second kind is marked `transient`, and tick() tries again before giving up.
function linkFailure(error) {
  const failed = new Error(error.message || String(error));
  failed.transient = true;
  return failed;
}

async function api(path, body, renewed = false) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["X-Banjo-Token"] = token;
  let res, text;
  try {
    res = await fetch(path, body === undefined
      ? { headers }
      : { method: "POST", headers, body: JSON.stringify(body) });
    text = await res.text();
  } catch (error) { throw linkFailure(error); }
  if (res.status === 403 && !renewed) {
    // The server hands the token out with its status rather than minting one on
    // demand, so this is where it comes from: the first time, and again after
    // the server has been restarted, because a new server has a new token and
    // refuses the old one. Only fetching it when there was none meant that
    // after a restart every request was refused, "Start the room again"
    // included, until the page was reloaded.
    let status;
    try { status = await (await fetch("/api/status")).json(); }
    catch (error) { throw linkFailure(error); }
    token = status.csrf_token;
    if (!token) throw new Error("the server would not hand out a session token");
    return api(path, body, true);
  }
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = { error: text.slice(0, 300) }; }
  // Behind a password (docs/deploy.md), a session that has run out -- the
  // server was started again, say -- goes to log in again rather than being
  // shown as a room that has stopped working.
  if (res.status === 401 && data.login) {
    location.assign(data.login);
    throw new Error(data.error || "log in first");
  }
  if (!res.ok) {
    const failed = new Error(data.error || `HTTP ${res.status}`);
    failed.status = res.status;
    failed.transient = res.status >= 500;
    throw failed;
  }
  return data;
}

const world = {
  session: null,
  bodies: new Map(),      // name -> { mesh, material, dims, anchored }
  fading: [],             // pieces on their way out, being collected
  stock: new Map(),       // material -> { kg, pieces }
  sweptSince: new Map(),  // material -> kg, waiting to be announced
  carriedGround: null,    // sand and soil out of this room's ground: the engine's count
  workingOn: "",          // what the engine is working out, for the frame record
  held: null,             // { name, distance }
  aim: null,              // what the crosshair is on, from the engine
  busy: false,
  lastTick: 0,
  // After a request that got no answer (see tick()).
  lost: 0,                // tries in a row that got none, not given up on yet
  lostSince: 0,           // when the first of them went out
  lostWhy: "",            // and what the last of them failed with
  retryAt: 0,             // do not ask again before this (performance.now())
  resync: false,          // the next step asks for every body, not just changes
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
  drawn: null,            // { name, from: Vector3, latch }
  loosing: null,          // { name, home: Vector3, latch, best }
  // For banjoRoom.ready(): whether a room is being opened, why the last attempt
  // failed, and how many frames have been drawn since one opened.
  opening: false,
  openError: null,
  framesSinceOpen: 0,
  // The hand as the one control language sees it (interaction.js): what it is
  // doing -- "none", "ready", "preparing", "throwing", "placing", "blocked",
  // "carrying", "thrown" -- and what the help and the meter say about it.
  use: { mode: "none" },
  // The room's interaction profiles (docs/interaction-profiles.md): how each
  // object in it is used. From the validated room, never worked out here.
  profiles: [],
};

function remember(what) {
  world.story.push(what);
  if (world.story.length > 60) world.story.shift();
}

// The notebook this page has shown (showNotebook): its revision, and the claims
// in it already said.
let notebookRevision = -1;
const notebookSeen = new Set();

async function act(op, extra) {
  // With the notebook revision this page has shown, so the answer carries the
  // notebook whenever the server's is newer -- after a swing the engine
  // measured, an action, or the chat -- and only then.
  const answer = await api("/api/live/act", Object.assign(
    { session: world.session, op, notebook_seen: notebookRevision }, extra || {}));
  if (answer && answer.notebook) showNotebook(answer.notebook, notebookRevision >= 0);
  return answer;
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
  beyond: [],   // sheets of water standing beyond the edges: see drawBeyond
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
  for (const sheet of ground.beyond || []) {
    scene.remove(sheet);
    sheet.geometry.dispose();
    sheet.material.dispose();
  }
  ground.beyond = [];
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
  drawBeyond(block.beyond);

  // The flat floor is the rock's safety net far below: not a thing to draw.
  floor.visible = false;
  grid.visible = false;
  // A river network beyond the edges reaches tens of metres out: the haze
  // stands back far enough to see where the river goes.
  const reachesOut = ground.beyond.length > 0;
  scene.fog.near = reachesOut ? 60 : 32;
  scene.fog.far = reachesOut ? 190 : 95;
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
  placeBeyond(block);
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
  const pools = [...(block.basins || []), ...(block.junctions || [])];
  const reaches = block.reaches || [];
  const networked = pools.length > 0 || reaches.length > 0;
  // With a river network beyond the edges nothing is handed in or let go at
  // the valley's own edges: the river crosses to and from it, said below.
  $("water-line").textContent = networked
    ? `${block.volume_m3.toFixed(2)} m³ standing in the valley`
    : `${block.volume_m3.toFixed(2)} m³ standing · river in ${block.in_m3_s.toFixed(2)} m³/s,`
      + ` out ${block.out_m3_s.toFixed(2)} m³/s`;
  $("water-cost").textContent =
    `${block.active_cells} of ${cells} columns computed (${block.wet_cells} wet)`
    + ` · unaccounted ${Number(block.residual_m3).toExponential(1)} m³`;
  const beyond = $("water-beyond");
  beyond.hidden = !networked;
  if (networked) {
    const flow = (q) => `${Math.abs(q).toFixed(2)} m³/s`;
    const said = pools.map((b) => {
      const parts = [`${b.name}: ${b.level_m.toFixed(3)} m, ${b.volume_m3.toFixed(1)} m³`];
      if (b.fed_m3_s > 0) parts.push(`fed ${flow(b.fed_m3_s)}`);
      if (b.across_m3_s < -1e-4) parts.push(`into the valley ${flow(b.across_m3_s)}`);
      else if (b.across_m3_s > 1e-4) parts.push(`from the valley ${flow(b.across_m3_s)}`);
      if (b.out_m3_s > 0) parts.push(`over its outlet ${flow(b.out_m3_s)}`);
      return parts.join(", ");
    });
    // What each reach carries where it starts, in its middle and where it
    // ends; at an end the valley meets, what crosses the valley's edge.
    for (const r of reaches)
      said.push(`${r.name} ${r.in_m3_s.toFixed(2)} → ${r.middle_m3_s.toFixed(2)} → ${r.out_m3_s.toFixed(2)} m³/s`);
    beyond.textContent = said.join(" · ")
      + ` · all of it unaccounted ${Number(block.all_unaccounted_m3).toExponential(1)} m³`;
  }
}

// The river network beyond the edges (docs/watershed.md), drawn from the
// engine's own numbers: each basin and junction a still sheet of water at its
// level over a floor at its bed -- a square of its surface's area -- and each
// reach a ribbon of water along its course, cell by cell at each cell's level,
// over a strip of bed at each cell's bed; a dry cell shows only its bed. A
// picture of numbers, as the rest of the water is: it holds no bodies, and
// nothing about it is decided here.
const BEYOND_BANK_M = 1.5;   // the bed drawn this much wider than the water, each side
function beyondWater() {
  return new THREE.MeshStandardMaterial({ color: WATER_DEEP.clone(), transparent: true, opacity: 0.8,
    roughness: 0.1, metalness: 0.05, depthWrite: false, side: THREE.DoubleSide });
}
function beyondBed() {
  const c = GROUND_COLOURS[1];
  return new THREE.MeshStandardMaterial({ color: new THREE.Color(c.r, c.g, c.b), roughness: 0.96,
    metalness: 0.0, side: THREE.DoubleSide });
}
// A strip along a course, `half` metres either side of it: a quad a cell, with
// each cell's four corners its own so each cell can stand at its own height.
function stripAlong(points, half, heights) {
  const n = points.length - 1;
  const pos = new Float32Array(12 * n), index = new Uint32Array(6 * n);
  for (let c = 0; c < n; ++c) {
    const [x0, z0] = points[c], [x1, z1] = points[c + 1];
    const len = Math.hypot(x1 - x0, z1 - z0) || 1;
    const sx = -(z1 - z0) / len * half, sz = (x1 - x0) / len * half;
    [[x0 + sx, z0 + sz], [x0 - sx, z0 - sz], [x1 + sx, z1 + sz], [x1 - sx, z1 - sz]].forEach(([x, z], v) => {
      pos[12 * c + 3 * v] = x;
      pos[12 * c + 3 * v + 1] = heights[c];
      pos[12 * c + 3 * v + 2] = z;
    });
    index.set([4 * c, 4 * c + 1, 4 * c + 2, 4 * c + 1, 4 * c + 3, 4 * c + 2], 6 * c);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geometry.setIndex(new THREE.BufferAttribute(index, 1));
  geometry.computeVertexNormals();
  return geometry;
}
function drawBeyond(beyond) {
  ground.beyond = [];
  if (!beyond || Array.isArray(beyond)) return;
  const add = (mesh, data) => { mesh.userData = data; scene.add(mesh); ground.beyond.push(mesh); };
  for (const pool of [...(beyond.basins || []), ...(beyond.junctions || [])]) {
    const sheet = new THREE.Mesh(new THREE.PlaneGeometry(pool.side_m, pool.side_m).rotateX(-Math.PI / 2),
                                 beyondWater());
    sheet.position.set(pool.at_m[0], -100, pool.at_m[1]);
    sheet.visible = false;
    sheet.renderOrder = 2;
    add(sheet, { pool: pool.name, bed: pool.bed_m });
    const side = pool.side_m + 2 * BEYOND_BANK_M;
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(side, side).rotateX(-Math.PI / 2), beyondBed());
    floor.position.set(pool.at_m[0], pool.bed_m, pool.at_m[1]);
    add(floor, { bedOf: pool.name });
  }
  for (const reach of beyond.reaches || []) {
    add(new THREE.Mesh(stripAlong(reach.points_m, reach.width_m / 2 + BEYOND_BANK_M, reach.bed_m), beyondBed()),
        { bedOf: reach.name });
    const water = new THREE.Mesh(stripAlong(reach.points_m, reach.width_m / 2, reach.bed_m.map((b) => b - 0.05)),
                                 beyondWater());
    water.visible = false;
    water.renderOrder = 2;
    add(water, { reach: reach.name, beds: reach.bed_m, cells: reach.cells, shown: [] });
  }
}

// Each sheet at its basin's or junction's level and each reach's cells at
// theirs, from the water block's report of the network.
function placeBeyond(block) {
  const pools = new Map([...(block.basins || []), ...(block.junctions || [])].map((p) => [p.name, p]));
  const reaches = new Map((block.reaches || []).map((r) => [r.name, r]));
  for (const mesh of ground.beyond || []) {
    const u = mesh.userData;
    if (u.pool) {
      const pool = pools.get(u.pool);
      mesh.visible = !!pool && pool.level_m > u.bed + 0.003;
      if (pool) mesh.position.y = pool.level_m;
    } else if (u.reach) {
      const r = reaches.get(u.reach);
      mesh.visible = !!r;
      if (!r) continue;
      const pos = mesh.geometry.attributes.position.array;
      u.shown = [];
      for (let c = 0; c < u.cells; ++c) {
        const wet = r.level_m[c] - u.beds[c] > 0.003;
        for (let v = 0; v < 4; ++v) pos[12 * c + 3 * v + 1] = wet ? r.level_m[c] : u.beds[c] - 0.05;
        u.shown.push(wet ? r.level_m[c] : null);
      }
      mesh.geometry.attributes.position.needsUpdate = true;
      mesh.geometry.computeBoundingSphere();
    }
  }
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
    // A body whose shape changed where it stands -- burned in from every face,
    // or rebuilt from the cells it has left -- is drawn again from what is left
    // of it (docs/thermal-mechanics.md, "One material state"). A box or a
    // sphere carries its new size in dimensions_m; a piece needs its cells, and
    // until they arrive it keeps the ones it has.
    const reshaped = held && (body.revision || 0) !== (held.revision || 0)
      && (!held.fromCells || (body.cells_local_m && body.cells_local_m.length));
    if (!held || dentChanged || reshaped || (body.cells_local_m && !held.fromCells)) {
      if (held) forget(held.mesh);
      const mesh = buildMesh(body);
      scene.add(mesh);
      held = { mesh, fromCells: !!(body.cells_local_m && body.cells_local_m.length),
               dentMm: body.dent_mm || 0 };
      world.bodies.set(body.name, held);
    }
    // The revision it is drawn at. A piece whose shape has changed but whose
    // cells have not come yet keeps the one it was drawn at, so that they are
    // drawn when they do.
    const waiting = held.fromCells && (body.revision || 0) !== (held.revision || 0)
      && !(body.cells_local_m && body.cells_local_m.length);
    if (!waiting) held.revision = body.revision || 0;
    held.material = body.material || "";
    held.dentMm = body.dent_mm || 0;
    held.dims = body.dimensions_m;
    held.anchored = !!body.anchored;
    held.shape = body.shape;
    // What the engine says it weighs: what a hand has to hold up and a throw
    // has to accelerate.
    held.mass = body.mass_kg || 0;
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
    // Held where it is on `a`, because that is what the engine measures it
    // from: `at` is a's pose times the point on a (LiveWorld::joints). This
    // block only arrives when the SET of joints changes, so a pin fixed
    // between two things that then fall would otherwise stay drawn in the air
    // where they were. A pin that came off stays on `a`, where it was.
    const on = world.bodies.get(pin.a);
    if (on) {
      const undo = on.mesh.quaternion.clone().invert();
      rod.userData.follows = pin.a;
      rod.userData.local = rod.position.clone().sub(on.mesh.position).applyQuaternion(undo);
      rod.userData.turn = undo.multiply(rod.quaternion);
    }
    pinGroup.add(rod);
  }
}

// Move each pin with the body it is measured on, after every reply's poses.
// A body that has gone keeps its pin where it was last seen.
function followJoints() {
  for (const rod of pinGroup.children) {
    const { follows, local, turn } = rod.userData;
    const on = follows && world.bodies.get(follows);
    if (!on) continue;
    rod.position.copy(local).applyQuaternion(on.mesh.quaternion).add(on.mesh.position);
    rod.quaternion.copy(on.mesh.quaternion).multiply(turn);
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
  // What is carried is shown in the panel now, with everything else the person
  // has (showInventory); the corner list stays hidden.
  $("stock").hidden = true;
  showInventory();
}

// What the person has, always in the panel beside the conversation: what is in
// their hand, what they carry, and what in this room can be used, with the keys
// that use it. Built from what the page already knows, and redrawn only when
// that changes.
let inventorySaid = "";
function showInventory() {
  const held = world.held && world.held.name;
  const entry = held ? world.bodies.get(held) : null;
  const holding = held ? `${held}${entry && entry.mass ? ` · ${grams(entry.mass)}` : ""}` : "nothing";
  const carrying = [...world.stock].sort((a, b) => b[1].kg - a[1].kg)
    .map(([what, have]) => ({ what, much: grams(have.kg) }));
  const uses = [
    ...(world.tools || []).map((p) => ({ what: p.object,
      keys: "E take up · Left mouse swing it · Right mouse lever it out" })),
    ...(world.profiles || []).map((p) => ({ what: p.object,
      keys: "E take up · hold Left mouse to draw · let go to shoot" })),
  ];
  const said = JSON.stringify([holding, carrying, uses]);
  if (said === inventorySaid) return;
  inventorySaid = said;
  $("inv-holding").textContent = holding;
  const rows = (items, none) => (items.length ? items : [{ none }]).map((item) => {
    const li = document.createElement("li");
    if (item.none) { li.className = "none"; li.textContent = item.none; return li; }
    li.textContent = item.what;
    if (item.much) {
      const much = document.createElement("span");
      much.className = "much";
      much.textContent = item.much;
      li.append(much);
    }
    if (item.keys) {
      const keys = document.createElement("span");
      keys.className = "keys";
      keys.textContent = item.keys;
      li.append(keys);
    }
    return li;
  });
  $("inv-carrying").replaceChildren(...rows(carrying, "nothing yet"));
  $("inv-tools").replaceChildren(...rows(uses, "nothing here yet"));
}
setInterval(showInventory, 250);

// What the ground under a point is made of, from the engine's own map of its
// surface -- as the label says it. Null off the ground, or in a room without.
function groundMadeOf(at) {
  if (!Array.isArray(at) || !ground.grid || !ground.surfaces) return null;
  const g = ground.grid;
  const i = Math.round((at[0] - g.x0) / g.dx), j = Math.round((at[2] - g.z0) / g.dx);
  if (i < 0 || j < 0 || i >= g.nx) return null;
  return ["rock", "soil", "sand"][ground.surfaces[j * g.nx + i]] || null;
}

// What the person can do right now, under what they have in the panel (the
// owner: prompts that show what you can do, "in a box to the side", that
// "recommend what tool you should use with a hot key to use it"). From what the
// page already knows -- what is in the hand and the state it is in, what the
// crosshair is on, what is carried, what in this room can be used -- as one
// line to a key. It says only what the engine has shown: rock stops an oak
// point, so on rock the pick is not offered.
let actionsSaid = "";
function showActions() {
  const k = (action) => keyOf(action);
  const rows = [];
  let tip = "";
  const held = world.held, use = world.use || {};
  const on = !held && world.aim && world.aim.name ? world.aim.name : null;
  const underfoot = !held && !on ? groundMadeOf(world.groundAim) : null;
  const tool = (world.tools || [])[0] || null;
  if (held && held.pick) {
    if (use.mode === "pick-in") rows.push([k("secondary"), `lever ${held.pick.object} out`]);
    else if (use.mode === "pick-ready")
      rows.push([k("primary"), `swing ${held.pick.object} at the ground under the crosshair`]);
    rows.push([k("interact"), `put ${held.pick.object} down`]);
    if (use.mode === "pick-ready" && groundMadeOf(world.groundAim) === "rock")
      tip = "Rock stops an oak point: aim at the soil to dig.";
  } else if (held && held.bow) {
    rows.push([k("primary"), "hold to draw, let go to shoot"]);
    rows.push([k("interact"), "let go of the bow"]);
  } else if (held) {
    if (held.throwable) rows.push([k("primary"), "hold to wind up, let go to throw"]);
    rows.push([k("interact"), `put ${held.name} down`]);
    rows.push([k("talk"), `ask the room to turn or move ${held.name}`]);
  } else if (on) {
    const entry = world.bodies.get(on);
    const pick = picks.profileOf(on), bow = profileOf(on);
    if (pick) rows.push([k("interact"), `take up ${pick.object} by its grip`]);
    else if (bow) rows.push([k("interact"), `take up ${bow.object}`]);
    else if (bladeFor(on)) rows.push(["double-click", `take ${on} by the grip`]);
    else if (entry && throwable(entry, onAJoint(on))) rows.push([k("interact"), `take hold of ${on}`]);
    rows.push([k("heat"), `heat ${on}`]);
    // Its own actions first: what the room's chat worked out a person does
    // with this thing when it made it, one per number key (offer_actions).
    rows.unshift(...allActionsFor(on).map((action, i) => [String(i + 1), action.label]));
  } else if (underfoot) {
    if (underfoot !== "rock") rows.push([k("dig"), `dig here, in the ${underfoot}`]);
    const carried = world.carriedGround
      ? (Number(world.carriedGround.soil_kg) || 0) + (Number(world.carriedGround.sand_kg) || 0) : 0;
    if (carried > 0.0005) rows.push([k("heap"), "heap what you carry here"]);
    if (underfoot === "rock") {
      if (tool) tip = `Bare rock: it stops the oak point of ${tool.object}.`;
    } else {
      tip = tool
        ? `The tool for this ground: ${tool.object}. Look at it and press ${k("interact")} to take it`
          + ` up, then ${k("primary")} to swing it.`
        : `No tool here to dig with: press ${k("talk")} and ask the room to make you a pick.`;
    }
  }
  rows.push([k("workbench"), workbench.state().open
    ? "the workbench: play, pause and scrub its run in the panel"
    : "watch a recorded run on a workbench in front of you"]);
  rows.push([k("talk"), "ask the room to build or change anything"]);
  const said = JSON.stringify([rows, tip]);
  if (said === actionsSaid) return;
  actionsSaid = said;
  $("actions-list").replaceChildren(...rows.map(([key, words]) => {
    const li = document.createElement("li");
    const kbd = document.createElement("kbd");
    kbd.textContent = key;
    li.append(kbd, document.createTextNode(words));
    return li;
  }));
  $("actions-tip").textContent = tip;
  $("actions-tip").hidden = !tip;
}
setInterval(showActions, 250);

// ---------------------------------------------------------------------------
// The workbench
// ---------------------------------------------------------------------------
//
// The lab's recorded runs, played back as a small copy on a bench in front of
// the person while the room goes on (the owner: recorded runs play "on a bench
// in front of you"; workbench.js sets it out and draws it). K opens the list
// here in the panel and lets the mouse go, so a run can be chosen with it. The
// bench stays where it was set down until it is put away.
const workbench = makeWorkbench({ scene, camera, groundAt, api });
let runsListed = false, scrubbing = false, workbenchSaid = "";

function openWorkbench(open = $("workbench-body").hidden) {
  $("workbench-body").hidden = !open;
  $("workbench-toggle").setAttribute("aria-expanded", String(open));
  if (!open) return;
  if (document.pointerLockElement) document.exitPointerLock?.();
  if (!runsListed) listRuns();
}

async function listRuns() {
  runsListed = true;
  const list = $("workbench-runs");
  const line = (words) => {
    const li = document.createElement("li");
    li.className = "none";
    li.textContent = words;
    return li;
  };
  list.replaceChildren(line("Looking for recorded runs…"));
  try {
    const { runs = [] } = await api("/api/runs");
    if (!runs.length) {
      list.replaceChildren(line("No recorded runs yet: the lab page records one each time it runs an experiment."));
      return;
    }
    list.replaceChildren(...runs.map((run) => {
      // "12 objects, 2496 cells at 20 mm: glass panel (glass), ..." -- what it
      // is on one line, and what is in it on the next, cut to fit.
      const [head, ...rest] = String(run.title).split(": ");
      const li = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "quiet";
      button.title = run.message ? `${run.title}\n\n${run.message}` : run.title;
      const name = document.createElement("span");
      name.className = "name";
      name.textContent = head;
      button.append(name);
      if (rest.length) {
        const what = document.createElement("span");
        what.className = "what";
        what.textContent = rest.join(": ");
        button.append(what);
      }
      const when = document.createElement("span");
      when.className = "when";
      when.textContent = new Date(run.saved_unix_s * 1000).toLocaleString(undefined,
        { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
        + ` · ${(run.recording_bytes / 1e6).toFixed(1)} MB to load`;
      button.append(when);
      button.addEventListener("click", () => setOut(run));
      li.append(button);
      return li;
    }));
  } catch (error) {
    runsListed = false;
    list.replaceChildren(line(`The runs could not be listed: ${error.message || error}`));
  }
}

async function setOut(run) {
  try { await workbench.open(run.id, run.case, run.title); }
  catch (error) { say("bad", `That run could not be set out on the bench: ${error.message || error}`); }
}

$("workbench-toggle").addEventListener("click", () => openWorkbench());
$("workbench-play").addEventListener("click", () => {
  if (workbench.state().playing) workbench.pause(); else workbench.play();
});
// Dragging the slider holds the run wherever it is dragged to.
const benchSlider = $("workbench-frame");
benchSlider.addEventListener("pointerdown", () => { scrubbing = true; workbench.pause(); });
addEventListener("pointerup", () => { scrubbing = false; });
benchSlider.addEventListener("input", () => { workbench.pause(); workbench.seek(benchSlider.value / 1000); });
$("workbench-speed").addEventListener("change", (e) => workbench.setSpeed(e.target.value));
$("workbench-away").addEventListener("click", () => workbench.close());

// The controls, said from the bench's own state and never ahead of it.
function showWorkbench() {
  const s = workbench.state();
  const said = JSON.stringify(s);
  if (said === workbenchSaid) return;
  workbenchSaid = said;
  $("workbench-controls").hidden = !s.open && !s.loading;
  if (s.loading) {
    $("workbench-title").textContent = `Setting out ${s.title}…`;
    $("workbench-time").textContent = "";
    return;
  }
  if (!s.open) return;
  $("workbench-title").textContent = s.title;
  $("workbench-title").title = s.title;
  $("workbench-play").textContent = s.playing ? "Pause" : s.t >= s.duration ? "Play again" : "Play";
  if (!scrubbing) benchSlider.value = String(s.duration > 0 ? Math.round(1000 * s.t / s.duration) : 0);
  const pace = s.speed === 1 ? "as fast as it happened" : `slowed to ${s.speed}×`;
  $("workbench-time").textContent = `${s.t.toFixed(3)} s of ${s.duration.toFixed(3)} s, ${pace}`
    + ` · drawn at ${Math.round(100 * s.scale)}% of its size`
    + (s.fractures ? ` · ${s.fractures} fractures so far` : "");
}
setInterval(showWorkbench, 100);

// The sand and soil dug out of this room's ground and not put back, as the
// engine counts them. Set from its numbers every time and never added to here:
// the ground and what is carried out of it are one account, kept by the engine
// through every edit -- so the room opened again from the same edits, after the
// chat changes it or on a reload, carries the same.
function carryGround(carried) {
  world.carriedGround = carried || null;
  for (const what of ["sand", "soil"]) {
    const kg = carried ? Number(carried[`${what}_kg`]) || 0 : 0;
    if (kg > 0.0005) world.stock.set(what, { kg, pieces: 0 });
    else world.stock.delete(what);
  }
  showStock();
}

function carriedSaid() {
  const c = world.carriedGround || {};
  const parts = ["sand", "soil"].filter((what) => Number(c[`${what}_kg`]) > 0.0005)
    .map((what) => `${grams(Number(c[`${what}_kg`]))} of ${what}`);
  return parts.length ? parts.join(" and ") : "no sand or soil";
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
const SHORTEST_REPORT_S = 2;     // a routine one over less says nothing about the clocks
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
  // Requests that got no answer. The world stands still while the server
  // cannot be reached, and in every other number here that reads as a lag.
  link: { times: 0, longest_ms: 0, why: "", gave_up: false },
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
  // A room still opening has no clock to measure yet. Its report starts when it
  // is drawn (traceNewWorld); one sent before then measured the page load, or
  // the replaced room's last seconds, against a clock that was not running --
  // "room: 0% of realtime", said out loud as a lag, whenever an open outlasted
  // the four seconds between reports: measured with a first open held to 5.5 s.
  // The replaced room's own report has already gone (traceOldWorld, first thing
  // in open()).
  if (why === "routine" && world.opening) return;
  // Too short a window to measure the clocks by: the world trails the wall by
  // up to a step, which over a fraction of a second is most of the number,
  // and a world not stepped yet reads 0% -- the figure that means the clock
  // stopped. A window that began part way through the interval (a new world
  // begins one) goes out with the next report instead, unless there is
  // something in it worth more than the clocks.
  if (why === "routine" && wall_s < SHORTEST_REPORT_S
      && !trace.breaks.length && !trace.slow.length) return;
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
    ...(trace.link.times ? { lost_link: { ...trace.link } } : {}),
  };
  const link = trace.link;
  trace.frames.length = 0; trace.slow.length = 0; trace.ticks.length = 0;
  trace.bytes.length = 0; trace.breaks.length = 0;
  trace.link = { times: 0, longest_ms: 0, why: "", gave_up: false };
  trace.startedWall = now;
  trace.startedWorld = world.clock;
  trace.sentAt = now;
  try { await api("/api/trace", report); } catch (e) {
    // A lost report is not worth a bad frame -- but a lost connection is the
    // one thing a report sent while the server is away is sure to lose, so it
    // is kept for the next report, which reaches whichever server comes back
    // and says why the room stopped.
    if (link.times) {
      trace.link.times += link.times;
      trace.link.longest_ms = Math.max(trace.link.longest_ms, link.longest_ms);
      trace.link.gave_up = trace.link.gave_up || link.gave_up;
      trace.link.why = trace.link.why || link.why;
    }
  }
}

// A world being replaced, and the one replacing it: "Start the room again",
// another scene, or the chat rebuilding the room.
//
// A report is about one world. The new world's clock is its own -- a room
// just opened starts from zero -- so a report that ran across the change took
// the old world's clock from the new one's. The log said "room: -358% of
// realtime", and when the difference came out positive it was no truer.
//
// So what the old world did since the last report goes out first, as its own:
// the seconds before somebody starts the room again are the likeliest to have
// the lag in them. Only if it was stepped at all -- a room that had already
// stopped has been saying so every four seconds.
function traceOldWorld() {
  if (trace.ticks.length) sendTrace("routine");
}

// And the new world's report starts with the new world: its clock from where
// that world is, the wall from now, and nothing carried over. An impact in the
// old world will never have pieces in this one.
function traceNewWorld(t) {
  world.clock = Number.isFinite(t) ? t : 0;
  world.lastTick = 0;   // its first step is one step, not a catch-up across the change
  trace.frames.length = 0; trace.slow.length = 0; trace.ticks.length = 0;
  trace.bytes.length = 0; trace.breaks.length = 0;
  trace.awaiting.clear();
  trace.startedWall = performance.now();
  trace.startedWorld = world.clock;
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

// Typing in a field is typing: no key pressed there is a control -- the chat's
// box, or anything else that takes text.
function typing(target) {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement
    || !!(target && target.isContentEditable);
}

addEventListener("keydown", (e) => {
  if (typing(e.target)) return;
  // "/" opens the room's chat, as it does in a game: say what you want -- "turn
  // this upright and set it in front of me" -- and the room does it.
  if (e.key === "/" || isKey("talk", e.code)) { e.preventDefault(); talk(); return; }
  if (isKey("more", e.code)) e.preventDefault();   // not the browser's focus hop
  if (e.repeat) return;
  keys.add(e.code);
  // The one control language (interaction.js): interact takes hold and puts
  // down; more says what else the thing in the hand can do, by number.
  if (isKey("interact", e.code)) intend(world.held ? "put down" : "pick");
  if (isKey("more", e.code) && world.held) { world.use.more = !world.use.more; showUse(); }
  if (world.use.more && /^Digit[123]$/.test(e.code)) moreAction(Number(e.code.slice(5)));
  // Turning what is held: the keys are read every frame while they are down
  // (turnFromKeys); U stands it on end. On something the wrist cannot turn,
  // the first press says why.
  if (isKey("upright", e.code)) standUpright();
  if (TURNS.some((t) => isKey(t.action, e.code))) turnKeyPressed();
  if (e.code === "KeyR") unlatch();
  if (e.code === "KeyL") markLag();
  // The panel's buttons from the keyboard (interaction.js BINDINGS), so what the
  // actions box offers, it offers with the key that does it.
  if (isKey("dig", e.code)) $("dig-it").click();
  if (isKey("heap", e.code)) $("heap-it").click();
  if (isKey("heat", e.code)) $("heat-it").click();
  if (isKey("workbench", e.code)) openWorkbench();
  if (e.key === "Escape") world.menuFor = null;
  // One of the actions of what the crosshair is on, by its number -- with
  // nothing in hand, where the number keys are not the hand's "more" menu.
  if (!world.held && /^Digit[1-9]$/.test(e.code) && world.aim && world.aim.name
      && allActionsFor(world.aim.name).length) runAction(world.aim.name, Number(e.code.slice(5)) - 1);
  if (["KeyW","KeyA","KeyS","KeyD","KeyQ","KeyE","Space",
       "ArrowUp","ArrowDown","ArrowLeft","ArrowRight"].includes(e.code)) e.preventDefault();
});
addEventListener("keyup", (e) => keys.delete(e.code));
addEventListener("blur", () => keys.clear());
// The controls, said from the same table the keys are read from.
$("hud-hint").innerHTML = controlsHint();

// "/": the chat's box, ready to type in. The mouse is let go so the person can
// see what they type and click Send, and a key held down to walk stops walking.
// What they hold or look at, where they stand and which way they face go with
// what they say (whereIAm), so "this" and "in front of me" mean something.
function talk() {
  keys.clear();
  if (document.pointerLockElement) document.exitPointerLock?.();
  $("ask-text").focus();
}
// And Esc in the box goes back to the room without sending anything.
$("ask-text").addEventListener("keydown", (e) => { if (e.key === "Escape") e.target.blur(); });

// The mouse wheel: how far out the hand holds what it holds -- pushed away, or
// brought in. Only where the hand wants it: a heavy thing takes as long to get
// there as the hand's strength says, and what is in the way stops it.
canvas.addEventListener("wheel", (e) => {
  const held = world.held;
  if (!held || held.bow || held.blade || held.pick) return;
  e.preventDefault();
  held.distance = clamp(held.distance * Math.exp(-e.deltaY * 0.0015),
                        HOLD_RANGE_M.least, HOLD_RANGE_M.most);
}, { passive: false });

// Right-click releases a latch on whatever is under the crosshair: the bar off
// the gate, the nock off the string. On the mouse as well as on R because a
// latch is a second thing to do to the object you are already pointing at, and
// reaching for a key to do it is one hand too many.
canvas.addEventListener("contextmenu", (e) => {
  e.preventDefault();
  // Secondary, in the middle of a wind-up: lower it instead of throwing.
  if (world.use.mode === "preparing") { cancelWindUp(); return; }
  // ...and in the middle of a draw, let the string back down.
  if (world.use.mode === "drawing") { intend("let down"); return; }
  // With a tool that digs in hand, it levers a point that is in the ground.
  if (world.held && world.held.pick) {
    if (world.use.mode === "pick-in") intend("lever");
    return;
  }
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
// Whether the press of primary that is down began a wind-up or a draw. Its
// release then throws or looses -- or, when secondary cancelled it first, does
// nothing at all. It is never also a click: a release after letting a string
// down used to pick the bow straight up again, and after lowering a wind-up it
// dropped the ball.
let primaryUsed = false;
// One click on a thing shows what can be done with it, beside it; a second
// click on it straight after takes hold of it (the owner: "click once to see
// the actions you can take", "maybe double click to take it").
let lastClick = null;
const DOUBLE_CLICK_MS = 400;
canvas.addEventListener("pointerdown", (e) => {
  // The LEFT button only. The right one releases a latch, and it used to do
  // that and then pick the thing up as well, because a pointerup is a
  // pointerup whichever button made it.
  if (e.button !== 0) return;
  // Primary held with something throwable in the hand winds it up. Looking
  // still works while it does -- that is how a throw is aimed.
  if (isButton("primary", e.button) && world.held && world.held.throwable &&
      (world.use.mode === "ready" || world.use.mode === "blocked")) {
    startWindUp();
    primaryUsed = true;
  } else if (isButton("primary", e.button) && world.held && world.held.bow &&
             world.use.mode === "bow-ready") {
    // The same button on a bow draws it.
    intend("draw");
    primaryUsed = true;
  } else if (isButton("primary", e.button) && world.held && world.held.pick &&
             world.use.mode === "pick-ready") {
    // And on a tool that digs, swings it at the ground under the crosshair.
    intend("swing");
    primaryUsed = true;
  }
  if (looking) return;           // captured: the move handler has it
  drag = { x: e.clientX, y: e.clientY, moved: false };
  // Capture can be refused -- a pointer already gone, or one a test made up --
  // and dragging to look works without it.
  try { canvas.setPointerCapture(e.pointerId); } catch { /* look without it */ }
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
  // Letting go of primary after a wind-up throws, however much the view was
  // turned while it was held.
  if (primaryUsed) {
    primaryUsed = false;
    if (drag) try { canvas.releasePointerCapture(e.pointerId); } catch { /* gone */ }
    drag = null;
    if (world.use.mode === "preparing") intend("let fly");
    else if (world.use.mode === "drawing") intend("loose");
    return;
  }
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
  if (world.held) { intend("drop"); return; }
  // With the hand empty a click no longer takes hold: it opens what can be
  // done with the thing, and a second click on it straight after takes hold.
  // A click on nothing closes what was open.
  const on = world.aim && world.aim.name;
  const now = performance.now();
  if (on && lastClick && lastClick.name === on && now - lastClick.at < DOUBLE_CLICK_MS) {
    lastClick = null;
    world.menuFor = null;
    intend("pick");
  } else {
    lastClick = on ? { name: on, at: now } : null;
    world.menuFor = on || null;
  }
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
  // Up and down from the bindings. E used to be up as well; it is interact now.
  if (BINDINGS.up.keys.some((k) => keys.has(k))) move.y += speed;
  if (BINDINGS.down.keys.some((k) => keys.has(k))) move.y -= speed;
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
// Turning what is held
// ---------------------------------------------------------------------------
//
// The keys and U change how the person WANTS it turned. The hand asks for that
// at a pace its 60 N m wrist can follow for this thing, and the engine turns it
// with what the wrist has (interaction.js, "Turning what is held"): `hand_q` on
// the step, which the engine's grip law turns towards with a bounded torque.
// Nothing here sets how anything is turned. A thing held against the floor, or
// too heavy to swing round quickly, turns as far and as fast as it can.
//
// The wish is kept relative to the way the person faces, so a pillar held
// across the view stays across it as they turn round, the way a thing in your
// hands comes round with you -- and what comes round is the wish, at the same
// pace: the pillar follows as fast as the wrist can take it.
const UP = new THREE.Vector3(0, 1, 0);
function facingTurn() { return new THREE.Quaternion().setFromAxisAngle(UP, yaw); }

function startTurning(entry) {
  const q = entry.mesh.quaternion.clone();
  return { want: facingTurn().invert().multiply(q), asked: q, pace: turnPace(entry) };
}

// Held turn keys turn the wish, about the person's own axes.
function turnFromKeys(dt) {
  const turn = world.held && world.held.turn;
  if (!turn || !["ready", "blocked"].includes(world.use.mode)) return;
  for (const t of TURNS) {
    if (!BINDINGS[t.action].keys.some((k) => keys.has(k))) continue;
    turn.want.premultiply(new THREE.Quaternion().setFromAxisAngle(
      new THREE.Vector3(...t.axis), t.sign * TURN_KEY_RATE * dt));
  }
}

// U: the smallest turn that stands it on its end.
function standUpright() {
  const held = world.held;
  if (!held) return;
  if (!held.turn) { turnKeyPressed(); return; }
  if (!["ready", "blocked"].includes(world.use.mode)) return;
  const entry = world.bodies.get(held.name);
  if (!entry) return;
  const wanted = uprightTurn(facingTurn().multiply(held.turn.want), entry.dims, entry.shape);
  if (!wanted) { say("world", `${held.name} has no long side to stand it on.`); return; }
  held.turn.want = facingTurn().invert().multiply(wanted);
  say("you", `Standing ${held.name} upright.`);
  remember(`stood ${held.name} upright in the hand`);
}

// What the hand asks of the wrist this tick: the wish come round towards what
// is wanted, at the pace this thing can take. As [w, x, y, z].
function wristWish(dt) {
  const turn = world.held && world.held.turn;
  if (!turn) return null;
  askTowards(turn.asked, facingTurn().multiply(turn.want), turn.pace, dt);
  const q = turn.asked;
  return [q.w, q.x, q.y, q.z];
}

// A turn key on something the wrist cannot turn says why, once each time it
// is taken hold of -- and says what can: the room.
function turnKeyPressed() {
  const held = world.held;
  if (!held || held.turn || held.saidTurn) return;
  held.saidTurn = true;
  const entry = world.bodies.get(held.name);
  if (held.blade) {
    say("world", "A blade is turned with the right mouse: its edge faces left, down, right or up.");
  } else if (!held.loose) {
    say("world", `${held.bow ? held.bow.object : held.name} is attached to other things:`
      + ` it turns only the way they let it.`);
  } else {
    say("world", `${held.name} is ${entry ? Math.round(entry.mass) : "too many"} kg — too heavy`
      + ` for one hand to hold up and turn (it holds up to about`
      + ` ${Math.floor(0.9 * 800 / 9.80665)} kg and can still move it). Press`
      + ` ${keyOf("talk")} and ask the room to turn it.`);
  }
}

// ---------------------------------------------------------------------------
// The hand
// ---------------------------------------------------------------------------

// What the crosshair is on, asked of the engine. One question in flight at a
// time: the answer is worth about a millisecond and the view moves faster than
// that, so the newest question wins and the rest are dropped.
let aimBusy = false;
async function aim() {
  // Asked while something is held too: it is held beside the view rather than
  // in front of it, so the crosshair is on something else -- and "put it on
  // that" has to know what that is. The label stays down while holding.
  if (!world.session || aimBusy) return;
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
    if (!world.held) showLabel(world.aim);
  } catch { /* the next frame asks again */ } finally { aimBusy = false; }
}

// What can be done with the thing a click opened, listed in its label: its own
// actions, then the built-in ones, then taking hold. Closed when the crosshair
// leaves it, on Esc, or once one of them has been done.
function updateMenu(found) {
  const list = $("label-actions");
  if (!found || found.name !== world.menuFor) {
    if (world.menuFor) world.menuFor = null;
    list.hidden = true;
    return;
  }
  const rows = allActionsFor(found.name).map((action, i) => `${i + 1} · ${action.label}`);
  rows.push(`${keyOf("interact")} or double-click · take hold`);
  const said = rows.join("\n");
  if (list.dataset.said !== said) {
    list.dataset.said = said;
    list.replaceChildren(...rows.map((row) => {
      const line = document.createElement("span");
      line.textContent = row;
      return line;
    }));
  }
  list.hidden = false;
}

function showLabel(found) {
  updateMenu(found);
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
      + (bladeFor(found.name) ? " · has an edge: double-click to take it by the grip" : "")
      + (!bladeFor(found.name) && !picks.profileOf(found.name) && throwable(entry, onAJoint(found.name))
          ? ` · ${entry.mass < 10 ? entry.mass.toFixed(2) : entry.mass.toFixed(1)} kg`
            + ` · click: what you can do · ${keyOf("interact")} or double-click: take hold` : "")
      + (profileOf(found.name)
          ? ` · part of ${profileOf(found.name).object}: ${keyOf("interact")} or double-click to take it up`
          : "")
      + (picks.profileOf(found.name)
          ? ` · part of ${picks.profileOf(found.name).object}: ${keyOf("interact")} or click to take it`
            + ` up by its grip`
          : "")
    : "";
  cross.classList.toggle("on", !entry?.anchored || !!profileOf(found.name)
                               || !!picks.profileOf(found.name));
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
  else if (what === "put down") putDown();
  else if (what === "let fly") letFly();
  else if (what === "draw") startDraw();
  else if (what === "loose") loose();
  else if (what === "let down") letDown();
  else if (what === "settle") settleDown();
  else if (what === "swing") picks.swing();
  else if (what === "lever") picks.lever();
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

// On any joint at all: hauled against it rather than taken by a grip.
function onAJoint(name) {
  return world.joints.some((j) => j.attached && (j.a === name || j.b === name));
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

// Every joint, asked for: a step carries the list only when the SET of them
// changes, because sending every angle sixty times a second is the traffic
// that was trimmed out of the reply in the first place. What each elastic
// holds is the exception, and comes with the step itself (takeElastics).
async function refreshJoints() {
  const got = await act("joints", {});
  if (got && got.joints) drawJoints(got.joints);
  return got && got.joints;
}

// What each elastic holds -- its stretch, its pull and the energy in it -- as
// the engine worked it out for the reply that has just come back. A step
// carries a reading for every spring that changed in it, so a draw brings its
// limbs' joules with every step, folded into the joints the page already
// holds, by id. Everything that reads world.joints then reads this step's
// numbers: the bow's meter, what a loose says the limbs held, the drawn
// string's panel line. Asked for four times a second instead, the meter
// trailed the draw by 100 mm at 0.4 m/s: 16.4 J shown at 387 mm, where the
// engine's own trial holds 32.0 J.
function takeElastics(readings) {
  if (!readings || !readings.length) return;
  const now = new Map(readings.map((r) => [r.id, r]));
  for (const joint of world.joints) {
    const reading = now.get(joint.id);
    if (reading) Object.assign(joint, reading);
  }
}

// What the elastics of ONE mechanism hold: those joined to the thing being drawn
// through any chain of attached joints, without going on through scenery.
// Summed over the whole room it read every other assembly's springs as this
// one's draw (docs/interaction-profiles.md).
function storedInElastics(name) {
  const seen = new Set([name]);
  const reach = [name];
  while (reach.length) {
    const at = reach.pop();
    for (const j of world.joints) {
      if (!j.attached || (j.a !== at && j.b !== at)) continue;
      const other = j.a === at ? j.b : j.a;
      if (seen.has(other)) continue;
      seen.add(other);
      if (!world.bodies.get(other)?.anchored) reach.push(other);
    }
  }
  return world.joints.reduce((sum, j) => sum + (j.kind === "elastic" && j.attached &&
    seen.has(j.a) && seen.has(j.b) ? (j.stored_j || 0) : 0), 0);
}

async function pickUp() {
  if (!world.aim) return;
  // An action has the hand while it runs (runAction).
  if (world.acting) { say("world", "Your hand is busy with an action."); return; }
  world.menuFor = null;
  const name = world.aim.name;
  const entry = world.bodies.get(name);
  // A part of something with a profile takes up the whole of it -- the bow,
  // not its grip, even though the grip is fixed in place. With Alt held the
  // hand takes exactly the part under the crosshair instead: the advanced
  // hold, which is how a bowstring can still be grabbed by itself.
  const profile = !(keys.has("AltLeft") || keys.has("AltRight")) && profileOf(name);
  if (profile) { await takeUpBow(profile); return; }
  // A part of a tool that digs takes the tool up by its grip (picks.js).
  const tool = !(keys.has("AltLeft") || keys.has("AltRight")) && picks.profileOf(name);
  if (tool) { await picks.takeUp(tool); return; }
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
    // A loose thing a hand can lift is taken by a GRIP, not carried: held at
    // its middle by the bounded hand, so that bringing it in, winding it up
    // and throwing it are the hand's force acting on its mass. Anything on a
    // joint keeps the hold it had -- a bowstring is hauled, a gate is shoved.
    if (entry && throwable(entry, onAJoint(name))) {
      const at = entry.mesh.position;
      await act("wield", { name, grip: [at.x, at.y, at.z] });
      // Held beside the view, far enough out for its size -- the wheel moves it
      // -- and turned by the wrist from the way it is now.
      world.held = { name, throwable: true, loose: true,
                     distance: holdDistanceFor(radiusOf(entry)), turn: startTurning(entry) };
      world.use = { mode: "ready", name, kg: entry.mass,
                    noun: entry.shape === "sphere" ? "ball" : "thing",
                    latched: !!latchOn(name), turnable: entry.shape !== "sphere",
                    bringing: { from: at.clone(), since: performance.now() } };
      $("crosshair").classList.add("holding");
      $("label").hidden = true;
      $("carry").hidden = false;
      remember(`took hold of the ${entry.material || ""} ${name}`.replace(/\s+/g, " "));
      say("you", `Took hold of ${name} — ${entry.mass < 10 ? entry.mass.toFixed(2) : entry.mass.toFixed(1)} kg.`);
      showUse();
      return;
    }
    await act("grab", { name });
    // Too heavy for the hand to hold up, a loose thing is CARRIED: placed where
    // the hand is. It is carried beside the view like anything else loose --
    // brought there over a third of a second -- rather than on the crosshair,
    // where a big one filled the screen. A thing on a joint is hauled from
    // exactly where it was taken hold of (below).
    const loose = !!entry && !onAJoint(name);
    world.held = { name, loose, distance: loose ? holdDistanceFor(radiusOf(entry))
                                                : clamp(world.aim.distance_m, 0.6, 4.0) };
    if (loose) world.held.bringing = { from: entry.mesh.position.clone(), since: performance.now() };
    world.use = { mode: "carrying", name, kg: entry?.mass || 0, latched: !!latchOn(name), loose };
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
    if (entry && !loose) {
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
                      latch: latchOn(name).id };
    }
    $("crosshair").classList.add("holding");
    $("label").hidden = true;
    $("carry").hidden = false;
    remember(`picked up the ${entry?.material || ""} ${name}`.replace(/\s+/g, " "));
    say("you", `Picked up ${name}.`);
    showUse();
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
    const stored = storedInElastics(name);
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
  aimArc.hide();
  world.use = { mode: "none" };
  showUse();
  try {
    await act("release");
    remember(at ? `let go of ${name} at ${at.x.toFixed(2)}, ${at.y.toFixed(2)}, ${at.z.toFixed(2)} m`
                : `let go of ${name}`);
    say("you", at ? `Let go of ${name} at ${at.y.toFixed(2)} m up.` : `Let go of ${name}.`);
  } catch (error) { say("bad", String(error.message || error)); }
}

// ---------------------------------------------------------------------------
// Using what is in the hand: one control language (interaction.js)
// ---------------------------------------------------------------------------
//
// A throw is the hand moving: a wind-up, then a stroke the ENGINE makes at its
// own step rate with the hand's bounded force, letting go when the thing gets
// to the end. Nothing here gives anything a speed. A heavy ball winds up slower
// and leaves slower because the same 800 N has more to move, and what it left
// with, and the work the hand put in, are read back from the engine.
//
// (This replaced a throw that was three 0.55 m jumps of a CARRIED body and a
// release. A carry is placement and zeroes the body's speed every step, so it
// left the hand at 0.00 m/s and fell 1.65 m in front of you, whatever it was.)
const aimArc = new AimArc(scene);

function startWindUp() {
  Object.assign(world.use, { mode: "preparing", since: performance.now(), asked: 0,
                             reached: 0, more: false, bringing: null });
  showUse();
}

function cancelWindUp() {
  Object.assign(world.use, { mode: "ready", asked: 0 });
  say("you", `Lowered ${world.use.name}.`);
  showUse();
}

async function letFly() {
  const use = world.use;
  const entry = world.held && world.bodies.get(world.held.name);
  if (!entry || use.mode !== "preparing") return;
  const grip = use.grip || entry.mesh.position.clone();
  const reached = use.reached || 0;
  // The stroke the arc on screen was drawn from, if it is the one just shown;
  // otherwise one made now (throwStroke lets go at its end either way).
  const aimed = use.aimed && performance.now() - use.aimed.at < 500 ? use.aimed.stroke : null;
  use.mode = "throwing";
  showUse();
  try {
    const reply = await act("stroke", aimed || throwStroke(camera, grip, reached));
    // The work the hand does on the throw itself, not on the wind-up before it.
    use.workBefore = reply && reply.hand ? reply.hand.work_j : 0;
  } catch (error) {
    use.mode = "ready";
    say("bad", String(error.message || error));
    showUse();
  }
}

// Put it down: lowered by the same hand onto what is under it, and let go of
// when it gets there. A carried thing is set down as it always was.
async function putDown() {
  const held = world.held;
  if (!held) return;
  if (held.pick) { await picks.putDown(`You put down ${held.pick.object}.`); return; }
  if (held.bow) {
    // A bow is not dropped with its string drawn: let down first, then let go.
    if (world.use.mode === "drawing") await letDown();
    else if (world.use.mode === "bow-ready") await releaseBow(`You let go of ${held.bow.object}.`);
    return;
  }
  if (!held.throwable && !held.loose) { await dropIt(); return; }
  const entry = world.bodies.get(held.name);
  if (!entry) return;
  // Where it comes to rest: its underside -- turned as it is, so a pillar held
  // upright rests on its end -- 2 mm over what is below it.
  const centre = held.throwable ? (world.use.grip || entry.mesh.position.clone())
                                : entry.mesh.position.clone();
  const restsAt = dropOnto.y + halfHeight(entry) + 0.002;
  if (dropOnto.empty || centre.y - restsAt < 0.02) { await dropIt(); return; }
  world.use.mode = "placing";
  world.use.more = false;
  showUse();
  if (!held.throwable) {
    // Carried, which is placement: so it is set down by being placed lower and
    // lower, at 0.8 m/s, onto what is below it -- and let go of there, rather
    // than dropped from wherever it was carried.
    held.lowering = { from: centre, toY: restsAt, since: performance.now(),
                      ms: 1000 * clamp((centre.y - restsAt) / 0.8, 0.15, 2.0) };
    return;
  }
  try { await act("stroke", placeStroke(centre, restsAt)); }
  catch (error) {
    world.use.mode = "ready";
    say("bad", String(error.message || error));
    showUse();
  }
}

// Let go of what has been lowered onto what is below it, where it was put.
async function settleDown() {
  const held = world.held;
  if (!held || world.use.mode !== "placing") return;
  const name = held.name;
  world.held = null;
  $("crosshair").classList.remove("holding");
  $("carry").hidden = true;
  clearGuides();
  aimArc.hide();
  world.use = { mode: "none" };
  showUse();
  try {
    await act("release");
    say("you", `Put ${name} down.`);
    remember(`put ${name} down`);
  } catch (error) { say("bad", String(error.message || error)); }
}

function moreAction(n) {
  world.use.more = false;
  if (n === 1) intend("drop");
  else if (n === 2) intend("put down");
  else if (n === 3) unlatch();
  showUse();
}

// Where the hand wants a throwable thing this tick: brought in to the hand,
// held there, or wound back as far as has been asked. While the engine is
// making a stroke the hand is the engine's, and nothing is sent.
function throwingHand(now) {
  const use = world.use;
  if (use.mode === "preparing") {
    use.asked = Math.min(1, (now - use.since) / (WIND_UP_S * 1000));
    const p = windUpPoint(camera, use.asked, world.held.distance);
    return [p.x, p.y, p.z];
  }
  if (use.mode !== "ready" && use.mode !== "blocked") return null;
  const hold = holdPoint(camera, world.held.distance);
  if (use.bringing) {
    // Brought in over a third of a second rather than yanked: the bounded hand
    // would get it there anyway, but at 800 N into a quarter-kilogram ball.
    const s = Math.min(1, (now - use.bringing.since) / 350);
    if (s >= 1) use.bringing = null;
    const p = use.bringing ? use.bringing.from.clone().lerp(hold, s) : hold;
    return [p.x, p.y, p.z];
  }
  return [hold.x, hold.y, hold.z];
}

// Where the hand puts a loose thing it CARRIES -- one too heavy to hold up,
// which is placed where the hand is: beside the view like anything else loose,
// brought there over a third of a second; and, being put down, lowered onto
// what is below it and then let go of.
function carriedHand(now) {
  const held = world.held;
  if (held.lowering) {
    const s = Math.min(1, (now - held.lowering.since) / held.lowering.ms);
    const p = held.lowering.from.clone();
    p.y += (held.lowering.toY - p.y) * s;
    if (s >= 1) intend("settle");
    return [p.x, p.y, p.z];
  }
  const hold = holdPoint(camera, held.distance);
  if (held.bringing) {
    const s = Math.min(1, (now - held.bringing.since) / 350);
    if (s >= 1) held.bringing = null;
    const p = held.bringing ? held.bringing.from.clone().lerp(hold, s) : hold;
    return [p.x, p.y, p.z];
  }
  return [hold.x, hold.y, hold.z];
}

// What the engine says the hand did: how far back a wind-up actually got, and
// how a stroke ended.
function followTheHand(hand) {
  const use = world.use;
  if (!hand || !world.held || !world.held.throwable) return;
  if (hand.grip_m && hand.holding) use.grip = new THREE.Vector3(...hand.grip_m);
  if (use.mode === "preparing" && use.grip) {
    use.reached = windUpReached(camera, use.grip, world.held.distance);
    showUse();
  }
  if (use.mode !== "throwing" && use.mode !== "placing") return;
  if (hand.stroke_ended === "let go" && hand.let_go && !hand.holding) { letGoOf(hand); return; }
  // Put down: the hand has lowered it onto what is below and kept hold -- the
  // stroke reached its end, or what it rests on stopped it first. Now it lets
  // go, and the thing is left standing where it was put.
  if (use.mode === "placing" && !hand.stroking
      && ["reached", "blocked", "gave up"].includes(hand.stroke_ended)) {
    intend("settle");
    return;
  }
  if (!hand.stroking && ["blocked", "gave up", "cancelled"].includes(hand.stroke_ended)) {
    use.mode = "blocked";
    say("world", `${use.name} would not go any further — something is in the way.`);
    showUse();
  }
}

function letGoOf(hand) {
  const use = world.use;
  const name = world.held.name;
  const v = hand.let_go.velocity_m_s;
  const speed = Math.hypot(v[0], v[1], v[2]);
  const thrown = use.mode === "throwing";
  world.held = null;
  $("crosshair").classList.remove("holding");
  $("carry").hidden = true;
  clearGuides();
  aimArc.hide();
  if (thrown) {
    const work = hand.let_go.work_j - (use.workBefore || 0);
    const kg = use.kg || 0;
    const text = `${name} left your hand at ${speed.toFixed(1)} m/s — the throw was`
      + ` ${work.toFixed(work < 10 ? 1 : 0)} J of your hand's work on`
      + ` ${kg < 10 ? kg.toFixed(2) : kg.toFixed(1)} kg.`;
    say("world", text);
    remember(`threw ${name}: it left the hand at ${speed.toFixed(1)} m/s after`
      + ` ${work.toFixed(1)} J of the hand's work`);
    world.use = { mode: "thrown", name, kg, result: text, until: performance.now() + 4000 };
  } else {
    say("you", `Put ${name} down.`);
    remember(`put ${name} down`);
    world.use = { mode: "none" };
  }
  showUse();
}

// Where the throw would go if it were let go of now: the engine's own preview
// of this hand on this thing, a few times a second, redrawn as the view and the
// wind-up change. It moves nothing.
let previewBusy = false, previewAt = 0;
async function previewThrow() {
  const use = world.use;
  if (!world.held || !world.held.throwable || (use.mode !== "ready" && use.mode !== "preparing")) {
    aimArc.hide();
    return;
  }
  const now = performance.now();
  if (previewBusy || !use.grip || use.bringing || now - previewAt < 180) return;
  previewAt = now;
  previewBusy = true;
  try {
    // The very stroke letFly would send now, let go of at its end.
    const stroke = throwStroke(camera, use.grip, use.mode === "preparing" ? use.reached || 0 : 0);
    const seen = await act("preview_stroke", Object.assign({ horizon_s: 4 }, stroke));
    if (world.use !== use || (use.mode !== "ready" && use.mode !== "preparing")) return;
    const v = seen.let_go_velocity_m_s || [0, 0, 0];
    use.preview = { possible: !!(seen.possible && seen.reaches_end), why: seen.why || "",
                    speed: Math.hypot(v[0], v[1], v[2]),
                    hit: !!(seen.flight && seen.flight.hit),
                    hitName: (seen.flight && seen.flight.hit_name) || "" };
    // What is on screen is what letFly throws: this stroke, not one made afresh
    // when the button comes up. A preview is a fifth of a second old by then,
    // and measured on this page, a throw made afresh after turning 12 degrees
    // came down 2.25 m to the side of the ring, and one let go halfway through
    // the wind-up 1 m past it. The engine starts the stroke from wherever the
    // thing is when it is thrown.
    use.aimed = use.preview.possible ? { stroke, at: performance.now() } : null;
    if (use.preview.possible) aimArc.show(seen.flight); else aimArc.hide();
    showUse();
  } catch { /* the next tick asks again */ } finally { previewBusy = false; }
}

function showUse() {
  const use = world.use;
  const box = $("use");
  if (!use || use.mode === "none") { box.hidden = true; return; }
  const help = helpFor(use);
  box.hidden = false;
  // Beside the crosshair while something is held, out of the way of it.
  box.classList.toggle("beside", !!world.held);
  $("use-title").innerHTML = help.title;
  $("use-line").innerHTML = help.line;
  $("use-note").textContent = help.note;
  $("use-turn").innerHTML = help.turn || "";
  $("use-meter").hidden = !help.meter;
  if (help.meter) {
    $("use-meter-label").textContent = help.meter.label;
    $("use-meter-fill").style.width = `${Math.round(100 * help.meter.fraction)}%`;
    $("use-meter-value").textContent = help.meter.value;
  }
}

// ---------------------------------------------------------------------------
// A bow, by its profile (docs/interaction-profiles.md)
// ---------------------------------------------------------------------------
//
// Taking up any part of it takes the string. Holding primary draws: the ENGINE
// makes the stroke, and the hand -- 800 N -- pulls the string back along the
// profile's axis until the limbs balance it; how far it comes is the bow's
// answer, and the meter reads it off the engine. Letting go opens the hand and
// the string runs home; the nock is one-way, so the arrow comes off the string
// by itself as the string slows at brace, and what it leaves with is what the
// limbs held, less what the string and the tips kept. Nothing here is a speed,
// and nothing here lets the arrow go.

function rememberProfiles(spec) {
  // The actions the room's chat gave its things (offer_actions), each
  // {body, label, steps}: on the number keys when the crosshair is on that thing.
  world.actions = (spec && spec.actions) || [];
  world.profiles = ((spec && spec.interactions) || [])
    .filter((p) => p.template === "draw-and-release");
  // And the tools that dig, which picks.js drives (swing-and-lever).
  world.tools = ((spec && spec.interactions) || [])
    .filter((p) => p.template === "swing-and-lever");
}

// Tools that dig: taken up by the grip their point was given with, swung at
// the ground and levered out. The engine makes every stroke; picks.js says
// where the person is and what came back.
const picks = makePicks({ world, act, say, remember, showUse, camera, carryGround, $ });

function profileOf(name) {
  return world.profiles.find((p) => p.parts.includes(name)) || null;
}

// Where each bow's string sits unshot, taken from the room as it opens, with
// everything at rest. Taken instead when the string was picked up, it was
// wherever a string still ringing from the last shot happened to be -- and the
// hand then held it there, off brace, with its full 800 N.
function braceProfiles() {
  for (const profile of world.profiles) {
    const entry = world.bodies.get(profile.draw.part);
    if (entry) profile.brace = entry.mesh.position.clone();
  }
}

function bowJoint(kind, a, b) {
  return world.joints.find((j) => j.kind === kind &&
    ((j.a === a && j.b === b) || (j.a === b && j.b === a))) || null;
}

// The bow as the engine last reported it: whether there is an arrow on the
// string, whether the string is still strung, and what ITS limbs hold.
function bowState(profile) {
  const part = profile.draw.part;
  const nock = bowJoint("fixing", profile.nock.a, profile.nock.b);
  const strung = world.joints.some((j) => j.kind === "link" && j.attached &&
                                          (j.a === part || j.b === part));
  const stored = profile.limbs.reduce((sum, [a, b]) => {
    const limb = bowJoint("elastic", a, b);
    return sum + (limb && limb.attached ? (limb.stored_j || 0) : 0);
  }, 0);
  return { arrowReady: !!(nock && nock.attached), nock, strung, stored };
}

function notice(name, text) {
  world.use = { mode: "notice", name, result: text, until: performance.now() + 4000 };
  say("world", text);
  showUse();
}

async function takeUpBow(profile) {
  const part = profile.draw.part;
  const entry = world.bodies.get(part);
  const state = bowState(profile);
  if (!entry || !state.strung) {
    notice(profile.object, entry ? `The string of ${profile.object} is cut — it cannot be drawn.`
                                 : `${profile.object} has no string any more.`);
    return;
  }
  await act("grab", { name: part });
  world.held = { name: part, bow: profile, distance: 1 };
  world.use = { mode: "bow-ready", name: profile.object,
                brace: (profile.brace || entry.mesh.position).clone(),
                bow: { arrowReady: state.arrowReady, strung: true, drawn: 0,
                       max: profile.draw.max_mm / 1000, storedJ: state.stored, pullN: 0 } };
  $("crosshair").classList.add("holding");
  $("label").hidden = true;
  remember(`took up ${profile.object} by its string`);
  say("you", `Took up ${profile.object}` + (state.arrowReady ? ", an arrow on the string."
                                                              : " — there is no arrow on the string."));
  showUse();
}

async function releaseBow(text) {
  world.held = null;
  world.use = { mode: "none" };
  $("crosshair").classList.remove("holding");
  aimArc.hide();
  showUse();
  try { await act("release"); } catch (error) { say("bad", String(error.message || error)); }
  if (text) say("you", text);
}

async function startDraw() {
  const use = world.use;
  const profile = world.held && world.held.bow;
  if (!profile || use.mode !== "bow-ready") return;
  const entry = world.bodies.get(profile.draw.part);
  if (!entry) return;
  if (!bowState(profile).strung) {
    await releaseBow();
    notice(profile.object, `The string of ${profile.object} is cut — it cannot be drawn.`);
    return;
  }
  const at = entry.mesh.position.clone();
  const back = use.brace.clone()
    .addScaledVector(new THREE.Vector3(...profile.draw.axis), profile.draw.max_mm / 1000);
  use.mode = "drawing";
  showUse();
  try {
    await act("stroke", { path: [[at.x, at.y, at.z], [back.x, back.y, back.z]],
                          speed_m_s: profile.draw.speed_mm_s / 1000, accel_m_s2: 2.0,
                          lead_m: 0.05, let_go: false, give_up_s: 30 });
  } catch (error) {
    use.mode = "bow-ready";
    say("bad", String(error.message || error));
    showUse();
  }
}

// Loosed: the hand opens, and that is all this does. The nock is one-way, so
// the arrow comes off the string by itself, at the engine's own step, when the
// string slowing at brace would have to pull it back. Here the arrow is watched
// for a second and a half and what it left with is said, with the share of the
// limbs' energy it carried.
async function loose() {
  const use = world.use;
  const profile = world.held && world.held.bow;
  if (!profile || use.mode !== "drawing") return;
  // What the limbs hold as the hand opens: the last step's reading, and no
  // step runs between that reply and this release -- a loose asked for while a
  // step is in flight waits for the next tick, and runs before its step.
  const state = bowState(profile);
  world.held = null;
  $("crosshair").classList.remove("holding");
  aimArc.hide();
  // How far ahead of the string the arrow sits, along the shot, while it is
  // nocked: once it is further than that, it has come off (see followTheBow).
  const shot = new THREE.Vector3(...profile.draw.axis).negate();
  const ahead = world.bodies.get(profile.projectile), behind = world.bodies.get(profile.draw.part);
  const apart = ahead && behind ? ahead.mesh.position.clone().sub(behind.mesh.position).dot(shot) : null;
  world.use = { mode: "loosed", name: profile.object, profile, stored: state.stored,
                arrowReady: state.arrowReady, shot, apart, left: null, reported: false,
                watchUntil: performance.now() + 1500, until: performance.now() + 6000,
                result: state.arrowReady ? "Loosed…" : "Loosed with no arrow on the string." };
  showUse();
  try { await act("release"); } catch (error) { say("bad", String(error.message || error)); }
  remember(`loosed ${profile.object} with ${state.stored.toFixed(1)} J in its limbs`);
}

async function letDown() {
  const use = world.use;
  const profile = world.held && world.held.bow;
  if (!profile || (use.mode !== "drawing" && use.mode !== "bow-ready")) return;
  const entry = world.bodies.get(profile.draw.part);
  if (!entry) return;
  const at = entry.mesh.position.clone();
  if (at.distanceTo(use.brace) < 0.01) { await releaseBow(`You let go of ${profile.object}.`); return; }
  use.mode = "letting-down";
  showUse();
  try {
    await act("stroke", { path: [[at.x, at.y, at.z], [use.brace.x, use.brace.y, use.brace.z]],
                          speed_m_s: 0.25, accel_m_s2: 1.0, lead_m: 0.05, let_go: false,
                          give_up_s: 6 });
  } catch (error) {
    use.mode = "drawing";
    say("bad", String(error.message || error));
    showUse();
  }
}

// After every step: how far back the string actually is, what this bow's limbs
// hold, how hard the hand pulls -- and, once loosed, how fast the arrow went.
// The draw and the joules come from the same reply, so the meter says one
// instant's numbers.
function followTheBow(state) {
  const use = world.use;
  const now = performance.now();
  if (use.mode === "loosed") {
    // What the arrow LEFT with: its speed along the shot at the first report
    // after it is clear of the string -- the nock has let it go -- and not the
    // fastest it is ever seen. The string and the arrow run together a little
    // faster than the arrow leaves, because the nock's grip takes some back as
    // the arrow slides off it, and an arrow falling after it has left is
    // faster again, which is gravity: measured on the courtyard's bow, 8.59
    // m/s together, 8.30 free, and 9.36 on its way to the floor.
    const arrow = (state.bodies || []).find((b) => b.name === use.profile.projectile);
    const ahead = world.bodies.get(use.profile.projectile);
    const behind = world.bodies.get(use.profile.draw.part);
    if (use.left === null && use.apart !== null && arrow && arrow.velocity_m_s && ahead && behind
        && ahead.mesh.position.clone().sub(behind.mesh.position).dot(use.shot) > use.apart + 0.01) {
      use.left = new THREE.Vector3(...arrow.velocity_m_s).dot(use.shot);
    }
    if (!use.reported && now > use.watchUntil) {
      use.reported = true;
      if (use.arrowReady && use.left !== null) {
        const kg = ahead?.mass || 0;
        const carried = 0.5 * kg * use.left * use.left;
        const share = use.stored > 0.05 ? carried / use.stored : 0;
        if (share > 0) use.profile.efficiency = share;
        use.result = `The arrow left at ${use.left.toFixed(1)} m/s — the limbs held`
          + ` ${use.stored.toFixed(1)} J and ${Math.round(100 * share)}% of it went into the arrow;`
          + ` the string and the limb tips kept the rest.`;
        say("world", use.result);
        remember(`the arrow left ${use.profile.object} at ${use.left.toFixed(1)} m/s`);
      } else if (use.arrowReady) {
        use.result = "The arrow never came clear of the string.";
        say("world", use.result);
      }
      showUse();
    }
    return;
  }
  const profile = world.held && world.held.bow;
  if (!profile) return;
  const entry = world.bodies.get(profile.draw.part);
  if (!entry || !use.brace) return;
  const s = bowState(profile);
  const hand = state.hand || {};
  use.bow = Object.assign(use.bow || {}, {
    arrowReady: s.arrowReady, strung: s.strung, storedJ: s.stored,
    drawn: Math.max(0, entry.mesh.position.clone().sub(use.brace)
                        .dot(new THREE.Vector3(...profile.draw.axis))),
    max: profile.draw.max_mm / 1000,
    pullN: hand.force_n ? Math.hypot(...hand.force_n) : 0,
    // Two different ends to a draw: the hand ran out of strength against the
    // limbs, or it got as far as the bow's profile asks and holds there.
    blocked: use.mode === "drawing" && !hand.stroking && hand.stroke_ended === "blocked",
    full: use.mode === "drawing" && !hand.stroking && hand.stroke_ended === "reached",
  });
  if (!s.strung) {
    releaseBow();
    notice(profile.object, `The string of ${profile.object} was cut.`);
    return;
  }
  if (use.mode === "letting-down" && !hand.stroking && hand.stroke_ended) {
    releaseBow("You let the string down.");
    return;
  }
  showUse();
}

// Where the shot would go: what the limbs hold NOW, times the share of it this
// bow gave its arrow on its last shot, as the arrow's speed along its own axis
// -- then the engine's flight. Approximate, and said to be: the share is from
// one shot, and the draw is not yet the shot. Before the first shot there is
// no share to use, and it says that instead of guessing.
let shotBusy = false, shotAt = 0;
async function previewShot() {
  const use = world.use;
  const profile = world.held && world.held.bow;
  if (!profile || use.mode !== "drawing" || !use.bow || !use.bow.arrowReady) {
    if (profile) aimArc.hide();
    return;
  }
  const now = performance.now();
  if (shotBusy || now - shotAt < 250) return;
  const arrow = world.bodies.get(profile.projectile);
  const kg = arrow ? arrow.mass || 0 : 0;
  if (!(profile.efficiency > 0)) {
    use.bow.noPreview = "shoot it once and its efficiency is measured for the aim";
    aimArc.hide();
    return;
  }
  if (!arrow || !(kg > 0) || !(use.bow.storedJ > 0.05)) { aimArc.hide(); return; }
  shotAt = now;
  shotBusy = true;
  try {
    const speed = Math.sqrt(2 * profile.efficiency * use.bow.storedJ / kg);
    const along = new THREE.Vector3(...profile.draw.axis).negate();
    const axis = new THREE.Vector3(1, 0, 0).applyQuaternion(arrow.mesh.quaternion);
    if (axis.dot(along) < 0) axis.negate();
    const p = arrow.mesh.position;
    const flight = await act("preview_flight", {
      from: [p.x, p.y, p.z], velocity: [axis.x * speed, axis.y * speed, axis.z * speed],
      horizon_s: 4, ignoring: profile.projectile });
    if (world.use !== use || use.mode !== "drawing") return;
    use.preview = { possible: true, text: `approximately ${speed.toFixed(1)} m/s, from what the`
      + ` limbs hold and this bow's last shot (${Math.round(100 * profile.efficiency)}% of it reached the arrow)` };
    aimArc.show(flight);
    showUse();
  } catch { /* the next step asks again */ } finally { shotBusy = false; }
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
  // What heat has done to what things can carry: the engine's "mechanics"
  // block (docs/thermal-mechanics.md), and each body's share of section that is
  // char or gone, which it is drawn darker by -- a picture of that number.
  strength: null,
  char: new Map(),        // body name -> share of its section char or burned away
  weakest: new Map(),     // body name -> the lowest share of strength already said
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

const CHARCOAL = new THREE.Color(0x1b1512);

function glow(name, tK) {
  const entry = world.bodies.get(name);
  const own = heat.glowing.get(name);
  const g = entry ? glowOf(tK, heat.last ? heat.last.ambient_k : 293.15) : null;
  // Char stays when the glow goes: a body whose section is part char is drawn
  // that much darker, whatever its temperature now.
  const charred = entry ? (heat.char.get(name) || 0) : 0;
  if (!g && !(charred > 0.001)) {
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
  mine.color.copy(look(entry.material).color).lerp(CHARCOAL, clamp(0.85 * charred, 0, 0.85));
  if (g) {
    mine.emissive.copy(g.color);
    mine.emissiveIntensity = g.intensity;
  } else {
    mine.emissive.setRGB(0, 0, 0);
    mine.emissiveIntensity = 0;
  }
}

// The share of a body's section that is char or burned away: what it is drawn
// darker by.
function charShare(b) {
  const [w, h] = b.section_mm || [0, 0];
  const [sw, sh] = b.sound_mm || [w, h];
  return w > 0 && h > 0 ? clamp(1 - (sw * sh) / (w * h), 0, 1) : 0;
}

// The engine's "mechanics" block: what heat has left of what each heated
// body can carry, and every attachment made of one with what it carries
// against what it can still take. Drawn as char and listed in the Heat panel;
// nothing here decides a strength.
function drawStrength(block) {
  heat.strength = block || null;
  const now = new Map();
  for (const b of (block && block.bodies) || []) {
    const share = charShare(b);
    if (share > 0.001) now.set(b.name, share);
  }
  const touched = new Set([...heat.char.keys(), ...now.keys()]);
  heat.char = now;
  const hot = new Map(((heat.last && heat.last.bodies) || []).map((b) => [b.name, b.t_k]));
  for (const name of touched) glow(name, hot.get(name) || 0);
  // Said once each time an attachment's strength falls below another fifth of
  // what it had cold: under 80%, 60%, 40%, 20%.
  for (const a of (block && block.attachments) || []) {
    if (!a.attached) continue;
    const said = heat.weakest.get(a.id) ?? 1;
    const step = Math.ceil(a.fraction * 5 - 1e-9) / 5;
    if (step < said) {
      heat.weakest.set(a.id, step);
      // "the oak peg in the gatepost": the member, in the other thing it
      // joins -- which is how anyone names a peg, a bracket or a rope's end.
      if (a.mode !== "stiffness")
        say("world", `${a.member} in ${a.b === a.member ? a.a : a.b} has`
          + ` ${Math.round(100 * a.fraction)}% of its strength left: it carries`
          + ` ${Math.round(a.load_n)} N and can take ${Math.round(a.holds_n)} N`
          + ` (${Math.round(a.rated_n)} N cold).`);
    }
  }
  if (!heat.last && block) showHeat({ bodies: [], regions: [], ledger: { residual_j: 0 } });
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
  const strength = new Map(((heat.strength && heat.strength.bodies) || []).map((s) => [s.name, s]));
  const strengthOf = (s) => {
    if (!s) return "";
    let text = ` · ${Math.round(100 * Math.min(s.tension, s.shear))}% strength left`;
    if (s.char_mm > 0) text += `, ${s.char_mm.toFixed(1)} mm char`;
    if (s.burned_mm >= 0.05) text += `, ${s.burned_mm.toFixed(1)} mm burned`;
    // What is left of it: the size it collides and is drawn at, and what it
    // weighs -- the same state its strength is read from.
    if (s.burned_mm >= 0.05 && Array.isArray(s.now_mm))
      text += ` · now ${s.now_mm.map((v) => Math.round(v)).join(" x ")} mm, ${Number(s.mass_kg).toFixed(2)} kg`;
    if (s.cells_burned > 0) text += `, ${s.cells_burned} cells gone`;
    return text;
  };
  // What statics last said about a body carrying a load: the survey asks when
  // beam theory passes the declared strength, and the lattice answers.
  const underLoad = new Map(((heat.strength && heat.strength.statics) || []).map((s) => [s.name, s]));
  const staticsOf = (name) => {
    const s = underLoad.get(name);
    if (!s) return "";
    if (s.stop === "held") return ` · under its load: holds, its bonds at ${Math.round(100 * s.ratio)}% of what breaks them`;
    if (s.stop === "broke") return ` · under its load: broke, ${s.bonds} bonds`;
    return ` · under its load: ${s.stop}`;
  };
  const listed = new Set();
  for (const b of block.bodies.slice(0, 8)) {
    let text = `${Math.round(b.t_k)} K`;
    if (b.reacting && b.power_w > 0) text += ` · ${(b.power_w / 1000).toFixed(1)} kW`;
    if (b.reacting && b.power_w < 0) text += " · drying";
    if (b.reacting && b.power_w > 0 && b.remaining_s)
      text += ` · ~${Math.round(b.remaining_s / 60)} min at this rate`;
    if (b.heater_w > 0) text += ` · heated ${(b.heater_w / 1000).toFixed(1)} kW`;
    text += strengthOf(strength.get(b.name));
    text += staticsOf(b.name);
    listed.add(b.name);
    row(b.name, text);
  }
  // Whatever has burned away entirely, and what was left of it.
  for (const gone of ((heat.strength && heat.strength.burned_away) || []).slice(-4))
    row(gone.name, `burned away at ${Math.round(gone.t)} s · ${Number(gone.residue_kg).toFixed(2)} kg of ash left with it`);
  // What heat has left of anything that has cooled again: the char stays.
  for (const s of strength.values()) {
    if (listed.has(s.name) || Math.min(s.tension, s.shear) > 0.999) continue;
    row(s.name, `cooled${strengthOf(s)} · would keep ${Math.round(100 * s.if_cooled)}% cold`);
  }
  // Every attachment made of something heat can weaken, and what it carries.
  for (const a of ((heat.strength && heat.strength.attachments) || []).slice(0, 6)) {
    const other = a.b === a.member ? a.a : a.b;
    if (!a.attached) { row(`${a.member} in ${other}`, "gave way"); continue; }
    if (a.mode === "stiffness")
      row(`${a.member} spring`, `${Math.round(a.stiffness_n_m)} of ${Math.round(a.rated_stiffness_n_m)} N/m`);
    else
      row(`${a.member} in ${other}`, `carries ${Math.round(a.load_n)} N of ${Math.round(a.holds_n)} N`
        + ` (${Math.round(a.rated_n)} N cold)`);
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
    + " pictures of these numbers, not sources of heat"
    + (heat.strength ? " · strength left is each material's law (oak EN 1995-1-2, iron EN"
      + " 1993-1-2); char is drawn darker" : "");
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
  heat.strength = null;
  heat.char = new Map();
  heat.weakest = new Map();
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
  return halfHeight(entry) + 0.005;
}

// How far a body reaches below its middle, turned as it is: a pillar held on
// its end reaches down half its length, lying down half its thickness. (This
// used to be half its own height whichever way up it was, so a pillar stood
// on end was lowered onto the floor as if it were still lying down.)
const turned = new THREE.Matrix4();
function halfHeight(entry) {
  const d = entry?.dims;
  if (!d) return 0.045;
  if (entry.shape === "sphere") return d[0] / 2;
  // How far up each of its own sides points: the rotation's second row.
  const m = turned.makeRotationFromQuaternion(entry.mesh.quaternion).elements;
  return (Math.abs(m[1]) * d[0] + Math.abs(m[5]) * d[1] + Math.abs(m[9]) * d[2]) / 2;
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

// How long to wait before each new try after a request got no answer: three
// tries, about a second of waiting in all, then the room says it has stopped.
// Long enough to ride out a moment with no socket to send on, which is what
// ended a room on 2026-09-12; short enough that a server that has really gone
// is said to have. A try at a server that is not there takes about two seconds
// of its own, because Windows retries a refused local connection before it
// fails it -- so when a server really stops, the first "trying again" comes
// about two seconds later and "the room stopped" about nine (measured).
const RETRY_MS = [150, 300, 600];

// A spell of the server being out of reach, written into the frame record when
// it ends: in an answer, in giving up, or in a server that no longer has the
// world. Kept with the spell rather than the record, because a record can go
// out halfway through one.
function recordLostLink(gaveUp) {
  trace.link.times += 1;
  trace.link.longest_ms = Math.max(trace.link.longest_ms,
    Math.round(performance.now() - world.lostSince));
  trace.link.why = world.lostWhy;
  trace.link.gave_up = trace.link.gave_up || gaveUp;
  world.lost = 0;
}

async function tick() {
  if (!world.session || world.busy || world.paused) return;
  // Waiting out a request that got no answer before asking again.
  if (performance.now() < world.retryAt) return;
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
      else if (what === "put down") await putDown();
      else if (what === "let fly") await letFly();
      else if (what === "draw") await startDraw();
      else if (what === "loose") await loose();
      else if (what === "let down") await letDown();
      else if (what === "settle") await settleDown();
      else if (what === "swing") await picks.swing();
      else if (what === "lever") await picks.lever();
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
    } else if (world.held && world.held.throwable) {
      hand = throwingHand(now);
      // And which way it is to face: the wrist's wish, sent only while the
      // page is placing the hand. During a stroke the hand is the engine's,
      // and the wish it had stays where it was.
      if (hand) hand_q = wristWish(elapsed);
    } else if (world.held && world.held.pick) {
      // A tool that digs: held ready by the page; during a swing, a lever or a
      // pull the hand is the engine's stroke, and once a blow has landed it
      // holds where the grip is (picks.js).
      ({ hand, hand_q } = picks.hand());
    } else if (world.held && world.held.bow) {
      // A bow's string: held where the hand took it, or drawn and let down by
      // the engine's own stroke. Nothing is sent; sending would take it back.
    } else if (world.held && world.held.loose) {
      hand = carriedHand(now);
    } else if (world.held) {
      const dir = forwardVector();
      const p = camera.position.clone().add(dir.multiplyScalar(world.held.distance));
      if (world.held.offset) p.add(world.held.offset);
      hand = [p.x, p.y, p.z];
    }
    const steps = clamp(Math.round(elapsed / LIVE_DT), 1, MAX_STEPS);
    const asked = performance.now();
    // Only what moved -- except straight after a request that got no answer.
    // The engine leaves out a body it has already sent, and a reply lost on
    // its way here may have carried the only word of one that moved or went
    // away. A step asked for WITHOUT `moved` sends every body and starts the
    // engine's record of what was sent over, which puts the two back in step.
    const moved = !world.resync;
    const ask = { dt: LIVE_DT, n: steps, moved };
    if (hand) ask.hand = hand;
    if (hand_q) ask.hand_q = hand_q;
    let state = await act("step", ask);
    // The pins too: they only come with a step when their set changes, and
    // the change may have been in the reply that was lost.
    if (!moved) await refreshJoints();
    world.resync = false;
    // Back. Written into the frame record, because the world stood still
    // while the server was out of reach.
    if (world.lost) recordLostLink(false);
    trace.ticks.push(+(performance.now() - asked).toFixed(1));
    // Roughly, and without stringifying it twice: bodies are what a reply is
    // made of, and they are all about the same size.
    trace.bytes.push(200 + (state.bodies ? state.bodies.length * 190 : 0));
    // The answer to a step for a world that was replaced while it was in flight
    // -- the room started again, or rebuilt by the chat. Its round trip is a
    // round trip all the same; what it says about the world is not. Drawn, it
    // would put the old room's bodies into the new one, and its clock would
    // undo the new world's.
    if (world.session !== driving) return;
    world.workingOn = state.working_on || "";
    // What the springs hold after this step, before anything below reads them.
    takeElastics(state.elastics);

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
    // What the hand did this tick, and where a throw would go from here.
    followTheHand(state.hand);
    previewThrow();
    followTheBow(state);
    picks.follow(state);
    previewShot();
    drawRopes();
    followJoints();
    // Strength before heat, so the panel drawHeat fills in says both.
    drawStrength(state.mechanics);
    drawHeat(state.heat);
    narrateCuts(state.cuts, say, remember);
    if (state.terrain) drawTerrain(state.terrain);
    if (state.terrain_changed) patchTerrain(state.terrain_changed);
    if (state.water) drawWater(state.water);
    if (state.joints) {
        const wasAttached = new Map(world.joints.map((p) => [p.id, p.attached]));
        for (const pin of state.joints) {
          if (wasAttached.get(pin.id) && !pin.attached) {
            // A fixing that gave way under its load says why, in the numbers
            // that decided it: the load the solver measured against what the
            // joint could still take -- and what heat had left of its member.
            // Not a one-way one: coming off is what a nock is for, said below.
            if (pin.parted_because && pin.kind === "fixing" && !(pin.comes_off_n > 0)) {
              say("world", `${pin.b} gave way from ${pin.a}: ${pin.parted_because}.`);
              remember(`${pin.b} gave way from ${pin.a}`);
              continue;
            }
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
            if (pin.kind === "fixing") {
              // A one-way fixing coming off is an arrow leaving a string, which
              // is what it is for. A two-way one that lets go was overloaded, or
              // the wood around it was cut away.
              if (pin.comes_off_n > 0) say("world", `${pin.b} came off ${pin.a}.`);
              else say("world", `${pin.b} is no longer fixed to ${pin.a}.`);
              remember(`${pin.b} came off ${pin.a}`);
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
    // new world. The same while the chat is answering: when it has changed
    // the room, the server opens it again before the answer arrives with the
    // new world in it. And while one of a thing's actions runs: a stand step
    // opens the room again from what it has become, and a step on its way
    // comes back "this live world has closed" just before the action's answer
    // hands over the new world (it said "the room stopped" over a plank that
    // had just been stood up). A lost server is still tried again as ever. A
    // world that really stopped is still said, by the first step after.
    const handedOver = world.acting && !error.transient;
    if (world.session === driving && !world.opening && !world.asking && !handedOver) {
      const why = error.message || String(error);
      if (error.transient) world.lostWhy = why;
      if (error.transient && world.lost < RETRY_MS.length) {
        // No answer is not a refusal. Try again shortly, a few times, before
        // deciding the server has gone. Nothing steps the world meanwhile, and
        // it carries on from where it stood rather than leaping the gap: the
        // next step is one step, not the time spent waiting.
        if (!world.lost) world.lostSince = performance.now();
        world.retryAt = performance.now() + RETRY_MS[world.lost];
        world.lost += 1;
        world.resync = true;
        world.lastTick = 0;
        $("panel-state").textContent = `Lost the server for a moment (${why}) —`
          + ` trying again, ${world.lost} of ${RETRY_MS.length}…`;
      } else {
        // Out of reach before this, whether it ended in giving up or in the
        // server answering that the world is gone -- a restarted server has
        // lost every world it held.
        if (world.lost) recordLostLink(!!error.transient);
        const said = error.transient
          ? `lost the server (${why}), and ${RETRY_MS.length} more tries over`
            + ` ${((performance.now() - world.lostSince) / 1000).toFixed(1)} s did not reach it.`
            + ` Start the room again once it is back.`
          : why;
        $("panel-state").textContent = `The room stopped: ${said}`;
        noteError(`the room stopped: ${said}`);
        world.session = null;
      }
    }
  } finally { world.busy = false; }
}

// A draw in progress, and a loose in flight.
//
// Both are hands rather than physics. The world does not know that a string is
// being drawn: it knows a body is being hauled against whatever it is attached
// to, and what makes that a draw is that the thing has ropes and a latch.
async function watchTheDraw() {
  // Drawing: what the limbs are holding, as this step's reply said it, so the
  // number on screen is the one the engine has rather than one worked out here.
  // Said every tick: it used to be asked for four times a second, and the
  // ticks in between said "Holding ..." over the draw.
  if (world.drawn) {
    const entry = world.bodies.get(world.drawn.name);
    const back = entry
      ? entry.mesh.position.distanceTo(world.drawn.from) : 0;
    const stored = storedInElastics(world.drawn.name);
    if (stored > 0.05)
      $("panel-state").textContent =
        `Drawing ${world.drawn.name} — ${(back * 1000).toFixed(0)} mm back,`
        + ` ${stored.toFixed(1)} J in the limbs.`;
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
  // A throw's result stays up long enough to read, then the help goes.
  if (["thrown", "loosed", "notice"].includes(world.use.mode) && now > world.use.until) {
    world.use = { mode: "none" };
    showUse();
  }
  const gap = now - last;
  const dt = Math.min(0.1, gap / 1000);
  last = now;
  traceFrame(gap);
  lookFromKeys(dt);
  walk(dt);
  turnFromKeys(dt);
  updateGuides();
  fadePieces(now);
  animateHeat(now);
  animateWater(now);
  stepFoam(dt);
  workbench.advance(now);
  render();
  world.framesSinceOpen++;
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// ---------------------------------------------------------------------------
// Seeing past what is held
// ---------------------------------------------------------------------------
//
// A loose thing is held beside the view, but a big one brought in close can
// still cover the middle of it. While it does, it is DRAWN see-through. That is
// a picture and nothing else: the body in the world is the same body, where it
// was, colliding as it did, whatever it is drawn as.
const ghosts = new WeakMap();
const seeing = new THREE.Raycaster();
// The middle of the view: the crosshair and a little round it.
const MIDDLE_OF_VIEW = [[0, 0], [0.05, 0], [-0.05, 0], [0, 0.07], [0, -0.07]]
  .map(([x, y]) => new THREE.Vector2(x, y));

function heldInTheWay() {
  const held = world.held;
  if (!held || !held.loose) return null;
  const entry = world.bodies.get(held.name);
  if (!entry) return null;
  camera.updateMatrixWorld();
  entry.mesh.updateMatrixWorld();
  for (const at of MIDDLE_OF_VIEW) {
    seeing.setFromCamera(at, camera);
    if (seeing.intersectObject(entry.mesh, false).length) return entry;
  }
  return null;
}

// The same look, see-through. Kept per material, and brought up to its colour
// every frame, so a thing that glows with heat still glows through.
function ghostOf(material) {
  let ghost = ghosts.get(material);
  if (!ghost) {
    ghost = material.clone();
    ghost.transparent = true;
    ghost.opacity = 0.28;
    ghost.depthWrite = false;
    ghosts.set(material, ghost);
  }
  ghost.color.copy(material.color);
  if (material.emissive) {
    ghost.emissive.copy(material.emissive);
    ghost.emissiveIntensity = material.emissiveIntensity;
  }
  return ghost;
}

// Only for as long as the frame is being drawn.
function render() {
  const inTheWay = heldInTheWay();
  world.seeThrough = !!inTheWay;
  if (!inTheWay) { renderer.render(scene, camera); return; }
  const own = inTheWay.mesh.material;
  inTheWay.mesh.material = ghostOf(own);
  try { renderer.render(scene, camera); } finally { inTheWay.mesh.material = own; }
}

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

// Where the person is, for the chat: a model that cannot see the room has no
// other way to know what "near me" or "over there" means. Where they stand
// (the ground under their feet), where their eyes are, which way they face,
// and what the crosshair is on -- the same answers the label shows.
function whereIAm() {
  const p = camera.position;
  const f = forwardVector();
  const level = new THREE.Vector3(f.x, 0, f.z);
  if (level.lengthSq() < 1e-9) level.set(0, 0, -1);
  level.normalize();
  const r = (v) => Math.round(v * 1000) / 1000;
  const person = { standing_m: [r(p.x), r(groundAt(p.x, p.z)), r(p.z)],
                   eyes_m: [r(p.x), r(p.y), r(p.z)], facing: [r(level.x), 0, r(level.z)] };
  // What is in their hand: "this", before anything they are looking at.
  if (world.held) {
    person.holding = world.held.name;
    const entry = world.bodies.get(world.held.name);
    if (entry) person.holding_at_m = entry.mesh.position.toArray().map(r);
  }
  // What they carry, by material, as the panel's Carrying list says it.
  if (world.stock.size)
    person.carrying = [...world.stock].map(([what, have]) => ({ what, kg: r(have.kg) }));
  if (world.aim && world.aim.name) {
    person.looking_at = world.aim.name;
    if (Array.isArray(world.aim.point_m)) person.looking_at_m = world.aim.point_m.map(r);
  } else if (Array.isArray(world.groundAim)) {
    const [x, , z] = world.groundAim;
    const water = waterAt(x, z);
    person.looking_at = !ground.grid ? "the floor"
      : water && water.depth > 0.005 ? "the water" : "the ground";
    person.looking_at_m = world.groundAim.map(r);
  }
  return person;
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
  world.asking = true;
  try {
    const answer = await api("/api/world/ask", {
      session: world.session,
      message: text,
      // What the person has been doing. A model asked to change a room it
      // cannot see has to be told what has happened in it.
      story: world.story.slice(-24),
      // And where they are: what "near me" and "over there" refer to.
      person: whereIAm(),
    });
    waiting.done();
    say("world", answer.reply || "(nothing to say)", answer.did);
    if (answer.reopened) adoptRebuilt(answer);
  } catch (error) {
    waiting.done();
    say("bad", String(error.message || error));
  } finally { world.asking = false; $("ask-send").disabled = false; input.focus(); }
});

// A room rebuilt from what it has become -- after the chat changed it, or after
// one of a thing's set-ups was used -- replaces the one on screen, with nothing
// of the old one in hand.
function adoptRebuilt(answer) {
  traceOldWorld();
  world.session = answer.session;
  // A rebuilt room: its own profiles and set-ups, and nothing of the old one
  // in hand.
  rememberProfiles(answer.state && answer.state.spec);
  world.held = null;
  world.use = { mode: "none" };
  world.loosing = null;
  aimArc.hide();
  // Asked with something in hand ("turn this upright"), the new room has
  // nothing in the hand: the carry readout, the ring and the drop line go.
  $("crosshair").classList.remove("holding");
  $("carry").hidden = true;
  clearGuides();
  showUse();
  world.bodies.forEach((e) => forget(e.mesh));
  world.bodies.clear();
  world.fading.forEach((f) => forget(f.mesh));
  world.fading.length = 0;
  world.stock.clear();
  world.sweptSince.clear();
  // ...but not what the spade dug: the ground keeps its edits, and the
  // engine counts what came out of them all over again.
  carryGround(answer.state.terrain ? answer.state.terrain.carried : null);
  draw(answer.state);
  braceProfiles();
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
  // Drawn: the frame report starts over with the rebuilt world.
  traceNewWorld(answer.state.t);
  if (answer.joint_problems && answer.joint_problems.length)
    say("bad", "Some joints would not hang: " + answer.joint_problems.join("; "));
  remember("the room was rebuilt: " + (answer.did || []).join(", "));
}

// ---------------------------------------------------------------------------
// A thing's actions
// ---------------------------------------------------------------------------
//
// What the room's chat worked out a person does with a thing when it made it
// (offer_actions in the MCP): each a label and a short program -- take hold of
// a part, carry it somewhere, put it down, push it, heat it, stand it upright.
// Shown in the actions box when the crosshair is on the thing, one per number
// key. Pressing one asks the server to run the program on the room as it is:
// the hand's steps in the running room with the hand's own strength, which
// this page keeps running and draws, and a stand step as turn_object. No model
// is asked. A step that cannot be done stops the action, with why.
// What the person knows (docs/knowledge-and-progression.md): the notebook the
// server keeps from what the engine measured their own tools doing. What was
// found or shown, each claim with its scope, what is blocked and by what, and
// what the engine does not model -- apart. Nothing on this page writes to it.
// A new claim is said in the conversation as it arrives; the ones there already
// when the page opened are not said again.
function showNotebook(book, fresh) {
  if (!book || typeof book.revision !== "number" || book.revision < notebookRevision) return;
  notebookRevision = book.revision;
  const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
  const rows = [];
  for (const design of book.designs || []) {
    rows.push(["design", `${design.name}${design.registered ? "" : " (a design of its own)"}:`
      + ` ${(design.standing || []).join(", ")}`]);
    for (const e of design.evidence || []) {
      rows.push([e.claim.startsWith("demonstrated") ? "shown" : "noted",
                 `${cap(e.said)}. ${cap(e.claim)} — ${e.scope}.`]);
      if (fresh && !notebookSeen.has(e.id)) say("world", `Notebook: ${cap(e.said)}. ${cap(e.claim)}.`);
      notebookSeen.add(e.id);
    }
  }
  for (const t of book.techniques || []) rows.push(["known", `You know ${t.name}.`]);
  for (const b of book.blocked || []) {
    rows.push(["blocked", `Making ${b.name.toLowerCase()} yourself is blocked: ${b.because.join("; ")}.`]);
  }
  for (const n of book.not_modelled || []) rows.push(["noted", `Not modelled yet: ${n}.`]);
  $("notebook-list").replaceChildren(...rows.map(([kind, text]) => {
    const li = document.createElement("li");
    li.className = `nb-${kind}`;
    li.textContent = text;
    return li;
  }));
  $("notebook-empty").hidden = (book.designs || []).length > 0;
}

function actionsFor(name) {
  return (world.actions || []).filter((action) => action.body === name);
}

// What anything loose can have done to it without the room's chat having
// thought of it (the owner: "there is also things like place on ground that are
// missing"): the server's BUILTIN_ACTIONS, run the same way as the chat's.
// Offered only where the engine could do them -- a hand lifts a loose thing up
// to 73 kg, and turn_object stands a box that is not a cube -- and not twice
// when the chat already gave the thing one of the same name.
function builtinsFor(name) {
  const entry = world.bodies.get(name);
  if (!entry || entry.anchored) return [];
  const own = new Set(actionsFor(name).map((action) => action.label.toLowerCase()));
  const out = [];
  const jointed = onAJoint(name);
  if (throwable(entry, jointed)) out.push({ key: "put_on_ground", label: "Put it on the ground in front of me" });
  const d = entry.dims || [0, 0, 0];
  if (entry.shape === "box" && !jointed && !bladeFor(name) && !picks.profileOf(name)
      && Math.max(...d) - Math.min(...d) > 1e-3) {
    // How it stands now, from its turn as drawn: how much each of its sides
    // points up, and so how high it reaches above its middle. Upright is its
    // longest side vertical; lying is as low as it goes, its thinnest side up.
    const m = new THREE.Matrix4().makeRotationFromQuaternion(entry.mesh.quaternion).elements;
    const up = [m[1], m[5], m[9]];
    const high = up.reduce((sum, u, i) => sum + Math.abs(u) * d[i] / 2, 0);
    if (Math.abs(up[d.indexOf(Math.max(...d))]) < 0.99) {
      out.push({ key: "stand_upright", label: "Stand it upright" });
    }
    if (high > Math.min(...d) / 2 + 0.005) out.push({ key: "lay_down", label: "Lay it down where I'm facing" });
  }
  return out.filter((builtin) => !own.has(builtin.label.toLowerCase()));
}

// Its own actions first, then the built-in ones: one list, one number each.
function allActionsFor(name) {
  return actionsFor(name).map((action, i) => ({ label: action.label, ask: { action: i } }))
    .concat(builtinsFor(name).map((builtin) => ({ label: builtin.label, ask: { builtin: builtin.key } })));
}

async function runAction(name, index) {
  const action = allActionsFor(name)[index];
  if (!action || world.asking || world.acting) return;
  world.acting = true;
  world.menuFor = null;
  const waiting = waitingFor(`${action.label}: doing it`);
  try {
    const answer = await api("/api/world/action", { object: name, ...action.ask,
                                                     person: whereIAm() });
    waiting.done();
    const done = (answer.done || []).join(", ");
    if (answer.refused) {
      say("bad", `${action.label}: ${answer.refused}` + (done ? ` (done first: ${done})` : ""));
    } else {
      say("world", `${action.label}: ${done || "done"}.`, answer.did);
    }
    if (answer.reopened) adoptRebuilt(answer);
  } catch (error) {
    waiting.done();
    say("bad", `${action.label}: ${error.message || error}`);
  } finally { world.acting = false; }
}

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
    carryGround(answer.carried);
    say("you", `Dug ${((d.sand_m3 || 0) + (d.soil_m3 || 0)).toFixed(2)} m³ (${grams(d.kg || 0)}) at`
      + ` [${at[0].toFixed(1)}, ${at[2].toFixed(1)}]: ${(d.sand_m3 || 0).toFixed(2)} of sand,`
      + ` ${(d.soil_m3 || 0).toFixed(2)} of soil; ${d.chunks_rebuilt} collider(s) rebuilt,`
      + ` ${d.bodies_woken} thing(s) woken. Carrying ${carriedSaid()}.`);
    remember(`dug a pit at [${at[0].toFixed(1)}, ${at[2].toFixed(1)}] and carried what came out`);
  } catch (error) { say("bad", String(error.message || error)); }
});

// Heap here: the sand and soil the spade took out go back on the ground where
// the crosshair meets it -- up to 0.2 m³ at a time, about what one Dig here
// lifts, in the proportion they are carried. The engine refuses a heap bigger
// than what is carried (ground does not come from nowhere), what it heaped
// comes off the Carried list by its own numbers, and the heap settles to the
// slope it can hold.
const HEAP_M3 = 0.2;
async function heapAt(x, z, sand, soil, radius = 0.8) {
  const answer = await act("deposit", { at: [x, z], radius_m: radius, sand_m3: sand, soil_m3: soil });
  draw(answer);
  if (answer.terrain_changed) patchTerrain(answer.terrain_changed);
  if (answer.water) drawWater(answer.water);
  return answer;
}
$("heap-it").addEventListener("click", async () => {
  if (!world.session) return;
  if (!ground.grid) {
    say("world", "This room's floor is flat concrete: there is no ground to heap on. The valley has ground.");
    return;
  }
  const at = world.groundAim;
  if (!at) {
    say("world", "Point the crosshair at the ground first: the heap goes where it is.");
    return;
  }
  const have = world.carriedGround || {};
  const sand = Number(have.sand_m3) || 0;
  const soil = Number(have.soil_m3) || 0;
  if (sand + soil <= 1e-6) {
    say("world", "You are carrying no sand or soil. Dig here first: what comes out is carried.");
    return;
  }
  const share = Math.min(1, HEAP_M3 / (sand + soil));
  try {
    const answer = await heapAt(at[0], at[2], sand * share, soil * share);
    const h = answer.heaped || {};
    carryGround(answer.carried);
    say("you", `Heaped ${((h.sand_m3 || 0) + (h.soil_m3 || 0)).toFixed(2)} m³ (${grams(h.kg || 0)}) at`
      + ` [${at[0].toFixed(1)}, ${at[2].toFixed(1)}]: ${(h.sand_m3 || 0).toFixed(2)} of sand,`
      + ` ${(h.soil_m3 || 0).toFixed(2)} of soil. Carrying ${carriedSaid()}.`);
    remember(`heaped sand and soil at [${at[0].toFixed(1)}, ${at[2].toFixed(1)}]`);
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
  // What the room being replaced did since its last report, as its own.
  traceOldWorld();
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
    world.lost = 0;
    world.retryAt = 0;
    world.resync = false;
    // This room's own clock. Left at the last room's, the first frame report
    // after a reopen measured one room's seconds against the other's; the
    // report itself starts over once the room is drawn (traceNewWorld, below).
    world.clock = Number(data.t) || 0;
    world.story = [];
    world.held = null;
    world.use = { mode: "none" };
    world.loosing = null;
    rememberProfiles(data.spec);
    aimArc.hide();
    showUse();
    $("carry").hidden = true;
    world.bodies.forEach((e) => forget(e.mesh));
    world.bodies.clear();
    world.joints = [];
    draw(data);
    braceProfiles();
    // A new room: no joints said means none, as when the chat rebuilds one. Left
    // to mean "unchanged" -- which it does in a step's reply -- it left the last
    // room's pins drawn in the air over this one.
    drawJoints(data.joints || []);
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
    // What this room's ground has had dug out of it and not put back: the
    // engine's count, the room's own edits replayed. A room with no ground has
    // none to carry.
    carryGround(data.terrain ? data.terrain.carried : null);
    world.framesSinceOpen = 0;
    // Drawn and ready to step: the frame report starts here, with this world's
    // clock and the wall from now -- not from the page load, nor the last room.
    traceNewWorld(data.t);
    $("panel-state").textContent = "Live.";
    $("chat").replaceChildren();
    // The conversation so far in this room, as the server keeps it -- across a
    // reload, and across the server starting again (room_store) -- so the panel
    // beside a room the chat has built in is not blank. A turn that failed is
    // shown as the room said it then, not as a new error.
    for (const turn of data.chat || []) {
      say("you", turn.asked);
      say("world", turn.replied, turn.did);
    }
    if (data.kept) say("world", "This is the room as you left it.");
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
  aim, pickUp, dropIt, putDown, letFly, intend,
  // Turning what is held, the way U does it, and "/" -- and what the hand holds:
  // how far out, whether the wrist turns it, the wish it is asking of the wrist
  // ([x, y, z, w]), and whether it is being drawn see-through.
  standUpright, talk,
  held: () => world.held && ({
    name: world.held.name, distance: world.held.distance, loose: !!world.held.loose,
    turnable: !!world.held.turn, wish: world.held.turn ? world.held.turn.asked.toArray() : null,
    seeThrough: !!world.seeThrough }),
  // The hand as the control language sees it, and what the help says about it.
  use: () => ({ ...world.use, grip: world.use.grip && world.use.grip.toArray() }),
  help: () => ({ shown: !$("use").hidden, title: $("use-title").textContent,
                 line: $("use-line").textContent, note: $("use-note").textContent,
                 meter: $("use-meter").hidden ? null : $("use-meter-value").textContent }),
  arcShown: () => aimArc.group.visible,
  // For measuring what a frame costs: building the meshes for a shattered pane
  // is the expensive part of a break, and it cannot be seen from outside.
  buildMesh, renderer, THREE, MATERIALS,
  // What the heat drawing was last given, and what it drew from it.
  heatState: () => heat.last,
  // What heat has left of what things can carry, as the engine last said it.
  strengthState: () => heat.strength,
  // The pins and grooves drawn right now: none may be left over from a room
  // that is no longer open.
  pinsDrawn: () => pinGroup.children.length,
  // The workbench: what is on it, and where its clock is (workbench.js).
  workbench: () => workbench.state(),
  heatDrawn: () => ({ glowing: [...heat.glowing.keys()], flames: [...heat.flames.keys()],
                      columns: [...heat.columns.keys()] }),
  // The ground and the water as drawn, for checking what is on screen against
  // what the engine said -- and a spade, for driving the room from outside.
  groundAt, waterAt, digAt,
  groundDrawn: () => ground.grid && ({ ...ground.grid, water: ground.last,
                                       wetPoints: ground.raw ? ground.raw.filter(Number.isFinite).length : 0 }),
  // The river network drawn beyond the edges (docs/watershed.md): each basin's
  // and junction's sheet, at the level it was last reported standing at, and
  // each reach's ribbon at its cells' levels (null where a cell is dry).
  beyondDrawn: () => ({
    pools: (ground.beyond || []).filter((m) => m.userData.pool).map((m) => ({
      name: m.userData.pool, visible: m.visible, y: m.position.y, x: m.position.x, z: m.position.z })),
    reaches: (ground.beyond || []).filter((m) => m.userData.reach).map((m) => ({
      name: m.userData.reach, visible: m.visible, levels: m.userData.shown })),
    beds: (ground.beyond || []).filter((m) => m.userData.bedOf).length,
  }),
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
