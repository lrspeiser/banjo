/* The Explorer: build the world from scratch and walk around in it.
 *
 * This page asks the engine for a world, draws what comes back, and steps it
 * against the real clock. It talks to the same HTTP API the rest of the
 * playground uses and nothing else -- no scene is authored here, and no physics
 * is done here. What it draws is what the engine says is there.
 *
 * It draws three things, which is all the valley is:
 *   the ground   -- one mesh from the packed heightfield
 *   the water    -- one translucent sheet from the packed surface heights
 *   the things   -- a body is either a shape or, once the engine has given it
 *                   cells, one instanced cube per cell. That second case is
 *                   what makes a broken thing look broken: the engine sends
 *                   the cells that are left, and they are drawn as they are.
 */
import * as THREE from "/vendor/three.module.js";

const $ = (id) => document.getElementById(id);
const SCENE = new URLSearchParams(location.search).get("scene") || "explore";

// --------------------------------------------------------------------------
// The server
// --------------------------------------------------------------------------

let token = "";

// What the page is waiting on right now, for the visual QA to say when a call
// never comes back: the frame loop waits on its step, so a step that hangs
// stops the world while the screen goes on looking fine.
const inFlight = new Map();
let calls = 0;

/** Every POST carries the page's token; a 403 means it went stale, so it is
 *  fetched again and the call retried exactly once. */
async function api(path, body) {
  const id = ++calls;
  inFlight.set(id, { path, op: body && body.op, since: performance.now() });
  try {
    return await apiOnce(path, body);
  } finally {
    inFlight.delete(id);
  }
}

async function apiOnce(path, body) {
  for (let attempt = 0; attempt < 2; attempt++) {
    if (!token) token = (await (await fetch("/api/status")).json()).csrf_token;
    const reply = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Banjo-Token": token },
      body: JSON.stringify(body),
    });
    if (reply.status === 403 && attempt === 0) { token = ""; continue; }
    const said = await reply.json().catch(() => ({}));
    if (!reply.ok) throw new Error(said.error || `${path} answered ${reply.status}`);
    return said;
  }
  throw new Error(`${path} would not take the page's token`);
}

// --------------------------------------------------------------------------
// What is out there
// --------------------------------------------------------------------------

const world = {
  session: "", cell: 0.04, t: 0,
  // A LIST, in the order the engine sends them -- not a map by name. A body
  // has no id of its own, and names are NOT unique: every part of a joined
  // product carries the group's name, so a cart arrives as ten bodies all
  // called "cart". Keyed by name they collapsed onto each other and nine
  // tenths of every product was never drawn.
  shown: [],                  // index -> { data, mesh, sig }
  ground: null,               // { nx, nz, cell, x0, z0, h: Float32Array }
  pace: 0,
  why: new Map(),             // what hit a thing the engine is working out a break for
  handAt: null,               // where the hand is being led, eased toward the carry
  liftTo: null,               // the height a thing rises to before it moves across
};

const view = new THREE.Scene();
view.background = new THREE.Color(0x0c1418);
view.fog = new THREE.Fog(0x0c1418, 26, 74);

const camera = new THREE.PerspectiveCamera(70, 1, 0.05, 260);
const renderer = new THREE.WebGLRenderer({ canvas: $("view"), antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));

view.add(new THREE.HemisphereLight(0xdfe9ec, 0x2a2118, 1.05));
const sun = new THREE.DirectionalLight(0xfff0d8, 1.5);
sun.position.set(-8, 14, 6);
view.add(sun);

function sized() {
  // The canvas fills the window and the side panel sits on top of it. Sizing it
  // to the gap beside the panel instead drew 940 px of picture into a 1280 px
  // box and stretched it. The sight is offset by half the panel's width
  // (explore.css) so that the middle of what you can SEE is what you are
  // pointing at.
  renderer.setSize(innerWidth, innerHeight, false);
  camera.aspect = Math.max(0.2, innerWidth / innerHeight);
  camera.updateProjectionMatrix();
}
addEventListener("resize", sized);

// --------------------------------------------------------------------------
// The ground
// --------------------------------------------------------------------------

