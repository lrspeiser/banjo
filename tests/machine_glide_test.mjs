// A run is drawn between measured engine frames: the drawn time trails the
// newest frame by about a frame and a half, applies frames in order, never
// passes the newest frame and catches up when frames stop. A preview sample
// far from the last one (a reset) is shown at once instead of blended.
import assert from 'node:assert/strict';
import {glides, frameBlend, pathPoint, blendPose, FramePlayback} from '../client/voxel-lab/machine-view.mjs';

const poseA={position_m:[0,0,0],orientation_wxyz:[1,0,0,0]},poseB={position_m:[1,2,-2],orientation_wxyz:[Math.SQRT1_2,0,Math.SQRT1_2,0]};
assert.deepEqual(blendPose(poseA,poseB,0).position_m,[0,0,0]);
assert.deepEqual(blendPose(poseA,poseB,1).position_m,[1,2,-2]);
assert.deepEqual(blendPose(poseA,poseB,.5).position_m,[.5,1,-1]);
assert.deepEqual(blendPose(poseA,poseB,3).position_m,[1,2,-2],'a fraction past the next frame stops at it');
const half=blendPose(poseA,poseB,.5).orientation_wxyz;
assert.ok(Math.abs(Math.hypot(...half)-1)<1e-12,'a blended turn stays a unit quaternion');
assert.ok(Math.abs(2*Math.acos(half[0])-Math.PI/4)<1e-9,'halfway through a quarter turn is an eighth of a turn');
const flipped=blendPose(poseA,{...poseB,orientation_wxyz:poseB.orientation_wxyz.map(v=>-v)},.5).orientation_wxyz;
assert.ok(half.every((v,i)=>Math.abs(v-flipped[i])<1e-12),'q and -q are the same turn: the short way round');
{
  const applied=[],apply=frame=>applied.push(frame.t);
  const play=new FramePlayback();play.reset(0,0);
  // Frames arrive every 50 ms, each 50 ms of world time on.
  for(let k=1;k<=4;k++)play.receive({t:k*.05,bodies:[]},k*50);
  let step=play.advance(200,apply,1);
  assert.ok(play.shown<=play.newest+1e-12,'never drawn past the newest frame');
  assert.ok(step.next,'a frame to draw toward while frames keep coming');
  assert.ok(step.fraction>=0&&step.fraction<=1);
  for(let now=216;now<=600;now+=16){if(now%50<16)play.receive({t:Math.round(now/50)*.05,bodies:[]},now);step=play.advance(now,apply,1);}
  assert.deepEqual(applied,[...applied].sort((a,b)=>a-b),'frames are applied in order');
  assert.ok(play.newest-play.shown>.02&&play.newest-play.shown<.2,'about a frame and a half behind while frames arrive: '+(play.newest-play.shown));
  // Frames stop: the drawing catches up to the last one and stops there.
  for(let now=616;now<=1600;now+=16)step=play.advance(now,apply,1);
  assert.equal(play.shown,play.newest);assert.equal(step.next,null);assert.equal(applied.at(-1),play.newest);
  // A paused run's frames, which do not move world time, are applied at once.
  const count=applied.length;play.receive({t:play.newest,bodies:[]},1700);play.advance(1716,apply,1);
  assert.equal(applied.length,count+1);
  // A tab that was not drawn drains its frames in order.
  play.receive({t:play.newest+.05,bodies:[]},1800);play.receive({t:play.newest+.1,bodies:[]},1850);
  play.drain(apply);assert.equal(play.queue.length,0);assert.equal(play.applied,play.newest);
}
{
  // A server behind real time sends frames covering less world time: the
  // drawing slows to match it rather than stopping and starting.
  const play=new FramePlayback();play.reset(0,0);const apply=()=>{};
  let stalls=0,last=0;
  for(let now=0,k=0;now<=4000;now+=16){
    if(now>=k*50){k++;play.receive({t:k*.02,bodies:[]},now);}
    const step=play.advance(now,apply,1);
    if(now>1000&&!step.next)stalls++;
    assert.ok(play.shown>=last);last=play.shown;
  }
  assert.ok(Math.abs(play.rate-.4)<.05,'measured world time per second: '+play.rate);
  assert.equal(stalls,0,'no stops while frames keep arriving');
}
console.log('PASS a run is drawn between measured frames, in order, never past the newest, and slows with a slow server');

assert.equal(glides([0, 0, 0], [0.02, 0, 0]), true);
assert.equal(glides([0, 0, 0], [3, 0, 0]), false, 'a reset is placed at once');
assert.equal(glides(null, [0, 0, 0]), false);
assert.equal(glides([0, 0, 0], [NaN, 0, 0]), false);
console.log('PASS a preview sample far from the last one is shown at once');

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
