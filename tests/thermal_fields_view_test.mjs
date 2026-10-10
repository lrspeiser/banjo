import fs from 'node:fs';import assert from 'node:assert/strict';
const html=fs.readFileSync(new URL('../client/voxel-lab/thermal-fields.html',import.meta.url),'utf8'),js=fs.readFileSync(new URL('../client/voxel-lab/thermal-fields.js',import.meta.url),'utf8');
const ids=[...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1]);assert.equal(new Set(ids).size,ids.length);
for(const m of js.matchAll(/\$\('([^']+)'\)/g))assert(ids.includes(m[1]),`missing ${m[1]}`);
assert(js.includes("fetch('/api/thermal-fields'"));assert(js.includes('c.temperature_k'));assert(js.includes('c.liquid_fraction'));assert(js.includes('c.products_kg'));assert(js.includes('new THREE.BoxGeometry(c.size_m,c.size_m,c.size_m)'));assert(html.includes('geometry stays fixed'));assert(html.includes('no flame animation'));assert(!js.includes('Math.random'));
console.log('3D field asset IDs, actual native observables and honest unsupported-law labels passed');
