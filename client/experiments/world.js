import * as THREE from './three.module.js';

const $ = id => document.getElementById(id);
const canvas = $('world');
const renderer = new THREE.WebGLRenderer({canvas, antialias:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));
renderer.setClearColor(0x17242e);
const scene = new THREE.Scene();
scene.fog = new THREE.Fog(0x17242e,12,35);
scene.add(new THREE.HemisphereLight(0xd8e8ff,0x705b41,2.5));
const sun = new THREE.DirectionalLight(0xffedcf,3);sun.position.set(3,7,4);scene.add(sun);
const camera = new THREE.PerspectiveCamera(48,1,.02,60);
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const bodies = new Map();
const groundGroup = new THREE.Group();scene.add(groundGroup);
const avatar = new THREE.Mesh(new THREE.CylinderGeometry(.12,.12,1.7,24),
    new THREE.MeshStandardMaterial({color:0x60aac7,transparent:true,opacity:.6,roughness:.55}));
scene.add(avatar);
const ring = new THREE.Mesh(new THREE.BoxGeometry(.101,.012,.101),
    new THREE.MeshBasicMaterial({color:0x66e2a3,transparent:true,opacity:.6,depthTest:false}));
ring.visible=false;ring.renderOrder=4;scene.add(ring);
let session=null,state=null,terrain=null,ground=null,busy=false,closed=false;
let azimuth=.68,elevation=.6,distance=4.8,drag=null,hover=null,hoverKey='',preview=null;
let pollTimer=null,moveTimer=null,lastEvent='',removed=0,heading=0;
const keys=new Set();
let noticeTimer=null;
const colours={iron:0x929fab,glass:0x8ac8d9,oak:0xa67c45};
const names={handle:'Tool',head:'Tool head','glass-block':'Glass block','iron-block':'Iron block','tool-stand':'Tool stand'};

