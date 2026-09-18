// Workshop Mode: product design, physical matter, editable skins and isolated physics playback.
import * as THREE from "/vendor/three.module.js";

const $ = (q) => document.querySelector(q);
let token = "";
let candidateRequest = 0;
async function api(path, body) {
  const changesCandidate = ["/api/workshop/open", "/api/workshop/candidates", "/api/workshop/more"].includes(path);
  const requestId = changesCandidate ? ++candidateRequest : null;
  if (!token) {
    const status = await fetch("/api/status").then((r) => r.json());
    token = status.csrf_token || "";
  }
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Banjo-Token": token },
    body: JSON.stringify(body || {}),
  });
  const answer = await response.json().catch(() => ({ error: "the bench gave no answer" }));
  if (!response.ok) throw new Error(answer.error || `${path} failed (${response.status})`);
  if (requestId !== null) answer.clientRequest = requestId;
  return answer;
}

// ---------------------------------------------------------------------------
// Three.js view
// ---------------------------------------------------------------------------
const stage = $("#workshop-stage");
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 100);
const renderer = new THREE.WebGLRenderer({ canvas: stage, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
scene.add(new THREE.HemisphereLight(0xffffff, 0x45505c, 2.1));
const sun = new THREE.DirectionalLight(0xffffff, 2.8);
sun.position.set(3, 5, 4); scene.add(sun);
const grid = new THREE.GridHelper(4, 20, 0x596777, 0x313b47); scene.add(grid);
const group = new THREE.Group(); scene.add(group);
const balance = new THREE.Mesh(
  new THREE.SphereGeometry(0.025, 16, 12),
  new THREE.MeshBasicMaterial({ color: 0xffd166 }));
scene.add(balance);
const support = new THREE.LineSegments(
  new THREE.BufferGeometry(),
  new THREE.LineBasicMaterial({ color: 0xffd166, transparent: true, opacity: 0.55 }));
scene.add(support);
const raycaster = new THREE.Raycaster(); raycaster.params.Line.threshold = 0.045;
const pointer = new THREE.Vector2();

const SKIN = {
  oak: 0x9a704d, pine: 0xc0a072, iron: 0x8d939b, steel: 0x9aa2ab,
  aluminium: 0xb8bfc6, aluminum: 0xb8bfc6, glass: 0x9fc6d8,
  concrete: 0x9a9a95, rubber: 0x3c3c42, ice: 0xcde8f1,
  "alumina ceramic": 0xd9d4c8,
};
function materialColor(material) { return SKIN[material] ?? 0x7d8ea0; }
function parseColor(value, fallback) {
  if (!value) return fallback;
  try { return new THREE.Color(value); } catch { return fallback; }
}

let view = "wire";
let yaw = 0.72, pitch = 0.42, distance = 3;
let dragging = false, dragged = false, px = 0, py = 0, reach = 1.5;
const target = new THREE.Vector3(0, 0.42, 0);

const bench = {
  kind: "table", generation: 0, candidates: [], selected: 0,
  session: null, savedDesigns: [], personalLibrary: [], pricebook: null,
  selectedPart: null, forcePoint: null, openedLibraryItem: null, expandedProduct: null, isolated: null,
  benchTests: [], benchPresets: [], selectedBenchTest: null,
  matter: null, matterKey: null, matterMeasured: null, matterBom: null, matterMasses: null,
  cellSkin: null, physicsDebug: null, matterMode: "cells",
  clip: {enabled:false, axis:"x", position:0},
  revision: 0,
  playback: null, playbackIndex: 0, playbackPlaying: false,
  playbackClock: 0, playbackFrom: 0, playbackSpeed: 1,
};
function chosen() { return bench.candidates[bench.selected]; }
// Explicit prototype placement is separate from the pure design/test APIs.
const installation = {sequence:0, preview:null, request:null, committing:false};
// Building part by part. Declared up here because the editor, which holds the
// Build panel, is installed while this module is still loading.
const build = { placing:false, onto:null, at:null, twist:0, depth:0, preview:null, request:0 };
const ghost = new THREE.Group(); scene.add(ghost);
const BUILD_FACES = [["face-y-","its bottom"],["face-y+","its top"],["face-x-","its left side"],
  ["face-x+","its right side"],["face-z-","its front"],["face-z+","its back"]];
const JOINT_COLORS = { fixed:0x5fd38d, bearing:0x6cb6ff };
const VERDICT_COLORS = { "holds":0x5fd38d, "uncertain":0xe0a63a, "gives way":0xe05c5c, "unrated":0x8a96a3 };
function invalidateInstallation() {
  installation.sequence++;
  installation.preview = null;
  installation.request = null;
  const confirm = $("#ws-install-confirm");
  if (confirm) confirm.disabled = true;
  const result = $("#ws-install-result");
  if (result) { result.textContent = "Preview the current design and position before installing."; result.dataset.status = "unbuilt"; }
}
function installPlacementControls(right) {
  const box = make("section", {id:"ws-install-box"});
  box.append(make("h3", {}, "Place prototype in world"),
    make("p", {class:"ws-note"}, "Creates one single-material solid in a flat-floor room. This is an authoring prototype, not manufactured inventory or a certified assembly. Open a world first and leave it paused while previewing."));
  const yard = make("a", {href:"/world?scene=yard&hold=1"}, "Open the yard"); box.append(yard);
  for (const [axis,value] of [["x",3],["z",0]]) {
    const label=make("label", {class:"ws-field"}, `World ${axis.toUpperCase()} (m)`);
    const input=make("input", {id:`ws-install-${axis}`, type:"number",min:"-100",max:"100",step:"0.001",value:String(value)});
    input.addEventListener("input", invalidateInstallation); input.addEventListener("change", invalidateInstallation);
    label.append(input);box.append(label);
  }
  const mode=make("label", {class:"ws-field"}, "Create in authoring sandbox: do not charge inventory or fabrication energy");
  const consent=make("input", {id:"ws-install-authoring",type:"checkbox"});
  consent.addEventListener("change",invalidateInstallation);mode.append(consent);box.append(mode);
  const row=make("div", {class:"ws-row"});
  const preview=make("button", {id:"ws-install-preview",type:"button",class:"ws-action"}, "Preview placement");
  const confirm=make("button", {id:"ws-install-confirm",type:"button",class:"ws-action primary"}, "Install prototype");
  confirm.disabled=true;row.append(preview,confirm);
  box.append(row,make("p",{id:"ws-install-context",class:"ws-note"}),
    make("p",{id:"ws-install-result",role:"status","aria-live":"polite"},"Preview the current design and position before installing."));
  right.append(box);
  preview.onclick=()=>guard(preview,async()=>{
    invalidateInstallation();
    if (!consent.checked) throw new Error("Acknowledge authoring-sandbox creation first. Inventory-funded fabrication is not implemented.");
    const position=[$("#ws-install-x"),$("#ws-install-z")].map(e=>e.valueAsNumber);
    if (!position.every(Number.isFinite)) throw new Error("Enter finite X and Z coordinates.");
    const sequence=installation.sequence,revision=bench.revision,candidate=candidateBody();
    const source=await api("/api/world/workshop/context",{});
    if(sequence!==installation.sequence || revision!==bench.revision)return;
    $("#ws-install-context").textContent=`Room: ${source.scene} · native cell size ${source.cell_size_m*1000} mm. ${chosen().mechanical_model === "rigid" ? "Precise rigid geometry keeps its dimensions and continuous placement; anchored scenery only." : "The whole lattice prototype snaps once to this room grid."}`;
    const answer=await api("/api/world/workshop/preview",{session:source.session,scene:source.scene,
      mode:"authoring",candidate,position_m:position});
    if(sequence!==installation.sequence || revision!==bench.revision)return;
    installation.preview=answer;installation.request=crypto.randomUUID();
    const result=$("#ws-install-result");result.dataset.status="preview";
    result.textContent=`Ready: ${answer.design_id}, ${answer.mass_kg.toFixed(3)} kg, ${answer.mechanical_model === "precise-rigid-v1" ? `${answer.collision_boxes} precise collision boxes, zero lattice cells` : `${answer.cells} exact cells`}. Translation: ${answer.applied_translation_m.map(x=>x.toFixed(3)).join(", ")} m. Native geometry and existing state verified. No strength certification or resource charge. ${answer.limits}`;
    confirm.disabled=false;
  });
  confirm.onclick=async()=>{
    const ready=installation.preview,request=installation.request;
    if(!ready || installation.committing || !consent.checked)return;
    installation.committing=true;confirm.disabled=true;preview.disabled=true;
    try {
      const answer=await api("/api/world/workshop/commit",{session:ready.session,scene:ready.scene,
        preview_id:ready.preview_id,request_id:request});
      installation.preview=null;installation.request=null;
      const result=$("#ws-install-result");result.dataset.status="installed";
      result.textContent=`Installed ${answer.design_id} as ${answer.root_body} in ${answer.scene}. The original world state and inventory were preserved. `;
      result.append(make("a",{href:`/world?scene=${encodeURIComponent(answer.scene)}&hold=1`},"Return to the world"));
      say("Prototype installed and room saved.");
    } catch(error) {
      // Retain the same request ID on an uncertain network result: retrying
      // retrieves the saved receipt rather than creating another prototype.
      say(`${error.message} Retrying uses the same installation request.`,true);
    } finally {
      installation.committing=false;preview.disabled=false;confirm.disabled=!installation.preview;
    }
  };
}

function currentMeasurements(candidate = chosen()) {
  if (candidate.mechanical_model === "rigid") {
    const rigid = bench.rigid;
    return rigid ? {...candidate.measured, basis:"precise-rigid-geometry", mass_kg:rigid.mass_kg,
      centre_of_mass_m:rigid.centre_of_mass_m, inertia_kg_m2:rigid.inertia_kg_m2,
      warnings:[...(candidate.measured.warnings || []), ...rigid.limitations]}
      : {...candidate.measured, basis:"wireframe-estimate", geometry_coherent:false};
  }
  return ["matter", "collision", "relations"].includes(view) && bench.matterMeasured ? bench.matterMeasured : candidate.measured;
}
function invalidateMatter(message = "Not built for this candidate. Rebuild Matter view.") {
  invalidateInstallation();
  bench.cellSkin = null; bench.physicsDebug = null;
  bench.matter = null; bench.matterKey = null; bench.matterMeasured = null;
  bench.matterBom = null; bench.matterMasses = null; bench.rigid = null;
  clearTimeout(buildabilityTimer); buildabilityRequest++; bench.buildabilityPending = null;
  bench.buildability = null; bench.buildabilityKey = null;
  const status = $("#ws-matter-status");
  if (status) { status.textContent = message; status.dataset.state = "unbuilt"; }
}
function selectedPart() {
  const candidate = chosen();
  return candidate && candidate.parts.find((p) => p.name === bench.selectedPart);
}
function candidateBody() {
  const candidate = chosen();
  return {
    kind: bench.kind, generation: bench.generation, design_id: candidate.design_id,
    purpose: candidate.purpose, parameters: candidate.parameters,
    component_overrides: candidate.component_overrides || {},
  };
}

function placeCamera() {
  pitch = Math.max(-0.15, Math.min(1.25, pitch));
  camera.position.set(
    target.x + distance * Math.cos(pitch) * Math.sin(yaw),
    target.y + distance * Math.sin(pitch),
    target.z + distance * Math.cos(pitch) * Math.cos(yaw));
  camera.lookAt(target);
}
function frameCandidate() {
  const up = THREE.MathUtils.degToRad(camera.fov) / 2;
  const across = Math.atan(Math.tan(up) * Math.max(0.2, camera.aspect));
  distance = Math.max(0.6, reach * 1.15 / Math.sin(Math.min(up, across)));
  placeCamera();
}
function applyClipPlane() {
  if (!bench.clip.enabled) { renderer.clippingPlanes = []; return; }
  const normal = bench.clip.axis === "x" ? new THREE.Vector3(-1,0,0)
    : bench.clip.axis === "y" ? new THREE.Vector3(0,-1,0) : new THREE.Vector3(0,0,-1);
  renderer.clippingPlanes = [new THREE.Plane(normal, Number(bench.clip.position || 0))];
}
function shapeFor(part) {
  const [w, h, d] = part.size_m;
  if (part.shape === "tapered") return new THREE.CylinderGeometry(w * 0.4, d * 0.62, h, 5, 1);
  if (part.shape === "cylinder") return new THREE.CylinderGeometry(w / 2, d / 2, h, 20, 1);
  return new THREE.BoxGeometry(w, h, d);
}
function skinPart(candidate, name) {
  return (candidate.skin?.components || []).find((item) => item.component === name) || null;
}
function skinGeometry(part, descriptor) {
  if (!descriptor) return shapeFor(part);
  const [w, h, d] = descriptor.size_m || part.size_m;
  if (descriptor.kind === "bezier_tube") {
    const points = descriptor.control_points_local_m || [];
    if (points.length === 4) {
      const curve = new THREE.CubicBezierCurve3(...points.map((p) => new THREE.Vector3(...p)));
      return new THREE.TubeGeometry(curve, 40, Number(descriptor.radius_m || Math.min(w, d) / 2), 14, false);
    }
  }
  if (descriptor.kind === "cylinder") {
    return new THREE.CylinderGeometry(Number(descriptor.radius_m || Math.min(w, d) / 2),
      Number(descriptor.radius_m || Math.min(w, d) / 2), h, 28, 1);
  }
  return new THREE.BoxGeometry(w, h, d);
}
function disposeMaterial(material) {
  if (Array.isArray(material)) material.forEach((m) => m && m.dispose());
  else if (material) material.dispose();
}
function clearGroup() {
  drawnRecording = null; playbackMeshes.clear();
  for (const child of [...group.children]) {
    group.remove(child);
    if (child.geometry) child.geometry.dispose();
    disposeMaterial(child.material);
  }
}
function spinFor(rotation) {
  return new THREE.Euler(
    THREE.MathUtils.degToRad(rotation?.[0] || 0),
    THREE.MathUtils.degToRad(rotation?.[1] || 0),
    THREE.MathUtils.degToRad(rotation?.[2] || 0), "XYZ");
}
// A component opened from the library is worked on by itself: the design views
// draw it alone. Matter, collision, relations and physics describe the whole
// assembled product, so isolation does not apply to them.
const ISOLATING_VIEWS = ["wire", "skin"];
function shownParts(candidate) {
  if (!bench.isolated || !ISOLATING_VIEWS.includes(view)) return candidate.parts;
  return candidate.parts.filter((part) => part.name === bench.isolated);
}
function isolatedPart() {
  return bench.isolated ? (chosen()?.parts || []).find((p) => p.name === bench.isolated) || null : null;
}
function drawWire(candidate) {
  for (const part of shownParts(candidate)) {
    const geometry = shapeFor(part);
    const line = new THREE.LineSegments(
      new THREE.EdgesGeometry(geometry),
      new THREE.LineBasicMaterial({ color: part.name === bench.selectedPart ? 0xffd166 : 0xdce7f5 }));
    line.position.set(...part.center_m); line.rotation.copy(spinFor(part.rotation_deg));
    line.userData.partName = part.name; group.add(line); geometry.dispose();
  }
}
function drawSkin(candidate, opacity = 1) {
  for (const part of shownParts(candidate)) {
    const descriptor = skinPart(candidate, part.name);
    const geometry = skinGeometry(part, descriptor);
    const selected = part.name === bench.selectedPart;
    const base = materialColor(part.material);
    const color = selected ? 0xd9a441 : parseColor(descriptor?.color, base);
    const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
      color, emissive: selected ? 0x3d2b0d : 0,
      roughness: Number(descriptor?.roughness ?? 0.72),
      metalness: Number(descriptor?.metalness ?? 0),
      transparent: opacity < 1, opacity, depthWrite: opacity >= 1,
    }));
    mesh.position.set(...(descriptor?.center_m || part.center_m));
    mesh.rotation.copy(spinFor(descriptor?.rotation_deg || part.rotation_deg));
    mesh.userData.partName = part.name; group.add(mesh);
  }
}
function drawDesignMatterFallback(candidate) {
  // Used only until an actual cell preview has arrived.
  for (const part of candidate.parts) {
    const geometry = shapeFor(part);
    const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
      color: part.name === bench.selectedPart ? 0xd9a441 : 0x6f8194,
      roughness: 0.6, transparent: true, opacity: 0.28,
    }));
    mesh.position.set(...part.center_m); mesh.rotation.copy(spinFor(part.rotation_deg));
    mesh.userData.partName = part.name; group.add(mesh);
  }
}
function drawMatterCells(candidate) {
  if (chosen()?.mechanical_model === "rigid") {
    if (!bench.rigid) return; // Never substitute lattice cells for a failed rigid compilation.
    for (const part of bench.rigid.components) {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(...part.dimensions_m),
        new THREE.MeshStandardMaterial({color:materialColor(bench.rigid.material),roughness:.65}));
      mesh.position.set(...part.center_m); mesh.userData.partName = part.component; group.add(mesh);
    }
    return;
  }
  const matter = bench.matter;
  if (!matter?.cells?.length) return;
  const cell = Number(matter.cell_size_m || 0.04);
  const byPart = new Map();
  for (const item of matter.cells) {
    if (!byPart.has(item.component)) byPart.set(item.component, []);
    byPart.get(item.component).push(item);
  }
  const cube = new THREE.BoxGeometry(cell * 0.94, cell * 0.94, cell * 0.94);
  const matrix = new THREE.Matrix4();
  for (const [partName, cells] of byPart.entries()) {
    const material = cells[0]?.material || selectedPart()?.material || "iron";
    const mesh = new THREE.InstancedMesh(cube.clone(), new THREE.MeshStandardMaterial({
      color: partName === bench.selectedPart ? 0xd9a441 : materialColor(material),
      roughness: 0.78, metalness: 0, transparent: true, opacity: 0.93,
    }), cells.length);
    mesh.userData.partNames = [];
    cells.forEach((item, index) => {
      matrix.makeTranslation(...item.center_m); mesh.setMatrixAt(index, matrix);
      mesh.userData.partNames[index] = item.component;
    });
    mesh.instanceMatrix.needsUpdate = true; group.add(mesh);
  }
  cube.dispose();
}
function faceQuad(face, cell) {
  const [gx,gy,gz] = face.grid;
  const lo = [gx*cell, gy*cell, gz*cell], hi = [(gx+1)*cell,(gy+1)*cell,(gz+1)*cell];
  const a = face.axis, p = face.positive ? hi[a] : lo[a];
  const axes = [0,1,2].filter((q) => q !== a), u = axes[0], v = axes[1];
  const points = [];
  for (const [su,sv] of [[0,0],[1,0],[1,1],[0,1]]) {
    const q = [0,0,0]; q[a]=p; q[u]=su ? hi[u] : lo[u]; q[v]=sv ? hi[v] : lo[v]; points.push(q);
  }
  // x/z use right-handed face axes; x cross z points toward negative y.
  if (face.positive === (a === 1)) points.reverse();
  return points;
}
function drawCellSkin() {
  const skin = bench.cellSkin;
  stage.dataset.cellSkinFaces = String(skin?.exposed_faces || 0);
  if (!skin?.faces?.length) return;
  const cell = Number(skin.cell_size_m || bench.matter?.cell_size_m || 0.04);
  const byPart = new Map();
  for (const face of skin.faces) {
    const key = face.component || "matter";
    if (!byPart.has(key)) byPart.set(key, []);
    byPart.get(key).push(face);
  }
  for (const [partName, faces] of byPart.entries()) {
    const positions = [];
    for (const face of faces) {
      const q = faceQuad(face, cell);
      for (const index of [0,1,2,0,2,3]) positions.push(...q[index]);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3)); geometry.computeVertexNormals();
    const material = faces[0]?.material || "iron";
    const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
      color: partName === bench.selectedPart ? 0xd9a441 : materialColor(material), roughness: 0.72,
      side: THREE.DoubleSide,
    }));
    mesh.userData.partName = partName; group.add(mesh);
  }
}
function drawMatter(candidate) {
  if (bench.rigid) { drawMatterCells(candidate); return; }
  if (bench.matterMode === "solid") drawCellSkin();
  else if (bench.matterMode === "skin-cells") { drawMatterCells(candidate); drawSkin(candidate, 0.28); }
  else drawMatterCells(candidate);
}
function debugComponent(id) { return (bench.physicsDebug?.components || []).find((c) => c.id === id) || null; }
function drawCollisionDebug() {
  if (bench.physicsDebug?.status === "unavailable") { stage.dataset.debugBasis = bench.physicsDebug.basis; return; }
  drawSkin(chosen(), 0.13);
  stage.dataset.debugBasis = bench.physicsDebug?.basis || "unavailable";
  for (const zone of bench.physicsDebug?.collision_zones || []) {
    const part = debugComponent(zone.component); if (!part) continue;
    const geometry = shapeFor({ size_m:part.size_m, shape:part.shape });
    const line = new THREE.LineSegments(new THREE.EdgesGeometry(geometry),
      new THREE.LineBasicMaterial({ color: 0xff7657, transparent:true, opacity:0.95 }));
    line.position.set(...part.center_m); line.rotation.copy(spinFor(part.rotation_deg));
    line.userData.partName = part.id; line.userData.collisionKind = zone.kind; group.add(line); geometry.dispose();
  }
}
function drawRelationshipDebug() {
  stage.dataset.debugBasis = bench.physicsDebug?.basis || "unavailable";
  if (bench.physicsDebug?.status === "unavailable") return;
  drawWire(chosen());
  const positions = [];
  for (const relation of bench.physicsDebug?.relationships || []) {
    const a = debugComponent(relation.a), b = debugComponent(relation.b); if (!a || !b) continue;
    positions.push(...a.center_m, ...b.center_m);
  }
  const geometry = new THREE.BufferGeometry(); geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions,3));
  const lines = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color:0x65c7ff, transparent:true, opacity:0.9 }));
  group.add(lines);
  for (const mechanism of bench.physicsDebug?.mechanisms || []) {
    const a = debugComponent(mechanism.a_component), b = debugComponent(mechanism.b_component); if (!a || !b) continue;
    const p = a.center_m.map((v,i) => (Number(v)+Number(b.center_m[i]))/2);
    const marker = new THREE.Mesh(new THREE.SphereGeometry(Math.max(0.015, reach*0.012),12,8),
      new THREE.MeshBasicMaterial({ color:0xffd166 })); marker.position.set(...p); group.add(marker);
  }
}
function playbackBodyGeometry(body) {
  const d = body.dimensions_m || [0.05, 0.05, 0.05];
  if (body.shape === "sphere" || body.shape === 1) return new THREE.SphereGeometry(d[0] / 2, 18, 12);
  return new THREE.BoxGeometry(Math.max(0.000001, d[0]), Math.max(0.000001, d[1]), Math.max(0.000001, d[2]));
}
let drawnRecording = null;
const playbackMeshes = new Map();
let physicsMeshBuilds = 0;
function drawPlayback() {
  const recording = bench.playback, frame = recording?.frames?.[bench.playbackIndex];
  if (!frame) return;
  if (drawnRecording !== recording) { clearGroup(); drawnRecording = recording; physicsMeshBuilds = 0; }
  const present = new Set(), thermal = new Map((frame.thermo?.bodies || []).map(b => [b.name, b.temperature_k]));
  let proxies = 0;
  for (const body of frame.bodies || []) {
    present.add(body.name);
    const geometry = recording.geometry?.[body.name];
    const exact = geometry && Number(geometry.revision) === Number(body.revision || 0);
    const signature = JSON.stringify([body.revision || 0, exact, body.shape, body.dimensions_m, body.material]);
    let entry = playbackMeshes.get(body.name);
    if (!entry || entry.signature !== signature) {
      if (entry) { group.remove(entry.mesh); entry.mesh.geometry.dispose(); disposeMaterial(entry.mesh.material); }
      const material = new THREE.MeshStandardMaterial({color:materialColor(body.material), roughness:0.62});
      let mesh;
      if (exact) {
        const cell = geometry.cell_size_m;
        mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(cell,cell,cell), material, geometry.offsets_m.length);
        const matrix = new THREE.Matrix4();
        geometry.offsets_m.forEach((offset,i) => { matrix.makeTranslation(...offset); mesh.setMatrixAt(i,matrix); });
        mesh.instanceMatrix.needsUpdate = true;
      } else mesh = new THREE.Mesh(playbackBodyGeometry(body), material);
      mesh.userData.partName = body.name;
      group.add(mesh); entry = {mesh,signature}; playbackMeshes.set(body.name,entry); physicsMeshBuilds++;
    }
    if (!exact && recording.geometry_basis !== "verified-precise-rigid-shapes") proxies++;
    entry.mesh.position.set(...body.position_m);
    const q = body.orientation_wxyz || [1,0,0,0]; entry.mesh.quaternion.set(q[1],q[2],q[3],q[0]);
    if (recording.test === "kettle_heat" && Number.isFinite(thermal.get(body.name))) {
      const hot = Math.max(0,Math.min(1,(thermal.get(body.name)-293.15)/80));
      entry.mesh.material.color.setHSL((1-hot)*.62,.85,.55);
      // The contained thermal proxy must remain visible inside the vessel.
      entry.mesh.material.transparent = body.name !== "water charge";
      entry.mesh.material.opacity = body.name === "water charge" ? .95 : .4;
      entry.mesh.material.depthWrite = body.name === "water charge";
    }
  }
  for (const [name,entry] of playbackMeshes) if (!present.has(name)) {
    group.remove(entry.mesh); entry.mesh.geometry.dispose(); disposeMaterial(entry.mesh.material); playbackMeshes.delete(name);
  }
  stage.dataset.physicsTime = String(frame.t_s);
  stage.dataset.physicsBodyCount = String(present.size);
  stage.dataset.physicsMeshBuilds = String(physicsMeshBuilds);
  stage.dataset.physicsPose = JSON.stringify(frame.bodies?.[0]?.position_m || []);
  const live = $("#ws-simulation-readout");
  if (recording.test === "kettle_heat") {
    live.textContent = `Water ${celsius(thermal.get("water charge"))} · heater ${celsius(thermal.get("heater plate"))}. Blue → red: measured 20–100 °C. Contained thermal model; no sloshing.`;
  } else if (recording.geometry_basis === "verified-precise-rigid-shapes") {
    const bodies = new Set((frame.bodies || []).map(part => part.object_id));
    live.textContent = `${present.size} collision shapes · ${bodies.size} rigid ${bodies.size === 1 ? "body" : "bodies"} · ${Number(frame.t_s).toFixed(2)} seconds. Actual native poses; no internal failure model.`;
  } else live.textContent = `${present.size} simulated bodies · ${Number(frame.t_s).toFixed(2)} seconds. Positions are calculated by the physics engine.`;
  $("#ws-play-note").textContent = recording.geometry_basis === "verified-precise-rigid-shapes"
    ? "Exact rigid collision shapes and actual native poses. No internal fracture, bending or attachment-failure calculation."
    : `${recording.geometry ? "Exact Matter cells until topology changes. " : ""}${proxies ? `${proxies} bodies use simplified collision shapes. ` : ""}Showing the computed experiment, not a live connection to the outside world.`;
}
function frameSimulation(recording) {
  const bounds = new THREE.Box3();
  for (const frame of recording.frames) for (const body of frame.bodies || []) {
    const radius = .5*Math.hypot(...(body.dimensions_m || [.05,.05,.05]));
    const point = new THREE.Vector3(...body.position_m);
    bounds.expandByPoint(point.clone().addScalar(radius)); bounds.expandByPoint(point.clone().addScalar(-radius));
  }
  if (!bounds.isEmpty()) { bounds.getCenter(target); reach = Math.max(.3,bounds.getSize(new THREE.Vector3()).length()/2); frameCandidate(); }
  grid.position.y = 0;
}

