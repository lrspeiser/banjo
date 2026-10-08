import * as THREE from '/three.module.js';
const $=id=>document.getElementById(id), canvas=$('scene');
const renderer=new THREE.WebGLRenderer({canvas,antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setClearColor(0x111a24);
const scene=new THREE.Scene();scene.add(new THREE.HemisphereLight(0xbddcff,0x3e4033,2.5));const light=new THREE.DirectionalLight(0xffffff,3);light.position.set(2,6,4);scene.add(light);
const camera=new THREE.PerspectiveCamera(42,1,.005,50), overview=new THREE.PerspectiveCamera(35,1,.01,50);overview.position.set(2.8,6,4);overview.lookAt(0,5.4,0);
let yaw=.7,pitch=.36,radius=1.2,whole=false;const target=new THREE.Vector3(0,.43,0);
const colors={glass:0x98d9ed,ice:0xd5eefb,iron:0xaeb9c9,aluminum:0xdbe1e6,ceramic:0xd6a78e,oak:0xad8b64,concrete:0x536575};
let groups=[],state=null,initial=null,session=null,running=false,busy=false,showBefore=false,sequence=0;
const nativeRoot=new THREE.Group();scene.add(nativeRoot);
const marker=new THREE.Mesh(new THREE.RingGeometry(.013,.017,32),new THREE.MeshBasicMaterial({color:0xb2ea78,side:THREE.DoubleSide}));marker.rotation.x=-Math.PI/2;scene.add(marker);
let aim=[0,0];
const matrix=new THREE.Matrix4(),q=new THREE.Quaternion(),pos=new THREE.Vector3(),scale=new THREE.Vector3();
function layout(s){for(const g of groups){nativeRoot.remove(g.mesh);g.mesh.geometry.dispose();g.mesh.material.dispose();}groups=[];
 const buckets=new Map();for(const c of s.cells){const key=[c.material,...c.size_m].join(':');if(!buckets.has(key))buckets.set(key,[]);buckets.get(key).push(c);}
 for(const cells of buckets.values()){const c=cells[0];const geometry=new THREE.BoxGeometry(1,1,1);const mesh=new THREE.InstancedMesh(geometry,new THREE.MeshStandardMaterial({color:0xffffff,roughness:.6,metalness:c.material==='iron'?.5:.05}),cells.length);nativeRoot.add(mesh);groups.push({mesh,ids:cells.map(x=>x.id)});}
}
function draw(s){if(!s)return;const cells=new Map(s.cells.map(c=>[c.id,c]));
 for(const g of groups){g.ids.forEach((id,i)=>{const c=cells.get(id);pos.fromArray(c.position_m);const [w,x,y,z]=c.quaternion_wxyz;q.set(x,y,z,w);scale.fromArray(c.size_m);matrix.compose(pos,q,scale);g.mesh.setMatrixAt(i,matrix);const color=new THREE.Color(colors[c.material]??0xffffff);color.multiplyScalar(.88+.12*((c.id*17)%11)/10);g.mesh.setColorAt(i,color);});g.mesh.instanceMatrix.needsUpdate=true;g.mesh.instanceColor.needsUpdate=true;g.mesh.computeBoundingSphere();}
 marker.position.set(aim[0],.501+Number($('thickness').value),aim[1]);marker.visible=s.time_s===0;
 const sheet=s.objects.find(x=>x.id===1),ball=s.objects.find(x=>x.id===2);$('time').textContent=s.time_s.toFixed(3)+' s';$('pieces').textContent=sheet.pieces+' / '+sheet.cells+' voxels';$('faces').textContent=sheet.broken_faces;$('speed').textContent=Math.hypot(...ball.velocity_m_s).toFixed(2)+' m/s';$('ballpieces').textContent=ball.pieces+' / '+ball.cells+' voxels';$('count').textContent=s.cells.length+' native cells · '+s.substeps+' accepted substeps';
 const d=s.diagnostics;$('audit').textContent=`Retained dynamic mass ${d.dynamic_mass_kg.toFixed(5)} kg · KE ${d.kinetic_j.toFixed(3)} J · elastic ${d.elastic_j.toFixed(3)} J · unclosed energy ${d.unclosed_energy_j.toFixed(3)} J · rejected trials ${s.rejected_trials}`;
 canvas.dataset.time=s.time_s;canvas.dataset.nativeCells=s.cells.length;canvas.dataset.sheetPieces=sheet.pieces;
}
function updateCamera(){target.set(0,whole?4.8:.43,0);const r=whole?13:radius;camera.position.set(target.x+r*Math.cos(pitch)*Math.sin(yaw),target.y+r*Math.sin(pitch),target.z+r*Math.cos(pitch)*Math.cos(yaw));camera.lookAt(target);}
function render(){const w=canvas.clientWidth,h=canvas.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();updateCamera();renderer.setViewport(0,0,w,h);renderer.setScissorTest(false);renderer.render(scene,camera);
 if(!whole&&w>850){const ih=Math.min(190,h*.25),iw=110;renderer.setScissorTest(true);renderer.setScissor(w-iw-22,h-ih-250,iw,ih);renderer.setViewport(w-iw-22,h-ih-250,iw,ih);overview.aspect=iw/ih;overview.updateProjectionMatrix();renderer.render(scene,overview);renderer.setScissorTest(false);}
 requestAnimationFrame(render);
}
async function request(command){const response=await fetch('/api/world',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(command)});const r=await response.json();if(r.state){state=r.state;if(!showBefore&&command.op!=='create')draw(state);}if(!r.ok)throw Error(r.error);return r;}
function controls(){for(const id of ['sheet','thickness','resolution','gap','ball','mass','height','reset'])$(id).disabled=busy||running;$('drop').disabled=(!running&&busy)||!session||showBefore||state?.time_s>=2;$('step').disabled=busy||running||!session||showBefore||state?.time_s>=2;$('before').disabled=busy||!initial||running;$('live').disabled=busy||!state||running;$('drop').textContent=running?'Pause':'Drop ball';}
async function reset(){if(busy)return;busy=true;running=false;showBefore=false;controls();$('phase').textContent='Building native scene…';const generation=++sequence;
 try{if(session)await request({op:'close',session});session=null;const declaration={sheet:$('sheet').value,ball:$('ball').value,mass_kg:Number($('mass').value),height_m:Number($('height').value),thickness_m:Number($('thickness').value),resolution:Number($('resolution').value),support_gap_m:Number($('gap').value),offset_x_m:aim[0],offset_z_m:aim[1]};const r=await request({op:'create',declaration});if(generation!==sequence)return;session=r.session;initial=structuredClone(state);layout(state);draw(state);$('phase').textContent='Ready · '+(9.81*declaration.mass_kg*declaration.height_m).toFixed(1)+' J drop';$('log').href='/api/log/'+session;}
 catch(e){$('phase').textContent='Stopped · '+e.message;}finally{busy=false;controls();}
}
async function advance(){if(busy||!session)return;busy=true;controls();const start=performance.now();
 try{await request({op:'advance',session,steps:16});$('phase').textContent=state.time_s>=2?'Drop complete':state.objects[0].broken_faces?'Fracture · native cells moving':'Running native physics';if(state.time_s>=2)running=false;}
 catch(e){running=false;$('phase').textContent='Stopped · '+e.message;}finally{busy=false;controls();if(running)setTimeout(advance,Math.max(0,16-(performance.now()-start)));}
}
$('drop').onclick=()=>{running=!running;controls();if(running)advance();};$('step').onclick=advance;$('reset').onclick=reset;
$('before').onclick=()=>{showBefore=true;draw(initial);$('phase').textContent='Before · starting state';controls();};$('live').onclick=()=>{showBefore=false;draw(state);$('phase').textContent=state.time_s>=2?'Drop complete':'Live · accepted native state';controls();};
$('view').onclick=()=>{whole=!whole;$('view').textContent=whole?'Impact close-up':'Whole rig';};
for(const id of ['sheet','thickness','resolution','gap','ball','mass','height'])$(id).onchange=reset;
let press=null;canvas.addEventListener('pointerdown',e=>{press={x:e.clientX,y:e.clientY,yaw,pitch,moved:false};canvas.setPointerCapture(e.pointerId);});canvas.addEventListener('pointermove',e=>{if(!press)return;const dx=e.clientX-press.x,dy=e.clientY-press.y;if(Math.hypot(dx,dy)>5)press.moved=true;if(press.moved){yaw=press.yaw-dx*.008;pitch=Math.max(.04,Math.min(1.4,press.pitch+dy*.006));}});
canvas.addEventListener('pointerup',e=>{if(!press)return;const clicked=!press.moved;press=null;if(!clicked||busy||running)return;const r=canvas.getBoundingClientRect(),ray=new THREE.Raycaster();ray.setFromCamera(new THREE.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),camera);const hit=ray.intersectObjects(groups.map(g=>g.mesh)).find(h=>state.cells.find(c=>c.id===groups.find(g=>g.mesh===h.object).ids[h.instanceId])?.object===1);if(hit){aim=[Math.max(-.19,Math.min(.19,hit.point.x)),Math.max(-.19,Math.min(.19,hit.point.z))];reset();}});
canvas.addEventListener('wheel',e=>{e.preventDefault();radius=Math.max(.45,Math.min(3,radius*Math.exp(e.deltaY*.001)));},{passive:false});
window.addEventListener('pagehide',()=>{if(session)fetch('/api/world',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({op:'close',session}),keepalive:true});});
render();reset();
