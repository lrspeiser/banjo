import * as THREE from '/three.module.js';
import {NativePlayback} from '/playback.mjs';
const $=id=>document.getElementById(id), canvas=$('scene');
function statusRow(parent,label,value,status){const row=document.createElement('div'),name=document.createElement('dt'),result=document.createElement('dd');name.textContent=label;result.textContent=value;if(status)result.dataset.status=status;row.append(name,result);parent.append(row);}
async function loadCheckpoint(){
 try{
  const response=await fetch('/api/checkpoint');if(!response.ok)throw Error('Build status unavailable');const build=await response.json(),c=build.checkpoint;
  const matched=build.native_verified&&!build.restart_pending&&build.local_changes===false;
  $('updates').textContent=(matched?'✓ Build ':'⚠ Check build ')+(build.website_revision?.slice(0,8)??'unknown');
  $('updates').dataset.status=matched?'passed':'blocked';$('checkpoint-title').textContent=c.title??'Update status';
  $('build-match').textContent=matched?'Running the tested native checkpoint.':build.restart_pending?'Server restart required for the current website revision.':build.local_changes?'Local source or website edits are not part of the published checkpoint.':'Native build differs from the checkpoint: these test results do not verify this executable.';
  $('build-match').dataset.status=matched?'passed':'blocked';
  statusRow($('build-versions'),'Website',build.website_revision?.slice(0,8)??'Unknown');
  statusRow($('build-versions'),'Physics',c.physics_revision?.slice(0,8)??'Unrecorded');
  statusRow($('build-versions'),'Local edits',build.local_changes===null?'Unknown':build.local_changes?'Present':'None');
  for(const text of c.changes??[]){const row=document.createElement('li');row.textContent=text;$('build-changes').append(row);}
  for(const check of c.checks??[])statusRow($('build-checks'),check.label,(matched?'': 'Checkpoint only · ')+(check.status==='passed'?'✓ ': '⚠ ')+check.value,matched?check.status:'blocked');
  for(const next of c.next??[])statusRow($('build-next'),next.label,next.status,next.status);
 }catch(e){$('updates').textContent='⚠ Build status unavailable';$('build-match').textContent=e.message;$('build-match').dataset.status='blocked';}
}
$('updates').onclick=()=>{const open=$('checkpoint').hidden;if(open)document.querySelector('footer details').open=false;$('checkpoint').hidden=!open;$('updates').setAttribute('aria-expanded',String(open));};
$('close-updates').onclick=()=>{$('checkpoint').hidden=true;$('updates').setAttribute('aria-expanded','false');$('updates').focus();};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!$('checkpoint').hidden)$('close-updates').click();});
document.querySelector('footer details').addEventListener('toggle',e=>{if(e.target.open){$('checkpoint').hidden=true;$('updates').setAttribute('aria-expanded','false');}});
loadCheckpoint();
const renderer=new THREE.WebGLRenderer({canvas,antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setClearColor(0x111a24);
const scene=new THREE.Scene();scene.add(new THREE.HemisphereLight(0xbddcff,0x3e4033,2.5));const light=new THREE.DirectionalLight(0xffffff,3);light.position.set(2,6,4);scene.add(light);
const camera=new THREE.PerspectiveCamera(42,1,.005,50), overview=new THREE.PerspectiveCamera(35,1,.01,50);overview.position.set(2.8,6,4);overview.lookAt(0,5.4,0);
let yaw=.7,pitch=.36,radius=1.2,whole=false;const target=new THREE.Vector3(0,.43,0);
const colors={glass:0x98d9ed,ice:0xd5eefb,iron:0xaeb9c9,aluminum:0xdbe1e6,ceramic:0xd6a78e,oak:0xad8b64,concrete:0x536575};
let groups=[],state=null,initial=null,session=null,running=false,busy=false,showBefore=false,sequence=0;
const playback=new NativePlayback();let frameId=0,polling=false,calculating=false,pipeline=null,pipelineArrivedAt=0,renderFrames=0,fpsStart=performance.now();
const nativeRoot=new THREE.Group();scene.add(nativeRoot);
const marker=new THREE.Mesh(new THREE.RingGeometry(.013,.017,32),new THREE.MeshBasicMaterial({color:0xb2ea78,side:THREE.DoubleSide}));marker.rotation.x=-Math.PI/2;scene.add(marker);
let aim=[0,0];
const matrix=new THREE.Matrix4(),q=new THREE.Quaternion(),q0=new THREE.Quaternion(),pos=new THREE.Vector3(),scale=new THREE.Vector3();
function layout(s){for(const g of groups){nativeRoot.remove(g.mesh);g.mesh.geometry.dispose();g.mesh.material.dispose();}groups=[];
 const buckets=new Map();for(const c of s.cells){const key=[c.material,...c.size_m].join(':');if(!buckets.has(key))buckets.set(key,[]);buckets.get(key).push(c);}
 for(const cells of buckets.values()){const c=cells[0];const geometry=new THREE.BoxGeometry(1,1,1);const mesh=new THREE.InstancedMesh(geometry,new THREE.MeshStandardMaterial({color:0xffffff,roughness:.6,metalness:c.material==='iron'?.5:.05}),cells.length);nativeRoot.add(mesh);groups.push({mesh,ids:cells.map(x=>x.id)});}
}
function drawPose(sample){if(!sample)return;const cells=new Map(sample.to.cells.map(c=>[c.id,c])),previous=new Map(sample.from.cells.map(c=>[c.id,c]));
 for(const g of groups){g.ids.forEach((id,i)=>{const c=cells.get(id),a=previous.get(id)??c;pos.set(...c.position_m.map((x,j)=>a.position_m[j]+(x-a.position_m[j])*sample.alpha));const [w,x,y,z]=c.quaternion_wxyz,[aw,ax,ay,az]=a.quaternion_wxyz;q.set(x,y,z,w);q0.set(ax,ay,az,aw);q0.slerp(q,sample.alpha);scale.fromArray(c.size_m);matrix.compose(pos,q0,scale);g.mesh.setMatrixAt(i,matrix);const color=new THREE.Color(colors[c.material]??0xffffff);color.multiplyScalar(.88+.12*((c.id*17)%11)/10);g.mesh.setColorAt(i,color);});g.mesh.instanceMatrix.needsUpdate=true;g.mesh.instanceColor.needsUpdate=true;g.mesh.computeBoundingSphere();}
 canvas.dataset.renderTime=sample.time_s;canvas.dataset.bufferedStates=playback.bufferedStates;
}
function draw(s){if(!s)return;
 marker.position.set(aim[0],.501+Number($('thickness').value),aim[1]);marker.visible=s.time_s===0;
 const sheet=s.objects.find(x=>x.id===1),ball=s.objects.find(x=>x.id===2);$('time').textContent=s.time_s.toFixed(3)+' s';$('pieces').textContent=sheet.pieces+' / '+sheet.cells+' voxels';$('faces').textContent=sheet.broken_faces;$('speed').textContent=Math.hypot(...ball.velocity_m_s).toFixed(2)+' m/s';$('ballpieces').textContent=ball.pieces+' / '+ball.cells+' voxels';$('count').textContent=s.cells.length+' native cells · '+s.substeps+' accepted substeps';
 const d=s.diagnostics;$('audit').textContent=`Retained dynamic mass ${d.dynamic_mass_kg.toFixed(5)} kg · KE ${d.kinetic_j.toFixed(3)} J · elastic ${d.elastic_j.toFixed(3)} J · unclosed energy ${d.unclosed_energy_j.toFixed(3)} J · rejected trials ${s.rejected_trials}`;
 const work=s.step_work?.measured;
 for(const [id,value] of [['phase-spring',work?.spring_work_j],['phase-contact',work?.contact_work_j],['phase-limit',work?.velocity_limit_work_j],['phase-residual',work?.solver_residual_work_j]])$(id).textContent=Number.isFinite(value)?value.toFixed(5)+' J':'Unavailable in this build';
 $('phase-angular').textContent=Array.isArray(work?.solver_angular_residual_n_m_s)?Math.hypot(...work.solver_angular_residual_n_m_s).toPrecision(4)+' N·m·s':'Unavailable in this build';
 const rejected=s.step_work?.last_rejected_trial;
 $('rejected-work').textContent=rejected?`Last rejected trial: ${rejected.time_s.toFixed(6)} s · dt ${rejected.dt_s.toExponential(3)} s · candidate change ${(rejected.candidate_j-rejected.before_j).toFixed(6)} J · elastic change ${rejected.elastic_change_j.toFixed(6)} J. Rejected motion is not rendered.`:'No rejected trial recorded in this run.';
 for(const [id,value] of [['spring-damping',d.spring_material_damping_j],['numerical-elastic',d.spring_implicit_elastic_loss_j],['spring-residual',d.spring_residual_work_j]])$(id).textContent=Number.isFinite(value)?value.toFixed(3)+' J':'Unavailable in this build';
 const contact=s.contact_audit;
 for(const [id,value] of [['contact-normal',contact?.normal_endpoint_work_j],['contact-friction',contact?.friction_endpoint_work_j]])$(id).textContent=Number.isFinite(value)?value.toFixed(3)+' J':'Unavailable in this build';
 for(const [id,value] of [['support-impulse',contact?.support_reaction_impulse_n_s],['momentum-residual',contact?.linear_momentum_residual_n_s]])$(id).textContent=Array.isArray(value)?Math.hypot(...value).toPrecision(4)+' N·s':'Unavailable in this build';
 $('contact-points').textContent=contact?.point_samples??'Unavailable in this build';
 $('native-cost').textContent=Number.isFinite(d.profile?.native_step_ms)?(d.profile.native_step_ms/1000).toFixed(2)+' s wall time':'Unavailable in this build';
 $('law-status').textContent=(s.qualification?.model??'Model identity unavailable')+(s.qualification?.contact_law==='midpoint-block-friction'?' Coupled sliding/twisting block with original impulse caps; global contact convergence and full accuracy remain unqualified.':s.qualification?.contact_law==='midpoint-unilateral'?' Midpoint normal and friction constraints match centered pose integration. Hard contact, not compliant indentation; full geometry and physical accuracy remain unqualified.':s.qualification?.contact_law==='resolved-deformation'?' Unilateral contact: inelastic normal constraints; recovery only from interfaces. No compliant contact indentation or calibrated energy accuracy.':' Material-derived instantaneous restitution remains the reference contact response.');
 const boundary=s.midpoint_boundary;$('boundary-audit').hidden=!boundary;
 if(boundary){
  const gap=(key)=>Number.isFinite(boundary[key])?boundary[key].toPrecision(4)+' J':'Unavailable in this build';
  $('boundary-audit').textContent='Midpoint contact · normal '+boundary.normal_midpoint_work_j.toFixed(4)+' J · friction '+boundary.friction_midpoint_work_j.toFixed(4)+' J · twist '+boundary.twist_midpoint_work_j.toFixed(4)+' J. Largest constraint disagreement: normal '+gap('max_complementarity_error_j')+' · sliding '+gap('max_friction_stationarity_gap_j')+' · twisting '+gap('max_twist_stationarity_gap_j')+'. These are measured solver terms, not calibrated heat.';
 }
 const failedTwist=rejected?.worst_twist_contact;
 if(failedTwist)$('rejected-work').textContent+=' Largest rejected twist disagreement: cells '+failedTwist.a+' / '+failedTwist.b+' · work '+failedTwist.twist_work_j.toPrecision(5)+' J · midpoint slip '+failedTwist.midpoint_spin_rad_s.toPrecision(5)+' rad/s · impulse '+failedTwist.twist_impulse_n_m_s.toPrecision(5)+' / ±'+failedTwist.twist_cap_n_m_s.toPrecision(5)+' N·m·s. Full contact details are in Download record.';
 canvas.dataset.time=s.time_s;canvas.dataset.nativeCells=s.cells.length;canvas.dataset.sheetPieces=sheet.pieces;
}
function updateCamera(){target.set(0,whole?4.8:.43,0);const r=whole?13:radius;camera.position.set(target.x+r*Math.cos(pitch)*Math.sin(yaw),target.y+r*Math.sin(pitch),target.z+r*Math.cos(pitch)*Math.cos(yaw));camera.lookAt(target);}
let viewportWidth=0,viewportHeight=0;
function render(now){drawPose(showBefore?{from:initial,to:initial,alpha:1,time_s:initial.time_s}:playback.sample(now));const w=canvas.clientWidth,h=canvas.clientHeight;if(w!==viewportWidth||h!==viewportHeight){renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();viewportWidth=w;viewportHeight=h;}updateCamera();renderer.setViewport(0,0,w,h);renderer.setScissorTest(false);renderer.render(scene,camera);
 if(pipeline)$('pose-age').textContent=(pipeline.published_state_age_ms+Math.max(0,now-pipelineArrivedAt)).toFixed(0)+' ms'+(!running&&!calculating?' · paused':'');
 if(!whole&&w>850){const ih=Math.min(190,h*.25),iw=110;renderer.setScissorTest(true);renderer.setScissor(w-iw-22,h-ih-250,iw,ih);renderer.setViewport(w-iw-22,h-ih-250,iw,ih);if(overview.aspect!==iw/ih){overview.aspect=iw/ih;overview.updateProjectionMatrix();}renderer.render(scene,overview);renderer.setScissorTest(false);}
 renderFrames++;if(now-fpsStart>=1000){$('render-fps').textContent=Math.round(renderFrames*1000/(now-fpsStart))+' fps';renderFrames=0;fpsStart=now;}
 requestAnimationFrame(render);
}
async function request(command){const start=performance.now();const response=await fetch('/api/world',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(command)});const reply=await response.json();if(command.op!=='frame')$('control-latency').textContent=(performance.now()-start).toFixed(1)+' ms';return reply;}
function accept(r){
 if(r.state){state=r.state;playback.push(state,performance.now());if(!showBefore)draw(state);}
 if(r.pipeline){pipeline=r.pipeline;pipelineArrivedAt=performance.now();running=pipeline.running;calculating=pipeline.calculating;$('sim-speed').textContent=pipeline.realtime_ratio.toFixed(2)+'× realtime';$('batch-cost').textContent=pipeline.max_native_batch_ms.toFixed(1)+' ms / '+pipeline.native_batch_budget_ms+' ms target';}
 if(r.pipeline){$('batch-p95').textContent=pipeline.batch_sample_count?pipeline.native_batch_p95_ms.toFixed(1)+' ms / '+pipeline.batch_sample_count+' batches':'No batches yet';$('pose-age').textContent=pipeline.published_state_age_ms.toFixed(0)+' ms'+(!running&&!calculating?' · paused':'');$('record-size').textContent=(pipeline.journal_compressed_bytes/1e6).toFixed(2)+' MB';}
 if(!r.ok){running=false;$('phase').textContent='Stopped · '+r.error;}
 else if(state)$('phase').textContent=state.time_s>=2?'Drop complete':calculating&&!running?'Pausing · finishing native batch':running?'Live native physics': 'Native state ready';
 controls();
}
async function poll(generation){
 if(polling)return;polling=true;
 try{while(generation===sequence&&session&&(running||calculating)){
  let r;
  for(let attempt=0;attempt<3;attempt++){
   try{r=await request({op:'frame',session,after:frameId,wait_ms:50});break;}
   catch(error){if(attempt===2)throw error;$('phase').textContent='Reconnecting · retaining last native state';await new Promise(resolve=>setTimeout(resolve,150*(attempt+1)));}
  }
  if(generation!==sequence)return;
  if(r.frame_id>frameId){frameId=r.frame_id;accept(r);}else if(r.pipeline)accept({...r,state:undefined});
  if(!r.ok)break;
 }}catch(e){if(generation===sequence){running=false;calculating=false;$('phase').textContent='Stopped · '+e.message;controls();}}
 finally{polling=false;if(generation!==sequence&&(running||calculating))poll(sequence);}
}
function controls(){for(const id of ['sheet','thickness','resolution','gap','ball','mass','height','face_law','contact_law'])$(id).disabled=busy||running||calculating;$('reset').disabled=busy;$('drop').disabled=busy||!session||showBefore||state?.time_s>=2||(!running&&calculating);$('step').disabled=busy||running||calculating||!session||showBefore||state?.time_s>=2;$('before').disabled=busy||!initial||running||calculating;$('live').disabled=busy||!state||running||calculating;$('drop').textContent=running?'Pause':'Drop ball';}
async function reset(){if(busy)return;busy=true;running=false;showBefore=false;controls();$('phase').textContent='Building native scene…';const generation=++sequence;
 try{const glass=$('ball').querySelector('option[value="glass"]');glass.disabled=$('contact_law').value==='material-restitution';glass.textContent=glass.disabled?'Glass · reference gate open':'Glass';if(glass.disabled&&$('ball').value==='glass')$('ball').value='iron';if(session)await request({op:'close',session});session=null;frameId=0;calculating=false;pipeline=null;const declaration={sheet:$('sheet').value,ball:$('ball').value,mass_kg:Number($('mass').value),height_m:Number($('height').value),thickness_m:Number($('thickness').value),resolution:Number($('resolution').value),support_gap_m:Number($('gap').value),offset_x_m:aim[0],offset_z_m:aim[1]};if($('face_law').value!=='native-motor')declaration.face_law=$('face_law').value;if($('contact_law').value!=='material-restitution')declaration.contact_law=$('contact_law').value;const r=await request({op:'create',declaration});if(!r.ok)throw Error(r.error);if(generation!==sequence)return;session=r.session;state=r.state;initial=structuredClone(state);playback.reset(state,performance.now());layout(state);draw(state);$('sim-speed').textContent='Ready';$('batch-cost').textContent='8 ms target';$('batch-p95').textContent='No batches yet';$('pose-age').textContent='Ready';$('record-size').textContent='New record';$('phase').textContent='Ready · '+(9.81*declaration.mass_kg*declaration.height_m).toFixed(1)+' J drop';$('log').href='/api/log/'+session;}
 catch(e){$('phase').textContent='Stopped · '+e.message;}finally{busy=false;controls();}
}
async function advance(){if(busy||!session)return;busy=true;controls();const start=performance.now();
 try{const r=await request({op:'advance',session,steps:16});accept(r);if(r.ok)$('phase').textContent='Native step accepted';}
 catch(e){running=false;$('phase').textContent='Stopped · '+e.message;}finally{busy=false;controls();}
}
$('drop').onclick=async()=>{busy=true;controls();try{const r=await request({op:'play',session,running:!running,target_time_s:2});accept(r);if(r.ok&&(running||calculating))poll(sequence);}catch(e){$('phase').textContent='Stopped · '+e.message;}finally{busy=false;controls();}};$('step').onclick=advance;$('reset').onclick=reset;
$('before').onclick=()=>{showBefore=true;draw(initial);$('phase').textContent='Before · starting state';controls();};$('live').onclick=()=>{showBefore=false;draw(state);$('phase').textContent=state.time_s>=2?'Drop complete':'Live · accepted native state';controls();};
$('view').onclick=()=>{whole=!whole;$('view').textContent=whole?'Impact close-up':'Whole rig';};
for(const id of ['sheet','thickness','resolution','gap','ball','mass','height','face_law','contact_law'])$(id).onchange=()=>{
 if(id==='contact_law'&&['midpoint-unilateral','midpoint-block-friction'].includes($('contact_law').value))$('face_law').value='centered-log-gradient';
 if(id==='face_law'&&$('face_law').value!=='centered-log-gradient'&&['midpoint-unilateral','midpoint-block-friction'].includes($('contact_law').value))$('contact_law').value='resolved-deformation';
 reset();
};
let press=null;canvas.addEventListener('pointerdown',e=>{press={x:e.clientX,y:e.clientY,yaw,pitch,moved:false};canvas.setPointerCapture(e.pointerId);});canvas.addEventListener('pointermove',e=>{if(!press)return;const dx=e.clientX-press.x,dy=e.clientY-press.y;if(Math.hypot(dx,dy)>5)press.moved=true;if(press.moved){yaw=press.yaw-dx*.008;pitch=Math.max(.04,Math.min(1.4,press.pitch+dy*.006));}});
canvas.addEventListener('pointerup',e=>{if(!press)return;const clicked=!press.moved;press=null;if(!clicked||busy||running)return;const r=canvas.getBoundingClientRect(),ray=new THREE.Raycaster();ray.setFromCamera(new THREE.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),camera);const hit=ray.intersectObjects(groups.map(g=>g.mesh)).find(h=>state.cells.find(c=>c.id===groups.find(g=>g.mesh===h.object).ids[h.instanceId])?.object===1);if(hit){aim=[Math.max(-.19,Math.min(.19,hit.point.x)),Math.max(-.19,Math.min(.19,hit.point.z))];reset();}});
canvas.addEventListener('wheel',e=>{e.preventDefault();radius=Math.max(.45,Math.min(3,radius*Math.exp(e.deltaY*.001)));},{passive:false});
window.addEventListener('pagehide',()=>{if(session)fetch('/api/world',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({op:'close',session}),keepalive:true});});
requestAnimationFrame(render);reset();
