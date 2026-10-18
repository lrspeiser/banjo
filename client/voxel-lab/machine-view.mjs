// What the machine page draws is what the engine last measured. These helpers
// merge the engine's frames and choose colours and camera targets; none of
// them moves a simulated body or predicts anything.

// An ideal spring's coil is a depiction of its measured attachment span.
// These points do not supply collisions, force, stress or simulated wire mass.
export function springCoilPoints(a,b,radius=.025,turns=8,samples=128) {
  const d=b.map((v,i)=>v-a[i]),length=Math.hypot(...d);
  if(!Number.isFinite(length)||length<1e-6)return [];
  const n=d.map(v=>v/length),seed=Math.abs(n[1])<.9?[0,1,0]:[1,0,0];
  const cross=(u,v)=>[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]];
  const raw=cross(n,seed),norm=Math.hypot(...raw),u=raw.map(v=>v/norm),v=cross(n,u);
  return Array.from({length:samples+1},(_,i)=>{
    const t=i/samples,angle=turns*2*Math.PI*t,r=radius*Math.min(1,t*turns,(1-t)*turns);
    return a.map((x,k)=>x+d[k]*t+r*(u[k]*Math.cos(angle)+v[k]*Math.sin(angle)));
  });
}

// Editing assistance changes a proposed placement, never a simulated body.
export const PLACEMENT_GRID = Object.freeze({size_m:40, fine_size_m:10, step_m:.05, major_step_m:.5, capture_m:.008, release_m:.012});
// True 3D alignment: both transverse coordinates must match an infinite XYZ
// guide within 8 mm, and the target must be within 5 m. No screen projection.
export function workingAlignment(primary, targets, tolerance=.008) {
  if (!primary?.at?.every(Number.isFinite)) return {axes:[],matches:[],direction:null};
  const targetOnLine = (q, n) => {
    if (!q.span?.length || q.span.length !== 2 || !q.span.every(p=>p?.length===3&&p.every(Number.isFinite))) return q;
    const [a,b]=q.span, v=b.map((x,i)=>x-a[i]), w=a.map((x,i)=>x-primary.at[i]);
    const alongV=v.reduce((s,x,i)=>s+x*n[i],0), alongW=w.reduce((s,x,i)=>s+x*n[i],0);
    const vp=v.map((x,i)=>x-alongV*n[i]), wp=w.map((x,i)=>x-alongW*n[i]);
    const length2=vp.reduce((s,x)=>s+x*x,0);
    const t=length2>1e-12 ? Math.max(0,Math.min(1,-wp.reduce((s,x,i)=>s+x*vp[i],0)/length2)) : .5;
    return {...q,at:a.map((x,i)=>x+t*v[i])};
  };
  const matches=[], axes=[];
  for(const [axis,i] of ['x','y','z'].map((axis,i)=>[axis,i])) {
    const hits=targets.map(q=>targetOnLine(q,[0,1,2].map(j=>j===i?1:0))).filter(q=>q.at?.every(Number.isFinite)&&Math.hypot(...q.at.map((v,j)=>j===i?0:v-primary.at[j]))<=tolerance&&
      Math.abs(q.at[i]-primary.at[i])<=5);
    if(hits.length){axes.push(axis);matches.push(...hits.map(q=>({...q,axis})));}
  }
  let direction=null;
  if(primary.dir?.length===3&&primary.dir.every(Number.isFinite)) {
    const length=Math.hypot(...primary.dir);
    if(length>1e-9){const n=primary.dir.map(v=>v/length);
      direction=targets.map(q=>targetOnLine(q,n)).map(q=>{const d=q.at?.map((v,i)=>v-primary.at[i]);if(!d?.every(Number.isFinite))return null;
        const along=d.reduce((s,v,i)=>s+v*n[i],0),off=Math.hypot(...d.map((v,i)=>v-along*n[i]));
        return along>.02&&along<=5&&off<=tolerance?{...q,along}:null;
      }).filter(Boolean).sort((a,b)=>a.along-b.along)[0]||null;
    }
  }
  return {axes,matches,direction};
}

