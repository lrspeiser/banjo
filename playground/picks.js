// A tool that digs, by its profile: swing-and-lever (docs/interaction-profiles.md).
//
// Taking up any part of it takes the tool by the grip its point was given with
// (docs/ground-work.md). The bounded hand -- 800 N, and a 60 N m wrist -- holds
// it ready in front of the person, point down and haft back towards them. A
// click swings it: the ENGINE plans and makes the stroke -- raised back over
// the shoulder, round it, and down so the point meets the ground where the
// crosshair is, along its own axis -- and the ground decides how far it goes
// in: ground-work-v1, from the soil's own materials, in the solver. The right
// mouse button levers a point that is in: turned about where it went in, then
// drawn up out of the ground; what the pry breaks loose goes out through the
// ground's own dig and is carried. Nothing here is a speed or a depth: this
// file only says where the person is, where they aim, and what came back.

import * as THREE from "/vendor/three.module.js";

// The person's shoulder is 0.17 m under their eyes (1.62 m eyes, 1.45 m
// shoulder), and the grip is held ready half a metre out and down from the eyes
// and a little to the right.
const SHOULDER_BELOW_EYES_M = 0.17;
const READY = { out: 0.55, down: 0.5, right: 0.18 };
// How far in front of them, level, a pick can be brought down: a haft and an
// arm's length at most, and not at their own feet.
const REACH_M = { least: 0.5, most: 2.0 };
// A pry that does not bring the point out by its own lift is drawn straight up.
const PULL_M = 0.4;

