// The machine page draws only what the engine sent: frame merging keeps a
// piece's cells until its revision changes, a full frame replaces everything,
// temperature colours start above 320 K, and the camera looks at the first
// station the engine has not yet measured as done.
import assert from 'node:assert/strict';
import {mergeFrame, family, heatTint, focusPoint, stationPoint, materialColor, describeTime, beamSegments, wireRoute, contactCircuitDiagram, PLACEMENT_GRID, snapGroundPoint} from '../client/voxel-lab/machine-view.mjs';

const finePlacement={x:.307,y:.613,z:-.207};
const aligned=snapGroundPoint(finePlacement);
assert.deepEqual(aligned,{point:{x:.3,y:.613,z:-.2},locks:{x:.3,z:-.2}});
assert.deepEqual(finePlacement,{x:.307,y:.613,z:-.207},'snapping does not mutate a saved declaration');
assert.deepEqual(snapGroundPoint(finePlacement,{enabled:false}).point,finePlacement,'free placement keeps the raw drag coordinates');
assert.deepEqual(snapGroundPoint({x:.312,z:-.212},{previous:aligned.locks}).locks,{x:.3,z:-.2},'alignment holds through the small release band');
assert.deepEqual(snapGroundPoint({x:.313,z:-.213},{previous:aligned.locks}).locks,{x:null,z:null},'dragging farther lets go without a grid-sized jump');
assert.deepEqual(snapGroundPoint({x:.008,z:-.008}).locks,{x:0,z:0},'capture is symmetric at the origin and its boundary');
assert.deepEqual(snapGroundPoint({x:.009,z:-.009}).locks,{x:null,z:null},'nearby but outside capture stays free');
assert.deepEqual(snapGroundPoint({x:.024,z:-.024}).point,{x:.024,z:-.024},'the middle of a square does not snap');
assert.deepEqual(snapGroundPoint({z:.051}).point,{z:.05},'pieces with one positional axis retain only that axis');
assert.equal(PLACEMENT_GRID.major_step_m/PLACEMENT_GRID.step_m,10,'ten small squares per major square');
assert.deepEqual(snapGroundPoint({x:NaN,z:Infinity}).locks,{x:null,z:null},'invalid coordinates do not create an alignment');

const pinA = [-.68, .18, .07], pinB = [.68, .08, .07];
for (const [a,b] of [[pinA,pinB], [pinB,pinA], [pinA,[-.68,.18,.07]], [[0,.012,.1],[0,.012,.3]]]) {
  const route = wireRoute(a,b);
  assert.deepEqual(route[0], a); assert.deepEqual(route.at(-1), b);
  assert.ok(route.every(p => p.every(Number.isFinite)), 'all cable points are finite');
  assert.ok(route.some(p => p[1] === .012), 'the wire reaches the floor');
  for (let i=1; i<route.length; i++) assert.equal(route[i].filter((v,k) => Math.abs(v-route[i-1][k])>1e-9).length, 1,
    'each nonzero cable segment runs along one axis');
}
assert.notDeepEqual(wireRoute(pinA,pinB,0), wireRoute(pinA,pinB,1), 'parallel wires have distinct floor lanes');
assert.deepEqual(pinA, [-.68,.18,.07], 'drawing never mutates native terminal coordinates');

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
assert.deepEqual(stationPoint(stations[0], bodies), [1, 0, 0], 'any station can be looked at, done or not');
assert.equal(stationPoint({focus: ['nothing here']}, bodies), null);
assert.deepEqual(focusPoint([{done: true}, {done: true}, {done: false}], stations, bodies), {index: 1, at: [3, 0, 0]});
// Light: each leg of each traced ray is a segment, in metres, brightest where
// the engine measured the most power.
const beams = beamSegments([{light: 1, mm: [0, 1000, 0, 0, 500, 0, 500, 1000, 0], w: [4, 1]}, {light: 1, mm: [0, 0, 0], w: []}]);
assert.equal(beams.legs, 2, 'two legs; a path with one corner draws nothing');
assert.deepEqual([...beams.positions.slice(0, 6)], [0, 1, 0, 0, .5, 0]);
assert.ok(beams.colors[0] > beams.colors[6], 'the stronger leg is brighter');
assert.ok(beams.colors[6] > 0, 'a faint leg still shows');
assert.equal(beamSegments(undefined).legs, 0);
const contactCircuit={name:'heat',battery:'store',switch:{touch:['tip','pad']},coil:{heats:'charge'}};
const contactMachine={batteries:[{name:'store',in:'battery'}],parts:[{name:'pad',fixed:true},{name:'tip',fixed:false}]};
const circuitBodies=new Map(['battery','tip','pad','charge'].map((name,i)=>[name,{name,position_m:[i,.1,0],dimensions_m:[.1,.1,.1],orientation_wxyz:[1,0,0,0]}]));
const diagram=contactCircuitDiagram(contactCircuit,contactMachine,circuitBodies);
assert.deepEqual(diagram.legs.map(l=>l.id),['supply','switched','return']);
assert.equal(diagram.fixed,'pad');assert.equal(diagram.moving,'tip');
assert.deepEqual(diagram.legs.map(l=>l.color),[0xf19076,0xf19076,0x83bbff]);
assert.ok(diagram.legs.every(l=>wireRoute(l.a,l.b).some(p=>p[1]===.012)));
const before=diagram.legs[1].a;
circuitBodies.get('tip').position_m=[1,.05,.2];
circuitBodies.get('tip').orientation_wxyz=[Math.SQRT1_2,0,Math.SQRT1_2,0];
const moved=contactCircuitDiagram(contactCircuit,contactMachine,circuitBodies);
assert.ok(Math.abs(moved.legs[1].a[0]-1.053)<1e-12,'the connector rotates with the measured body');
assert.notDeepEqual(moved.legs[1].a,before);
assert.deepEqual(moved.legs[0],diagram.legs[0],'moving the tip never relocates the lower pad');
assert.equal(contactCircuitDiagram({...contactCircuit,switch:{hinge:'hinge'}},contactMachine,circuitBodies),null);
circuitBodies.delete('tip');assert.equal(contactCircuitDiagram(contactCircuit,contactMachine,circuitBodies),null,'missing contacts never get an invented connection');
console.log('PASS machine page draws engine frames, measured heat colours, light beams, contact circuits and the next unmeasured station');
