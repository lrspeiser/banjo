import * as THREE from './three.module.js';
import {mergeFrame, family, materialColor, heatTint, focusPoint, stationPoint, describeTime, beamSegments, lensOutline, clearWireRoute, contactCircuitDiagram, PLACEMENT_GRID, snapGroundPoint, workingAlignment, wheelAlignment, thermalCells, draggedKnobValue, pieceToolbarPosition, springCoilPoints} from './machine-view.mjs';
import {anonymousSave, validVisitor, returnURL} from './anonymous-profile.mjs';
import {ProfileSync, mergeProfiles} from './profile-sync.mjs';
import {renderLevelCards,createLevelMoreMenu} from './level-library.mjs';
import {renderDesignGallery} from './design-gallery.mjs';
import {levelIntroduction} from './level-intro.mjs';
import {sitePath} from './site-paths.mjs';

const APP_BASE = document.documentElement.dataset.banjoBase || '';
const TEST_BUILD = document.documentElement.dataset.banjoEnvironment === 'test';
const appPath = path => sitePath(APP_BASE, path);
const SHARE_SITE = TEST_BUILD ? location.origin + APP_BASE : 'https://banjo.is';

// The machine page. It asks the server to build a declaration, then shows
// what the engine measures, frame by frame. It never moves a body itself.
const $ = id => document.getElementById(id);
const view = $('view');
let introduction=null;
function positionLevelIntroduction(){
  const dialog=$('level-intro');if(!dialog.open)return;
  const rect=view.getBoundingClientRect(),card=dialog.getBoundingClientRect();
  const x=Math.max(card.width/2+12,Math.min(innerWidth-card.width/2-12,rect.left+rect.width/2));
  const y=Math.max(card.height/2+12,Math.min(innerHeight-card.height/2-12,rect.top+rect.height/2));
  dialog.style.left=x+'px';dialog.style.top=y+'px';
}
function showLevelIntroduction(){
  if(!introduction||level?.free)return;
  for(const key of ['title','place','works','goal'])$('level-intro-'+key).textContent=introduction[key];
  if(!$('level-intro').open)$('level-intro').showModal();
  positionLevelIntroduction();
}
function closeLevelIntroduction(){if($('level-intro').open)$('level-intro').close();}
$('level-intro').addEventListener('close',()=>view.focus({preventScroll:true}));
$('level-instructions').addEventListener('click',showLevelIntroduction);
const renderer = new THREE.WebGLRenderer({antialias: true});
// Advertise the scene as a click target to touch browsers. Otherwise their
// tap adjustment can redirect a nearby 3D socket tap to a camera button.
// Pointer handlers below perform the action once; this listener is inert.
renderer.domElement.addEventListener('click',()=>{});
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
view.prepend(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x11222d);
const ambient = new THREE.HemisphereLight(0xdfefff, 0x2a3a2a, 1.1);
scene.add(ambient);
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(4, 8, 5);
scene.add(sun);
// Shadows from the key light: where the machine has a sun, the shade its
// parts cast is where the engine's sunlight does not reach (drawn, not
// measured: the panel readings are the engine's).
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, {left: -5, right: 5, top: 5, bottom: -5, near: .5, far: 40});
sun.shadow.bias = -.0005; sun.shadow.normalBias = .02;
// The machine's sun itself, low or high in the sky where it stands.
const sunDisc = new THREE.Mesh(new THREE.SphereGeometry(.9, 24, 16), new THREE.MeshBasicMaterial({color: 0xffe9a0, fog: false}));
sunDisc.visible = false;
scene.add(sunDisc);
const ground = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), new THREE.MeshStandardMaterial({color: 0x2b3a32, roughness: 1}));
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
scene.add(ground);
const grid = new THREE.Group();
const fineGrid = new THREE.GridHelper(PLACEMENT_GRID.fine_size_m,PLACEMENT_GRID.fine_size_m/PLACEMENT_GRID.step_m,0x71957b,0x71957b);
fineGrid.material.transparent=true; fineGrid.material.opacity=.18; fineGrid.material.depthWrite=false;
fineGrid.material.onBeforeCompile=shader=>{
  shader.vertexShader='varying vec2 gridXZ;\n'+shader.vertexShader;
  shader.vertexShader=shader.vertexShader.replace('#include <begin_vertex>','#include <begin_vertex>\ngridXZ=position.xz;');
  shader.fragmentShader='varying vec2 gridXZ;\n'+shader.fragmentShader;
  shader.fragmentShader=shader.fragmentShader.replace('#include <opaque_fragment>',
    'diffuseColor.a*=1.0-smoothstep(3.0,5.0,max(abs(gridXZ.x),abs(gridXZ.y)));\n#include <opaque_fragment>');
};
const majorGrid = new THREE.GridHelper(PLACEMENT_GRID.size_m,PLACEMENT_GRID.size_m/PLACEMENT_GRID.major_step_m,0x76947e,0x526e5b);
majorGrid.material.transparent=true; majorGrid.material.opacity=.65; majorGrid.material.depthWrite=false;
fineGrid.position.y=.0005; majorGrid.position.y=.001;
grid.add(fineGrid,majorGrid);
scene.add(grid);
let gridSnapEnabled=true;
let objectSnapEnabled=true;
const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 200);
const target = new THREE.Vector3(1, 0.4, 0), goal = target.clone();
let azimuth = -0.55, elevation = 0.42, distance = 6.5;

let spec = null, machine = null, session = null, world = {seq: 0, t: 0, bodies: new Map()};
const airflowGroup=new THREE.Group(); scene.add(airflowGroup);
function drawAirflows(fields=machine?.airflows||[]){
  for(const child of [...airflowGroup.children]){airflowGroup.remove(child);child.traverse(o=>{o.geometry?.dispose();if(o.material)o.material.dispose();});}
  for(const air of fields){
    const center=new THREE.Vector3(...air.center_m),size=new THREE.Vector3(...air.size_m);
    const box=new THREE.Box3(center.clone().sub(size.clone().multiplyScalar(.5)),center.clone().add(size.clone().multiplyScalar(.5)));
    const outline=new THREE.Box3Helper(box,0x75cddd);outline.material.transparent=true;outline.material.opacity=.25;airflowGroup.add(outline);
    const velocity=new THREE.Vector3(...air.velocity_m_s);if(velocity.length()<.001)continue;
    for(const y of [.3,.8,1.3]) for(const side of [-.25,.25]){
      const at=center.clone();at.y=box.min.y+y;at.z+=side*size.z;
      airflowGroup.add(new THREE.ArrowHelper(velocity.clone().normalize(),at,Math.min(.5,size.x*.3),0x75cddd,.1,.05));
    }
  }
}
window.machineAirflowState=()=>({fields:machine?.airflows||[],arrows:airflowGroup.children.filter(c=>c.type==='ArrowHelper').length,loads:readouts.airflow||[]});
let playing = false, follow = true, readouts = {}, polling = 0, history = [], undo = [], lastFrame = null;
let switchDragging = null, switchPullQueue = Promise.resolve(), switchTouchGesture=false, playPending=null;
const meshes = new Map(), wires = [];
function disposeBodyGeometry(body){body.traverse(object=>object.geometry?.dispose());}
const materials = new Map();

function material(hex, kind) {
  const key = hex + ':' + kind;
  if (!materials.has(key)) materials.set(key, new THREE.MeshStandardMaterial(kind === 'glass' || kind === 'ice'
    ? {color: hex, roughness: .1, metalness: 0, transparent: true, opacity: .55}
    : {color: hex, roughness: kind === 'iron' || kind === 'aluminum' ? .45 : .8, metalness: kind === 'iron' || kind === 'aluminum' ? .5 : .02}));
  return materials.get(key);
}

const previewOwner = crypto.randomUUID();
let previewEpoch = 0;
function api(body) {
  if(body.op==='level_open'||body.op==='close'||body.op==='play'&&body.running)previewEpoch++;
  return fetch(appPath('/api/machine'), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...body,preview_owner:previewOwner,preview_epoch:previewEpoch})})
    .then(async r => {
      if (r.status === 401) { location.href = '/login'; throw Error('Log in first'); }
      const data = await r.json().catch(() => ({ok: false, error: 'The server answered with something that is not JSON'}));
      if (!r.ok || data.ok === false) { const e = Error(data.error || 'Request failed'); e.data = data; e.status = r.status; throw e; }
      return data;
    });
}

// ---- meshes: one per body, drawn from the engine's own record --------------
const stripeLook = new THREE.MeshStandardMaterial({color: 0xf1d38a, roughness: .7, metalness: 0});

function makeMesh(b) {
  const hex = materialColor(b.material, b.color_rgba);
  const look = () => material(hex, b.material).clone();
  let mesh;
  if (b.shape === 'sphere') mesh = new THREE.Mesh(new THREE.SphereGeometry(b.dimensions_m[0] / 2, 28, 18), look());
  else if (b.shape === 'cone') mesh = new THREE.Mesh(new THREE.ConeGeometry(b.dimensions_m[0] / 2, b.dimensions_m[1], 24), look());
  else if (b.shape === 'compound' && Array.isArray(b.rigid_parts_local)) {
    // An exact rigid body made of boxes and cylinders, each about its centre
    // of mass, as the engine sends it.
    mesh = new THREE.Group();
    for (const part of b.rigid_parts_local) {
      const piece = new THREE.Mesh(part.shape === 'cylinder'
        ? new THREE.CylinderGeometry(part.dimensions_m[0] / 2, part.dimensions_m[0] / 2, part.dimensions_m[1], 20)
        : new THREE.BoxGeometry(...part.dimensions_m), look());
      piece.position.set(...part.center_local_m);
      const r = part.rotation_wxyz;
      piece.quaternion.set(r[1], r[2], r[3], r[0]);
      if (part.shape === 'cylinder') {
        // A pale stripe from the hub to the rim, through both faces, so a
        // turning wheel shows how far it has turned.
        const radius = part.dimensions_m[0] / 2;
        const stripe = new THREE.Mesh(new THREE.BoxGeometry(.85 * radius, part.dimensions_m[1] * 1.04, .14 * radius), stripeLook);
        stripe.position.x = .45 * radius;
        piece.add(stripe);
      }
      mesh.add(piece);
    }
    mesh.material = mesh.children[0].material;
  }
  else if (b.shape === 'hull' && b.cells_local_m && b.cells_local_m.length) {
    const cell = machine ? machine.cell_m : .02;
    mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(cell, cell, cell), look(), b.cells_local_m.length);
    const m = new THREE.Matrix4();
    b.cells_local_m.forEach((c, i) => mesh.setMatrixAt(i, m.makeTranslation(c[0], c[1], c[2])));
  } else mesh = new THREE.Mesh(new THREE.BoxGeometry(...b.dimensions_m), look());
  mesh.userData = {revision: b.revision, cells: b.cells_local_m ? b.cells_local_m.length : 0, base: hex};
  mesh.traverse(o => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
  scene.add(mesh);
  return mesh;
}

function place(mesh, b) {
  mesh.position.set(...b.position_m);
  const q = b.orientation_wxyz;
  mesh.quaternion.set(q[1], q[2], q[3], q[0]);
}

function syncMeshes(changed) {
  for (const [name, mesh] of meshes) if (!world.bodies.has(name)) { scene.remove(mesh); disposeBodyGeometry(mesh); meshes.delete(name); }
  for (const b of changed) {
    let mesh = meshes.get(b.name);
    const cells = b.cells_local_m ? b.cells_local_m.length : 0;
    if (mesh && (mesh.userData.revision !== b.revision || mesh.userData.cells !== cells)) {
      scene.remove(mesh); disposeBodyGeometry(mesh); meshes.delete(b.name); mesh = null;
    }
    if (!mesh) { mesh = makeMesh(b); meshes.set(b.name, mesh); }
    place(mesh, b);
  }
  const heat = new Map((readouts.heat || []).map(h => [h.name, h.temperature_k]));
  $('heat-legend').hidden = !(readouts.heat || []).some(h => h.temperature_k > 320);
  for (const [name, mesh] of meshes) {
    const k = heat.get(name) ?? heat.get(family(name));
    mesh.material.color.setHex(heatTint(mesh.userData.base, k));
    mesh.material.emissive?.setHex(k > 600 ? heatTint(0x000000, k) & 0x7f3f1f : 0);
  }
}

// Explicit terminal wires and prepared contact/coil circuits share visible
// floor routes. A contact circuit includes its supply, switched and return
// leads; its mechanical gap is not a wire. Other legacy loads retain their
// schematic source/load path. Current and contact state come from the engine.
let wireObstacleSeq=null,wireObstacleFrame=-2,wireObstacles=[];
function wireRoute(a,b,lane=0) {
  const frame=flowGroup.visible?flowIndex:-1;
  if(wireObstacleSeq!==world||wireObstacleFrame!==frame) {
    wireObstacleSeq=world;wireObstacleFrame=frame;wireObstacles=[];
    for(const [name,liveMesh] of meshes) {
      const mesh=frame>=0&&flowMechanismMeshes.get(name)?.visible?flowMechanismMeshes.get(name):liveMesh;
      mesh.updateMatrixWorld(true);
      for(const solid of mesh.isGroup?mesh.children:[mesh]) {
        const box=new THREE.Box3().setFromObject(solid);
        if(!box.isEmpty())wireObstacles.push({min:box.min.toArray(),max:box.max.toArray()});
      }
    }
  }
  return clearWireRoute(a,b,lane,wireObstacles)||[];
}
function routedCurve(a, b, lane) {
  const points = wireRoute(a, b, lane).map(p => new THREE.Vector3(...p));
  // Unroutable meshes are hidden below, never drawn through an obstacle.
  if(points.length<2)return new THREE.LineCurve3(new THREE.Vector3(...a),new THREE.Vector3(...b));
  const curve = new THREE.CurvePath();
  for (let i = 1; i < points.length; i++) curve.add(new THREE.LineCurve3(points[i - 1], points[i]));
  return curve;
}
function wireColor(wire) { return wire.a.endsWith(':minus') || wire.b.endsWith(':minus') ? 0x83bbff : 0xf19076; }
const electricalStartPoses = new Map();
function terminalAt(device, key, at) {
  const part = device.terminal_parts?.[key] || device.part;
  if (ghost && (device.name === ghostName() || device.name.startsWith(ghostName()+' '))) return at;
  const start = electricalStartPoses.get(part), now = world.bodies.get(part);
  if (!start) return at; // A new ghost's body does not exist in the engine yet.
  if (!now) return null;
  const q = start.orientation_wxyz, n = now.orientation_wxyz;
  return new THREE.Vector3(...at).sub(new THREE.Vector3(...start.position_m))
    .applyQuaternion(new THREE.Quaternion(q[1],q[2],q[3],q[0]).invert())
    .applyQuaternion(new THREE.Quaternion(n[1],n[2],n[3],n[0]))
    .add(new THREE.Vector3(...now.position_m)).toArray();
}
function terminalMap(electrical) {
  return new Map((electrical?.devices || []).flatMap(d => Object.entries(d.terminals || {})
    .map(([key, at]) => [`${d.name}:${key}`,terminalAt(d,key,at)]).filter(([,at])=>at)));
}
function powerPortAt(port) {
  return port.part?terminalAt({name:'',part:port.part},'',port.at_m)
    :readouts.machines?.solar_panels?.find(p=>p.name===port.solar_panel)?.at_m||port.at_m;
}
// Enlarge conductors for visibility; preserve the relative size cue rather
// than drawing a 50-micrometre wire invisibly at world scale.
function wireDisplayRadius(wire) {
  return wire?.area_mm2 == null ? .009 : Math.max(.004,Math.min(.018,.009*Math.sqrt(wire.area_mm2/.5)));
}
function syncWires() {
  for (const w of wires) { scene.remove(w.line); w.line.geometry.dispose(); w.line.material.dispose(); }
  wires.length = 0;
  if (!machine) return;
  for (const c of machine.circuits) {
    const diagram = contactCircuitDiagram(c,machine,world.bodies);
    if (diagram) {
      for (const [lane,leg] of diagram.legs.entries()) {
        const line = new THREE.Mesh(new THREE.TubeGeometry(routedCurve(leg.a,leg.b,lane),64,.009,6,false),
          new THREE.MeshBasicMaterial({color:leg.color}));
        scene.add(line);wires.push({line,name:c.name,contactCircuit:c,leg:leg.id,lane,color:leg.color,
          route:wireRoute(leg.a,leg.b,lane)});
      }
      continue;
    }
    const battery = machine.batteries.find(b => b.name === c.battery);
    const hinge = c.switch ? machine.joints.find(j => j.name === c.switch.hinge) : null;
    const geometry = new THREE.BufferGeometry();
    const line = new THREE.Line(geometry, new THREE.LineBasicMaterial({color: 0x6b7680}));
    scene.add(line);
    const driven = c.motor ? machine.joints.find(j => j.name === c.motor.hinge) : null;
    wires.push({line, from: battery && battery.in, via: hinge && hinge.at_m,
                to: c.coil ? c.coil.heats : null, toPoint: driven && driven.at_m, name: c.name});
  }
  const terminals = terminalMap(machine.electrical);
  for (const [lane, wire] of (machine.electrical?.wires || []).entries()) {
    const a = terminals.get(wire.a), b = terminals.get(wire.b);
    if (!a || !b) continue;
    const radius=wireDisplayRadius(wire);
    const line = new THREE.Mesh(new THREE.TubeGeometry(routedCurve(a, b, lane), 64, radius, 6, false),
      new THREE.MeshBasicMaterial({color: wireColor(wire)}));
    scene.add(line); wires.push({line, terminalWire: true, name: wire.name, a:wire.a, b:wire.b, lane,
      color: wireColor(wire), radius, route: wireRoute(a, b, lane)});
  }
  const ports = new Map((machine.electrical?.power_ports || []).map(p => [p.name, p]));
  for (const cable of machine.electrical?.power_cables || []) {
    const from = ports.get(cable.a), to = ports.get(cable.b), a=from&&powerPortAt(from), b=to&&powerPortAt(to);
    if (!a || !b) continue;
    const curve = routedCurve(a,b,0);
    const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 24, .008, 6, false),
      new THREE.MeshBasicMaterial({color: 0x83bbff}));
    scene.add(tube); wires.push({line: tube, powerCable: true, panel: from.solar_panel, name: cable.name,
      fromPort:from,toPort:to,points_m:[a,b],route:wireRoute(a,b,0)});
  }
  syncPowerLabels();
  syncTerminalLabels();
  syncContactCircuits();
}

const contactCircuitRows = new Map(), contactCircuitOutlines = [];
let inspectedCircuit = null, inspectionFollow = true;
function switchDiagram(row) {
  if (!row?.device) return row && contactCircuitDiagram(row.circuit,machine,world.bodies);
  const [moving,fixed]=row.device.touch;
  if (!world.bodies.has(moving)||!world.bodies.has(fixed)) return null;
  return {moving,fixed,fixedIsStatic:Boolean(machine.parts.find(p=>p.name===fixed)?.fixed),
    contactCenters:[moving,fixed].map(name=>world.bodies.get(name).position_m)};
}
function switchReading(name,row,frame) {
  return (row.device ? frame?.devices || readouts.electrical?.devices || [] : frame?.contact_circuits || readouts.circuits || []).find(c=>c.name===name);
}
function syncContactCircuits() {
  for (const outline of contactCircuitOutlines) {scene.remove(outline);outline.geometry.dispose();outline.material.dispose();}
  contactCircuitOutlines.length=0;contactCircuitRows.clear();
  if(inspectedCircuit){follow=inspectionFollow;$('follow').setAttribute('aria-pressed',String(follow));if(!ghost)$('control-panel').append($('instrument-panel'));}
  inspectedCircuit=null;
  if($('level-done').hidden)view.append($('level-done'));
  const labels=$('contact-switch-labels');labels.replaceChildren();labels.hidden=true;
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');labels.append(svg);
  for(const text of ['Moving contact','Fixed pad']) {
    const tag=document.createElement('span');tag.textContent=text;labels.append(tag);
    const leader=document.createElementNS(svg.namespaceURI,'line');leader.setAttribute('stroke-width','1.5');svg.append(leader);
  }
  const host=$('contact-circuit-readings');host.replaceChildren();
  for (const c of machine.circuits) {
    const diagram=contactCircuitDiagram(c,machine,world.bodies);if(!diagram)continue;
    const card=document.createElement('section'), title=document.createElement('strong'), status=document.createElement('output');
    title.textContent=c.name;
    const explanation=document.createElement('p');
    explanation.textContent=`The moving metal contact presses onto ${diagram.fixedIsStatic?'the lower pad':'the other contact'}. Red wires supply power; blue is the return. The closed circuit powers the heating coil.`;
    const inspect=button('Inspect switch',()=>inspectContactCircuit(c.name),{ariaLabel:`Inspect ${c.name}`});
    card.append(title,status,explanation,inspect);host.append(card);contactCircuitRows.set(c.name,{status,circuit:c,inspect});
    for (const name of c.switch.touch) {
      const outline=new THREE.BoxHelper(meshes.get(name),0xffad66);
      outline.userData={part:name,circuit:c.name};scene.add(outline);contactCircuitOutlines.push(outline);
    }
  }
  for (const device of machine.electrical?.devices || []) {
    if (device.kind!=='switch'||!device.touch) continue;
    const card=document.createElement('section'),title=document.createElement('strong'),status=document.createElement('output');
    title.textContent=device.name.replace(/^your /,'');
    const inspect=button('Inspect switch',()=>inspectContactCircuit(device.name),{ariaLabel:`Inspect ${device.name}`});
    card.append(title,status,inspect);host.append(card);
    contactCircuitRows.set(device.name,{status,device,inspect});
    for (const name of device.touch) {
      const mesh=meshes.get(name);if(!mesh)continue;
      const outline=new THREE.BoxHelper(mesh,0xffad66);
      outline.userData={part:name,circuit:device.name};scene.add(outline);contactCircuitOutlines.push(outline);
    }
  }
  $('inspect-switch').hidden=![...contactCircuitRows.values()].some(row=>row.circuit);
  $('inspect-switch').textContent='Inspect switch';view.classList.toggle('has-contact-switch',Boolean(contactCircuitRows.size));
  showInstrumentPanel();updateContactCircuitReadings();
}
function inspectContactCircuit(name) {
  const row=contactCircuitRows.get(name);if(!row)return;
  const diagram=switchDiagram(row);if(!diagram)return;
  if(!inspectedCircuit)inspectionFollow=follow;
  inspectedCircuit=name;follow=false;$('follow').setAttribute('aria-pressed','false');
  const box=new THREE.Box3().setFromPoints(diagram.contactCenters.map(p=>new THREE.Vector3(...p))).expandByScalar(.12);
  box.getCenter(goal);target.copy(goal);
  const half=Math.min(camera.fov*Math.PI/360,Math.atan(Math.tan(camera.fov*Math.PI/360)*camera.aspect));
  distance=Math.max(.6,box.getSize(new THREE.Vector3()).length()*.6/Math.sin(half));
  azimuth=-.65;elevation=.12;
  $('inspect-switch').textContent='Back to scene';
  selectPhonePanel('controls',true);
  if(!ghost){$('control-panel').prepend($('instrument-panel'));$('control-panel').scrollTop=0;}
  else $('instrument-panel').scrollIntoView({block:'start',inline:'nearest',behavior:'instant'});
  if($('level-done').hidden)view.append($('level-done'));
  flowGroup.visible=false;freshView();updateContactCircuitReadings();
}
$('inspect-switch').addEventListener('click',()=>{
  if(inspectedCircuit){inspectedCircuit=null;follow=inspectionFollow;$('follow').setAttribute('aria-pressed',String(follow));frameCamera();$('inspect-switch').textContent='Inspect switch';if($('level-done').hidden)view.append($('level-done'));if(!ghost){$('control-panel').append($('instrument-panel'));$('control-panel').scrollTop=0;}}
  else inspectContactCircuit(contactCircuitRows.keys().next().value);
});
function updateContactCircuitReadings() {
  const frame=flowGroup.visible&&previewShown?.flow_frames?.[flowIndex];
  for(const [name,row] of contactCircuitRows) {
    row.inspect.hidden=contactCircuitRows.size===1 || inspectedCircuit===name;
    const measured=switchReading(name,row,frame);
    const state=typeof measured?.closed==='boolean'?(measured.closed?'closed':'open'):'not measured';
    const amps=Number.isFinite(measured?.current_a)?Math.abs(measured.current_a).toFixed(3):'—';
    const watts=Number.isFinite(measured?.coil_w)?measured.coil_w.toFixed(1):'—';
    row.status.textContent=(frame?'Preview · ':'Live · ')+(row.device?`Metal contact: ${state} · ${amps} A`:
      `Pressure switch: ${state} · ${amps} A · Coil: ${watts} W → ${row.circuit.coil.heats}`);
  }
  for(const outline of contactCircuitOutlines) {
    outline.update();outline.visible=!flowGroup.visible;
    const measured=switchReading(outline.userData.circuit,contactCircuitRows.get(outline.userData.circuit));
    outline.material.color.setHex(measured?.closed?0x5fe08f:0xffad66);
  }
  const diagram=inspectedCircuit&&switchDiagram(contactCircuitRows.get(inspectedCircuit));
  const labels=$('contact-switch-labels');labels.hidden=!diagram;
  if(diagram) {
    const closed=switchReading(inspectedCircuit,contactCircuitRows.get(inspectedCircuit))?.closed;
    const tags=[...labels.querySelectorAll('span')],leaders=[...labels.querySelectorAll('line')];
    tags[1].textContent=diagram.fixedIsStatic?'Fixed pad':'Other contact';
    for(const [i,name] of [diagram.moving,diagram.fixed].entries()) {
      const at=new THREE.Vector3(...world.bodies.get(name).position_m).project(camera);
      const x=(at.x+1)*view.clientWidth/2,y=(1-at.y)*view.clientHeight/2,tag=tags[i];
      const left=Math.max(8,Math.min(view.clientWidth-tag.offsetWidth-8,x-tag.offsetWidth-35));
      const top=Math.max(55,Math.min(view.clientHeight-tag.offsetHeight-8,y+(i?28:-40)));
      tag.style.left=left+'px';tag.style.top=top+'px';tag.style.color=closed?'#9ef5bd':'#ffd1a5';
      const line=leaders[i];line.setAttribute('x1',left+tag.offsetWidth);line.setAttribute('y1',top+tag.offsetHeight/2);
      line.setAttribute('x2',x);line.setAttribute('y2',y);line.setAttribute('stroke',closed?'#5fe08f':'#ffad66');
    }
  }
}
window.machineContactCircuitState=()=>({inspected:inspectedCircuit,
  circuits:[...contactCircuitRows.entries()].map(([name,row])=>({diagram:switchDiagram(row),reading:switchReading(name,row)})),
  wires:wires.filter(w=>w.contactCircuit).map(w=>({name:w.name,leg:w.leg,route:w.route,color:w.line.material.color.getHex(),visible:w.line.visible})),
  outlines:contactCircuitOutlines.map(o=>({part:o.userData.part,color:o.material.color.getHex(),visible:o.visible}))});

// Terminal clicks save the same wire placements as the existing selectors.
// Validation, current and available pieces belong to the server/engine.
const terminalLabels = new Map(), terminalPins = new THREE.Group(), terminalGhostWires = new THREE.Group();
scene.add(terminalPins, terminalGhostWires);
let terminalStart = null, terminalBusy = false, terminalStamp = '', wiringMode = false;
function setWiringMode(value) {
  wiringMode = value; $('wire-mode').setAttribute('aria-pressed', String(value));
  $('wire-mode').textContent = value ? 'Finish wiring' : 'Connect wires';
  if (!value) {
    pickedPowerPort = null;
    if (terminalStart) cancelGhost();
    powerMessage('');
  }
  positionPowerLabels(); positionTerminalLabels();
}
$('wire-mode').addEventListener('click', () => setWiringMode(!wiringMode));
function showInstrumentPanel() {
  $('instrument-panel').hidden = !powerLabels.size && !terminalLabels.size && !contactCircuitRows.size;
  $('wire-mode').hidden = !powerLabels.size && !terminalLabels.size;
}
function shownElectrical() { return ghost?.electrical || machine?.electrical || {}; }
function syncTerminalLabels() {
  const electrical = shownElectrical(), stamp = JSON.stringify(electrical.devices || []);
  if (stamp === terminalStamp) return;
  terminalStamp = stamp;
  const host = $('terminal-labels'); host.replaceChildren(); terminalLabels.clear();
  const pins = $('terminal-pins'); pins.replaceChildren();
  for (const c of [...terminalPins.children]) { terminalPins.remove(c); c.geometry.dispose(); c.material.dispose(); }
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.classList.add('power-leaders'); svg.setAttribute('aria-hidden', 'true'); pins.append(svg);
  for (const device of electrical.devices || []) {
    const card = document.createElement('section'); card.className = 'terminal-label';
    card.dataset.device=device.name;card.dataset.kind=device.kind;
    const title = document.createElement('strong'); title.textContent = device.name.replace(/^your /, '');
    const controls = document.createElement('div'); controls.className = 'terminal-buttons';
    const rows = [];
    for (const [key, at] of Object.entries(device.terminals || {})) {
      const name = `${device.name}:${key}`, text = {plus:'+', minus:'−', in:'In', out:'Out',a:'A',b:'B'}[key] || key;
      const control = button(text, () => pickTerminal(name), {ariaLabel:`Connect ${device.name} ${key}`});
      // New labels remain inert until the current tray and scene position
      // have been evaluated, including between a rebuild and its next frame.
      control.disabled = true;
      control.dataset.terminal = name; control.className = `terminal-${key}`; controls.append(control);
      const leader = document.createElementNS(svg.namespaceURI, 'line'); svg.append(leader);
      const pin = new THREE.Mesh(new THREE.SphereGeometry(.016, 12, 8), new THREE.MeshBasicMaterial({color:key === 'minus' ? 0x83bbff : 0xf19076}));
      pin.position.set(...at); terminalPins.add(pin);
      rows.push({name, at, declaredAt:at, key, device, pin, control, leader});
    }
    if (!rows.length) continue;
    const feedback=document.createElement('output'); feedback.className='contact-feedback'; feedback.style.display='block';
    card.append(title, feedback);
    if(device.touch){const inspect=button('Inspect contacts',()=>inspectContactCircuit(device.name),
      {ariaLabel:`Inspect ${device.name} contacts`});inspect.className='contact-inspect';card.append(inspect);}
    const overlay = document.createElement('section'); overlay.className='terminal-control-pin';
    overlay.append(controls); pins.append(overlay);
    let handle;
    if (device.handle) {
      handle=button(device.handle.label||'↕',()=>{}, {ariaLabel:`Drag ${device.name} handle`});
      handle.style.cssText='min-height:44px;min-width:44px;touch-action:none;cursor:ns-resize';
      handle.title=device.handle.help||'Drag down to close, up to open. The engine moves the rocker.';
      handle.addEventListener('pointerdown',e=>{
        if (!startSwitchDrag(device,e)) return;
        e.preventDefault();e.stopPropagation();pointers.set(e.pointerId,[e.clientX,e.clientY]);handle.setPointerCapture(e.pointerId);
      });
      handle.addEventListener('pointermove',e=>{moveCameraPointer(e);moveSwitchDrag(e);});
      for (const type of ['pointerup','pointercancel','lostpointercapture']) handle.addEventListener(type,e=>{
        endSwitchPointer(e);pointers.delete(e.pointerId);pinch=0;if(!pointers.size)cameraGesture=false;
      });
      overlay.append(handle);
    }
    host.append(card); terminalLabels.set(device.name, {card, overlay, controls, rows, device, feedback,handle});
  }
  showInstrumentPanel();
}
async function pickTerminal(name,fromScene=false) {
  if (!level || playing || terminalBusy || (ghost && ghost.p.piece !== 'wire')) return;
  const tray = level.tray.find(t => t.piece === 'wire');
  if (!tray || (!ghost && piecesLeft(tray) <= 0)) return;
  if (!terminalStart) {
    if (!ghost) {
      const p = {piece:'wire'};
      for (const [key, rule] of Object.entries(tray.knobs)) p[key] = knobDefault(rule);
      startGhost(p, placements.length, true);
    }
    terminalStart = name; ghost.p.a_terminal = name; ghost.p.b_terminal = '';
    renderGhostBar(); askGhost();
    powerMessage('Now choose the other terminal. Esc cancels this wire.',!fromScene); return;
  }
  if (terminalStart === name) { cancelGhost(); powerMessage(''); return; }
  const g = ghost, sourceLevel = level;
  g.p[g.rewireKey || 'b_terminal'] = name; renderGhostBar(); terminalBusy = true;
  try {
    askGhost();
    while (ghost === g && g.busy) await g.check;
    if (ghost !== g || level !== sourceLevel) return;
    if (!g.fits) { powerMessage(g.problems.join(' · ')); return; }
    if (placeGhost()) {
      await rebuildLevel(false);
      if (level === sourceLevel) powerMessage('Wire connected. Try It! to try the circuit.',!fromScene);
    }
  } catch (e) { powerMessage(e.message); }
  finally { terminalBusy = false; positionTerminalLabels(); }
}
function positionTerminalLabels() {
  syncTerminalLabels();
  if (!terminalLabels.size) return;
  const rect = renderer.domElement.getBoundingClientRect();
  const top = Math.max(8, $('clock').getBoundingClientRect().bottom - rect.top + 8);
  const bottom = Math.min(rect.height - 8, innerHeight - rect.top - 8);
  const occupied = [...view.querySelectorAll('#scene-mode, #clock, #viewer-zoom, #viewer-perspective, #piece-editor, #viewer-history, .power-pin, #piece-handles button:not([hidden])')]
    .filter(el => !el.hidden && el.style.visibility !== 'hidden' && el.offsetWidth && el.offsetHeight).map(el => {
      const r = el.getBoundingClientRect(); return {x:r.left-rect.left, y:r.top-rect.top, w:r.width, h:r.height};
    });
  occupied.push(...readoutBodyRects(rect));
  const tray = level?.tray.find(t => t.piece === 'wire');
  const editable = !playing && !terminalBusy && Boolean(tray && (ghost?.p.piece === 'wire' || (!ghost && piecesLeft(tray) > 0)));
  const snapshot=contactSnapshot(), previewTerminals=snapshot.preview?new Map((snapshot.terminals||[]).map(t=>[t.name,t.at_m])):null;
  const physical=shownElectrical().devices?.some(d=>d.kind==='socket');
  for (const {card: reading, overlay: card, controls, rows, device, feedback,handle} of terminalLabels.values()) {
    reading.hidden = false;
    controls.hidden = playing || !wiringMode;
    feedback.hidden=false;
    {
      const prefix=snapshot.preview?'Preview · ':'';
      if (device.kind==='battery') {
        const battery=snapshot.batteries.find(b=>b.name===device.battery);
        const store=machine?.batteries?.find(b=>b.name===device.battery);
        feedback.textContent=prefix+`${store?.voltage_v||0} V · `+(battery?`${battery.charge_j.toFixed(1)} J · ${Math.round(100*battery.charge_j/battery.capacity_j)}% charged`:'Charge measured on Run');
      } else if (device.kind==='bulb') {
        const bulb=snapshot.devices.find(d=>d.name===device.name);
        feedback.textContent=prefix+`${(bulb?.power_w||0).toFixed(2)} W lamp · ${Math.abs(bulb?.voltage_v||0).toFixed(1)} V / ${device.rated_voltage_v} V rated`;
      } else if(device.kind==='capacitor') {
        const measured=snapshot.devices.find(d=>d.name===device.name);
        feedback.textContent=prefix+`${device.capacitance_f} F · ${(measured?.capacitor_voltage_v||0).toFixed(2)} V · ${(measured?.stored_j||0).toFixed(2)} J · ${(measured?.current_a||0).toFixed(3)} A`;
      } else if (device.kind==='coil' || device.kind==='motor' || device.kind==='resistor') {
        const measured=snapshot.devices.find(d=>d.name===device.name);
        feedback.textContent=prefix+`${Math.abs(measured?.current_a||0).toFixed(3)} A · ${(measured?.power_w||0).toFixed(1)} W`;
        if(device.kind==='resistor')feedback.textContent=prefix+`${device.resistance_ohm} Ω · ${Math.abs(measured?.voltage_v||0).toFixed(2)} V drop · ${Math.abs(measured?.current_a||0).toFixed(3)} A`;
        if(device.kind==='coil') {
          const heat=!snapshot.preview&&readouts.heat?.find(h=>h.name===device.heats);
          feedback.textContent+=heat?` · ${heat.temperature_k.toFixed(0)} K${heat.reacting?' · burning':''}`:` → ${device.heats.replace(/^your /,'')}`;
        }
      } else if (device.kind==='socket') {
        feedback.textContent=prefix+Object.keys(device.terminals||{}).map(key=>{
          const contacts=snapshot.contacts.filter(c=>c.a===`${device.name}:${key}`||c.b===`${device.name}:${key}`);
          return `${key==='plus'?'+':'−'} ${contacts.some(c=>c.closed===true)?'closed':contacts.length?contacts.every(c=>c.closed===false)?'open':'not measured':'no pack'}`;
        }).join(' · ');
      } else if(device.kind==='switch' && device.touch) {
        const measured=snapshot.devices.find(d=>d.name===device.name);
        feedback.textContent=prefix+`Metal contacts ${measured?.closed?'closed':'open'} · ${Math.abs(measured?.current_a||0).toFixed(3)} A`;
      } else feedback.hidden=true;
    }
    if (handle) {
      handle.disabled=Boolean(ghost||pullMode||attachMode||!session);
      const measured=snapshot.devices.find(d=>d.name===device.name);
      feedback.hidden=false;feedback.textContent=(snapshot.preview?'Preview · ':'')+(measured?`${measured.closed?'Closed':'Open'} · ${Math.abs(measured.current_a||0).toFixed(3)} A`:'Drag to operate');
    }
    for (const row of rows) {
      row.at = previewTerminals?.get(row.name)||terminalAt(row.device,row.key,row.declaredAt);
      row.pin.visible = Boolean(row.at);
      if (row.at) row.pin.position.set(...row.at);
      if (physical) row.control.title=editable?'Connect this terminal':'Physical terminal: contact is measured by the engine';
    }
    const first = rows.find(row=>row.at);
    if (!first) {card.hidden=true; for (const row of rows) row.leader.style.display='none'; continue;}
    const grip=device.handle&&terminalAt({name:device.name,part:device.handle.part},'',device.handle.at_m);
    const p = new THREE.Vector3(...(grip||first.at)).project(camera);
    card.hidden = ((playing || !wiringMode) && !handle) || Math.abs(p.z) > 1 || Math.abs(p.x) > 1.4 || Math.abs(p.y) > 1.4;
    for (const row of rows) { row.leader.style.display = card.hidden ? 'none' : ''; row.control.disabled = !editable; row.control.setAttribute('aria-pressed', String(row.name === terminalStart)); }
    if (card.hidden) continue;
    const w = card.offsetWidth, h = card.offsetHeight, ax = (p.x+1)*rect.width/2, ay = (1-p.y)*rect.height/2;
    const collides = (x,y) => occupied.some(r => x < r.x+r.w+6 && x+w+6 > r.x && y < r.y+r.h+6 && y+h+6 > r.y);
    const xs = readoutSideXs(ax,w,rect.width).map(x=>Math.max(8,Math.min(rect.width-w-8,x)));
    const preferredY = Math.max(top, Math.min(bottom-h, ay-h-30));
    // Align rows so an anchor cannot leave two gaps just too short for
    // another card on a landscape phone. Leaders still point to the pins.
    const ys = [top + Math.round((preferredY-top)/(h+8))*(h+8), preferredY, top, bottom-h,
      ...occupied.flatMap(r => [r.y+r.h+8, r.y-h-8])];
    const candidates = xs.flatMap(x => ys.map(y => ({x,y}))).filter(c => c.x >= 8 && c.x+w <= rect.width-8 && c.y >= top && c.y+h <= bottom);
    const pos = candidates.find(c => !collides(c.x,c.y));
    // Large sandbox circuits can have more labels than a scene can hold.
    // Hide overflow rather than covering Run or another terminal; zoom/pan to inspect.
    if (!pos) { card.hidden = true; for (const row of rows) row.leader.style.display = 'none'; continue; }
    card.style.left = `${pos.x}px`; card.style.top = `${pos.y}px`; occupied.push({...pos,w,h});
    for (const row of rows) {
      if (controls.hidden) {row.leader.style.display='none';continue;}
      if (!row.at) {row.leader.style.display='none'; continue;}
      const pin = new THREE.Vector3(...row.at).project(camera), b = row.control.getBoundingClientRect();
      row.leader.setAttribute('x1', String((pin.x+1)*rect.width/2)); row.leader.setAttribute('y1', String((1-pin.y)*rect.height/2));
      row.leader.setAttribute('x2', String(b.left-rect.left+b.width/2)); row.leader.setAttribute('y2', String(b.bottom-rect.top));
    }
  }
}
window.machineWiringState = () => ({selected:terminalStart, busy:terminalBusy,
  wires:wires.filter(w => w.terminalWire).map(w => ({name:w.name, route:w.route, visible:w.line.visible, color:w.line.material.color.getHex()})),
  ghostWires:terminalGhostWires.children.length,
  terminals:Object.fromEntries([...terminalLabels.values()].flatMap(({rows})=>rows.filter(r=>r.at).map(r=>[r.name,r.at]))),
  powerPorts:Object.fromEntries((machine?.electrical?.power_ports||[]).map(p=>[p.name,powerPortAt(p)])),
  powerCables:wires.filter(w=>w.powerCable).map(w=>({name:w.name,points_m:w.points_m,visible:w.line.visible}))});

// Pick the actual connection point in the scene, independently of the
// optional offset buttons and precision selectors. These rings and the
// unfinished line are editing guides, not energized wires or conductors.
let socketPointer = null, socketPress = null;
const socketMarks = new Map();
const socketSvg = $('scene-sockets'), socketNS = socketSvg.namespaceURI;
const heaterAttachButton=button('Clip to cord',()=>{
  const target=level?.goal?.station?.done_when?.parted;
  const part=machine?.parts.find(p=>p.name===target);
  if(part&&ghost?.p.piece==='ignition')chooseSceneSocket({kind:'heater',data:part});
},{id:'heater-attach',ariaLabel:'Clip heater to hanging cord'});
heaterAttachButton.hidden=true;view.append(heaterAttachButton);
const socketTail = document.createElementNS(socketNS,'path');
socketTail.classList.add('wire-tail'); socketSvg.append(socketTail);
socketTail.style.display='none';
function sceneSockets() {
  const heater=ghost?.p.piece==='ignition'&&ghost.p.attachment_version===2;
  if (!level || playing || terminalBusy || powerBusy || rewiringBusy || pullMode || attachMode || switchDragging ||
      (ghost && !heater&&!['wire','power_cable'].includes(ghost.p.piece))) return [];
  const rect=renderer.domElement.getBoundingClientRect(), rows=[];
  const available=kind=>ghost?.p.piece===kind || level.tray.some(t=>t.piece===kind && piecesLeft(t)>0);
  const project=(name,at,kind,label,data)=>{
    if (!at?.every(Number.isFinite)) return;
    const p=new THREE.Vector3(...at).project(camera);
    const x=rect.left+(p.x+1)*rect.width/2,y=rect.top+(1-p.y)*rect.height/2;
    if(p.z < -1 || p.z>1 || x<rect.left+10 || x>rect.right-10 || y<$('clock').getBoundingClientRect().bottom+12 || y>rect.bottom-10)return;
    // UI actions remain authoritative where they overlap a world endpoint.
    if(document.elementFromPoint(x,y)!==renderer.domElement)return;
    rows.push({name,at,kind,label,data,x,y});
  };
  if(heater) {
    const cord=level.goal?.station?.done_when?.parted;
    for(const part of machine.parts.filter(p=>p.shape==='box'&&!p.name.startsWith(ghostName())&&(!cord||p.name===cord))) {
      project('heat:'+part.name,world.bodies.get(part.name)?.position_m||part.at_m,'heater','Clip',part);
    }
    return rows;
  }
  if(available('wire') && ghost?.p.piece!=='power_cable') for(const {rows:terminals} of terminalLabels.values()) for(const row of terminals) {
    const at=terminalAt(row.device,row.key,row.declaredAt);
    project(row.name,at,'terminal',row.control.textContent,row);
  }
  if(available('power_cable') && ghost?.p.piece!=='wire') for(const row of powerLabels.values()) {
    if(row.control)project(row.port.name,powerPortAt(row.port),'power',row.port.kind==='output'?'Out':'In',row.port);
  }
  return rows;
}
function socketSelection() {
  return terminalStart || pickedPowerPort || (ghost?.p.piece==='power_cable' && (ghost.p.a_port||ghost.p.b_port)) || null;
}
function socketsAt(x,y,touch=false) {
  freshView();
  return sceneSockets().map(row=>({...row,gap:Math.hypot(row.x-x,row.y-y)}))
    .filter(row=>row.gap<=(touch?28:22)).sort((a,b)=>a.gap-b.gap);
}
function chooseSceneSocket(row) {
  $('socket-choices').hidden=true;
  if(row.kind==='heater'&&ghost?.p.piece==='ignition') {
    ghost.p.target=row.data.name;renderGhostBar();showGhostKnobs();askGhost();
  } else if(row.kind==='terminal') pickTerminal(row.name,true);
  else pickPowerPort(row.data,true);
}
function finishSocketClick(x,y,touch) {
  const rows=socketsAt(x,y,touch);
  if(!rows.length)return false;
  // When two pins are nearly on top of one another, offer labelled touch
  // targets instead of guessing which conductor the player intended.
  if(rows[1] && rows[1].gap-rows[0].gap<8) {
    const choice=$('socket-choices');choice.replaceChildren();
    const editIndex=!ghost&&!wiringMode&&!socketSelection()?placedAt(x,y):-1;
    if(editIndex>=0){const label=placements[editIndex]?`${pieceLabel(placements[editIndex].piece)} ${editIndex+1}`:sandboxObjects[editIndex-placements.length]?.name;
      const adjust=button(`Adjust ${label}`,()=>{choice.hidden=true;pickUp(editIndex);});adjust.dataset.pieceIndex=editIndex;choice.append(adjust);}
    for(const row of rows.slice(0,4)){
      const option=button(`${row.name.replace(/^your /,'').replace(':',' · ')} (${row.label})`,()=>chooseSceneSocket(row));
      option.dataset.socketName=row.name;choice.append(option);
    }
    choice.append(button('Cancel',()=>{choice.hidden=true;}));choice.hidden=false;
    const rect=renderer.domElement.getBoundingClientRect();
    choice.style.left=`${Math.max(6,Math.min(rect.width-choice.offsetWidth-6,x-rect.left+12))}px`;
    choice.style.top=`${Math.max(6,Math.min(rect.height-choice.offsetHeight-6,y-rect.top+12))}px`;
  } else chooseSceneSocket(rows[0]);
  return true;
}
function drawSceneSockets() {
  const rows=sceneSockets(), rect=renderer.domElement.getBoundingClientRect(), selected=socketSelection();
  const cord=level?.goal?.station?.done_when?.parted;
  const attaching=ghost?.p.piece==='ignition'&&ghost.p.attachment_version===2&&!ghost.p.target;
  const part=attaching&&machine?.parts.find(p=>p.name===cord);
  heaterAttachButton.hidden=!part||playing;
  if(part&&!heaterAttachButton.hidden){
    const point=new THREE.Vector3(...(world.bodies.get(part.name)?.position_m||part.at_m)).project(camera);
    heaterAttachButton.hidden=Math.abs(point.z)>1||Math.abs(point.x)>1||Math.abs(point.y)>1;
    if(!heaterAttachButton.hidden){
      const x=rect.left+(point.x+1)*rect.width/2,y=rect.top+(1-point.y)*rect.height/2;
      const mesh=meshes.get(part.name),box=mesh&&coachObjectBox([mesh]);
      const bounds=box?{left:box.x,right:box.x+box.width,top:box.y,bottom:box.y+box.height}:{left:x-12,right:x+12,top:y-12,bottom:y+12};
      const obstacles=[...view.querySelectorAll('#clock,#viewer-zoom,#viewer-perspective,#viewer-history')]
        .filter(e=>e.checkVisibility()).map(e=>e.getBoundingClientRect());
      const at=pieceToolbarPosition(rect,bounds,heaterAttachButton.getBoundingClientRect(),obstacles);
      heaterAttachButton.style.left=`${at.x-rect.left}px`;heaterAttachButton.style.top=`${at.y-rect.top}px`;
    }
  }
  const hover=socketPointer && !cameraGesture && !sceneDragged && !draggingGhost && !switchDragging
    ?rows.map(row=>({...row,gap:Math.hypot(row.x-socketPointer[0],row.y-socketPointer[1])})).filter(row=>row.gap<=22).sort((a,b)=>a.gap-b.gap)[0]:null;
  const names=new Set(rows.map(row=>row.name));
  for(const [name,mark] of socketMarks)if(!names.has(name)){mark.remove();socketMarks.delete(name);}
  for(const row of rows) {
    let mark=socketMarks.get(row.name);
    if(!mark){mark=document.createElementNS(socketNS,'g');mark.dataset.socket=row.name;
      const ring=document.createElementNS(socketNS,'circle');ring.setAttribute('r','9');
      const label=document.createElementNS(socketNS,'text');label.textContent=row.label;
      mark.append(ring,label);socketSvg.append(mark);socketMarks.set(row.name,mark);}
    mark.setAttribute('transform',`translate(${row.x-rect.left},${row.y-rect.top})`);
    mark.setAttribute('stroke',row.kind==='power'?'#ffe066':row.name.endsWith(':minus')?'#83bbff':'#f19076');
    mark.classList.toggle('selected',row.name===selected);mark.classList.toggle('hovered',row.name===hover?.name&&row.name!==selected);
  }
  const first=rows.find(row=>row.name===selected), end=hover || (socketPointer && {x:socketPointer[0],y:socketPointer[1]});
  socketTail.style.display=first&&end?'':'none';
  if(first&&end)socketTail.setAttribute('d',`M ${first.x-rect.left} ${first.y-rect.top} L ${end.x-rect.left} ${end.y-rect.top}`);
  view.classList.toggle('socket-hover',Boolean(hover));
  const learningWires=!level?.free && placements.some(p=>p.piece==='battery') && level.tray.some(t=>t.piece==='wire'&&piecesLeft(t)>0);
  const hint=$('scene-wire-hint');hint.hidden=!rows.length || (!selected&&!ghost&&!hover&&!wiringMode&&!learningWires);
  hint.hidden=hint.hidden&&ghost?.p.piece!=='ignition';
  hint.textContent=ghost?.p.piece==='ignition'&&ghost.p.attachment_version===2?
    (ghost.p.target?'Choose heating power, then Place and connect both wires':hover?.kind==='heater'?`Clip heater to ${hover.data.name}`:'Click a Clip ring on the material to attach the heater'):selected?`${selected.replace(/^your /,'')} → click another connection point · Esc cancels`
    :hover?`Click ${hover.name.replace(/^your /,'')} to start a wire`:learningWires?'Click a + or − ring to start a wire, then click its other end':'Click a connection point on a piece, then the other end';
}
window.machineSceneSockets=()=>{freshView();return {selected:socketSelection(),pending:socketTail.style.display!=='none',
  points:sceneSockets().map(({name,at,x,y,kind})=>({name,at,x,y,kind}))};};
document.addEventListener('keydown',e=>{
  if(e.key!=='Escape' || document.querySelector('dialog[open]'))return;
  if(!$('socket-choices').hidden){$('socket-choices').hidden=true;e.preventDefault();e.stopImmediatePropagation();return;}
  if(ghost?.p.piece==='power_cable' && ghost.p.a_port){cancelGhost();setWiringMode(false);}
});

function contactSnapshot() {
  const frame=flowGroup.visible&&flowIndex>=0?previewShown?.flow_frames?.[flowIndex]:null;
  return frame?{preview:true,contacts:frame.contacts||[],devices:frame.devices||[],batteries:frame.batteries||[],terminals:frame.terminals||[]}
    :{preview:false,contacts:readouts.electrical?.contacts||[],devices:readouts.electrical?.devices||[],batteries:readouts.machines?.batteries||[]};
}
const contactGaps=new Map();
function updateContactGaps() {
  const contacts=readouts.electrical?.contacts||[], terminals=terminalMap(machine?.electrical), seen=new Set();
  for (const contact of contacts) {
    const a=terminals.get(contact.a), b=terminals.get(contact.b);
    if (!a||!b) continue;
    seen.add(contact.name);
    let line=contactGaps.get(contact.name);
    if (!line) {
      line=new THREE.Line(new THREE.BufferGeometry(),new THREE.LineDashedMaterial({color:0xffad66,dashSize:.015,gapSize:.012,depthWrite:false}));
      scene.add(line);contactGaps.set(contact.name,line);
    }
    line.geometry.setFromPoints([new THREE.Vector3(...a),new THREE.Vector3(...b)]);line.computeLineDistances();
    line.material.color.setHex(contact.closed===true?0x5fe08f:0xffad66);
    line.visible=!flowGroup.visible;
  }
  for (const [name,line] of contactGaps) if (!seen.has(name)) {
    scene.remove(line);line.geometry.dispose();line.material.dispose();contactGaps.delete(name);
  }
}
window.machineContactState=()=>({...contactSnapshot(),terminals:window.machineWiringState().terminals,
  liveContacts:readouts.electrical?.contacts||[],liveDevices:readouts.electrical?.devices||[],
  liveTerminals:Object.fromEntries(terminalMap(machine?.electrical)),
  guides:[...contactGaps].map(([name,line])=>({name,visible:line.visible,color:line.material.color.getHex()}))});

// Power ports are explicit two-conductor leads. These buttons only save
// topology; the native collector, energy store and motor decide the power.
let pickedPowerPort = null, powerBusy = false;
const powerLabels = new Map(), solarRays = new Map();
let solarResult=null,solarWanted='',solarStamp='',solarVersion=0,solarTimer=null,solarBusy=false,solarPending=false,solarError='';
function scheduleSolarPreview(ms=140) {
  if(!ghost || playing || !level || document.body.matches('.on-sandbox,.on-levels') ||
     !(ghost.p.piece==='solar' || (ghost.solar_setup||machine?.solar_panels||[]).length))return;
  const request={op:'level_sunlight',level:level.id,...sandboxRequest(),placements:ghostPlacements()};
  const stamp=JSON.stringify(request);
  if(stamp===solarWanted && (solarTimer || solarBusy || stamp===solarStamp))return;
  clearTimeout(solarTimer);solarWanted=stamp;solarVersion++;solarPending=true;solarError='';
  solarTimer=setTimeout(()=>{solarTimer=null;askSolarPreview();},ms);
}
async function askSolarPreview() {
  if(solarBusy || !solarWanted || !ghost || ghost.busy || !ghost.answered || !ghost.fits || playing)return;
  const stamp=solarWanted,mine=solarVersion;solarBusy=true;
  try {
    const result=await api(JSON.parse(stamp));
    if(mine!==solarVersion || !ghost || playing)return;
    solarResult=result;solarStamp=stamp;solarPending=false;updatePowerLabels();showGhostState();
  } catch(error) {
    if(mine!==solarVersion)return;
    if(error.status===503)solarTimer=setTimeout(()=>{solarTimer=null;askSolarPreview();},500);
    else {solarError='Sunlight preview unavailable; set down to measure.';solarResult=null;solarStamp=stamp;solarPending=false;updatePowerLabels();showGhostState();}
  } finally {
    solarBusy=false;
    if(mine!==solarVersion && ghost && !playing){clearTimeout(solarTimer);solarTimer=setTimeout(()=>{solarTimer=null;askSolarPreview();},0);}
  }
}
function solarSnapshot() {
  if(ghost && !playing) {
    const request={op:'level_sunlight',level:level.id,...sandboxRequest(),placements:ghostPlacements()};
    const pending=solarPending || solarStamp!==JSON.stringify(request);
    return {preview:true,pending,error:solarError,panels:pending?[]:solarResult?.panels||[],batteries:pending?[]:solarResult?.stores||[]};
  }
  return {preview:false,pending:false,panels:readouts.machines?.solar_panels||[],batteries:readouts.machines?.batteries||[]};
}
function powerMessage(text,reveal=true) {
  $('power-status').textContent = text;
  $('power-status').hidden = !text;
}
// Explain the graph that actually exists; this UI never connects or powers it
// without the same two-port player action used in the sandbox.
function solarLiftGraph(){
  const family=level?.variant?.family||level?.id;
  const baseTitle=activeDesign?.draft?.base?.title||machine?.title;
  if(family!=='easy-charge-lift' && !(level?.free&&['Sun-powered lift','Charge then lift','Sun powers the flag'].includes(baseTitle)))return null;
  if(!(machine?.sun?.irradiance_w_m2>0) || !(machine.solar_panels?.length || level?.tray?.some(t=>t.piece==='solar')))return null;
  const network=machine.electrical?.networks?.find(n=>n.devices.some(d=>d.kind==='motor'));
  if(!network)return null;
  const motor=network.devices.find(d=>d.kind==='motor');
  const input=machine.electrical.power_ports.find(p=>p.kind==='input'&&p.battery===network.battery);
  const cable=machine.electrical.power_cables.find(c=>c.b===input?.name);
  const output=machine.electrical.power_ports.find(p=>p.kind==='output'&&(!cable||p.name===cable.a));
  const direct=!cable&&machine.solar_panels.some(p=>p.name===output?.solar_panel&&p.battery===network.battery);
  return {network,motor,input,output,cable,direct};
}
function updateSolarLiftGuide(){
  const box=$('solar-lift-guide'),bearing=$('sun-bearing'),g=solarLiftGraph();
  box.hidden=!g || document.body.matches('.on-levels,.on-sandbox');
  bearing.hidden=document.body.matches('.on-levels,.on-sandbox')||!(machine?.sun?.irradiance_w_m2>0)||
    !(machine.solar_panels?.length||level?.tray?.some(t=>t.piece==='solar'));
  view.classList.toggle('has-sun-guide',!bearing.hidden);
  if(!bearing.hidden)updateSunBearing();
  if(box.hidden)return;
  box.classList.toggle('has-ghost',Boolean(ghost));
  const pending=!playing&&(flowPending||ghost&&!ghost.answered);
  const sample=flowGroup.visible?previewShown?.flow_frames?.[flowIndex]:null;
  const battery=(sample?.batteries||readouts.machines?.batteries||[]).find(b=>b.name===g.network.battery);
  const panel=(sample?.solar_panels||readouts.machines?.solar_panels||[]).find(p=>p.name===g.output?.solar_panel);
  const motor=(sample?.devices||readouts.electrical?.devices||[]).find(d=>d.name===g.motor.name);
  const setText=(id,text)=>{if($(id).textContent!==text)$(id).textContent=text;};
  setText('solar-lift-reading',pending?'Updating power readings…':
    `${sample?'Preview':'Now'} · Panel ${(panel?.power_w||0).toFixed(1)} W · Battery ${(battery?.charge_j||0).toFixed(1)} J · Motor ${(motor?.power_w||0).toFixed(1)} W`);
  setText('solar-lift-connection',ghost?'Set the panel down to connect.':!g.output?'Add a solar panel; aim at the sun.':
    g.direct?'Panel already connected · earlier design.':pickedPowerPort===g.output.name?'Now click Battery In.':g.cable?'Cable connected · motor and bulb are already wired.':'Click Panel Out, then Battery In.');
  $('solar-out-connect').disabled=playing||powerBusy||Boolean(ghost)||!g.output||g.direct;
  $('solar-out-connect').setAttribute('aria-pressed',String(Boolean(g.output&&pickedPowerPort===g.output.name)));
  $('solar-in-connect').disabled=playing||powerBusy||Boolean(ghost)||!g.input||!g.output||g.direct||pickedPowerPort!==g.output.name;
}
function updateSunBearing(){
  const bearing=$('sun-bearing');
  // Screen bearing from the declared sunlight vector and camera axes, even
  // when the distant sun disc is outside the view. It does not aim the panel.
  const el=machine.sun.elevation_deg*Math.PI/180,az=machine.sun.azimuth_deg*Math.PI/180;
  const direction=new THREE.Vector3(Math.cos(el)*Math.sin(az),Math.sin(el),Math.cos(el)*Math.cos(az));
  const right=direction.dot(new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld,0));
  const up=direction.dot(new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld,1));
  const behind=direction.dot(new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld,2))>0;
  $('sun-arrow').style.transform=`rotate(${Math.atan2(right,up)*180/Math.PI}deg)`;
  $('sun-side').textContent=behind?'behind view':'';
  bearing.setAttribute('aria-label',`Sun direction${behind?', behind view':''}; elevation ${machine.sun.elevation_deg} degrees`);
}
async function connectFromSolarGuide(kind){
  const g=solarLiftGraph();
  if(!g?.[kind])return;
  await pickPowerPort(g[kind]);
}
$('solar-out-connect').addEventListener('click',()=>connectFromSolarGuide('output'));
$('solar-in-connect').addEventListener('click',()=>connectFromSolarGuide('input'));
function syncPowerLabels() {
  const host = $('power-labels'); host.replaceChildren(); powerLabels.clear();
  const pins = $('power-pins'); pins.replaceChildren();
  const svg = document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.classList.add('power-leaders'); svg.setAttribute('aria-hidden','true'); pins.append(svg);
  pickedPowerPort = null; powerBusy = false; powerMessage('');
  const shown=shownElectrical(),panels=ghost?.solar_setup||machine.solar_panels||[];
  for (const port of shown.power_ports || []) {
    const pack=machine.electrical.devices?.find(d=>d.kind==='battery'&&d.battery===port.battery&&d.terminal_parts);
    if (pack&&!machine.solar_panels?.length&&!machine.electrical.power_cables?.length) continue;
    if (machine.electrical.devices?.some(d=>d.kind==='socket')&&!machine.solar_panels?.length&&!level?.tray.some(t=>t.piece==='solar'||t.piece==='power_cable')) continue;
    // Show charging sockets when a collector or charging cable can be used.
    if (port.kind === 'input' && !machine.solar_panels?.length && !machine.electrical?.power_cables?.length
        && !level?.tray.some(t => t.piece === 'solar' || t.piece === 'power_cable')) continue;
    const card = document.createElement('section'); card.className = `power-label ${port.kind}`;
    card.dataset.port = port.name;
    const title = document.createElement('strong'); title.textContent = port.label || port.name.replace(/:power$/, '');
    card.title = port.kind === 'output' ? 'Dashed line: the engine’s sunlight sample from the collector’s center. Orange ends at the blocking part.' : 'Input for an ideal two-conductor solar charging lead.';
    const watts = document.createElement('output'); watts.className = 'solar-watts';
    const detail = document.createElement('output'); detail.className = 'solar-detail';
    const state = document.createElement('output'); state.className = 'solar-state';
    const control = button(port.kind === 'output' ? 'Out' : 'In', () => pickPowerPort(port),
      {ariaLabel: `${port.kind === 'output' ? 'Power output of' : 'Power input of'} ${title.textContent}`});
    control.setAttribute('aria-pressed', 'false');
    if (port.kind === 'output') card.append(title, watts, detail, state);
    else card.append(title, state);
    const pin = document.createElement('section'); pin.className='power-pin';pin.dataset.port=port.name;
    const badge = document.createElement('output'); badge.className='power-badge';
    pin.append(badge,control);pins.append(pin);
    host.append(card); powerLabels.set(port.name, {port, card, pin, badge, watts, detail, state, control});
  }
  // Older saved declarations also get a visible meter even without ports.
  for (const panel of panels) {
    if ([...powerLabels.values()].some(row => row.port.solar_panel === panel.name)) continue;
    const card = document.createElement('section'); card.className = 'power-label output';
    const title = document.createElement('strong'); title.textContent = panel.name;
    const watts = document.createElement('output'); watts.className = 'solar-watts';
    const detail = document.createElement('output'); detail.className = 'solar-detail';
    const state = document.createElement('output');
    card.append(title, watts, detail, state); host.append(card);
    const pin = document.createElement('section'); pin.className='power-pin';
    const badge = document.createElement('output'); badge.className='power-badge';pin.append(badge);pins.append(pin);
    powerLabels.set(panel.name, {port:{name:panel.name,kind:'output',solar_panel:panel.name,at_m:panel.at_m},
      card, pin, badge, watts, detail, state});
  }
  for (const row of powerLabels.values()) {
    row.leader = document.createElementNS(svg.namespaceURI,'line');
    row.dot = document.createElementNS(svg.namespaceURI,'circle'); row.dot.setAttribute('r','4');
    svg.append(row.leader,row.dot);
  }
  updatePowerLabels();
  showInstrumentPanel();
}
function updatePowerLabels() {
  const snapshot=solarSnapshot(),prefix=snapshot.preview?'Preview · ':'';
  for (const {port, badge, watts, detail, state, control} of powerLabels.values()) {
    const cable = machine.electrical?.power_cables?.find(c => c.a === port.name || c.b === port.name);
    if (port.kind === 'output') {
      const measured = snapshot.panels.find(p => p.name === port.solar_panel);
      const panel = machine.solar_panels?.find(p => p.name === port.solar_panel);
      const battery = snapshot.batteries.find(b => b.name === (measured?.battery || panel?.battery));
      watts.textContent = measured ? `${prefix}${(measured.power_w || 0).toFixed(1)} W charging` : snapshot.error?'Preview unavailable':'Updating sunlight…';
      badge.textContent = measured ? `${(measured.power_w || 0).toFixed(1)} W` : '… W';
      detail.textContent = measured ? `${(measured.sunlight_w || 0).toFixed(0)} W sunlight · ${(battery?.charge_j || 0).toFixed(1)} J stored` : '';
      const aim = Number.isFinite(measured?.off_sun_deg) ? `${measured.off_sun_deg.toFixed(0)}° off sun` : '';
      state.textContent = [snapshot.error || (snapshot.pending?'Measuring proposed position…':measured?.shaded ? `${prefix}In shadow at panel center · ${measured.shaded_by || 'a part'}` : measured?`${prefix}${measured.ray_cast?'Panel center in sunlight':'No sunlight on collecting face'}`:''), aim,
        battery && battery.charge_j >= battery.capacity_j ? 'Store full' : '',
        cable ? 'Cable connected' : 'Output not wired'].filter(Boolean).join(' · ');
    } else state.textContent = cable ? 'Cable connected' : 'Waiting for a cable';
    badge.hidden = port.kind !== 'output' || (wiringMode && !playing);
    if (control) {
      control.hidden = playing || (!wiringMode && !pickedPowerPort);
      control.disabled = playing || powerBusy || Boolean(ghost);
      control.setAttribute('aria-pressed', String(port.name === pickedPowerPort));
    }
  }
  updateSolarRays();
  positionPowerLabels();
  // A new or resized meter can occupy an old terminal card's position before
  // the next animation frame. Move both sets before exposing ready controls.
  positionTerminalLabels();
}
function updateSolarRays() {
  const seen = new Set();
  for (const p of solarSnapshot().panels) {
    if (!p.ray_cast || !p.ray_from_m || !p.toward_sun) continue;
    seen.add(p.name);
    let line = solarRays.get(p.name);
    if (!line) {
      line = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineDashedMaterial({color:0xffcf59,
        dashSize:.04,gapSize:.025,transparent:true,opacity:.85,depthTest:false}));
      const sample=new THREE.Mesh(new THREE.SphereGeometry(.014,12,8),new THREE.MeshBasicMaterial({color:0xffcf59,depthTest:false}));
      line.add(sample);line.userData.sample=sample;
      line.renderOrder = 20; scene.add(line); solarRays.set(p.name, line);
    }
    const from = new THREE.Vector3(...p.ray_from_m);
    const end = p.shadow_hit_m ? new THREE.Vector3(...p.shadow_hit_m)
      : from.clone().addScaledVector(new THREE.Vector3(...p.toward_sun), .7);
    line.geometry.setFromPoints([from, end]); line.computeLineDistances();
    line.material.color.setHex(p.shaded ? 0xff906c : 0xffcf59);
    line.userData.sample.position.copy(from);line.userData.sample.material.color.copy(line.material.color);
  }
  for (const [name, line] of solarRays) if (!seen.has(name)) {
    line.userData.sample.geometry.dispose();line.userData.sample.material.dispose();
    scene.remove(line); line.geometry.dispose(); line.material.dispose(); solarRays.delete(name);
  }
}
window.machineSolarState=()=>({
  ...solarSnapshot(),
  livePanels:readouts.machines?.solar_panels||[],
  lightDirection:sun.position.clone().sub(sun.target.position).normalize().toArray(),
  guides:[...solarRays].map(([name,line])=>({name,points:Array.from(line.geometry.attributes.position.array)})),
  renderedHits:solarSnapshot().panels.filter(p=>p.ray_cast).map(p=>{
    const caster=new THREE.Raycaster(new THREE.Vector3(...p.ray_from_m),sun.position.clone().sub(sun.target.position).normalize(),0,1000);
    const rows=[...meshes].filter(([name])=>!hiddenPiece(name));
    const hit=caster.intersectObjects(rows.map(([,mesh])=>mesh),true).find(hit=>hit.object.castShadow);
    const owner=hit&&rows.find(([,mesh])=>{let object=hit.object;while(object){if(object===mesh)return true;object=object.parent;}return false;});
    return {name:p.name,part:owner?.[0]||null,point:hit?.point.toArray()||null};
  })
});
async function pickPowerPort(port,fromScene=false) {
  if(ghost?.p.piece==='power_cable' && !playing && !powerBusy && !terminalBusy && level) {
    const g=ghost, sourceLevel=level;
    const selected=g.p.a_port||g.p.b_port, key=port.kind==='output'?'a_port':'b_port', other=key==='a_port'?'b_port':'a_port';
    if(selected===port.name){cancelGhost();return;}
    if(g.rewireKey && key!==g.rewireKey){powerMessage(`Choose a ${g.rewireKey==='a_port'?'solar output':'power input'} for this end.`);return;}
    if(!selected || g.p[key]) {
      g.p[key]=port.name;g.p[other]='';renderGhostBar();askGhost();return;
    }
    g.p[key]=port.name;renderGhostBar();powerBusy=true;terminalBusy=true;
    try {
      askGhost();while(ghost===g && g.busy)await g.check;
      if(ghost!==g || level!==sourceLevel)return;
      if(!g.fits){powerMessage(g.problems.join(' · '));return;}
      if(placeGhost()){await rebuildLevel(false);setWiringMode(false);powerMessage('Power cable connected. Try It! to try the machine.',!fromScene);}
    } catch(e){powerMessage(e.message);}
    finally{powerBusy=false;terminalBusy=false;updatePowerLabels();}
    return;
  }
  if (playing || powerBusy || ghost || !level) return;
  const selectedPort=[...powerLabels.values()].find(row=>row.port.name===pickedPowerPort)?.port;
  if (!selectedPort || selectedPort.kind===port.kind || pickedPowerPort===port.name) {
    pickedPowerPort = pickedPowerPort === port.name ? null : port.name;
    powerMessage(pickedPowerPort ? (port.kind==='output'?'Now click the winch or battery input to connect the power cable. Esc cancels.':'Now click a solar output to connect the power cable. Esc cancels.') : '',!fromScene);
    updatePowerLabels(); return;
  }
  const output = port.kind==='output'?port.name:pickedPowerPort, input=port.kind==='input'?port.name:pickedPowerPort;
  const sourceLevel = level, designId = activeDesign?.id, before = JSON.stringify(placements);
  const existing = placements.findIndex(p => p.piece === 'power_cable' && p.a_port === output);
  const cable = {piece:'power_cable',a_port:output,b_port:input};
  powerBusy = true; updatePowerLabels();
  try {
    // Validate the whole saved graph before replacing its current connection.
    const next = placements.map(p => ({...p}));
    if (existing >= 0) next[existing] = cable; else next.push(cable);
    await api({op:'check',level:level.id,placements:next,
      ...(level.free ? {base:activeDesign?.draft.base || sandboxBase} : {})});
    if (level !== sourceLevel || activeDesign?.id !== designId || JSON.stringify(placements) !== before) return;
    remember(); placements = next; pickedPowerPort = null; renderTray(); renderPlaced();
    await rebuildLevel(false);
    setWiringMode(false);
    if (level === sourceLevel && activeDesign?.id === designId) powerMessage('Power cable connected. Try It! to try the machine.',!fromScene);
  } catch (e) { powerMessage(e.message); }
  finally { powerBusy = false; updatePowerLabels(); }
}
document.addEventListener('keydown', e => {
  if (document.querySelector('dialog[open]')) return;
  if (e.key === 'Escape' && pickedPowerPort) { pickedPowerPort = null; powerMessage(''); updatePowerLabels(); }
  if (e.key === 'Escape' && wiringMode) setWiringMode(false);
});

function positionPowerLabels() {
  // A rehearsal may finish between selecting an output and pressing an input.
  // Keep its changing legend out of the wiring layout during that gesture.
  $('preview-legend').style.visibility = pickedPowerPort || terminalStart ? 'hidden' : '';
  if (!machine || !powerLabels.size) return;
  const rect = renderer.domElement.getBoundingClientRect();
  const clock = $('clock').getBoundingClientRect();
  const top = Math.max(8, clock.bottom - rect.top + 8);
  const bottom = rect.height - 10;
  const occupied = ['scene-mode','sun-bearing','viewer-zoom','viewer-perspective','piece-editor','viewer-history']
    .map(id => $(id)).concat([...view.querySelectorAll('#piece-handles button:not([hidden])')]).filter(el => el && !el.hidden && el.offsetWidth && el.offsetHeight && !((pickedPowerPort || terminalStart) && el.id === 'preview-legend'))
    .map(el => { const r = el.getBoundingClientRect(); return {x:r.left - rect.left,y:r.top - rect.top,w:r.width,h:r.height}; });
  occupied.push(...readoutBodyRects(rect));
  // Place the larger meters first, then fit receiver buttons beside them.
  const rows = [...powerLabels.values()].sort((a,b) => (a.port.kind === 'input') - (b.port.kind === 'input'));
  for (const {port, card: reading, pin: card, badge, control, leader, dot} of rows) {
    badge.hidden = port.kind !== 'output' || (wiringMode && !playing);
    if (control) control.hidden = playing || (!wiringMode && !pickedPowerPort);
    const at = powerPortAt(port);
    if (!at) { card.hidden = true; continue; }
    const p = new THREE.Vector3(...at).project(camera);
    reading.hidden = false;
    const editingThisPanel = ghost?.p.piece === 'solar' && port.solar_panel === `your solar ${ghost.index + 1}`;
    card.hidden = editingThisPanel || (port.kind === 'input' && (playing || (!wiringMode && !pickedPowerPort))) || p.z > 1 || p.z < -1 || Math.abs(p.x) > 1.4 || Math.abs(p.y) > 1.4;
    if (leader) { leader.style.display = dot.style.display = card.hidden ? 'none' : ''; }
    if (card.hidden) continue;
    const width = card.offsetWidth, height = card.offsetHeight;
    const anchor = {x:(p.x + 1) / 2 * rect.width, y:(1 - p.y) / 2 * rect.height};
    let x = Math.max(8, Math.min(rect.width - width - 8, readoutSideXs(anchor.x,width,rect.width)[0]));
    let y = Math.max(top, Math.min(bottom - height, anchor.y - height - 10));
    const collides = (x, y) => occupied.some(r => x < r.x + r.w + 6 && x + width + 6 > r.x && y < r.y + r.h + 6 && y + height + 6 > r.y);
    if (collides(x, y)) {
      // A short, wide scene may have camera/history tools on both edges.
      // Try beside those tools and near the port as well as the outer edges;
      // keep the actual apparatus reserved rather than hiding a connection.
      const xs = [...readoutSideXs(anchor.x,width,rect.width),anchor.x-width/2,
        ...occupied.flatMap(r=>[r.x-width-8,r.x+r.w+8])]
        .map(x=>Math.max(8,Math.min(rect.width-width-8,x)));
      const ys = [y, bottom - height, top, ...occupied.flatMap(r=>[r.y-height-8,r.y+r.h+8])];
      const candidates = xs.flatMap(x => ys.map(y => ({x,y})));
      const free = candidates.find(c => c.x >= 8 && c.x + width <= rect.width - 8 && c.y >= top && c.y + height <= bottom && !collides(c.x,c.y));
      if (free) { x = free.x; y = free.y; }
      else {card.hidden=true;if(leader)leader.style.display=dot.style.display='none';continue;}
    }
    card.style.left = `${x}px`; card.style.top = `${y}px`;
    if (leader) {
      leader.setAttribute('x1', String(anchor.x)); leader.setAttribute('y1', String(anchor.y));
      leader.setAttribute('x2', String(Math.max(x, Math.min(x + width, anchor.x))));
      leader.setAttribute('y2', String(Math.max(y, Math.min(y + height, anchor.y))));
      dot.setAttribute('cx', String(anchor.x)); dot.setAttribute('cy', String(anchor.y));
    }
    occupied.push({x,y,w:width,h:height});
  }
}

// Light (docs/optics-checkpoint.md): the rays the engine last traced, as lines
// as bright as the power it measured on them, and each light sensor as a small
// disc that glows with what it reads. The key light comes from where the
// machine's sun is.
let beams = null;
const sensors = new Map();
const hotVoxels=new Map(),hotVoxelShape=new THREE.BoxGeometry(1,1,1);
let heatingTarget=null,heatInspection=null;
function closeHeatInspection(restore=true) {
  if(!heatInspection)return;
  const old=heatInspection;heatInspection=null;
  $('inspect-heat').textContent=heatingTarget?.how==='chars'?'Inspect burn':'Inspect heat';
  if(restore){azimuth=old.azimuth;elevation=old.elevation;distance=old.distance;goal.copy(old.goal);target.copy(old.target);follow=old.follow;
    $('follow').setAttribute('aria-pressed',String(follow));
  }
  if(restore)syncLight();
}
$('inspect-heat').addEventListener('click',()=>{
  if(heatInspection){closeHeatInspection();return;}
  if(!heatingTarget)return;
  heatInspection={azimuth,elevation,distance,goal:goal.clone(),target:target.clone(),follow};
  $('inspect-heat').textContent='Back to scene';
  follow=false;$('follow').setAttribute('aria-pressed','false');
  // Look from the incoming beam's side of the actual heated cell; a wall
  // should not obscure the face being inspected. This changes only camera.
  let nearest=null;
  for(const p of readouts.light?.paths||[])for(let i=3;i<p.mm.length;i+=3){
    const a=p.mm.slice(i-3,i).map(v=>v/1000),b=p.mm.slice(i,i+3).map(v=>v/1000);
    const d=Math.hypot(...b.map((v,k)=>v-heatingTarget.at_m[k]));
    if(!nearest||d<nearest.d)nearest={d,a,b};
  }
  if(nearest){const dx=nearest.a[0]-nearest.b[0],dz=nearest.a[2]-nearest.b[2];if(Math.hypot(dx,dz)>.01)azimuth=Math.atan2(dx,dz)+.3;}
  elevation=.25;distance=.65;goal.set(...heatingTarget.at_m);target.copy(goal);
  freshView();
  syncLight();
});
function syncThermalSpots(light) {
  const rows=thermalCells(light),seen=new Set();
  for(const row of rows){
    const body=world.bodies.get(row.body);if(!body)continue;
    const key=row.body+':'+row.cell;seen.add(key);
    let mesh=hotVoxels.get(key);
    if(!mesh){mesh=new THREE.Mesh(hotVoxelShape,new THREE.MeshStandardMaterial({roughness:1,polygonOffset:true,polygonOffsetFactor:-1,polygonOffsetUnits:-1}));scene.add(mesh);hotVoxels.set(key,mesh);}
    mesh.scale.setScalar(row.cell_m);
    mesh.quaternion.set(body.orientation_wxyz[1],body.orientation_wxyz[2],body.orientation_wxyz[3],body.orientation_wxyz[0]);
    mesh.position.set(...row.local_m).applyQuaternion(mesh.quaternion).add(new THREE.Vector3(...body.position_m));
    mesh.material.color.setHex(row.charring?0x241a12:heatTint(materialColor(body.material),row.temperature_k));
    mesh.userData.row=row;
  }
  for(const [key,mesh] of hotVoxels)if(!seen.has(key)){scene.remove(mesh);mesh.material.dispose();hotVoxels.delete(key);}
  const row=rows.find(c=>c.cut_w>0)||rows[0],taken=(light?.taken||[]).at(-1);
  const ropeFor=name=>(machine?.ropes||[]).find(r=>r.segments.some(n=>family(n)===family(name)));
  const takenRope=taken&&ropeFor(taken.body),cutRope=takenRope&&
    (readouts.joints||[]).some(j=>j.name===takenRope.cord&&j.attached===false)?takenRope:null;
  heatingTarget=cutRope?{...taken,cutThrough:true}:row||(taken?{...taken,at_m:taken.at_m}:null);
  const output=$('thermal-readout'),inspect=$('inspect-heat');
  output.hidden=inspect.hidden=!heatingTarget;
  view.classList.toggle('has-thermal-spot',Boolean(heatingTarget));
  if(!heatingTarget){closeHeatInspection(false);return;}
  inspect.textContent=heatInspection?'Back to scene':row?.charring||taken?.how==='chars'?'Inspect burn':'Inspect heat';
  const bodyName=cutRope?.cord||(row&&ropeFor(row.body)?.cord)||family(row?.body||taken.body),celsius=row?row.temperature_k-273.15:null;
  if(row){
    output.textContent=`${bodyName} · ${cutRope?'Cut through · nearby heat':row.charring?'Charring':row.how==='melts'&&row.cut_w>0?'Melting':'Heating'} · ${celsius.toFixed(0)} °C\n`+
      `${row.absorbed_w.toFixed(0)} W absorbed`+(row.progress!==null?` · ${(100*row.progress).toFixed(0)}% cell energy`:'');
    output.title=`Engine steady-spot temperature at the lit ${1000*row.cell_m} mm lattice cell; warm-up delay is not modeled. ${row.held_j.toFixed(0)} / ${row.needed_j.toFixed(0)} J toward cell removal. This is an energy indicator, not char depth. `+
      (row.beyond_model?'Temperature is beyond the thermal model’s declared range.':'Geometry changes only when the native engine takes matter away.');
  }else{
    const pieces=[...world.bodies.keys()].filter(n=>family(n)===bodyName).length;
    output.textContent=`${bodyName} · ${cutRope||pieces>1||pieces===0?'Cut through':'Material removed'}\n${taken.cm3.toFixed(1)} cm³ · ${taken.j.toFixed(0)} J`;
    output.title='The native engine removed this cell and rebuilt the remaining geometry. No flames or fragment motions are invented.';
  }
}
window.machineThermalState=()=>({cells:[...hotVoxels.values()].map(m=>({...m.userData.row,position_m:m.position.toArray()})),
  text:$('thermal-readout').textContent,visible:!$('thermal-readout').hidden,inspecting:Boolean(heatInspection),target:heatingTarget,
  taken:readouts.light?.taken||[],rayPaths:beams?.userData.paths||0});
function syncLight() {
  const light = readouts.light;
  syncThermalSpots(light);
  // The close-up must expose the native char/gap, not bury it beneath dozens
  // of overlapping sample lines. Keep six actual traced paths; no power,
  // footprint, thermal state or geometry is changed by this display filter.
  const paths=solarLiftGraph()&&!opticalSetup()?.lamps?.length?[]:light?.paths||[],stride=Math.max(1,Math.ceil(paths.length/6));
  const shown=heatInspection?paths.filter((_,i)=>i%stride===0).slice(0,6):paths;
  const {positions, colors, legs} = beamSegments(shown);
  if (!beams) {
    // Opaque, so the glass is drawn over them and they show through it.
    beams = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({vertexColors: true}));
    beams.frustumCulled = false;
    scene.add(beams);
  }
  beams.geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  beams.userData.paths=shown.length;
  beams.geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  beams.geometry.setDrawRange(0, legs * 2);
  beams.visible = legs > 0;
  const seen = new Set();
  for (const c of (light && light.photocells) || []) {
    if (!c.at_m) continue;
    seen.add(c.name);
    let disc = sensors.get(c.name);
    if (!disc) {
      const r = Math.max(.006, Math.sqrt((c.area_m2 || 1e-4) / Math.PI));
      disc = new THREE.Mesh(new THREE.CircleGeometry(r, 20), new THREE.MeshBasicMaterial({color: 0x334455, side: THREE.DoubleSide}));
      scene.add(disc); sensors.set(c.name, disc);
    }
    const n = new THREE.Vector3(...(c.normal || [0, 1, 0])).normalize();
    disc.position.set(...c.at_m).addScaledVector(n, .002);
    disc.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), n);
    disc.material.color.setHex(c.power_w > 0 ? 0xffe066 : 0x334455);
  }
  for (const [name, disc] of sensors) if (!seen.has(name)) { scene.remove(disc); disc.geometry.dispose(); sensors.delete(name); }
}
function placeSun() {
  const s = machine && (machine.sun || (machine.light && machine.light.sun));
  // Keep real cast shadows legible under the declared sun. This adjusts only
  // display fill lighting; the native ray and energy readings remain final.
  ambient.intensity = s && s.irradiance_w_m2 > 0 ? .65 : 1.1;
  if (!s) { sun.position.set(4, 8, 5); sunDisc.visible = false; return; }
  const el = s.elevation_deg * Math.PI / 180, az = s.azimuth_deg * Math.PI / 180;
  const toward = [Math.cos(el) * Math.sin(az), Math.sin(el), Math.cos(el) * Math.cos(az)];
  sun.position.set(...toward.map(v => 12 * v));
  sunDisc.position.set(...toward.map(v => 30 * v));
  sunDisc.visible = true;
}

// The ground the engine built: its own heights, one per column.
let terrain = null, water = null, parcels = null;
let riverFlow = null, riverState = null;
// Poured water in the air: one small sphere per parcel the engine carries,
// where the engine says it is (millimetres).
function syncParcels(p) {
  if (!p) return;
  const xyz = p.xyz_mm || [], count = Math.floor(xyz.length / 3);
  if (!parcels || parcels.instanceMatrix.count < count) {
    if (parcels) { scene.remove(parcels); parcels.geometry.dispose(); }
    const capacity = Math.max(256, 2 * count);
    parcels = new THREE.InstancedMesh(new THREE.SphereGeometry(p.r_m || .018, 10, 8),
      new THREE.MeshStandardMaterial({color: 0x3f8fd8, transparent: true, opacity: .85, roughness: .15}), capacity);
    parcels.frustumCulled = false;
    scene.add(parcels);
  }
  const m = new THREE.Matrix4();
  for (let k = 0; k < count; k++) parcels.setMatrixAt(k, m.makeTranslation(xyz[3 * k] / 1000, xyz[3 * k + 1] / 1000, xyz[3 * k + 2] / 1000));
  parcels.count = count;
  parcels.instanceMatrix.needsUpdate = true;
}
function decodeFloats(b64) {
  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  return new Float32Array(bytes.buffer, 0, bytes.length / 4);
}
function syncGround(view) {
  if (terrain) { scene.remove(terrain); terrain.geometry.dispose(); terrain = null; }
  ground.visible = grid.visible = !view;
  if (!view || !view.grid) return;
  const g = view.grid, heights = decodeFloats(view.heights_b64);
  const width = (g.nx - 1) * g.cell_m, depth = (g.nz - 1) * g.cell_m;
  const geometry = new THREE.PlaneGeometry(width, depth, g.nx - 1, g.nz - 1);
  geometry.rotateX(-Math.PI / 2);
  const pos = geometry.attributes.position;
  // After the turn, vertex (i, j) is column i along x and row j along z.
  for (let j = 0; j < g.nz; j++) for (let i = 0; i < g.nx; i++) pos.setY(j * g.nx + i, heights[j * g.nx + i]);
  geometry.computeVertexNormals();
  terrain = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({color: 0x4a5b3c, roughness: 1, flatShading: true}));
  terrain.position.set(g.x0_m + width / 2, 0, g.z0_m + depth / 2);
  scene.add(terrain);
  terrain.userData.grid = g;
  terrain.userData.heights = heights;
}
// Static arrows show the current the engine measured in its wet cells. They
// are indicators, not animated water parcels; their length is capped for
// readability and is not a claim about displacement or energy.
function waterCurrentArrows(samples, cell) {
  const moving = samples.filter(s => Array.isArray(s.at_m) && s.at_m.length === 3 &&
    s.at_m.every(Number.isFinite) && Array.isArray(s.velocity_m_s) && s.velocity_m_s.length === 2 &&
    s.velocity_m_s.every(Number.isFinite) && Math.hypot(...s.velocity_m_s) > .025);
  if (!moving.length) return null;
  const coordinates = [], stride = Math.max(1, Math.ceil(moving.length / 96)), shown = [];
  for (let k = 0; k < moving.length; k += stride) {
    const sample = moving[k], [x,y,z] = sample.at_m, [vx,vz] = sample.velocity_m_s;
    const speed = Math.hypot(vx,vz), ux = vx / speed, uz = vz / speed;
    const length = Math.max(.06, Math.min(.18, cell * 1.4)), head = length * .32;
    const a = [x - ux * length / 2,y + .008,z - uz * length / 2];
    const b = [x + ux * length / 2,y + .008,z + uz * length / 2];
    coordinates.push(...a,...b,...b,b[0]-ux*head-uz*head*.55,b[1],b[2]-uz*head+ux*head*.55,
      ...b,b[0]-ux*head+uz*head*.55,b[1],b[2]-uz*head-ux*head*.55);
    shown.push(sample);
  }
  const line = new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position',
    new THREE.Float32BufferAttribute(coordinates,3)),
    new THREE.LineBasicMaterial({color:0xb8f4ff,transparent:true,opacity:.95,depthWrite:false}));
  line.userData.samples = shown;
  return line;
}
// The water: each wet column's surface, in millimetres above base_m.
function syncWater(w) {
  if (water) { scene.remove(water); water.geometry.dispose(); water.material.dispose(); water = null; }
  if (riverFlow) { scene.remove(riverFlow); riverFlow.geometry.dispose(); riverFlow.material.dispose(); riverFlow = null; }
  riverState = null;
  if (!w || !terrain || !w.box || !w.box[2] || !w.surface_mm_b64) return;
  const g = terrain.userData.grid, [i0, j0, ni, nj] = w.box;
  const bytes = Uint8Array.from(atob(w.surface_mm_b64), c => c.charCodeAt(0));
  const mm = new Uint16Array(bytes.buffer, 0, bytes.length / 2);
  // Native flow_b64 stores signed vx,vz pairs, each count representing
  // 0.05 m/s and capped at +/-6.35 m/s (Environment::waterBox).
  const flowBytes = w.flow_b64 ? Uint8Array.from(atob(w.flow_b64), c => c.charCodeAt(0)) : null;
  const flow = flowBytes && flowBytes.length === 2 * ni * nj ? new Int8Array(flowBytes.buffer) : null;
  const wet = [], samples = [];
  let speedSum = 0, maxSpeed = 0, depthSum = 0, depthCount = 0, capped = false;
  for (let j = 0; j < nj; j++) for (let i = 0; i < ni; i++) {
    const k = j * ni + i, v = mm[k];
    if (!v) continue;
    const at = [g.x0_m + (i0 + i) * g.cell_m, w.base_m + v / 1000, g.z0_m + (j0 + j) * g.cell_m];
    wet.push(at);
    const bed = terrain.userData.heights[(j0+j)*g.nx+i0+i], depth = Math.max(0,at[1]-bed);
    if (Number.isFinite(depth)) { depthSum += depth; depthCount++; }
    if (flow) {
      const velocity = [flow[2*k]*.05,flow[2*k+1]*.05], speed = Math.hypot(...velocity);
      speedSum += speed; maxSpeed = Math.max(maxSpeed,speed);
      capped ||= Math.abs(flow[2*k]) === 127 || Math.abs(flow[2*k+1]) === 127;
      samples.push({at_m:at,velocity_m_s:velocity,depth_m:Number.isFinite(depth)?depth:null});
    }
  }
  if (!wet.length) return;
  const tile = new THREE.PlaneGeometry(g.cell_m, g.cell_m);
  tile.rotateX(-Math.PI / 2);
  water = new THREE.InstancedMesh(tile, new THREE.MeshStandardMaterial({color: 0x3f8fd8, transparent: true, opacity: .72, roughness: .15}), wet.length);
  const m = new THREE.Matrix4();
  wet.forEach((p, k) => water.setMatrixAt(k, m.makeTranslation(p[0], p[1], p[2])));
  scene.add(water);
  riverFlow = waterCurrentArrows(samples,g.cell_m);
  if (riverFlow) scene.add(riverFlow);
  riverState = {t:w.t,wetCells:wet.length,hasCurrent:Boolean(flow),meanSpeed_m_s:flow?speedSum/wet.length:null,
    maxSpeed_m_s:flow?maxSpeed:null,meanDepth_m:depthCount?depthSum/depthCount:null,capped,
    inflow_m3_s:w.in_m3_s,outflow_m3_s:w.out_m3_s,arrows:riverFlow?.userData.samples.length||0};
}
window.machineRiverState = () => riverState && {...riverState,visible:Boolean(riverFlow?.visible),
  samples:(riverFlow?.userData.samples||[]).map(s=>({at_m:[...s.at_m],velocity_m_s:[...s.velocity_m_s],depth_m:s.depth_m}))};

// Ropes and ideal spring depictions follow their two attachment points, fixed
// in its body's own frame and carried by that body's measured pose. Hidden
// once the engine reports the joint gone.
const ropes = [];
const LINK_DOT = new THREE.SphereGeometry(.012, 12, 8);
const linkLook = {hinge: new THREE.MeshBasicMaterial({color: 0xffd34d}), fix: new THREE.MeshBasicMaterial({color: 0xf2f6f8})};
const coilLook=new THREE.MeshStandardMaterial({color:0xaac9de,metalness:.65,roughness:.32});
const latchLook=new THREE.MeshBasicMaterial({color:0xff7153});
function coilGeometry(a,b){
  const points=springCoilPoints(a,b).map(p=>new THREE.Vector3(...p));
  return points.length ? new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points),128,.0035,6,false) : new THREE.BufferGeometry();
}
function syncRopes() {
  for (const r of ropes) { scene.remove(r.line); if (r.line.geometry !== LINK_DOT) r.line.geometry.dispose(); }
  ropes.length = 0;
  if (!machine) return;
  const local = (name, at) => {
    const b = world.bodies.get(name); if (!b) return null;
    const q = new THREE.Quaternion(b.orientation_wxyz[1], b.orientation_wxyz[2], b.orientation_wxyz[3], b.orientation_wxyz[0]);
    return new THREE.Vector3(...at).sub(new THREE.Vector3(...b.position_m)).applyQuaternion(q.invert());
  };
  for (const j of machine.joints) {
    if(j.kind==='fix' && /^your spring \d+ restraint$/.test(j.name)) {
      const localA=local(j.b,j.at_m);if(!localA)continue;
      // Visible outside the plate: a marker of the native restraint, not
      // an extra collider or a separately simulated withdrawal mechanism.
      localA.x-=.045;localA.z+=.085;
      const dot=new THREE.Mesh(LINK_DOT,latchLook);dot.scale.setScalar(1.7);scene.add(dot);
      ropes.push({line:dot,dot:true,name:j.name,a:j.b,localA});continue;
    }
    // A pin or glue a player put between two parts: a dot where they join.
    if (/^your link \d+$/.test(j.name) && (j.kind === 'hinge' || j.kind === 'fix')) {
      const a = local(j.a, j.at_m);
      if (!a) continue;
      const dot = new THREE.Mesh(LINK_DOT, linkLook[j.kind]);
      scene.add(dot);
      ropes.push({line: dot, dot: true, name: j.name, a: j.a, localA: a});
      continue;
    }
    if (j.kind !== 'tie' && j.kind !== 'spring' && j.kind !== 'pulley') continue;
    if (j.hidden) continue;   // a rope's cord, inside the chain drawn as its segments
    const a = local(j.a, j.at_m), b = local(j.b, j.at_b_m);
    if (!a || !b) continue;
    const coil=j.kind==='spring';
    const line = coil ? new THREE.Mesh(coilGeometry(j.at_m,j.at_b_m),coilLook)
      : new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({color:0xd8c9a3}));
    scene.add(line);
    // A pulley's rope runs up over its two fixed points.
    const over = j.kind === 'pulley' ? [new THREE.Vector3(...j.over_a_m), new THREE.Vector3(...j.over_b_m)] : [];
    ropes.push({line,coil, name: j.name, a: j.a, b: j.b, localA: a, localB: b, over});
  }
}
const drumLines = new Map();
function updateRopes() {
  // A rope on a drum: from where the engine says it leaves the drum to where
  // it meets its load.
  for (const j of (readouts.joints || []).filter(j => j.kind === 'drum' && j.leaves && j.meets)) {
    let line = drumLines.get(j.name);
    if (!line) { line = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({color: 0xd8c9a3})); scene.add(line); drumLines.set(j.name, line); }
    line.geometry.setFromPoints([new THREE.Vector3(...j.leaves), new THREE.Vector3(...j.meets)]);
    line.visible = j.attached !== false;
  }
  const gone = new Set((readouts.joints || []).filter(j => j.attached === false).map(j => j.name));
  const at = (name, v) => {
    const b = world.bodies.get(name); if (!b) return null;
    const q = new THREE.Quaternion(b.orientation_wxyz[1], b.orientation_wxyz[2], b.orientation_wxyz[3], b.orientation_wxyz[0]);
    return v.clone().applyQuaternion(q).add(new THREE.Vector3(...b.position_m));
  };
  for (const r of ropes) {
    if (r.dot) {
      const pa = at(r.a, r.localA);
      r.line.visible = Boolean(pa) && !gone.has(r.name) && !hiddenPiece(r.a);
      if (pa) r.line.position.copy(pa);
      continue;
    }
    const pa = at(r.a, r.localA), pb = at(r.b, r.localB);
    r.line.visible = Boolean(pa && pb) && !gone.has(r.name) && !hiddenPiece(r.b);
    if (r.line.visible && r.coil) {
      const span=[...pa.toArray(),...pb.toArray()];
      if(!r.span || span.some((v,i)=>Math.abs(v-r.span[i])>.0001)) {
        r.line.geometry.dispose();r.line.geometry=coilGeometry(pa.toArray(),pb.toArray());r.span=span;
      }
    } else if(r.line.visible)r.line.geometry.setFromPoints([pa, ...r.over, pb]);
  }
}

// Goal zones (a station done when a part is inside a box): drawn as a
// translucent green box where the engine will look.
const zones = [];
function syncZones() {
  for (const z of zones) {scene.remove(z);z.traverse(child=>{
    if(!child.isSprite)child.geometry?.dispose();
    for(const material of Array.isArray(child.material)?child.material:[child.material]){material?.map?.dispose();material?.dispose();}
  });}
  zones.length = 0;
  const shown = (machine?.stations || []).map(s => s.done_when && s.done_when.in_zone).filter(Boolean);
  // A level's goal zone is drawn even before the piece it is about is placed
  // (the goal is then left out of the run): it is where to build.
  const goalZone = LEVEL_MODE && level && level.goal && level.goal.station.done_when.in_zone;
  if (goalZone && !shown.some(z => z.at_m.every((v, i) => v === goalZone.at_m[i]))) shown.push(goalZone);
  if(LEVEL_MODE && level?.goal?.area)shown.push(level.goal.area);
  for (const z of shown) {
    const box = new THREE.Mesh(new THREE.BoxGeometry(...z.size_m),
      new THREE.MeshStandardMaterial({color: 0x3fbf6f, transparent: true, opacity: .22, depthWrite: false}));
    box.position.set(...z.at_m);
    box.add(new THREE.LineSegments(new THREE.EdgesGeometry(box.geometry), new THREE.LineBasicMaterial({color: 0x5fe08f})));
    scene.add(box); zones.push(box);
  }
}
window.machineGoalGuideState=()=>zones.map(z=>({at_m:z.position.toArray(),textLabels:z.children.filter(c=>c.isSprite).length}));

// Gas pushing a piston (steam under a piston, a cannon's breech): its column,
// where the engine says it is, tinted by its measured temperature. Not drawn
// once it is open to the air.
const gasColumns = new Map();
function updateGas() {
  const live = new Set();
  for (const g of readouts.gas || []) {
    if (!g.piston || g.vent_open || !(g.area_m2 > 0) || !(g.volume_m3 > 0) || !g.axis) continue;
    live.add(g.name);
    let mesh = gasColumns.get(g.name);
    if (!mesh) {
      mesh = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1),
        new THREE.MeshStandardMaterial({color: 0xdfe8f0, transparent: true, opacity: .35, roughness: .9, depthWrite: false}));
      scene.add(mesh); gasColumns.set(g.name, mesh);
    }
    const side = Math.sqrt(g.area_m2), length = g.volume_m3 / g.area_m2;
    const axis = new THREE.Vector3(...g.axis).normalize();
    mesh.scale.set(side, length, side);
    mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), axis);
    mesh.position.copy(new THREE.Vector3(...g.base_m).addScaledVector(axis, length / 2));
    mesh.material.color.setHex(heatTint(0xdfe8f0, g.temperature_k || 293));
  }
  for (const [name, mesh] of gasColumns) if (!live.has(name)) { scene.remove(mesh); mesh.geometry.dispose(); gasColumns.delete(name); }
}

function updateWires() {
  updateRopes();
  updateGas();
  const terminals=terminalMap(machine.electrical);
  for (const w of wires) {
    if(w.contactCircuit) {
      const diagram=contactCircuitDiagram(w.contactCircuit,machine,world.bodies),leg=diagram?.legs.find(l=>l.id===w.leg);
      w.line.visible=Boolean(leg)&&w.route?.length>1&&!flowGroup.visible;
      if(leg) {
        const route=wireRoute(leg.a,leg.b,w.lane);
        if(JSON.stringify(route)!==JSON.stringify(w.route)) {
          w.line.geometry.dispose();w.line.geometry=new THREE.TubeGeometry(routedCurve(leg.a,leg.b,w.lane),64,.009,6,false);w.route=route;
        }
      }
      const live=readouts.circuits?.find(c=>c.name===w.name);
      w.line.material.color.setHex(Math.abs(live?.current_a||0)>1e-4?0xffd34d:w.color);
      continue;
    }
    if (w.powerCable) {
      const a=powerPortAt(w.fromPort),b=powerPortAt(w.toPort);
      const route=a&&b?wireRoute(a,b,0):[];
      w.connected=Boolean(a&&b);w.line.visible=w.connected&&route.length>1;
      if (a&&b&&JSON.stringify(route)!==JSON.stringify(w.route)) {
        w.line.geometry.dispose();w.line.geometry=new THREE.TubeGeometry(routedCurve(a,b,0),64,.008,6,false);w.points_m=[a,b];w.route=route;
      }
      const panel = readouts.machines?.solar_panels?.find(p => p.name === w.panel);
      w.line.material.color.setHex(panel?.power_w > .01 ? 0xffd34d : 0x83bbff);
      continue;
    }
    if (w.terminalWire) {
      const a = terminals.get(w.a), b = terminals.get(w.b);
      if (a && b) {
        const route = wireRoute(a,b,w.lane);
        if (JSON.stringify(route)!==JSON.stringify(w.route)) {
          w.line.geometry.dispose();
          w.line.geometry = new THREE.TubeGeometry(routedCurve(a,b,w.lane),64,w.radius,6,false);
          w.route = route;
        }
      }
      w.connected=Boolean(a&&b); w.line.visible=w.connected&&w.route?.length>1;
      const live = readouts.electrical?.wires?.find(row => row.name === w.name);
      w.line.material.color.setHex(Math.abs(live?.current_a || 0) > 1e-4 ? 0xffd34d : w.color);
      continue;
    }
    const at = name => { const b = world.bodies.get(name); return b ? b.position_m : null; };
    const pts = [at(w.from), w.via, w.to ? at(w.to) : w.toPoint].filter(Boolean).map(p => new THREE.Vector3(...p));
    w.line.geometry.setFromPoints(pts);
    const live = (readouts.circuits || []).find(c => c.name === w.name);
    const flowing = Math.abs(live?.current_a || 0) > 1e-4;
    w.line.material.color.setHex(flowing ? 0xffd34d : 0x6b7680);
  }
}

// ---- the panel ---------------------------------------------------------------
function renderStations() {
  const list = $('stations'); list.replaceChildren();
  const live = readouts.stations || [];
  const current = live.findIndex((s, i) => !s.done && machine.stations[i] && machine.stations[i].done_when);
  machine.stations.forEach((s, i) => {
    const li = document.createElement('li');
    li.dataset.index = String(i); li.title = 'Look at this station';
    const state = live[i];
    if (state && state.done) li.className = 'done'; else if (i === current && playing) li.className = 'current';
    const head = document.createElement('div'); head.className = 'head';
    const title = document.createElement('span');
    title.textContent = `${i + 1}. ${s.title}` + (state && state.done ? ` ✓ ${describeTime(state.at_s)}` : '');
    const badge = document.createElement('span');
    const kind = (s.maturity || 'calculated').replace(' ', '-');
    badge.className = 'badge ' + kind; badge.textContent = s.maturity || 'calculated';
    head.append(title, badge);
    const shows = document.createElement('div'); shows.className = 'shows'; shows.textContent = s.shows || '';
    const law = document.createElement('div'); law.className = 'law'; law.textContent = s.law || '';
    li.append(head, shows, law);
    list.append(li);
  });
}

function pair(dl, label, value) {
  const div = document.createElement('div'), dt = document.createElement('dt'), dd = document.createElement('dd');
  dt.textContent = label; dd.textContent = value; div.append(dt, dd); dl.append(div);
}

function renderReadings(frame) {
  updatePowerLabels();
  const dl = $('readings'); dl.replaceChildren();
  pair(dl, 'World time', describeTime(frame.t));
  if (riverState) {
    pair(dl,'Water flow',`${((riverState.inflow_m3_s||0)*1000).toFixed(2)} L/s in · ${((riverState.outflow_m3_s||0)*1000).toFixed(2)} L/s out`);
    if (riverState.hasCurrent) pair(dl,'Water current',`${riverState.meanSpeed_m_s.toFixed(2)} m/s mean · ${riverState.capped?'at least ':''}${riverState.maxSpeed_m_s.toFixed(2)} m/s max · arrows show direction (0.05 m/s samples)`);
    if (riverState.meanDepth_m!=null) pair(dl,'Water depth',`about ${riverState.meanDepth_m.toFixed(3)} m mean across ${riverState.wetCells} visible wet cells`);
  }
  for (const c of readouts.circuits || []) {
    pair(dl, `${c.name}: switch`, c.closed === null ? 'always closed' : c.closed ? 'closed' : 'open');
    pair(dl, `${c.name}: current`, `${(c.current_a || 0).toFixed(2)} A` + (c.heats ? ` · ${(c.coil_w || 0).toFixed(0)} W into ${c.heats}` : '') +
      (c.drives ? ` · driving the motor on ${c.drives}` : ''));
    pair(dl, `${c.name}: energy`, `${((c.source_j || 0) / 1000).toFixed(2)} kJ from the battery` +
      (c.heats ? `, ${((c.into_body_j || 0) / 1000).toFixed(1)} kJ into ${c.heats}` : ''));
  }
  for (const device of readouts.electrical?.devices || []) {
    if (device.kind === 'battery') continue;
    pair(dl, device.name, device.kind === 'switch' ? (device.closed ? 'closed' : 'open') :
      `${(device.current_a || 0).toFixed(3)} A · ${(device.power_w || 0).toFixed(2)} W` +
      (device.kind === 'bulb' ? ` · ${(device.emitted_w || 0).toFixed(2)} W light` :
        device.kind==='capacitor'?` · ${(device.capacitor_voltage_v||0).toFixed(2)} V · ${(device.stored_j||0).toFixed(2)} J stored`:''));
    if (device.kind === 'bulb') {
      const part = machine.electrical.devices.find(row => row.name === device.name)?.part;
      meshes.get(part)?.traverse(object => {
        if (object.material?.emissive) {
          object.material.emissive.setHex(0xffcb64);
          object.material.emissiveIntensity = Math.min(1.5, (device.emitted_w || 0) / .6);
        }
      });
    }
  }
  for (const network of readouts.electrical?.networks || []) {
    pair(dl, `${network.id}: supply`, `${(network.last?.source_current_a || 0).toFixed(3)} A · ` +
      `${(network.ledger?.source_j || 0).toFixed(2)} J from the battery`);
  }
  for (const h of (readouts.heat || []).slice(0, 4))
    pair(dl, h.name, `${h.temperature_k.toFixed(0)} K` + (h.reacting ? ' · burning' : '') + (h.heater_w ? ` · ${h.heater_w.toFixed(0)} W in` : ''));
  for (const c of readouts.cuts || [])
    pair(dl, `${c.blade} → ${c.target}`, c.through ? `cut through: ${(c.area_mm2 || 0).toFixed(0)} mm² for ${(c.work_j || 0).toFixed(2)} J`
      : `${c.kind}: ${(c.area_mm2 || 0).toFixed(0)} mm² cut, ${(c.work_j || 0).toFixed(2)} J`);
  for (const g of readouts.gas || [])
    pair(dl, g.name, `${(g.pressure_kpa || 0).toFixed(0)} kPa · ${(g.temperature_k || 0).toFixed(0)} K` +
      (g.piston ? ` · ${g.piston} pushed ${((g.stroke_m || 0) * 1000).toFixed(0)} mm` : ''));
  for (const b of readouts.machines?.batteries || [])
    pair(dl, b.name, `${((b.charge_j || 0) / 1000).toFixed(1)} kJ of ${((b.capacity_j || 0) / 1000).toFixed(0)} kJ`);
  for (const s of readouts.machines?.solar_panels || [])
    pair(dl, s.name, s.shaded ? `in shadow (${s.shaded_by || 'something'})` : `${(s.sunlight_w || 0).toFixed(0)} W of sunlight, ${(s.power_w || 0).toFixed(1)} W into the battery`);
  for (const m of readouts.machines?.motors || [])
    pair(dl, `Motor ${m.id}`, `${(m.speed_rad_s || 0).toFixed(1)} rad/s · ${(m.torque_n_m || 0).toFixed(2)} N·m · ${(m.power_w || 0).toFixed(0)} W`);
  if (readouts.light) {
    const l = readouts.light;
    pair(dl, 'Light', `${(l.sent_w || 0).toFixed(1)} W traced, ${(l.heated_w || 0).toFixed(1)} W of it warming parts`);
    for (const c of l.photocells || []) pair(dl, `${c.name} (light sensor)`, `${(c.power_w || 0).toFixed(3)} W`);
  }
  if (readouts.pour)
    pair(dl, 'Poured water', `${readouts.pour.poured_l.toFixed(1)} L poured, ${readouts.pour.landed_l.toFixed(1)} L in the stream, ${readouts.pour.in_air_l.toFixed(1)} L falling`);
  for (const source of readouts.pour?.sources || [])
    if (source.finite) pair(dl, source.name, `${source.valve_open ? 'open' : 'closed'} · ${((source.remaining_m3 || 0) * 1000).toFixed(2)} L left · ${((source.received_m3 || 0) * 1000).toFixed(2)} L received`);
  for (const j of (readouts.joints || []).filter(j => j.kind === 'hinge').slice(0, 3))
    pair(dl, j.name, `${(j.degrees || 0).toFixed(1)}°`);
  for (const j of (readouts.joints || []).filter(j => j.kind === 'spring'))
    pair(dl, j.name, `${(j.force_n || 0).toFixed(2)} N · ${(j.stored_j || 0).toFixed(3)} J stored · ${(j.rest_m || 0).toFixed(3)} m relaxed`);
  for(const air of machine?.airflows||[])pair(dl,air.name,`${Math.hypot(...air.velocity_m_s).toFixed(1)} m/s · open-air field`);
  for(const load of readouts.airflow||[])if(Math.hypot(...load.force_n)>.001)
    pair(dl,`${load.body} · air drag`,`${Math.hypot(...load.force_n).toFixed(2)} N · ${load.work_j.toFixed(3)} J external work`);
  const pieces = [...world.bodies.keys()].filter(n => n.includes(' piece ')).length;
  if (pieces) pair(dl, 'Broken pieces', String(pieces));
  pair(dl, 'Calculation', `${frame.pace.compute_s.toFixed(1)} s of engine time, ${frame.pace.fracture_s.toFixed(1)} s of it breaking`);
}

function addEvents(events) {
  const ol = $('events');
  for (const e of events) {
    const li = document.createElement('li');
    li.textContent = `${describeTime(e.t)} · ${e.text}`;
    ol.prepend(li);
  }
  while (ol.children.length > 80) ol.lastChild.remove();
}

function clockMessage(text) {
  $('clock').hidden = false;
  $('clock').textContent = text;
}
function showTestBusy(message='Test simulation is busy') {
  if(!TEST_BUILD)return;
  $('test-busy').querySelector('strong').textContent=message;
  $('test-busy').hidden=false;
  $('clock').hidden=true;
}
$('test-takeover').addEventListener('click',async()=>{
  const button=$('test-takeover');button.disabled=true;
  try {await rebuildLevel(false,{takeOver:true});}
  finally {button.disabled=false;}
});
function sceneReadoutTop(rect) {
  return Math.max(6, ...[$('clock'), $('viewer-corner')]
    .filter(el => !el.hidden && el.getClientRects().length)
    .map(el => el.getBoundingClientRect().bottom - rect.top + 6));
}
function renderClock(frame) {
  const behind = frame.pace.behind_s;
  // A level runs at real time, so its clock leaves the speed out.
  let text = `World ${describeTime(frame.t)} · ` + (LEVEL_MODE ? '' : `${frame.speed}× · `) + (frame.error ? 'stopped: ' + frame.error :
    frame.playing ? 'calculating live' : frame.t > 0 ? (LEVEL_MODE && scored ? 'run over' : 'paused')
    : LEVEL_MODE ? 'ready: press Try It!'+(level?.release_to_start&&machine?.joints.some(j=>j.name.endsWith(' restraint'))&&!ghost?' · Release spring to start':'') : 'ready: press Start');
  if (frame.playing && behind > .25) text += ` · ${behind.toFixed(1)} s behind real time while the engine works`;
  clockMessage(text);
  $('clock').hidden = !frame.error && !frame.playing && frame.t === 0;
  $('start').hidden=Boolean(LEVEL_MODE&&scored&&lastRun&&lastRun.goal_at_s==null);
  $('start').textContent = frame.playing ? 'Pause' : !LEVEL_MODE ? (frame.t > 0 ? 'Continue' : 'Start')
    : frame.t > 0 ? (scored ? 'Try It!' : 'Continue') : 'Try It!';
}

// ---- building and running --------------------------------------------------------
// Close and open in order, including an open still awaiting its response.
// Otherwise a rebuild competes with its own previous world on a one-slot host.
let worldTask = Promise.resolve();
function queueWorldTask(task) {
  const result = worldTask.then(task);
  worldTask = result.catch(() => {});
  return result;
}
function releaseWorld() {
  const closing = session;
  session = null; playing = false;
  return queueWorldTask(async () => {
    if (closing) await api({op: 'close', session: closing});
  });
}
async function build(next, start, request) {
  await stopSwitchDrag();
  closeHeatInspection();
  syncThermalSpots(null);
  const mine = ++polling;
  $('test-busy').hidden=true;
  const released = releaseWorld();
  $('power-labels').replaceChildren(); powerLabels.clear(); powerMessage('');
  clockMessage('Building in the engine…');
  for (const [, mesh] of meshes) { scene.remove(mesh); disposeBodyGeometry(mesh); }
  meshes.clear(); $('events').replaceChildren();
  try {
    await released;
    const opened = await queueWorldTask(async () => {
      if (mine !== polling) return null;
      const reply = await api(request || {op: 'open', spec: next});
      if (mine !== polling) {
        await api({op: 'close', session: reply.session});
        return null;
      }
      session = reply.session;
      return reply;
    });
    if (!opened || mine !== polling) return {};
    spec = request ? opened.machine : next; machine = opened.machine; session = opened.session; readouts = opened.readouts || {};
    drawAirflows();
    world = mergeFrame({seq: 0, t: 0, bodies: new Map()}, opened);
    electricalStartPoses.clear();
    for (const [name,body] of world.bodies) electricalStartPoses.set(name,
      {position_m:[...body.position_m],orientation_wxyz:[...body.orientation_wxyz]});
    $('title').textContent = LEVEL_MODE && level ? levelTitle(level) : machine.title;
    $('spec').value = JSON.stringify(level && level.free ? (activeDesign?.draft.base || sandboxBase) : spec, null, 1);
    const notes = $('notes'); notes.replaceChildren();
    for (const n of machine.notes || []) { const li = document.createElement('li'); li.textContent = n; notes.append(li); }
    for (const [, line] of drumLines) { scene.remove(line); line.geometry.dispose(); }
    drumLines.clear();
    if (parcels) { scene.remove(parcels); parcels.geometry.dispose(); parcels = null; }
    syncGround(opened.ground); syncWater(opened.water); syncParcels(opened.parcels);
    syncMeshes([...world.bodies.values()]); syncWires(); syncRopes(); syncZones(); updateWires(); placeSun(); syncLight(); renderStations(); renderReadings(opened); renderClock(opened); renderMachineControls();
    // A free build is framed once, as it opens: after that the view is
    // where the player put it, not moved every time a piece is set down.
    if (!(LEVEL_MODE && level && level.free && framedFree)) frameCamera();
    if (LEVEL_MODE && level && level.free) framedFree = true;
    drawLensOutlines();
    if (start) await setPlaying(true); else scheduleLaserPreview(0);
    poll(mine);
    return opened;
  } catch (e) {
    if (mine !== polling) return {};
    clockMessage(e.data?.code === 'site_busy'
      ? 'Simulation busy. Close another game tab or wait a moment, then press Try It!.'
      : 'Could not build: ' + e.message);
    if(e.data?.code==='site_busy')showTestBusy();
    if (e.data && e.data.problems) addEvents(e.data.problems.map(text => ({t: 0, text})));
    throw e;
  }
}

async function setPlaying(run) {
  // An idle session is rebuilt before starting the command queue.
  if (!session) { if (LEVEL_MODE && run && level) await rebuildLevel(true); return; }
  const mine=polling,requestedSession=session;
  const previous=playPending;
  let finish;
  const command=new Promise(resolve=>{finish=()=>{resolve();if(playPending===command)playPending=null;};});
  playPending=command;
  try {
    if(previous)await previous;
    if(mine!==polling||session!==requestedSession)return;
    if(!run)await stopSwitchDrag();
    if(run){clearTimeout(previewTimer);previewAsk++;clearPreview();resetLaserPreview();}
    let frame;
    try {frame=await api({op:'play',session:requestedSession,running:run,speed:Number($('speed').value)});}
    catch(error){
      if(mine!==polling||session!==requestedSession)return;
      if(error.status===410&&LEVEL_MODE&&run&&level){session=null;finish();await rebuildLevel(true);return;}
      throw error;
    }
    if(mine!==polling||session!==requestedSession)return;
    playing=frame.playing;renderClock(frame);if(wake)wake();
  } finally {finish();}
}

// At most 20 frame requests a second while running and one a second while
// paused: each request is its own connection to this server, and asking as
// fast as frames arrive exhausted the machine's sockets.
const RUNNING_MS = 50, PAUSED_MS = 1000;
let wake = null;
let liveControlPending = false;
let liveControlRequest = null;
async function poll(mine) {
  let last = 0;
  while (mine === polling && session) {
    const gap = (playing ? RUNNING_MS : PAUSED_MS) - (performance.now() - last);
    if (gap > 0) await new Promise(r => { wake = r; setTimeout(r, gap); });
    wake = null;
    if (mine !== polling || !session) return;
    last = performance.now();
    try {
      const frame = await api({op: 'frame', session, after: world.seq, wait_ms: playing ? 120 : 0});
      if (mine !== polling) return;
      const changed = frame.bodies;
      world = mergeFrame(world, frame);
      readouts = frame.readouts || readouts; playing = frame.playing; lastFrame = frame;
      syncMeshes(changed.map(b => world.bodies.get(b.name)));
      if (frame.water) syncWater(frame.water);
      if (frame.parcels) syncParcels(frame.parcels);
      updateWires(); syncLight(); addEvents(frame.events); renderStations(); renderReadings(frame); renderClock(frame);
      watchGoal(frame);
    } catch (e) {
      if (mine !== polling) return;
      if (e.status === 410) {
        clockMessage(LEVEL_MODE ? 'The server closed this level while it sat idle; press Try It! to build it again'
          : 'This machine stopped running on the server; press Set up again');
        showTestBusy('Test simulation moved');
        session = null; return;
      }
      clockMessage('Connection problem: ' + e.message);
      await new Promise(r => setTimeout(r, 1500));
    }
  }
}

// ---- camera -------------------------------------------------------------------
let framedFree = false;
function frameCamera(includeGhost=false) {
  // A free build's table corners mark where pieces can go; the view is of what is built.
  const pts = [];
  for (const body of world.bodies.values()) {
    if (body.name.startsWith('table corner ')) continue;
    const mesh = meshes.get(body.name);
    const bounds = new THREE.Box3();
    mesh?.updateWorldMatrix(true, true);
    // Composite native shapes keep a disposal shim on their Group. Only
    // actual rendered geometry contributes to the bounds.
    mesh?.traverse(child => {
      if (child.isMesh && child.geometry?.isBufferGeometry)
        bounds.union(new THREE.Box3().setFromObject(child));
    });
    if (!bounds.isEmpty()) pts.push(bounds.min.toArray(), bounds.max.toArray());
    else pts.push(body.position_m);
  }
  if(includeGhost && ghostGroup.children.length) {
    const bounds=new THREE.Box3();ghostGroup.updateWorldMatrix(true,true);
    ghostGroup.traverse(child=>{if(child.isMesh && child.geometry?.isBufferGeometry)bounds.union(new THREE.Box3().setFromObject(child));});
    if(!bounds.isEmpty())pts.push(bounds.min.toArray(),bounds.max.toArray());
  }
  // A level's goal zone is in the picture too, and the ground under it:
  // where the player is to build, even before anything stands there.
  const zone = LEVEL_MODE && level && level.goal && (level.goal.station.done_when.in_zone || level.goal.area);
  if (zone) pts.push(zone.at_m, [zone.at_m[0], 0, zone.at_m[2]]);
  // An empty table: its middle, from a little way off.
  if (!pts.length && LEVEL_MODE && level && level.free) pts.push([-1, 0, -.6], [1, .8, .6]);
  for (let i=pts.length-1;i>=0;i--) if (!pts[i]?.every(Number.isFinite)) pts.splice(i,1);
  if (!pts.length) return;
  const lo = [0, 1, 2].map(i => Math.min(...pts.map(p => p[i]))), hi = [0, 1, 2].map(i => Math.max(...pts.map(p => p[i])));
  // A level is looked at from half its height (its goal zone is often high), a little further back.
  goal.set((lo[0] + hi[0]) / 2, Math.max(.3, (lo[1] + hi[1]) / (zone ? 2 : 3)), (lo[2] + hi[2]) / 2);
  target.copy(goal);
  // Fit full geometry, including rotated walls, rather than just body centers.
  // A bounding sphere around the look-at point fits either aspect ratio.
  const half = Math.min(camera.fov * Math.PI / 360, Math.atan(Math.tan(camera.fov * Math.PI / 360) * camera.aspect));
  const radius = Math.hypot(...lo.map((low, i) => Math.max(Math.abs(low - goal.getComponent(i)), Math.abs(hi[i] - goal.getComponent(i)))));
  distance = Math.min(40, Math.max(level?.camera_min_m || (zone ? 2.2 : 1.6), 1.12 * radius / Math.sin(half)));
  azimuth = -.25; elevation = .38;
}

// A scripted view, for scripts/film_machine.py: where the camera looks from
// (azimuth and elevation in radians, distance in metres) and at what point.
// It stops following, as dragging the view does.
window.machineView = ({azimuth: a, elevation: e, distance: d, at} = {}) => {
  follow = false; $('follow').setAttribute('aria-pressed', 'false');
  if (Number.isFinite(a)) azimuth = a;
  if (Number.isFinite(e)) elevation = e;
  if (Number.isFinite(d)) distance = d;
  if (Array.isArray(at) && at.length === 3) { goal.set(...at); target.copy(goal); }
};

// And where a point in the world is on the page, for a script that clicks
// where a person would (tests of placing a piece by clicking).
window.machineScreenPoint = point => {
  freshView();
  const p = new THREE.Vector3(...point).project(camera), rect = renderer.domElement.getBoundingClientRect();
  return [rect.left + (p.x + 1) / 2 * rect.width, rect.top + (1 - p.y) / 2 * rect.height];
};

function resize() {
  const w = view.clientWidth, h = view.clientHeight;
  if (!w || !h) return;
  const vertical = camera.fov * Math.PI / 360;
  const oldHalf = Math.min(vertical, Math.atan(Math.tan(vertical) * camera.aspect));
  renderer.setSize(w, h, false); camera.aspect = w / Math.max(1, h); camera.updateProjectionMatrix();
  const half = Math.min(vertical, Math.atan(Math.tan(vertical) * camera.aspect));
  // Preserve the framing when the phone rotates.
  distance = Math.min(40, distance * Math.sin(oldHalf) / Math.sin(half));
  positionLevelIntroduction();
}
addEventListener('resize', resize);

const pointers = new Map();
let pinch = 0;
// Once a second finger joins, keep the entire gesture for the camera until
// every finger lifts. The remaining finger must not pick up or move a piece.
let cameraGesture = false;
let sceneDragged = false;
renderer.domElement.addEventListener('pointerdown', e => {
  pointers.set(e.pointerId,[e.clientX,e.clientY]);renderer.domElement.setPointerCapture(e.pointerId);
  if(pointers.size===2){const [a,b]=[...pointers.values()];pinch=Math.hypot(a[0]-b[0],a[1]-b[1]);}
});
renderer.domElement.addEventListener('pointerup', e => { pointers.delete(e.pointerId); pinch = 0; });
renderer.domElement.addEventListener('pointercancel', e => { pointers.delete(e.pointerId); pinch = 0; });
function moveCameraPointer(e) {
  const last = pointers.get(e.pointerId); if (!last) return;
  const before = [...pointers.values()];
  pointers.set(e.pointerId, [e.clientX, e.clientY]);
  if (pressedAt && Math.hypot(e.clientX - pressedAt[0], e.clientY - pressedAt[1]) >= 6) sceneDragged = true;
  if (draggingGhost || pulling || switchDragging) return;
  if (pressedAt && !cameraGesture && Math.hypot(e.clientX - pressedAt[0], e.clientY - pressedAt[1]) < 6) return;
  if (pointers.size === 2) {
    // Two fingers: apart and together zoom, moved together turn the view
    // (one finger moves a piece being placed, on a touch screen).
    const [p0, q0] = before;
    const [a, b] = [...pointers.values()], gap = Math.hypot(a[0] - b[0], a[1] - b[1]);
    if (pinch) distance = Math.min(40, Math.max(.4, distance * pinch / gap));
    azimuth -= ((a[0] + b[0]) - (p0[0] + q0[0])) / 2 * .006;
    elevation = Math.min(1.45, Math.max(.05, elevation + ((a[1] + b[1]) - (p0[1] + q0[1])) / 2 * .006));
    pinch = gap; return;
  }
  azimuth -= (e.clientX - last[0]) * .006;
  elevation = Math.min(1.45, Math.max(.05, elevation + (e.clientY - last[1]) * .006));
}
renderer.domElement.addEventListener('pointermove',moveCameraPointer);
view.addEventListener('wheel', e => {
  // A trackpad pinch belongs to the whole scene, including floating sockets
  // and labels. Ordinary wheel scrolling over controls keeps its behavior.
  if (!e.ctrlKey && e.target !== renderer.domElement) return;
  e.preventDefault();
  if (switchDragging) return;
  if (ghost && !e.ctrlKey && (e.shiftKey || e.altKey)) return;
  const previous = distance;
  // Desktop trackpad pinches arrive as Ctrl+wheel, usually only a few
  // pixels per event. Ordinary wheels retain their existing sensitivity.
  const pixels = e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? view.clientHeight : 1);
  distance = Math.min(40, Math.max(.4, distance * Math.exp(pixels * (e.ctrlKey ? .01 : .001))));
  // Zoom while holding a piece without changing its position under the new
  // camera. Subsequent movement is relative to this new grab ray.
  if (ghost && draggingGhost) {
    const at = pointers.get(draggingGhost.id);
    const from = at && slidePoint(at[0], at[1], draggingGhost.y);
    if (!from) { distance = previous; return; }
    Object.assign(draggingGhost, {from, x: ghost.p.x_m ?? 0, z: ghost.p.z_m ?? 0});
  }
}, {passive: false});
renderer.domElement.addEventListener('contextmenu', e => e.preventDefault());

// The camera where the view says it is. A frame drawn does this; so does
// anything that picks from the view (where a piece goes, what is under the
// pointer), with every part where it stands -- a press can come before the
// first frame after a change (a slow phone, a level just built), and it must
// not aim at the view as it was before.
function aimCamera() {
  $('view-zoom').value=Math.round(100*Math.log(40/distance)/Math.log(100));
  camera.position.set(target.x + distance * Math.cos(elevation) * Math.sin(azimuth), target.y + distance * Math.sin(elevation),
                      target.z + distance * Math.cos(elevation) * Math.cos(azimuth));
  camera.lookAt(target);
}
function freshView() { aimCamera(); camera.updateMatrixWorld(); scene.updateMatrixWorld(); }
function pointerRay(clientX, clientY) {
  freshView();
  const rect = renderer.domElement.getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2((clientX - rect.left) / rect.width * 2 - 1, -(clientY - rect.top) / rect.height * 2 + 1), camera);
}

function render() {
  requestAnimationFrame(render);
  if (follow && machine && playing) {
    const f = focusPoint(readouts.stations, machine.stations, world.bodies);
    if (f) { goal.set(f.at[0], Math.max(.25, f.at[1]), f.at[2]); distance += (Math.max(2.2, Math.min(distance, 3.4)) - distance) * .02; }
  }
  target.lerp(goal, .05);
  aimCamera();
  // Fade the small squares in distant overviews; major lines remain readable.
  fineGrid.material.opacity=.18*THREE.MathUtils.clamp((12-distance)/6,0,1);
  // A local patch avoids thousands of tiny lines at the horizon. Moving its
  // bounds by whole major squares keeps every line on the same world grid.
  fineGrid.position.x=Math.round(target.x/PLACEMENT_GRID.major_step_m)*PLACEMENT_GRID.major_step_m;
  fineGrid.position.z=Math.round(target.z/PLACEMENT_GRID.major_step_m)*PLACEMENT_GRID.major_step_m;
  if (LEVEL_MODE) { for (const [name, mesh] of meshes) mesh.visible = !hiddenPiece(name); updateGuides(); updateEditGuide(); syncMovePad(); }
  drawPull();
  drawSwitchPull();
  for (const w of wires) {
    if (w.terminalWire) w.line.visible = w.connected!==false && !hiddenPiece(w.name) && !ghost?.electrical;
    if (w.powerCable) w.line.visible=w.connected!==false && !hiddenPiece(w.name);
  }
  updateFlowPreview();
  updateGearMotionFeedback();
  updateLaserPreview();
  updateWaterDisplay();
  positionLensGrip();
  updateContactGaps();
  updateContactCircuitReadings();
  renderer.render(scene, camera);
  view.classList.toggle('choosing-attachment',Boolean(ghost?.p.attachment_version===2||machine?.electrical?.devices?.some(d=>d.attachment_version===2&&d.heats)));
  frameNewConnections();
  positionPieceEditor();
  updatePieceHandles();
  positionPowerLabels();
  positionTerminalLabels();
  drawSceneSockets();
  updatePowerFeedback();
  paintCoachGuide();
}

// ---- controls -----------------------------------------------------------------
$('start').addEventListener('click', () => {
  if (LEVEL_MODE && level) { runLevel(); return; }
  setPlaying(!playing).catch(e => { clockMessage(e.message); });
});
// Reset a challenge to its authored beginning; sandbox resets its built machine.
function resetGame(keep) {
  endGhost(); cancelAttach(); stopSwitchDrag();
  if (!keep) { startOver(false); return; }
  rebuildLevel(false).catch(() => {});
}
$('reset').addEventListener('click', () => {
  if (LEVEL_MODE && level) resetGame(Boolean(level.free));
  else build(spec).catch(() => {});
});
$('restart-pieces').addEventListener('click', () => resetGame(true));
$('speed').addEventListener('change', () => { if (session) api({op: 'play', session, running: playing, speed: Number($('speed').value)}).catch(() => {}); });
$('follow').addEventListener('click', () => { follow = !follow; $('follow').setAttribute('aria-pressed', String(follow)); if (!follow) goal.copy(target); });
// Press a station to look at it. The list is drawn again with every frame, so
// the press is taken on the list itself, as it starts, not as a click.
$('stations').addEventListener('pointerdown', e => {
  const li = e.target.closest('li[data-index]');
  const at = li && machine ? stationPoint(machine.stations[Number(li.dataset.index)], world.bodies) : null;
  if (!at) return;
  follow = false; $('follow').setAttribute('aria-pressed', 'false');
  goal.set(at[0], Math.max(.25, at[1]), at[2]); distance = 2.6;
});
$('build-json').addEventListener('click', async () => {
  let next;
  try { next = JSON.parse($('spec').value); } catch (e) { clockMessage('That is not valid JSON: ' + e.message); return; }
  try {
    // Check the complete overlay before changing the stored design. A bad
    // declaration leaves the last working setup available to reopen.
    await api({op: 'check', level: 'free', base: next, placements});
    remember(); activeDesign.draft.base = next; framedFree = false;
    await rebuildLevel(false);
  } catch (e) { $('verdict').textContent = e.data?.problems?.join('; ') || e.message; }
});
$('undo').addEventListener('click', () => {
  const back = undo.pop(); $('undo').disabled = !undo.length;
  if (back) build(back).catch(() => {});
});

function say(kind, text) {
  const li = document.createElement('li'); li.className = kind; li.textContent = text; $('chat-log').prepend(li);
}

$('chat-form').addEventListener('submit', async e => {
  e.preventDefault();
  if (LEVEL_MODE && level && level.free) { askFree(); return; }
  if (LEVEL_MODE) { askLevel('hint'); return; }
  const message = $('message').value.trim();
  if (!message) return;
  $('send').disabled = true; $('chat-status').textContent = 'The model is writing a declaration; the server checks it and rehearses it once in the engine. This takes up to a few minutes…';
  say('you', message);
  try {
    const r = await api({op: 'chat', message, spec, history});
    history.push({role: 'user', text: message}, {role: 'assistant', text: r.reply});
    history = history.slice(-6);
    if (!r.buildable) {
      say('refused', r.reply + ' — The server could not build it: ' + r.problems.join('; '));
      $('chat-status').textContent = 'Nothing was built. You can rephrase, or edit the machine as data.';
      $('spec').value = JSON.stringify(r.spec, null, 1);
      return;
    }
    say('model', r.reply + ` (${r.parts} parts, checked in ${r.attempts} ${r.attempts === 1 ? 'try' : 'tries'})`);
    if (r.rehearsal && r.rehearsal.new_stations.length) say(r.rehearsal.new_stations.every(s => s.happened) ? 'model' : 'refused',
      'Rehearsed once in the engine: ' + r.rehearsal.new_stations.map(s => s.title + (s.happened ? ` happened at ${describeTime(s.at_s)}` : ' did not happen')).join('; ') + '.');
    undo.push(spec); $('undo').disabled = false;
    $('message').value = '';
    $('chat-status').textContent = 'Building it in the engine…';
    await build(r.spec, true);
    $('chat-status').textContent = 'Built. The engine is calculating it now.';
  } catch (err) {
    say('refused', err.message);
    $('chat-status').textContent = '';
  } finally { $('send').disabled = false; }
});

fetch(appPath('/api/checkpoint')).then(r => r.ok ? r.json() : null).then(c => {
  if (!c) return;
  $('build').textContent = `${c.environment === 'test' ? 'TEST · ' : ''}${(c.website_revision || 'unknown').slice(0, 7)}${c.local_changes ? ' + local edits' : ''}`;
  $('build').title = c.branch ? `Branch: ${c.branch}` : '';
}).catch(() => {});


// ---- the puzzles (/play) ---------------------------------------------------------
// A level is a fixed machine, a goal and a tray. The player adds pieces from
// the tray and turns their knobs; the server composes the machine and the
// engine runs it. The stars come from what the engine measured.
const params = new URLSearchParams(location.search);
const LEVEL_MODE = true;
let levels = [], level = null, placements = [], placedCost = [], placedEnergy = {}, helped = false, scored = false, lastRun = null, rebuildTimer = null;
let generatedLevel = null;
let freeLevel = null;
let sandboxBase = null, sandboxTemplates = [], activeDesign = null, sandboxObjects = [];
function sandboxRequest() { const base=ghost?.baseObject ? ghost.base || ghost.originalBase : activeDesign?.draft.base; return level?.free && base ? {base} : {}; }

// ---- the ghost: a piece before it is set down ------------------------------------
// A see-through copy of a piece. It stays put until deliberately dragged;
// its knobs can be changed and turned
// any way, and then set down. It is nothing in the engine meanwhile: the
// server compiles it where it would go (set down on what is there, turned as
// it is turned) and says why it could not go there. Blue fits, red does not
// (green is the level's own: where the goal is).
// Only when it is set down does the engine build it.
let ghost = null, pressedAt = null, draggingGhost = null;
const raycaster = new THREE.Raycaster();
const ghostLook = {
  fits: new THREE.MeshStandardMaterial({color: 0x6cc6ff, transparent: true, opacity: .35, depthWrite: false, roughness: .6}),
  refused: new THREE.MeshStandardMaterial({color: 0xff5f5f, transparent: true, opacity: .4, depthWrite: false, roughness: .6})};
const ghostEdge = {fits: new THREE.LineBasicMaterial({color: 0xcdeeff}), refused: new THREE.LineBasicMaterial({color: 0xffc2c2})};
const ghostGroup = new THREE.Group();
scene.add(ghostGroup);
const TURN_KEYS = {q: ['yaw_deg', 1], e: ['yaw_deg', -1], r: ['pitch_deg', 1], f: ['pitch_deg', -1], z: ['roll_deg', -1], c: ['roll_deg', 1]};

function ghostName() { return ghost?.baseObject?.name || (ghost ? `your ${ghost.p.piece} ${ghost.index + 1}` : ''); }
// The piece picked up is hidden while its ghost is out; Cancel shows it again.
function hiddenPiece(name) { return ghost?.baseObject ? ghost.baseObject.parts.includes(name) : Boolean(ghost && ghost.was) && (name === ghostName() || name.startsWith(ghostName() + ' ')); }
function ghostPlacements() { const list = placements.slice(); if(!ghost.baseObject)list[ghost.index] = ghost.p; return list; }

// A knob set as its slider would set it: on its step, within its range.
function setKnob(p, key, v) {
  const r = trayItem(p.piece).knobs[key];
  if(r?.choices) {
    if(!r.choices.includes(v) || p[key]===v)return false;
    p[key]=v; return true;
  }
  if (!r || r.choices || r.part || r.hinge || r.terminal || r.power_port || !Number.isFinite(v)) return false;
  if (r.turning) v = ((v + 180) % 360 + 360) % 360 - 180;
  // On its step counted from its minimum, as the slider steps.
  const step = r.step || 0.01;
  const next = Number(Math.min(r.max, Math.max(r.min, r.min + Math.round((v - r.min) / step) * step)).toFixed(4));
  if (next === p[key]) return false;
  p[key] = next;
  if (ghost?.p===p && (key==='x_m'||key==='z_m')) ghost.gridLocks=null;
  return true;
}

function sceneHit(clientX, clientY) {
  pointerRay(clientX, clientY);
  const solid = [ground, ...[...meshes].filter(([name, m]) => m.visible && !hiddenPiece(name)).map(([, m]) => m)];
  const hits = raycaster.intersectObjects(solid, true);
  return hits.length ? hits[0].point : null;
}

function ghostHit(clientX, clientY) {
  pointerRay(clientX, clientY);
  return raycaster.intersectObjects(ghostGroup.children, true).some(h => h.object.isMesh);
}

// Where the other pieces connect, while a piece is placed: a dot at each --
// green where a marble comes in, amber where it goes out, violet a gate's
// paddle -- the one it is joined to bigger.
const portGroup = new THREE.Group();
scene.add(portGroup);
const PORT_DOT = new THREE.SphereGeometry(.018, 14, 10);
const portLook = {in: 0x5fe08f, out: 0xffb347, trigger: 0xc38bff};
function drawPorts(list, joined) {
  for (const c of [...portGroup.children]) portGroup.remove(c);
  for (const q of list) {
    const dot = new THREE.Mesh(PORT_DOT, new THREE.MeshBasicMaterial({color: portLook[q.kind] || 0xffffff, transparent: true,
      opacity: .85, depthTest: false}));
    dot.position.set(...q.at);
    if (joined && joined.to === q.name && joined.port === q.port) dot.scale.setScalar(1.8);
    portGroup.add(dot);
  }
}

// The knob that turns a piece about an axis: the free one, or for the turn
// about the vertical a piece's own (a mirror's angle).
function turnKnob(p, key) {
  const knobs = trayItem(p.piece).knobs;
  if (knobs[key] && pieceKnobVisible(p,key)) return key;
  return key === 'yaw_deg' ? Object.keys(knobs).find(k => knobs[k].turning && pieceKnobVisible(p,k) && k !== 'pitch_deg' && k !== 'roll_deg') : undefined;
}

function turnGhost(key, by) {
  const k = ghost && turnKnob(ghost.p, key);
  if (k && setKnob(ghost.p, k, (ghost.p[k] || 0) + by)) {
    if (ghost.card !== k) { ghost.card = k; clearEditGuide(); renderGhostBar(); }
    showGhostKnobs(); askGhost();
  }
}

// Moving it as it is seen: left, right, away from you and toward you go
// along whichever of the level's ground directions (x, the red guide line;
// z, the blue) is nearest that way on the screen, so a press moves it along
// one guide line; up and down move whatever sets its height, all together
// or not at all (a ramp keeps its slope). A piece with no height of its own
// rests on what is under it.
const HEIGHT_KNOBS = ['height_m', 'pivot_height_m', 'bore_height_m', 'drop_from_m', 'top_height_m', 'foot_height_m'];
function heightKnobs(p) {
  const knobs = trayItem(p.piece).knobs;
  return HEIGHT_KNOBS.filter(k => knobs[k] && !knobs[k].choices && pieceKnobVisible(p,k));
}
function viewAxis(dir) {
  // The camera looks along (-sin a, -cos a) on the ground; its right is (cos a, -sin a).
  const [dx, dz] = {right: [Math.cos(azimuth), -Math.sin(azimuth)], left: [-Math.cos(azimuth), Math.sin(azimuth)],
                    forward: [-Math.sin(azimuth), -Math.cos(azimuth)], back: [Math.sin(azimuth), Math.cos(azimuth)]}[dir];
  return Math.abs(dx) >= Math.abs(dz) ? ['x_m', Math.sign(dx)] : ['z_m', Math.sign(dz)];
}
function moveGhostBy(dir, metres) {
  if (!ghost) return false;
  const knobs = trayItem(ghost.p.piece).knobs;
  let moved = false;
  if (dir === 'up' || dir === 'down') {
    const keys = heightKnobs(ghost.p), by = dir === 'up' ? metres : -metres;
    if (!keys.length || keys.some(k => (ghost.p[k] ?? 0) + by > knobs[k].max + 1e-9 || (ghost.p[k] ?? 0) + by < knobs[k].min - 1e-9)) return false;
    for (const k of keys) moved = setKnob(ghost.p, k, (ghost.p[k] ?? 0) + by) || moved;
  } else {
    const [key, sign] = viewAxis(dir);
    if (!knobs[key]) return false;
    moved = setKnob(ghost.p, key, (ghost.p[key] ?? 0) + sign * metres);
  }
  if (moved) { followGhost(); showGhostKnobs(); askGhost(); }
  return moved;
}

// The arrows, over the scene while a piece is placed. Each is drawn in the
// colour of the guide line it moves along, which changes as the view turns.
// Held, an arrow keeps moving it.
const MOVE_STEP_M = 0.02;
const PAD = [['forward', '↑', 'Move it away from you'], ['left', '←', 'Move it left'], ['right', '→', 'Move it right'],
             ['back', '↓', 'Move it toward you'], ['up', '▲', 'Raise it'], ['down', '▼', 'Lower it']];
let padAxes = '';
// A click returns to View without changing placement. Deliberately dragging
// the selected piece resumes Move; dragging empty space always turns the view.
let looking = false;
let editorMode = 'move', lastEdited = null;
function setLooking(on) {
  looking = Boolean(on && ghost);
  draggingGhost = null;
  view.classList.toggle('looking', looking);
  view.classList.remove('grab');
  if (ghost) renderGhostBar();
}
function renderMovePad() {
  const pad = $('move-pad');
  pad.hidden = !LEVEL_MODE || !movableGhost();
  $('scene-mode').hidden = true;
  $('mode-view').setAttribute('aria-pressed', String(looking));
  $('mode-move').setAttribute('aria-pressed', String(!looking));
  padAxes = '';
  if (pad.hidden) { pad.replaceChildren(); return; }
  const high = heightKnobs(ghost.p).length > 0;
  pad.replaceChildren(...PAD.filter(([dir]) => high || (dir !== 'up' && dir !== 'down')).map(([dir, glyph, say]) => {
    const b = holdButton(glyph, () => moveGhostBy(dir, MOVE_STEP_M), {ariaLabel: say, title: say});
    b.dataset.dir = dir;
    return b;
  }));
  syncMovePad();
}
$('mode-view').addEventListener('click', () => setLooking(true));
$('mode-move').addEventListener('click', () => setLooking(false));
function syncMovePad() {
  const pad = $('move-pad');
  if (pad.hidden) return;
  const axes = ['left', 'right', 'forward', 'back'].map(dir => viewAxis(dir)[0]).join();
  if (axes === padAxes) return;
  padAxes = axes;
  // A piece kept in line (level 8's counterweight, under its beam) has no z:
  // an arrow that would move it that way is greyed out.
  const knobs = trayItem(ghost.p.piece).knobs;
  for (const b of pad.querySelectorAll('button[data-dir]')) {
    const dir = b.dataset.dir;
    b.dataset.axis = dir === 'up' || dir === 'down' ? 'y' : viewAxis(dir)[0] === 'x_m' ? 'x' : 'z';
    if (b.dataset.axis !== 'y') b.disabled = !knobs[viewAxis(dir)[0]];
  }
}

// A button that acts when pressed, and again and again while it is held.
function holdButton(text, act, extra = {}) {
  const b = Object.assign(document.createElement('button'), {type: 'button', textContent: text}, extra);
  let wait = null, again = null;
  const stop = () => { clearTimeout(wait); clearInterval(again); wait = again = null; };
  const tick = () => { if (!b.isConnected || b.disabled) stop(); else act(); };
  b.addEventListener('pointerdown', e => {
    e.preventDefault(); stop(); tick();
    wait = setTimeout(() => { again = setInterval(tick, 80); }, 350);
  });
  for (const end of ['pointerup', 'pointerleave', 'pointercancel', 'blur']) b.addEventListener(end, stop);
  // From the keyboard (or a script) a press is a click with no pointer: once.
  b.addEventListener('click', e => { if (e.detail === 0) act(); });
  return b;
}

// Keep ordinary taps and handle drags intact. A stationary hold starts after
// 350 ms and stops on release/cancel, a drag, lost focus, or a removed control.
function repeatOnHold(b, act, {drag=false}={}) {
  let timer=null,press=null,repeated=false;
  const stop=()=>{clearTimeout(timer);timer=null;press=null;window.removeEventListener('blur',stop);document.removeEventListener('visibilitychange',stop);};
  b.classList.add('hold-repeat');
  b.addEventListener('pointerdown',e=>{
    if(e.button!==0||b.disabled)return;
    stop();repeated=false;press={id:e.pointerId,x:e.clientX,y:e.clientY};
    if(!drag)b.setPointerCapture(e.pointerId);
    window.addEventListener('blur',stop);document.addEventListener('visibilitychange',stop);
    const tick=()=>{
      if(!press||!b.isConnected||b.disabled||!b.checkVisibility()){stop();return;}
      repeated=true;act();timer=setTimeout(tick,100);
    };
    timer=setTimeout(tick,350);
  });
  b.addEventListener('pointermove',e=>{
    if(!press||press.id!==e.pointerId)return;
    const rect=b.getBoundingClientRect();
    if(drag?Math.hypot(e.clientX-press.x,e.clientY-press.y)>5:
      e.clientX<rect.left||e.clientX>rect.right||e.clientY<rect.top||e.clientY>rect.bottom)stop();
  });
  for(const end of ['pointerup','pointercancel','lostpointercapture','blur'])b.addEventListener(end,stop);
  b.addEventListener('click',e=>{if(repeated&&e.detail!==0){e.preventDefault();e.stopImmediatePropagation();}},true);
  return stop;
}

// The ghost as last compiled, moved at once by however far its knobs have
// moved since; the server's answer then sets it down again.
function followGhost() {
  if (!ghost || !ghost.drawnAt) return;
  ghostGroup.position.set((ghost.p.x_m ?? 0) - ghost.drawnAt.x, 0, (ghost.p.z_m ?? 0) - ghost.drawnAt.z);
}
function fitNewPieceInView() {
  const bounds = new THREE.Box3().setFromObject(ghostGroup);
  // On short phone views, the addition alone can fit while its target falls
  // below the canvas. Keep the lesson apparatus in this one-time Add framing.
  if(mobileEdgeControls()&&!level?.free)for(const mesh of meshes.values())if(mesh.visible)bounds.expandByObject(mesh);
  if (bounds.isEmpty() || ![...bounds.min.toArray(), ...bounds.max.toArray()].every(Number.isFinite)) return;
  freshView();
  // Keep the player's angle and look-at point. Moving the camera backwards
  // fits the addition and preserves the apparatus already visible beside it.
  // Leave room for the clock and corner controls, including short phone views.
  const horizontal = Math.tan(camera.fov * Math.PI / 360) * camera.aspect * (1 - 2 * Math.min(.2, 24 / view.clientWidth));
  const vertical = Math.tan(camera.fov * Math.PI / 360) * (1 - 2 * Math.min(.3, 60 / view.clientHeight));
  const corner = new THREE.Vector3();
  const settledCamera = camera.clone();
  settledCamera.position.add(new THREE.Vector3().subVectors(goal, target));
  settledCamera.updateMatrixWorld();
  let extra = 0;
  // Check both ends of any existing camera pan so the piece stays in view
  // while the look-at point finishes easing into place.
  for (const eye of [camera, settledCamera]) for (let i = 0; i < 8; i++) {
    corner.set(i & 1 ? bounds.max.x : bounds.min.x, i & 2 ? bounds.max.y : bounds.min.y,
               i & 4 ? bounds.max.z : bounds.min.z).applyMatrix4(eye.matrixWorldInverse);
    extra = Math.max(extra, Math.abs(corner.x) / horizontal + corner.z,
                    Math.abs(corner.y) / vertical + corner.z, eye.near + corner.z);
  }
  if (extra > 0) { distance = Math.min(40, distance + extra); freshView(); }
  // A narrow phone also needs room for all three gear fields beside the
  // complete selected assembly. Do this once on Add; later zooms stay manual.
  if(ghost.p.piece==='gear'&&view.clientWidth<360){
    const rect=view.getBoundingClientRect(),editor=$('piece-editor');
    const obstacles=[...view.querySelectorAll('#clock,#viewer-zoom,#viewer-perspective,#viewer-history')]
      .filter(n=>!n.hidden&&n.getClientRects().length).map(n=>n.getBoundingClientRect());
    for(let i=0;i<20&&distance<40;i++){
      const box=ghostScreenBox(),size=editor.getBoundingClientRect();if(!box)break;
      const at=pieceToolbarPosition(rect,{left:box.x0,right:box.x1,top:box.y0,bottom:box.y1},size,obstacles);
      if(!(at.x<box.x1&&at.x+size.width>box.x0&&at.y<box.y1&&at.y+size.height>box.y0))break;
      distance=Math.min(40,distance*1.1);freshView();
    }
  }
}
function focusSelectedPiece() {
  if (!ghost?.drawnAt || !ghostGroup.children.length) return;
  const bounds = new THREE.Box3().setFromObject(ghostGroup);
  // An optical part makes sense in relation to its source and receiver.
  // Keep both in sight instead of zooming down to a tiny glass holder.
  const optics=ghost.optical_setup;
  if (optics && [...(optics.lenses||[]),...(optics.mirrors||[])].some(p=>(typeof p==='string'?p:p.on)===ghostName())) {
    for (const item of [...(optics.lamps||[]),...(optics.photocells||[])])
      if (item.at_m?.every(Number.isFinite)) bounds.expandByPoint(new THREE.Vector3(...item.at_m));
    for (const name of level.goal?.focus || []) {
      const at=world.bodies.get(name)?.position_m;
      if (at?.every(Number.isFinite)) bounds.expandByPoint(new THREE.Vector3(...at));
    }
  }
  if (bounds.isEmpty()) return;
  if (![...bounds.min.toArray(),...bounds.max.toArray()].every(Number.isFinite)) return;
  bounds.getCenter(goal); target.copy(goal);
  const half = Math.min(camera.fov * Math.PI / 360, Math.atan(Math.tan(camera.fov * Math.PI / 360) * camera.aspect));
  distance = Math.min(40,Math.max(.6, bounds.getSize(new THREE.Vector3()).length() * .65 / Math.tan(half)));
  freshView();
}
$('focus-piece').addEventListener('click',focusSelectedPiece);
$('view-overview').addEventListener('click',()=>{frameCamera();freshView();});

function clearGhostMeshes() {
  for (const c of [...ghostGroup.children]) { ghostGroup.remove(c); c.traverse(o => { if (o.geometry) o.geometry.dispose(); }); }
  for (const c of [...terminalGhostWires.children]) { terminalGhostWires.remove(c); c.geometry.dispose(); }
}

// A piece's parts as the ghost op sends them, built into `into`: each in the
// look lookOf(material) gives it, with its edges drawn when there is an edge.
function buildParts(into, parts, lookOf, edge) {
  const turn = (o, deg) => o.rotation.set(...deg.map(d => d * Math.PI / 180), 'XYZ');   // R = Rx Ry Rz, as the engine turns
  const solid = (geometry, at, deg, kind) => {
    const mesh = new THREE.Mesh(geometry, lookOf(kind));
    if (edge) mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 30), edge));
    mesh.position.set(...at); turn(mesh, deg);
    return mesh;
  };
  for (const part of parts) {
    if (part.shape === 'compound') {
      const body = new THREE.Group();
      body.position.set(...part.at_m); turn(body, part.turn_deg);
      for (const sub of part.parts) body.add(solid(sub.shape === 'cylinder'
        ? new THREE.CylinderGeometry(sub.size_m[0] / 2, sub.size_m[0] / 2, sub.size_m[1], 20)
        : new THREE.BoxGeometry(...sub.size_m), sub.at_m, sub.turn_deg, sub.material || part.material));
      into.add(body);
    } else if (part.shape === 'sphere') into.add(solid(new THREE.SphereGeometry(part.size_m[0] / 2, 24, 16), part.at_m, part.turn_deg, part.material));
    else if (part.shape === 'cone') into.add(solid(new THREE.ConeGeometry(part.size_m[0] / 2, part.size_m[1], 24), part.at_m, part.turn_deg, part.material));
    else into.add(solid(new THREE.BoxGeometry(...part.size_m), part.at_m, part.turn_deg, part.material));
    into.children.at(-1).userData.partName=part.name;
  }
}

function drawGhost(parts, fits) {
  clearGhostMeshes();
  const look = fits ? ghostLook.fits : ghostLook.refused;
  buildParts(ghostGroup, parts, () => look, fits ? ghostEdge.fits : ghostEdge.refused);
  followGhost();
}

// Editing annotations use the server's comparison of compiled part geometry.
// They never participate in picking, collisions, or a physics preview.
const editGroup = new THREE.Group();
scene.add(editGroup);
const editLook = new THREE.MeshBasicMaterial({color: 0xffcf59, transparent: true, opacity: .12, depthTest: false, depthWrite: false});
const editEdge = new THREE.LineBasicMaterial({color: 0xffcf59, depthTest: false, depthWrite: false});
const editArrowLook = new THREE.MeshBasicMaterial({color: 0xffcf59, depthTest: false, depthWrite: false});
const editRestLook = new THREE.LineDashedMaterial({color:0xffdc72,dashSize:.025,gapSize:.015,depthTest:false,depthWrite:false});
const editShaft = new THREE.CylinderGeometry(1, 1, 1, 10);
const editHead = new THREE.ConeGeometry(1, 1, 14);
const editRing = new THREE.TorusGeometry(1, .09, 8, 40);
const editShared = new Set([editShaft, editHead, editRing]);
let editArrows = [], editMarker = null, editAnchor = null;
const editHandles=document.createElement('div');editHandles.id='piece-handles';view.append(editHandles);
const editHandleLinks=document.createElementNS('http://www.w3.org/2000/svg','svg');editHandleLinks.id='piece-handle-links';editHandleLinks.setAttribute('aria-hidden','true');view.append(editHandleLinks);
const valueChoices=document.createElement('div');valueChoices.id='piece-value-choices';valueChoices.setAttribute('popover','auto');view.append(valueChoices);
function closeValueChoices(){if(valueChoices.matches(':popover-open'))valueChoices.hidePopover();}
function choiceText(key,value){
  if(key==='module_m'&&ghost?.p.piece==='gear')return `${((ghost.p.teeth/2+.7)*Number(value)*100).toFixed(1)} cm radius`;
  if(key==='preset'&&ghost?.p.piece==='ignition')return value==='hot'?'Hot · 0.12 Ω':'Warm · 12 Ω';
  return key==='teeth'?`${value} teeth`:key==='module_m'?`${Math.round(value*1000)} mm teeth`:String(value);
}
function knobDisplayValue(key,value){return key==='module_m'&&ghost?.p.piece==='gear'?choiceText(key,value):String(value);}
function showValueChoices(key,rule,name,source){
  closeValueChoices();const selected=ghost;if(!selected)return;
  valueChoices.replaceChildren(Object.assign(document.createElement('strong'),{textContent:name}));
  const options=Object.assign(document.createElement('div'),{className:'value-choice-grid'});
  for(const value of rule.choices){
    const option=button(choiceText(key,value),()=>{
      closeValueChoices();if(ghost!==selected)return;
      if(setKnob(ghost.p,key,value)){renderGhostBar();showGhostKnobs();askGhost();}
    },{ariaLabel:`Set ${name} to ${choiceText(key,value)}`});
    option.setAttribute('aria-pressed',String(selected.p[key]===value));options.append(option);
  }
  valueChoices.append(options);valueChoices.showPopover();
  positionValueChoices(source);
}
function positionValueChoices(source){
  valueChoices.source=source;
  const box=ghostScreenBox(),object=box?{left:box.x0,right:box.x1,top:box.y0,bottom:box.y1}:source.getBoundingClientRect(),rect=valueChoices.getBoundingClientRect();
  const sceneRect=view.getBoundingClientRect();
  const bounds=rect.height<=sceneRect.height-12&&rect.width<=sceneRect.width-12?sceneRect:
    {left:12,top:Math.max(12,sceneRect.top),right:innerWidth-12,bottom:innerHeight-12};
  const at=pieceToolbarPosition(bounds,object,rect,[source.getBoundingClientRect()]);
  valueChoices.style.left=at.x+'px';valueChoices.style.top=at.y+'px';
}
valueChoices.addEventListener('keydown',e=>{if(e.key==='Escape')pendingPieceReference=null;e.stopPropagation();});
addEventListener('resize',()=>{if(valueChoices.matches(':popover-open')&&valueChoices.source?.isConnected)positionValueChoices(valueChoices.source);});
let handleDrag=null;
function updatePieceHandles() {
  if(handleDrag)return; // Preserve pointer capture while native previews are replaced.
  const rule=ghost&&trayItem(ghost.p.piece).knobs[ghost.card];
  const numericChoices=rule?.choices?.length>1&&rule.choices.every(Number.isFinite);
  const numericRange=!rule?.choices&&rule?.min!=null&&rule.max>rule.min;
  if(!ghost||(!numericChoices&&!numericRange)){editHandles.replaceChildren();editHandleLinks.replaceChildren();return;}
  const anchors=editArrows.slice(0,2).map(({arrow})=>({at:arrow.position.clone().add(editGroup.position),
    direction:new THREE.Vector3(0,1,0).applyQuaternion(arrow.quaternion)}));
  // Lens curvature changes the refracting faces, not its mounting box.
  // Anchor its grip to the actual front face from the compiled optical setup.
  if(!anchors.length&&ghost.p.piece==='lens'&&ghost.card==='radius_m'){
    const lens=ghost.optical_setup?.lenses?.find(l=>l.on===ghostName());
    if(lens){const direction=new THREE.Vector3(...lens.axis).normalize();anchors.push({at:new THREE.Vector3(...lens.at_m).add(editGroup.position).add(direction.clone().multiplyScalar((lens.thickness_m||.01)/2)),direction});}
  }
  // Ratings and joint parameters may change no solid face. Give them the
  // same scene controls, without inventing a change to the physical shape.
  const generic=!anchors.length;
  if(generic){
    const objects=ghostGroup.children.length?[ghostGroup]:terminalGhostWires.children.filter(w=>w.userData.wireName===ghostName());
    const box=new THREE.Box3();for(const o of objects)box.expandByObject(o);
    if(box.isEmpty()){editHandles.replaceChildren();editHandleLinks.replaceChildren();return;}
    const at=box.getCenter(new THREE.Vector3());
    const right=new THREE.Vector3(1,0,0).applyQuaternion(camera.quaternion);
    anchors.push({at:at.clone(),direction:right,side:1},{at:at.clone(),direction:right,side:-1});
  }
  if(anchors.length===1)anchors.push({...anchors[0],side:-1});
  const key=ghost.card,rect=view.getBoundingClientRect();
  if(editHandles.dataset.key!==key||editHandles.childElementCount!==anchors.length){
    editHandles.replaceChildren();editHandleLinks.replaceChildren();editHandles.dataset.key=key;
    anchors.forEach((_,i)=>{
      const direction=i===0?1:-1;
      const h=button(direction>0?'+':'−',()=>{
        if(h.suppressClick){h.suppressClick=false;return;}
        if(ghost)editByDrag(key,Number(ghost.p[key]),direction*240*(numericChoices?1/(rule.choices.length-1):(rule.step||.01)/(rule.max-rule.min)));
      },{ariaLabel:`${direction>0?'Increase':'Decrease'} ${knobName(rule,key)} on object`,
        title:'Tap for one increment, hold to keep changing, or drag along the highlighted direction. Exact values are in Changes → Settings.'},false);
      h.className='piece-dimension-handle';
      h.link=document.createElementNS('http://www.w3.org/2000/svg','line');editHandleLinks.append(h.link);
      h.addEventListener('pointerdown',e=>{if(e.button!==0||!ghost)return;e.preventDefault();h.focus({preventScroll:true});
        h.suppressClick=false;
        editorMode='adjust';looking=false;view.classList.remove('looking');
        handleDrag={id:e.pointerId,key,initial:Number(ghost.p[key]),x:e.clientX,y:e.clientY,dx:Number(h.dataset.dx),dy:Number(h.dataset.dy)};h.setPointerCapture(e.pointerId);
      });
      h.addEventListener('pointermove',e=>{if(handleDrag?.id===e.pointerId){
        if(Math.hypot(e.clientX-handleDrag.x,e.clientY-handleDrag.y)>5)h.suppressClick=true;
        editByDrag(handleDrag.key,handleDrag.initial,(e.clientX-handleDrag.x)*handleDrag.dx+(e.clientY-handleDrag.y)*handleDrag.dy);
      }});
      for(const type of ['pointerup','pointercancel','lostpointercapture'])h.addEventListener(type,()=>{handleDrag=null;updatePieceHandles();});
      repeatOnHold(h,()=>{
        if(!ghost||!handleDrag)return;
        h.suppressClick=true;
        editByDrag(key,Number(ghost.p[key]),direction*240*(numericChoices?1/(rule.choices.length-1):(rule.step||.01)/(rule.max-rule.min)));
        if(handleDrag)handleDrag.initial=Number(ghost.p[key]);
      },{drag:true});
      h.addEventListener('keydown',e=>{if(!ghost||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();e.stopPropagation();
        editByDrag(key,Number(ghost.p[key]),(['ArrowRight','ArrowUp'].includes(e.key)?1:-1)*240*(rule.choices?1/(rule.choices.length-1):(rule.step||.01)/(rule.max-rule.min)));});
      editHandles.append(h);
    });
  }
  anchors.forEach((anchor,i)=>{
    const a=anchor.at.clone().project(camera),b=anchor.at.clone().add(anchor.direction.clone().multiplyScalar(.2)).project(camera);
    let dx=(b.x-a.x)*rect.width/2,dy=-(b.y-a.y)*rect.height/2,l=Math.hypot(dx,dy);if(l<1){dx=1;dy=0;l=1;}
    dx/=l;dy/=l;const h=editHandles.children[i];
    const obstacles=[...view.querySelectorAll('#piece-editor,#clock,#viewer-zoom,#viewer-perspective,#viewer-history')].filter(n=>!n.hidden&&n.getClientRects().length).map(n=>n.getBoundingClientRect());
    obstacles.push(...sceneControlObstacles(rect));
    const box=ghostScreenBox();if(box)obstacles.push({left:box.x0,right:box.x1,top:box.y0,bottom:box.y1});
    for(let j=0;j<i;j++){const previous=editHandles.children[j];if(!previous.hidden)obstacles.push(previous.getBoundingClientRect());}
    let point=null;
    const half=view.clientWidth<360?22:28;
    for(const distance of [56,80,104,128,160,192,224,-56,-80,-104,-128,-160,-192,-224,0].map(v=>v*(anchor.side||1))){
      const x=rect.left+(a.x+1)*rect.width/2+dx*distance,y=rect.top+(1-a.y)*rect.height/2+dy*distance;
      if(Math.abs(a.z)<=1&&x>=rect.left+half&&x<=rect.right-half&&y>=rect.top+half&&y<=rect.bottom-half&&!obstacles.some(r=>x+half>r.left&&x-half<r.right&&y+half>r.top&&y-half<r.bottom)){point={x,y};break;}
    }
    // On a narrow phone the projected axis can pass through the toolbar.
    // Keep the handle usable in the nearest clear space and link it back to
    // the actual working point; dragging still follows the same 3D axis.
    if(!point&&Math.abs(a.z)<=1){
      const sx=rect.left+(a.x+1)*rect.width/2,sy=rect.top+(1-a.y)*rect.height/2;
      let nearest=Infinity;
      for(let x=rect.left+half+8;x<=rect.right-half-8;x+=16)for(let y=rect.top+half+8;y<=rect.bottom-half-8;y+=16){
        const distance=(x-sx)**2+(y-sy)**2;
        if(distance<nearest&&!obstacles.some(r=>x+half>r.left&&x-half<r.right&&y+half>r.top&&y-half<r.bottom)){nearest=distance;point={x,y};}
      }
    }
    h.link.style.display=point?'':'none';
    h.hidden=!point;if(!point)return;
    {
      const limit=numericChoices?rule.choices.indexOf(ghost.p[key])===(i===0?rule.choices.length-1:0):Number(ghost.p[key])===(i===0?rule.max:rule.min);
      h.textContent=limit?(i===0?'MAX':'MIN'):(i===0?'+':'−');h.classList.toggle('at-limit',limit);
    }
    h.style.left=`${point.x-rect.left-half}px`;h.style.top=`${point.y-rect.top-half}px`;h.dataset.dx=dx;h.dataset.dy=dy;
    for(const [key,value] of Object.entries({x1:(a.x+1)*rect.width/2,y1:(1-a.y)*rect.height/2,x2:point.x-rect.left,y2:point.y-rect.top}))h.link.setAttribute(key,String(value));

  });
  for(const h of editHandles.children){h.removeAttribute('id');h.title=`${knobName(rule,key)}: ${knobDisplayValue(key,ghost.p[key])}. Tap for one increment, hold to keep changing, or drag along the highlighted direction.`;}
  const primary=[...editHandles.children].find(h=>!h.hidden);if(primary)primary.id='piece-grip';
}


function clearEditGuide() {
  for (const c of [...editGroup.children]) {
    editGroup.remove(c);
    c.traverse(o => { if (o.geometry && !editShared.has(o.geometry)) o.geometry.dispose(); });
  }
  editArrows = []; editMarker = editAnchor = null;
  if(!handleDrag&&!editHandles.contains(document.activeElement)){editHandles.replaceChildren();editHandleLinks.replaceChildren();}
  $('edit-guide-label').hidden = true;
}
function drawEditGuide(parts) {
  clearEditGuide();
  const guide = ghost?.editGuide;
  if (!guide || guide.key !== ghost.card) {updatePieceHandles();return;}
  buildParts(editGroup, parts.filter(p => guide.focus.includes(p.name)), () => editLook, editEdge);
  for (const a of guide.arrows) {
    const arrow = new THREE.Group(), shaft = new THREE.Mesh(editShaft, editArrowLook), head = new THREE.Mesh(editHead, editArrowLook);
    arrow.position.set(...a.at);
    arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), new THREE.Vector3(...a.direction).normalize());
    arrow.add(shaft, head); editGroup.add(arrow);
    editArrows.push({arrow, shaft, head});
  }
  if (guide.marker) {
    editMarker = new THREE.Mesh(editRing, editArrowLook);
    editMarker.position.set(...guide.marker); editGroup.add(editMarker);
  }
  if(guide.rest_span){
    const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(guide.rest_span.map(p=>new THREE.Vector3(...p))),
      editRestLook);
    line.computeLineDistances();editGroup.add(line);
  }
  editGroup.traverse(o => { o.renderOrder = 100; });
  const at = guide.marker || guide.arrows[0]?.at;
  editAnchor = at ? new THREE.Vector3(...at) : new THREE.Box3().setFromObject(ghostGroup).getCenter(new THREE.Vector3()).sub(ghostGroup.position);
  const label = knobName(trayItem(ghost.p.piece).knobs[guide.key], guide.key);
  $('edit-guide-label').textContent = `${label}: ${knobDisplayValue(guide.key,ghost.p[guide.key])}${guide.rest_span?' m relaxed (dotted guide)':''}`;
  updateEditGuide();
}
function updateEditGuide() {
  const label = $('edit-guide-label');
  editGroup.visible = Boolean(ghost && editAnchor && ghost.editGuide?.key === ghost.card);
  if (!editGroup.visible) { label.hidden = true; updatePieceHandles();return; }
  editGroup.position.copy(ghostGroup.position);
  // Keep the arrows legible as the camera zooms, without changing their anchors.
  const metresPerPixel = at => 2 * camera.position.distanceTo(at) * Math.tan(camera.fov * Math.PI / 360) / Math.max(1, view.clientHeight);
  for (const {arrow, shaft, head} of editArrows) {
    const pixel = metresPerPixel(arrow.position.clone().add(editGroup.position));
    const length = Math.max(.08, Math.min(.8, 48 * pixel)), tip = length * .27;
    shaft.scale.set(Math.max(.002, pixel * 1.5), length - tip, Math.max(.002, pixel * 1.5));
    shaft.position.y = (length - tip) / 2;
    head.scale.set(Math.max(.008, pixel * 6), tip, Math.max(.008, pixel * 6));
    head.position.y = length - tip / 2;
  }
  if (editMarker) {
    editMarker.quaternion.copy(camera.quaternion);
    editMarker.scale.setScalar(Math.max(.04, 22 * metresPerPixel(editMarker.position.clone().add(editGroup.position))));
  }
  updatePieceHandles();
  const screen = editAnchor.clone().add(editGroup.position).project(camera);
  label.hidden = Math.abs(screen.x) > 1 || Math.abs(screen.y) > 1 || Math.abs(screen.z) > 1;
  if (label.hidden) return;
  const sceneRect = view.getBoundingClientRect(), width = label.offsetWidth, height = label.offsetHeight;
  const minY = Math.max(8, -sceneRect.top + 8), maxY = Math.max(minY, Math.min(view.clientHeight, innerHeight - sceneRect.top) - height - 12);
  const maxX = Math.max(8, view.clientWidth - width - 8);
  const x = (screen.x + 1) * view.clientWidth / 2 + 14, y = (1 - screen.y) * view.clientHeight / 2 + 16;
  // A wrapped toolbar can fill a short phone scene. Try spaces beside the
  // piece and the controls, rather than forcing the caption below every row.
  const obstacles = [...view.querySelectorAll('#clock, #scene-mode, #viewer-zoom, #viewer-perspective, #piece-editor, #viewer-history, #move-pad, #scene-tray, .scene-actions button, .scene-actions label, .scene-actions .speed, #preview-legend, #piece-handles button:not([hidden])')]
    .filter(e => e.offsetWidth && e.offsetHeight).map(e => e.getBoundingClientRect());
  let best = null;
  for (const [cx, cy] of [[x, y], [x, y - height - 40], [x - width - 30, y], [8, maxY], [maxX, maxY], [maxX, minY]]) {
    const left = Math.max(8, Math.min(cx, maxX)), top = Math.max(minY, Math.min(cy, maxY));
    const overlap = obstacles.reduce((sum, r) => sum + Math.max(0, Math.min(left + width, r.right - sceneRect.left + 6) - Math.max(left, r.left - sceneRect.left - 6)) *
      Math.max(0, Math.min(top + height, r.bottom - sceneRect.top + 6) - Math.max(top, r.top - sceneRect.top - 6)), 0);
    if (!best || overlap < best.overlap) best = {left, top, overlap};
    if (!overlap) break;
  }
  label.style.left = `${best.left}px`;
  label.style.top = `${best.top}px`;
}

// A picture of each piece in the tray, as it comes: the ghost op's parts for
// it, drawn in their materials by a small renderer of its own, once a level.
const pictures = new Map();
let pictureRenderer = null;
function trayPicture(t) {
  const key = level.id + ':' + t.piece;
  if (!pictures.has(key)) pictures.set(key, (async () => {
    const p = {piece: t.piece};
    for (const [knob, rule] of Object.entries(t.knobs)) p[knob] = knobDefault(rule);
    const context = sandboxRequest();
    if (level.free && ['water_wheel', 'water_tank', 'water_chute', 'water_collector'].includes(t.piece)) {
      const example = sandboxTemplates.find(example => example.placements?.some(placement => placement.piece === t.piece));
      if (example?.base) context.base = example.base;
    }
    const r = await api({op: 'level_ghost', level: level.id, ...context, placements: [p], index: 0});
    const shot = new THREE.Scene(), piece = new THREE.Group();
    buildParts(piece, r.parts, kind => material(materialColor(kind), kind), null);
    if (t.piece === 'wire' || t.piece === 'power_cable') {
      const curve = new THREE.QuadraticBezierCurve3(new THREE.Vector3(-.3, 0, 0), new THREE.Vector3(0, .3, 0), new THREE.Vector3(.3, 0, 0));
      piece.add(new THREE.Mesh(new THREE.TubeGeometry(curve, 24, .012, 8, false), new THREE.MeshStandardMaterial({color:0xffd34d})));
      for (const x of [-.3, .3]) {
        const terminal = new THREE.Mesh(new THREE.SphereGeometry(.035, 12, 8), new THREE.MeshStandardMaterial({color:x < 0 ? 0xe76858 : 0x83bbff}));
        terminal.position.x = x; piece.add(terminal);
      }
    }
    shot.add(piece, new THREE.HemisphereLight(0xdfefff, 0x334455, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.8);
    sun.position.set(2, 3, 4); shot.add(sun);
    // Looked at from the front, a little above and to one side, filling the frame.
    const box = new THREE.Box3().setFromObject(piece), mid = box.getCenter(new THREE.Vector3());
    const reach = box.getSize(new THREE.Vector3()).length() / 2;
    const eye = new THREE.PerspectiveCamera(30, 1, .001, 100);
    eye.position.copy(mid).add(new THREE.Vector3(.55, .45, 1).normalize().multiplyScalar(reach / Math.sin(15 * Math.PI / 180) * 1.05));
    eye.lookAt(mid);
    if (!pictureRenderer) {
      pictureRenderer = new THREE.WebGLRenderer({antialias: true, alpha: true, preserveDrawingBuffer: true});
      pictureRenderer.setSize(320, 320, false);
    }
    pictureRenderer.render(shot, eye);
    piece.traverse(o => { if (o.geometry) o.geometry.dispose(); });
    // A blob, not a data: URL, which the page's security policy refuses for images.
    const png = await new Promise(done => pictureRenderer.domElement.toBlob(done, 'image/png'));
    return png ? URL.createObjectURL(png) : null;
  })().catch(() => { pictures.delete(key); return null; }));
  return pictures.get(key);
}
function pictureInto(img, t) {
  trayPicture(t).then(url => { if (url) { img.src = url; img.hidden = false; } });
}

// One question to the server at a time; a change made meanwhile asks again
// when the answer comes.
function askGhost() {
  if (!ghost) return;
  // Invalidate old water/current readings as soon as the player edits,
  // including edits queued behind an in-flight placement check.
  if (JSON.stringify(ghostPlacements()) !== ghost.previewStamp) markFlowPending();
  scheduleLaserPreview();
  scheduleSolarPreview();
  updatePowerLabels();
  if (ghost.busy) { ghost.again = true; showGhostState(); return ghost.check; }
  const g = ghost;
  g.check = checkGhost(g);
  showGhostState();
  return g.check;
}
async function checkGhost(g) {
  const sent = {x: g.p.x_m ?? 0, z: g.p.z_m ?? 0}, snapping = Boolean(g.snapNext);
  const setupStamp = JSON.stringify([ghostPlacements(),g.baseObject?[g.p.x_m,g.p.height_m,g.p.z_m]:null]);
  g.busy = true; g.again = false; g.snapNext = false;
  try {
    const r = await api(g.baseObject ? {op:'sandbox_object',level:'free',base:g.originalBase,object:g.baseObject.id,
      delta:[g.p.x_m-g.baseObject.at_m[0],g.p.height_m,g.p.z_m-g.baseObject.at_m[2]],placements,
      snap:snapping&&objectSnapEnabled,nearby_snap:true,snap_hold:g.objectLock} : {op: 'level_ghost', level: level.id, ...sandboxRequest(), placements: ghostPlacements(), index: g.index,
      snap: snapping && objectSnapEnabled, nearby_snap:true, snap_hold:g.objectLock, edit_key: g.card});
    if (ghost !== g) return;
    if(g.baseObject)g.base=r.base;
    // Moved by hand near where it connects to another piece: put where the
    // two connect, and asked about again there.
    if (r.snap && r.snap.moved && snapping && objectSnapEnabled && !g.again) {
      const moved = Object.entries(r.snap.knobs).map(([k, v]) => setKnob(g.p, k, v)).some(Boolean);
      if (moved) { followGhost(); showGhostKnobs(); g.again = true; }
    }
    Object.assign(g, {fits: r.fits, problems: r.problems, cost: r.cost, sun: r.sun || [], energy: r.energy, drawnAt: sent, answered: true,
                      joined: objectSnapEnabled && r.snap ? `${r.snap.port} of ${r.snap.to}` : null,
                      alignmentOnly:r.snap?.port==='cutting plane',
                      objectLock:r.snap && objectSnapEnabled ? r.snap.to+'|'+r.snap.port : null, alignment:r.alignment||null});
    g.electrical = r.electrical_preview || null;
    g.batteryPreview=r.battery_preview||[];g.proposedParts=r.parts||[];
    g.optical_setup = r.optical_setup || null;
    g.water_setup = r.water_setup || [];
    g.solar_setup = r.solar_setup || [];
    g.spring_setup=r.spring_setup||[];
    g.airflows=r.airflows||[];drawAirflows(g.airflows);
    syncPowerLabels();
    drawGhost(r.parts, r.fits);
    for(const j of r.spring_setup||[])ghostGroup.add(new THREE.Mesh(coilGeometry(j.at_m,j.at_b_m),ghostLook[r.fits?'fits':'refused']));
    drawLensOutlines();
    if (g.electrical) {
      const terminals = terminalMap(g.electrical);
      for (const [lane, wire] of (g.electrical.wires || []).entries()) {
        const a = terminals.get(wire.a), b = terminals.get(wire.b);
        if (!a || !b) continue;
        const mine = wire.name === ghostName() || wire.name.startsWith(ghostName() + ' ');
        const tube = new THREE.Mesh(new THREE.TubeGeometry(routedCurve(a, b, lane), 64, wireDisplayRadius(wire), 6, false),
          mine ? ghostLook[r.fits ? 'fits' : 'refused'] : material(wireColor(wire), 'wire'));
        tube.userData.wireName=wire.name;
        terminalGhostWires.add(tube);
      }
    }
    if (r.wire_preview && g.p.piece === 'power_cable') {
      const [a, b] = r.wire_preview;
      const curve = new THREE.QuadraticBezierCurve3(new THREE.Vector3(...a),
        new THREE.Vector3((a[0] + b[0]) / 2, Math.max(a[1], b[1]) + .1, (a[2] + b[2]) / 2), new THREE.Vector3(...b));
      ghostGroup.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(20)), ghostEdge.fits));
      for (const at of [a, b]) {
        const dot = new THREE.Mesh(new THREE.SphereGeometry(.025, 12, 8), ghostLook.fits);
        dot.position.set(...at); ghostGroup.add(dot);
      }
    }
    g.editGuide = r.edit_guide || null;
    drawEditGuide(r.parts);
    drawPorts(r.ports || [], r.snap);
    // Fit every new addition once, before placement; later adjustments and
    // manual zooms remain under the player's control.
    if(g.frameOnAdd){g.frameOnAdd=false;fitNewPieceInView();}
    // Selecting a control changes annotations, not the simulated setup.
    if (!g.again && setupStamp !== g.previewStamp) { g.previewStamp = setupStamp; schedulePreview(); }
  } catch (e) {
    if (ghost === g) Object.assign(g, {fits: false, problems: e.data && e.data.problems ? e.data.problems : [e.message], answered: true});
  } finally {
    g.busy = false;
    if (ghost === g) { showGhostKnobs();showGhostState(); if (g.again) askGhost(); else scheduleSolarPreview(); }
  }
}

// A piece from the tray (index after the rest) or one picked up (its own
// index): a ghost of it, starting where the middle of
// the view meets the scene.
function startGhost(p, index, keepPlace = false) {
  endGhost();
  editorMode='move';lastEdited=index;
  // Prebuilt/saved placements may omit default-valued knobs. Resolve them
  // before editing so range controls and selectors show the compiled setup.
  for (const [key, rule] of Object.entries(trayItem(p.piece).knobs)) {
    if (p[key] == null) p[key] = index < placements.length && rule.legacy_default != null ? rule.legacy_default : knobDefault(rule);
  }
  selectPhonePanel('controls');
  ghost = {p, index, was: index < placements.length ? placements[index] : null, fits: true, problems: [],
           drawnAt: null, busy: false, again: false, cost: null, answered: false, inputs: {},card:trayItem(p.piece).focus_knob,
           frameOnAdd:index>=placements.length};
  if(p.piece==='base_object')Object.assign(ghost,{baseObject:sandboxObjects.find(o=>o.id===p.object),originalBase:clone(activeDesign.draft.base || sandboxBase)});
  view.classList.add('placing'); view.classList.remove('pickable', 'looking');
  looking = false;
  renderTray(); renderPlaced(); renderGhostBar();
  if (phoneLayout.matches) $('control-panel').scrollTop = 0;
  // Where the ghost is: in sight (a phone's page has scrolled down to the tray).
  sceneIntoView();
  // A copy starts beside what it copies; a new piece where the view's middle meets the scene.
  if (!ghost.was && !keepPlace) {
    const rect = renderer.domElement.getBoundingClientRect();
    const at = sceneHit(rect.left + rect.width / 2, rect.top + rect.height / 2);
    if (at) { setKnob(ghost.p, 'x_m', at.x); setKnob(ghost.p, 'z_m', at.z); showGhostKnobs(); }
  }
  askGhost();
}

// A piece set down, made a ghost again to move, change or turn it (from the
// panel, or by clicking it in the scene). After a run, or during one, the
// level goes back to its start first: pieces are placed there.
function pickUp(i) {
  if(level?.free && i>=placements.length){
    const object=sandboxObjects[i-placements.length];if(!object)return;
    if(playing||world.t>0)rebuildLevel(false).then(()=>pickUp(i)).catch(()=>{});
    else startGhost({piece:'base_object',object:object.id,x_m:object.at_m[0],z_m:object.at_m[2],height_m:0},placements.length,true);
    return;
  }
  if (!placements[i]) return;
  if (playing || world.t > 0) rebuildLevel(false).catch(() => {});
  startGhost({...placements[i]}, i);
}

function endGhost() {
  closeValueChoices();
  $('socket-choices').hidden=true;
  clearTimeout(solarTimer);solarTimer=null;solarWanted='';solarStamp='';solarResult=null;solarVersion++;solarPending=false;solarError='';
  ghost = null; draggingGhost = null; pressedAt = null;pendingPieceReference=null;handleDrag=null;drawAirflows();
  view.classList.remove('grabbing', 'grab');
  terminalStart = null; powerMessage('');
  clearGhostMeshes(); ghostGroup.position.set(0, 0, 0); drawPorts([]);
  clearEditGuide();
  drawLensOutlines();
  $('lens-grip').hidden=true;
  view.classList.remove('placing', 'looking');
  looking = false;
  renderGhostBar();
  positionTerminalLabels();updatePowerLabels();positionPowerLabels();
}

function cancelGhost() { if (!ghost) return; endGhost(); renderTray(); renderPlaced(); schedulePreview(200); }

function placeGhost() {
  if (!ghost || !ghost.fits || ghost.busy || !ghost.answered) return false;
  remember();
  if(ghost.baseObject)activeDesign.draft.base=ghost.base;
  else if (ghost.was) placements[ghost.index] = ghost.p; else placements.push(ghost.p);
  endGhost(); renderTray(); renderPlaced();
  return true;
}
function setGhostDown() {
  if (placeGhost()) {selectPhonePanel('controls');scheduleRebuild(0);}
}

// The ghost's own controls, just below the scene and out of its way (the top
// of the side panel, kept in sight as the panel scrolls): on a phone the list
// of pieces is a scroll away. One adjustment menu, a stepped flat slider
// and an exact value keep the active setting beside Set down.
function knobName(rule, key) { return ghost?.p.piece==='gear'&&key==='module_m'?'Radius':(rule.label || key).replace(/\s*\(.*\)\s*$/, ''); }
let sliderSerial=0;
function addSliderTicks(input,rule){
  const list=document.createElement('datalist');list.id=`slider-ticks-${++sliderSerial}`;
  const count=Math.min(10,Math.round((rule.max-rule.min)/(rule.step||.01)));
  for(let i=0;i<=count;i++){
    const value=rule.min+Math.round((rule.max-rule.min)*i/Math.max(1,count)/(rule.step||.01))*(rule.step||.01);
    if(value<=rule.max+1e-9)list.append(new Option('',String(Number(value.toFixed(6)))));
  }
  input.setAttribute('list',list.id);input.classList.add('flat-slider');input.tickList=list;
}
function electricalEditRating(){
  if(!ghost)return '';
  const p=ghost.p,name=ghostName(),device=ghost.electrical?.devices?.find(d=>d.name===name);
  const battery=ghost.batteryPreview?.find(b=>b.name.startsWith(name+' '));
  let rating;
  if(p.piece==='battery')rating=battery?`${battery.voltage_v} V · ${battery.charge_j} J / ${battery.capacity_j} J · ≤ ${p.max_power_w??200} W`:`${p.voltage_v??12} V`;
  else if(p.piece==='bulb'&&device)rating=`${device.rated_voltage_v} V · ${device.watts} W bulb`;
  else if(p.piece==='resistor')rating=`${p.resistance_ohm} Ω resistance`;
  else if(p.piece==='capacitor')rating=`${p.capacitance_f} F · ${p.esr_ohm??.1} Ω internal · ${p.leakage_ohm??1000000} Ω leakage`;
  else if(p.piece==='motor')rating=`${Math.round((p.throttle??1)*100)}% throttle · ${p.direction||'forward'}`;
  else if(p.piece==='wire')rating=`${p.size||'standard'} wire · ${p.length_m??5} m`;
  else if(p.piece==='ignition')rating=`${p.preset==='hot'?'.12':'12'} Ω heater · ${p.target?'clipped to '+p.target:'not attached'}`;
  else if(p.piece==='switch')rating=p.mode==='paddle'?`Contact closes at ${p.threshold_deg}°`:`Starting switch: ${p.state||'open'}`;
  else if(p.piece==='spring'&&p.mechanism_version===3){
    const j=ghost.spring_setup?.[0];
    if(j){const compression=j.rest_m-Math.hypot(...j.at_m.map((v,i)=>v-j.at_b_m[i]));
      rating=`${(.5*j.stiffness_n_m*compression**2).toFixed(1)} J stored · ${(j.stiffness_n_m*compression).toFixed(0)} N push · latch held`;}
  }
  return rating?`Proposed ${rating}`:'';
}
function pieceKnobVisible(p,key) {
  const tray=trayItem(p.piece),rule=tray?.knobs?.[key];
  if(!level?.free&&tray?.lesson_knobs){
    if(!tray.lesson_knobs.includes(key))return false;
    // A prepared value is a reading, not a choice the player can change.
    if(rule?.choices?.length===1||(!rule?.choices&&rule?.min!=null&&rule.min===rule.max))return false;
  }
  if(p.piece==='spring'&&(p.mechanism_version??1)===1){
    if(['yaw_deg','pitch_deg','roll_deg','compressed_m'].includes(key))return false;
    if(key==='height_m'&&(!p.load||p.load==='included load'))return true;
  }
  if(p.piece==='ignition'&&p.attachment_version===2&&key==='target')return false;
  if(p.piece==='marble' && key==='height_m' && p.placement!=='at height')return false;
  if(p.piece==='pipe_elbow' && key==='fall_m' && p.plane==='downward')return false;
  if(trayItem(p.piece)?.knobs?.[key]?.hidden)return false;
  if(p.piece==='bulb' && key==='preset' && p.size && p.size!=='preset')return false;
  if(p.piece==='spring' && p.load && p.load!=='included load' && ['height_m','material','load'].includes(key))return false;
  if(p.piece==='tackle' && p.load && p.load!=='included load' && key==='load_material')return false;
  if(p.piece==='water_wheel' && p.side==='off' && ['side','discharge_l_s'].includes(key))return false;
  if(p.piece==='water_tank') {
    if(p.outlet_model==='gravity' && (['outlet_model','discharge_l_s'].includes(key) || (key==='valve' && p.valve!=='closed')))return false;
    if(p.outlet_model!=='gravity' && key==='opening_percent')return false;
  }
  if(p.piece==='switch'&&(p.mode==='paddle'?['state','handle_material'].includes(key):key==='threshold_deg'))return false;
  return !(p.piece==='battery' && p.mount!=='contact pack' && ['height_m','yaw_deg','housing_material'].includes(key));
}

function nudgeKnob(key, by) {
  if (ghost && setKnob(ghost.p, key, (ghost.p[key] ?? 0) + by)) { followGhost(); showGhostKnobs(); askGhost(); }
}

let pendingPieceReference=null;
function sceneReferenceControl(p,key,rule,changed){
  const row=document.createElement('div');row.className='scene-reference';
  const allowed=[...referenceControl(p,key,rule,()=>{}).options].map(o=>o.value);
  const available=allowed.filter(Boolean),load=key==='load_part';
  const hint=Object.assign(document.createElement('p'),{className:'reference-hint',textContent:available.length?
    (load?'Choose the separate object the wheel’s rope should lift.':'Choose a connection from the scene.'):
    (load?'No movable load yet. Add a weight or loose box first.':'No compatible connection is available yet.')});
  const choose=button(p[key]?`${knobName(rule,key)}: ${p[key]}`:`Choose ${knobName(rule,key)}`,()=>{
    closeValueChoices();const selected=ghost;
    pendingPieceReference={p,key,rule,changed,allowed};
    $('adjustment-feedback').textContent='Click an object in the scene, or choose its name in the list. Escape cancels.';
    valueChoices.replaceChildren(Object.assign(document.createElement('strong'),{textContent:knobName(rule,key)}),
      Object.assign(document.createElement('p'),{textContent:load?'Choose the object to lift, or click it in the scene.':'Choose a connection, or click its object in the scene.'}));
    const options=Object.assign(document.createElement('div'),{className:'value-choice-grid'});
    for(const value of allowed){
      const label=value||'No connection';
      const option=button(label,()=>{
        closeValueChoices();pendingPieceReference=null;if(ghost!==selected)return;
        p[key]=value;changed();
      },{ariaLabel:`Connect ${knobName(rule,key)} to ${label}`});
      option.setAttribute('aria-pressed',String(p[key]===value));options.append(option);
    }
    valueChoices.append(options,button('Pick in scene',()=>{closeValueChoices();}),
      button('Cancel',()=>{pendingPieceReference=null;closeValueChoices();showGhostKnobs();}));
    valueChoices.showPopover();positionValueChoices(choose);
  },{ariaLabel:`Choose ${knobName(rule,key)} in scene`,disabled:!available.length});
  row.append(choose);
  if(rule.default&&rule.default!==p[key])row.append(button('Default',()=>{p[key]=rule.default;pendingPieceReference=null;changed();},{ariaLabel:`Use default ${knobName(rule,key)}`}));
  row.append(hint);
  return row;
}
function selectGhostKnob(key, force=false) {
  if (!ghost || (ghost.card === key&&!force)) return;
  const rule=trayItem(ghost.p.piece).knobs[key];
  editorMode=rule?.turning?'turn':rule?.choices||rule?.part||rule?.hinge?'move':'adjust';looking=false;view.classList.remove('looking');
  ghost.card = key;
  clearEditGuide();
  renderGhostBar();
  askGhost();
}

function gearControls(knobs){
  const group=Object.assign(document.createElement('div'),{className:'gear-controls',ariaLabel:'Gear size and height'});
  group.setAttribute('role','group');
  for(const [key,label] of [['teeth','Teeth'],['module_m','Radius'],['height_m','Height']]){
    const rule=knobs[key],name=knobName(rule,key);
    const field=button('',()=>{
      selectGhostKnob(key,true);
      if(rule.choices)showValueChoices(key,rule,name,$('piece-editor').querySelector(`[data-gear-key="${key}"]`));
    },{ariaLabel:rule.choices?`Choose ${name}`:`Adjust ${name}`,
      title:key==='height_m'?'Axle height: tap, then drag the gold vertical handles or tap + / −.':
        key==='module_m'?'Radius to the tooth tips. Changing radius also changes tooth spacing.':'Number of teeth: tap to choose a size.'});
    field.dataset.gearKey=key;
    field.append(Object.assign(document.createElement('span'),{className:'gear-label',textContent:label}),
      Object.assign(document.createElement('span'),{className:'gear-value'}));
    group.append(field);
  }
  return group;
}

function springLengthControls(rule){
  const group=Object.assign(document.createElement('div'),{className:'spring-length-controls'});
  group.setAttribute('role','group');group.setAttribute('aria-label','Spring length');
  const heading=Object.assign(document.createElement('div'),{className:'spring-length-heading'});
  heading.append(Object.assign(document.createElement('span'),{textContent:'Spring length',title:'Relaxed length before compression. The latch holds the compressed spring until release.'}),
    Object.assign(document.createElement('output'),{className:'spring-length-value',ariaLive:'polite'}));
  const step=rule.step||.01,increment=step*Math.max(1,Math.round(.05/step));
  const amount=`${Number((increment*100).toFixed(3))} cm`;
  group.append(heading);
  for(const [direction,label] of [[-1,'Shorten spring'],[1,'Lengthen spring']]){
    const control=button(`${direction<0?'−':'+'} ${amount}`,()=>{
      if(!ghost)return;
      if(ghost.card!=='rest_m'){ghost.card='rest_m';editorMode='adjust';clearEditGuide();}
      nudgeKnob('rest_m',direction*increment);
    },{ariaLabel:label,title:`${label} by ${amount}. Drag the gold handles for finer changes.`});
    control.dataset.springDirection=direction;group.append(control);
  }
  return group;
}

function renderGhostBar() {
  pendingPieceReference=null;
  const precisionOpen = Boolean($('precision-controls')?.open);
  renderMovePad();
  const card = $('ghost-bar');
  card.hidden = !ghost;
  $('focus-piece').hidden = !ghost;
  ghost && (ghost.cardInput = null);
  ghost && (ghost.gaugeButtons = null);
  ghost && (ghost.choiceButtons = null);
  if (!ghost) {
    view.classList.remove('choosing-attachment');
    for(const id of ['instrument-panel','laser-preview-status','water-status','river-wheel-status','solar-lift-guide']) if($(id)) $('control-panel').append($(id));
    for(const id of ['flow-preview','move-pad','preview-legend','edit-guide-label','view-controls','scene-actions'])if($(id))$('help-settings-content')?.append($(id));
    card.replaceChildren();$('piece-editor').hidden=true;$('piece-editor').replaceChildren();
    $('precision-controls')?.remove();return;
  }
  const throwAway = button('✕', cancelGhost, {ariaLabel: 'Throw the ghost away', title: 'Throw the ghost away'});
  const selectedName=ghost.baseObject?.name || pieceLabel(ghost.p.piece);
  const head = Object.assign(document.createElement('p'), {className: 'head',
    textContent: ghost.rewireKey?`Rewire ${selectedName}`:looking ? `View mode · ${selectedName}` : `Adjust ${selectedName}`});
  // Where it stands is the arrows' and the drag's; the menu changes the rest.
  const primary=trayItem(ghost.p.piece).primary_knobs;
  const knobs = trayItem(ghost.p.piece).knobs, allKeys = Object.keys(knobs).filter(k =>
    ((!['x_m','z_m'].includes(k))||primary?.includes(k)) && !(ghost.p.attachment_version===2&&knobs[k].scene_attach) && pieceKnobVisible(ghost.p,k));
  // Endpoints are chosen on the objects. Their selectors stay in Precision
  // controls; ordinary cable editing exposes thickness/length instead.
  const connecting=['wire','power_cable'].includes(ghost.p.piece);
  const available=allKeys.filter(k=>!knobs[k].connection_target&&(!connecting||(!knobs[k].terminal&&!knobs[k].power_port)));
  const compactGear=ghost.p.piece==='gear'&&primary&&!precisionOpen;
  const keys=compactGear?primary.filter(k=>available.includes(k)):[...available];
  if(editorMode==='turn')for(const k of available.filter(k=>knobs[k].turning))if(!keys.includes(k))keys.push(k);
  if(editorMode!=='turn'&&!precisionOpen)for(const k of heightKnobs(ghost.p))if(available.includes(k)&&!keys.includes(k))keys.push(k);
  if(!compactGear&&available.includes(ghost.card)&&!keys.includes(ghost.card))keys.push(ghost.card);
  // Move-only lessons still need a valid editing key for placement feedback.
  // Connections remain scene sockets even when there is no property to tune.
  if(!keys.length)keys.push(allKeys[0]||Object.keys(knobs).find(k=>pieceKnobVisible(ghost.p,k)));
  if (!keys.includes(ghost.card)) ghost.card = keys[0];
  const chips = Object.assign(document.createElement('div'), {className: 'adjustment-picker'});
  const adjustment=document.createElement('select');adjustment.id='adjustment-choice';adjustment.setAttribute('aria-label','Adjustment');
  for (const key of keys) {
    adjustment.append(new Option(ghost.p.piece==='gear'&&key==='module_m'?'Radius (cm)':ghost.p.piece==='lens'&&key==='radius_m'?'Focus / face radius (m)':knobs[key].label||knobName(knobs[key],key),key));
  }
  adjustment.value=ghost.card;adjustment.addEventListener('change',()=>selectGhostKnob(adjustment.value));
  chips.append(Object.assign(document.createElement('label'),{textContent:'Adjust',htmlFor:'adjustment-choice'}),adjustment);
  chips.hidden=keys.length===1;
  const key = ghost.card, rule = knobs[key], name = knobName(rule, key);
  let precisionChoice=null;
  const row = Object.assign(document.createElement('div'), {className: 'knob-row'});
  if (rule.part || rule.hinge || rule.terminal || rule.power_port) {
    const select = referenceControl(ghost.p, key, rule, () => { showGhostKnobs(); askGhost(); });
    ghost.cardInput = [select, null, key];
    row.append(select);
  } else if (rule.choices) {
    const select = document.createElement('select');
    for (const c of rule.choices) select.append(Object.assign(document.createElement('option'), {value: c, textContent: choiceText(key,c)}));
    select.value = ghost.p[key];
    select.setAttribute('aria-label', `Its ${name}`);
    select.addEventListener('change', () => {
      ghost.p[key] = rule.choices.find(c => String(c) === select.value) ?? select.value;
      if ((key==='mount' && ghost.p.piece==='battery')||(key==='mode'&&ghost.p.piece==='switch')||(key==='size'&&ghost.p.piece==='bulb')) {renderPlaced();renderGhostBar();}
      showGhostKnobs(); askGhost();
    });
    // Choices use labelled buttons; the native selector remains an exact-value fallback.
    select.hidden=true;
    const applyChoice=value=>{
      ghost.p[key]=value;
      renderGhostBar();showGhostKnobs();askGhost();
    };
    if(ghost.p.piece==='wire'&&key==='size') {
      row.classList.add('wire-gauge');
      ghost.gaugeButtons=rule.choices.map(value=>{
        const label=value[0].toUpperCase()+value.slice(1);
        const choice=button(label,()=>applyChoice(value),{ariaLabel:`${label} wire`});
        choice.dataset.gauge=value;choice.setAttribute('aria-pressed',String(ghost.p.size===value));
        row.append(choice);return choice;
      });
    } else if(rule.choices.length===2) {
      const toggle=button(`${choiceText(key,ghost.p[key])} ⇄`,()=>applyChoice(rule.choices.find(v=>v!==ghost.p[key])),
        {ariaLabel:`Toggle ${name}`,title:`${name}: ${rule.choices.join(' or ')}`});
      toggle.id='piece-choice-toggle';
      toggle.setAttribute('aria-pressed',String(ghost.p[key]===rule.choices[1]));row.append(toggle);
    } else if(rule.choices.length>1) {
      const choose=button(choiceText(key,ghost.p[key]),()=>showValueChoices(key,rule,name,choose),{ariaLabel:`Choose ${name}`});
      row.classList.add('choice-cycle');row.append(choose);
    } else row.append(Object.assign(document.createElement('output'),{textContent:String(ghost.p[key])}));
    precisionChoice=select;
    ghost.cardInput = [select, null, key];
  } else {
    row.classList.add('numeric-slider');
    const input = Object.assign(document.createElement('input'), {type: 'range', min: rule.min, max: rule.max,
      step: rule.step || 0.01, value: ghost.p[key]});
    input.setAttribute('aria-label', `Its ${name}`);
    addSliderTicks(input,rule);
    input.addEventListener('input', () => { if (setKnob(ghost.p, key, Number(input.value))) { followGhost(); showGhostKnobs(); askGhost(); } });
    const shown = Object.assign(document.createElement('input'), {type:'number',min:rule.min,max:rule.max,
      step:rule.step || 0.01,value:ghost.p[key],className:'exact-value'});
    shown.setAttribute('aria-label',`Exact ${name}`);
    const applyExact=()=>{
      if (shown.value !== '' && shown.checkValidity() && setKnob(ghost.p,key,Number(shown.value))) {
        followGhost(); askGhost(); showGhostKnobs();
      }
    };
    shown.addEventListener('input',applyExact);
    shown.addEventListener('change',()=>{
      applyExact();
      showGhostKnobs();
    });
    row.append(input);
    row.append(input.tickList);
    row.append(shown);
    ghost.cardInput = [input, shown, key];
  }
  const state = Object.assign(document.createElement('p'), {className: 'state'});
  const actions = Object.assign(document.createElement('div'), {className: 'actions'});
  actions.append(button('Place', setGhostDown, {className: 'down', ariaLabel:'Place', disabled: !ghost.fits || ghost.busy}), throwAway);
  if(ghost.baseObject || ghost.was)actions.insertBefore(button('Delete piece',()=>removeSelectedObject(),{ariaLabel:'Delete selected piece'}),throwAway);
  if(ghost.rewireKey) actions.insertBefore(button('Disconnect wire',()=>{
    if(!ghost?.rewireKey || terminalBusy || powerBusy)return;
    const index=ghost.index;
    remember();endGhost();removePiece(index);renderTray();renderPlaced();scheduleRebuild(0);
  },{disabled:terminalBusy||powerBusy}),throwAway);
  const precision = document.createElement('details'); precision.id='precision-controls';
  precision.open=precisionOpen;
  ghost.advancedOpen=precisionOpen;
  precision.addEventListener('toggle',()=>{if(ghost&&primary&&precision.isConnected&&ghost.advancedOpen!==precision.open){ghost.advancedOpen=precision.open;renderGhostBar();}});
  precision.append(Object.assign(document.createElement('summary'),{textContent:'Precision controls'}),$('move-pad'),$('edit-guide-label'),ghostItem(),
    Object.assign(document.createElement('p'),{id:'ghost-cost',className:'legend'}));
  const fields=Object.assign(document.createElement('div'),{className:'ghost-fields'});
  const gridRow=Object.assign(document.createElement('div'),{className:'grid-snap-row'});
  const snapButton=button('Snap to grid',()=>{
    gridSnapEnabled=!gridSnapEnabled;if (ghost) ghost.gridLocks=null;
    try {localStorage.setItem(TEST_BUILD?'banjo-test-grid-snap':'banjo-grid-snap',gridSnapEnabled?'on':'off');} catch { /* private window */ }
    snapButton.setAttribute('aria-pressed',String(gridSnapEnabled));showGridSnap();
  },{id:'grid-snap',title:'Gently align to nearby 5 cm grid lines while dragging. Exact controls stay free. Snap to objects separately aligns nearby surfaces and connectors. Alt+drag bypasses both.'});
  snapButton.setAttribute('aria-pressed',String(gridSnapEnabled));
  const objectButton=button('Snap to objects',()=>{
    objectSnapEnabled=!objectSnapEnabled;if(ghost){ghost.objectLock=null;ghost.joined=null;}
    objectButton.setAttribute('aria-pressed',String(objectSnapEnabled));showGridSnap();
  },{id:'object-snap',title:'Align a knife with a nearby cord, center a marble on a board or join track and pipe ends. Pull away to release; Alt+drag bypasses both snaps. Green guides show alignment, not a predicted win.'});
  objectButton.setAttribute('aria-pressed',String(objectSnapEnabled));
  gridRow.hidden=false;
  gridRow.append(snapButton,objectButton,Object.assign(document.createElement('output'),{id:'grid-snap-status',ariaLive:'polite'}));
  const setting=Object.assign(document.createElement('output'),{id:'adjustment-feedback',className:'adjustment-feedback',ariaLive:'polite'});
  if(row.classList.contains('numeric-slider')||rule.part||rule.hinge||rule.terminal||rule.power_port)precision.append(row);
  if(precisionChoice){precisionChoice.hidden=false;precision.append(precisionChoice);}
  fields.append(head,state,$('instrument-panel'));
  const connectionActions=allKeys.filter(k=>knobs[k].connection_target).map(key=>referenceControl(ghost.p,key,knobs[key],()=>{renderGhostBar();askGhost();}));
  $('snap-settings').replaceChildren(gridRow);
  // Keep these shared nodes connected before replacing the old inspector.
  // Otherwise a second selection discards the controls with its old content.
  precision.append($('scene-actions'),$('view-controls'));
  $('help-settings-content').replaceChildren(precision,$('preview-legend'),$('flow-preview'));
  let unclipButton=null;
  if(ghost.p.piece==='ignition'&&ghost.p.attachment_version===2) {
    const prompt=Object.assign(document.createElement('p'),{className:'wire-prompt',textContent:ghost.p.target?
      `Heater clipped to ${ghost.p.target}. Click a Clip ring to move the attachment.`:'Click a Clip ring on the material in the 3D scene. Then set the heater down and connect both power leads.'});
    head.after(prompt);
    if(ghost.p.target)unclipButton=button('Unclip heater',()=>{ghost.p.target='';renderGhostBar();askGhost();});
  }
  for(const id of ['laser-preview-status','water-status','river-wheel-status','solar-lift-guide'])fields.append($(id));
  if(connecting&&!ghost.was){
    const prompt=Object.assign(document.createElement('p'),{className:'wire-prompt',textContent:ghost.rewireKey?'Click a new connection point for the detached end. Esc restores this wire.':'Click a connection point in the 3D scene, then click the other end.'});
    head.after(prompt);if(!keys.some(k=>!knobs[k].terminal&&!knobs[k].power_port)){row.hidden=true;chips.hidden=true;}
  }
  // Removal is an occasional action; keep it with the exact controls.
  for(const b of [...actions.children])if(!b.classList.contains('down')&&b!==throwAway)precision.append(b);
  card.replaceChildren(fields);
  const needsClip=ghost.p.piece==='ignition'&&ghost.p.attachment_version===2&&!ghost.p.target;
  view.classList.toggle('choosing-attachment',Boolean(needsClip));
  const editor=$('piece-editor');editor.hidden=(connecting&&!ghost.was)||needsClip;
  const isGear=ghost.p.piece==='gear';editor.classList.toggle('editing-gear',isGear);
  const modes=Object.assign(document.createElement('div'),{className:'piece-modes'});
  const move=button('Move',()=>{editorMode='move';setLooking(false);},{ariaLabel:'Move selected piece'});
  const turn=button('Turn',()=>{
    const rules=trayItem(ghost.p.piece).knobs;
    const key=turnKnob(ghost.p,'yaw_deg')||Object.keys(rules).find(k=>rules[k].turning&&pieceKnobVisible(ghost.p,k));
    if(key){ghost.card=key;editorMode='turn';setLooking(false);askGhost();}
  },{ariaLabel:'Turn selected piece'});
  move.setAttribute('aria-pressed',String(editorMode==='move'&&!looking));
  turn.setAttribute('aria-pressed',String(editorMode==='turn'&&!looking));
  move.disabled=!movableGhost();turn.hidden=!Object.entries(knobs).some(([k,r])=>r.turning&&pieceKnobVisible(ghost.p,k));
  modes.append(move,turn);
  modes.hidden=move.disabled&&turn.hidden;
  const top=Object.assign(document.createElement('div'),{className:'piece-toolbar'});top.append(modes,actions);
  editor.replaceChildren(top,...(isGear?[gearControls(knobs)]:[chips]));
  if(ghost.p.piece==='spring'&&knobs.rest_m&&pieceKnobVisible(ghost.p,'rest_m'))editor.append(springLengthControls(knobs.rest_m));
  if(isGear)precision.querySelector('summary').after(chips);
  if(rule.choices&&(!isGear||!['teeth','module_m','height_m'].includes(key)))editor.append(row);
  else if(rule.part||rule.hinge)editor.append(sceneReferenceControl(ghost.p,key,rule,()=>{renderGhostBar();showGhostKnobs();askGhost();}));
  editor.append(...connectionActions,...(unclipButton?[unclipButton]:[]),setting);
  setting.hidden=isGear; // The three visible fields already show these measurements.
  if(isGear)editor.append(Object.assign(document.createElement('output'),{id:'gear-plane-feedback',className:'adjustment-feedback',ariaLive:'polite'}));
  if(ghost.p.piece==='gear')editor.append(Object.assign(document.createElement('output'),{id:'gear-motion-feedback',className:'adjustment-feedback',textContent:'Checking gear motion…',
    title:'This is a replay of the engine’s predicted motion for the current placement. Radius is measured to the tooth tips; it changes tooth spacing too.'}));
  // The geometric piece editor is hidden while drawing a cable. A lesson
  // that teaches gauge still needs its three choices before the second click.
  if(connecting&&!ghost.was&&row.classList.contains('wire-gauge'))fields.append(row);
  if((connecting&&!ghost.was)||needsClip){throwAway.textContent=needsClip?'Cancel heater':'Cancel wire';fields.append(throwAway);}
  showGhostKnobs(); showGhostState();
}

function editByDrag(key,initial,pixels) {
  if(!ghost)return;
  const rule=trayItem(ghost.p.piece).knobs[key];
  if(!rule)return;
  let value;
  if(rule.choices?.every(Number.isFinite)&&rule.choices.length>1){const index=Math.max(0,Math.min(rule.choices.length-1,Math.round(rule.choices.indexOf(initial)+pixels*(rule.choices.length-1)/240)));value=rule.choices[index];}
  else if(!rule.choices&&rule.min!=null)value=draggedKnobValue(rule,initial,pixels);else return;
  if(setKnob(ghost.p,key,value)){followGhost();showGhostKnobs();askGhost();}
}

const liveCards=document.createElement('div');liveCards.id='device-live-controls';view.append(liveCards);
const controlLeaders=document.createElementNS('http://www.w3.org/2000/svg','svg');
controlLeaders.id='object-control-leaders';controlLeaders.setAttribute('aria-hidden','true');view.append(controlLeaders);
const editorLeader=document.createElementNS(controlLeaders.namespaceURI,'line');
editorLeader.dataset.for='piece-editor';controlLeaders.append(editorLeader);
const liveControlLeaders=new Map();
function mobileEdgeControls(){return view.clientWidth<600 || innerHeight<=500;}
function controlLeader(line,card,anchor) {
  line.style.display='none';
  if(card.hidden)return;
  const rect=view.getBoundingClientRect(),box=card.getBoundingClientRect();
  const to={x:Math.max(box.left,Math.min(box.right,anchor.x)),y:Math.max(box.top,Math.min(box.bottom,anchor.y))};
  line.setAttribute('x1',String(anchor.x-rect.left));line.setAttribute('y1',String(anchor.y-rect.top));
  line.setAttribute('x2',String(to.x-rect.left));line.setAttribute('y2',String(to.y-rect.top));
  line.style.display='';
}
function sceneControlObstacles(rect) {
  const boxes=[];
  // Reserve the apparatus, not every fracture fragment each animation frame.
  for(const part of machine?.parts||[]) {
    const mesh=meshes.get(part.name);if(!mesh?.visible)continue;
    const box=coachObjectBox([mesh]);
    // Large background surfaces are not editing targets. Reserving the
    // entire projected floor would leave no place for an edge callout.
    if(!box||box.width*box.height>rect.width*rect.height*.7)continue;
    boxes.push({left:box.x-4,right:box.x+box.width+4,top:box.y-4,bottom:box.y+box.height+4});
  }
  return boxes;
}
function positionLiveControls(){
  const rect=view.getBoundingClientRect(),occupied=[...view.querySelectorAll('#clock,#viewer-zoom,#viewer-perspective,#viewer-history,#piece-editor,#level-done')]
    .filter(n=>!n.hidden&&n.getClientRects().length).map(n=>n.getBoundingClientRect());
  for(const card of liveCards.children){
    let leader=liveControlLeaders.get(card);
    if(!leader){leader=document.createElementNS(controlLeaders.namespaceURI,'line');controlLeaders.append(leader);liveControlLeaders.set(card,leader);}
    leader.style.display='none';
    const released=card.dataset.restraint && readouts.joints?.some(j=>j.name===card.dataset.restraint&&j.attached===false);
    const release=card.querySelector('[data-release]');
    if(released) {
      release.textContent='Latch released';release.disabled=true;
      card.querySelector('output').textContent='The restrained part is free to move.';
    }
    const adjust=card.querySelector('.spring-adjust');
    if(adjust)adjust.disabled=!session||playing||world.t>0||liveControlPending||released||release.dataset.queuedRelease==='true';
    card.hidden=Boolean(ghost)||document.body.matches('.on-levels,.on-sandbox,.scene-win');if(card.hidden)continue;
    const anchor=card.anchor.clone().project(camera);card.hidden=Math.abs(anchor.z)>1||Math.abs(anchor.x)>1||Math.abs(anchor.y)>1;if(card.hidden)continue;
    if(card.matches(':active')){occupied.push(card.getBoundingClientRect());continue;}
    const x=rect.left+(anchor.x+1)*rect.width/2,y=rect.top+(1-anchor.y)*rect.height/2;
    const objects=[...meshes].filter(([name,m])=>m.visible&&(name===card.deviceName||name.startsWith(card.deviceName+' '))).map(([,m])=>m);
    const body=objects.length?coachObjectBox(objects):null;
    const bounds=body?{left:body.x,right:body.x+body.width,top:body.y,bottom:body.y+body.height}:{left:x-20,right:x+20,top:y-20,bottom:y+20};
    const at=pieceToolbarPosition(rect,bounds,card.getBoundingClientRect(),[...occupied,...sceneControlObstacles(rect)],{edgeOnly:true});
    card.style.left=`${at.x-rect.left}px`;card.style.top=`${at.y-rect.top}px`;occupied.push(card.getBoundingClientRect());
    controlLeader(leader,card,{x,y});
  }
  for(const [card,leader] of liveControlLeaders)if(!card.isConnected){leader.remove();liveControlLeaders.delete(card);}
}
function positionPieceEditor() {
  positionLiveControls();
  editorLeader.style.display='none';
  const editor=$('piece-editor');if(editor.hidden||!ghost)return;
  const box=ghostScreenBox();if(!box)return;
  if(editor.matches(':active')){controlLeader(editorLeader,editor,{x:(box.x0+box.x1)/2,y:(box.y0+box.y1)/2});return;}
  const rect=view.getBoundingClientRect();
  // The toolbar owns its position; readouts yield to it afterwards. Letting
  // both avoid each other's last position makes the buttons oscillate.
  const obstacles=[...view.querySelectorAll('#clock,#viewer-zoom,#viewer-perspective,#viewer-history')]
    .filter(n=>!n.hidden&&n.getClientRects().length).map(n=>n.getBoundingClientRect());
  const at=pieceToolbarPosition(rect,{left:box.x0,right:box.x1,top:box.y0,bottom:box.y1},editor.getBoundingClientRect(),
    [...obstacles,...sceneControlObstacles(rect)],{edgeOnly:true});
  editor.style.left=`${at.x-rect.left}px`;editor.style.top=`${at.y-rect.top}px`;
  controlLeader(editorLeader,editor,{x:(box.x0+box.x1)/2,y:(box.y0+box.y1)/2});
}

// What the pieces take to make with the ghost as it is, against the level's
// par: said while it is changed, so cutting a plank shorter shows the
// number fall. (Par is for the whole win, the run's energy too; on most
// levels that is next to nothing.)
function madeAgainstPar() {
  const mine = `your ${ghost.p.piece} ${ghost.index + 1}`;
  const others = Object.entries(placedEnergy).filter(([name]) => name !== mine).reduce((a, [, e]) => a + (e.j || 0), 0);
  const it = ghost.energy.j, all = others + it, par = level && level.par_energy_j;
  let said = `It takes ${energyText(it)} to make`;
  if (others) said += `; with your other pieces, ${energyText(all)}`;
  if (!par) return said + '.';
  return said + (all <= par ? `: under par (${energyText(par)}).` : `: ${energyText(all - par)} over par (${energyText(par)}).`);
}

function showGhostState() {
  $('focus-piece').hidden = !ghost || !ghostGroup.children.length;
  $('focus-piece').disabled = !ghost?.drawnAt || Boolean(ghost.busy);
  const cable=ghost && ['wire','power_cable'].includes(ghost.p.piece);
  const choosingTerminal=Boolean(cable && (ghost.p.piece==='wire'
    ?!ghost.p.a_terminal||!ghost.p.b_terminal:!ghost.p.a_port||!ghost.p.b_port));
  const checkingCable=Boolean(cable && !choosingTerminal && ghost.busy);
  if(cable)$('piece-editor').hidden=!ghost.was&&(choosingTerminal||checkingCable);
  const bar = document.querySelector('#piece-editor .down');
  if (bar && ghost) {
    bar.disabled = !ghost.fits || ghost.busy || !ghost.answered;
    // A scene click completes a rewire automatically; reserve this action
    // for a complete endpoint edit made through Precision controls.
    bar.hidden=Boolean(ghost.rewireKey && (choosingTerminal || checkingCable));
  }
  const said = document.querySelector('#ghost-bar .state');
  if (said && ghost) {
    said.className = 'state ' + (choosingTerminal || checkingCable ? '' : ghost.fits ? 'fits' : 'refused');
    const sunlight=solarSnapshot(),panel=sunlight.panels.find(p=>p.name===ghostName());
    const solarText=sunlight.error || (sunlight.pending?'measuring sunlight at this position…':panel?
      `Preview · ${Math.round(panel.sunlight_w)} W sunlight · ${panel.shaded?'center shaded by '+panel.shaded_by:panel.ray_cast?'center in sunlight':'face away from sun'}`:'sunlight not measured');
    said.textContent = choosingTerminal ? (socketSelection()?'Choose the other connection point.':'Choose the first connection point.') : checkingCable?'Checking connection…' : (ghost.fits ? (ghost.sun && ghost.sun.length
      ? `Fits · aim ${ghost.sun[0].off_sun_deg}° · ${solarText}` : 'Fits')
      : ghost.problems.join('; ')) + (ghost.joined ? ` · ${ghost.alignmentOnly ? 'aligned with' : 'joined to'} ${ghost.joined}` : '');
    said.title=ghost.fits && ghost.energy ? madeAgainstPar() : said.textContent;
  }
  const cost=$('ghost-cost');
  if(cost && ghost) cost.textContent=ghost.energy ? madeAgainstPar() : '';
}

function showGhostKnobs() {
  if (!ghost) return;
  for(const b of ghost.gaugeButtons||[])b.setAttribute('aria-pressed',String(b.dataset.gauge===ghost.p.size));
  for(const b of ghost.choiceButtons||[])b.setAttribute('aria-pressed',String(b.dataset.value===String(ghost.p[b.dataset.key])));
  showGridSnap();
  const knobs = trayItem(ghost.p.piece).knobs;
  const rule=knobs[ghost.card];if(!rule)return; // Connecting ghosts have no selected setting until their editor is built.
  const choice=$('adjustment-choice');if(choice)choice.value=ghost.card;
  const springLength=$('piece-editor').querySelector('.spring-length-controls');
  if(springLength){
    springLength.querySelector('output').textContent=`${Number((ghost.p.rest_m*100).toFixed(2))} cm`;
    for(const control of springLength.querySelectorAll('button'))control.disabled=Number(control.dataset.springDirection)<0?
      ghost.p.rest_m<=knobs.rest_m.min+1e-9:ghost.p.rest_m>=knobs.rest_m.max-1e-9;
  }
  for(const field of $('piece-editor').querySelectorAll('[data-gear-key]')){
    const key=field.dataset.gearKey;
    field.querySelector('.gear-value').textContent=key==='teeth'?String(ghost.p.teeth):
      key==='module_m'?`${((ghost.p.teeth/2+.7)*ghost.p.module_m*100).toFixed(1)} cm`:`${Math.round(ghost.p.height_m*100)} cm`;
    field.setAttribute('aria-description',`${key==='height_m'?'Axle height':knobName(knobs[key],key)}: ${field.querySelector('.gear-value').textContent}`);
    field.setAttribute('aria-pressed',String(ghost.card===key));
  }
  const cycle=$('piece-editor').querySelector('.choice-cycle button');if(cycle)cycle.textContent=choiceText(ghost.card,ghost.p[ghost.card]);
  const rating=electricalEditRating(),numeric=typeof ghost.p[ghost.card]==='number';
  const units=rule.turning?'°':(rule.label||'').match(/\(([^()]*)\)\s*$/)?.[1]||'';
  const shownValue=`${ghost.p[ghost.card]}${units?' '+units:''}`;
  const feedback=$('adjustment-feedback');if(feedback)feedback.textContent=ghost.p.piece==='gear'?
    `${ghost.p.teeth} teeth · ${((ghost.p.teeth/2+.7)*ghost.p.module_m*100).toFixed(1)} cm radius · ${(ghost.p.height_m*100).toFixed(0)} cm height`:
    springLength&&ghost.card==='rest_m'?rating:
    rating?(numeric?`${shownValue} · ${rating}`:rating):`${knobName(rule,ghost.card)}: ${shownValue}`;
  const value = document.querySelector('#ghost-bar .knob-value');
  if (value) value.textContent = ` ${ghost.p[ghost.card]}${knobs[ghost.card].turning ? '°' : ''}`;
  for (const [key, [input, shown]] of Object.entries(ghost.inputs)) {
    if (String(input.value) !== String(ghost.p[key])) input.value = ghost.p[key];
    shown.textContent = String(ghost.p[key]) + (knobs[key].turning ? '°' : '');
  }
  if (ghost.cardInput) {
    const [input, shown, key] = ghost.cardInput;
    if (String(input.value) !== String(ghost.p[key])) input.value = ghost.p[key];
    if (shown) shown.value = ghost.p[key];
  }
}

window.machineGhostState = () => ghost ? {p: {...ghost.p}, index: ghost.index, fits: ghost.fits, problems: ghost.problems,
  follow: false, busy: ghost.busy, answered: ghost.answered, parts: ghostGroup.children.length,
  editGuide: ghost.editGuide?.key === ghost.card ? ghost.editGuide : null} : null;

// ---- the preview: where things will go ----------------------------------------------
// Before a run (and while it plays), the engine's own rehearsal of the level
// as it stands -- with a ghost as if it were set down -- drawn see-through:
// each loose thing's path, blue while it moves freely, green inside the goal
// zone, and after it hits something, that thing's colour, with a dot where it
// hit. A see-through copy of the goal's thing stands where it ends up.
const previewGroup = new THREE.Group();
scene.add(previewGroup);
const HIT_COLOURS = [0xffb347, 0xff6bd6, 0xc38bff, 0xffe066, 0x7cf0e0, 0xff8080];
const FREE_COLOUR = 0x9fdcff, GOAL_COLOUR = 0x5fe08f;
const PREVIEW_DOT = new THREE.SphereGeometry(.02, 12, 8);
const previewEndLook = new THREE.MeshStandardMaterial({color: 0xcdeeff, transparent: true, opacity: .3, depthWrite: false});
let previewAsk = 0, previewTimer = null, previewOn = true, previewShown = null;
const flowGroup = new THREE.Group();
scene.add(flowGroup);
const tankWater=new THREE.Group();scene.add(tankWater);
const tankWaterMeshes=new Map(),tankWaterGeometry=new THREE.BoxGeometry(1,1,1);
const tankWaterLook=new THREE.MeshStandardMaterial({color:0x56bfff,transparent:true,opacity:.75,roughness:.25,depthWrite:false});
let waterDisplay=[];
function updateWaterDisplay() {
  const active=LEVEL_MODE && level && !document.body.matches('.on-sandbox,.on-levels');
  tankWater.visible=active;
  const setup=ghost?.water_setup || machine?.spouts || [];
  const sources=setup.filter(s=>s.reservoir_area_m2>0),current=readouts.pour?.sources || [];
  const predicted=setupOpticsVisible() && flowGroup.visible?previewShown?.flow_frames?.[flowIndex]?.water?.sources:null;
  const readings=predicted || (!ghost?current:(!flowPending?previewShown?.flow_frames?.[0]?.water?.sources:[])) || [];
  const byName=new Map(readings.map(s=>[s.name,s])),wanted=new Set(sources.map(s=>s.name));
  for(const [name,mesh] of tankWaterMeshes)if(!wanted.has(name)){tankWater.remove(mesh);tankWaterMeshes.delete(name);}
  waterDisplay=sources.map(source=>{
    const reading=byName.get(source.name),litres=reading?.remaining_m3!=null?reading.remaining_m3*1000:source.initial_volume_l;
    const opening=reading?.opening_fraction??source.opening_fraction??1;
    let mesh=tankWaterMeshes.get(source.name);
    if(!mesh){mesh=new THREE.Mesh(tankWaterGeometry,tankWaterLook);tankWaterMeshes.set(source.name,mesh);tankWater.add(mesh);}
    const floor=source.reservoir_floor_m || [source.at_m[0],source.at_m[1]+(source.head_offset_m||0),source.at_m[2]];
    const width=Math.sqrt(source.reservoir_area_m2),height=litres/1000/source.reservoir_area_m2;
    mesh.scale.set(width,height,width);mesh.position.set(floor[0],floor[1]+height/2,floor[2]);mesh.visible=height>0;
    return {name:source.name,litres,opening,flow_l_s:reading?.flow_l_s??null,preview:Boolean(predicted),height_m:height};
  });
  const meter=$('water-status');meter.hidden=!active || !waterDisplay.length;
  if(!meter.hidden){
    const selected=waterDisplay.find(s=>s.name===ghostName()+' outlet') || waterDisplay[0];
    const text=`${waterDisplay.length>1?waterDisplay.length+' tanks · ':''}${selected.preview?'Preview · ':''}${selected.litres.toFixed(2)} L · tap ${Math.round(selected.opening*100)}% · ${selected.flow_l_s==null?'Updating flow…':selected.flow_l_s.toFixed(2)+' L/s'}`;
    if(meter.textContent!==text)meter.textContent=text;
  }
  const collector=$('collector-status');
  const preview=world.t===0 && setupOpticsVisible();
  const regions=preview && flowGroup.visible?(previewShown?.flow_frames?.[flowIndex]?.water?.regions || readouts.water_regions):readouts.water_regions;
  const region=regions?.[0];
  collector.hidden=!active || !region || (preview && flowPending);
  if(!collector.hidden){
    const timed=Boolean(level.goal?.station?.done_when?.water_in_zone_l);
    const time=preview && flowGroup.visible?previewShown.flow_frames[flowIndex]?.t||0:world.t;
    const left=Math.max(0,(level.time_s||0)-time);
    const goal=readouts.stations?.[0],filled=goal?.done&&goal.at_s<=level.time_s;
    collector.textContent=`${preview && flowGroup.visible?'Preview · ':''}Container ${region.litres.toFixed(2)} / ${region.target_l.toFixed(0)} L${timed && !preview?` · ${filled?'Filled in '+goal.at_s.toFixed(1)+' s':left>0&&!scored?left.toFixed(1)+' s left':'Time up'}`:''}`;
    collector.title='Water currently inside the marked volume, measured from the engine’s parcels. Water passing outside does not count.'+
      (timed?` At least ${region.target_l} L must stay inside for ${level.goal.station.done_when.water_in_zone_l.for_s||0} s before the ${level.time_s} s deadline.`:'');
    const point=new THREE.Vector3(...region.at_m).project(camera);
    collector.hidden=Math.abs(point.z)>1 || Math.abs(point.x)>1 || Math.abs(point.y)>1;
    positionSceneReading(collector,{x:(point.x+1)*view.clientWidth/2,y:(1-point.y)*view.clientHeight/2});
  }
  if(collector.hidden)sceneReadingLeaders.get(collector.id)?.setAttribute('visibility','hidden');
  updateRiverWheelStatus();
}
function updateRiverWheelStatus(){
  const output=$('river-wheel-status');
  const index=ghost?.p?.piece==='water_wheel'?ghost.index:placements.findIndex(p=>p.piece==='water_wheel');
  const p=ghost?.p?.piece==='water_wheel'?ghost.p:placements[index];
  output.hidden=!(machine?.ground?.discharge_m3_s>0 && p);
  if(output.hidden)return;
  const name=`your water_wheel ${index+1}`,preview=world.t===0;
  const frame=flowGroup.visible?previewShown?.flow_frames?.[flowIndex]:null;
  const joints=preview?(frame?.mechanism_joints||[]):readouts.joints||[];
  const axle=joints.find(j=>j.kind==='hinge'&&j.b===name);
  const rule=level.goal?.station?.done_when?.rose_m;
  const body=rule && (preview?frame?.mechanisms?.find(b=>b.name===rule.part):world.bodies.get(rule.part));
  const initial=preview?body?.initial_position_m:machine.parts.find(b=>b.name===rule?.part)?.at_m;
  const rise=body&&initial?Math.max(0,(body.position_m[1]-initial[1])*100):0;
  const outside=Math.abs(p.z_m||0)>machine.ground.trench_width_m/2+.18;
  const rope=rule?(p.load_part===rule.part?'Rope connected to gate':'Rope not connected'):'';
  output.textContent=outside?'Wheel on bank · drag into the marked river':flowPending&&preview?'Updating wheel preview…':
    `${preview?'Preview · ':''}Wheel ${Math.abs(axle?.turned_deg||0).toFixed(0)}°${rule?` · Gate up ${rise.toFixed(1)} cm`:''}${rope?` · ${rope}`:''}`;
}
window.machineWaterDisplay=()=>waterDisplay.map(row=>({...row}));

// A small independent native trace keeps light visible during rapid edits.
// Full machine rehearsals still own the ball/water/current timeline. An old
// beam is retained and labelled while its replacement is being calculated.
const laserBeam=new THREE.LineSegments(new THREE.BufferGeometry(),
  new THREE.LineBasicMaterial({vertexColors:true,transparent:true,opacity:.9,depthWrite:false}));
laserBeam.visible=false; scene.add(laserBeam);
const lensLines=new THREE.LineSegments(new THREE.BufferGeometry(),
  new THREE.LineBasicMaterial({color:0x82e9ff,transparent:true,opacity:.95,depthWrite:false}));
scene.add(lensLines);
let laserResult=null,laserStamp='',laserWanted='',laserVersion=0,laserTimer=null,laserBusy=false,laserPending=false,laserError='';
const opticalSetup=()=>ghost?.answered?ghost.optical_setup:machine?.light;
const setupOpticsVisible=()=>LEVEL_MODE && level && !playing && !(world?.t>0) && !document.body.matches('.on-sandbox,.on-levels');
function resetLaserPreview() {
  clearTimeout(laserTimer);laserVersion++;laserWanted='';laserStamp='';laserResult=null;laserPending=false;laserError='';
  laserBeam.visible=false;laserBeam.geometry.dispose();laserBeam.geometry=new THREE.BufferGeometry();
  $('laser-preview-status').hidden=true;
}
function scheduleLaserPreview(ms=140) {
  if (!setupOpticsVisible() || !opticalSetup()?.lamps?.length) {resetLaserPreview();return;}
  const request={op:'level_optics',level:level.id,...sandboxRequest(),placements:ghost?ghostPlacements():placements};
  const stamp=JSON.stringify(request);
  if (stamp===laserWanted && (laserPending || stamp===laserStamp)) return;
  clearTimeout(laserTimer);laserWanted=stamp;laserVersion++;laserPending=true;laserError='';
  laserTimer=setTimeout(()=>askLaserPreview(),ms);
}
async function askLaserPreview() {
  if (laserBusy || !laserWanted || !setupOpticsVisible()) return;
  const stamp=laserWanted,mine=laserVersion;laserBusy=true;
  try {
    const result=await api(JSON.parse(stamp));
    if (mine!==laserVersion || !setupOpticsVisible()) return;
    const light=beamSegments(result.paths),geometry=new THREE.BufferGeometry();
    geometry.setAttribute('position',new THREE.BufferAttribute(light.positions,3));
    geometry.setAttribute('color',new THREE.BufferAttribute(light.colors,3));
    laserBeam.geometry.dispose();laserBeam.geometry=geometry;
    laserResult=result;laserStamp=stamp;laserPending=false;
  } catch (error) {
    if (mine!==laserVersion) return;
    if (error.status===503) laserTimer=setTimeout(()=>askLaserPreview(),500);
    else {laserPending=false;laserError=`Laser preview unavailable: ${error.message}`;}
  } finally {
    laserBusy=false;
    if (laserWanted && mine!==laserVersion && setupOpticsVisible()) {
      clearTimeout(laserTimer);laserTimer=setTimeout(()=>askLaserPreview(),0);
    }
  }
}
function updateLaserPreview() {
  const active=setupOpticsVisible() && Boolean(opticalSetup()?.lamps?.length);
  laserBeam.visible=active && Boolean(laserResult?.paths?.length);
  if (laserBeam.visible && beams) beams.visible=false;
  const status=$('laser-preview-status');status.hidden=!active;
  if (active) {
    const readings=(laserResult?.photocells||[]).map(p=>`${p.name}: ${Number(p.power_w||0).toFixed(2)} W`).join(' · ');
    const text=laserError || (laserPending?'Updating laser preview…':`Laser preview${readings?' · '+readings:''}`);
    if (status.textContent!==text) status.textContent=text;
  }
}
function drawLensOutlines() {
  const optics=opticalSetup(),segments=(optics?.lenses||[]).flatMap(lens=>lensOutline(lens));
  lensLines.geometry.dispose();lensLines.geometry=new THREE.BufferGeometry().setAttribute('position',new THREE.Float32BufferAttribute(segments,3));
}
function positionLensGrip() {
  const grip=$('lens-grip'),lens=ghost?.optical_setup?.lenses?.find(l=>l.on===ghostName());
  grip.hidden=!lens || !setupOpticsVisible();
  if (grip.hidden) return;
  const screen=new THREE.Vector3(...lens.at_m).add(ghostGroup.position).project(camera);
  const x=(screen.x+1)*view.clientWidth/2,y=(1-screen.y)*view.clientHeight/2;
  grip.hidden=Math.abs(screen.z)>1 || x<24 || y<24 || x>view.clientWidth-24 || y>view.clientHeight-40;
  grip.style.left=`${x}px`;grip.style.top=`${y}px`;
}
window.machineLaserPreviewState=()=>({visible:laserBeam.visible,pending:laserPending,stamp:laserStamp,wanted:laserWanted,
  paths:laserResult?.paths||[],photocells:laserResult?.photocells||[],world_time_s:laserResult?.world_time_s,
  wall_s:laserResult?.wall_s,error:laserError});
let flowIndex = -1, flowTime = 0, flowPlaying = true, flowTick = 0;
let flowPending=false;
const flowLabels = [];
const powerFeedbackRows = new Map();
const feedbackLeaders=document.createElementNS('http://www.w3.org/2000/svg','svg');
feedbackLeaders.classList.add('feedback-leaders');feedbackLeaders.setAttribute('aria-hidden','true');
$('power-feedback-labels').append(feedbackLeaders);
const sceneReadingLeaders=new Map();
const powerFlowDots = new THREE.InstancedMesh(new THREE.SphereGeometry(.014,8,6),
  new THREE.MeshBasicMaterial({color:0xfff1a6,depthTest:false}),64);
powerFlowDots.count=0;powerFlowDots.frustumCulled=false;scene.add(powerFlowDots);

function powerFeedbackSnapshot() {
  const preview=flowGroup.visible&&flowIndex>=0?previewShown?.flow_frames?.[flowIndex]:null;
  if(preview) return {preview:true,wires:preview.wires||[],devices:preview.power_devices||[]};
  const samples=[];
  for(const w of wires) {
    if(w.powerCable) {
      samples.push({name:w.name,points_m:w.route,unit:'W',routed:true,
        value:readouts.machines?.solar_panels?.find(p=>p.name===w.panel)?.power_w||0});
    } else if(w.terminalWire) {
      const live=readouts.electrical?.wires?.find(r=>r.name===w.name);
      if(w.route) samples.push({...live,name:w.name,points_m:w.route,unit:'A',value:live?.current_a||0,routed:true});
    } else {
      const live=readouts.circuits?.find(c=>c.name===w.name);
      const points=w.route||[world.bodies.get(w.from)?.position_m,w.via,
        w.to?world.bodies.get(w.to)?.position_m:w.toPoint].filter(Boolean);
      if(points.length>1) samples.push({name:w.name+(w.leg?'/'+w.leg:''),points_m:points,
        unit:'A',value:live?.current_a||0,through_w:live?.power_w||0,return_path:w.leg==='return',routed:Boolean(w.route)});
    }
  }
  return {preview:false,wires:samples,devices:readouts.power_devices||[]};
}

function feedbackCurve(w) {
  const drawn=wires.find(row=>row.name===w.name&&row.route?.length>1);
  const pts=(drawn?.route||w.points_m).map(p=>new THREE.Vector3(...p));
  const lane=(shownElectrical().wires||[]).findIndex(row=>row.name===w.name);
  if(w.routed||drawn) {
    const curve=new THREE.CurvePath();
    for(let i=1;i<pts.length;i++)curve.add(new THREE.LineCurve3(pts[i-1],pts[i]));
    return curve;
  }
  if(w.unit==='A'&&lane>=0&&pts.length===2) return routedCurve(w.points_m[0],w.points_m[1],lane);
  if(pts.length===2) return new THREE.QuadraticBezierCurve3(pts[0],new THREE.Vector3(
    (pts[0].x+pts[1].x)/2,Math.max(pts[0].y,pts[1].y)+(w.unit==='W'?.18:.1),(pts[0].z+pts[1].z)/2),pts[1]);
  return new THREE.CatmullRomCurve3(pts);
}

function updatePowerFeedback() {
  updateSolarLiftGuide();
  updateWireAdjustments();
  const host=$('power-feedback-labels'),sample=powerFeedbackSnapshot(),items=[];
  const pending=!(world?.t>0)&&!playing&&Boolean(flowPending||ghost&&!ghost.answered);
  powerFlowDots.count=0;
  if(!machine||document.body.matches('.on-levels,.on-sandbox')) {host.hidden=true;return;}
  host.hidden=false;
  const rating=electricalEditRating(),proposed=ghost?.proposedParts?.find(p=>p.name.startsWith(ghostName()));
  for(const wire of wires.filter(w=>w.connected&&w.route?.length===0)) {
    const at=wire.points_m?.[0]||terminalMap(machine.electrical).get(wire.a);
    if(at)items.push({id:'route:'+wire.name,name:wire.name,kind:'wire',at,text:'Cable route blocked · move its endpoints',
      title:'No drawing route clears the solid parts. This is an electrical connection without a mechanical cable model.'});
  }
  if(rating&&proposed){
    const rule=trayItem(ghost.p.piece).knobs[ghost.card],unit=rule?.label?.match(/\(([^)]+)\)/)?.[1]||'';
    const compact=Number.isFinite(ghost.p[ghost.card])?`Proposed ${ghost.p[ghost.card]}${unit?' '+unit:''}`:rating;
    items.push({id:'proposed-setting',name:`Adjust ${pieceLabel(ghost.p.piece)}`,kind:'object',priority:-1,at:proposed.at_m,text:compact,
      title:rating+(ghost.p.piece==='spring'?'. Proposed spring settings; the engine measures motion after release.':'. Measured voltage, current and power remain separate.')});
  }
  for(const d of sample.devices) {
    const at=world.bodies.get(d.part)?.position_m||d.at_m;if(!at)continue;
    if(d.requirement==='heater') {
      items.push({id:'device:'+d.name,name:'Heater',kind:'object',at,
        text:`${d.resistance_ohm} Ω · ${d.clipped_to?'clipped to '+d.clipped_to:'not attached'}\n${pending?'Updating…':`${sample.preview?'Preview':'Now'} ${d.input_w.toFixed(0)} W · ${Math.abs(d.current_a).toFixed(2)} A`}`+
          (Number.isFinite(d.material_temperature_k)?`\n${d.clipped_to?'Material':'Heater'} ${(d.material_temperature_k-273.15).toFixed(0)} °C${d.burning?' · burning':''}`:''),
        title:'Native current supplies I²R heat to the body this clip is mounted on. The winding uses the existing ideal lumped thermal coupling; surface contact heat transport is not modeled.'});
      continue;
    }
    if(d.requirement==='capacitor'||d.requirement==='resistor') {
      const storage=d.requirement==='capacitor';
      items.push({id:'device:'+d.name,name:d.name.replace(/^your /,''),kind:'object',priority:d.required_j?0:1,at,
        text:storage?`${d.capacitance_f} F${d.required_j?` · Goal ≥ ${d.required_j} J`:''}\n${pending?'Updating…':`${sample.preview?'Preview':'Now'} ${d.capacitor_voltage_v.toFixed(2)} V · ${d.stored_j.toFixed(2)} J`}`:
          `${d.resistance_ohm} Ω\n${pending?'Updating…':`${sample.preview?'Preview':'Now'} ${Math.abs(d.voltage_v).toFixed(2)} V drop · ${Math.abs(d.current_a).toFixed(3)} A`}`,
        low:storage&&d.required_j&&d.stored_j<d.required_j,
        title:storage?`Measured current ${d.current_a.toFixed(3)} A. Nonpolar rated capacitor. Signed current charges (+) or discharges (−) the A-to-B voltage. Stored energy is measured by the native solver.`:'Rated resistance; measured voltage drop and current determine Joule heat.'});
      continue;
    }
    let need;
    if(d.requirement==='goal')need=`Goal ≥ ${d.required_w.toFixed(1)} W`;
    else if(d.requirement==='rated')need=`Rated ${d.rated_w.toFixed(1)} W`;
    else if(d.requirement==='start_estimate')need=d.exceeds_motor?
      `Needs ${d.required_torque_n_m.toFixed(1)} N·m; stall ${d.rated_torque_n_m.toFixed(1)}`:
      `Start ≈ ${d.required_w.toFixed(1)} W · ${d.required_torque_n_m.toFixed(1)} N·m`;
    else need=`Load varies · ${d.rated_torque_n_m.toFixed(1)} N·m stall`;
    if(Number.isFinite(d.rated_voltage_v))need=`Rated ${d.rated_voltage_v} V · ${d.rated_w.toFixed(1)} W`+
      (d.requirement==='goal'?` · Goal ≥ ${d.required_w.toFixed(1)} W`:'');
    // Keep a lesson's supply limit with its objective when a short screen
    // cannot also fit a separate wire reading at the edge.
    const supply=sample.wires.find(w=>w.show_supply_limit&&Number.isFinite(w.supply_max_power_w));
    if(d.requirement==='goal'&&supply)need+=`\nShared supply ≤ ${supply.supply_max_power_w.toFixed(1)} W · ${supply.supply_voltage_v} V`;
    let actual=d.input_w<-.05?`${Math.abs(d.input_w).toFixed(1)} W returned`:`${Math.max(0,d.input_w).toFixed(1)} W in`;
    if(Number.isFinite(d.voltage_v))actual+=` · ${Math.abs(d.voltage_v).toFixed(1)} V`;
    if(Number.isFinite(d.torque_n_m))actual+=` · ${Math.abs(d.torque_n_m).toFixed(1)} N·m`;
    items.push({id:'device:'+d.name,name:d.name.replace(/^your /,''),kind:'object',priority:d.requirement==='goal'?0:1,at,
      displayName:solarLiftGraph()?.network.devices.some(n=>n.name===d.name&&n.kind==='bulb')?'Bulb · shared load':
        d.requirement==='start_estimate'?`${d.part.replace(/^your /,'')} · ${d.name.replace(/^your /,'')}`:d.name.replace(/^your /,''),
      text:`${need}\n${pending?'Updating…':`${sample.preview?'Preview':'Now'} ${actual}`}`,
      low:d.exceeds_motor||((d.requirement==='goal'||d.requirement==='start_estimate')&&d.input_w<d.required_w),
      title:d.requirement==='start_estimate'?'Estimated electrical power to overcome gravity and bearing friction at rest. Acceleration, contacts, other loads and supply losses need more power.':
        d.requirement==='rated'?'Full-brightness power rating, not an on/off threshold.':
        d.requirement==='variable'?'Contacts or connected mechanisms change the torque needed. Stall torque is its full-command rating at rest, not a guaranteed movement threshold.':'The existing level measures power arriving at this object.'});
  }
  const dotMatrix=new THREE.Matrix4(),time=performance.now()/1000;
  // A current indicator on the metal bridge, never across an open gap.
  // This visualises the native branch current; it is not an electrical law.
  for (const device of machine.electrical?.devices || []) {
    if (device.kind!=='switch'||!device.touch||flowGroup.visible) continue;
    const measured=readouts.electrical?.devices?.find(d=>d.name===device.name);
    const a=terminalAt(device,'in',device.terminals.in),b=terminalAt(device,'out',device.terminals.out);
    if (!a||!b) continue;
    items.push({id:'contact:'+device.name,name:device.name.replace(/^your /,''),kind:'object',at:b,
      text:`Metal contact ${measured?.closed?'closed':'open'} · ${Math.abs(measured?.current_a||0).toFixed(3)} A`,
      title:'The moving iron leaf must touch its separate iron output pad. Closing a contact powers a load only when the full supply and return loop is connected.'});
    if (!measured?.closed||Math.abs(measured.current_a||0)<=1e-4||pending) continue;
    const start=electricalStartPoses.get(device.touch[0]);if(!start)continue;
    const localTip=[2*start.position_m[0]-device.terminals.in[0],2*start.position_m[1]-device.terminals.in[1],device.terminals.in[2]];
    const tip=terminalAt(device,'in',localTip);
    const curve=new THREE.CurvePath();
    curve.add(new THREE.LineCurve3(new THREE.Vector3(...a),new THREE.Vector3(...tip)));
    curve.add(new THREE.LineCurve3(new THREE.Vector3(...tip),new THREE.Vector3(...b)));
    for (const offset of [0,.5]) {
      const t=((time*.7*Math.sign(measured.current_a)+offset)%1+1)%1;
      powerFlowDots.setMatrixAt(powerFlowDots.count++,dotMatrix.makeTranslation(...curve.getPoint(t).toArray()));
    }
  }
  for(const w of sample.wires.filter(w=>w.points_m?.length>1).slice(0,12)) {
    const declaration=(shownElectrical().wires||[]).find(row=>row.name===w.name);
    const area=declaration?.area_mm2;
    const gauge=Number.isFinite(area)?`${({.01:'Thin',.5:'Standard',2.5:'Thick'})[area]||'Copper'} · ${area} mm²`:
      w.unit==='A'&&Number.isFinite(declaration?.resistance_ohm)?`Low resistance · ${declaration.resistance_ohm.toFixed(3)} Ω`:'';
    const curve=feedbackCurve(w),active=Math.abs(w.value)>1e-4;
    const watts=w.unit==='W'?Math.abs(w.value):Math.abs(w.through_w||0);
    if(active&&!pending)for(const offset of [0,.5]) {
      const t=((time*(.35+Math.min(1,Math.log1p(watts)/5))*Math.sign(w.value)+offset)%1+1)%1;
      powerFlowDots.setMatrixAt(powerFlowDots.count++,dotMatrix.makeTranslation(...curve.getPoint(t).toArray()));
    }
    let text=w.unit==='W'?`${watts.toFixed(1)} W`:
      w.return_path?`Return · ${Math.abs(w.value).toFixed(3)} A`:`${watts.toFixed(1)} W · ${Math.abs(w.value).toFixed(3)} A`;
    if(w.show_supply_limit&&Number.isFinite(w.supply_max_power_w))text+=`\nShared supply ≤ ${w.supply_max_power_w.toFixed(1)} W · ${w.supply_voltage_v} V`;
    const drawnWire=wires.find(row=>row.name===w.name&&row.line.visible);
    const labelCurve=drawnWire?.line.geometry.parameters?.path||curve;
    items.push({id:'wire:'+w.name,name:w.name,kind:'wire',at:labelCurve.getPoint(.5).toArray(),
      text:(gauge?((ghost?.p.piece==='wire'&&ghost.busy)?'Gauge updating…':gauge)+'\n':'')+
        (pending?'Updating…':(sample.preview?'Preview · ':'')+text),title:'Wire cross-section is the declared copper area used by the engine to calculate resistance. Measured flow and shared supply limits include losses; dots show conventional-current direction. Return-wire watts depend on the battery-negative reference.'});
  }
  powerFlowDots.instanceMatrix.needsUpdate=true;
  // Keep the current edit and the measured objective readable when edge
  // labels compete for a small screen; optional wire readings come after.
  const labelPriority=item=>item.priority??(item.kind==='object'?1:2);
  items.sort((a,b)=>labelPriority(a)-labelPriority(b));
  const seen=new Set(items.map(i=>i.id));
  for(const [id,row] of powerFeedbackRows)if(!seen.has(id)){row.card.remove();row.leader.remove();powerFeedbackRows.delete(id);}
  const rect=renderer.domElement.getBoundingClientRect();
  const occupied=[...view.querySelectorAll('#clock,#scene-mode,#viewer-zoom,#viewer-perspective,#piece-editor, #viewer-history,#collector-status,.power-pin,.terminal-control-pin,.inspect-switch,#thermal-readout,#scene-actions,#machine-controls,#attach-card,#level-done,#scene-wire-hint,#piece-handles button:not([hidden])')]
    .filter(el=>!el.hidden&&el.getClientRects().length).map(el=>{const r=el.getBoundingClientRect();return {x:r.left-rect.left,y:r.top-rect.top,w:r.width,h:r.height};});
  // A power reading must not hide the connection the player is trying to
  // click, especially on a phone. Reserve the rings before placing labels.
  occupied.push(...sceneSockets().map(p=>({x:p.x-rect.left-14,y:p.y-rect.top-14,w:28,h:28})));
  occupied.push(...readoutBodyRects(rect,sample.devices));
  const top=sceneReadoutTop(rect),bottom=rect.height-26;
  for(const item of items) {
    let row=powerFeedbackRows.get(item.id);
    if(!row) {
      const editableWire=item.kind==='wire' && /^your (wire|power_cable) \d+$/.test(item.name);
      const card=document.createElement(editableWire?'button':'section');card.className='power-feedback-label '+item.kind;
      if(editableWire){card.type='button';card.setAttribute('aria-label',`Adjust ${item.name}`);card.classList.add('editable-wire');
        card.addEventListener('click',()=>{const index=Number(item.name.match(/ (\d+)$/)[1])-1;if(placements[index])pickUp(index);});}
      card.dataset[item.kind==='object'?'device':'wire']=item.name;
      const name=document.createElement('strong'),output=document.createElement('output');card.append(name,output);host.append(card);
      const leader=document.createElementNS(feedbackLeaders.namespaceURI,'line');feedbackLeaders.append(leader);
      row={card,name,output,leader};powerFeedbackRows.set(item.id,row);
    }
    const title=item.displayName||item.name;
    row.name.hidden=item.kind==='wire';if(row.name.textContent!==title)row.name.textContent=title;
    if(row.output.textContent!==item.text)row.output.textContent=item.text;row.card.title=item.title;
    if(row.card.classList.contains('editable-wire'))row.card.title+=' Click this label to adjust the wire; click its cable to remove it.';
    row.card.classList.toggle('low',Boolean(item.low));row.card.hidden=false;
    const p=new THREE.Vector3(...item.at).project(camera);
    row.leader.style.display='none';
    if(Math.abs(p.z)>1||Math.abs(p.x)>1||Math.abs(p.y)>1){row.card.hidden=true;continue;}
    const {width,height}=row.card.getBoundingClientRect();
    const ax=(p.x+1)*rect.width/2,ay=(1-p.y)*rect.height/2;
    const xs=readoutSideXs(ax,width,rect.width),ys=[ay-height/2,ay-height-14,ay+14,ay-height-38,ay+38,
      top,bottom-height,...occupied.flatMap(r=>[r.y-height-6,r.y+r.h+6])];
    const candidate=xs.flatMap(x=>ys.map(y=>({x:Math.max(6,Math.min(rect.width-width-6,x)),y})))
      .find(c=>c.y>=top&&c.y+height<=bottom&&!occupied.some(r=>c.x<r.x+r.w+4&&c.x+width+4>r.x&&c.y<r.y+r.h+4&&c.y+height+4>r.y));
    if(!candidate){row.card.hidden=true;continue;}
    row.card.style.left=`${candidate.x}px`;row.card.style.top=`${candidate.y}px`;occupied.push({...candidate,w:width,h:height});
    const placed=row.card.getBoundingClientRect(),labelX=placed.left-rect.left,labelY=placed.top-rect.top;
    row.leader.style.display='';
    row.leader.setAttribute('x1',String(ax));row.leader.setAttribute('y1',String(ay));
    row.leader.setAttribute('x2',String(Math.max(labelX,Math.min(labelX+placed.width,ax))));
    row.leader.setAttribute('y2',String(Math.max(labelY,Math.min(labelY+placed.height,ay))));
  }
}
function updateWireAdjustments() {
  const host=$('wire-adjustments');
  const rows=placements.flatMap((p,index)=>{
    if(!['wire','power_cable'].includes(p.piece))return [];
    const name=`your ${p.piece} ${index+1}`,d=(shownElectrical().wires||[]).find(w=>w.name===name);
    const area=d?.area_mm2,gauge=Number.isFinite(area)?`${({.01:'Thin',.5:'Standard',2.5:'Thick'})[area]||'Copper'} · ${area} mm²`:'';
    return [{index,label:`${p.piece==='wire'?'Wire':'Power cable'} ${index+1}${gauge?' · '+gauge:''}`}];
  });
  const key=JSON.stringify(rows);if(host.dataset.contents===key)return;host.dataset.contents=key;
  host.replaceChildren(...rows.map(row=>{const b=button(row.label,()=>pickUp(row.index));b.setAttribute('aria-label',`Adjust placed ${row.label}`);return b;}));
}
function readoutSideXs(anchor,width,viewWidth) {
  const sides=[6,Math.max(6,viewWidth-width-6)];
  return anchor<viewWidth/2?sides:sides.reverse();
}
function positionSceneReading(card,anchor) {
  const rect=renderer.domElement.getBoundingClientRect();
  let leader=sceneReadingLeaders.get(card.id);
  if(!leader){leader=document.createElementNS(feedbackLeaders.namespaceURI,'line');leader.dataset.reading=card.id;feedbackLeaders.append(leader);sceneReadingLeaders.set(card.id,leader);}
  leader.setAttribute('visibility','hidden');if(card.hidden)return;
  const {width,height}=card.getBoundingClientRect(),top=sceneReadoutTop(rect);
  const occupied=[...view.querySelectorAll('#scene-mode,#viewer-zoom,#viewer-perspective,#piece-editor, #viewer-history,.power-pin,.terminal-control-pin,.power-feedback-label,.inspect-switch,#thermal-readout,#level-done,#scene-wire-hint,#piece-handles button:not([hidden])')]
    .filter(el=>!el.hidden&&el.getClientRects().length).map(el=>{const r=el.getBoundingClientRect();return {x:r.left-rect.left,y:r.top-rect.top,w:r.width,h:r.height};});
  occupied.push(...readoutBodyRects(rect),{x:anchor.x-18,y:anchor.y-18,w:36,h:36});
  const ys=[anchor.y-height/2,top,rect.height-height-6,...occupied.flatMap(r=>[r.y-height-6,r.y+r.h+6])];
  const candidate=readoutSideXs(anchor.x,width,rect.width).flatMap(x=>ys.map(y=>({x,y})))
    .find(c=>c.y>=top&&c.y+height<=rect.height-6&&!occupied.some(r=>c.x<r.x+r.w+4&&c.x+width+4>r.x&&c.y<r.y+r.h+4&&c.y+height+4>r.y));
  if(!candidate){card.hidden=true;return;}
  card.style.left=`${candidate.x}px`;card.style.top=`${candidate.y}px`;
  const placed=card.getBoundingClientRect(),x=placed.left-rect.left,y=placed.top-rect.top;
  leader.setAttribute('visibility','visible');leader.setAttribute('x1',String(anchor.x));leader.setAttribute('y1',String(anchor.y));
  leader.setAttribute('x2',String(Math.max(x,Math.min(x+placed.width,anchor.x))));
  leader.setAttribute('y2',String(Math.max(y,Math.min(y+placed.height,anchor.y))));
}
function readoutBodyRects(rect,devices=[]) {
  const boxes=[];
  const names=new Set([...(shownElectrical().devices||[]),...(machine?.solar_panels||[]),...(readouts.power_devices||[]),...devices].map(d=>d.part));
  const protectedMeshes=[...names].map(name=>meshes.get(name)).filter(m=>m?.visible);
  if(ghost&&!['wire','power_cable'].includes(ghost.p.piece)&&ghostGroup.children.length)protectedMeshes.push(ghostGroup);
  for(const mesh of protectedMeshes) {
    const b=new THREE.Box3().setFromObject(mesh),points=[];
    for(const x of [b.min.x,b.max.x])for(const y of [b.min.y,b.max.y])for(const z of [b.min.z,b.max.z]) {
      const p=new THREE.Vector3(x,y,z).project(camera);
      if(p.z>=-1&&p.z<=1)points.push({x:(p.x+1)*rect.width/2,y:(1-p.y)*rect.height/2});
    }
    if(!points.length)continue;
    const x=Math.min(...points.map(p=>p.x)),y=Math.min(...points.map(p=>p.y));
    boxes.push({x:x-4,y:y-4,w:Math.max(...points.map(p=>p.x))-x+8,h:Math.max(...points.map(p=>p.y))-y+8});
  }
  return boxes;
}
window.machinePowerFeedbackState=()=>({dots:powerFlowDots.count,
  labels:[...powerFeedbackRows.values()].filter(r=>!r.card.hidden).map(r=>({device:r.card.dataset.device,wire:r.card.dataset.wire,text:r.output.textContent}))});
window.machineReadoutCallouts=()=>{
  const rect=renderer.domElement.getBoundingClientRect();
  return {width:rect.width,height:rect.height,bodies:readoutBodyRects(rect),
    labels:[...powerFeedbackRows.values()].filter(r=>!r.card.hidden).map(r=>{
      const box=r.card.getBoundingClientRect();return {wire:r.card.dataset.wire,device:r.card.dataset.device,
        x:box.left-rect.left,y:box.top-rect.top,w:box.width,h:box.height,
        leader:r.leader.style.display!=='none',
        from:[Number(r.leader.getAttribute('x1')),Number(r.leader.getAttribute('y1'))],
        to:[Number(r.leader.getAttribute('x2')),Number(r.leader.getAttribute('y2'))]};})};
};

function clearFlowFrame() {
  for (const child of [...flowGroup.children]) {
    if(child===flowMechanismGroup)continue;
    flowGroup.remove(child);
    child.traverse(o => {
      o.geometry?.dispose();
      for (const m of Array.isArray(o.material) ? o.material : o.material ? [o.material] : []) {
        m.map?.dispose(); m.dispose();
      }
    });
  }
  flowLabels.length = 0;
}

const flowMechanismGroup=new THREE.Group();flowGroup.add(flowMechanismGroup);
const flowMechanismMeshes=new Map();
function clearFlowMechanisms(){
  for(const mesh of flowMechanismMeshes.values()){
    flowMechanismGroup.remove(mesh);
    const disposed=new Set();mesh.traverse(o=>{
      if(o.isMesh)o.geometry?.dispose();
      if(o.isMesh && o.material && !disposed.has(o.material)){o.material.dispose();disposed.add(o.material);}
    });
  }
  flowMechanismMeshes.clear();
  for(const child of ghostGroup.children)child.visible=true;
}
function drawFlowMechanisms(frame){
  const shapes=new Map((previewShown?.mechanism_shapes||[]).map(b=>[b.name,b]));
  for(const pose of frame.mechanisms||[]){
    const shape=shapes.get(pose.name);if(!shape)continue;
    let mesh=flowMechanismMeshes.get(pose.name);
    if(!mesh){
      mesh=makeMesh(shape);flowMechanismGroup.add(mesh);flowMechanismMeshes.set(pose.name,mesh);
      mesh.traverse(o=>{if(o.isMesh){
        if(o.material===stripeLook)o.material=stripeLook.clone();
        o.material.transparent=true;o.material.opacity=.8;o.material.depthWrite=false;
        o.material.color.lerp(new THREE.Color(0x6bd1ef),.25);
      }});
    }
    place(mesh,pose);mesh.visible=true;
  }
  const names=new Set((frame.mechanisms||[]).map(p=>p.name));
  for(const [name,mesh] of flowMechanismMeshes)mesh.visible=names.has(name);
  for(const j of frame.mechanism_joints||[]){
    if(j.kind!=='drum'||!j.leaves||!j.meets)continue;
    const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(...j.leaves),new THREE.Vector3(...j.meets)]),
      new THREE.LineBasicMaterial({color:0xead4a0,depthWrite:false}));
    flowGroup.add(line);
  }
}
function syncFlowMechanismVisibility(){
  for(const [name,mesh] of flowMechanismMeshes){
    if(flowGroup.visible&&mesh.visible){const original=meshes.get(name);if(original)original.visible=false;}
  }
  for(const child of ghostGroup.children)child.visible=!(flowGroup.visible&&flowMechanismMeshes.get(child.userData.partName)?.visible);
}

function flowLabel(text, point) {
  const canvas = document.createElement('canvas'); canvas.width = 160; canvas.height = 40;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#112431ee'; ctx.fillRect(0,0,160,40);
  ctx.font = 'bold 24px system-ui'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillStyle = '#ffe066'; ctx.fillText(text,80,20);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(canvas),depthTest:false,depthWrite:false}));
  sprite.visible = false;
  sprite.position.copy(point); flowGroup.add(sprite); flowLabels.push(sprite);
}

function drawFlowFrame(frame) {
  clearFlowFrame();
  drawFlowMechanisms(frame);
  // The sunlight lesson keeps the real bulb glow without displaying its
  // radiated rays as if they were a collector source. Native light is intact.
  const light = beamSegments(solarLiftGraph()&&!opticalSetup()?.lamps?.length?[]:frame.light);
  let arrows=0,bulbs=0;
  if (light.legs && !opticalSetup()?.lamps?.length) {
    const line = new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position',new THREE.BufferAttribute(light.positions,3)),
      new THREE.LineDashedMaterial({color:0xff8cdc,dashSize:.035,gapSize:.015,transparent:true,opacity:.85,depthWrite:false}));
    line.computeLineDistances(); flowGroup.add(line);
  }
  const water = frame.water?.xyz_mm || [];
  if (water.length) flowGroup.add(new THREE.Points(new THREE.BufferGeometry().setAttribute('position',
    new THREE.Float32BufferAttribute(water.map(v=>v/1000),3)),
    new THREE.PointsMaterial({color:0x62cfff,size:.045,transparent:true,opacity:.8,depthWrite:false})));
  const surface = frame.surface;
  if (surface?.xyz_mm?.length) {
    const tile = new THREE.PlaneGeometry(surface.cell_m,surface.cell_m); tile.rotateX(-Math.PI/2);
    const mesh = new THREE.InstancedMesh(tile,new THREE.MeshBasicMaterial({color:0x62cfff,transparent:true,opacity:.45,side:THREE.DoubleSide,depthWrite:false}),surface.xyz_mm.length/3);
    const matrix = new THREE.Matrix4();
    for (let i=0;i<mesh.count;i++) mesh.setMatrixAt(i,matrix.makeTranslation(...surface.xyz_mm.slice(i*3,i*3+3).map(v=>v/1000)));
    mesh.frustumCulled=false; flowGroup.add(mesh);
  }
  const riverArrows = waterCurrentArrows(surface?.flow_samples || [],surface?.cell_m || .02);
  if (riverArrows) flowGroup.add(riverArrows);
  for (const contact of frame.contacts||[]) {
    if (!contact.points_m?.length) continue;
    const points=contact.points_m.map(p=>new THREE.Vector3(...p));
    const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),
      new THREE.LineDashedMaterial({color:contact.closed===true?0x5fe08f:0xffad66,dashSize:.015,gapSize:.012,depthWrite:false}));
    line.computeLineDistances();flowGroup.add(line);
  }
  for (const [i,w] of (frame.wires || []).entries()) {
    const contact=frame.contact_circuits?.find(c=>c.name===w.circuit);
    const circuit=machine.circuits.find(c=>c.name===w.circuit);
    const diagram=contact&&circuit&&contactCircuitDiagram(circuit,machine,new Map(contact.bodies.map(b=>[b.name,b])));
    const leg=diagram?.legs.find(l=>l.id===w.legacy_leg), legLane=diagram?.legs.findIndex(l=>l.id===w.legacy_leg);
    const ends=leg?[leg.a,leg.b]:w.points_m;
    const pts = ends.map(p=>new THREE.Vector3(...p));
    const electrical = shownElectrical();
    const lane = (electrical.wires || []).findIndex(wire => wire.name === w.name);
    const routed = w.unit === 'A' && pts.length === 2 && lane >= 0;
    const route=pts.length===2?wireRoute(ends[0],ends[1],legLane>=0?legLane:Math.max(0,lane)):null;
    if(route?.length===0)continue;
    const curve = pts.length===2 ? routedCurve(ends[0],ends[1],legLane>=0?legLane:Math.max(0,lane))
      : new THREE.CatmullRomCurve3(pts);
    const active = Math.abs(w.value)>1e-4;
    const line = routed || leg ? new THREE.Mesh(new THREE.TubeGeometry(curve, 64, routed?wireDisplayRadius(electrical.wires[lane]):.010, 6, false),
      new THREE.MeshBasicMaterial({color:active?0xffe066:leg?leg.color:wireColor(electrical.wires[lane]),depthWrite:false}))
      : new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(32)),
      new THREE.LineBasicMaterial({color:active?0xffe066:0x788994,transparent:true,opacity:active?.9:.35,depthWrite:false}));
    flowGroup.add(line);
    if (active) {
      for (const t of [.3,.7]) {
        const direction=curve.getTangent(t).normalize().multiplyScalar(Math.sign(w.value));
        flowGroup.add(new THREE.ArrowHelper(direction,curve.getPoint(t),.07,0xffe066,.035,.025));
        arrows++;
      }
    }
    // Compact DOM cable meters are shared with live mode, rather than a
    // second set of preview-only sprites covering the scene.
  }
  for(const c of frame.contact_circuits||[]) {
    const circuit=machine.circuits.find(row=>row.name===c.name);if(!circuit)continue;
    const contactNames=new Set(circuit.switch.touch);
    const parents=new Set(machine.joints.filter(j=>j.kind==='fix'&&contactNames.has(j.b)).map(j=>j.a));
    for(const body of c.bodies) {
      if(!contactNames.has(body.name)&&!parents.has(body.name))continue;
      if(!body.dimensions_m)continue;
      const look=new THREE.MeshBasicMaterial({color:c.closed?0x5fe08f:0xffad66,wireframe:true,transparent:true,opacity:.65,depthWrite:false});
      const outline=new THREE.Mesh(new THREE.BoxGeometry(...body.dimensions_m),look);
      outline.position.set(...body.position_m);const q=body.orientation_wxyz||[1,0,0,0];outline.quaternion.set(q[1],q[2],q[3],q[0]);flowGroup.add(outline);
    }
  }
  for (const d of frame.devices || []) if (d.kind==='bulb' && d.at_m && d.emitted_w>1e-4) {
    const glow=new THREE.Mesh(new THREE.SphereGeometry(d.diameter_m*.51,12,8),
      new THREE.MeshBasicMaterial({color:0xffed9d,transparent:true,opacity:Math.min(.85,.3+.3*Math.sqrt(d.emitted_w)),depthWrite:false}));
    glow.position.set(...d.at_m); flowGroup.add(glow); bulbs++;
  }
  flowGroup.userData.drawn={lightSegments:light.legs,waterPoints:water.length/3,
    mechanisms:[...flowMechanismMeshes].filter(([,mesh])=>mesh.visible).map(([name,mesh])=>({name,
      position_m:mesh.position.toArray(),orientation_wxyz:[mesh.quaternion.w,mesh.quaternion.x,mesh.quaternion.y,mesh.quaternion.z]})),
    wetCells:surface?.xyz_mm?.length/3||0,wires:frame.wires.length,arrows,bulbs,
    riverArrows:riverArrows?.userData.samples.length||0,
    contacts:(frame.contacts||[]).map(c=>({name:c.name,closed:c.closed,current_a:c.current_a}))};
  const rows=[];
  if (frame.light.length) rows.push(`Light: ${frame.light.length} sampled rays`);
  const amps=(frame.wires||[]).filter(w=>w.unit==='A').map(w=>Math.abs(w.value));
  if (amps.length) rows.push(`Wire current: up to ${Math.max(...amps).toFixed(3)} A · arrows show conventional current`);
  const watts=(frame.wires||[]).filter(w=>w.unit==='W').map(w=>w.value);
  if (watts.length) rows.push(`Charging lead: ${Math.max(...watts).toFixed(1)} W`);
  const emitted=(frame.devices||[]).filter(d=>d.kind==='bulb').reduce((n,d)=>n+d.emitted_w,0);
  if ((frame.devices||[]).some(d=>d.kind==='bulb')) rows.push(`Bulb light: ${emitted.toFixed(2)} W`);
  if (frame.contacts?.length) rows.push(`Contact paths: ${frame.contacts.filter(c=>c.closed===true).length} touching`);
  for (const battery of frame.batteries||[]) rows.push(`${battery.name}: ${battery.charge_j.toFixed(1)} J stored`);
  if (frame.water) {
    const left=frame.water.sources.filter(s=>s.remaining_m3!=null).reduce((n,s)=>n+s.remaining_m3*1000,0);
    rows.push(`Water: ${frame.water.poured_l.toFixed(2)} L released${frame.water.sources.some(s=>s.remaining_m3!=null)?`, ${left.toFixed(2)} L left`:''}`);
    if (frame.water.sources.length && frame.water.sources.every(s=>!s.valve_open || (s.gravity_reservoir && !s.opening_fraction))) rows.push('Water valves closed');
  }
  const currents=(surface?.flow_samples||[]).map(s=>Math.hypot(...s.velocity_m_s)).filter(Number.isFinite);
  if (currents.length) rows.push(`Water current: up to ${Math.max(...currents).toFixed(2)} m/s · arrows show direction (0.05 m/s samples)`);
  $('flow-readings').textContent=rows.join(' · ');
}

function syncFlowPlayButton() {
  $('flow-play').textContent=flowPlaying?'Pause preview':'Play preview';
  $('flow-play').setAttribute('aria-pressed',String(flowPlaying));
}
function updateGearMotionFeedback(){
  const output=$('gear-motion-feedback');if(!output||ghost?.p.piece!=='gear')return;
  if(ghost.answered&&!ghost.busy&&!ghost.fits){
    output.textContent=ghost.problems.some(p=>/overlap|goes .*into/i.test(p))?'Clear the overlap — move apart':'Adjust placement to fit';return;
  }
  const linedUp=wheelGuideState.length>0&&wheelGuideState.every(q=>q.samePlane&&q.sameHeight);
  const spacing=linedUp&&!wheelGuideState.every(q=>q.teethReach)?'Teeth apart · ':'';
  const frame=flowGroup.visible?previewShown?.flow_frames?.[flowIndex]:null;
  if(flowPending||!frame){output.textContent=spacing||'Checking gear motion…';return;}
  const target=level.goal?.station?.done_when?.turned_deg?.joint;
  const joint=(frame.mechanism_joints||[]).find(j=>target?j.name===target:j.b===ghostName()+' wheel');
  output.textContent=spacing+(joint&&Number.isFinite(joint.turned_deg)?`Preview · ${target?'target wheel':'axle'} ${Math.abs(joint.turned_deg).toFixed(0)}°`:'Preview · gear motion');
}
function updateFlowPreview() {
  const frames=previewShown?.flow_frames || [];
  const visible=Boolean(frames.length) && !flowPending && !playing && !(world?.t>0) && previewOn && !inspectedCircuit && !document.body.matches('.on-sandbox,.on-levels');
  flowGroup.visible=visible; $('flow-preview').hidden=!visible;
  syncFlowMechanismVisibility();
  for(const [name,line] of drumLines)line.visible=!visible && (readouts.joints||[]).some(j=>j.name===name&&j.attached!==false);
  if (beams) beams.visible=visible?false:Boolean(readouts.light?.paths?.length);
  if (parcels) parcels.visible=!visible;
  if (water) water.visible=!visible;
  if (riverFlow) riverFlow.visible=!visible;
  const now=performance.now();
  if (!visible) {flowTick=now;return;}
  const end=frames[frames.length-1].t;
  if (flowPlaying && flowTick) flowTime+=Math.min(.1,(now-flowTick)/1000);
  flowTick=now;
  if (flowTime>end) flowTime=0;
  let index=0;
  while (index+1<frames.length && frames[index+1].t<=flowTime) index++;
  if (index!==flowIndex) {flowIndex=index;drawFlowFrame(frames[index]);syncFlowMechanismVisibility();}
  const currents=(frames[index].surface?.flow_samples||[]).map(s=>Math.hypot(...s.velocity_m_s)).filter(Number.isFinite);
  $('flow-summary').textContent=`Flow preview · ${describeTime(frames[index].t)}${currents.length?` · Current up to ${Math.max(...currents).toFixed(2)} m/s`:''}${previewShown.complete?'':' · incomplete'}`;
  $('flow-time').max=String(end); $('flow-time').value=String(flowTime);
  syncFlowPlayButton();
  const scale=distance*2*Math.tan(THREE.MathUtils.degToRad(camera.fov/2))/view.clientHeight;
  const rect=view.getBoundingClientRect(), occupied=[...view.querySelectorAll('.power-label, .terminal-label, #clock, #preview-legend')]
    .filter(e=>!e.hidden).map(e=>{const r=e.getBoundingClientRect();return {x:r.left-rect.left,y:r.top-rect.top,w:r.width,h:r.height};});
  for (const sprite of flowLabels) {
    sprite.scale.set(scale*76,scale*19,1);
    const p=sprite.position.clone().project(camera), x=(p.x+1)*view.clientWidth/2-38, y=(1-p.y)*view.clientHeight/2-9.5;
    sprite.visible=(wiringMode || $('flow-preview').open) && p.z<1 && x>=0 && y>=0 && x+76<=view.clientWidth && y+19<=view.clientHeight &&
      !occupied.some(r=>x<r.x+r.w && x+76>r.x && y<r.y+r.h && y+19>r.y);
    if (sprite.visible) occupied.push({x,y,w:76,h:19});
  }
}

$('flow-play').addEventListener('click',()=>{flowPlaying=!flowPlaying;flowTick=performance.now();syncFlowPlayButton();});
$('flow-time').addEventListener('input',()=>{flowPlaying=false;flowTime=Number($('flow-time').value);flowIndex=-1;syncFlowPlayButton();});
$('flow-preview').addEventListener('toggle',()=>{
  if ($('flow-preview').open) $('flow-time').scrollIntoView({block:'nearest',inline:'nearest'});
});

function clearPreview() {
  clearFlowFrame();clearFlowMechanisms(); flowIndex=-1; flowTime=0; flowTick=0;
  $('flow-preview').hidden=true;
  for (const c of [...previewGroup.children]) {
    previewGroup.remove(c);
    c.traverse(o => { if (o.geometry && !o.userData.shared) o.geometry.dispose(); });
  }
  previewShown = null;
  showPreviewLegend(null);
}

function markFlowPending() {
  clearTimeout(previewTimer);
  previewAsk++; flowPending=true; flowGroup.visible=false; $('flow-preview').hidden=true;
}

function schedulePreview(ms = 700) {
  scheduleLaserPreview();
  markFlowPending();
  if (!LEVEL_MODE || !level || !previewOn || document.body.matches('.on-sandbox,.on-levels')) return;
  previewTimer = setTimeout(() => askPreview().catch(() => {}), ms);
}

async function askPreview() {
  if (!LEVEL_MODE || !level || !previewOn || playing || document.body.matches('.on-sandbox,.on-levels')) return;
  // A ghost that does not fit, or is still being worked out: nothing to rehearse.
  if (ghost && (!ghost.answered || !ghost.fits)) { clearPreview(); return; }
  const mine = ++previewAsk, list = ghost ? ghostPlacements() : placements;
  try {
    const r = await api({op: 'level_preview', level: level.id, ...sandboxRequest(), placements: list});
    if (mine === previewAsk && !playing && !r.cancelled) drawPreview(r);
  } catch (e) {
    if (mine !== previewAsk) return;
    clearPreview();                     // a piece the goal needs is not placed yet, or it cannot be built
    if (e.status === 503 && previewOn) previewTimer = setTimeout(() => askPreview().catch(() => {}), 2500);
  }
}

function drawPreview(r) {
  clearPreview();
  previewShown = r;
  flowPending=false;
  // Electrical rehearsals start at their initial state. Future current and
  // bulb light appear only if the player explicitly plays/scrubs the preview.
  flowPlaying=ghost?.p.piece==='gear'||!(r.flow_frames||[]).some(f=>f.wires?.some(w=>w.unit==='A'));
  syncFlowPlayButton();
  const zone = level.goal && level.goal.station.done_when.in_zone;
  const inZone = p => Boolean(zone) && [0, 1, 2].every(i => Math.abs(p[i] - zone.at_m[i]) <= zone.size_m[i] / 2);
  const colourOf = new Map(), dotShape = PREVIEW_DOT;
  for (const path of r.paths) {
    const hits = r.hits.filter(h => h.body === path.name).sort((a, b) => a.t - b.t);
    const positions = [], colours = [];
    let current = new THREE.Color(FREE_COLOUR), k = 0;
    for (const [t, x, y, z] of path.points) {
      for (; k < hits.length && hits[k].t <= t; k++) {
        const other = hits[k].other;
        if (!colourOf.has(other)) colourOf.set(other, HIT_COLOURS[colourOf.size % HIT_COLOURS.length]);
        current = new THREE.Color(colourOf.get(other));
        const dot = new THREE.Mesh(dotShape, new THREE.MeshBasicMaterial({color: current, transparent: true, opacity: .9}));
        dot.userData.shared = true;
        dot.position.set(x, y, z);
        previewGroup.add(dot);
      }
      const c = inZone([x, y, z]) ? new THREE.Color(GOAL_COLOUR) : current;
      positions.push(x, y, z); colours.push(c.r, c.g, c.b);
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(colours, 3));
    previewGroup.add(new THREE.Line(geometry, new THREE.LineBasicMaterial({vertexColors: true, transparent: true,
      opacity: path.goal ? .95 : .6})));
    const dots = new THREE.Points(geometry, new THREE.PointsMaterial({vertexColors: true, size: path.goal ? .045 : .025,
      transparent: true, opacity: .75}));
    dots.userData.shared = true;                 // the line's geometry: disposed once, with it
    previewGroup.add(dots);
    const mesh = path.goal && meshes.get(path.name);
    if (mesh && path.points.length) {
      // Where the goal's thing comes to rest (or is at the end), see-through.
      const end = mesh.clone(true), last = path.points[path.points.length - 1];
      end.traverse(o => { if (o.isMesh) { o.material = previewEndLook; o.castShadow = false; o.userData.shared = true; } });
      end.userData.shared = true;
      end.position.set(last[1], last[2], last[3]);
      const q = path.turn_wxyz;
      if (q) end.quaternion.set(q[1], q[2], q[3], q[0]);
      previewGroup.add(end);
    }
  }
  showPreviewLegend(r, colourOf);
}

function showPreviewLegend(r, colourOf) {
  const box = $('preview-legend');
  box.replaceChildren();
  box.hidden = !r;
  if (!r) return;
  box.append(Object.assign(document.createElement('p'), {className: 'head',
    textContent: r.error ? 'Preview stopped: '+r.error : !r.complete ? 'Preview incomplete'
      : !level.goal ? 'Preview'
      : r.goal_at_s != null ? `Preview · goal at ${describeTime(r.goal_at_s)}`
      : r.manual_input_required ? `Preview · ${r.manual_input_label || 'drag the handle'} to start` : 'Preview · goal not reached'}));
  const chip = (colour, text) => {
    const s = Object.assign(document.createElement('span'), {className: 'chip', textContent: text});
    s.style.setProperty('--c', '#' + new THREE.Color(colour).getHexString());
    return s;
  };
  const row = Object.assign(document.createElement('p'), {className: 'chips'});
  row.append(chip(FREE_COLOUR, 'moving'));
  if (level.goal) row.append(chip(GOAL_COLOUR, 'in the goal'));
  // A few of what is hit, not every rail of a big build: the key is over the scene.
  const hit = [...colourOf];
  for (const [name, colour] of hit.slice(0, 4)) row.append(chip(colour, `after it hits ${name}`));
  if (hit.length > 4) row.append(Object.assign(document.createElement('span'), {className: 'more', textContent: `and ${hit.length - 4} more`}));
  const frames=r.flow_frames || [], keys=[];
  if (frames.some(f=>f.light.length)) keys.push(chip(0xff8cdc,'light preview'));
  if (frames.some(f=>f.water || f.surface)) keys.push(chip(0x62cfff,'water preview'));
  if (frames.some(f=>f.surface?.flow_samples?.some(s=>Math.hypot(...s.velocity_m_s)>.025))) keys.push(chip(0xb8f4ff,'river current'));
  if (frames.some(f=>f.wires.length)) keys.push(chip(0xffe066,'current preview'));
  row.prepend(...keys);
  const keyDetails = document.createElement('details');
  const previewHeading=box.querySelector('.head');
  const summary=Object.assign(document.createElement('summary'),{textContent:previewHeading.textContent+' ▾'});
  summary.setAttribute('aria-label','Preview key'); summary.title='Preview key';
  previewHeading.remove(); keyDetails.append(summary,row);
  box.append(keyDetails);
}

window.machinePreviewState = () => previewShown && {paths: previewShown.paths.map(p => ({name: p.name, goal: p.goal,
  points: p.points.length})), hits: previewShown.hits.length, goal_at_s: previewShown.goal_at_s,
  legend: $('preview-legend').textContent};
window.machineFlowPreviewState=()=>!flowPending && previewShown && {frames:previewShown.flow_frames?.length||0,time:flowTime,
  playing:flowPlaying,visible:flowGroup.visible,labels:flowLabels.filter(s=>s.visible).length,index:flowIndex,drawn:flowGroup.userData.drawn,sample:previewShown.flow_frames?.[flowIndex]};

$('path-toggle').addEventListener('click', () => {
  previewOn = !previewOn;
  $('path-toggle').setAttribute('aria-pressed', String(previewOn));
  if (previewOn) schedulePreview(0); else { clearTimeout(previewTimer); previewAsk++; clearPreview(); }
});

// Only a deliberate primary drag near the selected piece moves it. Keep
// its grab offset on a horizontal plane; clicks and small hand jitter never
// change placement. Empty-space drags, secondary buttons and two fingers
// turn the camera without leaving the piece editor.
const ghostBox = new THREE.Box3(), boxCorner = new THREE.Vector3(), slidePlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
function ghostScreenBox() {
  if (!ghost) return null;
  freshView();
  if(ghostGroup.children.length)ghostBox.setFromObject(ghostGroup);
  else {
    ghostBox.makeEmpty();
    for(const wire of terminalGhostWires.children)if(wire.userData.wireName===ghostName())ghostBox.expandByObject(wire);
  }
  if (ghostBox.isEmpty()) return null;
  const rect = renderer.domElement.getBoundingClientRect();
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (let i = 0; i < 8; i++) {
    boxCorner.set(i & 1 ? ghostBox.max.x : ghostBox.min.x, i & 2 ? ghostBox.max.y : ghostBox.min.y,
                  i & 4 ? ghostBox.max.z : ghostBox.min.z).project(camera);
    const sx = rect.left + (boxCorner.x + 1) / 2 * rect.width, sy = rect.top + (1 - boxCorner.y) / 2 * rect.height;
    x0 = Math.min(x0, sx); x1 = Math.max(x1, sx); y0 = Math.min(y0, sy); y1 = Math.max(y1, sy);
  }
  return {x0, x1, y0, y1, bottom: ghostBox.min.y};
}
function nearGhost(clientX, clientY, margin) {
  const b = ghostScreenBox();
  return Boolean(b) && clientX >= b.x0 - margin && clientX <= b.x1 + margin && clientY >= b.y0 - margin && clientY <= b.y1 + margin;
}
function slidePoint(clientX, clientY, y) {
  pointerRay(clientX, clientY);
  slidePlane.constant = -y;
  return raycaster.ray.intersectPlane(slidePlane, new THREE.Vector3());
}
const GRAB_MARGIN_PX = 40;
let rewiringBusy=false;
function wireCandidates(clientX,clientY,touch=false) {
  if(ghost || rewiringBusy || pullMode || attachMode || switchDragging || !level)return [];
  pointerRay(clientX,clientY);
  const rect=renderer.domElement.getBoundingClientRect();
  const obstruction=raycaster.intersectObjects([...meshes.values()].filter(m=>m.visible),true)[0];
  const result=[];
  for(const wire of wires) {
    if(!(wire.terminalWire||wire.powerCable)||!wire.line.visible)continue;
    const m=wire.name?.match(/^your (wire|power_cable) (\d+)$/),index=m?Number(m[2])-1:-1;
    if(index<0 || placements[index]?.piece!==m[1])continue; // prepared puzzle apparatus stays fixed
    if(wire.pickGeometry!==wire.line.geometry) {
      wire.pickGeometry=wire.line.geometry;
      wire.pickPoints=wire.line.geometry.parameters.path.getPoints(24);
    }
    const pts=wire.pickPoints.map(at=>{const p=at.clone().project(camera);return {at,x:rect.left+(p.x+1)*rect.width/2,y:rect.top+(1-p.y)*rect.height/2,z:p.z};});
    let best=null;
    for(let i=1;i<pts.length;i++) {
      const a=pts[i-1],b=pts[i];if(a.z < -1 || a.z>1 || b.z < -1 || b.z>1)continue;
      const dx=b.x-a.x,dy=b.y-a.y,t=THREE.MathUtils.clamp(((clientX-a.x)*dx+(clientY-a.y)*dy)/(dx*dx+dy*dy||1),0,1);
      const gap=Math.hypot(clientX-a.x-t*dx,clientY-a.y-t*dy);
      const at=a.at.clone().lerp(b.at,t),depth=at.clone().sub(raycaster.ray.origin).dot(raycaster.ray.direction);
      if(obstruction && depth>obstruction.distance+.025)continue;
      if(gap<=(touch?24:14) && (!best || gap<best.gap))best={gap};
    }
    if(best) {
      const first=pts[0],last=pts[pts.length-1];
      result.push({...best,index,name:wire.name,end:Math.hypot(clientX-first.x,clientY-first.y)<Math.hypot(clientX-last.x,clientY-last.y)?'a':'b'});
    }
  }
  return result.sort((a,b)=>a.gap-b.gap);
}
async function disconnectPlacedWire(hit) {
  if(ghost || rewiringBusy || !placements[hit.index])return;
  const sourceLevel=level,was=JSON.stringify(placements);
  rewiringBusy=true;
  try {
    // Stop a live circuit and restore its starting apparatus before editing.
    if(playing || world.t>0)await rebuildLevel(false);
    if(level!==sourceLevel || JSON.stringify(placements)!==was)return;
    remember();removePiece(hit.index);setWiringMode(false);renderTray();renderPlaced();
    await rebuildLevel(false);
  } catch(e){powerMessage(e.message);}
  finally{rewiringBusy=false;}
}
function clickExistingWire(x,y,touch) {
  const rows=wireCandidates(x,y,touch);if(!rows.length)return false;
  if(rows[1] && rows[1].gap-rows[0].gap<6) {
    const choice=$('socket-choices');choice.replaceChildren();
    for(const row of rows.slice(0,4))choice.append(button(`Remove ${row.name.replace(/^your /,'')}`,()=>{choice.hidden=true;disconnectPlacedWire(row);}));
    choice.append(button('Cancel',()=>{choice.hidden=true;}));choice.hidden=false;
    const rect=renderer.domElement.getBoundingClientRect();
    choice.style.left=`${Math.max(6,Math.min(rect.width-choice.offsetWidth-6,x-rect.left+12))}px`;
    choice.style.top=`${Math.max(6,Math.min(rect.height-choice.offsetHeight-6,y-rect.top+12))}px`;
  } else disconnectPlacedWire(rows[0]);
  return true;
}
function movableGhost() {
  if (!ghost || ['wire', 'power_cable'].includes(ghost.p.piece)) return false;
  if(ghost.p.piece==='ignition'&&ghost.p.attachment_version===2&&ghost.p.target)return false;
  const knobs = ghost && trayItem(ghost.p.piece)?.knobs;
  return Boolean(knobs?.x_m || knobs?.z_m);
}
// Which of the player's pieces (its index), if any, is the first thing under
// the pointer in the scene.
function placedOwnersAt(clientX, clientY) {
  if (!LEVEL_MODE || !level || (!placements.length && !sandboxObjects.length)) return [];
  pointerRay(clientX, clientY);
  const owner = name => {
    const m = name?.match(/^your (\S+) (\d+)(?: |$)/), i = m ? Number(m[2]) - 1 : -1;
    return i >= 0 && placements[i]?.piece === m[1] ? i : -1;
  };
  const nameOf = new Map([...meshes].map(([name, m]) => [m, name]));
  // A pulley device includes its drawn rope and its connected load. A load
  // shared by several devices is ambiguous; click the owning device instead.
  const loadOwners = new Map();
  for (const j of machine?.joints || []) {
    if (j.kind !== 'pulley' || owner(j.name) < 0) continue;
    const owners = loadOwners.get(j.b) || new Set(); owners.add(owner(j.name)); loadOwners.set(j.b, owners);
  }
  for (const r of ropes) if (r.line.visible && owner(r.name) >= 0) nameOf.set(r.line, r.name);
  // Keep thin ropes easy to select without a one-metre raycaster tolerance.
  raycaster.params.Line.threshold = Math.max(.002, distance * 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * 6 / view.clientHeight);
  const hits=raycaster.intersectObjects([...nameOf.keys()].filter(m=>m.visible),true).filter(h=>h.object.isMesh || (nameOf.has(h.object)&&h.object.isLine)),indices=[];
  for(const hit of hits){
    let o=hit.object;while(o&&!nameOf.has(o))o=o.parent;
    const name=o&&nameOf.get(o);let i=owner(name);
    if(i<0&&level.free){const baseIndex=sandboxObjects.findIndex(o=>o.parts.includes(name));if(baseIndex>=0)i=placements.length+baseIndex;}
    if(i<0){const attached=loadOwners.get(name);if(attached?.size===1)i=[...attached][0];}
    if(i>=0&&!indices.includes(i))indices.push(i);
    const material=hit.object.material;
    if(!material?.transparent || material.opacity>=.95)break;
  }
  return indices;
}
function placedAt(x,y){return placedOwnersAt(x,y)[0]??-1;}
function chooseScenePiece(indices,x,y){
  const choice=$('socket-choices');choice.replaceChildren();
  for(const index of indices){const name=placements[index]?`${pieceLabel(placements[index].piece)} ${index+1}`:sandboxObjects[index-placements.length]?.name;
    const b=button(`Adjust ${name}`,()=>{choice.hidden=true;pickUp(index);});b.dataset.pieceIndex=index;choice.append(b);}
  choice.append(button('Cancel',()=>{choice.hidden=true;}));choice.hidden=false;
  const rect=renderer.domElement.getBoundingClientRect();
  choice.style.left=`${Math.max(6,Math.min(rect.width-choice.offsetWidth-6,x-rect.left+12))}px`;
  choice.style.top=`${Math.max(6,Math.min(rect.height-choice.offsetHeight-6,y-rect.top+12))}px`;
}
// For tests: where a body is on the page (the middle of its mesh).
window.machineBodyScreen = name => {
  const mesh = meshes.get(name);
  if (!mesh) return null;
  freshView();
  const c = new THREE.Box3().setFromObject(mesh).getCenter(new THREE.Vector3()).project(camera), rect = renderer.domElement.getBoundingClientRect();
  return [rect.left + (c.x + 1) / 2 * rect.width, rect.top + (1 - c.y) / 2 * rect.height];
};
// For tests: the pieces as they stand.
window.machinePlacements = () => JSON.parse(JSON.stringify(placements));
// For tests: where each body is in the world now.
window.machineBodies = () => Object.fromEntries([...world.bodies].map(([name, b]) => [name, b.position_m]));
// For tests: where the piece being placed is on the screen, and the view.
window.machineGhostScreen = () => ghostScreenBox();
// Read-only camera/plane projection for input regression fixtures.
window.machineDragPoint=(x,y)=>slidePoint(x,y,ghostScreenBox()?.bottom||0)?.toArray();
window.machineCamera = () => ({azimuth, elevation, distance, guides: guides.visible, settled: target.distanceTo(goal) < 1e-3});
window.machineScenePick=(x,y)=>{const sockets=socketsAt(x,y,true),pieces=placedOwnersAt(x,y);return {piece:pieces[0]??-1,pieces,wire:wireCandidates(x,y,true).length>0,socket:sockets.some(s=>s.gap<=9),ambiguous:sockets.length>1&&sockets[1].gap-sockets[0].gap<8};};
window.machineWireScreen=(name,fraction=.5)=>{
  const wire=wires.find(w=>w.name===name);if(!wire?.line.visible || !wire.line.geometry.parameters?.path)return null;
  freshView();const at=wire.line.geometry.parameters.path.getPoint(fraction).project(camera),rect=renderer.domElement.getBoundingClientRect();
  return [rect.left+(at.x+1)*rect.width/2,rect.top+(1-at.y)*rect.height/2];
};
function alignedGridAxes() {
  return ghost && gridSnapEnabled && grid.visible ? ['x','z'].filter(axis=>Number.isFinite(ghost.gridLocks?.[axis])&&Math.abs(ghost.p[axis+'_m']-ghost.gridLocks[axis])<1e-6) : [];
}
function showGridSnap() {
  const output=$('grid-snap-status');if (!output) return;
  const axes=alignedGridAxes();
  const match=guideMatch?.direction||guideMatch?.matches?.[0],primary=ghost?.alignment?.primary;
  const label=ghost?.joined && objectSnapEnabled ? `Snapped to ${ghost.joined}` : match ? `${match.axis?.toUpperCase()||'Facing'} aligned · ${match.part.replace(/^your /,'')} ${match.label}` : '';
  output.textContent=[primary?.label, label || (!gridSnapEnabled?'Free placement':axes.length?`5 cm · ${axes.map(a=>a.toUpperCase()).join(' + ')} aligned`:'5 cm grid')].filter(Boolean).join(' · ');
  output.title=primary?.kinematic?'The lowest point of the cutting edge’s hinge circle. Contact and energy can stop the knife before it reaches this point.':'Green means geometric alignment within 8 mm in 3D. It does not check obstructions, reflected rays or available energy.';
  output.classList.toggle('aligned',axes.length>0||Boolean(match)||Boolean(ghost?.joined&&objectSnapEnabled));
}
window.machineWorkingGuide=()=>({primary:ghost?.alignment?.primary,match:guideMatch,objects_enabled:objectSnapEnabled,joined:ghost?.joined,
  wheels:wheelGuideState.map((row,i)=>({...row,ring_color:wheelPlaneGuides[i+1].material.color.getHex(),center_color:wheelCenterGuides[i].material.color.getHex()}))});
window.machinePlacementGrid=()=>({enabled:gridSnapEnabled,step_m:PLACEMENT_GRID.step_m,
  major_step_m:PLACEMENT_GRID.major_step_m,visible:grid.visible,fine_opacity:fineGrid.material.opacity,
  fine_vertices:fineGrid.geometry.attributes.position.count,major_vertices:majorGrid.geometry.attributes.position.count,
  aligned:alignedGridAxes(),marker:gridSnapMarker.visible});
renderer.domElement.addEventListener('pointerdown', e => {
  if (pointers.size > 1) {
    if (pulling) letGo();
    cameraGesture = true; draggingGhost = null; pressedAt = null; socketPress=null;$('socket-choices').hidden=true;
    view.classList.remove('grabbing'); return;
  }
  if (cameraGesture) return;
  $('socket-choices').hidden=true;
  socketPointer=[e.clientX,e.clientY];socketPress=null;
  if(pendingPieceReference&&ghost&&e.button===0&&!e.ctrlKey){pressedAt=[e.clientX,e.clientY];sceneDragged=false;draggingGhost=null;return;}
  const nearbySockets=socketsAt(e.clientX,e.clientY,e.pointerType==='touch');
  // The enlarged terminal hit area must not swallow a click on a small case.
  // Actual rings (9 px radius), or an explicitly started wire, still connect.
  const caseClick=!ghost&&!wiringMode&&!terminalStart&&!pickedPowerPort&&
    nearbySockets[0]?.gap>9&&placedAt(e.clientX,e.clientY)>=0;
  if(e.button===0&&!e.ctrlKey && nearbySockets.length&&!caseClick) {
    socketPress=e.pointerId;pressedAt=[e.clientX,e.clientY];sceneDragged=false;draggingGhost=null;return;
  }
  if (!ghost&&!pullMode&&!attachMode&&e.button===0&&!e.ctrlKey) {
    const device=switchHandleAt(e.clientX,e.clientY,e.pointerType==='touch');
    if (device&&startSwitchDrag(device,e)) return;
  }
  pressedAt = [e.clientX, e.clientY];
  sceneDragged = false;
  draggingGhost = null;
  if (!ghost || e.button !== 0 || e.ctrlKey) return;
  if (nearGhost(e.clientX, e.clientY, GRAB_MARGIN_PX)) {
    if(editorMode!=='move'){
      const key=ghost.card,rule=trayItem(ghost.p.piece).knobs[key];
      if(rule&&!rule.choices&&rule.min!=null)draggingGhost={id:e.pointerId,kind:'adjust',key,initial:Number(ghost.p[key]),screenX:e.clientX,active:false};
      return;
    }
    if(!movableGhost())return;
    const box = ghostScreenBox(), y = box ? box.bottom : 0, from = slidePoint(e.clientX, e.clientY, y);
    if (from) draggingGhost = {id: e.pointerId, y, from, x: ghost.p.x_m ?? 0, z: ghost.p.z_m ?? 0, active: false};
  }
});
renderer.domElement.addEventListener('pointermove', e => {
  socketPointer=[e.clientX,e.clientY];if(!e.buttons)sceneDragged=false;
  if (!ghost) {
    view.classList.remove('grab');
    // A piece of yours under the mouse can be clicked to pick it up.
    if (!e.buttons && e.pointerType === 'mouse') view.classList.toggle('pickable', !pullMode && !attachMode && (wireCandidates(e.clientX,e.clientY).length>0 || placedAt(e.clientX, e.clientY) >= 0));
    return;
  }
  if (draggingGhost && draggingGhost.id === e.pointerId && pointers.size === 1 && !cameraGesture) {
    if (!draggingGhost.active) {
      if (!pressedAt || Math.hypot(e.clientX - pressedAt[0], e.clientY - pressedAt[1]) < 6) return;
      const drag = draggingGhost;
      looking=false;view.classList.remove('looking');draggingGhost = drag; drag.active = true;
      $('mode-view').setAttribute('aria-pressed','false');$('mode-move').setAttribute('aria-pressed','true');
      $('piece-editor').querySelector('[aria-label="Move selected piece"]')?.setAttribute('aria-pressed',String(editorMode==='move'));
      $('piece-editor').querySelector('[aria-label="Turn selected piece"]')?.setAttribute('aria-pressed',String(editorMode==='turn'));
      view.classList.add('grabbing');
    }
    if(draggingGhost.kind==='adjust'){
      editByDrag(draggingGhost.key,draggingGhost.initial,e.clientX-draggingGhost.screenX);return;
    }
    const at = slidePoint(e.clientX, e.clientY, draggingGhost.y);
    if (!at) return;
    const knobs=trayItem(ghost.p.piece).knobs;
    const snapped=snapGroundPoint({x:knobs.x_m?draggingGhost.x+at.x-draggingGhost.from.x:undefined,
      z:knobs.z_m?draggingGhost.z+at.z-draggingGhost.from.z:undefined},{enabled:gridSnapEnabled&&grid.visible&&!e.altKey,previous:ghost.gridLocks||{}});
    const moved = [setKnob(ghost.p,'x_m',snapped.point.x),setKnob(ghost.p,'z_m',snapped.point.z)].some(Boolean);
    ghost.gridLocks=snapped.locks; showGridSnap();
    if (moved) { ghost.snapNext = objectSnapEnabled&&!e.altKey; if(e.altKey)ghost.objectLock=null;followGhost(); showGhostKnobs(); askGhost(); }
  } else if (!e.buttons) view.classList.toggle('grab', movableGhost() && nearGhost(e.clientX, e.clientY, GRAB_MARGIN_PX));
});
renderer.domElement.addEventListener('pointerup', e => {
  if(switchDragging?.pointerId===e.pointerId){endSwitchPointer(e);pressedAt=null;if(!pointers.size)cameraGesture=false;return;}
  const click = e.button === 0 && !cameraGesture && !sceneDragged && pressedAt && Math.hypot(e.clientX - pressedAt[0], e.clientY - pressedAt[1]) < 6;
  if(click && socketPress===e.pointerId && finishSocketClick(e.clientX,e.clientY,e.pointerType==='touch')) {
    socketPress=null;draggingGhost=null;pressedAt=null;return;
  }
  socketPress=null;
  if(click && !ghost && !e.ctrlKey && clickExistingWire(e.clientX,e.clientY,e.pointerType==='touch')) {
    draggingGhost=null;pressedAt=null;return;
  }
  if(ghost&&click&&pendingPieceReference){
    const ref=pendingPieceReference;pointerRay(e.clientX,e.clientY);
    const nameOf=new Map([...meshes].map(([name,m])=>[m,name]));
    const hit=raycaster.intersectObjects([...nameOf.keys()].filter(m=>m.visible),true).find(h=>h.object.isMesh);
    let object=hit?.object;while(object&&!nameOf.has(object))object=object.parent;
    const name=object&&nameOf.get(object);
    const endpoint=ref.rule.hinge?(machine?.joints||[]).find(j=>j.kind==='hinge'&&(j.a===name||j.b===name)&&ref.allowed.includes(j.name))?.name:
      ref.key==='battery'?(machine?.batteries||[]).find(b=>b.in===name&&ref.allowed.includes(b.name))?.name:name;
    if(endpoint&&ref.allowed.includes(endpoint)){ref.p[ref.key]=endpoint;pendingPieceReference=null;closeValueChoices();ref.changed();}
    else $('adjustment-feedback').textContent='Choose a compatible object in the scene. Default connections and exact endpoints are in Changes → Settings.';
  } else if (ghost && click) setLooking(true);
  else if (!ghost && click && !pullMode && !attachMode) {
    const choices=placedOwnersAt(e.clientX,e.clientY);
    if(choices.length>1)chooseScenePiece(choices,e.clientX,e.clientY);
    else if(choices.length)pickUp(choices[0]);
  }
  draggingGhost = null; pressedAt = null;
  if (!pointers.size) cameraGesture = false;
  view.classList.remove('grabbing');
});
const cancelPlacementGesture = () => {
  draggingGhost = null; pressedAt = null;socketPress=null;
  if (!pointers.size) cameraGesture = false;
  view.classList.remove('grabbing');
};
renderer.domElement.addEventListener('pointercancel', cancelPlacementGesture);
renderer.domElement.addEventListener('pointerleave',()=>{socketPointer=null;view.classList.remove('socket-hover');});
renderer.domElement.addEventListener('lostpointercapture', e => {
  pointers.delete(e.pointerId); pinch = 0; cancelPlacementGesture();
});

// Guides through the piece being placed, as 3D editors draw them: a line
// along x (red) and along z (blue) through it to the horizon at the height
// it stands, the same on the ground beneath when it stands above it, and a
// vertical line (green) down to a mark on the ground under it.
const guides = new THREE.Group();
guides.visible = false;
scene.add(guides);
// Bars, not lines: a WebGL line is one pixel whatever the distance, too thin
// to see; a bar is kept two or three pixels thick by the camera's distance.
const barShape = new THREE.BoxGeometry(1, 1, 1);
function guideBar(colour, opacity) {
  const bar = new THREE.Mesh(barShape, new THREE.MeshBasicMaterial({color: colour, transparent: true, opacity, depthWrite: false}));
  bar.frustumCulled = false;
  guides.add(bar);
  return bar;
}
const guideX = guideBar(0xff5c5c, .85), guideZ = guideBar(0x4d9dff, .85), guideY = guideBar(0x6fe08a, .9);
const guideGroundX = guideBar(0xff5c5c, .4), guideGroundZ = guideBar(0x4d9dff, .4);
const guideAim=guideBar(0xffcf59,.9);
const guideAimHead=new THREE.Mesh(new THREE.ConeGeometry(1,1,12),new THREE.MeshBasicMaterial({color:0xffcf59}));
guides.add(guideAimHead);
const guideOrigin=new THREE.Mesh(new THREE.SphereGeometry(.012,12,8),new THREE.MeshBasicMaterial({color:0xffcf59}));
guides.add(guideOrigin);
const guideMatches=Array.from({length:8},()=>{
  const dot=new THREE.Mesh(new THREE.SphereGeometry(.012,12,8),new THREE.MeshBasicMaterial({color:0x50ffb0,depthWrite:false}));
  guides.add(dot);return dot;
});
let guideMatch=null;
let wheelGuideState=[];
const wheelPlaneShape=new THREE.RingGeometry(1,1.025,64);
const wheelPlaneGuides=Array.from({length:5},()=>{
  const ring=new THREE.Mesh(wheelPlaneShape,new THREE.MeshBasicMaterial({color:0xffcf59,side:THREE.DoubleSide,transparent:true,opacity:.85,depthTest:false,depthWrite:false}));
  guides.add(ring);return ring;
});
const wheelCenterGuides=Array.from({length:4},()=>guideBar(0xffcf59,.85));
function updateWheelGuides(primary){
  wheelGuideState=wheelAlignment(primary,ghost?.alignment?.targets||[]);
  const planeAligned=wheelGuideState.length>0&&wheelGuideState.every(q=>q.samePlane);
  const level=wheelGuideState.length>0&&wheelGuideState.every(q=>q.sameHeight);
  for(const [i,ring] of wheelPlaneGuides.entries()){
    const row=i===0?primary:wheelGuideState[i-1];
    ring.visible=Boolean(row?.wheel&&wheelGuideState.length);if(!ring.visible)continue;
    ring.position.set(...row.at);ring.scale.setScalar(row.wheel.radius_m+.015);
    ring.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1),new THREE.Vector3(...row.dir).normalize());
    ring.material.color.setHex((i===0?planeAligned:row.samePlane)?0x50ffb0:0xffcf59);
  }
  wheelCenterGuides.forEach((bar,i)=>{
    const row=wheelGuideState[i];bar.visible=Boolean(row);if(!row)return;
    const a=new THREE.Vector3(...primary.at),delta=new THREE.Vector3(...row.at).sub(a),length=delta.length();
    bar.position.copy(a).addScaledVector(delta,.5);bar.scale.set(.004,length,.004);
    if(length>1e-9)bar.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),delta.normalize());
    bar.material.color.setHex(row.samePlane&&row.sameHeight?0x50ffb0:0xffcf59);
  });
  const output=$('gear-plane-feedback');
  if(output){
    const error=key=>Math.max(...wheelGuideState.map(q=>Math.abs(q[key])))*100;
    const text=!wheelGuideState.length?'Bring it near another wheel':
      !wheelGuideState.every(q=>q.parallel)?'Wheel axes point in different directions':
      `${planeAligned?'Plane aligned':`Plane off ${error('plane_m').toFixed(1)} cm`} · ${level?'Height aligned':`Height off ${error('height_m').toFixed(1)} cm`}`;
    if(output.textContent!==text)output.textContent=text;
    output.classList.toggle('aligned',planeAligned&&level);
    output.title=wheelGuideState.map(q=>`${q.part}: ${q.samePlane?'same plane':'plane offset '+(Math.abs(q.plane_m)*100).toFixed(1)+' cm'}; ${q.sameHeight?'same centre height':'height offset '+(Math.abs(q.height_m)*100).toFixed(1)+' cm'}; ${q.teethReach?'teeth within reach':'teeth separated or roots overlap'}`).join('\n')+'\nGreen shows geometry, not a guaranteed turn. The engine preview checks contact.';
  }
  return {planeAligned,level};
}
const gridSnapMarker=new THREE.Group();
for (const axis of ['x','z']) {
  const points=axis==='x'?[new THREE.Vector3(0,0,-.08),new THREE.Vector3(0,0,.08)]
    :[new THREE.Vector3(-.08,0,0),new THREE.Vector3(.08,0,0)];
  const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(points),new THREE.LineBasicMaterial({color:0xffcf59}));
  line.userData.axis=axis;gridSnapMarker.add(line);
}
gridSnapMarker.visible=false;scene.add(gridSnapMarker);
const guideFoot = new THREE.Mesh(new THREE.RingGeometry(.035, .05, 28),
  new THREE.MeshBasicMaterial({color: 0x6fe08f, transparent: true, opacity: .9, side: THREE.DoubleSide}));
guideFoot.rotation.x = -Math.PI / 2;
guides.add(guideFoot);
function updateGuides() {
  const axes=alignedGridAxes();
  gridSnapMarker.visible=Boolean(ghost&&axes.length&&grid.visible);
  if (gridSnapMarker.visible) {
    gridSnapMarker.position.set(ghost.p.x_m??0,.005,ghost.p.z_m??0);
    for (const line of gridSnapMarker.children) line.visible=axes.includes(line.userData.axis);
  }
  guides.visible = Boolean(ghost && ghostGroup.children.length);
  if (!guides.visible) {guideMatch=null;wheelGuideState=[];return;}
  ghostBox.setFromObject(ghostGroup);
  if (ghostBox.isEmpty()) { guides.visible = false; return; }
  const working=ghost.alignment?.primary;
  const at=working?.at?.map((v,i)=>v+ghostGroup.position.getComponent(i));
  const cx = at?.[0]??(ghostBox.min.x + ghostBox.max.x) / 2, cz = at?.[2]??(ghostBox.min.z + ghostBox.max.z) / 2;
  const base = Math.max(.004, at?.[1]??ghostBox.min.y), top = Math.max(base+.4,ghostBox.max.y + .4), far = 50;
  guideMatch=workingAlignment(working?{...working,at}:null,ghost.alignment?.targets||[]);
  const wheel=updateWheelGuides(working?{...working,at}:null);
  for(const [bar,axis,color] of [[guideX,'x',0xff5c5c],[guideY,'y',0x6fe08a],[guideZ,'z',0x4d9dff]])
    bar.material.color.setHex(guideMatch.axes.includes(axis)||(wheel.level&&axis==='y')||(wheel.planeAligned&&Math.abs(working?.dir?.[['x','y','z'].indexOf(axis)]||0)>.999)?0x50ffb0:color);
  const t = Math.max(.004, .0025 * camera.position.distanceTo(new THREE.Vector3(cx, base, cz)));
  guideX.position.set(cx, base, cz); guideX.scale.set(far, t, t);
  guideZ.position.set(cx, base, cz); guideZ.scale.set(t, t, far);
  guideY.position.set(cx, top / 2, cz); guideY.scale.set(t, top, t);
  const raised = base > .03;
  guideGroundX.visible = guideGroundZ.visible = raised;
  guideGroundX.position.set(cx, .004, cz); guideGroundX.scale.set(far, .002, t);
  guideGroundZ.position.set(cx, .004, cz); guideGroundZ.scale.set(t, .002, far);
  guideFoot.position.set(cx, .005, cz);
  guideOrigin.position.set(cx,base,cz);
  const direction=working?.dir&&new THREE.Vector3(...working.dir);
  guideAim.visible=guideAimHead.visible=Boolean(direction?.lengthSq()>1e-9);
  if(guideAim.visible){
    direction.normalize();const length=Math.min(1.2,guideMatch.direction?.along??.6),origin=new THREE.Vector3(cx,base,cz);
    const rotation=new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,1,0),direction);
    guideAim.position.copy(origin).addScaledVector(direction,length/2);guideAim.quaternion.copy(rotation);guideAim.scale.set(t,length,t);
    guideAimHead.position.copy(origin).addScaledVector(direction,length);guideAimHead.quaternion.copy(rotation);guideAimHead.scale.set(t*3,t*8,t*3);
    guideAim.material.color.setHex(guideMatch.direction?0x50ffb0:0xffcf59);guideAimHead.material.color.copy(guideAim.material.color);
  }
  const unique=[...new Map(guideMatch.matches.map(q=>[q.part+'|'+q.label,q])).values()];
  if(guideMatch.direction)unique.unshift(guideMatch.direction);
  guideMatches.forEach((dot,i)=>{dot.visible=Boolean(unique[i]);if(unique[i])dot.position.set(...unique[i].at);});
  showGridSnap();
}
// ---- testing a part: a pull ----------------------------------------------------
// With Pull on, pressing a loose part and dragging pulls it that way -- the
// engine's own force at that point of it, no hand in the world -- harder the
// further the pointer goes from the point (PULL_N_PER_M), up to PULL_MAX_N.
// A line is the string. Letting go lets go. The work the pull does counts in
// what the run took (the win card says so). It pulls while the world runs, and
// starts it if it is not running.
const PULL_N_PER_M = 400, PULL_MAX_N = 200;
let pullMode = false, pulling = null;
const pullLine = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
                                new THREE.LineBasicMaterial({color: 0xffd34d}));
pullLine.visible = false;
pullLine.frustumCulled = false;
scene.add(pullLine);
$('pull-tool').addEventListener('click', () => {
  pullMode = !pullMode;
  $('pull-tool').setAttribute('aria-pressed', String(pullMode));
  view.classList.toggle('pulling-mode', pullMode);
});
// The loose part under the pointer, and the point of it there.
function pullTarget(clientX, clientY) {
  pointerRay(clientX, clientY);
  const nameOf = new Map([...meshes].map(([name, m]) => [m, name]));
  const hit = raycaster.intersectObjects([...nameOf.keys()].filter(m => m.visible), true).find(h => h.object.isMesh);
  let o = hit && hit.object;
  while (o && !nameOf.has(o)) o = o.parent;
  const name = o && nameOf.get(o), body = name && world.bodies.get(name);
  if (!body || body.anchored) return null;
  return {name, mesh: o, local: o.worldToLocal(hit.point.clone()), plane: new THREE.Plane().setFromNormalAndCoplanarPoint(
    camera.getWorldDirection(new THREE.Vector3()).negate(), hit.point)};
}
function pullForce(clientX, clientY) {
  pointerRay(clientX, clientY);
  const to = raycaster.ray.intersectPlane(pulling.plane, new THREE.Vector3());
  const at = pulling.mesh.localToWorld(pulling.local.clone());
  if (!to) return {at, to: at, force: new THREE.Vector3()};
  const force = to.clone().sub(at).multiplyScalar(PULL_N_PER_M);
  if (force.length() > PULL_MAX_N) force.setLength(PULL_MAX_N);
  return {at, to, force};
}
let pullSent = 0;
function sendPull(force, at, now = false) {
  if (!pulling || !session) return;
  const stamp = performance.now();
  if (!now && stamp - pullSent < 100) return;
  pullSent = stamp;
  api({op: 'pull', session, body: pulling.name, at: at.toArray().map(v => +v.toFixed(4)),
       force: force.toArray().map(v => +v.toFixed(2))}).catch(() => {});
}
renderer.domElement.addEventListener('pointerdown', e => {
  if (!pullMode || ghost || pointers.size > 1 || cameraGesture || e.button !== 0 || e.ctrlKey) return;
  const target = pullTarget(e.clientX, e.clientY);
  if (!target) return;
  pulling = {...target, pointerId: e.pointerId, clientX: e.clientX, clientY: e.clientY};
  pullLine.visible = true;
  if (!playing) setPlaying(true).catch(() => {});
});
renderer.domElement.addEventListener('pointermove', e => {
  if (!pulling || pulling.pointerId !== e.pointerId) return;
  pulling.clientX = e.clientX; pulling.clientY = e.clientY;
  const {at, force} = pullForce(e.clientX, e.clientY);
  sendPull(force, at);
});
const letGo = () => {
  if (!pulling) return;
  const {at} = pullForce(pulling.clientX, pulling.clientY);
  sendPull(new THREE.Vector3(), at, true);
  pulling = null;
  pullLine.visible = false;
  $('clock').title = '';
};
renderer.domElement.addEventListener('pointerup', letGo);
renderer.domElement.addEventListener('pointercancel', letGo);
renderer.domElement.addEventListener('lostpointercapture', letGo);
// Each frame: the string from the point of the part to the pointer, and the
// force sent again as the part moves under it.
function drawPull() {
  if (!pulling) return;
  const {at, to, force} = pullForce(pulling.clientX, pulling.clientY);
  pullLine.geometry.setFromPoints([at, to]);
  pullLine.material.color.setHSL(0.14 - 0.14 * force.length() / PULL_MAX_N, 1, 0.55);
  sendPull(force, at);
  $('clock').title = `Pulling ${pulling.name} with ${Math.round(force.length())} N`;
}
window.machinePullState = () => pulling && {body: pulling.name, force_n: Math.round(pullForce(pulling.clientX, pulling.clientY).force.length())};

// A manual switch is operated by force on its real rocker. The label offers
// a full touch target; its pointer offset prevents the label from moving the
// grip before the player deliberately drags. It does not set an angle/state.
const SWITCH_MAX_N=20;
const switchPullLine=new THREE.Line(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:0xffd34d}));
switchPullLine.visible=false;switchPullLine.frustumCulled=false;scene.add(switchPullLine);
function switchHandleAt(x,y,touch=false) {
  const devices=(machine?.electrical?.devices||[]).filter(d=>d.handle&&meshes.get(d.handle.part)?.visible);
  pointerRay(x,y);
  const names=new Map([...meshes].map(([name,mesh])=>[mesh,name]));
  const hit=raycaster.intersectObjects([...names.keys()].filter(m=>m.visible),true)[0];
  let object=hit?.object;while(object&&!names.has(object))object=object.parent;
  const direct=devices.find(d=>d.handle.part===names.get(object));
  if(direct)return direct;
  if(!touch)return null;
  return devices.find(d=>{
    const at=terminalAt({name:d.name,part:d.handle.part},'',d.handle.at_m);
    if(!at)return false;
    const [sx,sy]=window.machineScreenPoint(at);
    return Math.hypot(sx-x,sy-y)<=22&&(!hit||names.get(object)===d.part);
  })||null;
}
function startSwitchDrag(device,e) {
  if(switchDragging||ghost||pullMode||attachMode||!session||cameraGesture||pointers.size>1||e.button!==0||e.ctrlKey)return false;
  const mesh=meshes.get(device.handle.part),grip=terminalAt({name:device.name,part:device.handle.part},'',device.handle.at_m);
  if(!mesh||!grip)return false;
  pointerRay(e.clientX,e.clientY);
  const initial=new THREE.Vector3(...grip),plane=new THREE.Plane().setFromNormalAndCoplanarPoint(camera.getWorldDirection(new THREE.Vector3()).negate(),initial);
  const from=raycaster.ray.intersectPlane(plane,new THREE.Vector3());
  if(!from)return false;
  switchDragging={device,mesh,local:mesh.worldToLocal(initial.clone()),initial,from,plane,
    pointerId:e.pointerId,start:[e.clientX,e.clientY],clientX:e.clientX,clientY:e.clientY,
    session,active:false,ready:false,sent:0};
  switchTouchGesture=e.pointerType==='touch';
  pressedAt=null;sceneDragged=true;draggingGhost=null;
  return true;
}
function switchForce(drag) {
  pointerRay(drag.clientX,drag.clientY);
  const pointer=raycaster.ray.intersectPlane(drag.plane,new THREE.Vector3()),at=drag.mesh.localToWorld(drag.local.clone());
  const to=pointer?drag.initial.clone().add(pointer.sub(drag.from)):at.clone();
  const force=to.clone().sub(at).multiplyScalar(PULL_N_PER_M);
  if(force.length()>SWITCH_MAX_N)force.setLength(SWITCH_MAX_N);
  return {at,to,force};
}
function switchInputError(error,drag) {
  if(session!==drag.session)return;
  powerMessage(`Switch handle: ${error.message}`);
  if(switchDragging===drag)stopSwitchDrag();
}
function sendSwitchPull(drag,force,at,release=false) {
  const stamp=performance.now();
  if(!release&&stamp-drag.sent<100)return switchPullQueue;
  drag.sent=stamp;
  const payload={op:'mechanical_switch_pull',session:drag.session,name:drag.device.name,body:drag.device.handle.part,
    at:at.toArray(),force:force.toArray()};
  switchPullQueue=switchPullQueue.then(()=>{
    if(!release&&(switchDragging!==drag||!drag.ready))return;
    return api(payload);
  }).catch(error=>switchInputError(error,drag));
  return switchPullQueue;
}
function moveSwitchDrag(e) {
  const drag=switchDragging;if(!drag||drag.pointerId!==e.pointerId)return;
  drag.clientX=e.clientX;drag.clientY=e.clientY;
  if(!drag.active) {
    if(Math.hypot(e.clientX-drag.start[0],e.clientY-drag.start[1])<6)return;
    drag.active=true;clearTimeout(previewTimer);previewAsk++;clearPreview();
    const ready=Promise.resolve(playPending).then(()=>{
      if(switchDragging!==drag||session!==drag.session)return;
      return setPlaying(true);
    });
    ready.then(()=>{
      if(switchDragging!==drag||session!==drag.session)return;
      drag.ready=true;const {at,force}=switchForce(drag);sendSwitchPull(drag,force,at);
    }).catch(error=>switchInputError(error,drag));
  }
  if(drag.ready){const {at,force}=switchForce(drag);sendSwitchPull(drag,force,at);}
}
function stopSwitchDrag() {
  const drag=switchDragging;if(!drag)return switchPullQueue;
  switchDragging=null;switchPullLine.visible=false;
  if(drag.active){const {at}=switchForce(drag);sendSwitchPull(drag,new THREE.Vector3(),at,true);}
  $('clock').title='';return switchPullQueue;
}
function endSwitchPointer(e) {if(switchDragging?.pointerId===e.pointerId)stopSwitchDrag();}
function drawSwitchPull() {
  const drag=switchDragging;if(!drag?.active||!drag.ready){switchPullLine.visible=false;return;}
  const {at,to,force}=switchForce(drag);
  switchPullLine.visible=true;switchPullLine.geometry.setFromPoints([at,to]);sendSwitchPull(drag,force,at);
  $('clock').title=`Operating ${drag.device.name} with ${force.length().toFixed(1)} N`;
}
renderer.domElement.addEventListener('pointermove',moveSwitchDrag);
for(const type of ['pointerup','pointercancel','lostpointercapture'])document.addEventListener(type,endSwitchPointer,true);
document.addEventListener('pointerdown',e=>{
  if(!switchTouchGesture||pointers.has(e.pointerId)||e.pointerType!=='touch')return;
  stopSwitchDrag();cameraGesture=true;sceneDragged=true;pressedAt=null;draggingGhost=null;
  pointers.set(e.pointerId,[e.clientX,e.clientY]);renderer.domElement.setPointerCapture(e.pointerId);
  if(pointers.size===2){const [a,b]=[...pointers.values()];pinch=Math.hypot(a[0]-b[0],a[1]-b[1]);}
  e.preventDefault();e.stopPropagation();
},true);
for(const type of ['pointerup','pointercancel','lostpointercapture'])document.addEventListener(type,e=>{
  if(!switchTouchGesture)return;
  pointers.delete(e.pointerId);pinch=0;
  if(!pointers.size){switchTouchGesture=false;cameraGesture=false;}
},true);
$('pull-tool').addEventListener('click',()=>stopSwitchDrag());
$('attach-tool').addEventListener('click',()=>stopSwitchDrag());
addEventListener('blur',()=>stopSwitchDrag());
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopSwitchDrag();});
window.machineSwitchState=()=>({drag:switchDragging&&{name:switchDragging.device.name,active:switchDragging.active,
  force_n:switchDragging.ready?switchForce(switchDragging).force.length():0},
  pointers:[...pointers.keys()],cameraGesture,switchTouchGesture,
  handles:(machine?.electrical?.devices||[]).filter(d=>d.handle).map(d=>({name:d.name,part:d.handle.part,
    at_m:terminalAt({name:d.name,part:d.handle.part},'',d.handle.at_m),
    closed:readouts.electrical?.devices?.find(row=>row.name===d.name)?.closed}))});

// ---- joining two parts: 🔗 Attach ------------------------------------------------
// With Attach on, press one part, then another: a card asks how to join them
// -- glue where they were pressed, a pin there (its axle along x, along z or
// upright), or a string from the first point to the second, as long as
// it is then. The join is one of the pieces: it is kept, taken back, removed.
let attachMode = false, attaching = [];
const attachMark = new THREE.Group();
scene.add(attachMark);
function partAt(clientX, clientY) {
  pointerRay(clientX, clientY);
  const nameOf = new Map([...meshes].map(([name, m]) => [m, name]));
  const hit = raycaster.intersectObjects([...nameOf.keys()].filter(m => m.visible), true).find(h => h.object.isMesh);
  let o = hit && hit.object;
  while (o && !nameOf.has(o)) o = o.parent;
  return o ? {name: nameOf.get(o), at: hit.point.toArray().map(v => +v.toFixed(4))} : null;
}
function cancelAttach() {
  attaching = [];
  for (const c of [...attachMark.children]) attachMark.remove(c);
  $('attach-card').hidden = true; $('attach-card').replaceChildren();
}
function setAttach(on) {
  attachMode = Boolean(on);
  if (attachMode && pullMode) $('pull-tool').click();
  $('attach-tool').setAttribute('aria-pressed', String(attachMode));
  view.classList.toggle('attaching', attachMode);
  cancelAttach();
}
$('attach-tool').addEventListener('click', () => { if (ghost) cancelGhost(); setAttach(!attachMode); });
$('pull-tool').addEventListener('click', () => { if (pullMode && attachMode) setAttach(false); });
function attachChoice() {
  const [one, two] = attaching, card = $('attach-card');
  const body = name => world.bodies.get(name);
  card.replaceChildren(Object.assign(document.createElement('p'), {textContent: `Join ${one.name} and ${two.name}:`}));
  if (body(one.name) && body(two.name) && body(one.name).anchored && body(two.name).anchored) {
    card.append(Object.assign(document.createElement('p'), {className: 'hint', textContent: 'Both are fixed, so a join would move nothing. Join something that moves.'}),
                button('Cancel', () => setAttach(false)));
    card.hidden = false;
    return;
  }
  const mid = one.at.map((v, i) => +((v + two.at[i]) / 2).toFixed(4));
  const join = (kind, extra = {}) => {
    remember();
    placements.push({piece: 'link', kind, a: one.name, b: two.name, at_m: ['string', 'spring'].includes(kind) ? one.at : mid,
                     ...(['string', 'spring'].includes(kind) ? {at_b_m: two.at} : {}), ...extra});
    setAttach(false); renderTray(); renderPlaced(); scheduleRebuild(0);
  };
  const row = Object.assign(document.createElement('div'), {className: 'actions'});
  row.append(button('Glue', () => join('glue'), {ariaLabel: 'Glue them together'}),
             button('String', () => join('string'), {ariaLabel: 'Tie them with a string'}),
             button('Pin, axle along x', () => join('pin', {axis: 'along x'}), {ariaLabel: 'Pin them, the axle along x'}),
             button('Pin, axle along z', () => join('pin', {axis: 'along z'}), {ariaLabel: 'Pin them, the axle along z'}),
             button('Pin, axle upright', () => join('pin', {axis: 'upright'}), {ariaLabel: 'Pin them, the axle upright'}),
             button('Cancel', () => setAttach(false)));
  card.append(row);
  const spring = {rest_m: Math.max(.01, Math.min(3, Math.hypot(...one.at.map((v, i) => v - two.at[i])))), stiffness_n_m: 100, damping_n_s_m: 1};
  const springOptions = Object.assign(document.createElement('details'), {});
  springOptions.append(Object.assign(document.createElement('summary'), {textContent: 'Connect with a spring'}));
  for (const key of Object.keys(spring)) {
    const rule = trayItem('link').knobs[key];
    springOptions.append(knobControl(spring, key, rule, 'this spring', () => {}).label);
  }
  springOptions.append(button('Add spring between picked points', () => join('spring', spring)));
  card.append(springOptions);
  card.hidden = false;
}
renderer.domElement.addEventListener('pointerup', e => {
  if (!attachMode || ghost || e.button !== 0 || cameraGesture || sceneDragged || !pressedAt || Math.hypot(e.clientX - pressedAt[0], e.clientY - pressedAt[1]) >= 6) return;
  const part = partAt(e.clientX, e.clientY);
  if (!part || attaching.length >= 2 || (attaching[0] && attaching[0].name === part.name)) return;
  attaching.push(part);
  const dot = new THREE.Mesh(PORT_DOT, new THREE.MeshBasicMaterial({color: 0xffd34d, depthTest: false}));
  dot.position.set(...part.at);
  attachMark.add(dot);
  $('clock').title = attaching.length === 1 ? `${part.name}: now press the part to join it to` : '';
  if (attaching.length === 2) attachChoice();
}, true);
window.machineAttachState = () => ({on: attachMode, picked: attaching.map(p => p.name), card: !$('attach-card').hidden});

// Turning by hand: Shift and the wheel turns it, Alt and the wheel tips it.
renderer.domElement.addEventListener('wheel', e => {
  if (!ghost || e.ctrlKey || !(e.shiftKey || e.altKey)) return;
  e.preventDefault();
  turnGhost(e.altKey ? 'pitch_deg' : 'yaw_deg', Math.sign(e.deltaY || e.deltaX) * -15);
}, {passive: false});
document.addEventListener('keydown', e => {
  if (document.querySelector('dialog[open]') || !ghost || e.ctrlKey || e.metaKey || e.target.closest('input, textarea, select')) return;
  const key = e.key.toLowerCase(), step = e.shiftKey ? 1 : 15;
  const nudge = {arrowleft: 'left', arrowright: 'right', arrowup: 'forward', arrowdown: 'back', pageup: 'up', pagedown: 'down'}[key];
  if (TURN_KEYS[key]) turnGhost(TURN_KEYS[key][0], TURN_KEYS[key][1] * step);
  else if (nudge) moveGhostBy(nudge, e.shiftKey ? 0.1 : 0.01);
  else if (key === 'enter' && !e.target.closest('button')) setGhostDown();
  else if (key === 'escape') { if(pendingPieceReference){pendingPieceReference=null;showGhostKnobs();return;}if (terminalStart) cancelGhost(); else setLooking(!looking); }
  else return;
  e.preventDefault();
});

// ---- anonymous return links and server saves ---------------------------------------
// The HttpOnly cookie remembers an opaque ID; the browser caches unsent edits.
const SAVE_KEY = TEST_BUILD ? 'banjo-test-play-save' : 'banjo-play-save';
let provisionalVisitor = null;
function loadSave() {
  let s = null;
  try { s = JSON.parse(localStorage.getItem(SAVE_KEY) || 'null'); } catch { /* private window */ }
  const importOldStars = !TEST_BUILD && s?.format !== 2 && !validVisitor(params.get('visitor'));
  const cachedIds = Object.keys(s?.players || {});
  s = anonymousSave(s, {visitor:params.get('visitor'), cookie:TEST_BUILD ? '' : document.cookie});
  if (!cachedIds.includes(s.current) && !s.migratedProfiles.includes(s.current) && !validVisitor(params.get('visitor')))
    provisionalVisitor = s.current;
  try {
    const first = s.players[s.current];
    for (let i = 0; i < localStorage.length; i++) {
      if (!importOldStars) break;
      const m = (localStorage.key(i) || '').match(/^banjo-level-(.+)$/);
      if (!m) continue;
      const row = first.levels[m[1]] || (first.levels[m[1]] = {});
      row.stars = Math.max(row.stars || 0, Number(localStorage.getItem(m[0])) || 0);
    }
  } catch { /* private window */ }
  return s;
}
let save = loadSave();
let profileStoragePersistent = false;
function cacheSave() { try { localStorage.setItem(SAVE_KEY, JSON.stringify(save)); return true; } catch { return false; } }
async function profileRequest(body) {
  const encoded = JSON.stringify(body);
  const response = await fetch(appPath('/api/profile'), {method:'POST', headers:{'Content-Type':'application/json'},
    body:encoded, keepalive:new TextEncoder().encode(encoded).byteLength < 60000});
  const data = await response.json();
  if (!response.ok) { const error = new Error(data.error || 'Could not save your profile.'); error.status = response.status; error.data = data; throw error; }
  return data;
}
function profileStatus() {
  const state = profileSync.state();
  if (state.error) return 'Not synced';
  if (!state.ready) return 'Opening…';
  if (state.pending) return 'Saving…';
  return profileStoragePersistent ? 'Saved' : 'Temporary storage';
}
function profileDetails() {
  const state = profileSync.state();
  if (state.error) return state.error + ' Keep this tab open. Save again to retry syncing, or use Share this design to export a copy.';
  if (!state.ready) return 'Opening your save.';
  if (state.pending) return 'Changes are waiting for the server to confirm the save.';
  return profileStoragePersistent ? 'Your changes are saved on the server.'
    : 'Server storage is temporary: saves may be lost when the website is updated. Use Share this design to export a copy.';
}
function designStatus(text, sync = false) {
  const node = $('design-status'); node.dataset.sync = String(sync); node.textContent = text;
}
let saveHelpSerial = 0;
function addSaveHelp(parent, label) {
  const panel = document.createElement('div'); panel.id = `save-help-${++saveHelpSerial}`;
  panel.className = 'save-help-panel'; panel.setAttribute('popover','auto');
  panel.setAttribute('role','dialog'); panel.setAttribute('aria-label',label);
  const trigger = button('?',e=>{
    e.preventDefault();
    if (panel.matches(':popover-open')) panel.hidePopover();
    else { panel.showPopover(); position(); }
    trigger.setAttribute('aria-expanded',String(panel.matches(':popover-open')));
  }, {className:'save-help-toggle',ariaLabel:label});
  trigger.setAttribute('popovertarget',panel.id); trigger.setAttribute('aria-haspopup','dialog'); trigger.setAttribute('aria-expanded','false');
  const head = document.createElement('div'); head.className = 'save-help-head';
  const title = document.createElement('strong'); title.textContent = label;
  const close = button('Close',()=>{panel.hidePopover();trigger.focus();},{ariaLabel:'Close save help'});
  head.append(title,close); panel.append(head);
  const notes = label === 'About your return link' ? [
    'This browser remembers your save with a cookie. Copy the return link to open your progress, designs and versions on another device.',
    'Keep this link private. Anyone with it can open and edit your saves.'
  ] : [
    'Drafts save automatically as you build. Save version keeps a checkpoint of the starting setup, not the running simulation.',
    'Saved versions reopens one of the latest 30 checkpoints. Restoring a different version also keeps the previous draft.'
  ];
  for (const text of notes) { const p = document.createElement('p'); p.textContent = text; panel.append(p); }
  const status = document.createElement('p'); status.className = 'save-help-current'; panel.append(status);
  const position = () => {
    if (!panel.matches(':popover-open')) return;
    if (!trigger.getClientRects().length) { panel.hidePopover(); return; }
    const r = trigger.getBoundingClientRect();
    const below = innerHeight-r.bottom-20, above = r.top-20, useBelow = below>=180 || below>=above;
    panel.style.maxHeight = `${Math.max(100,Math.min(innerHeight-24,useBelow?below:above))}px`;
    const w = panel.offsetWidth, h = panel.offsetHeight;
    panel.style.left = `${Math.max(12,Math.min(innerWidth-w-12,r.right-w))}px`;
    panel.style.top = `${Math.max(12,Math.min(innerHeight-h-12,useBelow?r.bottom+8:r.top-h-8))}px`;
  };
  panel.addEventListener('beforetoggle',e=>{if(e.newState==='open')status.textContent=profileDetails();});
  panel.addEventListener('toggle',()=>{trigger.setAttribute('aria-expanded',String(panel.matches(':popover-open')));position();});
  panel.positionSaveHelp = position;
  parent.append(trigger,panel);
}
addEventListener('resize',()=>{for(const panel of document.querySelectorAll('.save-help-panel:popover-open'))panel.positionSaveHelp();});
document.addEventListener('keydown',e=>{
  const panel = document.querySelector('.save-help-panel:popover-open');
  if (e.key!=='Escape'||!panel) return;
  e.preventDefault(); e.stopImmediatePropagation(); panel.hidePopover();
  document.querySelector(`[popovertarget="${panel.id}"]`)?.focus();
},true);
addSaveHelp($('save-design').parentElement,'About saving versions');
function updateProfileStatus() {
  for (const node of document.querySelectorAll('.profile-sync-status')) node.textContent = profileStatus();
  const node = $('design-status');
  if (node?.dataset.sync === 'true') node.textContent = profileStatus();
  for (const panel of document.querySelectorAll('.save-help-panel:popover-open')) panel.querySelector('.save-help-current').textContent = profileDetails();
}
const profileSync = new ProfileSync({request:profileRequest, read:() => me(),
  onChange:() => { cacheSave(); updateProfileStatus(); },
  onCommit:({visitor,revision,profile}) => {
    const metadata = save.cloud || (save.cloud = {});
    metadata[visitor] = {revision, base:profile, dirty:profileSync.state().dirty}; cacheSave();
  },
  onMerge:({profile,remappedDesignIds}) => {
    const selected = activeDesign?.id;
    save.players[save.current] = profile;
    if (selected) {
      activeDesign = profile.sandbox?.items?.find(d => d.id === (remappedDesignIds[selected] || selected)) || null;
      if (activeDesign) {
        $('title').textContent = activeDesign.name; renderDesignControls();
        history_.replaceState(null, '', appPath('/machine') + '?design=' + encodeURIComponent(activeDesign.id));
      }
    }
    cacheSave();
  }
});
function persist() {
  const metadata = save.cloud || (save.cloud = {});
  metadata[save.current] = {...metadata[save.current], dirty:true};
  const cached = cacheSave(); profileSync.schedule();
  return cached || profileSync.state().ready;
}
async function openAnonymousProfile() {
  const imports = [...save.migratedProfiles];
  for (const id of imports) {
    try {
      const imported = await profileRequest({op:'create', visitor:id, profile:save.players[id]});
      (save.cloud || (save.cloud = {}))[id] = {revision:imported.revision, base:imported.profile, dirty:false};
    } catch (error) { if (error.status !== 409) throw error; }
    save.migratedProfiles = save.migratedProfiles.filter(value => value !== id); cacheSave();
  }
  const explicit = validVisitor(params.get('visitor')) ? params.get('visitor').toLowerCase() : null;
  const opened = await profileRequest({op:'open', visitor:explicit || (imports.length ? save.current : null), cached_visitor:save.current});
  const cached = save.players[opened.visitor], metadata = save.cloud?.[opened.visitor];
  if (provisionalVisitor && provisionalVisitor !== opened.visitor) delete save.players[provisionalVisitor];
  provisionalVisitor = null;
  save.current = opened.visitor;
  // Clean caches defer to the server. An old browser save or interrupted save
  // merges with the last acknowledged snapshot, preserving concurrent drafts.
  save.players[opened.visitor] = cached && (metadata?.dirty || !metadata)
    ? mergeProfiles(opened.profile, cached, metadata?.base || {}).profile : opened.profile;
  me().levels ||= {};
  profileStoragePersistent = Boolean(opened.storage?.persistent);
  (save.cloud || (save.cloud = {}))[opened.visitor] = {revision:opened.revision, base:opened.profile,
    dirty:JSON.stringify(me()) !== JSON.stringify(opened.profile)};
  profileSync.initialize(opened); cacheSave();
  await profileSync.flush();
}
function me() { return save.players[save.current] || (save.players[save.current] = {levels: {}}); }
function record(id) { return me().levels[id] || {}; }
function bestStars(id) { return record(id).stars || 0; }
// A run's result, kept where it is better: more stars, or a win on less energy.
// The tools a player has won with -- a plank, a cannon, a steam engine --
// each first win with one an achievement. A player whose wins were kept
// before tools were counted has the tools of the levels they won.
const TOOL_NAMES = {plank: 'plank', knife: 'knife', cannon: 'cannon', steam: 'steam engine', ramp: 'ramp',
                    mirror: 'mirror', solar: 'solar panel', tackle: 'block and tackle', lens: 'lens', flipflop: 'flip-flop'};
// A piece's name on its button: as the tray calls it, but a flip-flop has its hyphen.
function pieceLabel(piece) { return piece==='base_object' ? ghost?.baseObject?.name || 'object' : ({door:'hinged door',trampoline:'spring trampoline',wind:'open airflow',loose_block:'loose block',flipflop:'flip-flop',water_wheel:'water wheel',water_tank:'water tank',water_chute:'water chute',water_collector:'water collector',pipe:'straight pipe',pipe_elbow:'pipe elbow',pipe_reducer:'pipe reducer',scaffold:'scaffolding',solar:'solar panel',tackle:'block and tackle',ignition:'heating coil',power_cable:'power cable'})[piece] || piece; }
function toolsOf(player) {
  if (!player.tools) {
    player.tools = {};
    for (const [id, row] of Object.entries(player.levels || {})) {
      const won = levels.find(l => l.id === id);
      if (won && (row.won_at || row.stars)) for (const t of won.tray) player.tools[t.piece] ??= id;
    }
  }
  return player.tools;
}
function toolName(piece) { return TOOL_NAMES[piece] || pieceLabel(piece); }

function keepResult(id, r) {
  const tools = toolsOf(me()), unlocked = [];
  if (r.earned.goal) for (const piece of new Set(placements.map(p => p.piece)))
    if (!tools[piece]) { tools[piece] = id; unlocked.push(piece); }
  const row = me().levels[id] || (me().levels[id] = {}), was = {...row};
  const lessEnergy = r.earned.goal && r.energy_j != null && (row.energy_j == null || r.energy_j < row.energy_j);
  if (r.stars > (row.stars || 0)) row.stars = r.stars;
  if (lessEnergy) row.energy_j = r.energy_j;
  if (r.earned.goal && !row.won_at) row.won_at = new Date().toISOString();
  me().last = id;
  persist();
  return {was, better: lessEnergy || r.stars > (was.stars || 0), unlocked};
}
window.machineSave = () => JSON.parse(JSON.stringify(save));
window.machineProfileState = () => profileSync.state();

// Energy as a person reads it: joules, kilo-, mega-, giga-.
function energyText(j) {
  if (j == null || !Number.isFinite(j)) return '—';
  const [div, unit] = [[1e9, 'GJ'], [1e6, 'MJ'], [1e3, 'kJ'], [1, 'J']].find(([d]) => Math.abs(j) >= d) || [1, 'J'];
  const v = j / div;
  return `${v >= 100 ? Math.round(v) : v >= 10 ? v.toFixed(1) : v.toFixed(2)} ${unit}`;
}

function renderLevels() {
  const nav = $('levels'); nav.replaceChildren();
  levels.forEach((l, i) => {
    const b = document.createElement('button'); b.type = 'button';
    const best = bestStars(l.id);
    b.textContent = `${i + 1}. ${l.title}${best ? ' ' + '★'.repeat(best) : ''}`;
    b.setAttribute('aria-current', String(Boolean(level) && l.id === level.id));
    b.addEventListener('click', () => chooseLevel(l.id).catch(() => {}));
    nav.append(b);
  });
}

function knobDefault(rule) { return rule.default ?? (rule.choices ? rule.choices[0] : rule.min); }
function levelTitle(l) { return l.free ? (activeDesign?.name || 'Sandbox') : l.variant
  ? `${l.title} · seed ${l.variant.seed.toString(16).padStart(8, '0')}` : l.title; }
const baseObjectTray={piece:'base_object',knobs:{
  x_m:{min:-10,max:10,step:.01,default:0,label:'along X (m)'},
  z_m:{min:-10,max:10,step:.01,default:0,label:'along Z (m)'},
  height_m:{min:-4,max:4,step:.01,default:0,label:'height change (m)'}}};
function trayItem(piece) { return piece==='base_object'?baseObjectTray:level.tray.find(t => t.piece === piece); }

const PIECE_INFO = {
  marble: ['motion', 'A ball to roll, drop, or set a machine moving.'],
  track: ['routes', 'A straight, sloping track with rails and an optional gate.'],
  bend: ['routes', 'A curved track to carry marbles around a corner.'],
  shelf: ['routes', 'Hold marbles behind a gate until its paddle is pressed.'],
  flipflop: ['routes', 'A rocker that sends arriving marbles to alternating sides.'],
  funnel: ['routes', 'Gather marbles into one outlet.'],
  block: ['structure', 'A post, wall, step, or stop to support your build.'],
  dominoes: ['motion', 'A row of dominoes to topple in a chain.'],
  door: ['motion', 'A real door on a vertical hinge. Push it with contact or open airflow; adjust hinge resistance.'],
  trapdoor: ['motion', 'A horizontal hinged flap that can fall under its own weight or carry a load.'],
  pendulum: ['motion', 'Raise a weighted arm, then let gravity swing it into another piece.'],
  trampoline: ['motion', 'A guided deck on four springs. A falling object compresses it and can rebound.'],
  flywheel: ['motion', 'A passive wheel stores rotation. Add a motor or drive it through contact.'],
  wind: ['power', 'A prescribed open-air field. Choose air speed and direction to push boxes or spheres.'],
  loose_block: ['structure', 'An independent material block that can fall, slide, collide or support a stack.'],
  lever: ['motion', 'A seesaw on a pin to transfer a push.'],
  plank: ['structure', 'A loose board to bridge a gap or join to another part.'],
  ramp: ['routes', 'A slope with a ball to start a rolling chain reaction.'],
  cannon: ['power', 'A powder charge that launches a ball.'],
  steam: ['power', 'A heated boiler and piston to lift or push.'],
  knife: ['motion', 'A swinging blade to cut a hanging rope.'],
  mirror: ['optics', 'Reflect a beam of light toward another part.'],
  solar: ['optics', 'Collect sunlight to power a machine.'],
  tackle: ['motion', 'Pulleys and a counterweight to lift a load.'],
  lens: ['optics', 'Focus or spread a beam through a glass lens.'],
  spring: ['motion', 'A latched spring drives a push plate. Aim it, compress it and release the latch to push a separate object.'],
  gear: ['motion', 'One toothed wheel on an axle. Choose its size, mesh it with another gear and connect a powered motor to an axle.'],
  gears: ['motion', 'Legacy gear pair from a saved design.'],
  weight: ['motion', 'A real material block, loose, hanging or guided.'],
  motor: ['electrics', 'Wire a battery to a motor that applies torque to an axle.'],
  battery: ['electrics', 'A finite energy store with labelled positive and negative terminals.'],
  switch: ['electrics', 'Drag a hinged rocker to open or close a wired circuit, or let a marble tip the paddle.'],
  bulb: ['electrics', 'A wired lamp with measured electrical, light and heat power.'],
  wire: ['electrics', 'Connect two terminals. Crossed wires stay separate.'],
  power_cable: ['electrics', 'Click a solar output, then a winch or battery input. A two-conductor lead carries collected power.'],
  ignition: ['electrics', 'A wired heating coil attached to a material target.'],
  resistor: ['electrics', 'A rated two-terminal resistance with measured voltage drop and Joule heat.'],
  capacitor: ['electrics', 'A nonpolar capacitor: charge, stored energy, internal resistance and leakage.'],
  water_wheel: ['water', 'River current or falling water pushes the paddles. Connect its drum to lift a load.'],
  water_tank: ['water', 'A separate finite gravity tank. Open its tap wider for more flow; falling water level slows it.'],
  water_chute: ['water', 'Aim and tip a supported open trough. Gravity and contact divert the falling water.'],
  water_collector: ['water', 'A separate fixed container. Its meter counts water currently retained inside.'],
  pipe: ['routes', 'A hollow pipe for water or marbles. Adjust its bore, slope and length; remove scaffolding to let it fall.'],
  pipe_elbow: ['routes', 'A hollow corner for water or marbles. Adjust the bore, bend radius, turn and fall.'],
  pipe_reducer: ['routes', 'A tapered pipe with independent inlet and outlet radii. A ball wider than its outlet cannot pass.'],
  scaffold: ['structure', 'A grounded platform with visible legs and feet. Put it below a loose piece to support it by contact.'],
  catapult: ['motion', 'A counterweight turns a cradle that launches through physical contact.']
};
function libraryTray() { return level.free || level.tray.filter(t => !t.attach).length > 4; }
function piecesLeft(t) { return (t.count || 1) - placements.filter(p => p.piece === t.piece).length; }
async function addTrayPiece(t) {
  if (ghost || piecesLeft(t) <= 0) return;
  if(level.free && ['water_wheel','water_tank','water_chute','water_collector'].includes(t.piece) && !(activeDesign.draft.base||sandboxBase).ground){
    try{if(!await applySandboxGround('channel'))return;t=trayItem(t.piece);}
    catch(e){$('verdict').textContent=e.data?.problems?.join('; ')||e.message;return;}
  }
  trayPiece = t.piece;
  const p = {piece: t.piece};
  for (const [key, rule] of Object.entries(t.knobs)) p[key] = knobDefault(rule);
  startGhost(p, placements.length,Boolean(t.start_at_defaults));
}
function openPiecePicker() {
  if (!level || ghost || $('piece-picker').open) return;
  $('piece-search').value = ''; $('piece-category').value = 'all';
  $('piece-picker-close').textContent = level.free ? 'Back to sandbox' : 'Back to puzzle';
  renderPiecePicker();
  document.body.classList.add('choosing-piece');
  $('piece-picker').showModal();
  // Do not raise the phone keyboard before a player asks to search.
  $('piece-picker-close').focus({preventScroll: true});
}
function renderPiecePicker() {
  const query = $('piece-search').value.trim().toLowerCase(), category = $('piece-category').value;
  const items = level.tray.filter(t => !t.attach && !t.legacy).filter(t => {
    const [group, description] = PIECE_INFO[t.piece] || ['structure', 'Add this piece to your machine.'];
    return (category === 'all' || category === group) && `${pieceLabel(t.piece)} ${description}`.toLowerCase().includes(query);
  });
  $('piece-results').textContent = `${items.length} ${items.length === 1 ? 'piece' : 'pieces'}`;
  $('piece-empty').hidden = Boolean(items.length);
  $('piece-grid').replaceChildren(...items.map(t => {
    const left = piecesLeft(t);
    const card = button('', () => {
      if (ghost || piecesLeft(t) <= 0) return;
      $('piece-picker').close();
      addTrayPiece(t);
      view.focus({preventScroll: true});
    }, {className: 'piece-card', ariaLabel: `Add a ${pieceLabel(t.piece)}`, disabled: left <= 0});
    card.dataset.piece=t.piece;
    const picture = Object.assign(document.createElement('span'), {className: 'piece-picture'});
    const img = Object.assign(document.createElement('img'), {alt: '', hidden: true});
    picture.append(img); pictureInto(img, t);
    card.append(picture, Object.assign(document.createElement('strong'), {textContent: pieceLabel(t.piece)}),
      Object.assign(document.createElement('span'), {className: 'piece-description', textContent: PIECE_INFO[t.piece]?.[1] || 'Add this piece to your machine.'}));
    if (!level.free || left <= 0) card.append(Object.assign(document.createElement('span'), {className: 'piece-count', textContent: left > 0 ? `${left} left` : 'none left'}));
    const example = level.free && sandboxTemplates.find(example => (example.pieces || example.placements?.map(p => p.piece) || []).includes(t.piece));
    if (!example) return card;
    const wrapper = Object.assign(document.createElement('div'), {className: 'piece-example-card'});
    wrapper.append(card, button(`Try ${pieceLabel(t.piece)} example`, () => {
      $('piece-picker').close(); parkDesign();
      const design = newDesign(example.name, {base: example.base, placements: example.placements});
      checkpointDesign(design); persist();
      chooseLevel('free', design).catch(e => { clockMessage(e.message); });
    }));
    return wrapper;
  }));
}
$('piece-search').addEventListener('input', renderPiecePicker);
$('piece-category').addEventListener('change', renderPiecePicker);
$('piece-picker-close').addEventListener('click', () => $('piece-picker').close());
$('piece-picker').addEventListener('close', () => {
  document.body.classList.remove('choosing-piece');
  const target = ghost ? view : !$('tray-library').hidden ? $('tray-library') : $('tray-add');
  target?.focus({preventScroll: true});
});
$('piece-picker').addEventListener('keydown', e => {
  if (e.key !== 'Tab') return;
  const controls = [...$('piece-picker').querySelectorAll('button:not(:disabled), input, select')];
  const first = controls[0], last = controls.at(-1);
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
});

// One pictured tray card lives where the player adds/adjusts a piece.
// Browsing changes only this card, never the setup or the engine session.
let trayLevel = null, trayDesign = null, trayPiece = null;
function browseTray(direction) {
  if (!level || ghost) return;
  const items = level.tray.filter(t => !t.attach && !t.legacy && (level.free || piecesLeft(t)>0));
  if (items.length < 2) return;
  const index = Math.max(0, items.findIndex(t => t.piece === trayPiece));
  trayPiece = items[(index + direction + items.length) % items.length].piece;
  renderSceneTray();
}
$('tray-prev').addEventListener('click', () => browseTray(-1));
$('tray-next').addEventListener('click', () => browseTray(1));
$('tray-library').addEventListener('click', openPiecePicker);
function renderSceneTray() {
  const bar = $('scene-tray');
  bar.hidden = !LEVEL_MODE || !level || Boolean(ghost);
  if (bar.hidden) return;
  const items = level.tray.filter(t => !t.attach && !t.legacy && (level.free || piecesLeft(t)>0));
  if (trayLevel !== level || trayDesign !== activeDesign?.id || !items.some(t => t.piece === trayPiece)) {
    trayLevel = level; trayDesign = activeDesign?.id; trayPiece = items[0]?.piece;
  }
  const ul = $('tray'); ul.replaceChildren();
  $('tray-prev').hidden = $('tray-next').hidden = items.length < 2;
  $('tray-page').hidden = items.length < 2;
  $('tray-page').textContent = `${items.findIndex(t => t.piece === trayPiece)+1} / ${items.length}`;
  $('tray-library').hidden = !libraryTray();
  const t = items.find(t => t.piece === trayPiece);
  if (!t) { bar.hidden = true; return; }
  const left = piecesLeft(t), li = document.createElement('li');
  const editIndex=!level.free&&left<=0?placements.findIndex(p=>p.piece===t.piece):-1;
  const card = button('', () => editIndex>=0?pickUp(editIndex):addTrayPiece(t), {id:'tray-add', ariaLabel:editIndex>=0?`Adjust ${pieceLabel(t.piece)}`:`Add a ${pieceLabel(t.piece)}`,
    disabled:left <= 0&&editIndex<0, title:editIndex>=0?'Click to adjust the piece you placed':left > 0 ? 'Click to place this piece' : 'All of these pieces are placed'});
  card.dataset.piece=t.piece;
  const picture = Object.assign(document.createElement('span'), {className:'tray-picture'});
  const img = Object.assign(document.createElement('img'), {alt:'', hidden:true});
  picture.append(img); pictureInto(img,t);
  const caption = Object.assign(document.createElement('span'), {className:'tray-caption'});
  caption.append(Object.assign(document.createElement('strong'), {className:'tray-name', textContent:pieceLabel(t.piece)}),
    Object.assign(document.createElement('small'), {className:'tray-left', textContent:editIndex>=0?'Click to adjust':left <= 0 ? 'none left' : level.free ? 'Click to add' : `${left} left`}));
  card.append(picture,caption); li.append(card); ul.append(li);
}
function renderTray() { renderSceneTray(); }

function button(text, onClick, extra = {}, repeat = /^[+−-](?:\s*\d|$)/.test(text)) {
  const b = Object.assign(document.createElement('button'), {type: 'button', textContent: text}, extra);
  b.addEventListener('click', onClick);
  if(repeat)repeatOnHold(b,onClick);
  return b;
}

// A knob's control: a slider (or a list of choices) that changes the piece
// and then calls changed().
function knobControl(p, key, rule, what, changed) {
  const label = Object.assign(document.createElement('label'), {className: 'knob'});
  label.append(Object.assign(document.createElement('span'), {textContent: rule.label || key}));
  let input;
  const shown = Object.assign(document.createElement('output'), {textContent: String(p[key]) + (rule.turning ? '°' : '')});
  if (rule.part || rule.hinge || rule.terminal || rule.power_port) {
    input = referenceControl(p, key, rule, () => { shown.textContent = p[key]; changed(); });
  } else if (rule.choices) {
    input = document.createElement('select');
    for (const c of rule.choices) input.append(Object.assign(document.createElement('option'), {value: c, textContent: c}));
    input.value = p[key];
    // A choice keeps its own type: a number of pulleys stays a number.
    input.addEventListener('change', () => {
      p[key] = rule.choices.find(c => String(c) === input.value) ?? input.value;
      shown.textContent = input.value; changed();
    });
  } else {
    input = Object.assign(document.createElement('input'), {type: 'range', min: rule.min, max: rule.max, step: rule.step || 0.01, value: p[key]});
    input.addEventListener('input', () => { p[key] = Number(input.value); shown.textContent = input.value + (rule.turning ? '°' : ''); changed(); });
  }
  input.setAttribute('aria-label', `${rule.label || key} of ${what}`);
  input.dataset.knob=key;
  label.append(input, shown);
  return {label, input, shown};
}

function referenceControl(p, key, rule, changed) {
  if(rule.connection_target){
    const connected=p[key]===rule.connection_target;
    const control=button(connected?`Disconnect rope from ${rule.connection_label}`:`Connect rope to ${rule.connection_label}`,()=>{
      p[key]=p[key]===rule.connection_target?'':rule.connection_target;
      control.value=p[key];control.textContent=p[key]?`Disconnect rope from ${rule.connection_label}`:`Connect rope to ${rule.connection_label}`;
      control.setAttribute('aria-pressed',String(Boolean(p[key])));changed();
    });
    control.classList.add('connection-action');
    control.value=p[key]||'';control.setAttribute('aria-pressed',String(connected));
    return control;
  }
  const input = document.createElement('select');
  const values = new Set([rule.default || '', p[key] || '']);
  if (rule.power_port) {
    for (const port of machine?.electrical?.power_ports || [])
      if (port.kind === rule.power_port) values.add(port.name);
  } else if (rule.terminal) {
    for (const d of machine?.electrical?.devices || [])
      for (const terminal of Object.keys(d.terminals || {})) values.add(`${d.name}:${terminal}`);
  } else if (rule.hinge) {
    for (const j of machine?.joints || []) if (j.kind === 'hinge') values.add(j.name);
  } else if (key === 'battery') {
    for (const b of machine?.batteries || []) values.add(b.name);
  } else {
    const mine=ghost&&ghostName();
    for (const part of machine?.parts || []) if(key!=='load_part'||(!part.fixed&&!(mine&&(part.name===mine||part.name.startsWith(mine+' ')))))values.add(part.name);
  }
  for (const value of values) input.append(new Option(value || 'Choose a connection', value));
  input.value = p[key] || ''; input.setAttribute('aria-label', `Its ${knobName(rule, key)}`);
  input.addEventListener('change', () => { p[key] = input.value; changed(); });
  return input;
}

function showDeviceControlStatus(message,node){
  $('machine-control-status').textContent=message;
  const out=node.closest('.device-live-card')?.querySelector('.device-control-status');if(out)out.textContent=message;
}
let connectionFramingPending=false;
function frameNewConnections(){
  if(!connectionFramingPending||ghost||playing||world.t>0)return;
  connectionFramingPending=false;
  const points=[...terminalMap(machine?.electrical).values()].map(at=>new THREE.Vector3(...at));
  if(!points.length)return;
  const rect=view.getBoundingClientRect(),top=rect.top+sceneReadoutTop(rect)+12;
  for(let i=0;i<12;i++){
    freshView();
    if(points.every(at=>{const p=at.clone().project(camera),x=rect.left+(p.x+1)*rect.width/2,y=rect.top+(1-p.y)*rect.height/2;
      return Math.abs(p.z)<=1&&x>=rect.left+18&&x<=rect.right-18&&y>=top&&y<=rect.bottom-18;}))return;
    distance=Math.min(40,distance*1.12);
  }
  freshView();
}
function renderMachineControls() {
  connectionFramingPending=true;
  liveControlPending = false;
  const controls = $('machine-controls'), rows = $('machine-control-rows');
  rows.replaceChildren();liveCards.replaceChildren();
  const beside=(node,name,at)=>{
    const card=document.createElement('section');card.className='device-live-card';card.anchor=new THREE.Vector3(...at);
    card.deviceName=name;card.append(Object.assign(document.createElement('strong'),{textContent:name}),node,Object.assign(document.createElement('output'),{className:'device-control-status',ariaLive:'polite'}));liveCards.append(card);return node;
  };
  const action = (label, command, name, at, autoStart=false) => {
    const b = button(label, async () => {
      b.disabled = true;
      try {
        liveControlPending = true;
        const operation=command();liveControlRequest = api({...operation, session});
        await liveControlRequest;
        if(operation.op==='release_joint')b.dataset.queuedRelease='true';
        if(autoStart&&!playing){liveControlPending=false;await setPlaying(true);}
        showDeviceControlStatus(playing?'Applying at the next engine step.':'Queued. Choose Try It! to continue.',b); if (wake) wake();
      }
      catch (e) { liveControlPending = false;showDeviceControlStatus(e.message,b); }
      finally { b.disabled = b.dataset.queuedRelease==='true'; }
    });
    beside(b,name,at);
  };
  for (const source of (level?.water_controls===false?[]:machine?.spouts || [])) {
    if (source.initial_volume_l == null) continue;
    if (source.reservoir_area_m2>0) {
      const label=document.createElement('label');label.textContent='Tap opening';
      const input=Object.assign(document.createElement('input'),{type:'range',min:0,max:100,step:1,value:100*(source.opening_fraction??1)});
      input.setAttribute('aria-label',`Live tap opening of ${source.name}`);
      const output=document.createElement('output');output.textContent=`${input.value}%`;
      input.addEventListener('input',()=>{output.textContent=`${input.value}%`;});
      input.addEventListener('change',async()=>{
        try {liveControlPending=true;liveControlRequest=api({op:'water_opening',session,name:source.name,fraction:Number(input.value)/100});
          await liveControlRequest;showDeviceControlStatus(playing?'Applying tap opening.':'Opening queued. Choose Try It! to continue.',input);if(wake)wake();}
        catch(error){liveControlPending=false;showDeviceControlStatus(error.message,input);}
      });
      label.append(input,output);beside(label,source.name.replace(/ outlet$/,''),source.at_m);continue;
    }
    let opened = source.valve_open !== false;
    action(`Toggle ${source.name} valve`, () => ({op: 'water_valve', name: source.name, open: opened = !opened}),source.name,source.at_m);
  }
  for (const joint of machine?.joints || []) {
    if (!/^your (catapult|spring) \d+ restraint$/.test(joint.name)) continue;
    const spring=joint.name.includes(' spring ');
    action(spring?'Release spring':`Release ${joint.name.replace(' restraint', '')}`, () => ({op: 'release_joint', name: joint.name}),joint.name.replace(' restraint',''),joint.at_m||machine.parts.find(p=>p.name===joint.b)?.at_m||[0,.5,0],spring);
    const card=liveCards.lastChild,release=card.querySelector('button');
    card.dataset.restraint=joint.name;release.dataset.release='true';
    const index=placements.findIndex((p,i)=>`your ${p.piece} ${i+1} restraint`===joint.name);
    if(spring&&index>=0){
      const adjust=button('Adjust spring',()=>{
        if(session&&!playing&&world.t===0&&!liveControlPending)pickUp(index);
      },{className:'spring-adjust',title:'Change the stored push before releasing the latch'});
      const actions=Object.assign(document.createElement('div'),{className:'spring-live-actions'});
      release.replaceWith(actions);actions.append(adjust,release);
    }
  }
  controls.hidden = true; controls.open = false; $('machine-control-status').textContent = '';
}

function describeKnobs(p, t) {
  const turned = Object.entries(t.knobs).filter(([k, r]) => pieceKnobVisible(p,k) && r.turning && p[k]).map(([k, r]) => `${r.label || k} ${p[k]}°`);
  const rest = Object.entries(t.knobs).filter(([k, r]) => pieceKnobVisible(p,k) && !r.turning && p[k] != null && !(r.free && !p[k]))
    .map(([k, r]) => `${(r.label || k).replace(/ \(.*\)$/, '')} ${p[k]}`);
  return [...rest, ...turned].join(' · ');
}

// Additional precision controls stay in the same inspector as the active knob.
function ghostItem() {
  const p = ghost.p, t = trayItem(p.piece), what = ghostName();
  const li = Object.assign(document.createElement('div'), {className: 'ghost-piece'});
  ghost.inputs = {};
  const turning = Object.assign(document.createElement('fieldset'), {className: 'turning'});
  turning.append(Object.assign(document.createElement('legend'), {textContent: 'Turn it (degrees)'}));
  for (const [key, rule] of Object.entries(t.knobs)) {
    if (!pieceKnobVisible(p,key) || rule.connection_target) continue;
    const c = knobControl(p, key, rule, what, () => {
      if (key==='x_m'||key==='z_m') ghost.gridLocks=null;
      if ((key==='mount' && p.piece==='battery')||(key==='mode'&&p.piece==='switch')||(key==='size'&&p.piece==='bulb')) {renderPlaced();renderGhostBar();}
      if (key !== 'x_m' && key !== 'z_m') ghost.card = key;
      followGhost(); showGhostKnobs(); askGhost();
    });
    if (key !== 'x_m' && key !== 'z_m') c.input.addEventListener('change', () => renderGhostBar());
    ghost.inputs[key] = [c.input, c.shown];
    if (!rule.turning) { li.append(c.label); continue; }
    // − and + by 15 degrees either side of the slider; the slider for the rest.
    const row = Object.assign(document.createElement('div'), {className: 'turn-row'});
    const word = rule.label.split(' ')[0];
    row.append(button('−15°', () => turnGhost(key, -15), {ariaLabel: `${word} back 15 degrees`}), c.label,
               button('+15°', () => turnGhost(key, 15), {ariaLabel: `${word} on 15 degrees`}));
    turning.append(row);
  }
  if (turning.children.length > 1) {
    turning.append(button('Square it up', () => {
      for (const [key, rule] of Object.entries(t.knobs)) if (rule.turning&&pieceKnobVisible(p,key)) setKnob(p, key, 0);
      showGhostKnobs(); askGhost();
    }));
    li.append(turning);
  }
  return li;
}

function renderPlaced() {
  $('placed').replaceChildren();
  $('placed-head').hidden=true;
  if (ghost) { showGhostKnobs(); showGhostState(); }
  const made = Object.values(placedEnergy).reduce((a, b) => a + (b.j || 0), 0);
  $('cost-line').textContent = !placements.length ? ''
    : level.free ? `${placements.length} ${placements.length === 1 ? 'piece' : 'pieces'} on the table, ${energyText(made)} to make.`
    : `Your pieces take ${energyText(made)} to make. Par for the whole win, pieces and run: ${energyText(level.par_energy_j)}.`;
  $('placed-head').hidden = true;
  $('restart-pieces').hidden=true;
}
window.machineEditableObjects=()=>[
  ...placements.map((p,index)=>{const name=`your ${p.piece} ${index+1}`;return {index,name,parts:[...(machine?.parts||[]).filter(part=>part.name===name||part.name.startsWith(name+' ')).map(part=>part.name),...(machine?.joints||[]).filter(j=>j.name===name||j.name.startsWith(name+' ')).map(j=>j.name),...(machine?.joints||[]).filter(j=>j.kind==='pulley'&&j.name.startsWith(name+' ')).map(j=>j.b)]};}),
  ...(level?.free?sandboxObjects.map((o,i)=>({...o,index:placements.length+i})):[])];
// QA can click actual rendered solids, rather than the empty center of a
// hollow pipe or compound ramp. This reads geometry and changes no setup.
window.machineBodyHitPoints=name=>{
  freshView();const mesh=meshes.get(name)||ropes.find(r=>r.name===name)?.line,rect=renderer.domElement.getBoundingClientRect(),points=[];
  mesh?.traverse(part=>{
    if(part.isLine){const data=part.geometry.attributes.position;for(let i=1;i<data.count;i++){const p=new THREE.Vector3().fromBufferAttribute(data,i).lerp(new THREE.Vector3().fromBufferAttribute(data,i-1),.5).applyMatrix4(part.matrixWorld).project(camera);points.push([rect.left+(p.x+1)*rect.width/2,rect.top+(1-p.y)*rect.height/2]);}return;}
    if(!part.isMesh||!part.geometry)return;
    part.geometry.computeBoundingBox();const center=part.geometry.boundingBox.getCenter(new THREE.Vector3()),size=part.geometry.boundingBox.getSize(new THREE.Vector3());
    const samples=[center,...['x','y','z'].flatMap(axis=>[-.3,.3].map(offset=>{const p=center.clone();p[axis]+=size[axis]*offset;return p;}))];
    const emit=matrix=>{for(const point of samples){const p=point.clone().applyMatrix4(matrix).project(camera);if(Math.abs(p.z)<=1)points.push([rect.left+(p.x+1)*rect.width/2,rect.top+(1-p.y)*rect.height/2]);}};
    if(part.isInstancedMesh){const local=new THREE.Matrix4();for(let i=0;i<part.count;i+=Math.max(1,Math.ceil(part.count/24))){part.getMatrixAt(i,local);emit(part.matrixWorld.clone().multiply(local));}}
    else emit(part.matrixWorld);
  });return points;
};

// A piece taken away: the pieces after it move up one, so what a join names
// moves with them, and a join to the piece taken away goes with it.
function removePiece(i) {
  const gone = `your ${placements[i].piece} ${i + 1}`;
  const belongs = n => typeof n === 'string' && (n === gone || n.startsWith(gone + ' ') || n.startsWith(gone + ':'));
  const refKeys = p => Object.entries(trayItem(p.piece).knobs).filter(([, r]) => r.part || r.hinge || r.terminal || r.power_port).map(([k]) => k);
  const remaining = placements.map((p, oldIndex) => ({p, oldIndex})).filter(({p, oldIndex}) => oldIndex !== i &&
    (!['link', 'wire', 'power_cable'].includes(p.piece) || !refKeys(p).some(k => belongs(p[k]))));
  const names = new Map(remaining.map(({p, oldIndex}, newIndex) => [`your ${p.piece} ${oldIndex + 1}`, `your ${p.piece} ${newIndex + 1}`]));
  const renamed = name => {
    const m = /^(your \S+ \d+)(.*)$/.exec(name);
    return m && names.has(m[1]) ? names.get(m[1]) + m[2] : name;
  };
  placements = remaining.map(({p}) => {
      const next = {...p};
      for (const key of refKeys(p)) next[key] = belongs(p[key]) ? knobDefault(trayItem(p.piece).knobs[key]) : renamed(p[key] || '');
      return next;
    });
}

function scheduleRebuild(ms = 350) {
  clearTimeout(rebuildTimer);
  // Set down must leave ready immediately: the old session is not the new setup.
  if (!ms) { rebuildLevel(false).catch(() => {}); return; }
  rebuildTimer = setTimeout(() => rebuildLevel(false).catch(() => {}), ms);
}

// Every change to the pieces can be taken back, and put back again: a copy
// of them as they were, before each change.
let undone = [], redone = [];
function remember() {
  undone.push(setupSnapshot()); redone = [];
  if (undone.length > 60) undone.shift();
  showUndo();
}
function showUndo() {
  $('undo-pieces').disabled = !undone.length; $('redo-pieces').disabled = !redone.length;
  $('undo-pieces').title=undone.length?'Take back the last change (Ctrl+Z)':'No changes to undo yet';
}
function travel(from, to) {
  if (!from.length) return;
  to.push(setupSnapshot());
  const back = JSON.parse(from.pop());
  placements = Array.isArray(back) ? back : back.placements;
  if (!Array.isArray(back) && activeDesign) {
    if (JSON.stringify(activeDesign.draft.base) !== JSON.stringify(back.base)) framedFree = false;
    activeDesign.draft.base = back.base;
  }
  endGhost(); cancelAttach(); renderTray(); renderPlaced(); showUndo(); scheduleRebuild(0);
}
function setupSnapshot() { return JSON.stringify(level?.free ? {placements, base: activeDesign?.draft.base || null} : placements); }
async function removeSelectedObject(){
  const g=ghost;if(!g)return;
  try{
    if(g.baseObject){
      const stamp=setupSnapshot(),r=await api({op:'sandbox_object',level:'free',base:g.originalBase,object:g.baseObject.id,remove:true});
      if(ghost!==g || setupSnapshot()!==stamp)return;
      const removed=new Set(r.removed);
      const dependent=placements.map((p,i)=>({p,i})).filter(({p})=>Object.values(p).some(v=>typeof v==='string'&&removed.has(v.split(':')[0])));
      remember();activeDesign.draft.base=r.base;
      for(const {i} of dependent.reverse())removePiece(i);
    }else{remember();removePiece(g.index);}
    endGhost();renderTray();renderPlaced();scheduleRebuild(0);
  }catch(e){$('verdict').textContent=e.data?.problems?.join('; ')||e.message;}
}
$('undo-pieces').addEventListener('click', () => travel(undone, redone));
$('redo-pieces').addEventListener('click', () => travel(redone, undone));
document.addEventListener('keydown', e => {
  if (document.querySelector('dialog[open]') || !LEVEL_MODE || !(e.ctrlKey || e.metaKey) || e.target.closest('input, textarea, select')) return;
  const key = e.key.toLowerCase();
  if (key === 'z' && !e.shiftKey) travel(undone, redone);
  else if (key === 'y' || (key === 'z' && e.shiftKey)) travel(redone, undone);
  else return;
  e.preventDefault();
});

// A free build's setup is synced as it changes, separately from the live world.
function keepBuild() {
  updateHeaderShare();
  if (!level?.free || !activeDesign) return;
  activeDesign.draft.placements = clone(placements);
  activeDesign.at = new Date().toISOString();
  persist(); designStatus(profileStatus(),true);
}

// Named designs and immutable checkpoints, alongside this player's progress.
// The draft is the setup, never the bodies' positions after a simulation.
const clone = value => JSON.parse(JSON.stringify(value));
function designStore() {
  if (!me().sandbox) {
    me().sandbox = {items: [], last: null};
    if (me().free?.placements?.length) {
      const d = newDesign('My free build', {base: null, placements: me().free.placements});
      me().sandbox.last = d.id;
    }
    persist();
  }
  for(const d of me().sandbox.items || []) {
    preserveLegacyWater(d.draft);
    for(const v of d.versions || [])preserveLegacyWater(v.draft);
  }
  return me().sandbox;
}
function preserveLegacyWater(draft) {
  for(const p of draft?.placements || []) {
    if(p.piece==='water_wheel' && p.side==null)p.side='left';
    if(p.piece==='water_tank' && p.outlet_model==null)p.outlet_model='metered';
  }
  return draft;
}
function newDesign(name, draft = {base: null, placements: []}) {
  const store = me().sandbox || (me().sandbox = {items: [], last: null});
  const d = {id: crypto.randomUUID(), name: name.trim().slice(0, 60) || 'Untitled design',
    draft: clone(draft), versions: [], nextVersion: 1, at: new Date().toISOString()};
  store.items.push(d); store.last = d.id; persist();
  return d;
}
function checkpointDesign(d, label = '') {
  d.versions.push({number: d.nextVersion++, at: new Date().toISOString(), label, draft: clone(d.draft)});
  if (d.versions.length > 30) d.versions.shift();
}
function renderDesignControls() {
  $('sandbox-controls').hidden = !level?.free;
  $('design-versions').hidden = !level?.free;
  $('machine-data').hidden = !level?.free;
  $('sandbox-environment').hidden = !level?.free;
  if(level?.free){const g=activeDesign?.draft.base?.ground;$('environment-kind').value=g?.kind==='flume'?(g.discharge_m3_s>0?'river':'channel'):'table';
    $('river-flow').value=(g?.discharge_m3_s||.1)*1000;}
  if (!level?.free || !activeDesign) return;
  $('design-name').value = activeDesign.name;
  const pick = $('version-pick');
  // A save acknowledgement or conflict merge can refresh this list while
  // the player is choosing a version. Keep that choice within this design.
  const selected = pick.dataset.designId === activeDesign.id ? pick.value : '';
  pick.dataset.designId = activeDesign.id; pick.replaceChildren();
  for (const v of [...activeDesign.versions].reverse())
    pick.append(new Option(`Version ${v.number} · ${new Date(v.at).toLocaleString()}${v.label ? ' · ' + v.label : ''}`, v.number));
  if ([...pick.options].some(option => option.value === selected)) pick.value = selected;
  $('restore-version').disabled = !activeDesign.versions.length;
}
function parkDesign() {
  closeLevelIntroduction();
  stopSwitchDrag();
  if ($('piece-picker').open) $('piece-picker').close();
  keepBuild(); clearTimeout(rebuildTimer); clearTimeout(previewTimer); endGhost(); cancelAttach(); closeDone();
  previewAsk++; clearPreview(); resetLaserPreview(); polling++;
  releaseWorld().catch(() => {});
}
function showSandboxScreen(show = true) {
  const box = $('sandbox-screen'); box.hidden = !show;
  if (!show) for (const panel of box.querySelectorAll('.save-help-panel:popover-open')) panel.hidePopover();
  document.body.classList.toggle('on-sandbox', show);
  if (!show) { resize(); return; }
  parkDesign(); showLevelsScreen(false);
  history_.replaceState(null, '', appPath('/machine'));
  updateHeaderShare();
  box.replaceChildren();
  const add = (parent, tag, props) => parent.appendChild(Object.assign(document.createElement(tag), props));
  const head = add(box, 'div', {className: 'ls-head'});
  add(head, 'h1', {textContent: 'Sandbox'});
  const more = createLevelMoreMenu(box,{id:'design-more'}).content;
  renderReturnLink(more);
  renderDesignGallery({box,head,store:designStore(),templates:sandboxTemplates,
    openDesign:d=>chooseLevel('free',d),
    createDesign:(name,draft,template)=>{const d=newDesign(name,draft);if(template){checkpointDesign(d);persist();}return d;}});
}
$('sandbox-open').addEventListener('click', e => { e.preventDefault(); if (freeLevel) showSandboxScreen(); });
$('designs-open').addEventListener('click', () => showSandboxScreen());
async function applySandboxGround(kind,flow=100){
  if(!activeDesign||!level?.free)return false;
  if(ghostInTheWay())return false;
  const stamp=setupSnapshot(),design=activeDesign,next=clone(activeDesign.draft.base||sandboxBase);
  next.ground=kind==='table'?null:{kind:'flume',nx:100,nz:60,cell_m:.1,trench_z_m:0,
    trench_width_m:.6,trench_depth_m:.35,trench_slope:.005,...(next.ground||{}),discharge_m3_s:kind==='river'?flow/1000:0};
  await api({op:'check',level:'free',base:next,placements});
  if(activeDesign!==design||setupSnapshot()!==stamp)return false;
  remember();activeDesign.draft.base=next;framedFree=false;
  await rebuildLevel(false);return true;
}
$('environment-apply').addEventListener('click',async()=>{
  const b=$('environment-apply');b.disabled=true;
  try{const kind=$('environment-kind').value,flow=Number($('river-flow').value);
    if(kind==='river'&&!$('river-flow').checkValidity())throw Error('Choose a flow from 1 to 1,000 L/s.');
    if(await applySandboxGround(kind,flow))$('environment-status').textContent=kind==='river'?`River added · ${flow} L/s`:'Ground updated';
  }catch(e){$('environment-status').textContent=e.data?.problems?.join('; ')||e.message;renderDesignControls();}
  finally{b.disabled=false;}
});
$('design-name').addEventListener('change', () => {
  if (!activeDesign) return;
  activeDesign.name = $('design-name').value.trim() || 'Untitled design';
  $('title').textContent = activeDesign.name; keepBuild();
  $('scene-goal').querySelector('strong').textContent=activeDesign.name;
});
$('save-design').addEventListener('click', async () => {
  if (!activeDesign || ghostInTheWay()) return;
  const d = activeDesign; $('save-design').disabled = true;
  const setup = setupSnapshot();
  let savedVersion = null;
  try {
    await api({op: 'check', level: 'free', ...sandboxRequest(), placements});
    if (activeDesign !== d) return;
    if (setup !== setupSnapshot()) throw new Error('The setup changed while checking it. Press Save version again.');
    d.name = $('design-name').value.trim() || 'Untitled design'; keepBuild();
    checkpointDesign(d); savedVersion = d.versions.at(-1); persist();
    await profileSync.flush();
    if (!activeDesign?.versions.some(v => v.number === savedVersion.number && v.at === savedVersion.at)) return;
    renderDesignControls(); $('title').textContent = activeDesign.name;
    designStatus(`Version ${savedVersion.number} saved${profileStoragePersistent ? '' : ' (temporary)'}.`);
  } catch (e) { if (activeDesign === d || activeDesign?.versions.some(v => v.number === savedVersion?.number && v.at === savedVersion?.at)) {
    renderDesignControls(); designStatus('Version not synced: ' + (e.data?.problems?.join('; ') || e.message));
  } }
  finally { $('save-design').disabled = false; }
});
$('restore-version').addEventListener('click', async () => {
  if (!activeDesign) return;
  const restoredDesign = activeDesign.id;
  const v = activeDesign.versions.find(v => v.number === Number($('version-pick').value));
  if (!v) return;
  keepBuild(); const draft = clone(v.draft);
  if (JSON.stringify(draft) !== JSON.stringify(activeDesign.draft)) checkpointDesign(activeDesign, 'Before restore');
  activeDesign.draft = draft;
  persist();
  endGhost(); cancelAttach(); placements = clone(draft.placements); undone = []; redone = []; showUndo();
  framedFree = false; renderTray(); renderPlaced(); renderDesignControls();
  try {
    await rebuildLevel(false); await profileSync.flush();
    if (activeDesign?.id !== restoredDesign) return;
    designStatus(`Restored version ${v.number}.`);
  } catch (error) { if (activeDesign?.id === restoredDesign) designStatus('Restored locally, not synced: ' + error.message); }
});
window.machineDesign = () => activeDesign ? clone(activeDesign) : null;

async function rebuildLevel(start, {takeOver=false}={}) {
  const runInspection = start ? inspectedCircuit : null;
  // A rebuild still waiting to start would come after this one and undo it
  // (a Run pressed just after setting a piece down stayed unstarted).
  clearTimeout(rebuildTimer);
  keepBuild();
  scored = false; $('verdict').replaceChildren(); closeDone();
  try {
    const opened = await build(null, false, {op: 'level_open', level: level.id, ...sandboxRequest(), placements, helped,...(takeOver?{take_over:true}:{})});
    if (opened.session !== session) return;
    if(runInspection && contactCircuitRows.has(runInspection)) inspectContactCircuit(runInspection);
    // The chosen sandbox environment can supply appropriate tray defaults:
    // a river wheel starts without the separate falling-water feed.
    if (level.free && opened.level?.tray) {
      sandboxObjects=opened.sandbox_objects||[];
      level.tray = opened.level.tray;
      renderTray();
    }
    placedCost = (opened.placements || []).map(p => p.cost);
    placedEnergy = opened.energy || {};
    renderPlaced();
    renderDesignControls();
    // Its goal is about a piece not placed yet: shown, not run.
    if (opened.needs) $('verdict').textContent = opened.needs;
    else if (start && level.release_to_start) clockMessage('Ready · press Release spring beside the spring');
    else if (start) await setPlaying(true);
    if (!start) schedulePreview(200);
  } catch (e) {
    const problems = e.data && e.data.problems ? e.data.problems.join('; ') : e.message;
    $('verdict').textContent = problems;
    // Still show the level as it stands, without the pieces that do not fit.
    if (placements.length && e.status === 422)
      await build(null, false, {op: 'level_open', level: level.id, ...sandboxRequest(), placements: [], helped}).catch(() => {});
  }
}

function watchGoal(frame) {
  if (!LEVEL_MODE || !level || level.free || scored || !frame || !session || !(world.t > 0)) return;
  const row = (readouts.stations || [])[0];
  const timedFill=Boolean(level.goal?.station?.done_when?.water_in_zone_l);
  const deadlineReached=timedFill?world.t>=level.time_s:world.t>level.time_s+.3;
  if ((row && row.done) || deadlineReached) { scored = true; score(row).catch(() => {}); }
}

async function score(row) {
  const ran=session,sourceLevel=level;
  lastRun = {goal_at_s: row && row.done ? row.at_s : null, world_t: world.t,
             events: [...$('events').children].slice(0, 20).map(li => li.textContent),
             measurements:clone({stations:(readouts.stations||[]).slice(0,16),joints:(readouts.joints||[]).slice(0,32),
               electrical:readouts.electrical?{devices:(readouts.electrical.devices||[]).slice(0,32),wires:(readouts.electrical.wires||[]).slice(0,64)}:null,
               pour:readouts.pour||null,machines:readouts.machines?{
                 batteries:(readouts.machines.batteries||[]).slice(0,32),solar_panels:(readouts.machines.solar_panels||[]).slice(0,32),
                 motors:(readouts.machines.motors||[]).slice(0,32)}:null})};
  const r = await api({op: 'level_score', session:ran});
  if(session!==ran || level!==sourceLevel)return;
  const v = $('verdict'); v.replaceChildren();
  v.append(Object.assign(document.createElement('span'), {className: 'stars', textContent: '★'.repeat(r.stars) + '☆'.repeat(3 - r.stars)}));
  const said = [r.earned.goal ? `Goal at ${describeTime(r.goal_at_s)}, on ${energyText(r.energy_j)} (par ${energyText(r.par_energy_j)}).`
                              : `The goal did not happen within ${level.time_s} s.`];
  if (r.helped) said.push('The chat placed the pieces, so one star at most.');
  v.append(' ' + said.join(' '));
  // A run pulled by hand is a test: nothing is kept for it.
  const kept = r.tested ? {was: record(level.id), better: false, unlocked: []} : keepResult(level.id, r);
  renderLevels();
  showDone(r, kept);
  // The goal happened: let what follows settle for a moment, then stop.
  if (r.earned.goal) setTimeout(() => { if (session === ran && playing) setPlaying(false).catch(() => {}); }, 1500);
  else if(session===ran && playing){await setPlaying(false);v.textContent='';}
}

// How the run went, over the scene: on the goal, congratulations and on to
// the next level (by itself in a few seconds, unless the player stays);
// without it, a way to try again.
let advanceTimer = null;
// Back to the level's beginning, not running: with the same pieces (to move
// or change them) or with none.
function startOver(keep) {
  endGhost();
  if (!keep && (placements.length || (level.free && activeDesign?.draft.base))) remember();
  if (!keep && level.free && activeDesign) { activeDesign.draft.base = null; framedFree = false; }
  if (!keep) { placements = []; placedCost = []; placedEnergy = {}; helped = false; }
  renderTray(); renderPlaced();
  return rebuildLevel(false).then(() => {
    if (!$('verdict').textContent) $('verdict').textContent = keep
      ? 'Back to the start, with your pieces: pick one up to move or change it, then Try It!.'
      : 'Back to the start: add a piece from your tray.';
    sceneIntoView();
  });
}

function closeDone() {
  clearInterval(advanceTimer); advanceTimer = null;
  document.body.classList.remove('run-complete','scene-win');
  $('level-done').hidden = true; $('level-done').replaceChildren();
}
function showDone(r, kept = {was: {}, better: false, unlocked: []}) {
  closeDone();
  document.body.classList.toggle('run-complete',Boolean(r.earned.goal||r.tested));
  const box = $('level-done'), next = level.variant ? null : levels[levels.indexOf(level) + 1];
  const completedAll = levels.every(row=>bestStars(row.id)>0);
  selectPhonePanel('controls',true);
  if(!r.tested){view.append(box);box.classList.toggle('retry-result',!r.earned.goal);if(r.earned.goal){closeCoach();document.body.classList.add('scene-win');}}
  else {box.classList.remove('retry-result');$('control-panel').prepend(box);$('control-panel').scrollTop=0;}
  const add = (tag, props) => box.appendChild(Object.assign(document.createElement(tag), props));
  const allLevels = button('All levels', () => { closeDone(); showLevelsScreen(true); });
  const compareScore = () => {
    if (!Number.isFinite(r.energy_j) || !(r.par_energy_j > 0)) return;
    const summary = add('div', {id: 'level-done-score'});
    const line = (className, textContent) => summary.appendChild(Object.assign(document.createElement('p'), {className, textContent}));
    line('energy', `Energy used: ${energyText(r.energy_j)}`);
    // This is the authored three-star benchmark, not a theoretical minimum.
    line('score-target', `Perfect score target: ${energyText(r.par_energy_j)} or less.`);
    const over = r.energy_j - r.par_energy_j;
    line('score-margin', over > 0 ? `${energyText(over)} above target.` : 'Energy target met.');
  };
  if (r.tested) {
    // Pulled by hand: what happened, and that it is a test, not a win.
    add('h2', {textContent: 'A test run'});
    add('p', {textContent: r.earned.goal ? `With your pull, the goal happened at ${describeTime(r.goal_at_s)}.`
                                         : `With your pull, the goal did not happen within ${level.time_s} s.`});
    add('p', {className: 'hint', textContent: 'A run you pull by hand tests the parts. To win, let the machine do it: run it without pulling.'});
    compareScore();
    const actions = add('div', {className: 'actions'});
    actions.append(button('Play again', () => { closeDone(); startOver(true); }, {className: 'primary', ariaLabel: 'Play this level again'}),
                   allLevels);
  } else if (r.earned.goal) {
    // The win, and what it took: less energy is better.
    // A first win with a tool is an achievement; a win again is the level.
    const unlocked = (kept.unlocked || []).map(toolName);
    add('h2', {textContent: level.variant ? 'Challenge complete!' : completedAll ? 'You finished every level!' : 'Level Complete!'});
    box.append(button('×',closeDone,{className:'result-close',ariaLabel:'Close level complete'}));
    add('p', {className: 'stars', textContent: '★'.repeat(r.stars) + '☆'.repeat(3 - r.stars)});
    compareScore();
    // Keep the score comparison visible; the fabrication/run breakdown is optional.
    const how = button('ⓘ', () => {
      details.hidden = !details.hidden;
      how.setAttribute('aria-expanded', String(!details.hidden));
    }, {className: 'how-open',ariaLabel:'Energy details',title:'Energy details'});
    how.setAttribute('aria-expanded', 'false'); how.setAttribute('aria-controls', 'level-done-energy');
    box.appendChild(how);
    const details = add('div', {id: 'level-done-energy', className: 'how', hidden: true});
    const addHow = (tag, props) => details.appendChild(Object.assign(document.createElement(tag), props));
    if(unlocked.length){
      addHow('h3',{textContent:'Achievement Unlocked'});
      addHow('p',{className:'unlocked',textContent:`Your first win with ${unlocked.map(t=>(/^[aeiou]/.test(t)?'an ':'a ')+t).join(' and ')}!`});
    }
    const e = r.energy || {}, run = e.run || {};
    addHow('p', {className: 'breakdown', textContent: `${energyText(e.pieces_j)} to make your pieces, ` +
      (run.j ? `${energyText(run.j)} in the run` : 'nothing used in the run') + (run.j ? ` (${[['heat', run.heat_j], ['powder', run.powder_j],
      ['electricity', run.electric_j], ['water source', run.water_j], ['your pulls', run.pull_j]].filter(([, j]) => j).map(([w, j]) => `${w} ${energyText(j)}`).join(', ')})` : '') + '.'});
    const par = r.par_energy_j;
    const best = kept.was.energy_j != null
      ? (r.energy_j < kept.was.energy_j ? ' New personal best!' : ` Your best: ${energyText(kept.was.energy_j)}.`) : '';
    addHow('p', {textContent: `Goal at ${describeTime(r.goal_at_s)}.${best}`});
    // What each piece took, and how far from par: a piece made of the same
    // stuff takes energy in proportion to its weight.
    const pieces = Object.entries(e.pieces || {});
    if (pieces.length) addHow('p', {className: 'breakdown', textContent: pieces.map(([name, m]) =>
      `${name[0].toUpperCase() + name.slice(1)}: ${Number(Number(m.kg).toPrecision(3))} kg, ${energyText(m.j)}`).join('; ') + '.'});
    if (r.stars < 3) {
      const over = r.energy_j - par, heavy = pieces.sort((a, b) => b[1].j - a[1].j)[0];
      addHow('p', {className: 'hint', textContent: r.helped ? 'Place the pieces yourself for more stars.'
        : heavy && over > 0 && over < heavy[1].j
          ? `To reach par, take ${energyText(over)} off: ${heavy[0]} about ${Math.ceil(100 * over / heavy[1].j)}% lighter ` +
            '(shorter, smaller or a cheaper material) and still reaching the goal.'
          : 'Win on less energy for more stars: smaller or lighter pieces, cheaper materials, less fuel.'});
    }
    const actions = add('div', {className: 'actions'});
    if (next) actions.append(button('Next level ▶', () => { closeDone(); chooseLevel(next.id).catch(() => {}); },
                                    {className: 'primary', ariaLabel: 'Next level'}));
    actions.append(button('Play again', () => { closeDone(); startOver(true); }, {ariaLabel: 'Play this level again'}),
                   allLevels);
  } else {
    // Running the same pieces again does the same thing: start the level
    // over, with no pieces or with the same ones to change.
    const actions = add('div', {className: 'actions'});
    actions.append(button('Try again', async () => {
      const selected=lastEdited;closeDone();
      await startOver(true);
      if(placements[selected])pickUp(selected);
      else if(placements.length)pickUp(placements.length-1);
    }, {className: 'primary'}),button('Ask for Help',()=>askLevel('hint',{popup:true,
      message:'My last attempt did not reach the goal. Explain why using my setup and measured last run, and suggest one clear change I can try myself.'})));
  }
  box.hidden = false;
  sceneIntoView();
}

// ---- the levels screen: every level, and how far this player has got --------------------
function renderReturnLink(box) {
  for (const old of document.querySelectorAll('.visitor-return,.previous-saves')) old.remove();
  const line = document.createElement('div'); line.className = 'visitor-return';
  const link = document.createElement('a'); link.id = 'visitor-return-link'; link.href = returnURL(location.origin, save.current, APP_BASE); link.textContent = 'Your return link';
  const copy = button('Copy return link', async () => {
    try { await navigator.clipboard.writeText(link.href); status.textContent = 'Return link copied.'; }
    catch { status.textContent = 'Open the return link to copy its address.'; }
  }, {id:'copy-return-link'});
  const status = document.createElement('span'); status.className = 'visitor-return-status'; status.setAttribute('role','status');
  const sync = document.createElement('span'); sync.className = 'visitor-return-status profile-sync-status'; sync.setAttribute('role','status'); sync.textContent = profileStatus();
  line.append(link, copy); addSaveHelp(line,'About your return link'); line.append(status,sync); box.append(line);
  const others = Object.keys(save.players).filter(id => id !== save.current);
  if (others.length) {
    const previous = document.createElement('details'), summary = document.createElement('summary'); previous.className = 'previous-saves'; summary.textContent = 'Previous saves'; previous.append(summary);
    others.forEach((id, index) => { const a = document.createElement('a'); a.href = returnURL(location.origin, id, APP_BASE); a.textContent = `Saved profile ${index + 1}`; a.className = 'previous-save'; previous.append(a); });
    box.append(previous);
  }
}
function showLevelsScreen(show) {
  if(show){parkDesign();$('test-busy').hidden=true;}
  const box = $('levels-screen');
  box.hidden = !show;
  if (!show) for (const panel of box.querySelectorAll('.save-help-panel:popover-open')) panel.hidePopover();
  document.body.classList.toggle('on-levels', show);
  if (!show) { resize(); return; }
  stopSwitchDrag();
  box.replaceChildren();
  const add = (parent, tag, props) => parent.appendChild(Object.assign(document.createElement(tag), props));
  const head = add(box, 'div', {className: 'ls-head'});
  add(head, 'h1', {textContent: 'Levels'});
  if (level) head.append(button(`Back to ${levelTitle(level)}`, async () => {
    showLevelsScreen(false);
    history_.replaceState(null, '', level.free ? appPath('/machine') + '?design=' + encodeURIComponent(activeDesign.id) : appPath('/play') + '?level=' + level.id);
    await rebuildLevel(false);
  }));
  const more = createLevelMoreMenu(box,{id:'level-more'}).content;
  renderReturnLink(more);
  history_.replaceState(null, '', returnURL(location.origin, save.current, APP_BASE));
  updateHeaderShare();
  const won = levels.filter(l => bestStars(l.id) > 0).length, starsAll = levels.reduce((s, l) => s + bestStars(l.id), 0);
  const nextUp = levels.find(l => !bestStars(l.id));
  add(box, 'p', {className: 'ls-summary', textContent: `${won}/${levels.length} levels · ${starsAll} stars`});
  // The free build: no goal, every piece, kept for this player.
  if (freeLevel) {
    const free = button('', () => showSandboxScreen(), {className: 'ls-card ls-free', ariaLabel: 'Sandbox: build anything'});
    add(free, 'strong', {textContent: 'Sandbox'});
    add(free, 'span', {className: 'teaches', textContent: 'Your designs and examples'});
    box.append(free);
  }
  const freshStatus = add(more, 'p', {role: 'status'});
  if (me().freshChallenges?.length) {
    const recent = add(more, 'section', {className: 'chat-actions', ariaLabel: 'Recent challenges'});
    add(recent, 'h2', {textContent: 'Return to a challenge'});
    for (const saved of me().freshChallenges) recent.append(button(saved.title, () => chooseLevel(saved.id).catch(e => { freshStatus.textContent = e.message; })));
  }
  box.append(more.parentElement);
  const list = add(box, 'ol', {className: 'ls-list'});
  renderLevelCards(list,levels,{record,bestStars,energyText,pieceLabel,nextUp,
    onChoose:l=>{showLevelsScreen(false);chooseLevel(l.id).catch(()=>{});}});
}
$('levels-open').addEventListener('click', e => {
  if (!LEVEL_MODE || !levels.length) return;
  e.preventDefault(); keepBuild(); showSandboxScreen(false); showLevelsScreen(true);
});
// Looking around the scene while it counts down: stay, and look.
renderer.domElement.addEventListener('pointerdown', () => {
  if (!advanceTimer) return;
  clearInterval(advanceTimer); advanceTimer = null;
  const count = document.querySelector('#level-done .count');
  if (count) count.textContent = '';
});

async function chooseLevel(id, design = null) {
  closeLevelIntroduction();
  if($('run-help').open)$('run-help').close();
  closeCoach();
  if (!levels.some(l => l.id === id) && id.includes('--v')) {
    if (generatedLevel?.id !== id) {
      const match = /^(easy-[a-z-]+)--v\d+--([0-9a-f]{8})--(?:\d|c)$/.exec(id);
      if (!match) throw new Error('This challenge link is not supported.');
      $('page-loading').hidden = false;
      $('page-loading').textContent = 'Testing this shared challenge in the physics engine…';
      try {
        const r = await api({op:'easy_variant', family:match[1], seed:parseInt(match[2], 16), recipe:id});
        generatedLevel = r.level;
      } finally { $('page-loading').hidden = true; }
    }
  }
  if ($('piece-picker').open) $('piece-picker').close();
  document.querySelector('main').hidden = false;
  keepBuild(); showSandboxScreen(false); showLevelsScreen(false);
  level = id === 'free' && freeLevel ? {...freeLevel} : levels.find(l => l.id === id) || (generatedLevel?.id === id ? generatedLevel : levels[0]);
  $('reset').title = level.free ? 'Return your machine to time zero' : 'Start the level over; Undo recovers your pieces';
  $('phone-design-tab').textContent = 'Design';
  $('phone-design-tab').hidden = !level.free;
  $('sandbox-build-description').hidden = !level.free;
  const sectionPanel = $('phone-design-panel');
  sectionPanel.prepend($('title'), $('sandbox-controls'), $('game'));
  $('help-settings').querySelector('summary').after($('level-instructions'));$('level-instructions').hidden=Boolean(level.free);
  $('help-settings').append($('challenge-actions'),$('challenge-link'));
  $('phone-help-panel').append($('feedback'));
  $('level-details').hidden = Boolean(level.free);
  selectPhonePanel('controls');
  if (level.variant) {
    me().freshChallenges = [{id:level.id, title:levelTitle(level)}, ...(me().freshChallenges || []).filter(row => row.id !== level.id)].slice(0, 12);
    persist();
  }
  activeDesign = null;
  sandboxObjects=[];
  if (level.free) {
    const store = designStore();
    if (sharedBuild) {
      const shared = sharedBuild; sharedBuild = null;
      try { const draft = await unpackBuild(shared); design = newDesign(draft.name || 'Shared design', {base: draft.base, placements: draft.placements}); }
      catch { say('refused', 'That link does not hold a design this page can read.'); }
    }
    activeDesign = design || store.items.find(d => d.id === store.last) || store.items[0] || newDesign('Untitled design');
    store.last = activeDesign.id; persist();
  }
  endGhost(); gridSnapEnabled=true;objectSnapEnabled=true;lastEdited=null;closeDone(); previewAsk++; clearPreview(); resetLaserPreview();
  for(const id of ['grid-snap','object-snap'])$(id)?.setAttribute('aria-pressed','true');
  placements = []; placedCost = []; placedEnergy = {}; helped = false; lastRun = null; framedFree = false;
  undone = []; redone = []; showUndo(); cancelAttach();
  $('attach-tool').hidden = !level.free;
  history_.replaceState(null, '', level.free ? appPath('/machine') + '?design=' + encodeURIComponent(activeDesign.id) : appPath('/play') + '?level=' + level.id);
  $('title').textContent = levelTitle(level);
  $('brief').textContent = level.brief;
  const objectives={
    gap:'Bridge the gap with a plank so the marble reaches the cup.',
    cut:'Swing the knife through the cord and drop the weight into the bin.',
    fire:'Aim the cannon, wire its trigger, then drag the trigger to knock off the block.',
    steam:'Heat the boiler until its piston reaches the marked height.',
    chain:'Land the marble on the seesaw to close the switch and fire the cannon.',
    laser:'Bounce the laser around the wall to burn through the cord.',
    sun:'Aim the panel in sunlight and wire it to the winch to lift the load.',
    tackle:'Use a falling counterweight and pulleys to lift the crate.',
    'easy-power':'Set the battery voltage and connect both leads with suitable wire thickness.',
    'easy-solar':'Aim the panel in sunlight and connect its output to the battery input.',
    'easy-tackle':'Choose enough counterweight to lift the glass crate with the pulleys.',
    'easy-switch':'Place the switch, then drag its handle to close the lamp circuit.',
    'easy-bulb':'Choose a smaller bulb that the supply can power.',
    'easy-heat':'Clip the heater to the hanging cord, wire both leads and heat it to release the weight.',
    'easy-water-receiver':'Widen the tap to fill the waiting box with 3 L in 5 seconds.',
    'easy-spring':'Put the push plate below the box, compress the spring, then release its latch.',
    'easy-gears':'Size and place a gear between the powered wheel and the target wheel.',
    'easy-water-wheel':'Aim a separate tank at the paddles and open its tap.',
    'easy-water-gate':'Aim the tank at the wheel, open the tap and connect the drum to the gate.',
    'easy-divert-water':'Aim and tip the chute downhill to fill the separate container.',
    'easy-river-wheel':'Move the wheel’s lower paddles into the current.',
    'easy-charge-lift':'Aim the panel at the sun and connect Panel Out to Battery In.',
    'easy-marble-light':'Place the paddle so the marble presses its metal contact closed.',
    'advanced-resistor':'Reduce the series resistance until enough power reaches the lamp.',
    'advanced-parallel':'Wire both lamps in parallel with complete feeds and returns.',
    'advanced-capacitor':'Increase capacitance to store enough energy before time runs out.'};
  const objective=objectives[level.variant?.family||level.id]||level.brief.split(/(?<=\.)\s+(?=[A-Z])/)[0];
  introduction=levelIntroduction(level,{title:levelTitle(level),objective});
  $('scene-goal').replaceChildren(Object.assign(document.createElement('strong'),{textContent:level.free?activeDesign?.name||'Sandbox':levelTitle(level)}),Object.assign(document.createElement('span'),{textContent:level.free?'Build anything. Click a piece to adjust it.':objective}));
  $('pull-tool').hidden=true;$('restart-pieces').hidden=true;
  $('scene-goal').title = level.free ? 'Build anything' : `Goal within ${level.time_s} s`;
  $('goal-line').textContent = level.free
    ? 'No goal: build anything and run it.'
    : `Goal: ${level.goal.title.toLowerCase()} within ${level.time_s} s, on as little energy as you can `+
      `(par ${energyText(level.par_energy_j)}, pieces and run). It teaches ${pieceLabel(level.teaches)}.`;
  if (level.variant) $('goal-line').textContent += level.variant.fallback
    ? ' This seed uses the tested original setup because fresh candidates failed verification.'
    : ` Fresh setup: ${level.variant.parameter_label || level.variant.parameter.replaceAll('_', ' ')} = ${level.variant.value}.`;
  $('challenge-actions').hidden = Boolean(level.free);
  $('challenge-link').hidden = true;
  $('chat-log').replaceChildren();
  // On a level the chat hints and places the tray's pieces; in a free build
  // it builds what it is asked.
  $('free-actions').hidden = !level.free;
  $('solve').hidden = true;
  $('send').textContent = level.free ? 'Build it' : 'Ask for a hint';
  document.querySelector('.chat h2').textContent = level.free ? 'Build with words' : 'Ask for help';
  $('message').placeholder = level.free
    ? 'Say what to build, e.g. “Hold three marbles up high behind a gate, then split them three ways”'
    : 'Ask about this level, e.g. “Why does my ball fall short?”';
  $('share-link').hidden = true;
  if (level.free) {
    placements = clone(activeDesign.draft.placements);
    me().last = 'free'; persist();
  }
  renderDesignControls();
  $('engine-readings').hidden = $('engine-assumptions').hidden = !level.free;
  for (const label of ['Stations', 'Measured now', 'What happened'])
    document.querySelector(`aside section[aria-label="${label}"]`).hidden = !level.free;
  document.querySelector('#scene-actions .speed').hidden = !level.free;
  $('follow').hidden = !level.free;
  if (!level.free) { $('speed').value = '1'; follow = true; $('follow').setAttribute('aria-pressed', 'true'); }
  renderLevels(); renderTray(); renderPlaced();
  const openingLevel=level;
  updateHeaderShare();
  await rebuildLevel(false);
  if(level===openingLevel && session && !document.body.classList.contains('on-levels') && !document.body.classList.contains('on-sandbox'))showLevelIntroduction();
}

$('challenge-share').addEventListener('click', async () => {
  const link = $('challenge-link'); link.value = SHARE_SITE + '/play?level=' + encodeURIComponent(level.id);
  link.hidden = false; link.focus(); link.select();
  try { await navigator.clipboard.writeText(link.value); } catch { /* visible link remains available */ }
});
$('sandbox-build-description').addEventListener('click',()=>{selectPhonePanel('help',true);$('message').focus();});

// A free build's own buttons: clear the table, or set out the example.
$('free-clear').addEventListener('click', () => {
  if ((!placements.length && !activeDesign?.draft.base) || confirm('Take every piece and the base machine off the table? Saved versions are kept.')) {
    startOver(false);
  }
});
$('free-example').addEventListener('click', () => {
  if (!level || !level.example) return;
  if ((placements.length || activeDesign?.draft.base) && !confirm('Put the example on the table instead of your build? Saved versions are kept.')) return;
  endGhost(); remember(); activeDesign.draft.base = null; placements = level.example.map(p => ({...p})); renderTray(); renderPlaced();
  framedFree = false; rebuildLevel(false).catch(() => {});
});

// A free build from words: the model says which pieces and what each joins
// to, the server works out where they go and rehearses it once in the engine.
async function askFree() {
  const message = $('message').value.trim();
  if (!message) { $('message').focus(); return; }
  $('send').disabled = true;
  $('chat-status').textContent = 'Building it, then rehearsing it once in the engine (up to a minute)…';
  say('you', message);
  try {
    const r = await api({op: 'chat', level: 'free', ...sandboxRequest(), placements, message});
    say('model', r.reply);
    endGhost(); remember();
    placements = r.placements.map(p => ({...p}));
    renderTray(); renderPlaced();
    const ended = (r.rehearsal && r.rehearsal.ended) || [];
    if (ended.length) {
      const onPieces = ended.filter(e => e.on && e.on !== 'the ground');
      // A marble that opens a gate is spent on the floor: most on a piece is a build that works.
      say(2 * onPieces.length > ended.length ? 'model' : 'refused', `Rehearsed once in the engine: ${onPieces.length} of ${ended.length} ` +
        `marbles ended on a piece${onPieces.length ? ` (${[...new Set(onPieces.map(e => e.on))].join(', ')})` : ''}` +
        (onPieces.length < ended.length ? `, ${ended.length - onPieces.length} on the ground` : '') + '. Choose Try It! to watch, and move what needs moving.');
    }
    $('message').value = '';
    framedFree = false;
    await rebuildLevel(false);
  } catch (err) { say('refused', err.data && err.data.problems ? `${err.message}: ${err.data.problems.join('; ')}` : err.message); }
  finally { $('send').disabled = false; $('chat-status').textContent = ''; }
}

// ---- sharing a build: all of it in a link ------------------------------------------
let headerShareEpoch=0;
async function headerShareURL() {
  if(document.body.classList.contains('on-levels'))return SHARE_SITE+'/play';
  if(document.body.classList.contains('on-sandbox'))return SHARE_SITE+'/machine';
  if(level?.free && activeDesign)return SHARE_SITE+'/machine#build='+await packBuild({name:activeDesign.name,base:activeDesign.draft.base,placements});
  return SHARE_SITE+'/play'+(level?'?level='+encodeURIComponent(level.id):'');
}
function updateHeaderShare() {
  const epoch=++headerShareEpoch;
  headerShareURL().then(url=>{if(epoch===headerShareEpoch)$('header-share').href=url;}).catch(()=>{});
}
$('header-share').addEventListener('click',async e=>{
  if(e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||e.button!==0)return;
  e.preventDefault();
  const link=$('header-share');
  try {
    const url=await headerShareURL();link.href=url;
    await navigator.clipboard.writeText(url);
    link.textContent='Copied';link.title='Share link copied';
    setTimeout(()=>{link.textContent='Share';link.title='Copy a link to this setup';},2000);
  } catch {window.prompt('Copy this share link',link.href);}
});
// The pieces, squeezed (deflate) and written in the link's #build= -- which
// the browser never sends to a server. Opening the link sets them out.
let sharedBuild = (location.hash.match(/^#build=([A-Za-z0-9_-]+)$/) || [])[1] || null;
async function packBuild(list) {
  let bytes = new TextEncoder().encode(JSON.stringify(list)), tag = 'j';
  if (window.CompressionStream) {
    const squeezed = new Blob([bytes]).stream().pipeThrough(new CompressionStream('deflate-raw'));
    bytes = new Uint8Array(await new Response(squeezed).arrayBuffer()); tag = 'z';
  }
  let text = '';
  for (const b of bytes) text += String.fromCharCode(b);
  return tag + btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
async function unpackBuild(packed) {
  const b64 = packed.slice(1).replace(/-/g, '+').replace(/_/g, '/');
  const bytes = Uint8Array.from(atob(b64 + '='.repeat((4 - b64.length % 4) % 4)), c => c.charCodeAt(0));
  const json = packed[0] === 'z'
    ? await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).text()
    : new TextDecoder().decode(bytes);
  const parsed = JSON.parse(json);
  const draft = Array.isArray(parsed) ? {base: null, placements: parsed} : parsed;
  const list = draft?.placements;
  if (!Array.isArray(list) || list.length > 200 || !list.every(p => p && typeof p === 'object' && typeof p.piece === 'string'))
    throw new Error('not a build');
  if (draft.base != null && (typeof draft.base !== 'object' || draft.base.schema !== 'banjo.machine.v1')) throw new Error('not a machine');
  preserveLegacyWater(draft);
  return {base: draft.base || null, placements: list, name: typeof draft.name === 'string' ? draft.name.slice(0, 60) : 'Shared design'};
}
$('free-share').addEventListener('click', async () => {
  const link = `${SHARE_SITE}/machine#build=${await packBuild({name: activeDesign.name, base: activeDesign.draft.base, placements})}`;
  const box = $('share-link');
  box.hidden = false; box.value = link; box.select();
  let copied = false;
  try { await navigator.clipboard.writeText(link); copied = true; } catch { /* no clipboard: the link is shown to copy */ }
  $('verdict').textContent = copied ? 'Design link copied. Opening it creates a separate copy, including the base machine.'
    : 'Copy this design link. Opening it creates a separate copy, including the base machine.';
});
window.machineShareLink = () => $('header-share').href;
// A shared link opened in a tab already on the page changes only its #: the
// page is not loaded again, so the build is read from it here.
addEventListener('hashchange', () => {
  const m = location.hash.match(/^#build=([A-Za-z0-9_-]+)$/);
  if (m && LEVEL_MODE && freeLevel) { sharedBuild = m[1]; showLevelsScreen(false); chooseLevel('free').catch(() => {}); }
});

// Teaching annotations never dispatch input, edit placements or change physics.
let coach = null, coachRequest = 0, coachPaintAt = 0;
const coachSVG=document.createElementNS('http://www.w3.org/2000/svg','svg');
coachSVG.id='coach-overlay';coachSVG.setAttribute('aria-hidden','true');coachSVG.setAttribute('hidden','');
document.body.append(coachSVG);
function coachObjectBox(objects) {
  const bounds=new THREE.Box3();bounds.makeEmpty();
  for(const object of objects)if(object?.visible)bounds.expandByObject(object);
  if(bounds.isEmpty())return null;
  const r=view.getBoundingClientRect();let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
  for(let i=0;i<8;i++) {
    const p=new THREE.Vector3(i&1?bounds.max.x:bounds.min.x,i&2?bounds.max.y:bounds.min.y,i&4?bounds.max.z:bounds.min.z).project(camera);
    if(Math.abs(p.z)>1)return null;
    const x=r.left+(p.x+1)*r.width/2,y=r.top+(1-p.y)*r.height/2;
    x0=Math.min(x0,x);y0=Math.min(y0,y);x1=Math.max(x1,x);y1=Math.max(y1,y);
  }
  x0=Math.max(r.left+3,x0);y0=Math.max(r.top+3,y0);x1=Math.min(r.right-3,x1);y1=Math.min(r.bottom-3,y1);
  return x1>x0&&y1>y0?{x:x0,y:y0,width:x1-x0,height:y1-y0}:null;
}
function coachTargets() {
  const targets=new Map();
  const add=(id,label,box,at_m)=>targets.set(id,{id,label,box,...(at_m?{at_m}:{})});
  for(const id of ['start','reset','phone-controls-tab','tray-library','tray-prev','tray-next','adjustment-choice','piece-grip','wire-mode','undo-pieces',
    'view-in','view-out','view-left','view-right','view-up','view-down','heater-attach','piece-choice-toggle']) {
    const el=$(id);if(el?.checkVisibility()&&!el.disabled){
      let label=el.getAttribute('aria-label')||el.textContent.trim();
      if(id==='adjustment-choice')label='Adjust property; selected: '+el.selectedOptions[0]?.textContent+'; options: '+[...el.options].map(o=>o.textContent).join(', ');
      if(id==='piece-grip')label='Tap or drag the on-object handle to change '+$('adjustment-choice').selectedOptions[0]?.textContent+'; '+$('adjustment-feedback')?.textContent;
      if(id==='piece-choice-toggle')label+='; current value: '+el.textContent;
      add('control:'+id,label,()=>el.getBoundingClientRect());
    }
  }
  for(const [label,name] of [['Place','place'],['Move selected piece','move'],['Turn selected piece','turn']]) {
    const el=[...$('piece-editor').querySelectorAll('button')].find(b=>(b.getAttribute('aria-label')||b.textContent)===label);
    if(el?.checkVisibility()&&!el.disabled)add('control:'+name,label,()=>el.getBoundingClientRect());
  }
  const tray=$('tray-add');if(tray?.checkVisibility()&&!tray.disabled)add('tray:'+trayPiece,'Add '+pieceLabel(trayPiece),()=>tray.getBoundingClientRect());
  placements.forEach((p,i)=>{
    const prefix=`your ${p.piece} ${i+1}`,objects=[...meshes].filter(([n])=>n===prefix||n.startsWith(prefix+' ')).map(([,m])=>m);
    add('piece:'+i,pieceLabel(p.piece),()=>ghost?.index===i?coachObjectBox([ghostGroup]):coachObjectBox(objects),[p.x_m||0,p.height_m||p.top_height_m||.1,p.z_m||0]);
  });
  if(ghost)add('piece:'+ghost.index,'Selected '+pieceLabel(ghost.p.piece),()=>coachObjectBox([ghostGroup]),
    [ghost.p.x_m||0,ghost.p.height_m||ghost.p.top_height_m||.1,ghost.p.z_m||0]);
  for(const socket of sceneSockets())add('socket:'+socket.name,`${socket.label}: ${socket.name}`,()=>{
    const p=sceneSockets().find(p=>p.name===socket.name);return p?{x:p.x-16,y:p.y-16,width:32,height:32}:null;
  },socket.at);
  for(const [name,mesh] of meshes)if(!name.startsWith('your ')&&mesh.visible&&targets.size<95)
    add('part:'+name,(level.free?'Scene object: ':'Fixed apparatus: ')+name,()=>coachObjectBox([mesh]),mesh.position.toArray());
  return targets;
}
function closeCoach() {
  coachRequest++;
  if(coach){const strong=$('scene-goal').querySelector('strong'),span=$('scene-goal').querySelector(':scope > span');
    if(strong)strong.textContent=coach.title;if(span)span.textContent=coach.task;}
  coach=null;coachSVG.setAttribute('hidden','');coachSVG.replaceChildren();coachSVG.dataset.shape='';$('coach-open').disabled=false;
  document.body.classList.remove('coaching');
}
async function askCoach() {
  if(!level||$('coach-open').disabled)return;
  selectPhonePanel('controls',true);
  const strong=$('scene-goal').querySelector('strong'),span=$('scene-goal').querySelector(':scope > span');
  if(!coach)coach={title:strong.textContent,task:span.textContent,guide:null,reply:''};
  const token=++coachRequest,previous=coach.reply;coach.guide=null;coachSVG.setAttribute('hidden','');
  document.body.classList.add('coaching');$('coach-open').disabled=true;
  strong.replaceChildren(Object.assign(document.createElement('span'),{textContent:coach.title}));
  const actions=Object.assign(document.createElement('div'),{className:'coach-actions'});
  const next=button('Next hint',askCoach,{id:'coach-next',disabled:true});
  actions.append(next,button('Close',closeCoach,{id:'coach-close',ariaLabel:'Close guided help'}));strong.append(actions);
  span.setAttribute('aria-live','polite');span.textContent='Finding your next step…';
  const targets=[...coachTargets().values()].filter(t=>t.box()).map(({box,...t})=>t);
  try {
    const r=await api({op:'chat',mode:'coach',level:level.id,...sandboxRequest(),placements,last_run:lastRun,
      ui:{targets,editing:ghost?{index:ghost.index,p:ghost.p,fits:ghost.fits,mode:editorMode,adjustment:ghost.card}:null,previous_hint:previous}});
    if(token!==coachRequest||!coach)return;
    coach.reply=r.reply;coach.guide=r.guide;span.textContent=r.reply;
    if(!r.guide)span.textContent+=' Choose Next hint for a visual step.';
    // Reveal a dock control without scrolling the scene or the whole page.
    const target=coachTargets().get(r.guide?.target_id);
    if(target?.id.startsWith('control:')||target?.id.startsWith('tray:')) {
      const el=target.id.startsWith('tray:')?$('tray-add'):$(target.id.slice(8));
      if(el?.closest('.phone-pane'))el.scrollIntoView({block:'nearest'});
    }
  } catch(err) {if(token===coachRequest&&coach){span.textContent=err.message;coach.guide=null;}}
  finally {if(token===coachRequest){$('coach-open').disabled=false;next.disabled=false;}}
}
function paintCoachGuide() {
  if(!coach?.guide||$('view').closest('main').hidden){coachSVG.setAttribute('hidden','');return;}
  const now=performance.now();if(now-coachPaintAt<100)return;coachPaintAt=now;
  const targets=coachTargets(),box=targets.get(coach.guide.target_id)?.box();
  if(!box||box.width<1||box.height<1){coachSVG.setAttribute('hidden','');return;}
  coachSVG.removeAttribute('hidden');coachSVG.setAttribute('viewBox',`0 0 ${innerWidth} ${innerHeight}`);
  const make=(name,attrs)=>{const e=document.createElementNS(coachSVG.namespaceURI,name);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,String(v));return e;};
  const outline=make('rect',{x:box.x-3,y:box.y-3,width:box.width+6,height:box.height+6,rx:8,class:'coach-outline'});
  let end=targets.get(coach.guide.end_target_id)?.box();
  if(coach.guide.to_m){const r=view.getBoundingClientRect(),suggested=new THREE.Vector3(...coach.guide.to_m);
    // Demonstrate the editor's actual horizontal grab plane. Projecting the
    // proposed body's center directly would misplace a drag under perspective.
    if(ghost&&editorMode==='move'&&coach.guide.target_id==='piece:'+ghost.index) {
      const grab=slidePoint(box.x+box.width/2,box.y+box.height/2,ghostScreenBox()?.bottom||0);
      if(grab)suggested.copy(grab).add(new THREE.Vector3(coach.guide.to_m[0]-ghost.p.x_m,0,coach.guide.to_m[2]-(ghost.p.z_m||0)));
    }
    const p=suggested.project(camera);
    if(Math.abs(p.z)<=1){const x=r.left+(p.x+1)*r.width/2,y=r.top+(1-p.y)*r.height/2;
      if(x>=r.left&&x<=r.right&&y>=r.top&&y<=r.bottom)end={x,y,width:0,height:0};}}
  let x=box.x+box.width/2;let y=box.y+box.height/2;
  let destination=end?{x:end.x+end.width/2,y:end.y+end.height/2}:null;
  if(!destination&&coach.guide.gesture==='drag'&&coach.guide.target_id==='control:piece-grip') {
    const grip=$('piece-grip'),dx=Number(grip?.dataset.dx)||0,dy=Number(grip?.dataset.dy)||0;
    x-=12*dx;y-=12*dy;destination={x:x+24*dx,y:y+24*dy};
  }
  // Subpixel camera settling must not restart the pointer demonstration.
  const shape=JSON.stringify([box.x,box.y,box.width,box.height,...(destination?[destination.x,destination.y]:[])].map(Math.round));
  if(coachSVG.dataset.shape===shape)return;coachSVG.dataset.shape=shape;
  const items=[outline];
  if(destination){
    const path=`M${x} ${y} L${destination.x} ${destination.y}`;
    items.push(make('path',{d:path,class:'coach-path'}),make('circle',{cx:destination.x,cy:destination.y,r:9,class:'coach-destination'}));
    const dot=make('circle',{cx:0,cy:0,r:7,class:'coach-pointer'});
    // CSS animation uses a pointer dot; it never moves a simulated body.
    dot.style.offsetPath=`path('${path}')`;items.push(dot);
  }
  coachSVG.replaceChildren(...items);
}
$('coach-open').addEventListener('click',askCoach);
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&coach&&!document.querySelector('dialog[open]'))closeCoach();});

async function askLevel(mode, {popup=false,message:requestedMessage}={}) {
  if($('send').disabled)return;
  const requestLevel=level;
  const message = requestedMessage || $('message').value.trim() || (mode === 'hint' ? 'Give me a hint.' : 'Place the pieces for me.');
  if(popup){$('run-help-reply').textContent='Thinking about your last attempt…';$('run-help').showModal();$('run-help-dismiss').focus();}
  $('send').disabled = $('solve').disabled = true;
  $('chat-status').textContent = mode === 'hint' ? 'Thinking about your last run…' : 'Placing pieces from your tray, then rehearsing them once in the engine…';
  say('you', message);
  try {
    const r = await api({op: 'chat', level: level.id, ...(level.free&&activeDesign?.draft.base?{base:activeDesign.draft.base}:{}), placements, mode, message, last_run: lastRun,
      ui:{targets:[...coachTargets().values()].filter(t=>t.box()).map(({box,...t})=>t),
        editing:ghost?{index:ghost.index,p:ghost.p,fits:ghost.fits,mode:editorMode,adjustment:ghost.card}:null}});
    if(level!==requestLevel)return;
    say('model', r.reply);
    if(popup)$('run-help-reply').textContent=r.reply;
    if (mode === 'build' && Array.isArray(r.placements)) {
      endGhost(); remember();
      placements = r.placements.map(p => { const q = {...p}; delete q.cost; return q; });
      helped = true; renderTray(); renderPlaced();
      if (r.rehearsal && level.free) say(r.rehearsal.error?'refused':'model',r.rehearsal.error?`Engine check: ${r.rehearsal.error}`:'Built and checked in the engine. Choose Try It! to watch.');
      else if (r.rehearsal) say(r.rehearsal.manual_input_required || r.rehearsal.goal_at_s != null ? 'model' : 'refused', r.rehearsal.manual_input_required
        ? `Setup checked. ${r.rehearsal.manual_input_label || 'Drag the field handle'} to try the machine.` : r.rehearsal.goal_at_s != null
        ? `Rehearsed once in the engine: the goal happened at ${describeTime(r.rehearsal.goal_at_s)}.`
        : 'Rehearsed once in the engine: the goal did not happen. Try moving the pieces.');
      await rebuildLevel(false);
    }
    if(!requestedMessage)$('message').value = '';
  } catch (err) { if(level===requestLevel){say('refused', err.message);if(popup)$('run-help-reply').textContent=err.message;} }
  finally { $('send').disabled = $('solve').disabled = false; $('chat-status').textContent = ''; }
}
$('run-help-dismiss').addEventListener('click',()=>$('run-help').close());

// Reading overlays never navigate, rebuild a design or appear automatically.
for (const id of ['guide', 'recent-changes']) {
  const dialog = $(id), opener = $(id + '-open'), close = $(id + '-done');
  opener.addEventListener('click', e => {
    e.preventDefault();
    if (dialog.open) return;
    document.body.classList.add('reading-guide');
    dialog.showModal();
    close.focus({preventScroll: true});
  });
  close.addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    document.body.classList.remove('reading-guide');
    opener.focus({preventScroll: true});
  });
  dialog.addEventListener('click', e => {
    if (e.target !== dialog) return;
    const r = dialog.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) dialog.close();
  });
}

// What a player tells us: with the level and pieces it is about, to the
// server's log. Nothing that names them is sent.
let feedbackAttempt=null;
$('feedback-form').addEventListener('submit', async e => {
  e.preventDefault();
  const text = $('feedback-text').value.trim();
  if (!text) return;
  $('feedback-send').disabled = true;
  try {
    const base=level?.free?activeDesign?.draft.base||null:null;
    const fingerprint=JSON.stringify([text,level?.id,placements,base]);
    if(feedbackAttempt?.fingerprint!==fingerprint){
      const replay=level?.free?`${SHARE_SITE}/machine#build=${await packBuild({name:activeDesign.name,base,placements})}`:null;
      feedbackAttempt={fingerprint,request:{op:'feedback',report_id:crypto.randomUUID(),text,level:level?.id,
        placements:clone(placements),base:clone(base),last_run:clone(lastRun),world_t:world.t,replay_link:replay||'',
        screen:[innerWidth,innerHeight],touch:matchMedia('(pointer: coarse)').matches}};
    }
    const delivered=await api(feedbackAttempt.request);
    $('feedback-text').value = '';
    feedbackAttempt=null;
    $('feedback-status').textContent = delivered.delivery==='sent'?'Report sent to Linear.':'Report saved. Linear delivery is pending.';
    if(delivered.issue_url){const link=Object.assign(document.createElement('a'),{href:delivered.issue_url,textContent:'Open report',target:'_blank',rel:'noopener'});$('feedback-status').append(' ',link);}
  } catch (err) { $('feedback-status').textContent = err.message; }
  finally { $('feedback-send').disabled = false; }
});

let phonePanel = 'controls';
const phoneLayout = matchMedia('(max-width:820px), (max-height:500px) and (min-width:600px)');
function selectPhonePanel(name, focus = false) {
  if (name === 'design' && !level?.free) name = 'help';
  phonePanel = name;
  if (!$('phone-design-panel')) return;
  for (const [key,id] of [['controls','control-panel'],['design','phone-design-panel'],['help','phone-help-panel']]) {
    const tab = $('phone-'+key+'-tab'), pane = $(id), selected = key === name && !tab.hidden;
    tab.setAttribute('aria-selected',String(selected)); tab.tabIndex = selected ? 0 : -1;
    pane.hidden = !selected;
    if (selected && focus) tab.focus();
  }
}
function installPhonePanels() {
  document.body.classList.add('panel-tabs');
  const controls = $('control-panel'), aside = controls.parentElement;
  const design = Object.assign(document.createElement('section'),{id:'phone-design-panel'});
  const help = Object.assign(document.createElement('section'),{id:'phone-help-panel'});
  for (const node of [...aside.children]) {
    if (node === controls || node === $('phone-toolbar') || node === $('scene-goal')) continue;
    (node.matches('.chat') ? help : design).append(node);
  }
  aside.append(design,help);
  const settings=Object.assign(document.createElement('details'),{id:'help-settings'});
  const content=Object.assign(document.createElement('div'),{id:'help-settings-content'});
  const snapping=Object.assign(document.createElement('div'),{id:'snap-settings'});
  settings.append(Object.assign(document.createElement('summary'),{textContent:'Settings'}),snapping,content);
  for(const [id,label,read,write] of [
    ['grid-snap','Snap to grid',()=>gridSnapEnabled,v=>{gridSnapEnabled=v;if(ghost)ghost.gridLocks=null;}],
    ['object-snap','Snap to objects',()=>objectSnapEnabled,v=>{objectSnapEnabled=v;if(ghost){ghost.objectLock=null;ghost.joined=null;}}]
  ]){
    const b=button(label,()=>{write(!read());b.setAttribute('aria-pressed',String(read()));showGridSnap();},{id});
    b.setAttribute('aria-pressed',String(read()));snapping.append(b);
  }
  document.querySelector('#recent-changes .guide-body').prepend(settings);
  settings.addEventListener('click',e=>{
    const action=e.target.closest('button');
    if(action && (['attach-tool','pull-tool','focus-piece','view-overview','level-instructions'].includes(action.id)||action.closest('.move-pad')||action.textContent==='Square it up'))$('recent-changes').close();
  });
  $('challenge-share').hidden=true;$('free-share').hidden=true;
  controls.append($('scene-actions'),$('view-controls'));
  $('viewer-history').append($('undo-pieces'),$('redo-pieces'));
  $('viewer-zoom').prepend($('view-out'));$('viewer-zoom').append($('view-in'));
  for(const [id,plus] of [['view-out',false],['view-in',true]])$(id).innerHTML=`<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="9" r="6"/><path d="M14 14L21 21M6 9H12${plus?'M9 6V12':''}"/></svg>`;
  $('redo-pieces').textContent='Redo';
  $('viewer-perspective').prepend($('view-left'),$('view-right'));
  $('view-left').hidden=false;$('view-right').hidden=false;
  $('view-overview').hidden=true;$('focus-piece').hidden=true;
  const update = () => {
    const mobile = phoneLayout.matches;
    document.body.classList.toggle('phone-panels',mobile);
    $('phone-toolbar').hidden = false;
    $('phone-runbar').append($('start'),$('reset'));
    $('reset').textContent = 'Reset';
    $('reset').setAttribute('aria-label','Reset');
    $('reset').title = level?.free ? 'Return your machine to time zero' : 'Start the level over; Undo recovers your pieces';
    for (const [key,pane] of [['controls',controls],['design',design],['help',help]]) {
      pane.classList.add('phone-pane');
      pane.setAttribute('role','tabpanel'); pane.setAttribute('aria-labelledby','phone-'+key+'-tab'); pane.tabIndex = 0;
    }
    selectPhonePanel(phonePanel);
  };
  for (const key of ['controls','design','help']) $('phone-'+key+'-tab').addEventListener('click',()=>{if(document.body.classList.contains('scene-win'))closeDone();selectPhonePanel(key);});
  $('phone-tabs').addEventListener('keydown',e=>{
    const names=level?.free?['controls','design','help']:['controls','help'], index=names.indexOf(phonePanel);
    const next=e.key==='Home'?0:e.key==='End'?names.length-1:e.key==='ArrowRight'?(index+1)%names.length:e.key==='ArrowLeft'?(index+names.length-1)%names.length:null;
    if(next!==null){e.preventDefault();e.stopPropagation();selectPhonePanel(names[next],true);}
  });
  phoneLayout.addEventListener('change',update); update();
}

async function startGame() {
  document.body.classList.add('playing-level');
  // A level plays at real time, the camera following what moves, its path
  // shown: the sandbox's switches for those are not on the game page.
  for (const id of ['follow', 'path-toggle']) $(id).hidden = true;
  for (const id of ['undo-pieces', 'redo-pieces']) $(id).hidden = false;
  document.querySelector('#scene-actions .speed').hidden = true;
  // What the player works with, together at the top of the scene: the
  // Running, viewing and piece editing share the adjacent control panel.
  const controls = $('control-panel');
  controls.append($('preview-legend'));
  controls.prepend($('scene-tray'), $('scene-actions'));
  $('view-controls').before($('flow-preview'));
  $('view-zoom').addEventListener('input',()=>{distance=40*Math.pow(.01,Number($('view-zoom').value)/100);follow=false;$('follow').setAttribute('aria-pressed','false');freshView();});
  controls.append($('machine-controls'));
  installPhonePanels();
  // Browser scroll-to-target must leave secondary buttons below this sticky
  // module, including when its prediction timeline changes its height.
  new ResizeObserver(() => controls.parentElement.style.setProperty('--control-height',`${controls.offsetHeight+8}px`)).observe(controls);
  for (const [id, change] of [
    ['view-left', () => { azimuth -= .2; }], ['view-right', () => { azimuth += .2; }],
    ['view-up', () => { elevation=Math.min(1.45,elevation+.15); }], ['view-down', () => { elevation=Math.max(.08,elevation-.15); }],
    ['view-in', () => { distance = Math.max(.4, distance / 1.2); }], ['view-out', () => { distance = Math.min(40, distance * 1.2); }]
  ]) $(id).addEventListener('click',()=>{follow=false;$('follow').setAttribute('aria-pressed','false');change();freshView();});
  for(const id of ['view-in','view-out'])repeatOnHold($(id),()=>{follow=false;$('follow').setAttribute('aria-pressed','false');distance=Math.max(.4,Math.min(40,distance*(id==='view-in'?1/1.2:1.2)));freshView();});
  $('scene-note').textContent = 'Drag a ghost to move · Drag empty space to turn · Wheel or trackpad pinch to zoom';
  $('game').hidden = false; $('solve').hidden = true; $('undo').hidden = true;
  document.querySelector('.lede').hidden = true;
  for (const d of document.querySelectorAll('aside details:not(#feedback):not(#solar-load-help):not(#help-settings)')) d.hidden = true;
  // The levels have their own screen, and the engine's readings are the
  // sandbox's: a player sees the scene, the goal and the result.
  $('levels').hidden = true;
  for (const label of ['Stations', 'Measured now', 'What happened']) {
    const part = document.querySelector(`aside section[aria-label="${label}"]`);
    if (part) part.hidden = true;
  }
  await openAnonymousProfile();
  const r = await api({op: 'levels'});
  levels = r.levels; freeLevel = r.free || null; sandboxBase = r.sandbox_base; sandboxTemplates = r.sandbox || [];
  // Browse first. A landing page does not build a world or replace /play
  // with the last puzzle's URL before the player chooses a level.
  $('page-loading').hidden = true;
  if (location.pathname === appPath('/machine')) {
    if (params.has('design') || sharedBuild) {
      const d = designStore().items.find(d => d.id === params.get('design'));
      await chooseLevel('free', d);
    } else showSandboxScreen();
  } else {
    if (params.get('level')) await chooseLevel(params.get('level'));
    else showLevelsScreen(true);
  }
}
// The scene in sight: on a phone the panel below it (the tray, Try It!) is a
// scroll away, and what happens -- a ghost, a run, how it went -- is up here.
function sceneIntoView() {
  const seen = view.getBoundingClientRect();
  if (seen.top < -40 || seen.bottom > innerHeight + 40) view.scrollIntoView({block: 'start'});
}

// Checkpoints contain placed pieces, rather than an uncommitted adjustment.
function ghostInTheWay() {
  if (!ghost) return false;
  const said = `Set your ${ghost.p.piece} down first (or cancel it): a ghost is not part of the machine yet.`;
  $('verdict').textContent = said;
  const bar = document.querySelector('#ghost-bar .state');
  if (bar) { bar.className = 'state refused'; bar.textContent = said; }
  return true;
}
// A level's one button, over the scene: Try It! builds the level afresh with
// the pieces and plays it; while it plays it pauses, then continues; after
// the run, Try It!.
let startingRun = false;
async function runLevel() {
  const failed = e => { clockMessage(e.message); };
  if (startingRun || rewiringBusy) return;
  startingRun = true;
  try {
    if (playing) { await setPlaying(false); return; }
    if (ghost) {
      const g = ghost, sourceLevel = level;
      // Edits queue another check; wait for the latest answer, not an older
      // blue ghost. Cancelling or selecting another piece cancels this run.
      while (ghost === g && g.busy) await g.check;
      if (ghost !== g || level !== sourceLevel) return;
      if (!placeGhost()) {
        selectPhonePanel('controls'); showGhostState();
        $('verdict').textContent = g.problems.join('; ') || 'This piece is not ready to place.';
        return;
      }
      // Place and start in one rebuild, so a delayed setup cannot stop it.
      sceneIntoView(); await rebuildLevel(true); return;
    }
    if (session && liveControlPending && !scored) {
      await liveControlRequest; liveControlPending = false; await setPlaying(true);
      $('machine-control-status').textContent = 'Applied while running. Set up again restores the initial controls.';
      return;
    }
    if (session && world.t > 0 && !scored) { await setPlaying(true); return; }
    sceneIntoView(); await rebuildLevel(true);
  } catch (e) { failed(e); }
  finally {
    startingRun = false;
  }
}
$('solve').addEventListener('click', () => askLevel('build'));

// Leaving the page: the server is told at once, so its world makes room for
// someone else instead of waiting to notice that the page has gone quiet.
addEventListener('pagehide', () => {
  keepBuild();
  if (profileSync.state().ready) profileSync.flush().catch(() => {});
  if (session) navigator.sendBeacon(appPath('/api/machine'), new Blob([JSON.stringify({op: 'close', session})], {type: 'application/json'}));
});

const history_ = window.history;
// Navigation can wrap on small screens. Subtract its measured height so the
// scene and control pane still fit the viewport, including after rotation.
new ResizeObserver(() => {
  document.documentElement.style.setProperty('--site-header-height', `${document.querySelector('header').offsetHeight}px`);
  resize();
}).observe(document.querySelector('header'));
new ResizeObserver(resize).observe(view);
resize(); render();
if (LEVEL_MODE) startGame().catch(e => {
  $('page-loading').hidden = false;
  $('page-loading').textContent = 'Could not load Banjo: ' + e.message + '. Reload to try again.';
});
else fetch(appPath('/machine-default.json')).then(r => r.json()).then(d => build(d)).catch(e => { clockMessage('Could not load the machine: ' + e.message); });