// Wheel planes are independent of centre height and tooth reach. All distances
// use compiled geometry, never screen projection or a lesson's stored solution.
export function wheelAlignment(primary, targets, tolerance=.008) {
  if(!primary?.wheel || !primary.at?.every(Number.isFinite))return [];
  const unit=v=>v?.length===3&&v.every(Number.isFinite)&&Math.hypot(...v)>1e-9?v.map(x=>x/Math.hypot(...v)):null;
  const normal=unit(primary.dir);if(!normal)return [];
  return targets.filter(q=>q.wheel&&q.at?.every(Number.isFinite)).map(q=>{
    const other=unit(q.dir);if(!other)return null;
    const delta=q.at.map((x,i)=>x-primary.at[i]);
    const plane=delta.reduce((s,x,i)=>s+x*normal[i],0);
    const separation=Math.sqrt(Math.max(0,delta.reduce((s,x)=>s+x*x,0)-plane*plane));
    const parallel=Math.abs(other.reduce((s,x,i)=>s+x*normal[i],0))>=.999;
    const samePlane=parallel&&Math.abs(plane)<=tolerance;
    const height=delta[1];
    return {...q,plane_m:plane,height_m:height,separation_m:separation,parallel,samePlane,
      sameHeight:Math.abs(height)<=tolerance,
      teethReach:samePlane&&separation<=primary.wheel.radius_m+q.wheel.radius_m&&
        separation>=primary.wheel.root_m+q.wheel.root_m};
  }).filter(q=>q&&Math.hypot(...q.at.map((x,i)=>x-primary.at[i]))<=2)
    .sort((a,b)=>a.separation_m-b.separation_m).slice(0,4);
}
// Only measured occupied cells. The fill is an energy budget indicator,
// not a fabricated sub-cell hole, char depth or time-to-win estimate.
export function thermalCells(light) {
  return (light?.hot_cells||[]).filter(c=>c.at_m?.length===3&&c.at_m.every(Number.isFinite)&&
    c.local_m?.length===3&&c.local_m.every(Number.isFinite)&&Number.isFinite(c.temperature_k)&&c.cell_m>0)
    .slice(0,64).map(c=>({...c,progress:c.needed_j>0?Math.max(0,Math.min(1,c.held_j/c.needed_j)):null,
      charring:c.how==='chars'&&c.cut_w>0&&!c.beyond_model}));
}
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

