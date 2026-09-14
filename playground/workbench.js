// The workbench: a run the lab recorded, played back as a small copy on a
// bench in front of the person while the room goes on around it (the owner,
// 2026-09-13: recorded runs play "on a bench in front of you"). A recording is
// the lab's banjo.playback.v1, in SI units: its bodies once, then frames of
// where each one is and how it is turned. This file sets the bench down, draws
// the run on it and keeps the run's clock. What is on the bench is a picture of
// a run that has already happened: it is not in the engine, nothing in the
// room can touch it, and it never touches the room's bodies or the hand.
// world.js lists the runs and holds the controls.

import * as THREE from "/vendor/three.module.js";

// A table a person stands at, its top a little below the hip, set down far
// enough in front of them to be seen whole.
const BENCH = { width: 1.2, depth: 0.8, height: 0.9, top: 0.04, ahead: 1.5 };
// The share of the tabletop a run is fitted into, so nothing hangs off it.
const USABLE = 0.9;
// The run's own ground is drawn as a cloth this thick on the tabletop, so the
// two never draw into each other.
const CLOTH = 0.003;
const CUBE = new THREE.BoxGeometry(1, 1, 1);
const WOOD = new THREE.MeshStandardMaterial({ color: 0x6b4a2f, roughness: 0.85 });
const CLOTH_MATERIAL = new THREE.MeshStandardMaterial({ color: 0x28323a, roughness: 0.95 });

// A recorded colour, packed 0xRRGGBBAA: the colour, and how opaque it is.
function colourOf(rgba) {
  const v = Number(rgba) >>> 0;
  return { colour: new THREE.Color(v >>> 8), alpha: (v & 255) / 255 };
}

// The recording as numbers to copy: each frame holds every body's position and
// turn (x y z, then w x y z) at the body's slot. A body a frame leaves out
// stays where the frame before had it.
function framesOf(recording, slots) {
  const width = slots.size * 7;
  const frames = [];
  let before = null;
  for (const frame of recording.frames) {
    if (!frame || !Array.isArray(frame.poses)) continue;
    const at = before ? before.slice() : new Float32Array(width).fill(NaN);
    for (const pose of frame.poses) {
      const i = slots.get(String(pose.id)), p = pose.position_m, q = pose.orientation_wxyz;
      if (i === undefined || !Array.isArray(p) || !Array.isArray(q)) continue;
      const o = i * 7;
      at[o] = p[0]; at[o + 1] = p[1]; at[o + 2] = p[2];
      at[o + 3] = q[0]; at[o + 4] = q[1]; at[o + 5] = q[2]; at[o + 6] = q[3];
    }
    frames.push({ time: Number(frame.time_s) || 0, fractures: Number(frame.fracture_count) || 0, at });
    before = at;
  }
  return frames;
}

// Where the run's bodies go over the whole run: each body's own box, turned as
// it is turned, from the first frame to the last. The bench is fitted to all of
// them but the one in a hundred that go farthest on each side, so a few pieces
// thrown far are drawn off the bench's edge rather than shrinking the rest of
// the run to fit them in. A run of fewer than a hundred bodies leaves none out.
function reachOf(frames, halves, round) {
  const n = round.length;
  const x0 = new Float32Array(n).fill(Infinity), x1 = new Float32Array(n).fill(-Infinity);
  const z0 = new Float32Array(n).fill(Infinity), z1 = new Float32Array(n).fill(-Infinity);
  for (const { at } of frames) {
    for (let i = 0; i < n; ++i) {
      const o = i * 7, x = at[o], z = at[o + 2];
      if (!Number.isFinite(x) || !Number.isFinite(z)) continue;
      const hx = halves[i * 3], hy = halves[i * 3 + 1], hz = halves[i * 3 + 2];
      let ex = hx, ez = hx;
      if (!round[i]) {
        // How far the turned box reaches along x and along z.
        const w = at[o + 3], qx = at[o + 4], qy = at[o + 5], qz = at[o + 6];
        ex = Math.abs(1 - 2 * (qy * qy + qz * qz)) * hx + Math.abs(2 * (qx * qy - w * qz)) * hy
           + Math.abs(2 * (qx * qz + w * qy)) * hz;
        ez = Math.abs(2 * (qx * qz - w * qy)) * hx + Math.abs(2 * (qy * qz + w * qx)) * hy
           + Math.abs(1 - 2 * (qx * qx + qy * qy)) * hz;
      }
      if (x - ex < x0[i]) x0[i] = x - ex;
      if (x + ex > x1[i]) x1[i] = x + ex;
      if (z - ez < z0[i]) z0[i] = z - ez;
      if (z + ez > z1[i]) z1[i] = z + ez;
    }
  }
  const seen = [];
  for (let i = 0; i < n; ++i) if (Number.isFinite(x0[i])) seen.push(i);
  if (!seen.length) return null;
  const skip = Math.floor(seen.length / 100);
  const edge = (values, farthest) => seen.map((i) => values[i])
    .sort((a, b) => (farthest ? b - a : a - b))[skip];
  return { x0: edge(x0, false), x1: edge(x1, true), z0: edge(z0, false), z1: edge(z1, true) };
}

