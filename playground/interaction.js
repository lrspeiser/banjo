// One control language for everything a hand can use. docs/interaction-profiles.md.
//
// Objects name SEMANTIC actions -- interact, primary, secondary, next -- and
// never keys. This file maps them to the player's bindings, says in words what
// each does in the state the hand is in, and draws where a throw will go. What
// any of it DOES is the engine's: a throw is a stroke of the bounded hand, the
// speed a thing leaves with is measured and never given, and the arc is the
// engine's own preview of this hand on this thing.

import * as THREE from "/vendor/three.module.js";

const clamp01 = (v) => Math.max(0, Math.min(1, v));

// The player's bindings. One table, and every word of help is written from it,
// so what the screen says to press is always what pressing does.
//
// The owner, 2026-09-14: E picks up what you look at -- or does its main thing --
// and puts it down again; Q puts it in the bag; 1-9 take a thing out of the
// bag's slots and the same number puts it back; the left mouse throws. Tab moves
// E on to the next thing that can be done, which the side view lists, so nothing
// needs the mouse let go of. Down moved off Q, which is the bag now.
export const BINDINGS = {
  interact:  { label: "E", keys: ["KeyE"] },
  primary:   { label: "Left mouse / J", button: 0, keys: ["KeyJ"] },
  secondary: { label: "Right mouse", button: 2 },
  next:      { label: "Tab", keys: ["Tab"] },
  stow:      { label: "Q", keys: ["KeyQ"] },
  slots:     { label: "1–9", keys: ["Digit1", "Digit2", "Digit3", "Digit4", "Digit5", "Digit6",
                                    "Digit7", "Digit8", "Digit9", "Numpad1", "Numpad2", "Numpad3",
                                    "Numpad4", "Numpad5", "Numpad6", "Numpad7", "Numpad8", "Numpad9"] },
  up:        { label: "Space", keys: ["Space"] },
  // Space with Shift held: the way a game's flying camera goes down.
  down:      { label: "Shift+Space", keys: ["Space"], shift: true },
  // Turning what the hand holds. Each asks the hand's wrist to turn it; the
  // wrist does that with the torque it has (see "Turning what is held").
  turnLeft:  { label: "Z", keys: ["KeyZ"] },
  turnRight: { label: "X", keys: ["KeyX"] },
  tipAway:   { label: "T", keys: ["KeyT"] },
  tipBack:   { label: "G", keys: ["KeyG"] },
  tipLeft:   { label: "C", keys: ["KeyC"] },
  tipRight:  { label: "V", keys: ["KeyV"] },
  upright:   { label: "U", keys: ["KeyU"] },
  // How far out the hand holds it: the mouse wheel, away to push it further.
  reach:     { label: "Mouse wheel" },
  // The room's chat, as in a game: "/" and say what you want.
  talk:      { label: "/", keys: ["Slash", "NumpadDivide"] },
  // The panel's buttons, from the keyboard: dig where the crosshair meets the
  // ground, heap what is carried there, and heat what the crosshair is on.
  dig:       { label: "F", keys: ["KeyF"] },
  heap:      { label: "H", keys: ["KeyH"] },
  heat:      { label: "B", keys: ["KeyB"] },
  // The workbench: the lab's recorded runs, played back on a bench in front of
  // you (workbench.js).
  workbench: { label: "K", keys: ["KeyK"] },
};
export const keyOf = (action) => BINDINGS[action].label;
export const isKey = (action, code) => (BINDINGS[action].keys || []).includes(code);
export const isButton = (action, button) => BINDINGS[action].button === button;

// The keys that turn what is held, and which way each turns it, in the frame
// of where the person faces: x to their right, y up, z back towards them.
export const TURNS = [
  { action: "turnLeft", axis: [0, 1, 0], sign: 1 },
  { action: "turnRight", axis: [0, 1, 0], sign: -1 },
  { action: "tipAway", axis: [1, 0, 0], sign: -1 },
  { action: "tipBack", axis: [1, 0, 0], sign: 1 },
  { action: "tipLeft", axis: [0, 0, 1], sign: 1 },
  { action: "tipRight", axis: [0, 0, 1], sign: -1 },
];

