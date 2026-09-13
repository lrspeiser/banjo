// Edges, the grip that swings them, and what they cut. docs/cutting-model.md.
//
// Nothing in this file decides anything about physics. The engine owns the
// edge, the grip and every cut; this draws what the engine reports, and turns
// where you are looking into where the hand wants the grip to be and which way
// it wants the blade to face. Whether the blade gets there -- how fast, and
// whether what is in the way slows it, turns it or stops it -- is the engine's
// answer, with a hand that has 800 N and 60 N m and nothing more.
import * as THREE from "/vendor/three.module.js";

const V = (a) => new THREE.Vector3(a[0], a[1], a[2]);

// Every edge in the room, as the engine last reported them. Only sent when the
// SET changes, because each edge rides on its body's pose and its own local
// frame is all that is needed to draw it from then on.
const edges = { list: [], said: new Set(), noted: new Map() };

export function rememberBlades(state) {
  if (state && Array.isArray(state.blades)) edges.list = state.blades;
}

export function bladeFor(name) {
  return edges.list.find((b) => b.body === name && b.attached !== false) || null;
}

// Which way the edge faces, relative to the view, in each stance. The blade
// points where you look; right-click turns it a quarter about its own length.
// Facing left and swung left, the edge leads. Facing up or down and swung
// sideways, the FLAT leads -- which is how a flat strike is made.
export const STANCES = [
  { name: "left", facing: [-1, 0, 0] },
  { name: "down", facing: [0, -1, 0] },
  { name: "right", facing: [1, 0, 0] },
  { name: "up", facing: [0, 1, 0] },
];

// Where the hand holds the grip, in the view's own frame -- a little right and
// a little down, at the reach it was taken up at -- and which way the blade
// points from it: forward, tipped up and in so the edge crosses the middle of
// the view about a metre out.
const GRIP_RIGHT = 0.16, GRIP_DOWN = -0.24;
const POINTING = new THREE.Vector3(-0.15, 0.22, -1.0).normalize();
// How quickly the hand comes round to the stance after taking hold or turning
// the edge. It is only how fast the hand ASKS; the blade gets there as fast as
// the engine's bounded hand can take it. Turning the view is not eased at all:
// the hand's aim is held in the view's frame, so a turn is a swing at once.
const SETTLE_S = 0.25;

// The edge's own axes in the body's frame, from the engine's declaration:
// along the edge from heel to tip, the way it faces, and the flat's normal.
function edgeFrame(blade) {
  const along = V(blade.tip_local).sub(V(blade.heel_local)).normalize();
  const faced = V(blade.facing_local);
  const facing = faced.sub(along.clone().multiplyScalar(faced.dot(along))).normalize();
  const flat = new THREE.Vector3().crossVectors(along, facing);
  return { along, facing, flat };
}

// The body's orientation, relative to the view, that puts the edge where the
// stance says. R L = W for the two orthonormal, right-handed frames, so R = W L^T.
function stanceInView(blade, stance) {
  const { along, facing, flat } = edgeFrame(blade);
  const wantAlong = POINTING.clone();
  const which = STANCES[((stance % STANCES.length) + STANCES.length) % STANCES.length];
  const wish = V(which.facing);
  const wantFacing = wish.sub(wantAlong.clone().multiplyScalar(wish.dot(wantAlong))).normalize();
  const wantFlat = new THREE.Vector3().crossVectors(wantAlong, wantFacing);
  const local = new THREE.Matrix4().makeBasis(along, facing, flat);
  const view = new THREE.Matrix4().makeBasis(wantAlong, wantFacing, wantFlat);
  return new THREE.Quaternion().setFromRotationMatrix(view.multiply(local.transpose()));
}

// Taking hold: the hand starts where the grip already is, turned the way the
// blade already is, both in the view's frame, and comes round from there.
export function takeHold(camera, entry, blade, reach) {
  camera.updateMatrixWorld();
  const grip = entry.mesh.localToWorld(V(blade.grip_local));
  const inverse = camera.quaternion.clone().invert();
  return {
    reach,
    stance: 0,
    gripView: camera.worldToLocal(grip.clone()),
    turnView: inverse.multiply(entry.mesh.quaternion.clone()),
  };
}

