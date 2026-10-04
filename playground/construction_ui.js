// Saved placement intent uses ordinary authenticated actions and exact retries.
export function placementUrl(item,current=location.href) {
  const source=new URL(current),url=new URL('/world',source.origin);
  for(const key of ['world','scene'])if(source.searchParams.has(key))url.searchParams.set(key,source.searchParams.get(key));
  url.searchParams.set('place',item);return url.pathname+url.search;
}

export async function constructionWrite(api,scope,action,fields={},person=null) {
  const key=`banjo.construction-write.${scope}`;
  let pending;
  try {pending=JSON.parse(sessionStorage.getItem(key) || 'null');}catch {pending=null;}
  if(pending && (pending.action!==action || pending.item!==fields.item))
    throw Error('Retry your pending construction step before choosing another');
  if(!pending) {
    const current=await api('/api/world/construction',{action:'view'});
    pending={action,...fields,revision:current.revision,request_id:crypto.randomUUID()};
    sessionStorage.setItem(key,JSON.stringify(pending));
  }
  try {
    const answer=await api('/api/world/construction',{...pending,...(person?{person}: {})});
    sessionStorage.removeItem(key);return answer;
  }catch(error) {
    if(/Construction revision changed|Select your own item|Hold your selected item|Invalid construction|Open World to check|Walk closer to (view|fasten)|Place your (selected item|item on a support)|already fastened|not fastened/i.test(error.message))
      sessionStorage.removeItem(key);
    throw error;
  }
}

export function constructionControls(root,context,{hold,find,place,inspect,cancel,check,fasten,unfasten}) {
  const project=context?.project;if(!project)return;
  const link=root.querySelector('a.ws-action');if(link)link.remove();
  root.querySelector('[data-guidance-clear]')?.remove();
  const steps=document.createElement('ol');steps.className='construction-steps';steps.setAttribute('aria-label','Placement steps');
  // The current step is a link to doing it, the same as its button below.
  const does={prepare:check,hold,site:find,place,inspect};
  for(const step of project.steps || []) {
    const row=document.createElement('li');row.dataset.status=step.status;
    const text=`${step.status==='done'?'✓ ':''}${step.label}`;
    if(step.status==='current' && does[step.id] && project.status!=='Unavailable') {
      const go=document.createElement('a');go.href='#';go.textContent=text;go.dataset.step=step.id;
      go.onclick=async event=>{
        event.preventDefault();
        try {await does[step.id]();}catch(error){dispatchEvent(new CustomEvent('banjo-construction-error',{detail:error.message}));}
      };
      row.append(go);
    }else row.textContent=text;
    if(step.status==='current')row.setAttribute('aria-current','step');steps.append(row);
  }
  root.insertBefore(steps,root.querySelector('.player-guide-tip'));
  const actions=document.createElement('div');actions.className='construction-actions';
  const button=(label,run)=>{
    const b=document.createElement('button');b.type='button';b.textContent=label;b.className='ws-action';
    b.onclick=async()=>{
      b.disabled=true;b.blur();
      try {await run();}catch(error){dispatchEvent(new CustomEvent('banjo-construction-error',{detail:error.message}));}
      finally {if(b.isConnected)b.disabled=false;}
    };actions.append(b);return b;
  };
  if(project.status==='Prepare ground' && project.preparation) {
    // The marked squares are drawn on the ground in World; this says how
    // much to dig and with what, as the server read the ground just now.
    const note=document.createElement('p');note.className='construction-prepare';
    note.textContent=project.preparation.instruction;
    root.insertBefore(note,root.querySelector('.player-guide-tip'));
  }
  if(project.status==='Prepare ground')button(project.next_label,check);
  else if(project.status==='Equip')button(project.next_label,hold);
  else if(project.status==='Place')button('Place here',place);
  else if(project.status==='Placed')button(project.inspected?'View item':'View components and use',inspect);
  else if(project.status!=='Unavailable')button('Find a supported spot',find);
  if(project.status==='Place')button('Another location',find);
  // On a support it only rests there until it is fastened; fastened, it
  // goes with the support and holds what the weaker material does.
  if(project.status==='Placed' && project.support) {
    const held=project.fastened && !project.fastened.broken;
    if(held && unfasten)button('Unfasten from the '+project.support,unfasten);
    else if(fasten)button('Fasten to the '+project.support,fasten);
    if(project.fastened) {
      const note=document.createElement('p');note.className='construction-fastened';
      const kn=n=>(n/1000).toLocaleString(undefined,{maximumFractionDigits:1});
      note.textContent=project.fastened.broken
        ? `The fastening to the ${project.fastened.to} has come apart.`
        : `Fastened to the ${project.fastened.to}: holds ${kn(project.fastened.holds_tension_n)} kN pulling, `
          +`${kn(project.fastened.holds_shear_n)} kN sideways (${project.fastened.governed_by}, the weaker material).`;
      root.insertBefore(note,root.querySelector('.player-guide-tip'));
    }
  }
  button('Close build guide',cancel);root.insertBefore(actions,root.querySelector('.player-guide-tip'));
  if(project.status==='Placed' && project.operation) {
    const use=document.createElement('div');use.className='construction-use';
    const facts=document.createElement('dl');
    for(const [name,value] of [['Mode',project.operation.mode],['Light',project.operation.status],['Power',project.operation.power]]) {
      const label=document.createElement('dt'),reading=document.createElement('dd');
      label.textContent=name;reading.textContent=value;facts.append(label,reading);
    }
    const note=document.createElement('p');note.textContent=project.operation.instruction;
    use.append(facts,note);root.insertBefore(use,root.querySelector('.player-guide-tip'));
  }
}
