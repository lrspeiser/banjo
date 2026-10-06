// Using a tool, the same way for every tool.
//
// The server (tool_use.py) says what the tool in hand does where the crosshair
// meets the ground -- its action and label, whether it can be done there and
// why not, and possible materials -- and does it when the button is pressed: the
// shared short contact stroke (or an explicitly authored full swing), each
// stroke the engine's. This page only holds the tool ready, shows material previews,
// sends the click and says what came of it. It never knows a tool's steps, so
// a new kind of tool needs nothing here (the owner: "make sure this is designed
// to be a generic capability, so if I build a hoe or an axe it will have the
// same capabilities"). How it is used -- what the click is called, how the hand
// uses it -- is its profile's `use`, which the room's chat may shape.
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
// The target preview follows the crosshair at up to five answers a second, one in flight.
const ASK_EVERY_MS = 200;
// Taken up from where it lies, a tool is first lifted straight up by its grip,
// turned as it lay, and only then brought round into the ready pose. Brought
// round at once, its point was swung through the ground on the way: on the
// owner's sim, "The point went 103 mm into the sand, arriving at 0.6 m/s ...
// The pry broke out 26.70 L" before they had swung it at all, and then the
// point was left 197 mm into the soil.
const LIFT_M = 0.6;
const LIFT_MS = 200;
export function makeTools(ctx) {
  const { world, act, api, say, remember, showUse, camera, carryGround, scene, whereIAm,
          lastAction, takeIntoHand, showHolding, showNotebook, showInventory } = ctx;

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
    if (!point.grip_body && point.pointing_local && point.tip_local && point.grip_local) {
      pointing = new THREE.Vector3(...point.pointing_local);
      tip = new THREE.Vector3(...point.tip_local);
      grip = new THREE.Vector3(...point.grip_local);
    } else {
      const entry = world.bodies.get(point.grip_body || point.body);
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

  // The tool's point as the engine has it now, still attached: what the tool is
  // held by, and ready from.
  async function pointOf(profile) {
    try {
      const answer = await act("tool_points", {});
      const point = (answer.tool_points || []).find((p) => (p.grip_body || p.body) === profile.tool
        && p.attached && p.grip_connected !== false) || null;
      if (!point) lastAction(`${profile.object} has no point that can go into the ground any more.`, "refused");
      return point;
    } catch (error) {
      say("bad", String(error.message || error));
      return null;
    }
  }

  // E on a tool, or beside one: taken up by its handle through the record
  // (world.js takeIntoHand), so what the hand holds is what the person has --
  // the server's hand grips it there, and the page holds it ready (adopt). A
  // tool the record does not keep is gripped by the page's own hand, as it
  // always was.
  async function takeUp(profile) {
    const point = await pointOf(profile);
    if (!point) return;
    const took = takeIntoHand ? await takeIntoHand(profile.tool, point) : "not kept";
    if (took !== "not kept") return;          // held and made ready, or refused with why
    try {
      await act("wield", { name: profile.tool, grip: point.grip });
    } catch (error) {
      say("bad", String(error.message || error));
      return;
    }
    hold(profile, point);
  }

  // A tool the server's hand already holds -- taken up through the record by its
  // handle (`point`), or out of the bag, gripped by its middle: held by its
  // handle from here, lifted, and made ready.
  async function adopt(profile, point) {
    if (!point) {
      point = await pointOf(profile);
      if (!point) return;
      try {
        await act("wield", { name: profile.tool, grip: point.grip });
      } catch (error) {
        say("bad", String(error.message || error));
        return;
      }
    }
    hold(profile, point);
  }

  function hold(profile, point) {
    world.held = { name: profile.tool, pick: profile, point, axes: axesOf(point), distance: 1 };
    const kg = [...new Set(profile.parts || [profile.tool])]
      .reduce((total, name) => total + (world.bodies.get(name)?.mass || 0), 0);
    world.use = { mode: "tool-lifting", name: profile.object, kg,
                  result: "", detail: "", target: null, down: false, stop: false,
                  liftTo: [point.grip[0], point.grip[1] + LIFT_M, point.grip[2]],
                  since: performance.now() };
    askedAt = 0;
    showHolding(true);
    remember(`took up ${profile.object} by its grip`);
    lastAction(`Took up ${profile.object}. Point at ground to preview materials; click or hold to dig.`);
    showUse();
  }

  // Each frame while a tool is held ready: what the server says it does where
  // the crosshair meets the ground, and possible materials there. Asking never does
  // anything to the room.
  let asking = false, askedAt = 0, askedFor = null, askedName = null, askedEyes = null, askedContext = null;
  function followAim() {
    const held = world.held, use = world.use;
    if (!held || !held.pick) { return; }
    if (use.mode !== "tool-ready" || asking) return;
    const name = world.aim?.name || null;
    const at = name ? world.aim.point_m : world.groundAim;
    const person=whereIAm(), eyes=person.eyes_m;
    const context=ctx.targetContext?.(at,name) ?? null;
    const now = performance.now();
    const moved = name !== askedName || (!askedFor) !== (!at)
      || (at && askedFor && Math.hypot(...at.map((v, i) => v - askedFor[i])) > 0.03)
      || !askedEyes || Math.hypot(...eyes.map((v,i)=>v-askedEyes[i]))>.03
      || context!==askedContext;
    if (now - askedAt < ASK_EVERY_MS || (!moved && now - askedAt < 1500)) return;
    asking = true;
    askedAt = now;
    askedFor = at ? at.slice() : null;
    askedName = name;
    askedEyes=eyes.slice();
    askedContext=context;
    api("/api/world/tool", { session: world.session, person, at_m: at || null, target_name: name })
      .then((answer) => {
        if (world.held !== held) return;
        const currentName = world.aim?.name || null;
        const currentAt = currentName ? world.aim.point_m : world.groundAim;
        if (currentName !== name || (!currentAt) !== (!at)
          || (currentAt && at && Math.hypot(...currentAt.map((v, i) => v - at[i])) > 0.03)
          || Math.hypot(...whereIAm().eyes_m.map((v,i)=>v-eyes[i]))>.03
          || (ctx.targetContext?.(currentAt,currentName) ?? null)!==context) return;
        use.target = {...answer,observed_from_m:eyes.slice(),observed_at_m:at?.slice() || null,
          observed_name:name,observed_context:context};
        showUse();
      })
      .catch(() => { /* the next frame asks again */ })
      .finally(() => { asking = false; });
  }

  // One use, the whole of it, done by the server with the bounded hand
  // (tool_use.run). From here the page stops holding the tool ready, so no
  // step of this page's can cancel the swing. What it came to is said in the
  // side view's details (lastAction), not the chat.
  function sightInput() {
    const direction=ctx.aimVector?.() || camera.getWorldDirection(new THREE.Vector3());
    return {from:camera.position.toArray(),dir:direction.toArray()};
  }
  async function useOnce(input) {
    const held = world.held, use = world.use;
    if (!held || !held.pick || use.mode !== "tool-ready") return;
    use.mode = "tool-working";
    use.startedAt = performance.now();
    use.shownReceipts=new Set();
    use.result = "";

    showUse();
    let answer = null;
    let struckAt=null;
    try {
      const enabled=localStorage.getItem('banjo.energy-assist')==='on';
      const pendingKey=`banjo.cut-pending.${new URLSearchParams(location.search).get('world') || 'lab'}`;
      let pending;
      try { pending=JSON.parse(localStorage.getItem(pendingKey) || 'null'); } catch { pending=null; }
      if(pending && !enabled)throw Error('A cutting reply is pending. Turn Energy assist on to retry the same cut.');
      // Explicit taps retain their clicked ray even if the cursor moves while
      // another stroke finishes. Held repeats sample the current cursor ray.
      // Sidebar actions retain the displayed point, not the camera centre.
      // A retained cut owns its target. A new ray must not turn an uncertain
      // ground debit into an unrelated object-contact request.
      const hit = pending ? {hit:true,point_m:pending.at_m,name:null}
        : input.at_m ? {hit:true,point_m:input.at_m,name:input.target_name}
        : await act("pick", {...input,max_m:40,past_held:true});
      if(!pending && hit.hit && !hit.name && ctx.groundTargetPoint)hit.point_m=ctx.groundTargetPoint(hit.point_m,input.from);
      struckAt=hit.hit ? hit.point_m : null;
      const assist=enabled && hit.hit && !hit.name;
      // Retry exactly the retained target after a missing response. A second
      // click cannot spend another reservation on an uncertain first cut.
      if(assist && !pending) {
        pending={request_id:crypto.randomUUID().replaceAll('-',''),at_m:hit.point_m.slice()};
        localStorage.setItem(pendingKey,JSON.stringify(pending));
      }
      answer = await api("/api/world/tool/use", { session: world.session, person: whereIAm(),
        at_m: assist?pending.at_m:(hit.hit?hit.point_m:null),
        target_name: hit.hit ? hit.name || null : null,
        energy_assist:assist,request_id:assist?pending.request_id:null });
      // A preflight refusal may follow an uncertain paid attempt. Only an
      // authoritative cut receipt resolves that retained request.
      if(assist && answer.cut && typeof answer.cut==='object')localStorage.removeItem(pendingKey);
    } catch (error) {
      use.result = String(error.message || error);
      say("bad", String(error.message || error));
    }
    // A finished stroke can carry a newer personal journal, even if the
    // player has since put down the tool. Do not wait for another live step.
    if (answer?.notebook) showNotebook(answer.notebook, true);
    if (answer?.ground_debris) ctx.followMatter?.(answer.ground_debris);
    if (answer?.goods) ctx.followGoods?.(answer.goods);
    if (answer?.inventory) {
      world.inventory = answer.inventory;
      showInventory?.();
    }
    if (world.held !== held) return;          // put down meanwhile
    use.last = answer;                        // each stroke and how it ended (done)
    if (answer && answer.refused) {
      use.result = answer.refused;
      lastAction(`${answer.action}: ${answer.refused}`, "refused");
    } else if (answer) {
      use.result = answer.said;
      use.detail = answer.detail || "";
      const brief=ctx.summarizeToolResult?.(answer) || answer.said;
      lastAction(brief,"did",[brief!==answer.said ? answer.said : "",answer.detail].filter(Boolean).join(" "));
      remember(`${answer.action}: ${answer.said}`);
    }
    if (answer && answer.carried) carryGround(answer.carried);
    if(answer && struckAt) {
      const results=(answer.results?.length ? answer.results : answer.result?.point!=null ? [answer.result] : [])
        .filter(r=>!use.shownReceipts.has(`${r.point}:${r.at_s}`));
      if(results.length)ctx.showToolOutcome?.({...answer,results},struckAt);
      else if(!answer.results?.length && !use.shownReceipts.size)ctx.showToolOutcome?.(answer,struckAt);
    }
    if (answer?.result?.working_point_connected === false) {
      // A separated head ends this burst even if clicks were queued while the
      // native stroke ran. The retained grip part can still be inspected in Lab.
      use.stop = true; use.down = false; use.queued = 0; use.inputs=[];
      clearTimeout(use.timer); use.timer = null;
    }
    if (["contact", "object-contact"].includes(answer?.gesture) && !answer.refused) {
      use.positioned = true;
      use.rest=answer.rest_hand_m?.slice() || null;
      use.restEyes=whereIAm().eyes_m.slice();
    }
    use.mode = "tool-ready";
    askedAt = 0;                               // the ring asked for again at once
    showUse();
    // Explicit taps and held repeat share one scheduler. Never overlap native
    // uses or impose a flourish/pause after a completed contact stroke.
    if (!use.stop && answer && !answer.refused && (use.queued || (use.down && answer.repeat))) {
      schedule();
    } else if (answer?.refused) {
      use.queued = 0; use.inputs=[];
    }
  }

  function schedule() {
    const held = world.held, use = world.use;
    if (!use || use.timer || use.mode !== "tool-ready" || use.stop) return;
    const interval = 1000 / (use.target?.cadence_hz || 4);
    use.timer = setTimeout(() => {
      use.timer = null;
      if (world.held !== held || use.stop || (!use.queued && !use.down)) return;
      // Keyboard/mouse repeats follow the current sight. A finger tap keeps
      // its screen ray after release; sidebar actions keep their exact point.
      const waiting=use.queued ? use.inputs.shift() : null;
      const input=waiting?.at_m || waiting?.from ? waiting : sightInput();
      if (use.queued) use.queued--;
      useOnce(input);
    }, Math.max(0, interval - (performance.now() - (use.startedAt || 0))));
  }

  // The primary button: down uses it, and holding it goes on; up lets it stop
  // after the use in hand. The secondary stops it too. None of them ever puts
  // the tool down: E does.
  function press(target=null) {
    const use = world.use;
    if (!use || !world.held || !world.held.pick) return;
    use.down = true;
    use.stop = false;
    // At most ONE click waits while a swing is in hand: a newer click
    // replaces it. Up to 16 used to queue and play out one by one, seconds
    // behind the player and at old aims (the owner, 2026-10-04: "not queue
    // up way behind me").
    use.inputs=[target?.at_m ? {at_m:target.at_m.slice(),target_name:target.target_name || null}
      : target?.from && target?.dir ? {from:target.from.slice(),dir:target.dir.slice()} : {sight:true}];
    use.queued=1;
    if (use.mode === "tool-ready") schedule();
  }
  function release() { if (world.use) world.use.down = false; }
  function stop() { if (world.use) {
    world.use.stop = true; world.use.down = false; world.use.queued = 0; world.use.inputs=[];
    clearTimeout(world.use.timer); world.use.timer = null;
  } }

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
    if ((held.pick.use?.gesture || "contact") === "contact") {
      if (use.positioned) {
        const eyes=whereIAm().eyes_m;
        return {hand:use.rest?.map((v,i)=>v+eyes[i]-use.restEyes[i]) || null,hand_q:null};
      }
      // Previewing a target must not move a tool there. Carry in a fixed place
      // above terrain, preserving native orientation; only Use positions it.
      const eyes = whereIAm().eyes_m;
      return { hand: [eyes[0], eyes[1] - 0.5, eyes[2]], hand_q: null };
    }
    return readyPose();
  }

  // After every step: what the person carries.
  function follow(state, heldAtRequest = world.held) {
    if (state.carried) carryGround(state.carried);
    // A step can finish after pickup/equip changed the hand. Its bodies and
    // receipts still matter, but its older hand observation cannot release
    // the newly adopted grip. A later step can report a genuine release.
    if (world.held === heldAtRequest && world.held?.pick && state.hand && Object.hasOwn(state.hand, "holding")
        && state.hand.holding !== world.held.name) {
      const name = world.use.name || world.held.pick.object;
      stop();
      world.held = null;
      world.use = { mode: "none" };
      forget();
      showHolding(false);
      showUse();
      lastAction(`${name} left your hand. Move close to it and press E to take it up again.`, "refused");
      ctx.refreshInventory?.();
      return;
    }
    const use=world.use;
    if(use?.mode!=="tool-working" || !world.held?.pick)return;
    const rows=[];
    for(const r of [...(state.tool_outcomes || []),...(state.ground_work || [])]) {
      const key=`${r.point}:${r.at_s}`;
      if(r.open===false && r.tool===world.held.name && !use.shownReceipts.has(key)) {
        use.shownReceipts.add(key);rows.push(r);
      }
    }
    if(rows.length && rows.at(-1).at_m)
      ctx.showToolOutcome?.({result:rows.at(-1),results:rows},rows.at(-1).at_m);
  }

  async function putDown(text) {
    world.held = null;
    world.use = { mode: "none" };

    showHolding(false);
    showUse();
    try { await act("release"); } catch (error) { say("bad", String(error.message || error)); }
    if (text) lastAction(text);
  }

  // The tool has left the hand some other way -- set aside into the bag, or the
  // room opened again: refresh its target preview.
  function forget() { askedAt = 0; }

  return { profileOf, nearTool, takeUp, adopt, press, release, stop, hand, follow, followAim,
           putDown, forget };
}