// What the hand wants this tick: the grip's place in the world, and the body
// orientation as [w, x, y, z]. `hold` is updated in place.
export function handTarget(camera, blade, hold, dt) {
  const ease = 1 - Math.exp(-Math.max(0, dt) / SETTLE_S);
  hold.gripView.lerp(new THREE.Vector3(GRIP_RIGHT, GRIP_DOWN, -hold.reach), ease);
  hold.turnView.slerp(stanceInView(blade, hold.stance), ease);
  const grip = hold.gripView.clone().applyQuaternion(camera.quaternion).add(camera.position);
  const turn = camera.quaternion.clone().multiply(hold.turnView);
  return { hand: [grip.x, grip.y, grip.z], hand_q: [turn.w, turn.x, turn.y, turn.z] };
}

// Mark the edge and the grip on the body that carries them. Drawn as children
// of the body's own mesh, so they ride its pose with no traffic; redrawn only
// when the mesh is rebuilt.
const EDGE_LOOK = new THREE.LineBasicMaterial({ color: 0xfff0c2 });
const GRIP_LOOK = new THREE.MeshStandardMaterial({ color: 0x4b2e1b, roughness: 0.92, metalness: 0.0 });

export function dressBlades(bodies) {
  for (const blade of edges.list) {
    const entry = bodies.get(blade.body);
    if (!entry || entry.dressedMesh === entry.mesh) continue;
    const { along, facing, flat } = edgeFrame(blade);
    const heel = V(blade.heel_local), tip = V(blade.tip_local);
    // The edge, a hair proud of the steel so it is not buried in it.
    const lift = facing.clone().multiplyScalar(0.0015);
    entry.mesh.add(new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([heel.clone().add(lift), tip.clone().add(lift)]),
      EDGE_LOOK));
    // The grip: a wrap round where the hand holds it. Only a marking -- the
    // matter there is the body's own, and so is its mass.
    const wrap = new THREE.Mesh(
      new THREE.BoxGeometry(0.11, 1.6 * (blade.thickness_m || 0.01), 0.036), GRIP_LOOK);
    wrap.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(along, flat, facing));
    wrap.position.copy(V(blade.grip_local));
    entry.mesh.add(wrap);
    entry.dressedMesh = entry.mesh;
  }
}

// Where a blade has been through something: a dark slit along each strip the
// edge swept, in the plane it swept, a little proud of the swept region so it
// shows where the cut meets the surface. Drawn from the engine's own record of
// the kerf -- a partial cut is drawn partial because it IS partial.
const KERF_LOOK = new THREE.MeshBasicMaterial({ color: 0x160b06 });

export function showKerfs(entry, body) {
  const kerfs = body.kerfs || [];
  const key = kerfs.length ? JSON.stringify(kerfs) : "";
  if (entry.kerfKey === key && entry.kerfMesh === entry.mesh) return;
  if (entry.kerfGroup) {
    entry.kerfGroup.parent?.remove(entry.kerfGroup);
    entry.kerfGroup.traverse((o) => o.geometry && o.geometry.dispose());
    entry.kerfGroup = null;
  }
  entry.kerfKey = key;
  entry.kerfMesh = entry.mesh;
  if (!kerfs.length) return;
  const group = new THREE.Group();
  for (const kerf of kerfs) {
    const at = V(kerf.at), along = V(kerf.along), facing = V(kerf.facing), normal = V(kerf.normal);
    const turn = new THREE.Quaternion().setFromRotationMatrix(
      new THREE.Matrix4().makeBasis(along, facing, normal));
    const thick = Math.max(0.002, 0.6 * (kerf.thickness_m || 0.01));
    // Neighbouring strips that reach the same depth are one slit.
    const runs = [];
    for (const [u0, u1, v0, v1] of kerf.strips || []) {
      const last = runs[runs.length - 1];
      if (last && Math.abs(last.u1 - u0) < 1e-6 && Math.abs(last.v0 - v0) < 0.001 &&
          Math.abs(last.v1 - v1) < 0.001) {
        last.u1 = u1;
      } else {
        runs.push({ u0, u1, v0, v1 });
      }
    }
    for (const run of runs) {
      const pad = 0.003;
      const slit = new THREE.Mesh(
        new THREE.BoxGeometry(run.u1 - run.u0 + pad, run.v1 - run.v0 + pad, thick), KERF_LOOK);
      slit.position.copy(at.clone()
        .addScaledVector(along, (run.u0 + run.u1) / 2)
        .addScaledVector(facing, (run.v0 + run.v1) / 2));
      slit.quaternion.copy(turn);
      group.add(slit);
    }
  }
  entry.mesh.add(group);
  entry.kerfGroup = group;
}

