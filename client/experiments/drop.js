import * as THREE from './three.module.js';
import {describeObservation} from './drop-observation.js';
const $=id=>document.getElementById(id);
for(const id of ['sheet','ball'])for(const name of ['iron','aluminum','glass','ceramic','oak','rubber','ice','concrete']){
  const option=document.createElement('option');option.value=name;option.textContent=name==='oak'?'oak · laboratory':name;$(id).append(option);
}
$('sheet').value='glass';$('ball').value='iron';
const canvas=$('view'),renderer=new THREE.WebGLRenderer({canvas,antialias:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));
function makeScene(){
  const scene=new THREE.Scene();scene.background=new THREE.Color(0x101923);
  scene.add(new THREE.HemisphereLight(0xffffff,0x50677b,2));
  const sun=new THREE.DirectionalLight(0xffffff,3);sun.position.set(3,8,5);scene.add(sun);
  const floor=new THREE.Mesh(new THREE.BoxGeometry(4,.1,4),new THREE.MeshStandardMaterial({color:0x34495a}));floor.name='floor';floor.position.y=-.05;scene.add(floor);
  const grid=new THREE.GridHelper(4,20,0x788997,0x4e6070);grid.name='grid';grid.position.y=.0001;scene.add(grid);return scene;
}
const scene=makeScene(),beforeScene=makeScene(),meshes=new Map(),beforeMeshes=new Map();
const camera=new THREE.PerspectiveCamera(45,1,.002,100);
let state=null,before=null,session=null,busy=false,running=false,closed=false,view='overview';
let yaw=.7,pitch=.45,distance=18,target=new THREE.Vector3(0,5,0),drag=null;
const receipts=[];
function message(text){$('message').textContent=text;}
function frame(){
  const rect=canvas.getBoundingClientRect();renderer.setSize(rect.width,rect.height,false);
  camera.aspect=rect.width/2/rect.height;camera.updateProjectionMatrix();
  if(view==='follow'){const ball=state?.report.objects?.find(o=>o.id===2);if(ball)target.fromArray(ball.position_m);}
  camera.position.copy(target).add(new THREE.Vector3(Math.sin(yaw)*Math.cos(pitch),Math.sin(pitch),Math.cos(yaw)*Math.cos(pitch)).multiplyScalar(distance));camera.lookAt(target);
  renderer.setScissorTest(true);
  renderer.setViewport(0,0,rect.width/2,rect.height);renderer.setScissor(0,0,rect.width/2,rect.height);renderer.render(beforeScene,camera);
  renderer.setViewport(rect.width/2,0,rect.width/2,rect.height);renderer.setScissor(rect.width/2,0,rect.width/2,rect.height);renderer.render(scene,camera);
  renderer.setScissorTest(false);requestAnimationFrame(frame);
}
function setView(value){
  view=value;
  if(state?.report.experiment==='water-wheel'){target.set(0,1,0);distance=value==='impact'?2:3.5;return;}
  const ball=state?.report.objects?.find(o=>o.id===2);
  if(value==='overview'){target.set(0,ball?Math.max(.6,ball.position_m[1]/2):5,0);distance=Math.max(2,ball?ball.position_m[1]*1.65:18);}
  else{target.set(0,.54,0);distance=value==='follow'?.9:.75;}
}
for(const id of ['overview','impact','follow'])$(id).onclick=()=>setView(id);
canvas.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY};canvas.setPointerCapture(e.pointerId);});
canvas.addEventListener('pointermove',e=>{if(!drag)return;yaw+=(e.clientX-drag.x)*.006;pitch=Math.max(.04,Math.min(1.5,pitch+(e.clientY-drag.y)*.006));drag={x:e.clientX,y:e.clientY};});
canvas.addEventListener('pointerup',()=>{drag=null;});canvas.addEventListener('pointercancel',()=>{drag=null;});
canvas.addEventListener('wheel',e=>{e.preventDefault();distance=Math.max(.15,Math.min(35,distance*Math.exp(e.deltaY*.001)));},{passive:false});
function clearMeshes(map,owner){for(const mesh of map.values()){owner.remove(mesh);mesh.geometry.dispose();mesh.material.dispose();}map.clear();}
function draw(value,map,owner){
  for(const i of value.instances){let mesh=map.get(i.element_id);
    if(!mesh){const color=i.material==='water'?0x4aafff:value.report.experiment==='water-wheel'?(i.object_id===1&&i.element_id===2?0xffd565:i.material==='oak'?0xa87945:0x889baa):i.object_id===1?0x68bbd2:i.object_id===2?0xdab467:0x889baa;
      mesh=new THREE.Mesh(i.shape==='box'?new THREE.BoxGeometry(...i.dimensions_m):new THREE.SphereGeometry(i.radius_m,12,8),new THREE.MeshStandardMaterial({color,roughness:.5,metalness:i.material==='iron'?.5:0}));map.set(i.element_id,mesh);owner.add(mesh);}
    mesh.position.fromArray(i.position_m);const q=i.orientation_wxyz;mesh.quaternion.set(q[1],q[2],q[3],q[0]);
    if(value.report.objects?.find(o=>o.id===i.object_id)?.components>1)mesh.material.color.setHSL((i.component_id*.61803398875)%1,.65,.6);
  }
}
function update(value){
  state=value;draw(value,meshes,scene);const r=value.report;let rows;
  if(r.experiment==='water-wheel'){
    rows=[['Native time',r.elapsed_s.toFixed(3)+' s'],['Wheel rotation',(r.wheel_angle_rad*180/Math.PI).toFixed(1)+'°'],['Wheel rate',r.wheel_rate_rad_s.toFixed(2)+' rad/s'],['Wheel energy',r.wheel_kinetic_energy_j.toFixed(3)+' J'],['Wheel mass',r.wheel_mass_kg.toFixed(2)+' kg'],['Water parcels',r.water_particles],['Water mass',r.water_mass_kg.toFixed(3)+' kg'],['Peak density',r.maximum_density_kg_m3.toFixed(0)+' kg/m³'],['Unclosed energy',r.unseparated_energy_change_j.toFixed(3)+' J'],['Last tick',r.performance.step_max_ms.toFixed(1)+' ms']];
    $('gate').textContent='Experimental fluid / rigid contact · qualification pending';
  }else{
    const s=r.objects.find(o=>o.id===1),b=r.objects.find(o=>o.id===2);
    rows=[['Native time',r.elapsed_s.toFixed(4)+' s'],['Ball mass',b.mass_kg.toFixed(3)+' kg'],['Ball speed',Math.hypot(...b.velocity_m_s).toFixed(2)+' m/s'],['Sheet bonds broken',s.broken_links],['Ball bonds broken',b.broken_links],['Sheet components',s.components],['Ball components',b.components],['Plastic work',(s.plastic_work_j+b.plastic_work_j).toExponential(2)+' J'],['Native cells',r.cells],['Unclosed energy',r.unseparated_energy_change_j.toFixed(3)+' J'],['Last tick',r.performance.step_max_ms.toFixed(1)+' ms'],['Refused bond updates',r.reaction_reconstruction.inadmissible_bond_updates]];
    $('gate').textContent=!r.state_valid?'Material state incomplete · refused bond updates':value.declaration.mode==='rigid'?'Rigid baseline · no deformation or fracture':'Deformable experiment · material qualification pending';
  }
  $('metrics').replaceChildren(...rows.map(([name,value])=>{const row=document.createElement('div');row.className='metric';const key=document.createElement('span'),v=document.createElement('strong');key.textContent=name;v.textContent=value;row.append(key,v);return row;}));
  $('after-label').textContent='After · '+r.elapsed_s.toFixed(4)+' s native time';$('observation').textContent=describeObservation(before,state);
}
async function request(command){
  const response=await fetch('/api/drop',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(command)});const result=await response.json();
  receipts.push({request:command,receipt:result});if(!response.ok)throw Error(result.error||'Native request failed');if(result.state)update(result.state);if(!result.ok)throw Error(result.error);return result;
}
async function prepare(){
  if(busy)return;busy=true;running=false;
  try{
    if(session){await request({op:'close',session});session=null;}
    clearMeshes(meshes,scene);clearMeshes(beforeMeshes,beforeScene);before=null;receipts.length=0;
    const wheel=$('experiment').value==='water-wheel';
    for(const owner of [scene,beforeScene])for(const name of ['floor','grid']){const item=owner.getObjectByName(name);item.scale.x=item.scale.z=wheel?1.5:1;}
    const command=wheel?{op:'create',experiment:'water-wheel',paddle:$('paddle').value,water:$('jet').value!=='dry',offset_m:$('jet').value==='dry'?.36:Number($('jet').value)}:
      {op:'create',sheet:$('sheet').value,ball:$('ball').value,mode:$('mode').value,mass_kg:Number($('mass').value),height_m:Number($('height').value),speed_m_s:Number($('speed').value),offset_m:Number($('offset').value)};
    const result=await request(command);session=result.session;closed=false;before=structuredClone(state);draw(before,beforeMeshes,beforeScene);update(state);
    setView(!wheel&&$('height').value==='0'?'impact':'overview');message('Ready · before state captured. Release or advance one native batch.');
  }catch(e){message(e.message);}finally{busy=false;}
}
async function advance(){
  if(busy||!session||closed)return;busy=true;const started=performance.now();
  try{
    message('Computing native physics…');await request({op:'advance',session});message('Live observation · '+((performance.now()-started)/1000).toFixed(2)+' s wall time');
    if(state.report.ticks>=12000||state.report.elapsed_s>=state.report.observation_duration_s-1e-9){closed=true;running=false;message('Declared observation complete. Compare the result or reset for another experiment.');}
    if(!state.report.state_valid){running=false;message('Paused: native updates refused. Inspect the observed log.');}
  }catch(e){running=false;message(e.message);}finally{busy=false;}
}
async function loop(){while(running&&!closed){await advance();await new Promise(resolve=>setTimeout(resolve,state?.report.experiment==='water-wheel'?16:$('mode').value==='rigid'?16:0));}}
$('prepare').onclick=prepare;
$('run').onclick=()=>{if(!session){message('Prepare the world first.');return;}if(!running&&!busy){running=true;loop();}};
$('pause').onclick=()=>{running=false;message('Pausing after the current bounded native batch.');};$('step').onclick=()=>{running=false;advance();};
$('experiment').onchange=()=>{running=false;const wheel=$('experiment').value==='water-wheel';$('wheel-controls').hidden=!wheel;$('drop-controls').hidden=wheel;message('Prepare again to load the selected experiment.');};
$('mode').onchange=()=>{running=false;if($('mode').value==='deformable'){$('height').value='0';$('speed').value='14';}message('Prepare again. Contact + 14 m/s is an explicit short impact experiment, with slow deformable solving.');};
$('download').onclick=()=>{const url=URL.createObjectURL(new Blob([receipts.map(r=>JSON.stringify(r)).join('\n')],{type:'application/x-ndjson'}));const a=document.createElement('a');a.href=url;a.download='banjo-drop-observations.jsonl';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
if(new URLSearchParams(location.search).get('experiment')==='water-wheel'){$('experiment').value='water-wheel';$('wheel-controls').hidden=false;$('drop-controls').hidden=true;}
frame();prepare();
