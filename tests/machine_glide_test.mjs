// Moving pieces glide between engine frames: the glide length follows the
// measured gap between frames within bounds, ignores pauses, never overshoots,
// and a large jump (a reset or teleport) is placed at once instead.
import assert from 'node:assert/strict';
import {GLIDE, glideSpan, glideAlpha, glides, frameBlend, pathPoint} from '../client/voxel-lab/machine-view.mjs';

assert.equal(glideSpan(50, 50), 50);
assert.ok(glideSpan(50, 120) > 50 && glideSpan(50, 120) < 120, 'a slower frame lengthens the glide gradually');
let span = 50;
for (let i = 0; i < 40; i++) span = glideSpan(span, 100);
assert.ok(Math.abs(span - 100) < 1, 'the glide settles on a steady frame interval');
assert.equal(glideSpan(50, 2000), 50, 'a pause is not a frame interval');
assert.equal(glideSpan(50, 0), 50);
assert.equal(glideSpan(GLIDE.max_ms, 10000), GLIDE.max_ms);
for (let i = 0; i < 50; i++) span = glideSpan(span, 500);
assert.ok(span <= GLIDE.max_ms, 'a struggling server never makes motion lag more than max_ms');
for (let i = 0; i < 50; i++) span = glideSpan(span, 1);
assert.ok(span >= GLIDE.min_ms);
assert.equal(glideSpan(undefined, 50) > 0, true);

assert.equal(glideAlpha(0, 50), 0);
assert.equal(glideAlpha(25, 50), .5);
assert.equal(glideAlpha(80, 50), 1, 'a glide never overshoots its target');
assert.equal(glideAlpha(-5, 50), 0);
assert.equal(glideAlpha(10, 0), 1);

assert.equal(glides([0, 0, 0], [0.02, 0, 0]), true);
assert.equal(glides([0, 0, 0], [3, 0, 0]), false, 'a reset is placed at once');
assert.equal(glides(null, [0, 0, 0]), false);
assert.equal(glides([0, 0, 0], [NaN, 0, 0]), false);
console.log('PASS moving pieces glide between engine frames, settle on the frame interval and jump only on a reset');

const frames = [{t: 0}, {t: .1}, {t: .3}];
assert.deepEqual(frameBlend(frames, 0), {index: 0, next: 1, f: 0});
assert.deepEqual(frameBlend(frames, .05), {index: 0, next: 1, f: .5});
const mid = frameBlend(frames, .2);
assert.equal(mid.index, 1); assert.equal(mid.next, 2); assert.ok(Math.abs(mid.f - .5) < 1e-9);
assert.deepEqual(frameBlend(frames, .5), {index: 2, next: 2, f: 0}, 'the last sample holds');
assert.equal(frameBlend([], 1), null);
const path = [[0, 0, 0, 0], [1, 2, 0, 0], [2, 2, 4, 0]];
assert.deepEqual(pathPoint(path, -1), [0, 0, 0]);
assert.deepEqual(pathPoint(path, .5), [1, 0, 0]);
assert.ok(pathPoint(path, 1.5).every((v, i) => Math.abs(v - [2, 2, 0][i]) < 1e-9));
assert.deepEqual(pathPoint(path, 9), [2, 4, 0]);
assert.equal(pathPoint([], 0), null);
console.log('PASS preview samples and paths are interpolated between samples and held at their ends');
