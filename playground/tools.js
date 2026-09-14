// Using a tool, the same way for every tool.
//
// The server (tool_use.py) says what the tool in hand does where the crosshair
// meets the ground -- its action and label, whether it can be done there and
// why not, and the ring to draw -- and does it when the button is pressed: the
// tool held still, swung, pried if the point went in, drawn back out, each
// stroke the engine's. This page only holds the tool ready, draws the ring,
// sends the click and says what came of it. It never knows a tool's steps, so
// a new kind of tool needs nothing here (the owner: "make sure this is designed
// to be a generic capability, so if I build a hoe or an axe it will have the
// same capabilities"). How it is used -- what the click is called, how the hand
// swings it -- is its profile's `use`, which the room's chat may shape.
//
// Measured with the pick before this (the scratchpad's headless_world_pick.py):
// E took it only with the crosshair exactly on its 4 cm haft; a second left
// click with its point in the ground dropped it; and one swing in three came
// back "It met no ground" on plain sand.

import * as THREE from "/vendor/three.module.js";

// The grip is held ready half a metre out and down from the eyes and a little
// to the right, point down and haft back towards the person: the pose the
// engine plans a swing from.
const READY = { out: 0.55, down: 0.5, right: 0.18 };
// E takes up a tool whose body passes this close to the crosshair's line
// within reach -- a pick lies flat and is 4 cm thick.
const NEAR_M = 0.3;
const REACH_M = 2.5;
// The ring follows the crosshair at up to five answers a second, one in flight.
const ASK_EVERY_MS = 200;
// Held, the next use waits this long in the ready pose after the last.
const REPEAT_AFTER_MS = 700;
// Taken up from where it lies, a tool is first lifted straight up by its grip,
// turned as it lay, and only then brought round into the ready pose. Brought
// round at once, its point was swung through the ground on the way: on the
// owner's sim, "The point went 103 mm into the sand, arriving at 0.6 m/s ...
// The pry broke out 26.70 L" before they had swung it at all, and then the
// point was left 197 mm into the soil.
const LIFT_M = 0.6;
const LIFT_MS = 700;
// Its colours, by what the server says of the target (tool_use.resolve).
const RING = { ok: 0x4fbf6a, far: 0xf0b429, near: 0xf0b429, warn: 0xe0533d, no: 0x8a949c };