function unpackFloats(b64) {
  const raw = atob(b64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return new Float32Array(bytes.buffer);
}

function unpackShorts(b64) {
  const raw = atob(b64);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return new Uint16Array(bytes.buffer);
}

let groundMesh = null;

function drawGround(terrain) {
  const g = terrain.grid;
  const h = unpackFloats(terrain.heights_b64);
  world.ground = { nx: g.nx, nz: g.nz, cell: g.cell_m, x0: g.x0_m, z0: g.z0_m, h };

  const positions = new Float32Array(g.nx * g.nz * 3);
  for (let j = 0; j < g.nz; j++) {
    for (let i = 0; i < g.nx; i++) {
      const k = (j * g.nx + i) * 3;
      positions[k] = g.x0_m + i * g.cell_m;
      positions[k + 1] = h[j * g.nx + i];
      positions[k + 2] = g.z0_m + j * g.cell_m;
    }
  }
  const index = [];
  for (let j = 0; j < g.nz - 1; j++) {
    for (let i = 0; i < g.nx - 1; i++) {
      const a = j * g.nx + i, b = a + 1, c = a + g.nx, d = c + 1;
      index.push(a, c, b, b, c, d);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setIndex(index);
  geometry.computeVertexNormals();

  if (groundMesh) { groundMesh.geometry.dispose(); view.remove(groundMesh); }
  groundMesh = new THREE.Mesh(geometry, new THREE.MeshLambertMaterial({ color: 0xa9866a }));
  view.add(groundMesh);
}

/** The ground under a point, by the nearest sample. Walking needs it every
 *  frame and the sight needs it to know what it is pointing at. */
function groundAt(x, z) {
  const g = world.ground;
  if (!g) return 0;
  const i = Math.min(g.nx - 1, Math.max(0, Math.round((x - g.x0) / g.cell)));
  const j = Math.min(g.nz - 1, Math.max(0, Math.round((z - g.z0) / g.cell)));
  return g.h[j * g.nx + i];
}

let waterMesh = null;

function drawWater(water) {
  if (!water || !water.box || !water.surface_mm_b64) return;
  const g = world.ground;
  const [i0, j0, ni, nj] = water.box;
  const mm = unpackShorts(water.surface_mm_b64);
  const positions = new Float32Array(ni * nj * 3);
  let wet = 0;
  for (let j = 0; j < nj; j++) {
    for (let i = 0; i < ni; i++) {
      const k = (j * ni + i) * 3;
      const depth = (mm[j * ni + i] || 0) / 1000;
      if (depth > 0.004) wet++;
      positions[k] = g.x0 + (i0 + i) * g.cell;
      positions[k + 1] = water.base_m + depth;
      positions[k + 2] = g.z0 + (j0 + j) * g.cell;
    }
  }
  const index = [];
  for (let j = 0; j < nj - 1; j++) {
    for (let i = 0; i < ni - 1; i++) {
      const a = j * ni + i, b = a + 1, c = a + ni, d = c + 1;
      index.push(a, c, b, b, c, d);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setIndex(index);
  geometry.computeVertexNormals();
  if (waterMesh) { waterMesh.geometry.dispose(); view.remove(waterMesh); }
  if (!wet) { waterMesh = null; return; }
  waterMesh = new THREE.Mesh(geometry, new THREE.MeshLambertMaterial({
    color: 0x3f93b8, transparent: true, opacity: 0.66, depthWrite: false }));
  view.add(waterMesh);
}

// --------------------------------------------------------------------------
// The things in it
// --------------------------------------------------------------------------

const colourOf = (body) => {
  const hex = (body.color_rgba || "9fd3ffff").slice(0, 6);
  return new THREE.Color(`#${hex}`);
};

let cellGeometry = null;
const cellGeometryFor = (size) => {
  if (!cellGeometry || cellGeometry.userData.size !== size) {
    cellGeometry?.dispose();
    cellGeometry = new THREE.BoxGeometry(size, size, size);
    cellGeometry.userData.size = size;
  }
  return cellGeometry;
};

/** An exact body's parts as one geometry, each where and as it is: a box, or
 *  a cylinder along its own y sized {diameter, length, diameter}, turned by its
 *  own rotation. A body of more than one material colours each part as its
 *  own -- the cart's iron axles through its oak wheels. */
const PRECISE_SIDES = 28;
function preciseGeometry(body, mixed) {
  const positions = [], normals = [], colours = [];
  const matrix = new THREE.Matrix4(), turn = new THREE.Quaternion();
  const at = new THREE.Vector3(), size = new THREE.Vector3();
  const own = colourOf(body);
  for (const part of body.rigid_parts_local) {
    const round = part.shape === "cylinder";
    const shape = (round ? new THREE.CylinderGeometry(0.5, 0.5, 1, PRECISE_SIDES)
                         : new THREE.BoxGeometry(1, 1, 1)).toNonIndexed();
    const q = part.rotation_wxyz || [1, 0, 0, 0];
    turn.set(q[1], q[2], q[3], q[0]).normalize();
    matrix.compose(at.fromArray(part.center_local_m), turn, size.fromArray(part.dimensions_m));
    shape.applyMatrix4(matrix);
    for (const v of shape.attributes.position.array) positions.push(v);
    for (const v of shape.attributes.normal.array) normals.push(v);
    if (mixed) {
      const stuff = part.material || body.material;
      const c = stuff === body.material ? own : new THREE.Color(SWATCH_OF(stuff));
      for (let k = 0; k < shape.attributes.position.count; k++) colours.push(c.r, c.g, c.b);
    }
    shape.dispose();
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute("normal", new THREE.Float32BufferAttribute(normals, 3));
  if (mixed) geometry.setAttribute("color", new THREE.Float32BufferAttribute(colours, 3));
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  return geometry;
}

/** A body's mesh. Cells win over shape: once the engine sends `cells_local_m`
 *  that IS the thing -- every piece a break left, every cell a dent moved --
 *  and drawing the original box instead would be drawing something that is no
 *  longer there. An exact rigid body is its parts; it has no cells. */
function buildMesh(body) {
  const parts = body.mechanical_model === "precise-rigid-v1" ? body.rigid_parts_local : null;
  if (Array.isArray(parts) && parts.length) {
    const mixed = new Set(parts.map((part) => part.material || body.material)).size > 1;
    const look = mixed ? { vertexColors: true } : { color: colourOf(body) };
    return new THREE.Mesh(preciseGeometry(body, mixed), new THREE.MeshLambertMaterial(look));
  }
  const material = new THREE.MeshLambertMaterial({ color: colourOf(body) });
  const cells = body.cells_local_m;
  if (cells && cells.length) {
    const mesh = new THREE.InstancedMesh(cellGeometryFor(world.cell), material, cells.length);
    const at = new THREE.Matrix4();
    for (let i = 0; i < cells.length; i++) {
      at.makeTranslation(cells[i][0], cells[i][1], cells[i][2]);
      mesh.setMatrixAt(i, at);
    }
    mesh.instanceMatrix.needsUpdate = true;
    return mesh;
  }
  const [dx, dy, dz] = body.dimensions_m || [0.2, 0.2, 0.2];
  const geometry = body.shape === "sphere"
    ? new THREE.SphereGeometry(dx / 2, 20, 14)
    : new THREE.BoxGeometry(dx, dy, dz);
  return new THREE.Mesh(geometry, material);
}

function place(mesh, body) {
  mesh.position.set(...body.position_m);
  const q = body.orientation_wxyz;
  if (q && q.length === 4) mesh.quaternion.set(q[1], q[2], q[3], q[0]);
}

function dispose(mesh) {
  if (!mesh.isInstancedMesh) mesh.geometry.dispose();
  mesh.material.dispose();
}

/** What would make this body need a new mesh rather than a new pose: what it
 *  is, how it is built, and how much of it is left. */
const signatureOf = (body) =>
  [body.name, body.shape, body.revision, (body.cells_local_m || []).length,
   (body.rigid_parts_local || []).length, (body.dimensions_m || []).join(",")].join("|");

/** Take what the engine last said.
 *
 *  Matched up by POSITION in the reply, because that is the only stable handle
 *  a body has: there is no id, and ten of them can share a name. The page
 *  therefore always asks for a whole reply -- a partial one carries only what
 *  moved, and there is no way to say which "cart" that was.
 */
function draw(state) {
  const list = state.bodies || [];
  if (state.partial) return;      // not asked for; see above
  for (let i = 0; i < list.length; i++) {
    const body = list[i];
    const slot = world.shown[i];
    // The open reply carries a lattice body's cells; step replies do not, and
    // a break sends the new ones. Without carrying the last ones forward, the
    // first step changed every product's signature and rebuilt it from
    // dimensions_m -- its bounding box -- so the table and the bench were
    // drawn as solid slabs, and a table in your hands filled the view.
    if (!body.cells_local_m && slot && slot.data.cells_local_m
        && slot.data.name === body.name && slot.data.revision === body.revision) {
      body.cells_local_m = slot.data.cells_local_m;
    }
    const sig = signatureOf(body);
    if (!slot || slot.sig !== sig) {
      if (slot) { view.remove(slot.mesh); dispose(slot.mesh); }
      const mesh = buildMesh(body);
      place(mesh, body);
      view.add(mesh);
      world.shown[i] = { data: body, mesh, sig };
    } else {
      slot.data = body;
      place(slot.mesh, body);
    }
  }
  for (let i = list.length; i < world.shown.length; i++) {
    view.remove(world.shown[i].mesh);
    dispose(world.shown[i].mesh);
  }
  world.shown.length = list.length;
  const was = me.holding;
  me.holding = heldInTheWorld();
  noteHeld();
  if (me.holding !== was) showHands();
  // See-through while it is in your hands: a table carried in front of you
  // hides the ground you are about to put it on, and the preview with it.
  for (const slot of world.shown) seeThrough(slot, me.heldSet.has(slot.data.name));
}

function seeThrough(slot, on) {
  if (!!slot.clear === on) return;
  slot.clear = on;
  const m = slot.mesh.material;
  m.transparent = on;
  m.opacity = on ? 0.38 : 1;
  m.depthWrite = !on;
  m.needsUpdate = true;
}

// --------------------------------------------------------------------------
// Walking and looking
// --------------------------------------------------------------------------

const EYE = 1.62;
const REACH = 0.6;          // how far out a small thing is carried; more for a big one

/** Where the hand is, in the world. Sent with every step: the engine carries a
 *  held body to the hand, and a hand that is never told where it is never
 *  moves -- which is why a picked-up table went on lying on the ground. */
function handPoint() {
  // Low and to the right of where you look, the way a thing is carried to see
  // past it. Carried in the middle of the view -- where it was -- it sat right
  // on top of the preview of where it would go, so you could not see where you
  // were putting it. Further out and lower the bigger it is, so a bench stays
  // at the edge of the view instead of blotting out the valley.
  const size = heldSize();
  // How much bigger than a block it is: a bench goes to your side and low, a
  // block to the lower right of the view.
  const big = Math.max(0, size - 0.5);
  const yaw = person.yaw - (0.2 + big * 0.25);
  const pitch = Math.min(-0.3, person.pitch - 0.45 - big * 0.3);
  const reach = REACH + size * 0.6;
  const eye = groundAt(person.x, person.z) + EYE;
  const x = person.x - Math.sin(yaw) * Math.cos(pitch) * reach;
  const z = person.z - Math.cos(yaw) * Math.cos(pitch) * reach;
  const y = eye + Math.sin(pitch) * reach;
  return [x, Math.max(y, groundAt(x, z) + size / 2 + 0.05), z];
}

/** Where the hand is led this frame: toward the carry point, no faster than a
 *  person moves a thing, and UP before ACROSS. The carry point jumps -- on
 *  taking something up, and whenever you turn -- and led straight there by an
 *  800 N hand, a block whipped across at several metres a second, clipped the
 *  ceramic block beside it, and the engine stopped the world to work out
 *  whether it had broken. */
const HAND_SPEED = 2.0;       // m/s

function leadHand(dt) {
  const want = handPoint();
  if (!world.handAt) {
    const held = world.shown.find((s) => s.data.name === me.holding);
    world.handAt = held ? held.data.position_m.slice() : want.slice();
    world.liftTo = world.handAt[1] + heldSize() * 0.5 + 0.25;
  }
  const at = world.handAt;
  const across = Math.hypot(want[0] - at[0], want[2] - at[2]);
  const goal = at[1] < world.liftTo - 0.02 && across > 0.15 ? [at[0], world.liftTo, at[2]] : want;
  const d = [goal[0] - at[0], goal[1] - at[1], goal[2] - at[2]];
  const length = Math.hypot(d[0], d[1], d[2]);
  // Slower the heavier it is. Most of the hand's 800 N goes on holding a 63 kg
  // iron block up, and what is left cannot brake it: led at 2 m/s it sailed a
  // metre past the hand and over the person's head.
  const mass = heldMass();
  const pace = HAND_SPEED * Math.min(1, Math.max(0.25, 25 / Math.max(mass, 1)));
  const k = length > pace * dt ? (pace * dt) / length : 1;
  world.handAt = [at[0] + d[0] * k, at[1] + d[1] * k, at[2] + d[2] * k];
  return world.handAt;
}

/** What hit it, how hard, and what came of it -- the engine's answer to a
 *  break it was asked to work out. */
function tellWhatBroke(state) {
  const name = state.finished;
  const hit = world.why.get(name);
  world.why.delete(name);
  const how = hit
    ? `The ${hit.by || "ground"} hit the ${name} at ${hit.closing_speed_m_s.toFixed(1)} m/s`
    : `The ${name} was struck`;
  if (state.outcome === "broke") say(`${how}. It broke into ${state.pieces} pieces.`);
  else if (state.outcome === "dented") say(`${how}. It bent out of shape.`);
  else say(`${how}, and it held.`);
}

/** The longest side of what is in your hand, over all its pieces, in metres. */
function heldSize() {
  const parts = world.shown.filter((s) => me.heldSet.has(s.data.name)).map((s) => s.data);
  if (!parts.length) return 0.3;
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (const part of parts) {
    const r = Math.max(...(part.dimensions_m || [0.3, 0.3, 0.3])) / 2;
    for (let k = 0; k < 3; k++) {
      lo[k] = Math.min(lo[k], part.position_m[k] - r);
      hi[k] = Math.max(hi[k], part.position_m[k] + r);
    }
  }
  return Math.max(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]);
}
// `back` pulls the camera away along its own line of sight. It is a zoom out,
// not an orbit: the eye stays where the person is, so the ray through the
// sight is the SAME line however far back the camera sits and aiming does not
// change as you zoom.
const person = { x: 0, z: -9, yaw: 0, pitch: -0.06, back: 0, came: null };
const pressed = new Set();

addEventListener("keydown", (e) => {
  if (e.code === "KeyR" && person.came) Object.assign(person, person.came, { came: person.came, back: 0 });
  pressed.add(e.code);
  if (e.code.startsWith("Arrow")) $("hint")?.remove();
  if (e.code === "KeyE") takeOrPutDown();
  if (e.code === "KeyJ") usePrimary().catch((t) => say(String(t.message).slice(0, 120), { refused: true }));
  if (e.code === "KeyQ") intoTheBag();
  if (e.code === "KeyG") sweepUp();
  if (e.code === "KeyX") letGo();
  if (["KeyW", "KeyA", "KeyS", "KeyD", "ArrowUp", "ArrowDown",
       "ArrowLeft", "ArrowRight"].includes(e.code)) e.preventDefault();
});
addEventListener("keyup", (e) => pressed.delete(e.code));
// Two ways to look, because one of them always turns out not to work for
// somebody: DRAG the view with the mouse down, or click once to capture the
// mouse and just move it (Esc gives it back). Pointer lock alone is a bad
// first move -- nothing on screen says the click did anything, and a browser
// can refuse it outright.
let dragging = false;
let turnedSince = 0;
const turn = (dx, dy) => {
  turnedSince += Math.abs(dx) + Math.abs(dy);
  person.yaw -= dx * 0.0025;
  person.pitch = Math.max(-1.45, Math.min(1.45, person.pitch - dy * 0.0025));
  $("hint")?.remove();
};
$("view").addEventListener("pointerdown", (e) => {
  dragging = true;
  $("view").setPointerCapture(e.pointerId);
});
$("view").addEventListener("pointerdown", (e) => { turnedSince = 0; });
$("view").addEventListener("pointerup", (e) => {
  dragging = false;
  $("view").releasePointerCapture(e.pointerId);
  // A click that did not turn the view is a use of what is in front of you;
  // one that did was you looking around, and must not also press something.
  if (turnedSince < 4) usePrimary().catch((t) => say(String(t.message).slice(0, 120), { refused: true }));
});
$("view").addEventListener("dblclick", () => {
  // Not every page is allowed to take the mouse: inside an embedded frame the
  // browser refuses with "The root document of this element is not valid for
  // pointer lock", and an unhandled refusal fills the console on every attempt.
  // Dragging works everywhere, so a refusal here costs nothing.
  try { $("view").requestPointerLock()?.catch?.(() => {}); } catch { /* drag instead */ }
});
// The wheel pulls back and pushes in. Standing in your own eyes you cannot see
// where a thing you are carrying would land -- the ground a metre in front of
// your feet is below the bottom of the screen -- so you need to be able to
// step back from yourself and look.
addEventListener("wheel", (e) => {
  if (e.target !== $("view")) return;      // let the side panel scroll
  e.preventDefault();
  person.back = Math.max(0, Math.min(8, person.back + e.deltaY * 0.0022));
  $("hint")?.remove();
}, { passive: false });

addEventListener("mousemove", (e) => {
  const locked = document.pointerLockElement === $("view");
  if (!locked && !dragging) return;
  turn(e.movementX, e.movementY);
});

function walk(dt) {
  const fast = pressed.has("ShiftLeft") || pressed.has("ShiftRight") ? 2.4 : 1.0;
  const step = 3.1 * fast * dt;
  let ahead = 0, side = 0;
  if (pressed.has("KeyW")) ahead += 1;
  if (pressed.has("KeyS")) ahead -= 1;
  if (pressed.has("KeyD")) side += 1;
  if (pressed.has("KeyA")) side -= 1;
  if (ahead || side) {
    const length = Math.hypot(ahead, side);
    const sin = Math.sin(person.yaw), cos = Math.cos(person.yaw);
    person.x += ((-sin * ahead) + (cos * side)) / length * step;
    person.z += ((-cos * ahead) - (sin * side)) / length * step;
  }
  // Turning on the arrows as well as by dragging. Not everyone wants to hold a
  // mouse button down to look round, and a trackpad drag runs out of desk.
  const TURN = 1.9;              // radians a second, about a half-turn in a second
  if (pressed.has("ArrowLeft")) person.yaw += TURN * dt;
  if (pressed.has("ArrowRight")) person.yaw -= TURN * dt;
  if (pressed.has("ArrowUp")) person.pitch += TURN * 0.55 * dt;
  if (pressed.has("ArrowDown")) person.pitch -= TURN * 0.55 * dt;
  person.pitch = Math.max(-1.45, Math.min(1.45, person.pitch));

  const g = world.ground;
  if (g) {
    person.x = Math.min(g.x0 + (g.nx - 1) * g.cell, Math.max(g.x0, person.x));
    person.z = Math.min(g.z0 + (g.nz - 1) * g.cell, Math.max(g.z0, person.z));
  }
  camera.rotation.set(person.pitch, person.yaw, 0, "YXZ");
  const eyeY = groundAt(person.x, person.z) + EYE;
  if (person.back < 0.01) {
    camera.position.set(person.x, eyeY, person.z);
  } else {
    // Straight back along the line of sight, and never into the hill behind
    // you: a camera under the ground sees the inside of it and nothing else.
    const back = new THREE.Vector3(0, 0, 1).applyQuaternion(camera.quaternion)
      .multiplyScalar(person.back);
    const at = new THREE.Vector3(person.x + back.x, eyeY + back.y, person.z + back.z);
    at.y = Math.max(at.y, groundAt(at.x, at.z) + 0.35);
    camera.position.copy(at);
  }
}

// --------------------------------------------------------------------------
// What is in front of you
// --------------------------------------------------------------------------

const ray = new THREE.Raycaster();
ray.far = 26;
let looked = "";

/** Where the sight actually is, in the camera's own coordinates.
 *
 *  The canvas fills the window and the side panel sits over its right-hand
 *  edge, so the middle of what you can SEE is left of the middle of what is
 *  DRAWN. The sight is moved there in explore.css; casting the ray from the
 *  camera's centre instead pointed it to the right of the sight, and you took
 *  hold of whatever was beside the thing you were aiming at. */
function sightInView() {
  const side = parseFloat(getComputedStyle(document.documentElement)
    .getPropertyValue("--side-w")) || 0;
  return new THREE.Vector2(-side / Math.max(1, innerWidth), 0);
}

function lookedAt() {
  ray.setFromCamera(sightInView(), camera);
  // Past what is in your own hand -- all of it: that is never what you are
  // looking AT.
  const hit = ray.intersectObjects(
    world.shown.filter((s) => !me.heldSet.has(s.data.name)).map((s) => s.mesh), false)[0];
  if (!hit) return null;
  const slot = world.shown.find((s) => s.mesh === hit.object);
  return slot ? { name: slot.data.name, known: slot, hit } : null;
}

const KG = (n) => (n >= 1 ? `${n.toFixed(n < 10 ? 2 : 1)} kg` : `${Math.round(n * 1000)} g`);

/** What J does to a thing, in its maker's words: the primary action of any of
 *  these parts ("Swing it", "Look at it"), lower-cased to sit in the line. */
function useOf(parts) {
  const own = (world.actions || []).filter((a) => parts.includes(a.body));
  const use = own.find((a) => a.primary) || own[0];
  if (!use || !use.label) return "use it";
  return use.label.charAt(0).toLowerCase() + use.label.slice(1);
}

/** The one line under the sight: what E does here, and what J does. */
function showWhatYouCanDo(found) {
  const can = [];
  if (me.holding) {
    can.push(["E", me.canPlace ? `put the ${heldName()} down there`
                               : `set the ${heldName()} on the ground`]);
    // What it is for, held: a mace's J swings it.
    can.push(["J", useOf([...me.heldSet])]);
    can.push(["Q", "into the bag"]);
    can.push(["X", "just let go"]);
  } else if (found) {
    can.push(["E", `take the ${found.name}`]);
    can.push(["J", useOf([found.name])]);
  }
  const box = $("can-do");
  box.replaceChildren(...can.flatMap(([key, what], i) => {
    const kbd = document.createElement("kbd");
    kbd.textContent = key;
    const said = document.createElement("span");
    said.textContent = what;
    return i ? [document.createTextNode(" · "), kbd, said] : [kbd, said];
  }));
  box.hidden = !can.length;
}

function showLookedAt() {
  const found = lookedAt();
  showWhatYouCanDo(found);
  if (!found) {
    if (looked !== "") { looked = ""; $("looking").hidden = true; $("seen-name").textContent = "—";
                         $("seen-facts").replaceChildren(); $("seen-hint").textContent =
                           "Point at something. Everything here is real matter: the engine knows what it is made of, what it weighs and what it takes to break it."; }
    return;
  }
  const body = found.known.data;
  $("looking").hidden = false;
  $("looking").textContent = body.name;
  if (looked === found.name) return;
  looked = found.name;

  $("seen-name").textContent = body.name;
  const facts = [
    ["made of", body.material || "—", true],
    ["it weighs", body.mass_kg ? KG(body.mass_kg) : "—", true],
    ["how big", (body.dimensions_m || []).map((v) => `${Math.round(v * 1000)}`).join(" × ") + " mm", false],
    ["how far off", `${found.hit.distance.toFixed(1)} m`, false],
  ];
  const cells = (body.cells_local_m || []).length;
  if (cells) facts.push(["built from", `${cells.toLocaleString()} cells of ${Math.round(world.cell * 1000)} mm`, false]);
  if (body.dent_mm > 0.05) facts.push(["dented", `${body.dent_mm.toFixed(1)} mm`, true]);
  const speed = Math.hypot(...(body.velocity_m_s || [0, 0, 0]));
  if (speed > 0.02) facts.push(["moving", `${speed.toFixed(2)} m/s`, true]);
  if (body.anchored) facts.push(["held down", "does not move", false]);

  $("seen-facts").replaceChildren(...facts.flatMap(([term, said, strong]) => {
    const dt = document.createElement("dt"); dt.textContent = term;
    const dd = document.createElement("dd"); dd.textContent = said;
    if (strong) dd.className = "strong";
    return [dt, dd];
  }));
  const law = MATTER.get(body.material);
  $("seen-hint").textContent = law
    ? (law.brittle
        ? `${body.material} is brittle: it does not bend first, it goes.`
        : `${body.material} bends before it breaks.`)
    : "";
}

// --------------------------------------------------------------------------
// The person, and what they have hold of
//
// Everything below goes through routes that already exist and are already
// tested: /api/world/inventory for the hands and the bag, /api/world/action
// for a thing's one use, /api/world/placement for where it would go. The page
// decides nothing about what is allowed -- it asks, and says what it was told.
// --------------------------------------------------------------------------

const me = { holding: null, record: null, recordParts: null, heldSet: new Set(),
             bagItems: [], carried: {}, revision: 0, busy: false, said: "" };

/** Every part of what is in your hand. The engine's hand grips ONE part
 *  (me.holding, the world's word for it); a thing of several parts -- a mace
 *  and the head on its chain -- comes with it on its own joints, and the record
 *  says which parts those are. So "held" is the whole thing: see-through, never
 *  what the sight lands on, and weighed and sized as all of it. */
function noteHeld() {
  const whole = me.holding && me.recordParts && me.recordParts.includes(me.holding);
  me.heldSet = new Set(me.holding ? (whole ? me.recordParts : [me.holding]) : []);
}

/** What all of what is in your hand weighs: a cart is its chassis and both
 *  its wheelsets, 43 kg, not the 21 kg the hand grips. */
function heldMass() {
  return world.shown.filter((s) => me.heldSet.has(s.data.name))
    .reduce((m, s) => m + (s.data.mass_kg || 0), 0);
}

/** What to call what is in your hand: the thing, not the part the hand grips. */
function heldName() {
  return me.record && me.heldSet.has(me.record) ? me.record : me.holding;
}

/** Where the sight lands: the nearer of the ground and the things in the
 *  world -- never the one in your hand, which would be the first thing hit --
 *  along the ray through the sight, and within reach. Null on the sky. */
function aimPoint(within = 4.5) {
  ray.setFromCamera(sightInView(), camera);
  const o = ray.ray.origin.clone(), d = ray.ray.direction.clone();
  const past = person.back;          // the camera may sit back along this line
  let best = null;
  const meshes = world.shown.filter((s) => !me.heldSet.has(s.data.name)).map((s) => s.mesh);
  const hit = ray.intersectObjects(meshes, false)[0];
  if (hit && hit.distance <= within + past) best = hit.distance;
  // The ground: march the same ray over the heightfield, then halve onto it.
  const below = (s) => o.y + d.y * s <= groundAt(o.x + d.x * s, o.z + d.z * s);
  for (let s = past + 0.05; s <= within + past && (best === null || s < best); s += 0.03) {
    if (!below(s)) continue;
    let lo = s - 0.03, hi = s;
    for (let k = 0; k < 10; k++) { const mid = (lo + hi) / 2; if (below(mid)) hi = mid; else lo = mid; }
    best = best === null ? hi : Math.min(best, hi);
    break;
  }
  return best === null ? null : [o.x + d.x * best, o.y + d.y * best, o.z + d.z * best];
}

/** Where the person is, in the words every world route asks for. */
function whereIAm() {
  // Which way the SIGHT points, not the middle of the canvas. The sight sits
  // left of the middle (the side panel covers the right), and "in front of
  // you" is where you are aiming.
  ray.setFromCamera(sightInView(), camera);
  const along = ray.ray.direction.clone();
  const level = Math.hypot(along.x, along.z) || 1;
  const found = lookedAt();
  const feet = groundAt(person.x, person.z);
  const said = {
    standing_m: [person.x, feet, person.z],
    facing: [along.x / level, 0, along.z / level],
    // The person's eyes, not the camera's: stepped back with the wheel, the
    // camera is metres behind them, and everything was then out of reach.
    eyes_m: [person.x, feet + EYE, person.z],
    look_direction: [along.x, along.y, along.z],
  };
  const aim = aimPoint();
  if (aim) said.aim_m = aim;
  if (me.holding) said.holding = me.holding;
  if (found) said.looking_at = found.name;
  return said;
}

const newRequest = () => `explore-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;

/** What the engine says is actually in the hand.
 *
 *  THE ENGINE IS THE AUTHORITY HERE, not the inventory record. The two can
 *  disagree: after a `place` the engine lets go but the record goes on listing
 *  the thing in the hand (server.run_action never tells the inventory), and a
 *  room saved in that state opens with the page believing you are carrying
 *  something you are not -- which showed the ghost before you had touched
 *  anything and sent E down the "put it down" branch so nothing could be
 *  picked up. What the page draws is what is physically true. */
function heldInTheWorld() {
  const slot = world.shown.find((s) => s.data.held);
  return slot ? slot.data.name : null;
}

function tookNote(said) {
  if (!said) return;
  // The revision lives on the RECORD, not at the top of the reply. Reading the
  // wrong one left it stale, and the next change was refused with "the
  // inventory changed since you last saw it" -- the optimistic-concurrency
  // guard doing its job against a page that was not keeping up.
  const revision = said.record?.revision ?? said.revision;
  if (typeof revision === "number") me.revision = revision;
  const shown = said.shown || said;
  const hands = shown.hands || {};
  const right = hands.right || hands.left || null;
  me.record = right ? (right.name || right.item || right.id || null) : null;
  // Every part of it, when it is a thing of several (inventory_room.shown).
  me.recordParts = right && Array.isArray(right.parts) ? right.parts : null;
  noteHeld();
  me.bagItems = (shown.stowed || []).map((b) => ({
    name: b.name || b.item || b.id || "?", material: b.material || "" }));
  me.carried = shown.carried || me.carried;
  showHands();
}

/** E: the one contextual thing. Empty-handed and pointing at something loose,
 *  take it up; holding something, put it down where the ghost says. */
async function takeOrPutDown() {
  if (!world.session) {
    say("The world is not running here any more. Reload the page to start again.",
        { refused: true, stays: true });
    return;
  }
  if (me.busy) { say("Still doing the last thing…"); return; }
  me.busy = true;
  try {
    const found = lookedAt();
    if (me.holding) {
      // Its own verb, NOT the thing's Use. A cart's use is "push it forward",
      // which wants the free hand you are holding the cart with, so putting a
      // cart down asked you to put the cart down first. /api/world/putdown
      // places anything where the ghost says, whatever it is for.
      const going = me.holding;
      // Said the moment E is pressed: the hand takes a moment to get there,
      // and a key that shows nothing for that moment reads as a key that did
      // nothing.
      say(`Putting the ${going} down…`);
      const said = await api("/api/world/putdown", {
        session: world.session, object: going, person: whereIAm(),
      });
      await refreshHands();
      if (said.ok) {
        const notes = [said.instead && `it would not go where the preview was: ${said.instead}`,
                       said.record].filter(Boolean);
        say(notes.length ? `${said.did} -- ${notes.join("; ")}` : (said.did || `Put the ${going} down.`));
      } else {
        say(`${said.why} · X lets go of it where you stand.`, { refused: true });
      }
    } else {
      if (!found) { say("Nothing in front of you to pick up.", { refused: true }); return; }
      if (found.known.data.anchored) { say(`${found.name} is fixed down.`, { refused: true }); return; }
      // Every /api/world/* call carries the session: the playground runs one
      // room at a time, and a page whose room was reopened elsewhere must not
      // go on moving things about in somebody else's (server._this_pages_room).
      const said = await api("/api/world/inventory", {
        session: world.session, request: newRequest(), revision: me.revision,
        op: "take_up", item: found.name, person: whereIAm(),
      });
      tookNote(said);
      // What the CALL just said, not what the world has caught up to: the hand
      // is read off the engine, which only reports the thing as held on its
      // next step, so asking me.holding here always answered "no".
      if (me.record) say(`You have the ${me.record}.`);
      else say(said.why || said.refused || "It would not come up.", { refused: true });
    }
  } catch (trouble) {
    say(String(trouble.message).slice(0, 120), { refused: true });
  } finally {
    me.busy = false;
  }
}

/** J or the left button: the one thing this object is for. */
async function usePrimary() {
  if (!world.session) return;
  const target = me.holding || lookedAt()?.name;
  if (!target) { say("Point at something, or pick something up.", { refused: true }); return; }
  // Held through the whole call: a Use runs the engine's own hand, and the
  // step loop must leave that hand alone while it does (see the step call).
  const was = me.busy;
  me.busy = true;
  let said;
  try {
    said = await api("/api/world/action", {
      session: world.session, object: target, primary: true, person: whereIAm(),
    });
  } finally {
    me.busy = was;
  }
  // A refusal first and in its own words: it is the most useful thing the
  // engine ever says, and burying it under a label reads as success.
  if (said.refused) say(`${said.action || "That"}: ${said.refused}`, { refused: true });
  else say(said.said || said.did || said.why || said.action || "Done.");
  if (said.inventory || said.shown) tookNote(said.inventory || said);
  else if (me.holding) await refreshHands();
}

async function refreshHands() {
  try { tookNote(await api("/api/world/inventory/shown", { session: world.session })); }
  catch { /* the hands are only a readout */ }
}

let saidFades = 0;

function say(words, { refused = false, stays = false } = {}) {
  me.said = words;
  $("did").textContent = words;
  $("did").hidden = !words;
  // And over the world, by the sight. The side panel is not where anyone is
  // looking when they press a key, so a refusal put only there reads as the
  // key having done nothing at all.
  //
  // Whether it WAS a refusal is said by whoever calls: reading it out of the
  // wording guessed, and guessed wrong -- "put down what you are holding
  // first" came up in plain white as though it had worked.
  const loud = $("said-loud");
  loud.textContent = words;
  loud.hidden = !words;
  loud.classList.toggle("refused", !!refused);
  clearTimeout(saidFades);
  if (!stays) saidFades = setTimeout(() => { loud.hidden = true; }, 4200);
}

function showHands() {
  const slot = me.holding ? world.shown.find((s) => s.data.name === me.holding) : null;
  const body = slot ? slot.data : null;
  // All of it: the part the hand grips and whatever hangs on it.
  const parts = world.shown.filter((s) => me.heldSet.has(s.data.name)).map((s) => s.data);
  $("hands-held").textContent = heldName() || "nothing";
  showInHand(parts);
  const kg = parts.reduce((m, p) => m + (p.mass_kg || 0), 0);
  $("hands-held-facts").textContent = body
    ? [body.material, kg ? KG(kg) : null,
       parts.length > 1 ? `${parts.length} parts, joined`
                        : (body.dimensions_m || []).map((v) => Math.round(v * 1000)).join(" × ") + " mm"]
        .filter(Boolean).join(" · ")
    : "";
  $("to-bag").disabled = !me.holding;
  const kind = workshopKindOf(me.holding);
  const link = $("to-workshop");
  link.hidden = !kind;
  if (kind) { link.href = `/world?workshop=1&kind=${encodeURIComponent(kind)}`; link.textContent = `Open the ${kind} in the Workshop`; }
  showCarrying();
  // Say so when the record and the world disagree, rather than picking one
  // quietly: it is a real fault and hiding it is how it stays unfixed. The hand
  // gripping one part of a thing the record lists whole is not a disagreement.
  const split = me.record && !me.heldSet.has(me.record);
  $("hands-note").hidden = !split;
  if (split) $("hands-note").textContent =
    `The record still lists the ${me.record}; the world says it is not held.`;
}

// --------------------------------------------------------------------------
// The ghost: where it would go if you let go now
// --------------------------------------------------------------------------

let ghost = null;
let ghostAsked = 0;

function showGhost(answer, body) {
  me.canPlace = !!(answer && answer.fits);
  if (!answer || !answer.on) { hideGhost(); return; }
  const [dx, dy, dz] = body.dimensions_m || [0.3, 0.3, 0.3];
  if (!ghost) {
    ghost = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1),
      new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.34, depthWrite: false }));
    view.add(ghost);
  }
  ghost.visible = true;
  ghost.scale.set(dx, dy, dz);
  // A thing of several parts held in place on each other goes down as one
  // shape (placement.resolve): every part where it will stand, the gripped one
  // among them -- a chair's seat up on its legs, not flat on the ground.
  const parts = Array.isArray(answer.parts) && answer.parts.length > 1 ? answer.parts : null;
  if (parts) {
    const [w, x, y, z] = parts[0].facing;
    ghost.position.set(...parts[0].at_m);
    ghost.quaternion.set(x, y, z, w);
  } else if (answer.facing && answer.at_m) {
    // Square to the ground under it, as the engine will set it down
    // (LiveWorld::placement): its box standing on the middle of its underside,
    // which is straight down its own up from its centre of mass by as much as
    // the engine put that over the point.
    const [w, x, y, z] = answer.facing;
    ghost.quaternion.set(x, y, z, w);
    const up = new THREE.Vector3(0, 1, 0).applyQuaternion(ghost.quaternion);
    const at = new THREE.Vector3(...answer.at_m);
    const height = at.clone().sub(new THREE.Vector3(...answer.on)).dot(up);
    ghost.position.copy(at.addScaledVector(up, dy / 2 - height));
  } else {
    ghost.position.set(answer.on[0], answer.on[1] + dy / 2, answer.on[2]);
    ghost.rotation.set(0, (answer.yaw_deg || 0) * Math.PI / 180, 0);
  }
  // Green it fits, amber it is held up by too few corners or is tall for the
  // slope it would stand on, red it does not.
  const corners = answer.supported_corners;
  ghost.material.color.set(!answer.fits ? 0xff9f91
    : ((typeof corners === "number" && corners < 4) || answer.may_fall_over ? 0xffd195 : 0xa2e1c8));
  showGhostParts(parts ? parts.slice(1) : [], ghost.material);
  $("ghost-said").textContent = answer.why || answer.label || "";
  $("ghost-said").hidden = false;
}

/** The rest of a thing of several parts, around the gripped one's ghost. */
let ghostRest = null;

function showGhostParts(rest, material) {
  if (!ghostRest) { ghostRest = new THREE.Group(); view.add(ghostRest); }
  while (ghostRest.children.length > rest.length) {
    const gone = ghostRest.children[ghostRest.children.length - 1];
    ghostRest.remove(gone);
    gone.geometry.dispose();
  }
  while (ghostRest.children.length < rest.length) {
    ghostRest.add(new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), material));
  }
  rest.forEach((part, i) => {
    const mesh = ghostRest.children[i];
    const [dx, dy, dz] = part.dimensions_m || [0.1, 0.1, 0.1];
    const [w, x, y, z] = part.facing;
    mesh.material = material;
    mesh.scale.set(dx, dy, dz);
    mesh.position.set(...part.at_m);
    mesh.quaternion.set(x, y, z, w);
  });
  ghostRest.visible = rest.length > 0;
}

function hideGhost() {
  me.canPlace = false;
  if (ghost) ghost.visible = false;
  if (ghostRest) ghostRest.visible = false;
  $("ghost-said").hidden = true;
}

/** Asked a few times a second while something is held, never faster: it is a
 *  round trip to the engine, which does a real ray and a real clearance test. */
async function askWhereItWouldGo() {
  if (!me.holding || !world.session) { hideGhost(); return; }
  const now = performance.now();
  if (now - ghostAsked < 180) return;
  ghostAsked = now;
  const slot = world.shown.find((s) => s.data.name === me.holding);
  const person = whereIAm();
  try {
    const answer = await api("/api/world/placement", {
      session: world.session, name: me.holding, person,
    });
    // What the engine made of the spot, for the visual QA: a preview that
    // never appears says nothing on screen about why.
    world.lastPlacement = { fits: !!answer.fits, why: answer.why || null, on: answer.on || null,
                            aim: person.aim_m || null };
    showGhost(answer, slot ? slot.data : {});
    // Nowhere here -- on top of a loose block, say: no box to draw, but the
    // reason is still said, by the sight. Said nothing, the screen looked the
    // same as a page that had stopped answering, and E there went on to set
    // the thing somewhere else without the person ever seeing why.
    if (!answer.on && answer.why) {
      $("ghost-said").textContent = `Nowhere to put it here: ${answer.why}`;
      $("ghost-said").hidden = false;
    }
  } catch (trouble) {
    world.lastPlacement = { error: String(trouble.message).slice(0, 200), aim: person.aim_m || null };
    hideGhost();
  }
}

// --------------------------------------------------------------------------
// The catalogue, and what is in the valley
// --------------------------------------------------------------------------

const MATTER = new Map();
const SWATCH = { oak: "#c9a06a", iron: "#8a8f99", glass: "#a9d8e8", concrete: "#9aa0a4",
                 ceramic: "#e4ded2", ice: "#bfe6f2", aluminum: "#c6ccd2", rubber: "#3b3b40" };

async function showMatter() {
  let said;
  try { said = await (await fetch("/api/materials")).json(); } catch { return; }
  const colours = said.colors || {};
  const body = $("matter-table").querySelector("tbody");
  body.replaceChildren(...Object.entries(said.materials || {}).map(([name, m]) => {
    // Brittle means it has no yield: it does not bend first, it goes. That is
    // the catalogue's own distinction, not a word chosen here.
    const brittle = !(m.yield_strength_pa > 0);
    MATTER.set(name, { brittle });
    MATTER.set(m.scene_name, { brittle });
    const tr = document.createElement("tr");
    const first = document.createElement("td");
    const swatch = document.createElement("i");
    swatch.style.setProperty("--c", `#${(colours[m.scene_name] || "888888ff").slice(0, 6)}`);
    first.append(swatch, document.createTextNode(name));
    const density = document.createElement("td");
    density.className = "num";
    density.textContent = m.density_kg_m3 ? Math.round(m.density_kg_m3).toLocaleString() : "—";
    const how = document.createElement("td");
    how.className = brittle ? "brittle" : "ductile";
    how.textContent = brittle ? "breaking" : "bending";
    tr.append(first, density, how);
    return tr;
  }));
}

// --------------------------------------------------------------------------
// A picture of what is in your hands
//
// Its own small renderer showing the ACTUAL body -- the same cells or the same
// shape the world is drawing -- turning slowly. A name is not much use when
// most of what is here is a block of something.
// --------------------------------------------------------------------------

const handView = (() => {
  const canvas = $("hand-right-view");
  const r = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  r.setPixelRatio(Math.min(devicePixelRatio, 2));
  r.setSize(96, 96, false);
  const scene = new THREE.Scene();
  const cam = new THREE.PerspectiveCamera(38, 1, 0.01, 60);
  scene.add(new THREE.HemisphereLight(0xdfe9ec, 0x2a2118, 1.2));
  const key = new THREE.DirectionalLight(0xfff0d8, 1.4);
  key.position.set(2, 3, 2);
  scene.add(key);
  const spin = new THREE.Group();
  scene.add(spin);
  return { canvas, r, scene, cam, spin, of: "" };
})();

/** Put what is held in the little view -- every part of it, as they stand to
 *  each other -- sized so it fills the frame. */
function showInHand(parts) {
  const view3 = handView;
  if (!parts || !parts.length) {
    view3.spin.clear();
    view3.of = "";
    view3.r.clear();
    return;
  }
  const of = parts.map((p) => p.name).join("|");
  if (view3.of === of) return;
  view3.of = of;
  view3.spin.clear();
  let mesh;
  if (parts.length === 1) mesh = buildMesh(parts[0]);
  else {
    mesh = new THREE.Group();
    for (const part of parts) {
      const one = buildMesh(part);
      place(one, part);
      mesh.add(one);
    }
  }
  // Stand it about its own middle so it turns on the spot.
  const box = new THREE.Box3().setFromObject(mesh);
  const middle = box.getCenter(new THREE.Vector3());
  mesh.position.sub(middle);
  view3.spin.add(mesh);
  const reach = Math.max(0.05, box.getSize(new THREE.Vector3()).length());
  view3.cam.position.set(reach * 0.9, reach * 0.75, reach * 1.25);
  view3.cam.lookAt(0, 0, 0);
}

function drawHandView(dt) {
  if (!handView.of) return;
  handView.spin.rotation.y += dt * 0.7;
  handView.r.render(handView.scene, handView.cam);
}

// --------------------------------------------------------------------------
// The bag, and sweeping up
// --------------------------------------------------------------------------

const SWATCH_OF = (material) => SWATCH[material] || "#8a8f99";

function showCarrying() {
  const rows = [];
  // Raw material first: it is a quantity, not a thing, and it is what you come
  // back with from digging.
  const ground = me.carried || {};
  for (const [what, kg] of [["sand", ground.sand_kg], ["soil", ground.soil_kg]]) {
    if (kg > 0.0005) rows.push({ what, said: kg >= 1 ? `${kg.toFixed(1)} kg` : `${Math.round(kg * 1000)} g`,
                                 colour: what === "sand" ? "#cbb389" : "#7d6a4f" });
  }
  // Then whole things, counted: five oak blocks is one line saying five.
  const counted = new Map();
  for (const item of me.bagItems) {
    const seen = counted.get(item.name) || { n: 0, material: item.material };
    seen.n++;
    counted.set(item.name, seen);
  }
  for (const [name, seen] of counted) {
    rows.push({ what: name, said: seen.n > 1 ? `x${seen.n}` : "1", colour: SWATCH_OF(seen.material) });
  }
  const body = $("bag-table").querySelector("tbody");
  body.replaceChildren(...rows.map((row) => {
    const tr = document.createElement("tr");
    const first = document.createElement("td");
    const swatch = document.createElement("i");
    swatch.style.setProperty("--c", row.colour);
    first.append(swatch, document.createTextNode(row.what));
    const much = document.createElement("td");
    much.className = "num";
    much.textContent = row.said;
    tr.append(first, much);
    return tr;
  }));
  $("bag-empty").hidden = rows.length > 0;

  const limit = ground.limit_kg || 0;
  const total = ground.total_kg || 0;
  const share = limit ? Math.min(1, total / limit) : 0;
  $("load-fill").style.width = `${share * 100}%`;
  $("load-fill").classList.toggle("heavy", share > 0.75);
  $("load-said").textContent = limit ? `${Math.round(total)} of ${Math.round(limit)} kg` : "";
}

/** Sweep loose pieces near you into what you carry. Its own engine op, which
 *  is why this is a sweep and not a pile of separate pick-ups. */
async function sweepUp(said = true) {
  if (!world.session) return;
  try {
    const answer = await api("/api/live/act", {
      session: world.session, op: "collect",
      at: [person.x, groundAt(person.x, person.z), person.z],
      radius_m: 2.5, largest_cells: 64,
    });
    const took = answer.collected ?? answer.taken ?? (answer.gone || []).length;
    if (took) { if (said) say(`Swept up ${took} loose piece${took === 1 ? "" : "s"}.`); await refreshHands(); }
    else if (said) say("Nothing loose within reach.", { refused: true });
  } catch (trouble) {
    if (said) say(String(trouble.message).slice(0, 110), { refused: true });
  }
}

/** X: just let go. The place step looks for somewhere the thing will SIT, and
 *  standing among other things there may be nowhere -- which left you holding
 *  it with no way out. This drops it where you are and lets gravity have it. */
async function letGo() {
  if (!me.holding) { say("Your hands are empty.", { refused: true }); return; }
  const going = me.holding;
  me.busy = true;
  try {
    // Through the inventory, not straight at the engine: `drop` releases the
    // engine's hand AND writes the record in one go. Releasing the hand on its
    // own would leave the record still listing it as held.
    const said = await api("/api/world/inventory", {
      session: world.session, request: newRequest(), revision: me.revision,
      op: "drop", item: going, person: whereIAm(),
    });
    tookNote(said);
    say(said.did || `Let go of the ${going}.`);
  } catch (trouble) {
    // The record can disagree with the world -- it does not hear about a let-go
    // that happened inside a `place`. Rather than leave someone stuck holding
    // something, open the engine's hand and say plainly that they are apart.
    try {
      await api("/api/live/act", { session: world.session, op: "release" });
      say(`Let go of the ${going}, but the record did not take it: ${trouble.message}`,
          { refused: true });
    } catch { say(String(trouble.message).slice(0, 110), { refused: true }); }
  } finally {
    me.busy = false;
  }
}

/** Q: the thing in your hand goes into the bag. */
async function intoTheBag() {
  if (!me.holding) { say("Your hands are empty.", { refused: true }); return; }
  const going = me.holding;
  me.busy = true;
  try {
    const said = await api("/api/world/inventory", {
      session: world.session, request: newRequest(), revision: me.revision,
      op: "stow", item: going, person: whereIAm(),
    });
    tookNote(said);
    // A refusal looks like one: a thing tied to the room cannot go in the bag.
    say(said.why || `The ${going} is in your bag.`, { refused: said.ok === false });
  } catch (trouble) {
    say(String(trouble.message).slice(0, 110), { refused: true });
  } finally {
    me.busy = false;
  }
}

/** Which Workshop product this is, when it is one, so it can be opened there. */
function workshopKindOf(name) {
  const root = String(name || "").replace(/-\d+$/, "");
  return ["table", "bench", "chair", "stool", "shelf-unit", "cart", "kettle"].includes(root)
    ? root : null;
}

// --------------------------------------------------------------------------
// Opening it, and keeping it running
// --------------------------------------------------------------------------

/** Stand a few paces off the things in this world, on their ground, looking
 *  at them. A written-down spawn point is only right for the world it was
 *  chosen in: (0, -9) in this valley is the top of a hill, four metres above
 *  everything, and from up there the whole place is a band on the horizon. */
function standWhereTheThingsAre() {
  const all = world.shown.map((s) => s.data.position_m).filter(Boolean);
  const middle = all.length
    ? all.reduce((sum, at) => [sum[0] + at[0], sum[1] + at[1], sum[2] + at[2]], [0, 0, 0])
        .map((v) => v / all.length)
    : [0, 1, 0];
  // Far enough back to see the yard, and on the LOWER ground: stepping back
  // onto a hill is the same mistake in a different place.
  let best = null;
  for (let angle = 0; angle < Math.PI * 2; angle += Math.PI / 8) {
    const x = middle[0] + Math.cos(angle) * 7.5;
    const z = middle[2] + Math.sin(angle) * 7.5;
    const rise = groundAt(x, z) - middle[1];
    const score = Math.abs(rise + 0.4);      // a little below the things, not above
    if (!best || score < best.score) best = { x, z, score };
  }
  person.x = best.x;
  person.z = best.z;
  person.back = 0;
  // Face the middle of them. Forward is (-sin yaw, ., -cos yaw).
  person.yaw = Math.atan2(-(middle[0] - person.x), -(middle[2] - person.z));
  const drop = groundAt(person.x, person.z) + EYE - middle[1];
  person.pitch = Math.max(-0.6, Math.min(0.2, -Math.atan2(drop, 7.5)));
  person.came = { x: person.x, z: person.z, yaw: person.yaw, pitch: person.pitch };
}


async function open() {
  const step = (said) => { $("opening-step").textContent = said; };
  step("asking the engine for the ground…");
  const opened = await api("/api/world/open", { scene: SCENE, fresh: true });
  world.session = opened.session;
  world.cell = opened.cell_size_m || 0.04;
  world.t = opened.t || 0;
  // Each thing's own actions, as its maker programmed them (the Workshop's
  // model, the room's chat, a recipe): what J is called for it.
  world.actions = (opened.spec && opened.spec.actions) || [];

  step("drawing the valley…");
  if (opened.terrain) drawGround(opened.terrain);
  if (opened.water) drawWater(opened.water);

  step("putting everything in it…");
  draw(opened);
  if (opened.inventory) tookNote(opened.inventory);

  // Come in on the ground, looking at the middle of the valley.
  standWhereTheThingsAre();
  person.came = { x: person.x, z: person.z, yaw: person.yaw, pitch: person.pitch };
  $("opening").hidden = true;
}

let last = performance.now();
let owed = 0;
let sinceCount = 0;

async function tick() {
  const now = performance.now();
  const real = Math.min(0.1, (now - last) / 1000);
  last = now;
  walk(real);

  // Step the world by the time that actually passed, so it runs at the clock
  // rather than as fast as the engine can go.
  owed += real;
  if (world.session && owed > 1 / 60) {
    const dt = 1 / 120;
    const n = Math.min(24, Math.floor(owed / dt));
    owed -= n * dt;
    if (n > 0) {
      const began = performance.now();
      try {
        // The hand goes with the step rather than in a call of its own: it is
        // one round trip instead of two, and the engine wants them together.
        //
        // But NOT while the engine is running a stroke of its own. Putting a
        // thing down moves the hand along a path and waits for the room to be
        // stepped -- by this loop -- for it to get anywhere. Carrying on saying
        // "the hand is at my chest" every frame pulled it back each time, so
        // the stroke never arrived and every put-down ended "ran out of time".
        if (!me.holding) { world.handAt = null; world.liftTo = null; }
        const asked = {
          session: world.session, op: "step", dt, n,
          ...(me.holding && !me.busy ? { hand: leadHand(n * dt) } : {}),
        };
        const before = world.t;
        const state = await api("/api/live/act", asked);
        // What the last step asked and what came back, for the visual QA.
        world.lastStep = { n, hand: asked.hand || null, t: state.t ?? null,
                           bodies: (state.bodies || []).length, partial: !!state.partial,
                           ok: state.ok ?? null, stepped_back: state.stepped_back ?? null,
                           working_on: state.working_on ?? null,
                           impacts: Array.isArray(state.impacts) ? state.impacts.slice(0, 3) : state.impacts ?? null };
        world.t = state.t ?? world.t;
        const was = world.shown.length;
        draw(state);
        // Something may break. The engine has taken the step back and waits to
        // be told to work it out, and until it is told, time does not move:
        // stepping on only replays the same instant. That is how a carried ice
        // block clipping the ceramic block froze the whole valley while this
        // page went on saying "4.9x realtime". Started on the engine's worker
        // and not waited for, as world.js does; a later step brings the answer.
        if (state.breakable && state.breakable.length && !state.working_on) {
          const name = state.breakable[0];
          const hit = (state.impacts || []).filter((i) => i.struck === name)
            .sort((a, b) => b.closing_speed_m_s - a.closing_speed_m_s)[0];
          world.why.set(name, hit || null);
          await api("/api/live/act", { session: world.session, op: "fracture", name, wait: false });
        }
        if (state.finished) tellWhatBroke(state);
        // Something came apart: its pieces are loose around you, so they are
        // swept up rather than left for you to chase one at a time.
        if (world.shown.length > was + 1) sweepUp(false);
        const spent = (performance.now() - began) / 1000;
        // What actually passed, not what was asked for: a world held still by
        // an unanswered break read "4.9x realtime" here while nothing moved.
        const passed = typeof state.t === "number" ? state.t - before : n * dt;
        world.pace = spent > 0 ? passed / spent : 0;
        $("pace").textContent = `${world.pace.toFixed(1)}× realtime`
          + (person.back > 0.05 ? ` · ${person.back.toFixed(1)} m back` : "");
        $("pace").classList.toggle("slow", world.pace < 1.1);
        world.failures = 0;
      } catch (trouble) {
        // One failed step is not the end: a request can be cut, or the server
        // busy for a moment. Dropping the session on the FIRST one stopped the
        // room, E and the preview all at once, with a word only in the pace
        // readout -- so E went on doing nothing and nothing said why. Three in
        // a row, and it stops, and says so where you are looking.
        world.failures = (world.failures || 0) + 1;
        $("pace").textContent = String(trouble.message).slice(0, 60);
        if (world.failures >= 3) {
          world.session = "";
          say(`The world stopped: ${String(trouble.message).slice(0, 140)}. Reload the page to start again.`,
              { refused: true, stays: true });
        }
      }
    }
  }
  showLookedAt();
  askWhereItWouldGo();
  drawHandView(real);
  renderer.render(view, camera);
  requestAnimationFrame(tick);
}

sized();
showMatter();
$("to-bag").addEventListener("click", intoTheBag);
open().then(() => requestAnimationFrame(tick)).catch((trouble) => {
  $("opening").classList.add("failed");
  $("opening").querySelector("strong").textContent = "The world would not open";
  $("opening-step").textContent = String(trouble.message).slice(0, 200);
});

// For the tests and for looking at it from the console.
//
// The visual QA (tests/explore_visual_qa.py) reads what is ON SCREEN through
// this: where the camera would draw a point, where the sight is, where each
// thing and the ghost are drawn. It only ever reads, apart from aimAt and
// faceThing, which turn and stand the person exactly as walking there would --
// they never touch the world.
function screenOf(point) {
  const v = new THREE.Vector3(...point).project(camera);
  return { x: (v.x + 1) / 2 * innerWidth, y: (1 - v.y) / 2 * innerHeight,
           front: v.z > -1 && v.z < 1 };
}

/** The box on screen that a set of oriented boxes covers. */
function screenBoxOf(boxes) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, front = false;
  const q = new THREE.Quaternion();
  for (const { at, size, wxyz } of boxes) {
    if (wxyz) q.set(wxyz[1], wxyz[2], wxyz[3], wxyz[0]); else q.identity();
    for (const sx of [-0.5, 0.5]) for (const sy of [-0.5, 0.5]) for (const sz of [-0.5, 0.5]) {
      const corner = new THREE.Vector3(sx * size[0], sy * size[1], sz * size[2])
        .applyQuaternion(q).add(new THREE.Vector3(...at));
      const s = screenOf([corner.x, corner.y, corner.z]);
      if (!s.front) continue;
      front = true;
      x0 = Math.min(x0, s.x); y0 = Math.min(y0, s.y);
      x1 = Math.max(x1, s.x); y1 = Math.max(y1, s.y);
    }
  }
  return front ? { x0, y0, x1, y1 } : null;
}

