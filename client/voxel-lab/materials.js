import * as THREE from '/three.module.js';
const $=id=>document.getElementById(id),view=$('view');
const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));view.append(renderer.domElement);
const scene=new THREE.Scene();scene.background=new THREE.Color('#101d26');
const camera=new THREE.PerspectiveCamera(38,1,.001,10);
scene.add(new THREE.HemisphereLight(0xf0f6ff,0x253c48,2));const light=new THREE.DirectionalLight(0xffffff,3);light.position.set(.1,.3,.2);scene.add(light);
const colors={glass:0x8fd1e9,oak:0xb0875c,iron:0x9ba8b7,ice:0xcbeafa};
const centers=[-.12,-.04,.04,.12],groups=[],labels=[];
let state=null,session=null,busy=false,expectedHash=null;
let yaw=.12,pitch=.6,radius=.42;
function pose(){const r=radius*Math.max(1,1.25/camera.aspect);camera.position.set(Math.sin(yaw)*Math.cos(pitch)*r,Math.sin(pitch)*r,Math.cos(yaw)*Math.cos(pitch)*r);camera.lookAt(0,0,0);}
function resize(){renderer.setSize(view.clientWidth,view.clientHeight);camera.aspect=view.clientWidth/view.clientHeight;camera.updateProjectionMatrix();pose();}new ResizeObserver(resize).observe(view);
let drag=null;renderer.domElement.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY};renderer.domElement.setPointerCapture(e.pointerId);});renderer.domElement.addEventListener('pointerup',()=>drag=null);renderer.domElement.addEventListener('pointercancel',()=>drag=null);renderer.domElement.addEventListener('pointermove',e=>{if(!drag)return;yaw-=(e.clientX-drag.x)*.006;pitch=Math.max(-.3,Math.min(1.4,pitch+(e.clientY-drag.y)*.006));drag={x:e.clientX,y:e.clientY};pose();});renderer.domElement.addEventListener('wheel',e=>{e.preventDefault();radius=Math.max(.15,Math.min(1,radius*Math.exp(e.deltaY*.001)));pose();},{passive:false});
function build(s){for(const g of groups)scene.remove(g);groups.length=0;$('labels').replaceChildren();labels.length=0;
  for(const [i,c] of s.coupons.entries()){const g=new THREE.Group();g.position.x=centers[i];
    const geometry=new THREE.BoxGeometry(c.cell_size_m,c.cell_size_m,c.cell_size_m);
    for(let j=0;j<2;j++){const mesh=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color:colors[c.material],metalness:c.material==='iron'?.55:0,roughness:.5}));mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry),new THREE.LineBasicMaterial({color:0x294552})));g.add(mesh);}
    const bond=new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(),new THREE.Vector3(.01,0,0)]),new THREE.LineBasicMaterial({color:0x6fe0bc}));g.add(bond);scene.add(g);groups.push(g);
    const label=document.createElement('span');label.className='object-label';label.textContent=c.material;$('labels').append(label);labels.push(label);
  }
}
function accept(reply){if(!reply.ok)throw Error(reply.error);if(!state)build(reply.state);state=reply.state;
  if(expectedHash&&state.qualification.source_sha256!==expectedHash)throw Error('Worker material source mismatch; reset the experiment');
  $('results').replaceChildren();
  for(const [i,c] of state.coupons.entries()){const outcome=c.model==='connector-plastic'?(c.permanent_rest_m?(c.permanent_rest_m*1e6).toFixed(2)+' µm rest':'Elastic'):c.separated?'Separated':c.damage?'Damaged':'Intact';labels[i].textContent=c.material[0].toUpperCase()+c.material.slice(1)+' · '+outcome;if(c.material!==$('readout').value)continue;const card=document.createElement('section');card.className='result';const h=document.createElement('h2');h.textContent=c.material;const badge=document.createElement('span');badge.textContent=outcome;h.append(badge);card.append(h);
    const pairs=[['Opening',(c.opening_m*1e6).toFixed(3)+' µm'],['Force',c.force_n.toPrecision(4)+' N'],['Stored energy',c.stored_energy_j.toPrecision(4)+' J'],['Physical dissipation',c.physical_dissipation_j.toPrecision(4)+' J']];
    if(c.model==='connector-plastic')pairs.push(['Permanent rest',(c.permanent_rest_m*1e6).toFixed(3)+' µm'],['Numerical return excess',c.numerical_return_excess_j.toPrecision(4)+' J']);
    else pairs.push(['Damage',(c.damage*100).toFixed(1)+'%']);
    pairs.push(['Loading work',c.loading_work_j.toPrecision(4)+' J'],['Work residual',c.balance_residual_j.toExponential(2)+' J']);
    const dl=document.createElement('dl');for(const [name,value] of pairs){const row=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=name;dd.textContent=value;row.append(dt,dd);dl.append(row);}card.append(dl);$('results').append(card);
  }
  const p=state.performance;$('latency').textContent=p.last_control_ms.toFixed(3)+' ms';$('kernel').textContent=p.kernel_ms.toFixed(3)+' ms';$('readback').textContent=p.readback_ms.toFixed(3)+' / '+p.audit_ms.toFixed(3)+' ms';
  $('status').classList.remove('error');$('status').textContent=`CUDA history accepted · ${state.ticks} loading updates · no dynamics clock`;
}
async function api(command){const response=await fetch('/api/gpu',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(command)});const reply=await response.json();if(!response.ok||!reply.ok)throw Error(reply.error);return reply;}
async function action(command){if(busy)return;busy=true;controls();try{accept(await api(command));}catch(e){$('status').textContent=e.message;$('status').classList.add('error');}finally{busy=false;controls();}}
function controls(){for(const id of ['reset','apply','unload'])$(id).disabled=busy||(!session&&id!=='reset');}
async function reset(){if(busy)return;busy=true;controls();$('status').textContent='Creating resident CUDA histories; compiling shared headers if needed…';try{if(session){await api({op:'close',session});session=null;}state=null;const reply=await api({op:'create',declaration:{solver_backend:'cupy-material-laws'}});session=reply.session;accept(reply);$('log').href='/api/log/'+session;$('log').hidden=false;}catch(e){$('status').textContent=e.message;$('status').classList.add('error');}finally{busy=false;controls();}}
$('reset').addEventListener('click',reset);$('apply').addEventListener('click',()=>{if(!$('opening').reportValidity())return;action({op:'strain',session,opening_m:Number($('opening').value)*1e-6});});$('unload').addEventListener('click',()=>action({op:'unload',session}));
$('magnification').addEventListener('change',()=>$('scale-note').textContent='Opening ×'+$('magnification').value);
$('readout').addEventListener('change',()=>{if(state)accept({ok:true,state});});
// This inspector owns only its temporary GPU worker; its journal stays on disk.
window.addEventListener('pagehide',()=>{if(session)navigator.sendBeacon('/api/gpu',new Blob([JSON.stringify({op:'close',session})],{type:'application/json'}));});
const projection=new THREE.Vector3();function draw(){if(state)for(const [i,c] of state.coupons.entries()){const g=groups[i],gap=c.opening_m*Number($('magnification').value);g.children[0].position.x=-.005;g.children[1].position.x=.005+gap;g.children[2].visible=!c.separated;g.children[2].scale.x=1+gap/.01;g.children[2].material.color.setHex(c.model==='connector-plastic'&&c.permanent_rest_m?0xffc579:0x6fe0bc);
    projection.set(centers[i]+gap/2,.023,0).project(camera);labels[i].hidden=projection.z>1||Math.abs(projection.x)>1||Math.abs(projection.y)>1;const half=labels[i].offsetWidth/2+4;labels[i].style.left=Math.max(half,Math.min(view.clientWidth-half,(projection.x+1)*view.clientWidth/2))+'px';labels[i].style.top=((1-projection.y)*view.clientHeight/2+(view.clientWidth<500?-45+(i%2?22:0):0))+'px';}
  renderer.render(scene,camera);requestAnimationFrame(draw);
}pose();draw();
fetch('/api/checkpoint').then(r=>r.json()).then(build=>{expectedHash=build.gpu_material_source_sha256;$('build').textContent=`Build ${build.website_revision?.slice(0,7)} · ${build.gpu_material_source_verified&&build.gpu_source_verified&&!build.local_changes&&!build.restart_pending?'shared GPU laws verified':'source / restart unverified'}`;reset();}).catch(e=>$('build').textContent=e.message);
