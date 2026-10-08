import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../client/experiments/sheet-observation.js',import.meta.url),'utf8');
const {brokenBondSegments,describeSheet}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const data=JSON.parse(readFileSync(new URL('../build/sheet-feedback-results.json',import.meta.url),'utf8'));
assert.deepEqual(data.cases.map(c=>c.material),['glass','ice','oak','iron']);
for(const c of data.cases){
  assert.deepEqual(brokenBondSegments(c.initial),[]);
  assert.match(describeSheet(c.initial),/no impact has been simulated/);
  const segments=brokenBondSegments(c.after);
  assert.equal(segments.length,c.after.broken_bonds*6);
  c.after.broken_interfaces.forEach(([a,b],k)=>assert.deepEqual(segments.slice(k*6,k*6+6),[...c.after.positions[a].slice(0,3),...c.after.positions[b].slice(0,3)]));
  const text=describeSheet(c.after);
  assert.match(text,/s simulated/);
  assert.match(text,c.after.open_columns?/not calibrated material fracture/:/No clear through-thickness opening/);
  if(c.after.broken_bonds)assert.ok(text.includes(`${c.after.broken_bonds} connections broke`));
}
const invalid=structuredClone(data.cases[0].after);invalid.broken_interfaces=[[0,800]];
assert.throws(()=>brokenBondSegments(invalid),/Invalid broken bond endpoint/);
assert.match(describeSheet(data.ice_continuation.state,data.ice_continuation.error),/Native contact refused:.*Last accepted state retained/);
console.log('PASS: broken-bond overlay uses actual native endpoint positions; descriptions distinguish damage from openings.');
