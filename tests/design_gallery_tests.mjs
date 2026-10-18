import test from 'node:test';
import assert from 'node:assert/strict';
import {previewGeometry} from '../client/voxel-lab/design-gallery.mjs';

const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-10, `${a} != ${b}`);

test('wall thumbnails look at the front and leave the retaining surface out',()=>{
  const geometry=previewGeometry({base:{build_surface:{kind:'wall'},parts:[
    {name:'workshop backing',shape:'box',at_m:[0,2,0],size_m:[6,4,.02]},
    {name:'cup',shape:'box',at_m:[1,.5,.3],size_m:[.5,.1,.5]}]},
    placements:[{piece:'marble',x_m:-1,height_m:3}]});
  assert.equal(geometry.length,2);
  assert.deepEqual(geometry[1],{kind:'marker',point:[-1,-3],name:'marble'});
  near(Math.min(...geometry[0].points.map(p=>p[1])),-.55);
});
test('part thumbnails use declared dimensions, position and the same Rx Ry Rz pose convention', () => {
  const draft = {base: {parts: [{name: 'plank', shape: 'box', material: 'oak', at_m: [2, 3, -1],
    size_m: [2, .1, .4], turn_deg: [0, 90, 0]}]}, placements: []};
  const saved = JSON.stringify(draft), geometry = previewGeometry(draft);
  assert.equal(geometry.length, 1); assert.equal(geometry[0].kind, 'polygon');
  const xs = geometry[0].points.map(p => p[0]), zs = geometry[0].points.map(p => p[1]);
  near(Math.min(...xs), 1.8); near(Math.max(...xs), 2.2);
  near(Math.min(...zs), -2); near(Math.max(...zs), 0);
  assert.equal(geometry[0].color, '#b07a45'); assert.equal(JSON.stringify(draft), saved);
});

test('compound child geometry transforms through its parent instead of drawing its local coordinates', () => {
  const geometry = previewGeometry({base: {parts: [{shape: 'compound', at_m: [1, 0, 2], material: 'glass',
    turn_deg: [0, 90, 0], parts: [{shape: 'sphere', at_m: [1, 0, 0], size_m: [.2, .2, .2]}]}]}});
  assert.equal(geometry.length, 1); assert.equal(geometry[0].kind, 'circle');
  near(geometry[0].point[0], 1); near(geometry[0].point[1], 1);
  near(geometry[0].radius, .1); assert.equal(geometry[0].color, '#9fd8ef');
});

test('dry channel and static wires show authored geometry without predicting water or current', () => {
  const base = {ground: {kind: 'flume', nx: 60, cell_m: .1, trench_z_m: .2, trench_width_m: .6, discharge_m3_s: 0},
    parts: [], electrical: {devices: [{name: 'supply', terminals: {plus: [-.6, .1, 0]}},
      {name: 'lamp', terminals: {plus: [.6, .2, 0]}}], wires: [{name: 'lead', a: 'supply:plus', b: 'lamp:plus'}]}};
  const saved = JSON.stringify(base), geometry = previewGeometry({base, placements: []});
  assert.equal(geometry.length, 3); assert.ok(geometry.every(row => row.kind === 'line'));
  near(geometry[0].points[0][0], -3); near(geometry[0].points.at(-1)[0], 3);
  near(geometry[0].points[0][1], -.1); near(geometry[1].points[0][1], .5);
  assert.deepEqual(geometry[2].points[0], [-.6, 0]); assert.deepEqual(geometry[2].points.at(-1), [.6, 0]);
  assert.equal(JSON.stringify(base), saved); assert.ok(geometry.every(row => !('current_a' in row) && !('water' in row)));
});

test('unexpanded kits and sparse placements mark actual declared anchors and never invent bodies', () => {
  const geometry = previewGeometry({base: {kits: [{name: 'ramp', top_m: [0, 2, -.4], bottom_m: [1, 0, .2]},
    {name: 'wheel', at_m: [.5, 0, 0], radius_m: .6}]}, placements: [
    {piece: 'battery', x_m: -.5, z_m: .2}, {piece: 'unknown'}, {piece: 'bad', x_m: NaN, z_m: 0}]});
  assert.equal(geometry.length, 3);
  assert.deepEqual(geometry[0].points, [[0, -.4], [1, .2]]);
  assert.deepEqual(geometry[1], {kind: 'marker', point: [.5, 0], name: 'wheel'});
  assert.deepEqual(geometry[2], {kind: 'marker', point: [-.5, .2], name: 'battery'});
  assert.deepEqual(previewGeometry({base: {parts: [{shape: 'box', at_m: [0, Infinity, 0], size_m: [1, 1, 1]}]}}), []);
  assert.deepEqual(previewGeometry(), []);
});
