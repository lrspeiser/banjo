import "/scene.js";
const $=id=>document.getElementById(id);
let token, catalog, runId="", report, viewer, serial=0, currentCase="", refreshing=null;
const active=()=>["starting","running"].includes(report?.status);
async function api(path,body){
 const r=await fetch(path,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json","X-Banjo-Token":token},body:JSON.stringify(body)});
 const d=await r.json();if(!r.ok||d.error)throw Error(d.error||"Request failed");return d;
}
const tell=e=>{$("progress").textContent=e.message||String(e);};
function option(select,value,text){const o=document.createElement("option");o.value=value;o.textContent=text;select.append(o);}
function controls(){for(const id of ["run-all","run-custom"])$(id).disabled=active()||!catalog?.engine_available;$("cancel").disabled=!active();}
function clear(){++serial;currentCase="";viewer?.dispose();viewer=null;$("stage").replaceChildren();$("checks").replaceChildren();$("failures").textContent=$("evidence").textContent=$("outcome").textContent="";$("play").disabled=$("frame").disabled=true;}
async function list(preferred){
 const selected=runId;const data=await api("/api/mechanics-qa/runs");if(runId!==selected)return;$("runs").replaceChildren();
 for(const r of data.runs)option($("runs"),r.id,new Date((r.started_unix_s||Date.now()/1000)*1000).toLocaleString()+" · "+r.completed+"/"+r.total+" · "+r.status);
 runId=preferred||runId||data.runs.find(r=>r.total===catalog.cases.length)?.id||data.runs[0]?.id||"";$("runs").value=runId;
}
async function inspect(id){
 const request=++serial,run=runId;currentCase=id;
 viewer?.dispose();viewer=null;$("stage").replaceChildren();$("checks").replaceChildren();$("play").disabled=$("frame").disabled=true;
 $("outcome").textContent="Loading recorded result…";$("failures").textContent=$("evidence").textContent="";
 const r=await api("/api/mechanics-qa/runs/"+run+"/"+id);
 if(request!==serial||run!==runId)return;
 $("case-title").textContent=r.title;
 $("outcome").textContent=(report.kind==="custom"?"Authored checks: ":"Regression checks: ")+r.status;
 $("outcome").className=r.status;
 for(const c of r.checks||[]){const tr=document.createElement("tr");for(const text of [(c.body?c.body+" · ":"")+c.metric,Number(c.value).toPrecision(6),c.min+" … "+c.max,c.passed?"Pass":"FAIL"]){const td=document.createElement("td");td.textContent=text;tr.append(td);}tr.className=c.passed?"passed":"failed";$("checks").append(tr);}
 $("failures").textContent=r.error||((r.joints||[]).filter(j=>!j.attached).map(j=>j.a+" → "+j.b+": "+j.parted_because).join("\n"));
 $("evidence").textContent=JSON.stringify({measured:r.measured,limits:r.limitations,provenance:report.provenance,request_hash:r.request_hash},null,2);
 const playback=await api("/api/mechanics-qa/runs/"+run+"/"+id+"/playback");
 if(request!==serial||run!==runId||!playback.frames?.length)return;
 viewer=window.BanjoScene.create($("stage"),{frameAllPoses:true,onFrame:({index,frame})=>{$("frame").value=index;$("clock").textContent=Number(frame.time_s).toFixed(3)+" s";},onPlayState:playing=>{$("play").textContent=playing?"Pause":"Play";}});
 viewer.load(playback);viewer.setSpeed(Number($("speed").value));
 $("frame").max=playback.frames.length-1;$("play").disabled=$("frame").disabled=false;
}
async function refresh(){
 if(!runId||refreshing===runId)return;const id=runId;refreshing=id;
 try{const next=await api("/api/mechanics-qa/runs/"+id);if(id!==runId)return;const wasActive=active();report=next;
 if(wasActive&&!active())await list(id);if(id!==runId)return;
 $("progress").textContent=report.completed+"/"+report.total+" · "+report.status+(report.kind==="custom"?" · custom experiment":" · regression suite")+(report.error?" · "+report.error:"");
 $("case").replaceChildren();for(const c of report.results||[])option($("case"),c.id,c.title+" · "+c.status);
 if(currentCase)$("case").value=currentCase;
 controls();if(!currentCase&&report.results?.length)await inspect(report.results[0].id);
 }finally{if(refreshing===id)refreshing=null;}
}
async function start(body){const r=await api("/api/mechanics-qa/run",body);clear();report=r;runId=r.id;await list(runId);await refresh();controls();}
$("example").onchange=()=>{$("recipe").value=JSON.stringify(catalog.cases.find(c=>c.id===$("example").value).document,null,2);$("validation").textContent="";};
$("run-all").onclick=()=>start({}).catch(tell);
$("run-custom").onclick=()=>{try{start({document:JSON.parse($("recipe").value)}).catch(tell);}catch(e){tell(e);}};
$("validate").onclick=async()=>{try{await api("/api/mechanics-qa/validate",{document:JSON.parse($("recipe").value)});$("validation").textContent="Valid recipe. Run it to measure the physical result.";}catch(e){$("validation").textContent=e.message;}};
$("cancel").onclick=()=>api("/api/mechanics-qa/cancel",{run_id:runId}).then(()=>{$("cancel").disabled=true;}).catch(tell);
$("runs").onchange=()=>{clear();runId=$("runs").value;refresh().catch(tell);};
$("case").onchange=()=>inspect($("case").value).catch(tell);
$("play").onclick=()=>{if(viewer.frame===viewer.frameCount-1)viewer.reset();viewer.play();};
$("frame").oninput=()=>viewer?.setFrame(Number($("frame").value));
$("speed").onchange=()=>viewer?.setSpeed(Number($("speed").value));
try{token=(await api("/api/status")).csrf_token;catalog=await api("/api/mechanics-qa");
for(const c of catalog.cases)option($("example"),c.id,c.group+" · "+c.document.title);
$("example").onchange();await list();await refresh();controls();
if(!runId)$("progress").textContent="Choose a recipe or run the regression suite.";
setInterval(()=>{if(active()||report?.status==="unattached")refresh().catch(tell);},1000);
}catch(e){tell(e);}

$("ask").onsubmit=async event=>{
 event.preventDefault();const button=$("ask-send");button.disabled=true;
 $("validation").textContent="The lab assistant is editing the recipe…";
 try{const answer=await api("/api/mechanics-qa/plan",{message:$("ask-text").value,document:JSON.parse($("recipe").value)});
 if(answer.document)$("recipe").value=JSON.stringify(answer.document,null,2);
 $("validation").textContent=answer.explanation+(answer.document?" Recipe validated; run it to measure the result.":"");
 }catch(e){$("validation").textContent=e.message;}finally{button.disabled=false;}
};

try {
 const c=await api("/api/gameplay/capabilities");
 $("capability-count").textContent=c.counts.complete+"/30 complete · "+c.counts.partial+" partial · "+c.counts.planned+" planned";
 for(const item of c.items){const tr=document.createElement("tr");
 for(const text of [item.workstream,item.id+". "+item.name,item.status,item.remaining+(item.evidence?" Evidence: "+item.evidence:"")]){
 const td=document.createElement("td");td.textContent=text;tr.append(td);}
 $("capabilities").append(tr);}
}catch(e){$("capability-count").textContent=e.message;}