function draw(candidate) {
  // What the viewport is actually showing, for the page and for tests.
  stage.dataset.showing = shownParts(candidate).length === candidate.parts.length ? "product" : bench.isolated;
  if (view !== "physics") clearGroup();
  applyClipPlane();
  balance.visible = !["physics", "collision", "relations"].includes(view);
  support.visible = balance.visible;
  if (view === "physics") drawPlayback();
  else if (view === "matter") drawMatter(candidate);
  else if (view === "skin") drawSkin(candidate);
  else if (view === "collision") drawCollisionDebug();
  else if (view === "relations") drawRelationshipDebug();
  else drawWire(candidate);
  if (view === "wire" || view === "skin") drawJoints(candidate);

  const m = currentMeasurements(candidate);
  const alone = ISOLATING_VIEWS.includes(view) ? isolatedPart() : null;
  if (alone) {
    // Balance and support are properties of the whole product, not of one piece.
    balance.visible = false; support.visible = false;
    const half = Math.max(...alone.size_m) / 2;
    grid.position.y = alone.center_m[1] - half * 1.4;
    target.set(...alone.center_m);
    reach = 0.5 * Math.hypot(...alone.size_m);
    return;
  }
  if (view !== "physics") {
    balance.position.set(...m.centre_of_mass_m);
    const feet = m.ground_contacts_m || [], ring = [];
    if (feet.length) {
      const xs = feet.map((f) => f[0]), zs = feet.map((f) => f[1]);
      const box = [
        [Math.min(...xs), Math.min(...zs)], [Math.max(...xs), Math.min(...zs)],
        [Math.max(...xs), Math.max(...zs)], [Math.min(...xs), Math.max(...zs)],
      ];
      const polygon = m.support_polygon_m || box;
      for (let i = 0; i < polygon.length; i++) {
        const a = polygon[i], b = polygon[(i + 1) % polygon.length];
        ring.push(a[0], m.lowest_m + 0.002, a[1], b[0], m.lowest_m + 0.002, b[1]);
      }
    }
    support.geometry.dispose(); support.geometry = new THREE.BufferGeometry();
    support.geometry.setAttribute("position", new THREE.Float32BufferAttribute(ring, 3));
    grid.position.y = m.lowest_m;
    target.set(0, m.lowest_m + m.bounding_box_m[1] * 0.5, 0);
    reach = 0.5 * Math.hypot(...m.bounding_box_m);
  }
}

const forceArrow = new THREE.ArrowHelper(
  new THREE.Vector3(0, -1, 0), new THREE.Vector3(), 0.3, 0xffb347, 0.08, 0.05);