// What each meeting between an edge and something was, said once when it is
// over. The engine sends a finished meeting exactly once; the set is a guard.
export function narrateCuts(cuts, say, remember) {
  for (const cut of cuts || []) {
    if (cut.open) continue;
    const key = `${cut.blade}|${cut.target}|${cut.at_s}|${cut.kind}`;
    if (edges.said.has(key)) continue;
    edges.said.add(key);
    if (edges.said.size > 400) edges.said.clear();
    const owner = edges.list.find((b) => b.id === cut.blade);
    const blade = owner ? owner.body : "blade";
    const speed = Number(cut.speed_m_s || 0).toFixed(1);
    const bit = ["edge", "slice", "press", "glancing"].includes(cut.kind) && cut.area_mm2 > 0;
    // A blade lying against something bumps it again and again, and every
    // bump is a meeting of its own. A flat or a point is said once, not each
    // time -- a cut is always said.
    if (!bit) {
      const pair = `${cut.blade}|${String(cut.target).replace(/ piece \d+$/, "")}|${cut.kind}`;
      const now = performance.now();
      if (now - (edges.noted.get(pair) ?? -1e9) < 2500) continue;
      edges.noted.set(pair, now);
    }
    if (bit) {
      const how = cut.kind === "press" ? "pressed in" : cut.kind === "slice" ? "sliced"
                : cut.kind === "glancing" ? "glanced in" : "struck edge-first";
      let said = `The ${blade} ${how} at ${speed} m/s and cut ${Math.round(cut.area_mm2)} mm² of`
        + ` ${cut.target} for ${Number(cut.work_j).toFixed(2)} J`
        + ` (it resists with ${(cut.resistance_j_m2 / 1000).toFixed(1)} kJ/m²)`;
      if (cut.links > 0) said += ` — the rope parted`;
      if (cut.separated) said += ` — it came apart in ${cut.pieces}`;
      else if (!cut.links) said += ` — a partial cut, and it stays one`;
      say("world", said + ".");
      remember(`the ${blade} cut ${cut.target}${cut.separated ? " through" : ""}`);
    } else if (cut.kind === "flat" && cut.speed_m_s > 0.3) {
      say("world", `The flat of the ${blade} struck ${cut.target} at ${speed} m/s. A flat does not cut.`);
    } else if (cut.kind === "point" && cut.speed_m_s > 0.3) {
      say("world", `The point of the ${blade} met ${cut.target}: a thrust, which this engine`
        + ` does not model as piercing.`);
    } else if (cut.kind === "glancing" && cut.speed_m_s > 0.3) {
      say("world", `The edge glanced off ${cut.target}: it met the surface too shallow to bite.`);
    } else if (cut.kind === "blunt") {
      say("world", `The edge cannot cut ${cut.target}: it is at least as hard as the ${blade}.`);
    } else if (cut.kind === "brittle") {
      say("world", `${cut.target} is brittle. An edge does not cut it; a hard enough blow cracks it.`);
    }
  }
}
