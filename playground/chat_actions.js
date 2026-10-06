// Only server-derived destinations are rendered. Chat never spends supplies.
import { screenUrl } from '/game_menu.js';

export function actionUrl(action) {
  const allowed = new Set(['world','inventory','build','progress','lab','recipes','market','skills','goals']);
  if (!allowed.has(action?.screen)) return null;
  const url = new URL(screenUrl(action.screen), location.origin);
  for (const key of ['carry','design','library','recipe','job','material','guide','goal-chain','focus','resource']) url.searchParams.delete(key);
  const source = action.selection;
  const key = {carried:'carry',saved:'design',library:'library',recipe:'recipe'}[source?.source];
  if (key && typeof source.id === 'string') url.searchParams.set(key,source.id);
  for (const key of ['focus','resource','job']) if (typeof action[key] === 'string') url.searchParams.set(key,action[key]);
  return url.pathname + url.search;
}

export function renderChatActions(root, actions = []) {
  const group=document.createElement('div');group.className='chat-actions';
  for (const action of actions.slice(0,8)) {
    const href=actionUrl(action);if(!href)continue;
    const link=document.createElement('a');link.href=href;link.className='ws-action';
    link.textContent=action.label;link.dataset.chatAction=action.id;
    group.append(link);
  }
  if(group.children.length)root.append(group);
}

export function rememberGuide(role,content) {
  const world=new URLSearchParams(location.search).get('world');
  const player=world && localStorage.getItem(`banjo.player.${world}`);
  if(!player)return;
  try {const rows=guideHistory();rows.push({role,content:String(content).slice(0,4000)});
    sessionStorage.setItem(`banjo.guide.${world}.${player}`,JSON.stringify(rows.slice(-10)));}catch{}
}
export function guideHistory() {
  const world=new URLSearchParams(location.search).get('world');
  const player=world && localStorage.getItem(`banjo.player.${world}`);
  try {return JSON.parse(sessionStorage.getItem(`banjo.guide.${world}.${player}`)||'[]');}catch{return [];}
}
