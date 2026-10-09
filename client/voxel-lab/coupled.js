import * as THREE from '/three.module.js';
import {requestScene,runSceneSteps} from '/scene-session.mjs';
import {ballObservation,cameraFrame,settingsDiffer,remainingSteps,computePace,dropMilestones} from '/coupled-view.mjs';
const $=id=>document.getElementById(id),view=$('view');
const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));view.append(renderer.domElement);
renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFShadowMap;
const scene=new THREE.Scene();scene.background=new THREE.Color('#101d26');scene.add(new THREE.HemisphereLight(0xf0f6ff,0x253c48,2));
const light=new THREE.DirectionalLight(0xffffff,3);light.position.set(.2,.4,.3);scene.add(light);
light.castShadow=true;light.shadow.mapSize.set(1024,1024);Object.assign(light.shadow.camera,{left:-.18,right:.18,top:.18,bottom:-.18,near:.001,far:2});light.shadow.bias=-.00001;
const camera=new THREE.PerspectiveCamera(40,1,.0001,100),meshes=[];
let yaw=.5,pitch=.55,radius=.15,target=new THREE.Vector3(0,.025,0),drag=null,session=null,state=null,initial=null,busy=false,showBefore=false,showImpact=false,impactFrame=null,hash=null;
let backend='cupy-implicit-body',endpoint='/api/coupled',backendLabel='CUDA';
let cameraMode='target',setupPending=false,stopRequested=false,runningAction=false;
const colors={glass:0x8fd1e9,oak:0xb0875c,iron:0x9ba8b7,ice:0xcbeafa};
function cameraPose(){const r=radius*Math.max(1,1.3/camera.aspect);camera.far=Math.max(100,r*4);camera.updateProjectionMatrix();camera.position.copy(target).add(new THREE.Vector3(Math.sin(yaw)*Math.cos(pitch)*r,Math.sin(pitch)*r,Math.cos(yaw)*Math.cos(pitch)*r));camera.lookAt(target);}
function shownState(){return showImpact?impactFrame:showBefore?initial:state;}
function frameView(mode,s=shownState()){if(!s)return;cameraMode=mode;const f=cameraFrame(s.cells,mode);target.fromArray(f.center);radius=f.radius;cameraPose();for(const m of ['target','ball','overview'])$('focus-'+m).setAttribute('aria-pressed',String(m===mode));}
function updateMarkers(){const s=shownState();if(!s)return;const o=ballObservation(s);for(const [id,position,label] of [['ball-marker',o.ball.position_m,'○ Ball'],['target-marker',cameraFrame(s.cells,'target').center,'□ Target']]){const p=new THREE.Vector3(...position).project(camera),marker=$(id);marker.hidden=cameraMode!=='overview'||p.z<-1||p.z>1||Math.abs(p.x)>1||Math.abs(p.y)>1;if(!marker.hidden){marker.style.left=((p.x+1)*view.clientWidth/2)+'px';marker.style.top=((1-p.y)*view.clientHeight/2)+'px';marker.textContent=label+' · actual position';}}}
new ResizeObserver(()=>{renderer.setSize(view.clientWidth,view.clientHeight);camera.aspect=view.clientWidth/view.clientHeight;camera.updateProjectionMatrix();cameraPose();}).observe(view);
renderer.domElement.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY};renderer.domElement.setPointerCapture(e.pointerId);});
for(const name of ['pointerup','pointercancel'])renderer.domElement.addEventListener(name,()=>drag=null);
renderer.domElement.addEventListener('pointermove',e=>{if(!drag)return;yaw-=(e.clientX-drag.x)*.006;pitch=Math.max(-.25,Math.min(1.4,pitch+(e.clientY-drag.y)*.006));drag={x:e.clientX,y:e.clientY};cameraPose();});
renderer.domElement.addEventListener('wheel',e=>{e.preventDefault();radius=Math.max(.04,Math.min(30,radius*Math.exp(e.deltaY*.001)));cameraPose();},{passive:false});
function build(s){for(const m of meshes){scene.remove(m);m.geometry.dispose();m.material.dispose();}meshes.length=0;
  for(const c of s.cells){const geometry=c.shape==='sphere'?new THREE.SphereGeometry(c.radius_m,24,16):c.shape==='plane'?new THREE.BoxGeometry(.3,.001,.3):new THREE.BoxGeometry(...c.size_m);
    const m=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color:c.shape==='plane'?0x223640:colors[c.material],roughness:.55,metalness:c.material==='iron'?.3:0}));
    m.castShadow=c.shape!=='plane';m.receiveShadow=true;if(c.shape==='cube')m.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry),new THREE.LineBasicMaterial({color:0x294552})));scene.add(m);meshes.push(m);}
  frameView(s.declaration.experiment==='freefall'?'overview':'target',s);
}
function display(){const shown=showImpact?impactFrame:showBefore?initial:state;if(!shown)return;
  for(const [i,c] of shown.cells.entries()){const m=meshes[i],q=c.quaternion_wxyz;m.position.fromArray(c.position_m);if(c.shape==='plane')m.position.y-=.0005;m.quaternion.set(q[1],q[2],q[3],q[0]);}
  const o=ballObservation(shown);if(cameraMode==='ball'){target.fromArray(o.ball.position_m);cameraPose();}
  $('drop-progress').textContent='Shown time '+shown.time_s.toFixed(4)+' s · Ball gap '+(o.contact?'Contact':o.gap_m>=.001?o.gap_m.toFixed(3)+' m':(o.gap_m*1e6).toFixed(3)+' µm')+' · '+(o.down_m_s>=0?'Falling ':'Rising ')+Math.abs(o.down_m_s).toFixed(3)+' m/s. '+(o.contact?'Ball touches a surface.': 'Gravity-only contact estimate: '+o.gravity_estimate_s.toFixed(3)+' s remaining.')+(cameraMode==='target'&&o.gap_m>.2?' Use Follow ball or Full drop to see the ball.':'');
  $('before').textContent=showBefore?'Live':'Before';$('inspect').textContent=showImpact?'Live':'Inspect ball contact';$('scene-note').lastChild.textContent=showImpact?'Ball contact view · Accepted '+impactFrame.time_s.toFixed(7)+' s · Geometric overlap '+(impactFrame.compression_m*1e6).toFixed(3)+' µm':showBefore?'Before · Accepted '+initial.time_s.toFixed(5)+' s · Actual scale':state.declaration.experiment==='freefall'?'Normal-contact control · Actual scale · Accepted physics only':'10 mm finite cells · Actual scale · Accepted physics only';
}
function pair(name,value,target=$('results')){const row=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=name;dd.textContent=value;row.append(dt,dd);target.append(row);}
let selectedObject=null;
function showObjects(s){
  $('object-list').replaceChildren();
  const objects=s.objects?.objects??[];
  if(!objects.some(o=>o.instance_id===selectedObject))selectedObject=objects.find(o=>o.label==='Sheet')?.instance_id??objects.at(-1)?.instance_id;
  for(const o of objects){const button=document.createElement('button');button.textContent=o.label+' · '+o.matter_count;button.setAttribute('aria-pressed',String(o.instance_id===selectedObject));button.addEventListener('click',()=>{selectedObject=o.instance_id;showObjects(state);});$('object-list').append(button);}
  const object=objects.find(o=>o.instance_id===selectedObject);$('object-info').replaceChildren();
  for(const [i,m] of meshes.entries())m.material.emissive.setHex(object?.body_ids.includes(i)?0x102c25:0);
  if(!object)return;
  const target=$('object-info');pair('Parts',object.matter_count,target);pair('Interfaces',object.interface_count,target);
  pair('Material mass',object.material_mass_kg===null?'External boundary':(object.material_mass_kg*1000).toFixed(2)+' g',target);
  pair('Occupied volume',object.occupied_volume_m3===null?'Infinite boundary':(object.occupied_volume_m3*1e6).toFixed(2)+' cm³',target);
  pair('Representation',object.family==='detailed-solid'?'Connected rigid cells':'Rigid primitive',target);
  pair('Solver owner',object.prescribed?'Prescribed boundary':object.solver_binding==='isolated-rigid-flight'?'Independent flight':'Coupled world',target);
  pair('Definition',object.definition_sha256.slice(0,12),target);pair('Accepted time',s.time_s.toFixed(5)+' s',target);
}
function refusalSummary(f){const counts={};for(const r of f.subdivision_refusals||[])counts[r.error]=(counts[r.error]||0)+1;
  const n=f.last_solver_failure,last=n?.iterations?.at(-1);
  return {stopped_by:f.error,accepted_time_s:f.accepted_time_s,interval_rolled_back:f.interval_rolled_back,
    contact_timestep_policy:f.contact_timestep_policy,last_contact_schedule:f.last_contact_schedule,private_elapsed_s:f.failed_interval_physical_s,private_accepted_steps_rolled_back:f.failed_interval_substeps,trial_attempts:f.trial_attempts,refusal_counts:counts,
    last_newton:n?{strategy:n.newton_strategy,attempted_fractions:n.attempted_fractions,dt_s:n.dt_s,iteration:last?.iteration,equation_residual:last?.equation_residual,
      equation_tolerance:n.equation_tolerance,line_search:last?.line_search}:null,
    note:'This is a rejected private candidate. Download the experiment log for its actual poses, forces, material history and Jacobian; the scene shows accepted physics.'};
}
function accept(reply){if(reply.state){const s=reply.state;if(hash&&hash!==s.qualification.source_sha256)throw Error('Coupled source changed; reset required');if(!initial){initial=structuredClone(s);build(s);}state=s;showBefore=showImpact=false;
    let time=s.time_s-s.substep_accounts.reduce((sum,a)=>sum+a.dt_s,0);
    for(const a of s.substep_accounts){time+=a.dt_s;const frame={time_s:time,cells:s.cells.map((c,i)=>({...c,position_m:a.poses_wxyz[i].slice(0,3),quaternion_wxyz:a.poses_wxyz[i].slice(3),velocity_m_s:a.velocities[i].slice(0,3)}))};const observation=ballObservation(frame);if(observation.contact&&(!impactFrame||-observation.gap_m>impactFrame.compression_m))impactFrame={...frame,compression_m:-observation.gap_m};}
    display();showObjects(s);const stages=dropMilestones(initial,state,impactFrame);for(const key of ['before','contact','after'])$('milestone-'+key).textContent=stages[key];
    $('experiment-title').textContent=s.declaration.experiment==='freefall'?'Rigid ball drop':'Sheet impact · unfinished';
    $('experiment-summary').textContent=s.declaration.experiment==='freefall'?'This test shows falling and rebound. The ball is one rigid sphere and the ground is a fixed boundary. Neither can dent, crack or break in this experiment. Material changes affect density and contact stiffness.':'Nine connected cells on supports, struck by one rigid ball. The stronger sheet impact still stops at the solver work limit. This is an unfinished material experiment; the ball itself cannot deform or break.';
    $('material').disabled=busy||s.declaration.experiment==='freefall';const d=s.diagnostics,p=s.performance;$('results').replaceChildren();pair('Backend',s.qualification.gpu?'CUDA':'CPU reference');pair('Trial pipeline',p.pipeline==='parallel'?'Parallel':'Serial reference');pair('Newton start',p.newton_strategy==='ranked'?'Ranked starts':'Single start reference');pair('Step-size probes',p.line_search==='batch-tail'?'Full step, then private batch':'One at a time');pair('Linear solve',p.linear_backend==='numpy-reference'?'NumPy CPU reference':p.linear_backend==='native-cusolver'?'Resident cuSOLVER':'CuPy reference');pair('Contact timing',p.contact_resolution==='reference'?'Reference':p.contact_resolution.slice(6)+' rad');pair('Ball representation',s.representations?.mechanical_mode==='rigid-free-flight'?'Independent rigid flight':s.representations?'Coupled contact':'Whole coupled reference');pair('Representation switches',s.representations?.transitions.length??0);pair('Internal steps',p.microsteps);pair('Accepted time',s.time_s.toFixed(5)+' s');pair('Cells / interfaces',s.cells.length+' / '+d.interfaces);pair('Separated sites',d.separated_sites);pair('Yielded faces',d.yielded_faces);pair('Energy residual',d.global_energy_residual_j.toExponential(2)+' J');pair('Fracture / plastic work',(d.fracture_work_j+d.plastic_work_j).toExponential(2)+' J');pair('Numerical return excess',d.numerical_return_excess_j.toExponential(2)+' J');pair('Last calculation',p.last_batch_ms.toFixed(1)+' ms');pair('Compute pace · physics only',computePace(p.compute_ratio));
    pair('Contact sites · last substep',s.substep_accounts.at(-1)?.ledger[7]??0);
    const f=s.rejected_candidate;if(f){pair('Rejected trials',f.subdivision_refusals?.length??'—');pair('Scene restored',f.interval_rolled_back?'Yes':'Unconfirmed');}
    $('failure').hidden=!f;$('failure').textContent=f?JSON.stringify(refusalSummary(f),null,2):'';
  }
  if(!reply.ok)throw Error(reply.error);$('status').classList.remove('error');$('status').textContent=busy?'Calculated '+state.time_s.toFixed(4)+' simulated seconds. '+(ballObservation(state).contact?'Ball contact observed.':'Ball is still in flight.'):'Scene ready. Run to ball contact to calculate the drop.';
}
const api=command=>requestScene(command,{endpoint});
async function saveScene(){
  if(busy||!session)return;busy=true;controls();
  try{const reply=await api({op:'export',session});if(!reply.ok)throw Error(reply.error);
    const blob=new Blob([JSON.stringify(reply.checkpoint,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');
    link.href=url;link.download='banjo-scene-'+state.objects.world_id.slice(0,8)+'.json';document.body.append(link);link.click();link.remove();URL.revokeObjectURL(url);
    $('status').textContent='Saved accepted scene at '+state.time_s.toFixed(5)+' s, including material history.';
  }catch(e){$('status').textContent='Save failed: '+e.message;}finally{busy=false;controls();}
}
async function openScene(file){
  if(busy||!file)return;busy=true;controls();let candidate=null;
  try{if(file.size>2_000_000)throw Error('Scene exceeds the 2 MB lab limit');
    const checkpoint=JSON.parse(await file.text());await refreshCheckpoint();const reply=await api({op:'restore',checkpoint});
    if(!reply.ok)throw Error(reply.error);candidate=reply.session;if(reply.state?.qualification?.source_sha256!==hash)throw Error('Reopened physics source differs');
    const previous=session;session=reply.session;candidate=null;initial=state=impactFrame=null;showBefore=showImpact=false;
    const d=reply.state.declaration;
    for(const [id,key] of Object.entries({representation:'representation_policy',experiment:'experiment',contact:'contact_resolution',material:'material',ball:'ball_material',mass:'ball_mass_kg',height:'height_m',pipeline:'pipeline',newton:'newton_strategy','line-search':'line_search',linear:'linear_backend'}))$(id).value=d[key];
    $('dt').value=String(Math.round(1/d.dt_s));setupPending=false;accept(reply);$('status').classList.remove('error');
    $('status').textContent='Reopened exact accepted state at '+state.time_s.toFixed(5)+' s.'+(state.rejected_candidate?' This saved experiment remains stopped.':' Continue with Run.');
    $('log').href='/api/log/'+session;$('log').hidden=false;
    if(previous)await api({op:'close',session:previous}).catch(()=>{});
  }catch(e){if(candidate)await api({op:'close',session:candidate}).catch(()=>{});$('status').textContent='Open failed: '+e.message;}finally{busy=false;$('scene-file').value='';controls();}
}
$('save-scene').addEventListener('click',saveScene);$('open-scene').addEventListener('click',()=>$('scene-file').click());$('scene-file').addEventListener('change',e=>openScene(e.target.files[0]));
$('after').addEventListener('click',()=>{if(!state)return;showBefore=showImpact=false;frameView(state.declaration.experiment==='freefall'?'overview':'target',state);display();});
function readSettings(){return {representation_policy:$('representation').value,experiment:$('experiment').value,contact_resolution:$('contact').value,material:$('material').value,ball_material:$('ball').value,ball_mass_kg:Number($('mass').value),height_m:Number($('height').value),dt_s:1/Number($('dt').value),pipeline:$('pipeline').value,newton_strategy:$('newton').value,line_search:$('line-search').value,linear_backend:$('linear').value};}
function controls(){$('after').disabled=busy||!impactFrame;$('save-scene').disabled=busy||!session;$('open-scene').disabled=busy;$('scene-file').disabled=busy;const pending=setupPending||settingsDiffer(state?.declaration,readSettings());for(const id of ['reset','step','run','impact','drop','full-drop'])$(id).disabled=busy||(id!=='reset'&&(!session||(!pending&&(state?.rejected_candidate||!remainingSteps(state)))));$('stop').disabled=!runningAction||stopRequested;$('before').disabled=busy||!initial;$('inspect').disabled=busy||!impactFrame;for(const id of ['material','ball','mass','height','dt','pipeline','newton','line-search','linear','experiment','contact','representation'])$(id).disabled=busy;$('material').disabled=busy||$('experiment').value==='freefall';$('material').closest('label').hidden=$('experiment').value==='freefall';const dt=1/Number($('dt').value);$('run').textContent='Run 10 steps · '+(10*dt).toFixed(3)+' s';$('run-hint').textContent='10 steps = '+(10*dt).toFixed(4)+' simulated seconds. A 10 m gravity-only drop takes about 1.43 s. Run to ball contact calculates accepted steps, up to the 2 s experiment limit.';}
async function step(amount){if(busy)return;if(setupPending||settingsDiffer(state?.declaration,readSettings())){await reset();if(setupPending||!state||settingsDiffer(state.declaration,readSettings()))return;}if(!state||!session)return;const remaining=remainingSteps(state),count=Math.min(remaining,(amount==='contact'||amount==='full')?remaining:amount==='0.1s'?Math.round(.1/state.dt_s):amount);if(count<1)return;busy=runningAction=true;stopRequested=false;controls();$('status').textContent='Calculating the drop on '+backendLabel+'...';try{const completed=await runSceneSteps({session,count,onState:accept,request:api,getBatchSize:()=>state.render_schedule?.safe_rigid_flight_steps??1,shouldStop:()=>stopRequested||(amount==='contact'&&(Boolean(impactFrame)||ballObservation(state).contact)),onExpired:async()=>{session=null;busy=runningAction=false;await reset();if(session&&state)$('status').textContent='Previous scene expired. Fresh scene ready; run it again.';}});if(completed)$('status').textContent=stopRequested?'Stopped after the last accepted step at '+state.time_s.toFixed(4)+' s.':impactFrame?'Accepted '+state.time_s.toFixed(4)+' s; ball contact at '+impactFrame.time_s.toFixed(4)+' s. Use Before or Inspect ball contact.':!remainingSteps(state)?'Reached the 2 s experiment limit. No new ball contact in this run.':'Advanced to '+state.time_s.toFixed(4)+' s; ball is still in flight ('+Math.max(0,ballObservation(state).gap_m).toFixed(3)+' m gap).';}catch(e){$('status').textContent='Simulation stopped at '+(state?.time_s??0).toFixed(4)+' s: '+e.message;$('status').classList.add('error');}finally{busy=runningAction=false;controls();}}
async function reset(){if(busy||!$('mass').reportValidity()||!$('height').reportValidity())return;busy=true;controls();$('status').textContent='Creating finite cells on '+backendLabel+'...';try{if(session){await api({op:'close',session});session=null;}initial=state=impactFrame=null;showImpact=showBefore=false;$('log').hidden=true;await refreshCheckpoint();const reply=await api({op:'create',declaration:{solver_backend:backend,device:backend==='cpu-implicit-body'?'cpu':'cuda:0',representation_policy:$('representation').value,experiment:$('experiment').value,contact_resolution:$('contact').value,material:$('material').value,ball_material:$('ball').value,ball_mass_kg:Number($('mass').value),height_m:Number($('height').value),dt_s:1/Number($('dt').value),pipeline:$('pipeline').value,newton_strategy:$('newton').value,line_search:$('line-search').value,linear_backend:$('linear').value}});accept(reply);session=reply.session;setupPending=false;$('status').textContent='Scene ready. Choose a view and Run to ball contact.';$('log').href='/api/log/'+session;$('log').hidden=false;}catch(e){$('status').textContent=e.message;$('status').classList.add('error');}finally{busy=false;controls();}}
function selectExperiment(){const control=$('experiment').value==='freefall';$('contact').value=control?'phase-0.0625':'reference';$('mass').value=control?'0.1':'0.01';$('height').value=control?'10':'0.001';controls();}
$('experiment').addEventListener('change',selectExperiment);
if(new URLSearchParams(location.search).get('test')==='contact'){$('experiment').value='freefall';selectExperiment();}
if(new URLSearchParams(location.search).get('representations')==='1')$('representation').value='partitioned-flight';
$('reset').addEventListener('click',reset);$('step').addEventListener('click',()=>step(1));$('run').addEventListener('click',()=>step(10));$('impact').addEventListener('click',()=>step('0.1s'));$('drop').addEventListener('click',()=>step('contact'));$('full-drop').addEventListener('click',()=>step('full'));$('stop').addEventListener('click',()=>{stopRequested=true;$('status').textContent='Stopping after the current accepted step…';controls();});$('before').addEventListener('click',()=>{showBefore=!showBefore;showImpact=false;frameView(state.declaration.experiment==='freefall'?'overview':'target',shownState());display();});$('inspect').addEventListener('click',()=>{showImpact=!showImpact;showBefore=false;frameView(state.declaration.experiment==='freefall'?'ball':'target',shownState());display();});
for(const mode of ['target','ball','overview'])$('focus-'+mode).addEventListener('click',()=>{frameView(mode);display();});
for(const id of ['material','ball','mass','height','dt','pipeline','newton','line-search','linear','experiment','contact','representation'])for(const event of ['input','change'])$(id).addEventListener(event,()=>{setupPending=true;$('status').textContent='Settings changed. Run will set up the new drop first.';controls();});
window.addEventListener('pagehide',()=>{if(session)navigator.sendBeacon(endpoint,new Blob([JSON.stringify({op:'close',session})],{type:'application/json'}));});
window.addEventListener('pageshow',event=>{if(event.persisted)reset();});
function draw(){renderer.render(scene,camera);updateMarkers();requestAnimationFrame(draw);}cameraPose();draw();
async function refreshCheckpoint(){
 const response=await fetch('/api/checkpoint');if(!response.ok)throw Error('Cannot inspect the running physics build');const c=await response.json();
 backend=c.coupled_backend;backendLabel=c.cpu_coupled_available?'CPU reference':'CUDA';
 hash=c.cpu_coupled_available?c.cpu_coupled_implementation_sha256:c.gpu_coupled_source_sha256;
 for(const id of ['native-link','gpu-link','materials-link'])$(id).hidden=c.cpu_coupled_available;
 if(c.cpu_coupled_available){$('pipeline').replaceChildren(new Option('Serial CPU reference','serial-reference'));$('linear').replaceChildren(new Option('NumPy CPU reference','numpy-reference'));}
 const verified=(c.cpu_coupled_available?c.cpu_coupled_source_verified:c.gpu_coupled_source_verified)&&!c.local_changes&&!c.restart_pending;
 $('build').textContent=backendLabel+' / '+(c.website_revision?.slice(0,7)??c.cpu_coupled_source_sha256?.slice(0,7)??'unknown build')+' / '+(verified?'source verified':'source / restart unverified');
}
reset();
