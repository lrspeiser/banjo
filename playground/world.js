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

const $ = (id) => document.getElementById(id);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

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
  const geometry = body.shape === "sphere"
    ? new THREE.SphereGeometry(w / 2, 24, 16)
    : new THREE.BoxGeometry(Math.max(w, 1e-4), Math.max(h, 1e-4), Math.max(d, 1e-4));
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
  const seen = new Set();
  for (const body of state.bodies) {
    seen.add(body.name);
    let held = world.bodies.get(body.name);
    // Geometry only travels when the set of bodies can have changed, so a
    // body already on screen keeps its mesh and only moves.
    if (!held || (body.cells_local_m && !held.fromCells)) {
      if (held) forget(held.mesh);
      const mesh = buildMesh(body);
      scene.add(mesh);
      held = { mesh, fromCells: !!(body.cells_local_m && body.cells_local_m.length) };
      world.bodies.set(body.name, held);
    }
    held.material = body.material || "";
    held.dims = body.dimensions_m;
    held.anchored = !!body.anchored;
    held.shape = body.shape;
    place(held.mesh, body);
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
  $("panel-count").textContent = `${world.bodies.size} objects`;
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
// Standing in it: W A S D, and the mouse
// ---------------------------------------------------------------------------

const keys = new Set();
let yaw = 0, pitch = 0, looking = false;

addEventListener("keydown", (e) => {
  if (e.target instanceof HTMLInputElement) return;
  keys.add(e.code);
  if (e.code === "KeyF" && world.held) intend("throw");
  if (["KeyW","KeyA","KeyS","KeyD","KeyQ","KeyE","Space",
       "ArrowUp","ArrowDown","ArrowLeft","ArrowRight"].includes(e.code)) e.preventDefault();
});
addEventListener("keyup", (e) => keys.delete(e.code));
addEventListener("blur", () => keys.clear());

let drag = null;
canvas.addEventListener("pointerdown", (e) => {
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
  // Not below the floor, and not so high the room is a map.
  camera.position.y = clamp(camera.position.y, 0.25, 12);
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
    showLabel(world.aim);
  } catch { /* the next frame asks again */ } finally { aimBusy = false; }
}

function showLabel(found) {
  const box = $("label");
  const cross = $("crosshair");
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
      + ` · ${found.distance_m.toFixed(2)} m away`
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

async function pickUp() {
  if (!world.aim) return;
  const name = world.aim.name;
  const entry = world.bodies.get(name);
  if (entry?.anchored) {
    say("world", `${name} is fixed in place — it is the room, not a prop.`);
    return;
  }
  try {
    await act("grab", { name });
    world.held = { name, distance: clamp(world.aim.distance_m, 0.6, 4.0) };
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

const LIVE_DT = 1 / 120;
const MAX_STEPS = 120;

async function tick() {
  if (!world.session || world.busy) return;
  world.busy = true;
  try {
    // Whatever was clicked for while the last step was in flight.
    if (wants) { const what = wants; wants = null; 
      if (what === "pick") await pickUp();
      else if (what === "drop") await dropIt();
      else if (what === "throw") await throwIt();
    }
    // Carry first, so the object is where the hand is before the step runs.
    if (world.held) {
      const dir = forwardVector();
      const p = camera.position.clone().add(dir.multiplyScalar(world.held.distance));
      await act("move", { to: [p.x, p.y, p.z] });
    }
    const now = performance.now();
    const elapsed = world.lastTick ? (now - world.lastTick) / 1000 : LIVE_DT;
    world.lastTick = now;
    const steps = clamp(Math.round(elapsed / LIVE_DT), 1, MAX_STEPS);
    let state = await act("step", { dt: LIVE_DT, n: steps, moved: true });

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
    if (state.breakable && state.breakable.length && !state.working_on) {
      const name = state.breakable[0];
      const hit = (state.impacts || []).filter((i) => i.struck === name)
        .sort((a, b) => b.closing_speed_m_s - a.closing_speed_m_s)[0];
      if (hit) world.why.set(name, hit);
      $("panel-state").textContent =
        `${name} was hit hard enough to break — working it out…`;
      await act("fracture", { name, wait: false });
    }
    // The answer to one started earlier.
    if (state.finished) {
      const name = state.finished;
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
    $("panel-state").textContent = `The room stopped: ${error.message || error}`;
    world.session = null;
  } finally { world.busy = false; }
}

let last = performance.now();
function frame() {
  const now = performance.now();
  const dt = Math.min(0.1, (now - last) / 1000);
  last = now;
  lookFromKeys(dt);
  walk(dt);
  updateGuides();
  fadePieces(now);
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// ---------------------------------------------------------------------------
// The panel
// ---------------------------------------------------------------------------

function say(who, text, did) {
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

$("ask").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("ask-text");
  const text = input.value.trim();
  if (!text || !world.session) return;
  input.value = "";
  say("you", text);
  const waiting = say("world", "Thinking…");
  waiting.classList.add("thinking");
  $("ask-send").disabled = true;
  try {
    const answer = await api("/api/world/ask", {
      session: world.session,
      message: text,
      // What the person has been doing. A model asked to change a room it
      // cannot see has to be told what has happened in it.
      story: world.story.slice(-24),
    });
    waiting.remove();
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
      remember("the room was rebuilt: " + (answer.did || []).join(", "));
    }
  } catch (error) {
    waiting.remove();
    say("bad", String(error.message || error));
  } finally { $("ask-send").disabled = false; input.focus(); }
});

$("reset").addEventListener("click", () => open());

// ---------------------------------------------------------------------------
// Opening
// ---------------------------------------------------------------------------

async function open() {
  $("panel-state").textContent = "Opening the room…";
  try {
    const data = await api("/api/world/open", {});
    world.session = data.session;
    world.lastTick = 0;
    world.story = [];
    world.held = null;
    $("carry").hidden = true;
    world.bodies.forEach((e) => forget(e.mesh));
    world.bodies.clear();
    draw(data);
    $("panel-state").textContent = "Live.";
    $("chat").replaceChildren();
    say("world",
      `${data.bodies.length} things, made of ${
        [...new Set(data.bodies.map((b) => b.material).filter(Boolean))].join(", ")
      }. Click the room to look around, walk with W A S D, and click again to pick`
      + ` something up. Ask me to change anything.`);
  } catch (error) {
    $("panel-state").textContent = `Could not open the room: ${error.message || error}`;
  }
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
};

setInterval(tick, 33);
setInterval(aim, 90);
open();
