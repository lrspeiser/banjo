// All screens render the authenticated server decision; links execute no work.
export function guidanceUrl(destination, data, current = location.href) {
  const source = new URL(current), url = new URL('/world', source.origin);
  for (const key of ['world','scene']) if (source.searchParams.has(key)) url.searchParams.set(key,source.searchParams.get(key));
  const screen=destination.screen || 'goals';
  if (screen!=='world') {url.searchParams.set('workshop','1');url.searchParams.set('tab',screen);}
  if (data.chain_id) url.searchParams.set('goal-chain',data.chain_id);
  if (data.goal?.id) url.searchParams.set('guide',data.goal.id);
  for (const key of ['focus','resource','job','ground']) if (destination[key]) url.searchParams.set(key,destination[key]);
  if (destination.selection) {
    const key={carried:'carry',recipe:'recipe',saved:'design',library:'library'}[destination.selection.source];
    if (key) url.searchParams.set(key,destination.selection.id);
  }
  if (destination.recipe && data.project) url.searchParams.set('recipe',
    data.project.saved_design_id || `${data.project.candidate.kind}:${destination.recipe}`);
  return url.pathname+url.search;
}

const adviceTurns=new WeakMap();
export function renderPlayerGuidance(root,data,api) {
  const prior=adviceTurns.get(root);if(prior?.timer)clearTimeout(prior.timer);
  const turn={};adviceTurns.set(root,turn);
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
    button.onclick=()=>dispatchEvent(new CustomEvent('banjo-guidance-clear'));root.append(button);
  }
  if(api && new URL(location.href).searchParams.has('world')) {
    const area=document.createElement('div');area.className='player-guide-tip';root.append(area);
    const current=()=>root.isConnected && adviceTurns.get(root)===turn;
    async function read(body={action:'request',event:'next-step'},polls=0) {
      try {
        const advice=await api('/api/world/assist',body);
        if(!current())return;
        // A response can describe a newer step than this rendered card. Leave
        // it for the next ordinary refresh instead of combining stale views.
        if(JSON.stringify(advice.next_action)!==JSON.stringify(data.next_action))return;
        area.replaceChildren();
        if(advice.status==='pending' && polls<16) {
          turn.timer=setTimeout(()=>read({action:'status',key:advice.key},polls+1),500);return;
        }
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
    read();
  }
}
