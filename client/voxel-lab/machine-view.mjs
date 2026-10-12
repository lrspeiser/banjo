// What the machine page draws is what the engine last measured. These helpers
// merge the engine's frames and choose colours and camera targets; none of
// them moves a body or predicts anything.

// Editing assistance changes a proposed placement, never a simulated body.
export const PLACEMENT_GRID = Object.freeze({size_m:40, fine_size_m:10, step_m:.05, major_step_m:.5, capture_m:.008, release_m:.012});
export function snapGroundPoint(point, {enabled=true, previous={}}={}) {
  const result={point:{...point},locks:{x:null,z:null}};
  if (!enabled) return result;
  for (const axis of ['x','z']) {
    const value=point[axis];
    if (!Number.isFinite(value)) continue;
    const held=previous[axis];
    const nearest=Number((Math.round(value/PLACEMENT_GRID.step_m)*PLACEMENT_GRID.step_m).toFixed(6));
    // Slight hysteresis avoids flickering between free motion and alignment.
    const snapped=Number.isFinite(held)&&Math.abs(value-held)<=PLACEMENT_GRID.release_m+1e-12 ? held
      : Math.abs(value-nearest)<=PLACEMENT_GRID.capture_m+1e-12 ? nearest : null;
    if (snapped!==null) {result.point[axis]=snapped;result.locks[axis]=snapped;}
  }
  return result;
}

// Apply one frame from /api/machine to the page's copy of the world. A full
// frame replaces everything; otherwise only the named bodies change, and a
// piece keeps its cells until the engine sends new ones for a new revision.
export function mergeFrame(world, frame) {
  if (!frame || typeof frame.seq !== 'number') throw Error('Not a machine frame');
  const bodies = frame.full ? new Map() : new Map(world.bodies);
  for (const name of frame.removed || []) bodies.delete(name);
  for (const b of frame.bodies || []) {
    const old = bodies.get(b.name);
    const row = {...b};
    if (!row.cells_local_m && old && old.cells_local_m && old.revision === b.revision) row.cells_local_m = old.cells_local_m;
    bodies.set(b.name, row);
  }
  return {seq: frame.seq, t: frame.t, bodies};
}

// What a piece is a piece of: "glass plate piece 3 piece 1" -> "glass plate".
export function family(name) { return String(name).split(' piece ')[0]; }

// Drawing geometry only: native terminals and current remain authoritative.
// Prepared, player-placed and preview wires share separated floor lanes.
export function wireRoute(a, b, lane = 0) {
  const floor = .012, frontA = a[2] + .045, frontB = b[2] + .045;
  const z = Math.max(frontA, frontB) + .14 + lane * .035;
  const points = [a, [a[0], a[1], frontA], [a[0], floor, frontA],
    [a[0], floor, z], [b[0], floor, z], [b[0], floor, frontB], [b[0], b[1], frontB], b];
  return points.filter((p, i) => !i || p.some((v, k) => Math.abs(v - points[i - 1][k]) > 1e-9)).map(p => [...p]);
}

// A schematic of an existing ideal contact/coil circuit, not new electrical
// or mechanical geometry. Body-local connector anchors follow measured poses.
// The two contact bodies remain separate: no cable bridges their open gap.
export function contactCircuitDiagram(circuit, machine, bodies) {
  const touch = circuit.switch?.touch;
  const battery = machine.batteries?.find(b => b.name === circuit.battery);
  if (!touch || touch.length !== 2 || !circuit.coil || !battery) return null;
  const names = [battery.in, ...touch, circuit.coil.heats];
  if (names.some(name => !bodies.has(name))) return null;
  const point = (name, offset) => {
    const b = bodies.get(name), [w,x,y,z] = b.orientation_wxyz || [1,0,0,0];
    const [vx,vy,vz] = offset, tx=2*(y*vz-z*vy), ty=2*(z*vx-x*vz), tz=2*(x*vy-y*vx);
    return [vx+w*tx+y*tz-z*ty, vy+w*ty+z*tx-x*tz, vz+w*tz+x*ty-y*tx].map((v,i)=>v+b.position_m[i]);
  };
  const size = name => bodies.get(name).dimensions_m || [.04,.04,.04];
  const fixed = touch.find(name => machine.parts?.find(p=>p.name===name)?.fixed) || touch[1];
  const moving = touch.find(name=>name!==fixed);
  const source = size(battery.in), target = size(circuit.coil.heats);
  const supplyPlus = point(battery.in,[-source[0]*.3,source[1]/2,source[2]/2+.003]);
  const supplyMinus = point(battery.in,[source[0]*.3,source[1]/2,source[2]/2+.003]);
  const pad = point(fixed,[0,0,size(fixed)[2]/2+.003]);
  const tip = point(moving,[0,0,size(moving)[2]/2+.003]);
  // The coil is represented at its thermal target, outside the body so the
  // connection can be seen, just as the explicit electrical terminal dots.
  const coilPlus = point(circuit.coil.heats,[-.018,0,Math.max(.08,target[2]/2+.015)]);
  const coilMinus = point(circuit.coil.heats,[.018,0,Math.max(.08,target[2]/2+.015)]);
  return {name:circuit.name, fixed, fixedIsStatic:Boolean(machine.parts?.find(p=>p.name===fixed)?.fixed), moving, coil:circuit.coil.heats,
    contactCenters:touch.map(name=>[...bodies.get(name).position_m]),
    legs:[{id:'supply',a:supplyPlus,b:pad,color:0xf19076},
          {id:'switched',a:tip,b:coilPlus,color:0xf19076},
          {id:'return',a:coilMinus,b:supplyMinus,color:0x83bbff}]};
}