// Every control, as rows of [keys, what they do], written from the table: the
// side view's Keys tab. Nothing else on the page lists them all.
export function controls() {
  const k = keyOf;
  return [
    ["W A S D", "walk"],
    ["Shift", "run"],
    [k("up"), "go up"],
    [k("down"), "go down"],
    ["Drag, arrow keys", "look; click the room to look with the mouse"],
    [k("interact"), "pick up what you look at, or do what the side view marks with E; again, put it down"],
    [k("next"), "move E on to the next thing the side view lists"],
    [k("stow"), "put what you hold, or what you look at, in your bag"],
    [k("slots"), "take that slot of your bag into your hand; the same number puts it back"],
    [k("primary"), "use the held product or the one you look at · hold/release for a throw or bow"],
    [k("secondary"), "lower a throw, let a string down, stop a tool · release a latch"],
    [`${k("turnLeft")} ${k("turnRight")}`, "turn what you hold"],
    [`${k("tipAway")} ${k("tipBack")}`, "tip it away or back"],
    [`${k("tipLeft")} ${k("tipRight")}`, "tip it sideways"],
    [k("upright"), "stand it upright"],
    [k("reach"), "hold it further out or nearer"],
    [`Alt+${k("interact")}`, "take hold of exactly the part you look at"],
    [k("talk"), "talk to the room"],
    [k("dig"), "dig where you look"],
    [k("heap"), "heap what you carry where you look"],
    [k("heat"), "heat what you look at"],
    [k("workbench"), "the workbench's recorded runs"],
    ["R", "release a latch"],
    ["L", "mark that it lagged"],
    ["Esc", "let the mouse go"],
  ];
}

// ---------------------------------------------------------------------------
// Where a thing is held
// ---------------------------------------------------------------------------
//
// Where a right hand holds a thing, how far back a full wind-up takes it, and
// where it lets go -- in the view's own frame, metres. These are a person's
// numbers, not the ball's: what the ball does with them is up to its mass and
// the hand's 800 N.
//
// Held below and to the right of the middle of the view, never in front of
// it. The direction is fixed; how far out is the person's (the mouse wheel),
// and never so close that a big thing fills the middle of the view: a pillar
// held where a ball is held covered the whole screen.
const HOLD = { forward: 0.5, right: 0.2, up: -0.15 };
const WOUND = { forward: -0.22, right: 0.34, up: 0.12 };
const RELEASE = { forward: 0.72, right: 0.12, up: -0.02 };
// A ball's hold, 0.56 m out: 27 degrees below and right of the line of sight.
export const HOLD_M = Math.hypot(HOLD.forward, HOLD.right, HOLD.up);
export const HOLD_RANGE_M = { least: 0.4, most: 3.0 };
// A lob to a hard overarm throw: how fast the hand itself goes, across the
// wind-up. 20 m/s is a hard throw by an ordinary adult -- a DEMONSTRATION
// value. A light thing leaves at about this; a heavy one at what the hand's
// strength can give it, which is less.
export const THROW_SPEED = { least: 3.0, most: 20.0 };
// Holding primary this long winds all the way back.
export const WIND_UP_S = 0.9;

function inView(camera, at) {
  const f = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion);
  const r = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion);
  const u = new THREE.Vector3(0, 1, 0).applyQuaternion(camera.quaternion);
  return camera.position.clone().addScaledVector(f, at.forward)
    .addScaledVector(r, at.right).addScaledVector(u, at.up);
}

// How far out a thing of this size is held, to start with. The hold is 27
// degrees off the line of sight; a thing whose bounding radius is r, held d
// away, reaches asin(r / d) round its middle -- so at 2.6 r it stops 4 degrees
// short of the crosshair. A ball is held where a ball always was.
export function holdDistanceFor(radius) {
  return Math.max(HOLD_RANGE_M.least,
                  Math.min(HOLD_RANGE_M.most, Math.max(HOLD_M, 2.6 * (radius || 0))));
}

// The bounding radius of a body the page has drawn.
export function radiusOf(entry) {
  const d = entry && entry.dims;
  if (!d) return 0.05;
  return entry.shape === "sphere" ? d[0] / 2 : Math.hypot(d[0], d[1], d[2]) / 2;
}

export function holdPoint(camera, distance = HOLD_M) {
  const s = distance / HOLD_M;
  return inView(camera, { forward: HOLD.forward * s, right: HOLD.right * s, up: HOLD.up * s });
}

// Where the hand wants the thing, `asked` of the way back.
export const windUpPoint = (camera, asked, distance = HOLD_M) =>
  holdPoint(camera, distance).lerp(inView(camera, WOUND), clamp01(asked));