forceArrow.visible = false; scene.add(forceArrow);
const PUSH_WAYS = { "down":[0,-1,0], "up":[0,1,0], "+x":[1,0,0], "-x":[-1,0,0], "+z":[0,0,1], "-z":[0,0,-1] };
function showForceAt(point, force_n, push = "down") {
  if (!point || view === "physics") { forceArrow.visible = false; return; }
  const span = Math.max(0.12, reach * 0.9);
  const size = span * (0.25 + 0.75 * Math.min(1, Math.log10(1 + (Number(force_n) || 0)) / Math.log10(50001)));
  const way = new THREE.Vector3(...(PUSH_WAYS[push] || PUSH_WAYS.down));
  // The arrow's head lands on the point: it starts one length back along the push.
  forceArrow.position.set(point[0] - way.x * size, point[1] - way.y * size, point[2] - way.z * size);
  forceArrow.setDirection(way);
  forceArrow.setLength(size, size * 0.28, size * 0.16); forceArrow.visible = true;
}
function hitPartName(hit) {
  if (!hit) return null;
  if (hit.instanceId != null && Array.isArray(hit.object.userData?.partNames)) {
    return hit.object.userData.partNames[hit.instanceId] || null;
  }
  return hit.object.userData?.partName || null;
}
function pickPart(event) {
  if (view === "physics") return;
  const rect = stage.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  // Meshes made since the last frame still have the identity as their world
  // matrix, so a click that beats the next frame would be cast against every
  // part piled at the origin and pick the wrong one.
  group.updateMatrixWorld(true);
  const hit = raycaster.intersectObjects(group.children, false)
    .find((item) => hitPartName(item));
  if (build.placing) { placeAtHit(hit); return; }
  bench.selectedPart = hitPartName(hit);
  bench.forcePoint = hit ? [hit.point.x, hit.point.y, hit.point.z] : null;
  // A new spot: the last push's colours no longer describe what is selected.
  bench.jointVerdicts = null; $("#ws-push-result")?.replaceChildren();
  show(false);
  if (bench.selectedPart && bench.selectedBenchTest === "force_probe") reprobe();
  else showForceAt(null);
}

let probing = false;
function reprobe() {
  if (bench.selectedBenchTest !== "force_probe" || !bench.selectedPart || probing) return;
  probing = true; const config = benchConfig(); showForceAt(bench.forcePoint, config.force_n);
  guard(null, async () => {
    try {
      const answer = await api("/api/workshop/plan", {
        ...candidateBody(), bench_test: { test: "force_probe", config },
      });
      renderBenchResult(answer.bench);
      showForceAt(answer.bench?.target?.point_m || bench.forcePoint, config.force_n);
    } finally { probing = false; }
  });
}

stage.addEventListener("pointerdown", (event) => {
  dragging = true; dragged = false; px = event.clientX; py = event.clientY;
  stage.setPointerCapture(event.pointerId);
});
stage.addEventListener("pointermove", (event) => {
  if (!dragging) return;
  const dx = event.clientX - px, dy = event.clientY - py;
  if (Math.abs(dx) + Math.abs(dy) > 3) dragged = true;
  yaw -= dx * 0.008; pitch += dy * 0.008; px = event.clientX; py = event.clientY; placeCamera();
});
stage.addEventListener("pointerup", (event) => { dragging = false; if (!dragged) pickPart(event); });
stage.addEventListener("pointercancel", () => { dragging = false; });
stage.addEventListener("wheel", (event) => {
  event.preventDefault(); distance = Math.max(0.6, Math.min(9, distance * Math.exp(event.deltaY * 0.001))); placeCamera();
}, { passive: false });
stage.addEventListener("dragover", (event) => { event.preventDefault(); stage.classList.add("ws-drop-target"); });
stage.addEventListener("dragleave", () => stage.classList.remove("ws-drop-target"));
stage.addEventListener("drop", (event) => {
  event.preventDefault(); stage.classList.remove("ws-drop-target");
  const itemId = event.dataTransfer.getData("application/x-banjo-library-item");
  if (!itemId) return;
  if (!bench.selectedPart) { say("Select the component the saved item should replace, then drop it again.", true); return; }
  guard(null, () => reuseLibraryComponent(itemId));
});

// ---------------------------------------------------------------------------
// DOM helpers and editors
// ---------------------------------------------------------------------------
function make(tag, attrs = {}, text = "") {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") element.className = value;
    else if (key === "id") element.id = value;
    else element.setAttribute(key, value);
  }
  if (text) element.textContent = text; return element;
}
function say(message, bad = false) {
  const notice = $("#ws-notice");
  if (notice) { notice.textContent = message; notice.hidden = !message; notice.classList.toggle("bad", bad); }
  const checks = $("#ws-checks"); checks.className = "ws-note" + (bad ? " bad" : ""); checks.textContent = message;
}
async function guard(button, work) {
  const original = button && button.textContent; if (button) button.disabled = true;
  const notice = $("#ws-notice"); if (notice) notice.hidden = true;
  try { await work(); } catch (err) { say(String(err.message || err), true); }
  finally { if (button) { button.disabled = button.id === "ws-run-bench" && !benchDefinition(); button.textContent = original; } }
}
function addOption(select, value, label) { select.append(make("option", { value }, label)); }

function updateClipControls() {
  const output=$("#ws-clip-value"); if(output) output.textContent=`${bench.clip.position.toFixed(2)} m`;
  applyClipPlane(); show(false);
}

function installEditor() {
  const notice = make("p", {id:"ws-notice", role:"status", "aria-live":"polite"});
  notice.hidden = true; $(".ws-top").append(notice);
  const buildability = make("section", {id:"ws-buildability", role:"status", "aria-live":"polite"});
  buildability.append(make("h3", {}, "Physical buildability"), make("p", {id:"ws-buildability-summary"}),
    make("div", {id:"ws-buildability-parts"}));
  $(".ws-metrics").after(buildability);
  const basis = make("p", {id:"ws-measurement-basis", class:"ws-note"});
  $(".ws-metrics").after(basis);
  const left = $(".ws-left"), right = $(".ws-right");
  const productBox = make("section", { id: "ws-product-library-box", class: "ws-product-section" });
  productBox.append(make("h2", {}, "Product library"),
    make("p", {}, "The open product lists its components and quantities underneath. Click one to edit it, or copy it into My library."),
    make("div", { id: "ws-product-catalog", class: "ws-product-catalog" }));
  left.prepend(productBox);
  const libraryBox = make("section", { id: "ws-personal-library-box" });
  libraryBox.append(make("h2", {}, "My library"),
    make("p", {}, "Reusable components and assemblies. Select a part, then click or drag a component onto it."),
    make("div", { id: "ws-user-library" }));
  productBox.after(libraryBox);

  const editor = make("section", { id: "ws-component-editor", class: "ws-component-editor" });
  editor.append(make("h3", {}, "Selected component"),
    make("p", { id: "ws-selected-part", class: "ws-note" }, "Click a part of the object to edit it."));
  const isolation = make("div", { id: "ws-isolation", class: "ws-isolation" });
  isolation.hidden = true;
  isolation.append(make("span", { id: "ws-isolation-note" }),
    make("button", { id: "ws-show-whole", type: "button", class: "ws-action" }, "Show the whole product"));
  editor.append(isolation);
  const saveName = make("input", { id:"ws-component-name", type:"text", maxlength:"120", placeholder:"My tapered leg" });
  const saveLabel = make("label", { class:"ws-field" }, "Save this component as"); saveLabel.append(saveName);
  editor.append(saveLabel, make("button", { id:"ws-save-component", type:"button", class:"ws-action" }, "Save as a new component"));
  const scope = make("select", { id: "ws-edit-scope", "aria-label": "Edit scope" });
  [["this", "This part"], ["similar", "Similar parts"], ["all", "Whole object"]].forEach(([v,l]) => addOption(scope,v,l));
  const scopeLabel = make("label", { class: "ws-field" }, "Change"); scopeLabel.append(scope); editor.append(scopeLabel);
  const actions = make("div", { class: "ws-edit-actions" });
  [["longer", "Longer"], ["shorter", "Shorter"], ["thicker", "Thicker"], ["thinner", "Thinner"]]
    .forEach(([action,label]) => actions.append(make("button", { type:"button", class:"ws-action", "data-component-edit":action }, label)));
  editor.append(actions);
  const material = make("select", { id: "ws-part-material" });
  const materialLabel = make("label", { class: "ws-field" }, "Material"); materialLabel.append(material); editor.append(materialLabel);

  editor.append(make("h3", {}, "Mechanical representation"));
  const model = make("select", {id:"ws-mechanical-model", "aria-label":"Mechanical representation"});
  addOption(model,"lattice","Breakable lattice (shared grid)");
  addOption(model,"rigid","Precise rigid (no internal failure)");
  const modelLabel = make("label", {class:"ws-field"}, "Whole candidate"); modelLabel.append(model); editor.append(modelLabel);
  editor.append(make("button", {id:"ws-apply-mechanics",type:"button",class:"ws-action"}, "Apply mechanical model"),
    make("p", {class:"ws-feedback-count"}, "Rigid shapes keep their dimensions. Beam, sheet and mixed-resolution solvers are not implemented. Rigid live-room installation is not available yet."));
  editor.append(make("h3", {}, "Skin & matter"));
  const profile = make("select", { id: "ws-skin-profile" });
  [["design","Design shape"],["block","Block"],["round","Round"],["curve","Curved tube"]]
    .forEach(([v,l]) => addOption(profile,v,l));
  const profileLabel = make("label", { class:"ws-field" }, "Surface profile"); profileLabel.append(profile); editor.append(profileLabel);
  const bend = make("input", { id:"ws-skin-bend", type:"range", min:"-1", max:"1", step:"0.01", value:"0" });
  const bendOut = make("output", { id:"ws-skin-bend-value", class:"ws-range-value" }, "0 m");
  bend.oninput = () => { bendOut.textContent = `${Number(bend.value).toFixed(2)} m`; };
  const bendLabel = make("label", { class:"ws-field" }, "Curve bend"); bendLabel.append(bend,bendOut); editor.append(bendLabel);
  const roughness = make("input", { id:"ws-skin-roughness", type:"range", min:"0", max:"1", step:"0.05", value:"0.72" });
  const roughOut = make("output", { id:"ws-skin-roughness-value", class:"ws-range-value" }, "0.72");
  roughness.oninput = () => { roughOut.textContent = Number(roughness.value).toFixed(2); };
  const roughLabel = make("label", { class:"ws-field" }, "Roughness"); roughLabel.append(roughness,roughOut); editor.append(roughLabel);
  const physicalLabel = make("label", { class:"ws-field" }, "Curve changes physical matter");
  const physical = make("input", { id:"ws-skin-physical", type:"checkbox" }); physicalLabel.append(physical); editor.append(physicalLabel);
  editor.append(make("button", { id:"ws-apply-skin", type:"button", class:"ws-action primary" }, "Apply skin"));
  const matterCell = make("input", { id:"ws-matter-cell", type:"number", min:"0.005", max:"0.2", step:"0.005", value:"0.04" });
  const cellLabel = make("label", { class:"ws-field" }, "Matter cell (m)"); cellLabel.append(matterCell); editor.append(cellLabel);
  const exteriorLabel = make("label", { class:"ws-field" }, "Show exterior cells only");
  const exterior = make("input", { id:"ws-matter-exterior", type:"checkbox" }); exterior.checked = true; exteriorLabel.append(exterior); editor.append(exteriorLabel);
  editor.append(make("button", { id:"ws-refresh-matter", type:"button", class:"ws-action" }, "Rebuild Matter view"),
    make("p", { id:"ws-matter-status", class:"ws-feedback-count" }, "Matter is compiled from the product geometry, not drawn from its skin."));

  editor.append(make("h3", {}, "Tell Workshop"));
  const chat = make("form", { id:"ws-component-chat", class:"ws-component-chat" });
  chat.append(make("input", { id:"ws-component-chat-text", type:"text", placeholder:"make all the legs thinner" }),
    make("button", { type:"submit", class:"ws-action" }, "Change")); editor.append(chat);
  // Buildability has a nested heading; insertBefore needs a direct child.
  right.insertBefore(editor, right.querySelector(":scope > h3"));
  installBuildPanel(editor);

  const bom = make("section", { id:"ws-bom-box" }); bom.append(make("h3", {}, "Materials"), make("div", { id:"ws-bom" }));
  right.insertBefore(bom, $("#ws-checks").previousElementSibling);

  const testBox = make("section", { id:"ws-test-bench" });
  testBox.append(make("h3", {}, "Test bench"),
    make("p", { class:"ws-feedback-count" }, "Choose a situation and press Run simulation. The computed motion starts automatically. The outside world stays unchanged."));
  const testPicker = make("select", { id:"ws-bench-test", "aria-label":"Functional test" });
  const pickerLabel = make("label", { class:"ws-field" }, "Test"); pickerLabel.append(testPicker); testBox.append(pickerLabel);
  testBox.append(make("div", { id:"ws-bench-controls" }));
  const testActions = make("div", { class:"ws-row" });
  testActions.append(make("button", { id:"ws-run-bench", type:"button", class:"ws-action primary" }, "Run simulation"),
    make("button", { id:"ws-save-bench-preset", type:"button", class:"ws-action" }, "Save preset")); testBox.append(testActions);
  const presetName = make("input", { id:"ws-bench-preset-name", type:"text", maxlength:"120", placeholder:"My drop test" });
  const presetLabel = make("label", { class:"ws-field" }, "Preset name"); presetLabel.append(presetName); testBox.append(presetLabel);
  const playback = make("div", { id:"ws-playback", class:"ws-note" }); playback.hidden = true;
  const playbackRow = make("div", { class:"ws-row" });
  playbackRow.append(make("button", { id:"ws-play", type:"button", class:"ws-action primary" }, "Play"),
    make("button", { id:"ws-play-reset", type:"button", class:"ws-action" }, "Reset"),
    make("output", { id:"ws-play-time" }, "0.00 s"));
  const timeline = make("input", { id:"ws-play-timeline", type:"range", min:"0", max:"0", step:"1", value:"0" });
  const speed = make("select", {id:"ws-play-speed", "aria-label":"Simulation display speed"});
  for (const value of [.25,1,5,10,30,60]) speed.append(make("option",{value:String(value)},`${value}×`));
  speed.value="1";
  speed.onchange=()=>{bench.playbackSpeed=Number(speed.value);bench.playbackClock=performance.now();bench.playbackFrom=Number(bench.playback?.frames?.[bench.playbackIndex]?.t_s || 0);};
  playbackRow.append(speed);
  playback.append(make("strong", {}, "Simulation result"), playbackRow, timeline,
    make("p", {id:"ws-simulation-readout",role:"status"}),
    make("p", { id:"ws-play-note", class:"ws-feedback-count" }, "Calculated motion and temperature. Replay does not rerun the physics."));
  testBox.append(playback, make("div", { id:"ws-bench-presets" }), make("div", { id:"ws-bench-result" }));
  right.insertBefore(testBox, $("#ws-save-design").parentElement.previousElementSibling || $("#ws-save-design").parentElement);

  // Keep the real Run/replay controls next to the object, not below a long
  // scrolling parameter panel. Move existing nodes, never duplicate handlers.
  const dock = make("section", {id:"ws-simulation-dock",class:"ws-simulation-dock","aria-label":"Simulation controls"});
  dock.hidden = true;
  dock.append(make("strong", {id:"ws-active-situation"}), $("#ws-run-bench"),
    make("div", {id:"ws-simulation-feedback"}), playback);
  $(".ws-viewport").append(dock);

  const matterMode=make("select",{id:"ws-matter-mode"});[["cells","Cells"],["solid","Solid CellSkin"],["skin-cells","Skin + cells"]].forEach(([v,l])=>addOption(matterMode,v,l));const modeLabel=make("label",{class:"ws-field"},"Matter display");modeLabel.append(matterMode);editor.append(modeLabel);
  editor.append(make("h3",{},"Section view"));
  const clipEnabled=make("input",{id:"ws-clip-enabled",type:"checkbox"});const clipEnabledLabel=make("label",{class:"ws-field"},"Enable clipping plane");clipEnabledLabel.append(clipEnabled);editor.append(clipEnabledLabel);
  const clipAxis=make("select",{id:"ws-clip-axis"});[["x","X"],["y","Y"],["z","Z"]].forEach(([v,l])=>addOption(clipAxis,v,l));const axisLabel=make("label",{class:"ws-field"},"Section axis");axisLabel.append(clipAxis);editor.append(axisLabel);
  const clipPosition=make("input",{id:"ws-clip-position",type:"range",min:"-3",max:"3",step:"0.01",value:"0"});const clipOut=make("output",{id:"ws-clip-value",class:"ws-range-value"},"0.00 m");const clipLabel=make("label",{class:"ws-field"},"Plane position");clipLabel.append(clipPosition,clipOut);editor.append(clipLabel);
  matterMode.onchange = () => { bench.matterMode = matterMode.value; view = "matter"; pressView(view); show(false); };
  clipEnabled.onchange = () => { bench.clip.enabled = clipEnabled.checked; updateClipControls(); };
  clipAxis.onchange = () => { bench.clip.axis = clipAxis.value; updateClipControls(); };
  clipPosition.oninput = () => { bench.clip.position = Number(clipPosition.value); updateClipControls(); };
  editor.append(make("p", {class:"ws-feedback-count",id:"ws-inspection-basis"}, "Collision and Relations show declared design-contract zones and connections, not a native contact or load test. Section clipping changes display only; it does not cut matter."));
  const bar = $(".ws-viewbar");
  if (bar && !bar.querySelector('[data-view="physics"]')) bar.append(make("button", { type:"button", "data-view":"physics", "aria-pressed":"false" }, "Physics"));

  for (const [mode,label] of [["collision","Collision"],["relations","Relations"]])
    if (bar && !bar.querySelector(`[data-view="${mode}"]`)) bar.append(make("button", {type:"button", "data-view":mode, "aria-pressed":"false"}, label));

  actions.querySelectorAll("button").forEach((button) => { button.onclick = () => guard(button, () => editSelected(button.dataset.componentEdit)); });
  material.onchange = () => guard(null, () => editSelected("material", material.value));
  $("#ws-apply-skin").onclick = (event) => guard(event.currentTarget, editSkin);
  $("#ws-apply-mechanics").onclick = (event) => guard(event.currentTarget, async () => {
    const answer = await api("/api/workshop/candidates", {...candidateBody(), mechanics_edit:{model:$("#ws-mechanical-model").value}});
    took(answer, bench.selectedPart);
    if (chosen().mechanical_model === "rigid") {
      bench.selectedBenchTest = "rigid_motion"; renderBenchCatalog();
    }
    await loadMatter(true); view = "matter"; pressView("matter"); show(false);
  });
  $("#ws-refresh-matter").onclick = (event) => guard(event.currentTarget, async () => { await loadMatter(true); view = "matter"; pressView("matter"); show(false); });
  $("#ws-save-component").onclick = (event) => guard(event.currentTarget, saveSelectedComponent);
  $("#ws-show-whole").onclick = (event) => guard(event.currentTarget, async () => { showWholeProduct(); });
  $("#ws-component-name").oninput = (event) => {
    if (event.target.value.trim()) event.target.dataset.edited = "1"; else delete event.target.dataset.edited;
  };
  chat.onsubmit = (event) => { event.preventDefault(); guard(chat.querySelector("button"), chatEdit); };
  testPicker.onchange = () => { bench.selectedBenchTest = testPicker.value; renderBenchControls(); $("#ws-bench-result").replaceChildren(); clearPlayback(); };
  $("#ws-run-bench").onclick = (event) => guard(event.currentTarget, runBenchTest);
  $("#ws-save-bench-preset").onclick = (event) => guard(event.currentTarget, saveBenchPreset);
  $("#ws-play").onclick = togglePlayback;
  $("#ws-play-reset").onclick = resetPlayback;
  timeline.oninput = () => { bench.playbackPlaying=false; $("#ws-play").textContent="Play"; setPlaybackIndex(Number(timeline.value)); };
  installPlacementControls(right);
}
installEditor();
for (const id of ["#ws-matter-cell", "#ws-matter-exterior"]) {
  $(id).addEventListener("change", () => { invalidateMatter("Settings changed. Rebuild Matter view."); clearPlayback(); $("#ws-bench-result").replaceChildren(); show(false); });
}