// A clearance drawing around conservative solid bounds. It does not supply
// cable mass, collision forces, resistance length or connector retention.
// Endpoints may be solder points in a conductor: escape its nearest face,
// then require every remaining segment to clear every expanded solid.
export function clearWireRoute(a,b,lane,solids,clearance=.022) {
  const finish=path=>[a,...path,b].filter((p,i,all)=>!i||p.some((v,k)=>Math.abs(v-all[i-1][k])>1e-9));
  const boxes=solids.map(s=>({min:s.min.map(v=>v-clearance),max:s.max.map(v=>v+clearance)}));
  const inside=(p,o)=>p.every((v,i)=>v>o.min[i]+1e-8&&v<o.max[i]-1e-8);
  const escape=p=>{
    let q=[...p];
    for(let n=0;n<boxes.length+1;n++) {
      const hits=boxes.filter(o=>inside(q,o));if(!hits.length)return q;
      const options=hits.flatMap(o=>[0,1,2].flatMap(i=>[o.min[i],o.max[i]].map(v=>{
        const point=[...q];point[i]=v;return point;
      }))).filter(point=>!boxes.some(o=>inside(point,o)));
      if(!options.length){q[1]=Math.max(...hits.map(o=>o.max[1]));continue;}
      options.sort((u,v)=>Math.hypot(...u.map((x,i)=>x-p[i]))-Math.hypot(...v.map((x,i)=>x-p[i])));
      return options[0];
    }
    return q;
  };
  const intersects=(p,q,o)=>{
    let lo=0,hi=1;
    for(let i=0;i<3;i++) {
      const d=q[i]-p[i];
      if(Math.abs(d)<1e-10){if(p[i]<=o.min[i]+1e-8||p[i]>=o.max[i]-1e-8)return false;continue;}
      const x=(o.min[i]-p[i])/d,y=(o.max[i]-p[i])/d;
      lo=Math.max(lo,Math.min(x,y));hi=Math.min(hi,Math.max(x,y));
      if(hi-lo<1e-8)return false;
    }
    return hi>1e-8&&lo<1-1e-8;
  };
  const start=escape(a),end=escape(b),original=wireRoute(start,end,lane);
  const hitBoxes=new Set();
  const clear=(p,q)=>{let ok=true;for(const o of boxes)if(intersects(p,q,o)){hitBoxes.add(o);ok=false;}return ok;};
  if(original.slice(1).every((p,i)=>clear(original[i],p)))return finish(original);
  // Add corners only for encountered obstacles; most routes need one or two
  // detours rather than a graph containing every tooth in a large machine.
  for(let attempt=0;attempt<8;attempt++) {
    const before=hitBoxes.size;
    const nodes=[start,end,...original.slice(1,-1)];
    for(const o of [...hitBoxes])for(let mask=0;mask<8;mask++) {
      const p=[0,1,2].map(i=>(mask&(1<<i))?o.max[i]:o.min[i]);
      if(!boxes.some(other=>inside(p,other)))nodes.push(p);
    }
    const cost=nodes.map(()=>Infinity),parent=nodes.map(()=>-1),done=new Set();cost[0]=0;
    for(let step=0;step<nodes.length;step++) {
      let k=-1;for(let i=0;i<nodes.length;i++)if(!done.has(i)&&(k<0||cost[i]<cost[k]))k=i;
      if(k<0||!Number.isFinite(cost[k]))break;
      if(k===1){const path=[];for(let i=1;i>=0;i=parent[i])path.unshift(nodes[i]);return finish(path);}
      done.add(k);
      for(let i=0;i<nodes.length;i++)if(!done.has(i)) {
        const next=cost[k]+Math.hypot(...nodes[k].map((v,j)=>v-nodes[i][j]));
        if(next<cost[i]&&clear(nodes[k],nodes[i])){cost[i]=next;parent[i]=k;}
      }
    }
    if(hitBoxes.size===before)break;
  }
  return null;
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

// Outline the two spherical faces used by the native lens model. These are
// display segments in metres, never a replacement collider or a larger lens.
export function lensOutline(lens) {
  const {at_m:at,axis,aperture_m:a,thickness_m:t,front_radius_m:front,back_radius_m:back}=lens;
  if (!at?.every(Number.isFinite) || !axis?.every(Number.isFinite) ||
      ![a,t,front,back].every(Number.isFinite) || a<=0 || t<=0) return [];
  const norm=Math.hypot(...axis); if (!norm) return [];
  const n=axis.map(v=>v/norm), ref=Math.abs(n[1])<.9?[0,1,0]:[1,0,0];
  const cross=(u,v)=>[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]];
  const raw=cross(n,ref), len=Math.hypot(...raw), u=raw.map(v=>v/len), v=cross(n,u);
  const sag=(R,z,r)=>R===0?z:z+R-Math.sign(R)*Math.sqrt(Math.max(0,R*R-r*r));
  const point=(x,y,z)=>at.map((p,i)=>p+u[i]*x+v[i]*y+n[i]*z);
  const out=[], segment=(p,q)=>out.push(...p,...q);
  for (const [R,z] of [[front,-t/2],[back,t/2]]) {
    if (R!==0 && Math.abs(R)<=a) return [];
    const rim=sag(R,z,a);
    for (let k=0;k<64;k++) {
      const p=k*2*Math.PI/64,q=(k+1)*2*Math.PI/64;
      segment(point(a*Math.cos(p),a*Math.sin(p),rim),point(a*Math.cos(q),a*Math.sin(q),rim));
    }
    for (const vertical of [false,true]) for (let k=0;k<32;k++) {
      const p=-a+2*a*k/32,q=-a+2*a*(k+1)/32;
      segment(point(vertical?0:p,vertical?p:0,sag(R,z,Math.abs(p))),
        point(vertical?0:q,vertical?q:0,sag(R,z,Math.abs(q))));
    }
  }
  return out;
}
// Editing gestures change declarations; simulated bodies remain engine-owned.
// A complete 240 px sweep spans a numeric knob, while turns use 1 degree/px.
export function draggedKnobValue(rule, initial, pixels) {
  const step=rule.step || .01;
  const raw=initial+pixels*(rule.turning ? 1 : (rule.max-rule.min)/240);
  const value=rule.turning ? ((raw+180)%360+360)%360-180 : raw;
  return Math.max(rule.min,Math.min(rule.max,rule.min+Math.round((value-rule.min)/step)*step));
}

