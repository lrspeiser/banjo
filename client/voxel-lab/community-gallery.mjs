import {preview} from './design-gallery.mjs';

// Only text and locally constructed SVG geometry are rendered from publications.
export function renderCommunity({box, request, openCourse, openSandbox}) {
  const doc=box.ownerDocument;
  const el=(tag,props={})=>Object.assign(doc.createElement(tag),props);
  const head=el('div',{className:'ls-head'});
  head.append(el('h1',{textContent:'Community'}));
  const back=el('button',{type:'button',textContent:'My Sandbox'});back.onclick=openSandbox;head.append(back);
  const intro=el('p',{textContent:'Run a shared course, or copy one to your Sandbox and make it your own.'});
  const form=el('form',{className:'community-search'});
  const search=el('input',{type:'search',placeholder:'Find a course',maxLength:80});search.setAttribute('aria-label','Find a course');
  const submit=el('button',{type:'submit',textContent:'Search'});form.append(search,submit);
  const status=el('p',{role:'status',textContent:'Loading courses…'});
  const list=el('div',{className:'ls-list design-gallery-list'});list.id='community-courses';
  const more=el('button',{type:'button',textContent:'Load more',hidden:true});
  box.replaceChildren(head,intro,form,status,list,more);
  let cursor=null,query='',epoch=0;
  const load=async(reset=false)=>{
    const serial=++epoch;more.disabled=true;submit.disabled=true;
    if(reset){cursor=null;list.replaceChildren();}
    status.textContent='Loading courses…';
    try{
      const result=await request({op:'browse',cursor,query});
      if(serial!==epoch||!box.contains(list))return;
      for(const course of result.courses){
        const card=el('button',{type:'button',className:'ls-card design-card'});
        card.setAttribute('aria-label',`Run course ${course.name}`);
        card.append(preview(doc,course.preview||course.draft),el('strong',{textContent:course.name}),
          el('span',{className:'teaches',textContent:course.description||'Shared course'}),
          el('span',{className:'community-card-action',textContent:'Run or copy →'}));
        card.onclick=async()=>{card.disabled=true;try{await openCourse(course.id);}catch(error){status.textContent=error.message;}finally{card.disabled=false;}};
        list.append(card);
      }
      cursor=result.next_cursor;more.hidden=!cursor;
      status.textContent=list.childElementCount?'':query?'No matching courses.':'No public courses yet. Open a design in Sandbox and choose Share / publish to add the first.';
    }catch(error){if(serial===epoch)status.textContent=error.message;}
    finally{if(serial===epoch){more.disabled=false;submit.disabled=false;}}
  };
  form.onsubmit=e=>{e.preventDefault();query=search.value.trim();load(true);};
  more.onclick=()=>load();
  return load(true);
}
