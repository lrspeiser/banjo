import * as THREE from './three.module.js';
import {worldGesture,moveWorldGesture,finishWorldGesture,worldUnavailable,connectedWorldParts} from './world-input.js';

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
let session=null,state=null,busy=false,closed=false,stopped=false;
let azimuth=.68,elevation=.6,distance=3.4,drag=null,hover=null,hoverKey='',preview=null;
let pollTimer=null,moveTimer=null,lastEvent='',heading=0;
const keys=new Set();
let noticeTimer=null,starting=false;
const colours={concrete:0x9c9a86,iron:0x929fab,glass:0x8ac8d9,oak:0xa67c45};
const outline=new THREE.Box3Helper(new THREE.Box3(),0x66e2a3);outline.visible=false;scene.add(outline);
let highlighted=[];
function highlight(parts,colour=0x66e2a3){
    for(const name of highlighted)bodies.get(name)?.traverse(child=>{if(child.material?.emissive)child.material.emissive.setHex(0);});
    highlighted=parts;outline.box.makeEmpty();
    for(const name of parts){const mesh=bodies.get(name);if(!mesh)continue;
        outline.box.expandByObject(mesh);
        mesh.traverse(child=>{if(child.material?.emissive)child.material.emissive.setHex(0x164d36);});
    }
    outline.visible=!outline.box.isEmpty();outline.material.color.setHex(colour);
}
let lastHitEnd='';
const refusal={out_of_reach:'Too far · move closer',not_holding:'Pick up a tool first',action_in_progress:'Tool is still working',no_contact:'The tool did not reach this target',unsupported_capability:'This item has no tool contact point',target_blocked:'Target blocks the tool path',insufficient_strength:'Too heavy for this hand',grip_released:'The grip was released'};
const label=name=>names[name] || (name.startsWith('grain-')?'Ground grain':name==='bedrock-base'?'Fixed base':name);
const names={handle:'Tool',head:'Tool head','glass-block':'Glass block','iron-block':'Iron block','tool-stand':'Tool stand'};