// Prefer a nearby clear side of the selected solid. When space is tight,
// dock to a clear scene edge and keep the solid uncovered.
export function pieceToolbarPosition(scene, piece, size, obstacles=[], {edgeOnly=false}={}) {
  const gap=10, w=size.width,h=size.height;
  const clamp=(v,lo,hi)=>Math.max(lo,Math.min(Math.max(lo,hi),v));
  const bound=([x,y])=>({x:clamp(x,scene.left+6,scene.right-w-6),y:clamp(y,scene.top+6,scene.bottom-h-6)});
  const overlaps=(a,b)=>a.x<b.right&&a.x+w>b.left&&a.y<b.bottom&&a.y+h>b.top;
  let candidates=[[piece.right+gap,(piece.top+piece.bottom-h)/2],[piece.left-w-gap,(piece.top+piece.bottom-h)/2],
    [(piece.left+piece.right-w)/2,piece.bottom+gap],[(piece.left+piece.right-w)/2,piece.top-h-gap],
    [scene.left+6,scene.top+54],[scene.right-w-6,scene.top+54],[scene.left+6,scene.bottom-h-60]];
  for(const o of obstacles)for(const x of [scene.left+6,scene.right-w-6,o.right+gap,o.left-w-gap])candidates.push([x,o.bottom+gap],[x,o.top-h-gap],[x,piece.top-h-gap],[x,piece.bottom+gap]);
  if(edgeOnly) {
    const ys=[(piece.top+piece.bottom-h)/2,scene.top+6,scene.bottom-h-6,
      piece.top-h-gap,piece.bottom+gap,...obstacles.flatMap(o=>[o.bottom+gap,o.top-h-gap])];
    candidates=[scene.left+6,scene.right-w-6].flatMap(x=>ys.map(y=>[x,y]));
  }
  const ranked=candidates.map(bound).map(at=>({...at,penalty:(overlaps(at,piece)?100000:0)+obstacles.filter(o=>overlaps(at,o)).length*10000,
    distance:Math.hypot(at.x+w/2-(piece.left+piece.right)/2,at.y+h/2-(piece.top+piece.bottom)/2)}));
  return ranked.sort((a,b)=>a.penalty-b.penalty||a.distance-b.distance)[0];
}

// A pose part of the way between two measured poses: the position on the
// straight line between them, the turn on the shortest arc. Display only;
// fraction 0 is `a` exactly and 1 is `b` exactly.
export function blendPose(a, b, fraction) {
  const f = Math.max(0, Math.min(1, Number.isFinite(fraction) ? fraction : 0));
  const position_m = a.position_m.map((v, i) => v + (b.position_m[i] - v) * f);
  const p = a.orientation_wxyz || [1, 0, 0, 0];
  let q = b.orientation_wxyz || [1, 0, 0, 0];
  let cos = p.reduce((s, v, i) => s + v * q[i], 0);
  if (cos < 0) { q = q.map(v => -v); cos = -cos; }
  let wa = 1 - f, wb = f;
  if (cos < .9995) {
    const angle = Math.acos(Math.min(1, cos)), sin = Math.sin(angle);
    wa = Math.sin((1 - f) * angle) / sin; wb = Math.sin(f * angle) / sin;
  }
  const blended = p.map((v, i) => v * wa + q[i] * wb), norm = Math.hypot(...blended) || 1;
  return {position_m, orientation_wxyz: blended.map(v => v / norm)};
}