async function editSelected(action, material = null) {
  if (!bench.selectedPart) throw new Error("Click a component first.");
  const selected = bench.selectedPart;
  const answer = await api("/api/workshop/candidates", {
    ...candidateBody(), component_edit: { part_name:selected, action, scope:$("#ws-edit-scope").value, amount:0.12, ...(material ? {material} : {}) },
  });
  took(answer, selected);
}
async function editSkin() {
  if (!bench.selectedPart) throw new Error("Click a component first.");
  const selected = bench.selectedPart;
  const answer = await api("/api/workshop/candidates", {
    ...candidateBody(), skin_edit: {
      part_name:selected, scope:$("#ws-edit-scope").value,
      skin: {
        profile: $("#ws-skin-profile").value,
        bend_m: Number($("#ws-skin-bend").value),
        physical: $("#ws-skin-physical").checked,
        roughness: Number($("#ws-skin-roughness").value),
      },
    },
  });
  if (!took(answer, selected)) return; view = "skin"; pressView("skin"); show(false);
  if ($("#ws-skin-physical").checked) await loadMatter(true);
}
async function chatEdit() {
  if (!bench.selectedPart) throw new Error("Click the part you want to talk about first.");
  const input = $("#ws-component-chat-text"), message = input.value.trim();
  if (!message) throw new Error("Tell Workshop what to change.");
  const selected = bench.selectedPart;
  const answer = await api("/api/workshop/candidates", { ...candidateBody(), component_chat:{ part_name:selected, message } });
  if (!took(answer, selected)) return;
  if (answer.workshop_chat?.scope) $("#ws-edit-scope").value = answer.workshop_chat.scope;
  if (answer.workshop_chat?.reply) say(answer.workshop_chat.reply); input.value = "";
}
async function saveSelectedComponent() {
  const part = selectedPart(); if (!part) throw new Error("Click the component you want to save first.");
  const field = $("#ws-component-name"), name = field.value.trim() || `${part.material} ${part.role}`;
  const answer = await api("/api/workshop/library", { action:"save_component", ...candidateBody(), part_name:part.name, name });
  bench.personalLibrary = answer.personal_library || []; bench.pricebook = answer.pricebook || bench.pricebook;
  renderUserLibrary(); field.value = ""; delete field.dataset.edited; say(`Saved ${name} to My library.`);
}
async function reuseLibraryComponent(itemId) {
  if (!bench.selectedPart) throw new Error("Click a target component first.");
  const selected = bench.selectedPart;
  const answer = await api("/api/workshop/candidates", {
    ...candidateBody(), reuse_library_item:{ item_id:itemId, part_name:selected, scope:$("#ws-edit-scope").value },
  });
  took(answer, selected);
}

async function loadMatter(force = false) {
  const cell = Number($("#ws-matter-cell")?.value || 0.04);
  const exterior = Boolean($("#ws-matter-exterior")?.checked);
  const key = JSON.stringify([candidateBody(), cell, exterior]);
  const revision = bench.revision;
  if (!force && bench.matter && bench.matterKey === key) return bench.matter;
  invalidateMatter("Building Matter at the requested resolution…");
  try {
    const answer = await api("/api/workshop/plan", { ...candidateBody(), visual:{ cell_size_m:cell, exterior_only:exterior } });
    if (revision !== bench.revision || key !== JSON.stringify([candidateBody(), Number($("#ws-matter-cell").value), $("#ws-matter-exterior").checked])) return null;
    bench.matter = answer.matter || null; bench.matterKey = key;
    bench.cellSkin = answer.cell_skin || null; bench.physicsDebug = answer.physics_debug || null;
    $("#ws-inspection-basis").textContent = bench.physicsDebug?.status === "unavailable"
      ? bench.physicsDebug.reason
      : "Collision and Relations show declared design-contract zones and connections, not a native contact or load test. Section clipping changes display only; it does not cut matter.";
    bench.rigid = answer.rigid || null;
    bench.buildability = answer.buildability || null; bench.buildabilityKey = key;
    renderBuildability();
    bench.matterMeasured = answer.matter_measured || null;
    bench.matterBom = answer.matter_bom || null;
    bench.matterMasses = answer.matter_component_mass_kg || null;
    if (answer.skin) chosen().skin = answer.skin;
    if (bench.rigid) {
      $("#ws-matter-status").dataset.state = "current";
      $("#ws-matter-status").textContent = `${bench.rigid.collision_boxes} precise rigid boxes · 0 lattice cells · ${bench.rigid.mass_kg.toFixed(3)} kg · no internal or attachment failure · native bench and anchored-scenery live authoring`;
    } else if (bench.matter) {
      $("#ws-matter-status").dataset.state = bench.buildability?.compilation_ready ? "current" : "blocked";
      $("#ws-matter-status").textContent = `${bench.matter.shown_cells.toLocaleString()} shown / ${bench.matter.total_cells.toLocaleString()} physical cells · ${(bench.matter.cell_size_m*1000).toFixed(0)} mm · cell sampling bound ±${(bench.matter.surface_error_bound_m*1000).toFixed(1)} mm · ${bench.matter.physics_hash.slice(0,12)}`;
    }
    if (!bench.rigid && !bench.matter && bench.buildability) {
      $("#ws-matter-status").dataset.state = "blocked";
      $("#ws-matter-status").textContent = (bench.buildability.errors || []).join(". ");
    }
    return bench.rigid || bench.matter;
  } catch (error) {
    if (revision === bench.revision) {
      invalidateMatter(`Rebuild failed: ${error.message || error}. No current Matter result.`);
      $("#ws-matter-status").dataset.state = "error";
      show(false);
    }
    throw error;
  }
}

// Buildability is distinct from appearance and from strength-test evidence.
let buildabilityTimer = null;
let buildabilityRequest = 0;
function renderBuildability() {
  const report = bench.buildability || chosen()?.buildability;
  const summary = $("#ws-buildability-summary"), parts = $("#ws-buildability-parts");
  if (!summary || !parts) return;
  parts.replaceChildren();
  if (!report) { summary.textContent = "Not assessed. The design remains editable."; return; }
  const issues = [...(report.errors || []), ...(report.warnings || [])];
  const cost = report.costs;
  const rigid = report.requested_model === "rigid";
  const prefix = rigid ? (report.rigid?.compilation_ready
    ? `${report.rigid.collision_boxes} precise rigid boxes, zero lattice cells. Native rigid-motion bench and anchored-scenery installation available; no dynamic lattice coupling. The following is the separate lattice comparison.`
    : `Rigid compilation blocked: ${report.representation_error || "not yet assessed"}. No substitution was made.`)
    : report.assessment === "dimensions-only" ? "Design dimensions only; checking the selected grid…"
    : report.compilation_ready ? "Geometry fits this grid and bridge. Native installation verification is still required."
    : "Not buildable on this grid. Your original dimensions are preserved.";
  summary.textContent = prefix + (cost?.stored_cells != null ? ` ${cost.stored_cells.toLocaleString()} / ${report.limits.scene_cells.toLocaleString()} scene cells.` : "")
    + (cost?.collision_boxes != null ? ` ${cost.collision_boxes} / ${report.limits.joined_boxes} joined boxes.` : "")
    + (issues.length ? " " + issues.join(". ") : "") + " No bending, fracture or joint-strength certification.";
  for (const part of report.components || []) {
    if (!part.disappeared && !part.subcell_axes.length) continue;
    parts.append(make("p", {class:"ws-note"}, `${part.component}: ${part.disappeared ? "disappears; " : "subcell feature; "}`
      + `${part.size_m.map(v => (v*1000).toFixed(1)).join(" × ")} mm. ${part.recommended_model}.`));
  }
}
function scheduleBuildability() {
  renderBuildability();
  const key = JSON.stringify([candidateBody(), Number($("#ws-matter-cell")?.value || .04), Boolean($("#ws-matter-exterior")?.checked)]);
  if (key === bench.buildabilityKey || key === bench.buildabilityPending) return;
  clearTimeout(buildabilityTimer);
  const request = ++buildabilityRequest, revision = bench.revision;
  bench.buildabilityPending = key;
  buildabilityTimer = setTimeout(async () => {
    try {
      const answer = await api("/api/workshop/plan", {...candidateBody(), visual:{
        cell_size_m:Number($("#ws-matter-cell")?.value || .04), exterior_only:true}});
      if (request !== buildabilityRequest || revision !== bench.revision) return;
      bench.buildability = answer.buildability || null; bench.buildabilityKey = key;
      if (chosen()?.mechanical_model === "rigid") bench.rigid = answer.rigid || null;
      renderBuildability();
      if (chosen()?.mechanical_model === "rigid") show(false);
    } catch (error) {
      if (request === buildabilityRequest && revision === bench.revision)
        $("#ws-buildability-summary").textContent = `Buildability could not be assessed: ${error.message}. No physical result is certified.`;
    } finally { if (request === buildabilityRequest) bench.buildabilityPending = null; }
  }, 220);
}

