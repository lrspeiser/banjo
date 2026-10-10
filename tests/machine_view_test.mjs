// The machine page draws only what the engine sent: frame merging keeps a
// piece's cells until its revision changes, a full frame replaces everything,
// temperature colours start above 320 K, and the camera looks at the first
// station the engine has not yet measured as done.
import assert from 'node:assert/strict';
import {mergeFrame, family, heatTint, focusPoint, materialColor, describeTime} from '../client/voxel-lab/machine-view.mjs';

const body = (name, extra = {}) => ({name, shape: 'box', material: 'oak', dimensions_m: [.1, .1, .1], position_m: [0, 0, 0],
  orientation_wxyz: [1, 0, 0, 0], revision: 0, ...extra});
let world = {seq: 0, t: 0, bodies: new Map()};
world = mergeFrame(world, {seq: 1, t: 0, full: true, bodies: [body('a'), body('glass', {shape: 'hull', cells_local_m: [[0, 0, 0]]})]});
assert.equal(world.bodies.size, 2);
world = mergeFrame(world, {seq: 2, t: .1, bodies: [body('glass', {shape: 'hull', position_m: [0, 1, 0]})], removed: []});
assert.deepEqual(world.bodies.get('glass').cells_local_m, [[0, 0, 0]], 'unchanged revision keeps its cells');
assert.deepEqual(world.bodies.get('glass').position_m, [0, 1, 0]);
world = mergeFrame(world, {seq: 3, t: .2, bodies: [body('glass', {shape: 'hull', revision: 1})], removed: ['a']});
assert.equal(world.bodies.get('glass').cells_local_m, undefined, 'a new revision waits for its own cells');
assert.equal(world.bodies.has('a'), false);
world = mergeFrame(world, {seq: 4, t: .3, full: true, bodies: [body('b')]});
assert.deepEqual([...world.bodies.keys()], ['b'], 'a full frame replaces everything');
assert.throws(() => mergeFrame(world, {}));

assert.equal(family('glass plate piece 3 piece 1'), 'glass plate');
assert.equal(family('domino 4'), 'domino 4');
assert.equal(heatTint(0x336699, 300), 0x336699, 'no tint below 320 K');
assert.notEqual(heatTint(0x336699, 900), 0x336699);
const hot = heatTint(0x336699, 1300), warm = heatTint(0x336699, 650);
assert.ok(((hot >> 16) & 255) > ((warm >> 16) & 255), 'hotter is brighter red');
assert.equal(materialColor('oak'), 0xb07a45);
assert.equal(materialColor('unknown', '102030ff'), 0x102030);
assert.equal(describeTime(1.5), '1.50 s');
assert.equal(describeTime(75), '1 min 15.0 s');

const stations = [{focus: ['a']}, {focus: ['glass plate']}, {focus: []}];
const bodies = new Map([['a', body('a', {position_m: [1, 0, 0]})], ['glass plate piece 1', body('glass plate piece 1', {position_m: [2, 0, 0]})],
  ['glass plate piece 2', body('glass plate piece 2', {position_m: [4, 0, 0]})]]);
assert.deepEqual(focusPoint([{done: false}, {done: false}], stations, bodies), {index: 0, at: [1, 0, 0]});
assert.deepEqual(focusPoint([{done: true}, {done: false}], stations, bodies), {index: 1, at: [3, 0, 0]}, 'pieces stand in for the broken part');
assert.deepEqual(focusPoint([{done: true}, {done: true}, {done: false}], stations, bodies), {index: 1, at: [3, 0, 0]});
console.log('PASS machine page draws engine frames, measured heat colours and the next unmeasured station');