// Smooth playback of a live run. Frames arrive a few times a second, each the
// engine's measured state at its world time. The page draws the run a moment
// behind the newest frame: a frame is applied when the drawn time reaches it,
// and each body is drawn between that frame and the next one already received.
// Nothing is drawn past the newest frame and nothing is predicted; when frames
// stop, the drawing stops at the last one. Frames that do not advance world
// time (a paused run, cords settling before Run) are applied at once.
export class FramePlayback {
  constructor() { this.reset(0, 0); }
  reset(t = 0, now = 0) {
    this.queue = []; this.shown = t; this.applied = t; this.newest = t; this.at = now;
    this.rate = null; this.gap = null; this.lastArrival = null; this.lastT = t;
    this.received = 0; this.longestWait_ms = 0;
  }
  // `now` is milliseconds on the page's clock (performance.now()).
  receive(frame, now) {
    const advanced = frame.t - this.lastT;
    if (advanced > 1e-9 && this.lastArrival != null) {
      const wall = (now - this.lastArrival) / 1000;
      if (wall > .005) {
        const rate = advanced / wall;
        this.rate = this.rate == null ? rate : this.rate + .25 * (rate - this.rate);
        this.gap = this.gap == null ? advanced : this.gap + .25 * (advanced - this.gap);
        this.longestWait_ms = Math.max(this.longestWait_ms, now - this.lastArrival);
      }
    }
    // A frame that did not move world time starts the measurement again.
    this.lastArrival = advanced > 1e-9 || this.lastArrival == null ? now : null;
    this.lastT = Math.max(this.lastT, frame.t);
    this.newest = Math.max(this.newest, frame.t);
    this.received++;
    this.queue.push(frame);
  }
  // Move the drawn time on to `now`, applying (in order) every frame it has
  // reached. Returns the next frame to draw toward and how far toward it.
  advance(now, apply, speed = 1) {
    const dt = Math.max(0, Math.min(.25, (now - this.at) / 1000));
    this.at = now;
    const rate = this.rate ?? speed, expected = this.gap ?? .05 * speed;
    // Overdue: three of the usual intervals between frames, at least 0.25 s.
    const waiting = this.lastArrival == null || now - this.lastArrival > Math.max(250, 3000 * expected / Math.max(.05, rate));
    // A frame and a half of world time behind the newest, so a late frame
    // does not stop the motion; all of the way once frames stop arriving.
    const want = waiting ? this.newest : this.newest - Math.min(.5, 1.5 * expected);
    if (this.newest - this.shown > 1.5) this.shown = want;   // far behind (a hidden tab): catch up
    let next = this.shown + dt * rate;
    next += (want - next) * Math.min(1, dt / .35);
    this.shown = Math.min(this.newest, Math.max(this.shown, next));
    while (this.queue.length && this.queue[0].t <= this.shown + 1e-9) this.applyNext(apply);
    const following = this.queue[0] || null;
    const span = following ? following.t - this.applied : 0;
    return {next: following, fraction: span > 1e-9 ? Math.max(0, Math.min(1, (this.shown - this.applied) / span)) : 0};
  }
  applyNext(apply) {
    const frame = this.queue.shift();
    this.applied = Math.max(this.applied, frame.t);
    this.shown = Math.max(this.shown, this.applied);
    apply(frame);
  }
  // Apply everything received, for a page that is not being drawn.
  drain(apply) { while (this.queue.length) this.applyNext(apply); }
}

// A preview sample further than snap_m from the previous one (a reset or a
// rebuilt rehearsal) is shown at once rather than blended.
export const GLIDE = {snap_m: 0.5};

// Whether a pose change is a glide or a jump: a piece that moved further than
// snap_m between two preview samples was set up again and is placed at once.
export function glides(from_m, to_m) {
  if (!from_m || !to_m) return false;
  const d = Math.hypot(to_m[0] - from_m[0], to_m[1] - from_m[1], to_m[2] - from_m[2]);
  return Number.isFinite(d) && d < GLIDE.snap_m;
}

// Where a time falls among sampled preview frames ({t} rows in time order):
// the sample at or before it, the next one, and how far between them (0..1).
export function frameBlend(frames, t) {
  if (!frames?.length) return null;
  let index = 0;
  while (index + 1 < frames.length && frames[index + 1].t <= t) index++;
  const next = index + 1 < frames.length ? index + 1 : index;
  const span = frames[next].t - frames[index].t;
  const f = next === index || !(span > 0) ? 0 : Math.min(1, Math.max(0, (t - frames[index].t) / span));
  return {index, next, f};
}

// A point along a sampled path ([t, x, y, z] rows in time order) at time t,
// interpolated between samples and held at the ends.
export function pathPoint(points, t) {
  if (!points?.length) return null;
  if (t <= points[0][0]) return points[0].slice(1, 4);
  const last = points[points.length - 1];
  if (t >= last[0]) return last.slice(1, 4);
  let i = 0;
  while (i + 1 < points.length && points[i + 1][0] <= t) i++;
  const a = points[i], b = points[i + 1], f = (t - a[0]) / (b[0] - a[0] || 1);
  return [1, 2, 3].map(k => a[k] + (b[k] - a[k]) * f);
}