// ---------------------------------------------------------------------------
// Bench controls, results and playback
// ---------------------------------------------------------------------------
function benchDefinition(name = bench.selectedBenchTest) { return bench.benchTests.find((item) => item.test === name) || null; }
function renderBenchCatalog() {
  // Analysis/reference tools remain callable by specialist APIs, not presented as product simulations.
  bench.benchTests = bench.benchTests.filter(t => t.category === "simulation" && t.subject === "selected-product"
    && (t.required_model || "lattice") === (chosen()?.mechanical_model || "lattice"));
  const picker = $("#ws-bench-test"); picker.replaceChildren();
  for (const test of bench.benchTests) picker.append(make("option", { value:test.test }, test.name));
  if (!bench.selectedBenchTest || !benchDefinition(bench.selectedBenchTest)) bench.selectedBenchTest = bench.benchTests[0]?.test || null;
  if (bench.selectedBenchTest) picker.value = bench.selectedBenchTest;
  picker.disabled = !bench.benchTests.length; $("#ws-run-bench").disabled = !bench.benchTests.length; $("#ws-save-bench-preset").disabled = !bench.benchTests.length;
  renderBenchControls(); renderBenchPresets();
}
let benchTestRequest = 0;
function renderBenchControls(values = null) {
  benchTestRequest++;
  const root = $("#ws-bench-controls"); root.replaceChildren(); const definition = benchDefinition();
  $("#ws-active-situation").textContent = definition?.name || "No simulation available for this product";
  root.oninput = root.onchange = () => {
    benchTestRequest++;
    $("#ws-bench-result").replaceChildren();
    clearPlayback();
  };
  if (!definition) { root.append(make("p", { class:"ws-feedback-count" }, "No working simulation is available for this product yet. Report-only tools have been removed from Test; the design is still editable.")); return; }
  root.append(make("p", { class:"ws-feedback-count" }, definition.about));
  for (const control of definition.controls || []) {
    if (control.name === "record_trace") continue;
    const label = make("label", { class:"ws-field" }, `${control.label}${control.unit ? ` (${control.unit})` : ""}`);
    const chosenValue = values && Object.prototype.hasOwnProperty.call(values, control.name) ? values[control.name] : control.default;
    let input;
    if (control.type === "boolean") { input = make("input", { type:"checkbox", "data-bench-control":control.name }); input.checked = Boolean(chosenValue); }
    else if (control.type === "select") {
      input = make("select", { "data-bench-control":control.name });
      (control.choices || []).forEach((choice,index) => { const option = make("option", { value:String(choice) }, (control.choice_labels || [])[index] || String(choice)); option.selected = String(choice) === String(chosenValue); input.append(option); });
      input.dataset.valueType = typeof control.default;
    } else if (control.type === "range") {
      input = make("input", { type:"range", min:String(control.min ?? 0), max:String(control.max ?? 100), step:String(control.step ?? "any"), "data-bench-control":control.name });
      input.value = String(chosenValue ?? control.min ?? 0); input.dataset.valueType = "number";
      const shown = make("output", { class:"ws-range-value" }, String(chosenValue ?? ""));
      const refresh = () => { shown.textContent = input.value; }; input.addEventListener("input", refresh); input.addEventListener("change", () => { refresh(); reprobe(); });
      label.append(input,shown); root.append(label); continue;
    } else {
      input = make("input", { type:"number", value:String(chosenValue ?? ""), min:String(control.min ?? ""), max:String(control.max ?? ""), step:String(control.step ?? "any"), "data-bench-control":control.name }); input.dataset.valueType = "number";
    }
    label.append(input); root.append(label);
  }
  for (const limitation of definition.limitations || []) root.append(make("p", { class:"ws-feedback-count" }, `Limit: ${limitation}`));
}
function benchConfig() {
  const definition = benchDefinition(); if (!definition) throw new Error("Choose a test first."); const out = {};
  for (const control of definition.controls || []) {
    const input = document.querySelector(`[data-bench-control="${control.name}"]`); if (!input) continue;
    if (control.optional && input.value.trim() === "") continue;
    if (input.type === "number" && (!input.checkValidity() || !Number.isFinite(input.valueAsNumber))) throw new Error(`Enter a valid ${control.label}.`);
    if (control.type === "boolean") out[control.name] = input.checked;
    else if (control.type === "number" || typeof control.default === "number") out[control.name] = Number(input.value);
    else out[control.name] = input.value;
  }
  out.record_trace = true; // Visible runs require actual simulation states.
  if (definition.test !== "rigid_motion") {
    if (bench.selectedPart && out.component === undefined) out.component = bench.selectedPart;
    if (bench.forcePoint && out.point_m === undefined) out.point_m = bench.forcePoint;
  }
  return out;
}
function renderBenchPresets() {
  const root = $("#ws-bench-presets"); root.replaceChildren(); const relevant = bench.benchPresets.filter((preset) => preset.test === bench.selectedBenchTest);
  if (!relevant.length) return; root.append(make("p", { class:"ws-feedback-count" }, "Saved test controls")); const row = make("div", { class:"ws-row" });
  for (const preset of relevant) { const button = make("button", { type:"button", class:"ws-action" }, preset.name); button.onclick = () => { renderBenchControls(preset.config || {}); $("#ws-bench-preset-name").value = preset.name; }; row.append(button); }
  root.append(row);
}
function celsius(k) { return k == null ? "—" : `${(Number(k)-273.15).toFixed(2)} °C`; }
function clearPlayback() {
  bench.playback = null; bench.playbackIndex = 0; bench.playbackPlaying = false;
  $("#ws-simulation-feedback")?.replaceChildren();
  const root = $("#ws-playback"); if (root) root.hidden = true;
  stage.dataset.physicsPlaying="false"; delete stage.dataset.physicsTime;
  if (view === "physics") { view = "wire"; pressView("wire"); show(false); }
}
function setPlayback(recording) {
  if (!recording?.frames || recording.frames.length < 2 || !(recording.duration_s > 0)) {
    clearPlayback(); throw new Error("The test returned no advancing simulation. No successful simulation is claimed.");
  }
  bench.playback=recording; bench.playbackIndex=0; bench.playbackPlaying=false;
  $("#ws-playback").hidden=false;
  const slider=$("#ws-play-timeline"); slider.max=String(recording.frames.length-1);slider.value="0";
  bench.playbackSpeed = recording.test === "kettle_heat" ? 30 : .25;
  $("#ws-play-speed").value=String(bench.playbackSpeed);
  view="physics";pressView("physics");show(false);frameSimulation(recording);
  setPlaybackIndex(0);togglePlayback();
}

function setPlaybackIndex(index, rebase = true) {
  if (!bench.playback?.frames?.length) return;
  bench.playbackIndex = Math.max(0, Math.min(bench.playback.frames.length - 1, Math.round(index)));
  $("#ws-play-timeline").value = String(bench.playbackIndex);
  const frame = bench.playback.frames[bench.playbackIndex]; $("#ws-play-time").textContent = `${Number(frame.t_s || 0).toFixed(2)} s`;
  if (rebase) { bench.playbackClock = performance.now(); bench.playbackFrom = Number(frame.t_s || 0); }
  if (view === "physics") drawPlayback();
}
function togglePlayback() {
  if (!bench.playback?.frames?.length) return;
  if (!bench.playbackPlaying && bench.playbackIndex >= bench.playback.frames.length-1) setPlaybackIndex(0);
  bench.playbackPlaying = !bench.playbackPlaying; $("#ws-play").textContent = bench.playbackPlaying ? "Pause" : "Play";
  bench.playbackClock = performance.now(); bench.playbackFrom = Number(bench.playback.frames[bench.playbackIndex]?.t_s || 0);
}
function resetPlayback() { bench.playbackPlaying = false; if ($("#ws-play")) $("#ws-play").textContent = "Play"; setPlaybackIndex(0); }
function advancePlayback(now) {
  stage.dataset.physicsPlaying=String(bench.playbackPlaying);
  if (!bench.playbackPlaying || !bench.playback?.frames?.length) return;
  const frames = bench.playback.frames, targetTime = bench.playbackFrom + (now - bench.playbackClock) / 1000 * bench.playbackSpeed;
  let i = bench.playbackIndex; while (i + 1 < frames.length && Number(frames[i+1].t_s) <= targetTime) i++;
  if (i !== bench.playbackIndex) setPlaybackIndex(i, false);
  if (i >= frames.length - 1) { bench.playbackPlaying = false; $("#ws-play").textContent = "Replay"; }
}
function renderJointScreen(card, screen) {
  bench.jointVerdicts = null;
  if (!screen) return;
  if (screen.available === false) { card.append(make("p", { class:"ws-note", id:"ws-joint-screen-note" }, `Joints not screened: ${screen.why}`)); return; }
  bench.jointVerdicts = Object.fromEntries((screen.joints || []).map((row) => [row.joint, row.verdict]));
  const box = make("div", { id:"ws-joint-screen", "data-gives-way":String((screen.gives_way || []).length) });
  const first = screen.first_to_give;
  box.append(make("strong", {}, (screen.gives_way || []).length
    ? `${screen.gives_way.length} joint${screen.gives_way.length === 1 ? "" : "s"} would give way`
    : "No joint is past its strength"));
  if (first?.joint) box.append(make("p", { id:"ws-first-to-give" }, `Pushed like this, the first to go is ${first.a} ↔ ${first.b}, ${first.would_be}, at about ${Number(first.force_n).toLocaleString(undefined, { maximumFractionDigits:0 })} N.`));
  else if (first?.why) box.append(make("p", { id:"ws-first-to-give" }, first.why));
  if ((screen.comes_apart_into || []).length > 1) box.append(make("p", { id:"ws-comes-apart" },
    `It would come apart into ${screen.comes_apart_into.length} pieces: ` + screen.comes_apart_into.map((piece) => piece.length > 3 ? `${piece[0]} and ${piece.length - 1} more` : piece.join(" + ")).join("; ") + "."));
  const floorNote = (screen.limitations || []).find((line) => line.startsWith("Not held by the floor"));
  if (floorNote) box.append(make("p", { class:"ws-note warn", id:"ws-screen-floor-note" }, floorNote));
  box.append(make("p", { class:"ws-feedback-count" }, `It is ${screen.standing}. One is all of a joint's strength; between a half and one is uncertain, because a sharp blow can load a joint up to about twice what a steady push does.`));
  const list = make("ul", { class:"ws-joint-list" });
  for (const row of (screen.joints || []).slice(0, 8)) {
    const item = make("li", { class:`ws-joint-row screened ${String(row.verdict).replace(" ", "-")}`, "data-joint":row.joint });
    const used = row.utilisation == null ? null : Number(row.utilisation);
    item.append(make("span", { class:`ws-joint-kind ${String(row.verdict).replace(" ", "-")}` }, row.verdict),
      make("span", { class:"ws-joint-parts" }, `${row.a} ↔ ${row.b}`),
      make("small", {}, used == null ? (row.why || "not rated") : `${used >= 0.1 ? (used * 100).toFixed(0) : (used * 100).toPrecision(2)}% of its strength · would be ${row.would_be}`));
    const bar = make("span", { class:"ws-joint-bar" }); const fill = make("i");
    fill.style.width = `${Math.min(100, (used || 0) * 100)}%`; bar.append(fill); item.append(bar); list.append(item);
  }
  box.append(list);
  if ((screen.joints || []).length > 8) box.append(make("p", { class:"ws-feedback-count" }, `and ${screen.joints.length - 8} more joints, all loaded less.`));
  card.append(box);
  if (view === "wire" || view === "skin") show(false);
}
function renderBenchResult(result) {
  const root = $("#ws-bench-result"); root.replaceChildren(); if (!result) return;
  const card = make("div", { class:"ws-note" });
  if (result.test === "rigid_motion") {
    const m = result.measured || {};
    card.append(make("strong", {}, "Native precise rigid motion — not a strength test"),
      make("p", {}, `${m.collision_boxes} exact boxes · ${m.stored_cells} lattice cells · ${Number(m.mass_kg).toFixed(3)} kg`),
      make("p", {}, `Centre of mass moved ${Number(m.displacement_m).toFixed(4)} m in ${Number(m.elapsed_s).toFixed(2)} s.`));
  } else if (["drop_product","slide_product"].includes(result.test)) {
    const m=result.measured || {}, r=result.requested || {};
    card.append(make("strong",{},result.test==="drop_product" ? "Drop completed" : "Slide completed"),
      make("p",{},result.test==="drop_product" ? `Requested height ${r.height_m} m · grid height ${r.applied_height_m} m` : `Starting speed ${r.speed_m_s} m/s along +X`),
      make("p",{},`Final displacement ${m.prototype_displacement_m == null ? "unavailable after separation" : Number(m.prototype_displacement_m).toFixed(3)+" m"} · ${m.fracture_events} fracture evaluations · ${m.clock_s.toFixed(2)} s simulated`));
  } else if (result.test === "cart_roll") {
    const m=result.measured || {};
    card.append(make("strong",{},"Cart run completed"),make("p",{},`Chassis displacement (X/Y/Z): ${(m.chassis_delta_m || []).map(v=>Number(v).toFixed(3)).join(" / ")} m`),
      make("p",{},`${m.joint_count} joints · ${(m.axle_turns || []).map(a=>`${a.axle}: ${Number(a.degrees).toFixed(1)}°`).join("; ")}`));
  } else if (result.test === "kettle_heat") {
    const m = result.measured || {}; card.append(make("strong", {}, `Water: ${celsius(m.water_start_k)} → ${celsius(m.water_end_k)}`),
      make("p", {}, `Kettle bottom ${celsius(m.kettle_bottom_k)} · heater plate ${celsius(m.heater_plate_k)}`));
    const heaterIn = m.ledger?.heater_in_j; if (heaterIn != null) card.append(make("p", {}, `External heat added: ${(Number(heaterIn)/1000).toFixed(1)} kJ`));
  } else if (result.test === "machine_control") {
    const m = result.measured || {}, control = m.control || {}, motor = m.motor || {}, battery = m.battery || {};
    card.append(make("strong", {}, `Controller: ${control.condition || "—"}`),
      make("p", {}, `Power ${control.power ? "on" : "off"} · direction ${control.direction ?? "—"} · setting ${control.setting == null ? "—" : `${(Number(control.setting)*100).toFixed(0)}%`}`),
      make("p", {}, `Speed ${Number(control.speed_rpm || 0).toFixed(1)} rpm · load moved ${Number(m.load_delta_y_m || 0).toFixed(3)} m`),
      make("p", {}, `Motor ${Number(motor.power_w || 0).toFixed(1)} W · battery supplied ${Number(battery.given_j || 0).toFixed(1)} J`));
  } else if (result.trial === "static_load" || result.test === "static_load") {
    const m = result.measured || {}; card.append(make("strong", {}, "Physical load trial"),
      make("p", {}, `Requested ${m.requested_load_kg} kg · applied ${m.actual_grid_load_kg} kg. Little or no movement means the object held in this model—not that bending strength is certified.`),
      make("p", {}, `Displacement ${m.prototype_displacement_m == null ? "unavailable" : Number(m.prototype_displacement_m).toFixed(4) + " m"} · rotation ${m.prototype_rotation_change_deg == null ? "unavailable" : Number(m.prototype_rotation_change_deg).toFixed(2) + "°"} · fractures ${(m.fractures || []).length}`));
  } else if (result.test === "force_probe") {
    const target = result.target || {}, asked = result.requested || {}; card.append(make("strong", {}, `Force probe · ${target.component || "component"}`),
      make("p", {}, `${Number(asked.force_n || 0).toFixed(0)} N at ${(target.point_m || []).map((v) => Number(v).toFixed(2)).join(", ")} m`));
    renderJointScreen(card, result.joint_screen);
  } else if (result.test === "runtime_contract") {
    const s = result.summary || {}; card.append(make("strong", {}, "Runtime physics compiled"),
      make("p", {}, `${s.detailed_components || 0} detailed components → ${s.runtime_bodies || 0} runtime bodies · ${s.mechanisms || 0} mechanisms`));
  }
  if (result.acceptance) card.append(make("p", {}, `Acceptance: ${result.acceptance.status} — ${result.acceptance.why || ""}`));
  if (result.prototype?.matter_physics_hash) card.append(make("p", {}, `Tested Matter ${result.prototype.matter_physics_hash.slice(0,12)} · ${result.prototype.matter_cells} cells`));
  if (result.trial === "static_load") {
    const acceptance = result.acceptance || {};
    const status = acceptance.status || "not-declared";
    const label = status === "not-declared" ? "not evaluated (no limits declared)" : status;
    card.append(make("strong", { id:"ws-acceptance-status", "data-status":status }, `Declared limits: ${label}`));
    for (const check of acceptance.checks || []) {
      if (check.status === "passed") continue;
      const actual = check.measured == null ? "not measured" : JSON.stringify(check.measured);
      card.append(make("p", {}, `${check.metric}: ${actual}; ${check.operator} ${JSON.stringify(check.limit)}${check.unit ? ` ${check.unit}` : ""} (${check.status}).`));
    }
    if (acceptance.scope === "this-exact-run") card.append(make("p", {}, acceptance.why));
  }
  if (card.childNodes.length) root.append(card);
  if (result.playback) setPlayback(result.playback);
  for (const limitation of result.limitations || []) root.append(make("p", { class:"ws-feedback-count" }, limitation));
  const details = make("details", { class:"ws-family" }); details.append(make("summary", {}, "Measured evidence"));
  const pre = make("pre"); pre.textContent = JSON.stringify({...result, playback:result.playback ? {test:result.playback.test,geometry_basis:result.playback.geometry_basis,duration_s:result.playback.duration_s,states:result.playback.frames.length,sampling:result.playback.sampling} : undefined}, null, 2); details.append(pre); root.append(details);
}
async function runBenchTest() {
  const definition=benchDefinition(); if(!definition) throw new Error("Choose a supported simulation first.");
  const revision=bench.revision, request=++benchTestRequest, config=benchConfig();
  const current=()=>request===benchTestRequest && revision===bench.revision && definition.test===bench.selectedBenchTest;
  clearPlayback();
  const status=make("p",{id:"ws-simulation-status",role:"status","aria-live":"polite"},`Calculating ${definition.name.toLowerCase()} on the selected object…`);
  status.dataset.state="running"; $("#ws-simulation-feedback").replaceChildren(status); $("#ws-bench-result").replaceChildren();
  try {
    const answer=await api("/api/workshop/plan",{...candidateBody(),bench_test:{test:definition.test,config}});
    if(!current()) return;
    if (!answer.bench?.playback?.frames || answer.bench.playback.frames.length < 2) throw new Error("No visible simulation was returned. This test is not complete.");
    renderBenchResult(answer.bench);
    status.dataset.state="complete";status.textContent="Simulation complete. Showing calculated behavior; use Pause or Replay to inspect it.";
    $("#ws-simulation-feedback").replaceChildren(status);
  } catch(error) {
    if(!current())return;
    clearPlayback(); status.dataset.state="error";
    status.textContent=`Simulation did not run: ${error.message}`; $("#ws-simulation-feedback").replaceChildren(status); $("#ws-bench-result").replaceChildren();
    throw error;
  }
}

