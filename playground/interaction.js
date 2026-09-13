// One control language for everything a hand can use. docs/interaction-profiles.md.
//
// Objects name SEMANTIC actions -- interact, primary, secondary, more -- and
// never keys. This file maps them to the player's bindings, says in words what
// each does in the state the hand is in, and draws where a throw will go. What
// any of it DOES is the engine's: a throw is a stroke of the bounded hand, the
// speed a thing leaves with is measured and never given, and the arc is the
// engine's own preview of this hand on this thing.

import * as THREE from "/vendor/three.module.js";

const clamp01 = (v) => Math.max(0, Math.min(1, v));
// Names come from whoever built the room -- the chat, the MCP, a person -- and
// the help is HTML, so they go in as text.
const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

// The player's bindings. One table, and every word of help is written from it,
// so what the screen says to press is always what pressing does.
export const BINDINGS = {
  interact:  { label: "E", keys: ["KeyE"] },
  primary:   { label: "Left mouse", button: 0 },
  secondary: { label: "Right mouse", button: 2 },
  more:      { label: "Tab", keys: ["Tab"] },
  up:        { label: "Space", keys: ["Space"] },
  down:      { label: "Q", keys: ["KeyQ"] },
};
export const keyOf = (action) => BINDINGS[action].label;
export const isKey = (action, code) => (BINDINGS[action].keys || []).includes(code);
export const isButton = (action, button) => BINDINGS[action].button === button;

// The line along the bottom of the screen, written from the table.
export function controlsHint() {
  return `<b>W A S D</b> walk · <b>${keyOf("up")}</b> up · <b>${keyOf("down")}</b> down`
    + ` · <b>Shift</b> run · <b>drag</b> or <b>arrow keys</b> look`
    + ` · <b>${keyOf("interact")}</b> or <b>click</b> take hold and put down`
    + ` · hold <b>${keyOf("primary")}</b> to wind up a throw, let go to throw`
    + ` · <b>${keyOf("secondary")}</b> cancel · <b>${keyOf("more")}</b> more`
    + ` · <b>R</b> release a latch · <b>L</b> if it lagged · <b>Esc</b> release the mouse`;
}

// ---------------------------------------------------------------------------
// The throw
// ---------------------------------------------------------------------------
//
// Where a right hand holds a thing it means to throw, how far back a full
// wind-up takes it, and where it lets go -- in the view's own frame, metres.
// These are a person's numbers, not the ball's: what the ball does with them
// is up to its mass and the hand's 800 N.
const HOLD = { forward: 0.5, right: 0.2, up: -0.15 };
const WOUND = { forward: -0.22, right: 0.34, up: 0.12 };
const RELEASE = { forward: 0.72, right: 0.12, up: -0.02 };
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

export const holdPoint = (camera) => inView(camera, HOLD);

// Where the hand wants the thing, `asked` of the way back.
export const windUpPoint = (camera, asked) =>
  holdPoint(camera).lerp(inView(camera, WOUND), clamp01(asked));

// How far back the thing actually IS: its grip measured along the wind-up.
// This is the meter -- a heavy thing winds up slower than it is asked to.
export function windUpReached(camera, grip) {
  const a = holdPoint(camera);
  const d = inView(camera, WOUND).sub(a);
  return clamp01(grip.clone().sub(a).dot(d) / d.lengthSq());
}

// The stroke that throws: from where the grip is to the release beside the eye,
// the last 0.3 m along the line of sight, so the thing leaves the way the
// person is looking. From a wind-up that did not get behind that line, it is
// one straight push.
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
    give_up_s: 1.0,
  };
}

// Putting a thing down: lowered straight onto what is below it, slowly, and let
// go of when it gets there. The same bounded hand; nothing is placed by fiat.
export function placeStroke(grip, restsAtY) {
  return {
    path: [[grip.x, grip.y, grip.z], [grip.x, Math.min(grip.y, restsAtY), grip.z]],
    speed_m_s: 0.8, accel_m_s2: 4, lead_m: 0.05, give_up_s: 3.0, let_go: true,
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
// What to say
// ---------------------------------------------------------------------------
//
// Only what can be done in the state the hand is in is offered, in the player's
// keys. `use` is the page's own record of the hand: { mode, name, kg, reached,
// preview, result, more }.
export function helpFor(use) {
  const k = (action) => `<kbd>${keyOf(action)}</kbd>`;
  const kg = use.kg ? ` · ${use.kg < 10 ? use.kg.toFixed(2) : use.kg.toFixed(1)} kg` : "";
  const title = `<b>${esc(use.name)}</b>${kg}`;
  const out = { title, line: "", meter: null, note: "" };
  const preview = use.preview && use.preview.possible
    ? `this throw would leave your hand at ${use.preview.speed.toFixed(1)} m/s`
      + (use.preview.hitName ? ` and hit ${use.preview.hitName}` : use.preview.hit ? " and come down on the ground" : "")
      + ` — a preview of this hand on this ${use.noun}, not of what it meets on the way`
    : use.preview && use.preview.why ? use.preview.why : "";
  switch (use.mode) {
    case "ready":
      out.line = `Hold ${k("primary")} to wind up · let go to throw · ${k("interact")} put it down · ${k("more")} more`;
      out.note = preview;
      break;
    case "preparing":
      out.line = `Let go of ${k("primary")} to throw · ${k("secondary")} lower it`;
      out.meter = { label: "Wind-up", fraction: use.reached || 0,
                    value: `${Math.round(100 * (use.reached || 0))}%` };
      out.note = preview;
      break;
    case "throwing":
      out.line = "Throwing…";
      break;
    case "placing":
      out.line = "Putting it down…";
      break;
    case "blocked":
      out.line = `Something is in the way · ${k("interact")} put it down · hold ${k("primary")} to try again`;
      break;
    case "carrying":
      out.line = `${k("primary")} or ${k("interact")} put it down · ${k("more")} more`;
      break;
    case "thrown":
      out.line = esc(use.result);
      break;
    default:
      out.line = "";
  }
  if (use.more && (use.mode === "ready" || use.mode === "carrying" || use.mode === "blocked")) {
    out.line = `<kbd>1</kbd> let go of it here · <kbd>2</kbd> put it down gently`
      + (use.latched ? ` · <kbd>3</kbd> release its latch` : "") + ` · ${k("more")} back`;
  }
  return out;
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