// Blueprints: a saved group of player pieces dropped into another design.
// Pieces refer to each other by name ("your plank 2 ..."), so a dropped copy
// renumbers those references after the pieces already in the design and
// moves every piece so the group's centre lands at the chosen ground point.
export function blueprintPlacements(saved, existing, at_m, quarterTurns=0, bindings={}) {
  const assembly=saved?.schema==='banjo.blueprint.v2'?saved:null;
  const source=assembly?assembly.pieces.map(p=>p.placement):Array.isArray(saved)?saved:saved?.placements||[];
  const rows = JSON.parse(JSON.stringify(source));
  const decode=value=>typeof value==='string'?value.replace(/^@(p\d+|port\d+)(?=$|[: ])/,(all,id)=>{
    if(id.startsWith('port')){if(!bindings[id])throw Error(`Connect ${assembly.ports.find(p=>p.id===id)?.label||id} first`);return bindings[id];}
    const index=assembly.pieces.findIndex(p=>p.id===id);if(index<0)throw Error('Blueprint contains a missing piece');
    return `your ${rows[index].piece} ${existing+index+1}`;
  }):Array.isArray(value)?value.map(decode):value&&typeof value==='object'?Object.fromEntries(Object.entries(value).map(([k,v])=>[k,decode(v)])):value;
  if(assembly)for(let i=0;i<rows.length;i++)rows[i]=decode(rows[i]);
  const offset = existing;
  const xs = rows.filter(p => Number.isFinite(p.x_m)).map(p => p.x_m);
  const zs = rows.filter(p => Number.isFinite(p.z_m)).map(p => p.z_m);
  const cx = xs.length ? (Math.min(...xs) + Math.max(...xs)) / 2 : 0;
  const cz = zs.length ? (Math.min(...zs) + Math.max(...zs)) / 2 : 0;
  const rename = value => typeof value === 'string'
    ? value.replace(/^your (\S+) (\d+)(?=$|[ :])/, (whole, piece, n) => {
        const i = Number(n) - 1;
        return i >= 0 && i < rows.length && rows[i].piece === piece ? `your ${piece} ${i + 1 + offset}` : whole;
      })
    : Array.isArray(value) ? value.map(rename)
    : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).map(([k, v]) => [k, rename(v)]))
    : value;
  const angle=quarterTurns*Math.PI/2,c=Math.cos(angle),s=Math.sin(angle);
  const point=p=>[Math.round(((p[0]-cx)*c+(p[2]-cz)*s+at_m[0])*1e4)/1e4||0,p[1],
    Math.round((-(p[0]-cx)*s+(p[2]-cz)*c+at_m[1])*1e4)/1e4||0];
  return rows.map(p => {
    const q = assembly?p:rename(p);
    if(Number.isFinite(q.x_m)||Number.isFinite(q.z_m)) {
      const at=point([q.x_m??0,0,q.z_m??0]);q.x_m=at[0];q.z_m=at[2];
    }
    for(const key of ['at_m','at_b_m'])if(Array.isArray(q[key]))q[key]=point(q[key]);
    if(quarterTurns&&Number.isFinite(q.yaw_deg))q.yaw_deg=((q.yaw_deg+quarterTurns*90+180)%360+360)%360-180;
    if(quarterTurns%2&&['along x','along z'].includes(q.axis))q.axis=q.axis==='along x'?'along z':'along x';
    return q;
  });
}

// Local IDs survive insertion and deletion elsewhere in a design. References
// to apparatus outside the selection become explicit ports, never silently
// attaching to an identically named object in the destination.
export function makeBlueprint(saved, indices, rules={},parts=[]) {
  const chosen=[...new Set(indices)].filter(i=>saved[i]).sort((a,b)=>a-b);
  const names=new Map(chosen.map((i,n)=>[`your ${saved[i].piece} ${i+1}`,`p${n}`]));
  const ports=[];
  const pieces=chosen.map((i,n)=>{
    const p=JSON.parse(JSON.stringify(saved[i])),knobs=rules[p.piece]||{};
    const encode=(value,key)=>Array.isArray(value)?value.map(v=>encode(v,key)):typeof value==='string'&&value?(()=>{
      const match=/^(your \S+ \d+)(.*)$/.exec(value);
      if(match&&names.has(match[1]))return '@'+names.get(match[1])+match[2];
      const id=`port${ports.length}`,side=value.match(/:(over|under)$/)?.[0]||'',target=side?value.slice(0,-side.length):value;
      const part=parts.find(p=>p.name===target),point=key==='load'&&part?.size_m?[part.at_m[0],part.at_m[1]+part.size_m[1]/2,part.at_m[2]]:null;
      ports.push({id,owner:`p${n}`,field:key,kind:knobs[key]?.terminal?'terminal':knobs[key]?.hinge?'hinge':'part',label:knobs[key]?.label||key,hint:target,point});return '@'+id+side;
    })():value;
    for(const [key,rule] of Object.entries(knobs))if(['part','hinge','terminal','power_port','part_list'].some(k=>rule[k]))p[key]=encode(p[key],key);
    return {id:`p${n}`,placement:p};
  });
  return {schema:'banjo.blueprint.v2',pieces,ports,placements:JSON.parse(JSON.stringify(chosen.map(i=>saved[i])))};
}
