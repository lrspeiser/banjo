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
const avatar = new THREE.Mesh(new THREE.CylinderGeometry(.12,.12,1.7,24),
    new THREE.MeshStandardMaterial({color:0x60aac7,transparent:true,opacity:.6,roughness:.55}));
scene.add(avatar);
let session=null,state=null,busy=false,closed=false;
let azimuth=.68,elevation=.6,distance=3.4,drag=null,hover=null,hoverKey='',preview=null;
let pollTimer=null,moveTimer=null,lastEvent='',heading=0;
const keys=new Set();
let noticeTimer=null,starting=false;
const colours={concrete:0x9c9a86,iron:0x929fab,glass:0x8ac8d9,oak:0xa67c45};
const outline=new THREE.BoxHelper(new THREE.Mesh(new THREE.BoxGeometry(1,1,1)),0x66e2a3);outline.visible=false;scene.add(outline);
let lastHitEnd='';
const refusal={out_of_reach:'Too far · move closer',not_holding:'Pick up a tool first',action_in_progress:'Tool is still working',no_contact:'The tool did not reach this target',unsupported_capability:'This item has no tool contact point',target_blocked:'Target blocks the tool path',insufficient_strength:'Too heavy for this hand',grip_released:'The grip was released'};
const label=name=>names[name] || (name.startsWith('grain-')?'Ground grain':name==='bedrock-base'?'Fixed base':name);
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
    if(!state)throw new Error('Missing native observation');
    const alive=new Set();
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
    $('step').textContent=holding ? '2 · Click a grain or object to strike' : '1 · Click the tool to pick it up';
    $('help').textContent=holding ? 'Green means the hand can attempt this hit. Grains move through collision; solid fracture is unfinished.' : 'The tool is on the stand to your right. Loose grains and blocks can also be picked up.';
    const physical=state.own_physical_hit;
    if(physical){
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
        say(event.status==='applied' ? 'Grip confirmed · item is in your hand' : `Pickup refused · ${refusal[event.reason] || event.reason}`);
    }
    const outcome=result.outcome;
    if(outcome?.reason)say(refusal[outcome.reason] || outcome.reason);
    else if(outcome?.status==='pending')say('Picking up · waiting for native grip confirmation…');
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
        session=result.session;consume(result);$('setup').hidden=true;$('settings').setAttribute('aria-expanded','false');
        say('Native world running · pick up the tool on the ground');
    }catch(error){say(error.message);$('step').textContent='World unavailable';}
    finally{busy=false;starting=false;$('restart').disabled=false;pollTimer=setTimeout(poll,120);moveTimer=setTimeout(move,140);}
}
async function poll(){
    if(closed)return;
    if(!busy && session){
        busy=true;
        try{consume(await api({action:'observe',session}));}
        catch(error){say(error.message);session=null;$('step').textContent='World stopped · choose New world';}
        finally{busy=false;}
        if(hover && !preview)updateTarget();
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
    const held=state?.own_hand?.holding;
    const ignored=new Set(state?.own_hand?.held_parts || (held?[held]:[]));
    const hits=raycaster.intersectObjects([...bodies.entries()].filter(([name])=>!ignored.has(name)).map(([,mesh])=>mesh));
    if(!hits.length)return null;
    const h=hits[0];
    if(h.object.userData.instance)return {instance:h.object.userData.instance,point:h.point.toArray()};
    return null;
}
async function hoverAt(event){hover=hit(event);return updateTarget();}
async function updateTarget(){
    if(!hover){outline.visible=false;$('target').hidden=true;return;}
    $('target').hidden=false;
    const body=state.bodies.find(b=>b.name===hover.instance);
    if(hover.instance){outline.setFromObject(bodies.get(hover.instance));outline.visible=true;outline.material.color.setHex(0x99a8b0);}
    const prefix=label(hover.instance || 'Ground')+' · '+(body?.material || 'soil')+(hover.instance?.startsWith('grain-')?' · 1 L':'');
    if(!state?.own_hand?.holding){$('target').textContent=prefix+(body?.anchored?' · Fixed support':' · Click to pick up');return;}
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
    if(state?.own_hand?.holding)act('hit',{target:selected.point});
    else if(selected.instance){
        const body=state.bodies.find(b=>b.name===selected.instance);
        if(body?.anchored){say('Fixed support · pick up a tool to hit it');return;}
        act('pickup',{instance:selected.instance==='head'?'handle':selected.instance});
    }else say('Pick up a tool first');
});
canvas.addEventListener('pointerleave',()=>{outline.visible=false;$('target').hidden=true;hoverKey='';preview=null;});
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
