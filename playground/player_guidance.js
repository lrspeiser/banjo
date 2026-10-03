// All screens render the authenticated server decision; links execute no work.
export function guidanceUrl(destination, data, current = location.href) {
  const source = new URL(current), url = new URL('/world', source.origin);
  for (const key of ['world','scene']) if (source.searchParams.has(key)) url.searchParams.set(key,source.searchParams.get(key));
  const screen=destination.screen || 'goals';
  if (screen!=='world') {url.searchParams.set('workshop','1');url.searchParams.set('tab',screen);}
  if (data.chain_id) url.searchParams.set('goal-chain',data.chain_id);
  if (data.goal?.id) url.searchParams.set('guide',data.goal.id);
  for (const key of ['focus','resource','job','ground','place']) if (destination[key]) url.searchParams.set(key,destination[key]);
  if (destination.selection) {
    const key={carried:'carry',recipe:'recipe',saved:'design',library:'library'}[destination.selection.source];
    if (key) url.searchParams.set(key,destination.selection.id);
  }
  if (destination.recipe && data.project) url.searchParams.set('recipe',
    data.project.saved_design_id || `${data.project.candidate.kind}:${destination.recipe}`);
  return url.pathname+url.search;
}

const adviceTurns=new WeakMap();
let activeGuideRoot=null;
addEventListener('keydown',event=>{
  if(event.key!=='F1' || event.repeat)return;
  const turn=activeGuideRoot?.isConnected && adviceTurns.get(activeGuideRoot);
  if(!turn?.ask)return;
  event.preventDefault();turn.ask.onclick();
});
function adviceContext(data) {
  const project=data.project || {},reading=data.build_readiness || {};
  const construction=data.construction_project?.project;
  // Match advice-bearing facts, excluding live clock, pose and meter updates.
  return JSON.stringify([data.next_action,project.focused ? null : data.goal?.id,
    project.name,project.candidate,project.focused,
    reading.status,reading.ready_to_start,reading.installation,
    construction && ['name','status','steps','installation','blocker'].map(k=>construction[k]),
    construction?.operation && ['mode','status','power','instruction'].map(k=>construction.operation[k]),data.limits]);
}
export function renderPlayerGuidance(root,data,api) {
  const prior=adviceTurns.get(root);
  const context=data?.next_action ? adviceContext(data) : null;
  const same=prior?.context===context;
  if(!same && prior?.timer)clearTimeout(prior.timer);
  const turn=same ? prior : {context,request:0,seenEvents:prior?.seenEvents || new Set()};
  adviceTurns.set(root,turn);
  activeGuideRoot=root;
  root.replaceChildren(); root.hidden=false;
  root.setAttribute('aria-label','Your next action');root.classList.add('player-guidance');
  root.setAttribute('role','region');
  if (!data?.next_action) {
    const note=document.createElement('strong');note.textContent='Next action unavailable';root.append(note);
    const link=document.createElement('a');link.className='ws-action';link.textContent='Open Goals';
    link.href=guidanceUrl({screen:'goals'},data || {});root.append(link);return;
  }
  const next=data.next_action;
  const title=document.createElement('strong');title.textContent=next.verb==='continue-build' ? 'Your workpiece'
    : data.project?.focused ? data.project.name : data.goal?.title || 'Explore';root.append(title);
  const link=document.createElement('a');link.className='ws-action';link.textContent=next.label;
  link.href=guidanceUrl(next.destination || {screen:'goals'},data);root.append(link);
  const blocked=(next.blockers || []).filter(Boolean);
  if (blocked.length) {const reason=document.createElement('p');reason.textContent=blocked[0];root.append(reason);}
  if (['build','review-project'].includes(next.verb) && data.build_readiness) {
    const label=document.createElement('p');label.textContent=`Workbench · ${data.build_readiness.status}`;root.append(label);
  }
  if (data.project?.focused) {
    const button=document.createElement('button');button.type='button';button.className='ws-action';button.textContent='Follow goals';
    button.dataset.guidanceClear='';
    button.onclick=()=>dispatchEvent(new CustomEvent('banjo-guidance-clear'));root.append(button);
  }
  if(api && new URL(location.href).searchParams.has('world')) {
    // Reattach the same tip node synchronously during ordinary card refreshes.
    // Its contents stay visible while the new read is in flight.
    const area=turn.area || document.createElement('div');turn.area=area;
    area.className='player-guide-tip';root.append(area);
    const current=()=>root.isConnected && adviceTurns.get(root)===turn;
    const project=data.construction_project?.project;
    const event=project ? project.status==='Placed'?'milestone':project.status==='Site changed'?'blocked':'placement' : 'next-step';
    async function read(body={action:'request',event},polls=0) {
      if(turn.timer) {clearTimeout(turn.timer);turn.timer=null;}
      const request=++turn.request;
      try {
        const advice=await api('/api/world/assist',body);
        if(!current() || request!==turn.request)return;
        // A response can describe a newer step than this rendered card. Leave
        // it for the next ordinary refresh instead of combining stale views.
        if(JSON.stringify(advice.next_action)!==JSON.stringify(data.next_action))return;
        if(turn.key && turn.key!==advice.key) {area.replaceChildren();turn.paint=null;}
        turn.key=advice.key;
        if(advice.status==='pending' && polls<16) {
          turn.timer=setTimeout(()=>read({action:'status',key:advice.key,
            ...(body.event==='asked'?{event:'asked'}:{})},polls+1),500);return;
        }
        // Temporary provider/network states do not erase valid advice for the
        // same observed task. Explicit preferences do; they also cancel polls.
        if(!['ready','quiet','dismissed'].includes(advice.status))return;
        if(turn.timer) {clearTimeout(turn.timer);turn.timer=null;}
        const paint=JSON.stringify([advice.key,advice.status,advice.text,advice.enabled]);
        if(turn.paint===paint)return;
        turn.paint=paint;area.replaceChildren();
        if(advice.status==='ready') {
          const label=document.createElement('small');label.textContent='AI Guide';area.append(label);
          const tip=document.createElement('p');tip.textContent=advice.text;area.append(tip);
          const hide=document.createElement('button');hide.type='button';hide.className='ws-action';hide.textContent='Hide tip';
          hide.onclick=()=>read({action:'dismiss',key:advice.key});area.append(hide);
        }
        if(advice.status==='ready' || advice.status==='quiet') {
          const quiet=document.createElement('button');quiet.type='button';quiet.className='ws-action';
          quiet.textContent=advice.enabled?'Quiet guide':'Enable guide';
          quiet.onclick=async()=>{
            await read({action:'settings',enabled:!advice.enabled});
            if(current() && !advice.enabled)await read();
          };area.append(quiet);
        }
      } catch { /* The verified action remains usable without the provider. */ }
    }
    const ask=turn.ask || document.createElement('button');turn.ask=ask;
    ask.type='button';ask.className='ws-action';ask.textContent='Ask AI · F1';
    ask.onclick=()=>read({action:'request',event:'asked'});root.append(ask);
    // Refreshing this card is a read, not a reason to call a model. Automatic
    // construction tips fire once per item/phase; ordinary exploration uses
    // an explicit click or F1. Status reads never launch provider work.
    if(!same) {
      const phase=project && `${project.item}:${project.status}`;
      const automatic=phase && !turn.seenEvents.has(phase);
      if(automatic) {
        turn.seenEvents.add(phase);
        if(turn.seenEvents.size>64)turn.seenEvents.delete(turn.seenEvents.values().next().value);
      }
      read({action:automatic?'request':'status',event});
    }
  }
}
