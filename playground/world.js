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
  if (!world.session || world.busy) return;
  world.busy = true;
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
      $("panel-state").textContent =
        `${name} was hit hard enough to break — working it out…`;
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
    narrateCuts(state.cuts, say, remember);
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
    $("panel-state").textContent = `The room stopped: ${error.message || error}`;
    world.session = null;
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
      remember("the room was rebuilt: " + (answer.did || []).join(", "));
    }
  } catch (error) {
    waiting.done();
    say("bad", String(error.message || error));
  } finally { $("ask-send").disabled = false; input.focus(); }
});

$("reset").addEventListener("click", () => open());
$("scene").addEventListener("change", () => open());

// ---------------------------------------------------------------------------
// Opening
// ---------------------------------------------------------------------------

async function open() {
  $("panel-state").textContent = "Opening the room…";
  try {
    const data = await api("/api/world/open", { scene: $("scene").value });
    world.session = data.session;
    world.lastTick = 0;
    world.story = [];
    world.held = null;
    $("carry").hidden = true;
    world.bodies.forEach((e) => forget(e.mesh));
    world.bodies.clear();
    world.joints = [];
    draw(data);
    drawJoints(data.joints);
    drawRopes();
    $("panel-state").textContent = "Live.";
    $("chat").replaceChildren();
    say("world",
      `${data.bodies.length} things, made of ${
        [...new Set(data.bodies.map((b) => b.material).filter(Boolean))].join(", ")
      }. Click the room to look around, walk with W A S D, and click again to pick`
      + ` something up. Ask me to change anything.`);
    const edged = (data.blades || []).map((b) => b.body);
    if (edged.length) {
      say("world", `${edged.join(", ")} ${edged.length > 1 ? "have edges" : "has an edge"}.`
        + ` Click it to take it by the grip; turn to swing it, and right-click to turn the`
        + ` edge (left, down, right, up). It cuts what its edge meets hard enough, and`
        + ` nothing else.`);
    }
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

// Reported on its own timer rather than from the frame loop, because a room
// that has stopped drawing is exactly the case worth hearing about and it
// would never send anything. "0 frames in four seconds" is a report.
setInterval(() => sendTrace("routine"), TRACE_EVERY_MS);
setInterval(tick, 33);
setInterval(aim, 90);
open();