async function saveBenchPreset() {
  const definition = benchDefinition(); if (!definition) throw new Error("Choose a test first.");
  const name = $("#ws-bench-preset-name").value.trim() || `${definition.name} preset`;
  const answer = await api("/api/workshop/library", { action:"save_bench_preset", name, test:definition.test, config:benchConfig() });
  bench.benchPresets = answer.bench_presets || []; renderBenchPresets(); say(`Saved test preset ${name}.`);
}

// ---------------------------------------------------------------------------
// Panels
// ---------------------------------------------------------------------------
function savedDesigns(rows) {
  bench.savedDesigns = Array.isArray(rows) ? rows : []; const root = $("#ws-saved-designs"); root.replaceChildren();
  if (!bench.savedDesigns.length) { root.append(make("p", { class:"ws-feedback-count" }, "No saved designs yet.")); return; }
  for (const saved of bench.savedDesigns) {
    const button = make("button", { type:"button", class:"ws-card" }); button.append(make("strong", {}, saved.label || saved.design_id),
      make("small", {}, `${saved.kind} · revision ${saved.revision}${saved.measured ? ` · ${saved.measured.mass_kg} kg` : ""}`));
    button.onclick = () => guard(button, async () => { const answer = await api("/api/workshop/open", { saved_design_id:saved.design_id }); bench.openedLibraryItem = null; if (took(answer)) $("#ws-archetype").value = answer.kind; }); root.append(button);
  }
}
function renderUserLibrary() {
  renderBuildChoices();
  const root = $("#ws-user-library"); root.replaceChildren();
  if (!bench.personalLibrary.length) { root.append(make("p", { class:"ws-feedback-count" }, "Nothing saved yet. Select a part and save it.")); return; }
  for (const item of bench.personalLibrary) {
    const card = make("button", { type:"button", class:"ws-card ws-library-item", draggable:"true" });
    card.append(make("strong", {}, item.name), make("small", {}, `${item.item_type}${item.family ? ` · ${item.family}` : ""} · v${item.version}`));
    card.ondragstart = (event) => { event.dataTransfer.setData("application/x-banjo-library-item", item.item_id); event.dataTransfer.effectAllowed = "copy"; };
    card.onclick = () => guard(card, async () => {
      if (item.item_type === "assembly") { const answer = await api("/api/workshop/open", { library_item_id:item.item_id }); bench.openedLibraryItem = item.item_id; if (took(answer)) $("#ws-archetype").value = answer.kind; }
      else if (bench.selectedPart) await reuseLibraryComponent(item.item_id); else say("Select a component, then click or drag this saved component onto it.");
    }); root.append(card);
  }
}
// The product library is a tree: a row per product, and under the open one a
// child row per distinct component with its quantity. Names alone carry the
// rows; every card once repeated "Open <name> in the Workshop", which said
// nothing a button does not already say.
function componentGroups(candidate) {
  const groups = new Map();
  for (const part of candidate.parts) {
    const base = part.name.replace(/-\d+$/, "");
    const size = (part.size_m || []).map((v) => Math.round(v * 1000)).join("x");
    const key = [base, part.role, part.material, size].join("|");
    let group = groups.get(key);
    if (!group) { group = { base, role:part.role, family:part.family, material:part.material, names:[], mass:0 }; groups.set(key, group); }
    group.names.push(part.name); group.mass += Number(part.mass_kg) || 0;
  }
  return [...groups.values()];
}
function productParts(candidate) {
  const list = make("ul", { class:"ws-product-parts" });
  for (const group of componentGroups(candidate)) {
    const first = group.names[0], row = make("li", { class:"ws-part-row" });
    const open = make("button", { type:"button", class:"ws-part-open", "data-part":first });
    open.append(make("span", { class:"ws-part-name" }, group.base));
    if (group.names.length > 1) open.append(make("span", { class:"ws-part-qty" }, `× ${group.names.length}`));
    open.title = `${group.role} · ${group.material} · ${group.mass.toFixed(3)} kg total`;
    if (group.names.includes(bench.selectedPart)) { row.classList.add("selected"); open.setAttribute("aria-current", "true"); }
    if (group.names.includes(bench.isolated)) row.classList.add("alone");
    open.onclick = () => { openComponent(first); };
    const copy = make("button", { type:"button", class:"ws-part-copy", title:`Copy ${group.base} into My library` }, "Copy");
    copy.onclick = () => guard(copy, () => copyComponent(first, group.base));
    row.append(open, copy); list.append(row);
  }
  if (!list.childElementCount) list.append(make("li", { class:"ws-feedback-count" }, "No components yet."));
  return list;
}
function openComponent(partName) {
  bench.selectedPart = partName; bench.isolated = partName;
  // Matter, collision, relations and physics are whole-product views; a single
  // component has nothing to show in them, so open it in the design view.
  if (!ISOLATING_VIEWS.includes(view)) { view = "wire"; pressView(view); }
  const part = (chosen()?.parts || []).find((p) => p.name === partName);
  const suggested = $("#ws-component-name");
  if (suggested && !suggested.dataset.edited) suggested.value = part ? `${bench.kind} ${partName}` : "";
  show();
  // The component editor lives in the Build tab of the shell, if the shell is there.
  document.querySelector('.ws-workspace-tabs button[data-mode="build"]')?.click();
  $("#ws-component-editor")?.scrollIntoView({ block:"start" });
}
function showWholeProduct() {
  bench.isolated = null; show(); renderProductCatalog();
}
async function copyComponent(partName, label) {
  if (!chosen()) throw new Error("Open a product first.");
  const name = `${bench.kind} ${label}`;
  const answer = await api("/api/workshop/library", { action:"save_component", ...candidateBody(), part_name:partName, name });
  bench.personalLibrary = answer.personal_library || bench.personalLibrary;
  bench.pricebook = answer.pricebook || bench.pricebook;
  renderUserLibrary(); say(`Copied ${name} into My library.`);
}
let catalogSignature = null, lastOpenProduct = null;
function renderProductCatalog() {
  const root = $("#ws-product-catalog"), picker = $("#ws-archetype");
  if (!root || !picker) return;
  // Opening a product expands it, however it was opened: a card, the native
  // picker, a saved design or a library assembly. Clicking the open row toggles.
  if (picker.value !== lastOpenProduct) { lastOpenProduct = picker.value; bench.expandedProduct = picker.value; }
  const candidate = chosen(), kinds = [...picker.options].map((o) => o.value);
  const signature = JSON.stringify([kinds, picker.value, bench.expandedProduct, bench.selectedPart, bench.isolated,
    candidate ? candidate.parts.map((p) => p.name) : null]);
  if (signature === catalogSignature) return;
  catalogSignature = signature; root.replaceChildren();
  for (const option of [...picker.options]) {
    const current = option.value === picker.value;
    const expanded = current && bench.expandedProduct === option.value && Boolean(candidate);
    const entry = make("div", { class:"ws-product-entry" });
    const card = make("button", { type:"button", class:"ws-product-card", "data-value":option.value,
      "aria-current":current ? "true" : "false", "aria-expanded":expanded ? "true" : "false" },
      option.textContent || option.value);
    if (option.title) card.title = option.title;
    card.onclick = () => guard(card, async () => {
      if (picker.value !== option.value) {
        picker.value = option.value; picker.dispatchEvent(new Event("change", { bubbles:true }));
      } else if (bench.isolated) { showWholeProduct(); }
      else { bench.expandedProduct = expanded ? null : option.value; catalogSignature = null; renderProductCatalog(); }
    });
    entry.append(card);
    if (expanded) entry.append(productParts(candidate));
    root.append(entry);
  }
}
function renderBom(candidate) {
  const root = $("#ws-bom"); root.replaceChildren(); const bom = candidate.mechanical_model !== "rigid" && ["matter", "collision", "relations"].includes(view) && bench.matterBom ? bench.matterBom : candidate.bom;
  if (!bom) { root.append(make("p", { class:"ws-feedback-count" }, "No material estimate.")); return; }
  const table = make("table", { class:"ws-bom-table" });
  for (const row of bom.materials || []) { const tr = make("tr"); tr.append(make("td", {}, row.material), make("td", {}, `${row.mass_kg} kg`), make("td", {}, row.cost == null ? "unpriced" : `${row.cost} cr`)); table.append(tr); }
  root.append(table, make("p", { class:"ws-bom-total" }, `Material cost: ${bom.material_cost} credits`), make("p", { class:"ws-feedback-count" }, bom.basis));
}
function renderIsolation() {
  const bar = $("#ws-isolation"); if (!bar) return;
  const alone = isolatedPart();
  bar.hidden = !alone;
  if (alone) $("#ws-isolation-note").textContent = `Working on ${alone.name} on its own.`;
  $("#ws-show-whole").textContent = `Show the whole ${bench.kind.replace("-", " ")}`;
  // Matter, collision, relations and physics measure the assembled product.
  document.querySelectorAll(".ws-viewbar button").forEach((button) => {
    const whole = !ISOLATING_VIEWS.includes(button.dataset.view);
    button.disabled = Boolean(bench.isolated) && whole;
    button.title = button.disabled ? "This view measures the whole product. Show it to use this view." : "";
  });
}
function renderSelected() {
  const part = selectedPart(), status = $("#ws-selected-part"), material = $("#ws-part-material");
  document.querySelectorAll("[data-component-edit], #ws-save-component, #ws-component-name, #ws-part-material, #ws-apply-skin")
    .forEach((element) => { element.disabled = !part; });
  renderIsolation();
  if (!part) {
    status.textContent = "Click a part of the object to edit it."; material.replaceChildren();
    $("#ws-skin-profile").value = "design"; $("#ws-skin-bend").value = "0";
    $("#ws-skin-bend-value").textContent = "0 m"; $("#ws-skin-physical").checked = false;
    $("#ws-skin-roughness").value = "0.72"; $("#ws-skin-roughness-value").textContent = "0.72";
    return;
  }
  status.textContent = `${part.name} · ${part.role}${part.family ? ` · ${part.family}` : ""} · ${part.material} · ${(part.size_m[0]*1000).toFixed(0)} × ${(part.size_m[1]*1000).toFixed(0)} × ${(part.size_m[2]*1000).toFixed(0)} mm`;
  material.replaceChildren(); const names = (bench.pricebook?.materials || []).map((item) => item.material); if (!names.includes(part.material)) names.push(part.material);
  names.sort().forEach((name) => { const option = make("option", { value:name }, name); option.selected = name === part.material; material.append(option); });
  const descriptor = skinPart(chosen(), part.name) || {};
  $("#ws-skin-profile").value = descriptor.profile || "design";
  $("#ws-skin-bend").value = String(descriptor.kind === "bezier_tube" ? Math.abs(descriptor.control_points_local_m?.[1]?.[0] || 0) * Math.sign(descriptor.control_points_local_m?.[1]?.[0] || 0) : 0);
  $("#ws-skin-bend-value").textContent = `${Number($("#ws-skin-bend").value).toFixed(2)} m`;
  $("#ws-skin-roughness").value = String(descriptor.roughness ?? 0.72); $("#ws-skin-roughness-value").textContent = Number(descriptor.roughness ?? 0.72).toFixed(2);
  $("#ws-skin-physical").checked = Boolean(descriptor.physical);
}
// What the four tiles and the title report has to be what the viewport shows:
// the product's balance means nothing while one component is alone on screen.
function metricLabel(id, text) {
  const label = $(id)?.previousElementSibling;
  if (label && label.tagName === "SPAN") label.textContent = text;
}
function headline(candidate, m) {
  const alone = isolatedPart();
  for (const id of ["#ws-buildability", "#ws-measurement-basis"]) { const box = $(id); if (box) box.hidden = Boolean(alone); }
  if (alone) {
    const mm = alone.size_m.map((v) => (v * 1000).toFixed(0));
    $("#ws-name").textContent = alone.name;
    $("#ws-purpose").textContent = `One ${alone.role.replace(/_/g, " ")} of the ${bench.kind.replace("-", " ")}.`;
    metricLabel("#ws-part-count", "Material"); $("#ws-part-count").textContent = alone.material;
    metricLabel("#ws-mass", "Mass"); $("#ws-mass").textContent = `${Number(alone.mass_kg).toFixed(3)} kg`;
    metricLabel("#ws-base", "Size"); $("#ws-base").textContent = `${mm[0]} × ${mm[1]} × ${mm[2]} mm`;
    metricLabel("#ws-tip", "Family"); $("#ws-tip").textContent = alone.family || alone.role.replace(/_/g, " ");
    return;
  }
  $("#ws-name").textContent = candidate.label || candidate.design_id;
  $("#ws-purpose").textContent = candidate.purpose;
  metricLabel("#ws-part-count", "Parts"); $("#ws-part-count").textContent = candidate.parts.length;
  metricLabel("#ws-mass", "Mass"); $("#ws-mass").textContent = `${Number(m.mass_kg).toFixed(3)} kg`;
  metricLabel("#ws-base", "Stands on"); $("#ws-base").textContent = `${m.support_footprint_m[0].toFixed(2)} × ${m.support_footprint_m[1].toFixed(2)} m`;
  metricLabel("#ws-tip", "Tips at"); $("#ws-tip").textContent = m.geometry_coherent === false ? "not validated" : `${Number(m.tip_angle_deg).toFixed(2)}°`;
}
function show(reframe = true) {
  // The buildability panel is hidden while one component is alone on screen;
  // do not pay for an analysis of the whole product that nobody can read.
  if (chosen() && !bench.isolated) scheduleBuildability();
  if ($("#ws-mechanical-model") && chosen()) $("#ws-mechanical-model").value = chosen().mechanical_model === "rigid" ? "rigid" : "lattice";
  const candidate = chosen(); if (!candidate) return;
  if (bench.selectedPart && !candidate.parts.some((part) => part.name === bench.selectedPart)) bench.selectedPart = null;
  draw(candidate); if (reframe) frameCandidate();
  const m = currentMeasurements(candidate); headline(candidate, m);
  const parts = $("#ws-parts"); parts.replaceChildren();
  for (const part of candidate.parts) { const row = make("li"), button = make("button", { type:"button", class:"ws-part-link" }, part.name); button.onclick = () => { if (bench.isolated) { openComponent(part.name); return; } bench.selectedPart = part.name; show(false); }; row.append(button, document.createTextNode(` · ${part.role} · ${part.material} · ${Number(candidate.mechanical_model === "rigid" ? (bench.rigid?.components.find(p => p.component === part.name)?.mass_kg ?? part.mass_kg) : (["matter", "collision", "relations"].includes(view) && bench.matterMasses ? bench.matterMasses[part.name] || 0 : part.mass_kg)).toFixed(4)} kg`)); parts.append(row); }
  renderSelected(); renderBuild(); renderBom(candidate); renderProductCatalog();
  const checks = $("#ws-checks"); checks.className = "ws-note"; const said = [];
  if (m.geometry_coherent === false) { checks.classList.add("bad"); said.push("Connectivity is unresolved; this is not a validated assembled product."); }
  else if (!m.stands_up) { checks.classList.add("bad"); said.push("Its geometric balance point is outside the support region."); }
  else said.push(`Balanced ${m.smallest_tip_margin_m} m inside its nearest edge; geometric tip angle ${m.tip_angle_deg}°.`);
  if (m.legs_not_under_the_top.length) { checks.classList.add("warn"); said.push(`${m.legs_not_under_the_top.join(", ")} meet nothing.`); }
  const stat = ((candidate.analytical || {}).static_loads || [])[0]; if (stat && m.basis !== "canonical-matter-grid") said.push(`Wireframe analytical ${stat.external_load_kg} kg load: ${stat.max_support.name} carries about ${stat.max_support.equivalent_load_kg} kg equivalent.`);
  if (candidate.mechanical_model === "rigid" && bench.rigid) said.push(`Precise rigid: ${bench.rigid.collision_boxes} exact boxes, zero lattice cells. No strength calculation.`);
  else if (view === "matter" && bench.matter) said.push(`Matter: ${bench.matter.shown_cells.toLocaleString()} cells shown at ${(bench.matter.cell_size_m*1000).toFixed(0)} mm.`);
  if (view === "physics" && bench.playback) said.push(`Physics: calculated ${bench.playback.frames.length} simulation states over ${Number(bench.playback.duration_s || 0).toFixed(2)} s.`);
  said.push(...(m.warnings || []));
  $("#ws-measurement-basis").textContent = m.basis === "precise-rigid-geometry"
    ? "Mass and inertia from exact rigid dimensions; cell width does not change this model. No internal deformation or failure calculation."
    : m.basis === "canonical-matter-grid"
    ? `Mass/balance from Matter at ${(m.cell_size_m*1000).toFixed(0)} mm · ${m.matter_physics_hash.slice(0,12)}. ${m.geometry_coherent === false ? "Connections unresolved. " : ""}Strength requires a test.`
    : "Wireframe estimates, not a physical test. Matter view reports grid measurements.";
  if (view === "matter" && !bench.matter && !bench.rigid) said.push("No current Matter result: rebuild it.");
  checks.textContent = said.join(" "); $("#ws-plan").hidden = true;
}