// How far back the thing actually IS: its grip measured along the wind-up.
// This is the meter -- a heavy thing winds up slower than it is asked to.
export function windUpReached(camera, grip, distance = HOLD_M) {
  const a = holdPoint(camera, distance);
  const d = inView(camera, WOUND).sub(a);
  return clamp01(grip.clone().sub(a).dot(d) / d.lengthSq());
}

// The stroke that throws: from where the grip is to the release beside the eye,
// the last 0.3 m along the line of sight, so the thing leaves the way the
// person is looking. From a wind-up that did not get behind that line, it is
// one straight push.
//
// It lets go at the end, and says so here rather than where it is sent, so the
// preview of it and the throw are the same stroke. Without let_go a stroke keeps
// hold, and a hand that keeps hold slows to ARRIVE at the end: the aim arc was
// drawn from exactly that, and measured, a rubber ball the arc said would leave
// at 4.7 m/s left at 14.7.
export function throwStroke(camera, grip, reached) {
  const f = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion);
  const release = inView(camera, RELEASE);
  const onLine = release.clone().addScaledVector(f, -0.3);
  const behind = grip.clone().sub(camera.position).dot(f) < onLine.clone().sub(camera.position).dot(f) - 0.02;
  const points = behind ? [grip, onLine, release] : [grip, release];
  return {
    path: points.map((v) => [v.x, v.y, v.z]),
    speed_m_s: THROW_SPEED.least + (THROW_SPEED.most - THROW_SPEED.least) * clamp01(reached),
    accel_m_s2: 2000,
    lead_m: 0.05,
    let_go: true,
    give_up_s: 1.0,
  };
}

// Putting a thing down: lowered straight onto what is below it and let go of
// once it is there. The same bounded hand; nothing is placed by fiat. The hand
// ARRIVES -- it slows as it comes to where the thing rests, and keeps hold --
// and the page lets go when the engine says the stroke has reached its end: a
// hand that let go on the way down, at speed, dropped a pillar onto its end.
export function placeStroke(grip, restsAtY) {
  return {
    path: [[grip.x, grip.y, grip.z], [grip.x, Math.min(grip.y, restsAtY), grip.z]],
    speed_m_s: 0.6, accel_m_s2: 3, lead_m: 0.05, give_up_s: 4.0, let_go: false,
  };
}

// Whether a thing is one a hand can pick up and throw: loose, on no joint, and
// light enough to hold up with most of the hand's strength left to throw it.
export const HAND_STRENGTH_N = 800;
export function throwable(entry, onAJoint) {
  if (!entry || entry.anchored || onAJoint) return false;
  const kg = entry.mass || 0;
  return kg > 0 && kg * 9.80665 < 0.9 * HAND_STRENGTH_N;
}

// ---------------------------------------------------------------------------
// Turning what is held
// ---------------------------------------------------------------------------
//
// The keys and U say how the person WANTS it turned. The hand asks for that
// at a pace its wrist can follow for this thing, and the engine turns it with
// what the wrist has: 60 N m, the engine's own number, and no more. Nothing
// here sets how anything is turned -- a turn the thing cannot make, because
// it is against the floor or too heavy to swing round, is simply not made.
//
// The pace matters because the wrist is bounded. Measured on the live engine
// (docs/interaction-profiles.md): a 49 kg concrete pillar asked to stand up
// all at once overshot upright by 74 degrees; asked at 1.2 to 3 rad/s, easing
// in over the last part, it stood up with no overshoot at all. A 74 kg pillar
// 1.2 m long -- four times the inertia -- stood up at 1.2 rad/s, overshot by
// 14 degrees at 1.8 and fell over at 3. So the pace is worked out from the
// thing's own inertia and the wrist's torque: sqrt(0.2 * torque / inertia).
export const HAND_TORQUE_N_M = 60;
// How fast a held key turns the wish, radians a second.
export const TURN_KEY_RATE = Math.PI / 2;
const EASE_S = 0.3;

// The most inertia a body has about any axis through its middle.
function inertiaOf(entry) {
  const kg = entry.mass || 0;
  const d = entry.dims || [0.1, 0.1, 0.1];
  if (entry.shape === "sphere") return 0.1 * kg * d[0] * d[0];
  const [a, b, c] = d;
  return kg * Math.max(a * a + b * b, b * b + c * c, a * a + c * c) / 12;
}

