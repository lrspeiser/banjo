import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../client/experiments/drop-observation.js',import.meta.url),'utf8');
const {describeObservation}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const drop=JSON.parse(readFileSync(new URL('../build/drop-world-results.json',import.meta.url),'utf8'));
const fluid=JSON.parse(readFileSync(new URL('../build/water-wheel-results.json',import.meta.url),'utf8'));
assert.equal(drop.integration_passed,true);assert.equal(fluid.integration_passed,true);
const pairs=drop.experiments.filter(e=>e.before);assert.equal(pairs.length,4);assert.equal(fluid.experiments.length,7);
for(const e of pairs){
  const text=describeObservation(e.before,e.after);
  assert.match(text,/Largest cell travel/);
  if(e.case==='glass/iron')assert.match(text,/bonds broke.*still one connected piece.*scattering is not established/);
  if(e.case==='iron/iron'){assert.match(text,/Sheet: no observed fracture or plastic change/);assert.match(text,/Ball:.*axial plastic work.*unloading/);}
}
for(const e of fluid.experiments){
  const text=describeObservation(e.initial,e.final);
  assert.match(text,e.water&&Math.abs(e.offset_m)<.5?/unpowered wheel turned/:e.water?/not measurably turned/:/Dry control/);
  if(e.water)assert.match(text,/not calibrated/);
}
const failed=structuredClone(fluid.experiments[0].final);failed.report.state_valid=false;
assert.match(describeObservation(fluid.experiments[0].initial,failed),/Incomplete result/);
console.log('PASS: actual native before/after explanations distinguish fracture, axial plasticity, water-driven rotation and dry/missed controls.');