export function makePicks(ctx) {
  const { world, act, say, remember, showUse, camera, carryGround, $ } = ctx;

  function profileOf(name) {
    return (world.tools || []).find((p) => p.parts.includes(name)) || null;
  }

  // The tool's own axes, as the engine's strike planner takes them: its point
  // (y), square to its point and its haft (z), and the third (x) -- in the
  // body's own frame. From the engine's local numbers where the reply carries
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
  // in the plane they face -- the pose the engine plans a swing from.
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

  function shoulder() {
    const eye = camera.position;
    return [eye.x, eye.y - SHOULDER_BELOW_EYES_M, eye.z];
  }

  // What a meeting of the point with the ground came to, in the engine's numbers.
  function words(w) {
    if (w.kind === "stopped" || w.kind === "not supported" || w.kind === "glanced") {
      return w.why ? `${w.why[0].toUpperCase()}${w.why.slice(1)}.` : `It ${w.kind} on the ${w.ground}.`;
    }
    let out = `The point went ${Math.round(1000 * w.depth_m)} mm into the ${w.ground}, arriving at`
      + ` ${w.closing_speed_m_s.toFixed(1)} m/s: the ground took ${w.work_j.toFixed(1)} J, at most`
      + ` ${Math.round(w.peak_force_n)} N`;
    const litres = 1000 * ((w.loosened && w.loosened.sand_m3) || 0)
      + 1000 * ((w.loosened && w.loosened.soil_m3) || 0);
    if (!w.open && litres > 0) {
      out += `. The pry broke out ${litres.toFixed(2)} L of ${w.ground}`
        + ` (${(w.loosened_kg || 0).toFixed(2)} kg), and you carry it`;
    } else if (!w.open) {
      out += ". It came out without breaking anything out";
    }
    return `${out}.`;
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
    world.use = { mode: "pick-ready", name: profile.object, kg: entry ? entry.mass : 0,
                  result: "", work: null };
    $("crosshair").classList.add("holding");
    $("label").hidden = true;
    remember(`took up ${profile.object} by its grip`);
    say("you", `Took up ${profile.object} by the grip. Aim at the ground a metre or so in front of`
      + ` you and click to swing it; with its point in, right-click levers it out.`);
    showUse();
  }

  async function swing() {
    const held = world.held, use = world.use;
    if (!held || !held.pick || use.mode !== "pick-ready") return;
    const at = world.groundAim;
    if (!at) {
      use.result = "Point the crosshair at the ground: the point comes down where it is.";
      showUse();
      return;
    }
    const eye = camera.position;
    const level = Math.hypot(at[0] - eye.x, at[2] - eye.z);
    if (level > REACH_M.most || level < REACH_M.least) {
      use.result = level > REACH_M.most
        ? `That is ${level.toFixed(1)} m away: step closer. A pick comes down about a haft and an`
          + ` arm in front of you.`
        : "That is at your feet: aim a little further out.";
      showUse();
      return;
    }
    const from = shoulder();
    Object.assign(use, { mode: "striking", result: "", work: null, stroking: false,
                         since: performance.now(), shoulder: from });
    starting();
    showUse();
    try {
      await act("strike", { at: [at[0], at[1], at[2]], shoulder: from, speed_m_s: 4, raise_deg: 110 });
      remember(`swung ${held.pick.object} at [${at[0].toFixed(1)}, ${at[2].toFixed(1)}]`);
    } catch (error) {
      use.mode = "pick-ready";
      use.result = String(error.message || error);
      say("bad", use.result);
      showUse();
    }
  }

  async function lever() {
    const held = world.held, use = world.use;
    if (!held || !held.pick || use.mode !== "pick-in") return;
    Object.assign(use, { mode: "levering", stroking: false, since: performance.now() });
    showUse();
    try {
      await act("strike", { lever: true, shoulder: use.shoulder || shoulder(), speed_m_s: 1.2,
                            lever_deg: 40 });
      remember(`levered ${held.pick.object}`);
    } catch (error) {
      use.mode = "pick-in";
      say("bad", String(error.message || error));
      showUse();
    }
  }

  async function pullOut(grip) {
    const use = world.use;
    Object.assign(use, { mode: "pulling", stroking: false, since: performance.now() });
    showUse();
    try {
      await act("stroke", { path: [grip, [grip[0], grip[1] + PULL_M, grip[2]]], speed_m_s: 0.6,
                            accel_m_s2: 4, lead_m: 0.05, let_go: false, give_up_s: 3 });
    } catch (error) {
      use.mode = "pick-ready";
      say("bad", String(error.message || error));
      showUse();
    }
  }

  async function putDown(text) {
    world.held = null;
    world.use = { mode: "none" };
    $("crosshair").classList.remove("holding");
    showUse();
    try { await act("release"); } catch (error) { say("bad", String(error.message || error)); }
    if (text) say("you", text);
  }

  // Where the hand is sent with each step: held ready by the page; during a
  // swing, a lever or a pull the hand is the engine's stroke and nothing is
  // sent; once a blow has landed it holds where the grip is.
  function hand() {
    const held = world.held, use = world.use;
    if (!held || !held.pick) return { hand: null, hand_q: null };
    if (use.mode === "pick-ready") return readyPose();
    if (use.mode === "pick-in" && held.holdAt) return { hand: held.holdAt, hand_q: null };
    return { hand: null, hand_q: null };
  }

  // Each meeting said once, however many replies carry it.
  function tell(use, w) {
    const key = `${w.point}|${w.at_s}|${w.kind}|${w.open}`;
    if (!use.said) use.said = new Set();
    if (use.said.has(key)) return;
    use.said.add(key);
    const text = words(w);
    say("world", text);
    remember(text);
  }

  const NOTES = ["stopped", "glanced", "not supported"];
  let lastT = null;

  // After every step: what the point met, and whether the engine's stroke is over.
  function follow(state) {
    const held = world.held, use = world.use;
    if (state.carried) carryGround(state.carried);
    if (typeof state.t === "number") lastT = state.t;
    if (!held || !held.pick) return;
    for (const w of state.ground_work || []) {
      if (w.tool !== held.name) continue;
      // A note left open from an earlier swing -- stopped on rock, say -- is
      // not what this one met.
      if (NOTES.includes(w.kind) && use.fromT != null && w.at_s < use.fromT) continue;
      use.work = w;
      // A meeting that is over is in one reply only: said as it closes.
      if (!w.open && (w.kind === "broke out" || w.kind === "pulled out")) tell(use, w);
    }
    const moving = ["striking", "levering", "pulling"].includes(use.mode);
    if (!moving) return;
    const h = state.hand || {};
    if (h.stroking) { use.stroking = true; return; }
    // Over: it was seen going, or long enough has passed that it never went.
    if (!use.stroking && performance.now() - use.since < 1500) return;
    const w = use.work;
    const inGround = !!(w && w.open && (w.kind === "in the ground" || w.kind === "broke out"));
    if (use.mode === "striking") {
      if (inGround) {
        held.holdAt = h.grip_m || null;
        use.mode = "pick-in";
        use.result = `${words(w)} Right-click to lever it out.`;
        tell(use, w);
      } else {
        use.mode = "pick-ready";
        use.result = w ? words(w) : "It met no ground.";
        if (w) tell(use, w); else say("world", use.result);
      }
    } else if (use.mode === "levering" && inGround && h.grip_m) {
      pullOut(h.grip_m);
      return;
    } else {
      held.holdAt = null;
      use.mode = "pick-ready";
      use.result = w ? words(w) : "";
    }
    showUse();
  }

  // When a stroke is asked for: meetings that were already noted before it are
  // not what it met.
  function starting() {
    world.use.fromT = lastT;
  }

  return { profileOf, takeUp, swing, lever, putDown, hand, follow };
}
