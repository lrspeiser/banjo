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

/** Every POST carries the page's token; a 403 means it went stale, so it is
 *  fetched again and the call retried exactly once. */
async function api(path, body) {
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

/** A body's mesh. Cells win over shape: once the engine sends `cells_local_m`
 *  that IS the thing -- every piece a break left, every cell a dent moved --
 *  and drawing the original box instead would be drawing something that is no
 *  longer there. */
function buildMesh(body) {
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
   (body.dimensions_m || []).join(",")].join("|");

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
    const sig = signatureOf(body);
    const slot = world.shown[i];
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
}

// --------------------------------------------------------------------------
// Walking and looking
// --------------------------------------------------------------------------

const EYE = 1.62;
const person = { x: 0, z: -9, yaw: 0, pitch: -0.06, fly: 0, came: null };
const pressed = new Set();

addEventListener("keydown", (e) => {
  if (e.code === "KeyR" && person.came) Object.assign(person, person.came, { came: person.came });
  pressed.add(e.code);
  if (e.code.startsWith("Arrow")) $("hint")?.remove();
  if (e.code === "KeyE") takeOrPutDown();
  if (e.code === "KeyJ") usePrimary().catch((t) => say(String(t.message).slice(0, 120)));
  if (["KeyW", "KeyA", "KeyS", "KeyD", "Space", "ArrowUp", "ArrowDown",
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
  if (turnedSince < 4) usePrimary().catch((t) => say(String(t.message).slice(0, 120)));
});
$("view").addEventListener("dblclick", () => {
  // Not every page is allowed to take the mouse: inside an embedded frame the
  // browser refuses with "The root document of this element is not valid for
  // pointer lock", and an unhandled refusal fills the console on every attempt.
  // Dragging works everywhere, so a refusal here costs nothing.
  try { $("view").requestPointerLock()?.catch?.(() => {}); } catch { /* drag instead */ }
});
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

  if (pressed.has("Space")) person.fly = Math.min(9, person.fly + 4 * dt);
  if (pressed.has("KeyC")) person.fly = Math.max(0, person.fly - 4 * dt);

  const g = world.ground;
  if (g) {
    person.x = Math.min(g.x0 + (g.nx - 1) * g.cell, Math.max(g.x0, person.x));
    person.z = Math.min(g.z0 + (g.nz - 1) * g.cell, Math.max(g.z0, person.z));
  }
  camera.position.set(person.x, groundAt(person.x, person.z) + EYE + person.fly, person.z);
  camera.rotation.set(person.pitch, person.yaw, 0, "YXZ");
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
  const hit = ray.intersectObjects(world.shown.map((s) => s.mesh), false)[0];
  if (!hit) return null;
  const slot = world.shown.find((s) => s.mesh === hit.object);
  return slot ? { name: slot.data.name, known: slot, hit } : null;
}

const KG = (n) => (n >= 1 ? `${n.toFixed(n < 10 ? 2 : 1)} kg` : `${Math.round(n * 1000)} g`);

function showLookedAt() {
  const found = lookedAt();
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

const me = { holding: null, revision: 0, busy: false, said: "" };

/** Where the person is, in the words every world route asks for. */
function whereIAm() {
  const ahead = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion);
  const found = lookedAt();
  const said = {
    standing_m: [person.x, groundAt(person.x, person.z), person.z],
    facing: [-Math.sin(person.yaw), 0, -Math.cos(person.yaw)],
    eyes_m: [camera.position.x, camera.position.y, camera.position.z],
    look_direction: [ahead.x, ahead.y, ahead.z],
  };
  if (me.holding) said.holding = me.holding;
  if (found) said.looking_at = found.name;
  return said;
}

const newRequest = () => `explore-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;

function tookNote(said) {
  if (!said) return;
  if (typeof said.revision === "number") me.revision = said.revision;
  const shown = said.shown || said;
  const hands = shown.hands || {};
  const right = hands.right || hands.left || null;
  me.holding = right ? (right.name || right.item || right.id || null) : null;
  showHands(shown);
}

/** E: the one contextual thing. Empty-handed and pointing at something loose,
 *  take it up; holding something, put it down where the ghost says. */
async function takeOrPutDown() {
  if (me.busy || !world.session) return;
  me.busy = true;
  try {
    if (me.holding) {
      // Put it down through its own Use, so a thing with a `place` program
      // lands where the ghost is rather than being dropped on the spot.
      await usePrimary();
    } else {
      const found = lookedAt();
      if (!found) { say("Nothing in front of you to pick up."); return; }
      if (found.known.data.anchored) { say(`${found.name} is fixed down.`); return; }
      // Every /api/world/* call carries the session: the playground runs one
      // room at a time, and a page whose room was reopened elsewhere must not
      // go on moving things about in somebody else's (server._this_pages_room).
      const said = await api("/api/world/inventory", {
        session: world.session, request: newRequest(), revision: me.revision,
        op: "take_up", item: found.name, person: whereIAm(),
      });
      tookNote(said);
      say(me.holding ? `You have the ${me.holding}.` : (said.why || "It would not come up."));
    }
  } catch (trouble) {
    say(String(trouble.message).slice(0, 120));
  } finally {
    me.busy = false;
  }
}

/** J or the left button: the one thing this object is for. */
async function usePrimary() {
  if (!world.session) return;
  const target = me.holding || lookedAt()?.name;
  if (!target) { say("Point at something, or pick something up."); return; }
  const said = await api("/api/world/action", {
    session: world.session, object: target, primary: true, person: whereIAm(),
  });
  // A refusal first and in its own words: it is the most useful thing the
  // engine ever says, and burying it under a label reads as success.
  if (said.refused) say(`${said.action || "That"}: ${said.refused}`);
  else say(said.said || said.did || said.why || said.action || "Done.");
  if (said.inventory || said.shown) tookNote(said.inventory || said);
  else if (me.holding) await refreshHands();
}

async function refreshHands() {
  try { tookNote(await api("/api/world/inventory/shown", { session: world.session })); }
  catch { /* the hands are only a readout */ }
}

function say(words) {
  me.said = words;
  $("did").textContent = words;
  $("did").hidden = !words;
}

function showHands(shown) {
  const hands = (shown && shown.hands) || {};
  const held = hands.right || hands.left || null;
  $("hands-held").textContent = held ? (held.name || held.item || "something") : "nothing";
  $("hands-held").className = held ? "strong" : "";
  const bag = (shown && shown.stowed) || [];
  $("hands-bag").textContent = bag.length
    ? bag.map((b) => b.name || b.item || "?").join(", ") : "empty";
}

// --------------------------------------------------------------------------
// The ghost: where it would go if you let go now
// --------------------------------------------------------------------------

let ghost = null;
let ghostAsked = 0;

function showGhost(answer, body) {
  if (!answer || !answer.on) { hideGhost(); return; }
  const [dx, dy, dz] = body.dimensions_m || [0.3, 0.3, 0.3];
  if (!ghost) {
    ghost = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1),
      new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.34, depthWrite: false }));
    view.add(ghost);
  }
  ghost.visible = true;
  ghost.scale.set(dx, dy, dz);
  ghost.position.set(answer.on[0], answer.on[1] + dy / 2, answer.on[2]);
  ghost.rotation.set(0, (answer.yaw_deg || 0) * Math.PI / 180, 0);
  // Green it fits, amber it is held up by too few corners, red it does not.
  const corners = answer.supported_corners;
  ghost.material.color.set(!answer.fits ? 0xff9f91
    : (typeof corners === "number" && corners < 4 ? 0xffd195 : 0xa2e1c8));
  $("ghost-said").textContent = answer.why || answer.label || "";
  $("ghost-said").hidden = false;
}

function hideGhost() {
  if (ghost) ghost.visible = false;
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
  try {
    const answer = await api("/api/world/placement", {
      session: world.session, name: me.holding, person: whereIAm(),
    });
    showGhost(answer, slot ? slot.data : {});
  } catch { hideGhost(); }
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

function showStuff() {
  // A thing is its join group: a table is one table, not five boards.
  const counts = new Map();
  for (const { data } of world.shown) {
    const root = data.name.replace(/-\d+$/, "");
    const seen = counts.get(root) || { n: 0, material: data.material };
    seen.n++;
    counts.set(root, seen);
  }
  $("stuff-list").replaceChildren(...[...counts.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([name, seen]) => {
      const li = document.createElement("li");
      const swatch = document.createElement("i");
      swatch.style.setProperty("--c", SWATCH[seen.material] || "#888");
      const what = document.createElement("span");
      what.className = "what"; what.textContent = name;
      const count = document.createElement("span");
      count.className = "count"; count.textContent = seen.n > 1 ? `${seen.n} parts` : "";
      li.append(swatch, what, count);
      return li;
    }));
  $("made").textContent = `${counts.size} things · ${world.shown.length} bodies`;
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
  person.fly = 0;
  // Face the middle of them. Forward is (-sin yaw, ., -cos yaw).
  person.yaw = Math.atan2(-(middle[0] - person.x), -(middle[2] - person.z));
  const drop = groundAt(person.x, person.z) + EYE - middle[1];
  person.pitch = Math.max(-0.6, Math.min(0.2, -Math.atan2(drop, 7.5)));
  person.came = { x: person.x, z: person.z, yaw: person.yaw, pitch: person.pitch, fly: 0 };
}


async function open() {
  const step = (said) => { $("opening-step").textContent = said; };
  step("asking the engine for the ground…");
  const opened = await api("/api/world/open", { scene: SCENE, fresh: true });
  world.session = opened.session;
  world.cell = opened.cell_size_m || 0.04;
  world.t = opened.t || 0;

  step("drawing the valley…");
  if (opened.terrain) drawGround(opened.terrain);
  if (opened.water) drawWater(opened.water);

  step("putting everything in it…");
  draw(opened);
  showStuff();
  if (opened.inventory) tookNote(opened.inventory);

  // Come in on the ground, looking at the middle of the valley.
  standWhereTheThingsAre();
  person.came = { x: person.x, z: person.z, yaw: person.yaw, pitch: person.pitch, fly: 0 };
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
        const state = await api("/api/live/act", { session: world.session, op: "step", dt, n });
        world.t = state.t ?? world.t;
        draw(state);
        const spent = (performance.now() - began) / 1000;
        world.pace = spent > 0 ? (n * dt) / spent : 0;
        $("pace").textContent = `${world.pace.toFixed(1)}× realtime`;
        $("pace").classList.toggle("slow", world.pace < 1.1);
        if (++sinceCount % 30 === 0) showStuff();
      } catch (trouble) {
        $("pace").textContent = String(trouble.message).slice(0, 60);
        world.session = "";
      }
    }
  }
  showLookedAt();
  askWhereItWouldGo();
  renderer.render(view, camera);
  requestAnimationFrame(tick);
}

sized();
showMatter();
open().then(() => requestAnimationFrame(tick)).catch((trouble) => {
  $("opening").classList.add("failed");
  $("opening").querySelector("strong").textContent = "The world would not open";
  $("opening-step").textContent = String(trouble.message).slice(0, 200);
});

// For the tests and for looking at it from the console.
window.banjoExplorer = {
  world, person,
  status: () => ({ session: world.session, t: world.t, pace: world.pace,
                   bodies: world.shown.length, ground: !!world.ground,
                   looking: looked, holding: me.holding }),
};
