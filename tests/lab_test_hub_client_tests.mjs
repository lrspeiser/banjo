import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
const code=readFileSync(new URL('../build/material-lab/ui/hub-contract.js',import.meta.url),'utf8');
const {validateContact,validateJob}=await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
// A recording from the actual compiled strict run is required; no invented trajectory.
const original=JSON.parse(readFileSync(process.argv[2],'utf8'));
test('all twelve actual comparative native recordings satisfy the viewer contract',()=>assert.equal(validateContact(original),original));
test('recordings reject incomplete cells, clocks, masses, topology and source poses',()=>{
  for(const edit of [v=>v.experiments.pop(),v=>v.experiments[1]=v.experiments[0],v=>v.experiments[0].frames.pop(),v=>v.experiments[0].frames[1].time_s+=1e-5,v=>v.experiments[0].frames[0].nodes.pop(),v=>v.experiments[0].frames[1].nodes[0].mass_kg*=2,v=>v.experiments[0].frames[0].source[0].orientation_wxyz=[0,0,0,0],v=>v.experiments[0].frames[0].broken_bonds=10,v=>v.experiments[0].bond_topology[0]=[0,0],v=>v.experiments[0].frames[0].nodes[0].position_m[0]=Infinity]){
    const value=structuredClone(original);edit(value);assert.throws(()=>validateContact(value));
  }
});
test('an acceptance failure remains a failure and cannot be silently marked passing',()=>{
  const id='a'.repeat(32),job={schema:'banjo.test-job.v1',id,selection:'contact-gate',status:'completed',current:'',total:1,checks:[{id:'contact-gate',name:'Contact',kind:'strict acceptance',status:'fail',exit_code:1,elapsed_s:7,output:'[FAIL]',artifact_sha256:'b'.repeat(64),recording_sha256:'c'.repeat(64)}]};
  assert.equal(validateJob(job,id),job);
  for(const edit of [v=>v.checks[0].status='pass',v=>v.id='b'.repeat(32),v=>v.checks=[],v=>v.checks[0].recording_sha256='bad',v=>v.checks[0].status='expected-pass']){const value=structuredClone(job);edit(value);assert.throws(()=>validateJob(value,id));}
});
