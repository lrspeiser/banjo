import {validateContact,validateJob,type Check,type Job,type ContactRecording,type Vec} from "./hub-contract.js";
function element<T extends HTMLElement>(id:string):T{const el=document.getElementById(id);if(!el)throw Error(`Missing ${id}`);return el as T;}
const all=element<HTMLButtonElement>("all"),progress=element("progress"),cards=element("checks"),slider=element<HTMLInputElement>("frame"),play=element<HTMLButtonElement>("play");
const material=element<HTMLSelectElement>("material"),width=element<HTMLSelectElement>("width"),dt=element<HTMLSelectElement>("dt"),magnify=element<HTMLSelectElement>("magnify");
let catalog:Check[]=[],job:Job|null=null,recording:ContactRecording|null=null,frame=0,timer:ReturnType<typeof setInterval>|null=null;
let recordingId="",starting=false;
const fmt=(n:number)=>new Intl.NumberFormat(undefined,{maximumFractionDigits:3}).format(n);
function stop(){if(timer!==null)clearInterval(timer);timer=null;play.textContent="Play response";}
function renderChecks(){
  cards.replaceChildren();const busy=starting||job?.status==="running";all.disabled=busy;
  for(const c of catalog){
    const result=job?.checks.find(r=>r.id===c.id),card=document.createElement("article"),title=document.createElement("h2"),kind=document.createElement("p"),badge=document.createElement("span"),button=document.createElement("button");
    card.className="test-card";title.textContent=c.name;kind.textContent=c.kind;badge.className="result";
    badge.textContent=result?.status?.toUpperCase()??"NOT RUN";badge.dataset["status"]=result?.status??"not-run";
    button.textContent=c.id==="contact-gate"?"Run + record":"Run check";button.disabled=busy;button.addEventListener("click",()=>void start(c.id));
    card.append(badge,title,kind,button);
    if(result){const detail=document.createElement("details"),summary=document.createElement("summary"),log=document.createElement("pre"),identity=document.createElement("small");summary.textContent=`${fmt(result.elapsed_s??0)} s · View output`;log.textContent=result.output??"";identity.textContent=result.artifact_sha256?`Executable SHA256 ${result.artifact_sha256}`:"No executable result";detail.append(summary,log,identity);card.append(detail);}
    cards.append(card);
  }
  if(job){const pass=job.checks.filter(c=>c.status==="pass").length,fail=job.checks.filter(c=>c.status==="fail").length,other=job.checks.length-pass-fail;
    progress.textContent=job.status==="running"?`${job.checks.length}/${job.total} · Running ${job.current}…`:`${pass} passed · ${fail} failed · ${other} unavailable/errors. Run complete.`;
    document.body.dataset["execution"]=job.status;
  }
}
async function response(url:string,options?:RequestInit){const r=await fetch(url,{cache:"no-store",...options});if(!r.ok){const v:unknown=await r.json();throw Error(typeof v==="object"&&v&&"error"in v?String(v.error):`Request failed (${r.status})`);}return r;}
async function start(check:string){
  if(starting||job?.status==="running")return;
  starting=true;stop();renderChecks();progress.textContent="Starting isolated tests…";let failure="";
  try{const r=await response("api/tests",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({check})});job=validateJob(await r.json());recording=null;recordingId="";element("replay").hidden=true;element("jump").hidden=true;localStorage.setItem("banjo.testJob",job.id);renderChecks();void poll(job.id);}
  catch(error){failure=error instanceof Error?error.message:"Cannot start tests";}
  finally{starting=false;renderChecks();if(failure)progress.textContent=failure;}
}
async function poll(id:string){
  try{const r=await response(`api/tests/${id}`);job=validateJob(await r.json(),id);renderChecks();const result=job.checks.find(c=>c.recording_sha256);
    if(result?.recording_sha256&&recordingId!==id){
      const r=await response(`api/tests/${id}/recording`);const bytes=await r.arrayBuffer();if(bytes.byteLength>10_000_000)throw Error("Recording exceeds budget");
      const digest=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)),b=>b.toString(16).padStart(2,"0")).join("");
      if(digest!==result.recording_sha256)throw Error("Recording fingerprint mismatch");
      recording=validateContact(JSON.parse(new TextDecoder().decode(bytes)));recordingId=id;frame=0;element("replay").hidden=false;element("jump").hidden=false;renderReplay();
      element("identity").textContent=`Execution ${id} · recording SHA256 ${digest}. ${recording.open_convergence_gates} open convergence checks.`;
    }
    if(job.status==="running")setTimeout(()=>void poll(id),1000);
  }catch(error){job=null;localStorage.removeItem("banjo.testJob");renderChecks();progress.textContent=`Cannot inspect results: ${error instanceof Error?error.message:"invalid response"}. Run checks to try again; an active server job continues.`;}
}
const project=(v:Vec):[number,number]=>[.866*(v[0]-v[2]),.43*(v[0]+v[2])-v[1]];
function rotate(q:[number,number,number,number],v:Vec):Vec{
  const [w,x,y,z]=q,[a,b,c]=v;
  return [(1-2*(y*y+z*z))*a+2*(x*y-w*z)*b+2*(x*z+w*y)*c,2*(x*y+w*z)*a+(1-2*(x*x+z*z))*b+2*(y*z-w*x)*c,2*(x*z-w*y)*a+2*(y*z+w*x)*b+(1-2*(x*x+y*y))*c];
}
function renderReplay(){
  if(!recording)return;const run=recording.experiments.find(r=>r.material===material.value&&r.width_m===Number(width.value)&&r.dt_s===Number(dt.value));if(!run)return;
  frame=Math.min(frame,run.frames.length-1);const f=run.frames[frame],initial=run.frames[0];if(!f||!initial)return;
  slider.max=String(run.frames.length-1);slider.value=String(frame);element("time").textContent=`${fmt(f.time_s*1e6)} μs`;element("view").textContent=`${magnify.value}× displacement · dimensions unchanged · view only`;
  const canvas=element<HTMLCanvasElement>("contact"),ctx=canvas.getContext("2d");if(!ctx)return;
  const w=canvas.clientWidth,h=canvas.clientHeight,dpr=Math.min(devicePixelRatio,2);canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);ctx.scale(dpr,dpr);
  const scale=Math.min(w/0.7,h/0.38),gain=Number(magnify.value);
  const screen=(p:Vec):[number,number]=>{const [x,y]=project(p);return [w*.52+x*scale,h*.52+y*scale];};
  const enlarged=(p:Vec,start:Vec):Vec=>[start[0]+gain*(p[0]-start[0]),start[1]+gain*(p[1]-start[1]),start[2]+gain*(p[2]-start[2])];
  const positions=f.nodes.map(n=>screen(enlarged(n.position_m,initial.nodes[n.id]!.position_m)));
  ctx.strokeStyle="#527592";ctx.lineWidth=1;
  for(const [i,[a,b]] of run.bond_topology.entries()){if(!f.bond_state[i]?.[0])continue;const p=positions[a],q=positions[b];if(p&&q){ctx.beginPath();ctx.moveTo(...p);ctx.lineTo(...q);ctx.stroke();}}
  for(const n of f.nodes){const p=positions[n.id];if(!p)continue;ctx.fillStyle=n.clamped?"#dce4ef":n.attached?"#6dbaf5":"#ffbf70";ctx.beginPath();ctx.arc(...p,5,0,Math.PI*2);ctx.fill();}
  for(const [i,source] of f.source.entries()){
    const start=initial.source[i];if(!start)continue;const center=enlarged(source.position_m,start.position_m);
    const dims=source.id===1?[.08,run.width_m,.08]:[.24,.04,.04];
    const corners:Vec[]=[];for(const x of [-1,1])for(const y of [-1,1])for(const z of [-1,1]){const v=rotate(source.orientation_wxyz,[x*dims[0]!/2,y*dims[1]!/2,z*dims[2]!/2]);corners.push([center[0]+v[0],center[1]+v[1],center[2]+v[2]]);}
    ctx.strokeStyle=source.id===1?"#e1c0ff":"#a5b7cd";ctx.lineWidth=2;
    for(let a=0;a<8;a++)for(const mask of [1,2,4]){const b=a^mask;if(b<a)continue;ctx.beginPath();ctx.moveTo(...screen(corners[a]!));ctx.lineTo(...screen(corners[b]!));ctx.stroke();}
    const p=screen(center);ctx.fillStyle=ctx.strokeStyle;ctx.font="12px system-ui";ctx.fillText(source.id===1?"Iron head":"Lab handle",p[0]-25,p[1]-20);
  }
  canvas.setAttribute("aria-label",`${run.material}, ${f.broken_bonds} broken bonds, ${f.components} components, ${fmt(f.time_s*1e6)} microseconds, ${gain} times displacement view`);
  const metrics=element("metrics");metrics.replaceChildren();
  const free=f.nodes.filter(n=>!n.attached).reduce((sum,n)=>sum+n.mass_kg,0);
  for(const [name,value] of [["Broken bonds",String(f.broken_bonds)],["Components",String(f.components)],["Detached mass",`${fmt(free)} kg`],["Contacts (full run)",String(run.contacts)],["Numerical energy",`${f.integration_error_j.toExponential(2)} J`],["Attributed energy error (final)",`${run.attributed_energy_error_j.toExponential(2)} J`]]){
    const item=document.createElement("div"),label=document.createElement("span"),v=document.createElement("strong");label.textContent=name??"";v.textContent=value??"";item.append(label,v);metrics.append(item);
  }
  document.body.dataset["frame"]=String(frame);
}
all.addEventListener("click",()=>void start("all"));
for(const el of [material,width,dt,magnify])el.addEventListener("change",()=>{stop();renderReplay();});
slider.addEventListener("input",()=>{stop();frame=Number(slider.value);renderReplay();});
play.addEventListener("click",()=>{if(timer!==null){stop();return;}if(frame===Number(slider.max))frame=0;play.textContent="Pause response";renderReplay();timer=setInterval(()=>{frame++;renderReplay();if(frame>=Number(slider.max))stop();},180);});
window.addEventListener("resize",renderReplay);document.addEventListener("visibilitychange",()=>{if(document.hidden)stop();});
async function load(){try{const r=await response("api/tests"),v:unknown=await r.json();if(!v||typeof v!=="object"||!("checks"in v)||!Array.isArray(v.checks)||v.checks.length!==15)throw Error("Incomplete test catalog");
  catalog=v.checks.map((c:unknown)=>{if(!c||typeof c!=="object"||!("id"in c)||!("name"in c)||!("kind"in c)||typeof c.id!=="string"||typeof c.name!=="string"||typeof c.kind!=="string")throw Error("Invalid catalog entry");return {id:c.id,name:c.name,kind:c.kind};});
  renderChecks();progress.textContent="Choose Run checkpoint checks, or run one check below.";const id=localStorage.getItem("banjo.testJob");if(id&&/^[0-9a-f]{32}$/.test(id))void poll(id);
}catch(error){progress.textContent=error instanceof Error?error.message:"Tests unavailable";}}
void load();