function say(text){
    clearTimeout(noticeTimer);$('notice').hidden=false;$('notice').textContent=text;
    noticeTimer=setTimeout(()=>{$('notice').hidden=true;},4000);
}
async function api(request){
    const response=await fetch('/api/world',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
    const result=await response.json();
    if(!response.ok)throw new Error(result.error || 'World request failed');
    return result;
}
function intent(action,extra={}){
    return {action,session,id:crypto.randomUUID().replaceAll('-',''),...extra};
}
function floats(encoded){
    const raw=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));
    const view=new DataView(raw.buffer), result=[];
    for(let i=0;i<raw.length;i+=4)result.push(view.getFloat32(i,true));
    return result;
}
function drawGround(value){
    if(!value || value.heights_b64===terrain?.heights_b64)return;
    const g=value.grid, heights=floats(value.heights_b64);
    if(heights.length!==g.nx*g.nz)throw new Error('Incomplete native terrain geometry');
    const materials=Uint8Array.from(atob(value.ground_b64),c=>c.charCodeAt(0));
    if(!ground){
        ground=new THREE.InstancedMesh(new THREE.BoxGeometry(1,1,1),new THREE.MeshStandardMaterial({roughness:1}),heights.length);
        ground.userData.ground=true;groundGroup.add(ground);
        const edges=new THREE.GridHelper(g.nx*g.cell_m,g.nx,0x73654f,0x73654f);
        edges.position.set((g.x0_m+(g.nx-1)*g.cell_m/2),heights[0]+.001,(g.z0_m+(g.nz-1)*g.cell_m/2));
        // This visual grid is removed after the first cut; native column edges
        // then provide the excavation boundary without a stale top overlay.
        edges.userData.initialGrid=true;groundGroup.add(edges);
    }else{
        const initial=groundGroup.children.find(c=>c.userData.initialGrid);
        if(initial){groundGroup.remove(initial);initial.geometry.dispose();initial.material.dispose();}
    }
    const transform=new THREE.Object3D();
    const floor=value.floor_m;
    for(let i=0;i<heights.length;i++){
        const h=Math.max(.001,heights[i]-floor);
        transform.position.set(g.x0_m+(i%g.nx)*g.cell_m,floor+h/2,g.z0_m+Math.floor(i/g.nx)*g.cell_m);
        transform.scale.set(g.cell_m,h,g.cell_m);transform.updateMatrix();ground.setMatrixAt(i,transform.matrix);
        const palette=[0x596271,0x887052,0xc6a975,0x78838d,0x516671,0x797780];
        const colour=new THREE.Color(palette[materials[i]] ?? 0x887052);
        colour.multiplyScalar(.93+.07*((i*17)%7)/6);ground.setColorAt(i,colour);
    }
    ground.instanceMatrix.needsUpdate=true;ground.instanceColor.needsUpdate=true;
    ground.computeBoundingSphere();terrain={...value,heights};
}
function disposeObject(object){
    object.traverse(child=>{child.geometry?.dispose();if(child.material)child.material.dispose();});
    scene.remove(object);
}
function shape(body){
    const d=body.dimensions_m;
    if(body.shape==='sphere')return new THREE.SphereGeometry(d[0]/2,24,16);
    if(body.shape==='cylinder')return new THREE.CylinderGeometry(d[0]/2,d[0]/2,d[1],24);
    // The sandbox fixtures are declared boxes. Refuse an unrendered shape
    // rather than draw a made-up cube for a native hull or compound.
    if(body.shape!=='box')throw new Error('Unsupported sandbox shape: '+body.shape);
    return new THREE.BoxGeometry(...d);
}
function consume(result){
    state=result.snapshot;
    if(!state)throw new Error('Missing native observation');
    drawGround(state.terrain);
    const alive=new Set();
    for(const body of state.bodies){
        alive.add(body.name);
        let mesh=bodies.get(body.name);
        if(!mesh){
            mesh=new THREE.Mesh(shape(body),new THREE.MeshStandardMaterial({color:colours[body.material] ?? 0x949ba0,
                metalness:body.material==='iron'?.55:0,roughness:.45}));
            mesh.userData.instance=body.name;scene.add(mesh);bodies.set(body.name,mesh);
        }
        mesh.position.fromArray(body.position_m);
        const [w,x,y,z]=body.orientation_wxyz;mesh.quaternion.set(x,y,z,w);
    }
    for(const [name,mesh] of bodies){if(!alive.has(name)){disposeObject(mesh);bodies.delete(name);}}
    const player=state.native_players.player;
    avatar.position.fromArray(player.position_m);
    const [w,x,y,z]=player.orientation_wxyz;avatar.quaternion.set(x,y,z,w);
    const holding=state.own_hand?.holding || '';
    $('holding').textContent=holding ? (holding==='handle'||holding==='head' ? $('family').selectedOptions[0].textContent : names[holding] || holding) : 'Empty';
    $('drop').disabled=!holding;
    $('clock').textContent=result.clock.simulation_s.toFixed(2)+' s';
    $('step').textContent=holding ? '2 · Click soil to use your tool' : '1 · Click the tool to pick it up';
    $('help').textContent=holding ? 'Click clear soil beside the stand. Green marks native reach and entry clearance, not guaranteed removal.' : 'The tool is on the stand to your right. Blocks can also be picked up and dropped.';
    for(const event of result.events || []){
        if(event.command_id===lastEvent)continue;
        // Events are returned cumulatively. Process each exactly once.
        if(seenEvents.has(event.command_id))continue;seenEvents.add(event.command_id);lastEvent=event.command_id;
        const tool=event.tool_use_result;
        if(tool){
            const litres=Object.values(tool.loosened_m3).reduce((a,b)=>a+b,0)*1000;
            removed+=litres;$('removed').textContent=removed.toFixed(2)+' L';
            say(litres>0 ? `Removed ${litres.toFixed(2)} L · ground updated from native geometry` : `No material removed · ${tool.reason || event.reason || tool.phase}`);
        }else say(event.status==='applied' ? 'Grip confirmed · tool is in your hand' : `Pickup refused · ${event.reason}`);
    }
    const outcome=result.outcome;
    if(outcome?.reason)say('Native response: '+outcome.reason);
    else if(outcome?.status==='pending')say(holding ? 'Tool working · waiting for measured result…' : 'Picking up · waiting for grip confirmation…');
    preview=result.preview ?? preview;
}
const seenEvents=new Set();
async function act(action,extra={}){
    if(!session)return;
    // A pointer intention must not disappear because a read is in flight.
    // Movement may retry on its next lease; deliberate clicks wait briefly.
    if(busy && action==='move')return;
    const intendedSession=session,deadline=performance.now()+2000;
    while(busy && performance.now()<deadline)await new Promise(resolve=>setTimeout(resolve,15));
    if(busy){say('World is busy · try again when the current response arrives');return;}
    if(session!==intendedSession)return;
    busy=true;
    try{consume(await api(intent(action,extra)));hoverKey='';}
    catch(error){say(error.message);}
    finally{busy=false;}
}
async function start(){
    if(busy)return;
    busy=true;clearTimeout(pollTimer);clearTimeout(moveTimer);keys.clear();
    try{
        if(session)await api({action:'close',session});session=null;
        const result=await api({action:'create',family:$('family').value,material:$('material').value});
        for(const mesh of bodies.values())disposeObject(mesh);bodies.clear();
        for(const child of [...groundGroup.children]){groundGroup.remove(child);child.geometry.dispose();child.material.dispose();}
        ground=null;terrain=null;hover=null;preview=null;hoverKey='';ring.visible=false;
        seenEvents.clear();removed=0;$('removed').textContent='0 L';
        session=result.session;consume(result);$('setup').hidden=true;$('settings').setAttribute('aria-expanded','false');
        say('Native world running · pick up the tool on the ground');
    }catch(error){say(error.message);$('step').textContent='World unavailable';}
    finally{busy=false;pollTimer=setTimeout(poll,120);moveTimer=setTimeout(move,140);}
}
async function poll(){
    if(closed)return;
    if(!busy && session){
        busy=true;
        try{consume(await api({action:'observe',session}));}
        catch(error){say(error.message);session=null;$('step').textContent='World stopped · choose New world';}
        finally{busy=false;}
    }
    pollTimer=setTimeout(poll,120);
}
async function move(){
    if(closed)return;
    const side=Number(keys.has('right'))-Number(keys.has('left'));
    const forward=Number(keys.has('forward'))-Number(keys.has('back'));
    if(!busy && session){
        const length=Math.hypot(side,forward)||1;
        const vx=(side*Math.cos(azimuth)-forward*Math.sin(azimuth))/length;
        const vz=(-side*Math.sin(azimuth)-forward*Math.cos(azimuth))/length;
        if(side || forward)heading=Math.atan2(vx,vz);
        // Native locomotion uses a short intent lease, including standing.
        // Renew the player's current intention; never assign body poses.
        await act('move',{velocity:[vx,0,vz],heading});
    }
    moveTimer=setTimeout(move,140);
}
function hit(event){
    const rect=canvas.getBoundingClientRect();
    pointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);
    raycaster.setFromCamera(pointer,camera);
    const hits=raycaster.intersectObjects([...bodies.values(),...(ground?[ground]:[])]);
    if(!hits.length)return null;
    const h=hits[0];
    if(h.object.userData.instance)return {instance:h.object.userData.instance,point:h.point.toArray()};
    const i=h.instanceId,g=terrain.grid;
    return {cell:i,point:[g.x0_m+i%g.nx*g.cell_m,terrain.heights[i],g.z0_m+Math.floor(i/g.nx)*g.cell_m]};
}
async function hoverAt(event){
    hover=hit(event);
    if(!hover){ring.visible=false;$('target').hidden=true;return;}
    $('target').hidden=false;
    if(hover.instance){
        ring.visible=false;$('target').textContent=names[hover.instance]+(hover.instance==='tool-stand'?' · Fixed support':' · Click to pick up');return;
    }
    ring.visible=true;ring.position.set(hover.point[0],hover.point[1]+.008,hover.point[2]);
    const key=String(hover.cell);
    if(key===hoverKey)return;
    if(busy)return;
    hoverKey=key;preview=null;ring.material.color.setHex(0x99a8b0);
    if(!state?.own_hand?.holding){$('target').textContent='Soil · pick up a tool first';return;}
    busy=true;
    try{
        const result=await api({action:'preview',session,target:hover.point});
        consume(result);
        if(hover?.cell!==Number(key))return;
        preview=result.preview;
        const ok=preview?.admitted && preview?.entry_clearance?.clear;
        ring.material.color.setHex(ok?0x66e2a3:0xf4a36a);
        $('target').textContent=ok ? 'Soil · reachable · Click to use' : 'Soil · '+(preview?.reason || preview?.entry_clearance?.obstruction?.kind || 'not ready');
    }catch(error){say(error.message);hoverKey='';}
    finally{busy=false;}
}
canvas.addEventListener('pointerdown',event=>{canvas.setPointerCapture(event.pointerId);drag={x:event.clientX,y:event.clientY,lastX:event.clientX,lastY:event.clientY,moved:false};hoverAt(event);});
canvas.addEventListener('pointermove',event=>{
    if(drag){
        if(Math.hypot(event.clientX-drag.x,event.clientY-drag.y)>8)drag.moved=true;
        if(drag.moved){azimuth-=(event.clientX-drag.lastX)*.008;elevation=Math.max(.15,Math.min(1.25,elevation+(event.clientY-drag.lastY)*.006));}
        drag.lastX=event.clientX;drag.lastY=event.clientY;
    }else hoverAt(event);
});
canvas.addEventListener('pointerup',event=>{
    const tapped=drag&&!drag.moved;drag=null;
    if(!tapped)return;
    // Use this pointer's screen hit, including touch, never a crosshair.
    const selected=hit(event);
    if(!selected)return;
    if(selected.instance==='tool-stand'){say('Fixed tool stand · click the tool above it');return;}
    if(selected.instance)act('pickup',{instance:selected.instance==='head'?'handle':selected.instance});
    else if(state?.own_hand?.holding)act('use',{target:selected.point});
    else say('Pick up a tool before using the ground');
});
canvas.addEventListener('pointercancel',()=>{drag=null;keys.clear();});
canvas.addEventListener('wheel',event=>{event.preventDefault();distance=Math.max(1.8,Math.min(9,distance+event.deltaY*.003));},{passive:false});
const binding={w:'forward',ArrowUp:'forward',s:'back',ArrowDown:'back',a:'left',ArrowLeft:'left',d:'right',ArrowRight:'right'};
addEventListener('keydown',event=>{if(event.target.closest('button,select'))return;const key=binding[event.key];if(key){event.preventDefault();keys.add(key);}});
addEventListener('keyup',event=>{if(binding[event.key])keys.delete(binding[event.key]);});
addEventListener('blur',()=>{keys.clear();drag=null;});
document.addEventListener('visibilitychange',()=>{if(document.hidden)keys.clear();});
for(const button of document.querySelectorAll('[data-move]')){
    button.addEventListener('pointerdown',event=>{event.preventDefault();button.setPointerCapture(event.pointerId);keys.add(button.dataset.move);button.classList.add('active');});
    for(const type of ['pointerup','pointercancel','lostpointercapture'])button.addEventListener(type,()=>{keys.delete(button.dataset.move);button.classList.remove('active');});
}
$('drop').addEventListener('click',()=>act('drop'));
$('zoom-in').addEventListener('click',()=>{distance=Math.max(1.8,distance-.6);});
$('zoom-out').addEventListener('click',()=>{distance=Math.min(9,distance+.6);});
$('settings').addEventListener('click',()=>{$('setup').hidden=!$('setup').hidden;$('settings').setAttribute('aria-expanded',String(!$('setup').hidden));});
$('restart').addEventListener('click',start);
addEventListener('pagehide',()=>{closed=true;clearTimeout(pollTimer);clearTimeout(moveTimer);if(session)fetch('/api/world',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'close',session}),keepalive:true}).catch(()=>{});});
function render(){
    const width=canvas.clientWidth,height=canvas.clientHeight;
    if(canvas.width!==Math.round(width*renderer.getPixelRatio()) || canvas.height!==Math.round(height*renderer.getPixelRatio())){
        renderer.setSize(width,height,false);camera.aspect=width/height;camera.updateProjectionMatrix();
    }
    const center=state ? new THREE.Vector3(...state.native_players.player.position_m).add(new THREE.Vector3(0,-.25,0)) : new THREE.Vector3(0,1,0);
    camera.position.copy(center).add(new THREE.Vector3(Math.sin(azimuth)*Math.cos(elevation)*distance,Math.sin(elevation)*distance,Math.cos(azimuth)*Math.cos(elevation)*distance));
    camera.lookAt(center);renderer.render(scene,camera);requestAnimationFrame(render);
}
render();start();