// How fast the hand asks this thing to turn, and how it eases into the end.
export function turnPace(entry) {
  const inertia = Math.max(1e-6, inertiaOf(entry));
  return { cap: Math.min(2.5, Math.sqrt(0.2 * HAND_TORQUE_N_M / inertia)), ease_s: EASE_S };
}

// One tick of the hand's wish coming round to what is wanted: at the pace,
// easing in over the last part. `asked` is changed in place.
export function askTowards(asked, wanted, pace, dt) {
  const gap = asked.angleTo(wanted);
  if (gap < 1e-6) return asked.copy(wanted);
  const step = Math.min(pace.cap * dt, gap * (1 - Math.exp(-dt / pace.ease_s)));
  return asked.rotateTowards(wanted, step);
}

// The turn that stands a thing upright: its longest side vertical, by the
// smallest turn from how it is -- so it keeps the way it faces. Between two
// equally long sides, the one nearer vertical already. Null for a ball or a
// cube, which have no long side to stand on.
export function uprightTurn(q, dims, shape) {
  if (shape === "sphere" || !dims) return null;
  const longest = Math.max(...dims);
  if (dims.every((v) => longest - v < 1e-6)) return null;
  let axis = null;
  for (let i = 0; i < 3; ++i) {
    if (longest - dims[i] > 1e-6) continue;
    const along = new THREE.Vector3().setComponent(i, 1).applyQuaternion(q);
    if (!axis || Math.abs(along.y) > Math.abs(axis.y)) axis = along;
  }
  const up = new THREE.Vector3(0, axis.y >= 0 ? 1 : -1, 0);
  return new THREE.Quaternion().setFromUnitVectors(axis, up).multiply(q);
}

// ---------------------------------------------------------------------------
// What to say
// ---------------------------------------------------------------------------
//
// What a bow says under its controls: whether there is an arrow on the string,
// what its own limbs hold, how hard the hand is pulling -- all measured -- and
// where the shot would go, which is said to be approximate because it is.
function bowNote(use) {
  const b = use.bow || {};
  const bits = [b.arrowReady ? "Arrow ready" : "No arrow on the string"];
  if (b.storedJ > 0.01) bits.push(`its limbs hold ${b.storedJ.toFixed(1)} J`);
  if (b.pullN > 1) bits.push(`your hand pulls ${Math.round(b.pullN)} N`);
  if (b.blocked) bits.push("as far as your hand can draw it");
  else if (b.full) bits.push("full draw");
  if (use.preview && use.preview.possible && use.preview.text) bits.push(use.preview.text);
  else if (b.noPreview) bits.push(b.noPreview);
  return bits.join(" · ");
}