function thingNamed(name) {
  const parts = world.shown.filter((s) => s.data.name === name).map((s) => s.data);
  if (!parts.length) return null;
  const q = new THREE.Quaternion();
  let lowest = Infinity, aim = null, most = -1, tilt = 0;
  const boxes = [];
  for (const p of parts) {
    const w = p.orientation_wxyz;
    if (w) q.set(w[1], w[2], w[3], w[0]); else q.identity();
    const at = new THREE.Vector3(...p.position_m);
    // A lattice body's position is its centre of mass and its dimensions its
    // bounds, which need not be centred on it: a table's mass sits up in its
    // top. Measured from its cells when it has them, from its box when not.
    let size = p.dimensions_m || [0, 0, 0], offset = [0, 0, 0];
    const cells = p.cells_local_m;
    if (cells && cells.length) {
      const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
      for (const c of cells) for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], c[k]); hi[k] = Math.max(hi[k], c[k]); }
      size = [0, 1, 2].map((k) => hi[k] - lo[k] + world.cell);
      offset = [0, 1, 2].map((k) => (lo[k] + hi[k]) / 2);
      // Lowest point: every cell's own lowest corner, turned as the body is.
      for (const c of cells) {
        const y = new THREE.Vector3(...c).applyQuaternion(q).y + at.y;
        lowest = Math.min(lowest, y - world.cell / 2);
      }
    } else {
      let reach = 0;
      for (let k = 0; k < 3; k++) {
        const axis = new THREE.Vector3(k === 0 ? 1 : 0, k === 1 ? 1 : 0, k === 2 ? 1 : 0).applyQuaternion(q);
        reach += Math.abs(axis.y) * size[k] / 2;
      }
      lowest = Math.min(lowest, at.y - reach);
    }
    const middle = new THREE.Vector3(...offset).applyQuaternion(q).add(at);
    boxes.push({ at: [middle.x, middle.y, middle.z], size, wxyz: w });
    // What a person aims at: a solid bit of its upper part -- a stool's seat,
    // not the middle of its legs, where the sight sees straight through it.
    const volume = size[0] * size[1] * size[2];
    if (volume > most) {
      most = volume;
      // How far it leans from the way it was made to stand: fallen over reads
      // near 90.
      const up = new THREE.Vector3(0, 1, 0).applyQuaternion(q);
      tilt = Math.acos(Math.max(-1, Math.min(1, up.y))) * 180 / Math.PI;
      if (cells && cells.length) {
        const want = new THREE.Vector3(offset[0], offset[1] + size[1] * 0.3, offset[2]);
        let best = cells[0], gap = Infinity;
        for (const c of cells) {
          const d = (c[0] - want.x) ** 2 + (c[1] - want.y) ** 2 + (c[2] - want.z) ** 2;
          if (d < gap) { gap = d; best = c; }
        }
        const v = new THREE.Vector3(...best).applyQuaternion(q).add(at);
        aim = [v.x, v.y, v.z];
      } else {
        aim = [middle.x, middle.y, middle.z];
      }
    }
  }
  const centre = [0, 1, 2].map((k) => boxes.reduce((s, b) => s + b.at[k], 0) / boxes.length);
  return {
    parts: parts.length, lowest, centre, aim, tilt,
    mass_kg: parts.reduce((m, p) => m + (p.mass_kg || 0), 0),
    cells: parts.reduce((n, p) => n + ((p.cells_local_m || []).length), 0),
    held: parts.some((p) => p.held),
    seeThrough: world.shown.some((s) => s.data.name === name && s.clear),
    ground: groundAt(centre[0], centre[2]),
    box: screenBoxOf(boxes),
    screen: screenOf(centre),
  };
}

