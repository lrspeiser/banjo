import * as THREE from '/three.module.js';
const $=id=>document.getElementById(id),view=$('view'),scene=new THREE.Scene();scene.background=new THREE.Color(0x0a171e);
const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));view.prepend(renderer.domElement);
const camera=new THREE.PerspectiveCamera(45,1,.001,100);scene.add(new THREE.HemisphereLight(0xe1faff,0x243340,2));
const light=new THREE.DirectionalLight(0xffffff,3);light.position.set(2,4,3);scene.add(light);
const group=new THREE.Group();scene.add(group);let data=null,index=0,detail=true,meshes=[],target=new THREE.Vector3(),distance=.4,azimuth=.7,elevation=.35,drag=null;
const colors={glass:0x9acfe3,oak:0xaf8960,iron:0xa0aab9,ice:0xb9e6fa};
function pose(){camera.position.copy(target).add(new THREE.Vector3(Math.sin(azimuth)*Math.cos(elevation)*distance,Math.sin(elevation)*distance,Math.cos(azimuth)*Math.cos(elevation)*distance));camera.lookAt(target);}
new ResizeObserver(()=>{camera.aspect=view.clientWidth/view.clientHeight;camera.updateProjectionMatrix();renderer.setSize(view.clientWidth,view.clientHeight);}).observe(view);
renderer.domElement.addEventListener('pointerdown',e=>{drag=[e.clientX,e.clientY];renderer.domElement.setPointerCapture(e.pointerId);});
renderer.domElement.addEventListener('pointermove',e=>{if(!drag)return;azimuth-=(e.clientX-drag[0])*.006;elevation=Math.max(-1.4,Math.min(1.4,elevation+(e.clientY-drag[1])*.006));drag=[e.clientX,e.clientY];pose();});
renderer.domElement.addEventListener('pointerup',()=>drag=null);renderer.domElement.addEventListener('pointercancel',()=>drag=null);
renderer.domElement.addEventListener('wheel',e=>{e.preventDefault();distance=Math.max(.004,Math.min(40,distance*Math.exp(e.deltaY*.001)));pose();},{passive:false});
function pair(name,value){const row=document.createElement('div'),dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=name;dd.textContent=value;row.append(dt,dd);$('results').append(row);}
function build(){for(const mesh of meshes){group.remove(mesh);mesh.geometry.dispose();mesh.material.dispose();for(const child of mesh.children){child.geometry.dispose();child.material.dispose();}}meshes=[];
  for(const c of data.definition.cells){const geometry=new THREE.BoxGeometry(...c.half_size_m.map(x=>2*x));const mesh=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color:colors[c.material],roughness:.55,metalness:c.material==='iron'?.3:0,polygonOffset:true,polygonOffsetFactor:1,polygonOffsetUnits:1}));
    mesh.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry),new THREE.LineBasicMaterial({color:0x122d38})));group.add(mesh);meshes.push(mesh);}
}
function display(){if(!data)return;const s=data.rigid_states[index],q=s.quaternion_wxyz;group.position.fromArray(s.position_m);group.quaternion.set(q[1],q[2],q[3],q[0]);
  for(const [i,c] of data.rigid_binding.cells.entries()){const m=meshes[i];m.position.fromArray(c.offset_m);const r=c.quaternion_local_wxyz;m.quaternion.set(r[1],r[2],r[3],r[0]);m.children[0].visible=detail;}
  $('drop-progress').textContent=s.time_s.toFixed(4)+' s · '+(detail?data.definition.cells.length+' retained elements':'1 rigid owner · same occupied geometry')+' · '+Math.abs(s.velocity_m_s[1]).toFixed(2)+' m/s';
  $('rigid').setAttribute('aria-pressed',String(!detail));$('detail').setAttribute('aria-pressed',String(detail));
}
function fit(){if(!data)return;target.fromArray(data.rigid_states[index].position_m);distance=data.definition.requested_geometry.radius_m*5;pose();}
async function compile(){if(!$('radius').reportValidity()||!$('height').reportValidity())return;$('compile').disabled=true;$('status').textContent='Compiling occupied matter and calculating conservative reference transfers…';
  try{const response=await fetch('/api/representation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({declaration:{material:$('material').value,radius_m:Number($('radius').value),level:Number($('level').value),height_m:Number($('height').value),frames:24}})});const result=await response.json();if(!response.ok||!result.ok)throw Error(result.error??'Representation reference refused');
    data=result;index=0;detail=true;build();display();fit();$('time').value='0';$('time').max=String(data.rigid_states.length-1);for(const id of ['time','initial','rigid','detail'])$(id).disabled=false;
    const d=data.definition,p=d.mass_properties,g=d.geometry,m=data.measured;$('results').replaceChildren();pair('Elements / interfaces',d.cells.length+' / '+d.interfaces.length);pair('Density',d.material_profile.density_kg_m3+' kg/m³');pair('Actual occupied mass',p.mass_kg.toFixed(4)+' kg');pair('Finest element', (g.finest_cell_m*1000).toFixed(2)+' mm');pair('Boundary error bound',(g.boundary_distance_bound_m*1000).toFixed(2)+' mm');pair('Sphere volume difference',(100*g.occupied_volume_error_m3/g.nominal_volume_m3).toFixed(2)+'%');pair('Transfer energy residual',data.transfer.mechanical_energy_residual_j.toExponential(2)+' J');pair('Flight energy residual',m.energy_residual_j.toExponential(2)+' J');pair('Calculated flight',m.physical_s.toFixed(3)+' s');pair('CPU calculation',m.wall_s.toFixed(3)+' s');
    $('build').textContent='Reference source '+result.source_sha256.slice(0,12);$('status').textContent='Calculated gravity-only flight and final expansion. Scrub the time slider; Rigid owner hides the element grid without replacing the occupied geometry. No impact is calculated.';
  }catch(e){$('status').textContent='Reference refused: '+e.message;}finally{$('compile').disabled=false;}
}
$('compile').addEventListener('click',compile);$('time').addEventListener('input',()=>{index=Number($('time').value);display();fit();});$('initial').addEventListener('click',()=>{index=0;$('time').value='0';display();fit();});
$('rigid').addEventListener('click',()=>{detail=false;display();});$('detail').addEventListener('click',()=>{index=data.rigid_states.length-1;$('time').value=String(index);detail=true;display();fit();});$('focus').addEventListener('click',fit);
$('cutaway').addEventListener('change',()=>{renderer.clippingPlanes=$('cutaway').checked?[new THREE.Plane(new THREE.Vector3(-1,0,0),0)]:[];});
$('flight-view').addEventListener('click',()=>{if(!data)return;target.set(0,data.rigid_states[0].position_m[1]/2,0);distance=Math.max(.4,data.rigid_states[0].position_m[1]*1.5);pose();});
async function frame(){renderer.render(scene,camera);requestAnimationFrame(frame);}pose();frame();
fetch('/api/checkpoint').then(r=>r.json()).then(c=>$('build').textContent='Build '+c.website_revision?.slice(0,8)).catch(()=>$('build').textContent='Build unavailable');