// What the hand can do in the state it is in, in the player's own keys: rows of
// [keys, what they do], a meter while the engine is measuring one, and a note.
// The side view lists them under what is held (world.js showDetails), after E,
// Tab and Q, which it works out itself. Only what can be done in this state is
// offered. Plain text: the names in it come from whoever built the room, and the
// page sets them as text, never as markup. `use` is the page's own record of the
// hand: { mode, name, kg, noun, reached, preview, bow, turnable, loose, guide,
// target }.
export function handHelp(use) {
  const k = keyOf;
  const rows = [];
  let meter = null, note = "";
  const preview = use.preview && use.preview.possible
    ? `This throw would leave your hand at ${use.preview.speed.toFixed(1)} m/s`
      + (use.preview.hitName ? ` and hit ${use.preview.hitName}` : use.preview.hit ? " and come down on the ground" : "")
      + ` — a preview of this hand on this ${use.noun || "thing"}, not of what it meets on the way.`
    : use.preview && use.preview.why ? use.preview.why : "";
  switch (use.mode) {
    case "ready":
      rows.push([[k("primary")], "hold to wind up, let go to throw"]);
      note = preview;
      break;
    case "preparing":
      rows.push([[k("primary")], "let go to throw"], [[k("secondary")], "lower it"]);
      meter = { label: "Wind-up", fraction: use.reached || 0,
                value: `${Math.round(100 * (use.reached || 0))}%` };
      note = preview;
      break;
    case "throwing":
      note = "Throwing…";
      break;
    case "placing":
      note = "Putting it down…";
      break;
    case "blocked":
      rows.push([[k("primary")], "hold to try the throw again"]);
      note = "Something is in the way.";
      break;
    case "carrying":
      // A thing on a pin or in a groove follows the crosshair over what the
      // joint lets it move along (world.js haulTarget): say so, or a winch
      // looks like it cannot be worked at all.
      if (use.guide === "hinge") {
        note = "It turns on a pin: move the crosshair round the pin and it follows — round and round to crank a wheel.";
      } else if (use.guide === "slider") {
        note = "It slides in a groove: move the crosshair along the groove and it follows.";
      }
      break;
    case "bow-ready":
      if (use.bow && use.bow.strung === false) {
        note = "The string is cut — it cannot be drawn.";
      } else {
        rows.push([[k("primary")], "hold to draw, let go to shoot"]);
        note = bowNote(use);
      }
      break;
    case "drawing": {
      const b = use.bow || {};
      const fraction = b.max > 0 ? Math.min(1, (b.drawn || 0) / b.max) : 0;
      rows.push([[k("primary")], "let go to shoot"], [[k("secondary")], "let the string down"]);
      meter = { label: "Draw", fraction,
                value: `${Math.round(100 * fraction)}% · ${Math.round(1000 * (b.drawn || 0))} mm` };
      note = bowNote(use);
      break;
    }
    case "letting-down":
      note = "Letting the string down…";
      break;
    // A tool (tools.js): what its click does where the ring is, as the server
    // says it (tool_use.resolve), and why it cannot be done there when it cannot.
    case "tool-lifting":
      note = "Lifting it…";
      break;
    case "tool-ready": {
      const t = use.target || {};
      if (t.enabled !== false) {
        rows.push([[k("primary")], (t.label || "use it").toLowerCase() + (t.repeat ? "; hold to keep going" : "")]);
      }
      note = t.reason || "";
      break;
    }
    case "tool-working": {
      const t = use.target || {};
      rows.push([[k("secondary")], "stop after this one"]);
      note = `${t.label || "Working"}…`;
      break;
    }
    default:
      break;
  }
  // Turning it, and how far out it is held: for a loose thing in the hand. The
  // wrist turns what the hand can hold up; what it cannot, it says, and the
  // room can be asked instead.
  if (use.mode === "ready" || use.mode === "blocked") {
    if (use.turnable) {
      rows.push([[k("turnLeft"), k("turnRight"), k("tipAway"), k("tipBack"), k("tipLeft"), k("tipRight")],
                 "turn it, or tip it away, back or sideways"],
                [[k("upright")], "stand it upright"]);
    }
    rows.push([[k("reach")], "hold it further out or nearer"]);
  } else if (use.loose && use.mode === "carrying") {
    rows.push([[k("reach")], "hold it further out or nearer"]);
    note = note || `Too heavy for your hand to turn: ${k("talk")} asks the room to turn it.`;
  }
  return { rows, meter, note };
}

// ---------------------------------------------------------------------------
// Where it will go
// ---------------------------------------------------------------------------
//
// The engine's preview, drawn: a dashed arc from where the hand would let go,
// and a ring where it would first meet something. Dashed because it is a
// preview and not the thing -- the real throw is the one the world makes.
export class AimArc {
  constructor(scene) {
    this.material = new THREE.LineDashedMaterial({
      color: 0xf0b429, dashSize: 0.14, gapSize: 0.09, transparent: true, opacity: 0.9 });
    this.line = new THREE.Line(new THREE.BufferGeometry(), this.material);
    this.ring = new THREE.Mesh(
      new THREE.RingGeometry(0.1, 0.14, 32),
      new THREE.MeshBasicMaterial({ color: 0xf0b429, side: THREE.DoubleSide,
                                    transparent: true, opacity: 0.9 }));
    this.ring.rotation.x = -Math.PI / 2;
    this.group = new THREE.Group();
    this.group.add(this.line, this.ring);
    this.group.visible = false;
    scene.add(this.group);
  }

  show(flight) {
    const points = (flight.points_m || []).map((p) => new THREE.Vector3(p[0], p[1], p[2]));
    if (points.length < 2) { this.hide(); return; }
    const geometry = new THREE.BufferGeometry().setFromPoints(points);
    this.line.geometry.dispose();
    this.line.geometry = geometry;
    this.line.computeLineDistances();
    this.ring.visible = !!flight.hit;
    if (flight.hit) {
      const [x, y, z] = flight.hit_point_m;
      this.ring.position.set(x, y + 0.01, z);
    }
    this.group.visible = true;
  }

  hide() { this.group.visible = false; }
}