/** Turn until the sight is on a point, the way the arrows would. */
function aimAt(point) {
  const target = new THREE.Vector3(...point);
  // Face it first, straight from the eye. Refining from wherever the view last
  // was failed whenever the point was behind the camera: a point behind
  // projects mirrored, and the correction turned the view up at the sky.
  const eye = groundAt(person.x, person.z) + EYE;
  person.yaw = Math.atan2(-(target.x - person.x), -(target.z - person.z));
  person.pitch = Math.atan2(target.y - eye, Math.hypot(target.x - person.x, target.z - person.z));
  for (let i = 0; i < 16; i++) {
    walk(0);
    camera.updateMatrixWorld();
    const at = target.clone().project(camera);
    const sight = sightInView();
    const ex = at.x - sight.x, ey = at.y - sight.y;
    if (Math.abs(ex) < 2e-4 && Math.abs(ey) < 2e-4) break;
    const vfov = camera.fov * Math.PI / 180;
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * camera.aspect);
    person.yaw -= ex * hfov / 2;
    person.pitch += ey * vfov / 2;
  }
  walk(0);
}

/** Stand `away` metres from a thing, on the flattest open side of it, looking
 *  at it. What a person does by walking up to it; the test does it directly so
 *  the same thing is looked at every time. */
function faceThing(name, away = 1.8) {
  const it = thingNamed(name);
  if (!it) return false;
  const [cx, , cz] = it.centre;
  let best = null;
  for (let k = 0; k < 16; k++) {
    const a = k * Math.PI / 8;
    const x = cx + Math.cos(a) * away, z = cz + Math.sin(a) * away;
    // Flat under the feet, and nobody else's things in the way.
    let rough = 0;
    for (const [dx, dz] of [[0.4, 0], [-0.4, 0], [0, 0.4], [0, -0.4]]) {
      rough += Math.abs(groundAt(x + dx, z + dz) - groundAt(x, z));
    }
    const crowd = world.shown.filter((s) => s.data.name !== name && s.data.position_m &&
      Math.hypot(s.data.position_m[0] - x, s.data.position_m[2] - z) < 0.9).length;
    const score = rough + crowd * 2 + Math.abs(groundAt(x, z) + EYE - it.centre[1] - 1.2) * 0.2;
    if (!best || score < best.score) best = { x, z, score };
  }
  Object.assign(person, { x: best.x, z: best.z, back: 0 });
  aimAt(it.aim);
  return true;
}