function took(answer, keepPart = null) {
  if (answer.clientRequest != null && answer.clientRequest !== candidateRequest) return false;
  bench.revision++;
  stage.dataset.kind = answer.kind; stage.dataset.revision = String(bench.revision);
  bench.kind = answer.kind; bench.generation = answer.generation; bench.candidates = answer.candidates; bench.selected = 0;
  bench.selectedPart = keepPart; bench.isolated = keepPart && bench.isolated ? keepPart : null;
  bench.forcePoint = null; invalidateMatter(); clearPlayback();
  if (build.placing) stopPlacing(); ensureKindOption(answer.kind); bench.jointVerdicts = null;
  $("#ws-push-result")?.replaceChildren(); showForceAt(null);
  $("#ws-bench-result").replaceChildren(); $("#ws-save-status").textContent = "";
  if (answer.session) bench.session = answer.session; if (answer.saved_designs) savedDesigns(answer.saved_designs);
  if (answer.personal_library) { bench.personalLibrary = answer.personal_library; renderUserLibrary(); }
  if (answer.pricebook) bench.pricebook = answer.pricebook; if (answer.bench_tests) bench.benchTests = answer.bench_tests; if (answer.bench_presets) bench.benchPresets = answer.bench_presets;
  renderBenchCatalog(); show();
  return true;
}

// ---------------------------------------------------------------------------
// Building part by part (mcp/workshop_construction.py). The page decides no
// geometry here either: it says what to add and where the person clicked, and
// draws the part where the server says it would go.
// ---------------------------------------------------------------------------

// Where a point of the object is on the page, so that a test (or a tool) can
// click a face of it rather than a pixel that a change of framing would move.
stage.pagePointOf = (point) => {
  const v = new THREE.Vector3(...point).project(camera), r = stage.getBoundingClientRect();
  return [r.left + (v.x + 1) / 2 * r.width, r.top + (1 - v.y) / 2 * r.height];
};
function clearGhost() {
  for (const child of [...ghost.children]) { ghost.remove(child); if (child.geometry) child.geometry.dispose(); disposeMaterial(child.material); }
}
function drawGhost(part, touching) {
  clearGhost();
  const color = touching ? 0x5fd38d : 0xe0a63a;
  const mesh = new THREE.Mesh(shapeFor(part), new THREE.MeshStandardMaterial({ color, transparent:true, opacity:0.5, depthWrite:false }));
  mesh.position.set(...part.center_m); mesh.rotation.copy(spinFor(part.rotation_deg)); ghost.add(mesh);
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry), new THREE.LineBasicMaterial({ color:0xeaffef }));
  edges.position.copy(mesh.position); edges.rotation.copy(mesh.rotation); ghost.add(edges);
}
function drawJoints(candidate) {
  const size = Math.max(0.008, reach * 0.014);
  for (const joint of candidate.construction?.joints || []) {
    const how = joint.interface; if (joint.open || !how?.centre_m) continue;
    // After a push, a joint shows how hard it was loaded rather than what kind it is.
    const verdict = bench.jointVerdicts?.[joint.id];
    const dot = new THREE.Mesh(new THREE.SphereGeometry(verdict === "gives way" ? size * 1.7 : size, 12, 8),
      new THREE.MeshBasicMaterial({ color:verdict ? VERDICT_COLORS[verdict] : (JOINT_COLORS[joint.kind] ?? 0xffffff), depthTest:false, transparent:true, opacity:0.95 }));
    dot.position.set(...how.centre_m); dot.renderOrder = 5; dot.userData.jointId = joint.id; group.add(dot);
    const axis = joint.kind === "bearing" ? (how.axis || how.normal) : null;
    if (axis) {
      const a = new THREE.Vector3(...how.centre_m), d = new THREE.Vector3(...axis).multiplyScalar(size * 5);
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a.clone().sub(d), a.clone().add(d)]),
        new THREE.LineBasicMaterial({ color:JOINT_COLORS.bearing, depthTest:false }));
      line.renderOrder = 5; group.add(line);
    }
  }
}

