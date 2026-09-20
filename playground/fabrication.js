import "/scene.js";
const $=id=>document.getElementById(id);
const requestedScene=new URLSearchParams(location.search).get("scene")||"fabrication";
const roomName=/^[a-z][a-z0-9_-]{0,63}$/.test(requestedScene)?requestedScene:"fabrication";
const pendingKey=roomName==="fabrication"?"banjo-fabrication-pending":"banjo-fabrication-pending:"+roomName;
const roomLabel=roomName==="world"?"Main world":roomName==="fabrication"?"Fabrication room":roomName;
$("room-label").textContent=roomLabel+" - manufacturing";
$("connect").textContent="Connect to "+roomLabel.toLowerCase();
for(const link of document.querySelectorAll("[data-return-world]"))link.href="/world?scene="+encodeURIComponent(roomName);
if(roomName==="world"){$("place-x").value=13;$("place-z").value=-7;}

let token, session="", state=null, preview=null, busy=false, viewer=null, cellSize=.04;
let carriedGround={};
let pending={};
try{pending=JSON.parse(sessionStorage.getItem(pendingKey)||"{}");if(!pending||Array.isArray(pending)||typeof pending!=="object")pending={};}catch{pending={};}
const fmt=(n,d=3)=>Number(n).toLocaleString(undefined,{maximumFractionDigits:d});
async function api(path,body){
 const r=await fetch(path,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json","X-Banjo-Token":token},body:JSON.stringify(body)});
 const d=await r.json();if(!r.ok||d.error){const e=Error(d.error||"Request failed");e.definitive=r.status>=400&&r.status<500;throw e;}return d;
}
const context=()=>({session,scene:roomName});
async function command(op,body={},retry=false){
 const key=op;let payload=body;
 if(retry){payload=pending[key]||{...body,request_id:crypto.randomUUID()};pending[key]=payload;sessionStorage.setItem(pendingKey,JSON.stringify(pending));}
 try{const answer=await api("/api/world/fabrication/"+op,{...context(),...payload});
 if(retry){delete pending[key];sessionStorage.setItem(pendingKey,JSON.stringify(pending));}
 if(answer.ground_audit){const a=answer.ground_audit;$("ground-audit").textContent=JSON.stringify(a,null,2);$("ground-balance").textContent=a.status==="unavailable"?"No terrain balance available.":a.status!=="matched"?"Material transfer mismatch: inspect the balance.":Object.values(a.substances).some(r=>r.collection_status!=="balanced")?"Stored transfers match; excavation has outside or untracked material. Inspect the balance.":"Sand and soil transfers match their native source accounts.";}
 if(answer.carried_ground){carriedGround=answer.carried_ground;$("carried-ground").textContent="Carrying "+fmt(carriedGround.sand_kg||0)+" kg sand and "+fmt(carriedGround.soil_kg||0)+" kg soil.";}
 if(answer.cell_m)cellSize=answer.cell_m;if(answer.session)session=answer.session;if(answer.state)render(answer.state);if(answer.native)draw(answer.native);return answer;
 }catch(e){if(retry&&e.definitive){delete pending[key];sessionStorage.setItem(pendingKey,JSON.stringify(pending));}throw e;}
}
function controls(){
 $("store-ground").disabled=busy||!session||!state||(!pending.store_ground&&!(carriedGround.sand_m3>0)&&!(carriedGround.soil_m3>0));
 for(const id of ["refresh","configure","quote","start","wait-one","wait-ten","preview","commit"])$(id).disabled=busy||!session;
 $("connect").disabled=busy;
 $("configure").disabled||=!!state;
 for(const id of ["quote","start","wait-one","wait-ten"])$(id).disabled||=!state;
 $("preview").disabled||=!$("finished").value;
 $("commit").disabled||=!preview;
 for(const b of document.querySelectorAll("#jobs button, #stocks button"))b.disabled=busy;
}
function render(s){
 state=s;$("setup").open=!state;$("setup-note").textContent="Initial stock and energy are fixed. Workpieces, heat and remaining supply survive leaving the room.";
 $("meters").textContent="World "+fmt(s.time_s)+" s · Supply "+fmt(s.energy_j)+" J · Station "+fmt(s.temperature_k-273.15,2)+" °C";
 $("stocks").replaceChildren();
 $("raw-lots").replaceChildren();
 const raw={};for(const lot of Object.values(s.raw_lots||{}))for(const item of lot.contents)raw[item.substance]=(raw[item.substance]||0)+item.mass_kg;
 for(const [substance,mass] of Object.entries(raw)){const p=document.createElement("p");p.textContent=fmt(mass)+" kg "+substance+" stored, unprocessed";$("raw-lots").append(p);}
 for(const material of Object.keys(s.stock_kg)){const tr=document.createElement("tr");for(const text of [material,fmt(s.stock_kg[material])+" kg",fmt(s.waste_kg[material]||0)+" kg",fmt(s.transferred_kg[material]||0)+" kg"]){const td=document.createElement("td");td.textContent=text;tr.append(td);}const recover=document.createElement("td");
 if((s.waste_kg[material]||0)>0){const b=document.createElement("button");b.textContent="Recover "+material+" offcuts";b.onclick=()=>run(async()=>{preview=null;await command("recover",{material,mass_kg:state.waste_kg[material],revision:state.revision},true);},"Offcuts returned to stock. Spent work and energy are retained.");recover.append(b);}tr.append(recover);$("stocks").append(tr);}
 const selected=$("finished").value;$("finished").replaceChildren();$("jobs").replaceChildren();
 for(const [id,j] of Object.entries(s.jobs)){
 const card=document.createElement("article");card.className="workpiece";const title=document.createElement("strong");title.textContent=j.material+" · "+j.condition;
 const progress=document.createElement("progress");progress.max=1;progress.value=j.fraction;
 const detail=document.createElement("p");detail.textContent=fmt(j.work_j)+" / "+fmt(j.required_j)+" J of work · "+fmt(j.product_kg)+" kg part · "+id.slice(0,8);
 card.append(title,progress,detail);
 if(["running","paused"].includes(j.status)){const button=document.createElement("button");button.textContent=j.status==="running"?"Pause":"Resume";button.onclick=()=>run(async()=>{preview=null;await command(j.status==="running"?"pause":"resume",{job_id:id,revision:state.revision},true);},"Workpiece retained.");card.append(button);}
 $("jobs").append(card);
 if(j.status==="ready"){const o=document.createElement("option");o.value=id;o.textContent=j.material+" · "+fmt(j.product_kg)+" kg · "+id.slice(0,8);$("finished").append(o);}
 }
 if([...$("finished").options].some(o=>o.value===selected))$("finished").value=selected;
 $("audit").textContent=JSON.stringify(s.audit,null,2);controls();
}
function draw(native){
 const bodies=(native.bodies||[]).filter(b=>!b.anchored&&b.name!=="marker stone");
 if(!bodies.length)return;
 viewer?.dispose();$("stage").replaceChildren();viewer=window.BanjoScene.create($("stage"),{frameAllPoses:true});viewer.loadLive(bodies,0,cellSize);
}
async function run(fn,done="Done."){
 if(busy)return;busy=true;controls();$("message").textContent="Working…";
 try{await fn();$("message").textContent=done;}catch(e){$("message").textContent=e.message;}finally{busy=false;controls();}
}
function design(){
 const size=[$("width"),$("height"),$("depth")].map(e=>Number(e.value));
 $("candidate").value=JSON.stringify({kind:"custom",parameters:{primary_use:{label:"Push",steps:[{do:"push_forward",distance_m:.2,speed_m_s:.4}]}},
 component_overrides:{"@construction":{added:[{name:"part",role:"panel",family:"panel",shape:"box",size_m:size,center_m:[0,size[1]/2,0],rotation_deg:[0,0,0],material:$("material").value}],joints_authored:true}}},null,2);
 $("quote-result").textContent="";
}
$("settings").value=JSON.stringify({mode:"authoring",stock_kg:{oak:50,glass:50,iron:50},energy_j:50000,power_w:250,work_j_kg:100,efficiency:1,heat_capacity_j_k:10000,cooling_w_k:5,max_temperature_k:393.15},null,2);
$("design").onclick=design;$("material").onchange=design;design();
$("connect").onclick=()=>run(async()=>{const n=await api("/api/world/open",{scene:roomName});if(n.scene!==roomName)throw Error("The requested room was not opened; no manufacturing changes were made.");session=n.session;preview=null;draw(n);const r=await command("state");if(!r.configured){state=null;controls();}},roomLabel+" connected. This page advances time only when requested; another open world view may also advance it.");
$("refresh").onclick=()=>run(async()=>{preview=null;await command("state");draw(await api("/api/live/act",{session,op:"poses"}));},"Current state read.");
$("configure").onclick=()=>run(()=>command("configure",{settings:JSON.parse($("settings").value)},true),"Initial resources declared.");
$("store-ground").onclick=()=>run(async()=>{preview=null;await command("store_ground",{sand_m3:carriedGround.sand_m3||0,soil_m3:carriedGround.soil_m3||0,revision:state.revision},true);await command("state");draw(await api("/api/live/act",{session,op:"poses"}));},"Raw material and the source world saved together.");
const recipe=()=>({candidate:JSON.parse($("candidate").value),stock_kg:Number($("stock").value)});
$("quote").onclick=()=>run(async()=>{const r=await command("quote",recipe());const q=r.quote;$("quote-result").textContent=fmt(q.product_kg)+" kg part + "+fmt(q.offcut_kg)+" kg offcuts\n"+fmt(q.required_j)+" J work; at least "+fmt(q.minimum_duration_s)+" s\n"+(r.affordable?"Stock available.":"Insufficient stock.");},"Quote checked without spending stock.");
$("start").onclick=()=>run(async()=>{preview=null;await command("start",{...recipe(),revision:state.revision},true);},"Stock reserved. Advance world time to do work.");
for(const [id,seconds] of [["wait-one",1],["wait-ten",10]])$(id).onclick=()=>run(async()=>{preview=null;await command("wait",{seconds});},"Native physics and manufacturing advanced and saved.");
$("preview").onclick=()=>run(async()=>{preview=await command("preview",{job_id:$("finished").value,position_m:[Number($("place-x").value),Number($("place-z").value)]});$("placement").textContent="Clear native placement: "+fmt(preview.mass_kg)+" kg at "+preview.applied_translation_m.map(v=>fmt(v)).join(", ")+" m. Keep time paused until placing.";},"Native placement checked.");
$("finished").onchange=$("place-x").oninput=$("place-z").oninput=()=>{preview=null;controls();};
$("commit").onclick=()=>run(async()=>{const r=await command("commit",{job_id:preview.fabrication_job_id,preview_id:preview.preview_id},true);preview=null;session=r.session;await command("state");draw(await api("/api/live/act",{session,op:"poses"}));$("placement").textContent="Installed "+r.root_body+"; material transfer and native world saved together.";},"Finished part is in the native world.");
try{token=(await api("/api/status")).csrf_token;controls();}catch(e){$("message").textContent=e.message;}
let qaId="",qaTimer;
function qaReport(r){
 $("qa-status").textContent=r.status+" · "+(r.completed||0)+" / "+(r.total||"pending")+" checks"+(r.error?" · "+r.error:"");
 $("qa-report").textContent=JSON.stringify(r,null,2);
 const active=["starting","running","cancelling"].includes(r.status);$("qa-cancel").disabled=!active;$("qa-run").disabled=active;
 if(!active)$("qa-details").open=true;
 return active;
}
async function qaPoll(){
 clearTimeout(qaTimer);
 try{if(qaReport(await api("/api/fabrication-qa/runs/"+qaId)))qaTimer=setTimeout(qaPoll,1000);}
 catch(e){$("qa-status").textContent=e.message;$("qa-run").disabled=false;}
}
$("qa-run").onclick=async()=>{
 $("qa-run").disabled=true;
 try{const r=await api("/api/fabrication-qa/run",{});qaId=r.id;qaReport(r);qaTimer=setTimeout(qaPoll,300);}
 catch(e){$("qa-status").textContent=e.message;$("qa-run").disabled=false;}
};
$("qa-cancel").onclick=async()=>{try{qaReport(await api("/api/fabrication-qa/cancel",{run_id:qaId}));}catch(e){$("qa-status").textContent=e.message;}};
$("qa-history").onclick=async()=>{
 try{const r=await api("/api/fabrication-qa/runs");$("qa-runs").replaceChildren();
 for(const run of r.runs){const b=document.createElement("button");b.textContent=run.status+" · "+run.id.slice(0,8);b.onclick=()=>{qaId=run.id;qaPoll();};$("qa-runs").append(b);}
 if(!r.runs.length)$("qa-status").textContent="No recorded runs yet.";
 }catch(e){$("qa-status").textContent=e.message;}
};
window.addEventListener("pagehide",()=>clearTimeout(qaTimer));
