import test from 'node:test';
import assert from 'node:assert/strict';
import {anonymousSave, cookieVisitor, validVisitor, returnURL} from '../client/voxel-lab/anonymous-profile.mjs';

const first = '77777777-7777-4777-8777-777777777777';
const second = '88888888-8888-4888-8888-888888888888';
const third = '99999999-9999-4999-8999-999999999999';
test('named saves migrate separately, retaining progress and complete design histories', () => {
  const design = {id:'design',name:'Catapult',draft:{placements:[{piece:'catapult'}]},
    versions:[{number:2,draft:{placements:[]}}],nextVersion:3};
  const raw = {current:'Henry',players:{Henry:{levels:{cut:{stars:3}},sandbox:{items:[design]}},
    Guest:{levels:{gap:{stars:1}}}}};
  const snapshot = JSON.stringify(raw), ids = [first,second];
  const result = anonymousSave(raw,{makeId:() => ids.shift()});
  assert.equal(result.current,first);
  assert.deepEqual(result.migratedProfiles,[first,second]);
  assert.deepEqual(result.players[first].sandbox.items[0],design);
  assert.equal(result.players[second].levels.gap.stars,1);
  assert.equal(JSON.stringify(raw),snapshot);
  assert.equal(JSON.stringify(result).includes('Henry'),false);
});
test('an incoming foreign return link does not absorb old named progress', () => {
  const result = anonymousSave({current:'Old',players:{Old:{levels:{cut:{stars:3}}}}},
    {visitor:third,makeId:() => first});
  assert.equal(result.current,third);
  assert.deepEqual(result.players[third],{levels:{}});
  assert.equal(result.players[first].levels.cut.stars,3);
});
test('invalid IDs and unrelated cookies cannot select a save', () => {
  assert.equal(validVisitor('__proto__'),false);
  assert.equal(validVisitor('77777777-7777-1777-8777-777777777777'),false);
  assert.equal(cookieVisitor('other='+first+'; banjo-visitor=bad'),null);
  assert.equal(cookieVisitor('banjo-visitor='+first.toUpperCase()),first);
  const raw = {format:2,current:first,players:{[first]:{levels:{cut:{stars:2}}}}};
  const result = anonymousSave(raw,{visitor:'bad',cookie:'banjo-visitor=bad',makeId:() => second});
  assert.equal(result.current,first);
  assert.equal(result.players[first].levels.cut.stars,2);
});
test('return link contains only the opaque identity, and repeat migration is stable', () => {
  assert.equal(returnURL('https://banjo.is/machine?design=private#build=data',first),
    'https://banjo.is/play?visitor='+first);
  const once = anonymousSave({players:{Old:{levels:{}}}},{makeId:() => first});
  const twice = anonymousSave(once,{makeId:() => {throw new Error('unexpected new identity');}});
  assert.deepEqual(twice,once);
});