function buildFamily() {
  const value = $("#ws-build-what")?.value || "";
  return value.startsWith("family:") ? (bench.families || []).find((f) => f.family === value.slice(7)) : null;
}
function renderBuildSizes() {
  const root = $("#ws-build-sizes"); if (!root) return; root.replaceChildren();
  const family = buildFamily(); $("#ws-build-material").closest("label").hidden = !family;
  if (!family) { root.append(make("p", { class:"ws-feedback-count" }, "A saved component comes in at the size and material it was saved with.")); return; }
  if ((family.offers || []).includes("start")) {
    const label = make("label", { class:"ws-field" }, "Length (m)");
    label.append(make("input", { id:"ws-build-length", type:"number", min:"0.005", max:"20", step:"0.005", value:"0.5" })); root.append(label);
  }
  for (const p of family.parameters) {
    if (["lean_x", "lean_z", "splay_deg", "style"].includes(p.name)) continue;   // a part stands as it is placed
    const label = make("label", { class:"ws-field" }, `${p.name.replace(/_m$/, "").replaceAll("_", " ")}${p.unit ? ` (${p.unit})` : ""}`);
    let input;
    if (p.choices) { input = make("select", { "data-parameter":p.name }); p.choices.forEach((c) => addOption(input, c, c)); input.value = p.default; }
    else input = make("input", { "data-parameter":p.name, type:"number", min:String(p.low ?? 0), max:String(p.high ?? 20), step:"0.005", value:String(p.default) });
    input.addEventListener("change", () => { if (build.placing) previewPlacement(); });
    label.append(input); root.append(label);
  }
}
function partRequest() {
  const what = $("#ws-build-what").value;
  if (what.startsWith("item:")) return { library_item_id:what.slice(5) };
  const family = buildFamily(); if (!family) throw new Error("Choose what to add first.");
  const parameters = {};
  document.querySelectorAll("#ws-build-sizes [data-parameter]").forEach((input) => {
    parameters[input.dataset.parameter] = input.tagName === "SELECT" ? input.value : Number(input.value);
  });
  const out = { family:family.family, material:$("#ws-build-material").value, parameters };
  if ($("#ws-build-length")) out.length_m = Number($("#ws-build-length").value);
  return out;
}
function placement(action) {
  const fasten = $("#ws-build-fasten").value;
  return { action, part:partRequest(), by:$("#ws-build-by").value, onto:build.onto, at_m:build.at,
    twist_deg:build.twist, depth_m:build.depth, snap:$("#ws-build-snap").checked,
    ...(action === "add" && fasten !== "none" ? { joint:{ kind:fasten } } : {}) };
}
function sayBuild(message, bad = false) {
  const status = $("#ws-build-status"); if (!status) return;
  status.textContent = message; status.classList.toggle("bad", bad);
}
function stopPlacing(message = "") {
  build.placing = false; build.onto = null; build.at = null; build.twist = 0; build.depth = 0; build.preview = null; build.request++;
  clearGhost(); stage.classList.remove("ws-placing");
  const start = $("#ws-build-place"); if (start) start.textContent = "Place it: click where it goes";
  if ($("#ws-build-adjust")) $("#ws-build-adjust").hidden = true;
  sayBuild(message);
}
async function previewPlacement() {
  if (!build.placing || !build.onto) return;
  const mine = ++build.request, revision = bench.revision;
  try {
    const answer = await api("/api/workshop/candidates", { ...candidateBody(), construct:placement("preview") });
    if (mine !== build.request || revision !== bench.revision || !build.placing) return;
    build.preview = answer.construct; const part = build.preview.part, touching = build.preview.touching;
    drawGhost(part, touching); $("#ws-build-adjust").hidden = false;
    const met = !touching ? `It does not meet ${build.onto} over any flat area, so it cannot be fastened there. A round side has none: use its end, or sink the part in until the shaft runs into it.`
      : touching.form === "planar" ? `Meets ${build.onto} over ${(touching.area_m2 * 1e4).toFixed(1)} cm²${touching.mitred ? " (cut to sit flat)" : ""}.`
      : `A ${(touching.diameter_m * 1000).toFixed(0)} mm shaft, ${(touching.engaged_m * 1000).toFixed(0)} mm of it inside ${build.onto}.`;
    sayBuild(`${part.name}: ${(part.size_m[0]*1000).toFixed(0)} × ${(part.size_m[1]*1000).toFixed(0)} × ${(part.size_m[2]*1000).toFixed(0)} mm, ${part.mass_kg} kg. ${met}`, !touching && $("#ws-build-fasten").value !== "none");
  } catch (error) { if (mine === build.request) sayBuild(String(error.message || error), true); }
}
function placeAtHit(hit) {
  const name = hitPartName(hit);
  if (!name) { sayBuild("Click on a part of the object: the new part goes against it.", true); return; }
  build.onto = name; build.at = [hit.point.x, hit.point.y, hit.point.z]; previewPlacement();
}
async function addPlaced() {
  if (!build.preview) throw new Error("Click where the part goes first.");
  const answer = await api("/api/workshop/candidates", { ...candidateBody(), construct:placement("add") });
  const added = answer.construct?.select || null; stopPlacing();
  if (took(answer, added)) { ensureKindOption(answer.kind); sayBuild(added ? `Added ${added}${answer.construct.fastened ? ", fastened" : ", loose"}.` : ""); }
}
async function constructNow(construct, keep = null) {
  const answer = await api("/api/workshop/candidates", { ...candidateBody(), construct });
  if (took(answer, keep)) ensureKindOption(answer.kind);
  return answer;
}
function ensureKindOption(kind) {
  const picker = $("#ws-archetype"); if (!picker || !kind) return;
  if (![...picker.options].some((o) => o.value === kind)) { const option = make("option", { value:kind }, kind === "custom" ? "my build" : kind); option.title = "A design built part by part."; picker.append(option); }
  picker.value = kind; renderProductCatalog();
}
async function startNewBuild() {
  const request = partRequest();
  const answer = await api("/api/workshop/open", { kind:"custom", first_part:request });
  bench.openedLibraryItem = null; stopPlacing();
  const first = answer.candidates?.[0]?.parts?.[0]?.name || null;
  if (took(answer, first)) { ensureKindOption("custom"); sayBuild(`Started a new build from ${first}. Add the next part against it.`); }
}
async function pushOnIt() {
  if (!bench.selectedPart) throw new Error("Click the spot on the object to push first.");
  const part = selectedPart(), point = bench.forcePoint || part.center_m;
  const config = { component:bench.selectedPart, point_m:point, force_n:Number($("#ws-push-force").value),
    push:$("#ws-push-way").value, standing:$("#ws-push-standing").value };
  const revision = bench.revision;
  const answer = await api("/api/workshop/plan", { ...candidateBody(), bench_test:{ test:"force_probe", config } });
  if (revision !== bench.revision) return;
  const root = $("#ws-push-result"); root.replaceChildren();
  renderJointScreen(root, answer.bench?.joint_screen);
  showForceAt(point, config.force_n, config.push);
}
function renderBuild() {
  const root = $("#ws-build-joints"), candidate = chosen(); if (!root || !candidate) return;
  const c = candidate.construction || { joints:[], unfastened:[], touching_unfastened:[] };
  root.replaceChildren();
  const off = $("#ws-build-remove"); if (off) { off.disabled = !bench.selectedPart || candidate.parts.length < 2; off.textContent = bench.selectedPart ? `Take ${bench.selectedPart} off` : "Take the selected part off"; }
  if (!c.joints_authored) {
    root.append(make("p", { class:"ws-feedback-count" }, "This is still the template: its parts are joined where they touch. The joints become yours to change the moment you add, take off or fasten a part."));
    const adopt = make("button", { type:"button", class:"ws-action", id:"ws-build-adopt" }, "Show me its joints");
    adopt.onclick = () => guard(adopt, () => constructNow({ action:"adopt" }, bench.selectedPart)); root.append(adopt); return;
  }
  const shown = bench.selectedPart ? c.joints.filter((j) => j.a === bench.selectedPart || j.b === bench.selectedPart) : c.joints;
  root.append(make("p", { class:"ws-feedback-count" }, bench.selectedPart
    ? `${shown.length} of ${c.joints.length} joints hold ${bench.selectedPart}. Green fixes two parts together; blue lets one turn in the other.`
    : `${c.joints.length} joints. Click a part to see only its own.`));
  const list = make("ul", { class:"ws-joint-list" });
  for (const joint of shown) {
    const row = make("li", { class:"ws-joint-row" + (joint.open ? " open" : ""), "data-joint":joint.id });
    const how = joint.interface, size = joint.open ? "no longer touching"
      : how.form === "planar" ? `${(how.area_m2 * 1e4).toFixed(1)} cm²${how.mitred ? " raked" : ""}`
      : `${(how.diameter_m * 1000).toFixed(0)} mm shaft, ${(how.engaged_m * 1000).toFixed(0)} mm in`;
    row.append(make("span", { class:`ws-joint-kind ${joint.kind}` }, joint.kind === "bearing" ? "turns" : "fixed"),
      make("span", { class:"ws-joint-parts" }, `${joint.a} ↔ ${joint.b}`), make("small", {}, `${joint.method} · ${size}`));
    const undo = make("button", { type:"button", class:"ws-part-copy" }, "Unfasten");
    undo.onclick = () => guard(undo, () => constructNow({ action:"unfasten", a:joint.a, b:joint.b }, bench.selectedPart));
    row.append(undo); list.append(row);
  }
  root.append(list);
  const near = (c.touching_unfastened || []).filter((pair) => !bench.selectedPart || pair.includes(bench.selectedPart));
  for (const [a, b] of near.slice(0, 12)) {
    const row = make("div", { class:"ws-joint-row loose" });
    row.append(make("span", { class:"ws-joint-parts" }, `${a} and ${b} touch and are not fastened`));
    for (const [kind, label] of [["fixed", "Fix"], ["bearing", "Let it turn"]]) {
      const button = make("button", { type:"button", class:"ws-part-copy" }, label);
      button.onclick = () => guard(button, () => constructNow({ action:"fasten", a, b, kind }, bench.selectedPart)); row.append(button);
    }
    root.append(row);
  }
  if ((c.unfastened || []).length) root.append(make("p", { class:"ws-note warn" }, `Nothing holds ${c.unfastened.join(", ")}.`));
}
function installBuildPanel(editor) {
  const box = make("section", { id:"ws-build-box", class:"ws-build-box" });
  box.append(make("h3", {}, "Build part by part"),
    make("p", { class:"ws-feedback-count" }, "Choose a part, press Place, then click the face it goes against. It comes in square to that face; turn it or sink it in, then add it."));
  const what = make("select", { id:"ws-build-what", "aria-label":"Part to add" });
  const whatLabel = make("label", { class:"ws-field" }, "Add"); whatLabel.append(what); box.append(whatLabel);
  const material = make("select", { id:"ws-build-material" });
  const materialLabel = make("label", { class:"ws-field" }, "Made of"); materialLabel.append(material); box.append(materialLabel);
  box.append(make("div", { id:"ws-build-sizes" }));
  const by = make("select", { id:"ws-build-by" }); BUILD_FACES.forEach(([v, l]) => addOption(by, v, l));
  const byLabel = make("label", { class:"ws-field" }, "Attach it by"); byLabel.append(by); box.append(byLabel);
  const fasten = make("select", { id:"ws-build-fasten" });
  [["fixed", "Fixed: glued, welded or pressed in"], ["bearing", "Turning: free to spin in the other part"], ["none", "Loose: just set there"]].forEach(([v, l]) => addOption(fasten, v, l));
  const fastenLabel = make("label", { class:"ws-field" }, "Fasten"); fastenLabel.append(fasten); box.append(fastenLabel);
  const snapLabel = make("label", { class:"ws-field" }, "Settle on the middle or flush to an edge");
  const snap = make("input", { id:"ws-build-snap", type:"checkbox" }); snap.checked = true; snapLabel.append(snap); box.append(snapLabel);
  const row = make("div", { class:"ws-row" });
  row.append(make("button", { id:"ws-build-place", type:"button", class:"ws-action primary" }, "Place it: click where it goes"),
    make("button", { id:"ws-build-new", type:"button", class:"ws-action" }, "Start a new build from it"));
  box.append(row);
  const adjust = make("div", { id:"ws-build-adjust", class:"ws-build-adjust" }); adjust.hidden = true;
  const nudges = make("div", { class:"ws-edit-actions" });
  for (const [label, change] of [["Turn left", () => { build.twist -= 90; }], ["Turn right", () => { build.twist += 90; }],
    ["Sink in 5 mm", () => { build.depth += 0.005; }], ["Pull out 5 mm", () => { build.depth -= 0.005; }]]) {
    const button = make("button", { type:"button", class:"ws-action" }, label);
    button.onclick = () => { change(); previewPlacement(); }; nudges.append(button);
  }
  const confirm = make("div", { class:"ws-row" });
  confirm.append(make("button", { id:"ws-build-add", type:"button", class:"ws-action primary" }, "Add it"),
    make("button", { id:"ws-build-cancel", type:"button", class:"ws-action" }, "Cancel"));
  adjust.append(nudges, confirm); box.append(adjust);
  box.append(make("p", { id:"ws-build-status", class:"ws-note", role:"status", "aria-live":"polite" }));
  box.append(make("button", { id:"ws-build-remove", type:"button", class:"ws-action" }, "Take the selected part off"));
  box.append(make("h3", {}, "Joints"), make("div", { id:"ws-build-joints" }));
  const push = make("div", { id:"ws-push-box", class:"ws-push-box" });
  push.append(make("h3", {}, "Push on it"),
    make("p", { class:"ws-feedback-count" }, "Click the spot to push, then press Push. A quick calculation, not a simulation: it says how much of each joint's strength the push uses and which joint would go first."));
  const force = make("input", { id:"ws-push-force", type:"number", min:"1", max:"100000", step:"50", value:"1000" });
  const forceLabel = make("label", { class:"ws-field" }, "Force (N)"); forceLabel.append(force); push.append(forceLabel);
  const way = make("select", { id:"ws-push-way" });
  [["down","down"],["up","up"],["+x","along +x, to the right"],["-x","along -x, to the left"],["+z","along +z, towards the back"],["-z","along -z, towards the front"]].forEach(([v,l]) => addOption(way, v, l));
  const wayLabel = make("label", { class:"ws-field" }, "Pushing"); wayLabel.append(way); push.append(wayLabel);
  const standing = make("select", { id:"ws-push-standing" });
  [["resting","standing on the floor"],["free","struck in mid-air"]].forEach(([v,l]) => addOption(standing, v, l));
  const standingLabel = make("label", { class:"ws-field" }, "While it is"); standingLabel.append(standing); push.append(standingLabel);
  push.append(make("button", { id:"ws-push-go", type:"button", class:"ws-action primary" }, "Push"), make("div", { id:"ws-push-result" }));
  box.append(push);
  editor.prepend(box);
  $("#ws-push-go").onclick = (event) => guard(event.currentTarget, pushOnIt);
  for (const control of [force, way, standing]) control.addEventListener("change", () => { if (bench.jointVerdicts) guard(null, pushOnIt); });

  what.onchange = () => { renderBuildSizes(); if (build.placing) previewPlacement(); };
  for (const control of [material, by, fasten, snap]) control.addEventListener("change", () => { if (build.placing) previewPlacement(); });
  $("#ws-build-place").onclick = () => {
    if (build.placing) { stopPlacing("Placing cancelled."); return; }
    // A click has to land on a face, and only the solid view has faces: a wire
    // edge belongs to two of them.
    if (view !== "skin") { view = "skin"; pressView("skin"); show(false); }
    build.placing = true; stage.classList.add("ws-placing"); $("#ws-build-place").textContent = "Placing… click a face (press again to stop)";
    sayBuild("Click the face of the part it goes against.");
  };
  $("#ws-build-add").onclick = (event) => guard(event.currentTarget, addPlaced);
  $("#ws-build-cancel").onclick = () => stopPlacing("Placing cancelled.");
  $("#ws-build-new").onclick = (event) => guard(event.currentTarget, startNewBuild);
  $("#ws-build-remove").onclick = (event) => guard(event.currentTarget, async () => {
    if (!bench.selectedPart) throw new Error("Click the part to take off first.");
    const gone = bench.selectedPart; await constructNow({ action:"remove", part_name:gone }); sayBuild(`Took ${gone} off, with the joints that held it.`);
  });
}
function renderBuildChoices() {
  const what = $("#ws-build-what"), material = $("#ws-build-material"); if (!what) return;
  const before = what.value; what.replaceChildren();
  const families = make("optgroup", { label:"Component families" });
  for (const family of bench.families || []) families.append(make("option", { value:`family:${family.family}`, title:family.about }, family.family));
  what.append(families);
  const mine = (bench.personalLibrary || []).filter((item) => item.item_type === "component");
  if (mine.length) { const saved = make("optgroup", { label:"My library" }); for (const item of mine) saved.append(make("option", { value:`item:${item.item_id}` }, item.name)); what.append(saved); }
  if ([...what.options].some((o) => o.value === before)) what.value = before;
  const kept = material.value; material.replaceChildren();
  const names = (bench.pricebook?.materials || []).map((m) => m.material); if (!names.includes("oak")) names.push("oak");
  names.sort().forEach((name) => addOption(material, name, name)); material.value = names.includes(kept) ? kept : "oak";
  renderBuildSizes();
}

// ---------------------------------------------------------------------------
// Whole-design controls
// ---------------------------------------------------------------------------
function pressView(name) {
  document.querySelectorAll(".ws-viewbar button").forEach((item) => item.setAttribute("aria-pressed", String(item.dataset.view === name)));
}
document.querySelectorAll(".ws-viewbar button").forEach((button) => {
  button.onclick = () => guard(button, async () => {
    const requested = button.dataset.view;
    if (["matter", "collision", "relations"].includes(requested)) await loadMatter(false);
    if (requested === "physics" && !bench.playback) { say("Run a supported simulation first. This view shows its calculated result.", true); return; }
    view = requested; pressView(view); show(false);
  });
});
$("#ws-archetype").onchange = (event) => guard(null, async () => { bench.openedLibraryItem = null; took(await api("/api/workshop/candidates", { kind:event.target.value, generation:bench.generation + 1 })); });
$("#ws-materialize").onclick = (event) => guard(event.currentTarget, async () => {
  if (!await loadMatter(true)) return;
  view = "matter"; pressView(view); show(false);
  $("#ws-plan").hidden = false; $("#ws-plan").textContent = JSON.stringify({mechanical_model: chosen().mechanical_model, rigid:bench.rigid, matter: bench.matter, measured: currentMeasurements()}, null, 2);
});
$("#ws-save-design").onclick = (event) => guard(event.currentTarget, async () => {
  const candidate = chosen(), label = $("#ws-save-name").value.trim() || candidate.label || candidate.design_id;
  const answer = await api("/api/workshop/feedback", { ...candidateBody(), save_design:true, label, library_item_id:bench.openedLibraryItem || null,
    world_revision:bench.session && bench.session.world_revision !== "unopened-world" ? bench.session.world_revision : null });
  if (answer.personal_library) { bench.personalLibrary = answer.personal_library; renderUserLibrary(); }
  if (answer.saved_designs) savedDesigns(answer.saved_designs);
  if (answer.bench_presets) bench.benchPresets = answer.bench_presets; const saved = answer.library_item || answer.design;
  if (answer.library_item) bench.openedLibraryItem = answer.library_item.item_id; $("#ws-save-status").textContent = saved ? `Saved to Saved designs and My Library · v${saved.version || saved.revision}` : "Not saved";
});
$("#ws-save-feedback").onclick = (event) => guard(event.currentTarget, async () => {
  const answer = await api("/api/workshop/feedback", { ...candidateBody(), rating:$("#ws-rating").value || null, note:$("#ws-note").value.trim(), selected:true });
  $("#ws-note").value = ""; $("#ws-rating").value = ""; $("#ws-feedback-count").textContent = `${answer.kept} feedback records kept`;
});

function resize() {
  const rect = stage.getBoundingClientRect(); if (!rect.width || !rect.height) return;
  renderer.setSize(rect.width, rect.height, false); camera.aspect = rect.width / rect.height; camera.updateProjectionMatrix(); placeCamera();
}
new ResizeObserver(resize).observe(stage); addEventListener("resize", resize);
function frame(now) { advancePlayback(now); renderer.render(scene, camera); requestAnimationFrame(frame); }

async function start() {
  const params = new URLSearchParams(location.search), libraryItem = params.get("library"), saved = params.get("design");
  const answer = await api("/api/workshop/open", libraryItem ? { library_item_id:libraryItem } : saved ? { saved_design_id:saved } : { kind:"table" });
  if (answer.library_item) bench.openedLibraryItem = answer.library_item.item_id;
  const picker = $("#ws-archetype"); picker.replaceChildren();
  for (const made of answer.assemblies) { const option = make("option", { value:made.assembly }, made.assembly.replace("-", " ")); option.title = made.about; picker.append(option); }
  picker.value = answer.kind; renderProductCatalog();
  bench.families = answer.families || []; savedDesigns(answer.saved_designs || []); bench.personalLibrary = answer.personal_library || [];
  bench.pricebook = answer.pricebook || null; bench.benchTests = answer.bench_tests || []; bench.benchPresets = answer.bench_presets || []; renderUserLibrary(); renderBuildChoices(); took(answer);
  try {
    const remembered = await api("/api/workshop/remembered", {}); $("#ws-feedback-count").textContent = remembered.kept ? `${remembered.kept} feedback records kept` : "";
    bench.personalLibrary = remembered.personal_library || bench.personalLibrary; bench.pricebook = remembered.pricebook || bench.pricebook; bench.benchPresets = remembered.bench_presets || bench.benchPresets;
    // Loading optional history must not reset controls or invalidate a test
    // started while this request was in flight. The test catalog is already
    // authoritative from /open; only saved presets changed here.
    // History has no geometry changes. Redrawing the editor here would erase
    // unsubmitted curve/material inputs if it arrives while the user edits.
    renderUserLibrary(); renderBenchPresets();
  } catch { /* optional */ }
}

placeCamera(); resize(); requestAnimationFrame(frame); guard(null, start);