export function makeTools(ctx) {
  const { world, act, api, say, remember, showUse, camera, carryGround, scene, whereIAm, $ } = ctx;

  const ring = new THREE.Mesh(
    new THREE.RingGeometry(0.11, 0.16, 40),
    new THREE.MeshBasicMaterial({ color: RING.ok, side: THREE.DoubleSide, transparent: true,
                                  opacity: 0.85, depthWrite: false }));
  ring.rotation.x = -Math.PI / 2;
  ring.renderOrder = 2;
  ring.visible = false;
  scene.add(ring);

  function profileOf(name) {
    return (world.tools || []).find((p) => p.parts.includes(name)) || null;
  }

  // The tool whose body passes nearest the crosshair's line, within NEAR_M of it
  // and inside reach: what E takes up with the crosshair on the ground beside it.
  function nearTool() {
    const from = camera.position;
    const dir = new THREE.Vector3();
    camera.getWorldDirection(dir);
    let best = null;
    for (const profile of world.tools || []) {
      for (const part of profile.parts) {
        const entry = world.bodies.get(part);
        if (!entry || !entry.mesh) continue;
        const box = new THREE.Box3().setFromObject(entry.mesh);
        for (let s = 0.3; s <= REACH_M; s += 0.05) {
          const d = box.distanceToPoint(from.clone().addScaledVector(dir, s));
          if (d <= NEAR_M && (!best || d < best.d)) best = { profile, d };
        }
      }
    }
    return best ? best.profile : null;
  }

  // The tool's own axes, as the engine's strike planner takes them: its point
  // (y), square to its point and its haft (z), and the third (x) -- in the
  // body's own frame, from the engine's local numbers where the reply carries
  // them, and otherwise from the world ones and how the body is turned now.
  function axesOf(point) {
    let pointing, tip, grip;
    if (point.pointing_local && point.tip_local && point.grip_local) {
      pointing = new THREE.Vector3(...point.pointing_local);
      tip = new THREE.Vector3(...point.tip_local);
      grip = new THREE.Vector3(...point.grip_local);
    } else {
      const entry = world.bodies.get(point.body);
      const back = entry ? entry.mesh.quaternion.clone().invert() : new THREE.Quaternion();
      pointing = new THREE.Vector3(...point.pointing).applyQuaternion(back);
      tip = new THREE.Vector3(...point.tip).applyQuaternion(back);
      grip = new THREE.Vector3(...point.grip).applyQuaternion(back);
    }
    const y = pointing.normalize();
    const z = new THREE.Vector3().crossVectors(y, grip.clone().sub(tip));
    if (z.lengthSq() < 1e-12) z.set(0, 0, 1);
    z.normalize();
    const x = new THREE.Vector3().crossVectors(y, z).normalize();
    return { x, y, z };
  }

  function levelForward() {
    const f = new THREE.Vector3();
    camera.getWorldDirection(f);
    f.y = 0;
    if (f.lengthSq() < 1e-9) f.set(0, 0, -1);
    return f.normalize();
  }

  // Held ready: the point straight down and the haft back towards the person,
  // in the plane they face.
  function readyPose() {
    const f = levelForward();
    const up = new THREE.Vector3(0, 1, 0);
    const k = new THREE.Vector3().crossVectors(up, f).normalize();
    const into = new THREE.Vector3(0, -1, 0);
    const xw = new THREE.Vector3().crossVectors(into, k).normalize();
    const { x, y, z } = world.held.axes;
    const toWorld = new THREE.Matrix4().makeBasis(xw, into, k);
    const fromLocal = new THREE.Matrix4().makeBasis(x, y, z).transpose();
    const q = new THREE.Quaternion().setFromRotationMatrix(toWorld.multiply(fromLocal));
    const right = new THREE.Vector3().crossVectors(f, up).normalize();
    const grip = camera.position.clone().addScaledVector(f, READY.out)
      .addScaledVector(up, -READY.down).addScaledVector(right, READY.right);
    return { hand: [grip.x, grip.y, grip.z], hand_q: [q.w, q.x, q.y, q.z] };
  }

  async function takeUp(profile) {
    let point = null;
    try {
      const answer = await act("tool_points", {});
      point = (answer.tool_points || []).find((p) => p.body === profile.tool && p.attached) || null;
    } catch (error) {
      say("bad", String(error.message || error));
      return;
    }
    if (!point) {
      say("world", `${profile.object} has no point that can go into the ground any more.`);
      return;
    }
    try {
      await act("wield", { name: profile.tool, grip: point.grip });
    } catch (error) {
      say("bad", String(error.message || error));
      return;
    }
    const entry = world.bodies.get(profile.tool);
    world.held = { name: profile.tool, pick: profile, point, axes: axesOf(point), distance: 1 };
    world.use = { mode: "tool-lifting", name: profile.object, kg: entry ? entry.mass : 0,
                  result: "", detail: "", target: null, down: false, stop: false,
                  liftTo: [point.grip[0], point.grip[1] + LIFT_M, point.grip[2]],
                  since: performance.now() };
    askedAt = 0;
    $("crosshair").classList.add("holding");
    $("label").hidden = true;
    remember(`took up ${profile.object} by its grip`);
    say("you", `Took up ${profile.object} by the grip. The ring on the ground shows where it will`
      + ` come down: click to use it there, and hold the button to keep going.`);
    showUse();
  }

  // Each frame while a tool is held ready: what the server says it does where
  // the crosshair meets the ground, and the ring drawn there. Asking never does
  // anything to the room.
  let asking = false, askedAt = 0, askedFor = null;
  function followAim() {
    const held = world.held, use = world.use;
    if (!held || !held.pick) { ring.visible = false; return; }
    if (use.mode !== "tool-ready" || asking) return;
    const at = world.groundAim;
    const now = performance.now();
    const moved = (!askedFor) !== (!at)
      || (at && askedFor && Math.hypot(at[0] - askedFor[0], at[2] - askedFor[2]) > 0.03);
    if (now - askedAt < ASK_EVERY_MS || (!moved && now - askedAt < 1500)) return;
    asking = true;
    askedAt = now;
    askedFor = at ? at.slice() : null;
    api("/api/world/tool", { session: world.session, person: whereIAm(), at_m: at || null })
      .then((answer) => {
        if (world.held !== held) return;
        use.target = answer;
        drawRing(use.mode === "tool-ready" ? answer : null);
        showUse();
      })
      .catch(() => { /* the next frame asks again */ })
      .finally(() => { asking = false; });
  }

  function drawRing(answer) {
    const r = answer && answer.ring;
    if (!r || !r.at_m) { ring.visible = false; return; }
    ring.material.color.setHex(RING[r.state] || RING.no);
    ring.position.set(r.at_m[0], r.at_m[1] + 0.012, r.at_m[2]);
    ring.visible = true;
  }

  // One use, the whole of it, done by the server with the bounded hand
  // (tool_use.run). From here the page stops holding the tool ready, so no
  // step of this page's can cancel the swing.
  async function useOnce() {
    const held = world.held, use = world.use;
    if (!held || !held.pick || use.mode !== "tool-ready") return;
    use.mode = "tool-working";
    use.result = "";
    ring.visible = false;
    showUse();
    let answer = null;
    try {
      answer = await api("/api/world/tool/use", { session: world.session, person: whereIAm(),
                                                  at_m: world.groundAim || null });
    } catch (error) {
      say("bad", String(error.message || error));
    }
    if (world.held !== held) return;          // put down meanwhile
    use.last = answer;                        // each stroke and how it ended (done)
    if (answer && answer.refused) {
      use.result = answer.refused;
      say("bad", `${answer.action}: ${answer.refused}`);
    } else if (answer) {
      use.result = answer.said;
      use.detail = answer.detail || "";
      say("world", answer.said + (answer.detail ? ` ${answer.detail}` : ""), answer.did);
      remember(`${answer.action}: ${answer.said}`);
    }
    if (answer && answer.carried) carryGround(answer.carried);
    use.mode = "tool-ready";
    askedAt = 0;                               // the ring asked for again at once
    showUse();
    // Held down, and the tool goes on while it is: again, where the crosshair
    // is now -- each use its own target, checked again before it is done --
    // once the hand has had it back in the ready pose a moment. Swung the
    // instant a use ended, it was swung from a tool still on its way back, and
    // a swing planned from a moving tool joins its path part way.
    if (use.down && !use.stop && answer && !answer.refused && answer.repeat) {
      setTimeout(() => { if (world.held === held && use.down && !use.stop) useOnce(); }, REPEAT_AFTER_MS);
    }
  }

  // The primary button: down uses it, and holding it goes on; up lets it stop
  // after the use in hand. The secondary stops it too. None of them ever puts
  // the tool down: E does.
  function press() {
    const use = world.use;
    if (!use || !world.held || !world.held.pick) return;
    use.down = true;
    use.stop = false;
    if (use.mode === "tool-ready") useOnce();
  }
  function release() { if (world.use) world.use.down = false; }
  function stop() { if (world.use) { world.use.stop = true; world.use.down = false; } }

  // Where the hand is sent with each step: held ready while nothing is being
  // done; while the server works it, nothing -- the hand is the engine's stroke.
  function hand() {
    const held = world.held, use = world.use;
    if (!held || !held.pick) return { hand: null, hand_q: null };
    if (use.mode === "tool-lifting") {
      // Straight up, turned as it lay (no wrist wish sent): the point leaves
      // the ground before anything swings it round.
      if (performance.now() - use.since < LIFT_MS) return { hand: use.liftTo, hand_q: null };
      use.mode = "tool-ready";
      showUse();
    }
    if (use.mode !== "tool-ready") return { hand: null, hand_q: null };
    return readyPose();
  }

  // After every step: what the person carries.
  function follow(state) {
    if (state.carried) carryGround(state.carried);
  }

  async function putDown(text) {
    world.held = null;
    world.use = { mode: "none" };
    ring.visible = false;
    $("crosshair").classList.remove("holding");
    showUse();
    try { await act("release"); } catch (error) { say("bad", String(error.message || error)); }
    if (text) say("you", text);
  }

  return { profileOf, nearTool, takeUp, press, release, stop, hand, follow, followAim, putDown };
}