// Each material keeps one recognisable colour. Colour is only identification:
// the engine's laws come from the material's declared properties, never from this.
export const MATERIAL_COLORS = {oak: 0xb07a45, iron: 0x5d636b, concrete: 0xa9a9a2, glass: 0x9fd8ef, ice: 0xd9f3ff,
  rubber: 0x2b2b2b, aluminum: 0xc7cdd3, ceramic: 0xeeeae2};
export function materialColor(material, rgba) {
  return MATERIAL_COLORS[material] ?? engineColor(rgba);
}

export function engineColor(rgba) {
  const v = parseInt(String(rgba || '9aa4adff').slice(0, 6), 16);
  return Number.isFinite(v) ? v : 0x9aa4ad;
}

// Measured temperature as colour: unchanged up to 320 K, then toward dull red
// at 600 K and bright orange-yellow at 1100 K. Only bodies the heat network
// reports are tinted; the legend names the quantity and its units.
export function heatTint(baseHex, kelvin) {
  if (!Number.isFinite(kelvin) || kelvin <= 320) return baseHex;
  const stops = [[320, [0, 0, 0], 0], [600, [150, 30, 10], .55], [900, [235, 90, 20], .8], [1300, [255, 210, 80], .95]];
  let i = 0;
  while (i < stops.length - 2 && kelvin > stops[i + 1][0]) i++;
  const [k0, c0, w0] = stops[i], [k1, c1, w1] = stops[i + 1];
  const f = Math.min(1, Math.max(0, (kelvin - k0) / (k1 - k0)));
  const glow = c0.map((c, j) => c + (c1[j] - c) * f), weight = w0 + (w1 - w0) * f;
  const base = [(baseHex >> 16) & 255, (baseHex >> 8) & 255, baseHex & 255];
  const mix = base.map((c, j) => Math.round(c * (1 - weight) + glow[j] * weight));
  return (mix[0] << 16) | (mix[1] << 8) | mix[2];
}

// Where the camera should look: the parts named by the first station not yet
// measured as done (the last station once all are). Averages the parts'
// current positions, including the pieces of a broken part.
export function focusPoint(stations, machineStations, bodies) {
  if (!Array.isArray(machineStations) || !machineStations.length) return null;
  let index = (stations || []).findIndex((s, i) => !s.done && (machineStations[i]?.focus || []).length);
  if (index < 0) {
    for (let i = machineStations.length - 1; i >= 0; i--) if ((machineStations[i].focus || []).length) { index = i; break; }
  }
  if (index < 0) return null;
  const at = stationPoint(machineStations[index], bodies);
  return at ? {index, at} : null;
}

// Where one station's parts are now: the middle of the bodies it names
// (pieces of a broken one count as it), or nothing when none is there.
export function stationPoint(machineStation, bodies) {
  const names = new Set(machineStation?.focus || []);
  const points = [];
  for (const b of bodies.values()) if (names.has(b.name) || names.has(family(b.name))) points.push(b.position_m);
  if (!points.length) return null;
  const sum = points.reduce((a, p) => [a[0] + p[0], a[1] + p[1], a[2] + p[2]], [0, 0, 0]);
  return sum.map(v => v / points.length);
}

// The engine's traced rays of light as line segments to draw: each path is a
// light's id, its corners in millimetres (x, y, z running) and the watts on each
// leg. A leg is as bright as its share of the strongest leg, never fully dark,
// so a faint reflection still shows where it goes. Returns flat positions in
// metres (two points a leg) and colours (r, g, b, 0 to 1, per point).
export function beamSegments(paths) {
  const legs = [];
  let strongest = 0;
  for (const p of paths || []) {
    const mm = p.mm || [], w = p.w || [];
    for (let k = 0; k + 1 < mm.length / 3 && k < w.length; k++) {
      legs.push([mm.slice(3 * k, 3 * k + 3), mm.slice(3 * k + 3, 3 * k + 6), w[k]]);
      strongest = Math.max(strongest, w[k]);
    }
  }
  const positions = new Float32Array(legs.length * 6), colors = new Float32Array(legs.length * 6);
  legs.forEach(([a, b, w], i) => {
    const glow = strongest > 0 ? .25 + .75 * Math.sqrt(Math.max(0, w) / strongest) : .25;
    for (let j = 0; j < 3; j++) { positions[6 * i + j] = a[j] / 1000; positions[6 * i + 3 + j] = b[j] / 1000; }
    for (const o of [0, 3]) { colors[6 * i + o] = glow; colors[6 * i + o + 1] = .85 * glow; colors[6 * i + o + 2] = .35 * glow; }
  });
  return {positions, colors, legs: legs.length};
}

export function describeTime(seconds) {
  if (!Number.isFinite(seconds)) return '–';
  return seconds < 60 ? seconds.toFixed(2) + ' s' : Math.floor(seconds / 60) + ' min ' + (seconds % 60).toFixed(1) + ' s';
}
