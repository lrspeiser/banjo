// The machine page draws only what the engine sent: frame merging keeps a
// piece's cells until its revision changes, a full frame replaces everything,
// temperature colours start above 320 K, and the camera looks at the first
// station the engine has not yet measured as done.
import assert from 'node:assert/strict';
import {mergeFrame, family, heatTint, focusPoint, stationPoint, materialColor, describeTime, beamSegments, lensOutline, wireRoute, clearWireRoute, contactCircuitDiagram, PLACEMENT_GRID, snapGroundPoint, workingAlignment, thermalCells, draggedKnobValue, pieceToolbarPosition} from '../client/voxel-lab/machine-view.mjs';

assert.equal(draggedKnobValue({min:0,max:2,step:.1},1,12),1.1);
assert.equal(draggedKnobValue({min:0,max:2,step:.1},1,400),2);
assert.equal(draggedKnobValue({min:-180,max:180,step:1,turning:true},175,10),-175);
for(const scene of [{left:0,top:0,right:900,bottom:600},{left:0,top:0,right:390,bottom:450}]){
  const piece={left:scene.right/2-25,right:scene.right/2+25,top:160,bottom:230};
  const at=pieceToolbarPosition(scene,piece,{width:184,height:148},[{left:200,right:scene.right,top:350,bottom:450}]);
  assert.ok(at.x>=scene.left&&at.y>=scene.top&&at.x+184<=scene.right&&at.y+148<=scene.bottom);
  assert.ok(at.x>=piece.right||at.x+184<=piece.left||at.y>=piece.bottom||at.y+148<=piece.top,'toolbar leaves the selected solid clear');
}

const heated={body:'cord',at_m:[0,.5,1],local_m:[0,.02,0],cell_m:.02,temperature_k:573.15,how:'chars',cut_w:100,held_j:400,needed_j:1000};
assert.equal(thermalCells({hot_cells:[heated]})[0].progress,.4);
assert.ok(thermalCells({hot_cells:[heated]})[0].charring);
assert.equal(thermalCells({hot_cells:[{...heated,how:'',cut_w:0,held_j:0,needed_j:0}]})[0].progress,null,'non-removable materials have no fictitious progress');
assert.equal(thermalCells({hot_cells:[{...heated,beyond_model:true}]})[0].charring,false);
assert.deepEqual(thermalCells({hot_cells:[{...heated,at_m:[NaN,0,0]}]}),[]);

const declaredLens={at_m:[.1,.575,0],axis:[1,0,0],aperture_m:.06,thickness_m:.020424,front_radius_m:.2,back_radius_m:-.2};
const lensLines=lensOutline(declaredLens);
assert.ok(lensLines.length>0 && lensLines.every(Number.isFinite));
const lensPoints=Array.from({length:lensLines.length/3},(_,i)=>lensLines.slice(i*3,i*3+3));
assert.ok(lensPoints.every(p=>Math.hypot(p[1]-.575,p[2])<=.06+1e-12),'outline uses the native aperture, not the screen handle size');
assert.ok(lensPoints.some(p=>Math.abs(p[0]-(.1-.020424/2))<1e-12),'convex surface includes its declared front vertex');
for (const axis of [[0,1,0],[0,0,-1],[1,2,3]]) assert.ok(lensOutline({...declaredLens,axis}).every(Number.isFinite));
assert.deepEqual(lensOutline({...declaredLens,axis:[0,0,0]}),[]);
assert.deepEqual(lensOutline({...declaredLens,aperture_m:.2}),[],'impossible curvature cannot poison camera bounds');

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
const working={at:[1,.5,2],dir:[1,0,0]};
const target={part:'cord',label:'center',at:[2,.504,2.004]};
assert.deepEqual(workingAlignment(working,[target]).axes,['x']);
assert.equal(workingAlignment(working,[target]).direction.part,'cord');
assert.deepEqual(workingAlignment(working,[{...target,at:[2,.52,2]}]).axes,[], 'both transverse coordinates matter');
assert.equal(workingAlignment(working,[{...target,at:[0,.5,2]}]).direction,null,'a facing arrow is forward only');
assert.deepEqual(workingAlignment(working,[{...target,at:[7,.5,2]}]).axes,[],'far-off collinear points do not highlight');
assert.equal(workingAlignment({...working,dir:[0,0,0]},[target]).direction,null);
assert.deepEqual(workingAlignment(null,[target]).axes,[]);
const cordSpan={part:'member',label:'member span',at:[0,.675,.235],span:[[0,.525,.235],[0,.825,.235]]};
const knifeSweep={at:[-.08,.69,.235],dir:[1,0,0]};
const spanAligned=workingAlignment(knifeSweep,[cordSpan]);
assert.deepEqual(spanAligned.axes,['x'],'a guide recognizes the cord between its endpoints');
assert.deepEqual(spanAligned.direction.at,[0,.69,.235]);
assert.deepEqual(workingAlignment({...knifeSweep,at:[-.08,.9,.235]},[cordSpan]).axes,[],'the cord does not extend infinitely upwards');
assert.equal(workingAlignment({...knifeSweep,at:[-.08,.69,.27]},[cordSpan]).direction,null,'screen crossings at different depths do not align');
const tiltedSpan={...cordSpan,span:[[0,.525,.185],[0,.825,.285]]};
assert.equal(workingAlignment({at:[-.08,.675,.235],dir:[1,0,0]},[tiltedSpan]).direction.part,'member','rotated member geometry remains usable');

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

const obstacles=[{min:[-.2,0,.06],max:[.2,.8,.3]},
  {min:[-.7,0,-.07],max:[-.5,.16,.07]},
  {min:[.5,0,-.07],max:[.7,.16,.07]}];
for(const [a,b] of [[pinA,pinB],[pinB,pinA],[[0,.1,-.076],pinB]]) {
  const route=clearWireRoute(a,b,0,obstacles);
  assert.ok(route&&route.length>=2,'a route around the pillar and behind a housing is found');
  assert.deepEqual(route[0],a);assert.deepEqual(route.at(-1),b);
  for(let n=2;n<route.length-1;n++)for(let t=0;t<=1;t+=.025) {
    const p=route[n-1].map((v,i)=>v+(route[n][i]-v)*t);
    assert.ok(!obstacles.some(o=>p.every((v,i)=>v>o.min[i]+1e-8&&v<o.max[i]-1e-8)),'every route segment clears solid interiors');
  }
}

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