// The run's own ground, where it has one: the box its support triangles span,
// and the height of its top.
function floorOf(recording) {
  let floor = null;
  for (const triangle of Array.isArray(recording.supports) ? recording.supports : []) {
    for (const p of Array.isArray(triangle) ? triangle : []) {
      if (!Array.isArray(p) || !Number.isFinite(p[0]) || !Number.isFinite(p[2])) continue;
      floor = floor || { x0: Infinity, x1: -Infinity, z0: Infinity, z1: -Infinity, y: -Infinity };
      floor.x0 = Math.min(floor.x0, p[0]); floor.x1 = Math.max(floor.x1, p[0]);
      floor.z0 = Math.min(floor.z0, p[2]); floor.z1 = Math.max(floor.z1, p[2]);
      floor.y = Math.max(floor.y, Number.isFinite(p[1]) ? p[1] : 0);
    }
  }
  return floor;
}

export function makeWorkbench({ scene, camera, groundAt, api }) {
  const group = new THREE.Group();     // the bench, and the run on it
  group.name = "workbench";
  group.visible = false;
  scene.add(group);
  const top = new THREE.Mesh(new THREE.BoxGeometry(BENCH.width, BENCH.top, BENCH.depth), WOOD);
  top.position.y = BENCH.height - BENCH.top / 2;
  group.add(top);
  const legHeight = BENCH.height - BENCH.top;
  for (const [sx, sz] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
    const leg = new THREE.Mesh(new THREE.BoxGeometry(0.05, legHeight, 0.05), WOOD);
    leg.position.set(sx * (BENCH.width / 2 - 0.06), legHeight / 2, sz * (BENCH.depth / 2 - 0.06));
    group.add(leg);
  }
  const copy = new THREE.Group();      // the run, scaled onto the tabletop
  group.add(copy);

  let run = null, loading = null, asked = 0;
  let t = 0, playing = false, speed = 0.25, last = null, shown = "";
  const placing = new THREE.Object3D();
  const qa = new THREE.Quaternion(), qb = new THREE.Quaternion();

  function clear() {
    for (const mesh of run ? run.meshes : []) {
      if (mesh.geometry !== CUBE) mesh.geometry.dispose();
      if (mesh.material !== CLOTH_MATERIAL) mesh.material.dispose();
      if (mesh.isInstancedMesh) mesh.dispose();
    }
    copy.clear();
    run = null;
    shown = "";
  }

  function build(recording, title) {
    const bodies = Array.isArray(recording.bodies) ? recording.bodies : [];
    if (!bodies.length || !Array.isArray(recording.frames))
      throw new Error("that recording has no bodies and frames to play");
    const slots = new Map(bodies.map((b, i) => [String(b.id), i]));
    const frames = framesOf(recording, slots);
    if (!frames.length) throw new Error("that recording has no frames to play");
    const sizes = bodies.map((b) => (Array.isArray(b.dimensions_m) ? b.dimensions_m : []).map(Number));
    const round = Uint8Array.from(bodies, (b) => (b.shape === "sphere" ? 1 : 0));
    const halves = new Float32Array(bodies.length * 3);
    sizes.forEach((d, i) => {
      const w = d[0] > 0 ? d[0] : 0.02;
      halves[i * 3] = w / 2;
      halves[i * 3 + 1] = (d[1] > 0 ? d[1] : w) / 2;
      halves[i * 3 + 2] = (d[2] > 0 ? d[2] : w) / 2;
    });
    const reach = reachOf(frames, halves, round), floor = floorOf(recording);
    if (!reach) throw new Error("that recording never says where its bodies are");
    const scale = Math.min(1, USABLE * BENCH.width / (reach.x1 - reach.x0),
                              USABLE * BENCH.depth / (reach.z1 - reach.z0));
    clear();
    const meshes = [], whole = [], cellSlots = [];
    // The cells a breakable body is recorded as, all in one instanced mesh.
    bodies.forEach((b, i) => { if (String(b.id).startsWith("cell:")) cellSlots.push(i); });
    let cells = null;
    if (cellSlots.length) {
      cells = new THREE.InstancedMesh(CUBE, new THREE.MeshStandardMaterial({ roughness: 0.6 }),
                                      cellSlots.length);
      cellSlots.forEach((slot, k) => cells.setColorAt(k, colourOf(bodies[slot].color_rgba).colour));
      cells.instanceColor.needsUpdate = true;
      cells.frustumCulled = false;     // its pieces go wherever the run took them
      copy.add(cells);
      meshes.push(cells);
    }
    // Every other body whole, as the box or ball it was.
    bodies.forEach((b, i) => {
      if (String(b.id).startsWith("cell:")) return;
      const d = sizes[i];
      const geometry = b.shape === "sphere"
        ? new THREE.SphereGeometry((d[0] || 0.1) / 2, 24, 16)
        : new THREE.BoxGeometry(d[0] || 0.1, d[1] || d[0] || 0.1, d[2] || d[0] || 0.1);
      const { colour, alpha } = colourOf(b.color_rgba);
      const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
        color: colour, roughness: 0.55, metalness: 0.08, transparent: alpha < 0.99, opacity: alpha }));
      copy.add(mesh);
      meshes.push(mesh);
      whole.push([i, mesh]);
    });
    // The run's own ground, where it has one and the bench shows it, as a
    // cloth; the run stands on it.
    const cloth = floor && { x0: Math.max(floor.x0, reach.x0), x1: Math.min(floor.x1, reach.x1),
                             z0: Math.max(floor.z0, reach.z0), z1: Math.min(floor.z1, reach.z1) };
    if (cloth && cloth.x1 > cloth.x0 && cloth.z1 > cloth.z0) {
      const mesh = new THREE.Mesh(CUBE, CLOTH_MATERIAL);
      mesh.scale.set(cloth.x1 - cloth.x0, CLOTH / scale, cloth.z1 - cloth.z0);
      mesh.position.set((cloth.x0 + cloth.x1) / 2, floor.y - CLOTH / scale / 2, (cloth.z0 + cloth.z1) / 2);
      copy.add(mesh);
      meshes.push(mesh);
    }
    copy.scale.setScalar(scale);
    copy.position.set(-scale * (reach.x0 + reach.x1) / 2, BENCH.height + CLOTH - scale * (floor ? floor.y : 0),
                      -scale * (reach.z0 + reach.z1) / 2);
    run = { title, frames, whole, cells, cellSlots, cellSizes: cellSlots.map((slot) => sizes[slot]),
            meshes, scale, start: frames[0].time, duration: frames[frames.length - 1].time - frames[0].time };
    t = 0;
    show(0);
  }

  // The last recorded frame at or before a moment of the run.
  function frameAt(time) {
    const frames = run.frames, target = run.start + time;
    let lo = 0, hi = frames.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (frames[mid].time <= target + 1e-9) lo = mid; else hi = mid - 1;
    }
    return lo;
  }

  // The run at a moment. Between two recorded frames each body is eased from
  // the one to the next: a picture of it moving between two samples of the
  // run, never a second opinion about where it was.
  function pose(a, b, u, o, position, quaternion) {
    position.set(a[o] + (b[o] - a[o]) * u, a[o + 1] + (b[o + 1] - a[o + 1]) * u,
                 a[o + 2] + (b[o + 2] - a[o + 2]) * u);
    qa.set(a[o + 4], a[o + 5], a[o + 6], a[o + 3]);
    qb.set(b[o + 4], b[o + 5], b[o + 6], b[o + 3]);
    quaternion.slerpQuaternions(qa, qb, u);
  }

  function show(time) {
    if (!run) return;
    const frames = run.frames, i = frameAt(time), j = Math.min(i + 1, frames.length - 1);
    const span = frames[j].time - frames[i].time;
    const u = span > 1e-9 ? Math.min(1, Math.max(0, (run.start + time - frames[i].time) / span)) : 0;
    const key = `${i}:${u.toFixed(4)}`;
    if (key === shown) return;
    shown = key;
    const a = frames[i].at, b = frames[j].at;
    for (const [slot, mesh] of run.whole) {
      const o = slot * 7;
      mesh.visible = Number.isFinite(a[o]);
      if (mesh.visible) pose(a, b, u, o, mesh.position, mesh.quaternion);
    }
    if (run.cells) {
      run.cellSlots.forEach((slot, k) => {
        const o = slot * 7, size = run.cellSizes[k];
        if (Number.isFinite(a[o])) {
          pose(a, b, u, o, placing.position, placing.quaternion);
          placing.scale.set(size[0] || 0.01, size[1] || size[0] || 0.01, size[2] || size[0] || 0.01);
        } else placing.scale.set(0, 0, 0);
        placing.updateMatrix();
        run.cells.setMatrixAt(k, placing.matrix);
      });
      run.cells.instanceMatrix.needsUpdate = true;
    }
  }

  // Set down in front of the person, its long side to them, on the ground
  // where it stands; the run turned the way the lab shows it, seen from +z.
  function standInFront() {
    const f = new THREE.Vector3();
    camera.getWorldDirection(f);
    f.y = 0;
    if (f.lengthSq() < 1e-9) f.set(0, 0, -1);
    f.normalize();
    const x = camera.position.x + f.x * BENCH.ahead, z = camera.position.z + f.z * BENCH.ahead;
    const ground = Number(groundAt(x, z));
    group.position.set(x, Number.isFinite(ground) ? ground : 0, z);
    group.rotation.set(0, Math.atan2(-f.x, -f.z), 0);
  }

  return {
    // A run by its job's id and the case in it: the job first, which is what
    // lets the server hand out its recordings, then that case's recording.
    async open(id, index, title) {
      const mine = ++asked;
      loading = title || id;
      try {
        await api(`/api/jobs/${encodeURIComponent(id)}`);
        const recording = await api(`/api/jobs/${encodeURIComponent(id)}/playback/${Number(index) || 0}`);
        if (mine !== asked) return false;          // another run was chosen meanwhile
        if (recording.schema !== "banjo.playback.v1")
          throw new Error(`the bench plays banjo.playback.v1 recordings, and this one is ${recording.schema || "unlabelled"}`);
        build(recording, title || id);
      } finally {
        if (mine === asked) loading = null;
      }
      if (!group.visible) standInFront();
      group.visible = true;
      playing = true;
      last = null;
      return true;
    },
    close() {
      ++asked;
      loading = null;
      playing = false;
      group.visible = false;
      clear();
    },
    play() {
      if (!run) return;
      if (t >= run.duration) t = 0;
      playing = true;
      last = null;
    },
    pause() { playing = false; },
    seek(fraction) {
      if (!run) return;
      t = Math.min(1, Math.max(0, Number(fraction) || 0)) * run.duration;
      show(t);
    },
    setSpeed(value) {
      const v = Number(value);
      if (Number.isFinite(v) && v > 0) speed = v;
    },
    // With every frame the room draws.
    advance(now) {
      if (run && playing && last !== null) {
        t += Math.min(0.1, (now - last) / 1000) * speed;
        if (t >= run.duration) { t = run.duration; playing = false; }
      }
      last = now;
      show(t);
    },
    state() {
      if (!run) return { open: false, loading: !!loading, title: loading || "" };
      const i = frameAt(t);
      return { open: true, loading: !!loading, title: loading || run.title, playing, speed, t,
               duration: run.duration, frame: i, frames: run.frames.length,
               fractures: run.frames[i].fractures, scale: run.scale,
               bodies: run.whole.length, cells: run.cellSlots.length,
               at: group.position.toArray(), facing: group.rotation.y };
    },
  };
}
