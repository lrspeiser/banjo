// Workshop Mode: product design, physical matter, editable skins and isolated physics playback.
import * as THREE from "/vendor/three.module.js";
import { gameNavigation, refreshNavigation } from "/game_menu.js";

const $ = (q) => document.querySelector(q);
const worldId = new URLSearchParams(location.search).get("world");
const worldHeaders = worldId ? { "X-Banjo-World": worldId } : {};
const backToWorld = (scene) => worldId
  ? `/world?world=${worldId}&scene=new-game`
  : `/world?scene=${encodeURIComponent(scene)}&hold=1`;
const homeWorld = () => worldId ? backToWorld("new-game") : "/world";
let token = "";
let designAssistantConnected = false;
let playerReady = null;
async function ensurePlayer() {
  if (!worldId) return;
  if (!playerReady) playerReady = (async () => {
    const key = `banjo.player.${worldId}`;
    const response = await fetch("/api/world/player/join", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Banjo-Token": token, ...worldHeaders },
      body: JSON.stringify({ token: localStorage.getItem(key) || undefined,
                             name: localStorage.getItem("banjo.avatar-name") || undefined }),
    });
    const answer = await response.json();
    if (!response.ok) throw new Error(answer.error || "Could not join the world");
    localStorage.setItem(key, answer.token);
    worldHeaders["X-Banjo-Player"] = answer.token;
  })();
  return playerReady;
}
let candidateRequest = 0;
async function api(path, body, {preview = false} = {}) {
  const changesCandidate = !preview && ["/api/workshop/open", "/api/workshop/candidates", "/api/workshop/more"].includes(path);
  const requestId = changesCandidate ? ++candidateRequest : null;
  if (!token) {
    const status = await fetch("/api/status", { headers: worldHeaders }).then((r) => r.json());
    token = status.csrf_token || "";
    designAssistantConnected = Boolean(status.key_configured);
  }
  await ensurePlayer();
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Banjo-Token": token, ...worldHeaders },
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
balance.visible = false; support.visible = false;
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

let view = "skin";
// Workspace UI state is separate from the product and from completed test evidence.
const workspace = {mode:"build", setup:null, sequence:0, timer:null, running:false, inspecting:0};
let yaw = 0.72, pitch = 0.42, distance = 3;
let dragging = false, dragged = false, px = 0, py = 0, reach = 1.5;
const target = new THREE.Vector3(0, 0.42, 0);

const bench = {
  inventorySelection: null,
  kind: "table", generation: 0, candidates: [], selected: 0,
  session: null, savedDesigns: [], personalLibrary: [], pricebook: null, rack: null, spread: 0,
  libraryInspection: null, selectedPart: null, forcePoint: null, openedLibraryItem: null, expandedProduct: null, isolated: null,
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
  const yard = make("a", {href:backToWorld("yard")}, "Open the yard"); box.append(yard);
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
    // replace: making a design again puts the new one where the old one was,
    // instead of leaving you with two and no way to tell which is which.
    const answer=await api("/api/world/workshop/preview",{session:source.session,scene:source.scene,
      mode:"authoring",candidate,position_m:position,replace:true});
    if(sequence!==installation.sequence || revision!==bench.revision)return;
    installation.preview=answer;installation.request=crypto.randomUUID();
    const result=$("#ws-install-result");result.dataset.status="preview";
    result.textContent=`Ready: ${answer.design_id}, ${answer.mass_kg.toFixed(3)} kg, ${answer.mechanical_model === "precise-rigid-v1" ? `${answer.collision_boxes} precise collision boxes, zero lattice cells` : `${answer.cells} exact cells`}. Translation: ${answer.applied_translation_m.map(x=>x.toFixed(3)).join(", ")} m. Native geometry and existing state verified. No strength certification or resource charge. ${answer.limits}`;
    // Material leaves the rack at commit, so a short rack still previews: the
    // person sees exactly what it would take and what they are missing.
    if (answer.needs && !answer.needs.enough) {
      result.dataset.status="short";
      result.append(make("p",{class:"ws-short"}, answer.needs.says + " Nothing has been spent; make it when you have that."));
      confirm.disabled=true; confirm.title=answer.needs.says;
    } else {
      confirm.disabled=false; confirm.title="";
      if (answer.needs) result.append(make("p",{class:"ws-bom-total"}, answer.needs.says));
    }
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
      result.append(make("a",{href:backToWorld(answer.scene)},"Return to the world"));
      if (answer.materials_taken && answer.materials_taken.length) {
        result.append(make("p",{class:"ws-bom-total"}, "Taken from the rack: " + answer.materials_taken
          .map(r=>`${r.took_kg} kg of ${r.material}, ${r.left_kg} kg left`).join("; ")));
      }
      if (answer.rack) { bench.rack = answer.rack; renderRack(); }
      say("Made, installed, and the rack charged.");
      reprobe();
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
  distance = Math.max(0.025, reach * 1.18 / Math.sin(Math.min(up, across)));
  camera.near = Math.max(0.00001, distance / 1000);
  camera.far = Math.max(100, distance * 20); camera.updateProjectionMatrix();
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
  if (candidate === bench.libraryInspection?.component_preview || !bench.isolated || !ISOLATING_VIEWS.includes(view)) return candidate.parts;
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
    line.position.set(...laidOutCenter(candidate, part)); line.rotation.copy(spinFor(part.rotation_deg));
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
    mesh.position.set(...laidOutCenter(candidate, Object.assign({}, part, { center_m: descriptor?.center_m || part.center_m })));
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
    mesh.position.set(...laidOutCenter(candidate, part)); mesh.rotation.copy(spinFor(part.rotation_deg));
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
// An exact compound is its parts, each about the body's centre of mass and each
// turned by its own rotation. Drawn as one box the whole way round it, a chair
// is a crate and a mace is a crate: the shape IS the answer in a rigid test.
function playbackCompound(parts, fallbackMaterial) {
  const compound = new THREE.Group();
  for (const part of parts) {
    const d = part.dimensions_m || [0.01, 0.01, 0.01];
    const geometry = part.shape === "cylinder"
      ? new THREE.CylinderGeometry(d[0] / 2, d[0] / 2, d[1], 16)
      : new THREE.BoxGeometry(Math.max(1e-6, d[0]), Math.max(1e-6, d[1]), Math.max(1e-6, d[2]));
    const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
      color: materialColor(part.material || fallbackMaterial), roughness: 0.62 }));
    mesh.position.set(...(part.center_local_m || [0, 0, 0]));
    const q = part.rotation_wxyz || [1, 0, 0, 0]; mesh.quaternion.set(q[1], q[2], q[3], q[0]);
    compound.add(mesh);
  }
  return compound;
}
function disposeCompound(node) {
  node.traverse?.((child) => { if (child.isMesh) { child.geometry.dispose(); disposeMaterial(child.material); } });
}
let drawnRecording = null;
const playbackMeshes = new Map();
let physicsMeshBuilds = 0;
function drawPlayback() {
  balance.visible=false;support.visible=false;forceArrow.visible=false;
  const recording = bench.playback || workspace.setup, frame = recording?.frames?.[bench.playback ? bench.playbackIndex : 0];
  if (!frame) return;
  if (drawnRecording !== recording) { clearGroup(); drawnRecording = recording; physicsMeshBuilds = 0; }
  const present = new Set(), thermal = new Map((frame.thermo?.bodies || []).map(b => [b.name, b.temperature_k]));
  let proxies = 0;
  for (const body of frame.bodies || []) {
    present.add(body.name);
    const geometry = recording.geometry?.[`${body.name}#${Number(body.revision || 0)}`] || recording.geometry?.[body.name];
    const exact = geometry && Number(geometry.revision) === Number(body.revision || 0);
    const signature = JSON.stringify([body.revision || 0, exact, body.shape, body.dimensions_m, body.material]);
    let entry = playbackMeshes.get(body.name);
    if (!entry || entry.signature !== signature) {
      if (entry) { group.remove(entry.mesh); disposeCompound(entry.mesh); entry.mesh.geometry?.dispose(); disposeMaterial(entry.mesh.material); }
      const material = new THREE.MeshStandardMaterial({color:materialColor(body.material), roughness:0.62});
      let mesh;
      if (exact && geometry.parts) {
        mesh = playbackCompound(geometry.parts, body.material);
        disposeMaterial(material);
      } else if (exact) {
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
    group.remove(entry.mesh); disposeCompound(entry.mesh); entry.mesh.geometry?.dispose(); disposeMaterial(entry.mesh.material); playbackMeshes.delete(name);
  }
  if (followsMatter(recording)) followCentre = matterCentre(recording, frame) || followCentre;
  stage.dataset.physicsTime = String(frame.t_s);
  stage.dataset.physicsBodyCount = String(present.size);
  stage.dataset.physicsMeshBuilds = String(physicsMeshBuilds);
  stage.dataset.physicsPose = JSON.stringify(frame.bodies?.[0]?.position_m || []);
  const live = $("#ws-simulation-readout");
  if (recording.phase === "setup") {
    stage.dataset.phase = "setup";
    live.textContent = recording.summary;
    $("#ws-play-note").textContent = "Setup only. Physics has not advanced.";
    return;
  }
  stage.dataset.phase = bench.playbackPlaying ? "playing" : "result";
  if (recording.test === "kettle_heat") {
    live.textContent = `Water ${celsius(thermal.get("water charge"))} · heater ${celsius(thermal.get("heater plate"))}. Blue → red: measured 20–100 °C. Contained thermal model; no sloshing.`;
  } else if (recording.geometry_basis === "verified-precise-rigid-shapes") {
    const bodies = new Set((frame.bodies || []).map(part => part.object_id));
    live.textContent = `${present.size} collision shapes · ${bodies.size} rigid ${bodies.size === 1 ? "body" : "bodies"} · ${Number(frame.t_s).toFixed(2)} seconds. Actual native poses; no internal failure model.`;
  } else {
    const broken = (recording.fractures || []).some(f => f.outcome === "broke" && Number(f.at_s) <= Number(frame.t_s) + 1e-9);
    live.textContent = `${broken ? `In ${present.size} pieces` : `${present.size} simulated ${present.size === 1 ? "body" : "bodies"}`} · ${Number(frame.t_s).toFixed(2)} seconds. Positions are calculated by the physics engine.`;
  }
  $("#ws-play-note").textContent = recording.geometry_basis === "verified-precise-rigid-shapes"
    ? "Exact rigid collision shapes and actual native poses. No internal fracture, bending or attachment-failure calculation."
    : recording.geometry_basis === "recorded-native-shapes"
    ? "A little world with real ground under it. Every body as the engine's own shape: its cells where it is cells, its exact parts where it is exact, and every piece as the cells the engine left it. Showing the computed experiment, not a live connection to the outside world."
    : `${recording.geometry_basis === "verified-native-cells-and-native-pieces" ? "Exact Matter cells, and every piece as the cells the engine left it. " : recording.geometry ? "Exact Matter cells until topology changes. " : ""}${proxies ? `${proxies} bodies use simplified collision shapes. ` : ""}Showing the computed experiment, not a live connection to the outside world.`;
}
// A thing dropped from 4 m, or knocked across the floor in pieces, is a speck if
// the view holds its whole journey. These runs are framed on the thing as it
// starts and the view then goes with the matter: every body weighed by the
// cells it is drawn with, so it stays on the bulk of the wreck and lets a
// one-cell shard fly out of shot.
const followsMatter = recording => recording?.geometry_basis === "verified-native-cells-and-native-pieces"
  || recording?.geometry_basis === "recorded-native-shapes";
let followCentre = null, followClock = 0;
function matterCentre(recording, frame) {
  const sum = new THREE.Vector3(); let weight = 0;
  for (const body of frame?.bodies || []) {
    // The ground and anything driven into it are scenery: 16 m of ground at the
    // origin would drag the view off whatever is being watched.
    if (body.anchored) continue;
    const cells = recording.geometry?.[body.name]?.offsets_m?.length || 1;
    sum.x += cells*body.position_m[0]; sum.y += cells*body.position_m[1]; sum.z += cells*body.position_m[2]; weight += cells;
  }
  return weight ? sum.multiplyScalar(1/weight) : null;
}
function followMatter(now) {
  const dt = Math.min(.1, Math.max(0, (now - followClock)/1000)); followClock = now;
  if (view !== "physics" || !followCentre || !followsMatter(bench.playback)) return;
  // Scrubbing or paused: be there. Playing: close most of the gap in a fifth of a second.
  if (bench.playbackPlaying) target.lerp(followCentre, 1 - Math.pow(.02, dt/.2)); else target.copy(followCentre);
  placeCamera();
}
function frameSimulation(recording) {
  const bounds = new THREE.Box3();
  for (const frame of followsMatter(recording) ? recording.frames.slice(0,1) : recording.frames) for (const body of frame.bodies || []) {
    // 16 m of ground would make everything standing on it a speck.
    if (body.anchored) continue;
    const radius = .5*Math.hypot(...(body.dimensions_m || [.05,.05,.05]));
    const point = new THREE.Vector3(...body.position_m);
    bounds.expandByPoint(point.clone().addScalar(radius)); bounds.expandByPoint(point.clone().addScalar(-radius));
  }
  const floor = Number(recording.ground_m) || 0;
  if(recording.phase==="setup" && !bounds.isEmpty()) bounds.expandByPoint(new THREE.Vector3((bounds.min.x+bounds.max.x)/2,floor,(bounds.min.z+bounds.max.z)/2));
  if (!bounds.isEmpty()) { bounds.getCenter(target); reach = Math.max(.3,bounds.getSize(new THREE.Vector3()).length()/2); frameCandidate(); }
  followCentre = followsMatter(recording) ? matterCentre(recording, recording.frames[0]) : null;
  if (followCentre) { target.copy(followCentre); placeCamera(); }
  // The little world's ground stands at the depth of its soil, so the grid goes
  // where the ground actually is rather than through the middle of it.
  grid.position.y = floor;
}

function draw(candidate) {
  if (!bench.inventorySelection || !candidate) { clearGroup(); balance.visible = false; support.visible = false; stage.dataset.showing = "empty"; return; }
  if (bench.libraryInspection) {
    clearGroup(); renderer.clippingPlanes=[]; balance.visible=false; support.visible=false;
    const preview = bench.libraryInspection.component_preview;
    drawSkin(preview); frameRenderedGeometry();
    stage.dataset.showing = "saved-component"; stage.dataset.phase = "inspection";
    updateInspector(); return;
  }
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

  updateInspector();
  const m = currentMeasurements(candidate);
  const alone = ISOLATING_VIEWS.includes(view) ? isolatedPart() : null;
  if (alone) {
    // Balance and support are properties of the whole product, not of one piece.
    balance.visible = false; support.visible = false;
    frameRenderedGeometry(); stage.dataset.phase = "inspection";
    updateInspector(); return;
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
  if (view === "physics" || bench.libraryInspection) return;
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
  setWorkspaceMode("build");
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
  // Feeling a point is its own question and always was. It used to wait for
  // "force_probe" to be the SELECTED test, which the picker can never offer:
  // the catalogue keeps only tests tagged "simulation" and this one is tagged
  // "analysis". Every one of its five callers was dead. It needs a part picked
  // and a point on it, and takes the force from the push panel beside it.
  if (!bench.selectedPart || !bench.forcePoint || probing) return;
  probing = true;
  const config = { force_n: Number($("#ws-push-force")?.value) || 1000,
                   direction: $("#ws-push-way")?.value || "down",
                   at_m: bench.forcePoint ? [bench.forcePoint.x, bench.forcePoint.y, bench.forcePoint.z] : null };
  showForceAt(bench.forcePoint, config.force_n);
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
  event.preventDefault(); distance = Math.max(0.015, Math.min(100, distance * Math.exp(event.deltaY * 0.001))); placeCamera();
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

// Where a control lives when it is still wired but is not a thing a person
// should be looking at. Everything in here is driven by the page or by the
// chat; nothing in here is a panel.
function holder() {
  let box = document.querySelector("#ws-hidden-controls");
  if (!box) {
    box = make("div", { id:"ws-hidden-controls", hidden:true });
    document.querySelector("#design-workshop")?.append(box);
  }
  return box;
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
    make("p", {}, "Click a saved component to inspect it. Replacing a selected part is a separate, explicit action."),
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
  // The rack: what the workshop holds. Designing never touches it; making does.
  // Editable here because nothing in the world stocks it yet.
  bom.append(make("h3", {}, "The rack"),
    make("p", { class:"ws-note" }, "What the workshop holds, in kilograms. A design is drawn, measured and tested whatever is here; only making it draws on it."),
    make("div", { id:"ws-rack" }));
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
  const presets=make("details",{class:"ws-advanced"});presets.append(make("summary",{},"Saved setups"),testBox.querySelector("#ws-save-bench-preset"),presetLabel,make("div",{id:"ws-bench-presets"}));
  testBox.append(playback,presets,make("div",{id:"ws-bench-result"}));
  right.insertBefore(testBox, $("#ws-save-design").parentElement.previousElementSibling || $("#ws-save-design").parentElement);

  // Keep the real Run/replay controls next to the object, not below a long
  // scrolling parameter panel. Move existing nodes, never duplicate handlers.
  const dock = make("section", {id:"ws-simulation-dock",class:"ws-simulation-dock","aria-label":"Simulation controls"});
  dock.hidden = true;
  dock.append(make("strong", {id:"ws-active-situation"}), $("#ws-run-bench"),
    make("div", {id:"ws-simulation-feedback"}), playback);
  // Nor is the dock. "Run simulation" and "Reset to setup" belonged to a Test
  // tab that no longer exists, and the owner could not tell what either did.
  // Trying a thing is something you ask for; what it leaves behind -- the
  // playback and its timeline -- is drawn over the view when there is one.
  holder().append(dock);
  const watching = make("section", { id:"ws-watching", class:"ws-watching" });
  watching.hidden = true;
  // Ask the chat to drop something on it and you watch it here, over the
  // object, with one way back. The owner: "it will do that and show you and
  // then have a reset button to bring it back to full build."
  const backToBuild = make("button", { id:"ws-back-to-build", type:"button", class:"ws-action" },
                           "Back to the build");
  backToBuild.onclick = () => { clearPlayback(); showWholeProduct(); };
  watching.append(playback, backToBuild);
  $(".ws-viewport").append(watching);
  const context = make("section", {id:"ws-view-context", role:"status", "aria-live":"polite"});
  context.append(make("strong", {id:"ws-view-title"}, "Product"), make("p",{id:"ws-view-description"}),
    make("div", {id:"ws-inspector-actions",class:"ws-row"}));
  const fit = make("button", {id:"ws-fit-view",type:"button",class:"ws-action"}, "Fit view");
  fit.onclick=()=>{if(workspace.mode==="test" && (bench.playback || workspace.setup)) frameSimulation(bench.playback || workspace.setup); else {draw(chosen());frameCandidate();}};
  const back = make("button", {id:"ws-inspector-back",type:"button",class:"ws-action"}, "Back to product");
  back.onclick=showWholeProduct;
  const use = make("button", {id:"ws-inspector-use",type:"button",class:"ws-action"}, "Use on selected part");
  use.onclick=()=>guard(use,()=>reuseLibraryComponent(bench.libraryInspection.library_item.item_id));
  context.querySelector("#ws-inspector-actions").append(fit,back,use);
  for(const [name,y,p] of [["Perspective",.72,.42],["Side",0,.08],["Top",0,1.25]]) {
    const button=make("button",{type:"button",class:"ws-action"},name);
    button.onclick=()=>{yaw=y;pitch=p;placeCamera();};context.querySelector("#ws-inspector-actions").append(button);
  }
  // Not on the page. "hold objects on a stable work surface" told a person
  // looking at a table that it was a table, and the buttons beside it are on
  // the bar now. It stays in the holder because updateInspector writes to it.
  context.hidden = true;
  holder().append(context);
  const setup = make("button", {id:"ws-reset-setup",type:"button",class:"ws-action"}, "Reset to setup");
  setup.onclick=()=>{benchTestRequest++;$("#ws-bench-result").replaceChildren();clearPlayback();scheduleSetup(0);};
  dock.insertBefore(setup, $("#ws-simulation-feedback"));

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
  testPicker.onchange = () => { bench.selectedBenchTest = testPicker.value; renderBenchControls(); $("#ws-bench-result").replaceChildren(); clearPlayback(); scheduleSetup(0); };
  $("#ws-run-bench").onclick = (event) => guard(event.currentTarget, runBenchTest);
  $("#ws-save-bench-preset").onclick = (event) => guard(event.currentTarget, saveBenchPreset);
  $("#ws-play").onclick = togglePlayback;
  $("#ws-play-reset").onclick = resetPlayback;
  timeline.oninput = () => { bench.playbackPlaying=false; $("#ws-play").textContent="Play"; setPlaybackIndex(Number(timeline.value)); };
  installPlacementControls(right);
}
// ---------------------------------------------------------------------------
// One bench. The world is the other place; this is the only place a product is
// taken apart and changed. Everything here is the product in front of you: its
// parts on the left, what it is held to and the chat on the right, what the
// rack holds along the bottom. The older panels are still here, folded away,
// until each has a home in this frame.
// ---------------------------------------------------------------------------
//: Where you stand to look at it. These were called 3/4, X, Y and Z -- the
//: axis you are looking ALONG -- which is not something anybody reads off a
//: button. They are named for what you see.
const BENCH_VIEWS = [["3/4", 0.72, 0.42], ["Front", 0, 0.06], ["Side", Math.PI / 2, 0.06], ["Top", 0, 1.45]];

function centroidOf(candidate) {
  const parts = candidate?.parts || [];
  if (!parts.length) return [0, 0, 0];
  const sum = [0, 0, 0];
  for (const part of parts) for (let axis = 0; axis < 3; axis++) sum[axis] += part.center_m[axis];
  return sum.map((v) => v / parts.length);
}
// Where a part is drawn once the bench is laid out: straight out from the
// middle of the product, so nothing crosses anything else on the way.
function laidOutCenter(candidate, part) {
  const spread = bench.spread || 0;
  if (!spread) return part.center_m;
  const middle = centroidOf(candidate);
  return part.center_m.map((v, axis) => v + (v - middle[axis]) * spread * 1.8);
}

function setMakeStatus(message, bad) {
  const line = $("#ws-make-status");
  if (!line) return;
  line.textContent = message || "";
  line.dataset.bad = bad ? "yes" : "no";
}

// Make it: the one act that spends. Preview is free and runs whatever the rack
// holds, so a short rack is reported here rather than refused in the engine.
// Check Validity: does it hold together as a machine, and can the room carry it
// as drawn? It redraws whatever the cell grid cannot hold and says every change.
async function checkValidity(button) {
  button.disabled = true;
  try {
    setMakeStatus("Checking it over…", false);
    let worldCell = null;
    try { worldCell = (await api("/api/world/workshop/context", {})).cell_size_m; }
    catch (_) { /* A design can still be checked in the Workshop without a world. */ }
    const answer = await api("/api/workshop/library", Object.assign({ action:"check_validity",
      cell_size_m:worldCell || .04 }, candidateBody()));
    const said = answer.validity || {};
    if (!said.ok) { setMakeStatus(said.says || "It cannot be drawn to work.", true); return; }
    if (answer.candidate) {
      bench.candidates = [answer.candidate]; bench.selected = 0; bench.revision++;
      invalidateMatter(); invalidateInstallation(); show();
    }
    const ready = answer.recipe_readiness;
    const blocker = !ready?.workshop?.as_drawn ? ready?.workshop?.reason
      : worldCell && !ready?.world?.as_drawn ? ready?.world?.reason : null;
    setMakeStatus((said.says || "Checked.") + (blocker
      ? ` Still blocked: ${blocker}`
      : worldCell ? ` Both the Workshop and this world's ${Math.round(worldCell*1000)} mm grids accept it as drawn. Test the function and preview placement before making.`
      : " Checked on the Workshop grid; open a world before making."), Boolean(blocker));
  } catch (error) {
    setMakeStatus(String(error.message || error), true);
  } finally {
    button.disabled = false;
  }
}

// Where a made thing is set down. The room refuses ground another body already
// claims, so walk along the row until one is free rather than reporting a
// collision the person did not ask about.
const MAKE_SPOTS = [[3, 0], [3, 1.6], [3, -1.6], [4.6, 0], [4.6, 1.6], [4.6, -1.6], [1.4, 1.6], [1.4, -1.6]];

async function makeIt(button, {candidate: suppliedCandidate = null, status = setMakeStatus, replace = true} = {}) {
  button.disabled = true;
  try {
    status("Checking placement…", false);
    const source = await api("/api/world/workshop/context", {});
    const candidate = suppliedCandidate || candidateBody();
    let preview = null, refused = null;
    for (const position_m of MAKE_SPOTS) {
      try {
        preview = await api("/api/world/workshop/preview", {
          session: source.session, scene: source.scene, mode: "authoring", candidate, position_m,
          replace });
        break;
      } catch (error) {
        refused = error;
        // Ground that is taken is worth stepping over; anything else is the
        // real answer and must not be hidden behind seven more attempts.
        if (!/claim .* of the same cells|placement error|placement overlaps(?: or touches)?/i.test(String(error.message))) throw error;
      }
    }
    if (!preview) throw refused || new Error("There is nowhere clear to set it down.");
    if (preview.needs && !preview.needs.enough) {
      status(preview.needs.says + " Nothing has been spent.", true);
      return null;
    }
    status("Making…", false);
    const done = await api("/api/world/workshop/commit", {
      session: preview.session, scene: preview.scene,
      preview_id: preview.preview_id, request_id: crypto.randomUUID(),
    });
    if (done.rack) { bench.rack = done.rack; renderRack(); }
    const spent = (done.materials_taken || [])
      .map((row) => `${row.took_kg} kg of ${row.material} gone, ${row.left_kg} kg left`).join("; ");
    status(`Made. It is standing in ${done.scene}. ${spent}`, false);
    reprobe();
    return done;
  } catch (error) {
    status(String(error.message || error).split(String.fromCharCode(10))[0], true);
    return null;
  } finally {
    button.disabled = false;
  }
}

function renderHeldTo() {
  const root = $("#ws-held");
  if (!root) return;
  const candidate = chosen();
  root.replaceChildren();
  if (!candidate) return;
  const measured = candidate.measured || {};
  const rows = [
    ["parts", String((candidate.parts || []).length)],
    ["mass", measured.mass_kg == null ? "—" : `${measured.mass_kg} kg`],
    ["stands on", measured.support_footprint_m ? measured.support_footprint_m.map((v) => v.toFixed(2)).join(" × ") + " m" : "—"],
    ["tips at", measured.tip_angle_deg == null ? "—" : `${measured.tip_angle_deg.toFixed(1)}°`],
  ];
  for (const [name, value] of rows) {
    const row = make("div", { class:"ws-held-row" });
    row.append(make("span", {}, name), make("strong", {}, value));
    root.append(row);
  }
  for (const test of candidate.tests || []) {
    const row = make("div", { class:"ws-held-row ws-held-run" });
    const said = test.kind === "static_load" ? `hold ${test.load_kg} kg on its ${test.on}`
      : test.kind === "tip" ? `tip about ${test.direction}` : test.kind;
    // "run it" was a <strong>: it read like a button, and nothing happened.
    const go = make("button", { type:"button", class:"ws-run-declared" }, "run it");
    go.onclick = () => runDeclared(test, go);
    row.append(make("span", {}, said), go);
    root.append(row);
  }
}

// What a declared test means at the bench: put the thing in a little world and
// do to it what the design says it must take.
async function runDeclared(test, button) {
  const was = button.textContent;
  button.disabled = true; button.textContent = "running…";
  try {
    const answer = await api("/api/workshop/plan", {
      ...candidateBody(),
      try_in_a_room: { seconds: 6, load_kg: test.kind === "static_load" ? test.load_kg : 0,
                       on: test.on || "top", tip: test.kind === "tip" ? test.direction : null },
    });
    say(answer.room?.says || "It ran, and said nothing.");
  } catch (error) {
    say(`That test would not run: ${error.message || error}`, true);
  } finally {
    button.disabled = false; button.textContent = was;
  }
}

// One card per option of a native select, kept in step with it. The select
// stays the source of truth and is hidden, so anything that reads or sets its
// value goes on working.
function cardify(select, rootId, cardClass, onPick) {
  if (!select) return null;
  const root = make("div", { id: rootId, class: rootId });
  const render = () => {
    root.replaceChildren();
    for (const option of [...select.options]) {
      const card = make("button", { type:"button", class: cardClass });
      card.dataset.value = option.value;
      card.append(make("strong", {}, option.textContent || option.value));
      if (option.title) card.title = option.title;
      card.setAttribute("aria-current", option.value === select.value ? "true" : "false");
      card.onclick = () => {
        // Anything the pick has to settle first -- the workspace mode, say --
        // runs before the change, because the change acts on it.
        if (onPick) onPick(option.value);
        select.value = option.value;
        select.dispatchEvent(new Event("change", { bubbles:true }));
      };
      root.append(card);
    }
  };
  const mark = () => {
    for (const card of [...root.children]) {
      card.setAttribute("aria-current", card.dataset.value === select.value ? "true" : "false");
    }
  };
  render();
  select.addEventListener("change", mark);
  new MutationObserver(render).observe(select, { childList:true, subtree:true });
  select.closest("label")?.classList.add("ws-native-picker-hidden");
  (select.closest("label") || select).before(root);
  return root;
}

// Which step of the work is showing. The word is the same one the workspace
// has always been told -- the viewport and the test scheduler listen for it --
// and now it also decides which step of the right pane you can see.
function setWorkspaceMode(mode) {
  if (workspace.mode === mode) return;
  dispatchEvent(new CustomEvent("banjo-workshop-mode", { detail: mode }));
}

// A run of nodes under a heading becomes a drawer with that heading's name.
// The headings were already there; all this does is decide which of them a
// person has to open. Everything stays reachable and stays where it was.
function foldSections(root, keepOpen) {
  if (!root) return;
  const open = new Set(keepOpen.map((name) => name.toLowerCase()));
  const runs = [];
  for (const node of [...root.children]) {
    if (/^H[1-6]$/.test(node.tagName)) runs.push({ heading: node, under: [] });
    else if (runs.length) runs.at(-1).under.push(node);
  }
  for (const run of runs) {
    const said = (run.heading.textContent || "").trim();
    if (open.has(said.toLowerCase()) || !run.under.length) continue;
    const box = make("details", { class:"ws-group ws-drawer ws-fold" });
    box.append(make("summary", {}, said));
    run.heading.replaceWith(box);
    for (const node of run.under) box.append(node);
  }
}

// Show one step and no other. Called on every mode change, including the ones
// the page makes for you: picking a part takes you to Change, picking a test
// takes you to Try, so you are never left looking at the wrong pane.
function showStep(mode) {
  for (const pane of document.querySelectorAll(".ws-step-pane")) {
    pane.hidden = pane.dataset.mode !== mode;
  }
  for (const tab of document.querySelectorAll(".ws-step-tab")) {
    tab.setAttribute("aria-selected", String(tab.dataset.mode === mode));
  }
}

function installBench() {
  const root = $("#design-workshop");
  const top = $(".ws-top"), left = $(".ws-left"), right = $(".ws-right"), viewport = $(".ws-viewport");
  if (!root || !top || !left || !right || !viewport || root.classList.contains("ws-benched")) return;
  root.classList.add("ws-benched");

  // ONE bar, over the view, and no header above it.
  //
  // The owner: "The workshop options of each item should be switched into a
  // dropdown on the same line as the wire/skin line, and we can also put the
  // nav elements in that line too so that we don't need the full workshop line
  // above." There were three bars before -- a page header, a Wire/Skin bar and
  // a row of view buttons under the object -- for about ten controls between
  // them.
  //
  // Which product, how it is drawn, where you are looking from, and the two
  // acts that leave the bench. Everything else is the chat's.
  const picker = $("#ws-archetype");
  const keep = holder();
  const status = make("p", { id:"ws-make-status", role:"status", "aria-live":"polite" });
  const checkButton = make("button", { id:"ws-check", type:"button", class:"ws-action" }, "Check it");
  checkButton.onclick = () => checkValidity(checkButton);
  const madeButton = make("button", { id:"ws-make", type:"button", class:"ws-action primary" }, "Make it");
  madeButton.onclick = () => makeIt(madeButton);
  const notice = $("#ws-notice");
  top.replaceChildren(keep);
  top.hidden = true;
  // The product picker is the select itself, on the bar, rather than a row of
  // chips: seven products is a list, and a list is a dropdown.
  const products = make("div", { id:"ws-products", class:"ws-chips", role:"group", "aria-label":"Which product" });
  products.hidden = true;
  keep.append(products);
  if (picker) {
    picker.id = "ws-archetype";
    picker.classList.add("ws-bar-select");
    picker.setAttribute("aria-label", "Which product");
    // The chips stay in the hidden holder because the page and its tests open
    // a product by clicking one; they mirror the select either way.
    const chips = () => {
      products.replaceChildren();
      for (const option of [...picker.options]) {
        const chip = make("button", { type:"button", class:"ws-chip" }, option.textContent || option.value);
        chip.dataset.value = option.value;
        chip.setAttribute("aria-current", option.value === picker.value ? "true" : "false");
        chip.onclick = () => {
          setWorkspaceMode("build");
          picker.value = option.value;
          picker.dispatchEvent(new Event("change", { bubbles:true }));
        };
        products.append(chip);
      }
    };
    chips();
    picker.addEventListener("change", chips);
    new MutationObserver(chips).observe(picker, { childList:true, subtree:true });
  }

  // Left: the chat, and nothing else. It is the widest way into the bench --
  // anything the controls do it can do, and it is where a person starts -- so
  // it gets a side of its own instead of a box at the top of the other side.
  // The parts of the thing move across to sit with the controls that change
  // them. The chat's own log, status line and intro are put in beside the form
  // by the page's shell after this runs, so moving the form moves all of it.
  const parts = $("#ws-parts");
  const leftKeep = [...left.children];

  // Where you are looking from, beside how it is drawn, on the same bar. This
  // was a row of buttons under the object in a panel that also said "hold
  // objects on a stable work surface", which is not something anyone needed
  // telling while looking straight at the thing.
  const views = make("div", { id:"ws-points-of-view", class:"ws-chips", role:"group",
                              "aria-label":"Point of view" });
  for (const [name, y, p] of BENCH_VIEWS) {
    const button = make("button", { type:"button", class:"ws-chip" }, name);
    // Not data-view: that belongs to Wire/Skin/Matter, which now share this
    // bar, and a point of view is not a way of drawing the thing.
    button.dataset.pointOfView = name;
    button.onclick = () => {
      yaw = y; pitch = p; placeCamera();
      for (const other of [...views.children]) other.setAttribute("aria-current", other === button ? "true" : "false");
    };
    views.append(button);
  }
  views.firstChild?.setAttribute("aria-current", "true");
  const apart = make("input", { id:"ws-spread", type:"range", min:"0", max:"100", step:"1", value:"0",
                                "aria-label":"How far apart the parts lie" });
  apart.addEventListener("input", () => { bench.spread = apart.valueAsNumber / 100; draw(chosen()); });
  const apartLabel = make("label", { class:"ws-benchbar-field" }, "Apart");
  apartLabel.append(apart);
  keep.append(apartLabel);

  // Right: the chat, always, and under it one step of the work at a time.
  //
  // This pane has been wrong twice. It was one shut drawer called "Bench
  // extras" holding about fifty working controls, and nobody ever opened it.
  // Then it was six named sections, all open, and the owner said: "there are
  // so many buttons and fields I don't have a clue where to begin". Both are
  // the same fault. The controls were never the problem; there was no ORDER
  // OF WORK, so every one of them looked equally like the next thing to do.
  //
  // Four steps, and you see one: Ask what to make, Change it, Try it, Keep it.
  // Nothing is deleted and nothing is hidden behind an unnamed lid -- the step
  // you are not in is a click away and says what it holds. The chat sits above
  // them because it is another way of doing any of the four, not a fifth step.
  const chatForm = $("#ws-component-chat");
  const chatHome = make("section", { id:"ws-chat-home" });
  chatHome.append(make("h2", {}, "Chat"));
  const heldBox = make("section", { id:"ws-held-box" });
  heldBox.append(make("h2", {}, "Held to"), make("div", { id:"ws-held" }));

  // The step names are what a person is doing, not what the code calls it; the
  // mode keys underneath are the ones the workspace has always used, so the
  // viewport and the test scheduler go on hearing what they listened for.
  const STEPS = [
    { mode:"start", name:"Ask", about:"Which product to start from, your own parts, and anything you saved." },
    { mode:"build", name:"Change", about:"The part you picked, building part by part, and taking a change back." },
    { mode:"test", name:"Try", about:"Put it in a little world with ground and a sky, and do something to it." },
    { mode:"details", name:"Keep", about:"What it is made of, making it in the world, and saving it." },
  ];
  const strip = make("div", { class:"ws-steps", role:"tablist", "aria-label":"What you are doing" });
  const groups = {};
  for (const step of STEPS) {
    const tab = make("button", { type:"button", class:"ws-step-tab", role:"tab",
                                 "data-mode":step.mode, "aria-selected":String(step.mode === workspace.mode) }, step.name);
    tab.onclick = () => setWorkspaceMode(step.mode);
    strip.append(tab);
    const pane = make("section", { id:`ws-step-${step.mode}`, class:"ws-step-pane", role:"tabpanel",
                                   "data-mode":step.mode });
    pane.hidden = step.mode !== workspace.mode;
    pane.append(make("p", { class:"ws-step-about" }, step.about));
    groups[step.mode] = pane;
  }
  // Two drawers under the steps, shut, because they describe the bench rather
  // than being a step of the work.
  const drawer = (id, title) => {
    const box = make("details", { id, class:"ws-group ws-drawer" });
    box.append(make("summary", {}, title));
    return box;
  };
  groups.measure = drawer("ws-group-measure", "How it measures up");
  groups.plumbing = drawer("ws-group-plumbing", "How the bench works");

  // Undo, and a list of what you did to get here. Every edit went through
  // took() and nothing kept the state before it, so a wrong material on all
  // eight parts was a wrong material on all eight parts for good.
  const back = make("button", { id:"ws-undo", type:"button", class:"ws-action" }, "Undo");
  const forward = make("button", { id:"ws-redo", type:"button", class:"ws-action" }, "Redo");
  back.onclick = () => stepHistory(-1);
  forward.onclick = () => stepHistory(1);
  const historyRow = make("div", { class:"ws-row" });
  historyRow.append(back, forward);
  const historyBox = make("section", { id:"ws-group-history", class:"ws-group" });
  historyBox.append(make("h2", {}, "What you changed"), historyRow, make("div", { id:"ws-history" }));

  // Where each thing goes. Some of what was swept in is anonymous -- a heading,
  // then the fields under it -- so an unnamed node joins whatever the last
  // heading joined.
  const BY_ID = {
    "ws-component-editor":"build", "ws-test-bench":"test",
    "ws-bom-box":"details", "ws-install-box":"details",
    "ws-product-library-box":"start", "ws-personal-library-box":"start", "ws-saved-designs":"start",
    "ws-name":"measure", "ws-purpose":"measure", "ws-checks":"measure",
    "ws-buildability":"measure", "ws-measurement-basis":"measure",
    "ws-materialize":"plumbing", "ws-plan":"plumbing",
  };
  const BY_HEADING = {
    // "Save design" and its name field sat under the test bench, because the
    // heading before them was the test bench's and an unnamed node follows the
    // last heading. Saving is Keep.
    "save design":"details", "saved designs":"start", "my library":"start", "product library":"start",
    "cheap checks":"measure", "feedback":"plumbing", "materialization":"plumbing",
    "how it compiles":"plumbing", "test bench":"test", "materials":"details",
  };
  let following = "plumbing";
  const placeIn = (node) => {
    const id = node.id || "";
    if (BY_ID[id]) return (following = BY_ID[id]);
    if (node.classList && node.classList.contains("ws-metrics")) return (following = "measure");
    if (node.classList && node.classList.contains("ws-viewbar-extra")) return "plumbing";
    if (/^H[1-6]$/.test(node.tagName)) {
      const said = (node.textContent || "").trim().toLowerCase();
      // "Components" was the heading over the parts list, which now lives in
      // the left pane on its own; the heading was left behind.
      if (said === "components") return null;
      if (BY_HEADING[said]) return (following = BY_HEADING[said]);
    }
    return following;
  };
  const partsBox = make("section", { id:"ws-parts-box" });
  partsBox.append(make("h2", {}, "Parts"));
  if (parts) partsBox.append(parts);
  const rightKeep = [...right.children];
  const railHeader = make("header", {class:"game-rail-header"});
  railHeader.append(make("h1", {}, "Banjo"),
    make("button", {type:"button", "data-game-menu":"", "aria-label":"Game menu"}, "Menu"),
    make("span", {id:"ws-screen-status"}, "Inventory"));
  left.classList.add("game-rail");
  left.replaceChildren(railHeader, chatHome);
  // The old control panel remains hidden machinery for chat and tests.
  //
  // The owner, twice: "there are so many buttons and fields I don't have a
  // clue where to begin on it", and then, of the four steps that replaced
  // them, "I don't really understand how to use the try or change or keep
  // functions, it makes no sense. Since we can't make this work we should just
  // leave it all up to the chat."
  //
  // So the bench is the chat, the object, and one bar. The panels are still
  // built and still wired -- the chat drives several of them, the page reads
  // values out of them, and they are what the browser tests hold the bench to
  // -- but they are not a wall of controls in front of a person any more. What
  // a person cannot yet ask the chat for is written down in
  // docs/workshop-deep-dive.md rather than left on the screen as a puzzle.
  right.replaceChildren(partsBox, heldBox, strip, groups.start, groups.build, groups.test,
                        groups.details, groups.measure, groups.plumbing);
  right.hidden = true;
  for (const node of [...rightKeep, ...leftKeep.filter((n) => n !== parts)]) {
    const where = placeIn(node);
    if (where) groups[where].append(node); else node.remove();
  }
  groups.build.append(historyBox);
  // Change was still 47 controls, which is most of the fault all over again in
  // one step. Inside it, the two things a person reaches for -- the part they
  // picked and adding a part -- stay out, and the other six become drawers
  // with the names they already had. Nothing moves and nothing is lost; a
  // drawer says what is in it, which "Bench extras" never did.
  foldSections($("#ws-component-editor"), ["selected component", "build part by part"]);
  foldSections($("#ws-build-box"), ["build part by part"]);
  foldSections($("#ws-push-box"), []);
  showStep(workspace.mode);
  // Saving is Keep, and it did not land there on its own: the name field and
  // the Save button are unnamed nodes, and an unnamed node follows the last
  // heading it saw, which in the pane they came from was the test bench's.
  for (const control of ["#ws-save-name", "#ws-save-design"]) {
    const node = $(control)?.closest("label, .ws-row");
    if (node) groups.details.append(node);
  }
  if (chatForm) chatHome.append(chatForm);

  // The bench tests stay cards rather than a dropdown: what each one does to
  // the thing is worth reading before you pick it. This used to live in the
  // page's inline shell, which the one-screen bench replaced.
  // Picking a situation to try is what "going to the test tab" was: the
  // workspace has to be in test mode or scheduleSetup does nothing at all, and
  // the three tabs that used to say so are gone.
  const testPicker = $("#ws-bench-test");
  cardify(testPicker, "ws-test-catalog", "ws-test-card", () => setWorkspaceMode("test"));
  // Whichever way a situation is chosen -- a card, or the select underneath --
  // the workspace has to be in test mode BEFORE the handler that sets it up
  // runs, and that handler was assigned before this one could listen.
  if (testPicker) {
    const chose = testPicker.onchange;
    testPicker.onchange = (event) => { setWorkspaceMode("test"); if (chose) chose.call(testPicker, event); };
  }
  // The old shell revealed the run dock only on the Test tab. There are no
  // tabs now, so it is simply there.
  const dock = $("#ws-simulation-dock");
  if (dock) dock.hidden = false;

  // Wire and Skin are the product. Matter, physics, collision and relations
  // describe how it is compiled, which is bench plumbing, not editing a thing.
  const viewbar = $(".ws-viewbar");
  if (viewbar) {
    const plumbing = make("div", { class:"ws-viewbar ws-viewbar-extra", role:"group", "aria-label":"How it compiles" });
    for (const button of [...viewbar.children]) {
      if (!["wire", "skin"].includes(button.dataset.view)) plumbing.append(button);
    }
    if (plumbing.children.length) groups.plumbing.append(make("h3", {}, "How it compiles"), plumbing);
    // Everything that was three bars, on one: which product, how it is drawn,
    // where from, and the two acts that leave the bench.
    // The owner: "we don't need Wire, Skin, 3/4, Front, Side, Top or the
    // dropdown of the items." The picker and the points of view stay in the
    // holder, because the page and its tests set them; the bar shows only the
    // two acts that leave the bench.
    if (picker) keep.append(picker);
    keep.append(views);
    for (const button of [...viewbar.children]) if (button.dataset.view) button.hidden = true;
    viewbar.append(make("span", { class:"ws-spacer" }), status,
                   checkButton, madeButton, make("a", { class:"ws-bar-link", href:homeWorld() }, "The world"));
    if (notice) viewport.insertBefore(notice, viewbar.nextSibling);
  }

  // The rack sits at the foot of the right side with the rest of the controls,
  // rather than across the whole bottom of the page. It is one of the things
  // you look at while you work, not a status bar under everything.
  const rackBox = $("#ws-rack")?.closest("section") || null;
  const foot = make("footer", { id:"ws-rack-foot" });
  foot.append(make("h2", {}, "The rack"), make("div", { id:"ws-rack-strip" }));
  right.append(foot);
  if (rackBox) rackBox.hidden = false;
  renderRackStrip();

  // The tabs over the object: Lab is the object with its bar; Inventory,
  // Skills and Recipes are read when opened (workshop_tabs). Chat and shared
  // navigation stay in the right rail; ws-left is its legacy DOM class.
  const centre = make("div", { id:"ws-centre" });
  viewport.parentElement.insertBefore(centre, viewport);
  const tabs = gameNavigation(WORKSHOP_OPENS_ON, showTab);
  // Inventory first, and open: the owner asked for it to be "the default
  // screen you go into when you switch out of the world". Coming out of the
  // room, what you have is the question; the Lab is where you go next.
  railHeader.after(tabs);
  // The takes: little pictures of the thing. The first is the clean one --
  // the design as it is, untouched by any run -- and every run adds one
  // beside it, so a test never replaces the thing and the runs stay to be
  // looked at again. Under the object, the machine's own controls, the
  // ones its panel has in the world.
  const takes = make("div", { id:"ws-takes", role:"tablist", "aria-label":"The thing, and every run of it" });
  const machineBench = make("section", { id:"ws-machine-bench", "aria-label":"Work it as in the world" });
  machineBench.hidden = true;
  centre.append(takes, viewport, machineBench);
  const empty = make("section", {id:"ws-empty", "aria-label":"Empty lab"});
  empty.append(make("h2", {}, "Your lab is empty"),
    make("p", {}, "Select a carried item or saved design from Inventory to examine it here."));
  const pick = make("button", {type:"button", class:"ws-action"}, "Choose from Inventory");
  pick.onclick = () => showTab("inventory"); empty.append(pick); viewport.append(empty);
  const clear = make("button", {id:"ws-clear-lab", type:"button", class:"ws-action"}, "Clear Lab");
  clear.onclick = () => { clearLab(); showTab("lab"); }; $(".ws-viewbar").append(clear);
  chatForm?.addEventListener("submit", (event) => {
    if (bench.inventorySelection) return;
    event.preventDefault(); event.stopImmediatePropagation();
    say("Select an item from Inventory before asking about it.", true);
  }, true);
  new MutationObserver(updateLabSelection).observe(chatHome, {childList:true, subtree:true});
  for (const name of ["inventory", "skills", "recipes", "market", "goals"]) { const pane = $(`#ws-pane-${name}`); if (pane) centre.append(pane); }
  installInventory();
  installRecipes();
  renderTakes();
}

// ---------------------------------------------------------------------------
// Takes: the clean thing, and every run of it, as little pictures
// ---------------------------------------------------------------------------
function snapshot() {
  // The buffer is not kept between frames, so draw and read in one go.
  renderer.render(scene, camera);
  return stage.toDataURL("image/jpeg", 0.7);
}
// A picture of what is on the canvas, once there is something on it: the
// first frames after a thing is opened can be empty while its meshes are
// built, and an empty picture is worse than a late one.
function thumbLater(assign, when = () => true, tries = 8) {
  const retry = () => { if (tries > 0) setTimeout(() => thumbLater(assign, when, tries - 1), 400); };
  setTimeout(() => {
    if (!when()) { retry(); return; }
    let url = "";
    try { url = snapshot(); } catch (error) { console.warn("banjo: no picture of the take", error); }
    if (!url) { retry(); return; }
    const img = new Image();
    img.onload = () => {
      const probe = document.createElement("canvas"); probe.width = 32; probe.height = 24;
      const g = probe.getContext("2d"); g.drawImage(img, 0, 0, 32, 24);
      const d = g.getImageData(0, 0, 32, 24).data; let sum = 0;
      for (let i = 0; i < d.length; i += 4) sum += d[i] + d[i + 1] + d[i + 2];
      if (sum / (d.length / 4 * 3) > 6) { assign(url); renderTakes(); } else retry();
    };
    img.onerror = retry;
    img.src = url;
  }, 250);
}
function scheduleCleanThumb() {
  if (bench.cleanThumbRevision === bench.revision && bench.cleanThumb) return;
  const revision = bench.revision;
  bench.cleanThumbRevision = revision; bench.cleanThumb = bench.cleanThumb || "";
  thumbLater((url) => { if (revision === bench.revision) bench.cleanThumb = url; },
             () => revision === bench.revision && !bench.playback && !bench.isolated && !bench.libraryInspection);
}
function takeLabel(recording) {
  const result = bench.lastResult && bench.lastResult.playback === recording ? bench.lastResult : null;
  const test = recording.test === "try_in_a_room" ? "Little world" : recording.test === "drive" ? "Driven" : (benchDefinition(recording.test)?.name || recording.test || "Run");
  const said = result?.says || result?.measured?.outcome || "";
  return { title: test, said: String(said).slice(0, 90) };
}
function noteTake(recording) {
  bench.takes = bench.takes || [];
  if (bench.takes.some((t) => t.recording === recording)) return;
  const label = takeLabel(recording);
  const take = { id: `take-${Date.now()}-${bench.takes.length}`, recording, thumb: "", when: new Date(), ...label };
  bench.takes.push(take);
  bench.shownTake = take.id;
  renderTakes();
  thumbLater((url) => { take.thumb = url; }, () => bench.playback === recording);
}
function showTake(id) {
  bench.shownTake = id;
  if (id === "clean") { clearPlayback(); setWorkspaceMode("build"); show(); }
  else {
    const take = (bench.takes || []).find((t) => t.id === id);
    if (take) { setWorkspaceMode("test"); setPlayback(take.recording); }
  }
  renderTakes();
}
function renderTakes() {
  const root = $("#ws-takes"); if (!root) return;
  root.replaceChildren();
  if (!bench.inventorySelection) return;
  const shown = bench.playback ? (bench.shownTake || "") : "clean";
  const card = (id, title, said, thumb) => {
    const button = make("button", { type:"button", class:"ws-take", role:"tab", "data-take":id, "aria-selected":String(id === shown) });
    const picture = make("div", { class:"ws-take-picture" });
    if (thumb) { const img = make("img", { alt:"" }); img.src = thumb; picture.append(img); }
    button.append(picture, make("strong", {}, title));
    if (said) button.append(make("small", {}, said));
    button.onclick = () => showTake(id);
    return button;
  };
  root.append(card("clean", "Clean", "the design, untouched", bench.cleanThumb || ""));
  for (const take of bench.takes || []) root.append(card(take.id, take.title, take.said, take.thumb));
}

// ---------------------------------------------------------------------------
// The machine bench: the controls its panel has in the world, here
// ---------------------------------------------------------------------------
function machinesOf(candidate) {
  const record = candidate?.component_overrides?.["@machines"];
  return record && typeof record === "object" ? record : null;
}
// Drive it: you become the thing. Take the keys, and W A S D (or the arrows)
// go, back, turn left and turn right in a little world kept open on the
// server, drawn here as it happens; let go, and the drive is a take.
const DRIVE_KEYS = { w: "forward", arrowup: "forward", s: "back", arrowdown: "back",
                     a: "left", arrowleft: "left", d: "right", arrowright: "right" };
// Up is Space and down is Shift+Space, the same as walking the world
// (interaction.js BINDINGS). Only a machine that flies is asked for those.
function driveKeyOf(event) {
  if (event.key === " " || event.code === "Space") return event.shiftKey ? "down" : "up";
  return DRIVE_KEYS[event.key.toLowerCase()] || null;
}
function renderMachineBench(candidate) {
  const root = $("#ws-machine-bench"); if (!root) return;
  const record = machinesOf(candidate);
  const drivable = (record?.programs || []).length || (record?.controls || []).length >= 2;
  if (!drivable) { if (bench.drive) letGo(); root.hidden = true; root.replaceChildren(); return; }
  root.hidden = false;
  if (root.dataset.forRevision === String(bench.revision) && root.children.length) return;
  if (bench.drive) letGo();
  root.dataset.forRevision = String(bench.revision);
  root.replaceChildren();
  const take = make("button", { id:"ws-drive-take", type:"button", class:"ws-action primary" }, "Take the keys");
  const stop = make("button", { id:"ws-drive-stop", type:"button", class:"ws-action" }, "Let go");
  stop.hidden = true;
  const status = make("p", { id:"ws-drive-status", class:"ws-note" },
    "Take the keys and you are the thing: W or \u2191 goes, S or \u2193 backs, A or \u2190 turns left, D or \u2192 turns right, and a machine that flies rises on Space and comes down on Shift+Space, in a little world with ground and a sky. Let go, and the drive is a take.");
  take.onclick = () => guard(take, takeTheKeys);
  stop.onclick = () => guard(stop, letGo);
  const row = make("div", { class:"ws-mb-run" }); row.append(take, stop);
  const energy = make("p", { id:"ws-drive-energy", class:"ws-feedback-count" });
  const store = (record?.stores || [])[0];
  if (store) energy.textContent = `${store.name || "its battery"}: ${joulesSaid(store.charge_j)} of ${joulesSaid(store.capacity_j)}. Drive it and this says what it is spending.`;
  root.append(make("h3", {}, "Drive it"), status, energy, row);
}

// What it holds and what it is spending, the same words the world's panel
// uses: a thing that stops, or lands, stops spending, and you can see it.
const joulesSaid = (j) => (j >= 1e6 ? `${(j / 1e6).toFixed(2)} MJ` : j >= 1e3 ? `${(j / 1e3).toFixed(1)} kJ` : `${Math.round(j)} J`);
const wattsSaid = (w) => (w >= 1000 ? `${(w / 1000).toFixed(2)} kW` : w >= 10 ? `${Math.round(w)} W` : `${w.toFixed(1)} W`);
const forHowLong = (s) => (s >= 3600 ? `${(s / 3600).toFixed(1)} hours` : s >= 60 ? `${Math.round(s / 60)} min` : `${Math.round(s)} s`);
function showEnergy(e) {
  const line = $("#ws-drive-energy");
  if (!line || !e) return;
  line.textContent = `${e.name || "its battery"}: ${joulesSaid(e.charge_j)} of ${joulesSaid(e.capacity_j)}`
    + ` · ${e.using_w > 0.05 ? `using ${wattsSaid(e.using_w)}` : "using nothing"}`
    + (e.taking_w > 0.05 ? `, taking in ${wattsSaid(e.taking_w)}` : "")
    + (e.left_s ? `, ${forHowLong(e.left_s)} left at that` : "");
}

async function takeTheKeys() {
  if (bench.drive) return;
  const answer = await api("/api/workshop/drive", { action:"start", candidate:candidateBody() });
  const recording = answer.recording;
  if (!recording?.frames?.length) throw new Error("The little world gave no first frame.");
  bench.drive = { keys: { forward:false, back:false, left:false, right:false, up:false, down:false },
                  recording, inflight:false, timer:null, answer };
  clearPlayback();
  setWorkspaceMode("test");
  bench.playback = recording; bench.playbackIndex = recording.frames.length - 1; bench.playbackPlaying = false;
  view = "physics"; pressView("physics"); show(false); frameSimulation(recording); drawPlayback();
  $("#ws-drive-take").hidden = true; $("#ws-drive-stop").hidden = false;
  showEnergy(answer.energy);
  driveStatus(`Driving${answer.program ? ` its ${answer.kind} program` : answer.wheels.length ? ` its ${answer.wheels.join(" and ")}` : ""}: W A S D or the arrows${answer.flies ? ", Space up, Shift+Space down" : ""}. Esc lets go.`);
  stage.dataset.driving = "true";
  stage.focus?.();
  bench.drive.timer = setInterval(driveStep, 125);
}
function driveStatus(text) { const line = $("#ws-drive-status"); if (line) line.textContent = text; }
async function driveStep() {
  const drive = bench.drive;
  if (!drive || drive.inflight) return;
  drive.inflight = true;
  try {
    const said = await api("/api/workshop/drive", { action:"step", keys:drive.keys, dt_s:0.125 });
    if (!bench.drive) return;
    for (const frame of said.frames || []) drive.recording.frames.push(frame);
    drive.recording.duration_s = Number(said.t_s) || drive.recording.duration_s;
    bench.playback = drive.recording; bench.playbackIndex = drive.recording.frames.length - 1;
    if (view !== "physics") { view = "physics"; pressView("physics"); }
    drawPlayback();
    showEnergy(said.energy);
    const held = Object.entries(drive.keys).filter(([, v]) => v).map(([k]) => k).join("+") || "no keys";
    driveStatus(`${(said.doing || said.asked || "").replace(/^\w/, (c) => c.toUpperCase())}${said.why ? `: ${said.why}` : ""} \u00b7 ${held} \u00b7 ${Number(said.t_s).toFixed(1)} s`
      + (said.speed_m_s != null ? ` \u00b7 ${Number(said.speed_m_s).toFixed(2)} m/s` : "")
      + (said.fell_over ? " \u00b7 it fell over" : "") + ((said.broke || []).length ? ` \u00b7 ${said.broke.length} broke` : ""));
  } catch (error) {
    driveStatus(`The little world stopped answering: ${error.message}`);
    await letGo(true);
  } finally { if (bench.drive) bench.drive.inflight = false; }
}
async function letGo(quiet = false) {
  const drive = bench.drive; if (!drive) return;
  clearInterval(drive.timer); bench.drive = null;
  delete stage.dataset.driving;
  $("#ws-drive-take") && ($("#ws-drive-take").hidden = false); $("#ws-drive-stop") && ($("#ws-drive-stop").hidden = true);
  let answer = null;
  try { answer = await api("/api/workshop/drive", { action:"stop" }); } catch (error) { if (!quiet) throw error; }
  const recording = answer?.recording || drive.recording;
  if (recording?.frames?.length > 1) {
    bench.lastResult = { test:"drive", says: answer?.says || "driven", playback: recording };
    renderBenchResult({ test:"drive", says: answer?.says || "driven", playback: recording, measured:{} });
    if (!bench.playback || bench.playback === drive.recording) setPlayback(recording);
  }
  driveStatus(answer?.says ? `Let go: ${answer.says}. The drive is a take.` : "Let go.");
}
addEventListener("keydown", (event) => {
  if (!bench.drive) return;
  const target = event.target;
  if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
  if (event.key === "Escape") { event.preventDefault(); guard(null, letGo); return; }
  const key = driveKeyOf(event);
  if (!key) return;
  event.preventDefault();
  // Shift is let go before Space as often as after it, so pressing one of
  // them clears the other: a machine cannot rise and descend at once.
  if (key === "up") bench.drive.keys.down = false;
  if (key === "down") bench.drive.keys.up = false;
  bench.drive.keys[key] = true;
});
addEventListener("keyup", (event) => {
  if (!bench.drive) return;
  if (event.key === " " || event.code === "Space") {
    event.preventDefault(); bench.drive.keys.up = false; bench.drive.keys.down = false; return;
  }
  const key = DRIVE_KEYS[event.key.toLowerCase()];
  if (key) { event.preventDefault(); bench.drive.keys[key] = false; }
});

// ---------------------------------------------------------------------------
// Inventory, Skills, Recipes (workshop_tabs). Each is read when it is opened
// and spends nothing.
// ---------------------------------------------------------------------------
function tag(text, cls = "") { return make("span", { class: `ws-tag ${cls}`.trim() }, text); }
function item(title, sub, cls = "") { const li = make("li", cls ? { class: cls } : {}); li.append(make("strong", {}, title)); if (sub) li.append(make("small", {}, sub)); return li; }
function fill(id, rows, empty) { const root = $(id); if (!root) return; root.replaceChildren(); if (!rows.length) root.append(item(empty)); for (const row of rows) root.append(row); }

// A small picture of a thing, drawn from what the room says it is: its shape
// and its own colour. Not a render of the real body -- the bench's 3D view is
// for the design being worked on -- but enough to tell a rubber ball from an
// iron sword at a glance, which a column of names never did.
function thumbnail(thing) {
  const size = 48;
  const canvas = make("canvas", { width: String(size), height: String(size),
                                  role: "img", "aria-label": `${thing.name}, ${thing.material}` });
  const pen = canvas.getContext("2d");
  if (!pen) return canvas;
  const hex = /^[0-9a-f]{6,8}$/i.test(thing.color_rgba || "") ? thing.color_rgba.slice(0, 6) : "9aa7b4";
  const face = `#${hex}`;
  const dark = (amount) => {
    const n = parseInt(hex, 16);
    const mix = (c) => Math.max(0, Math.min(255, Math.round(c * amount)));
    return `rgb(${mix((n >> 16) & 255)}, ${mix((n >> 8) & 255)}, ${mix(n & 255)})`;
  };
  const m = 8, w = size - m * 2;
  pen.clearRect(0, 0, size, size);
  if (thing.shape === "sphere" || thing.shape === "capsule") {
    const light = pen.createRadialGradient(size * 0.38, size * 0.36, 2, size / 2, size / 2, w / 2);
    light.addColorStop(0, face);
    light.addColorStop(1, dark(0.45));
    pen.fillStyle = light;
    pen.beginPath(); pen.arc(size / 2, size / 2, w / 2, 0, Math.PI * 2); pen.fill();
  } else if (thing.shape === "cylinder") {
    pen.fillStyle = dark(0.7);
    pen.fillRect(m, m + 5, w, w - 10);
    pen.fillStyle = face;
    pen.beginPath(); pen.ellipse(size / 2, m + 5, w / 2, 5, 0, 0, Math.PI * 2); pen.fill();
    pen.fillStyle = dark(0.5);
    pen.beginPath(); pen.ellipse(size / 2, size - m - 5, w / 2, 5, 0, 0, Math.PI * 2); pen.fill();
  } else {
    // A box, drawn with its top and one side, so it reads as a solid.
    const d = 7;
    pen.fillStyle = face;
    pen.fillRect(m, m + d, w - d, w - d);
    pen.fillStyle = dark(1.25);
    pen.beginPath(); pen.moveTo(m, m + d); pen.lineTo(m + d, m);
    pen.lineTo(size - m, m); pen.lineTo(size - m - d, m + d); pen.closePath(); pen.fill();
    pen.fillStyle = dark(0.6);
    pen.beginPath(); pen.moveTo(size - m - d, m + d); pen.lineTo(size - m, m);
    pen.lineTo(size - m, size - m - d); pen.lineTo(size - m - d, size - m); pen.closePath(); pen.fill();
  }
  return canvas;
}

// Opening a carried thing on the bench. Something the Workshop made opens its
// own design; anything else becomes a design of one part, from the shape,
// size and material the room has for it, so it can be edited and made again.
// The bench cannot hold a sphere (a design part is box, tapered or cylinder),
// so a round thing opens as the nearest it can and the row says so.
function carriedDesign(thing) {
  const mm = thing.size_mm || [100, 100, 100];
  const size_m = mm.map((v) => Math.max(0.001, v / 1000));
  return {
    kind: "custom",
    generation: bench.generation + 1,
    component_overrides: { "@construction": {
      schema: "banjo.workshop-construction.v1",
      added: [{ name: thing.name || "part", role: "part", shape: thing.bench_shape || "box",
                material: thing.material || "oak", size_m,
                center_m: [0, size_m[1] / 2, 0] }],
      removed: [], joints: [] } },
  };
}

// ---------------------------------------------------------------------------
// WHAT YOU HAVE
// ---------------------------------------------------------------------------
//
// The owner: "i want the inventory screen to only have the items I am
// carrying. even the raw materials should be the same thumbnail just with
// quantity attached to it, no entry fields."
//
// One grid. A thing you are carrying and a heap of oak on the rack are drawn
// the same way -- a picture with its name under it and, for anything measured
// by the kilogram, how much on the corner of the picture. The number boxes
// are gone: the rack is still editable in the Lab, where spending it happens.
//
// A material has no shape and no colour of its own, so it borrows the room's:
// MATERIAL_LOOK is the same table world.js paints bodies from, which is why a
// heap of oak in here is the colour oak is out there.
const MATERIAL_LOOK = {
  "iron": "8d949c", "aluminum": "c6ccd2", "glass": "9fd3ff",
  "alumina ceramic": "eee6da", "oak": "b07a43", "rubber": "2b2f33",
  "ice": "cfeaf5", "concrete": "9a9285", "copper": "b87333",
  "limestone": "ded6c4", "clay": "9d7b5f", "sand": "d8c89a",
  "copper ore": "7f8b74", "iron ore": "8a6a58", "cement": "b9b4a8",
  "wire": "c98b5a", "steel": "9aa3ab",
};
const kgSaid = (kg) => (kg >= 1000 ? `${(kg / 1000).toFixed(1)} t`
  : kg >= 10 ? `${Math.round(kg)} kg` : kg >= 0.1 ? `${kg.toFixed(1)} kg`
  : `${Math.round(kg * 1000)} g`);

// One tile: a picture, a name, and how much of it there is.
function invTile(thing, { quantity = null, where = "", onOpen = null } = {}) {
  const tile = make("button", { type: "button", class: "ws-tile", title: thing.name });
  const art = make("span", { class: "ws-tile-art" });
  art.append(thumbnail(thing));
  if (quantity) art.append(make("b", { class: "ws-tile-count" }, quantity));
  tile.append(art, make("span", { class: "ws-tile-name" }, thing.name));
  if (where) tile.append(make("span", { class: "ws-tile-where" }, where));
  if (onOpen) tile.onclick = () => guard(tile, onOpen);
  else tile.disabled = true;
  return tile;
}

async function showInventory() {
  const inv = await api("/api/workshop/inventory");
  $("#ws-inv-ai-help").textContent = designAssistantConnected
    ? "Building blocks are ready-made shapes. The AI creates new designs when you ask in Lab chat—for example, ‘Turn this into a small stool.’ Save keeps a design; Make builds it using your supplies."
    : "Building blocks are ready-made shapes. AI design is not connected right now; Lab chat can make basic edits, while Recipes offers existing designs to build. With AI connected, describe a new item in Lab chat.";
  const grid = $("#ws-inv-grid");
  if (!grid) return;
  const tiles = [];

  // What is on you: hands first, then the bag, in the order the room has them.
  for (const thing of inv.carried || []) {
    tiles.push(invTile(thing, {
      quantity: thing.kg != null ? kgSaid(thing.kg) : null,
      where: thing.where,
      onOpen: async () => {
        await openTheCarriedThing(thing.id);
      },
    }));
  }

  // Raw stock, drawn the same way. A material is a heap, so it is a box in
  // the material's own colour with its weight on the corner.
  for (const r of inv.materials || []) {
    if (!(r.mass_kg > 0)) continue;
    tiles.push(invTile({ name: r.material, material: r.material, shape: "box",
                         color_rgba: MATERIAL_LOOK[r.material] || "9aa7b4" },
                       { quantity: kgSaid(r.mass_kg), where: "on the rack" }));
  }
  for (const r of inv.goods || []) {
    if (!(r.mass_kg > 0)) continue;
    tiles.push(invTile({ name: r.substance, material: r.substance, shape: "sphere",
                         color_rgba: MATERIAL_LOOK[r.substance] || "8b9bab" },
                       { quantity: kgSaid(r.mass_kg), where: "goods" }));
  }

  const stock = tiles.splice((inv.carried || []).length);
  grid.replaceChildren(...tiles);
  $("#ws-inv-stock").replaceChildren(...stock);
  $("#ws-inv-note").textContent = tiles.length
    ? "Click an item to open a design copy in the Lab. Your carried item stays where it is."
    : "Your hands and bag are empty. Pick up an item in the World to bring it here.";
  $("#ws-inv-stock-empty").hidden = stock.length > 0;
  const designs = $("#ws-inv-saved"); designs.replaceChildren();
  const saved = inv.saved || [];
  const records = [...saved.map(d => ({id:d.design_id, source:"saved", name:d.label || titleCase(d.kind), kind:d.kind, version:d.revision})),
    ...(inv.designs || []).filter(d => !saved.some(s => s.design_id === d.payload?.design_id && s.label === d.name))
      .map(d => ({id:d.item_id, source:"library", name:d.name, kind:d.payload?.kind, version:d.version}))];
  for (const category of ["Furniture", "Structures", "Machines", "Other designs"]) {
    const matching = records.filter(d => designCategory(d.kind) === category);
    if (!matching.length) continue;
    const group = inventoryGroup(category);
    for (const record of matching) {
      const card = designCard(record.name, "Saved design", inventoryDesignButton(record.id, record.source));
      group.querySelector(".ws-design-grid").append(card);
      loadInventoryPicture(card, record);
    }
    designs.append(group);
  }
  if (!records.length) designs.append(make("p", {class:"ws-note"}, "No saved designs yet. Choose a building block to start one."));
  const components = $("#ws-inv-components"); components.replaceChildren();
  for (const component of inv.components || []) {
    const open = make("button", {type:"button", class:"ws-action", "data-lab-component":component.item_id}, "Use in new design");
    open.onclick = () => guard(open, () => designFromPart({library_item_id:component.item_id}, `${component.name} design`));
    const card = designCard(component.name, "Reusable part", open);
    components.append(card); paintInventoryPicture(card.querySelector("canvas"), [component.payload]);
  }
  $("#ws-inv-components-section").hidden = !(inv.components || []).length;
  renderBuildingBlocks(inv.families || []);
}

const titleCase = name => String(name || "Design").replaceAll("-", " ").replace(/\b\w/g, c => c.toUpperCase());
const designCategory = kind => ["table", "stool", "bench", "chair", "shelf-unit"].includes(kind) ? "Furniture"
  : ["frame", "shelter", "bridge"].includes(kind) ? "Structures"
  : ["cart", "rover", "drone", "kettle", "processor", "breaker"].includes(kind) ? "Machines" : "Other designs";

function installInventory() {
  const pane = $("#ws-pane-inventory"); pane.replaceChildren(make("h2", {}, "Inventory"));
  pane.append(make("p", {class:"ws-inventory-intro"}, "Open an item to change or test it in the Lab. To invent something new, choose a building block, then tell the Lab assistant what you want to make."));
  const actions = make("div", {class:"ws-inventory-actions"});
  const create = make("button", {type:"button", class:"ws-action primary", id:"ws-inv-create"}, "Start a new design");
  create.onclick = () => $("#ws-inv-blocks").scrollIntoView({block:"start", behavior:"smooth"});
  const recipes = make("button", {type:"button", class:"ws-action"}, "See what you can make"); recipes.onclick = () => showTab("recipes");
  actions.append(create, recipes); pane.append(actions);
  pane.append(make("p", {id:"ws-inv-ai-help", class:"ws-note"}));
  const section = (title, note, id, cls = "ws-design-grid") => {
    const box = make("section", {class:"ws-inventory-section"}); box.append(make("h3", {}, title));
    if (note) box.append(make("p", {class:"ws-note"}, note));
    const content = make("div", {id, class:cls}); box.append(content); pane.append(box); return box;
  };
  const carried = section("Hands & bag", "", "ws-inv-grid", "ws-inv-grid");
  carried.querySelector("h3").after(make("p", {id:"ws-inv-note", class:"ws-note"}));
  const stock = section("Materials & supplies", "These are used when you Make an item. Recipes shows what you can build; Market sells more supplies.", "ws-inv-stock", "ws-inv-grid");
  stock.append(make("p", {id:"ws-inv-stock-empty", class:"ws-note"}, "No supplies yet. Visit Market to buy some with energy."));
  section("Saved designs", "Open a design, ask for changes, then Save it or Make a physical item.", "ws-inv-saved", "ws-design-groups");
  section("Saved parts", "Use a reusable part as the start of a new design.", "ws-inv-components").id = "ws-inv-components-section";
  const blocks = section("Building blocks", "Choose a starting shape. This saves a new design and opens it in the Lab. Designing is free; Make uses materials. The assistant can add and arrange supported parts when you ask. These previews show shapes, not working machines.", "ws-inv-blocks", "ws-design-groups");
  blocks.id = "ws-inv-blocks-section";
}

function inventoryGroup(name) {
  const group = make("section", {class:"ws-design-group"});
  group.append(make("h4", {}, name), make("div", {class:"ws-design-grid"})); return group;
}

function designCard(name, description, action) {
  const card = make("article", {class:"ws-design-card"});
  card.append(make("canvas", {width:"160", height:"112", role:"img", "aria-label":`${name} shape preview`}),
    make("h5", {}, name), make("p", {}, description), action);
  card.querySelector("canvas").onclick = () => action.click();
  return card;
}

// One reusable offscreen renderer; no thumbnail touches the Lab scene,
// selection or candidate request counter.
let inventoryRenderer = null;
function paintInventoryPicture(canvas, parts) {
  if (!parts?.length || !canvas.isConnected) return;
  inventoryRenderer ||= new THREE.WebGLRenderer({alpha:true, antialias:true});
  inventoryRenderer.setSize(160, 112, false);
  inventoryRenderer.outputColorSpace = THREE.SRGBColorSpace;
  const preview = new THREE.Scene(), objects = new THREE.Group(); preview.add(objects);
  preview.add(new THREE.HemisphereLight(0xffffff, 0x45505c, 2.1));
  const light = new THREE.DirectionalLight(0xffffff, 2.8); light.position.set(3, 5, 4); preview.add(light);
  for (const part of parts) {
    if (!part.size_m) continue;
    const mesh = new THREE.Mesh(shapeFor(part), new THREE.MeshStandardMaterial({color:materialColor(part.material), roughness:.7}));
    mesh.position.set(...(part.center_m || [0, 0, 0])); mesh.rotation.copy(spinFor(part.rotation_deg)); objects.add(mesh);
  }
  const bounds = new THREE.Box3().setFromObject(objects), centre = bounds.getCenter(new THREE.Vector3());
  const radius = Math.max(.01, bounds.getSize(new THREE.Vector3()).length() / 2);
  const camera = new THREE.PerspectiveCamera(38, 160 / 112, .001, radius * 20 + 10);
  camera.position.copy(centre).add(new THREE.Vector3(1.3, .9, 1.7).normalize().multiplyScalar(radius / Math.sin(19 * Math.PI / 180) * 1.12));
  camera.lookAt(centre); inventoryRenderer.render(preview, camera);
  canvas.getContext("2d").drawImage(inventoryRenderer.domElement, 0, 0);
  canvas.dataset.preview = "ready";
  for (const mesh of objects.children) { mesh.geometry.dispose(); mesh.material.dispose(); }
}

const inventoryPictures = new Map();
const inventoryPictureQueue = [];
let inventoryPictureJobs = 0;
function inventoryPictureRequest(record) {
  return new Promise((resolve, reject) => {
    inventoryPictureQueue.push({record, resolve, reject}); pumpInventoryPictures();
  });
}
function pumpInventoryPictures() {
  while (inventoryPictureJobs < 3 && inventoryPictureQueue.length) {
    const {record, resolve, reject} = inventoryPictureQueue.shift(); inventoryPictureJobs++;
    (record.recipe ? recipeSource(record.recipe) : api("/api/workshop/open", record.source === "saved" ? {saved_design_id:record.id} : {library_item_id:record.id}, {preview:true}))
      .then(answer => resolve(answer.candidates[0].parts), reject)
      .finally(() => { inventoryPictureJobs--; pumpInventoryPictures(); });
  }
}
async function loadInventoryPicture(card, record) {
  const key = `${record.source}:${record.id}:${record.version}`;
  try {
    if (!inventoryPictures.has(key)) {
      if (inventoryPictures.size >= 200) inventoryPictures.delete(inventoryPictures.keys().next().value);
      inventoryPictures.set(key, inventoryPictureRequest(record));
    }
    paintInventoryPicture(card.querySelector("canvas"), await inventoryPictures.get(key));
  } catch {
    inventoryPictures.delete(key);
    card.querySelector("canvas").dataset.preview = "unavailable";
    card.append(make("p", {class:"ws-preview-error"}, card.dataset.recipe ? "Preview unavailable" : "Preview unavailable. Open in Lab to inspect."));
  }
}

const BLOCK_GROUPS = {
  "Frames & supports": ["leg", "apron", "stretcher", "beam", "post", "brace", "handle"],
  "Surfaces & panels": ["surface", "panel", "solar-panel"],
  "Wheels & axles": ["wheel", "axle", "mount"],
  "Machine housings": ["battery", "bin", "hopper"],
};
const BLOCK_LABELS = {surface:"Flat surface", apron:"Support rail", stretcher:"Cross rail", mount:"Axle mount", "solar-panel":"Solar panel shape", battery:"Battery housing", bin:"Container block", hopper:"Hopper block"};
const BLOCK_PURPOSES = {leg:"Support a table or seat", surface:"Start a tabletop, seat or shelf", apron:"Join legs under a tabletop",
  stretcher:"Connect the lower frame", beam:"Connect a frame", post:"Start an upright frame", brace:"Support a corner",
  handle:"Give an item a grip", panel:"Start a back, side or partition", wheel:"A turning wheel shape", axle:"A shaft for turning parts",
  mount:"Support an axle", "solar-panel":"Collector shape; add solar behavior in Lab", battery:"Housing shape; add power in Lab",
  bin:"Solid block; ask for container walls", hopper:"Solid block; ask for container walls"};
function renderBuildingBlocks(families) {
  const root = $("#ws-inv-blocks"); root.replaceChildren();
  for (const [category, names] of Object.entries(BLOCK_GROUPS)) {
    const group = inventoryGroup(category); root.append(group);
    for (const name of names) {
      const family = families.find(f => f.name === name); if (!family) continue;
      const values = Object.fromEntries(family.parameters.map(p => [p.name, p.default]));
      const label = BLOCK_LABELS[name] || titleCase(name);
      const open = make("button", {type:"button", class:"ws-action", "data-building-block":name}, "Use in new design");
      open.onclick = () => guard(open, () => designFromPart({family:name, material:"oak"}, `${label} design`));
      const card = designCard(label, BLOCK_PURPOSES[name], open);
      group.querySelector(".ws-design-grid").append(card);
      const spanning = family.offers.includes("start"), round = ["wheel", "axle", "handle"].includes(name);
      const size = spanning ? [values.width_m, .5, values.depth_m]
        : name === "wheel" ? [values.diameter_m, values.width_m, values.diameter_m]
        : name === "mount" ? [values.section_m, values.height_m, values.section_m]
        : [values.width_m, values.height_m || values.thickness_m, values.depth_m || values.thickness_m];
      paintInventoryPicture(card.querySelector("canvas"), [{size_m:size, material:"oak", shape:round ? "cylinder" : "box"}]);
    }
  }
}

async function designFromPart(first_part, label) {
  const source = await api("/api/workshop/open", {kind:"custom", first_part}, {preview:true});
  const candidate = source.candidates[0];
  const saved = await api("/api/workshop/feedback", {kind:"custom", design_id:`draft-${crypto.randomUUID()}`,
    purpose:label, parameters:candidate.parameters, component_overrides:candidate.component_overrides,
    save_design:true, label});
  await openInventoryDesign(saved.library_item.item_id, "library");
  say(designAssistantConnected
    ? "Your draft is in the Lab. Tell the AI what to make from it—for example, ‘Build a small stool from this part.’ Save keeps the design; Make builds it using your materials."
    : "Your draft is in the Lab. AI design is not connected; basic chat edits still work. Save keeps the design; Make builds it using your materials.");
}

// ---------------------------------------------------------------------------
// THE TECH TREE
// ---------------------------------------------------------------------------
//
// The owner: "The Skills area will show you more of a tech tree you can
// navigate like civilization where you can see what types of items you can
// make with that skill, what you need to unlock next, and what you could make
// with those... We also need to indicate what you have to complete to get the
// skill."
//
// It is a real graph and it is drawn as one: a column per rank, a card per
// technique, and a line from a technique to everything it stands on. The
// server works out the ranks (progression.ranks_of) because that is where the
// graph lives; this only places what it is told.
//
// Clicking a card picks it: the card beside the tree fills with what it is,
// what has to be done to earn it, and what it would let you make -- and the
// tree dims to the path, so what you are looking at is the route to that one
// thing and not nine things at once.
const tree = { picked: null, techniques: [], lines: null };

function techniqueById(id) { return tree.techniques.find((t) => t.id === id) || null; }

// Everything a technique stands on, all the way down, and everything that
// stands on it, all the way up. This is the lit path.
function treePath(id) {
  const lit = new Set([id]);
  const walk = (at, way) => {
    for (const next of (techniqueById(at) || {})[way] || []) {
      if (lit.has(next.id)) continue;
      lit.add(next.id);
      walk(next.id, way);
    }
  };
  walk(id, "needs");
  walk(id, "leads_to");
  return lit;
}

function pickTechnique(id) {
  tree.picked = tree.picked === id ? null : id;
  drawTree();
}

// The card beside the tree: everything about the one that is picked.
function treeAbout(t) {
  const box = $("#ws-tree-about");
  box.replaceChildren();
  if (!t) { box.hidden = true; return; }
  box.hidden = false;
  box.append(make("h3", {}, t.name));
  box.append(make("p", { class: "ws-note" }, t.describes || ""));

  const state = t.known ? "You know this." : t.within_reach ? "You can earn this now."
    : `First: ${t.needs.filter((n) => !n.known).map((n) => n.name).join(", ")}.`;
  box.append(make("p", { class: t.known ? "ws-tree-state ok" : t.within_reach
                                          ? "ws-tree-state reach" : "ws-tree-state" }, state));

  // WHAT YOU HAVE TO COMPLETE. Each way of earning it, in the words the
  // registry gives, ticked when the journal has seen it happen.
  if (t.earned_by && t.earned_by.length) {
    box.append(make("h4", {}, t.known ? "How it was earned" : "To earn it"));
    const list = make("ul", { class: "ws-tree-todo" });
    for (const route of t.earned_by) {
      const li = make("li", { class: route.done ? "done" : "" });
      li.append(make("i", { class: "ws-tick", "aria-hidden": "true" },
                     route.done ? "\u2713" : "\u25cb"));
      li.append(make("span", {}, route.says || route.id || ""));
      list.append(li);
    }
    box.append(list);
  } else if (!t.known) {
    box.append(make("p", { class: "ws-note" },
                    "Nothing in the world demonstrates this yet: it has to be taught."));
  }

  // WHAT IT LETS YOU MAKE, which is the whole reason to want it.
  if (t.opens && t.opens.length) {
    box.append(make("h4", {}, t.known ? "It lets you make" : "It would let you make"));
    const list = make("ul", { class: "ws-tree-opens" });
    for (const design of t.opens) {
      const li = make("li", {});
      const go = make("button", { type: "button", class: "ws-link" }, design.name);
      // Straight to the bench for that thing: a tech tree that cannot be
      // acted on is a poster.
      go.onclick = () => guard(go, async () => {
        showTab("lab");
        bench.openedLibraryItem = null;
        took(await api("/api/workshop/candidates",
                       { kind: design.name, generation: bench.generation + 1 }));
        const picker = $("#ws-archetype");
        if (picker && [...picker.options].some((o) => o.value === design.name)) {
          picker.value = design.name;
        }
      });
      li.append(go);
      list.append(li);
    }
    box.append(list);
  }

  // AND WHAT COMES AFTER IT.
  const after = (t.leads_to || []).filter((n) => !n.known);
  if (after.length) {
    box.append(make("h4", {}, "Then you could learn"));
    const list = make("ul", { class: "ws-tree-opens" });
    for (const next of after) {
      const li = make("li", {});
      const go = make("button", { type: "button", class: "ws-link" }, next.name);
      go.onclick = () => pickTechnique(next.id);
      li.append(go);
      list.append(li);
    }
    box.append(list);
  }
}

function drawTree() {
  const board = $("#ws-tree");
  if (!board) return;
  board.replaceChildren();
  const lit = tree.picked ? treePath(tree.picked) : null;
  const ranks = [];
  for (const t of tree.techniques) (ranks[t.rank] || (ranks[t.rank] = [])).push(t);

  const cards = new Map();
  for (const [depth, row] of ranks.entries()) {
    if (!row) continue;
    const column = make("div", { class: "ws-tree-rank" });
    column.append(make("p", { class: "ws-tree-rank-head" },
                       depth === 0 ? "From the start" : `After ${depth}`));
    for (const t of row) {
      const state = t.known ? "known" : t.within_reach ? "reach" : "locked";
      const card = make("button", {
        type: "button", class: `ws-tech ${state}`, "data-technique": t.id,
        role: "treeitem", "aria-selected": String(tree.picked === t.id),
      });
      card.append(make("b", {}, t.name));
      // One line under the name, and it is the useful one: what it makes.
      const opens = (t.opens || []).map((o) => o.name);
      card.append(make("span", { class: "ws-tech-opens" },
                       opens.length ? opens.join(", ") : "nothing new yet"));
      if (t.known) card.append(make("i", { class: "ws-tech-mark" }, "\u2713"));
      if (lit && !lit.has(t.id)) card.classList.add("dim");
      if (tree.picked === t.id) card.classList.add("on");
      card.onclick = () => pickTechnique(t.id);
      column.append(card);
      cards.set(t.id, card);
    }
    board.append(column);
  }

  // The lines. An SVG over the board rather than between the columns: the
  // columns scroll and wrap, and a line has to follow wherever a card ended
  // up. Measured NOW, not on the next frame -- a tab that is not on screen
  // gets no frame, and the lines would never have been drawn at all.
  // getBoundingClientRect is what we were waiting for anyway: it forces the
  // layout.
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "ws-tree-lines");
  board.append(svg);
  treeLines(board, svg, cards, lit);
  treeAbout(tree.picked ? techniqueById(tree.picked) : null);
}

function treeLines(board, svg, cards, lit) {
  const box = board.getBoundingClientRect();
  svg.setAttribute("viewBox", `0 0 ${box.width} ${box.height}`);
  svg.setAttribute("width", String(box.width));
  svg.setAttribute("height", String(box.height));
  svg.replaceChildren();
  for (const t of tree.techniques) {
    const to = cards.get(t.id);
    if (!to) continue;
    for (const need of t.needs || []) {
      const from = cards.get(need.id);
      if (!from) continue;
      const a = from.getBoundingClientRect(), b = to.getBoundingClientRect();
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      const x1 = a.right - box.left + board.scrollLeft;
      const y1 = a.top + a.height / 2 - box.top;
      const x2 = b.left - box.left + board.scrollLeft;
      const y2 = b.top + b.height / 2 - box.top;
      const mid = (x1 + x2) / 2;
      path.setAttribute("d", `M${x1} ${y1} C${mid} ${y1} ${mid} ${y2} ${x2} ${y2}`);
      path.setAttribute("class", need.known ? "ws-tree-line met" : "ws-tree-line");
      if (lit && !(lit.has(t.id) && lit.has(need.id))) path.classList.add("dim");
      svg.append(path);
    }
  }
}

// A pane that changes width moves every card, and a line drawn to where a
// card used to be points at nothing.
let treeResizing = null;
addEventListener("resize", () => {
  if (!tree.techniques.length) return;
  const pane = $("#ws-pane-skills");
  if (!pane || pane.hidden) return;
  clearTimeout(treeResizing);
  treeResizing = setTimeout(drawTree, 120);
});

async function showSkills() {
  const s = await api("/api/workshop/skills");
  $("#ws-skills-count").textContent = s.of ? `${s.known} of ${s.of} skills. A skill is earned by what the engine measured your own hands, or your machines, doing \u2014 click one to see what it takes and what it makes.` : "The world has no skills to learn yet.";
  tree.techniques = s.techniques || [];
  if (tree.picked && !techniqueById(tree.picked)) tree.picked = null;
  // Nothing picked: open on the one to do next -- the nearest rung that is
  // within reach -- so the tree arrives answering "what now".
  if (!tree.picked) {
    const next = tree.techniques.find((t) => t.within_reach);
    if (next) tree.picked = next.id;
  }
  drawTree();
  fill("#ws-skills-designs", s.designs.map((d) => item(d.name, (d.demonstrated.length ? `demonstrated: ${d.demonstrated.join(", ")}. ` : "") + `${d.evidence.length} piece${d.evidence.length === 1 ? "" : "s"} of evidence`, d.demonstrated.length ? "unlocked" : "")), "Nothing demonstrated yet: use a tool of your own on the ground, or watch a machine work.");
  fill("#ws-skills-blocked", s.blocked.map((b) => item(b.name, `${b.route}: ${(b.because || []).join("; ")}`)), "Nothing is blocked.");
  $("#ws-skills-notes").textContent = s.not_modelled.length ? `The engine said it does not model: ${s.not_modelled.join("; ")}.` : "";
}

// A LINE OF A RECIPE: how much it wants, how much you have, and the bar that
// says how near you are. A tag that reads "2.4 kg iron (have 0.6)" makes you
// do the arithmetic; the bar does it.
function recipeLine(line) {
  const wants = Number(line.kg) || 0;
  const have = Number(line.held_kg) || 0;
  const got = wants > 0 ? Math.min(1, have / wants) : 1;
  const row = make("div", { class: line.enough ? "ws-need ok" : "ws-need short" });
  row.append(make("span", { class: "ws-need-what" }, line.material || line.substance || ""));
  const bar = make("span", { class: "ws-need-bar" });
  bar.append(make("i", { style: `width:${Math.round(got * 100)}%` }));
  row.append(bar);
  row.append(make("span", { class: "ws-need-said" },
                  line.enough ? `${wants} kg` : `${have} of ${wants} kg`));
  row.title = line.enough ? `you have enough ${line.material || line.substance}`
    : `${line.short_kg} kg of ${line.material || line.substance} short`;
  return row;
}

const recipeResults = new Map();
let recipeMaking = false;
const recipeKey = t => t.saved_design_id || `${t.kind}:${t.name}`;
function recipeSource(t) {
  return api(t.saved_design_id ? "/api/workshop/open" : "/api/workshop/candidates",
    t.saved_design_id ? {saved_design_id:t.saved_design_id} : {kind:t.kind, parameters:t.parameters,
      component_overrides:t.component_overrides, sweeps:{}, generation:0}, {preview:true});
}
function installRecipes() {
  const pane = $("#ws-pane-recipes");
  pane.replaceChildren(make("h2", {}, "Recipes"));
  pane.append(make("p", {class:"ws-recipes-intro"}, "Make places an item in the World. Pick it up there to add it to your bag."),
    make("ul", {id:"ws-recipes-templates", class:"ws-list ws-recipe-grid"}));
  const processes = make("details", {id:"ws-recipes-processes", class:"ws-processes"});
  processes.append(make("summary", {}, "World processes"), make("ul", {id:"ws-recipes-room", class:"ws-list"}),
    make("ul", {id:"ws-recipes-deposits", class:"ws-list"}));
  pane.append(processes);
}
function recipeValue(name, value, cls = "") {
  const row = make("div", {class:`ws-recipe-value ${cls}`.trim()});
  row.append(make("span", {}, name), make("b", {}, value)); return row;
}
function recipeUses(t) {
  const uses = new Set(["Carry", "Place"]);
  // These badges summarize source declarations, not successful use trials.
  for (const use of t.can_do || []) {
    if (use.includes("drives itself")) uses.add("Drive");
    if (use.includes("flies")) uses.add("Fly");
    if (use.includes("digs at")) uses.add("Dig");
    if (use.includes("hauls goods")) uses.add("Haul");
    if (use.includes("works the recipe")) uses.add("Process");
    if (use.includes("charges its battery")) uses.add("Solar charging");
    if (/heat|warm/i.test(use)) uses.add("Heat");
    if (use.includes("sees water")) uses.add("Sense water");
    if (use.includes("steps of its own")) uses.add("Program");
  }
  return [...uses];
}
function recipeResult(card, result) {
  const line = card.querySelector(".ws-recipe-result");
  line.replaceChildren(); line.hidden = !result;
  if (!result) return;
  line.dataset.bad = result.bad ? "yes" : "no";
  line.append(make("b", {}, result.done ? "Made ✓" : result.bad ? "Could not make" : result.message));
  if (result.done) {
    const url = new URL(backToWorld(result.done.scene), location.origin);
    url.searchParams.set("focus", result.done.root_body);
    const view = make("a", {href:url.pathname + url.search, class:"ws-action", "data-made-body":result.done.root_body}, "View in World");
    line.append(view);
  } else if (result.bad) {
    const details = make("details", {}); details.append(make("summary", {}, "Reason"), make("p", {}, result.message)); line.append(details);
  }
}
async function showRecipes() {
  const r = await api("/api/workshop/recipes");
  fill("#ws-recipes-templates", r.templates.map(t => {
    const ready = Boolean(t.readiness?.ready_as_drawn);
    const short = t.enough ? 0 : Math.max(1, Math.round((t.short_share || 0) * 100));
    const li = item(t.source === "saved" || t.name === "Camp stool" ? t.name : titleCase(t.name), "",
      !t.enough ? "short" : ready ? "enough" : "blocked");
    li.dataset.recipe = recipeKey(t);
    const canvas = make("canvas", {width:"160", height:"112", role:"img", "aria-label":`${t.name} shape preview`});
    li.querySelector("strong").before(canvas);
    if (t.problem) {
      li.append(recipeValue("Build", "Needs repair", "ws-recipe-readiness"));
      const details = make("details", {}); details.append(make("summary", {}, "Reason"), make("p", {}, t.problem)); li.append(details); return li;
    }
    loadInventoryPicture(li, {id:recipeKey(t), source:"recipe", recipe:t,
      version:JSON.stringify([t.parameters, t.component_overrides])});
    const progress = recipeValue("Materials", `${100-short}%`);
    progress.append(make("progress", {max:"100", value:String(100-short), "aria-label":`${t.name}: ${100-short}% of materials available`}));
    li.append(progress);
    if (!t.enough) li.append(make("p", {class:"ws-missing"}, `${short}% missing`));
    const needs = make("div", {class:"ws-needs"});
    for (const line of [...(t.materials || []), ...(t.goods || [])]) if (!line.enough) needs.append(recipeLine(line));
    if (needs.childElementCount) li.append(needs);
    const all = make("details", {class:"ws-recipe-details"}); all.append(make("summary", {}, "Materials & build details"));
    const materials = make("div", {class:"ws-needs"});
    for (const line of [...(t.materials || []), ...(t.goods || [])]) materials.append(recipeLine(line));
    all.append(materials);
    const readiness = t.readiness || {};
    const fit = !readiness.workshop?.as_drawn ? readiness.workshop?.reason || "Workshop check unavailable"
      : !readiness.world ? "Open a world to check placement."
      : !readiness.world.as_drawn ? readiness.world.reason : "Fits both grids. Placement is checked when you Make.";
    all.append(make("p", {}, fit));
    li.append(recipeValue("Build", ready ? "Ready" : !readiness.world ? "World required" : "Needs changes", "ws-recipe-readiness"));
    // Current Workshop authoring has no technique gate. Do not infer a
    // requirement from an item's name or a progression hint.
    li.append(recipeValue("Skill", "None required", "ws-recipe-skill"));
    const uses = make("div", {class:"ws-recipe-uses", "aria-label":"Declared uses"});
    uses.append(make("span", {}, "Uses"));
    for (const use of recipeUses(t)) uses.append(tag(use));
    uses.title = "Source declarations; a functional trial is still required.";
    li.append(uses);
    if (t.can_do?.length) all.append(make("p", {}, "Declared: " + t.can_do.join("; ")));
    li.append(all);
    const result = make("div", {class:"ws-recipe-result", role:"status", "aria-live":"polite"}); li.append(result);
    recipeResult(li, recipeResults.get(recipeKey(t)));
    const row = make("div", {class:"ws-recipe-acts"});
    const made = make("button", {type:"button", class:"ws-action primary"}, "Make");
    made.disabled = recipeMaking || !t.enough || !ready;
    made.title = !t.enough ? `${short}% materials missing` : !ready ? fit : `Make ${t.name}`;
    made.onclick = async () => {
      if (recipeMaking) return;
      recipeMaking = true;
      $("#ws-recipes-templates").querySelectorAll(".ws-recipe-acts button:first-child").forEach(b=>b.disabled=true);
      const status = (message, bad=false, done=null) => {
        const key = recipeKey(t), entry = {message, bad, done};
        if (recipeResults.size >= 200 && !recipeResults.has(key)) recipeResults.delete(recipeResults.keys().next().value);
        recipeResults.set(key, entry); recipeResult(li, entry);
      };
      try {
        status("Preparing…");
        const source = await recipeSource(t), candidate = source.candidates[0];
        const done = await makeIt(made, {candidate:{kind:source.kind, generation:source.generation,
          design_id:candidate.design_id, purpose:candidate.purpose, parameters:candidate.parameters,
          component_overrides:candidate.component_overrides || {}}, status, replace:false});
        if (done) status("Made", false, done);
      } catch (error) { status(String(error.message || error), true); }
      finally { recipeMaking=false; await showRecipes().catch(error=>say(error.message, true)); }
    };
    row.append(made);
    if (!t.enough) {
      const shop = make("button", {type:"button", class:"ws-action"}, "Get supplies"); shop.onclick = () => showTab("market"); row.append(shop);
    }
    li.append(row); return li;
  }), "No recipes.");
  fill("#ws-recipes-room", r.room_recipes.map(x => {
    const li = item(x.name);
    li.append(recipeValue("Input", Object.entries(x.in).map(([k,v])=>`${v} kg ${k}`).join(" + ")),
      recipeValue("Output", Object.entries(x.out).map(([k,v])=>`${v} kg ${k}`).join(" + ")),
      recipeValue("Machine", x.worked_by?.join(", ") || "None")); return li;
  }), "");
  fill("#ws-recipes-deposits", r.deposits.map(d=>item(d.name, `${d.left_kg} kg ${d.substance}`)), "");
  $("#ws-recipes-processes").hidden = !r.room_recipes.length && !r.deposits.length;
}

async function showMarket() {
  const market = await api("/api/workshop/market", { action:"view" });
  $("#ws-market-balance").textContent = `${market.balance_j.toLocaleString()} J`;
  $("#ws-market-pricing").textContent = `${market.pricing} The trader restocks one lot of each item every two minutes of world time, up to its shelf capacity. Your solar farm keeps generating energy while the world runs.`;
  const next = market.guidance?.skill;
  $("#ws-market-next").textContent = next
    ? `Next skill: ${next.name}. ${next.route} Buying stock does not teach the skill; use it in the world to demonstrate the technique.`
    : "You have reached the currently available skills. Keep building and testing designs.";
  const rec = market.guidance?.recipe;
  $("#ws-market-recipe").textContent = rec
    ? `A ready recipe to work toward: ${rec}. The highlighted lot ${market.guidance.covers_gap ? "fills" : "reduces"} its ${kgSaid(market.guidance.gap_kg)} material gap.`
    : "Open Recipes to see what your next build needs. Market stock can fill material and machine-goods gaps.";
  const bank = $("#ws-market-bank");
  bank.disabled = !market.bankable;
  bank.title = market.bankable ? "Draw 100 measured joules from the solar farm's battery" : "Open the world before banking energy";
  bank.onclick = () => guard(bank, async () => {
    try {
      const after = await api("/api/workshop/market", { action:"bank", joules:100, request_id:crypto.randomUUID() });
      $("#ws-market-status").textContent = `Banked 100 J. Balance: ${after.balance_j.toLocaleString()} J.`;
      await showMarket();
    } catch (error) {
      $("#ws-market-status").textContent = error.message || String(error);
    }
  });
  fill("#ws-market-offers", market.offers.map((offer) => {
    const li = item(offer.name,
      `${kgSaid(offer.mass_kg)} ${offer.substance} · ${offer.price_j} J · ${offer.remaining} lots in this world`);
    if (offer.id === market.guidance?.offer_id) li.classList.add("ws-market-next");
    const buy = make("button", { type:"button", class:"ws-action" }, "Buy for Workshop");
    buy.disabled = offer.remaining < 1 || market.balance_j < offer.price_j;
    buy.onclick = () => guard(buy, async () => {
      try {
        const after = await api("/api/workshop/market", { action:"buy", item_id:offer.id,
          quoted_price_j:offer.price_j, request_id:crypto.randomUUID() });
        $("#ws-market-status").textContent = `${offer.name} is on your Workshop rack. ${after.balance_j.toLocaleString()} J remains.`;
        await showMarket();
      } catch (error) {
        $("#ws-market-status").textContent = error.message || String(error);
        await showMarket();
      }
    });
    li.append(buy);
    return li;
  }), "The trader has no stock right now. A new lot arrives after two minutes of world time.");
  fill("#ws-market-orders", market.orders.map((order) => item(
    market.offers.find((offer) => offer.id === order.item_id)?.name || order.item_id,
    `${order.price_j} J · ${order.created_at}`)), "No purchases yet.");
}

// Opening the Workshop straight onto one rung of the tree: the world page's
// "Next: ..." line links here, because that line IS the tech tree and saying
// so in a place you cannot get to from it is not saying it.
// A thing dragged out of the world's bag and dropped on the Workshop. Its
// own design if the bench made it, else a bench copy of its shape -- the
// same two routes the Inventory tab's own tiles take, because it is the
// same act by a different gesture.
async function openTheCarriedThing(id) {
  clearLab();
  const revision = bench.revision;
  let inv;
  try {
    inv = await api("/api/workshop/inventory");
  } catch {
    if (revision !== bench.revision) return;
    showTab(WORKSHOP_OPENS_ON);
    return;
  }
  if (revision !== bench.revision) return;
  const thing = (inv.carried || []).find((x) => String(x.id) === String(id));
  if (!thing) {
    // Put down between the drag and the arrival, or carried by somebody
    // else's page. The inventory is the honest place to land.
    clearLab(); showTab("lab");
    say("That is not being carried any more.", true);
    return;
  }
  bench.inventorySelection = {id:thing.id, name:thing.name, source:"carried"};
  showTab("lab");
  bench.openedLibraryItem = null;
  try {
    if (thing.design_id) {
      const source = await api("/api/world/workshop/what_made", {body:thing.name});
      if (revision !== bench.revision) return;
      const answer = await api("/api/workshop/candidates", {...source.recipe, sweeps:{}});
      if (revision !== bench.revision) return;
      if (took(answer)) { $("#ws-archetype").value = answer.kind; return; }
    }
    const answer = await api("/api/workshop/candidates", carriedDesign(thing));
    if (revision !== bench.revision) return;
    if (took(answer)) {
      $("#ws-archetype").value = "custom";
      say(`${thing.name} is on the bench: one part, ${thing.material}.`);
    }
  } catch (error) {
    if (revision !== bench.revision) return;
    clearLab(); showTab("lab");
    say(`${thing.name} could not be opened: ${error.message || error}`, true);
  }
}

function openTheTreeAt(id) {
  tree.picked = id || null;
  showTab("skills");
}

function inventoryDesignButton(id, source) {
  const open = make("button", {type:"button", class:"ws-action", "data-lab-source":source, "data-item":id}, "Open in the Lab");
  open.onclick = () => guard(open, () => openInventoryDesign(id, source));
  return open;
}

async function openInventoryDesign(id, source) {
  clearLab();
  const revision = bench.revision;
  try {
    const answer = await api("/api/workshop/open", source === "saved" ? {saved_design_id:id} : {library_item_id:id});
    if (revision !== bench.revision) return;
    bench.inventorySelection = {id, source, name:answer.library_item?.name || answer.candidates[0]?.label || "Saved design"};
    bench.openedLibraryItem = source === "library" ? id : null;
    if (took(answer)) { $("#ws-archetype").value = answer.kind; showTab("lab"); }
  } catch (error) {
    if (revision !== bench.revision) return;
    clearLab(); showTab("lab"); say(`That saved design could not be opened: ${error.message || error}`, true);
  }
}

async function showGoals() {
  const root = $("#ws-goals-list"), status = $("#ws-goals-status");
  if (!worldId) {
    root.replaceChildren(item("Start your first camp", "Use Menu to create or join a game."));
    return;
  }
  const goals = await api("/api/workshop/goals", {});
  root.replaceChildren();
  $("#ws-goals-progress").textContent = goals.complete ? "First camp complete. Your progress is saved."
    : `${goals.goals.filter((g) => g.complete).length} / ${goals.goals.length} goals complete · Your energy: ${goals.balance_j} J`;
  $("#ws-goals-limits").textContent = goals.limits;
  $("#ws-goals-next").textContent = goals.complete ? goals.follow_up
    : "Gather → build → carry. Your stool needs 2.5088 kg of oak; six lots leave wood for the next build. Prices change, so bank more energy when you need it.";
  const act = async (button, work) => {
    button.disabled = true; status.textContent = "Working…";
    try { await work(); status.textContent = "Saved."; await showGoals(); }
    catch (error) { status.textContent = error.message || String(error); }
    finally { button.disabled = false; }
  };
  for (const goal of goals.goals) {
    const li = item(goal.title, `${goal.complete ? "Complete" : `${goal.value} / ${goal.target} ${goal.unit}`} · ${goal.instruction}`,
                    goal.complete ? "enough" : "short");
    li.dataset.goal = goal.id;
    li.dataset.complete = String(goal.complete);
    if (goals.next_goal === goal.id) {
      let label, work;
      if (goal.id === "bank-solar") {
        label = "Bank 500 J";
        work = async () => {
          await api("/api/world/open", {});
          await api("/api/workshop/market", { action:"bank", joules:500, request_id:crypto.randomUUID() });
        };
      } else if (goal.id === "stock-oak") {
        label = "Buy 0.5 kg of oak";
        work = async () => {
          const market = await api("/api/workshop/market", {});
          const oak = market.offers.find((o) => o.id === "oak-stock");
          if (market.balance_j < oak.price_j) throw new Error(`This lot costs ${oak.price_j} J. Bank another 500 J, then buy.`);
          await api("/api/workshop/market", { action:"buy", item_id:oak.id,
            quoted_price_j:oak.price_j, request_id:crypto.randomUUID() });
        };
        const bank = make("button", { type:"button", class:"ws-action", "data-goal-bank":"" }, "Bank another 500 J");
        bank.onclick = () => act(bank, async () => {
          await api("/api/world/open", {});
          await api("/api/workshop/market", { action:"bank", joules:500, request_id:crypto.randomUUID() });
        });
        li.append(bank);
      } else if (goal.id === "build-camp") {
        label = "Build camp stool";
        work = async () => {
          await api("/api/world/open", {});
          clearLab();
          took(await api("/api/workshop/candidates", { ...goals.recipe, sweeps:{} }));
          $("#ws-archetype").value = goals.recipe.kind;
          await makeIt($("#ws-make"));
          if ($("#ws-make-status")?.dataset.bad === "yes") throw new Error($("#ws-make-status").textContent);
        };
      } else {
        label = "Pack camp stool";
        work = async () => {
          const opened = await api("/api/world/open", {});
          const current = await api("/api/workshop/goals", {});
          if (!current.camp_body) throw new Error("Your camp stool is no longer in the world. Build another from the same recipe.");
          const packed = await api("/api/world/inventory", { session:opened.session, op:"take",
            item:current.camp_body, request:crypto.randomUUID() });
          if (!packed.ok) throw new Error(packed.why || "The stool could not be packed.");
        };
      }
      const button = make("button", { type:"button", class:"ws-action primary", "data-goal-action":goal.id }, label);
      button.onclick = () => act(button, work);
      li.append(button);
    }
    root.append(li);
  }
}

const WORKSHOP_OPENS_ON = "inventory";

function showTab(name) {
  if (!["inventory", "lab", "skills", "recipes", "market", "goals"].includes(name)) name = WORKSHOP_OPENS_ON;
  const url = new URL(location.href); url.searchParams.set("tab", name);
  for (const key of ["carry", "design", "library"]) url.searchParams.delete(key);
  if (bench.inventorySelection) {
    const key = {carried:"carry", saved:"design", library:"library"}[bench.inventorySelection.source];
    if (key) url.searchParams.set(key, bench.inventorySelection.id);
  }
  window.history.replaceState(null, "", url);
  refreshNavigation(name);
  $("#ws-screen-status").textContent = name === "lab" && bench.inventorySelection ? bench.inventorySelection.name : name[0].toUpperCase() + name.slice(1);
  for (const button of document.querySelectorAll(".ws-tabs button")) button.setAttribute("aria-selected", String(button.dataset.tab === name));
  const viewport = $(".ws-viewport"); if (viewport) viewport.hidden = name !== "lab";
  // The takes are the Lab's too: little pictures of the thing on the
  // bench, which mean nothing beside what you are carrying.
  const takes = $("#ws-takes"); if (takes) takes.hidden = name !== "lab" || !bench.inventorySelection;
  const machines = $("#ws-machine-bench"); if (machines && name !== "lab") machines.hidden = true;
  for (const pane of ["inventory", "skills", "recipes", "market", "goals"]) { const el = $(`#ws-pane-${pane}`); if (el) el.hidden = pane !== name; }
  if (name === "lab") resize();
  const loader = { inventory: showInventory, skills: showSkills, recipes: showRecipes, market: showMarket, goals: showGoals }[name];
  if (loader) guard(null, loader);
  updateLabSelection();
}

let labWasSelected = false;
function updateLabSelection() {
  const selected = Boolean(bench.inventorySelection && chosen());
  $("#design-workshop").classList.toggle("lab-empty", !selected);
  const empty = $("#ws-empty"); if (empty) empty.hidden = selected;
  const input = $("#ws-component-chat-text"), send = $("#ws-component-chat button[type=submit]");
  if (input && !selected) { input.disabled = true; input.placeholder = "Select an item from Inventory first"; }
  else if (input && !labWasSelected) { input.disabled = false; input.placeholder = "Ask about this item or describe a change"; }
  if (send && !selected) send.disabled = true;
  else if (send && !labWasSelected) send.disabled = false;
  const intro = $(".ws-chat-intro");
  const text = selected ? "Discuss, modify or test your selected item. Lab changes leave your carried item or saved version unchanged until you explicitly make or save them."
    : "Select a carried item or saved design from Inventory to discuss, modify or test it in the Lab.";
  if (intro && intro.textContent !== text) intro.textContent = text;
  labWasSelected = selected;
}

function clearLab() {
  bench.inventorySelection = null; bench.candidates = []; bench.selectedPart = null;
  bench.libraryInspection = null; bench.isolated = null; bench.revision++; candidateRequest++;
  clearPlayback(); clearGroup(); clearGhost(); balance.visible = false; support.visible = false;
  stage.dataset.showing = "empty"; delete stage.dataset.kind;
  $("#ws-name").textContent = "Empty lab"; $("#ws-parts").replaceChildren();
  bench.takes = []; bench.cleanThumb = ""; renderTakes(); updateLabSelection();
  history.past = []; history.now = null; history.future = [];
}

// The rack as a row of bins, the same shape as the world's numbered bag slots.
function renderRackStrip() {
  const strip = $("#ws-rack-strip");
  if (!strip) return;
  const rows = (bench.rack && bench.rack.materials) || [];
  const needs = chosen()?.needs || null;
  const wanted = {};
  for (const row of (needs && needs.materials) || []) wanted[row.material] = row;
  strip.replaceChildren();
  for (const row of rows) {
    const want = wanted[row.material];
    const bin = make("label", { class:"ws-bin" });
    if (want) bin.dataset.state = want.short_kg > 0 ? "short" : "wanted";
    bin.append(make("span", { class:"ws-bin-name" }, row.material));
    const input = make("input", { type:"number", min:"0", max:"100000", step:"0.1", value:String(row.mass_kg),
                                  "aria-label":`${row.material} in the rack, kilograms` });
    if (worldId) { input.disabled = true; input.title = "Game stock comes from the world and Market"; }
    input.addEventListener("change", () => guard(input, async () => {
      const mass = input.valueAsNumber;
      if (!Number.isFinite(mass) || mass < 0) throw new Error("Enter a mass in kilograms, zero or more.");
      const answer = await api("/api/workshop/library", { action:"set_rack", material:row.material, mass_kg:mass });
      bench.rack = answer.rack; renderRack(); renderRackStrip(); reprobe();
    }));
    bin.append(input);
    if (want) bin.append(make("span", { class:"ws-bin-need" },
      want.short_kg > 0 ? `wants ${want.needed_kg} · short ${want.short_kg}` : `wants ${want.needed_kg}`));
    strip.append(bin);
  }
  if (needs) strip.append(make("p", { class:"ws-bin-says", "data-bad": needs.enough ? "no" : "yes" }, needs.says));
}

installEditor();
installBench();
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
// Read back what a turn has done so far, about once a second, and tell the
// chat's own shell so it can put it under the working bubble.
function watchTheTurn(turn) {
  let stopped = false;
  const tick = async () => {
    if (stopped) return;
    try {
      const said = await api("/api/workshop/progress", { turn });
      if (!stopped && said?.steps?.length) {
        dispatchEvent(new CustomEvent("banjo-workshop-progress", { detail: said }));
      }
    } catch { /* the answer itself is what matters; this is only the commentary */ }
    if (!stopped) setTimeout(tick, 900);
  };
  // Ask once straight away, before the turn itself is even sent. A turn that
  // ends quickly -- an error, a refusal, a question -- would otherwise be over
  // before the first read, and a wait that sometimes says nothing is worse
  // than one that always does. The first answer is usually empty, which shows
  // nothing; the point is that the reading has started.
  tick();
  return { stop: () => { stopped = true; } };
}

async function chatEdit() {
  if (!bench.selectedPart) throw new Error("Click the part you want to talk about first.");
  const input = $("#ws-component-chat-text"), message = input.value.trim();
  if (!message) throw new Error("Tell Workshop what to change.");
  const selected = bench.selectedPart;
  // A turn is one POST that answers when the whole thing is done, and the work
  // inside it is several round trips to the model. The id goes in with the
  // request and the page reads back what the turn has done so far, so the wait
  // says what is happening instead of nothing.
  const turn = crypto.randomUUID();
  const watching = watchTheTurn(turn);
  let answer;
  try {
    answer = await api("/api/workshop/candidates",
                       { ...candidateBody(), component_chat:{ part_name:selected, message, turn } });
  } finally { watching.stop(); }
  if (!took(answer, selected)) return;
  if (answer.workshop_chat?.scope) $("#ws-edit-scope").value = answer.workshop_chat.scope;
  // Asked to try the thing, the chat hands back a run to watch. It is played
  // over the object, with one button back to the build.
  const showing = answer.workshop_chat?.showing;
  if (showing?.frames?.length > 1) { setWorkspaceMode("test"); setPlayback(showing); }
  // Asked to take a change back, the chat says so and the PAGE does it: the
  // session's history lives here, not in the turn, so it reaches back past
  // whatever the chat itself did.
  for (let step = Number(answer.workshop_chat?.undo) || 0; step > 0; step--) stepHistory(-1);
  // The reply belongs in the chat, which already shows it. It used to be said
  // here as well, which put it across the top of the page and under "Cheap
  // checks" at the same time: the same sentence in three places.
  input.value = "";
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
    + (issues.length ? " " + issues.join(". ") : "") + " No bending, fracture or joint-strength certification."
  // A design the room cannot carry has to reach the person, and the panel this
  // is written in is not on the bench any more. The notice sits over the view.
  if (!rigid && report.assessment !== "dimensions-only" && !report.compilation_ready) {
    say(summary.textContent, true);
  }
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
  // "any" is the little world: it installs whatever the design compiles to, so
  // it is offered for a design of cells and a design of exact bodies alike.
  bench.benchTests = bench.benchTests.filter(t => t.category === "simulation" && t.subject === "selected-product"
    && (t.required_model === "any" || (t.required_model || "lattice") === (chosen()?.mechanical_model || "lattice")));
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
    clearPlayback(); scheduleSetup();
  };
  if (!definition) { root.append(make("p", { class:"ws-feedback-count" }, "No working simulation is available for this product yet. Report-only tools have been removed from Test; the design is still editable.")); return; }
  root.append(make("p", { class:"ws-feedback-count" }, definition.about));
  const advanced = make("details",{class:"ws-advanced"});
  advanced.append(make("summary",{},"Advanced settings and limits"));
  const advancedNames = new Set(["duration_s","cell_size_m","evaluate_limits","max_displacement_m","max_rotation_deg","max_fracture_events","min_actual_load_kg"]);
  for (const control of definition.controls || []) {
    const destination = advancedNames.has(control.name) || control.name.startsWith("max_") || control.name.startsWith("min_") ? advanced : root;
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
      if (definition.test === "drop_product" && control.name === "height_m") input.addEventListener("change", () => {
        const time = document.querySelector('[data-bench-control="duration_s"]'); if (!time) return;
        const wanted = Math.min(Number(time.max) || 5, Math.ceil((Math.sqrt(2*Number(input.value)/9.81) + .75)*10)/10);
        if (Number(time.value) < wanted) { time.value = String(wanted); time.dispatchEvent(new Event("change", {bubbles:true})); }
      });
      label.append(input,shown); destination.append(label); continue;
    } else {
      input = make("input", { type:"number", value:String(chosenValue ?? ""), min:String(control.min ?? ""), max:String(control.max ?? ""), step:String(control.step ?? "any"), "data-bench-control":control.name }); input.dataset.valueType = "number";
    }
    label.append(input); destination.append(label);
  }
  root.append(advanced);
  for (const limitation of definition.limitations || []) advanced.append(make("p", { class:"ws-feedback-count" }, `Limit: ${limitation}`));
  scheduleSetup();
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
  if (definition.test !== "rigid_motion" && definition.test !== "try_in_a_room") {
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
function watchPanel(showing) {
  const panel = $("#ws-watching");
  if (panel) panel.hidden = !showing;
}
function clearPlayback() {
  watchPanel(false);
  workspace.sequence++; clearTimeout(workspace.timer); workspace.setup=null;
  bench.playback = null; bench.playbackIndex = 0; bench.playbackPlaying = false;
  $("#ws-simulation-feedback")?.replaceChildren();
  const root = $("#ws-playback"); if (root) root.hidden = true;
  stage.dataset.physicsPlaying="false"; delete stage.dataset.physicsTime;
  if (view === "physics") { view = "skin"; pressView("skin"); show(false); }
}
function setPlayback(recording) {
  watchPanel(Boolean(recording?.frames?.length));
  if (!recording?.frames || recording.frames.length < 2 || !(recording.duration_s > 0)) {
    clearPlayback(); throw new Error("The test returned no advancing simulation. No successful simulation is claimed.");
  }
  workspace.sequence++; clearTimeout(workspace.timer); workspace.setup=null;
  bench.playback=recording; bench.playbackIndex=0; bench.playbackPlaying=false;
  $("#ws-playback").hidden=false;
  const slider=$("#ws-play-timeline"); slider.max=String(recording.frames.length-1);slider.value="0";
  bench.playbackSpeed = recording.test === "kettle_heat" ? 30 : .25;
  $("#ws-play-speed").value=String(bench.playbackSpeed);
  view="physics";pressView("physics");show(false);frameSimulation(recording);
  setPlaybackIndex(0);togglePlayback();
  noteTake(recording);
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
  const leaves = screen.stops_standing_square;
  if (leaves) box.append(make("p", { class:"ws-note" + (screen.standing === "resting on the floor" ? "" : " warn"), id:"ws-screen-floor-note" },
    `Pushed along this line it stays put up to about ${Number(leaves.force_n).toLocaleString(undefined, { maximumFractionDigits:0 })} N; past that it ${leaves.does}.`));
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
  bench.lastResult = result || null;
  const root = $("#ws-bench-result"); root.replaceChildren(); if (!result) return;
  const card = make("div", { class:"ws-note" });
  if (result.test === "drive") {
    card.append(make("strong", {}, "Driven by hand"), make("p", {}, result.says || "driven"));
    root.append(card);
    if (result.playback) setPlayback(result.playback);
    return;
  }
  if (result.test === "try_in_a_room") {
    // The little world says what it did and what became of the thing. Turning
    // is its own line: a stool that settled 3 mm and a stool lying on its side
    // have both "moved" about nothing.
    const m = result.measured || {}, broke = m.broke || [], dented = m.dented || [];
    const what = m.fell_over ? "It went over" : broke.length ? `${broke.length} of it broke`
      : dented.length ? `${dented.length} of it is dented` : "It stayed up";
    card.append(make("strong", { id:"ws-room-outcome", "data-outcome": m.fell_over ? "fell" : broke.length ? "broke" : dented.length ? "dented" : "stood",
                                 "data-broke": String(broke.length), "data-dented": String(dented.length) }, what),
      make("p", { id:"ws-room-says" }, result.says || ""),
      make("p", {}, `Moved ${m.moved_m == null ? "—" : `${(Number(m.moved_m) * 1000).toFixed(0)} mm`} · turned ${Number(m.turned_deg || 0).toFixed(1)}° · ${Number(m.ran_for_s || 0).toFixed(1)} s in the room`));
    for (const store of m.stores || []) card.append(make("p", {}, `${store.name}: ${Number(store.charge_j).toFixed(0)} J`));
    for (const panel of m.panels || []) card.append(make("p", {}, `${panel.name}: ${Number(panel.power_w).toFixed(1)} W`));
    for (const program of m.programs || []) card.append(make("p", {}, `${program.name} is ${program.doing}: ${program.why}`));
    for (const run of m.failures || []) card.append(make("p", {}, `${run.name} ${run.outcome} into ${run.pieces} at ${Number(run.at_s).toFixed(2)} s`));
    const verdict = result.acceptance || {}, status = verdict.status || "not-declared";
    card.append(make("strong", { id:"ws-acceptance-status", "data-status":status },
      `Declared limits: ${status === "not-declared" ? "not evaluated (no limits declared)" : status}`));
    for (const check of verdict.checks || []) {
      if (check.status === "passed") continue;
      card.append(make("p", {}, `${check.metric}: ${check.measured == null ? "not measured" : check.measured}; ${check.operator} ${check.limit}${check.unit ? ` ${check.unit}` : ""} (${check.status}).`));
    }
  } else if (result.test === "rigid_motion") {
    const m = result.measured || {};
    card.append(make("strong", {}, "Native precise rigid motion — not a strength test"),
      make("p", {}, `${m.collision_boxes} exact boxes · ${m.stored_cells} lattice cells · ${Number(m.mass_kg).toFixed(3)} kg`),
      make("p", {}, `Centre of mass moved ${Number(m.displacement_m).toFixed(4)} m in ${Number(m.elapsed_s).toFixed(2)} s.`));
  } else if (["drop_product","slide_product","impact_product"].includes(result.test)) {
    const m=result.measured || {}, r=result.requested || {}, hit=m.hardest_impact, striker=r.striker;
    const inTheAir = result.test === "drop_product" && m.landed === false;
    const what = inTheAir ? `Still falling when the run ended: simulate ${r.settled_duration_s} s to see it land`
      : m.outcome === "broke" ? `Broke into ${m.pieces} pieces${m.first_break_s == null ? "" : ` at ${Number(m.first_break_s).toFixed(2)} s`}`
      : m.outcome === "dented" ? "Dented, and still in one piece" : "Held: still in one piece";
    const headline = make("strong",{id:"ws-break-outcome","data-outcome":inTheAir ? "in-the-air" : m.outcome || "held","data-pieces":String(m.pieces ?? 1)},what);
    card.append(headline,
      make("p",{},result.test==="drop_product" ? `Dropped ${r.applied_height_m} m (asked ${r.height_m} m; heights are whole cells)`
        : result.test==="impact_product" ? `Struck by ${Number(striker?.actual_kg || 0).toFixed(1)} kg of iron at ${Number(striker?.speed_m_s || 0).toFixed(1)} m/s: ${Math.round(Number(striker?.energy_j || 0)).toLocaleString()} J`
        : `Starting speed ${r.speed_m_s} m/s along +X`));
    // The engine's own reading of the hardest blow to the thing as designed:
    // what it met, how fast, and the speed under which that meeting can break nothing.
    if (hit) card.append(make("p",{id:"ws-break-reading"},`Met ${hit.by} at ${Number(hit.closing_speed_m_s).toFixed(2)} m/s. Against that, this can first break at ${Number(hit.threshold_speed_m_s).toFixed(2)} m/s${hit.dent_speed_m_s == null ? " and has no bending range" : ` and bend at ${Number(hit.dent_speed_m_s).toFixed(2)} m/s`}.`));
    card.append(make("p",{},`${m.prototype_displacement_m == null ? "It did not survive as one body" : `Moved ${Number(m.prototype_displacement_m).toFixed(3)} m`} · ${m.fracture_events} failure ${m.fracture_events === 1 ? "run" : "runs"} · ${m.clock_s.toFixed(2)} s simulated`));
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
    // What became of it under the load, in the engine's own words: the load
    // survey's beam reading if it was ever called overloaded, and what statics
    // on its own cells then said, with how near its bonds came to giving.
    const m = result.measured || {}, over = m.overload, statics = m.statics, percent = statics?.ratio == null ? null : Math.round(Number(statics.ratio)*100);
    const applied = Number(m.actual_grid_load_kg).toFixed(1);
    const what = m.outcome === "broke" ? `Gave way under ${applied} kg: in ${m.pieces} pieces`
      : percent != null ? `Held ${applied} kg, at ${percent}% of what breaks it`
      : `Held ${applied} kg`;
    card.append(make("strong", {id:"ws-load-outcome","data-outcome":m.outcome || "held","data-pieces":String(m.pieces ?? 1)}, what));
    if (over) card.append(make("p", {id:"ws-load-reading"}, `By beam theory the load puts ${Number(over.stress_mpa).toFixed(1)} MPa of bending in it over the ${Number(over.span_m).toFixed(2)} m between its feet, against the ${Number(over.holds_mpa).toFixed(1)} MPa it can take, so the engine was asked. Statics on its own cells: ${statics?.stop || "no answer"}${percent == null ? "" : `, its bonds at ${percent}% of what breaks them`}.`));
    else card.append(make("p", {id:"ws-load-reading"}, "By beam theory the bending in it stays under what its material can take, so nothing asked whether it would give."));
    card.append(make("p", {}, `Requested ${m.requested_load_kg} kg · applied ${m.actual_grid_load_kg} kg. A top one cell thick has no depth to bend through: use a cell size that puts at least two cells through the part that carries the load.`),
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
  // What this EXACT shape was told before. Kept against the design's
  // fingerprint, so editing a leg does not inherit yesterday's verdict.
  if (result.earlier?.length) {
    const past = make("details", { class:"ws-family", id:"ws-earlier-runs" });
    past.append(make("summary", {}, `Tried ${result.earlier.length} time${result.earlier.length === 1 ? "" : "s"} before on this exact shape`));
    for (const run of result.earlier) {
      past.append(make("p", {}, `${new Date(run.ran_at).toLocaleString()} · ${run.test} · ${run.verdict} — ${run.says}`));
    }
    card.append(past);
  } else if (result.kept_against) {
    card.append(make("p", { class:"ws-feedback-count", id:"ws-earlier-runs" },
      "First run on this exact shape. It is kept, so the next one can be compared with it."));
  }
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
async function runBenchTest(configOverride = null) {
  const definition=benchDefinition(); if(!definition) throw new Error("Choose a supported simulation first.");
  const revision=bench.revision, request=++benchTestRequest, config=configOverride || benchConfig();
  const current=()=>request===benchTestRequest && revision===bench.revision && definition.test===bench.selectedBenchTest;
  workspace.sequence++; clearTimeout(workspace.timer); workspace.running=true;
  bench.playback=null; bench.playbackPlaying=false; $("#ws-playback").hidden=true;
  if (workspace.setup) {view="physics";drawPlayback();} else {view="skin";show(false);}
  const started=performance.now();
  const status=make("p",{id:"ws-simulation-status",role:"status","aria-live":"polite"},`Calculating ${definition.name.toLowerCase()} on the selected object…`);
  status.dataset.state="running"; stage.dataset.phase="calculating";
  $("#ws-simulation-feedback").replaceChildren(status); $("#ws-bench-result").replaceChildren();
  const clock=setInterval(()=>{if(current())status.textContent=`Calculating ${definition.name.toLowerCase()} · ${((performance.now()-started)/1000).toFixed(1)} s elapsed. The setup stays visible; results appear when calculation finishes.`;},200);
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
  } finally {clearInterval(clock);workspace.running=false;}
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
// Rename and throw away. Nothing in the Workshop could do either: fourteen
// routes and not one of them removed anything, and a name could only be
// changed by saving again, which counted as a new revision of the design.
function keepOrBin(row, { open, rename, remove, label }) {
  const card = make("div", { class:"ws-card ws-keep-row" });
  const name = make("button", { type:"button", class:"ws-keep-open" });
  name.append(make("strong", {}, row.title), make("small", {}, row.said));
  name.onclick = () => guard(name, open);
  const edit = make("button", { type:"button", class:"ws-keep-small", title:`Rename this ${label}` }, "Rename");
  edit.onclick = () => guard(edit, async () => {
    const called = window.prompt(`What should this ${label} be called?`, row.title);
    if (called == null || !called.trim()) return;
    await rename(called.trim());
  });
  const bin = make("button", { type:"button", class:"ws-keep-small ws-keep-bin", title:`Throw this ${label} away` }, "Delete");
  bin.onclick = () => guard(bin, async () => {
    if (!window.confirm(`Throw away "${row.title}"? This cannot be undone.`)) return;
    await remove();
  });
  const actions = make("div", { class:"ws-keep-actions" });
  actions.append(edit, bin);
  card.append(name, actions);
  return card;
}
function savedDesigns(rows) {
  bench.savedDesigns = Array.isArray(rows) ? rows : []; const root = $("#ws-saved-designs"); root.replaceChildren();
  if (!bench.savedDesigns.length) { root.append(make("p", { class:"ws-feedback-count" }, "No saved designs yet.")); return; }
  for (const saved of bench.savedDesigns) {
    root.append(keepOrBin({
      title: saved.label || saved.design_id,
      said: `${saved.kind} · saved ${saved.revision} time${saved.revision === 1 ? "" : "s"}${saved.measured ? ` · ${saved.measured.mass_kg} kg` : ""}`,
    }, {
      label: "design",
      open: async () => { const answer = await api("/api/workshop/open", { saved_design_id:saved.design_id }); bench.openedLibraryItem = null; if (took(answer)) $("#ws-archetype").value = answer.kind; },
      rename: async (name) => savedDesigns((await api("/api/workshop/library", { action:"rename_design", design_id:saved.design_id, name })).saved_designs),
      remove: async () => savedDesigns((await api("/api/workshop/library", { action:"delete_design", design_id:saved.design_id })).saved_designs),
    }));
  }
}
function renderUserLibrary() {
  renderBuildChoices();
  const root = $("#ws-user-library"); root.replaceChildren();
  if (!bench.personalLibrary.length) { root.append(make("p", { class:"ws-feedback-count" }, "Nothing saved yet. Select a part and save it.")); return; }
  for (const item of bench.personalLibrary) {
    const card = keepOrBin({
      title: item.name,
      said: `${item.item_type}${item.family ? ` · ${item.family}` : ""} · version ${item.version}`,
    }, {
      label: item.item_type,
      open: async () => {
        if (item.item_type === "assembly") { const answer = await api("/api/workshop/open", { library_item_id:item.item_id }); bench.openedLibraryItem = item.item_id; if (took(answer)) $("#ws-archetype").value = answer.kind; }
        else await inspectLibraryComponent(item.item_id);
      },
      rename: async (name) => { bench.personalLibrary = (await api("/api/workshop/library", { action:"rename_component", item_id:item.item_id, name })).personal_library; renderUserLibrary(); },
      remove: async () => { bench.personalLibrary = (await api("/api/workshop/library", { action:"delete_component", item_id:item.item_id })).personal_library; renderUserLibrary(); },
    });
    // The name IS the item: clicking it opens the thing and dragging it drops
    // the thing. Putting those on the card around it instead would mean a
    // click on the card did nothing, which is what a person would try first.
    const open = card.querySelector(".ws-keep-open");
    open.classList.add("ws-library-item");
    open.draggable = true;
    open.ondragstart = (event) => { event.dataTransfer.setData("application/x-banjo-library-item", item.item_id); event.dataTransfer.effectAllowed = "copy"; };
    // Every version of this was written on every save and could not be read
    // back by anything. This is the reader.
    if (item.version > 1) {
      const past = make("button", { type:"button", class:"ws-keep-small" }, `${item.version} versions`);
      past.onclick = () => guard(past, () => showVersions(item));
      card.querySelector(".ws-keep-actions").prepend(past);
    }
    root.append(card);
  }
}
async function showVersions(item) {
  const answer = await api("/api/workshop/library", { action:"versions", item_id:item.item_id });
  const root = $("#ws-user-library");
  const box = make("div", { class:"ws-note", id:"ws-versions" });
  box.append(make("strong", {}, `${item.name}: every version saved`));
  for (const version of answer.versions || []) {
    const row = make("button", { type:"button", class:"ws-card ws-history-step" });
    row.append(make("strong", {}, `Version ${version.version}${version.current ? " (the one in use)" : ""}`),
               make("small", {}, new Date(version.saved_at).toLocaleString()));
    row.onclick = () => guard(row, async () => {
      const got = await api("/api/workshop/library", { action:"open_version", item_id:item.item_id, version:version.version });
      say(`Version ${version.version} of ${item.name}, saved ${new Date(got.version.saved_at).toLocaleString()}. `
        + `Its recipe is ${JSON.stringify(got.version.payload).slice(0, 200)}…`);
    });
    box.append(row);
  }
  $("#ws-versions")?.remove();
  root.prepend(box);
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
function resetInspectionView() {
  clearPlayback(); workspace.inspecting++;
  bench.clip.enabled=false; $("#ws-clip-enabled").checked=false;renderer.clippingPlanes=[];
  showForceAt(null); if(build.placing)stopPlacing();clearGhost();
  view="skin";pressView(view);
}
function openComponent(partName) {
  const part = (chosen()?.parts || []).find(p=>p.name===partName); if(!part)return;
  document.querySelector('.ws-workspace-tabs button[data-mode="build"]')?.click();
  resetInspectionView();bench.libraryInspection=null;
  $("#ws-component-editor").querySelectorAll("input,select,button").forEach(el=>el.disabled=false);
  bench.selectedPart=partName;bench.isolated=partName;
  const suggested=$("#ws-component-name");
  if(suggested && !suggested.dataset.edited)suggested.value=`${bench.kind} ${partName}`;
  show(); requestAnimationFrame(()=>{resize();show();});
}
function showWholeProduct() {
  workspace.inspecting++;bench.libraryInspection=null;bench.isolated=null;
  $("#ws-component-editor").querySelectorAll("input,select,button").forEach(el=>el.disabled=false);
  show();renderProductCatalog();updateInspector();
}
async function inspectLibraryComponent(itemId) {
  document.querySelector('.ws-workspace-tabs button[data-mode="build"]')?.click();
  resetInspectionView();const request=workspace.inspecting,revision=bench.revision;
  const answer=await api("/api/workshop/library",{action:"inspect_component",item_id:itemId});
  if(request!==workspace.inspecting || revision!==bench.revision)return;
  bench.libraryInspection=answer;bench.isolated=null;
  show();requestAnimationFrame(()=>{resize();show();});
  say(`Inspecting ${answer.library_item.name}. Your product has not changed.`);
}
async function copyComponent(partName, label) {
  if (!chosen()) throw new Error("Open a product first.");
  const revision=bench.revision,name=`${bench.kind} ${label}`;
  const answer=await api("/api/workshop/library",{action:"save_component",...candidateBody(),part_name:partName,name});
  bench.personalLibrary=answer.personal_library || bench.personalLibrary;
  bench.pricebook=answer.pricebook || bench.pricebook;renderUserLibrary();
  if(revision===bench.revision)openComponent(partName);
  say(`Copied ${name} into My library. Showing the component on its own.`);
}
function frameRenderedGeometry() {
  group.updateMatrixWorld(true);
  const bounds=new THREE.Box3().setFromObject(group);
  if(bounds.isEmpty())return;
  bounds.getCenter(target);reach=Math.max(.001,bounds.getSize(new THREE.Vector3()).length()/2);
  grid.position.y=bounds.min.y-reach*.06;
}
function updateInspector() {
  const root=$("#ws-view-context");if(!root)return;
  const saved=bench.libraryInspection,part=saved?.component_preview?.parts?.[0] || isolatedPart();
  $("#ws-inspector-back").hidden=!part;$("#ws-inspector-use").hidden=!saved;
  $("#ws-inspector-use").disabled=!bench.selectedPart;
  $("#ws-inspector-use").textContent=bench.selectedPart ? `Replace ${bench.selectedPart} with this copy` : "Select a product part to replace first";
  root.dataset.mode=part ? "component" : workspace.mode;
  $("#ws-view-title").textContent=part ? saved?.library_item.name || part.name : workspace.mode==="test" ? benchDefinition()?.name || "Simulation workspace" : chosen()?.purpose || "Product";
  $("#ws-view-description").textContent=part ? `${part.material} · ${part.size_m.map(v=>(v*1000).toFixed(1)).join(" × ")} mm · ${saved ? "Read-only saved component. Product unchanged." : "This component only. Edits apply to the product."} Drag to orbit; scroll to zoom.`
    : workspace.mode==="test" ? workspace.setup?.summary || "Choose a situation. Inspect its setup, then run the physics." : "Drag to orbit · scroll to zoom · click a part to select it.";
}
function scheduleSetup(delay=250) {
  clearTimeout(workspace.timer);const sequence=++workspace.sequence;
  if(workspace.mode!=="test" || !chosen() || !benchDefinition())return;
  workspace.timer=setTimeout(()=>previewSetup(sequence),delay);
}
async function previewSetup(sequence) {
  if(sequence!==workspace.sequence || workspace.mode!=="test")return;
  const revision=bench.revision,test=bench.selectedBenchTest;
  const current=()=>sequence===workspace.sequence && revision===bench.revision && test===bench.selectedBenchTest && workspace.mode==="test";
  const status=make("p",{id:"ws-setup-status",role:"status"},"Preparing the test scene…");
  status.dataset.state="preparing";$("#ws-simulation-feedback").replaceChildren(status);
  try {
    const config=benchConfig();
    const answer=await api("/api/workshop/plan",{...candidateBody(),bench_preview:{test,config}});
    if(!current())return;
    const setup=answer.bench_preview;
    if(!setup?.frames?.[0]?.bodies?.length)throw new Error("No visible setup returned.");
    workspace.setup=setup;bench.playback=null;bench.playbackPlaying=false;bench.playbackIndex=0;
    view="physics";pressView(view);drawPlayback();frameSimulation(setup);updateInspector();
    $("#ws-playback").hidden=true;
    status.dataset.state="ready";status.textContent=`Setup ready · ${setup.native_verified ? "native geometry" : "compiled rigid geometry"} · physics has not run. ${setup.summary}`;
  }catch(error){
    if(!current())return;
    workspace.setup=null;stage.dataset.phase="unavailable";
    status.dataset.state="error";status.textContent=`Cannot prepare this test: ${error.message}`;
    view="skin";pressView(view);show(false);
  }
}
addEventListener("banjo-workshop-mode",event=>{
  workspace.mode=event.detail;workspace.sequence++;benchTestRequest++;clearTimeout(workspace.timer);
  showStep(workspace.mode);
  if(workspace.mode==="test") {
    workspace.inspecting++;bench.libraryInspection=null;bench.isolated=null;
    bench.clip.enabled=false;$("#ws-clip-enabled").checked=false;renderer.clippingPlanes=[];
    showForceAt(null);if(build.placing)stopPlacing();clearGhost();
    if(bench.playback){view="physics";drawPlayback();frameSimulation(bench.playback);}else{view="skin";show();scheduleSetup(0);}
  }else {bench.playbackPlaying=false;workspace.setup=null;if(view==="physics"){view="skin";pressView(view);}if(chosen())show();}
  updateInspector();requestAnimationFrame(()=>{resize();if(bench.playback && workspace.mode==="test")frameSimulation(bench.playback);else frameCandidate();});
});
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
      } else if (bench.isolated || bench.libraryInspection) { showWholeProduct(); }
      else { bench.expandedProduct = expanded ? null : option.value; catalogSignature = null; renderProductCatalog(); }
    });
    entry.append(card);
    if (expanded) entry.append(productParts(candidate));
    root.append(entry);
  }
}
function renderRack() {
  const root = $("#ws-rack"); if (!root) return;
  const rows = (bench.rack && bench.rack.materials) || [];
  root.replaceChildren();
  if (!rows.length) { root.append(make("p", { class:"ws-feedback-count" }, "The rack has not been read yet.")); return; }
  for (const row of rows) {
    const label = make("label", { class:"ws-field" }, row.material);
    const input = make("input", { type:"number", min:"0", max:"100000", step:"0.1", value:String(row.mass_kg) });
    if (worldId) { input.disabled = true; input.title = "Game stock comes from the world and Market"; }
    input.dataset.material = row.material;
    input.addEventListener("change", () => guard(input, async () => {
      const mass = input.valueAsNumber;
      if (!Number.isFinite(mass) || mass < 0) throw new Error("Enter a mass in kilograms, zero or more.");
      const answer = await api("/api/workshop/library", { action:"set_rack", material:row.material, mass_kg:mass });
      bench.rack = answer.rack; renderRack(); reprobe();
      say(`The rack holds ${mass} kg of ${row.material}.`);
    }));
    label.append(input); root.append(label);
  }
}
function renderBenchReadouts() { renderHeldTo(); renderRackStrip(); }
function renderBom(candidate) {
  const root = $("#ws-bom"); root.replaceChildren(); const bom = candidate.mechanical_model !== "rigid" && ["matter", "collision", "relations"].includes(view) && bench.matterBom ? bench.matterBom : candidate.bom;
  if (!bom) { root.append(make("p", { class:"ws-feedback-count" }, "No material estimate.")); return; }
  // What it takes, what the rack holds, and what is short. A design is drawn,
  // measured and tested whatever the rack has; only making it is refused.
  const needs = candidate.needs, byMaterial = {};
  for (const row of (needs && needs.materials) || []) byMaterial[row.material] = row;
  const table = make("table", { class:"ws-bom-table" });
  const head = make("tr");
  for (const label of ["material", "it takes", "the rack", "short"]) head.append(make("th", {}, label));
  table.append(head);
  for (const row of bom.materials || []) {
    const have = byMaterial[row.material], missing = have && have.short_kg > 0;
    const tr = make("tr");
    tr.append(make("td", {}, row.material), make("td", {}, `${row.mass_kg} kg`),
      make("td", {}, have ? `${have.held_kg} kg` : "—"),
      make("td", { class: missing ? "ws-short" : "" }, missing ? `${have.short_kg} kg` : "—"));
    table.append(tr);
  }
  root.append(table);
  if (needs) {
    root.append(make("p", { class: needs.enough ? "ws-bom-total" : "ws-short" }, needs.says));
    if (!needs.enough) root.append(make("p", { class:"ws-feedback-count" },
      "Keep designing, measuring and testing it. It cannot be made or placed until the rack covers it."));
  }
  root.append(make("p", { class:"ws-bom-total" }, `Material cost: ${bom.material_cost} credits`), make("p", { class:"ws-feedback-count" }, bom.basis));
  renderBenchReadouts();
}
function renderIsolation() {
  const bar = $("#ws-isolation"); if (!bar) return;
  const alone = isolatedPart();
  bar.hidden = !alone;
  if (alone) $("#ws-isolation-note").textContent = `Working on ${alone.name} on its own.`;
  $("#ws-show-whole").textContent = `Show the whole ${bench.kind.replace("-", " ")}`;
  // Matter, collision, relations and physics measure the assembled product.
  document.querySelectorAll(".ws-viewbar button[data-view]").forEach((button) => {
    const whole = !ISOLATING_VIEWS.includes(button.dataset.view);
    button.disabled = Boolean(bench.isolated || bench.libraryInspection) && whole;
    button.title = button.disabled ? "This view measures the whole product. Show it to use this view." : "";
  });
}
function renderSelected() {
  const part = bench.libraryInspection ? null : selectedPart(), status = $("#ws-selected-part"), material = $("#ws-part-material");
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
  const alone = bench.libraryInspection?.component_preview?.parts?.[0] || isolatedPart();
  for (const id of ["#ws-buildability", "#ws-measurement-basis"]) { const box = $(id); if (box) box.hidden = Boolean(alone); }
  if (alone) {
    const mm = alone.size_m.map((v) => (v * 1000).toFixed(0));
    $("#ws-name").textContent = bench.libraryInspection?.library_item.name || alone.name;
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
  if (!bench.inventorySelection) { clearGroup(); balance.visible = false; support.visible = false; stage.dataset.showing = "empty"; updateLabSelection(); return; }
  // The buildability panel is hidden while one component is alone on screen;
  // do not pay for an analysis of the whole product that nobody can read.
  if (chosen() && !bench.isolated && !bench.libraryInspection && workspace.mode!=="test") scheduleBuildability();
  if ($("#ws-mechanical-model") && chosen()) $("#ws-mechanical-model").value = chosen().mechanical_model === "rigid" ? "rigid" : "lattice";
  const candidate = chosen(); if (!candidate) return;
  if (bench.selectedPart && !candidate.parts.some((part) => part.name === bench.selectedPart)) bench.selectedPart = null;
  draw(candidate); if (reframe) frameCandidate();
  updateLabSelection();
  const m = currentMeasurements(candidate); headline(candidate, m);
  renderMachineBench(candidate);
  if (!bench.playback) scheduleCleanThumb();
  const parts = $("#ws-parts"); parts.replaceChildren();
  for (const part of candidate.parts) { const row = make("li"), button = make("button", { type:"button", class:"ws-part-link" }, part.name); button.onclick = () => { if (bench.isolated) { openComponent(part.name); return; } setWorkspaceMode("build"); bench.selectedPart = part.name; show(false); }; row.append(button, document.createTextNode(` · ${part.role} · ${part.material} · ${Number(candidate.mechanical_model === "rigid" ? (bench.rigid?.components.find(p => p.component === part.name)?.mass_kg ?? part.mass_kg) : (["matter", "collision", "relations"].includes(view) && bench.matterMasses ? bench.matterMasses[part.name] || 0 : part.mass_kg)).toFixed(4)} kg`)); parts.append(row); }
  renderSelected(); renderBuild(); renderBom(candidate); renderProductCatalog();
  if(bench.libraryInspection) {
    $("#ws-selected-part").textContent="Inspecting a saved component. Your product has not changed.";
    $("#ws-component-editor").querySelectorAll("input,select,button").forEach(el=>el.disabled=true);
  }
  updateInspector();
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

// ---------------------------------------------------------------------------
// What you changed, and going back
//
// Every edit came through took() and nothing kept the state before it, so a
// wrong material applied to all eight parts stayed wrong. The whole design is
// {kind, generation, candidates, selected}: small, and enough to restore
// without asking the server anything. What each step DID is worked out by
// comparing the two states rather than by every caller remembering to say.
// ---------------------------------------------------------------------------
const history = { past: [], now: null, future: [], restoring: false, max: 50 };

function designState() {
  if (!bench.candidates?.length) return null;
  return { kind: bench.kind, generation: bench.generation, selected: bench.selected,
           candidates: JSON.parse(JSON.stringify(bench.candidates)), at: Date.now() };
}

// What was done to one part, in words. A part with no override before is not
// "added" as far as a person is concerned -- what happened is that its material
// or its size was set to something.
function partDetail(before, after) {
  if (after === undefined) return "put back as it was";
  const from = before || {};
  const fields = [...new Set([...Object.keys(from), ...Object.keys(after)])]
    .filter(k => JSON.stringify(from[k]) !== JSON.stringify(after[k]));
  if (!fields.length) return "changed";
  if (fields.some(k => after[k] !== null && typeof after[k] === "object")) return "redrawn";
  return fields.map(k => from[k] === undefined ? `${k} set to ${after[k]}`
    : after[k] === undefined ? `${k} cleared` : `${k} ${from[k]} → ${after[k]}`).join(", ");
}

// A sentence for one step, from the two states around it. Names of parts, not
// counts, while there are few enough of them to read.
function whatChanged(was, now) {
  if (!was) return "opened";
  if (was.kind !== now.kind) return `opened a ${now.kind}`;
  const a = was.candidates[was.selected] || {}, b = now.candidates[now.selected] || {};
  if (a.design_id !== b.design_id) return `opened ${b.design_id}`;
  const said = [];
  const oldParts = a.component_overrides || {}, newParts = b.component_overrides || {};
  // Grouped by WHAT was done, not by which part it was done to: applying one
  // material to every part is one thing a person did, and eight lines saying
  // "leg-1 added; leg-2 added" is not what they would call it.
  const byDetail = new Map();
  for (const name of new Set([...Object.keys(oldParts), ...Object.keys(newParts)])) {
    const before = oldParts[name], after = newParts[name];
    if (JSON.stringify(before) === JSON.stringify(after)) continue;
    const detail = partDetail(before, after);
    if (!byDetail.has(detail)) byDetail.set(detail, []);
    byDetail.get(detail).push(name);
  }
  for (const [detail, names] of byDetail) {
    said.push(names.length > 2 ? `${names.length} parts: ${detail}` : `${names.join(" and ")}: ${detail}`);
  }
  for (const key of new Set([...Object.keys(a.parameters || {}), ...Object.keys(b.parameters || {})])) {
    const before = (a.parameters || {})[key], after = (b.parameters || {})[key];
    if (JSON.stringify(before) !== JSON.stringify(after)) said.push(`${key} ${before ?? "—"} → ${after ?? "—"}`);
  }
  if (was.selected !== now.selected) said.push(`picked variant ${now.selected + 1}`);
  if (!said.length) return "redrawn, with nothing of the design changed";
  return said.length > 4 ? `${said.length} things changed: ${said.slice(0, 3).join("; ")}…` : said.join("; ");
}

function remember(next) {
  if (history.restoring || !next) return;
  if (history.now) {
    history.past.push({ ...history.now, said: whatChanged(history.past.at(-1) || null, history.now) });
    if (history.past.length > history.max) history.past.shift();
  }
  history.now = next;
  history.future.length = 0;
  renderHistory();
}

function stepHistory(way) {
  const from = way < 0 ? history.past : history.future, to = way < 0 ? history.future : history.past;
  const going = from.pop();
  if (!going || !history.now) return;
  to.push(history.now);
  history.now = going;
  history.restoring = true;
  try {
    took({ kind: going.kind, generation: going.generation, candidates: going.candidates });
    bench.selected = Math.min(going.selected, going.candidates.length - 1);
    show();
  } finally { history.restoring = false; }
  renderHistory();
}

function renderHistory() {
  const root = $("#ws-history"); if (!root) return;
  const undo = $("#ws-undo"), redo = $("#ws-redo");
  if (undo) undo.disabled = !history.past.length;
  if (redo) redo.disabled = !history.future.length;
  root.replaceChildren();
  if (!history.past.length) {
    root.append(make("p", { class:"ws-feedback-count" },
      "Nothing changed yet this session. Every edit will be listed here, newest first, and Undo takes the last one back."));
    return;
  }
  const said = whatChanged(history.past.at(-1), history.now);
  root.append(make("p", { class:"ws-history-now" }, `Now: ${said}`));
  for (let i = history.past.length - 1; i >= 0; i--) {
    const step = history.past[i], when = new Date(step.at);
    const row = make("button", { type:"button", class:"ws-card ws-history-step", "data-step":String(i) });
    row.append(make("strong", {}, step.said || "opened"),
               make("small", {}, when.toLocaleTimeString()));
    row.onclick = () => { while (history.past.length > i + 1) stepHistory(-1); stepHistory(-1); };
    root.append(row);
  }
}

function took(answer, keepPart = null) {
  if (answer.clientRequest != null && answer.clientRequest !== candidateRequest) return false;
  workspace.inspecting++;bench.libraryInspection=null;
  $("#ws-component-editor").querySelectorAll("input,select,button").forEach(el=>el.disabled=false);
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
  remember(designState());
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
  // As the camera stands NOW, not as it stood at the last frame. lookAt sets
  // the camera's rotation and leaves matrixWorldInverse -- which is what
  // project() uses -- to be rebuilt by the next render. So a point of view
  // clicked and read in the same turn answered for the PREVIOUS point of view
  // until a frame happened to land in between: green on a machine drawing at
  // 60 fps, red on a runner drawing when it can.
  camera.updateMatrixWorld();
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
  if (shownParts(candidate).length !== candidate.parts.length) return;   // one component alone has no joints to show
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
  if (bench.isolated) { const keep = bench.selectedPart; showWholeProduct(); bench.selectedPart = keep; }
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
    if (bench.isolated || bench.libraryInspection) showWholeProduct(); // a part goes against the product, not against one piece of it
    // A click has to land on a face, and only the solid view has faces: a wire
    // edge belongs to two of them.
    view = "skin"; pressView("skin"); show(false);
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
  document.querySelectorAll(".ws-viewbar button[data-view]").forEach((item) => item.setAttribute("aria-pressed", String(item.dataset.view === name)));
}
// Only the buttons that say how to DRAW it. This ran at module load over every
// button in the bar, and installBench had already put the points of view there
// -- so clicking "Top" ran this handler with dataset.view undefined, set the
// representation to undefined and moved no camera at all. The owner: "what
// does x y z do, I don't see it changing anything." Nothing. It was this.
document.querySelectorAll(".ws-viewbar button[data-view]").forEach((button) => {
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
  if (answer.design && bench.inventorySelection) {
    bench.inventorySelection = {id:answer.design.design_id, source:"saved", name:label};
    const url = new URL(location.href);
    for (const key of ["carry", "library"]) url.searchParams.delete(key);
    url.searchParams.set("design", answer.design.design_id);
    window.history.replaceState(null, "", url); refreshNavigation(url.searchParams.get("tab") || "lab");
    $("#ws-screen-status").textContent = label;
  }
});
$("#ws-save-feedback").onclick = (event) => guard(event.currentTarget, async () => {
  const answer = await api("/api/workshop/feedback", { ...candidateBody(), rating:$("#ws-rating").value || null, note:$("#ws-note").value.trim(), selected:true });
  $("#ws-note").value = ""; $("#ws-rating").value = ""; $("#ws-feedback-count").textContent = `${answer.kept} feedback records kept`;
});

function resize() {
  const rect = stage.getBoundingClientRect(); if (!rect.width || !rect.height) return;
  const changed=Math.abs(camera.aspect-rect.width/rect.height)>0.001;
  renderer.setSize(rect.width, rect.height, false); camera.aspect=rect.width/rect.height;camera.updateProjectionMatrix();
  if(changed)frameCandidate();else placeCamera();
}
new ResizeObserver(resize).observe(stage); addEventListener("resize", resize);
function frame(now) {advancePlayback(now);followMatter(now);renderer.render(scene,camera);requestAnimationFrame(frame);}
stage.visibleGeometry = () => {
  group.updateMatrixWorld(true);camera.updateMatrixWorld(true);
  const b=new THREE.Box3().setFromObject(group),r=stage.getBoundingClientRect();
  if(b.isEmpty())return null;
  const points=[];for(const x of [b.min.x,b.max.x])for(const y of [b.min.y,b.max.y])for(const z of [b.min.z,b.max.z]) {
    const v=new THREE.Vector3(x,y,z).project(camera);points.push([r.left+(v.x+1)*r.width/2,r.top+(1-v.y)*r.height/2,v.z]);
  }
  return {points,meshes:group.children.filter(c=>c.isMesh || c.isLineSegments).length,clipped:renderer.clippingPlanes.length};
};

async function start() {
  const params = new URLSearchParams(location.search);
  const wantSaved = params.get("design"), wantLibrary = params.get("library");
  // ?tab=skills&technique=burning-lime opens the tree on that rung. The
  // world page's "Next: ..." line uses it.
  const wantTab = (params.get("tab") || "").trim();
  const wantTechnique = (params.get("technique") || "").trim();
  // ?carry=<item id>: a thing dragged out of the bag and dropped on the
  // Workshop. It opens on that thing's bench, which is what the owner meant
  // by "take you into the workshop where you can modify it".
  const wantCarried = (params.get("carry") || "").trim();
  // Load the existing catalogs, never their default/remembered geometry.
  // Only an explicitly selected item still carried by this guest opens Lab.
  const answer = await api("/api/workshop/open", {kind:"table"});
  const picker = $("#ws-archetype"); picker.replaceChildren();
  for (const made of answer.assemblies) { const option = make("option", { value:made.assembly }, made.assembly.replace("-", " ")); option.title = made.about; picker.append(option); }
  picker.value = answer.kind; renderProductCatalog();
  bench.families = answer.families || []; savedDesigns(answer.saved_designs || []); bench.personalLibrary = answer.personal_library || [];
  bench.pricebook = answer.pricebook || null; bench.rack = answer.rack || null; bench.benchTests = answer.bench_tests || []; bench.benchPresets = answer.bench_presets || []; bench.session = answer.session || null; renderUserLibrary(); renderRack(); renderBuildChoices(); clearLab();
  if (wantCarried) await openTheCarriedThing(wantCarried);
  else if (wantSaved || wantLibrary) await openInventoryDesign(wantSaved || wantLibrary, wantSaved ? "saved" : "library");
  if (wantTechnique && (!wantTab || wantTab === "skills")) openTheTreeAt(wantTechnique);
  else showTab(wantTab || (wantCarried || wantSaved || wantLibrary ? "lab" : WORKSHOP_OPENS_ON));
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
