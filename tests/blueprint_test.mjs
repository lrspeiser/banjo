// A dropped blueprint keeps its pieces' relative layout around the chosen
// point and renumbers references between its own pieces after the design's.
import assert from 'node:assert/strict';
import {blueprintPlacements} from '../client/voxel-lab/machine-view.mjs';

const saved = [
  {piece: 'plank', x_m: 1, z_m: 0, length_m: .7},
  {piece: 'marble', x_m: 2, z_m: 1},
  {piece: 'link', a: 'your plank 1', b: 'your marble 2 body', kind: 'string'},
  {piece: 'wire', from: {part: 'your marble 2'}, to: 'table'},
];
const got = blueprintPlacements(saved, 3, [0, 0]);
assert.deepEqual(got.map(p => [p.x_m, p.z_m]).slice(0, 2), [[-.5, -.5], [.5, .5]], 'centred on the drop point');
assert.equal(got[2].a, 'your plank 4');
assert.equal(got[2].b, 'your marble 5 body');
assert.equal(got[3].from.part, 'your marble 5');
assert.equal(got[3].to, 'table', 'names outside the blueprint are kept');
assert.equal(saved[0].x_m, 1, 'the saved blueprint is not changed');
// A reference to a piece the blueprint does not contain stays as it was.
assert.equal(blueprintPlacements([{piece: 'link', a: 'your plank 9'}], 0, [0, 0])[0].a, 'your plank 9');
assert.equal(blueprintPlacements([{piece: 'link', a: 'your knife 1'}], 0, [0, 0])[0].a, 'your knife 1', 'only matching pieces renumber');
assert.deepEqual(blueprintPlacements([], 2, [1, 1]), []);
const moved = blueprintPlacements([{piece: 'block', x_m: 0, z_m: 0}], 0, [1.25, -2]);
assert.deepEqual([moved[0].x_m, moved[0].z_m], [1.25, -2]);
const withAction=[{piece:'pinball_button',x_m:0,z_m:0,yaw_deg:0},
  {piece:'object_action',part:'your pinball_button 1 button',label:'Press',key:'KeyA',location:'object',push_x_n:0,push_y_n:-30,push_z_n:0}];
const turned=blueprintPlacements(withAction,4,[1,1],1);
assert.equal(turned[1].part,'your pinball_button 5 button');
assert.equal(turned[1].location,'object');
assert.equal(turned[0].yaw_deg,90);
assert.deepEqual([turned[1].push_x_n,turned[1].push_y_n,turned[1].push_z_n],[0,-30,0], 'hand force remains in the handle initial axes');
console.log('PASS blueprints drop centred on a point and renumber their own piece references');
