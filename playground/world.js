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
import { expeditionUI } from "/gameplay.js";
import { rememberBlades, bladeFor, STANCES, takeHold, handTarget, dressBlades, showKerfs,
         narrateCuts } from "/blades.js";
import { BINDINGS, isKey, isButton, keyOf, controls, holdPoint, windUpPoint,
         windUpReached, throwStroke, placeStroke, throwable, handHelp, AimArc,
         WIND_UP_S, TURNS, TURN_KEY_RATE, HOLD_RANGE_M, holdDistanceFor, radiusOf,
         turnPace, askTowards, uprightTurn } from "/interaction.js";
import { cellSurface } from "/cellmesh.js";
import { dress, dressedClone, showGrain, grainState } from "/surfaces.js";
import { makeTools } from "/tools.js";
import { makeWorkbench } from "/workbench.js";
import { gameNavigation, showSaveStatus } from "/game_menu.js";

const $ = (id) => document.getElementById(id);
const worldId = new URLSearchParams(location.search).get("world");
const watchedId = new URLSearchParams(location.search).get("watch");
const worldNavigation = gameNavigation("world");
$("panel").querySelector("header").after(worldNavigation);
for (const link of document.querySelectorAll("#panel header .workshop-entry:not(.debug-entry)")) link.remove();
let watchedView = null;
let watchedAt = 0;
if (worldId) {
  for (const link of document.querySelectorAll("#panel .workshop-entry:not(.debug-entry)")) {
    const target = new URL(link.href);
    target.searchParams.set("world", worldId);
    link.href = target.pathname + target.search;
  }
}
let playerToken = null;
let playerId = null;
let playerName = null;
let joinedPlayer = null;
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
  if (watchedId && body !== undefined && path !== "/api/world/player/join"
      && !(path === "/api/world/ai" && body.action === "watch")
      && !(path === "/api/live/act" && body.op === "structure"))
    throw new Error("Watching is read-only. Return to your character to interact.");
  const headers = { "Content-Type": "application/json" };
  if (worldId) headers["X-Banjo-World"] = worldId;
  if (worldId && playerToken) headers["X-Banjo-Player"] = playerToken;
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
    try { status = await (await fetch("/api/status", { headers })).json(); }
    catch (error) { throw linkFailure(error); }
    token = status.csrf_token;
    if (!token) throw new Error("the server would not hand out a session token");
    return api(path, body, true);
  }
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = { error: text.slice(0, 300) }; }
  showSaveStatus(data.persistence);
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
  inventory: null,        // what the person has: the server's record, as it shows it
  workingOn: "",          // what the engine is working out, for the frame record
  held: null,             // { name, distance }
  aim: null,              // what the crosshair is on, from the engine
  // The side view's details (showDetails): which of what can be done E does
  // (Tab moves it on), what the last thing done came to, the action running,
  // and where what is held would come down.
  choice: { of: "", index: 0 },
  last: null,             // { text, tone: "did" | "refused" }
  doing: null,            // the label of the action running
  carry: null,            // "over the floor, 0.83 m up · at x, y, z m"
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

async function joinPlayer() {
  if (!worldId) return;
  if (joinedPlayer) return joinedPlayer;
  joinedPlayer = (async () => {
    const key = `banjo.player.${worldId}`;
    const remembered = localStorage.getItem(key);
    const name = localStorage.getItem("banjo.avatar-name") || undefined;
    const data = await api("/api/world/player/join", { token: remembered || undefined, name });
    playerToken = data.token;
    playerId = data.id;
    playerName = data.name;
    localStorage.setItem(key, playerToken);
    const label = document.querySelector("#players-online");
    if (label) label.textContent = `You: ${playerName}`;
    return data;
  })();
  try { return await joinedPlayer; }
  catch (error) { joinedPlayer = null; throw error; }
}

function playerView(pose) {
  if (!pose?.eyes_m || !pose.facing) return null;
  const eye_m = pose.eyes_m;
  return { eye_m, look_m: eye_m.map((v, i) => v + 4 * pose.facing[i]) };
}

// ---------------------------------------------------------------------------
// The room
// ---------------------------------------------------------------------------

const canvas = $("stage");
// A lost context never draws again, and nothing else on the page would say so.
canvas.addEventListener("webglcontextlost", () => noteError("the WebGL context was lost"));
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
// Lit the way a camera sees it rather than the way the numbers add up. With no
// tone curve a bright surface clips to flat white and takes its shape with it,
// which is why polished iron read as a grey cut-out; with one, the highlight
// rolls off and the shape survives it.
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.15;
// The sun casts a shadow, and nothing else does. A second casting lamp doubles
// what every frame draws, and a room lit from four sides has no shadow anybody
// believes anyway. What this buys is the cue the room never had: a thing
// standing on the ground looks like it is ON the ground, and a thing that is
// not quite touching looks like that too.
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x070b0d);
scene.fog = new THREE.Fog(0x0a1116, 18, 55);
const avatars = new Map();
const online = document.createElement("p");
online.id = "players-online";
online.setAttribute("aria-live", "polite");
online.hidden = !worldId;
document.querySelector("#panel > header")?.append(online);

function makeAvatar(person) {
  const group = new THREE.Group();
  const cloth = new THREE.MeshStandardMaterial({ color: person.color || "#66b8b2", roughness: .84 });
  const skin = new THREE.MeshStandardMaterial({ color: "#e4bb91", roughness: .9 });
  const part = (geometry, material, x, y, z) => {
    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(x, y, z);
    group.add(mesh);
  };
  part(new THREE.CylinderGeometry(.19, .23, .7, 10), cloth, 0, 1.02, 0);
  part(new THREE.SphereGeometry(.15, 12, 9), skin, 0, 1.55, 0);
  for (const side of [-1, 1]) {
    part(new THREE.CylinderGeometry(.055, .065, .57, 7), cloth, side * .28, 1.00, 0);
    part(new THREE.CylinderGeometry(.075, .08, .67, 7), cloth, side * .11, .34, 0);
  }
  const canvas = document.createElement("canvas");
  canvas.width = 256; canvas.height = 64;
  const ink = canvas.getContext("2d");
  ink.fillStyle = "#101b27dd"; ink.fillRect(0, 0, 256, 64);
  ink.fillStyle = "#ffffff"; ink.font = "bold 24px sans-serif";
  ink.textAlign = "center"; ink.textBaseline = "middle";
  ink.fillText(person.name || "Player", 128, 32, 240);
  const label = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas),
                                                           transparent: true, depthWrite: false }));
  label.position.y = 1.95;
  label.scale.set(1.3, .33, 1);
  group.add(label);
  scene.add(group);
  return group;
}

function showPlayers(players) {
  if (!playerId || !Array.isArray(players)) return;
  const seen = new Set();
  for (const person of players) {
    if (person.id === playerId || person.id === watchedId || !person.pose?.eyes_m) continue;
    seen.add(person.id);
    let avatar = avatars.get(person.id);
    if (!avatar) { avatar = makeAvatar(person); avatars.set(person.id, avatar); }
    const eye = person.pose.eyes_m;
    avatar.position.set(eye[0], eye[1] - 1.62, eye[2]);
    const f = person.pose.facing || [0, 0, -1];
    avatar.rotation.y = Math.atan2(-f[0], -f[2]);
  }
  for (const [id, avatar] of avatars) {
    if (seen.has(id)) continue;
    scene.remove(avatar);
    avatar.traverse((part) => { part.geometry?.dispose(); part.material?.map?.dispose(); part.material?.dispose(); });
    avatars.delete(id);
  }
  online.textContent = `${playerName || "You"} · ${seen.size + 1} here`;
}

const camera = new THREE.PerspectiveCamera(72, 1, 0.05, 300);
// ZOOM. The owner, 2026-09-26: "i need a slider that lets me zoom in and out
// of a world to see things better." It is the field of view and nothing more:
// where you stand does not move, so what you can reach, dig, pick up and put
// down is exactly what it was at 1x. A camera that moved instead would change
// all of that quietly, and reach is measured from the eye (world.js, aim).
//
// The slider is in MAGNIFICATION because that is the number a person means by
// zoom -- bigger as things get bigger. 72 degrees is the view at 1x, and the
// rest follows from it: half the field's tangent divided by the magnification.
const FOV_AT_ONE = 72;
const ZOOM_LEAST = 0.7, ZOOM_MOST = 4;
function fovFor(mag) {
  const half = Math.tan((FOV_AT_ONE * Math.PI / 180) / 2) / mag;
  return 2 * Math.atan(half) * 180 / Math.PI;
}
function setZoom(mag) {
  world.zoom = clamp(mag, ZOOM_LEAST, ZOOM_MOST);
  camera.fov = fovFor(world.zoom);
  camera.updateProjectionMatrix();
  const slider = $("zoom-range"), said = $("zoom-said");
  if (slider && slider.value !== String(world.zoom)) slider.value = String(world.zoom);
  if (said) said.textContent = `${world.zoom.toFixed(1)}\u00d7`;
}
// Eye height. A person, not a drone: the scale of the room reads wrong from
// anywhere else, and a 60 mm ball looks like a boulder from 300 mm up.
const EYE = 1.62;
camera.position.set(0, EYE, 2.6);

// Lit so that a dark rubber ball on a dark floor is still an object. The sky
// light does most of it, because a room lit by one lamp has half of every
// object in shadow and the shape of a thing is what you are trying to see.
//
// The sky's share of that is smaller than it was, because the sky is now also
// something to REFLECT (skyEnvironment) and the two would otherwise be counted
// twice. The sun's is larger, because it is the one that casts and a shadow
// only reads as a shadow when the light making it leads.
const sky = new THREE.HemisphereLight(0xcfe3f2, 0x1a2830, 0.85);
scene.add(sky);
const key = new THREE.DirectionalLight(0xfff2dd, 2.0);
key.name = "sun-light";
key.position.set(4, 8, 5);
scene.add(key);
// A directional light shines from its position towards its target, so the
// target has to be in the scene for the light to be aimed at all.
scene.add(key.target);
const rim = new THREE.DirectionalLight(0x8cc0ff, 0.45);
rim.position.set(-6, 4, -5);
scene.add(rim);
const fill = new THREE.DirectionalLight(0xffffff, 0.22);
fill.position.set(0, 2, 8);
scene.add(fill);
const KEY_AT = key.position.clone();
const KEY_LIGHT = key.intensity, SKY_LIGHT = sky.intensity, RIM_LIGHT = rim.intensity;
const FILL_LIGHT = fill.intensity;
// A distant disc follows the native sun direction. It contributes no energy;
// nearer terrain can obscure it, and it disappears below the horizon.
const sunDisc = new THREE.Mesh(new THREE.SphereGeometry(0.85, 20, 12),
  new THREE.MeshBasicMaterial({ color: 0xfff0c4, fog: false,
    toneMapped: false, depthWrite: false }));
sunDisc.name = "sun-disc";
sunDisc.visible = false;
scene.add(sunDisc);
const sunHalo = new THREE.Mesh(new THREE.SphereGeometry(1.7, 20, 12),
  new THREE.MeshBasicMaterial({ color: 0xffdf89, fog: false, toneMapped: false,
    transparent: true, opacity: 0.12, depthWrite: false }));
sunHalo.name = "sun-halo";
sunHalo.visible = false;
scene.add(sunHalo);
const sunDirection = new THREE.Vector3();

// Underground it is dark (docs/machine-world.md, "Light underground").
//
// The three daylight lights are directional and the hill does not stop them: a
// tunnel drawn from the inside was lit as brightly as the meadow above it, so an
// electric lamp in it was decoration. So the daylight is kept in one place --
// what the sun says it should be, in `daylight` -- and what reaches the eye is
// that turned down by how much rock is over it: out by half a metre of rock,
// nearly out by two. It is cheap, it is read from the same runs the walls are
// drawn from, so it agrees with what you can see, and it leaves the place lit by
// whatever somebody has hung there.
//
// It is the EYE's cover, not each thing's, so the meadow seen through the adit
// mouth darkens with you. That is the price of doing this with the scene's own
// lights rather than per fragment, and standing in a 1.75 m adit there is not
// much of the meadow to see anyway.
const COVER_DARK_M = 2.0;
const daylight = { key: KEY_LIGHT, sky: SKY_LIGHT, rim: RIM_LIGHT, fill: FILL_LIGHT };
let underCover = 1;
function applyDaylight() {
  key.intensity = daylight.key * underCover;
  // A little residual sky, so a mine with no lamp in it is gloom and not a black
  // screen: you can still find your way back out towards the daylight.
  sky.intensity = daylight.sky * Math.max(0.05, underCover);
  rim.intensity = daylight.rim * underCover;
  fill.intensity = daylight.fill * underCover;
}
function daylightUnderCover(eye) {
  const over = coverOver(eye.x, eye.y, eye.z);
  underCover = Math.max(0.04, 1 - Math.min(1, over / COVER_DARK_M));
  applyDaylight();
  return underCover;
}

// Every lamp the engine reports, as a light of its own (LiveLamp): a point light
// where the lamp is, as bright as the lumens it is giving, and a small glowing
// bead so you can see the fitting itself. A lamp that is off, or whose store is
// flat, has the bead and no light.
//
// The lights are a POOL of a fixed size, not one per lamp. Three.js compiles the
// number of lights into every material, so a light appearing or going out
// rebuilds every shader in the scene -- a lamp flickering as its battery runs
// down would have stuttered the whole room. Eight lights sit in the scene from
// the start and are handed to the eight lit lamps nearest the eye, so the count
// never changes; the rest of a big installation is beads, which cost nothing.
const LAMPS_LIT_MOST = 8;
const lights = new THREE.Group();
lights.name = "lamps";
scene.add(lights);
const lampPool = [];
for (let i = 0; i < LAMPS_LIT_MOST; ++i) {
  const light = new THREE.PointLight(0xfff1d0, 0, 1, 2);
  lights.add(light);
  lampPool.push(light);
}
const lampParts = new Map();
const LAMP_BEAD = new THREE.MeshBasicMaterial({ color: 0xfff0c8 });
const LAMP_DARK = new THREE.MeshBasicMaterial({ color: 0x4a4a44 });
// A drawn line is one pixel wide whatever the distance, which in a dark heading
// is all but invisible. The run is a tube of 8 mm instead -- about what twin
// 4 mm2 in its sheath measures -- so it reads as a cable somebody hung.
const CABLE_LOOK = new THREE.MeshStandardMaterial({ color: 0x2a2a30, roughness: 0.85, metalness: 0.0 });
const CABLE_R = 0.008;
function cableTube(run) {
  const points = run.map((at) => new THREE.Vector3(at[0], at[1], at[2]));
  const along = new THREE.CatmullRomCurve3(points, false, "catmullrom", 0.0);
  return new THREE.TubeGeometry(along, Math.max(8, points.length * 6), CABLE_R, 5, false);
}

// The fittings and the runs of cable: with every step that carries machines,
// because a lamp on a machine moves with it.
function dressLights(block) {
  const lamps = (block && block.lamps) || [];
  const cables = (block && block.cables) || [];
  const seen = new Set();
  for (const lamp of lamps) {
    if (!lamp || !Array.isArray(lamp.at_m)) continue;
    const key_of = `lamp:${lamp.id}`;
    seen.add(key_of);
    let part = lampParts.get(key_of);
    if (!part) {
      const bead = new THREE.Mesh(new THREE.SphereGeometry(0.06, 10, 8), LAMP_DARK);
      lights.add(bead);
      part = { bead };
      lampParts.set(key_of, part);
    }
    part.bead.position.set(lamp.at_m[0], lamp.at_m[1], lamp.at_m[2]);
    part.bead.material = lamp.lit ? LAMP_BEAD : LAMP_DARK;
  }
  for (const cable of cables) {
    if (!cable || !Array.isArray(cable.run_m) || cable.run_m.length < 2) continue;
    const key_of = `cable:${cable.id}`;
    seen.add(key_of);
    let part = lampParts.get(key_of);
    if (!part) {
      const line = new THREE.Mesh(cableTube(cable.run_m), CABLE_LOOK);
      line.castShadow = false;
      lights.add(line);
      lampParts.set(key_of, { line, points: cable.run_m.length });
    } else if (part.points !== cable.run_m.length) {
      part.line.geometry.dispose();
      part.line.geometry = cableTube(cable.run_m);
      part.points = cable.run_m.length;
    }
  }
  for (const [key_of, part] of lampParts) {
    if (seen.has(key_of)) continue;
    for (const thing of [part.bead, part.line]) {
      if (!thing) continue;
      lights.remove(thing);
      if (thing.geometry) thing.geometry.dispose();
    }
    lampParts.delete(key_of);
  }
  aimLamps();
}

// The powered breaker in your hand, if you are holding one (LiveBreaker): the
// room's breaker whose part is the thing the hand has. A breaker is a compound,
// so its chisel's body may be a part of the group the hand holds.
function breakerInHand() {
  const held = world.held && world.held.name;
  if (!held) return null;
  const mine = (world.machines && world.machines.breakers) || [];
  return mine.find((b) => b && (b.body === held || sameThing(b.body, held))) || null;
}

// Two names for one thing: a product installed as exact bodies is a group whose
// parts share a root name, so "breaker: chisel" and "breaker" are the same
// thing to a hand (docs, "Same name, several bodies").
function sameThing(a, b) {
  if (!a || !b) return false;
  const root = (n) => String(n).split(":")[0].trim();
  return root(a) === root(b);
}

// The lamp and the store on a thing, for wiring: which of the room's fittings
// and batteries belong to the thing you are looking at.
function lampOn(name) {
  const lamps = (world.machines && world.machines.lamps) || [];
  return lamps.find((l) => l && (l.body === name || sameThing(l.body, name))) || null;
}
function storeOn(name) {
  const stores = (world.machines && world.machines.stores) || [];
  return stores.find((s) => s && (s.body === name || sameThing(s.body, name))) || null;
}

// A run of cable being paid out: where it started, and where you have walked
// since. The run follows your feet, so going the long way round really does
// cost you volts (docs/machine-world.md, "Light underground").
const CABLE_STEP_M = 0.6;
world.laying = null;
function layCable(from, store) {
  world.laying = { store, points: [from.slice()] };
}
function payOutCable() {
  if (!world.laying) return;
  const at = [camera.position.x, standingOn(camera.position.x, camera.position.z, camera.position.y) + 0.06,
              camera.position.z];
  const last = world.laying.points[world.laying.points.length - 1];
  if (Math.hypot(at[0] - last[0], at[1] - last[1], at[2] - last[2]) < CABLE_STEP_M) return;
  if (world.laying.points.length > 250) return;    // the engine takes 256 points
  world.laying.points.push(at);
}

// Which lit lamps get one of the pool's lights: the nearest to the eye. Every
// frame, because the eye moves between steps -- walking past a string of lamps
// should not wait for the next reply to light the one you have reached.
function aimLamps() {
  const lamps = (world.machines && world.machines.lamps) || [];
  const eye = camera.position;
  const near = lamps.filter((l) => l && l.lit && Array.isArray(l.at_m) && Number(l.lumens) > 0)
    .map((l) => ({ l, away: Math.hypot(l.at_m[0] - eye.x, l.at_m[1] - eye.y, l.at_m[2] - eye.z) }))
    .sort((a, b) => a.away - b.away).slice(0, LAMPS_LIT_MOST);
  for (let i = 0; i < lampPool.length; ++i) {
    const light = lampPool[i];
    const lamp = near[i] ? near[i].l : null;
    if (!lamp) { light.intensity = 0; continue; }
    light.position.set(lamp.at_m[0], lamp.at_m[1], lamp.at_m[2]);
    // Lumens are not three.js intensity and no number here pretends to be
    // photometric. A 20 W LED at 120 lm/W is 2400 lm, which reads right in a
    // 1.75 m heading at about 2.4, and reaching about 6 m as the root of the
    // lumens -- far enough to see the face, not the whole mine.
    const lm = Math.max(0, Number(lamp.lumens) || 0);
    light.intensity = lm / 1000;
    light.distance = Math.max(1.5, Math.sqrt(lm) / 8);
  }
}

// The sun's shadow, and why it follows the person.
//
// One lamp over a sixty-metre valley spreads its shadow map so thin that a
// cart's wheel and the daylight under it land in the same texel, and the whole
// thing turns to mud. So the shadow is drawn for a box a few strides across
// that is kept over whoever is looking: what is near enough to matter is
// sharp, and what is beyond the box is drawn unshadowed, which at that
// distance nobody reads as missing.
const SHADOW_REACH_M = 15;     // half the box, each side of the person
const SHADOW_LAMP_M = 45;      // how far off the lamp stands along the sun
const SHADOW_AHEAD_M = 5;      // the box set this far ahead of the view
key.shadow.mapSize.set(2048, 2048);
key.shadow.camera.left = -SHADOW_REACH_M;
key.shadow.camera.right = SHADOW_REACH_M;
key.shadow.camera.top = SHADOW_REACH_M;
key.shadow.camera.bottom = -SHADOW_REACH_M;
key.shadow.camera.near = 1;
key.shadow.camera.far = SHADOW_LAMP_M + 55;
// Acne against peter-panning. The bias moves the depth comparison and the
// normal bias moves the sample along the surface's own normal; a cell wall
// forty millimetres thick needs the second one or it stripes itself in its own
// shadow, and too much of the first lifts every shadow off its object's feet.
key.shadow.bias = -0.0004;
key.shadow.normalBias = 0.03;
key.shadow.camera.updateProjectionMatrix();

const SUN_TOWARD = new THREE.Vector3(0, 1, 0);
const SUN_OVER = new THREE.Vector3(), SUN_LEFT = new THREE.Vector3();
const SUN_FRAME = new THREE.Matrix4();
const SUN_RIGHT = new THREE.Vector3(), SUN_UP = new THREE.Vector3();
const ORIGIN = new THREE.Vector3(), STRAIGHT_UP = new THREE.Vector3(0, 1, 0);
const SIDEWAYS = new THREE.Vector3(0, 0, 1);

function followSun() {
  const toward = world.sun?.toward;
  sunDisc.visible = Array.isArray(toward) && toward.length === 3
    && toward.every(Number.isFinite) && toward[1] > 0;
  sunHalo.visible = sunDisc.visible;
  if (sunDisc.visible) {
    sunDirection.fromArray(toward).normalize();
    sunDisc.position.copy(camera.position).addScaledVector(sunDirection, 180);
    sunHalo.position.copy(sunDisc.position);
  }
  // Whoever moved the lamp last says where the sun is: the day (lightFromSun),
  // an expedition (gameplay.js), or the room's own default. All of them mean
  // its position as a DIRECTION from the middle of the room, so that is how it
  // is read -- and then the lamp is moved to stand over the person, because a
  // shadow map has to be spent where somebody is looking.
  if (!key.position.equals(SUN_LEFT) && key.position.lengthSq() > 1e-9)
    SUN_TOWARD.copy(key.position).normalize();
  // Under the horizon it lights nothing, and a shadow map drawn for a lamp of
  // no brightness is a sixth of a frame spent on nothing at all.
  key.castShadow = key.intensity > 0.02 && SUN_TOWARD.y > 0.04;
  if (!key.castShadow) return;
  SUN_OVER.copy(camera.position).addScaledVector(forwardVector().setY(0).normalize(),
                                                 SHADOW_AHEAD_M);
  // Snapped to the shadow map's own grid. A box that slides with the person by
  // less than a texel makes every shadow edge crawl, which reads as the room
  // being unsteady rather than as the person walking; stepped a whole texel at
  // a time it holds still.
  SUN_FRAME.lookAt(SUN_TOWARD, ORIGIN,
                   Math.abs(SUN_TOWARD.y) > 0.99 ? SIDEWAYS : STRAIGHT_UP);
  SUN_RIGHT.setFromMatrixColumn(SUN_FRAME, 0);
  SUN_UP.setFromMatrixColumn(SUN_FRAME, 1);
  const texel = 2 * SHADOW_REACH_M / key.shadow.mapSize.x;
  const across = Math.round(SUN_OVER.dot(SUN_RIGHT) / texel) * texel;
  const up = Math.round(SUN_OVER.dot(SUN_UP) / texel) * texel;
  const along = SUN_OVER.dot(SUN_TOWARD);
  SUN_OVER.copy(ORIGIN).addScaledVector(SUN_RIGHT, across)
          .addScaledVector(SUN_UP, up).addScaledVector(SUN_TOWARD, along);
  key.position.copy(SUN_OVER).addScaledVector(SUN_TOWARD, SHADOW_LAMP_M);
  SUN_LEFT.copy(key.position);
  key.target.position.copy(SUN_OVER);
  key.target.updateMatrixWorld();
}

// Something for a polished surface to reflect.
//
// Metalness has no meaning without an environment. A mirror with nothing
// around it is black, which is why iron at 0.92 metal read as a flat grey
// cut-out and glass read as a tinted sheet: they were reflecting a room that
// was not there. This gives them the cheapest honest one there is -- the
// room's own sky over the room's own ground, blurred to nothing but a gradient
// -- and rebuilds it only when the sky changes colour, which under a day is a
// few times a minute and otherwise never.
const SKY_ACROSS = 32;
const skyPixels = new Uint8Array(SKY_ACROSS * (SKY_ACROSS / 2) * 4);
const skySource = new THREE.DataTexture(skyPixels, SKY_ACROSS, SKY_ACROSS / 2);
skySource.mapping = THREE.EquirectangularReflectionMapping;
skySource.colorSpace = THREE.SRGBColorSpace;
// A DataTexture is uploaded without a flip, so its first row is what the
// sampler reads at v = 0 -- and three.js puts v = 0 at the BOTTOM of an
// equirectangular sky (equirectUv: v = asin(dir.y)/PI + 0.5). Row zero is
// therefore straight down, and the last row is straight up.
skySource.flipY = false;
let skyBlur = null;
let skyMade = "";
const skyAbove = new THREE.Color(), skyBelow = new THREE.Color();
const skyBand = new THREE.Color(), skyRGB = { r: 0, g: 0, b: 0 };

function skyEnvironment() {
  // Built from what the room is lit BY, and not from what is drawn behind it.
  // A room without a day has a near-black backdrop and a bright sky light over
  // it, and reflecting the backdrop would tell every polished surface in the
  // place that it was standing in the dark -- which is exactly the flat grey
  // this was meant to fix. The hemisphere light is the room's own statement
  // about what is overhead and what is underfoot, so that is what it reflects.
  const lit = Math.min(1, sky.intensity);
  const mark = `${sky.color.getHex()}:${GROUND_COLOURS[1].getHex()}:${lit.toFixed(2)}`;
  if (mark === skyMade) return;
  skyMade = mark;
  skyAbove.copy(sky.color).multiplyScalar(lit);
  // Underfoot is the ground the room is actually standing on, dimmed the way
  // the sky's own downward colour is: bare soil throws back soil.
  skyBelow.copy(GROUND_COLOURS[1]).lerp(sky.groundColor, 0.45).multiplyScalar(lit);
  const rows = SKY_ACROSS / 2;
  for (let y = 0; y < rows; ++y) {
    // Row zero is straight down and the last row straight up (see flipY).
    const up = y / (rows - 1);
    skyBand.copy(skyBelow).lerp(skyAbove, up * up * (3 - 2 * up));
    // Written as the bytes of an sRGB texture, which is what it is tagged as.
    // Handing it the working colour space's own numbers would bake the sky in
    // about half as bright as it looks.
    skyBand.getRGB(skyRGB, THREE.SRGBColorSpace);
    for (let x = 0; x < SKY_ACROSS; ++x) {
      const at = (y * SKY_ACROSS + x) * 4;
      skyPixels[at] = Math.round(255 * Math.min(1, Math.max(0, skyRGB.r)));
      skyPixels[at + 1] = Math.round(255 * Math.min(1, Math.max(0, skyRGB.g)));
      skyPixels[at + 2] = Math.round(255 * Math.min(1, Math.max(0, skyRGB.b)));
      skyPixels[at + 3] = 255;
    }
  }
  skySource.needsUpdate = true;
  const made = skyPMREM().fromEquirectangular(skySource);
  if (skyBlur) skyBlur.dispose();
  skyBlur = made;
  scene.environment = made.texture;
  // Enough to put something in a reflection and not so much that it washes the
  // lamps out: the sun and the sky still say where the light comes from.
  scene.environmentIntensity = 0.6;
}

let pmrem = null;
function skyPMREM() {
  if (!pmrem) pmrem = new THREE.PMREMGenerator(renderer);
  return pmrem;
}
// The sky's light at night, and the rim's: dim, but enough to see what is in
// the room by.
const SKY_NIGHT = 0.035, RIM_NIGHT = 0.015, FILL_NIGHT = 0.01;
// The sky behind the room under a sun with a day: a day's blue with the sun
// well up, red as it nears the horizon, and the night's black the page has
// always had. A room without a day keeps that black.
const NIGHT_SKY = scene.background.clone(), NIGHT_FOG = scene.fog.color.clone();
const DAY_SKY = new THREE.Color(0x5d7f93), LOW_SKY = new THREE.Color(0x9a6444);
const skyTint = new THREE.Color();
let skyTinted = false;

// A room with a sun (docs/machine-world.md, "Solar panels") is lit from where
// the engine has it, so the side of a panel the light falls on is the side the
// engine charges it from; one without keeps the lamp it had.
//
// A sun with a day ("A day for the sun") goes down. Its lamp is as bright as
// the sunlight the engine has reaching the ground against what it gives
// overhead, so it reddens into nothing at sunset; the sky's light goes on for
// a while after, as twilight does, falling to a night's by the time the sun is
// six degrees under the horizon. Presentation only: what a panel collects is
// the engine's, from the engine's sun.
function lightFromSun(sun) {
  world.sun = sun || null;
  if (sun && Array.isArray(sun.toward) && sun.toward[1] > 0) {
    key.position.set(sun.toward[0] * 20, sun.toward[1] * 20, sun.toward[2] * 20);
  } else {
    key.position.copy(KEY_AT);
  }
  if (sun && sun.day_s > 0) {
    const share = sun.zenith_irradiance_w_m2 > 0
      ? Math.min(1, Math.max(0, sun.irradiance_w_m2 / sun.zenith_irradiance_w_m2)) : 0;
    const dusk = Math.min(1, Math.max(0, (sun.elevation_deg + 6) / 12));
    daylight.key = sun.toward[1] > 0 ? KEY_LIGHT * share : 0;
    key.color.setRGB(1, 0.62 + 0.33 * share, 0.45 + 0.42 * share);
    daylight.sky = SKY_NIGHT + (SKY_LIGHT - SKY_NIGHT) * dusk;
    daylight.rim = RIM_NIGHT + (RIM_LIGHT - RIM_NIGHT) * dusk;
    daylight.fill = FILL_NIGHT + (FILL_LIGHT - FILL_NIGHT) * dusk;
    applyDaylight();
    skyTint.copy(LOW_SKY).lerp(DAY_SKY, Math.min(1, Math.max(0, sun.elevation_deg / 20)));
    scene.background.copy(NIGHT_SKY).lerp(skyTint, dusk);
    scene.fog.color.copy(NIGHT_FOG).lerp(skyTint, dusk);
    skyTinted = true;
  } else {
    daylight.key = KEY_LIGHT;
    key.color.setHex(0xfff2dd);
    daylight.sky = SKY_LIGHT;
    daylight.rim = RIM_LIGHT;
    daylight.fill = FILL_LIGHT;
    applyDaylight();
    if (skyTinted) {
      scene.background.copy(NIGHT_SKY);
      scene.fog.color.copy(NIGHT_FOG);
      skyTinted = false;
    }
  }
}

// What a break cost, in a sentence (docs/what-a-break-costs.md): the energy
// that left with the bonds the lattice removed, over the crack they stand for,
// and what that is per square metre against what the material itself takes to
// crack. The second number is the one to watch: today the room charges the
// material's own only under the energy-scaled law, and even then what leaves is
// more than the charge.
function breakCost(cost) {
  if (!cost || !cost.broken_bonds) return "";
  const material = (cost.material || "it").replace(/_/g, " ");
  // A crack in glass costs single joules, one in iron thousands, so the
  // small numbers keep their decimals: "0.19 J" says something, "0 J" does not.
  const each = (j) => (j >= 10 ? Math.round(j).toLocaleString() : j.toFixed(1));
  return ` It cost ${cost.removed_energy_j >= 1000 ? `${(cost.removed_energy_j / 1000).toFixed(2)} kJ`
    : cost.removed_energy_j >= 10 ? `${Math.round(cost.removed_energy_j)} J`
    : `${cost.removed_energy_j.toFixed(2)} J`}`
    + ` over ${(cost.crack_area_m2 * 1e4).toFixed(0)} cm² of new crack:`
    + ` ${each(cost.crack_energy_j_m2)} J/m², where ${material} itself takes`
    + ` ${each(cost.declared_energy_j_m2)} J/m² and this room charges`
    + ` ${each(cost.law_energy_j_m2)} (${cost.failure_law}).`
    // A break can only spend what the blow and the thing itself brought. When
    // that runs out the break stops there, and saying so is the difference
    // between "it came apart this far" and "it came apart".
    + (cost.spent_it_all
        ? ` That was everything it had to spend (${each(cost.available_energy_j)} J), so it stopped there.`
        : "");
}

// The time of day under a sun with a day, as a clock and where the sun is:
// "14:05, the sun 38° up", or "21:40, night". Nothing for a sun without one.
function dayWords(sun) {
  if (!sun || !(sun.day_s > 0)) return "";
  const minutes = Math.floor(sun.hour * 60) % 1440;
  const clock = `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
  return sun.elevation_deg > 0 ? `${clock}, the sun ${Math.round(sun.elevation_deg)}° up` : `${clock}, night`;
}
const expedition = expeditionUI({
  scene, camera, sun: key,
  request: action => api("/api/world/gameplay", {session: world.session, op: "action", action}),
  pause: value => { world.paused = value; world.lastTick = 0; },
  isPaused: () => world.paused,
  wait: async () => {
    while (world.busy) await new Promise(resolve => setTimeout(resolve, 20));
    const state = await act("step", {dt: 1/120, n: 120});
    world.clock = state.t;
    expedition.update(state.gameplay);
    draw(state);
    if (state.water) drawWater(state.water);
    return state;
  }
});

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
floor.receiveShadow = true;
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
                        new THREE.Color(0xc9ad7c),   // sand
                        new THREE.Color(0x8a6b4a),   // loose soil: soil that was dug
                        new THREE.Color(0x8d8274),   // weathered rock: paler, rotted
                        new THREE.Color(0x5d6b6e),   // clay: the grey-green weak bed
                        new THREE.Color(0x4e6b54),   // ore: the green of a fresh copper vein
                        new THREE.Color(0xa8622c)];  // oxidised ore: the rust a vein shows
const WATER_SHALLOW = new THREE.Color(0x58a7ad), WATER_DEEP = new THREE.Color(0x163f63);
// Ground nobody has been near yet (machine_sight): drawn, because the lie of the
// land is the shape of the room and hiding it would leave holes in the world, but
// drawn as unknown -- flat and colourless -- so the ground that HAS been seen
// reads as the part of the room anyone knows anything about.
const GROUND_UNSEEN = new THREE.Color(0x2b2f36);
const FOAM_COUNT = 700;
const WATER_EASE_MS = 260;
const ground = {
  grid: null, heights: null, surfaces: null, view: null,
  // What every column is MADE of, all the way down, as the engine sends it: the
  // runs, held the way the engine holds them -- where each column's runs start,
  // what each run is, and the height it reaches. This is what a cut face is
  // drawn from (buildFaces).
  runs: null, floor: 0, faces: null, facesStale: false,
  // What has been seen: a coarse grid of its own, a byte a cell, as the server
  // keeps it. Null until the server sends one, and then every cell is drawn
  // either as its surface or as unknown.
  seen: null, seenGrid: null,
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
  for (const key of ["mesh", "water", "foam", "faces"]) {
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

// Whether this ground has been seen. Without a record everything has: a room
// with no sight block is one nothing keeps fog for.
function groundSeen(index) {
  if (!ground.seen || !ground.seenGrid || !ground.grid) return true;
  const { nx, dx, x0, z0 } = ground.grid;
  const x = x0 + (index % nx) * dx, z = z0 + Math.floor(index / nx) * dx;
  const s = ground.seenGrid;
  const i = Math.floor((x - s.x0_m) / s.cell_m), j = Math.floor((z - s.z0_m) / s.cell_m);
  if (i < 0 || j < 0 || i >= s.nx || j >= s.nz) return true;
  return ground.seen[j * s.nx + i] !== 0;
}

function paintGround(colours, index) {
  // What the TOP of the column is made of, from the runs: a vein that reaches
  // the surface is a stain on the hillside you can see from across the valley,
  // and it cannot be if the ground is painted from three surface kinds. The
  // engine's own `surfaces` is the fallback, and what the physics still uses.
  const runs = ground.runs;
  const kind = runs && runs.count[index] > 0
    ? runs.kind[index * runs.stride + runs.count[index] - 1] : ground.surfaces[index];
  const c = groundSeen(index) ? (GROUND_COLOURS[kind] || GROUND_COLOURS[1]) : GROUND_UNSEEN;
  colours[3 * index] = c.r; colours[3 * index + 1] = c.g; colours[3 * index + 2] = c.b;
}

// ---- what the ground is made of, and the faces a cut exposes ----------------
//
// The engine sends every column's RUNS: a material and the height it reaches,
// bottom to top (Environment::runsPacked). A column is rock, the soil that
// formed on it, and the loose mixture on top -- and will be strata and veins.
// Heights come over as millimetres above the ground's floor.
// Held at a fixed stride -- room for the same number of runs under every column
// -- so that the rectangle a dig changes can be written straight in. A dig takes
// runs away and a heap adds one, and if a column ever arrives with more runs
// than there is room for, the room grows.
function decodeRuns(raw, at, into, c, stride) {
  const count = raw[at++];
  into.count[c] = count;
  for (let k = 0; k < count; ++k) {
    if (k < stride) {
      into.kind[c * stride + k] = raw[at];
      into.top[c * stride + k] = ground.floor + (raw[at + 1] | (raw[at + 2] << 8)) / 1000;
    }
    at += 3;
  }
  return at;
}

function runsRoom(raw, cells) {
  let most = 0, at = 0;
  for (let c = 0; c < cells && at < raw.length; ++c) {
    most = Math.max(most, raw[at]);
    at += 1 + 3 * raw[at];
  }
  return Math.max(4, most);
}

function takeRuns(block, cells) {
  const raw = bytesOf(block.runs_b64);
  if (!raw.length) return null;
  const stride = runsRoom(raw, cells);
  const runs = { stride, count: new Uint8Array(cells),
                 kind: new Uint8Array(cells * stride), top: new Float32Array(cells * stride) };
  let at = 0;
  for (let c = 0; c < cells && at < raw.length; ++c) at = decodeRuns(raw, at, runs, c, stride);
  return runs;
}

// One column of a changed rectangle into the runs the page holds. `raw` is the
// rectangle's own packing and `nth` which column of it this is.
function patchRuns(c, raw, nth) {
  const runs = ground.runs;
  if (!runs) return;
  let at = 0;
  for (let k = 0; k < nth; ++k) at += 1 + 3 * raw[at];
  if (raw[at] > runs.stride) growRuns(raw[at]);
  decodeRuns(raw, at, ground.runs, c, ground.runs.stride);
}

function growRuns(needed) {
  const was = ground.runs, cells = was.count.length, stride = Math.max(needed, was.stride + 2);
  const runs = { stride, count: was.count,
                 kind: new Uint8Array(cells * stride), top: new Float32Array(cells * stride) };
  for (let c = 0; c < cells; ++c)
    for (let k = 0; k < was.stride; ++k) {
      runs.kind[c * stride + k] = was.kind[c * was.stride + k];
      runs.top[c * stride + k] = was.top[c * was.stride + k];
    }
  ground.runs = runs;
}

// What is underfoot at a point for somebody whose eye is at `y`: the top of the
// highest SOLID run at or below them. On open ground that is the ground. Inside
// a working it is the working's floor -- the hill over their head is not
// something they are standing on, and asking the height field alone (which only
// knows the hill) is what used to shove anyone who went in back out on top of it.
const RUN_VOID = 8;
function standingOn(x, z, y) {
  const g = ground.grid, runs = ground.runs;
  if (!g || !runs) return groundAt(x, z);
  const i = Math.round((x - g.x0) / g.dx), j = Math.round((z - g.z0) / g.dx);
  if (i < 0 || j < 0 || i >= g.nx || j >= g.nz) return groundAt(x, z);
  const c = j * g.nx + i;
  for (let k = runs.count[c] - 1; k >= 0; --k) {
    const at = c * runs.stride + k;
    if (runs.kind[at] === RUN_VOID) continue;
    if (runs.top[at] <= y + 0.05) return runs.top[at];
  }
  return groundAt(x, z);
}

// Open terrain follows the collider's triangles, not the nearest column's
// stair steps. Underground support still comes from the solid/void runs.
function walkingSupport(x, z, feet) {
  const surface = groundAt(x, z), g = ground.grid, runs = ground.runs;
  if (!g || !runs) return surface;
  const i = Math.round((x-g.x0)/g.dx), j = Math.round((z-g.z0)/g.dx);
  if (i<0 || j<0 || i>=g.nx || j>=g.nz) return surface;
  const c = j*g.nx+i;
  let outer = -Infinity;
  for (let k=runs.count[c]-1;k>=0;k--) {
    const at=c*runs.stride+k;
    if (runs.kind[at]!==RUN_VOID) { outer=runs.top[at]; break; }
  }
  if (Math.abs(outer-ground.heights[c])<.002 && feet>=Math.max(surface,outer)-.5)
    return surface;
  return standingOn(x,z,feet+.2);
}

// How much rock is over a point: 0 in the open, and the thickness of every
// solid run above it where it is inside a working. This is what makes a mine
// dark -- see daylightUnderCover -- and it is read from the same runs the walls
// are drawn from, so it agrees with what you can see.
function coverOver(x, y, z) {
  const g = ground.grid, runs = ground.runs;
  if (!g || !runs) return 0;
  const i = Math.round((x - g.x0) / g.dx), j = Math.round((z - g.z0) / g.dx);
  if (i < 0 || j < 0 || i >= g.nx || j >= g.nz) return 0;
  const c = j * g.nx + i;
  let over = 0;
  for (let k = 0; k < runs.count[c]; ++k) {
    const at = c * runs.stride + k;
    const below = k > 0 ? runs.top[c * runs.stride + k - 1] : ground.floor;
    if (runs.top[at] <= y) continue;                       // entirely under the point
    if (runs.kind[at] === RUN_VOID) continue;              // a hole is not cover
    over += runs.top[at] - Math.max(below, y);
  }
  return over;
}

// The strata a step cuts, drawn on the step the collider already has.
//
// The ground is ONE surface. Where a dig leaves half a metre of drop between two
// columns, the collider spans it with a steep triangle and the page painted that
// triangle the colour of whatever was on top of the column -- so the wall of your
// own pit came out the colour of the grass above it, and there was nowhere for a
// seam to show. These are vertical bands standing in the step, one for each run
// the step cuts through, each in its own material.
//
// They add no surface and nothing stands on them: what things stand on is still
// the ground mesh, and these are drawn with a polygon offset so that where the
// two lie together the band is what you see. Both sides are drawn, because a
// step is looked at from whichever side you are standing on.
// A drop worth drawing is one the ground could not have come to rest at: at
// 0.25 m columns this is 55 degrees, well past the angle any soil or sand stands
// at (30 to 32), so what shows is a cut, a pit's wall or bare rock -- and not
// every gentle step down a hillside, which at a lower threshold covered the
// whole valley in dark chevrons.
const FACE_STEP_M = 0.35;
const FACE_BAND_M = 0.01;      // thinner than this is not a band anyone can see

function buildFaces() {
  ground.facesStale = false;
  if (ground.faces) {
    scene.remove(ground.faces);
    ground.faces.geometry.dispose();
    ground.faces = null;
  }
  const g = ground.grid, runs = ground.runs;
  if (!g || !runs || !ground.heights) return;
  const H = ground.heights, half = g.dx / 2;
  const points = [], colours = [];
  // One band: a vertical quad from `lo` to `hi` in the plane the two columns
  // meet in, across the width of a cell.
  const band = (x0, z0, x1, z1, lo, hi, colour) => {
    points.push(x0, lo, z0, x1, lo, z1, x1, hi, z1,
                x0, lo, z0, x1, hi, z1, x0, hi, z0);
    for (let v = 0; v < 6; ++v) colours.push(colour.r, colour.g, colour.b);
  };
  // The step between two columns, split at the runs of the taller one: what the
  // drop actually cuts through.
  const step = (a, b, along) => {
    const ha = H[a], hb = H[b];
    if (!(Math.abs(ha - hb) > FACE_STEP_M)) return;
    const high = ha > hb ? a : b, lo = Math.min(ha, hb), hi = Math.max(ha, hb);
    const i = high % g.nx, j = (high - i) / g.nx;
    // The plane the two columns meet in: half a cell from the taller one,
    // towards the shorter.
    const toward = high === a ? 1 : -1;
    const cx = g.x0 + i * g.dx + (along ? 0 : toward * half);
    const cz = g.z0 + j * g.dx + (along ? toward * half : 0);
    const [x0, z0, x1, z1] = along ? [cx - half, cz, cx + half, cz] : [cx, cz - half, cx, cz + half];
    const seen = groundSeen(high);
    let from = lo;
    for (let k = 0; k < runs.count[high]; ++k) {
      const at = high * runs.stride + k, to = Math.min(hi, runs.top[at]);
      if (to - from > FACE_BAND_M) {
        band(x0, z0, x1, z1, from, to,
             seen ? (GROUND_COLOURS[runs.kind[at]] || GROUND_COLOURS[1]) : GROUND_UNSEEN);
        from = to;
      }
      if (runs.top[at] >= hi) break;
    }
    // Above the last run there is nothing but the air the ground ends in; a step
    // that reaches higher than the taller column's own top cannot happen.
  };
  // A working: the hole itself, drawn from the inside. Its floor, the roof over
  // it, and a wall wherever the rock beside it is solid -- which is every side
  // the working does not carry on through. The hill above is drawn as it always
  // was: a person outside sees a hillside, and a person inside sees a tunnel.
  const working = (c) => {
    const runs = ground.runs;
    for (let k = 0; k < runs.count[c]; ++k)
      if (runs.kind[c * runs.stride + k] === RUN_VOID)
        return { floor: k > 0 ? runs.top[c * runs.stride + k - 1] : ground.floor,
                 roof: runs.top[c * runs.stride + k],
                 under: k > 0 ? runs.kind[c * runs.stride + k - 1] : 0,
                 over: k + 1 < runs.count[c] ? runs.kind[c * runs.stride + k + 1] : 0 };
    return null;
  };
  const flat = (x0, z0, x1, z1, y, colour) => {
    points.push(x0, y, z0, x1, y, z0, x1, y, z1, x0, y, z0, x1, y, z1, x0, y, z1);
    for (let v = 0; v < 6; ++v) colours.push(colour.r, colour.g, colour.b);
  };
  for (let j = 0; j < g.nz; ++j)
    for (let i = 0; i < g.nx; ++i) {
      const c = j * g.nx + i;
      if (i + 1 < g.nx) step(c, c + 1, false);
      if (j + 1 < g.nz) step(c, c + g.nx, true);
      if (!ground.runs) continue;
      const w = working(c);
      if (!w) continue;
      const seen = groundSeen(c);
      const paint = (kind) => seen ? (GROUND_COLOURS[kind] || GROUND_COLOURS[0]) : GROUND_UNSEEN;
      const x = g.x0 + i * g.dx - half, z = g.z0 + j * g.dx - half;
      flat(x, z, x + g.dx, z + g.dx, w.floor, paint(w.under));
      flat(x, z, x + g.dx, z + g.dx, w.roof, paint(w.over));
      // A wall on each side the working stops at, in what it is cut from.
      const sides = [[1, 0, i + 1 < g.nx], [-1, 0, i > 0], [0, 1, j + 1 < g.nz], [0, -1, j > 0]];
      for (const [di, dj, inside] of sides) {
        const n = inside ? working(c + di + dj * g.nx) : null;
        const lo = n ? Math.min(w.roof, Math.max(w.floor, n.floor)) : w.floor;
        const hi = n ? Math.max(w.floor, Math.min(w.roof, n.roof)) : w.roof;
        // Wall the part of this side the neighbour's hole does not open.
        if (!n || lo > w.floor + FACE_BAND_M)
          band(x + (di > 0 ? g.dx : 0), z + (dj > 0 ? g.dx : 0),
               x + (di !== 0 ? (di > 0 ? g.dx : 0) : g.dx), z + (dj !== 0 ? (dj > 0 ? g.dx : 0) : g.dx),
               w.floor, n ? lo : w.roof, paint(w.under));
        if (n && hi < w.roof - FACE_BAND_M)
          band(x + (di > 0 ? g.dx : 0), z + (dj > 0 ? g.dx : 0),
               x + (di !== 0 ? (di > 0 ? g.dx : 0) : g.dx), z + (dj !== 0 ? (dj > 0 ? g.dx : 0) : g.dx),
               hi, w.roof, paint(w.over));
      }
    }
  if (!points.length) return;
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(points), 3));
  geometry.setAttribute("color", new THREE.BufferAttribute(new Float32Array(colours), 3));
  geometry.computeVertexNormals();
  ground.faces = new THREE.Mesh(geometry, dress(new THREE.MeshStandardMaterial({
    vertexColors: true, roughness: 0.97, metalness: 0.0, side: THREE.DoubleSide,
    polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 }), "ground"));
  ground.faces.receiveShadow = true;
  ground.faces.castShadow = false;
  scene.add(ground.faces);
}

// What has been seen, as the server sends it with a room and with every step it
// changes. Repaints the ground when the edge of what is known has moved, which
// is what makes a machine's going about visibly uncover the room.
function showSeen(block) {
  if (!block || !block.seen_b64) return;
  const was = ground.seen ? ground.seen.length : 0;
  const known = block.known_cells || 0;
  const same = ground.seenGrid && ground.seenGrid.known === known && was === (block.cells || 0);
  ground.seen = bytesOf(block.seen_b64);
  ground.seenGrid = { nx: block.nx, nz: block.nz, cell_m: block.cell_m,
                      x0_m: block.x0_m, z0_m: block.z0_m, known };
  if (!same) repaintSeen();
}

// Every cell's colour again, after the edge of what is known has moved. Only the
// colours: the ground's shape has not changed, so the heights and the normals
// stand.

function repaintSeen() {
  if (!ground.mesh || !ground.grid) return;
  const col = ground.mesh.geometry.attributes.color;
  const count = ground.grid.nx * ground.grid.nz;
  for (let k = 0; k < count; ++k) paintGround(col.array, k);
  col.needsUpdate = true;
  // The faces of a step are coloured by what has been seen too.
  ground.facesStale = true;
}

function drawTerrain(block) {
  clearGround();
  const { nx, nz, cell_m: dx, x0_m: x0, z0_m: z0 } = block.grid;
  ground.grid = { nx, nz, dx, x0, z0 };
  ground.heights = new Float32Array(bytesOf(block.heights_b64).buffer);
  ground.surfaces = bytesOf(block.ground_b64);
  // The runs come over as millimetres above the ground's own floor, which is the
  // level the water block is measured from as well.
  ground.floor = Number(block.floor_m) || 0;
  ground.runs = takeRuns(block, nx * nz);
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
  ground.mesh = new THREE.Mesh(geometry, dress(new THREE.MeshStandardMaterial({
    vertexColors: true, roughness: 0.96, metalness: 0.0 }), "ground"));
  // The ground catches what the room drops on it, and casts too: a valley
  // whose own hills throw no shade at a low sun is a valley with no shape.
  ground.mesh.castShadow = true;
  ground.mesh.receiveShadow = true;
  scene.add(ground.mesh);
  // And the faces of every step in it, in the materials the step cuts through.
  ground.facesStale = true;

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
  // Water catches a shadow and throws none: what a surface does to the light
  // going through it is refraction, and drawing it as a shadow would be a
  // picture of something that is not happening.
  ground.water.receiveShadow = true;
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
  const patched = changed.runs_b64 ? bytesOf(changed.runs_b64) : null;
  const g = ground.grid;
  const pos = ground.mesh.geometry.attributes.position, col = ground.mesh.geometry.attributes.color;
  for (let j = 0; j < nj; ++j)
    for (let i = 0; i < ni; ++i) {
      const k = (j0 + j) * g.nx + (i0 + i);
      ground.heights[k] = heights[j * ni + i];
      ground.surfaces[k] = surfaces[j * ni + i];
      if (patched) patchRuns(k, patched, j * ni + i);
      pos.array[3 * k + 1] = ground.heights[k];
      paintGround(col.array, k);
    }
  pos.needsUpdate = true;
  col.needsUpdate = true;
  ground.mesh.geometry.computeVertexNormals();
  // The step a dig leaves is what the faces are drawn on, so they are stood up
  // again -- once for the frame, however many changes arrive in it.
  ground.facesStale = true;
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
  // Water nobody has seen is not drawn: a lake shows itself when someone comes
  // near enough to see it, as the ground does. NaN is what dry already is here,
  // so unseen water is dry until it is found.
  if (ground.seen && ground.seenGrid)
    for (let k = 0; k < extended.length; ++k) if (!groundSeen(k)) extended[k] = NaN;
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

// Where the person stood, kept for this tab: sessionStorage lasts through a
// reload and goes with the tab. A reload rejoins the room as it stands
// (server.py _rejoin), and puts the person back where they were rather than at
// the valley's view point. Kept when the room has stopped too: a server that
// went away leaves the page with no session, and when it is back it gives the
// room back whole -- the reload after that is the one that most needs it. It
// is only used for a room as it stood (asItStood), so keeping it costs nothing.
function keepView() {
  if (watchedId) return;
  if (!world.scene) return;
  const look = camera.position.clone().add(forwardVector().multiplyScalar(4));
  try {
    sessionStorage.setItem(worldId ? `banjo.view.${worldId}.${world.scene}` : `banjo.view.${world.scene}`,
      JSON.stringify({ eye_m: camera.position.toArray(), look_m: look.toArray() }));
  } catch (_) { /* no storage here: a reload starts at the view point */ }
}
function keptView(scene) {
  try {
    const key = worldId ? `banjo.view.${worldId}.${scene}` : `banjo.view.${scene}`;
    const view = JSON.parse(sessionStorage.getItem(key) || "null");
    return view && Array.isArray(view.eye_m) && Array.isArray(view.look_m) ? view : null;
  } catch (_) { return null; }
}
addEventListener("pagehide", keepView);

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
//
// Two of them, in fact. A body drawn as the hull of its cells carries its
// corner shading in the mesh itself (cellmesh.js), and a material that reads
// that attribute is not the same material as one that does not -- so glass
// drawn as a hull and glass drawn as a box are two shared materials rather
// than one, and each still batches with its own kind.
const MATERIALS = new Map();
const SHADED = new Map();
function look(material, shaded = false) {
  const kept = shaded ? SHADED : MATERIALS;
  const had = kept.get(material);
  if (had) return had;
  const m = MATERIAL_LOOK[material] || { color: 0x9aa6ae, rough: 0.6, metal: 0.1 };
  const options = { color: m.color, roughness: m.rough, metalness: m.metal };
  if (m.clear) { options.transparent = true; options.opacity = 1 - m.clear * 0.55; }
  if (shaded) options.vertexColors = true;
  // Dressed with the substance's own grain (surfaces.js). It is the shared
  // material that is dressed, not the body, so every oak thing in the room
  // still batches together and the grain costs one shader for the lot.
  const made = dress(new THREE.MeshStandardMaterial(options), material);
  kept.set(material, made);
  return made;
}

// The shape a thing was DRAWN TO, as against the cells it is made of.
//
// A room describes a thing as the boxes somebody laid out -- each with a size,
// a place, a turn and a `join` saying which of them are one thing -- and the
// engine compiles those onto its grid and collides the cells. The cells are the
// matter; the boxes are the design; and the difference between them is the
// voxelisation, up to sqrt(3)/2 of a cell, which is 34.6 mm at the forty the
// rooms use. A raked strut is the case that shows it: a board set at an angle
// becomes a staircase of cells, and the staircase is what the page drew.
//
// So a thing that is still WHOLE is drawn as the shape it was drawn to. A thing
// that has broken is drawn from its cells, because the moment it comes apart
// the boxes stop describing it -- which is the same rule the hull already
// follows and the reason the hull is still there.
//
// NOTHING HERE IS A CLAIM ABOUT THE MATTER. The room says what it says, the
// engine collides what it collides, and the drawn shape is checked against the
// cells before it is used: if it does not sit where the matter sits, to within
// a cell, it is not drawn and the cells are.
const OUTLINE_SLACK_CELLS = 1.6;

function rememberOutlines(spec) {
  world.outlines = new Map();
  const grouped = new Map();
  for (const row of (spec && spec.bodies) || []) {
    if (!row || String(row.shape || "box") !== "box") continue;
    if (!Array.isArray(row.size_mm) || !Array.isArray(row.center_mm)) continue;
    if (!row.size_mm.every(Number.isFinite) || !row.center_mm.every(Number.isFinite)) continue;
    const of = String(row.join || row.name || "");
    if (!of) continue;
    let held = grouped.get(of);
    if (!held) grouped.set(of, held = []);
    held.push(row);
  }
  for (const [name, rows] of grouped) {
    // Where the thing's middle is, weighted by how much of it each box is --
    // the engine reports a body about its centre of mass, and a group of one
    // material has its centre of mass where its volume is.
    let bulk = 0, mx = 0, my = 0, mz = 0;
    for (const row of rows) {
      const v = row.size_mm[0] * row.size_mm[1] * row.size_mm[2];
      bulk += v;
      mx += v * row.center_mm[0]; my += v * row.center_mm[1]; mz += v * row.center_mm[2];
    }
    if (!(bulk > 0)) continue;
    const mid = [mx / bulk / 1000, my / bulk / 1000, mz / bulk / 1000];
    const parts = rows.map((row) => {
      const turn = new THREE.Quaternion();
      const spin = Array.isArray(row.rotation_deg) ? row.rotation_deg : [0, 0, 0];
      // The room turns a box z first (Rx.Ry.Rz), which is what three.js means
      // by an XYZ euler. If it were not, the shape would sit askew on its own
      // matter and the check below would refuse to draw it.
      turn.setFromEuler(new THREE.Euler(THREE.MathUtils.degToRad(spin[0] || 0),
                                        THREE.MathUtils.degToRad(spin[1] || 0),
                                        THREE.MathUtils.degToRad(spin[2] || 0), "XYZ"));
      return { shape: "box", name: String(row.part || row.name || ""),
               dimensions_m: row.size_mm.map((v) => v / 1000),
               center_local_m: [row.center_mm[0] / 1000 - mid[0],
                                row.center_mm[1] / 1000 - mid[1],
                                row.center_mm[2] / 1000 - mid[2]],
               rotation_wxyz: [turn.w, turn.x, turn.y, turn.z],
               material: row.material };
    });
    if (parts.length > 64) continue;   // preciseGeometry will not take more
    world.outlines.set(name, { parts, cells: null,
                               mixed: new Set(parts.map((p) => p.material)).size > 1 });
  }
}

// Does the shape it was drawn to sit where its matter is? The cells' box and
// the design's box, in the body's own frame, agreeing to within a cell and a
// half at both ends of every axis. This is what catches a thing that has lost
// matter, a frame worked out wrongly, and a turn read the wrong way round --
// all three of which draw perfectly well and are all three wrong.
function sitsOnItsMatter(parts, cells, h) {
  const low = [Infinity, Infinity, Infinity], high = [-Infinity, -Infinity, -Infinity];
  for (const at of cells)
    for (let d = 0; d < 3; ++d) {
      if (at[d] - h / 2 < low[d]) low[d] = at[d] - h / 2;
      if (at[d] + h / 2 > high[d]) high[d] = at[d] + h / 2;
    }
  const box = new THREE.Box3();
  const corner = new THREE.Vector3(), turn = new THREE.Quaternion(), matrix = new THREE.Matrix4();
  const at = new THREE.Vector3(), size = new THREE.Vector3(1, 1, 1);
  for (const part of parts) {
    const q = part.rotation_wxyz;
    turn.set(q[1], q[2], q[3], q[0]).normalize();
    matrix.compose(at.fromArray(part.center_local_m), turn, size);
    const d = part.dimensions_m;
    for (let c = 0; c < 8; ++c) {
      corner.set((c & 1 ? 0.5 : -0.5) * d[0], (c & 2 ? 0.5 : -0.5) * d[1],
                 (c & 4 ? 0.5 : -0.5) * d[2]).applyMatrix4(matrix);
      box.expandByPoint(corner);
    }
  }
  const slack = OUTLINE_SLACK_CELLS * h;
  const ends = [[box.min.x, box.min.y, box.min.z], [box.max.x, box.max.y, box.max.z]];
  for (let d = 0; d < 3; ++d)
    if (Math.abs(ends[0][d] - low[d]) > slack || Math.abs(ends[1][d] - high[d]) > slack)
      return false;
  return true;
}

// The shape this body should be drawn to, or nothing when it should be drawn
// from its cells.
function outlineFor(body) {
  const held = world.outlines && world.outlines.get(body.name);
  if (!held) return null;
  const cells = body.cells_local_m;
  // The first sight of it is what "whole" means; losing matter after that is
  // what breaking looks like from here.
  if (held.cells === null) held.cells = cells.length;
  if (cells.length < held.cells) return null;
  return sitsOnItsMatter(held.parts, cells, world.cellSize) ? held : null;
}

// What one body is drawn with: the shared material of its substance, or, when
// the Workshop gave it a finish, a material wearing that finish.
//
// Kept by the FINISH rather than by the body, so that everything wearing the
// same one shares a material -- a skinned pane that shatters into seventy
// shards is still one material and one draw call, and a room does not compile
// a shader in the middle of a break.
const SKINNED = new Map();
function lookFor(name, material, shaded = false) {
  const skin = world.skins && world.skins.get(name);
  if (!skin) return look(material, shaded);
  const key = `${material}|${shaded ? 1 : 0}|${skin.color || ""}`
    + `|${skin.roughness ?? ""}|${skin.metalness ?? ""}`;
  const had = SKINNED.get(key);
  if (had) return had;
  const made = dressedClone(look(material, shaded));
  // A colour the bench let through that this page cannot read is not worth
  // losing the thing over: it keeps its material's own.
  if (skin.color) { try { made.color.set(skin.color); } catch { /* keep its own */ } }
  if (typeof skin.roughness === "number") made.roughness = skin.roughness;
  if (typeof skin.metalness === "number") made.metalness = skin.metalness;
  SKINNED.set(key, made);
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

// A round part is drawn with this many sides: enough that a wheel reads as a
// wheel when you stand beside it, few enough for a room of carts.
const PRECISE_SIDES = 28;

// An exact body's parts as one geometry, each where and as it is: a box, or a
// cylinder along its own y sized {diameter, length, diameter}, turned by its
// own rotation. Where the parts are of more than one material each part is
// coloured as its own -- an iron axle through oak wheels shows as that.
function preciseGeometry(parts, fallbackMaterial, mixed) {
  const positions = [], normals = [], colors = [];
  const matrix = new THREE.Matrix4(), turn = new THREE.Quaternion();
  const at = new THREE.Vector3(), size = new THREE.Vector3();
  for (const part of parts) {
    if (![part.center_local_m, part.dimensions_m].every(v => Array.isArray(v) && v.length === 3 && v.every(Number.isFinite)) || part.dimensions_m.some(v => v <= 0))
      throw new Error("Invalid precise rigid collision geometry.");
    const round = part.shape === "cylinder";
    if (!round && part.shape !== "box") throw new Error("Unknown precise rigid part shape.");
    const q = Array.isArray(part.rotation_wxyz) && part.rotation_wxyz.length === 4 ? part.rotation_wxyz : [1, 0, 0, 0];
    if (!q.every(Number.isFinite)) throw new Error("Invalid precise rigid part rotation.");
    const shape = (round ? new THREE.CylinderGeometry(0.5, 0.5, 1, PRECISE_SIDES)
                         : new THREE.BoxGeometry(1, 1, 1)).toNonIndexed();
    turn.set(q[1], q[2], q[3], q[0]).normalize();
    matrix.compose(at.fromArray(part.center_local_m), turn, size.fromArray(part.dimensions_m));
    shape.applyMatrix4(matrix);
    for (const v of shape.attributes.position.array) positions.push(v);
    for (const v of shape.attributes.normal.array) normals.push(v);
    if (mixed) {
      const c = look(part.material || fallbackMaterial).color;
      for (let k = 0; k < shape.attributes.position.count; k++) colors.push(c.r, c.g, c.b);
    }
    shape.dispose();
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute("normal", new THREE.Float32BufferAttribute(normals, 3));
  if (mixed) geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  return geometry;
}

function buildMesh(body) {
  if (body.mechanical_model === "precise-rigid-v1") {
    const parts = body.rigid_parts_local;
    if (!Array.isArray(parts) || !parts.length || parts.length > 64)
      throw new Error("Precise rigid geometry is missing; refusing to draw a substitute bounding box.");
    // A thing of several materials draws each part in the colour of what that
    // part is made of -- an iron axle through oak wheels shows as that. A
    // FINISH that names a colour overrules it and paints the whole thing:
    // somebody has said what this machine looks like and meant all of it. A
    // finish that says only how polished it is leaves every part the colour of
    // its own material and changes the shine.
    const finish = world.skins && world.skins.get(body.name);
    const mixed = new Set(parts.map(part => part.material || body.material)).size > 1
      && !(finish && finish.color);
    let material = lookFor(body.name, body.material);
    if (mixed) {
      // Its own, so colouring its parts touches no other body of that stuff.
      material = dressedClone(material);
      material.vertexColors = true;
      material.color.set(0xffffff);
    }
    const mesh = new THREE.Mesh(preciseGeometry(parts, body.material, mixed), material);
    mesh.userData.mechanicalModel = body.mechanical_model;
    mesh.userData.collisionParts = parts.length;
    mesh.userData.ownMaterial = mixed;
    return mesh;
  }

  // Cells first. This used to build a box or a sphere and a material before
  // asking, then throw both away for anything drawn from its cells -- which is
  // every piece of everything that ever breaks.
  if (Array.isArray(body.cells_local_m) && body.cells_local_m.length) {
    // Drawn from its cells -- as the outside surface of them where that can be
    // built honestly (cellmesh.js), and as cubes where it cannot. Either way it
    // is one mesh carried by the body's own pose, so it stays one pose on the
    // wire and one draw call on screen.
    //
    // The surface is the same matter: it stands on the cell boundaries the
    // engine is colliding, it is not smoothed, and where the mesher will not
    // vouch for it the cubes come back, which are always right.
    // Drawn to the shape it was drawn to, while it still is that shape.
    const drawn = outlineFor(body);
    if (drawn) {
      try {
        const mesh = new THREE.Mesh(preciseGeometry(drawn.parts, body.material, drawn.mixed),
                                    lookFor(body.name, body.material));
        mesh.userData.drawnToDesign = true;
        mesh.userData.hullCells = body.cells_local_m.length;
        return mesh;
      } catch { /* not a shape this can draw: its cells, then */ }
    }
    const hull = cellSurface(body.cells_local_m, world.cellSize);
    if (hull) {
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(hull.positions, 3));
      geometry.setAttribute("normal", new THREE.Float32BufferAttribute(hull.normals, 3));
      geometry.setAttribute("color", new THREE.Float32BufferAttribute(hull.shades, 3));
      const hulled = new THREE.Mesh(geometry, lookFor(body.name, body.material, true));
      hulled.userData.shaded = true;
      hulled.userData.hullQuads = hull.quads;
      hulled.userData.hullFaces = hull.faces;
      hulled.userData.hullCells = body.cells_local_m.length;
      hulled.userData.hullBent = !!hull.bent;
      return hulled;
    }
    const cloud = new THREE.InstancedMesh(cellCube(), lookFor(body.name, body.material),
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
  return new THREE.Mesh(geometry, lookFor(body.name, body.material));
}

// Take a mesh out of the scene and give back what only it was using.
//
// The material is shared and the cell cube is shared, so neither is this
// mesh's to dispose -- but an authored body's own box or sphere is, and a
// room where things break and are swept up builds and drops these all day.
function forget(mesh) {
  scene.remove(mesh);
  if (mesh.geometry && mesh.geometry !== cellGeometry) mesh.geometry.dispose();
  // A body of mixed materials had one of its own; the shared ones stay.
  if (mesh.userData && mesh.userData.ownMaterial && mesh.material) mesh.material.dispose();
}

// A body WALKS to each new state instead of appearing at it.
//
// The page draws at the display's rate and the room's state arrives at the
// network's, and those are not the same number. Measured on this page with
// latency injected: 29.2 states a second with none added and 7.2 at 100 ms,
// with frames flat at both. A body set straight from each state therefore
// jumps seven times a second while the view glides -- which reads as the room
// running slowly when the frame rate is in fact perfect.
//
// So each new state becomes somewhere to walk TO, over the gap the last two
// states actually took. It is one state behind by construction: that is what
// this costs, and it is the price every game pays for the same thing.
//
// `?glide=0` turns it off, which is how the two were measured against each
// other.
const glides = new Map();   // mesh -> where it is walking from, to, and when
let stateGapMs = 33, lastStateAt = 0;
const gliding = new URLSearchParams(location.search).get("glide") !== "0";
// Further than this in one state is a thing being PUT somewhere -- carried
// across the room, swept up, respawned -- not a thing moving. Walking there
// would draw it streaking through everything between. A ball thrown at 20 m/s
// covers 2.9 m in a seventh of a second, so this has to clear that.
const GLIDE_SNAP_M = 4.0;

function snapTo(mesh, body) {
  mesh.position.set(body.position_m[0], body.position_m[1], body.position_m[2]);
  const q = body.orientation_wxyz;
  mesh.quaternion.set(q[1], q[2], q[3], q[0]);
  glides.delete(mesh);
  mesh.userData.placed = true;
}

function place(mesh, body) {
  // Snapped: the first time it is drawn, with gliding off, and for whatever is
  // in the hand -- that one follows what the page itself asked the hand to do,
  // so the state is a confirmation and walking to it would only add lag to the
  // one thing whose lag is felt directly.
  if (!gliding || !mesh.userData.placed
      || (world.held && world.held.name === body.name)) {
    snapTo(mesh, body);
    return;
  }
  const to = new THREE.Vector3(body.position_m[0], body.position_m[1], body.position_m[2]);
  if (mesh.position.distanceToSquared(to) > GLIDE_SNAP_M * GLIDE_SNAP_M) {
    snapTo(mesh, body);
    return;
  }
  const q = body.orientation_wxyz;
  glides.set(mesh, { from: mesh.position.clone(), fromQ: mesh.quaternion.clone(),
                     to, toQ: new THREE.Quaternion(q[1], q[2], q[3], q[0]),
                     start: performance.now(), ms: stateGapMs });
}

// Every frame: as far along each walk as the clock says, and no further. A
// glide that has run out is done and dropped, so a still room costs nothing.
function advanceGlides(now) {
  if (!glides.size) return;
  for (const [mesh, g] of glides) {
    if (!mesh.parent) { glides.delete(mesh); continue; }
    const t = g.ms > 0 ? Math.min(1, (now - g.start) / g.ms) : 1;
    mesh.position.lerpVectors(g.from, g.to, t);
    mesh.quaternion.slerpQuaternions(g.fromQ, g.toQ, t);
    if (t >= 1) glides.delete(mesh);
  }
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
  const at = performance.now();
  if (lastStateAt) stateGapMs = Math.min(400, Math.max(16, at - lastStateAt));
  lastStateAt = at;
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
    if (!held || dentChanged || reshaped || (body.cells_local_m && !held.fromCells) || (body.mechanical_model === "precise-rigid-v1" && !held.fromPrecise)) {
      if (held) forget(held.mesh);
      const mesh = buildMesh(body);
      // Everything the engine is carrying casts and catches the sun. This is
      // the one place a body's mesh is made, so it is the one place to say so.
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      scene.add(mesh);
      held = { mesh, fromPrecise: body.mechanical_model === "precise-rigid-v1", fromCells: !!(body.cells_local_m && body.cells_local_m.length),
               dentMm: body.dent_mm || 0 };
      world.bodies.set(body.name, held);
    }
    // The revision it is drawn at. A piece whose shape has changed but whose
    // cells have not come yet keeps the one it was drawn at, so that they are
    // drawn when they do.
    const waiting = held.fromCells && (body.revision || 0) !== (held.revision || 0)
      && !(body.cells_local_m && body.cells_local_m.length);
    if (!waiting) held.revision = body.revision || 0;
    held.geometryPending = !!waiting;
    // Retain only reported geometry, including across pose-only updates.
    if (body.cells_local_m) held.cells = body.cells_local_m;
    held.material = body.material || "";
    held.dentMm = body.dent_mm || 0;
    held.dims = body.dimensions_m;
    // An exact body's parts, which come with its geometry (the mark on a
    // turning wheel goes on the wheel, not on its box).
    if (body.rigid_parts_local) held.parts = body.rigid_parts_local;
    held.anchored = !!body.anchored;
    held.shape = body.shape;
    held.mechanicalModel = body.mechanical_model || "lattice";
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

// Each rope's line is made once and moved after: only its points change. It was
// made again for every rope on every update -- a new geometry each time, for the
// page to throw away -- which the owner's review found.
const ropeLines = new Map();   // joint id -> THREE.Line

function ropeLine(id, material, points) {
  let line = ropeLines.get(id);
  if (!line || line.material !== material || line.userData.points !== points.length) {
    if (line) { ropeGroup.remove(line); line.geometry.dispose(); }
    line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), material);
    line.userData.points = points.length;
    // Its ends move every frame; a bounding sphere kept up with them costs more
    // than drawing a line that is off screen.
    line.frustumCulled = false;
    ropeLines.set(id, line);
    ropeGroup.add(line);
    return;
  }
  const at = line.geometry.getAttribute("position");
  points.forEach((p, i) => at.setXYZ(i, p.x, p.y, p.z));
  at.needsUpdate = true;
}

function drawRopes() {
  const drawn = new Set();
  for (const joint of world.joints) {
    if (!joint.attached) continue;    // parted: there is no rope to draw
    const a = world.bodies.get(joint.a);
    const b = world.bodies.get(joint.b);
    if (!a || !b) continue;
    let points = null, material = ROPE_MATERIAL;
    if (joint.kind === "link") {
      points = [a.mesh.position.clone(), b.mesh.position.clone()];
    } else if (joint.kind === "elastic") {
      // From where it is anchored on `a` -- which the engine reports, worked
      // out from where `a` now stands -- to `b`'s middle. A bow limb is
      // anchored to a point on the grip that is nowhere near the grip's own
      // centre, and drawing it centre to centre would show a different machine
      // from the one being simulated. The far end is `b`'s centre because that
      // is what the joint report carries; when a spring is made off somewhere
      // other than the middle of `b`, this line is short by that much.
      const at = joint.at || [0, 0, 0];
      points = [new THREE.Vector3(at[0], at[1], at[2]), b.mesh.position.clone()];
      material = LIMB_MATERIAL;
    } else if (joint.kind === "pulley") {
      // Three runs, not one: up from the first body to its sheave, across
      // between the sheaves, and down to the second. Drawing it as a straight
      // line between the two bodies would show a rope passing through the
      // lintel, which is the one thing a pulley exists to avoid.
      const over = (p) => new THREE.Vector3(p[0], p[1], p[2]);
      points = [a.mesh.position.clone(), over(joint.over_a || [0, 0, 0]),
                over(joint.over_b || [0, 0, 0]), b.mesh.position.clone()];
    } else if (joint.kind === "drum") {
      // A rope on a drum: from where it leaves the drum -- the point on the
      // drum's rim it runs off towards the load, which moves as the load swings
      // -- to where it is made off on the load. Both change every step, so they
      // come with every step (world.machines), and the joint's own report,
      // which travels only when the set of joints changes, is the fallback.
      const now = (world.machines && world.machines.ropes || []).find((r) => r.joint === joint.id);
      const ends = now || joint;
      if (!ends.leaves || !ends.meets) continue;
      const at = (p) => new THREE.Vector3(p[0], p[1], p[2]);
      points = [at(ends.leaves), at(ends.meets)];
    }
    if (!points) continue;
    ropeLine(joint.id, material, points);
    drawn.add(joint.id);
  }
  for (const [id, line] of ropeLines) {
    if (drawn.has(id)) continue;
    ropeGroup.remove(line);
    line.geometry.dispose();
    ropeLines.delete(id);
  }
}

// Batteries, motors and ropes on drums, as the last step left them
// (docs/machine-world.md): every step that has any carries them all.
const storeFlows = new Map();
function followMachines(machines, t) {
  const present = new Set();
  for (const store of machines?.stores || []) {
    present.add(store.id);
    const previous = storeFlows.get(store.id);
    const sample = { t, taken: store.taken_j, given: store.given_j, known: false };
    if ([t, store.taken_j, store.given_j].every(Number.isFinite) && previous) {
      const dt = t - previous.t;
      const incoming = store.taken_j - previous.taken;
      const outgoing = store.given_j - previous.given;
      if (dt > 0 && incoming >= 0 && outgoing >= 0) {
        Object.assign(sample, { known: true, taking: incoming / dt, using: outgoing / dt });
      } else if (dt === 0 && incoming === 0 && outgoing === 0) {
        Object.assign(sample, previous);
      }
    }
    storeFlows.set(store.id, sample);
  }
  for (const id of storeFlows.keys()) if (!present.has(id)) storeFlows.delete(id);
  world.machines = machines || null;
  chooseSomethingToRide();
  showRidingSettings();
  drawMachines(world.machines);
  dressLights(world.machines);
  showMachinePanel();
  // THE ARCS AND THE BEADS ARE OFF (the owner, 2026-09-26: "i don't like the
  // green and yellow arcs on the screen ... what are the blue dots on lines
  // in front the rover, they are confusing"). Both were world-space overlays
  // explaining a machine to somebody who had not asked: dressMachines drew a
  // yellow stripe on every turning part and a green arc for which way its
  // motor runs, dressSensors a blue bead and a thread to the ground at each
  // water sensor, amber when it saw water. What they said is now said in
  // words on the machine's own line when you look at it, which is where the
  // owner asked for it. The two functions are left in place, called by
  // nothing, so that a machine being worked on by hand can have them back in
  // one line.
}

// Who decides for each machine's program on what it meets, and what was
// decided last (docs/machine-world.md, "What the rover decides by itself"):
// with the room when it opens, and with a step whenever one has changed.
world.brains = new Map();
function followBrains(brains) {
  if (!Array.isArray(brains)) return;
  for (const b of brains) if (b && b.name) world.brains.set(b.name, b);
  resourceVisuals.loads([...world.brains.values()]);
  drawHolds();
  if (machinePanel.of === "program") showMachinePanel();
}

// Every mouth on every machine, as the last step left it (machine_ports): the
// playground sends them with each step, because a mouth moves with the machine
// that carries it. Nothing said means this reply carried none, which is not the
// same as a room with no ports -- that is said as an empty list, when the room
// opens.
world.ports = [];
function followPorts(ports) {
  if (ports === undefined) return;
  world.ports = Array.isArray(ports) ? ports : [];
  dressPorts();
  showMachineHolds();
}

// The room's containers (playground/vessels.py), sent with every step for the
// same reason the mouths are: what a bucket holds changes as it is carried and
// tipped, so it is different on almost every step. Nothing said means this
// reply carried none, which is not the same as a room with no containers --
// that is an empty list, when the room opens.
world.vessels = [];
function followVessels(vessels) {
  if (vessels === undefined) return;
  world.vessels = Array.isArray(vessels) ? vessels : [];
  drawHolds();
}

// What a machine's controller was told, in a person's words.
function commandedWords(c) {
  const hoist = c.kind === "hoist";
  if (c.direction === 0) return c.holds ? "stop and hold" : "stop";
  const way = c.direction > 0 ? (hoist ? "raise" : "forward") : (hoist ? "lower" : "reverse");
  return `${way} at ${Math.round(c.setting * 100)}%`;
}

// The machines in the side panel: what each battery holds, what each motor is
// doing, and where what it drew went -- its work and its heat -- as the engine
// counted them, what each machine's controller was told and what stands in its
// way, and each drum's rope. Every step that has machines comes here, so each
// row is made once and only its words change after: the list was built again
// from nothing on every update (the owner's review).
const machineRows = new Map();   // key -> { li, what, much }

function drawMachines(block) {
  const rows = [];
  const row = (key, what, much, control = null) => {
    let r = machineRows.get(key);
    if (!r) {
      const li = document.createElement("li");
      const a = document.createElement("span");
      a.className = "what";
      const b = document.createElement("span");
      b.className = "much";
      li.append(a, b);
      r = { li, what: a, much: b };
      machineRows.set(key, r);
    }
    if (r.what.textContent !== what) r.what.textContent = what;
    if (r.much.textContent !== much) r.much.textContent = much;
    if (control) {
      r.control = control;
      if (!r.button) {
        r.button = document.createElement("button");
        r.button.type = "button";
        r.button.className = "quiet";
        r.button.textContent = "Controls";
        r.button.addEventListener("click", () => openMachinePanel(r.control));
        r.li.append(r.button);
      }
      r.button.setAttribute("aria-label", `Control ${control.name}`);
    }
    rows.push(r.li);
  };
  const joules = (j) => (Math.abs(j) >= 1000 ? `${(j / 1000).toFixed(2)} kJ` : `${Math.round(j)} J`);
  for (const s of (block && block.stores) || []) {
    const share = s.capacity_j > 0 ? Math.round(100 * s.charge_j / s.capacity_j) : 0;
    row(`store ${s.id}`, s.name,
        `${joules(s.charge_j)} of ${joules(s.capacity_j)} (${share}%) · has given ${joules(s.given_j)}`
        + (s.taken_j > 0 ? ` · has taken in ${joules(s.taken_j)}` : ""));
  }
  for (const c of (block && block.controls) || []) {
    row(`control ${c.id}`, `${c.name}: its controller`,
        `${c.power ? `on, told to ${commandedWords(c)}` : "off"}${c.condition ? ` · ${c.condition}` : ""}`, c);
  }
  for (const p of (block && block.programs) || []) {
    row(`program ${p.id}`, `${p.name}: its program`,
        p.power ? `on, ${p.doing}${p.why ? ` · ${p.why}` : ""}` : "off", p);
  }
  for (const panel of (block && block.panels) || []) {
    const lit = panel.shaded ? `in the shade of ${panel.shaded_by}`
      : panel.sunlight_w > 0 ? `${Math.round(panel.power_w)} W from ${Math.round(panel.sunlight_w)} W of sun on it`
      : world.sun && world.sun.day_s > 0 && world.sun.elevation_deg <= 0 ? "nothing: it is night"
      : world.sun && world.sun.irradiance_w_m2 > 0 ? "facing away from the sun" : "no sun";
    row(`panel ${panel.id}`, `${panel.name} on ${panel.body}`, `${lit} · has given ${joules(panel.collected_j)}`);
  }
  for (const m of (block && block.motors) || []) {
    const turns = m.on && m.on.length === 2 ? m.on[1] : `pin ${m.joint}`;
    const doing = m.state === "driving"
      ? `running ${m.speed_rad_s.toFixed(1)} rad/s at ${Math.abs(m.torque_n_m).toFixed(1)} N m, ${Math.round(m.power_w)} W`
      : m.state === "flat" ? "stopped: its battery is flat"
      : m.state === "braking" ? `braked, holding ${Math.abs(m.torque_n_m).toFixed(1)} N m`
      : m.state === "gone" ? "its pin is gone"
      : "coasting";
    row(`motor ${m.id}`, `motor turning ${turns}`, `${doing} · drew ${joules(m.drawn_j)}: ${joules(m.work_j)} of work,`
      + ` ${joules(m.heat_j)} of heat`);
  }
  for (const r of (block && block.ropes) || []) {
    const joint = (world.joints || []).find((j) => j.id === r.joint);
    row(`rope ${r.joint}`, joint ? `rope from ${joint.a} to ${joint.b}` : "rope on a drum",
      `${r.out_m.toFixed(2)} m out, ${r.wound_m.toFixed(2)} m on the drum · carries ${Math.round(r.tension_n)} N`);
  }
  // The list itself is only put together again when its rows change.
  const list = $("machine-list");
  if (list.children.length !== rows.length || rows.some((li, i) => list.children[i] !== li)) {
    list.replaceChildren(...rows);
  }
  const shown = new Set(rows);
  for (const [key, r] of machineRows) if (!shown.has(r.li)) machineRows.delete(key);
  const note = "what each motor drew is its work and its heat; no motor gives anything back to a battery,"
    + " and a brake holds without drawing";
  if ($("machine-note").textContent !== note) $("machine-note").textContent = note;
  $("machines").hidden = rows.length === 0;
}

// ---------------------------------------------------------------------------
// A machine's panel (docs/machine-world.md, "Operating a machine")
// ---------------------------------------------------------------------------
//
// A powered machine is worked like an appliance, not by grabbing its drum or by
// pressing E through a list: E on any part of it opens its panel, which stays
// until it is closed or another machine is chosen (the owner's review,
// 2026-09-15). Each button says a state outright -- power on, power off, raise,
// stop, lower -- and goes straight to the machine's controller in the engine
// with this page's own count (POST /api/world/machine). The engine drops a
// command no newer than one it has applied from this page, so a raise held up on
// its way cannot undo a later stop. What the panel reads out is the engine's:
// what the machine was told, what its shaft and its load are measured doing, and
// what stands in the way. A command taken is never shown as motion.
const machinePanel = {
  id: null,        // the controller shown, by the engine's id
  name: "",        // and by name, to find it again in a room opened again
  sender: `page ${Math.random().toString(36).slice(2, 10)}`,
  seq: 0,
  said: "",        // what became of the last command sent from here
  stale: false,
  // Power On pressed and not yet answered: the drive buttons can be pressed at
  // once, since the engine takes the page's commands in the order they were
  // sent. Raise pressed a moment after On was lost while it waited.
  poweringOn: false,
  // What the panel shows: a machine's controller, or a machine's program.
  of: "control",
  // The program being talked to, by name, while its chat is open.
  talkingTo: null,
};

function controlsNow() {
  return (world.machines && world.machines.controls) || [];
}

// What a machine's battery holds and what it is spending right now
// (docs/machine-world.md): its store, the watts its motors are asking of it
// this step, and the watts its panels are putting back. Switched off, or
// standing with its motors stopped, it asks for nothing and the panel says
// so -- which is how you see that landing a flying machine costs less than
// holding it up.
function energyOf(p) {
  const m = world.machines || {};
  let ident = p.store || 0;
  if (!ident) {
    const first = (p.rotors && p.rotors[0]) || p.left;
    const control = (m.controls || []).find((c) => c.id === first);
    const motor = control && (m.motors || []).find((x) => x.id === control.motor);
    ident = motor ? motor.store : 0;
  }
  const store = (m.stores || []).find((s) => s.id === ident);
  if (!store) return null;
  return energyOfStore(store);
}
function energyOfStore(store) {
  const flow = storeFlows.get(store.id);
  const using = flow?.using || 0, taking = flow?.taking || 0;
  return { store, using, taking, net: using - taking, known: !!flow?.known };
}
const joulesSaid = (j) => (j >= 1e6 ? `${(j / 1e6).toFixed(2)} MJ` : j >= 1e3 ? `${(j / 1e3).toFixed(1)} kJ` : `${Math.round(j)} J`);
const wattsSaid = (w) => (w >= 1000 ? `${(w / 1000).toFixed(2)} kW` : w >= 10 ? `${Math.round(w)} W` : `${w.toFixed(1)} W`);
const forHowLong = (s) => (s >= 3600 ? `${(s / 3600).toFixed(1)} hours` : s >= 60 ? `${Math.round(s / 60)} min` : `${Math.round(s)} s`);
function spendingSaid(power) {
  if (!power) return "";
  if (power.known === false) return " · reading energy flow…";
  const using = power.using > 0.05 ? `using ${wattsSaid(power.using)}` : "using nothing";
  const taking = power.taking > 0.05 ? `, taking in ${wattsSaid(power.taking)}` : "";
  const left = power.net > 0.05 ? `, ${forHowLong(power.store.charge_j / power.net)} left at that` : "";
  return ` · ${using}${taking}${left}`;
}

// A machine's programs (docs/machine-world.md, "One autonomous creature"):
// each works the controllers of a machine's wheels, from what its sensors read.
function programsNow() {
  return (world.machines && world.machines.programs) || [];
}

const isProgram = (m) => !!m && typeof m.doing === "string";

// The machines a thing is part of: either side of a motor's pin, and a hoist's
// load (the runner's `parts`) -- and a program's machine, whose wheels it
// works: that machine is offered as its program, not wheel by wheel.
function machinesOfPart(name) {
  const programs = programsNow().filter((p) => (p.parts || []).includes(name));
  const worked = new Set(programsNow().flatMap((p) => [p.left, p.right, ...(p.rotors || [])]));
  return [...programs, ...controlsNow().filter((c) => !worked.has(c.id) && (c.parts || []).includes(name))];
}

function shownControl() {
  const all = machinePanel.of === "program" ? programsNow() : controlsNow();
  return all.find((c) => c.id === machinePanel.id) || all.find((c) => c.name === machinePanel.name) || null;
}

function mergeProgram(program) {
  if (!world.machines) return;
  const list = world.machines.programs || (world.machines.programs = []);
  const at = list.findIndex((p) => p.id === program.id);
  if (at >= 0) list[at] = program;
  else list.push(program);
}

function openMachinePanel(control) {
  machinePanel.of = isProgram(control) ? "program" : "control";
  machinePanel.id = control.id;
  machinePanel.name = control.name;
  machinePanel.said = "";
  machinePanel.stale = false;
  $("machine-panel").hidden = false;
  document.body.classList.add("machine-open");
  // The mouse is the person's again, to press the panel's buttons; a click in
  // the room takes it back to looking round.
  if (document.pointerLockElement) document.exitPointerLock?.();
  showMachinePanel();
  (control.power ? $("mp-stop") : $("mp-on")).focus({ preventScroll: true });
}

function closeMachinePanel() {
  if (!$("mp-chat").hidden) closeTalk(true);
  machinePanel.id = null;
  machinePanel.name = "";
  $("machine-panel").hidden = true;
  document.body.classList.remove("machine-open");
  showMachineHolds();
}

function mergeControl(control) {
  if (!world.machines) return;
  const list = world.machines.controls || (world.machines.controls = []);
  const at = list.findIndex((c) => c.id === control.id);
  if (at >= 0) list[at] = control;
  else list.push(control);
}

// One command to the machine shown, and what the engine said of it: "applied",
// with the controller as it now stands -- the acknowledgement -- or "stale".
async function commandMachine(what) {
  const control = shownControl();
  if (!control || !world.session) return;
  machinePanel.seq += 1;
  const seq = machinePanel.seq;
  try {
    const body = machinePanel.of === "program"
      ? { session: world.session, program: control.id, sender: machinePanel.sender, seq, power: !!what.power }
      : { session: world.session, control: control.id, sender: machinePanel.sender, seq, ...what };
    const answer = await api("/api/world/machine", body);
    if (answer.control) mergeControl(answer.control);
    if (answer.program) mergeProgram(answer.program);
    machinePanel.stale = answer.operated === "stale";
    machinePanel.said = machinePanel.stale
      ? "That arrived after a newer command, so the machine did not take it."
      : "The machine took it.";
  } catch (error) {
    machinePanel.stale = true;
    machinePanel.said = error.message || String(error);
  }
  showMachinePanel();
}

function setText(id, text) {
  const el = $(id);
  if (el.textContent !== text) el.textContent = text;
}

function setPressed(id, on, disabled = false) {
  const button = $(id);
  const want = on ? "true" : "false";
  if (button.getAttribute("aria-pressed") !== want) button.setAttribute("aria-pressed", want);
  if (button.disabled !== disabled) button.disabled = disabled;
}

// The panel, from the controller as the last step -- or the last command's
// answer -- left it. With every step: only what changed is written.
function showMachinePanel() {
  if (machinePanel.id == null) return;
  const c = shownControl();
  if (!c) {
    setText("mp-condition", "This machine is not in the room any more.");
    for (const id of ["mp-on", "mp-off", "mp-back", "mp-stop", "mp-ahead"]) $(id).disabled = true;
    $("mp-setting").disabled = true;
    return;
  }
  machinePanel.id = c.id;
  if (machinePanel.of === "program") {
    showProgramPanel(c);
    return;
  }
  panelRows(false);
  $("mp-brain").hidden = true;
  $("mp-decided").hidden = true;
  $("mp-routine").hidden = true;
  if ($("mp-watch-batch")) $("mp-watch-batch").hidden = true;
  $("mp-talk").hidden = true;
  if (!$("mp-chat").hidden) closeTalk(true);
  const hoist = c.kind === "hoist";
  setText("mp-kind", hoist ? "Hoist" : "Machine");
  setText("mp-name", titled(c.name));
  setText("mp-back", hoist ? "Lower" : "Reverse");
  setText("mp-ahead", hoist ? "Raise" : "Forward");
  setText("mp-stop", c.holds ? "Stop & hold" : "Stop: it coasts");
  setPressed("mp-on", c.power);
  setPressed("mp-off", !c.power);
  // Driving is for a machine that is on, or being turned on: off, its brake
  // holds it.
  const on = c.power || machinePanel.poweringOn;
  setPressed("mp-back", c.power && c.direction < 0, !on);
  setPressed("mp-stop", c.power && c.direction === 0, !on);
  setPressed("mp-ahead", c.power && c.direction > 0, !on);
  // ITS PROGRAM HAS THIS WHEEL. Do not offer a direction that will be
  // overwritten before the next frame; say who has it and where you can
  // drive it from instead.
  const owner = programOwning(c.id);
  const ownedHint = document.querySelector("#machine-panel .mp-hint");
  for (const id of ["mp-back", "mp-stop", "mp-ahead"]) $(id).disabled = !!owner || !on;
  if (ownedHint) {
    ownedHint.textContent = owner
      ? `${titled(owner.name)}'s program has this wheel and tells it every step, on or off, `
        + "so a direction set here would be put back before the next frame. "
        + "Turn that program off to work it by hand — or be the machine: Settings, "
        + `then ${owner.name}.`
      : "A share of the battery's voltage, not a speed: what the machine does with it is below.";
    ownedHint.classList.toggle("owned", !!owner);
  }
  const slider = $("mp-setting");
  slider.disabled = !!owner;
  if (document.activeElement !== slider) {
    const value = String(Math.round(c.setting * 100));
    if (slider.value !== value) slider.value = value;
  }
  setText("mp-setting-value", `${slider.value}%`);
  setText("mp-enabled", c.power ? "On" : "Off");
  const told = commandedWords(c);
  setText("mp-commanded", c.power ? told.charAt(0).toUpperCase() + told.slice(1) : "Nothing: it is off");
  const rpm = Math.abs(c.speed_rpm) < 0.05 ? "0" : Math.abs(c.speed_rpm).toFixed(1);
  let measured = `${rpm} turns a minute`;
  if (hoist) {
    const load = (c.parts || [])[2] || "its load";
    const v = c.rope_speed_m_s || 0;
    const going = Math.abs(v) < 0.005 ? "still" : v > 0 ? `rising ${v.toFixed(2)} m/s`
      : `coming down ${(-v).toFixed(2)} m/s`;
    measured += ` · ${load} ${going} · ${(c.out_m || 0).toFixed(2)} m of rope out`;
  }
  // What its sensors read, as the last step left them.
  for (const s of c.sensors || []) {
    measured += ` · ${sensorName(s)}: ${sensorReading(s)}`;
  }
  setText("mp-measured", measured);
  setText("mp-condition", c.condition || "nothing in its way");
  $("mp-condition").classList.toggle("attention",
    /stalled|too weak|flat|held back|hand|gone|coasts|water|ground drop/.test(c.condition || ""));
  setText("mp-ack", machinePanel.said);
  $("mp-ack").classList.toggle("stale", machinePanel.stale);
  showMachineHolds();
  if ($("machine-panel").hidden) $("machine-panel").hidden = false;
}

// The program that owns a controller, if one does.
//
// A machine with a program TELLS its wheels every step -- off or on -- so
// pressing Forward on a wheel of the rover does nothing at all: the program
// puts it back before the next frame is drawn. That was deliberate and it was
// also invisible, which is the half that was wrong. The owner, having tried
// it: "I don't understand all the commands for the rover in the side bar,
// they don't seem to do things they say."
function programOwning(controlId) {
  const programs = (world.machines && world.machines.programs) || [];
  return programs.find((p) => p && (p.left === controlId || p.right === controlId
                                    || p.pose === controlId)) || null;
}


// A program is turned on and off, and nothing else: its wheels' directions
// and their setting are its own to decide, so those rows are put away -- by
// their display, which the panel's own rules set and `hidden` does not beat.
function panelRows(program) {
  const panel = $("machine-panel");
  if($("mp-recovery")) $("mp-recovery").hidden=!program;
  for (const selector of [".mp-drive", ".mp-setting", ".mp-hint"]) {
    const row = panel.querySelector(selector);
    const want = program ? "none" : "";
    if (row && row.style.display !== want) row.style.display = want;
  }
}

// A program's panel: whether it is on, what it has its wheels doing, what its
// sensors and its own slope read, and why it is doing what it does.
function sensorName(s) {
  return `${s.stops<0 ? "Rear" : "Front"} ${s.side>0 ? "left" : s.side<0 ? "right" : "middle"} · ${s.kind==="ground" ? "ground" : "water"}`;
}

let recoveryBusy = false;
function recoverySection(program) {
  const section=document.createElement("section");section.dataset.roverRecovery="";
  const held=world.held?.recovery===program.id ? world.held : null;
  const button=document.createElement("button");button.type="button";button.className="pk-recovery";
  button.dataset.recoveryAction=held ? "release" : "start";
  button.textContent=held ? "Release rover" : "Take hold to recover";
  button.disabled=recoveryBusy || !!watchedId || (!held && !!world.held);
  button.onclick=()=>recoverRover(program,held ? "release" : "start");section.append(button);
  if(held) {
    const hand=held.hand || {};
    section.append(inspectionValues([
      ["Assembly",`${world.use.kg.toFixed(1)} kg`],
      ["Pull",`${Math.round(Math.hypot(...(hand.force_n || [0,0,0])))} N`],
      ["Work",`${Math.round(hand.work_j || 0)} J`],
      ["Grip",hand.grip_m && hand.target_m && Math.hypot(...hand.grip_m.map((v,i)=>v-hand.target_m[i]))>.25
        ? "Pulling / obstructed" : "Following"],
    ]));
  }
  const hint=document.createElement("p");hint.className="pk-doing";
  hint.textContent=held ? "Look up to lift · walk to pull · E releases" : "Approach chassis · rover stops while held";
  section.append(hint);return section;
}

function adoptRecovery(program,hand,mass=null) {
  const entry=world.bodies.get(program.body);
  if(!entry || !hand?.grip_m) return;
  const target=new THREE.Vector3(...(hand.target_m || hand.grip_m));
  const distance=clamp(camera.position.distanceTo(target),.6,2);
  const from=camera.position.clone().add(forwardVector().multiplyScalar(distance));
  world.held={name:program.body,loose:false,recovery:program.id,distance,offset:target.sub(from),hand};
  const kg=mass ?? (program.parts || [program.body]).reduce((sum,n)=>sum+(world.bodies.get(n)?.mass || 0),0);
  world.use={mode:"carrying",name:program.name,kg,loose:false};
  clearGuides();showHolding(true);showUse();
}

async function recoverRover(program,action) {
  if(recoveryBusy) return;
  recoveryBusy=true;
  try {
    const answer=await api("/api/world/machine",{session:world.session,program:program.id,
      recovery:action,person:whereIAm()});
    if(answer.state) draw(answer.state);
    mergeProgram(answer.program);
    if(answer.recovering) {
      adoptRecovery(answer.program,answer.hand,answer.assembly_mass_kg);
      picked.name=answer.program.body;picked.at=null;
      lastAction("Rover stopped. Look up to lift; walk to pull; E releases.");
    } else {
      world.held=null;world.use={mode:"none"};showHolding(false);clearGuides();showUse();
      lastAction("Rover released. Turn it on when ready.");
    }
  } catch(error) { lastAction(error.message || String(error),"refused");say("bad",error.message || String(error)); }
  finally { recoveryBusy=false;showPicked();showMachinePanel(); }
}
function sensorReading(s) {
  const value=Number(s.reading_m)||0,cm=Math.abs(value)*100;
  const reading=s.kind==="ground" ? (cm<.5 ? "Level" : `${value>0?"Drop":"Step"} ${cm.toFixed(1)} cm`) :
    (cm<.05 ? "Dry" : `${cm.toFixed(1)} cm deep`);
  return `${reading}${s.sees ? " · ⚠" : ""}`;
}
function showProgramPanel(p) {
  panelRows(true);
  setText("mp-kind", "Machine with a program");
  setText("mp-name", titled(p.name));
  setPressed("mp-on", p.power,world.held?.recovery===p.id);
  setPressed("mp-off", !p.power);
  let recovery=$("mp-recovery");
  if(!recovery) {recovery=document.createElement("div");recovery.id="mp-recovery";$("mp-measured").before(recovery);}
  recovery.replaceChildren(...(p.kind==="roam" ? [recoverySection(p)] : []));
  setText("mp-enabled", p.power ? "On" : "Off");
  const wheels = p.kind === "still" ? {
    "standing by": "ready, with nothing to do",
    "waiting": "working, or waiting as it was asked",
    "resting": "its battery low, resting until it is charged",
  } : p.kind === "hover" ? {
    "going forward": "leaning forward on its rotors",
    "backing off": "leaning back on its rotors",
    "turning left": "its rotors turning it left",
    "turning right": "its rotors turning it right",
    "waiting": "hovering on its spot",
    "rising": "climbing on its rotors",
    "descending": "coming down on its rotors",
    "landed": "on the ground, its rotors stopped",
    "resting": "down on the ground, its rotors off",
  } : {
    "going forward": "both wheels forward",
    "backing off": "both wheels back",
    "turning left": "left wheel back, right wheel forward",
    "turning right": "left wheel forward, right wheel back",
    "stopping": "both wheels held on their brakes, to turn from rest",
    "resting": "both wheels held on their brakes",
    "stuck": "it cannot get itself out, and its wheels are held",
  };
  const doing = p.doing.charAt(0).toUpperCase() + p.doing.slice(1);
  setText("mp-commanded", p.power ? `${doing}: ${wheels[p.doing] || "stopped"}` : "Nothing: it is off");
  const pitch = Math.round(p.pitch_deg || 0), roll = Math.round(p.roll_deg || 0);
  const slope = pitch === 0 && roll === 0 ? "level ground"
    : [pitch !== 0 ? `${Math.abs(pitch)}° ${pitch > 0 ? "up" : "down"} ahead` : "",
       roll !== 0 ? `${Math.abs(roll)}° down to its ${roll > 0 ? "right" : "left"}` : ""].filter(Boolean).join(", ");
  const sensors = (p.sensors || []).map((s) => {
    return `${sensorName(s)}: ${sensorReading(s)}`;
  });
  const power = energyOf(p);
  const battery = `its battery ${Math.round((p.charge_share || 0) * 100)}%`
    + (power ? ` (${joulesSaid(power.store.charge_j)} of ${joulesSaid(power.store.capacity_j)})` : "")
    + (p.rest_below > 0 ? `, resting below ${Math.round(p.rest_below * 100)}%` : "")
    + spendingSaid(power)
    + (p.kind === "hover" ? ` · ${(p.height_m || 0).toFixed(2)} m up, holding ${p.hover_m} m` : "");
  setText("mp-measured", `${battery} · ${p.turns} turn${p.turns === 1 ? "" : "s"} away · ${slope}`
    + (sensors.length ? ` · sensors: ${sensors.join("; ")}` : ""));
  setText("mp-condition", p.power ? (p.why || "nothing in its way") : "off");
  $("mp-condition").classList.toggle("attention",
    p.power && /water|ground drop|steeper|progress|gone|battery is low/.test(p.why || ""));
  showBrain(p);
  showMachineHolds();
  setText("mp-ack", machinePanel.said);
  $("mp-ack").classList.toggle("stale", machinePanel.stale);
  if ($("machine-panel").hidden) $("machine-panel").hidden = false;
}

// Who decides for this program -- its reflexes, Jev, or the chat's OpenAI
// model -- and what was decided last. A decider without its key in the local
// .env cannot be pressed, and its button says why.
function showBrain(p) {
  const brain = world.brains.get(p.name) || null;
  const mode = brain ? brain.mode : "reflex";
  const configured = (brain && brain.configured) || {};
  const labels = (brain && brain.labels) || {};
  $("mp-brain").hidden = false;
  setPressed("mp-brain-reflex", mode === "reflex");
  setPressed("mp-brain-jev", mode === "jev", !configured.jev);
  setPressed("mp-brain-openai", mode === "openai", !configured.openai);
  $("mp-brain-jev").title = configured.jev ? "Ask Jev what to do at each thing that happens to it"
    : "TYPESAFE_API_KEY is not in the local .env, so Jev cannot be asked";
  $("mp-brain-openai").title = configured.openai
    ? `Ask ${labels.openai || "the chat's model"} what to do at each thing that happens to it`
    : "OPENAI_API_KEY is not in the local .env, so the model cannot be asked";
  const who = labels[mode] || (mode === "jev" ? "Jev" : "the model");
  showRoutine(brain && brain.routine);
  showBatchWatch(p, brain && brain.routine);
  const last = brain && brain.decisions && brain.decisions.length ? brain.decisions[brain.decisions.length - 1] : null;
  const decided = $("mp-decided");
  if (brain && brain.thinking) { decided.textContent = `Asking ${who} about: ${brain.thinking}…`; decided.hidden = false; }
  else if (mode !== "reflex" && last) { decided.textContent = last.said + (last.applied === "applied" ? "" : last.applied ? ` (${last.applied})` : ""); decided.hidden = false; }
  else if (mode !== "reflex") { decided.textContent = `${who} has not been asked anything yet: nothing has happened to it.`; decided.hidden = false; }
  else { decided.hidden = true; }
  decided.classList.toggle("attention", !!(brain && brain.thinking));
  $("mp-talk").hidden = !$("mp-chat").hidden;
  if (!$("mp-chat").hidden && machinePanel.talkingTo !== p.name) closeTalk(false);
}

// Its routine (docs/machine-world.md, "A machine's senses and its tools"):
// what it does on its own, which step it is on, what it carries, and who has
// it instead when it waits.
function showRoutine(r) {
  const line = $("mp-routine");
  if (!r || !r.of) { line.hidden = true; return; }
  // What is IN the hopper is a slot of its own above this line now, so the
  // line says only what the slot cannot: how many loads have gone.
  const load = r.load && r.load.trips
    ? ` · ${r.load.trips} load${r.load.trips === 1 ? "" : "s"} delivered (${Math.round(r.load.delivered_kg)} kg)` : "";
  const paused = r.paused_by ? ` · waiting: ${r.paused_by} has it` : "";
  const note = r.notes && r.notes.length ? ` · ${r.notes[r.notes.length - 1]}` : "";
  const on = r.on ? ` · on ${r.on}: ${r.doing}` : "";
  const orders = r.orders && r.orders.length ? ` · ${r.orders.length} order${r.orders.length === 1 ? "" : "s"} to do` : "";
  const watches = r.watches ? ` · watching ${r.watches} thing${r.watches === 1 ? "" : "s"}` : "";
  line.textContent = `Routine: ${r.kind}, step ${r.step} of ${r.of} (${r.doing})${on}${orders}${watches}${load}${paused}${note}`;
  line.hidden = false;
}

async function setBrain(mode) {
  const c = shownControl();
  if (!c || machinePanel.of !== "program") return;
  try {
    const brain = await api("/api/world/rover/brain", { session: world.session, program: c.name, mode });
    followBrains([brain]);
    machinePanel.said = mode === "reflex" ? "Its reflexes alone decide for it now."
      : `${(brain.labels || {})[mode] || mode} decides for it now, at each thing that happens to it.`;
    machinePanel.stale = false;
  } catch (error) {
    machinePanel.stale = true;
    machinePanel.said = error.message || String(error);
  }
  showMachinePanel();
}
$("mp-brain-reflex").addEventListener("click", () => setBrain("reflex"));
$("mp-brain-jev").addEventListener("click", () => setBrain("jev"));
$("mp-brain-openai").addEventListener("click", () => setBrain("openai"));

// Talking to it (docs/machine-world.md, "Talking to the rover"): opened, it
// stops and turns to face the person; what they type is sorted and done, and
// it answers from its own state; "Let it go on" lifts the ask.
function sayInChat(who, words) {
  const li = document.createElement("li");
  if (who === "you") li.className = "you";
  const label = document.createElement("span");
  label.className = "who";
  label.textContent = who === "you" ? "You" : titled(who);
  li.append(label, document.createTextNode(words));
  $("mp-chat-log").append(li);
  $("mp-chat-log").scrollTop = $("mp-chat-log").scrollHeight;
}
async function talkTo(body) {
  const c = shownControl();
  if (!c || machinePanel.of !== "program") throw new Error("no machine with a program is shown");
  const answer = await api("/api/world/rover/talk", { session: world.session, program: c.name, person: whereIAm(), ...body });
  if (answer.program) mergeProgram(answer.program);
  return answer;
}
async function openTalk() {
  const c = shownControl();
  if (!c) return;
  $("mp-chat-log").replaceChildren();
  $("mp-chat").hidden = false;
  $("mp-talk").hidden = true;
  machinePanel.talkingTo = c.name;
  try {
    const answer = await talkTo({ open: true });
    for (const turn of answer.talk || []) sayInChat(turn.who, turn.said);
    if (!(answer.talk || []).length) sayInChat(c.name, answer.reply);
  } catch (error) {
    sayInChat(c.name, `(${error.message || error})`);
  }
  $("mp-chat-say").focus({ preventScroll: true });
  showMachinePanel();
}
async function closeTalk(tell = true) {
  const name = machinePanel.talkingTo;
  machinePanel.talkingTo = null;
  $("mp-chat").hidden = true;
  $("mp-talk").hidden = false;
  if (!tell || !name) return;
  try {
    const c = programsNow().find((p) => p.name === name);
    if (c) {
      const answer = await api("/api/world/rover/talk", { session: world.session, program: name, close: true });
      if (answer.program) mergeProgram(answer.program);
    }
  } catch { /* it goes on when the ask runs out, or on the next open */ }
  showMachinePanel();
}
$("mp-talk").addEventListener("click", openTalk);
$("mp-chat-close").addEventListener("click", () => closeTalk(true));
$("mp-chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const said = $("mp-chat-say").value.trim();
  if (!said) return;
  $("mp-chat-say").value = "";
  sayInChat("you", said);
  $("mp-chat-send").disabled = true;
  try {
    const answer = await talkTo({ said });
    sayInChat(machinePanel.talkingTo || "it", answer.reply);
  } catch (error) {
    sayInChat(machinePanel.talkingTo || "it", `(${error.message || error})`);
  } finally {
    $("mp-chat-send").disabled = false;
    $("mp-chat-say").focus({ preventScroll: true });
  }
});

$("mp-close").addEventListener("click", closeMachinePanel);
$("mp-on").addEventListener("click", async () => {
  machinePanel.poweringOn = true;
  showMachinePanel();
  try { await commandMachine({ power: true }); } finally { machinePanel.poweringOn = false; showMachinePanel(); }
});
$("mp-off").addEventListener("click", () => commandMachine({ power: false }));
$("mp-back").addEventListener("click", () => commandMachine({ direction: -1 }));
$("mp-stop").addEventListener("click", () => commandMachine({ direction: 0 }));
$("mp-ahead").addEventListener("click", () => commandMachine({ direction: 1 }));
$("mp-setting").addEventListener("input", () => setText("mp-setting-value", `${$("mp-setting").value}%`));
$("mp-setting").addEventListener("change", () => commandMachine({ setting: Number($("mp-setting").value) / 100 }));

// Which way a machine turns, on the machine itself (the owner's review): a
// stripe painted along the part that turns, which turns with it, and an arrow
// round its shaft in the shaft's own frame, the way the motor is driving it --
// green raising or forward, amber lowering or in reverse -- shown only while it
// drives.
const STRIPE_PAINT = new THREE.MeshStandardMaterial({ color: 0xf0b429, roughness: 0.55, metalness: 0.1 });
const ARROW_AHEAD = new THREE.MeshStandardMaterial({ color: 0x7ee08a, emissive: 0x1f4424, roughness: 0.45,
                                                     side: THREE.DoubleSide });
const ARROW_BACK = new THREE.MeshStandardMaterial({ color: 0xf0b429, emissive: 0x4a3510, roughness: 0.45,
                                                    side: THREE.DoubleSide });
const machineMarks = new Map();   // controller id -> { host, stripe, arrow, radius }

// Along which of a box's own axes a direction in the world runs: 0, 1 or 2.
function alongAxis(mesh, axisWorld) {
  const local = new THREE.Vector3(axisWorld[0], axisWorld[1], axisWorld[2])
    .applyQuaternion(mesh.quaternion.clone().invert());
  const size = [Math.abs(local.x), Math.abs(local.y), Math.abs(local.z)];
  return size.indexOf(Math.max(...size));
}

// Along the shaft (k) on the face across the next axis, a fifth as wide as the
// third: in the turning part's own frame, so it turns with it.
function stripeFor(dims, k) {
  const j = (k + 1) % 3, i = (k + 2) % 3;
  const size = [0, 0, 0];
  size[k] = Math.max(dims[k] * 0.92, 0.01);
  size[j] = 0.006;
  size[i] = Math.max(dims[i] * 0.2, 0.01);
  const stripe = new THREE.Mesh(new THREE.BoxGeometry(size[0], size[1], size[2]), STRIPE_PAINT);
  const at = [0, 0, 0];
  at[j] = dims[j] / 2 + 0.002;
  stripe.position.set(at[0], at[1], at[2]);
  return stripe;
}

// On an exact body, the stripe on each wheel that turns about the pin -- the
// widest round parts whose own axis is the pin's -- as a spoke painted on its
// outer face, in the body's own frame so it turns with it. Laid along the
// body's box, as on a drum, it was a yellow plank floating between a
// wheelset's two wheels. Null when the body has no such part.
function spokesFor(parts, axisLocal) {
  const up = new THREE.Vector3(0, 1, 0);
  const round = [];
  for (const part of parts || []) {
    if (part.shape !== "cylinder") continue;
    const q = part.rotation_wxyz || [1, 0, 0, 0];
    const along = up.clone().applyQuaternion(new THREE.Quaternion(q[1], q[2], q[3], q[0]));
    if (Math.abs(along.dot(axisLocal)) > 0.99) round.push({ part, along });
  }
  const widest = Math.max(0, ...round.map((r) => r.part.dimensions_m[0]));
  const spokes = new THREE.Group();
  for (const { part, along } of round) {
    const [d, length] = part.dimensions_m;
    if (d < 0.9 * widest) continue;                  // an axle through the wheels
    const centre = new THREE.Vector3(...part.center_local_m);
    const out = centre.dot(along) < 0 ? along.clone().negate() : along.clone();
    const radial = new THREE.Vector3(1, 0, 0).cross(out);
    if (radial.lengthSq() < 1e-6) radial.set(0, 1, 0).cross(out);
    radial.normalize();
    const third = new THREE.Vector3().crossVectors(radial, out);
    const spoke = new THREE.Mesh(new THREE.BoxGeometry(0.42 * d, 0.006, 0.12 * d), STRIPE_PAINT);
    spoke.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(radial, out, third));
    spoke.position.copy(centre).addScaledVector(out, length / 2 + 0.003).addScaledVector(radial, 0.26 * d);
    spokes.add(spoke);
  }
  return spokes.children.length ? spokes : null;
}

function disposeStripe(stripe) {
  stripe.parent?.remove(stripe);
  stripe.traverse((o) => o.geometry?.dispose());
}

// Most of a ring with a head on its end, the positive way round +z.
function arrowFor(radius) {
  const arrow = new THREE.Group();
  const sweep = Math.PI * 1.4;
  arrow.add(new THREE.Mesh(new THREE.TorusGeometry(radius, 0.011, 8, 40, sweep), ARROW_AHEAD));
  const head = new THREE.Mesh(new THREE.ConeGeometry(0.03, 0.075, 14), ARROW_AHEAD);
  head.position.set(radius * Math.cos(sweep), radius * Math.sin(sweep), 0);
  head.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0),
                                     new THREE.Vector3(-Math.sin(sweep), Math.cos(sweep), 0));
  arrow.add(head);
  return arrow;
}

function forgetMarks(marks) {
  if (marks.stripe) disposeStripe(marks.stripe);
  if (marks.arrow) { scene.remove(marks.arrow); marks.arrow.traverse((o) => o.geometry?.dispose()); }
}

function dressMachines() {
  const seen = new Set();
  const motors = (world.machines && world.machines.motors) || [];
  for (const c of controlsNow()) {
    const motor = motors.find((m) => m.id === c.motor);
    const pin = motor && (world.joints || []).find((j) => j.id === motor.joint);
    if (!motor || !pin || !pin.attached || !motor.on) continue;
    // The part that turns: of the pin's two, the one not fixed in place.
    const [a, b] = motor.on;
    const second = world.bodies.get(b);
    const turning = second && !second.anchored ? b : a;
    const body = world.bodies.get(turning);
    if (!body || body.fromCells || !body.dims || body.shape === "sphere") continue;
    seen.add(c.id);
    let marks = machineMarks.get(c.id);
    if (!marks) {
      marks = { host: null, stripe: null, arrow: null, radius: 0 };
      machineMarks.set(c.id, marks);
    }
    const axis = pin.axis || [0, 1, 0];
    const k = alongAxis(body.mesh, axis);
    // The stripe rides the turning part's own mesh, so it turns with it: put on
    // again whenever that mesh is made again (a dent, a burn).
    if (marks.host !== body.mesh) {
      if (marks.stripe) disposeStripe(marks.stripe);
      const axisLocal = new THREE.Vector3(axis[0], axis[1], axis[2]).normalize()
        .applyQuaternion(body.mesh.quaternion.clone().invert());
      marks.stripe = (body.fromPrecise && spokesFor(body.parts, axisLocal)) || stripeFor(body.dims, k);
      body.mesh.add(marks.stripe);
      marks.host = body.mesh;
    }
    const radius = Math.max(...body.dims.filter((_, i) => i !== k)) * 0.72 + 0.04;
    if (!marks.arrow || Math.abs(marks.radius - radius) > 1e-6) {
      if (marks.arrow) { scene.remove(marks.arrow); marks.arrow.traverse((o) => o.geometry?.dispose()); }
      marks.arrow = arrowFor(radius);
      marks.radius = radius;
      scene.add(marks.arrow);
    }
    // Just past the turning part's end, round the pin's axis, the way the motor
    // drives: its command turns b about the axis relative to a.
    const drives = c.power && c.command !== 0;
    marks.arrow.visible = drives;
    if (!drives) continue;
    const along = new THREE.Vector3(axis[0], axis[1], axis[2]).normalize();
    const way = Math.sign(c.command) * (turning === b ? 1 : -1);
    marks.arrow.position.copy(body.mesh.position).addScaledVector(along, body.dims[k] / 2 + 0.03);
    marks.arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), along);
    marks.arrow.scale.set(way < 0 ? -1 : 1, 1, 1);
    const paint = c.direction > 0 ? ARROW_AHEAD : ARROW_BACK;
    marks.arrow.traverse((o) => { if (o.isMesh && o.material !== paint) o.material = paint; });
  }
  for (const [id, marks] of machineMarks) {
    if (seen.has(id)) continue;
    forgetMarks(marks);
    machineMarks.delete(id);
  }
}

// Where each controller's sensors look (the runner's `sensors`, docs/machine-
// world.md): a bead at the point and a thread from it straight down to the
// ground, since a water sensor reads the water under it -- blue while it reads
// less than its depth, amber once it sees more, which is what stops the machine.
// So why a cart stopped is there on the ground in front of it.
const SENSOR_DRY = new THREE.MeshStandardMaterial({ color: 0x6fb7ff, emissive: 0x16324a, roughness: 0.5 });
const SENSOR_SEES = new THREE.MeshStandardMaterial({ color: 0xf0b429, emissive: 0x4a3510, roughness: 0.5 });
const sensorMarks = new Map();   // "controller id/sensor index" -> { bead, thread }

function dressSensors() {
  const seen = new Set();
  const carriers = [...controlsNow().map((c) => ["", c]), ...programsNow().map((p) => ["program ", p])];
  for (const [of, c] of carriers) {
    (c.sensors || []).forEach((s, i) => {
      if (!Array.isArray(s.at_m) || s.at_m.length !== 3) return;
      const key = `${of}${c.id}/${i}`;
      seen.add(key);
      let mark = sensorMarks.get(key);
      if (!mark) {
        mark = { bead: new THREE.Mesh(new THREE.SphereGeometry(0.03, 16, 12), SENSOR_DRY),
                 thread: new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.004, 1, 6), SENSOR_DRY) };
        scene.add(mark.bead, mark.thread);
        sensorMarks.set(key, mark);
      }
      const [x, y, z] = s.at_m;
      const floor = ground.grid ? Math.min(groundAt(x, z), y) : y;
      mark.bead.position.set(x, y, z);
      mark.thread.position.set(x, (y + floor) / 2, z);
      mark.thread.scale.set(1, Math.max(y - floor, 1e-3), 1);
      const paint = s.sees ? SENSOR_SEES : SENSOR_DRY;
      if (mark.bead.material !== paint) mark.bead.material = mark.thread.material = paint;
    });
  }
  for (const [key, mark] of sensorMarks) {
    if (seen.has(key)) continue;
    scene.remove(mark.bead, mark.thread);
    mark.bead.geometry.dispose();
    mark.thread.geometry.dispose();
    sensorMarks.delete(key);
  }
}

// Where goods go into a device and where they come out (docs/machine-world.md,
// "Devices that pair"): a ring at the mouth, lying in the plane of its face,
// with a cone through it pointing the way the goods go -- out along the face
// for a port that gives, back into the device for one that takes. So which end
// of a smelter is its intake is there on the smelter, and the rover's store
// shows at the front of its deck and turns with it.
//
// The ring is steel while nothing is alongside, amber while another mouth is
// near but the two are not paired -- too far apart, or turned away -- and green
// while they are docked and goods can pass. The playground works out which
// (machine_ports.Ports) and says so with every step, so the page and the
// machine never disagree about whether a dock is made: what is drawn green is
// exactly what the dock tool would move goods through.
const PORT_IDLE = new THREE.MeshStandardMaterial({ color: 0x9fb3c8, emissive: 0x1b2733, roughness: 0.5 });
const PORT_NEAR = new THREE.MeshStandardMaterial({ color: 0xf0b429, emissive: 0x4a3510, roughness: 0.5 });
const PORT_DOCKED = new THREE.MeshStandardMaterial({ color: 0x7ee08a, emissive: 0x1f4424, roughness: 0.45 });
const PORT_R = 0.09;               // the mouth's ring: a hand's width across
const portMarks = new Map();       // port name -> { ring, cone }

function dressPorts() {
  const seen = new Set();
  for (const p of world.ports || []) {
    if (!Array.isArray(p.at_m) || p.at_m.length !== 3) continue;
    if (!Array.isArray(p.normal) || p.normal.length !== 3) continue;
    seen.add(p.name);
    let mark = portMarks.get(p.name);
    if (!mark) {
      mark = { ring: new THREE.Mesh(new THREE.TorusGeometry(PORT_R, 0.012, 8, 24), PORT_IDLE),
               cone: new THREE.Mesh(new THREE.ConeGeometry(0.045, 0.11, 14), PORT_IDLE) };
      scene.add(mark.ring, mark.cone);
      portMarks.set(p.name, mark);
    }
    const along = new THREE.Vector3(p.normal[0], p.normal[1], p.normal[2]).normalize();
    const at = new THREE.Vector3(p.at_m[0], p.at_m[1], p.at_m[2]);
    mark.ring.position.copy(at);
    mark.ring.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), along);
    const way = p.flow === "out" ? along : along.clone().negate();
    mark.cone.position.copy(at).addScaledVector(way, 0.07);
    mark.cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), way);
    const paint = p.docked ? PORT_DOCKED : (p.near ? PORT_NEAR : PORT_IDLE);
    if (mark.ring.material !== paint) mark.ring.material = mark.cone.material = paint;
  }
  for (const [name, mark] of portMarks) {
    if (seen.has(name)) continue;
    scene.remove(mark.ring, mark.cone);
    mark.ring.geometry.dispose();
    mark.cone.geometry.dispose();
    portMarks.delete(name);
  }
}

// ---------------------------------------------------------------------------
// Slots: what everything that can hold something is holding
// ---------------------------------------------------------------------------
//
// The owner, 2026-09-26: "also have slots for anything that can hold things and
// show the material being held it is so we can see it happen more as it goes."
//
// Four kinds of thing in a room hold material, and only the first of them could
// be seen:
//
//   * the person -- their hands, their bag, and the sand and soil they carry,
//     all in the Bag tab, which is left as it is: what a person carries is the
//     GROUND's account (the spade's cubic metres), and mixing it into the same
//     strip as the goods would say the two ledgers were one;
//   * a machine's hopper (machine_routine.Routine), which was six words at the
//     end of the routine's one line: "hopper 12 of 40 kg";
//   * a heap on the ground (machine_goods.Goods). This reached the page for the
//     first time with this work: a stockpile was a number in the room's spec,
//     and nothing on the page said it or drew it, so the ore the rover tipped
//     into the smelter simply vanished as far as anybody watching could tell;
//   * the ore still in the ground -- a deposit -- likewise.
//
// The last three are drawn the same way, because they are the same thing: a
// name, and one slot per substance in it with that substance's mass. A holder
// that has a known capacity -- a hopper, a deposit's reserve -- gets the bar
// too, so how full it is reads without arithmetic.
//
// A slot whose mass moved since the last step lights for a moment, green for
// more and amber for less. That is what makes a chain legible while it runs
// rather than after it: the ore leaves the rover's hopper amber and arrives in
// the smelter's intake green, in the same second, and a person watching can
// see WHERE the stuff went instead of only that a number changed.
//
// WHAT IS NOT MODELLED. A slot is an account, not a picture of a pile: nothing
// is drawn on the ground where a heap is, a heap has no shape, no angle of
// repose and no volume, two substances in one heap neither mix nor separate,
// and a heap cannot be full. A deposit's mass is what the room's ledger says is
// still down there, not a measurement of the ground. The colours are tints
// picked from the substance's NAME, so that two slots can be told apart at a
// glance; nothing anywhere measures what colour copper ore is. Where a
// substance is called after one of the materials the room actually draws with,
// that material's own colour is used instead, so iron in a heap is the grey
// that iron is in the room.

// The room's heaps and the ore left in its ground (rover_brain.Brains.attach),
// with the room when it opens and with a step whenever any of it has moved.
// Nothing said means this reply carried none, which is not the same as a room
// with no heaps -- that is said as empty lists, when the room opens.
world.goods = null;
function followGoods(goods, reset = false) {
  if (goods === undefined) return;
  world.goods = goods || null;
  resourceVisuals.follow(world.goods, reset);
  drawHolds();
}

const SUBSTANCE_TINT = new Map();
function substanceColour(what) {
  const resource={"copper":"#b97647","copper wire":"#db994b","copper ore":"#858c65",
                  "sand and soil":"#96764c","slag":"#666a70"}[what];
  if(resource)return resource;
  const drawn = MATERIAL_LOOK[what];
  if (drawn) return `#${drawn.color.toString(16).padStart(6, "0")}`;
  let tint = SUBSTANCE_TINT.get(what);
  if (tint === undefined) {
    let hash = 0;
    for (let i = 0; i < what.length; i += 1) hash = (hash * 31 + what.charCodeAt(i)) >>> 0;
    tint = `hsl(${hash % 360} 46% 60%)`;
    SUBSTANCE_TINT.set(what, tint);
  }
  return tint;
}

// A mass in a slot. Three figures at most: a slot is read at a glance, and
// "0.28 kg" beside "402.00 kg" is two different questions.
const heldSaid = (kg) => (kg >= 100 ? `${Math.round(kg)} kg`
  : kg >= 1 ? `${kg.toFixed(1)} kg` : `${Math.round(kg * 1000)} g`);


// Resource packets picture recorded ledger transfers. They have no solver
// mass, collisions or fracture impulses; their count is not the mass count.
function goodsVisuals({scene,camera,groundAt,body,ports,colour,collect,readonly}) {
  const root=new THREE.Group(); root.name="resource-packets"; scene.add(root);
  const cube=new THREE.BoxGeometry(.13,.13,.13);
  const materials=new Map(), piles=new Map(), hoppers=new Map(), seams=new Map();
  const matrix=new THREE.Object3D(), flights=[];
  let epoch=null, seen=new Set(), goods=null, brains=[], nearest=null, busy=false, retry=null, failureUntil=0, nextPickup=0;
  const reduced=matchMedia("(prefers-reduced-motion: reduce)").matches;
  const pickup=document.createElement("button");
  pickup.id="collect-output"; pickup.type="button"; pickup.hidden=true;
  async function takeNearby(automatic=false) {
    if (!nearest || busy || readonly()) return;
    busy=true; pickup.disabled=true;
    const pile=retry?.pile || nearest.name;
    const request=retry?.request || crypto.randomUUID(); retry={pile,request};
    try {
      await collect(pile,request,automatic); retry=null;
    } catch(error) { pickup.textContent=error.message; failureUntil=performance.now()+6000; }
    finally { busy=false; pickup.disabled=false; nextPickup=performance.now()+1000; }
  }
  pickup.addEventListener("click",()=>takeNearby(false));
  document.body.append(pickup);
  function material(what) {
    if (!materials.has(what)) {
      const tint=colour(what), hsl=tint.match(/^hsl\((\d+) (\d+)% (\d+)%\)$/);
      const color=hsl ? new THREE.Color().setHSL(Number(hsl[1])/360,Number(hsl[2])/100,Number(hsl[3])/100) : new THREE.Color(tint);
      materials.set(what,new THREE.MeshStandardMaterial({color,roughness:.8}));
    }
    return materials.get(what);
  }
  function label(text) {
    const canvas=document.createElement("canvas"); canvas.width=512; canvas.height=96;
    const ctx=canvas.getContext("2d");
    ctx.fillStyle="rgba(14,24,29,.9)"; ctx.fillRect(0,0,512,96);
    ctx.fillStyle="#f2ece0"; ctx.font="600 26px system-ui"; ctx.textAlign="center";
    ctx.fillText(text,256,57,490);
    const map=new THREE.CanvasTexture(canvas), m=new THREE.SpriteMaterial({map,depthTest:true});
    const sprite=new THREE.Sprite(m); sprite.scale.set(1.6,.3,1); return sprite;
  }
  function remove(group) {
    group.traverse(o=>{
      if(o.isSprite){o.material.map.dispose();o.material.dispose();}
      else if(o.geometry && o.geometry!==cube){o.geometry.dispose();o.material.dispose();}
      if(o.isInstancedMesh)o.dispose();
    });
    root.remove(group);
  }
  function endpoint(e) {
    if(e.player===playerId) return camera.position.clone().add(new THREE.Vector3(0,-.3,0));
    if(e.point_m) return new THREE.Vector3(...e.point_m);
    if(e.body) { const mesh=body(e.body)?.mesh; if(mesh) return mesh.position.clone().add(new THREE.Vector3(0,.45,0)); }
    if(e.port) { const port=ports().find(p=>p.name===e.port); if(port) return new THREE.Vector3(...port.at_m); }
    if(e.pile) {
      const pile=(goods?.stockpiles||[]).find(p=>p.name===e.pile);
      if(pile)return pilePosition(pile).add(new THREE.Vector3(0,.2,0));
    }
    const at=e.at_m || (goods?.stockpiles||[]).find(p=>p.name===e.pile)?.at_m;
    if(at) return new THREE.Vector3(at[0],groundAt(at[0],at[1])+.2,at[1]);
    return null;
  }
  function storage(name) {
    const making=brains.map(b=>b.routine?.making).filter(Boolean);
    if(making.some(m=>m.intake===name))return "input";
    if(making.some(m=>m.output===name))return "output";
    return "stock";
  }
  function pilePosition(p) {
    const port=storage(p.name)==="input" ? ports().find(v=>v.holds===p.name&&v.flow==="in") : null;
    return port ? new THREE.Vector3(...port.at_m) : new THREE.Vector3(p.at_m[0],groundAt(...p.at_m)+.03,p.at_m[1]);
  }
  function follow(next,reset=false) {
    if(next===undefined)return;
    goods=next;
    const events=next?.activities||[];
    if(reset || epoch!==next?.activity_epoch) {
      epoch=next?.activity_epoch; seen=new Set(events.map(e=>e.id));
      for(const f of flights)root.remove(f.mesh); flights.length=0;
    } else {
      for(const e of events) {
        if(seen.has(e.id))continue;
        seen.add(e.id);
        if(reduced || document.hidden)continue;
        const from=endpoint(e.from),to=endpoint(e.to);
        if(!from || !to)continue;
        for(const [what,kg] of Object.entries(e.goods_kg)) {
          const count=Math.min(12,Math.max(2,Math.ceil(Math.sqrt(kg)*2)));
          for(let i=0;i<count && flights.length<192;i++) {
            const mesh=new THREE.Mesh(cube,material(what)); root.add(mesh);
            mesh.userData.transferKind=e.kind;
            flights.push({mesh,from,to,target:e.to,start:performance.now()+i*55+(e.kind==="output"?700:0),index:i});
          }
        }
      }
      seen=new Set(events.map(e=>e.id));
    }
    const keep=new Set();
    for(const p of next?.stockpiles||[]) {
      keep.add(p.name);
      const role=storage(p.name),signature=JSON.stringify([role,p.holds_kg]);
      if(piles.get(p.name)?.signature===signature)continue;
      if(piles.has(p.name))remove(piles.get(p.name).group);
      const group=new THREE.Group(), slots=Object.entries(p.holds_kg).filter(([,kg])=>kg>0);
      group.userData.resourcePile=p.name; group.userData.resourceStorage=role;
      if(role==="input") {
        // Open-topped storage picture at the declared input mouth. Its
        // contents are ledger goods; this adds no native collision or mass.
        const steel=new THREE.MeshStandardMaterial({color:0x607580,roughness:.75,transparent:true,opacity:.55});
        for(const [size,at] of [ [[.88,.04,.72],[0,-.04,0]], [[.04,.48,.72],[-.44,.18,0]],
            [[.04,.48,.72],[.44,.18,0]], [[.88,.48,.04],[0,.18,-.36]], [[.88,.48,.04],[0,.18,.36]] ]) {
          const wall=new THREE.Mesh(new THREE.BoxGeometry(...size),steel.clone());wall.position.set(...at);group.add(wall);
        }
        steel.dispose();
      }
      let n=0;
      for(const [what,kg] of slots) {
        const count=Math.min(16,Math.max(1,Math.ceil(Math.sqrt(kg)*3)));
        const mesh=new THREE.InstancedMesh(cube,material(what),count);
        for(let i=0;i<count;i++,n++) {
          matrix.position.set((n%5-2)*.16,.075+Math.floor(n/25)*.15,(Math.floor(n/5)%5-2)*.16);
          matrix.updateMatrix();mesh.setMatrixAt(i,matrix.matrix);
        }
        group.add(mesh);
      }
      const kg=slots.reduce((a,[,v])=>a+v,0);
      if(kg>0 || role==="input") {
        const title=label(`${role==="input"?"Input hopper":p.name} · ${heldSaid(kg)}`);
        title.position.y=.7; group.add(title);
      }
      group.position.copy(pilePosition(p));
      root.add(group);piles.set(p.name,{group,signature});
    }
    for(const [name,p] of piles)if(!keep.has(name)){remove(p.group);piles.delete(name);}
    const deposits = new Set();
    for (const d of next?.deposits || []) {
      if (!(d.left_kg>0) || !(d.radius_m>0)) continue;
      deposits.add(d.name);
      const signature = JSON.stringify([d.at_m,d.substance,d.radius_m,d.left_kg]);
      if (seams.get(d.name)?.signature === signature) continue;
      if (seams.has(d.name)) remove(seams.get(d.name).group);
      const group = new THREE.Group(); group.userData.resourceDeposit = d.name;
      // Survey markers for ledger extraction areas, not fictitious native ore.
      const ring = new THREE.Mesh(new THREE.RingGeometry(Math.max(.1,d.radius_m-.08),d.radius_m,48),
        new THREE.MeshBasicMaterial({color:material(d.substance).color,transparent:true,opacity:.7,side:THREE.DoubleSide,depthWrite:false}));
      ring.rotation.x = -Math.PI/2; ring.position.y = .07; group.add(ring);
      const title = label(`${d.substance} · ${heldSaid(d.left_kg)}`); title.position.y = .9; group.add(title);
      group.position.set(d.at_m[0],groundAt(...d.at_m)+.02,d.at_m[1]);
      root.add(group); seams.set(d.name,{group,signature});
    }
    for (const [name,s] of seams) if (!deposits.has(name)) {remove(s.group);seams.delete(name);}
  }
  function loads(next) { if(next!==undefined){brains=next;follow(goods);} }
  function advance(now) {
    for (const s of seams.values()) {
      s.group.position.y = groundAt(s.group.position.x,s.group.position.z)+.02;
      for (const child of s.group.children) if(child.isSprite) child.visible = s.group.position.distanceTo(camera.position)<12;
    }
    for(const [name,p] of piles) {
      const pile=(goods?.stockpiles||[]).find(s=>s.name===name);
      if(pile)p.group.position.copy(pilePosition(pile));
      for(const child of p.group.children)if(child.isSprite)
        child.visible=p.group.position.distanceTo(camera.position)<5;
    }
    for(let i=flights.length-1;i>=0;i--) {
      const f=flights[i],t=(now-f.start)/1150;
      f.mesh.visible=t>=0;
      if(t>=1){root.remove(f.mesh);flights.splice(i,1);continue;}
      if(t<0)continue;
      const to=endpoint(f.target)||f.to;
      f.mesh.position.copy(f.from).lerp(to,t);
      f.mesh.position.y+=Math.sin(t*Math.PI)*(.6+f.index*.02);
      f.mesh.rotation.set(t*2,t*3,0);
      if(f.mesh.userData.transferKind==="collect")f.mesh.scale.setScalar(1-.8*t);
    }
    const keep=new Set();
    for(const b of brains) {
      const load=b.routine?.load;
      if(!(load?.capacity_kg>0))continue;
      const port=ports().find(p=>p.machine===b.name&&p.holds==="hopper");
      const position=port ? new THREE.Vector3(...port.at_m) : endpoint({body:b.body});
      if(!position)continue;
      keep.add(b.name);
      let h=hoppers.get(b.name);
      const fill=Math.max(0,Math.min(1,load.kg/load.capacity_kg));
      const signature=`${load.kg}/${load.capacity_kg}`;
      if(!h || h.signature!==signature) {
        if(h)remove(h.group);
        const group=new THREE.Group();
        const box=new THREE.Mesh(new THREE.BoxGeometry(.7,.65,.5),new THREE.MeshBasicMaterial({color:0xf0cd77,wireframe:true}));
        group.add(box);
        for(let i=0;i<Math.ceil(fill*24);i++) {
          const packet=new THREE.Mesh(cube,material(Object.keys(load.goods_kg||{})[0]||"soil"));
          packet.position.set((i%4-1.5)*.16,(Math.floor(i/8)-1)*.15,(Math.floor(i/4)%2-.5)*.16);group.add(packet);
        }
        const title=label(`Hopper · ${Math.round(fill*100)}%`);title.position.y=.65;group.add(title);
        root.add(group);h={group,signature};hoppers.set(b.name,h);
      }
      h.group.position.copy(position).add(new THREE.Vector3(0,.7,0));
    }
    for(const [name,h] of hoppers)if(!keep.has(name)){remove(h.group);hoppers.delete(name);}
    nearest=(goods?.stockpiles||[]).filter(p=>!p.rack&&storage(p.name)!=="input"&&(p.name===retry?.pile||Object.values(p.holds_kg).some(v=>v>0)))
      .map(p=>({...p,d:Math.hypot(camera.position.x-p.at_m[0],camera.position.z-p.at_m[1])}))
      .filter(p=>p.d<=2).sort((a,b)=>a.d-b.d)[0];
    pickup.hidden=!nearest || readonly();
    if(!busy && nearest && now>failureUntil) {
      const kg=Math.min(25,Object.values(nearest.holds_kg).reduce((a,v)=>a+v,0));
      pickup.textContent=retry ? `Retry collection · ${retry.pile}` : `Collect ${heldSaid(kg)} · ${nearest.name} → Your inventory`;
    }
    pickup.dataset.pile=nearest?.name||"";
    if(nearest && storage(nearest.name)==="output" && nearest.d<=1.6 && !readonly() && !busy &&
        !retry && now>nextPickup && now>failureUntil && movementMode==="gravity" && !whatIsRidden() &&
        camera.position.y-groundAt(...nearest.at_m)>=0 && camera.position.y-groundAt(...nearest.at_m)<=3)
      void takeNearby(true);
  }
  return {follow,loads,advance};
}

const resourceVisuals = goodsVisuals({scene,camera,groundAt,
  body:name=>world.bodies.get(name), ports:()=>world.ports,
  colour:substanceColour, readonly:()=>!!watchedId || !worldId,
  collect:async(pile,request_id,automatic=false)=>{
    const answer=await api('/api/world/goods/collect',{session:world.session,pile,request_id,automatic,person:whereIAm()});
    followGoods(answer.goods);
    lastAction(`+ ${Object.entries(answer.collected).map(([what,kg])=>`${heldSaid(kg)} ${what}`).join(' · ')} → Inventory`);
    return answer;
  }});

// What a container on that body holds, said in the fewest words that are
// still true: "holding 18.0 kg of sand, 20 C", or "empty". Temperature only
// when it is worth saying -- a pail at room temperature is just a pail, and a
// line that always ends in "20 C" stops being read.
function vesselLine(body) {
  const mine = (world.vessels || []).filter((v) => v.body === body);
  if (!mine.length) return "";
  return mine.map((vessel) => {
    const slots = Object.entries(vessel.holds_kg || {})
      .filter(([, kg]) => Number(kg) > 0.0005)
      .map(([what, kg]) => `${Number(kg).toFixed(1)} kg of ${what}`);
    const warmth = Math.abs(Number(vessel.temperature_c) - 20) >= 2
      ? `, ${Math.round(Number(vessel.temperature_c))} C` : "";
    const tipping = Number(vessel.pouring) > 0 ? ", pouring" : "";
    return slots.length ? `holding ${slots.join(" and ")}${warmth}${tipping}`
                        : `empty${tipping}`;
  }).join(" · ");
}

// Everything in the room that holds something, in an order that does not move:
// each machine's hopper, then the room's heaps as the room declares them, then
// the ore in its ground. Never sorted by how much is in them -- a row that
// jumps up the list as it fills is a row you cannot watch.
function holdersNow() {
  const holders = [];
  for (const brain of world.brains.values()) {
    const load = (brain.routine && brain.routine.load) || null;
    if (!load || !(load.capacity_kg > 0)) continue;
    const slots = Object.entries(load.goods_kg || {}).map(([what, kg]) => ({ what, kg: Number(kg) || 0 }));
    // What is in the hopper besides the named substances: the spade's own
    // sand and soil, which is most of a scoop. `kg` is the whole load.
    const spoil = (Number(load.kg) || 0) - slots.reduce((sum, s) => sum + s.kg, 0);
    if (spoil > 0.001) slots.push({ what: "sand and soil", kg: spoil });
    holders.push({ key: `hopper ${brain.name}`, machine: brain.name, name: `${titled(brain.name)}: its hopper`,
                   kind: "hopper", slots, kg: Number(load.kg) || 0, capacity_kg: Number(load.capacity_kg) || 0 });
  }
  const goods = world.goods || {};
  for (const pile of goods.stockpiles || []) {
    const slots = Object.entries(pile.holds_kg || {}).map(([what, kg]) => ({ what, kg: Number(kg) || 0 }));
    holders.push({ key: `pile ${pile.name}`, pile: pile.name, name: titled(pile.name),
                   kind: pile.rack ? "the Workshop's rack" : "heap", slots,
                   kg: slots.reduce((sum, s) => sum + s.kg, 0), capacity_kg: 0 });
  }
  for (const seam of goods.deposits || []) {
    const left = Number(seam.left_kg) || 0;
    holders.push({ key: `ore ${seam.name}`, name: titled(seam.name), kind: "in the ground",
                   slots: left > 0.0005 ? [{ what: seam.substance, kg: left }] : [],
                   kg: left, capacity_kg: Number(seam.of_kg) || 0 });
  }
  // And every container. A heap is a place and stays where it is put; a
  // container rides the body that carries it, so it says what it is riding
  // and, when it has been turned far enough to pour, that it is pouring.
  for (const vessel of world.vessels || []) {
    const slots = Object.entries(vessel.holds_kg || {}).map(([what, kg]) => ({ what, kg: Number(kg) || 0 }));
    const tipping = Number(vessel.pouring) > 0;
    holders.push({ key: `vessel ${vessel.name}`, body: vessel.body, name: titled(vessel.name),
                   kind: tipping ? "pouring" : "a container", slots,
                   kg: slots.reduce((sum, s) => sum + s.kg, 0),
                   capacity_kg: Number(vessel.capacity_kg) || 0 });
  }
  return holders;
}

// How long a slot stays lit after its mass moved. Long enough to catch out of
// the corner of the eye while the room runs, short enough that a busy chain
// does not end up with every slot lit at once.
const SLOT_LIT_MS = 1200;
// One card per holder per list, made once and then only written to: the whole
// list was rebuilt from nothing on every step in an earlier draft, which threw
// away the "it just moved" light with the element it was on.
const holdCards = new Map();     // "<list id> <holder key>" -> the card

function holdCard(list, holder) {
  const key = `${list.id} ${holder.key}`;
  let card = holdCards.get(key);
  if (!card) {
    const li = document.createElement("li");
    li.className = "hold";
    const head = document.createElement("p");
    head.className = "hold-head";
    const name = document.createElement("span");
    name.className = "hold-name";
    const of = document.createElement("span");
    of.className = "hold-of";
    head.append(name, of);
    const bar = document.createElement("span");
    bar.className = "meter-bar";
    bar.hidden = true;
    const fill = document.createElement("i");
    bar.append(fill);
    const slots = document.createElement("ul");
    slots.className = "hold-slots";
    li.append(head, bar, slots);
    card = { li, name, of, bar, fill, slots, rows: new Map(), drawn: false };
    holdCards.set(key, card);
  }
  return card;
}

// Nothing else redraws the slots once the room has gone quiet: the brains and
// the goods reach the page only when they have changed, so a slot emptied and
// kept while it was lit would stay at nothing until the next thing moved --
// which was measured lingering for eight seconds in the mine. One redraw is
// asked for after the last light goes out, however many went out together.
let holdsSettle = 0;

function litSlot(row, way) {
  if (row.lit) clearTimeout(row.lit);
  row.li.classList.remove("up", "down");
  row.li.classList.add(way);
  row.moved = way;
  row.lit = setTimeout(() => {
    row.lit = 0;
    row.moved = null;
    row.li.classList.remove("up", "down");
    clearTimeout(holdsSettle);
    holdsSettle = setTimeout(drawHolds, 30);
  }, SLOT_LIT_MS);
}

function fillHoldCard(card, holder) {
  if (card.name.textContent !== holder.name) card.name.textContent = holder.name;
  const of = holder.capacity_kg > 0
    ? `${holder.kind} · ${heldSaid(holder.kg)} of ${heldSaid(holder.capacity_kg)}`
    : holder.kind;
  if (card.of.textContent !== of) card.of.textContent = of;
  const full = holder.capacity_kg > 0 ? Math.max(0, Math.min(1, holder.kg / holder.capacity_kg)) : 0;
  card.bar.hidden = !(holder.capacity_kg > 0);
  const width = `${(full * 100).toFixed(1)}%`;
  if (card.fill.style.width !== width) card.fill.style.width = width;
  // A card drawn for the first time lights nothing: at a room's open, and
  // when a machine's panel is opened again, every slot in it is new and none
  // of it moved. After that a slot that was not there IS a move -- the first
  // ore into an empty heap is the whole thing worth watching -- so it lights
  // like any other.
  const settled = card.drawn;
  card.drawn = true;
  const shown = [];
  for (const slot of holder.slots) {
    let row = card.rows.get(slot.what);
    if (!row) {
      const li = document.createElement("li");
      li.className = "hold-slot";
      const swatch = document.createElement("i");
      swatch.style.setProperty("--c", substanceColour(slot.what));
      const what = document.createElement("span");
      what.textContent = slot.what;
      const much = document.createElement("b");
      li.append(swatch, what, much);
      row = { li, much, was: null, lit: 0, moved: null, gone: false };
      card.rows.set(slot.what, row);
      if (settled && slot.kg > 0.0005) litSlot(row, "up");
    }
    row.gone = false;
    const said = heldSaid(slot.kg);
    if (row.much.textContent !== said) row.much.textContent = said;
    if (row.was !== null && Math.abs(slot.kg - row.was) > 0.0005) litSlot(row, slot.kg > row.was ? "up" : "down");
    row.was = slot.kg;
    shown.push(row.li);
  }
  // A substance that has left: it stays at nothing while its light is on --
  // the last kilogram going is exactly the moment worth seeing -- and goes on
  // the render after the light does.
  for (const [what, row] of card.rows) {
    if (holder.slots.some((s) => s.what === what)) continue;
    if (!row.gone) {
      row.gone = true;
      if (row.was > 0.0005) litSlot(row, "down");
      row.was = 0;
      row.much.textContent = heldSaid(0);
    }
    if (row.lit) shown.push(row.li);
    else card.rows.delete(what);
  }
  if (!shown.length) {
    if (!card.empty) {
      card.empty = document.createElement("li");
      card.empty.className = "hold-slot none";
      card.empty.textContent = "empty";
    }
    shown.push(card.empty);
  }
  if (card.slots.children.length !== shown.length || shown.some((li, i) => card.slots.children[i] !== li))
    card.slots.replaceChildren(...shown);
  return card.li;
}

// One list of holders drawn into one <ul>: the Room tab's, which is every
// holder in the room, and the machine panel's, which is the open machine's.
function drawHoldList(list, holders) {
  const rows = holders.map((holder) => fillHoldCard(holdCard(list, holder), holder));
  if (list.children.length !== rows.length || rows.some((li, i) => list.children[i] !== li))
    list.replaceChildren(...rows);
  const keep = new Set(holders.map((h) => `${list.id} ${h.key}`));
  for (const key of holdCards.keys())
    if (key.startsWith(`${list.id} `) && !keep.has(key)) holdCards.delete(key);
  return rows.length;
}

const HOLDS_NOTE = "Walk within 2 m of an output pile to collect it into your Inventory."
  + " Cubes show resource quantities; they are not breakable bodies.";

function drawHolds() {
  const all = holdersNow();
  const many = drawHoldList($("holds-list"), all);
  $("holds").hidden = many === 0;
  if ($("holds-note").textContent !== HOLDS_NOTE) $("holds-note").textContent = HOLDS_NOTE;
  showMachineHolds(all);
}

// What the machine whose panel is open holds: its own hopper, and the heap
// behind each of its mouths, which is where its goods come from and go to. A
// mouth's line says which way and whether it is docked, so the moment the
// rover's store and the smelter's intake pair up is on the panel of either.
function machineHolders(c, all) {
  if (!c || machinePanel.of !== "program") return [];
  const mine = [];
  const hopper = all.find((h) => h.key === `hopper ${c.name}`);
  if (hopper) mine.push(hopper);
  const atThe = (port) => `${port.flow === "out" ? "goods out" : "goods in"} · `
    + (port.docked ? `docked to ${port.docked}`
       : port.near ? "a mouth near it, not docked" : "nothing alongside");
  for (const port of world.ports || []) {
    if (port.machine !== c.name) continue;
    // A mouth onto the machine's OWN hopper -- the rover's store -- is not a
    // second holder: it is the same hopper with a mouth on it, so the dock
    // goes on the hopper's own card rather than making a card that would
    // show the same kilograms twice.
    if (port.holds === "hopper") {
      if (hopper) hopper.kind = `${titled(port.name)} · ${atThe(port)}`;
      continue;
    }
    const behind = all.find((h) => h.key === `pile ${port.holds}`);
    if (!behind) continue;
    mine.push({ ...behind, key: `${behind.key} at ${port.name}`,
                name: `${titled(port.name)}: ${behind.name.toLowerCase()}`,
                kind: atThe(port) });
  }
  // And any container riding the machine's own body -- a bucket on a cart
  // goes where the cart goes, so what is in it belongs on the cart's panel.
  for (const holder of all) {
    if (holder.body && holder.body === c.body) mine.push(holder);
  }
  return mine;
}

function showMachineHolds(all = holdersNow()) {
  const list = $("mp-holds-list");
  const mine = machinePanel.id == null ? [] : machineHolders(shownControl(), all);
  const many = drawHoldList(list, mine);
  $("mp-holds").hidden = many === 0;
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
        pin.kind === "elastic" || pin.kind === "drum") continue;
    // Away in the bag with the thing it is in: nothing of it is in the room
    // for a pin to be drawn on, and it is not a pin that came off.
    if (pin.away) continue;
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

// How close you have to be, and how big a piece can be and still be something
// you walk off with.
//
// 64 cells was a fragment you could hold in one hand, and it left the pieces
// people actually want lying there: a plank broken in seven leaves 784 g
// pieces of about 130 cells, so walking over them did nothing and asking for
// one was refused (the owner, 2026-09-22). 512 cells is a piece you could
// carry in two hands -- at 20 mm cells, about 3 kg of oak, 10 kg of glass --
// and what you can actually carry is the limit that decides the rest.
const REACH_M = 1.2;
const DEBRIS_CELLS = 512;

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
// Where the person stands, which is not where they look from: the camera is at
// eye height, so a shard lying against your boots is 1.6 m from the camera and
// was never "within reach" of it. Measured from the eye, the sweep could only
// ever fire while crouching (the owner, 2026-09-22: walking near pieces did
// nothing).
function feet() {
  const p = camera.position;
  return { x: p.x, y: p.y - EYE, z: p.z };
}

function debrisUnderfoot() {
  const stand = feet();
  // Whatever the hand holds stays in it -- the engine leaves it alone
  // (LiveWorld::collect) -- so a piece carried in the hand is not a reason to
  // ask. Anything else loose within reach of where you stand is.
  const inHand = world.held && world.held.name;
  for (const [name, entry] of world.bodies) {
    if (entry.shape !== "hull" || entry.anchored || name === inHand) continue;
    const at = entry.mesh.position;
    // Flat distance, and anything from the floor to shoulder height: a piece
    // on a bench beside you is as reachable as one on the ground.
    if (Math.hypot(at.x - stand.x, at.z - stand.z) > REACH_M) continue;
    if (at.y > stand.y - 0.5 && at.y < stand.y + 1.5) return true;
  }
  return false;
}

async function sweep() {
  if (handsFull()) return {};
  // Swept from where you stand, and up to the height of your hands, so the
  // sphere the engine clears is the one around your feet.
  const stand = feet();
  // Never what the hand is holding. The engine skips the body IT holds, and a
  // loose thing is held by this page's own grip instead -- so without saying
  // which, walking with a piece in hand swept that piece out of your own hand
  // and left the page holding a name with no body behind it.
  return takeHaul(await act("collect", { at: [stand.x, stand.y + 0.5, stand.z],
                                         radius_m: REACH_M + 0.5,
                                         largest_cells: DEBRIS_CELLS,
                                         except: world.held ? world.held.name : "" }));
}

// Material has weight, and a person can carry so much of it: past the limit
// the world stops filling your arms as you walk (the load is what the Bag tab
// shows, and what slows you down).
function handsFull() {
  return !!world.carryLimitKg && carriedKg() >= world.carryLimitKg;
}

// One piece, swept from where it lies: what Q does with a broken piece, which
// is material rather than a thing the bag can keep. The hand lets go of it
// first, because the engine leaves whatever a hand holds where it is.
async function sweepPiece(name) {
  const entry = world.bodies.get(name);
  if (!entry) return false;
  if (world.held && world.held.name === name) await dropIt(true);
  const p = (world.bodies.get(name) || entry).mesh.position;
  if (handsFull()) {
    lastAction(`You are carrying all you can: ${Math.round(carriedKg())} kg.`, "refused");
    return false;
  }
  const got = takeHaul(await act("collect", { at: [p.x, p.y, p.z], radius_m: 0.6,
                                              largest_cells: DEBRIS_CELLS }));
  const haul = got.collected || [];
  if (!haul.length) {
    // Nothing came: either it is too big a piece to walk off with, or it was
    // collected a moment ago as you walked and this side of the wire has not
    // caught up. Weight tells them apart, and the sweep has already said what
    // it took, so the second case says nothing.
    const still = world.bodies.get(name);
    if (still && still.mass > 3.0)
      lastAction(`${titled(name)} is too big a piece to carry off: put it down instead.`, "refused");
    return false;
  }
  const much = haul.map((lot) => `${grams(lot.kg)} of ${lot.material.replace(/_/g, " ")}`).join(", ");
  lastAction(`Swept up ${much}.`);
  return true;
}

function takeHaul(got) {
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
    lastAction(`Collected ${said}.`);
  }, 700);
}

// Grams below a kilogram, kilograms above it. Nobody says "0.042 kilograms".
function grams(kg) {
  return kg < 1 ? `${Math.round(kg * 1000)} g` : `${kg.toFixed(2)} kg`;
}

function showStock() {
  // What is carried is in the side view's Bag tab, with everything else the
  // person has (showInventory).
  showInventory();
}

// What the person has: in the side view's Bag tab, and the bag's first nine
// slots along the bottom of the view, by the number keys that take each out.
// Built from the server's record and what the page already knows, and redrawn
// only when that changes.
let inventorySaid = "";
// How many of the bag's slots have a number key: 1 to 9.
//: How many numbered slots the hot list shows. Ten, as the owner asked;
//: the tenth is 0, because that is where a tenth goes on a keyboard, and
//: `inventory.SLOTS` on the server is the same number.
const SLOT_KEYS = 10;

// A name as the view and the side view say it: "iron kettle" is "Iron Kettle".
function titled(name) {
  return String(name || "").replace(/(^|[\s(-])(\p{Ll})/gu, (_, before, letter) => before + letter.toUpperCase());
}
// A sentence as the details say it: a capital, and a stop at the end.
function sentence(text) {
  const s = String(text || "").trim();
  if (!s) return s;
  const said = s[0].toUpperCase() + s.slice(1);
  return /[.!?…]$/.test(said) ? said : `${said}.`;
}

// What the hand holds, by what a person calls it: the bow, not its string.
function heldName() {
  const held = world.held;
  const item = Object.values(world.inventory?.hands || {}).find(x => x && (x.name === held?.name || x.parts?.includes(held?.name)));
  return !held ? "" : item?.label || (held.bow ? held.bow.object : held.pick ? held.pick.object : held.name);
}

// Whether the record says the hand the engine has holds this thing: taken up
// with E, or out of the bag.
function recordHolds(name) {
  const inv = world.inventory;
  const hand = inv && inv.hands && inv.hands[inv.hand_in_the_world];
  return !!(name && hand && (hand.name === name || hand.parts?.includes(name)));
}

// The page's hand has let go of a thing into the world -- put down, dropped,
// thrown: when the record says the hand held it, the record is told. The room
// has already let go; this only tells it.
function leftTheHand(name) {
  if (recordHolds(name)) inventoryChange("drop", name, { quiet: true });
}

// The crosshair, and the name over the view, with something in the hand or not.
function showHolding(on) {
  $("crosshair").classList.toggle("holding", !!on);
  if (on) $("label").hidden = true;
}

// The page's side of a hold the room has already ended -- set aside, or let go
// of by the server: what dropIt does, without asking the room to let go again.
function forgetHold() {
  world.drawn = null;
  world.held = null;
  showHolding(false);
  clearGuides();
  aimArc.hide();
  tools.forget();
  world.use = { mode: "none" };
  showUse();
}

// A thing the server has put in the hand -- taken up with E, or out of the bag:
// held where the server gripped it, as taking hold of a loose thing a hand can
// lift always is. A tool is held ready by its handle instead (tools.js), from
// `point`, the grip it was taken up by, when there is one.
function adoptGrip(name, point) {
  const entry = world.bodies.get(name);
  if (!entry) return;
  const tool = tools.profileOf(name);
  if (tool) { tools.adopt(tool, point || null); return; }
  const blade = bladeFor(name);
  if (blade) {
    // A blade out of the bag is held by its grip, its edge facing down, the way
    // E takes one up (pickUp): the hand takes it again where its blade says.
    act("wield", { name }).then(() => {
      world.held = Object.assign({ name, blade, distance: 0.8 }, takeHold(camera, entry, blade, 0.8));
      showHolding(true);
      showUse();
    }).catch((error) => say("bad", String(error.message || error)));
    return;
  }
  world.held = { name, throwable: true, loose: true,
                 distance: holdDistanceFor(radiusOf(entry)), turn: startTurning(entry) };
  world.use = { mode: "ready", name, kg: entry.mass,
                noun: entry.shape === "sphere" ? "ball" : "thing",
                latched: !!latchOn(name), turnable: entry.shape !== "sphere",
                bringing: { from: entry.mesh.position.clone(), since: performance.now() } };
  showHolding(true);
  showUse();
}

// What the person has is the server's record (inventory_room.py): the page
// asks for a change and shows the answer -- it never decides it. Each change
// has its own id, so a retry is never done twice, and carries the revision the
// page last saw, so a stale one is refused rather than guessed at. They go one
// at a time, in the order they were asked for: a thing put down and another
// picked up straight after reach the record in that order, each against the
// revision the one before it left.
//
// `options`: quiet (what came of it is not said in the details -- a failure to
// reach the server always is), grip (take_up: where the hand takes hold) and
// point (a tool's point, which it is then held ready by).
let inventoryQueue = Promise.resolve();
function inventoryChange(op, item, options = {}) {
  const run = inventoryQueue.then(() => changeInventory(op, item, options));
  inventoryQueue = run.catch(() => {});
  return run;
}

async function changeInventory(op, item, options, again = false) {
  if (!world.session) return null;
  const revision = world.inventory && world.inventory.record ? world.inventory.record.revision : null;
  let answer;
  try {
    const ask = { session: world.session, request: crypto.randomUUID(), op, item, revision,
                  person: whereIAm() };
    if (options.grip) ask.grip = options.grip;
    // Which numbered slot to put it in, for `slot` (inventory.py).
    if (Number.isInteger(options.slot)) ask.slot = options.slot;
    answer = await api("/api/world/inventory", ask);
  } catch (error) {
    say("bad", String(error.message || error));
    return null;
  }
  if (answer.shown) { world.inventory = answer.shown; if(answer.shown.carried) carryGround(answer.shown.carried); }
  inventorySaid = "";
  showInventory();
  if (!answer.ok) {
    // Changed since this page last saw it -- the chat changed the room, say:
    // asked again, once, against the record as it is now.
    const now = answer.record ? answer.record.revision : revision;
    if (!again && now !== revision) return changeInventory(op, item, options, true);
    if (!options.quiet) lastAction(answer.why, "refused");
    return answer;
  }
  const room = answer.room || {};
  if (room.set_aside) {
    // Out of the world, all of it -- a cart and both its wheelsets: not in the
    // hand, and not drawn from now on.
    for (const part of room.parts || [room.set_aside]) {
      if (world.held && world.held.name === part) forgetHold();
      const entry = world.bodies.get(part);
      if (entry) { forget(entry.mesh); world.bodies.delete(part); }
    }
  }
  if (room.let_go && world.held && world.held.name === room.let_go) forgetHold();
  if (room.brought_back) {
    // Back in the world: drawn from what the room says of it now.
    draw(await act("poses"));
    if (room.held) adoptGrip(room.brought_back);
  }
  // Its pins went with it and came back with it. The engine says so once, on
  // the reply the room's own call got (the bag's, not this page's), so they
  // are asked for: a pin left drawn where the cart stood is a pin to nothing.
  if (room.set_aside || room.brought_back) await refreshJoints();
  if (room.taken_up) adoptGrip(room.taken_up, options.point);
  remember(answer.did.replace(/\.$/, "").replace(/^./, (c) => c.toLowerCase()));
  if (!options.quiet) lastAction(answer.did);
  return answer;
}

// Into the hand through the record (take_up): the server's hand takes hold --
// of a tool, by its handle -- and the record says the hand holds it. "held"
// when it did. "not kept" when the record would not keep it: a broken piece,
// which the room's spec does not have, or a thing it cannot keep as it is. That
// says only that it cannot go in the bag, never that a hand cannot hold it, so
// the page's own grip then takes it, as it always did, and Q says why. Null
// when the server could not be reached, which is said.
async function takeIntoHand(name, point) {
  const answer = await inventoryChange("take_up", name,
                                      { quiet: true, grip: point ? point.grip : null, point });
  if (!answer) return null;
  return answer.ok ? "held" : "not kept";
}

// A hand in the middle of a throw, a draw or a tool's stroke, or of one of a
// thing's actions, is busy: the bag and its slots wait until it is done.
const HAND_BUSY = new Set(["preparing", "throwing", "placing", "drawing", "letting-down",
                           "tool-working", "tool-lifting", "carrying-to"]);
function handBusy() {
  if (world.acting || (world.held && HAND_BUSY.has(world.use.mode))) {
    lastAction("Your hand is busy: finish or stop what it is doing first.", "refused");
    return true;
  }
  return false;
}

// Q: into the bag -- what the hand holds or, with the hand empty, what the
// crosshair is on. The room sets it aside (inventory_room.py).
async function toTheBag() {
  if(world.held?.recovery) {lastAction("Release the rover before packing an item.","refused");return;}
  if (handBusy()) return;
  const on = world.aim && world.aim.name;
  const name = world.held ? world.held.name
    : on ? (tools.profileOf(on) ? tools.profileOf(on).tool : on) : null;
  if (!name) { lastAction("Look at what to put in your bag, or hold it, first.", "refused"); return; }
  // The pieces you walk over are collected as you walk, so the one the panel
  // offered can be in what you carry by the time the key arrives. That is not
  // a refusal -- the sweep already said what it took -- and answering "there
  // is nothing like that here" makes a person doubt the key.
  if (!world.held && !world.bodies.has(name)) return;
  const said = world.held ? titled(heldName()) : titled(name);
  // Asked quietly: the record answers "there is nothing like that here" for
  // every broken piece, which is not the thing to say to a person -- and by
  // the time the key arrives the piece may already be in what you carry,
  // collected as you walked.
  const answer = await inventoryChange(world.held && recordHolds(name) ? "stow" : "take", name, { quiet: true });
  if (answer && !answer.ok) {
    // A broken piece is not a thing the record can keep -- it has no name of
    // its own to come back under -- but it is material, and material goes into
    // what you carry. So the same key sweeps it up instead of refusing.
    if (answer.unknown) await sweepPiece(name);
    else lastAction(answer.why, "refused");
  }
}

// 1-9: that slot of the bag into the hand -- and, with the thing from that slot
// in the hand, back into it (the owner: "the same number again puts it back").
// A thing of the record's in the hand is stowed first, so a number swaps what
// is held; anything else in the hand is put down first, with E.
async function fromSlot(i) {
  const inv = world.inventory;
  if (!inv || handBusy()) return;
  const hand = inv.hands && inv.hands[inv.hand_in_the_world];
  const ours = !!(world.held && recordHolds(world.held.name));
  if (ours && hand && hand.slot === i) { await inventoryChange("stow", world.held.name); return; }
  const thing = (inv.stowed || [])[i];
  if (!thing) { lastAction(`Slot ${i + 1} of your bag is empty.`, "refused"); return; }
  if (world.held && !ours) {
    lastAction(`Your hand holds ${heldName()}: ${keyOf("interact")} puts it down first.`, "refused");
    return;
  }
  if (ours) {
    const stowed = await inventoryChange("stow", world.held.name);
    if (!stowed || !stowed.ok) return;
  }
  await inventoryChange("equip", thing.id);
}

// What a thing in the bag is called: a tool by what it is ("the pick"), not by
// the name of its first part ("pick haft"), which is the record's name for it.
function bagName(thing) {
  if (thing.label) return thing.label;
  const tool = tools.profileOf(thing.name);
  return titled(tool ? tool.object : thing.name);
}

// A thing's colour in its slot: the colour the room draws its material with.
function slotColour(material) {
  const seen = MATERIAL_LOOK[material];
  return `#${(seen ? seen.color : 0x9aa6ae).toString(16).padStart(6, "0")}`;
}

function showInventory() {
  const inv = world.inventory;
  const hand = inv && inv.hands ? inv.hands[inv.hand_in_the_world] : null;
  const held = watchedId ? hand?.name : world.held && world.held.name;
  const entry = held ? world.bodies.get(held) : null;
  const mass = entry && entry.mass ? ` · ${grams(entry.mass)}` : "";
  const left = inv && inv.hands && inv.hands.left ? inv.hands.left.name : null;
  const slots = inv && Array.isArray(inv.stowed) ? inv.stowed : [];
  const carrying = [...world.stock].sort((a, b) => b[1].kg - a[1].kg)
    .map(([what, have]) => ({ what, much: grams(have.kg) }));
  // How near that is to all a person can carry, and what it is doing to them.
  const wet = world.inWater;
  if (wet)
    carrying.unshift({ what: wet.head_under ? "under water" : wet.under >= WADE_TO_SWIM_M ? "swimming" : "wading",
                       much: `${Math.round(100 * wet.under)} cm of you under · moving at ${Math.round(100 * wet.pace)}%`
                         + (wet.carried > 0 && wet.speed > 0.005 ? ` · the water carries you at ${(wet.speed * wet.carried).toFixed(2)} m/s` : "") });
  if (carriedKg() > 0 && world.carryLimitKg)
    carrying.push({ what: carriedKg() >= world.carryLimitKg - 0.05 ? "all you can carry" : "of what you can carry",
                    much: `${Math.round(carriedKg())} of ${Math.round(world.carryLimitKg)} kg · walking at ${Math.round(100 * loadPace())}%` });
  // A key and the short thing it does, rather than a sentence about it: these
  // are read at a glance while looking at the room, not studied (the owner,
  // 2026-09-14: "there is way too much text on the screen").
  const uses = [
    ...(world.tools || []).map((p) => ({ what: p.object,
      binds: [[keyOf("interact"), "take it up"], [keyOf("primary"), "use it, hold to keep going"]] })),
    ...(world.profiles || []).map((p) => ({ what: p.object,
      binds: [[keyOf("interact"), "take it up"], [keyOf("primary"), "hold to draw, let go to shoot"]] })),
  ];
  const storedHeat = new Map((heat.last?.stored || []).map(b => [b.name, b]));
  const temperatures = slots.map(thing => thing ? storedHeat.get(thing.name) : null);
  const said = JSON.stringify([held, heldName(), mass, recordHolds(held), hand, left, slots, carrying, uses, temperatures, movementMode]);
  if (said === inventorySaid) return;
  inventorySaid = said;
  showHotbar(slots, hand);
  // A button in the panel is not the room: clicking one never also acts in the
  // world, and it lets go of the focus, so Space cannot click it again.
  const button = (label, op, item) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.addEventListener("click", (e) => {
      e.stopPropagation(); b.blur();
      if (op !== "drop") { inventoryChange(op, item); return; }
      if (world.held?.name === item) { intend("put down"); return; }
      if (world.held) { lastAction("Put down what you are holding first.", "refused"); return; }
      // Take a bag item into the hand so its destination is visible before
      // committing. E then uses precisely that preview.
      inventoryChange("equip", item);
    });
    return b;
  };
  const rightName = Object.values(inv?.hands || {}).find(x => x && (x.name === held || x.parts?.includes(held)))?.label
    || titled(heldName()) || bagName({name:held});
  $("inv-right").replaceChildren(document.createTextNode(held ? `${rightName}${mass}` : "free"));
  if (recordHolds(held)) $("inv-right").append(button("Stow", "stow", held), button("Put down", "drop", held));
  $("inv-left").textContent = left ? bagName(inv.hands.left) : "free";
  const bag = slots.map((thing, i) => [thing, i]).filter(([thing]) => thing);
  // The Workshop link takes a drop too, whether or not the bag has
  // anything in it this moment. Made once; the guard sees to that.
  workshopTakesDrops();
  $("inv-bag").replaceChildren(...(bag.length ? bag.map(([thing, i]) => {
    const li = document.createElement("li");
    const key = document.createElement("span");
    key.className = "slot-key";
    key.textContent = i < SLOT_KEYS ? slotKeySaid(i) : "";
    li.append(key, document.createTextNode(bagName(thing)),
              button("Hold", "equip", thing.id), button("Hold to place", "drop", thing.id));
    // PICK IT UP WITH THE MOUSE and drop it on a slot in the row over the
    // room: that is the hot list. The buttons still work for anyone who
    // would rather not drag, and for a touch screen, which has no drag.
    li.draggable = !watchedId;
    li.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData(BAG_DRAG, thing.id);
      e.dataTransfer.effectAllowed = "move";
      document.body.classList.add("moving-a-thing");
    });
    li.addEventListener("dragend", () => document.body.classList.remove("moving-a-thing"));
    li.title = watchedId ? bagName(thing) : `${bagName(thing)} — drag it onto a slot in the row over the `
            + "room, or onto Workshop to open it on the bench";
    const measured = storedHeat.get(thing.name);
    if (measured && Number.isFinite(measured.t_k) && Number.isFinite(measured.core_k)) {
      const condition = document.createElement("small");
      condition.className = "much";
      condition.textContent = `Surface ~${Math.round(measured.t_k - 273.15)} °C · core ~${Math.round(measured.core_k - 273.15)} °C · insulated storage`;
      li.append(condition);
    }
    const details = document.createElement("details"), summary = document.createElement("summary");
    summary.textContent = "Details"; details.append(summary);
    const identity = document.createElement("small"); identity.className = "much";
    identity.textContent = `Item: ${thing.id} · Body: ${thing.name}`; details.append(identity);
    if (!measured) {
      const condition = document.createElement("small"); condition.className = "much";
      condition.textContent = "Temperature not tracked"; details.append(condition);
    }
    li.append(details);
    return li;
  }) : [Object.assign(document.createElement("li"), { className: "none",
         textContent: `nothing yet: ${keyOf("stow")} puts what you hold, or look at, in it` })]));
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
    if (item.binds) {
      for (const [pressed, does] of item.binds) {
        const line = document.createElement("span");
        line.className = "bind";
        const key = document.createElement("kbd");
        key.textContent = pressed;
        const what = document.createElement("span");
        what.textContent = does;
        line.append(key, what);
        li.append(line);
      }
    }
    return li;
  });
  $("inv-carrying").replaceChildren(...rows(carrying, "nothing yet"));
  $("inv-tools").replaceChildren(...rows(uses, "nothing here yet"));
  const meter = document.querySelector("#world-load-meter");
  if (meter) {
    const limit = world.carryLimitKg, mass = carriedKg();
    meter.hidden = !world.session || !!watchedId;
    meter.querySelector("output").textContent = `${mass.toFixed(1)} / ${(limit || 0).toFixed(0)} kg`;
    meter.querySelector("progress").max = limit || 1;
    meter.querySelector("progress").value = mass;
    const full = limit>0 && mass>=limit-.05;
    meter.dataset.full = String(full);
    meter.querySelector("b").textContent = full ? "Full · digging stopped" : "Ground materials";
    meter.querySelector("small").textContent = full ? "Point at clear ground → H to empty your load" :
      [...world.stock].filter(([,v])=>v.kg>0).map(([what,v])=>`${what} ${v.kg.toFixed(1)} kg`).join(" · ") || "Empty";
    meter.querySelector("[data-movement]").textContent = movementMode === "fly" ? "Fly · Space ↑ · Shift + Space ↓" :
      wet && wet.under>.5 ? "Swim · Space ↑ · Shift + Space ↓" : "Walk · Space jump · Shift run";
  }
}
setInterval(showInventory, 250);
const loadMeter = document.createElement("aside"); loadMeter.id = "world-load-meter"; loadMeter.hidden = true;
loadMeter.innerHTML = `<a href="${worldId ? `/world?world=${worldId}&workshop=1&tab=inventory` : "/world?scene=world&workshop=1&tab=inventory"}">Inventory</a><b>Ground materials</b><output></output><progress max="1" value="0"></progress><small></small><small data-movement></small>`;
document.body.append(loadMeter);

// The bag's first nine slots along the bottom of the view: each with its number,
// the colour of what it is made of (round for a ball), and its name. A slot
// whose thing is in the hand stays marked, since its number puts it back.
// Hidden while nothing of the bag is in them.
//: What a slot's key is called: 1 to 9, then 0 for the tenth.
const slotKeySaid = (i) => String((i + 1) % 10);

// DROPPING A THING INTO A SLOT. The owner asked to be able to move things
// from the inventory into the hot list, and the row was `pointer-events:
// none` -- something to look at, not to use. A slot takes a drop from the
// bag list in the side panel, and the server swaps it with whatever was
// there (inventory.py, the `slot` op).
function slotTakesDrops(li, index) {
  li.addEventListener("dragover", (e) => {
    if (!e.dataTransfer.types.includes(BAG_DRAG)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    li.classList.add("taking");
  });
  li.addEventListener("dragleave", () => li.classList.remove("taking"));
  li.addEventListener("drop", (e) => {
    li.classList.remove("taking");
    const id = e.dataTransfer.getData(BAG_DRAG);
    if (!id) return;
    e.preventDefault();
    inventoryChange("slot", id, { slot: index });
  });
}

//: The one kind of thing that can be dragged in the room: a thing of yours,
//: by its id. Its own type, so a slot cannot be confused by anything else
//: the browser is carrying (a file, a selection, a link).
const BAG_DRAG = "application/x-banjo-item";

// AND THE OTHER PLACE A THING CAN BE DROPPED: the Workshop. The owner:
// "from the inventory screen you can click on an item and drag it into the
// workshop, which will then take you into the workshop where you can modify
// it." The Workshop opens on that thing's bench rather than on whatever it
// had open last.
function workshopTakesDrops() {
  const link = document.querySelector('#panel .game-tabs [data-screen="inventory"]');
  if (!link || link.dataset.takesThings) return;
  link.dataset.takesThings = "yes";
  link.addEventListener("dragover", (e) => {
    if (!e.dataTransfer.types.includes(BAG_DRAG)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    link.classList.add("taking");
  });
  link.addEventListener("dragleave", () => link.classList.remove("taking"));
  link.addEventListener("drop", (e) => {
    link.classList.remove("taking");
    const id = e.dataTransfer.getData(BAG_DRAG);
    if (!id) return;
    e.preventDefault();
    document.body.classList.remove("moving-a-thing");
    const url = new URL("/world", location.origin);
    url.searchParams.set("workshop", "1");
    if (worldId) url.searchParams.set("world", worldId);
    url.searchParams.set("carry", id);
    location.href = url.toString();
  });
}

function showHotbar(slots, hand) {
  const bar = $("hotbar");
  const home = hand && Number.isInteger(hand.slot) ? hand.slot : -1;
  const any = slots.slice(0, SLOT_KEYS).some(Boolean) || (home >= 0 && home < SLOT_KEYS);
  bar.hidden = !any;
  if (!any) { bar.replaceChildren(); return; }
  // Only the slots that hold something are drawn, plus the one after the last
  // of them, so the row says where the next thing goes without putting eight
  // empty boxes in front of the room. Every slot is still in the list, so the
  // numbers and what status() reports are unchanged.
  const filled = Array.from({ length: SLOT_KEYS },
                            (_, i) => Boolean(slots[i] || (i === home ? hand : null)));
  const next = filled.lastIndexOf(true) + 1;
  bar.replaceChildren(...Array.from({ length: SLOT_KEYS }, (_, i) => {
    const thing = slots[i] || (i === home ? hand : null);
    const li = document.createElement("li");
    li.className = `slot${thing ? "" : " empty"}${!thing && i === next ? " next" : ""}`
                 + `${i === home ? " in-hand" : ""}`;
    const number = document.createElement("b");
    number.textContent = slotKeySaid(i);
    li.append(number);
    if (thing) {
      const swatch = document.createElement("i");
      swatch.style.setProperty("--c", slotColour(thing.material));
      if (thing.shape === "sphere") swatch.className = "sphere";
      const name = document.createElement("span");
      name.textContent = bagName(thing);
      li.append(swatch, name);
      li.title = `${slotKeySaid(i)}: ${bagName(thing)}${i === home ? ", in your hand" : ""}`;
    } else {
      li.title = `Slot ${slotKeySaid(i)}: drag a thing from your bag here`;
    }
    slotTakesDrops(li, i);
    return li;
  }));
}

// What the ground under a point is made of, from the engine's own map of its
// surface -- as the label says it. Null off the ground, or in a room without.
function groundMadeOf(at) {
  if (!Array.isArray(at) || !ground.grid || !ground.surfaces) return null;
  const g = ground.grid;
  const i = Math.round((at[0] - g.x0) / g.dx), j = Math.round((at[2] - g.z0) / g.dx);
  if (i < 0 || j < 0 || i >= g.nx) return null;
  const runs = ground.runs, c = j * g.nx + i;
  const kind = runs && runs.count[c] > 0 ? runs.kind[c * runs.stride + runs.count[c] - 1]
                                         : ground.surfaces[c];
  return RUN_NAMES[kind] || null;
}

const RUN_NAMES = ["rock", "soil", "sand", "loose soil",
                   "weathered rock", "clay", "ore", "oxidised ore"];

// What the ground under a point is made of ALL THE WAY DOWN, in words, from the
// runs the engine sends: "0.2 m of sand, then 0.6 m of soil, then rock". What a
// test pit is for, and the same thing the survey says to a machine.
function groundUnderfoot(at) {
  const runs = ground.runs, g = ground.grid;
  if (!Array.isArray(at) || !g || !runs) return "";
  const i = Math.round((at[0] - g.x0) / g.dx), j = Math.round((at[2] - g.z0) / g.dx);
  if (i < 0 || j < 0 || i >= g.nx || j >= g.nz) return "";
  const c = j * g.nx + i, said = [];
  // Down from the top, because that is the order you would dig it.
  for (let k = runs.count[c] - 1; k >= 0; --k) {
    const at_k = c * runs.stride + k;
    const below = k > 0 ? runs.top[c * runs.stride + k - 1] : ground.floor;
    const thick = runs.top[at_k] - below;
    if (thick <= 0.001) continue;
    const name = RUN_NAMES[runs.kind[at_k]] || "soil";
    // The bottom run is the rock the ground stands on: it has no thickness worth
    // saying, because nothing here digs to the bottom of it.
    said.push(k === 0 ? name : `${thick < 1 ? `${Math.round(thick * 100)} cm` : `${thick.toFixed(1)} m`} of ${name}`);
  }
  return said.length ? said.join(", then ") : "";
}

// ---------------------------------------------------------------------------
// WHAT YOU CLICKED, AND IT STAYS CLICKED
// ---------------------------------------------------------------------------
//
// The owner, 2026-09-29: "If I do click on something it would be good to
// highlight the thing i click on on the page and leave it in the right nav
// until I click on something else. If I click on something not a machine, like
// some land, it should show me what it is composed of, a mineral and if so how
// much."
//
// Until now the side view followed the crosshair, so the moment you looked
// away to read it, it was about something else. This pins: a click says THAT
// ONE, a box is drawn round it in the room, and the panel is about it until
// you click something else. Escape lets go.
//
// A pinned thing REPLACES the hovering view rather than sitting under it. The
// owner had already said there was too much in the panel, and two cards saying
// nearly the same thing about two different objects is the worst of it.

const picked = { name: null, at: null, box: null };

// Its section, made here. world.html's inline blocks are hashed into the
// content policy every running server sends, so a card added there would shut
// every open page; one made from script is the page's own doing.
(function makePickedCard() {
  const details = document.getElementById("details");
  if (!details || document.getElementById("picked")) return;
  const box = document.createElement("section");
  box.id = "picked";
  box.hidden = true;
  box.setAttribute("aria-label", "What you clicked");
  box.setAttribute("aria-live", "polite");
  details.parentNode.insertBefore(box, details);
})();

// The box drawn round what is pinned. One set of lines, reused: it is moved
// and resized each frame rather than rebuilt, because the thing it is round
// may be being driven.
let pickedBox = null;
function pickedOutline() {
  if (pickedBox) return pickedBox;
  const lines = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)),
    new THREE.LineBasicMaterial({ color: 0x9fe8ff, transparent: true, opacity: 0.95,
                                  depthTest: false }));
  lines.renderOrder = 998;      // over the room, so it reads through a wall
  lines.visible = false;
  scene.add(lines);
  pickedBox = lines;
  return lines;
}

// Each frame: sit the box on what is pinned. A thing that has left the room
// takes the pin with it -- otherwise the box hangs in the air over nothing.
const pickedBounds = new THREE.Box3();
const pickedSize = new THREE.Vector3();
const pickedMiddle = new THREE.Vector3();
function drawPickedOutline() {
  const lines = pickedOutline();
  const body = picked.name && world.bodies && world.bodies.get(picked.name);
  if (!body || !body.mesh) {
    lines.visible = false;
    if (picked.name && world.bodies && !world.bodies.has(picked.name)) unpick();
    return;
  }
  pickedBounds.setFromObject(body.mesh);
  if (pickedBounds.isEmpty()) { lines.visible = false; return; }
  pickedBounds.getSize(pickedSize);
  pickedBounds.getCenter(pickedMiddle);
  // A little proud of the thing, so the lines are not inside its own surface.
  lines.scale.set(pickedSize.x + 0.02, pickedSize.y + 0.02, pickedSize.z + 0.02);
  lines.position.copy(pickedMiddle);
  lines.visible = true;
}

// A click pins whatever it was on: a body by name, or, on open ground, the
// place on the ground it met. Clicking the same thing twice lets it go, which
// is what a second click on a selected thing does everywhere else.
function pinWhatWasClicked() {
  const was = picked.name;
  if (world.aim && world.aim.name) {
    picked.name = was === world.aim.name ? null : world.aim.name;
    picked.at = picked.name ? (world.aim.point_m || null) : null;
  } else if (world.groundAim) {
    picked.name = null;
    picked.at = world.groundAim.slice();
  } else {
    return;                     // a click on the sky pins nothing and clears nothing
  }
  revealPicked();
  showPicked();
}

function unpick() {
  clearReveal();
  picked.name = null;
  picked.at = null;
  showPicked();
}

function somethingIsPinned() { return !!(picked.name || picked.at); }

// A short inspection pulse, entirely in the renderer. Cell centres come from
// the native snapshot; rigid bodies show parts, never invented voxels. The
// terrain is a layered height field, so its reveal is one real column.
const REVEAL_MS = 3200, REVEAL_MAX_CELLS = 16000;
let revealing = null, revealTicket = 0, structureLoading = false;
function cellInspection(entry) {
  if (entry.geometryPending) return null;
  if (entry.cells?.length) return { cells_local_m: entry.cells, cell_count: entry.cells.length, complete: true };
  return entry.inspection?.revision === entry.revision ? entry.inspection : null;
}
function clearReveal() {
  revealTicket++;
  if (!revealing) return;
  scene.remove(revealing.group);
  revealing.group.traverse(mesh => {
    mesh.material?.map?.dispose();
    if (mesh.geometry) mesh.geometry.dispose();
    if (mesh.material) mesh.material.dispose();
    if (mesh.isInstancedMesh) mesh.dispose();
  });
  if (revealing.skin) revealing.skin.dispose();
  for (const row of revealing.sources || []) row.skin.dispose();
  revealing = null;
}
function structureLabel(name, material) {
  const canvas=document.createElement("canvas"); canvas.width=512; canvas.height=136;
  const ctx=canvas.getContext("2d"); ctx.fillStyle="rgba(12,22,29,.94)"; ctx.fillRect(0,0,512,136);
  ctx.fillStyle="#f5f1e8"; ctx.font="600 40px system-ui"; ctx.textAlign="center";
  ctx.fillText(name,256,55,490);ctx.font="30px system-ui";ctx.fillText(material,256,109,490);
  const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(canvas),
    transparent:true,opacity:0,depthTest:false,depthWrite:false}));
  sprite.scale.set(1.6,.425,1); return sprite;
}
function inspectionAssembly(name) {
  const names=new Set([name]);
  // Actual attached constraints define membership; a broken joint cannot
  // borrow the other body's parts. Bound traversal to the room body budget.
  for (let pass=0;pass<64;pass++) {
    let changed=false;
    for (const j of world.joints) if (j.attached && (names.has(j.a) || names.has(j.b)))
      for (const end of [j.a,j.b]) if (world.bodies.has(end) && !names.has(end) && names.size<64) {
        names.add(end); changed=true;
      }
    if (!changed) break;
  }
  return [...names].map(name=>({name,entry:world.bodies.get(name)}));
}
function explodedStructure(entry, name, group) {
  const rows=[], sources=[];
  for (const source of inspectionAssembly(name)) {
    const body=source.entry;
    if (!body || body.geometryPending) continue;
    let parts=body.mechanicalModel === "precise-rigid-v1" ? body.parts : null;
    const inspection=cellInspection(body);
    if (!parts && inspection?.complete && inspection.cell_count<=REVEAL_MAX_CELLS) {
      const outline=world.outlines?.get(source.name);
      if (outline?.parts.length) {
        // Partition actual reported cells by the authored boxes. Every cell
        // must belong and each component must retain matter. No synthetic fill.
        const buckets=outline.parts.map(p=>({...p,cells:[]}));
        const transforms=buckets.map(p=>new THREE.Matrix4().compose(new THREE.Vector3(...p.center_local_m),
          new THREE.Quaternion(p.rotation_wxyz[1],p.rotation_wxyz[2],p.rotation_wxyz[3],p.rotation_wxyz[0]),new THREE.Vector3(1,1,1)).invert());
        let complete=true;
        for (const cell of inspection.cells_local_m) {
          const index=buckets.findIndex((p,i)=>{
            const local=new THREE.Vector3(...cell).applyMatrix4(transforms[i]);
            return [local.x,local.y,local.z].every((v,k)=>Math.abs(v)<=p.dimensions_m[k]/2+1e-7);
          });
          if (index<0) {complete=false;break;} buckets[index].cells.push(cell);
        }
        if (complete && buckets.every(p=>p.cells.length)) parts=buckets;
      }
      if (!parts && inspection.cells_local_m?.length) parts=[{name:source.name,material:body.material,
        center_local_m:[0,0,0],dimensions_m:body.dims,cells:inspection.cells_local_m}];
    }
    if (!parts?.length) continue;
    const skin=dressedClone(body.mesh.material);skin.transparent=true;skin.depthWrite=false;
    sources.push({...source,mesh:body.mesh,revision:body.revision,skin});
    for (const [i,part] of parts.entries()) {
      if (rows.length>=256) break;
      const wrapper=new THREE.Group(), material=new THREE.MeshStandardMaterial({
        color:look(part.material || body.material).color,transparent:true,opacity:0,
        depthTest:false,depthWrite:false,roughness:.8});
      let mesh;
      if (part.cells) {
        mesh=new THREE.InstancedMesh(new THREE.BoxGeometry(world.cellSize*.96,world.cellSize*.96,world.cellSize*.96),material,part.cells.length);
        const matrix=new THREE.Matrix4();
        part.cells.forEach((at,k)=>mesh.setMatrixAt(k,matrix.makeTranslation(...at)));
        mesh.instanceMatrix.needsUpdate=true;
      } else mesh=new THREE.Mesh(preciseGeometry([part],body.material,false),material);
      mesh.matrixAutoUpdate=false;
      const partName=(part.name || `part ${i+1}`).split("/").pop();
      const component=source.name.includes(":") ? `${source.name.split(":").pop().trim()} · ${partName}` : partName;
      const substance=part.material || body.material;
      const label=structureLabel(component,`${substance}${part.cells ? ` · ${part.cells.length} cells` : ""}`);
      wrapper.add(mesh,label);group.add(wrapper);
      rows.push({wrapper,mesh,label,source:body,sourceName:source.name,part,component,substance});
    }
  }
  if (!rows.length) return null;
  const centre=new THREE.Vector3();
  for (const row of rows) {
    row.source.mesh.updateMatrixWorld();
    row.at=new THREE.Vector3(...row.part.center_local_m).applyMatrix4(row.source.mesh.matrixWorld);
    centre.add(row.at);
  }
  centre.divideScalar(rows.length);
  rows.forEach((row,i)=>{
    const out=row.at.clone().sub(centre);
    if (out.lengthSq()<.001) out.set(Math.cos(i*2.4),.4,Math.sin(i*2.4));
    row.explode=out.normalize().multiplyScalar(.65+.1*Math.sqrt(rows.length));
  });
  return {rows,sources};
}
function revealPicked(mode="components") {
  clearReveal();
  const group = new THREE.Group();
  group.name = "selection-structure-reveal";
  const material = color => new THREE.LineBasicMaterial({ color,
    transparent: true, opacity: 0, depthTest: false, depthWrite: false });
  const edgesOf = shape => {
    const edges = new THREE.EdgesGeometry(shape); shape.dispose(); return edges;
  };
  const entry = picked.name && world.bodies.get(picked.name);
  let kind, count = 0, skin = null, beds = null, cells = null, exploded=null;
  if (entry) {
    if (entry.geometryPending) return;
    const inspection = cellInspection(entry);
    if (mode!=="cells") exploded=explodedStructure(entry,picked.name,group);
    if (exploded) {
      kind="parts";count=exploded.rows.length;
    } else if (inspection?.cells_local_m?.length && inspection.complete && inspection.cell_count <= REVEAL_MAX_CELLS) {
      cells = inspection.cells_local_m;
      kind = "cells"; count = cells.length;
      const edges = edgesOf(new THREE.BoxGeometry(world.cellSize, world.cellSize, world.cellSize));
      const edge = edges.attributes.position.array;
      // One bounded line buffer and draw call. No face diagonals: exactly the
      // twelve cube edges around each reported centre, including internal cells.
      const positions = new Float32Array(edge.length * count);
      cells.forEach((at, i) => {
        for (let k = 0; k < edge.length; k++) positions[i * edge.length + k] = edge[k] + at[k % 3];
      });
      edges.dispose();
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
      group.add(new THREE.LineSegments(geometry, material(0x70eddb)));
    } else {
      // Intact native boxes omit cells from ordinary pose packets. Ask once
      // per selection/revision, with one request in flight and stale replies
      // discarded. A server without this query reports unavailable.
      if (!inspection && !entry.inspectionError && !structureLoading) {
        const ticket = revealTicket, name = picked.name, revision = entry.revision;
        structureLoading = true;
        act("structure", { name }).then(answer => {
          if (ticket !== revealTicket || world.bodies.get(name) !== entry || entry.revision !== revision) return;
          const value = answer.structure;
          if (!value || value.name !== name || value.revision !== revision) {
            entry.inspectionError = "Geometry changed; select the item again"; return;
          }
          entry.inspection = value;
        }).catch(error => {
          if (world.bodies.get(name) === entry) entry.inspectionError = error.message || "Inspection unavailable";
        }).finally(() => {
          structureLoading = false;
          const selected = picked.name && world.bodies.get(picked.name);
          if (ticket === revealTicket || (selected && !cellInspection(selected) && !selected.inspectionError
              && selected.mechanicalModel !== "precise-rigid-v1")) {
            revealPicked(mode); showPicked();
          }
        });
      }
      return; // Missing/over-budget geometry is not a substitute box.
    }
    if (!exploded) {
      skin = dressedClone(entry.mesh.material);
      skin.transparent = true; skin.depthWrite = false;
      group.matrixAutoUpdate = false;
    }
  } else if (picked.at) {
    beds = bedsUnder(picked.at);
    if (!beds.length) return;
    kind = "layers";
    const g = ground.grid;
    const x = g.x0 + Math.round((picked.at[0] - g.x0) / g.dx) * g.dx;
    const z = g.z0 + Math.round((picked.at[2] - g.z0) / g.dx) * g.dx;
    for (const bed of beds) {
      if (bed.hole) continue;
      const mesh = new THREE.LineSegments(edgesOf(new THREE.BoxGeometry(g.dx, bed.thick_m, g.dx)),
        material(GROUND_COLOURS[bed.kind] || 0x70eddb));
      mesh.position.set(x, bed.top_m - bed.thick_m / 2, z);
      group.add(mesh); count++;
    }
  } else return;
  if (!count) { group.traverse(m => { m.geometry?.dispose(); m.material?.dispose(); }); return; }
  group.traverse(m => { m.renderOrder = 997; m.frustumCulled = false; });
  scene.add(group);
  revealing = { group, entry, mesh: entry?.mesh, skin, kind, count, beds, cells,
    revision: entry?.revision,
    name: picked.name, at: picked.at?.slice(), start: performance.now(), amount: 0,
    ...exploded, reduced: matchMedia("(prefers-reduced-motion: reduce)").matches };
}
function animateReveal(now) {
  const r = revealing;
  if (!r) return;
  const age = now - r.start;
  const current = r.name && world.bodies.get(r.name);
  // Never keep drawing cells from a body replaced, removed or awaiting a new
  // geometry revision. Digging also invalidates a revealed ground column.
  if ((!r.rows && age >= REVEAL_MS) || (r.name && (current !== r.entry || current?.mesh !== r.mesh || current.geometryPending || current.revision !== r.revision))
      || r.sources?.some(s=>world.bodies.get(s.name)!==s.entry || s.entry.mesh!==s.mesh || s.entry.geometryPending || s.entry.revision!==s.revision)
      || (!r.name && JSON.stringify(bedsUnder(r.at)) !== JSON.stringify(r.beds))) {
    clearReveal(); showPicked(); return;
  }
  r.amount = r.reduced ? 1 : r.rows ? Math.min(1,age/600) : Math.min(1, age / 450, (REVEAL_MS - age) / 650);
  r.group.traverse(m => { if (m.material) m.material.opacity = r.amount * 0.8; });
  for (const row of r.rows || []) {
    row.source.mesh.updateMatrixWorld();row.mesh.matrix.copy(row.source.mesh.matrixWorld);
    row.wrapper.position.copy(row.explode).multiplyScalar(r.amount);
    row.label.position.fromArray(row.part.center_local_m).applyMatrix4(row.source.mesh.matrixWorld);
    row.label.position.y += Math.min(.6,Math.max(...row.part.dimensions_m)/2+.2);
  }
  if (r.rows) {
    // Keep labels readable in the viewport. The complete name/material list
    // stays in the panel; occluded/out-of-view labels never stack into a blur.
    r.group.updateMatrixWorld(true);
    const rects=[], width=renderer.domElement.clientWidth, height=renderer.domElement.clientHeight;
    for (const row of r.rows) {
      const worldAt=row.label.getWorldPosition(new THREE.Vector3());
      const depth=-worldAt.clone().applyMatrix4(camera.matrixWorldInverse).z;
      const pixels=height*camera.projectionMatrix.elements[5]/(2*Math.max(.01,depth));
      const p=worldAt.project(camera);
      const x=(p.x+1)*width/2,y=(1-p.y)*height/2;
      const w=row.label.scale.x*pixels/2,h=row.label.scale.y*pixels/2;
      const box={x:x-w,y:y-h,right:x+w,bottom:y+h};
      row.label.visible=depth>0 && pixels>60 && p.z>=-1 && p.z<=1 && box.x>4 && box.y>4 && box.right<width-4 && box.bottom<height-4
        && !rects.some(a=>box.x<a.right+6 && box.right>a.x-6 && box.y<a.bottom+6 && box.bottom>a.y-6);
      if (row.label.visible) rects.push(box);
    }
  }
  if (r.entry && !r.rows) {
    r.mesh.updateMatrixWorld(); r.group.matrix.copy(r.mesh.matrixWorld);
  }
}
function inspectionValues(values) {
  const list = document.createElement("dl"); list.className = "pk-analysis";
  for (const [name, value] of values) {
    const term = document.createElement("dt"), description = document.createElement("dd");
    term.textContent = name; description.textContent = value;
    list.append(term, description);
  }
  return list;
}
function revealButton() {
  const button = document.createElement("button");
  button.type = "button"; button.className = "pk-reveal";
  button.textContent = revealing?.rows && revealing.name===picked.name ? "Return to assembled" : "Explode components";
  const entry = picked.name && world.bodies.get(picked.name);
  if (!entry) button.textContent="Reveal ground layers";
  const inspection = entry && cellInspection(entry);
  const available = entry ? !entry.geometryPending && (entry.mechanicalModel === "precise-rigid-v1"
    ? !!entry.parts?.length : inspection ? !!inspection.cells_local_m?.length && inspection.complete && inspection.cell_count <= REVEAL_MAX_CELLS : true)
    : !!bedsUnder(picked.at).some(b => !b.hole);
  button.disabled = !available || (!!entry && structureLoading && !inspection && entry.mechanicalModel !== "precise-rigid-v1");
  if (structureLoading && !inspection && entry) button.textContent = "Loading structure…";
  else if (entry?.inspectionError) { button.textContent = "Retry reveal"; button.title = entry.inspectionError; }
  if (!available) button.title = entry?.inspectionError || (entry?.geometryPending ? "Updating geometry" : "No reveal geometry within the display budget");
  button.addEventListener("click", () => {
    if (revealing?.rows && revealing.name===picked.name) {clearReveal();showPicked();return;}
    if (entry) entry.inspectionError = null;
    revealPicked(); showPicked();
  });
  return button;
}

// ---------------------------------------------------------------------------
// The battery, drawn as a battery
// ---------------------------------------------------------------------------
//
// The owner: "a rover or drone or machine should show an intuitive image for
// power, like a battery symbol with % full. It should show something that
// indicates charging speed or time until full like a tesla."
//
// So: the symbol fills with the charge and colours with it, and beside it the
// one number a driver wants, which is not watts. Taking in more than it
// spends, that is how long until it is full; spending more than it takes in,
// how long until it stops. The watts are there too, small, because this is a
// game about machines and somebody will want them.
const BATTERY_LOW = 0.15, BATTERY_FAIR = 0.4;

function batterySymbol(share) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 44 22");
  svg.setAttribute("class", "battery");
  svg.setAttribute("role", "img");
  const el = (kind, attrs) => {
    const node = document.createElementNS("http://www.w3.org/2000/svg", kind);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    return node;
  };
  const full = Math.max(0, Math.min(1, share));
  const colour = full <= BATTERY_LOW ? "var(--bad)" : full <= BATTERY_FAIR ? "var(--warn)" : "var(--good)";
  svg.append(
    el("rect", { x: 1, y: 1, width: 36, height: 20, rx: 3, class: "battery-shell" }),
    el("rect", { x: 38, y: 7, width: 5, height: 8, rx: 1.5, class: "battery-cap" }),
    el("rect", { x: 3.5, y: 3.5, width: Math.max(0, 31 * full), height: 15, rx: 1.5,
                 fill: colour, class: "battery-fill" }));
  const says = el("title", {});
  says.textContent = `${Math.round(full * 100)}% charged`;
  svg.append(says);
  return svg;
}

// "45 min until full", "1.2 hours left", "holding steady".
function batteryWord(power) {
  if (power.known === false) return "Reading flow…";
  const { store, using, taking } = power;
  const room = Math.max(0, store.capacity_j - store.charge_j);
  if (taking - using > 0.05) {
    return room < 1 ? "full" : `${forHowLong(room / (taking - using))} until full`;
  }
  if (using - taking > 0.05) return `${forHowLong(store.charge_j / (using - taking))} left`;
  if (room < Math.max(1, store.capacity_j * 0.005)) return "full";
  return store.charge_j > 0 ? "holding steady" : "flat";
}

function batteryRow(power) {
  const share = power.store.capacity_j > 0 ? power.store.charge_j / power.store.capacity_j : 0;
  const row = document.createElement("div");
  row.className = "pk-battery";
  row.dataset.store = power.store.id;
  row.dataset.chargeJ = power.store.charge_j;
  row.dataset.capacityJ = power.store.capacity_j;
  row.dataset.flowW = power.known === false ? "" : power.taking - power.using;
  const said = document.createElement("div");
  said.className = "pk-battery-said";
  const big = document.createElement("strong");
  big.textContent = `${Math.round(share * 100)}%`;
  const when = document.createElement("span");
  when.className = "pk-when";
  when.textContent = batteryWord(power);
  const flow = document.createElement("span");
  flow.className = "pk-flow";
  // Which way the energy is going, as an arrow, because that is the thing to
  // see at a glance -- the numbers are for afterwards.
  const net = power.taking - power.using;
  flow.textContent = power.known === false ? "— awaiting next reading"
    : net > 0.05 ? `▲ ${wattsSaid(power.taking - power.using)} in`
    : net < -0.05 ? `▼ ${wattsSaid(power.using - power.taking)} out`
    : "— nothing flowing";
  flow.classList.add(net > 0.05 ? "in" : net < -0.05 ? "out" : "still");
  const energy = document.createElement("span");
  energy.className = "pk-energy";
  energy.textContent = `${joulesSaid(power.store.charge_j)} / ${joulesSaid(power.store.capacity_j)}`;
  said.append(big, energy, when, flow);
  row.append(batterySymbol(share), said);
  row.title = `${joulesSaid(power.store.charge_j)} of ${joulesSaid(power.store.capacity_j)}`
    + (power.known === false ? " · awaiting next reading"
      : ` · energy out ${wattsSaid(power.using)} · energy in ${wattsSaid(power.taking)}`);
  return row;
}

// ---------------------------------------------------------------------------
// The keys that do something TO THIS THING
// ---------------------------------------------------------------------------
//
// The owner: "it should show any specific keys to it, in this case E does
// nothing, P doesn't seem to do anything, J doesn't do anything."
//
// They were right, and the panel was wrong to offer them. E is "do the thing
// the side view is offering", J swings what your hand holds and P lays cable
// from a battery -- none of which is a thing you can do to a rover you are
// driving. So the keys are worked out from the thing rather than listed: a
// machine you are being gets the driving keys, a machine you are not gets
// whatever the side view really offers, and a key with nothing behind it is
// not shown at all.
function keysForPicked(name) {
  const out = [{ key: "Alt+Click", what: "inspect without using or dropping" }];
  const mine = whatIsRidden();
  if (mine && mine.name === name) {
    out.push({ key: "W / S", what: "drive it forward and back" },
             { key: "A / D", what: "turn it" });
    if ((mine.program.can || []).some((a) => RIDE_FLIES_ONLY.has(a))) {
      out.push({ key: "Space", what: "climb" }, { key: "Shift+Space", what: "come down" });
    }
    out.push({ key: "Esc", what: "get out of it" });
    return out;
  }
  // Not being it: what the side view is really offering for it, each with the
  // key that runs it. This is the same list E walks with Tab, so it cannot
  // promise anything E will not do.
  const { list } = chosen();
  if (world.aim && world.aim.name === name) {
    for (const [i, choice] of list.entries()) {
      out.push({ key: i === 0 ? keyOf("interact") : `Tab ×${i}, ${keyOf("interact")}`,
                 what: choice.label.toLowerCase() });
    }
  }
  // Being it. The offer only appears for something that can really be ridden,
  // which is what whatCanBeRidden() answers -- a key that is shown is a key
  // that works.
  if (whatCanBeRidden().some((m) => m.name === name)) {
    out.push({ key: "Settings", what: "be it, from the Settings tab" });
  }
  if (machinesOfPart(name).length && !out.some((k) => /panel/.test(k.what))) {
    out.push({ key: "Click", what: "open its panel" });
  }
  return out;
}

function keyRows(keys) {
  const list = document.createElement("ul");
  list.className = "pk-keys";
  for (const { key, what } of keys) {
    const li = document.createElement("li");
    const cap = document.createElement("kbd");
    cap.textContent = key;
    const said = document.createElement("span");
    said.textContent = what;
    li.append(cap, said);
    list.append(li);
  }
  return list;
}

// ---------------------------------------------------------------------------
// What the land is made of
// ---------------------------------------------------------------------------
//
// The owner: "if I click on something not a machine, like some land, it should
// show me what it is composed of, a mineral and if so how much."
//
// A core sample, drawn the way a core sample is drawn: the beds in order down
// the page, each band as deep as the bed is thick and in the colour that bed
// is painted in the room, so what you see in the panel is what you are
// standing on. Ore is called out with its thickness, because that is the
// number you came for.
const CORE_TALL = 132;          // pixels for the whole column
const ORE_NAMES = ["ore", "oxidised ore"];

// The beds under a point, top down: [{name, kind, thick_m, top_m}].
function bedsUnder(at) {
  const runs = ground.runs, g = ground.grid;
  if (!Array.isArray(at) || !g || !runs) return [];
  const i = Math.round((at[0] - g.x0) / g.dx), j = Math.round((at[2] - g.z0) / g.dx);
  if (i < 0 || j < 0 || i >= g.nx || j >= g.nz) return [];
  const c = j * g.nx + i, out = [];
  for (let k = runs.count[c] - 1; k >= 0; --k) {
    const at_k = c * runs.stride + k;
    const below = k > 0 ? runs.top[c * runs.stride + k - 1] : ground.floor;
    const thick = runs.top[at_k] - below;
    if (thick <= 0.001) continue;
    out.push({ kind: runs.kind[at_k], name: RUN_NAMES[runs.kind[at_k]] || "soil",
               thick_m: thick, top_m: runs.top[at_k], hole: runs.kind[at_k] === RUN_VOID });
  }
  return out;
}

const deepSaid = (m) => (m < 1 ? `${Math.round(m * 100)} cm` : `${m.toFixed(1)} m`);

// A BROKEN SCALE, the way a core log is really drawn. Straight to scale, 60 cm
// of soil beside 30 m of rock is a 7-pixel sliver -- and the 60 cm is the part
// you were asking about. So no bed may take more than a share of the column
// and none less than enough to read its own label; a bed that was cut short
// says so with a torn edge, which is the geologist's own mark for it.
const BED_MOST = 0.42, BED_LEAST_PX = 17;

function coreColumn(beds) {
  const deep = beds.reduce((sum, b) => sum + b.thick_m, 0) || 1;
  const least = BED_LEAST_PX / Math.max(CORE_TALL, beds.length * BED_LEAST_PX);
  const want = beds.map((b) => Math.min(BED_MOST, Math.max(least, b.thick_m / deep)));
  const sum = want.reduce((a, b) => a + b, 0) || 1;
  const tall = Math.max(CORE_TALL, beds.length * BED_LEAST_PX);
  const column = document.createElement("div");
  column.className = "pk-core";
  for (const [i, bed] of beds.entries()) {
    const band = document.createElement("div");
    band.className = bed.hole ? "pk-bed hole" : "pk-bed";
    if (bed.thick_m / deep > BED_MOST) band.classList.add("cut");
    band.style.height = `${(want[i] / sum) * tall}px`;
    if (!bed.hole) {
      const colour = GROUND_COLOURS[bed.kind];
      if (colour) band.style.background = `#${colour.getHexString()}`;
    }
    if (ORE_NAMES.includes(bed.name)) band.classList.add("ore");
    const said = document.createElement("span");
    said.textContent = bed.hole ? "dug out" : `${bed.name} · ${deepSaid(bed.thick_m)}`;
    band.append(said);
    band.title = bed.hole ? `${deepSaid(bed.thick_m)} of nothing: this has been dug`
      : `${deepSaid(bed.thick_m)} of ${bed.name}, its top ${bed.top_m.toFixed(2)} m up`
        + (bed.thick_m / deep > BED_MOST ? " -- drawn short to leave room for the rest" : "");
    column.append(band);
  }
  return column;
}

// ---------------------------------------------------------------------------

function pickedTitle(words, sub) {
  const head = document.createElement("header");
  head.className = "pk-head";
  const box = document.createElement("div");
  const h = document.createElement("h2");
  h.textContent = words;
  box.append(h);
  if (sub) {
    const p = document.createElement("p");
    p.className = "pk-sub";
    p.textContent = sub;
    box.append(p);
  }
  const shut = document.createElement("button");
  shut.type = "button";
  shut.className = "quiet";
  shut.id = "pk-close";
  shut.setAttribute("aria-label", "Stop looking at this");
  shut.textContent = "×";
  shut.addEventListener("click", unpick);
  head.append(box, shut);
  return head;
}

// The whole card. Called every time the room says something new, so everything
// in it is live: the battery empties while you watch it.
function showPicked() {
  const box = $("picked");
  if (!box) return;
  const details = $("details");
  if (!somethingIsPinned()) {
    box.hidden = true;
    box.replaceChildren();
    if (details) details.hidden = false;
    return;
  }
  box.hidden = false;
  if (details) details.hidden = true;     // one card about one thing, not two
  const rows = [];

  if (picked.name) {
    const entry = world.bodies && world.bodies.get(picked.name);
    const part = tools.profileOf(picked.name) || profileOf(picked.name);
    const programs = machinesOfPart(picked.name);
    const program = programs.find((p) => isProgram(p));
    rows.push(pickedTitle(titled(part ? part.object : picked.name),
                          program ? "a machine" : entry && entry.anchored ? "fixed in place" : null));

    const power = program ? energyOf(program) : null;
    if (power) rows.push(batteryRow(power));
    else {
      // Not a program, but it may still BE a battery: the store on this body.
      const lamp = lampOn(picked.name);
      const store = ((world.machines && world.machines.stores) || [])
        .find((s) => (sameThing(s.body, picked.name) || s.id === lamp?.store) && s.capacity_j > 0);
      if (store) rows.push(batteryRow(energyOfStore(store)));
    }

    if (program) {
      const doing = document.createElement("p");
      doing.className = "pk-doing";
      doing.textContent = program.power ? (program.why || program.doing || "running")
                                        : "switched off";
      rows.push(doing);
      if(program.kind==="roam") rows.push(recoverySection(program));
      if(program.sensors?.length) {
        const readings=document.createElement("section");readings.dataset.roverSensors="";
        const heading=document.createElement("h4");heading.textContent="Sensors";readings.append(heading);
        const ordered=[...program.sensors].sort((a,b)=>
          Number(b.kind==="ground")-Number(a.kind==="ground") || Number(b.sees)-Number(a.sees));
        readings.append(inspectionValues(ordered.map(s=>[sensorName(s),sensorReading(s)])));
        rows.push(readings);
      }
    }

    if (entry) {
      const rigid = entry.mechanicalModel === "precise-rigid-v1";
      const inspection = cellInspection(entry);
      const expanded=revealing?.rows && revealing.name===picked.name ? revealing : null;
      const materials = expanded ? [...new Set(expanded.rows.map(r=>r.substance))] : rigid ? [...new Set((entry.parts || []).map(p => p.material || entry.material))] : [entry.material];
      const mass=expanded ? expanded.sources.reduce((sum,s)=>sum+s.entry.mass,0) : entry.mass;
      const memberNames=expanded ? new Set(expanded.sources.map(s=>s.name)) : new Set([picked.name]);
      rows.push(inspectionValues([
        ["Material", materials.filter(Boolean).join(" / ") || "Not reported"],
        [!expanded && program?.kind==="roam" ? "Body mass" : "Mass", entry.anchored ? "Fixed · not reported" : `${mass.toLocaleString(undefined, { maximumFractionDigits: 3 })} kg`],
        ["Structure", expanded ? "Assembly components" : rigid ? "Rigid parts" : "Cells"],
        [expanded ? "Components" : rigid ? "Parts" : "Cells", entry.geometryPending ? "Updating" :
          (expanded ? expanded.count : rigid ? entry.parts?.length : inspection?.cell_count)?.toLocaleString() || "Not reported"],
        ...(!expanded && !rigid && inspection?.cell_count ? [["Cell width", `${Math.round(world.cellSize * 1000)} mm`]] : []),
        ["Connections", world.joints.filter(j => j.attached && (memberNames.has(j.a) || memberNames.has(j.b))).length.toLocaleString()],
        ["Breaking", rigid ? "No cell fracture" : "Tool dependent"],
      ]));
      rows.push(revealButton());
      if (revealing?.rows && revealing.name===picked.name) {
        const parts=inspectionValues(revealing.rows.map(r=>[r.component,r.substance]));
        parts.classList.add("pk-components");rows.push(parts);
      }
      if (!rigid) {
        const cells=document.createElement("button");cells.className="pk-reveal";cells.type="button";
        cells.textContent="Show native cells";cells.onclick=()=>{revealPicked("cells");showPicked();};rows.push(cells);
      }
    }

    const keys = keysForPicked(picked.name);
    if (keys.length) rows.push(keyRows(keys));
  } else {
    const beds = bedsUnder(picked.at);
    const top = beds.find((b) => !b.hole);
    const away = camera.position.distanceTo(
      new THREE.Vector3(picked.at[0], picked.at[1], picked.at[2]));
    rows.push(pickedTitle(titled(top ? top.name : "the ground"),
                          `the ground, ${away.toFixed(1)} m away`));
    if (beds.length) {
      rows.push(coreColumn(beds));
      // The one thing worth calling out of a column of dirt.
      const ore = beds.filter((b) => ORE_NAMES.includes(b.name));
      const deposits = (world.goods?.deposits || []).filter(d=>d.left_kg>0 &&
        Math.hypot(picked.at[0]-d.at_m[0],picked.at[2]-d.at_m[1])<=d.radius_m);
      const values = [["Surface", top?.name || "Ground"], ["Layers", String(beds.length)]];
      for (const d of deposits) values.push(["Extraction area",d.substance], ["Reserve",heldSaid(d.left_kg)],
        ["Yield",`${Math.round(d.grade*100)}% ore / scoop`], ["Get it", "Rover → dig → deliver to intake"]);
      if (ore.length) {
        const thick = ore.reduce((sum, b) => sum + b.thick_m, 0);
        const under = Math.max(0, (beds[0].top_m || 0) - ore[0].top_m);
        values.push(["Resource", [...new Set(ore.map(b => b.name))].join(" / ")],
          ["Ore depth", under > 0.05 ? deepSaid(under) : "At surface"], ["Ore thickness", deepSaid(thick)]);
      } else {
        if (!deposits.length) values.push(["Resource", "No ore in this column"]);
      }
      rows.push(inspectionValues(values), revealButton());
    }
    const water = waterAt(picked.at[0], picked.at[2]);
    if (water && water.depth > 0.05) {
      const wet = document.createElement("p");
      wet.className = "pk-facts";
      wet.textContent = `under ${deepSaid(water.depth)} of water`;
      rows.push(wet);
    }
    rows.push(keyRows([{ key: keyOf("dig"), what: "dig here" },
                       { key: keyOf("heap"), what: "heap what you carry here" }]));
  }

  box.replaceChildren(...rows);
}

// ---------------------------------------------------------------------------
// What you look at, or hold: the side view's details
// ---------------------------------------------------------------------------
//
// The owner, 2026-09-14: over the view only the name of what the crosshair is
// on, and "the details about it in the side view". What it is, and what can be
// done with it now, each with its key. E does the one marked E -- what a person
// would do first: pick a loose thing up, open a gate -- and Tab moves E on to
// the next, so every one of them is on a key and nothing needs the mouse let go
// of. Under them, what the last thing you did came to. It says only what the
// engine has shown: rock stops an oak point, so on rock no digging is offered.

// What the last thing the person did came to -- "Ball left your hand at 7.2
// m/s" -- or why it could not be done. Said in the details, not the chat: the
// chat is the conversation with the room.
function lastAction(text, tone = "did") {
  if (!text) return;
  world.last = { text: sentence(text), tone };
  showDetails(true);
}

// What E can do with the thing the crosshair is on, with the hand empty, in
// order; E does the first unless Tab has moved it on. Each is { label, run }.
// A loose thing is picked up first (the owner: "E on a loose thing: pick it
// up"); a thing on a joint does first what the room's chat gave it -- "Open the
// gate" -- and otherwise is taken hold of by hand; then the rest of its actions.
function choicesFor(name) {
  const entry = world.bodies.get(name);
  if (!entry) return [];
  // A part of a machine opens the machine's panel first -- the owner's review,
  // 2026-09-15: "E on a machine opens the panel" -- and what else it offers
  // comes after, Tab away: working a machine by hand is the advanced choice.
  const panels = machinesOfPart(name).map((c) => ({ label: `Open the ${c.name}'s panel`,
                                                    run: () => openMachinePanel(c) }));
  return [...panels, ...thingChoices(name, entry)];
}

function thingChoices(name, entry) {
  const pick = tools.profileOf(name), bow = profileOf(name), blade = bladeFor(name);
  const take = () => intend("pick");
  const actions = allActionsFor(name).map((action, i) => ({ label: action.label, run: () => runAction(name, i) }));
  if (pick) return [{ label: `Take up ${pick.object}`, run: take }, ...actions];
  if (bow) return [{ label: `Take up ${bow.object}`, run: take }, ...actions];
  if (blade) return [{ label: "Take it by the grip", run: take }, ...actions];
  if (entry.anchored) return actions;
  if (onAJoint(name)) {
    const own = actionsFor(name).length;
    return [...actions.slice(0, own), { label: "Take hold of it and work it by hand", run: take },
            ...actions.slice(own)];
  }
  if (throwable(entry, false)) return [{ label: "Pick it up", run: take }, ...actions];
  return [{ label: "Take hold of it and carry it", run: take }, ...actions];
}

// ...and with something in the hand: what E does with it -- puts it down, or
// lets go of what is held on a joint -- then what else can be done from there.
function heldChoices() {
  const held = world.held;
  if (!held) return [];
  const name = held.name;
  if(held.recovery) return [{label:"Release rover",run:()=>intend("drop")}];
  if (held.pick) return [{ label: `Put ${held.pick.object} down`, run: () => intend("put down") }];
  if (held.bow) {
    return [{ label: world.use.mode === "drawing" ? "Let the string down" : `Let go of ${held.bow.object}`,
              run: () => intend("put down") }];
  }
  if (held.blade) return [{ label: `Let go of ${name}`, run: () => intend("drop") }];
  const latch = latchOn(name) ? [{ label: "Release its latch", run: () => unlatch() }] : [];
  if (workingJoint()) {
    const out = [{ label: `Let go of ${name}`, run: () => intend("drop") }];
    allActionsFor(name).forEach((action, i) => {
      if (goesOnFromHold(name, action)) out.push({ label: action.label, run: () => runAction(name, i) });
    });
    return [...out, ...latch];
  }
  // Preview is visible before the key is pressed; E commits that destination.
  if (world.placing) {
    return [{ label: "Put it here", run: () => intend(placeHere) },
            { label: "Stop placing", run: () => stopPlacing(true) }];
  }
  return [{ label: "Place it…", run: () => startPlacing() },
          { label: "Put it down", run: () => intend("drop") }, ...latch];
}

function choices() {
  if (world.held) return { of: `held:${world.held.name}`, list: heldChoices() };
  const on = world.aim && world.aim.name;
  if (on) return { of: `on:${on}`, list: choicesFor(on) };
  // Nothing under the crosshair: a tool lying beside where it meets the ground
  // is still taken up by E (tools.js nearTool).
  const near = world.groundAim && !world.acting ? tools.nearTool() : null;
  return near ? { of: `near:${near.tool}`, list: [{ label: `Take up ${near.object}`, run: () => intend("pick") }] }
              : { of: "", list: [] };
}

// Which one E does: the first, or the one Tab moved it on to -- back to the
// first whenever what the crosshair is on, or what is held, changes.
function chosen() {
  const { of, list } = choices();
  if (world.choice.of !== of) world.choice = { of, index: 0 };
  if (world.choice.index >= list.length) world.choice.index = 0;
  return { list, index: world.choice.index };
}

// E.
function doChoice() {
  const { list, index } = chosen();
  world.choice.index = 0;
  if (list[index]) list[index].run();
}

// Tab: E moves on to the next.
function nextChoice() {
  const { list } = chosen();
  if (list.length > 1) world.choice.index = (world.choice.index + 1) % list.length;
  showDetails(true);
}

// What the details say about a thing: what it is made of, what it weighs, how
// big it is and how far away, and what holds it -- the engine's numbers.
function factsOf(name, entry, distance) {
  if (!entry) return "";
  const out = [];
  const part = tools.profileOf(name) || profileOf(name);
  if (part && part.object !== name) out.push(`its ${name}`);
  if (entry.material) out.push(entry.material);
  if (entry.mass && !entry.anchored) out.push(grams(entry.mass));
  const d = entry.dims;
  if (d) {
    out.push(entry.shape === "sphere" ? `${Math.round(d[0] * 1000)} mm across`
      : `${Math.round(d[0] * 1000)} × ${Math.round(d[1] * 1000)} × ${Math.round(d[2] * 1000)} mm`);
  }
  if (Number.isFinite(distance)) out.push(`${distance.toFixed(1)} m away`);
  if (entry.anchored) out.push("fixed in place");
  else if (onAJoint(name)) {
    const guide = guideFor(name);
    out.push(!guide ? "joined to something" : guide.kind === "slider" ? "slides in a groove" : "turns on a pin");
  } else if (!throwable(entry, false) && entry.mass) out.push("too heavy for one hand to throw");
  // A machine, as the last step left it (docs/machine-world.md): what the motor
  // that turns this is doing, and what a battery in it holds -- here, where the
  // person is looking, as well as in the Room tab's Machines panel.
  for (const m of (world.machines && world.machines.motors) || []) {
    if (!m.on || m.on[1] !== name) continue;
    out.push(m.state === "driving" ? `its motor runs at ${Math.round(m.power_w)} W`
      : m.state === "braking" ? "its motor's brake is on"
      : m.state === "flat" ? "its motor's battery is flat"
      : m.state === "gone" ? "its motor's pin is gone" : "its motor is off");
  }
  for (const s of (world.machines && world.machines.stores) || []) {
    if (s.body !== name || !(s.capacity_j > 0)) continue;
    out.push(`a battery, ${Math.round(100 * s.charge_j / s.capacity_j)}% charged (${(s.charge_j / 1000).toFixed(2)} kJ)`);
  }
  // The true depth, beside a hollow drawn deeper than that so it can be seen at
  // all: saying so is what makes the drawing honest rather than a claim.
  if (entry.dentMm > 0) {
    out.push(`dented ${entry.dentMm < 1 ? entry.dentMm.toFixed(2) : entry.dentMm.toFixed(1)} mm`
      + " (drawn deeper so you can see it)");
  }
  const hot = heat.last && (heat.last.bodies || []).find((b) => b.name === name);
  if (hot) out.push(`${Math.round(hot.t_k)} K`);
  if (bladeFor(name)) out.push("has an edge");
  return out.join(" · ");
}

// Everything the details say, worked out from what the page knows now: the
// thing held, else the thing looked at, else the ground looked at.
function detailsModel() {
  const k = keyOf;
  const rows = [];
  const model = { name: "", facts: "", rows, note: "", meter: null,
                  last: world.last ? { ...world.last } : null };
  const { list, index } = chosen();
  const choiceRows = () => {
    list.forEach((choice, i) => rows.push(i === index ? [[k("interact")], choice.label, "chosen"]
                                                       : [[], choice.label, "other"]));
    if (list.length > 1) rows.push([[k("next")], "E does the next one"]);
  };
  const held = world.held;
  if(held?.recovery) {
    model.name=titled(world.use.name);model.facts="Recovery · rover stopped";
    model.note="Look up to lift · walk to pull · mouse wheel changes reach";
    choiceRows();return model;
  }
  if (held) {
    const entry = world.bodies.get(held.name);
    model.name = titled(heldName());
    const facts = [];
    if (entry && entry.material) facts.push(entry.material);
    if (entry && entry.mass) facts.push(grams(entry.mass));
    const ours = recordHolds(held.name);
    facts.push(ours ? "in your right hand" : held.bow ? "its string in your hand" : "held by your hand");
    const inv = world.inventory;
    const slot = ours && inv && inv.hands ? (inv.hands[inv.hand_in_the_world] || {}).slot : null;
    if (Number.isInteger(slot) && slot < SLOT_KEYS) facts.push(`${slot + 1} puts it back in your bag`);
    model.facts = facts.join(" · ");
    choiceRows();
    if (world.placing) {
      rows.push([["Mouse wheel"], world.placing.turnable ? "turn it" : "it goes down the way it is held"],
                [["Esc"], "stop placing: it stays in your hand"]);
    }
    // A broken piece has no name of its own to come back under, so the bag
    // takes it as the material it is made of: the same key, said as what it
    // does.
    if (ours || held.throwable || held.pick || held.blade)
      rows.push([[k("stow")], entry && entry.shape === "hull" ? "sweep it up into what you carry"
                                                             : "put it in your bag"]);
    if (held.blade) rows.push([[k("secondary")], "turn the edge a quarter: left, down, right, up"]);
    const breaker = breakerInHand();
    if (breaker) {
      rows.push([[k("breaker")], breaker.on ? "let the trigger go" : "hold the trigger against the face"]);
      const battery = ((world.machines && world.machines.stores) || [])
        .find((s) => s.id === breaker.store);
      const left = battery ? ` · ${(battery.charge_j / 1000).toFixed(0)} kJ left` : "";
      model.note = [breaker.on
        ? (breaker.working
            ? `breaking: ${Math.round(breaker.drawn_w)} W into the rock, ` +
              `${Math.round(100 * breaker.broken_share)}% through this cell`
            : `running, doing nothing: ${breaker.why}`)
        : `${Math.round(breaker.watts)} W against rock${left}`, model.note].filter(Boolean).join(" · ");
    }
    // Placing: what the copy is doing is the only help -- not a throw's preview,
    // nor the wheel as it is when only holding.
    const help = world.placing ? { rows: [], note: "", meter: null } : handHelp(world.use);
    rows.push(...help.rows);
    model.meter = help.meter;
    model.note = [help.note, world.carry].filter(Boolean).join(" · ");
  } else if (world.aim && world.aim.name) {
    const name = world.aim.name;
    const entry = world.bodies.get(name);
    const part = tools.profileOf(name) || profileOf(name);
    model.name = world.inventory?.labels?.[name] || titled(part ? part.object : name);
    model.facts = factsOf(name, entry, world.aim.distance_m);
    // And what it holds, if it is a container: walking up to a pail should
    // tell you about the pail without opening a panel.
    const holding = vesselLine(name);
    if (holding) model.facts += ` · ${holding}`;
    choiceRows();
    if (entry && !entry.anchored && (tools.profileOf(name) || throwable(entry, onAJoint(name))))
      rows.push([[k("stow")], entry.shape === "hull" ? "sweep it up into what you carry"
                                                     : "put it in your bag"]);
    // Wiring: a run starts at a battery and is made off at a fitting. What you
    // are looking at decides which end this is.
    const store = storeOn(name), fitting = lampOn(name);
    if (world.laying && fitting && !fitting.cable) {
      const paid = runLength(world.laying.points.concat([[camera.position.x, camera.position.y, camera.position.z]]));
      rows.push([[k("cable")], `make the cable off here — ${paid.toFixed(1)} m paid out`]);
    } else if (world.laying && store) {
      rows.push([[k("cable")], "drop the drum: this run goes nowhere"]);
    } else if (!world.laying && store) {
      rows.push([[k("cable")], "start a run of cable here"]);
    } else if (!world.laying && fitting && !fitting.cable) {
      model.note = ["it is not wired to anything: start a run at a battery and walk it here",
                    model.note].filter(Boolean).join(" · ");
    }
    if (fitting) {
      model.facts = [model.facts, fitting.lit
        ? `lit: ${Math.round(fitting.drawn_w)} W, ${Math.round(fitting.lumens)} lumens`
        : `dark — ${fitting.why || "not wired"}`].filter(Boolean).join(" · ");
    }
    rows.push([[k("heat")], "heat it"]);
  } else if (world.groundAim) {
    const underfoot = groundMadeOf(world.groundAim);
    choiceRows();
    if (!ground.grid || !underfoot) {
      model.name = "The Floor";
      model.facts = "flat concrete: there is nothing to dig";
    } else {
      const [x, , z] = world.groundAim;
      const water = waterAt(x, z);
      model.name = water && water.depth > 0.05 ? "Water" : titled(underfoot);
      // What it is made of down there, not only what is on top: this is the
      // whole of knowing where you are digging.
      const under = groundUnderfoot(world.groundAim);
      model.facts = [under ? `the ground: ${under}` : `the ground, ${underfoot}`,
                     `${groundAt(x, z).toFixed(2)} m up`,
                     water && water.depth > 0.005
                       ? `under ${(water.depth * 100).toFixed(0)} cm of water flowing ${Math.hypot(water.u, water.w).toFixed(2)} m/s`
                       : ""].filter(Boolean).join(" · ");
      if (underfoot !== "rock") rows.push([[k("dig")], `dig here, in the ${underfoot}`]);
      const carried = world.carriedGround
        ? (Number(world.carriedGround.soil_kg) || 0) + (Number(world.carriedGround.sand_kg) || 0) : 0;
      if (carried > 0.0005) rows.push([[k("heap")], "heap what you carry here"]);
      const tool = (world.tools || [])[0] || null;
      model.note = underfoot === "rock"
        ? (tool ? "Bare rock: a point no harder than the rock stops on it." : "")
        : !tool ? `Nothing here to dig with — ${k("talk")} and ask the room for a pick.`
          : list.length ? ""
            // WHICH tool, and nothing about how to hold it. How to hold it is
            // already written twice over: on the tool itself in the Bag tab,
            // and in the Keys tab. Saying it a third time here is what turned
            // the side view into a wall of text.
            // tool.object already reads "the pick", so it only wants a capital
            // and a stop -- writing "The " in front of it gave "The the pick".
            : sentence(`${tool.object} digs this ground`);
    }
  } else {
    model.facts = "Look at something to see what it is and what you can do with it.";
    rows.push([[k("talk")], "ask the room to build or change anything"]);
  }
  const focused = world.bodies.get(held?.name || world.aim?.name);
  if (focused?.fromPrecise) {
    model.facts += " · precise rigid, no internal failure";
    model.note = [model.note, "Exact collision shape; it turns on its pins and goes in the bag whole, and does not bend, break or take heat."].filter(Boolean).join(" · ");
    // It takes no heat yet; the bag it does take, whole (LiveWorld::park).
    for (let i = rows.length - 1; i >= 0; i--) {
      if (rows[i][1] === "heat it") rows.splice(i, 1);
    }
  }
  // WHAT A MACHINE IS DOING AND WHAT IS IN IT, ON THE THING ITSELF.
  // Its routine used to be shown only in the machine panel, a second click
  // away behind the other panes, so a rover that had just dug 12 kg of copper
  // ore read exactly like one that had done nothing at all -- the owner,
  // 2026-09-26: "i can't see what its trying to do, did it dig? did it get
  // something? nothing visual happens". A machine's parts are named
  // "rover: left wheel", so the program is what stands before the colon.
  //
  // The NAME comes from the aim and not from the body, because a body entry
  // in world.bodies has no name on it at all -- the name is the map's key.
  // Reading focused.name gave undefined, the lookup asked for "" every time,
  // and the line silently never appeared however right everything else was.
  const lookingAt = String(held?.name || world.aim?.name || "");
  const running = lookingAt && world.brains
    ? world.brains.get(lookingAt.split(":")[0].trim()) : null;
  if (running && running.routine && running.routine.of) {
    const r = running.routine, load = r.load || null;
    const got = load && load.goods_kg && Object.keys(load.goods_kg).length
      ? Object.entries(load.goods_kg).map(([what, kg]) => `${(+kg).toFixed(1)} kg of ${what}`).join(", ")
      : load && load.kg > 0.05 ? `${load.kg.toFixed(1)} kg of soil and sand`
        : "nothing yet";
    model.facts += ` · ${r.doing || "idle"}`
      + (load ? ` · carrying ${got}, of ${Math.round(load.capacity_kg)} kg it can hold` : "");
    const said = r.notes && r.notes.length ? r.notes[r.notes.length - 1] : "";
    if (said) model.note = [model.note, said].filter(Boolean).join(" · ");
    // And how it is doing, in words rather than as an arc over its wheels.
    // Off its PROGRAM, not its controls: a control on the page is called
    // "left wheel" and carries nothing saying which machine it drives, while
    // a program carries `body` and `parts`, and the state worth reading.
    const mine = programsNow().find((p) => p.name === lookingAt.split(":")[0].trim()
      || p.body === lookingAt.split(":")[0].trim() || (p.parts || []).includes(lookingAt));
    if (mine) {
      const how = [];
      if (mine.doing) how.push(mine.why ? `${mine.doing} — ${mine.why}` : mine.doing);
      const wet = (mine.sensors || []).filter((x) => x.kind !== "ground" && x.sees).length;
      if (wet) how.push(`${wet === 1 ? "a water sensor sees" : wet + " water sensors see"} water`);
      const groundHazards=(mine.sensors || []).filter(x=>x.kind==="ground"&&x.sees).length;
      if(groundHazards) how.push(`${groundHazards} ground ${groundHazards===1 ? "probe sees" : "probes see"} a drop/step`);
      if (how.length) model.facts += ` · ${how.join(" · ")}`;
    }
  }
  if (world.doing) model.note = `${world.doing}: doing it…`;
  return model;
}

// The details, drawn from the model: only when it has changed, several times a
// second, and at once when the hand's state changes (showUse). The crosshair's
// ring fills with the meter.
let detailsSaid = "";
let lastDetails = { name: "", facts: "", rows: [], note: "", meter: null, last: null };
function showDetails(now = false) {
  // What is pinned is about one thing and stays about it, but everything IN it
  // is live -- the battery empties while you watch. Rebuilt on the same beat.
  if (somethingIsPinned()) showPicked();
  const model = detailsModel();
  const useName = world.held?.name || world.aim?.name;
  if (useName && (actionsFor(useName).length || !world.held)) {
    model.rows = model.rows.filter(([keys]) => !keys.includes(keyOf("primary")));
    model.rows.unshift([[keyOf("primary")], primaryAction(useName).label, "primary"]);
  }
  const said = JSON.stringify(model);
  if (!now && said === detailsSaid) return;
  detailsSaid = said;
  lastDetails = model;
  $("details-name").textContent = model.name || " ";
  $("details-facts").textContent = model.facts;
  $("details-actions").replaceChildren(...model.rows.map(([keysOf, what, kind]) => {
    const li = document.createElement("li");
    if (kind) li.className = kind;
    const cell = document.createElement("span");
    cell.className = "keys";
    for (const key of keysOf) {
      const kbd = document.createElement("kbd");
      kbd.textContent = key;
      cell.append(kbd);
    }
    const words = document.createElement("span");
    words.className = "what";
    words.textContent = what;
    li.append(cell, words);
    return li;
  }));
  $("details-note").textContent = model.note;
  const meter = model.meter;
  $("details-meter").hidden = !meter;
  if (meter) {
    $("details-meter-label").textContent = meter.label;
    $("details-meter-fill").style.width = `${Math.round(100 * meter.fraction)}%`;
    $("details-meter-value").textContent = meter.value;
  }
  $("details-last").hidden = !model.last;
  $("details-last").classList.toggle("refused", !!model.last && model.last.tone === "refused");
  $("details-last-text").textContent = model.last ? model.last.text : "";
  const cross = $("crosshair");
  cross.classList.toggle("metering", !!meter);
  if (meter) cross.style.setProperty("--fill", String(Math.max(0, Math.min(1, meter.fraction))));
}
setInterval(showDetails, 150);

// ---------------------------------------------------------------------------
// The workbench
// ---------------------------------------------------------------------------
//
// The lab's recorded runs, played back as a small copy on a bench in front of
// the person while the room goes on (the owner: recorded runs play "on a bench
// in front of you"; workbench.js sets it out and draws it). K opens the side
// view's Bench tab and lets the mouse go, so a run can be chosen with it. The
// bench stays where it was set down until it is put away.
const workbench = makeWorkbench({ scene, camera, groundAt, api });
let runsListed = false, scrubbing = false, workbenchSaid = "";

// The side view's tabs, one shown at a time (the owner: "all the other text
// needs to be in tabs in part of the side view"). A tab lets go of the focus
// once clicked, so the keys go back to the room.
const TABS = ["bag", "notes", "room", "bench", "keys"];
function showTab(which) {
  for (const tab of TABS) {
    $(`tab-${tab}`).setAttribute("aria-selected", String(tab === which));
    $(`pane-${tab}`).hidden = tab !== which;
  }
  if (which === "bench" && !runsListed) listRuns();
}
for (const tab of TABS) {
  $(`tab-${tab}`).addEventListener("click", (e) => { e.currentTarget.blur(); showTab(tab); });
}

// K: the Bench tab, with the mouse let go so a run can be chosen with it.
function openWorkbench() {
  showTab("bench");
  if (document.pointerLockElement) document.exitPointerLock?.();
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
  // What a person can carry is the room's to say, and a room with no ground says nothing.
  world.carryLimitKg = carried && Number.isFinite(Number(carried.limit_kg)) ? Number(carried.limit_kg) : null;
  // Rock too, since a face can be worked by hand: a 0.25 m cell of it is 37 kg,
  // so two of them is most of what a person can carry.
  for (const what of ["sand", "soil", "rock"]) {
    const kg = carried ? Number(carried[`${what}_kg`]) || 0 : 0;
    if (kg > 0.0005) world.stock.set(what, { kg, pieces: 0 });
    else world.stock.delete(what);
  }
  showStock();
}

function carriedSaid() {
  const c = world.carriedGround || {};
  const parts = ["sand", "soil", "rock"].filter((what) => Number(c[`${what}_kg`]) > 0.0005)
    .map((what) => `${grams(Number(c[`${what}_kg`]))} of ${what === "rock" ? "broken rock" : what}`);
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
  storeFlows.clear();
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
  lastAction("Noted: the last few seconds are in the server log.");
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
  if (isKey("next", e.code)) e.preventDefault();   // not the browser's focus hop
  if (e.repeat) return;
  // CTRL, ALT AND THE COMMAND KEY BELONG TO THE BROWSER, not to the room.
  // Ctrl+A is select-all, and taking its A as "strafe left" is how the owner
  // ended up flying sideways: "it was like i was flying left when i hit
  // ctrl+A to try to select all it started doing it." Whether the keyup
  // arrives after a shortcut is the browser's business and not something to
  // rely on -- so a modified key is never taken as a held control in the
  // first place. Shift is ours: Shift+Space is how a flying camera goes
  // down, and Shift runs.
  if (e.ctrlKey || e.altKey || e.metaKey) return;
  keys.add(e.code);

  // The one control language (interaction.js): E does what the side view marks
  // -- picks up, puts down, opens -- and Tab moves it on; Q puts in the bag, and
  // the number keys take a thing out of the bag's slots and put it back.
  // Esc while placing: the copy goes, and the thing stays in the hand.
  // Esc while a throw is aimed is how you change your mind: wound up, it comes
  // down and stays in the hand; otherwise it is put back down where the ghost
  // shows. Never a throw -- there is no key that throws by accident.
  //
  // It goes AHEAD of stopping a placement, because a throwable thing in the
  // hand always has a placing ghost up the moment it is picked up: Esc would
  // otherwise only ever dismiss the ghost, and a second Esc would be needed to
  // put the thing back, which is not what one key meaning "never mind" does.
  if (e.code === "Escape" && world.held?.throwable
      && ["ready", "preparing", "blocked"].includes(world.use.mode)) {
    if (world.use.mode === "preparing") cancelWindUp();
    else {
      if (world.placing) stopPlacing(true);
      intend(() => putDown(false));
    }
  }
  else if (e.code === "Escape" && world.placing && !world.placing.carrying) stopPlacing(true);
  // Esc closes a machine's panel when nothing else is using it -- and not
  // while the mouse is looking round, where Esc gives the mouse back first.
  else if (e.code === "Escape" && machinePanel.id != null && !document.pointerLockElement) closeMachinePanel();
  // Esc is "never mind", and it means the lightest thing still standing:
  // let go of what is pinned before letting go of the machine you are being.
  else if (e.code === "Escape" && somethingIsPinned()) unpick();
  // And last, out of the machine. The panel tells you this key, so it has to
  // be true -- the owner's complaint about the panel was keys that were not.
  else if (e.code === "Escape" && !riding.godMode && riding.name && !document.pointerLockElement) {
    letGoOfTheMachine();
  }
  if (isKey("primary", e.code)) { e.preventDefault(); primaryUsed = pressPrimary(); }
  if (isKey("interact", e.code)) intend(doChoice);
  if (isKey("next", e.code)) nextChoice();
  if (isKey("stow", e.code)) toTheBag();
  if (isKey("slots", e.code)) fromSlot(Number(e.code.slice(-1)) - 1);
  // Turning what is held: the keys are read every frame while they are down
  // (turnFromKeys); U stands it on end. On something the wrist cannot turn,
  // the first press says why.
  if (isKey("upright", e.code)) standUpright();
  if (TURNS.some((t) => isKey(t.action, e.code))) turnKeyPressed();
  if (e.code === "KeyR") unlatch();
  if (e.code === "KeyL") markLag();
  // The room's buttons from the keyboard (interaction.js BINDINGS), so what the
  // side view offers, it offers with the key that does it.
  if (isKey("breaker", e.code)) { e.preventDefault(); pullTheTrigger(); }
  if (isKey("cable", e.code)) { e.preventDefault(); workTheCable(); }
  if (isKey("dig", e.code)) $("dig-it").click();
  if (isKey("heap", e.code)) $("heap-it").click();
  if (isKey("heat", e.code)) $("heat-it").click();
  if (isKey("workbench", e.code)) openWorkbench();
  if (["KeyW","KeyA","KeyS","KeyD","KeyQ","KeyE","Space",
       "ArrowUp","ArrowDown","ArrowLeft","ArrowRight"].includes(e.code)) e.preventDefault();
});
addEventListener("keyup", (e) => {
  keys.delete(e.code);
  if (isKey("primary", e.code) && primaryUsed) { primaryUsed = false; releasePrimary(); }
  // LETTING GO IS AN EVENT, not something to notice on the next frame. The
  // renewal belongs on the frame loop -- it is a heartbeat -- but the
  // release happens at a known instant and this is it. Leaving it to the
  // loop meant a machine went on being told to drive until the loop next
  // ran, and since an ask now stands for three seconds rather than six
  // tenths that was far worse than it used to be: CI measured one still
  // doing 4.13 m/s three seconds after the key came up.
  if (RIDE_KEYS.has(e.code)) letGoOfTheKeys();
});
addEventListener("blur", () => keys.clear());
// A tab put behind another never gets the keyup for what was held when it
// went, and a machine you are riding would go on being told to turn.
document.addEventListener("visibilitychange", () => { if (document.hidden) keys.clear(); });
// Every control, in the side view's Keys tab, said from the same table the keys
// are read from.
$("keys-list").replaceChildren(...controls().flatMap(([keysSaid, what]) => {
  const dt = document.createElement("dt");
  const kbd = document.createElement("kbd");
  kbd.textContent = keysSaid;
  dt.append(kbd);
  const dd = document.createElement("dd");
  dd.textContent = what;
  return [dt, dd];
}));

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
  if (!held) {
    // Hands empty: the wheel zooms. A notch is about a tenth of the way, and
    // it works under pointer lock, where the slider cannot be clicked.
    e.preventDefault();
    setZoom(world.zoom * Math.exp(-e.deltaY * 0.0012));
    return;
  }
  if (held.bow || held.blade || held.pick) return;
  e.preventDefault();
  // Placing: the wheel turns the see-through copy about the vertical instead,
  // a twelfth of a turn a notch, and the engine is asked about it at once.
  if (world.placing && !world.placing.carrying) {
    if (world.placing.turnable) {
      world.placing.yaw += Math.sign(e.deltaY) * (Math.PI / 12);
      world.placing.asked = 0;
    }
    return;
  }
  held.distance = clamp(held.distance * Math.exp(-e.deltaY * 0.0015),
                        HOLD_RANGE_M.least, HOLD_RANGE_M.most);
}, { passive: false });

// Right-click releases a latch on whatever is under the crosshair: the bar off
// the gate, the nock off the string. On the mouse as well as on R because a
// latch is a second thing to do to the object you are already pointing at, and
// reaching for a key to do it is one hand too many.
$("zoom-range")?.addEventListener("input", (e) => setZoom(parseFloat(e.target.value)));
setZoom(1);

canvas.addEventListener("contextmenu", (e) => {
  e.preventDefault();
  // Secondary, in the middle of a wind-up: lower it instead of throwing.
  if (world.use.mode === "preparing") { cancelWindUp(); return; }
  // ...and in the middle of a draw, let the string back down.
  if (world.use.mode === "drawing") { intend("let down"); return; }
  // With a tool in hand it stops the tool going on after the use in hand
  // (tools.js): the server's use pries and draws the point out by itself.
  if (world.held && world.held.pick) {
    tools.stop();
    return;
  }
  // With a blade in hand it turns the edge instead, a quarter about the
  // blade's own length: left, down, right, up.
  if (world.held && world.held.blade) {
    world.held.stance = (world.held.stance + 1) % STANCES.length;
    lastAction(`Turned the edge to face ${STANCES[world.held.stance].name}.`);
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
function primaryAction(name) {
  const offered = actionsFor(name);
  return offered.find((a) => a.primary) || offered[0] || { label: "Inspect", steps: [{ do: "inspect" }] };
}

// Whether a thing's own primary action does nothing but set it down. The one
// step called "place" is the shape pressPrimary already knew, because that is
// what it hands to placeHere; now it is also the only action a throw is allowed
// to go in front of. Nothing offered at all counts as nothing in the way.
function wouldOnlySetItDown(name) {
  if (!actionsFor(name).length) return true;
  const program = primaryAction(name);
  return program.steps?.length === 1 && program.steps[0].do === "place";
}

function pressPrimary() {
  if (!world.session) return false;
  if (world.placing?.carrying || world.placing?.confirming) return true;
  if (world.asking || world.acting) return true;
  if (world.paused) { lastAction("Resume the world before using a product.", "refused"); return true; }
  const name = world.held?.name || world.aim?.name;
  // A throw takes the button ahead of the held thing's OWN action, but only
  // when that action does nothing but set it down (the owner, 2026-09-26).
  // Every block in the valley has "Set it down" on it, so clicking used to put
  // the block at your feet and the aim arc could never throw it at all.
  // Anything with a real use in the hand keeps the button -- the mace still
  // swings, a tool still works, a bow still draws -- and setting down is still
  // on E, in the side view, and now on Esc.
  const aimingAThrow = !!world.held && world.held.throwable && name === world.held.name
    && ["ready", "blocked"].includes(world.use.mode) && wouldOnlySetItDown(name);
  if (!aimingAThrow && name && actionsFor(name).length) {
    const program = primaryAction(name);
    if (world.held && program.steps?.length === 1 && program.steps[0].do === "place") intend(placeHere);
    else runAction(name, 0, true);
    return true;
  }
  if (world.held?.throwable && ["ready", "blocked"].includes(world.use.mode)) {
    // Refused before the wind-up only when the hand cannot make the throw at
    // all: winding up something you cannot throw spends the wind-up and tells
    // you nothing. Pointing somewhere it would not land is NOT refused here --
    // the wind-up is half of how a throw is aimed, and the ring moves further
    // out as it fills, so the way to reach a far target is to hold on.
    const seen = world.use.preview;
    if (seen && !seen.possible) {
      lastAction(seen.why || `${titled(world.held.name)} cannot be thrown from here.`, "refused");
      return true;
    }
    startWindUp();
  }
  else if (world.held?.bow && world.use.mode === "bow-ready") intend("draw");
  else if (world.held?.pick) tools.press();
  else if (name) runAction(name, 0, true);
  else return false;
  return true;
}

function releasePrimary() {
  if (world.use.mode === "preparing") intend("let fly");
  else if (world.use.mode === "drawing") intend("loose");
  tools.release();
}

// A CLICK DOES IT. One click on a thing does what E does -- picks it up, or
// whatever the side view marks as its first action.
//
// It used to take two: the first click was swallowed asking for the pointer
// lock, and a second on the same thing within 400 ms acted. That was written
// when the only way to aim was to line the crosshair up in the middle of the
// view, so a click could not mean "that one" -- the view had to be turned
// until the crosshair was on it. The cursor picks now (aimVector), so a click
// already says which thing, and the first one may as well do the thing. The
// owner: "it's hard to click on objects because I have to line up my +
// symbol, I'd like to be able to just click on it with my mouse."
//
// Looking around is dragging, which is what the drag handler was always for.
canvas.addEventListener("pointerdown", (e) => {
  offerStick(e);
  // The LEFT button only. The right one releases a latch, and it used to do
  // that and then pick the thing up as well, because a pointerup is a
  // pointerup whichever button made it.
  if (e.button !== 0) return;
  if (e.altKey) return;          // inspect while carrying, without primary Use
  // Primary held with something throwable in the hand winds it up. Looking
  // still works while it does -- that is how a throw is aimed.
  if (looking || world.held) primaryUsed = pressPrimary();
  if (looking) return;           // captured: the move handler has it
  drag = { x: e.clientX, y: e.clientY, moved: false };
  // Capture can be refused -- a pointer already gone, or one a test made up --
  // and dragging to look works without it.
  try { canvas.setPointerCapture(e.pointerId); } catch { /* look without it */ }
});
canvas.addEventListener("pointermove", (e) => {
  cursor = cursorAt(e);
  if (cursor) cursor.touch = e.pointerType !== "mouse";
  offerStick(e);
  markAt(cursor);
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
  drag.x = e.clientX; drag.y = e.clientY;
  turn(dx, dy);
});
// The mouse off the view: back to the middle, so nothing is aimed at a place
// the mouse is no longer at.
canvas.addEventListener("pointerleave", () => { cursor = null; markAt(null); });

// The ring rides the cursor. It is the same mark it always was -- it fills as
// a wind-up fills and colours as something comes under it -- it is just no
// longer nailed to the middle of the screen.
function markAt(at) {
  const mark = $("crosshair");
  if (!mark) return;
  if (!at || document.pointerLockElement) {
    mark.style.left = ""; mark.style.top = "";
    return;
  }
  const box = canvas.getBoundingClientRect();
  mark.style.left = `${box.left + at.px}px`;
  mark.style.top = `${box.top + at.py}px`;
}
canvas.addEventListener("pointerup", (e) => {
  if (e.button !== 0) return;
  if (e.altKey && !primaryUsed) return;
  // Letting go of primary after a wind-up throws, however much the view was
  // turned while it was held.
  if (primaryUsed) {
    primaryUsed = false;
    if (drag) try { canvas.releasePointerCapture(e.pointerId); } catch { /* gone */ }
    drag = null;
    releasePrimary();
    return;
  }
  const was = drag;
  drag = null;
  // A finger that has lifted is nowhere, so nothing stays aimed at where it
  // last was -- and the crosshair goes back to the middle.
  if (e.pointerType !== "mouse") { cursor = null; markAt(null); }
  try { canvas.releasePointerCapture(e.pointerId); } catch { /* already gone */ }
  if (was && was.moved) return;          // that was a look, not a click
  // A tool is never dropped by a click -- E puts it down. A second click with
  // the pick's point in the ground used to come here and drop it.
  if (world.held && world.held.pick) return;
  if (world.held) { intend("drop"); return; }
  // Hand empty, and the cursor is on something: do the thing.
  if (world.aim && world.aim.name) intend(doChoice);
});

// AND THE SAME CLICK PINS IT. Separate from doing the thing: picking a stone
// up and reading about the stone you picked up are not in each other's way,
// and a click on bare ground -- which does nothing at all -- now says what
// the ground is.
canvas.addEventListener("click", (e) => {
  if (e.button !== 0) return;
  if (world.held && world.held.pick && !e.altKey) return;   // a swing, not a choice
  pinWhatWasClicked();
});

document.addEventListener("pointerlockchange", () => {
  looking = document.pointerLockElement === canvas;
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

// THE CURSOR PUSHES THE VIEW. Moving the mouse turns the room without
// clicking anything and without holding a button down: the middle of the
// screen is a dead zone where the cursor only picks things, and from there out
// to an edge the view turns that way, faster the nearer the edge. Park the
// cursor by an edge and it keeps turning; bring it back to the middle and it
// stops.
//
// Why not pointer lock, which is how a shooter does this: a browser will only
// lock the pointer on a click, and not having to click first is the whole
// point. So this is the ordinary cursor, and dragging still works for a big
// turn in one go.
//
// The dead zone is most of the screen because the owner asked to be able to
// click straight onto a thing rather than line the crosshair up with it: the
// place you click in is the place that does not turn.
const LOOK_DEAD = 0.55;        // share of the half-width that turns nothing
// Measured in the real page rather than guessed: at 2.2 the cursor in the
// corner brought the view round 122 degrees a second -- a whole turn in under
// three -- which is a flick, not a look. These are 63 and 34 degrees a second
// at the very edge, and gentler than that for most of the way out.
const LOOK_YAW_RATE = 1.1;     // radians a second at the very edge, side to side
const LOOK_PITCH_RATE = 0.6;   // and up and down, slower -- there is less of it

// How hard the cursor pushes at `v`, which is -1 to 1 across the visible view.
// Squared, so it eases in at the edge of the dead zone instead of stepping.
function lookPush(v) {
  const away = Math.abs(v);
  if (away <= LOOK_DEAD) return 0;
  const into = Math.min(1, (away - LOOK_DEAD) / (1 - LOOK_DEAD));
  return Math.sign(v) * into * into;
}

function lookFromCursor(dt) {
  // Dragging already turns the view, and a wind-up is aimed by hand.
  if (!cursor || drag) return;
  // And a finger is not a cursor. It has no hover: the last place it touched
  // stays put once it lifts, so an edge push would turn the room for ever.
  // On a touch screen looking around IS the drag, which already works.
  if (cursor.touch) return;
  const box = canvas.getBoundingClientRect();
  if (!box.width || !box.height) return;
  // The side panel sits ON the canvas, so the canvas's own right edge is
  // behind it and a cursor can never reach it. What counts is the edge of what
  // can be seen: turn right has to start before the panel does, or it is a
  // turn nobody can ask for.
  const panel = $("panel");
  const over = panel ? panel.getBoundingClientRect() : null;
  const right = over && over.width && over.left > box.left ? over.left : box.right;
  const wide = right - box.left;
  if (wide <= 0) return;
  const nx = (cursor.px / wide) * 2 - 1;
  const ny = -(cursor.py / box.height) * 2 + 1;
  const dx = lookPush(nx), dy = lookPush(ny);
  if (!dx && !dy) return;
  // turn() is in mouse pixels at 0.0022 radians each, so a rate in radians a
  // second becomes that many pixels of the same turn.
  const px = (rate) => (rate * dt) / 0.0022;
  turn(dx * px(LOOK_YAW_RATE), -dy * px(LOOK_PITCH_RATE));
}

// Arrow keys look, for anyone who would rather not drag and for a keyboard on
// its own.
function lookFromKeys(dt) {
  const rate = 90 * dt;
  if (keys.has("ArrowLeft")) turn(-rate, 0);
  if (keys.has("ArrowRight")) turn(rate, 0);
  if (keys.has("ArrowUp")) turn(0, -rate);
  if (keys.has("ArrowDown")) turn(0, rate);
}

// What the person carries weighs on them: the sand and soil they have dug, and
// the thing in their hand. With nothing, they walk and run as they did; with
// all they can carry (the engine's limit, CARRY_LIMIT_KG in live_session.py)
// they walk at two fifths of the pace and cannot run. It was all weightless:
// 435 kg of sand crossed the owner's room at a run.
function carriedKg() {
  let kg = Number(world.carriedGround?.objects_kg) || 0;
  for (const [, have] of world.stock) kg += Number(have.kg) || 0;
  return kg;
}
function loadFraction() {
  const limit = world.carryLimitKg;
  if (!limit) return 0;
  return Math.min(1, carriedKg() / limit);
}
function loadPace() { return 1 - 0.6 * loadFraction(); }

// The person in the water. Everything else in it already is: the engine presses
// on every body's own surface, so oak floats with 70% of itself under and a log
// goes downstream with the river (docs/terrain-and-water.md). The person is a
// point of view and not a body, and stood in 39 cm of water flowing at 0.32 m/s
// as if on dry land, or on the bed of a pool with the view under the surface and
// nothing to say so.
//
// The body is taken to hang 1.6 m below the eye, never below the ground, and
// what matters is how much of it is under: to the knees they wade at four fifths
// of their pace, by 1.2 m they are swimming at three tenths. Water deeper than
// their thighs takes them with it -- none of its speed at 0.5 m, all of it by
// 1.2 m, where nothing of them is on the bed -- and a person overhead sees so.
// Standing 5 m up over a river is over it, not in it.
const BODY_BELOW_EYE_M = 1.6, WADE_TO_SWIM_M = 1.2, CARRIED_FROM_M = 0.5;
// The water where the person is: the room's, unless a journey has said
// (banjoRoom.waterForThePerson). A journey cannot ask a river to be 0.9 m deep
// and moving at 0.4 m/s under someone -- where the page is drawn in software the
// world runs behind the clock, and the river's deeper reaches are not moving yet
// when it looks -- so what such water does to a person is checked in water the
// journey describes: { level, depth, u, w }, as waterAt gives it, over a bed at
// level - depth.
let waterSaid = null;
function inTheWater() {
  const wet = waterSaid ? waterSaid(camera.position.x, camera.position.z)
    : ground.heights ? waterAt(camera.position.x, camera.position.z) : null;
  if (!wet || !(wet.depth > 0.02)) return null;
  // The bed under their own feet, not under the nearest column's middle: on a
  // riffle the two are 8 cm apart and more, and they stand on the ground.
  const bed = waterSaid ? wet.level - wet.depth : groundAt(camera.position.x, camera.position.z);
  const feet = Math.max(bed, camera.position.y - BODY_BELOW_EYE_M);
  const under = Math.min(BODY_BELOW_EYE_M, wet.level - feet);
  if (!(under > 0.02)) return null;
  const carried = Math.min(1, Math.max(0, (under - CARRIED_FROM_M) / (WADE_TO_SWIM_M - CARRIED_FROM_M)));
  return { under, level: wet.level, u: wet.u, w: wet.w, speed: Math.hypot(wet.u, wet.w),
           pace: 1 - 0.7 * Math.min(1, under / WADE_TO_SWIM_M), carried,
           head_under: camera.position.y < wet.level };
}

// A THUMBSTICK, for a screen with no keyboard. How far it is pushed, -1 to 1
// each way, and whether a finger is on it. Fed into walk() exactly where W, A,
// S and D are read, so everything downstream -- load, water, the ground under
// you -- is the same walk it always was.
const stick = { x: 0, y: 0, hard: 0, on: false };
const STICK_REACH = 40;   // pixels from the middle that count as fully pushed
// A shove PAST the pad is a run. Not a full push, which is just how a thumb
// says "forward" -- measured at 0.92 of the rim it ran everywhere and never
// walked. There is no Shift on a phone, so the extra has to be in the gesture.
const STICK_RUN = 1.6;

function installStick() {
  const pad = $("stick");
  if (!pad) return;
  const thumb = pad.querySelector("i");
  let holding = null;
  const show = (dx, dy) => {
    thumb.style.setProperty("--dx", `${dx}px`);
    thumb.style.setProperty("--dy", `${dy}px`);
  };
  const move = (e) => {
    const box = pad.getBoundingClientRect();
    let dx = e.clientX - (box.left + box.width / 2);
    let dy = e.clientY - (box.top + box.height / 2);
    const out = Math.hypot(dx, dy);
    // Held past the rim, the thumb stays on the rim and the push stays full:
    // a thumb slides off a small pad constantly and should not cut the walk.
    stick.hard = out / STICK_REACH;
    if (out > STICK_REACH) { dx *= STICK_REACH / out; dy *= STICK_REACH / out; }
    show(dx, dy);
    stick.x = dx / STICK_REACH;
    stick.y = dy / STICK_REACH;
    stick.on = true;
  };
  const let_go = () => {
    holding = null; stick.x = 0; stick.y = 0; stick.hard = 0; stick.on = false;
    pad.dataset.held = "no"; show(0, 0);
  };
  pad.addEventListener("pointerdown", (e) => {
    holding = e.pointerId; pad.dataset.held = "yes";
    try { pad.setPointerCapture(e.pointerId); } catch { /* works without it */ }
    move(e); e.preventDefault();
  });
  pad.addEventListener("pointermove", (e) => { if (holding === e.pointerId) move(e); });
  for (const end of ["pointerup", "pointercancel", "pointerleave"]) {
    pad.addEventListener(end, (e) => { if (holding === e.pointerId) let_go(); });
  }
}

// The stick is for fingers, so it appears the first time one arrives and not
// before: a mouse never sees it, and nobody has to choose.
function offerStick(e) {
  const pad = $("stick");
  if (!pad || !pad.hidden || e.pointerType === "mouse") return;
  pad.hidden = false;
  pad.dataset.held = "no";
}

// FOLDING THE PANEL AWAY. The room is what a small screen came for, so the
// panel starts folded on one and is remembered either way.
function foldPanel(away) {
  document.body.classList.toggle("panel-away", away);
  const fold = $("panel-fold"), show = $("panel-show");
  if (fold) fold.setAttribute("aria-expanded", String(!away));
  if (show) show.hidden = !away;
  try { localStorage.setItem("banjo.panel", away ? "away" : "out"); } catch { /* private */ }
}

function installPanelFold() {
  const fold = $("panel-fold"), show = $("panel-show");
  if (fold) fold.addEventListener("click", () => foldPanel(true));
  if (show) show.addEventListener("click", () => foldPanel(false));
  let kept = null;
  try { kept = localStorage.getItem("banjo.panel"); } catch { /* private */ }
  foldPanel(kept ? kept === "away" : window.innerWidth <= 760);
}

installStick();
installPanelFold();

// ---------------------------------------------------------------------------
// WHO YOU ARE: a machine in the room, or a camera above it
// ---------------------------------------------------------------------------
//
// The owner, 2026-09-29, asked for the player to walk with gravity rather than
// fly, and then asked the better question: "can we always inhabit the body of a
// robot and choose which one we want to inhabit?" So there is no person. You
// are always looking out of something that is really there.
//
// That is not a shortcut, it is the whole point. A machine is already a body
// the engine simulates: it has mass, it collides with a crate, it falls off the
// lip of the adit, its wheels slip on a slope, and it can be run over. A
// walking person would have needed every one of those written again, and they
// would have been an approximation of what the rover already does exactly.
//
// GOD MODE is the old behaviour kept whole: the free camera that rises with
// Space, sinks with Shift+Space and passes through everything. It is for
// looking at the room rather than being in it, and it is off by default.
//
// The keys mean the same here as they do at the bench (workshop_drive.py):
// one machine does one thing at a time, and the ask that wins is the first of
// up, down, left, right, forward, back that is held.

const RIDE_ASKS = [["up", "rising"], ["down", "descending"], ["left", "turning left"],
                   ["right", "turning right"], ["forward", "going forward"], ["back", "backing off"]];
const RIDE_FLIES_ONLY = new Set(["rising", "descending"]);
//: How long an ask stands if the page stops sending. Long enough to cover a
//: slow frame, short enough that letting go of the key stops the machine
//: rather than leaving it driving into the lake.
// HOW LONG AN ASK STANDS. It lapses on purpose: a page that dies must not
// leave a machine driving for ever. But it has to outlive a slow frame by a
// wide margin, because a roam-kind program with no standing ask goes back to
// roaming -- with you aboard. At 0.6 s, renewed once a frame, a CI run at
// 1.4 fps lost the race and the rover drove 3.3 m off on its own. Three
// seconds, renewed at a third of it, survives two 700 ms frames and the
// round trip.
const RIDE_FOR_S = 3.0;
const RIDE_RENEW_S = RIDE_FOR_S / 3;
//: Where the eye sits above the middle of what you are riding. A rover's deck
//: is about a third of a metre up and you want to see over it, not along it.
const RIDE_EYE_M = 1.1;

// GOD MODE IS WHERE YOU START, and that is not what was asked for -- it is
// what the room can carry today. Being a machine by default was tried and
// measured: it takes six things away at once. Three are the machine's own
// life -- a rover cannot roam, rest in the sun or wake in the morning
// while somebody is sitting in it holding it still -- and three are the
// person's, because a rover has no hands: you cannot click what the side
// view marks, learn a technique by doing it, or carry ore along the chain.
// The hand, the bag, digging and throwing all belong to somebody who is
// not a machine.
//
// So you begin as the camera and get into something when you choose to,
// from the Settings tab. Everything the owner asked for is there; what is
// not there is it being the only way to be.
const riding = { name: null, asked: null, at: 0, seq: 0, sending: false, godMode: true,
                 powering: false, poweredAt: 0 };

function ridingRemembered() {
  try {
    // Only a remembered CHOICE puts you in something; the absence of a
    // memory leaves you the camera.
    const was = localStorage.getItem("banjo.riding");
    riding.godMode = localStorage.getItem("banjo.godMode") !== "0" || !was;
    if (was) riding.name = was;
  } catch { /* a private window has no memory, and that is not an error */ }
}

function rememberRiding() {
  try {
    localStorage.setItem("banjo.godMode", riding.godMode ? "1" : "0");
    if (riding.name) localStorage.setItem("banjo.riding", riding.name);
    else localStorage.removeItem("banjo.riding");
  } catch { /* nothing to do about it */ }
}

// Every machine in the room that can be inhabited, as {name, kind, program}.
// A machine with a program is driven through the program; one without is
// driven by its wheels, which is what the bench does too.
function whatCanBeRidden() {
  const machines = world.machines || {};
  return (machines.programs || [])
    .filter((p) => p && p.body)
    .map((p) => ({ name: String(p.body), kind: String(p.kind || "machine"), program: p }));
}

function whatIsRidden() {
  if (riding.godMode || !riding.name) return null;
  return whatCanBeRidden().find((m) => m.name === riding.name) || null;
}

// Riding is the ordinary way to be here, so something is chosen for you: the
// machine you rode last if it is still in the room, else the first one there
// is. A room with no machines at all leaves you as the camera, and says so.
// Only ever keeps a choice honest: what you were riding is gone from the
// room, so you are the camera again. Nothing is chosen FOR you -- getting
// into a machine is a thing you do.
function chooseSomethingToRide() {
  if (riding.godMode || !riding.name) return;
  if (!whatCanBeRidden().some((m) => m.name === riding.name)) {
    riding.name = null;
    riding.godMode = true;
  }
}

//: The keys that drive a machine. A keyup for one of these tells it to stop
//: there and then; every other key can wait for the next frame.
const RIDE_KEYS = new Set(["KeyW", "KeyA", "KeyS", "KeyD", "Space"]);

// Nothing is being asked for any more. Sent the moment the last driving key
// comes up, so a machine stops when you stop rather than when the page next
// gets round to it.
function letGoOfTheKeys() {
  const mine = whatIsRidden();
  if (!mine || !world.session) return;
  if ([...RIDE_KEYS].some((code) => keys.has(code))) return;   // another still held
  if (riding.asked === "") return;                             // already told
  riding.asked = "";
  riding.at = performance.now();
  act("behave", { program: mine.program.id, sender: "person", by_person: true,
                  seq: ++riding.seq, doing: "waiting", for_s: RIDE_FOR_S,
                  why: "you let go of the keys" })
    .then((said) => { if (said && said.program) mergeProgram(said.program); })
    // The next frame renews it; a lost release is not worth saying anything
    // about, and `asked` is put back so the loop sends it again.
    .catch(() => { riding.asked = null; });
}

// The keys, as the thing being ridden hears them.
function ridingKeys() {
  const shifted = keys.has("ShiftLeft") || keys.has("ShiftRight");
  return {
    forward: keys.has("KeyW"), back: keys.has("KeyS"),
    left: keys.has("KeyA"), right: keys.has("KeyD"),
    up: keys.has("Space") && !shifted, down: keys.has("Space") && shifted,
  };
}

// What one press means, in the order one key wins over another.
function ridingAsk(flies) {
  const held = ridingKeys();
  for (const [key, doing] of RIDE_ASKS) {
    if (!held[key]) continue;
    if (RIDE_FLIES_ONLY.has(doing) && !flies) continue;
    return doing;
  }
  return "";
}

// Tell the machine what the keys say. Sent when the ask CHANGES and again
// while it is held, because an ask lapses on its own -- a page that stops
// asking leaves a machine stopped rather than driving on without anybody.
// Getting into a machine turns it on. A rover you are sitting in that does
// not answer the keys is not a machine with its power off, it is a broken
// game -- and nothing else on the page would tell you which it was. Tried
// again no more than once a second, so a machine that refuses (a flat
// battery) says so through its own panel instead of being nagged.
async function powerWhatIsRidden(mine, now) {
  if (mine.program.power || riding.powering || now - riding.poweredAt < 1000) return;
  riding.powering = true;
  riding.poweredAt = now;
  try {
    const said = await api("/api/world/machine", { session: world.session, program: mine.program.id,
                                                  sender: "person", seq: ++riding.seq, power: true });
    // The page is told what a step CHANGED, and a machine block does not
    // come with every step -- so without taking the answer here the page
    // goes on believing the machine is off and turns it on again every
    // second for ever. Measured: fifteen of them before I looked.
    if (said && said.program) { mergeProgram(said.program); showRidingSettings(); }
  } catch { /* its panel says why; the next second tries again */ }
  finally { riding.powering = false; }
}

async function driveWhatIsRidden(now) {
  const mine = whatIsRidden();
  if (!mine || riding.sending) return;
  if (!mine.program.power) { powerWhatIsRidden(mine, now); return; }
  const flies = String(mine.program.kind || "") === "hover";
  // `asked` starts as null rather than "", so the FIRST thing a machine
  // you get into hears is that nobody is asking for anything -- it holds
  // still. Starting it at "" made the two equal, nothing was sent, and a
  // roaming rover drove off with you aboard before you touched a key.
  const want = ridingAsk(flies);
  // Renewed whether or not a key is down. An ask lapses on purpose, so a
  // machine you are sitting in with your hands off the keys has to go on
  // being told that nobody is asking for anything -- or it takes itself
  // back and starts roaming with you aboard. Measured: it turned away from
  // the lake on its own while I sat in it.
  const again = now - riding.at > RIDE_RENEW_S * 1000;
  if (want === riding.asked && !again) return;
  riding.sending = true;
  riding.asked = want;
  riding.at = now;
  try {
    // by_person, because it is: a person at the keys outranks the water
    // reflex, which is the owner's own rule ("your order wins"). A machine
    // you are riding goes where you steer it, into the lake if you insist.
    const said = await act("behave", { program: mine.program.id, sender: "person", by_person: true,
                                      seq: ++riding.seq, doing: want || "waiting", for_s: RIDE_FOR_S,
                                      why: want ? "you are driving it" : "you let go of the keys" });
    if (said && said.program) mergeProgram(said.program);
  } catch {
    // The room may have been rebuilt under it; the next frame asks again.
    riding.asked = null;
  } finally { riding.sending = false; }
}

// LETTING GO. Told to wait first: the ask now stands for three seconds, and
// one that outlives the person who gave it drives a machine nobody is in.
function letGoOfTheMachine() {
  const mine = whatIsRidden();
  if (mine && world.session) {
    riding.seq += 1;
    act("behave", { program: mine.program.id, sender: "person", by_person: true,
                    seq: riding.seq, doing: "waiting", for_s: RIDE_FOR_S,
                    why: "you got out of it" }).catch(() => { /* it stops when the ask lapses */ });
  }
  riding.godMode = true;
  riding.asked = null;
  rememberRiding();
  if (typeof showRidingSettings === "function") showRidingSettings();
}

// The eye goes where the machine is. Looking about is still the mouse's --
// you turn your head in the seat, and the keys turn the machine.
function rideTheCamera() {
  const mine = whatIsRidden();
  if (!mine) return false;
  const body = world.bodies && world.bodies.get(mine.name);
  if (!body || !body.mesh) return false;
  camera.position.copy(body.mesh.position);
  camera.position.y += RIDE_EYE_M;
  camera.quaternion.setFromEuler(new THREE.Euler(pitch, yaw, 0, "YXZ"));
  return true;
}

// ---------------------------------------------------------------------------
// WHAT IT SENSES, as lamps and swatches rather than sentences
// ---------------------------------------------------------------------------
//
// The owner, looking at the side panel: "we need to decide what is absolutely
// critical on the right nav and be far more visual about things, like show me
// what the rover can sense like if it can see ore in front of it. Use
// thumbnails and such instead of gobs of text."
//
// This is the machine's own senses drawn as what they are. Its water sensors
// are five lamps laid out as they sit on it -- three across the front, two
// behind -- so a lit one tells you WHERE, not just that. What is ahead is a
// swatch in the ground's own colour, the same colour the ground under it is
// painted, so ore reads as ore without a word. Its battery is a bar.
//
// All of it is read from what the page already has: the sensors ride on the
// program, and the beds come from the same `ground.runs` that `standingOn`
// walks, so nothing here costs a round trip.

const SENSE_AHEAD_M = 2.5;

function senseLamp(lit, title) {
  const dot = document.createElement("i");
  dot.className = lit ? "sense-lamp lit" : "sense-lamp";
  dot.title = title;
  return dot;
}

// The five water sensors, laid out as they sit on the machine: front row
// left-middle-right above the back row.
function sensorLamps(program, kind) {
  const grid = document.createElement("div");
  grid.className = "sense-grid";
  const of = (stops, side) => (program.sensors || []).find(
    (s) => (s.kind || "water") === kind && Math.sign(s.stops) === stops && Math.sign(s.side) === side);
  for (const [stops, side, where] of [[1, 1, "ahead on its left"], [1, 0, "straight ahead"],
                                      [1, -1, "ahead on its right"], [-1, 1, "behind, on its left"],
                                      [0, 0, ""], [-1, -1, "behind, on its right"]]) {
    if (!where) { grid.append(document.createElement("i")); continue; }
    const sensor = of(stops, side);
    grid.append(senseLamp(!!(sensor && sensor.sees), sensor ? `${sensorName(sensor)}: ${sensorReading(sensor)}` : `No ${kind} sensor ${where}`));
  }
  return grid;
}

// A patch of ground drawn in the colour the ground itself is drawn in.
function groundSwatch(at) {
  const swatch = document.createElement("i");
  swatch.className = "sense-swatch";
  const made = groundMadeOf(at);
  const kind = made ? RUN_NAMES.indexOf(made) : -1;
  const colour = kind >= 0 ? GROUND_COLOURS[kind] : null;
  if (colour) swatch.style.background = `#${colour.getHexString()}`;
  swatch.title = made || "off the map";
  return { swatch, made };
}

// A bar, 0 to 1, with what it is of written once.
function senseBar(share, words) {
  const wrap = document.createElement("div");
  wrap.className = "sense-bar";
  const fill = document.createElement("i");
  fill.style.width = `${Math.round(Math.max(0, Math.min(1, share)) * 100)}%`;
  const said = document.createElement("span");
  said.textContent = words;
  wrap.append(fill, said);
  return wrap;
}

// Everything the machine you are being can tell you, redrawn each time the
// room says something new.
function showWhatItSenses() {
  const box = $("settings-senses");
  if (!box) return;
  const mine = whatIsRidden();
  if (!mine) { box.replaceChildren(); box.hidden = true; return; }
  box.hidden = false;
  const p = mine.program;

  const rows = [];
  for(const kind of ["ground","water"]) {
    if(!(p.sensors || []).some(s=>(s.kind || "water")===kind)) continue;
    const row=document.createElement("div");row.className="sense-row";
    const word=document.createElement("span");word.className="sense-what";
    word.textContent=kind==="ground" ? "Drops / steps" : "Water";
    row.append(word,sensorLamps(p,kind));rows.push(row);
  }

  // What it is standing on, and what is a couple of metres in front of it.
  const body = world.bodies && world.bodies.get(mine.name);
  if (body && body.mesh) {
    const here = body.mesh.position;
    const way = new THREE.Vector3(0, 0, 1).applyQuaternion(body.mesh.quaternion);
    const ahead = [here.x + way.x * SENSE_AHEAD_M, here.y, here.z + way.z * SENSE_AHEAD_M];
    const row = document.createElement("div");
    row.className = "sense-row";
    const word = document.createElement("span");
    word.className = "sense-what";
    word.textContent = "Ground";
    const under = groundSwatch([here.x, here.y, here.z]);
    const front = groundSwatch(ahead);
    const said = document.createElement("span");
    said.className = "sense-said";
    said.textContent = front.made === under.made
      ? (under.made || "off the map")
      : `${under.made || "off the map"}, then ${front.made || "off the map"}`;
    row.append(word, under.swatch, front.swatch, said);
    rows.push(row);
  }

  if (typeof p.charge_share === "number") {
    const row = document.createElement("div");
    row.className = "sense-row";
    const word = document.createElement("span");
    word.className = "sense-what";
    word.textContent = "Battery";
    row.append(word, senseBar(p.charge_share, `${Math.round(p.charge_share * 100)}%`));
    rows.push(row);
  }

  box.replaceChildren(...rows);
}

// ---------------------------------------------------------------------------
// The Settings tab: what you are, and god mode
// ---------------------------------------------------------------------------
//
// Built here rather than written into world.html, so that adding a tab does
// not touch the page's inline blocks: their hashes are in the CSP, and
// editing one takes down every server already running until it restarts
// (docs, and the hard way).

function buildRidingSettings() {
  const strip = document.querySelector("#tabs > div[role=tablist]");
  const tabs = $("tabs");
  if (!strip || !tabs || $("tab-settings")) return;

  const tab = document.createElement("button");
  tab.type = "button";
  tab.id = "tab-settings";
  tab.setAttribute("role", "tab");
  tab.setAttribute("aria-controls", "pane-settings");
  tab.setAttribute("aria-selected", "false");
  tab.textContent = "Settings";
  strip.append(tab);

  const pane = document.createElement("div");
  pane.id = "pane-settings";
  pane.setAttribute("role", "tabpanel");
  pane.setAttribute("aria-labelledby", "tab-settings");
  pane.hidden = true;
  pane.innerHTML = "";

  const who = document.createElement("section");
  who.setAttribute("aria-label", "What you are");
  const title = document.createElement("h3");
  title.textContent = "What you are";
  const said = document.createElement("p");
  said.id = "settings-said";
  said.textContent = "Looking for something to be…";
  const list = document.createElement("ul");
  list.id = "settings-riders";
  const senses = document.createElement("div");
  senses.id = "settings-senses";
  senses.className = "senses";
  senses.hidden = true;
  who.append(title, said, senses, list);

  const god = document.createElement("section");
  god.setAttribute("aria-label", "God mode");
  const godTitle = document.createElement("h3");
  godTitle.textContent = "God mode";
  const godWhy = document.createElement("p");
  godWhy.className = "mp-hint";
  godWhy.textContent = "Leave the machine and float: Space rises, Shift+Space sinks, "
    + "and nothing in the room can stop you. For looking at the room rather than being in it.";
  const godButton = document.createElement("button");
  godButton.type = "button";
  godButton.id = "settings-god";
  godButton.setAttribute("aria-pressed", "false");
  godButton.textContent = "Fly";
  godButton.addEventListener("click", () => {
    godButton.blur();
    // Going up: let go properly, which tells the machine to wait. An ask
    // stands for three seconds now, and one that outlives the person who
    // gave it drives a machine nobody is in.
    if (!riding.godMode) { letGoOfTheMachine(); return; }
    riding.godMode = false;
    riding.asked = null;
    chooseSomethingToRide();
    rememberRiding();
    showRidingSettings();
  });
  god.append(godTitle, godWhy, godButton);

  pane.append(who, god);
  tabs.append(pane);
  TABS.push("settings");
  tab.addEventListener("click", (e) => { e.currentTarget.blur(); showTab("settings"); });
  showRidingSettings();
}

// What the tab says now: what you are, and what else you could be.
function showRidingSettings() {
  const said = $("settings-said"), list = $("settings-riders"), god = $("settings-god");
  if (!said || !list || !god) return;
  god.setAttribute("aria-pressed", String(!!riding.godMode));
  god.textContent = riding.godMode ? "Stop flying" : "Fly";

  const all = whatCanBeRidden();
  const mine = whatIsRidden();
  said.textContent = riding.godMode
    ? "Flying. Nothing in the room can stop you, and nothing in it is yours to drive."
    : mine
      ? `You are ${mine.name}. W A S D drive it`
        + (mine.kind === "hover" ? ", Space up, Shift+Space down." : ".")
      : all.length
        ? "Pick something to be."
        : "There is no machine in this room to be, so you are a camera above it.";

  showWhatItSenses();
  list.replaceChildren(...all.map((m) => {
    const li = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "quiet";
    button.dataset.rides = m.name;
    const now = !riding.godMode && mine && mine.name === m.name;
    button.setAttribute("aria-pressed", String(!!now));
    button.textContent = now ? `${m.name} — you` : m.name;
    button.addEventListener("click", () => {
      button.blur();
      riding.name = m.name;
      riding.godMode = false;
      riding.asked = null;
      rememberRiding();
      showRidingSettings();
    });
    li.append(button);
    return li;
  }));
}

let movementMode = localStorage.getItem("banjo.movement") || "gravity";
let verticalSpeed = 0, jumpHeld = false;
// Camera-controller approximation: 70 kg, 75 litres over the 1.6 m below
// the eye. Buoyancy and drag accelerate the controller; this is not a native
// avatar and applies no reaction to the river or carried objects.
const PLAYER_MASS_KG = 70, PLAYER_VOLUME_M3 = .075;
addEventListener("banjo-movement-mode", event => {
  movementMode = event.detail === "fly" ? "fly" : "gravity";
  verticalSpeed = 0; jumpHeld = false;
  // Return the player's controls from a ridden machine to their own feet.
  if (movementMode === "gravity") letGoOfTheMachine();
});
function walk(dt) {
  // RIDING IS THE ORDINARY WAY TO BE HERE. The keys go to the machine and
  // the eye goes where the machine is; everything below -- the free camera,
  // its ceiling of twelve metres, wading and being carried by a current --
  // is god mode, which is a way of LOOKING at the room rather than being in
  // it. A machine in the water is the machine's own problem and the engine's.
  if (rideTheCamera()) {
    world.inWater = null;
    document.body.classList.remove("head-under-water");
    driveWhatIsRidden(performance.now());
    return;
  }
  // How far the stick is pushed, which is also how fast: a gentle push is a
  // gentle walk. Keys stay what they were -- one key or two, always full pace.
  const pushed = stick.on ? Math.min(1, Math.hypot(stick.x, stick.y)) : 0;
  const running = ((keys.has("ShiftLeft") || keys.has("ShiftRight")) || stick.hard > STICK_RUN)
    && loadFraction() < 0.5;
  const water = inTheWater();
  world.inWater = water;
  document.body.classList.toggle("head-under-water", !!(water && water.head_under));
  const speed = (running && !water ? 5.6 : 2.4) * loadPace() * (water ? water.pace : 1) * dt;
  const forward = new THREE.Vector3(-Math.sin(yaw), 0, -Math.cos(yaw));
  const right = new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw));
  const move = new THREE.Vector3();
  if (keys.has("KeyW")) move.add(forward);
  if (keys.has("KeyS")) move.sub(forward);
  if (keys.has("KeyD")) move.add(right);
  if (keys.has("KeyA")) move.sub(right);
  // Up the screen is away from you, which is what a thumb means by it.
  if (stick.on) { move.addScaledVector(forward, -stick.y); move.addScaledVector(right, stick.x); }
  if (move.lengthSq() > 0) {
    // The keys are all or nothing and the stick is not, so the pace is how far
    // the stick is pushed. A key held is always a full walk -- and it has to be
    // a WALKING key: Shift is in `keys` too, and counting it made a feather
    // touch on the stick run.
    const keyed = keys.has("KeyW") || keys.has("KeyS") || keys.has("KeyA") || keys.has("KeyD");
    move.normalize().multiplyScalar(speed * (keyed ? 1 : Math.min(1, pushed || 1)));
  }
  // Up, and down with Shift held (interaction.js BINDINGS). E used to be up and
  // Q down: E is the hand's and Q the bag's now.
  const shifted = keys.has("ShiftLeft") || keys.has("ShiftRight");
  const jump = BINDINGS.up.keys.some((k) => keys.has(k));
  if (movementMode === "fly" && jump) move.y += shifted ? -speed : speed;
  // And where the water is going, as far as it has hold of them.
  if (water && water.carried > 0) { move.x += water.u * water.carried * dt; move.z += water.w * water.carried * dt; }
  if (movementMode === "gravity") {
    // Terrain controller: integrate gravity, rather than assigning a hover
    // height. This is a player's controller, not a native colliding rigid body.
    const supportAt = (x,z,feet) => ground.heights ? walkingSupport(x,z,feet) : 0;
    const before = camera.position.clone();
    const feet = before.y - BODY_BELOW_EYE_M;
    const floor = supportAt(before.x,before.z,feet);
    const grounded = feet <= floor+.025 && verticalSpeed <= 0;
    if (jump && !jumpHeld && grounded && !shifted) verticalSpeed = 4.5;
    jumpHeld = jump;
    const newFloor = supportAt(before.x+move.x,before.z+move.z,feet);
    const distance = Math.hypot(move.x,move.z);
    // Gentle hills use the continuous surface; half-metre steps and slopes
    // above 45 degrees require a jump or another route.
    if (newFloor > feet+.5 || (grounded && distance>1e-6 && newFloor-floor>distance+.02)) {
      move.x = 0; move.z = 0;
    }
    camera.position.add(move);
    const slices = Math.max(1,Math.ceil(Math.min(dt,.1)*120)), h = Math.min(dt,.1)/slices;
    for (let i=0;i<slices;i++) {
      const wet = inTheWater(), fraction = wet ? wet.under/BODY_BELOW_EYE_M : 0;
      const buoyancy = 9.81*1000*PLAYER_VOLUME_M3/PLAYER_MASS_KG*fraction;
      const stroke = wet && wet.under>.5 && jump ? (shifted ? -6 : 6) : 0;
      verticalSpeed += (-9.81+buoyancy+stroke-2.5*fraction*verticalSpeed)*h;
      camera.position.y += verticalSpeed*h;
      const under = supportAt(camera.position.x,camera.position.z,camera.position.y-BODY_BELOW_EYE_M);
      if (camera.position.y <= under+BODY_BELOW_EYE_M) {
        camera.position.y = under+BODY_BELOW_EYE_M; verticalSpeed = 0;
      }
    }
  } else { jumpHeld = false; verticalSpeed = 0; camera.position.add(move); }
  // Not below the floor, and not so high the room is a map. On uneven ground
  // the floor is the ground under you.
  // What they are standing on, which inside a working is its floor and not the
  // hill over it.
  const under = ground.heights
    ? standingOn(camera.position.x, camera.position.z, camera.position.y - BODY_BELOW_EYE_M + 0.2)
    : 0;
  if (movementMode === "fly") camera.position.y = clamp(camera.position.y, under + 0.25, under + 12);
  camera.position.x = clamp(camera.position.x, -28, 28);
  camera.position.z = clamp(camera.position.z, -28, 28);
  camera.quaternion.setFromEuler(new THREE.Euler(pitch, yaw, 0, "YXZ"));
}

function forwardVector() {
  const v = new THREE.Vector3(0, 0, -1);
  v.applyQuaternion(camera.quaternion);
  return v;
}

// WHERE THE CURSOR IS, as the camera sees it: -1 to 1 across and up the
// canvas. Null until the mouse has been over the view, and null while the
// pointer is locked -- a locked pointer has no place on the screen, and the
// middle of the view is the only thing it can mean.
let cursor = null;
function cursorAt(e) {
  const box = canvas.getBoundingClientRect();
  if (!box.width || !box.height) return null;
  return { x: ((e.clientX - box.left) / box.width) * 2 - 1,
           y: -((e.clientY - box.top) / box.height) * 2 + 1,
           px: e.clientX - box.left, py: e.clientY - box.top };
}
// The direction a pick is cast along: through the cursor where there is one,
// and along the camera's forward where there is not. Through the camera's
// own projection, so it is right at every zoom -- a narrower field of view
// means the same pixel points somewhere else, and reading it off the
// projection is the only way that stays true.
const throughCursor = new THREE.Raycaster();
function aimVector() {
  if (!cursor || document.pointerLockElement) return forwardVector();
  throughCursor.setFromCamera(new THREE.Vector2(cursor.x, cursor.y), camera);
  return throughCursor.ray.direction.clone();
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
  if (!wanted) { lastAction(`${held.name} has no long side to stand it on.`, "refused"); return; }
  held.turn.want = facingTurn().invert().multiply(wanted);
  lastAction(`Standing ${held.name} upright.`);
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
    lastAction("A blade is turned with the right mouse: its edge faces left, down, right or up.", "refused");
  } else if (!held.loose) {
    lastAction(`${held.bow ? held.bow.object : held.name} is attached to other things:`
      + ` it turns only the way they let it.`, "refused");
  } else {
    lastAction(`${held.name} is ${entry ? Math.round(entry.mass) : "too many"} kg — too heavy`
      + ` for one hand to hold up and turn (it holds up to about`
      + ` ${Math.floor(0.9 * 800 / 9.80665)} kg and can still move it). Press`
      + ` ${keyOf("talk")} and ask the room to turn it.`, "refused");
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
    const dir = aimVector();
    let found = await act("pick", { from: [from.x, from.y, from.z],
                                    dir: [dir.x, dir.y, dir.z], max_m: 40 });
    // Past the tool in your own hand: held ready it can be under the
    // crosshair, and where you are looking is the ground beyond it.
    for (let past = 0; past < 3 && found.hit && found.name && found.point_m && world.held
         && world.held.pick && world.held.pick.parts.includes(found.name); past++) {
      const p = found.point_m;
      found = await act("pick", { from: [p[0] + 0.05 * dir.x, p[1] + 0.05 * dir.y, p[2] + 0.05 * dir.z],
                                  dir: [dir.x, dir.y, dir.z], max_m: 40 });
    }
    world.aim = found.hit && found.name ? found : null;
    // Where the crosshair meets the ground, when it is the ground it meets:
    // that is where a spade goes in.
    world.groundAim = found.hit && !found.name ? found.point_m : null;
    if (!world.held) showLabel(world.aim);
  } catch { /* the next frame asks again */ } finally { aimBusy = false; }
}

// The name of what the crosshair is on, just under it, and nothing else (the
// owner: "when you mouse over something show the name of it, like 'Iron
// Kettle'"). What it is and what can be done with it are the side view's
// (showDetails). On the ground, what the ground is there.
function showLabel(found) {
  const box = $("label");
  const cross = $("crosshair");
  let name = "";
  if (found) {
    const part = tools.profileOf(found.name) || profileOf(found.name);
    const entry = world.bodies.get(found.name);
    name = titled(part ? part.object : found.name);
    cross.classList.toggle("on", !entry?.anchored || !!part);
  } else {
    cross.classList.toggle("on", false);
    if (world.groundAim && ground.grid) {
      const [x, , z] = world.groundAim;
      const water = waterAt(x, z);
      name = water && water.depth > 0.05 ? "Water" : titled(groundMadeOf(world.groundAim) || "the ground");
    }
  }
  box.hidden = !name;
  $("label-name").textContent = name;
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
  // E's choice (doChoice), done now or at the top of the next tick like the rest.
  if (typeof what === "function") what();
  else if (what === "pick") pickUp();
  else if (what === "drop") dropIt();
  else if (what === "put down") putDown();
  else if (what === "let fly") letFly();
  else if (what === "draw") startDraw();
  else if (what === "loose") loose();
  else if (what === "let down") letDown();
  else if (what === "settle") settleDown();
  else if (what === "swing") { tools.press(); tools.release(); }
  else if (what === "lever") tools.stop();
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

// What a thing on a joint moves along when it is hauled: the pin it turns on or
// the groove it slides in -- its own, or that of what it is fixed to. A winch's
// handle is fixed to its wheel, and the wheel turns on the pin.
function guideFor(name) {
  const seen = new Set([name]);
  let these = [name];
  while (these.length) {
    const next = [];
    for (const n of these) {
      for (const j of world.joints) {
        if (!j.attached || (j.a !== n && j.b !== n)) continue;
        if ((j.kind === "hinge" || j.kind === "slider") && j.axis) return j;
        const other = j.a === n ? j.b : j.a;
        if (j.kind === "fixing" && !seen.has(other)) { seen.add(other); next.push(other); }
      }
    }
    these = next;
  }
  return null;
}

// A product's own wheel: a pin free all the way round between two of its
// exact rigid parts -- the cart's wheelsets on their axles (rigid_assembly's
// bearings). It turns because the thing is pushed along, not because a hand
// works it. Every hinge a room gives a hand to work -- a gate, a winch's drum,
// a door -- is made of cells, or has stops.
function ownWheel(joint) {
  if (!joint || joint.kind !== "hinge") return false;
  const free = joint.lower_deg == null || joint.upper_deg == null
    || joint.upper_deg - joint.lower_deg >= 359;
  const a = world.bodies.get(joint.a), b = world.bodies.get(joint.b);
  return free && !!(a && a.fromPrecise) && !!(b && b.fromPrecise);
}

// The fixing that holds a thing fast: on the way from it, through what it is
// fixed to, to something anchored -- the one nearest the thing, so a gate's
// latch bar stays on its post when the gate is let go of. Null when nothing
// fixed to it is fixed to anything that does not move.
function latchHolding(name) {
  const via = new Map([[name, null]]);
  let these = [name];
  while (these.length) {
    const next = [];
    for (const n of these) {
      for (const j of world.joints) {
        if (!j.attached || j.kind !== "fixing" || (j.a !== n && j.b !== n)) continue;
        const other = j.a === n ? j.b : j.a;
        if (via.has(other)) continue;
        const first = via.get(n) || j;
        const entry = world.bodies.get(other);
        if (entry && entry.anchored) return first;
        via.set(other, first);
        next.push(other);
      }
    }
    these = next;
  }
  return null;
}

// Where the view meets what a joint lets a thing move along: the plane a pin
// turns it in, through its middle, or the line a groove slides it along. Null
// when the view runs along the plane or the groove, or meets it out of reach.
const HAUL_REACH_M = 6.0;
function alongGuide(guide, middle, from, dir) {
  const axis = new THREE.Vector3(...guide.axis).normalize();
  if (guide.kind === "hinge") {
    const facing = dir.dot(axis);
    if (Math.abs(facing) < 0.05) return null;
    const t = middle.clone().sub(from).dot(axis) / facing;
    return t > 0 && t < HAUL_REACH_M ? from.clone().addScaledVector(dir, t) : null;
  }
  // A groove: the point on its line nearest the view.
  const w = middle.clone().sub(from);
  const b = dir.dot(axis);
  if (1 - b * b < 1e-4) return null;
  const s = (b * dir.dot(w) - axis.dot(w)) / (1 - b * b);
  return Math.abs(s) < HAUL_REACH_M ? middle.clone().addScaledVector(axis, s) : null;
}

// Where the hand hauls a thing on a joint: its middle, moved by as much as the
// crosshair has moved over the plane it turns in or along the groove it slides
// in, from where it was taken hold of. Moving the crosshair round a winch's axle
// cranks it. At a fixed distance along the view instead, as it used to be, the
// hand drew a small loop beside the axle -- that point falls short of the rim
// below the axle -- and the wheel turned 0.1 degrees for two sweeps round it.
// With no pin or groove, or a view along its plane, at that distance as before.
function haulTarget() {
  const held = world.held;
  const dir = forwardVector();
  if (held.guide) {
    const now = alongGuide(held.guide.joint, held.guide.middle, camera.position, dir);
    if (now) {
      const p = held.guide.middle.clone().add(now.sub(held.guide.grabbed));
      return [p.x, p.y, p.z];
    }
  }
  const p = camera.position.clone().add(dir.multiplyScalar(held.distance));
  if (held.offset) p.add(held.offset);
  return [p.x, p.y, p.z];
}

// Let go of a latch by hand: whatever is held, or whatever is under the
// crosshair. This is how the bar comes off the gate.
async function unlatch() {
  const name = world.held ? world.held.name : world.aim && world.aim.name;
  if (!name) return;
  const latch = latchOn(name);
  if (!latch) {
    lastAction(`Nothing is latched to ${name}.`, "refused");
    return;
  }
  try {
    await act("unhinge", { joint: latch.id });
    lastAction(`Released the fixing between ${latch.a} and ${latch.b}.`);
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
  // On the ground beside a tool -- a pick lies flat and is 4 cm thick -- E
  // takes up the tool whose body passes nearest the crosshair's line (tools.js).
  if (!world.aim) {
    const near = !world.held && !world.acting ? tools.nearTool() : null;
    if (near) await tools.takeUp(near);
    return;
  }
  // An action has the hand while it runs (runAction).
  if (world.acting) { lastAction("Your hand is busy with an action.", "refused"); return; }
  const name = world.aim.name;
  const entry = world.bodies.get(name);
  // A part of something with a profile takes up the whole of it -- the bow,
  // not its grip, even though the grip is fixed in place. With Alt held the
  // hand takes exactly the part under the crosshair instead: the advanced
  // hold, which is how a bowstring can still be grabbed by itself.
  const profile = !(keys.has("AltLeft") || keys.has("AltRight")) && profileOf(name);
  if (profile) { await takeUpBow(profile); return; }
  // A part of a tool takes the tool up by its grip (tools.js).
  const tool = !(keys.has("AltLeft") || keys.has("AltRight")) && tools.profileOf(name);
  if (tool) { await tools.takeUp(tool); return; }
  if (entry?.anchored) {
    lastAction(`${name} is fixed in place: it is the room, not a prop.`, "refused");
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
      showHolding(true);
      remember(`took up the ${name} by its grip`);
      lastAction(`Took up ${name} by the grip, its edge facing ${STANCES[0].name}. Turn to`
        + ` swing it; right-click turns the edge.`);
      return;
    }
    // A loose thing a hand can lift goes into the hand (the owner, 2026-09-14:
    // "E on a loose thing: pick it up"; E again puts it down, Q puts it in the
    // bag), through the record, so what the hand holds is what the person has:
    // the server's hand grips it at its middle where it lies (inventory_room's
    // take_up). A thing the record does not keep -- a broken piece -- is taken
    // by the page's own grip below, as it always was; Alt+E takes that grip on
    // anything, the advanced hold.
    const alt = keys.has("AltLeft") || keys.has("AltRight");
    if (entry && !alt && throwable(entry, onAJoint(name))) {
      const took = await takeIntoHand(name);
      if (took === "held") lastAction(`Picked up ${name}, ${grams(entry.mass)}.`);
      if (took !== "not kept") return;
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
      showHolding(true);
      remember(`took hold of the ${entry.material || ""} ${name}`.replace(/\s+/g, " "));
      lastAction(`Took hold of ${name}, ${grams(entry.mass)}.`);
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
      // And what it moves along, when that is a pin or a groove (haulTarget):
      // from here the hand follows the crosshair over it.
      const joint = guideFor(name);
      const middle = entry.mesh.position.clone();
      const grabbed = joint && alongGuide(joint, middle, camera.position, forwardVector());
      if (grabbed) {
        world.held.guide = { joint, middle, grabbed };
        world.use.guide = joint.kind;
      }
    }
    // Taking hold of something that hangs on ropes AND carries a latch is
    // taking hold of a drawn thing. Where it is NOW is where it comes back to,
    // which is all the geometry the release needs to know -- no brace height,
    // no bow, no names.
    if (entry && latchOn(name) && ropedTo(name)) {
      world.drawn = { name, from: entry.mesh.position.clone(),
                      latch: latchOn(name).id };
    }
    showHolding(true);
    remember(`picked up the ${entry?.material || ""} ${name}`.replace(/\s+/g, " "));
    lastAction(`Took hold of ${name}.`);
    showUse();
  } catch (error) { say("bad", String(error.message || error)); }
}

async function dropIt(raw = false) {
  if (!world.held) return;
  if(world.held.recovery) {
    const program=programsNow().find(p=>p.id===world.held.recovery);
    if(program) await recoverRover(program,"release");
    return;
  }
  if (!raw && placementEligible()) { await placeHere(); return; }
  stopPlacing(false);
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
      lastAction(`Loosed. The limbs were holding ${stored.toFixed(1)} J.`);
      remember(`loosed ${name} with ${stored.toFixed(1)} J in the limbs`);
    }
  }
  world.drawn = null;
  world.held = null;
  showHolding(false);
  clearGuides();
  aimArc.hide();
  world.use = { mode: "none" };
  showUse();
  try {
    await act("release");
    // Dropped from the hand, a thing the record says the hand held is in the
    // world now.
    leftTheHand(name);
    remember(at ? `let go of ${name} at ${at.x.toFixed(2)}, ${at.y.toFixed(2)}, ${at.z.toFixed(2)} m`
                : `let go of ${name}`);
    lastAction(at ? `Let go of ${name} at ${at.y.toFixed(2)} m up.` : `Let go of ${name}.`);
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
                             reached: 0, bringing: null });
  showUse();
}

function cancelWindUp(said) {
  Object.assign(world.use, { mode: "ready", asked: 0 });
  lastAction(said || `Lowered ${world.use.name}.`, said ? "refused" : "did");
  showUse();
}

async function letFly() {
  const use = world.use;
  const entry = world.held && world.bodies.get(world.held.name);
  if (!entry || use.mode !== "preparing") return;
  // Grey means no. A throw leaves the hand only while the room can see it come
  // down where the crosshair is asking for; letting go on grey lowers it and
  // says why, and it stays in the hand. That is the whole of the aiming: move
  // the ring onto what you want and it goes green.
  if (!use.preview || !use.preview.onTarget) {
    cancelWindUp(use.preview && !use.preview.possible && use.preview.why
      ? use.preview.why
      : "Its first touch would not be where you are pointing, so it was not thrown."
        + " Move the ring onto what you want, or hold on longer.");
    return;
  }
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
async function putDown(placing = true) {
  // `placing` false lowers it onto what is under it and lets go there, without
  // going through a placement. Esc uses that: a placement can be refused for
  // want of a clear spot -- "no clear receiving point or ground in front" --
  // and a key that means "never mind" must not be something the room can turn
  // down and leave the thing still in your hand.
  if (placing && placementEligible()) { await placeHere(); return; }
  const held = world.held;
  if (!held) return;
  if (held.pick) {
    await tools.putDown(`You put down ${held.pick.object}.`);
    leftTheHand(held.name);
    return;
  }
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
  showHolding(false);
  clearGuides();
  aimArc.hide();
  world.use = { mode: "none" };
  showUse();
  try {
    await act("release");
    // Put down, a thing the record says the hand held is in the world now.
    leftTheHand(name);
    lastAction(`Put ${name} down.`);
    remember(`put ${name} down`);
  } catch (error) { say("bad", String(error.message || error)); }
}

// ---------------------------------------------------------------------------
// Placing: a see-through copy where it will go
// ---------------------------------------------------------------------------
//
// The owner, 2026-09-15: "E shows, E places" (docs/inventory-and-hands.md,
// section 5). With a thing in the hand, E shows a copy of it where the person
// is looking -- as it was made, square to the surface there, turned with the
// wheel -- and the engine says whether it fits (op place_check,
// LiveWorld::placement): what it would go into, what it would rest on, whether
// it may tip off, or, a tall thing on a slope, fall over. E again carries it
// there with the hand -- the same bounded hand, so what is in the way stops it
// -- and lets go. Esc, and the copy goes; the thing stays in the hand. Nothing
// in the room moves for the copy.
const ghostLook = (color) => new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.4,
                                                            depthWrite: false });
const GHOST_LOOK = { fits: ghostLook(0x9fe8b0), tips: ghostLook(0xf2c46b), no: ghostLook(0xf07a6a) };

// Which way a thing faces about the vertical: its own x axis, laid flat.
function headingOf(q) {
  const v = new THREE.Vector3(1, 0, 0).applyQuaternion(q);
  return Math.hypot(v.x, v.z) < 1e-6 ? 0 : Math.atan2(-v.z, v.x);
}

function placementEligible() {
  return world.held && (world.held.throwable || world.held.loose) && !world.held.blade
    && !world.held.pick && !world.held.bow && !workingJoint()
    && ["ready", "blocked", "carrying", "carrying-to"].includes(world.use.mode);
}

function startPlacing(automatic = false) {
  const held = world.held;
  const entry = held && world.bodies.get(held.name);
  if (!entry || world.placing) return;
  const ghost = entry.mesh.clone();
  ghost.traverse((part) => { if (part.isMesh) { part.material = GHOST_LOOK.fits; part.castShadow = false; } });
  ghost.renderOrder = 10;
  ghost.visible = false;
  scene.add(ghost);
  // What the wrist can turn is turned with the wheel; a thing carried in the
  // arms goes down the way it is held.
  world.placing = { name: held.name, ghost, yaw: headingOf(entry.mesh.quaternion), turnable: !!held.throwable,
                    answer: null, asked: 0, busy: false, carrying: null, automatic };
  world.placeDismissed = null;
  if (!automatic) lastAction(`Look where ${titled(held.name)} should go${held.throwable ? " and turn it with the wheel" : ""};`
             + ` ${keyOf("interact")} puts it there, Esc keeps it in your hand.`);
  showDetails(true);
}

function stopPlacing(said) {
  const p = world.placing;
  if (!p) return;
  world.placing = null;
  scene.remove(p.ghost);
  if (said) {
    world.placeDismissed = p.name;
    if (p.carrying) world.use.mode = p.carrying.was;
    lastAction(`Stopped placing: ${titled(p.name)} is still in your hand.`);
  }
  showDetails(true);
}

function placementRequest(p, expected = null) {
  return api("/api/world/placement", { session: world.session, name: p.name,
    person: whereIAm(), yaw_deg: p.yaw * 180 / Math.PI, ...(expected ? { expected } : {}) });
}

async function askWhere(p) {
  try {
    const answer = await placementRequest(p);
    if (world.placing !== p || p.carrying || p.confirming) return;
    p.answer = answer;
    drawGhost(p);
  } catch (error) {
    if (world.placing !== p) return;
    p.answer = { fits: false, why: error.message || String(error) };
    drawGhost(p);
  }
}

function drawGhost(p) {
  const a = p.answer;
  // Said at once, not a frame later: the side view is drawn from world.carry,
  // which updateGuides would only set on the next frame.
  world.carry = placingNote();
  if (!a || !a.at_m) { p.ghost.visible = false; showDetails(true); return; }
  const f = a.facing || a.q;
  p.ghost.position.set(a.at_m[0], a.at_m[1], a.at_m[2]);
  p.ghost.quaternion.set(f[1], f[2], f[3], f[0]);
  const look = !a.fits ? GHOST_LOOK.no
    : a.supported_corners < 3 || a.may_fall_over ? GHOST_LOOK.tips : GHOST_LOOK.fits;
  p.ghost.traverse((part) => { if (part.isMesh) part.material = look; });
  p.ghost.visible = true;
  showDetails(true);
}

// Said under what is held, in the side view: what the engine made of the spot.
function placingNote() {
  const a = world.placing && world.placing.answer;
  return a ? sentence(a.why) : "looking for where it can go";
}

function updatePlacing(now) {
  if (!world.held) world.placeDismissed = null;
  if (!world.placing && placementEligible() && !world.acting && !world.asking
      && !world.paused && world.placeDismissed !== world.held.name) startPlacing(true);
  const p = world.placing;
  if (!p) return;
  if (!world.held || world.held.name !== p.name || ["preparing", "throwing"].includes(world.use.mode)) {
    stopPlacing(false);
    return;
  }
  if (p.carrying || p.confirming || p.busy || world.paused || now - p.asked < 200) return;
  p.asked = now;
  p.busy = true;
  askWhere(p).finally(() => { p.busy = false; });
}

// E, with the copy shown: asked once more of the room as it is now -- something
// may have moved into the spot -- and then carried there.
async function placeHere() {
  if (!placementEligible() || world.paused || world.acting || world.asking) return;
  if (!world.placing) { startPlacing(); await askWhere(world.placing); }
  const p = world.placing;
  if (!p || p.carrying || p.confirming) return;
  const a = p.answer;
  if (!a?.fits || !a.target) {
    lastAction(a?.why || "Wait for a clear placement preview.", "refused");
    return;
  }
  p.confirming = true;
  try {
    const checked = await placementRequest(p, a.target);
    if (world.placing !== p || !world.held) return;
    p.answer = checked;
    drawGhost(p);
    if (!checked.fits) { lastAction(checked.why, "refused"); return; }
    if (!world.held.throwable) {
      const entry = world.bodies.get(p.name);
      await act("wield", { name: p.name, grip: entry.mesh.position.toArray() });
      if (world.placing !== p || !world.held) return;
      world.held.throwable = true;
      world.held.turn = startTurning(entry);
      world.use.grip = entry.mesh.position.clone();
      p.turnable = true;
    }
    carryTo(p, checked);
  } catch (error) { lastAction(String(error.message || error), "refused"); }
  finally { p.confirming = false; }
}

// Along a path a hand can take -- up, over, and down onto the spot -- at the
// pace of a careful hand. The hand holds a point of the thing (its grip, or its
// middle when carried), so the path is that point's, to where it will be when
// the thing stands on the spot.
function carryTo(p, target) {
  const held = world.held, entry = world.bodies.get(p.name);
  if (!held || !entry) return;
  const at = new THREE.Vector3(...target.at_m);
  const facing = new THREE.Quaternion(target.facing[1], target.facing[2], target.facing[3], target.facing[0]);
  const from = held.throwable && world.use.grip ? world.use.grip.clone() : entry.mesh.position.clone();
  const local = from.clone().sub(entry.mesh.position).applyQuaternion(entry.mesh.quaternion.clone().invert());
  const end = at.clone().add(local.applyQuaternion(facing));
  const over = Math.max(from.y, end.y + 0.2);
  const path = [from, new THREE.Vector3(from.x, over, from.z), new THREE.Vector3(end.x, end.y + 0.2, end.z), end];
  const lengths = path.slice(1).map((q, i) => q.distanceTo(path[i]));
  const total = lengths.reduce((s, l) => s + l, 0);
  p.carrying = { path, lengths, total, since: performance.now(), ms: 1000 * Math.max(0.4, total / 0.8),
                 at, facing: target.facing, arrived: 0, letting: false, was: world.use.mode };
  world.use.mode = "carrying-to";
  showUse();
}

// Which way the wrist is to turn it while it is carried there: the way the
// copy faced. Nothing for a thing carried in the arms.
function placingFacing() {
  const c = world.placing && world.placing.carrying;
  return c && world.placing.turnable ? c.facing : null;
}

// Where the hand wants the thing while it carries it to its spot -- and, once
// the path is done and the thing has got there, let go.
function placingHand(now) {
  const c = world.placing && world.placing.carrying;
  if (!c) return null;
  let along = Math.min(1, (now - c.since) / c.ms) * c.total;
  let k = 0;
  while (k < c.lengths.length - 1 && along > c.lengths[k]) { along -= c.lengths[k]; ++k; }
  const p = c.path[k].clone().lerp(c.path[k + 1], c.lengths[k] > 0 ? Math.min(1, along / c.lengths[k]) : 1);
  if (now - c.since >= c.ms) {
    if (!c.arrived) c.arrived = now;
    const entry = world.bodies.get(world.placing.name);
    const desired = new THREE.Quaternion(c.facing[1], c.facing[2], c.facing[3], c.facing[0]);
    const there = entry && entry.mesh.position.distanceTo(c.at) < 0.03
      && entry.mesh.quaternion.angleTo(desired) < 0.15;
    if ((there || now - c.arrived > 1500) && !c.letting) intend(letGoWhereItWent);
  }
  return [p.x, p.y, p.z];
}

async function letGoWhereItWent() {
  const p = world.placing, c = p && p.carrying;
  if (!c || c.letting) return;
  c.letting = true;
  const name = p.name;
  const entry = world.bodies.get(name);
  let check;
  try { check = await placementRequest(p, p.answer.target); }
  catch (error) { check = { fits: false, why: error.message || String(error) }; }
  if (world.placing !== p || !world.held) return;
  if (!check.fits) {
    p.carrying = null;
    world.use.mode = c.was;
    p.answer = check;
    drawGhost(p);
    lastAction(check.why, "refused");
    return;
  }
  const off = entry ? entry.mesh.position.distanceTo(c.at) : Infinity;
  const desired = new THREE.Quaternion(c.facing[1], c.facing[2], c.facing[3], c.facing[0]);
  if (off > 0.05 || (entry && entry.mesh.quaternion.angleTo(desired) > 0.15)) {
    // It did not get there: something is in the way. The hand keeps hold.
    p.carrying = null;
    world.use.mode = c.was;
    showUse();
    lastAction(`${titled(name)} would not go there: something is in the way`
               + ` (it stopped ${off.toFixed(2)} m short).`, "refused");
    return;
  }
  try {
    await act("release");
    stopPlacing(false);
    world.held = null;
    showHolding(false);
    clearGuides();
    aimArc.hide();
    world.use = { mode: "none" };
    showUse();
    leftTheHand(name);
    lastAction(`Put ${name} there.`);
    remember(`placed ${name} at ${c.at.x.toFixed(2)}, ${c.at.y.toFixed(2)}, ${c.at.z.toFixed(2)} m`);
  } catch (error) {
    p.carrying = null;
    world.use.mode = c.was;
    say("bad", String(error.message || error));
  }
}

// Where the hand wants a throwable thing this tick: brought in to the hand,
// held there, or wound back as far as has been asked. While the engine is
// making a stroke the hand is the engine's, and nothing is sent.
function throwingHand(now) {
  const placed = placingHand(now);
  if (placed) return placed;
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
  const placed = placingHand(now);
  if (placed) return placed;
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
  if(world.held?.recovery && hand) world.held.hand=hand;
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
    lastAction(`${use.name} would not go any further: something is in the way.`, "refused");
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
  // A thing of the record's that has left the hand -- thrown, or put down: the
  // record says so too.
  leftTheHand(name);
  showHolding(false);
  clearGuides();
  aimArc.hide();
  if (thrown) {
    const work = hand.let_go.work_j - (use.workBefore || 0);
    const kg = use.kg || 0;
    const text = `${name} left your hand at ${speed.toFixed(1)} m/s — the throw was`
      + ` ${work.toFixed(work < 10 ? 1 : 0)} J of your hand's work on`
      + ` ${kg < 10 ? kg.toFixed(2) : kg.toFixed(1)} kg.`;
    lastAction(text);
    remember(`threw ${name}: it left the hand at ${speed.toFixed(1)} m/s after`
      + ` ${work.toFixed(1)} J of the hand's work`);
    world.use = { mode: "thrown", name, kg, result: text, until: performance.now() + 4000 };
  } else {
    lastAction(`Put ${name} down.`);
    remember(`put ${name} down`);
    world.use = { mode: "none" };
  }
  showUse();
}

// Where the crosshair is asking for: the point on whatever it is on, or the
// ground where it meets the ground. Nothing when it is on the sky.
function askedFor() {
  if (world.aim && world.aim.point_m) return world.aim.point_m;
  return world.groundAim || null;
}

// How near the landing has to be to what is asked for to count as on target:
// half a metre close to, and a twentieth of the way out further off, because a
// metre at twenty paces is the same aim as half a metre at ten.
const ON_TARGET_M = 0.5, ON_TARGET_SHARE = 0.05;

// Whether the flight the engine foresees comes down where the crosshair is
// asking for. Hitting the very thing under the crosshair counts wherever on it
// the throw lands -- if you meant the crate and the crate is what it hits, you
// hit what you meant.
function landsWhereAsked(flight) {
  if (!flight || !flight.hit || !flight.hit_point_m) return false;
  const asked = askedFor();
  if (!asked) return false;                     // pointing at the sky
  if (world.aim && world.aim.name && flight.hit_name === world.aim.name) return true;
  const away = Math.hypot(flight.hit_point_m[0] - asked[0], flight.hit_point_m[1] - asked[1],
                          flight.hit_point_m[2] - asked[2]);
  const reach = Math.hypot(asked[0] - camera.position.x, asked[1] - camera.position.y,
                           asked[2] - camera.position.z);
  return away <= ON_TARGET_M + ON_TARGET_SHARE * reach;
}

// Where the throw would go if it were let go of now: the engine's own preview
// of this hand on this thing, a few times a second, redrawn as the view and the
// wind-up change. It moves nothing.
let previewBusy = false, previewAt = 0;
async function previewThrow() {
  const use = world.use;
  if (!world.held || !world.held.throwable
      || !["ready", "preparing", "blocked"].includes(use.mode)) {
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
    if (world.use !== use || !["ready", "preparing", "blocked"].includes(use.mode)) return;
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
    use.preview.onTarget = use.preview.possible && landsWhereAsked(seen.flight);
    // The stroke on screen is the one letFly sends, and it is only kept while
    // the arc is green, because green is the only state that throws.
    use.aimed = use.preview.onTarget ? { stroke, at: performance.now() } : null;
    if (use.preview.possible) {
      aimArc.show(seen.flight, use.preview.onTarget);
    } else {
      // No throw, so no flight to draw: the spot asked for, marked grey.
      const asked = askedFor();
      if (asked) aimArc.mark(asked); else aimArc.hide();
    }
    showUse();
  } catch { /* the next tick asks again */ } finally { previewBusy = false; }
}

// The hand's state changed: the side view's details say so now, and the
// crosshair's ring shows the meter (showDetails).
function showUse() {
  showDetails(true);
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
  // {body, label, steps}: in the side view's details when the crosshair is on it.
  world.actions = (spec && spec.actions) || [];
  // The finish the Workshop gave a thing, carried into the room with it
  // (fracture_lab.normalise_skins): its colour and how polished it is, and
  // nothing else -- never a shape, and never anything the engine reads.
  world.skins = new Map(((spec && spec.skins) || []).map((s) => [String(s.body), s]));
  rememberOutlines(spec);
  world.profiles = ((spec && spec.interactions) || [])
    .filter((p) => p.template === "draw-and-release");
  // And the tools that work the ground (swing-and-lever), which tools.js holds.
  world.tools = ((spec && spec.interactions) || [])
    .filter((p) => p.template === "swing-and-lever");
}

// Tools: taken up by the grip their point was given with, and used the same
// way whatever they are -- the server says what the tool does where the ring
// is and does it (tool_use.py), each stroke the engine's; tools.js holds the
// tool ready, draws the ring and sends the click.
const tools = makeTools({ world, act, api, say, remember, showUse, camera, carryGround, scene,
                          whereIAm, lastAction, takeIntoHand, showHolding });

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
  lastAction(text, "refused");
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
  showHolding(true);
  remember(`took up ${profile.object} by its string`);
  lastAction(`Took up ${profile.object}` + (state.arrowReady ? ", an arrow on the string."
                                                              : ": there is no arrow on the string."));
  showUse();
}

async function releaseBow(text) {
  world.held = null;
  world.use = { mode: "none" };
  showHolding(false);
  aimArc.hide();
  showUse();
  try { await act("release"); } catch (error) { say("bad", String(error.message || error)); }
  if (text) lastAction(text);
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
  showHolding(false);
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
        lastAction(use.result);
        remember(`the arrow left ${use.profile.object} at ${use.left.toFixed(1)} m/s`);
      } else if (use.arrowReady) {
        use.result = "The arrow never came clear of the string.";
        lastAction(use.result, "refused");
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
  jets: new Map(),        // gas region name -> the nozzle plume drawn for it
  jetsSeen: new Set(),    // and every one that has drawn at any point
  burning: new Set(),     // what was burning at the last reply, to say when it changes
  melting: new Set(),     // what was melting fast at the last reply, likewise
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
      if (entry && entry.mesh.material === own)
        entry.mesh.material = lookFor(name, entry.material, entry.mesh.userData.shaded);
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
    mine = dressedClone(lookFor(name, entry.material, entry.mesh.userData.shaded));
    entry.mesh.material = mine;
    heat.glowing.set(name, mine);
  }
  mine.color.copy(lookFor(name, entry.material).color)
    .lerp(CHARCOAL, clamp(0.85 * charred, 0, 0.85));
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
  // Thicker when there is more of it in the same room. A cylinder filling with
  // steam should LOOK like it is filling, and pressure over temperature is
  // what density is, so this is the gas's own number and not a mood.
  const density = clamp((region.p_pa / 101325) * (293 / Math.max(region.t_k, 1)), 0, 6);
  column.material.opacity = clamp(0.14 + 0.2 * density, 0.14, 0.75);
}

// A nozzle's jet, drawn as cells that leave.
//
// The owner, 2026-09-28: "steam within a container could also be represented
// with transparentish voxels that have an outward pushing motion". This is
// that, at the one place the engine knows gas is moving: out of a vent. Each
// cell marches down the vent axis and starts again at the throat, and it goes
// further and there are more of them the harder the nozzle is pushing.
//
// It is a PICTURE of the thrust the engine reports, never a source of it --
// the same rule the flames follow. Take the drawing away and the rocket flies
// exactly as high.
const JET_CELLS = 8;
const JET_BOX = new THREE.BoxGeometry(1, 1, 1);
function nozzleJet(region) {
  const vessel = world.bodies.get(region.vessel);
  if (!vessel) return;
  let jet = heat.jets.get(region.name);
  if (!jet) {
    const group = new THREE.Group();
    const cells = [];
    for (let i = 0; i < JET_CELLS; ++i) {
      const cell = new THREE.Mesh(JET_BOX, new THREE.MeshStandardMaterial({
        color: GAS_HOT, transparent: true, opacity: 0.5, depthWrite: false,
        emissive: GAS_HOT, emissiveIntensity: 0.6, roughness: 0.4, metalness: 0 }));
      group.add(cell);
      cells.push(cell);
    }
    heatGroup.add(group);
    jet = { group, cells, reach: 0.5, width: 0.05, vessel: region.vessel,
            axis: new THREE.Vector3(0, -1, 0) };
    heat.jets.set(region.name, jet);
    heat.jetsSeen.add(region.name);
  }
  jet.vessel = region.vessel;
  // How far it throws and how wide, from the thrust and the throat. A newton
  // of push is not much of a plume; a kilonewton is a torch.
  jet.reach = clamp(0.25 + 0.6 * Math.cbrt(Math.max(region.thrust_n, 0)), 0.25, 6.0);
  jet.width = clamp(0.6 * Math.sqrt(Math.max(region.area_m2 || 0.0004, 0.0004)), 0.03, 0.4);
  const axis = new THREE.Vector3(...(region.vent_axis || [0, -1, 0]));
  if (axis.lengthSq() === 0) axis.set(0, -1, 0);
  jet.axis = axis.normalize();
  // From the vessel's own face, the way the gas goes.
  const p = vessel.mesh.position;
  const half = vessel.dims ? 0.5 * vessel.dims[1] : 0.1;
  jet.group.position.set(p.x + jet.axis.x * half, p.y + jet.axis.y * half,
                         p.z + jet.axis.z * half);
}

function dropJet(name) {
  const jet = heat.jets.get(name);
  if (!jet) return;
  for (const cell of jet.cells) cell.material.dispose();
  heatGroup.remove(jet.group);
  heat.jets.delete(name);
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
  // Melting, said once when something starts melting fast -- heated, not the
  // room's slow warmth, which melts ice by a fraction of a gram a second.
  const melting = new Set();
  for (const b of block.bodies) {
    const was = heat.melting.has(b.name);
    if (b.melt_g_s > (was ? 0.5 : 2)) melting.add(b.name);
  }
  for (const b of block.bodies) {
    if (!melting.has(b.name) || heat.melting.has(b.name)) continue;
    say("world", `${b.name} is melting: ${Number(b.melt_g_s).toFixed(1)} g of water a second runs off it,`
      + ` and it stays at ${Math.round(b.t_k)} K until the ice is gone.`);
    remember(`${b.name} started melting`);
  }
  heat.melting = melting;
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
    // Ice's law changes nothing about its strength: only what melted is gone.
    const melts = s.gone === "melted";
    let text = melts ? "" : ` · ${Math.round(100 * Math.min(s.tension, s.shear))}% strength left`;
    if (s.char_mm > 0) text += `, ${s.char_mm.toFixed(1)} mm char`;
    if (s.burned_mm >= 0.05) text += `${melts ? " ·" : ","} ${s.burned_mm.toFixed(1)} mm ${s.gone || "burned"}`;
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
    if (b.melt_g_s > 0) text += ` · melting ${Number(b.melt_g_s).toFixed(2)} g/s`;
    if (b.melted_kg > 0) text += ` · ${Number(b.melted_kg).toFixed(2)} kg melted`;
    text += strengthOf(strength.get(b.name));
    text += staticsOf(b.name);
    listed.add(b.name);
    row(b.name, text);
  }
  // Whatever has burned or melted away entirely, and what was left of it.
  for (const gone of ((heat.strength && heat.strength.burned_away) || []).slice(-4))
    row(gone.name, gone.gone === "melted"
      ? `melted away at ${Math.round(gone.t)} s`
      : `burned away at ${Math.round(gone.t)} s · ${Number(gone.residue_kg).toFixed(2)} kg of ash left with it`);
  // Where the meltwater off ice has gone.
  if (block.meltwater)
    row("meltwater", `${Number(block.meltwater.into_water_kg).toFixed(2)} kg into the water`
      + ` · ${Number(block.meltwater.ran_off_kg).toFixed(2)} kg ran off across the floor`);
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
  const jetting = new Set();
  for (const r of block.regions) {
    regions.add(r.name);
    if (r.piston) gasColumn(r);
    // A jet only while something is actually leaving. A sealed region under
    // any pressure at all draws nothing, which is the point: the plume is the
    // gas going, not the gas being squeezed.
    if (r.vessel && Number(r.thrust_n) > 0) { jetting.add(r.name); nozzleJet(r); }
  }
  for (const [name, column] of heat.columns) {
    if (regions.has(name)) continue;
    heatGroup.remove(column);
    column.material.dispose();
    heat.columns.delete(name);
  }
  for (const name of [...heat.jets.keys()]) if (!jetting.has(name)) dropJet(name);
  narrateHeat(block);
  showHeat(block);
}

// Every frame: each flame sits on its body and flickers. The body's pose is
// the engine's; the flicker is only drawing.
function animateHeat(now) {
  const t = now / 1000;
  // Every jet cell walks from the throat to the end of its reach and starts
  // again, spread out so they leave one after another. They shrink and thin as
  // they go, which is what a jet does as it spreads into the room.
  for (const [, jet] of heat.jets) {
    // On its vessel every frame, not once a reply: a rocket under thrust moves
    // a long way between replies, and a plume left behind reads as a mistake.
    const vessel = world.bodies.get(jet.vessel);
    if (vessel) {
      const p = vessel.mesh.position;
      const half = vessel.dims ? 0.5 * vessel.dims[1] : 0.1;
      jet.group.position.set(p.x + jet.axis.x * half, p.y + jet.axis.y * half,
                             p.z + jet.axis.z * half);
    }
    for (let i = 0; i < jet.cells.length; ++i) {
      const along = ((t * 2.4) + i / jet.cells.length) % 1;
      const cell = jet.cells[i];
      cell.position.set(jet.axis.x * along * jet.reach, jet.axis.y * along * jet.reach,
                        jet.axis.z * along * jet.reach);
      const spread = jet.width * (1 + 2.2 * along);
      cell.scale.set(spread, spread, spread);
      cell.material.opacity = 0.55 * (1 - along) * (1 - along);
    }
  }
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
      ? { name: found.name || (ground.grid ? "the ground" : "the floor"), y: from - found.distance_m }
      : { name: "nothing below", y: 0, empty: true };
  } catch { /* keep the last answer */ } finally { dropBusy = false; }
}

function updateGuides() {
  if (!world.held) { world.carry = null; return; }
  // Placing: the see-through copy says where it goes, and the side view what
  // the engine made of the spot -- not the drop straight down from the hand.
  if (world.placing) {
    guides.visible = false;
    landing.visible = false;
    world.carry = placingNote();
    return;
  }
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

  // Said in the side view's details, under what is held.
  world.carry = `${dropOnto.empty ? "over nothing" : `over ${dropOnto.name}`},`
    + ` ${Math.max(0, bottom - dropOnto.y).toFixed(2)} m up · at ${at.x.toFixed(2)}, ${at.y.toFixed(2)},`
    + ` ${at.z.toFixed(2)} m`;
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

function updateWatchedCharacter(view) {
  watchedView = view;
  let panel = $("watch-character");
  if (!panel) {
    panel = document.createElement("section"); panel.id = "watch-character";
    panel.innerHTML = '<h2 id="watch-name"></h2><p id="watch-status" role="status"></p><p id="watch-progress"></p><p id="watch-tech"></p><ol id="watch-history"></ol>';
    const back = document.createElement("a"); back.textContent = "Return to my character";
    back.id = "watch-return"; back.href = `/world?world=${worldId}&scene=new-game`;
    panel.append(back); $("panel").querySelector("header").after(panel);
    document.body.classList.add("watching-character");
    $("ask-text").disabled = true;
    $("ask-send").disabled = true;
    $("ask-text").placeholder = "Watching a character. Return to your character to interact.";
  }
  const character = view.character, pose = character.pose;
  if (pose?.eyes_m) {
    camera.position.set(...pose.eyes_m);
    const f = pose.look_direction || pose.facing || [0, 0, -1];
    yaw = Math.atan2(-f[0], -f[2]); pitch = Math.asin(clamp(f[1], -1, 1));
    camera.quaternion.setFromEuler(new THREE.Euler(pitch, yaw, 0, "YXZ"));
  }
  $("watch-name").textContent = `Watching ${character.name}`;
  $("watch-status").textContent = `${character.mode === "openai" ? "AI" : "Reference bot"} · ${character.status} · ${character.message}`;
  $("watch-progress").textContent = `${view.goals.goals.filter((g) => g.complete).length} / ${view.goals.goals.length} goals · ${view.goals.title} · ${view.goals.balance_j} J · ${character.decisions} / ${character.decision_budget} decisions`;
  const learned = view.skills.filter((s) => s.known);
  $("watch-tech").textContent = `Its tech tree: ${learned.length} / ${view.skills.length} techniques known${learned.length ? " · " + learned.map((s) => s.name).join(", ") : ""}`;
  $("watch-history").replaceChildren(...character.history.slice(-5).map((entry) => {
    const li = document.createElement("li");
    li.textContent = `${entry.action.replaceAll("_", " ")} · ${entry.result}${entry.error ? " · " + entry.error : ""}`;
    return li;
  }));
  $("panel-state").textContent = `Watching ${character.name} · ${character.status}`;
  world.inventory = view.state.inventory || null;
  if (view.state.notebook) showNotebook(view.state.notebook, false);
  showInventory();
}

function showBatchWatch(program, routine) {
  let button = $("mp-watch-batch");
  if (!button) {
    button = document.createElement("button"); button.type = "button";
    button.id = "mp-watch-batch"; button.textContent = "Watch next batch";
    $("mp-routine").after(button);
    button.addEventListener("click", async () => {
      const selected = shownControl();
      if (!selected || machinePanel.of !== "program") return;
      button.disabled = true;
      try {
        const answer = await api("/api/world/watch-machine", {
          session: world.session, machine: selected.name, person: whereIAm() });
        machinePanel.said = answer.said; machinePanel.stale = false;
      } catch (error) {
        machinePanel.said = error.message; machinePanel.stale = true;
      } finally {
        button.disabled = false; showMachinePanel();
      }
    });
  }
  button.hidden = !worldId || !!watchedId || routine?.kind !== "process";
}

async function tickWatchedCharacter() {
  if (document.hidden || world.busy || !world.session || world.opening || performance.now() - watchedAt < 250) return;
  world.busy = true; wants = null; watchedAt = performance.now();
  try {
    const view = await api("/api/world/ai", { action:"watch", id:watchedId });
    if (view.state.session !== world.session) {
      world.busy = false;
      await open();
      return;
    }
    const state = view.state;
    draw(state); showPlayers(state.players);
    followMachines(state.machines, state.t); followBrains(state.brains); followGoods(state.goods); followPorts(state.ports);
    followVessels(state.vessels); drawStrength(state.mechanics); drawHeat(state.heat);
    if (state.sun) lightFromSun(state.sun);
    if (state.joints) drawJoints(state.joints);
    world.clock = state.t;
    $("room-clock").textContent = `The room's clock: ${Number(state.t).toFixed(1)} s · watching`;
    updateWatchedCharacter(view);
  } catch (error) {
    $("panel-state").textContent = `Watching paused: ${error.message || error}`;
    watchedAt = performance.now() + 750;
  } finally { world.busy = false; }
}

async function tick() {
  if (watchedId) { await tickWatchedCharacter(); return; }
  if (document.hidden) { world.lastTick = 0; return; }
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
      if (typeof what === "function") await what();
      else if (what === "pick") await pickUp();
      else if (what === "drop") await dropIt();
      else if (what === "put down") await putDown();
      else if (what === "let fly") await letFly();
      else if (what === "draw") await startDraw();
      else if (what === "loose") await loose();
      else if (what === "let down") await letDown();
      else if (what === "settle") await settleDown();
      else if (what === "swing") { tools.press(); tools.release(); }
      else if (what === "lever") tools.stop();
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
      if (hand) hand_q = placingFacing() || wristWish(elapsed);
    } else if (world.held && world.held.pick) {
      // A tool: held ready by the page, with the ring following the crosshair;
      // while the server uses it, nothing is sent -- the hand is the engine's
      // stroke, and a step carrying the ready pose would cancel the swing
      // (tools.js).
      tools.followAim();
      ({ hand, hand_q } = tools.hand());
    } else if (world.held && world.held.bow) {
      // A bow's string: held where the hand took it, or drawn and let down by
      // the engine's own stroke. Nothing is sent; sending would take it back.
    } else if (world.held && world.held.loose) {
      hand = carriedHand(now);
    } else if (world.held) {
      hand = haulTarget();
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
    // Where the person stands, for the machines' senses: a machine told to
    // come to them, or asked what to do with someone close, reads it.
    if (worldId || (world.machines && world.machines.programs && world.machines.programs.length))
      ask.person = whereIAm();
    let state = await act("step", ask);
    if (worldId) showPlayers(state.players);
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

    // Anything loose underfoot comes with you, whatever the hand is holding:
    // the engine leaves the held thing where it is, and stopping the sweep
    // while you carry something meant that picking up one piece switched off
    // the collecting of all the others (the owner, 2026-09-22). Done after the
    // step so it acts on where things have just landed, and before draw so the
    // pieces it takes are moved into the fade rather than deleted outright.
    if (debrisUnderfoot()) {
      const swept = await sweep();
      if (swept.collected && swept.collected.length) tellLater();
    }
    // A thing that is no longer in the world cannot be in your hand. Burned
    // away, swept up by somebody else, taken by the room: whatever became of
    // it, holding its name leaves every key working on nothing, and the panel
    // describing a thing that is not there.
    if (world.held && !world.bodies.has(world.held.name) && !world.acting) forgetHold();

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
      const cost = breakCost(state.cost);
      if (state.outcome === "broke") {
        say("world", `${how}${bars}. It broke into ${state.pieces} pieces.${cost}`);
        remember(`${name} broke into ${state.pieces} pieces`);
      } else if (state.outcome === "dented") {
        say("world", `${how}${bars}. It held together and came out a different shape.${cost}`);
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
    tools.follow(state);
    previewShot();
    followMachines(state.machines, state.t);
    followBrains(state.brains);
    followGoods(state.goods);
    followPorts(state.ports);
    followVessels(state.vessels);
    // A sun with a day moves with every step the engine takes.
    if (state.sun) lightFromSun(state.sun);
    drawRopes();
    followJoints();
    // Strength before heat, so the panel drawHeat fills in says both.
    drawStrength(state.mechanics);
    drawHeat(state.heat);
    narrateCuts(state.cuts, say, remember);
    if (state.terrain) drawTerrain(state.terrain);
    if (state.terrain_changed) patchTerrain(state.terrain_changed);
    // What has been seen of the room, which grows as machines get about it.
    if (state.sight) showSeen(state.sight);
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
    expedition.update(state.gameplay);
    const day = dayWords(world.sun);
    $("room-clock").textContent = `The room's clock: ${state.t.toFixed(1)} s · ${steps} steps a frame`
      + (day ? ` · ${day} (a day is ${Math.round(world.sun.day_s)} s)` : "");
    $("panel-state").textContent = world.held ? `Holding ${heldName()}.` : "Live.";
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
        // Another collaborator can install or author a change that reopens
        // this named world's native session. Join its new session rather than
        // leaving this page stopped with no reset control.
        if (worldId && !error.transient &&
            /no longer open|has closed|room is not open|no longer has the room/i.test(why)) {
          world.session = null;
          world.lastTick = 0;
          $("panel-state").textContent = "Rejoining the shared world…";
          setTimeout(() => { if (!world.session && !world.opening) open(); }, 300);
          return;
        }
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
    lastAction(`The nock let go ${(back * 1000).toFixed(0)} mm from brace.`
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
  advanceGlides(now);
  if (!watchedId) {
    lookFromKeys(dt);
    lookFromCursor(dt);
    walk(dt);
    payOutCable();
    turnFromKeys(dt);
    updateGuides();
    updatePlacing(now);
  }
  fadePieces(now);
  animateHeat(now);
  animateWater(now);
  stepFoam(dt);
  workbench.advance(now);
  followSun();
  // How dark it is where the eye is: under a hill, the daylight is not there,
  // and the lamps nearest the eye are the ones that light it.
  daylightUnderCover(camera.position);
  aimLamps();
  skyEnvironment();
  if (ground.facesStale) buildFaces();
  drawPickedOutline();
  animateReveal(now);
  resourceVisuals.advance(now);
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
    ghost = dressedClone(material);
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
  const swapped = [];
  if (inTheWay) {
    swapped.push([inTheWay.mesh, inTheWay.mesh.material]);
    inTheWay.mesh.material = ghostOf(inTheWay.mesh.material);
  }
  const r = revealing;
  // Swap only during rendering, restoring even if rendering fails. The skin
  // and the held-item ghost keep their own materials and lifetimes.
  if (r && r.amount > 0) {
    for (const {mesh,skin} of r.sources || (r.skin ? [{mesh:r.mesh,skin:r.skin}] : [])) {
      const own=mesh.material;swapped.push([mesh,own]);
      skin.color.copy(own.color);
      if (own.emissive) {skin.emissive.copy(own.emissive);skin.emissiveIntensity=own.emissiveIntensity;}
      skin.opacity=own.opacity*(1-.86*r.amount);mesh.material=skin;
    }
  }
  try { renderer.render(scene, camera); }
  finally { for (const [mesh, material] of swapped.reverse()) mesh.material = material; }
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

// What a structure the chat declared was measured to do, under its answer
// (docs/building-from-language.md): each requirement with what it needs and
// what the room measured. Whether it is finished is the room's to say, not the
// chat's -- a board named "ramp" is not a ski jump.
function sayChecked(turn, checked) {
  for (const c of checked) {
    const box = document.createElement("div");
    box.className = `checked ${c.passed ? "passed" : "failed"}`;
    const head = document.createElement("p");
    head.className = "checked-head";
    head.textContent = `${c.construction}: ${c.passed ? "does what it was declared to do" : "not finished"}`;
    const list = document.createElement("ul");
    for (const r of c.results || []) {
      const row = document.createElement("li");
      row.className = r.passed ? "ok" : "no";
      row.textContent = `${r.passed ? "✓" : "✗"} ${r.requirement}: ${r.measured} (needs ${r.required})`;
      list.append(row);
    }
    box.append(head, list);
    turn.append(box);
  }
  $("chat").scrollTop = $("chat").scrollHeight;
}

// What the chat worked on the room once its change was in it: held back until
// then, because before it the running room did not have the change.
function sayThen(turn, then) {
  const line = document.createElement("p");
  line.className = "did";
  line.textContent = "then, on the room with the change in it: " + then.map((t) =>
    t.error ? `${t.name} could not be done (${t.error})` : `${t.name} done`).join(", ");
  turn.append(line);
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
                   eyes_m: [r(p.x), r(p.y), r(p.z)], facing: [r(level.x), 0, r(level.z)],
                   look_direction: f.toArray().map(r) };
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
    const turn = say("world", answer.reply || "(nothing to say)", answer.did);
    if (answer.then && answer.then.length) sayThen(turn, answer.then);
    if (answer.checked && answer.checked.length) sayChecked(turn, answer.checked);
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
  // What the person has in the rebuilt room: the bag's things set aside again,
  // and a thing that was in the hand back in the bag (inventory_room.after_open).
  if (answer.state && answer.state.inventory) world.inventory = answer.state.inventory;
  // A rebuilt room: its own profiles and set-ups, and nothing of the old one
  // in hand.
  rememberProfiles(answer.state && answer.state.spec);
  world.held = null;
  world.use = { mode: "none" };
  world.loosing = null;
  aimArc.hide();
  // Asked with something in hand ("turn this upright"), the new room has
  // nothing in the hand: the ring and the drop line go.
  showHolding(false);
  tools.forget();
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
    if (answer.state.sight) showSeen(answer.state.sight);
    if (answer.state.water) drawWater(answer.state.water);
  } else {
    clearGround();
  }
  // Carried into the changed room (`restored` "carried"), the engine's hand
  // still holds what it held when that came back as it was: taken over as a
  // reload or a restart takes it over (open). And, said plainly, what is not
  // as it was -- what the change touched, and what could not be carried.
  const restored = answer.state.restored;
  const carried = !!(restored && restored.tier === "carried");
  const holding = carried && answer.state.hand ? answer.state.hand.holding : "";
  if (holding && world.bodies.has(holding)) {
    adoptNativeHold(holding,answer.state);
  }
  if (carried && (restored.not_carried || []).length)
    say("world", `As the room has it now: ${restored.not_carried.join("; ")}.`);
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
// Shown in the side view's details when the crosshair is on the thing: E does
// the one marked, and Tab moves it on. Doing one asks the server to run the
// program on the room as it is:
// the hand's steps in the running room with the hand's own strength, which
// this page keeps running and draws, and a stand step as turn_object. No model
// is asked. A step that cannot be done stops the action, with why.
// WHAT A RUNG WOULD OPEN, by name. "It would let you make 1 thing you cannot
// make yet" tells nobody why they should want it; "It would let you make a
// copper mill" is the reason. The names come from the server (opens_named);
// would_open stays a list of ids, which is what it has always been.
function opensSays(rung, have) {
  const opens = (rung && rung.opens_named) || [];
  if (!opens.length) return "";
  // "make one-piece wooden pick" is not English. An article, unless the name
  // already carries one or is plural.
  const article = (name) => (/^(a |an |the )/i.test(name) || /s$/i.test(name) ? ""
                             : /^[aeiou]/i.test(name) ? "an " : "a ");
  const names = opens.map((o) => article(o.name) + o.name.toLowerCase());
  const said = names.length === 1 ? names[0]
    : names.slice(0, -1).join(", ") + " and " + names[names.length - 1];
  return `It ${have ? "lets" : "would let"} you make ${said}.`;
}

// A card over the world, for a moment. Not the conversation: the conversation
// is where the machines talk, and they talk far more than you learn.
let unlockedFor = null;
function unlocked(what, opens) {
  const box = $("unlocked");
  if (!box) return;
  $("unlocked-what").textContent = what;
  $("unlocked-opens").textContent = opens;
  box.hidden = false;
  clearTimeout(unlockedFor);
  unlockedFor = setTimeout(() => { box.hidden = true; }, 9000);
}

// The nearest rung, under what you are looking at. One line, because the
// whole ladder is still in Notes and the owner has said there are too many
// panes; clicking it opens that tab.
function showNextStep(book) {
  const line = $("next-step");
  if (!line) return;
  const step = (book.next || []).find((n) => n.within_reach);
  if (!step) { line.hidden = true; return; }
  nextRung = step.technique || null;
  const way = (step.earned_by || []).find((e) => !e.done) || (step.earned_by || [])[0];
  const opens = opensSays(step);
  line.replaceChildren();
  const b = document.createElement("b");
  b.textContent = `Next: ${step.name}.`;
  line.append(b, document.createTextNode(` ${way && way.says ? way.says : ""}${opens ? " " + opens : ""}`));
  line.hidden = false;
}

// IT IS THE TECH TREE, so it opens the tech tree. The owner, seeing the line:
// "why does it say 'Next: Burning Lime' is that the tech tree? if so link it
// to the tech tree." It used to open the Notes tab, which lists what you know
// -- near the right thing and not it. The Workshop's Skills tab is the tree,
// and ?technique= opens it on this rung with its path lit.
let nextRung = null;
$("next-step")?.addEventListener("click", () => {
  const url = new URL("/world", location.origin);
  url.searchParams.set("workshop", "1");
  url.searchParams.set("tab", "skills");
  if (nextRung) url.searchParams.set("technique", nextRung);
  location.href = url.toString();
});

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
  for (const t of book.techniques || []) {
    rows.push(["known", `You know ${t.name}.`]);
    // Said once, when it happens, OVER THE WORLD and not into the
    // conversation. It was said in the conversation, where the next thing a
    // smelter reported pushed it out of sight -- learning something and being
    // told nothing where you are looking is the same as not learning it.
    if (fresh && !notebookSeen.has(`t:${t.id}`)) {
      // "You can now smelting copper" is not English, and a technique's name
      // cannot be conjugated into one. And what it OPENS is read off the
      // technique and not off `next`: the moment it is learned it leaves that
      // list, which is exactly when somebody wants to know what it was for.
      unlocked(`Learned: ${t.name}`, opensSays(t, true) || "");
    }
    notebookSeen.add(`t:${t.id}`);
  }
  // What is one step away, and what it would open. Without this a person can
  // be one demonstration short of a capability and never know it exists.
  for (const step of book.next || []) {
    if (!step.within_reach) {
      rows.push(["later", `${step.name} needs ${step.first_learn.join(", ")} first.`]);
      continue;
    }
    const way = (step.earned_by || []).find((e) => !e.done) || (step.earned_by || [])[0];
    const opens = opensSays(step);
    rows.push(["next", `Next: ${step.name}. ${way ? way.says : ""}${opens ? " " + opens : ""}`]);
  }
  for (const b of book.blocked || []) {
    rows.push(["blocked", `Making ${b.name.toLowerCase()} yourself is blocked: ${b.because.join("; ")}.`]);
  }
  for (const n of book.not_modelled || []) rows.push(["noted", `Not modelled yet: ${n}.`]);
  showNextStep(book);
  $("notebook-list").replaceChildren(...rows.map(([kind, text]) => {
    const li = document.createElement("li");
    li.className = `nb-${kind}`;
    li.textContent = text;
    return li;
  }));
  // There is always a next rung, so the panel is not empty just because
  // nothing has been tried yet.
  $("notebook-empty").hidden = (book.designs || []).length > 0 || (book.next || []).length > 0;
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
  if (entry.shape === "box" && !jointed && !bladeFor(name) && !tools.profileOf(name)
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
  // On a pin or in a groove -- its own, or that of what it is fixed to, like a
  // winch's handle -- it is worked, not carried: turned or slid by the hand to
  // the joint's stops (server.py's turn and slide). For everything on a joint,
  // in every room, whoever made it: the stops are the joint's own.
  // Held fast by a latch -- fixed, through what it is fixed to, to something
  // that does not move -- it is let go of from here as with R.
  const latch = jointed && latchHolding(name);
  if (latch) out.push({ label: "Release the latch", ask: { latch: latch.id } });
  const joint = jointed && guideFor(name);
  // Not a product's own wheel: the cart's wheelsets turn because the cart is
  // pushed, and turned from here they would tip it over its axle (the owner,
  // 2026-09-21: take these off the cart).
  if (joint && joint.kind === "hinge" && !ownWheel(joint)) {
    // A wheel -- no stops, or stops a whole turn apart -- is all the way round
    // half a turn either way, so "all the way back" would be the same place.
    const wheel = joint.lower_deg == null || joint.upper_deg == null
      || joint.upper_deg - joint.lower_deg >= 359;
    out.push({ label: "Turn it all the way", ask: { builtin: "turn", stop: "all_the_way" } });
    out.push({ label: "Turn it half way", ask: { builtin: "turn", stop: "half_way" } });
    if (!wheel) {
      out.push({ label: "Turn it all the way back", ask: { builtin: "turn", stop: "all_the_way_back" } });
    }
    if (wheel || (joint.lower_deg < -1 && joint.upper_deg > 1)) {
      out.push({ label: "Turn it back to where it started", ask: { builtin: "turn", stop: "back_to_start" } });
    }
  } else if (joint && joint.kind === "slider") {
    out.push({ label: "Slide it all the way", ask: { builtin: "slide", stop: "all_the_way" } });
    out.push({ label: "Slide it half way", ask: { builtin: "slide", stop: "half_way" } });
    out.push({ label: "Slide it all the way back", ask: { builtin: "slide", stop: "all_the_way_back" } });
  }
  // One of its own that does what a built-in does -- "Open the gate", a turn to
  // its far stop -- takes the built-in's place on the menu.
  // And "Stand the plank upright", a stand step, takes "Stand it upright"'s.
  // And "Put the crate on the ground in front of me" -- taken up, carried to
  // in front of the person, put down -- takes "Put it on the ground in front of me"'s.
  const same = new Set(actionsFor(name).map((a) => {
    const steps = a.steps || [];
    const s = steps[0] || {};
    if (steps.length === 1 && (s.do === "turn" || s.do === "slide") && s.stop) return `${s.do}:${s.stop}`;
    if (steps.length === 1 && s.do === "stand")
      return s.stand === "lying" ? "lay_down:undefined" : "stand_upright:undefined";
    if (steps.length === 3 && s.do === "take_hold" && steps[1].do === "carry_to"
        && steps[1].to && steps[1].to.kind === "in_front" && steps[2].do === "put_down")
      return "put_on_ground:undefined";
    return null;
  }).filter(Boolean));
  return out.filter((builtin) => {
    const ask = builtin.ask || { builtin: builtin.key };
    return !own.has(builtin.label.toLowerCase()) && !same.has(`${ask.builtin}:${ask.stop}`);
  });
}

// The hand kept hold at the end of an action -- a winch turned all the way and
// held there, so its gate stays up. The page takes the hold over as if the
// person had taken hold of it where it now is: the crosshair hauls it on from
// here, and E, or a click, lets go.
function adoptHold(name) {
  const entry = world.bodies.get(name);
  if (!entry || world.held) return;
  const distance = clamp(entry.mesh.position.distanceTo(camera.position), 0.6, 4.0);
  const from = camera.position.clone().add(forwardVector().multiplyScalar(distance));
  world.held = { name, loose: false, distance, offset: entry.mesh.position.clone().sub(from) };
  world.use = { mode: "carrying", name, kg: entry.mass || 0, latched: !!latchOn(name), loose: false };
  const joint = guideFor(name);
  const middle = entry.mesh.position.clone();
  const grabbed = joint && alongGuide(joint, middle, camera.position, forwardVector());
  if (grabbed) {
    world.held.guide = { joint, middle, grabbed };
    world.use.guide = joint.kind;
  }
  showHolding(true);
  showUse();
}

function adoptNativeHold(name,state) {
  const rover=(state.machines?.programs || []).find(p=>p.kind==="roam" && p.body===name);
  if(rover && state.hand?.mode==="grip") {adoptRecovery(rover,state.hand);return;}
  const pinned=(state.joints || []).some(j=>j.attached!==false && (j.a===name || j.b===name));
  if(pinned) adoptHold(name);else adoptGrip(name,null);
}

// The hand on a thing on a joint -- hauled round its pin or along its groove,
// not carried, thrown, wielded or drawn.
function workingJoint() {
  const held = world.held;
  return !!(held && !held.loose && !held.throwable && !held.pick && !held.bow && !held.blade);
}

// Whether an action goes on from the hand's hold on a thing on a joint: one
// that begins with a turn or a slide (server.py run_action). Anything else
// needs the hand free.
function goesOnFromHold(name, action) {
  if (!action) return false;
  if (action.ask.builtin === "turn" || action.ask.builtin === "slide") return true;
  const own = action.ask.action != null ? actionsFor(name)[action.ask.action] : null;
  return !!(own && own.steps && own.steps[0] && ["turn", "slide"].includes(own.steps[0].do));
}

// The page lets go of its side of a hold while the server's hand works it --
// its hauling would take the hand back from the stroke -- and takes it back
// after (adoptHold). The engine's hand keeps hold throughout.
function setHoldAside() {
  world.held = null;
  showHolding(false);
  clearGuides();
  world.use = { mode: "none" };
  showUse();
}

// Its own actions first, then the built-in ones: one list, one number each.
function allActionsFor(name) {
  return actionsFor(name).map((action, i) => ({ label: action.label, ask: { action: i } }))
    .concat(builtinsFor(name).map((builtin) => ({ label: builtin.label,
                                                  ask: builtin.ask || { builtin: builtin.key } })));
}

async function runAction(name, index, primary = false) {
  const action = primary ? { label: primaryAction(name).label, ask: { primary: true } } : allActionsFor(name)[index];
  if (!action || world.asking || world.acting) return;
  if (action.ask.latch != null) {
    // The fixing that holds it fast is let go of, as R does.
    try {
      await act("unhinge", { joint: action.ask.latch });
      lastAction(`Released the latch holding ${name}.`);
      remember(`released the latch holding ${name}`);
      await refreshJoints();
    } catch (error) { say("bad", `${action.label}: ${error.message || error}`); }
    return;
  }
  world.acting = true;
  // Going on from a hold -- the winch kept turned -- the hand is the server's
  // for the action.
  const previousHold = world.held;
  const previousUse = world.use;
  const person = whereIAm();
  const placementTarget = world.placing?.answer?.target;
  stopPlacing(false);
  const aside = !!previousHold;
  if (aside) setHoldAside();
  // Said in the details while it runs, and what it came to after.
  world.doing = action.label;
  showDetails(true);
  try {
    // On the room this page has open: a page whose room was opened again
    // elsewhere is refused, and nothing is done in the room somebody else has.
    const answer = await api("/api/world/action", { session: world.session, object: name,
                                                     ...action.ask, person, placement_target: placementTarget });
    const done = (answer.done || []).join(", ");
    if (answer.refused) {
      lastAction(`${action.label}: ${answer.refused}` + (done ? ` (done first: ${done})` : ""), "refused");
    } else {
      lastAction(`${action.label}: ${done || "done"}.`);
    }
    if (answer.reopened) adoptRebuilt(answer);
    if (previousHold && !answer.holding) leftTheHand(previousHold.name);
    if (answer.holding && previousHold?.name === answer.holding) {
      world.held = previousHold;
      world.use = previousUse;
      showHolding(true);
      showUse();
    } else if (answer.holding) {
      adoptHold(answer.holding);
      lastAction(`You are holding ${answer.holding} there: move the crosshair to work it on,`
        + ` or ${keyOf("interact")} to let go; ${keyOf("next")} moves E on to its turns, from here.`);
    }
  } catch (error) {
    say("bad", `${action.label}: ${error.message || error}`);
    // Whatever the hand was doing, the page no longer holds its side of it.
    if (aside) { try { await act("release"); } catch (_) { /* the room says why */ } }
  } finally { world.acting = false; world.doing = null; showDetails(true); }
}

$("reset").addEventListener("click", () => open({ again: true }));

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
    lastAction("Point the crosshair at something first: the heat goes into whatever it is on.", "refused");
    return;
  }
  const region = heat.last && ((heat.last.regions || []).find((r) => r.piston === name)
                               || (!world.held && gasBehindGlass(name)));
  const target = region ? region.name : name;
  const power = region ? 800 : 10000;
  const seconds = region ? 30 : 60;
  try {
    await act("heat", { target, power_w: power, seconds });
    lastAction(`Heating ${target} at ${power / 1000} kW for ${seconds} s.`);
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
  // And a room opened by its link: the link stops naming it too.
  if (sceneLink() !== null && $("scene").value !== sceneLink()) {
    const url = new URL(location.href);
    url.searchParams.delete("scene");
    history.replaceState(history.state, "", url);
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
// The breaker's trigger. The engine decides whether anything happens: a chisel
// in the air breaks nothing, and it says so.
async function pullTheTrigger() {
  const breaker = breakerInHand();
  if (!breaker) { lastAction("Nothing in your hand breaks rock.", "refused"); return; }
  const answer = await act("breaker_switch", { breaker: breaker.id, on: !breaker.on });
  const now = (answer && answer.working) || null;
  if (now) {
    for (const b of (world.machines && world.machines.breakers) || [])
      if (b.id === now.id) Object.assign(b, now);
    lastAction(now.on ? `The breaker is running: ${Math.round(now.watts)} W.` : "You let the trigger go.");
  }
  showDetails();
}

function runLength(points) {
  let out = 0;
  for (let i = 1; i < points.length; ++i)
    out += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1],
                      points[i][2] - points[i - 1][2]);
  return out;
}

// Stringing a run: start it at a battery, walk it where you want it, make it off
// at a fitting. The run is where YOU walked, so the cable is as long as the way
// you took and the lamp is dimmer for every metre of it.
async function workTheCable() {
  const name = world.aim && world.aim.name;
  const store = name ? storeOn(name) : null;
  const fitting = name ? lampOn(name) : null;
  if (!world.laying) {
    if (!store) { lastAction("Start a run of cable at a battery.", "refused"); return; }
    const entry = world.bodies.get(name);
    const at = entry ? entry.mesh.position : camera.position;
    layCable([at.x, at.y, at.z], store.id);
    lastAction(`A run of cable started at ${titled(name)}. Walk it to the fitting.`);
    showDetails();
    return;
  }
  if (!fitting) {
    world.laying = null;
    lastAction("You put the drum down. Nothing was run.", "refused");
    showDetails();
    return;
  }
  const entry = world.bodies.get(name);
  const end = entry ? entry.mesh.position : camera.position;
  const points = world.laying.points.concat([[end.x, end.y, end.z]]);
  const answer = await act("cable", { store: world.laying.store, run_m: points, area_mm2: 4.0 });
  const run = answer && answer.ran;
  if (!run) { lastAction("The run would not go in.", "refused"); return; }
  const wired = await act("lamp_wire", { lamp: fitting.id, cable: run.id });
  world.laying = null;
  const lit = wired && wired.lit;
  // What it will draw is not known until the next step settles the run, so the
  // line says what was RUN, and the fitting's own line says what it is giving.
  lastAction(`${run.length_m.toFixed(1)} m of cable from the battery to ${titled(name)}: `
             + `${run.resistance_ohm.toFixed(3)} ohm.`);
  showDetails();
}

$("dig-it").addEventListener("click", async () => {
  if (!world.session) return;
  if (!ground.grid) {
    lastAction("This room's floor is flat concrete: there is nothing to dig. The valley has ground.", "refused");
    return;
  }
  const at = world.groundAim;
  if (!at) {
    lastAction("Point the crosshair at the ground first: the spade goes in where it is.", "refused");
    return;
  }
  try {
    const answer = await digAt(at[0], at[2]);
    const d = answer.dug || {};
    carryGround(answer.carried);
    lastAction(`${d.limited ? "Took what you could still carry: dug" : "Dug"} ${((d.sand_m3 || 0) + (d.soil_m3 || 0)).toFixed(2)} m³ (${grams(d.kg || 0)}) at`
      + ` [${at[0].toFixed(1)}, ${at[2].toFixed(1)}]: ${(d.sand_m3 || 0).toFixed(2)} of sand,`
      + ` ${(d.soil_m3 || 0).toFixed(2)} of soil; ${d.chunks_rebuilt} collider(s) rebuilt,`
      + ` ${d.bodies_woken} thing(s) woken. Carrying ${carriedSaid()}.`);
    remember(`dug a pit at [${at[0].toFixed(1)}, ${at[2].toFixed(1)}] and carried what came out`);
  } catch (error) {
    // Carrying all that can be carried is an answer, not a fault: said where a
    // refusal is said, like a crosshair that is not on the ground.
    const why = String(error.message || error);
    if (why.includes("is all you can carry")) lastAction(why[0].toUpperCase() + why.slice(1), "refused");
    else say("bad", why);
  }
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
    lastAction("This room's floor is flat concrete: there is no ground to heap on. The valley has ground.", "refused");
    return;
  }
  const at = world.groundAim;
  if (!at) {
    lastAction("Point the crosshair at the ground first: the heap goes where it is.", "refused");
    return;
  }
  const have = world.carriedGround || {};
  const sand = Number(have.sand_m3) || 0;
  const soil = Number(have.soil_m3) || 0;
  if (sand + soil <= 1e-6) {
    lastAction("You are carrying no sand or soil. Dig here first: what comes out is carried.", "refused");
    return;
  }
  const share = Math.min(1, HEAP_M3 / (sand + soil));
  try {
    const answer = await heapAt(at[0], at[2], sand * share, soil * share);
    const h = answer.heaped || {};
    carryGround(answer.carried);
    lastAction(`Heaped ${((h.sand_m3 || 0) + (h.soil_m3 || 0)).toFixed(2)} m³ (${grams(h.kg || 0)}) at`
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
// A room off the menu, by its link: /world?scene=yard. The menu has one room,
// the world, with everything in it (the owner, 2026-09-14); the rooms the tests
// and the docs name are still there, and a link opens one the way a QA build's
// link does.
function sceneLink() {
  return new URLSearchParams(location.search).get("scene");
}
function showSceneLink(name) {
  if (!name) return;
  let option = [...$("scene").options].find((o) => o.value === name);
  if (!option) {
    option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    $("scene").append(option);
  }
  $("scene").value = name;
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

// `again`: the "Start the room again" button, which opens the room again from
// what it is held as -- the way out of a room that has stopped. Without it, a
// page opening the room that is running (a reload) rejoins it as it stands.
async function open({ again = false } = {}) {
  // What the room being replaced did since its last report, as its own.
  traceOldWorld();
  world.opening = true;
  $("panel-state").textContent = "Opening the room…";
  const qa = qaBuild();
  showBuild(qa);
  try {
    const myPlayer = worldId ? await joinPlayer() : null;
    const data = watchedId
      ? (watchedView = await api("/api/world/ai", { action:"watch", id:watchedId, full:true })).state
      : await api("/api/world/open", qa !== null ? { qa } : { scene: $("scene").value, ...(again ? { again } : {}) });
    world.session = data.session;
    expedition.update(data.gameplay);
    // What the person has, with the bag's things already set aside by the server.
    world.inventory = data.inventory || null;
    if (worldId) showPlayers(data.players);
    world.scene = data.scene || null;
    // A link naming no room opens the world: the menu says which room opened.
    if (qa === null && data.scene && $("scene").value !== data.scene) showSceneLink(data.scene);
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
    stopPlacing(false);
    world.held = null;
    world.use = { mode: "none" };
    world.loosing = null;
    world.last = null;
    rememberProfiles(data.spec);
    aimArc.hide();
    showHolding(false);
    tools.forget();
    showUse();
    world.bodies.forEach((e) => forget(e.mesh));
    world.bodies.clear();
    world.joints = [];
    draw(data);
    braceProfiles();
    // A new room: no joints said means none, as when the chat rebuilds one. Left
    // to mean "unchanged" -- which it does in a step's reply -- it left the last
    // room's pins drawn in the air over this one.
    drawJoints(data.joints || []);
    // Its batteries and motors likewise: none said means none, and a hoist
    // opened again says its own, so its rope and its panel are there before
    // the first step rather than the last room's.
    followMachines(data.machines, data.t);
  world.brains.clear();
  followBrains(data.brains);
    // A room opening has no "unchanged": no goods said means this room has none.
    followGoods(data.goods || { stockpiles: [], deposits: [] }, true);
    followPorts(data.ports || []);
    followVessels(data.vessels || []);
    lightFromSun(data.sun);
    drawRopes();
    clearHeat();
    // The room as it stood: rejoined on a reload, or opened again whole from
    // the world the server saved before it stopped (`restored`). Either way it
    // is the room the person was in, standing where they stood.
    const asItStood = !!data.rejoined || !!(data.restored && data.restored.tier === "whole");
    if (data.terrain) {
      drawTerrain(data.terrain);
      if (data.sight) showSeen(data.sight);
      if (data.water) drawWater(data.water);
      // Somewhere to stand that looks at something: the valley says where --
      // or, when the room is as it stood, where the person was standing.
      placeCamera((asItStood && (keptView(data.scene) || playerView(myPlayer?.pose))) || data.arrival || (data.gameplay
        ? {eye_m: data.gameplay.spawn_m, look_m: data.gameplay.nodes[0].at_m}
        : data.terrain.view));
    } else {
      clearGround();
      if (asItStood) placeCamera(keptView(data.scene) || playerView(myPlayer?.pose));
    }
    // What this room's ground has had dug out of it and not put back: the
    // engine's count, the room's own edits replayed. A room with no ground has
    // none to carry.
    carryGround(data.terrain ? data.terrain.carried : null);
    // A reload rejoins the room with the hand as it was, and a restart gives it
    // back so: what the engine's hand holds is the person's again, taken over
    // the way a thing out of the bag is (adoptGrip) -- or, on a joint, the way
    // the hand's hold is at the end of an action (adoptHold).
    const holding = asItStood && data.hand && (!worldId || data.hand_owner === playerId
                                                || recordHolds(data.hand.holding))
      ? data.hand.holding : "";
    if (holding && world.bodies.has(holding)) {
      adoptNativeHold(holding,data);
    }
    const focus = new URLSearchParams(location.search).get("focus");
    const focusBody = !watchedId && focus && world.bodies.get(focus);
    if (focusBody) {
      const at = focusBody.mesh.getWorldPosition(new THREE.Vector3());
      window.banjoRoom.lookAt(at.x, at.y, at.z);
      picked.name = focus; picked.at = null; showPicked();
    }
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
    // As left: rejoined, or opened again whole after a restart -- or, for a room
    // kept before the running world was kept with it, as the chat left it.
    if (asItStood || (data.kept && !data.restored && !data.kept_problem))
      say("world", "This is the room as you left it.");
    // And, said plainly, what a restart does not give back yet.
    if (data.restored && data.restored.tier === "whole" && (data.restored.not_kept || []).length)
      say("world", `Not kept yet: ${data.restored.not_kept.join("; ")}.`);
    if (data.kept_problem) say("bad", data.kept_problem);
    for (const upgrade of data.world_upgrades || []) {
      if (upgrade.status === "pending")
        say("world", `${upgrade.title} is waiting: ${upgrade.reason}`);
      else if (upgrade.help)
        say("world", upgrade.help);
    }
    if (watchedId) say("world", "This camera follows the character's eyes. Its bag, goals and tech journal are shown here. Use Menu to pause it, or return to your character to play.");
    else say("world",
      `${data.bodies.length} things, made of ${
        [...new Set(data.bodies.map((b) => b.material).filter(Boolean))].join(", ")
      }. Click the room to look around, and walk with W A S D. ${keyOf("interact")} picks up`
      + ` what you look at and puts it down again, and ${keyOf("stow")} puts it in your bag;`
      + ` what else you can do is under this conversation. Ask me to build or change anything.`);
    // Said, not dropped, as when the chat rebuilds the room: a gate that does
    // not swing reads as broken physics rather than as a pin in the wrong place.
    if (data.joint_problems && data.joint_problems.length)
      say("bad", "Some joints would not hang: " + data.joint_problems.join("; "));
    const edged = (data.blades || []).map((b) => b.body);
    if (edged.length) {
      say("world", `${edged.join(", ")} ${edged.length > 1 ? "have edges" : "has an edge"}.`
        + ` ${keyOf("interact")} takes it by the grip; turn to swing it, and right-click to turn the`
        + ` edge (left, down, right, up). It cuts what its edge meets hard enough, and`
        + ` nothing else.`);
    }
    if (watchedId) updateWatchedCharacter(watchedView);
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
  // Whether bodies are walking to their states rather than appearing at
  // them, and how many are mid-walk right now -- so a check can tell that
  // the smoothing is engaged and not merely switched on.  
  glide: () => ({ on: gliding, walking: glides.size, state_gap_ms: Math.round(stateGapMs) }),
  lookAt(x, y, z) {
    const to = new THREE.Vector3(x, y, z).sub(camera.position);
    yaw = Math.atan2(-to.x, -to.z);
    pitch = Math.atan2(to.y, Math.hypot(to.x, to.z));
    camera.quaternion.setFromEuler(new THREE.Euler(pitch, yaw, 0, "YXZ"));
  },
  standAt(x, y, z) { camera.position.set(x, y, z); },
  // WHICH KEYS THE ROOM THINKS ARE DOWN. A key stuck here is a camera that
  // will not stop: Ctrl+A was one, and a check can only see that by looking
  // at the set itself.
  keysDown: () => [...keys].sort(),
  // What is pinned in the side view, and pinning it without a mouse: a check
  // drives the same state a click sets, so what it reads is what a person
  // would see.
  pick(name, mode) {
    picked.name = name || null;
    picked.at = null;
    revealPicked(mode); showPicked();
  },
  pickGround(x, y, z) {
    picked.name = null;
    picked.at = [x, y, z];
    revealPicked(); showPicked();
  },
  reveal: () => revealing && ({ kind: revealing.kind, count: revealing.count,
    amount: revealing.amount, name: revealing.name, at: revealing.at,
    objects: revealing.group.children.length, matrix: revealing.group.matrix.toArray(),
    cellCentres: revealing.cells,
    components: revealing.rows?.map(r=>({name:r.component,material:r.substance,body:r.sourceName,
      cells:r.part.cells?.length,offset:r.wrapper.position.toArray()})),
    layers: revealing.beds, skinOpacity: revealing.skin?.opacity }),
  picked: () => ({ name: picked.name, at: picked.at, outlined: !!(pickedBox && pickedBox.visible),
                   said: (document.getElementById("picked") || {}).innerText || "" }),
  aim, pickUp, dropIt, putDown, letFly, intend,
  // Mining: the breaker's trigger and the cable drum, which the M and P keys
  // are bound to (tests/lamp_shots.py drives these, not the engine behind the
  // page's back, so what a check photographs is what a person does).
  pullTheTrigger, workTheCable, breakerInHand,
  // Where the hand hauls what it holds on a joint, and what it moves along.
  haulTarget: () => world.held && haulTarget(),
  haulGuide: () => world.held && world.held.guide && ({
    kind: world.held.guide.joint.kind, axis: world.held.guide.joint.axis,
    middle: world.held.guide.middle.toArray(), grabbed: world.held.guide.grabbed.toArray() }),
  // Turning what is held, the way U does it, and "/" -- and what the hand holds:
  // how far out, whether the wrist turns it, the wish it is asking of the wrist
  // ([x, y, z, w]), and whether it is being drawn see-through.
  standUpright, talk,
  // Which way each machine turns, as it is drawn on it: its stripe, and its
  // arrow while it drives.
  machineMarks: () => [...machineMarks].map(([id, m]) => ({
    id, stripe: !!(m.stripe && m.stripe.parent), arrow: !!(m.arrow && m.arrow.visible) })),
  // Each sensor's bead as drawn: where, and whether it is showing water seen.
  sensorMarks: () => [...sensorMarks].map(([key, m]) => ({
    key, at: m.bead.position.toArray(), sees: m.bead.material === SENSOR_SEES })),
  // Each port's ring as drawn: where, which way its mouth looks, and what it
  // is saying -- idle, near, or docked.
  portMarks: () => [...portMarks].map(([name, m]) => ({
    name, at: m.ring.position.toArray(),
    says: m.ring.material === PORT_DOCKED ? "docked"
      : m.ring.material === PORT_NEAR ? "near" : "idle" })),
  // The room's light as drawn: the sun's lamp, how bright and from where, the
  // sky's, and the sun the engine last said.
  light: () => ({ key: key.intensity, from: key.position.toArray(), sky: sky.intensity, sun: world.sun }),
  held: () => world.held && ({
    name: world.held.name, distance: world.held.distance, loose: !!world.held.loose,
    turnable: !!world.held.turn, wish: world.held.turn ? world.held.turn.asked.toArray() : null,
    seeThrough: !!world.seeThrough }),
  // The hand as the control language sees it, and what the help says about it.
  use: () => ({ ...world.use, grip: world.use.grip && world.use.grip.toArray() }),
  help: () => ({ shown: !!world.held, title: lastDetails.name,
                 line: lastDetails.rows.map(([k, what]) => `${k.join(" ")} ${what}`.trim()).join(" · "),
                 note: lastDetails.note, meter: lastDetails.meter ? lastDetails.meter.value : null }),
  // The side view's details as drawn -- name, facts, rows of [keys, what, kind],
  // note, meter and last -- the name over the view, and the bag's slots.
  details: () => ({ ...lastDetails, label: $("label").hidden ? null : $("label-name").textContent }),
  hotbar: () => ({ shown: !$("hotbar").hidden,
                   slots: [...$("hotbar").children].map((li) => ({
                     key: li.querySelector("b").textContent,
                     name: li.querySelector("span") ? li.querySelector("span").textContent : null,
                     inHand: li.classList.contains("in-hand") })) }),
  doChoice, nextChoice, toTheBag, fromSlot, showTab,
  // Putting a thing in a numbered slot, which the hot list's drop does
  // (inventory.py, the `slot` op). A check drives the same call the drop
  // makes: a browser drag is not something CDP can send.
  putInSlot: (item, slot) => inventoryChange("slot", item, { slot }),
  arcShown: () => aimArc.group.visible,
  // What the aim arc is saying, which is the whole of how a throw is aimed:
  // whether it is up, whether it has drawn a flight or only marked the spot,
  // and whether it is green -- green being the only state that throws.
  aiming: () => ({ shown: aimArc.group.visible, line: aimArc.line.visible,
                   ring: aimArc.ring.visible, onTarget: !!aimArc.onTarget,
                   colour: aimArc.material.color.getHex(),
                   mode: world.use.mode,
                   possible: !!(world.use.preview && world.use.preview.possible),
                   why: (world.use.preview && world.use.preview.why) || "" }),
  // For measuring what a frame costs: building the meshes for a shattered pane
  // is the expensive part of a break, and it cannot be seen from outside.
  buildMesh, renderer, THREE, MATERIALS,
  // The grain each substance is drawn with (surfaces.js): what is dressed, and
  // a way to turn the whole room's grain down, which is how a picture of the
  // difference is taken and how a test tells a grain that is really being
  // drawn from one that is not.
  grain: grainState, showGrain,
  // The finishes the room came with, and what a body is actually drawn with.
  skins: () => [...(world.skins || new Map()).values()],
  drawnWith: (name) => {
    const held = world.bodies.get(name);
    if (!held) return null;
    const m = held.mesh.material;
    return { color: `#${m.color.getHexString()}`, roughness: m.roughness,
             metalness: m.metalness, grainOf: m.userData.grainOf || null,
             shared: m === look(held.material, !!held.mesh.userData.shaded) };
  },
  // How the bodies made of cells are actually drawn, which is not something a
  // picture can be asked: `hulls` are the ones drawn as their outside surface
  // (cellmesh.js) and `cubes` the ones the mesher would not vouch for and
  // handed back. `triangles` is what they cost against `asCubes`, what the
  // same cells would have cost drawn one cube each.
  hullsDrawn: () => {
    let hulls = 0, cubes = 0, cells = 0, triangles = 0, designs = 0;
    for (const held of world.bodies.values()) {
      const mesh = held.mesh;
      if (mesh.isInstancedMesh && mesh.geometry === cellGeometry) {
        ++cubes;
        cells += mesh.count;
        triangles += 12 * mesh.count;
      } else if (mesh.userData.drawnToDesign) {
        ++designs;
        cells += mesh.userData.hullCells || 0;
        triangles += mesh.geometry.attributes.position.count / 3;
      } else if (mesh.userData.shaded) {
        ++hulls;
        cells += mesh.userData.hullCells || 0;
        triangles += mesh.geometry.attributes.position.count / 3;
      }
    }
    return { hulls, cubes, designs, cells, triangles, asCubes: 12 * cells,
             shadows: renderer.shadowMap.enabled, sunCasts: key.castShadow,
             environment: !!scene.environment, toneMapping: renderer.toneMapping };
  },
  // What one body of cells came out as: the faces its cells expose, the
  // rectangles those merged into, and the triangles drawn for it.
  hullOf: (name) => {
    const held = world.bodies.get(name);
    if (!held || !held.mesh.userData.shaded) return null;
    return { faces: held.mesh.userData.hullFaces, quads: held.mesh.userData.hullQuads,
             cells: held.mesh.userData.hullCells, bent: !!held.mesh.userData.hullBent,
             triangles: held.mesh.geometry.attributes.position.count / 3 };
  },
  // What the heat drawing was last given, and what it drew from it.
  heatState: () => heat.last,
  // What heat has left of what things can carry, as the engine last said it.
  strengthState: () => heat.strength,
  // The pins and grooves drawn right now: none may be left over from a room
  // that is no longer open.
  pinsDrawn: () => pinGroup.children.length,
  // Every holder's slots as they are DRAWN: the Room tab's list, and the
  // open machine's own. `moved` is up or down while a slot is lit.
  holds: (which = "holds-list") => ({
    shown: !$(which === "holds-list" ? "holds" : "mp-holds").hidden,
    holders: [...$(which).children].map((li) => ({
      name: li.querySelector(".hold-name").textContent,
      of: li.querySelector(".hold-of").textContent,
      full: li.querySelector(".meter-bar").hidden ? null : li.querySelector(".meter-bar i").style.width,
      slots: [...li.querySelectorAll(".hold-slot")].map((slot) => ({
        what: slot.classList.contains("none") ? null : slot.querySelector("span").textContent,
        much: slot.classList.contains("none") ? null : slot.querySelector("b").textContent,
        tint: slot.classList.contains("none") ? null : slot.querySelector("i").style.getPropertyValue("--c"),
        moved: slot.classList.contains("up") ? "up" : slot.classList.contains("down") ? "down" : null,
      })),
    })),
  }),
  // The workbench: what is on it, and where its clock is (workbench.js).
  workbench: () => workbench.state(),
  // `jetsSeen` is every nozzle that has drawn a jet at any point, not just the
  // ones drawing one now: a motor's burn is over in a fraction of a second and
  // a check that has to catch it live would be a test of timing rather than of
  // drawing.
  heatDrawn: () => ({ glowing: [...heat.glowing.keys()], flames: [...heat.flames.keys()],
                      columns: [...heat.columns.keys()], jets: [...heat.jets.keys()],
                      jetsSeen: [...heat.jetsSeen],
                      // How see-through each column actually is, so a check can
                      // hold the drawing against the gas it is a drawing of.
                      columnOpacity: Object.fromEntries(
                        [...heat.columns].map(([name, mesh]) => [name, mesh.material.opacity])) }),
  // The ground and the water as drawn, for checking what is on screen against
  // what the engine said -- and a spade, for driving the room from outside.
  groundAt, waterAt, digAt,
  // The water a journey says the person is in (inTheWater), or null for the room's own.
  waterForThePerson(said) { waterSaid = typeof said === "function" ? said : null; },
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
    player_id: playerId,
    player_name: playerName,
    avatars: avatars.size,
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
// The step loop paces ITSELF. It used to be setInterval(tick, 33) with a
// world.busy guard, which meant a round trip was rounded UP to the next
// multiple of 33 ms: at a measured 109 ms that is 132, and 7.6 states a second
// where the network could give 9.2. Measured at 100 ms of added latency: 7.2
// states a second on the interval. Now the next one is asked for as soon as
// the last is answered, with the same 33 ms floor so a fast local server is
// paced exactly as before.
const TICK_FLOOR_MS = 33;
async function tickLoop() {
  const began = performance.now();
  try {
    await tick();
  } finally {
    setTimeout(tickLoop, Math.max(0, TICK_FLOOR_MS - (performance.now() - began)));
  }
}
ridingRemembered();
buildRidingSettings();
tickLoop();
setInterval(aim, 90);
if (qaBuild() === null) showSceneLink(sceneLink());
open();