function say(text,persistent=false){
    clearTimeout(noticeTimer);$('notice').hidden=false;$('notice').textContent=text;
    if(!persistent)noticeTimer=setTimeout(()=>{$('notice').hidden=true;},4000);
}
async function api(request){
    const response=await fetch('/api/world',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
    const result=await response.json();
    if(!response.ok){const error=new Error(result.error || 'World request failed');error.code=result.code;throw error;}
    return result;
}
function intent(action,extra={}){
    return {action,session,id:crypto.randomUUID().replaceAll('-',''),...extra};
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
    const previousHolding=state?.own_hand?.holding,previousActive=state?.own_physical_hit?.active;
    state=result.snapshot;
    if(previousHolding!==state?.own_hand?.holding || previousActive!==state?.own_physical_hit?.active){hoverKey='';preview=null;}
    if(previousHolding!==state?.own_hand?.holding){hover=null;highlight([]);$('target').hidden=true;}
    if(!state)throw new Error('Missing native observation');
    const alive=new Set();
    const heldParts=new Set(state.own_hand?.held_parts || []);
    for(const body of state.bodies){
        alive.add(body.name);
        let mesh=bodies.get(body.name);
        if(!mesh){
            const parts=body.shape==='compound'?body.rigid_parts_local:[{...body,center_local_m:[0,0,0],rotation_wxyz:[1,0,0,0]}];
            if(!parts?.length)throw new Error('Missing native collision parts');
            mesh=new THREE.Group();
            for(const part of parts){
                const child=new THREE.Mesh(shape(part),new THREE.MeshStandardMaterial({color:colours[part.material] ?? 0x949ba0,
                    metalness:part.material==='iron'?.55:0,roughness:.65}));
                child.position.fromArray(part.center_local_m);const [w,x,y,z]=part.rotation_wxyz;child.quaternion.set(x,y,z,w);
                child.userData.instance=body.name;mesh.add(child);
            }
            mesh.userData.instance=body.name;scene.add(mesh);bodies.set(body.name,mesh);
        }
        mesh.position.fromArray(body.position_m);
        // Equipped custody is shown in the hand slot. The real native body
        // still collides; show its actual pose only during the contact action.
        mesh.visible=!heldParts.has(body.name) || !!state.own_physical_hit?.active;
        mesh.traverse(child=>{if(child.material){child.material.transparent=heldParts.has(body.name);child.material.opacity=heldParts.has(body.name)?.28:1;}});
        const [w,x,y,z]=body.orientation_wxyz;mesh.quaternion.set(x,y,z,w);
    }
    for(const [name,mesh] of bodies){if(!alive.has(name)){disposeObject(mesh);bodies.delete(name);}}
    const holding=state.own_hand?.holding || '';
    const configured=(state.tool_points || []).some(point=>heldParts.has(point.body));
    $('holding').textContent=holding ? (configured ? $('family').selectedOptions[0].textContent : names[holding] || holding) : 'Empty';
    $('drop').disabled=!holding;
    $('holding').parentElement.dataset.equipped=String(!!holding);
    $('clock').textContent=result.clock.simulation_s.toFixed(2)+' s';
    $('step').textContent=holding ? '2 · Click a grain or object to strike' : '1 · Click the tool to pick it up';
    $('help').textContent=holding ? 'Green means the hand can attempt this hit. Grains move through collision; solid fracture is unfinished.' : 'The tool is on the stand to your right. Loose grains and blocks can also be picked up.';
    const physical=state.own_physical_hit;
    if(physical){
        if(physical.active && !previousActive)say('Striking · native contact in progress');
        $('removed').textContent=physical.active?'Working…':physical.contacted?'Confirmed':'Missed';
        $('travel').textContent=(Math.hypot(...physical.target_displacement_m)*100).toFixed(1)+' cm';
        $('work').textContent=physical.hand_work_j.toFixed(2)+' J';
        const end=physical.started_s+':'+physical.ended_s;
        if(!physical.active && end!==lastHitEnd){lastHitEnd=end;say(physical.contacted?'Native contact · '+label(physical.target):refusal[physical.reason] || physical.reason || 'No contact measured');}
    }
    for(const event of result.events || []){
        if(event.command_id===lastEvent)continue;
        // Events are returned cumulatively. Process each exactly once.
        if(seenEvents.has(event.command_id))continue;seenEvents.add(event.command_id);lastEvent=event.command_id;
        say(event.status==='applied' ? 'Grip confirmed · item is in your hand' : `Pickup refused · ${refusal[event.reason] || event.reason}`,event.status!=='applied');
    }
    const outcome=result.outcome;
    if(outcome?.reason==='capacity_exceeded' || outcome?.reason==='kernel_unavailable'){
        stopWorld(new Error(outcome.reason==='capacity_exceeded' ? 'This bounded test session reached its input limit. Start a fresh test world.' : 'The native test world is unavailable. Start a fresh test world.'));
        return;
    }
    if(outcome?.reason)say(refusal[outcome.reason] || outcome.reason,true);
    else if(outcome?.status==='pending')say('Picking up · waiting for native grip confirmation…');
    preview=result.preview ?? preview;
}
const seenEvents=new Set();
function stopWorld(error){
    stopped=true;keys.clear();drag=null;hover=null;preview=null;highlight([]);
    $('target').hidden=true;$('drop').disabled=true;$('holding').textContent='Unavailable';
    $('step').textContent='Test world stopped';
    $('help').textContent='The scene shows the last observation. Start a fresh test world to pick up or use items.';
    $('paused-reason').textContent=error.message;
    $('paused').hidden=false;clearTimeout(noticeTimer);$('notice').hidden=true;
}
async function act(action,extra={}){
    if(!session || stopped){$('paused').hidden=false;return;}
    // A pointer intention must not disappear because a read is in flight.
    // Movement may retry on its next lease; deliberate clicks wait briefly.
    if(busy && action==='move')return;
    const intendedSession=session,deadline=performance.now()+2000;
    while(busy && performance.now()<deadline)await new Promise(resolve=>setTimeout(resolve,15));
    if(busy){say('World is busy · try again when the current response arrives');return;}
    if(session!==intendedSession)return;
    busy=true;
    try{consume(await api(intent(action,extra)));hoverKey='';}
    catch(error){if(worldUnavailable(error.code))stopWorld(error);else say(error.message,true);}
    finally{busy=false;}
}
async function start(){
    if(starting)return;
    starting=true;$('restart').disabled=true;
    const deadline=performance.now()+2000;
    while(busy && performance.now()<deadline)await new Promise(resolve=>setTimeout(resolve,15));
    if(busy){starting=false;$('restart').disabled=false;say('World is busy · try New world again');return;}
    busy=true;clearTimeout(pollTimer);clearTimeout(moveTimer);keys.clear();
    try{
        if(session)await api({action:'close',session});session=null;
        const result=await api({action:'create',family:$('family').value,material:$('material').value,model:'rigid-grains',ground_material:$('ground-material').value});
        for(const mesh of bodies.values())disposeObject(mesh);bodies.clear();
        hover=null;preview=null;hoverKey='';
        seenEvents.clear();lastHitEnd='';$('removed').textContent='—';$('travel').textContent='—';$('work').textContent='—';outline.visible=false;
        session=result.session;stopped=false;$('paused').hidden=true;consume(result);$('setup').hidden=true;$('settings').setAttribute('aria-expanded','false');
        say('Native world running · pick up the tool on the ground');
    }catch(error){stopWorld(error);}
    finally{busy=false;starting=false;$('restart').disabled=false;pollTimer=setTimeout(poll,120);moveTimer=setTimeout(move,140);}
}
async function poll(){
    if(closed)return;
    if(!busy && session && !stopped){
        busy=true;
        try{consume(await api({action:'observe',session}));}
        catch(error){stopWorld(error);}
        finally{busy=false;}
        if(hover && !preview)updateTarget();
    }
    pollTimer=setTimeout(poll,120);
}
async function move(){
    if(closed)return;
    const side=Number(keys.has('right'))-Number(keys.has('left'));
    const forward=Number(keys.has('forward'))-Number(keys.has('back'));
    if(!busy && session && !stopped){
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
    const held=state?.own_hand?.holding;
    const ignored=new Set(state?.own_hand?.held_parts || (held?[held]:[]));
    const hits=raycaster.intersectObjects([...bodies.entries()].filter(([name])=>!ignored.has(name)).map(([,mesh])=>mesh));
    const h=hits[0];
    const exact=h?.object.userData.instance ? {instance:h.object.userData.instance,point:h.point.toArray()} : null;
    if(held || (exact && !state.bodies.find(b=>b.name===exact.instance)?.anchored))return exact;
    // A configured assembly gets a modest screen selection halo. It changes
    // input acquisition only: the server still checks visibility and reach.
    const tested=new Set(),margin=event.pointerType==='touch'?18:10;
    for(const capability of state?.tool_points || []){
        if(!capability.attached || tested.has(capability.body))continue;
        const parts=connectedWorldParts(capability.body,state);parts.forEach(name=>tested.add(name));
        const box=new THREE.Box3();for(const name of parts){const mesh=bodies.get(name);if(mesh)box.expandByObject(mesh);}
        if(box.isEmpty())continue;
        let left=Infinity,right=-Infinity,top=Infinity,bottom=-Infinity;
        for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z]){
            const p=new THREE.Vector3(x,y,z).project(camera);if(p.z < -1 || p.z > 1)continue;
            const sx=rect.left+(p.x+1)*rect.width/2,sy=rect.top+(1-p.y)*rect.height/2;
            left=Math.min(left,sx);right=Math.max(right,sx);top=Math.min(top,sy);bottom=Math.max(bottom,sy);
        }
        if(event.clientX<left-margin || event.clientX>right+margin || event.clientY<top-margin || event.clientY>bottom+margin)continue;
        const root=parts.includes(capability.grip_body)?capability.grip_body:capability.body;
        const mesh=bodies.get(root);
        if(h && camera.position.distanceTo(mesh.position)>h.distance+.02)continue;
        return {instance:root,point:mesh.position.toArray()};
    }
    return exact;
}
async function hoverAt(event){hover=hit(event);return updateTarget();}
async function updateTarget(){
    if(stopped)return;
    if(!hover){highlight([]);$('target').hidden=true;return;}
    $('target').hidden=false;
    const body=state.bodies.find(b=>b.name===hover.instance);
    if(hover.instance)highlight(connectedWorldParts(hover.instance,state),0x99a8b0);
    const prefix=label(hover.instance || 'Ground')+' · '+(body?.material || 'soil')+(hover.instance?.startsWith('grain-')?' · 1 L':'');
    if(!state?.own_hand?.holding){
        if(!body?.anchored)outline.material.color.setHex(0x66e2a3);
        $('target').textContent=prefix+(body?.anchored?' · Fixed support':' · Click any highlighted part to equip');return;
    }
    const key=hover.instance || String(hover.cell);
    if(key!==hoverKey)preview=null;
    const verdict=preview?.admitted?'Click to strike':refusal[preview?.reason] || preview?.reason || 'Checking reach…';
    $('target').textContent=prefix+' · '+verdict;
    if(key===hoverKey && preview){outline.material.color.setHex(preview.admitted?0x66e2a3:0xf4a36a);return;}
    if(busy){$('target').textContent=prefix+' · Checking reach…';return;}
    hoverKey=key;preview=null;
    const target=hover.point;busy=true;
    try{
        const result=await api({action:'preview-hit',session,target});consume(result);
        if((hover?.instance || String(hover?.cell))!==key){preview=null;return;}
        preview=result.preview;outline.material.color.setHex(preview?.admitted?0x66e2a3:0xf4a36a);
        $('target').textContent=prefix+' · '+(preview?.admitted?'Click to strike':refusal[preview?.reason] || preview?.reason || 'Not ready');
    }catch(error){if(worldUnavailable(error.code))stopWorld(error);else say(error.message);hoverKey='';}
    finally{busy=false;}
}
canvas.addEventListener('pointerdown',event=>{
    if(stopped || drag)return;
    canvas.setPointerCapture(event.pointerId);drag=worldGesture(event,hit(event));hover=drag.selection;updateTarget();
});
canvas.addEventListener('pointermove',event=>{
    if(drag){
        if(!moveWorldGesture(drag,event))return;
        if(drag.moved){azimuth-=(event.clientX-drag.lastX)*.008;elevation=Math.max(.15,Math.min(1.25,elevation+(event.clientY-drag.lastY)*.006));}
        drag.lastX=event.clientX;drag.lastY=event.clientY;
    }else hoverAt(event);
});
canvas.addEventListener('pointerup',event=>{
    if(!drag || event.pointerId!==drag.pointerId)return;
    const selected=finishWorldGesture(drag,event);drag=null;
    // Retain this press's exact screen hit; release drift must not retarget it.
    if(!selected)return;
    if(state?.own_hand?.holding)act('hit',{target:selected.point});
    else if(selected.instance){
        const body=state.bodies.find(b=>b.name===selected.instance);
        if(body?.anchored){say('Fixed support · pick up a tool to hit it');return;}
        // Native admission resolves the connected assembly and declared grip.
        act('pickup',{instance:selected.instance});
    }else say('Pick up a tool first');
});
canvas.addEventListener('pointerleave',()=>{highlight([]);$('target').hidden=true;hoverKey='';preview=null;});
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
$('resume').addEventListener('click',start);
addEventListener('pagehide',()=>{closed=true;clearTimeout(pollTimer);clearTimeout(moveTimer);if(session)fetch('/api/world',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'close',session}),keepalive:true}).catch(()=>{});});
function render(){
    const width=canvas.clientWidth,height=canvas.clientHeight;
    if(canvas.width!==Math.round(width*renderer.getPixelRatio()) || canvas.height!==Math.round(height*renderer.getPixelRatio())){
        renderer.setSize(width,height,false);camera.aspect=width/height;camera.updateProjectionMatrix();
    }
    const center=state ? new THREE.Vector3(...state.native_players.player.position_m).add(new THREE.Vector3(0,-.25,0)) : new THREE.Vector3(0,1,0);
    camera.position.copy(center).add(new THREE.Vector3(Math.sin(azimuth)*Math.cos(elevation)*distance,Math.sin(elevation)*distance,Math.cos(azimuth)*Math.cos(elevation)*distance));
    camera.lookAt(center);
    if(highlighted.length){outline.box.makeEmpty();for(const name of highlighted){const mesh=bodies.get(name);if(mesh)outline.box.expandByObject(mesh);}}
    renderer.render(scene,camera);requestAnimationFrame(render);
}
render();start();
