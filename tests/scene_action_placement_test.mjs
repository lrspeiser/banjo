import assert from 'node:assert/strict';
import fs from 'node:fs';
const pages={representations:['compile','initial','rigid','detail','focus','flight-view'],gpu:['reset','play','pause','focus','blocks','stack-control'],materials:['apply','unload','reset']};
for(const [page,required] of Object.entries(pages)){
  const html=fs.readFileSync(new URL(`../client/voxel-lab/${page}.html`,import.meta.url),'utf8');
  const section=html.match(/<section[^>]*id="view"[^>]*>([\s\S]*?)<\/section>/)?.[1];assert.ok(section,page+' must contain a 3D view');
  const ids=[...html.matchAll(/id="([^"]+)"/g)].map(match=>match[1]);assert.equal(new Set(ids).size,ids.length,page+' duplicate control IDs');
  for(const id of required)assert.ok(section.includes(`id="${id}"`),page+' action '+id+' must stay beside the 3D view');
  const aside=html.match(/<aside>([\s\S]*?)<\/aside>/)?.[1]??'';assert.ok(!/<button\b/.test(aside),page+' action still in sidebar');
  assert.ok(html.includes('href="/scene-actions.css"'),page+' missing scene action styles');
  assert.ok(section.includes('class="scene-actions"'),page+' missing scene-local dock');
  const js=fs.readFileSync(new URL(`../client/voxel-lab/${page}.js`,import.meta.url),'utf8');
  for(const match of js.matchAll(/\$\('([^']+)'\)/g))assert.ok(ids.includes(match[1]),page+' lost listener target '+match[1]);
}
const css=fs.readFileSync(new URL('../client/voxel-lab/scene-actions.css',import.meta.url),'utf8');assert.ok(css.includes('min-height:44px'));assert.ok(css.includes('overflow:auto'));assert.ok(!css.includes('#primary-actions'),'Shared dock must not collide with coupled action IDs');
console.log('All representation/GPU/material action IDs stay in 3D view; listeners and 44 px drawer controls preserved');
