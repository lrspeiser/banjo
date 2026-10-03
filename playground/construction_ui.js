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
    if(/Construction revision changed|Select your own item|Hold your selected item|Invalid construction|Open World to check|Walk closer to view|Place your selected item/i.test(error.message))
      sessionStorage.removeItem(key);
    throw error;
  }
}

export function constructionControls(root,context,{hold,find,place,inspect,cancel}) {
  const project=context?.project;if(!project)return;
  const link=root.querySelector('a.ws-action');if(link)link.remove();
  root.querySelector('[data-guidance-clear]')?.remove();
  const steps=document.createElement('ol');steps.className='construction-steps';steps.setAttribute('aria-label','Placement steps');
  for(const step of project.steps || []) {
    const row=document.createElement('li');row.dataset.status=step.status;
    row.textContent=`${step.status==='done'?'✓ ':''}${step.label}`;
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
  if(project.status==='Equip')button(project.next_label,hold);
  else if(project.status==='Place')button('Place here',place);
  else if(project.status==='Placed')button(project.inspected?'View item':'View components and use',inspect);
  else if(project.status!=='Unavailable')button('Find a supported spot',find);
  if(project.status==='Place')button('Another location',find);
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
