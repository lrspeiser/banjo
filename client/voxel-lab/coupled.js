import * as THREE from '/three.module.js';
const $=id=>document.getElementById(id),view=$('view');
const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));view.append(renderer.domElement);
const scene=new THREE.Scene();scene.background=new THREE.Color('#101d26');scene.add(new THREE.HemisphereLight(0xf0f6ff,0x253c48,2));
const light=new THREE.DirectionalLight(0xffffff,3);light.position.set(.2,.4,.3);scene.add(light);
const camera=new THREE.PerspectiveCamera(40,1,.0001,100),meshes=[];
let yaw=.5,pitch=.55,radius=.15,target=new THREE.Vector3(0,.025,0),drag=null,session=null,state=null,initial=null,busy=false,showBefore=false,hash=null;
const colors={glass:0x8fd1e9,oak:0xb0875c,iron:0x9ba8b7,ice:0xcbeafa};
function cameraPose(){const r=radius*Math.max(1,1.3/camera.aspect);camera.position.copy(target).add(new THREE.Vector3(Math.sin(yaw)*Math.cos(pitch)*r,Math.sin(pitch)*r,Math.cos(yaw)*Math.cos(pitch)*r));camera.lookAt(target);}
new ResizeObserver(()=>{renderer.setSize(view.clientWidth,view.clientHeight);camera.aspect=view.clientWidth/view.clientHeight;camera.updateProjectionMatrix();cameraPose();}).observe(view);
renderer.domElement.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY};renderer.domElement.setPointerCapture(e.pointerId);});
for(const name of ['pointerup','pointercancel'])renderer.domElement.addEventListener(name,()=>drag=null);
renderer.domElement.addEventListener('pointermove',e=>{if(!drag)return;yaw-=(e.clientX-drag.x)*.006;pitch=Math.max(-.25,Math.min(1.4,pitch+(e.clientY-drag.y)*.006));drag={x:e.clientX,y:e.clientY};cameraPose();});
renderer.domElement.addEventListener('wheel',e=>{e.preventDefault();radius=Math.max(.04,Math.min(30,radius*Math.exp(e.deltaY*.001)));cameraPose();},{passive:false});
function build(s){for(const m of meshes){scene.remove(m);m.geometry.dispose();m.material.dispose();}meshes.length=0;
  for(const c of s.cells){const geometry=c.shape==='sphere'?new THREE.SphereGeometry(c.radius_m,24,16):c.shape==='plane'?new THREE.BoxGeometry(.3,.001,.3):new THREE.BoxGeometry(...c.size_m);
    const m=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color:c.shape==='plane'?0x223640:colors[c.material],roughness:.55,metalness:c.material==='iron'?.3:0}));
    if(c.shape==='cube')m.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry),new THREE.LineBasicMaterial({color:0x294552})));scene.add(m);meshes.push(m);}
  const ymax=Math.max(...s.cells.map(c=>c.position_m[1]+c.radius_m));target.set(0,ymax/2,0);radius=Math.max(.12,ymax*2.5);cameraPose();
}
function display(){const shown=showBefore?initial:state;if(!shown)return;
  for(const [i,c] of shown.cells.entries()){const m=meshes[i],q=c.quaternion_wxyz;m.position.fromArray(c.position_m);if(c.shape==='plane')m.position.y-=.0005;m.quaternion.set(q[1],q[2],q[3],q[0]);}
  $('before').textContent=showBefore?'Live':'Before';
}
function pair(name,value){const row=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=name;dd.textContent=value;row.append(dt,dd);$('results').append(row);}
function accept(reply){if(reply.state){const s=reply.state;if(hash&&hash!==s.qualification.source_sha256)throw Error('Coupled source changed; reset required');if(!initial){initial=structuredClone(s);build(s);}state=s;showBefore=false;display();
    const d=s.diagnostics,p=s.performance;$('results').replaceChildren();pair('CUDA pipeline',p.pipeline==='parallel'?'Parallel':'Serial reference');pair('Physical time',s.time_s.toFixed(5)+' s');pair('Cells / interfaces',s.cells.length+' / '+d.interfaces);pair('Separated sites',d.separated_sites);pair('Yielded faces',d.yielded_faces);pair('Energy residual',d.global_energy_residual_j.toExponential(2)+' J');pair('Fracture / plastic work',(d.fracture_work_j+d.plastic_work_j).toExponential(2)+' J');pair('Numerical return excess',d.numerical_return_excess_j.toExponential(2)+' J');pair('Last calculation',p.last_batch_ms.toFixed(1)+' ms');pair('Physical / wall speed',p.compute_ratio===null?'—':p.compute_ratio.toFixed(5)+'×');
    $('failure').hidden=!s.rejected_candidate;$('failure').textContent=s.rejected_candidate?JSON.stringify(s.rejected_candidate,null,2):'';
  }
  if(!reply.ok)throw Error(reply.error);$('status').classList.remove('error');$('status').textContent='Accepted CUDA states · experimental / realtime gate open';
}
async function api(command){const response=await fetch('/api/gpu',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(command)});const reply=await response.json();if(!response.ok)throw Error(reply.error);return reply;}
function controls(){for(const id of ['reset','step','run'])$(id).disabled=busy||(id!=='reset'&&(!session||state?.rejected_candidate));$('before').disabled=!initial;for(const id of ['material','ball','mass','height','dt','pipeline'])$(id).disabled=busy;}
async function step(count){if(busy)return;busy=true;controls();$('status').textContent='Solving on CUDA; the accepted scene remains visible…';try{for(let i=0;i<count;i++){accept(await api({op:'advance',session,steps:1}));}}catch(e){$('status').textContent=e.message;$('status').classList.add('error');}finally{busy=false;controls();}}
async function reset(){if(busy||!$('mass').reportValidity()||!$('height').reportValidity())return;busy=true;controls();$('status').textContent='Creating finite CUDA cells…';try{if(session){await api({op:'close',session});session=null;}initial=state=null;const reply=await api({op:'create',declaration:{solver_backend:'cupy-implicit-body',material:$('material').value,ball_material:$('ball').value,ball_mass_kg:Number($('mass').value),height_m:Number($('height').value),dt_s:1/Number($('dt').value),pipeline:$('pipeline').value}});session=reply.session;accept(reply);$('log').href='/api/log/'+session;$('log').hidden=false;}catch(e){$('status').textContent=e.message;$('status').classList.add('error');}finally{busy=false;controls();}}
$('reset').addEventListener('click',reset);$('step').addEventListener('click',()=>step(1));$('run').addEventListener('click',()=>step(10));$('before').addEventListener('click',()=>{showBefore=!showBefore;display();});
window.addEventListener('pagehide',()=>{if(session)navigator.sendBeacon('/api/gpu',new Blob([JSON.stringify({op:'close',session})],{type:'application/json'}));});
function draw(){renderer.render(scene,camera);requestAnimationFrame(draw);}cameraPose();draw();
fetch('/api/checkpoint').then(r=>r.json()).then(c=>{hash=c.gpu_coupled_source_sha256;$('build').textContent='Build '+c.website_revision?.slice(0,7)+' · '+(c.gpu_coupled_source_verified&&!c.local_changes&&!c.restart_pending?'coupled source verified':'source / restart unverified');reset();}).catch(e=>$('build').textContent=e.message);