/** Look at the ground `ahead` metres in front, keeping the way you face. */
function aimAtGround(ahead = 1.6, turn = 0) {
  const fx = -Math.sin(person.yaw + turn), fz = -Math.cos(person.yaw + turn);
  const x = person.x + fx * ahead, z = person.z + fz * ahead;
  aimAt([x, groundAt(x, z), z]);
}

function snapshot(names = []) {
  const side = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--side-w")) || 0;
  const sight = sightInView();
  const text = (id) => ($(id) && !$(id).hidden ? $(id).textContent.trim() : null);
  const things = {};
  for (const name of names) things[name] = thingNamed(name);
  const shownGhost = ghost && ghost.visible ? {
    at: [ghost.position.x, ghost.position.y, ghost.position.z],
    size: [ghost.scale.x, ghost.scale.y, ghost.scale.z],
    colour: `#${ghost.material.color.getHexString()}`,
    screen: screenOf([ghost.position.x, ghost.position.y, ghost.position.z]),
    // Where it will STAND: the middle of its base, down its own up (it is set
    // square to the ground). For a 1.8 m shelf unit the middle of the preview
    // is 0.9 m above the spot the sight is on.
    base: screenOf(ghost.position.clone()
      .addScaledVector(new THREE.Vector3(0, 1, 0).applyQuaternion(ghost.quaternion), -ghost.scale.y / 2)
      .toArray()),
    box: screenBoxOf([{ at: [ghost.position.x, ghost.position.y, ghost.position.z],
                        size: [ghost.scale.x, ghost.scale.y, ghost.scale.z],
                        wxyz: [ghost.quaternion.w, ghost.quaternion.x, ghost.quaternion.y, ghost.quaternion.z] }]),
  } : null;
  const handRect = $("hand-right-view").getBoundingClientRect();
  return {
    now: performance.now(), t: world.t, pace: world.pace, live: !!world.session,
    view: { w: innerWidth, h: innerHeight, side },
    sight: { x: (sight.x + 1) / 2 * innerWidth, y: (1 - sight.y) / 2 * innerHeight },
    person: { x: person.x, z: person.z, yaw: person.yaw, pitch: person.pitch, back: person.back },
    me: { holding: me.holding, record: me.record, busy: me.busy, canPlace: !!me.canPlace,
          heldKg: heldMass() },
    ghost: shownGhost,
    said: { loud: text("said-loud"), refused: !!$("said-loud")?.classList.contains("refused"),
            panel: text("did"), canDo: text("can-do"), ghost: text("ghost-said"),
            held: text("hands-held"), inFront: text("seen-name"), pace: text("pace") },
    handView: { x: handRect.x, y: handRect.y, w: handRect.width, h: handRect.height },
    things,
    waiting: [...inFlight.values()].map((c) => ({ path: c.path, op: c.op || null,
                                                  for_s: (performance.now() - c.since) / 1000 })),
    lastStep: world.lastStep || null, failures: world.failures || 0,
    lastPlacement: world.lastPlacement || null,
  };
}

window.banjoExplorer = {
  world, person,
  status: () => ({ session: world.session, t: world.t, pace: world.pace,
                   bodies: world.shown.length, ground: !!world.ground,
                   looking: looked, holding: me.holding }),
  snapshot, faceThing, aimAt, aimAtGround, screenOf,
  names: () => [...new Set(world.shown.map((s) => s.data.name))],
};
