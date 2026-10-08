import * as THREE from './three.module.js';
import {brokenBondSegments,describeSheet} from './sheet-observation.js';
const names=['iron','aluminum','glass','ceramic','oak','rubber','ice','concrete'];
const colors=[0x889baa,0xc9d0d4,0x68bbd2,0xe7d9c1,0xae794d,0x45465a,0x91d7ef,0xada397];
const $=id=>document.getElementById(id), canvas=$('view'),renderer=new THREE.WebGLRenderer({canvas,antialias:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));const scene=new THREE.Scene();scene.background=new THREE.Color(0x101923);
const camera=new THREE.PerspectiveCamera(38,1,.001,2);camera.position.set(0,.3,.23);camera.lookAt(0,0,0);
scene.add(new THREE.HemisphereLight(0xffffff,0x465d7a,2));const light=new THREE.DirectionalLight(0xffffff,3);light.position.set(.1,.3,.15);scene.add(light);
const geometry=new THREE.BoxGeometry(.002,.002,.002),dummy=new THREE.Object3D();
const specimens=names.map((name,k)=>{
 const offset=new THREE.Vector3((k%4-1.5)*.065,.03,(Math.floor(k/4)-.5)*.085);
 const standMaterial=new THREE.MeshStandardMaterial({color:0x505f6b,roughness:.8});
 for(const x of [-.022,.022])for(const z of [-.022,.022]){const post=new THREE.Mesh(new THREE.BoxGeometry(.003,.03,.003),standMaterial);post.position.set(offset.x+x,.014,offset.z+z);scene.add(post);}
 for(const x of [-.021,.021]){const rail=new THREE.Mesh(new THREE.BoxGeometry(.003,.003,.046),standMaterial);rail.position.set(offset.x+x,.029,offset.z);scene.add(rail);}
 for(const z of [-.021,.021]){const rail=new THREE.Mesh(new THREE.BoxGeometry(.046,.003,.003),standMaterial);rail.position.set(offset.x,.029,offset.z+z);scene.add(rail);}
 const material=new THREE.MeshStandardMaterial({color:0xffffff,roughness:.55,metalness:k<2?.6:0});
 const cells=new THREE.InstancedMesh(geometry,material,800);cells.position.copy(offset);scene.add(cells);
 const cracks=new THREE.LineSegments(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:0xff5656,depthTest:false,transparent:true,opacity:.9}));cracks.position.copy(offset);cracks.renderOrder=2;scene.add(cracks);
 const label=document.createElement('button');label.className='label';label.textContent=name; $('labels').append(label);
 const s={name,offset,cells,cracks,label,session:null,state:null,everHit:false,failure:''};label.onclick=()=>select(s);resetDrawing(s);return s;
});
const ground=new THREE.Mesh(new THREE.PlaneGeometry(.29,.20),new THREE.MeshStandardMaterial({color:0x293440,roughness:1}));ground.rotation.x=-Math.PI/2;ground.position.y=-.002;scene.add(ground);
function resetDrawing(s){for(let z=0;z<20;z++)for(let y=0;y<2;y++)for(let x=0;x<20;x++){const index=x+20*(y+2*z);dummy.position.set(-.019+x*.002,-.001+y*.002,-.019+z*.002);dummy.updateMatrix();s.cells.setMatrixAt(index,dummy.matrix);s.cells.setColorAt(index,new THREE.Color(colors[names.indexOf(s.name)]));}s.cells.instanceMatrix.needsUpdate=true;s.cells.instanceColor.needsUpdate=true;s.cells.computeBoundingSphere();}
for(const name of names){const o=document.createElement('option');o.value=name;o.textContent=name;$('pick').append(o);}
let active=null,running=false,busy=false,version=0,focused=false;
function frameCamera(){const scale=Math.max(1,(focused?.06:.31)/((focused?.065:.26)*camera.aspect));const target=focused&&active?active.offset:new THREE.Vector3(0,.02,0);camera.position.copy(target).add(new THREE.Vector3(0,(focused?.065:.3)*scale,(focused?.048:.23)*scale));camera.lookAt(target);camera.updateProjectionMatrix();}
$('inspect').onclick=()=>{focused=true;frameCamera();};$('all').onclick=()=>{focused=false;frameCamera();};
function message(text){$('message').textContent=text;}
function show(s){active=s;$('selected').textContent=s.name;const v=s.state;
 for(const item of specimens)item.label.setAttribute('aria-pressed',String(item===s));
 $('ball-world').href='drop.html?sheet='+encodeURIComponent(s.name)+'&ball='+encodeURIComponent($('pick').value);
 $('response').textContent=v?describeSheet(v,s.failure):'No impact has been simulated. Run the reference to begin.';
 const entries=[['Material',s.name],['Cells','800 · 20 × 2 × 20'],['Cell edge','2 mm'],['Sheet','40 × 40 × 4 mm'],...(v?[['Pick mass',(v.source[0].mass_kg*1000).toFixed(3)+' g'],['Initial energy',v.initial_energy_j.toPrecision(4)+' J'],['Broken bonds',v.broken_bonds],['Detached cells',v.detached_cells],['Clear probes',v.open_columns],['Displacement',(v.max_displacement_m*1000).toFixed(2)+' mm'],['Plastic extension',(v.max_plastic_extension_m*1e6).toFixed(2)+' µm'],['Simulated time',(v.time_s*1e6).toFixed(1)+' µs'],['Steps',v.steps],['Energy residual',v.energy_residual_j.toExponential(2)+' J']]:[['State','Unstruck']])];
 $('metrics').replaceChildren(...entries.map(([name,value])=>{const row=document.createElement('div');row.className='metric';const n=document.createElement('span'),val=document.createElement('strong');n.textContent=name;val.textContent=value;row.append(n,val);return row;}));
}
function select(s){if(running||busy){message('Pause and wait for the current native batch before selecting another specimen.');return;}show(s);if(focused)frameCamera();message(s.everHit?'Selected '+s.name+' · resume its recorded state with Continue, or reset.':'Selected '+s.name+' · Run starts the 6 m/s pick reference. No ball has been dropped.');}
function apply(s,v){s.state=v;v.positions.forEach((p,k)=>{dummy.position.set(p[0],p[1],p[2]);dummy.updateMatrix();s.cells.setMatrixAt(k,dummy.matrix);s.cells.setColorAt(k,new THREE.Color(p[3]?0xffa451:colors[names.indexOf(s.name)]));});s.cells.instanceMatrix.needsUpdate=true;if(s.cells.instanceColor)s.cells.instanceColor.needsUpdate=true;s.cells.computeBoundingSphere();s.cracks.geometry.dispose();s.cracks.geometry=new THREE.BufferGeometry();s.cracks.geometry.setAttribute('position',new THREE.Float32BufferAttribute(brokenBondSegments(v),3));s.cracks.visible=$('bonds').checked;show(s);}
async function request(v){const response=await fetch('/api/sheets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(v)});const result=await response.json();if(!response.ok)throw Error(result.error||'Sheet request failed');return result;}
async function run(s,token){while(running&&token===version&&s.session){busy=true;try{message('Computing next native batch…');const r=await request({op:'advance',session:s.session});if(token!==version)return;if(r.state)apply(s,r.state);if(!r.ok)throw Error(r.error);if(r.state.steps>=60000){running=false;message('Reference step limit reached. This is not a complete drop or settled-fragment result.');break;}message('Native batch received · '+(r.state.time_s*1e6).toFixed(1)+' µs simulated.');}catch(e){running=false;s.failure=e.message;show(s);message('Native contact stopped; last accepted state retained. '+e.message);}finally{busy=false;}}}
canvas.addEventListener('pointerup',async event=>{
 if(busy){message('Impact is still being computed. Pause to inspect.');return;}
 const rect=canvas.getBoundingClientRect(),ray=new THREE.Raycaster();ray.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,1-(event.clientY-rect.top)/rect.height*2),camera);
 const hits=ray.intersectObjects(specimens.map(s=>s.cells));if(!hits.length){message('Choose a sheet or its material name.');return;}const hit=hits[0],s=specimens.find(s=>s.cells===hit.object);select(s);
});
$('strike').onclick=async()=>{if(busy||!active||active.everHit){message('Select an unstruck sheet, or pause and reset it first.');return;}const s=active,token=++version;busy=true;try{message('Starting the explicit centre reference…');const r=await request({op:'create',material:s.name,pick:$('pick').value,point_m:[0,0,0]});if(!r.ok)throw Error(r.error);s.session=r.session;s.everHit=true;apply(s,r.state);running=true;}catch(e){message(e.message);}finally{busy=false;}if(running)run(s,token);};
$('stop').onclick=()=>{if(!running)return;running=false;message('Pausing after the current native batch.');};
$('continue').onclick=()=>{if(active?.session&&!busy&&!running){running=true;run(active,version);}};
$('reset').onclick=async()=>{if(busy){message('Pause and wait for the current batch before resetting.');return;}if(!active)return;running=false;++version;const s=active;busy=true;try{if(s.session)await request({op:'close',session:s.session});s.session=null;s.state=null;s.everHit=false;s.failure='';s.cracks.geometry.dispose();s.cracks.geometry=new THREE.BufferGeometry();resetDrawing(s);show(s);message('Unstruck specimen restored. Run starts the explicit centre reference.');}catch(e){message(e.message);}finally{busy=false;}};
$('bonds').onchange=()=>{for(const s of specimens)s.cracks.visible=$('bonds').checked;};
$('pick').onchange=()=>{show(active);message('Pick selected. Reset an existing specimen before changing its striker.');};
function draw(){const rect=canvas.getBoundingClientRect();if(canvas.width!==Math.round(rect.width*renderer.getPixelRatio())||canvas.height!==Math.round(rect.height*renderer.getPixelRatio())){renderer.setSize(rect.width,rect.height,false);camera.aspect=rect.width/rect.height;frameCamera();}for(const s of specimens){s.label.hidden=focused&&s!==active;const p=s.offset.clone().add(new THREE.Vector3(0,0,.031)).project(camera);s.label.style.left=Math.max(24,Math.min(rect.width-24,(p.x*.5+.5)*rect.width))+'px';s.label.style.top=Math.max(24,Math.min(rect.height-50,(-p.y*.5+.5)*rect.height))+'px';}renderer.render(scene,camera);requestAnimationFrame(draw);}show(specimens[2]);draw();
