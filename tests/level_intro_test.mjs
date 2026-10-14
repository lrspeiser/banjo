import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import {LEVEL_MECHANISMS,levelIntroduction} from '../client/voxel-lab/level-intro.mjs';
const levels=JSON.parse(execFileSync('python',['-c',"import sys,json;sys.path.insert(0,'scripts');import machine_game as g;print(json.dumps([g.public(l) for l in g.load_levels()]))"],{encoding:'utf8'}));
assert.deepEqual(Object.keys(LEVEL_MECHANISMS).sort(),levels.map(l=>l.id).sort(),'Every authored level has a reviewed mechanism explanation');
for(const level of levels){
  const info=levelIntroduction(level);
  for(const field of ['title','place','works','goal'])assert.ok(info[field]?.trim(),`${level.id}: ${field}`);
  assert.ok(info.works.split(/\s+/).length<=40,`${level.id}: keep the explanation short`);
  const rule=level.goal.station.done_when;
  if(rule.turned_deg)assert.ok(info.goal.includes(`${rule.turned_deg.deg}°`),'The target comes from the declared goal');
  if(rule.rose_m)assert.ok(info.goal.includes(`${Number((rule.rose_m.m*100).toFixed(3))} cm`),'The lift height comes from the declared goal');
  assert.deepEqual(levelIntroduction({...level,solution:[{secret:'DO NOT SHOW'}],wrong:[],solution_releases:['SECRET']}),info,'Private answers do not affect the introduction');
}
assert.equal(levelIntroduction({free:true}),null,'Sandbox has no forced level briefing');
const legacy=levelIntroduction({id:'old-spring',variant:{family:'easy-spring',version:2},title:'Spring',brief:'Lift the load.',tray:[{piece:'spring',knobs:{mechanism_version:{default:1}}}]});
assert.ok(!legacy.works.includes('latch'),'Old shared springs do not promise a release control');
const heat=levelIntroduction(levels.find(l=>l.id==='easy-heat'));
for(const instruction of ['Clip to cord','Hot','Place','supply +','heater +','heater −','supply −'])assert.ok(heat.works.includes(instruction),instruction);
const oldHeat=levelIntroduction({id:'old-heat',variant:{family:'easy-heat',version:1},title:'Heat',brief:'Release the weight.',tray:[{piece:'ignition',knobs:{}}]});
assert.ok(!oldHeat.works.includes('Clip to cord'),'Legacy heaters keep their automatic leads and attachment');
console.log(`PASS introductions for ${levels.length} authored levels, private-answer isolation and retained spring descriptions`);
