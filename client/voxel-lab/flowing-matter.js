import * as THREE from '/three.module.js';
import {scalar,columnTransform,frameAtTime} from '/flow-view.mjs';
const $=id=>document.getElementById(id),nx=48,nz=24,dx=.1,view=$('view');
const scene=new THREE.Scene();scene.background=new THREE.Color(0x0a141b);
const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));view.prepend(renderer.domElement);
const camera=new THREE.PerspectiveCamera(45,1,.01,100);scene.add(new THREE.HemisphereLight(0xdcf4ff,0x273c4a,2));
const light=new THREE.DirectionalLight(0xffffff,3);light.position.set(1,5,3);scene.add(light);
const water=new THREE.InstancedMesh(new THREE.BoxGeometry(dx*.96,1,dx*.96),new THREE.MeshStandardMaterial({roughness:.45,metalness:.1}),nx*nz);water.instanceMatrix.setUsage(THREE.DynamicDrawUsage);scene.add(water);
const floor=new THREE.Mesh(new THREE.BoxGeometry(nx*dx,.06,nz*dx),new THREE.MeshStandardMaterial({color:0x344a53}));floor.position.y=-.03;scene.add(floor);
const grid=new THREE.GridHelper(nx*dx,nx,0x496978,0x29434f);grid.position.y=.001;scene.add(grid);
for(const [x,z,sx,sz] of [[-nx*dx/2,0,.04,nz*dx],[nx*dx/2,0,.04,nz*dx],[0,-nz*dx/2,nx*dx,.04],[0,nz*dx/2,nx*dx,.04]]){const wall=new THREE.Mesh(new THREE.BoxGeometry(sx,.5,sz),new THREE.MeshStandardMaterial({color:0x6c919f,transparent:true,opacity:.22}));wall.position.set(x,.25,z);scene.add(wall);}
let initial=[],data=null,index=0,playing=false,busy=false,start=0,startTime=0,paint=false,drag=null,azimuth=.6,elevation=.65,distance=8;
const dummy=new THREE.Object3D(),color=new THREE.Color(),ray=new THREE.Raycaster(),pointer=new THREE.Vector2();
function pose(){const d=distance*Math.max(1,1/camera.aspect);camera.position.set(Math.sin(azimuth)*Math.cos(elevation)*d,Math.sin(elevation)*d,Math.cos(azimuth)*Math.cos(elevation)*d);camera.lookAt(0,.1,0);}pose();
new ResizeObserver(()=>{camera.aspect=view.clientWidth/view.clientHeight;camera.updateProjectionMatrix();renderer.setSize(view.clientWidth,view.clientHeight);pose();}).observe(view);
function current(){return data?data.frames[index].cells:initial;}
function show(){const cells=current(),mode=$('color').value,rho=data?data.definition.material.density_kg_m3:Number($('density').value);let peak=0;
  for(const c of cells){const value=scalar(c,mode,rho);peak=Math.max(peak,value);}
  for(let k=0;k<cells.length;k++){const c=cells[k],value=scalar(c,mode,rho),transform=columnTransform(k,nx,nz,dx,c[0]);
    dummy.position.fromArray(transform.position);dummy.scale.fromArray(transform.scale);dummy.updateMatrix();water.setMatrixAt(k,dummy.matrix);
    color.setHSL(.58-.56*(peak?value/peak:0),.8,.5);water.setColorAt(k,color);
  }water.instanceMatrix.needsUpdate=true;water.instanceColor.needsUpdate=true;water.computeBoundingSphere();
  $('clock').textContent=(data?data.frames[index].account.time_s.toFixed(3)+' s · accepted flow':'Initial state · '+(paint?'paint depth':'orbit basin'));
  $('legend').textContent='Blue → red · '+mode+' · 0 — '+peak.toFixed(mode==='pressure'?0:2)+(mode==='pressure'?' Pa':mode==='depth'?' m':' m/s');
  if(data)receipts();
}
function pair(name,value){const row=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=name;dd.textContent=value;row.append(dt,dd);$('results').append(row);}
function receipts(){const a=data.frames[index].account;$('results').replaceChildren();pair('Conserved water',a.mass_kg.toFixed(3)+' kg');pair('Mass error',a.mass_residual_kg.toExponential(2)+' kg');pair('Wall impulse',Math.hypot(a.wall_impulse_x_n_s,a.wall_impulse_z_n_s).toFixed(3)+' N·s');pair('Wall angular impulse',a.wall_angular_impulse_y_n_m_s.toFixed(3)+' N·m·s');pair('Numerical angular change',a.numerical_angular_y_n_m_s.toExponential(2)+' N·m·s');pair('Momentum error',Math.hypot(a.momentum_x_residual_n_s,a.momentum_z_residual_n_s).toExponential(2)+' N·s');pair('Mechanical energy',a.mechanical_energy_j.toFixed(2)+' J');pair('Numerical energy change',a.numerical_energy_j.toFixed(2)+' J');pair('Energy receipt error',a.energy_residual_j.toExponential(2)+' J');pair('CFL substeps',String(a.substeps));pair('Calculation',data.measured.native_compute_s.toFixed(3)+' wall s / '+data.measured.physical_s.toFixed(2)+' physical s');}
function reset(){if(busy)return;playing=false;data=null;initial=Array.from({length:nx*nz},(_,k)=>[k%nx<nx/3?Number($('left').value):Number($('right').value),0,0]);for(const id of ['continue','play','pause','scrub'])$(id).disabled=true;$('results').replaceChildren();show();}
function brushAt(e){if(busy)return;if(data){$('status').textContent='Set initial field before painting. Calculated states are immutable.';return;}pointer.set((e.offsetX/view.clientWidth)*2-1,-(e.offsetY/view.clientHeight)*2+1);ray.setFromCamera(pointer,camera);const hit=ray.intersectObject(floor)[0];if(!hit)return;const i=Math.floor((hit.point.x+nx*dx/2)/dx),j=Math.floor((hit.point.z+nz*dx/2)/dx),depth=Number($('paint-depth').value);if(!Number.isFinite(depth)||depth<0||depth>2)return;for(let y=j-1;y<=j+1;y++)for(let x=i-1;x<=i+1;x++)if(x>=0&&x<nx&&y>=0&&y<nz)initial[y*nx+x]=[depth,0,0];show();}
renderer.domElement.addEventListener('pointerdown',e=>{renderer.domElement.setPointerCapture(e.pointerId);drag=[e.clientX,e.clientY];if(paint)brushAt(e);});
renderer.domElement.addEventListener('pointermove',e=>{if(!drag)return;if(paint)brushAt(e);else{azimuth-=(e.clientX-drag[0])*.006;elevation=Math.max(.1,Math.min(1.5,elevation+(e.clientY-drag[1])*.006));pose();}drag=[e.clientX,e.clientY];});for(const event of ['pointerup','pointercancel'])renderer.domElement.addEventListener(event,()=>drag=null);
renderer.domElement.addEventListener('wheel',e=>{e.preventDefault();distance=Math.max(1,Math.min(20,distance*Math.exp(e.deltaY*.001)));pose();},{passive:false});
$('orbit').onclick=()=>{paint=false;$('orbit').setAttribute('aria-pressed','true');$('brush').setAttribute('aria-pressed','false');};$('brush').onclick=()=>{if(busy)return;paint=true;$('brush').setAttribute('aria-pressed','true');$('orbit').setAttribute('aria-pressed','false');};$('fit').onclick=()=>{distance=8;pose();};$('initial').onclick=reset;
function setBusy(value){busy=value;for(const id of ['initial','calculate','brush','left','right','density','duration','paint-depth'])$(id).disabled=value;for(const id of ['continue','play','pause','scrub'])$(id).disabled=value||!data;}
async function calculateFlow(continuing=false){
  if(busy||(continuing&&!data?.checkpoint))return;
  for(const id of continuing?['duration']:['density','duration','left','right'])if(!$(id).reportValidity())return;
  const previous=data,previousIndex=index,previousBuild=$('build').textContent,previousIdentity=$('identity').textContent,declaration=continuing?{duration_s:Number($('duration').value),frames:121}:{nx,nz,dx_m:dx,density_kg_m3:Number($('density').value),duration_s:Number($('duration').value),frames:121,initial};
  const payload=continuing?{declaration,checkpoint:previous.checkpoint}:{declaration};
  playing=false;drag=null;setBusy(true);$('status').textContent=continuing?'Continuing the same conserved water…':'Calculating actual native conservative face fluxes…';let accepted=false;
  try{
    const r=await fetch('/api/flow-reference',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),result=await r.json();
    if(!r.ok||!result.ok)throw Error(result.error||'Flow calculation refused');
    if(!result.checkpoint||!Array.isArray(result.frames)||!result.frames.length)throw Error('Incomplete accepted flow state');
    if(continuing){
      if(result.instance.id!==previous.instance.id||JSON.stringify(result.instance.matter_ids)!==JSON.stringify(previous.instance.matter_ids)||JSON.stringify(result.instance.control_volume_ids)!==JSON.stringify(previous.instance.control_volume_ids))throw Error('Persistent flow identity changed');
      if(result.frames[0].account.time_s!==previous.frames.at(-1).account.time_s||result.instance.accepted_time_s<=previous.instance.accepted_time_s)throw Error('Accepted flow clock did not continue');
    }
    data=result;index=0;$('scrub').value='0';$('scrub').max=String(result.frames.length-1);$('build').textContent='Native flow '+result.native_sha256.slice(0,12)+' · experimental';
    $('identity').textContent=JSON.stringify({instance_id:result.instance.id,matter_ids:result.instance.matter_ids,accepted_time_s:result.instance.accepted_time_s,law:result.law,source_sha256:result.source_sha256,native_sha256:result.native_sha256,limits:result.limits},null,2);
    $('status').textContent=(continuing?'Continued the same water to ':'Calculated to ')+result.instance.accepted_time_s.toFixed(3)+' s. Replay shows accepted states only.';show();if(matchMedia('(max-width:850px)').matches)view.scrollIntoView({block:'start'});accepted=true;
  }catch(e){const changed=data!==previous;data=previous;index=previousIndex;$('build').textContent=previousBuild;$('identity').textContent=previousIdentity;$('scrub').value=String(index);$('scrub').max=String(previous?previous.frames.length-1:120);if(changed)show();$('status').textContent='Refused: '+e.message+(previous?' Last accepted flow retained.':' Initial field retained.');}finally{setBusy(false);}
  if(accepted)play();
}
$('calculate').onclick=()=>calculateFlow(false);$('continue').onclick=()=>calculateFlow(true);
function play(){if(busy||!data)return;if(index===data.frames.length-1)index=0;start=performance.now();startTime=data.frames[index].account.time_s;playing=true;}$('play').onclick=play;$('pause').onclick=()=>playing=false;$('scrub').oninput=()=>{if(busy)return;playing=false;index=Number($('scrub').value);show();};$('color').onchange=show;
function frame(now){if(playing&&data){const time=startTime+(now-start)/1000,next=frameAtTime(data.frames,time,index);if(next!==index){index=next;$('scrub').value=String(index);show();}if(index===data.frames.length-1)playing=false;}renderer.render(scene,camera);requestAnimationFrame(frame);}reset();requestAnimationFrame(frame);
