// Player-facing explanations of the declared mechanisms, never solutions.
const pieces={plank:'a plank',ramp:'a ramp',knife:'a swinging knife',mirror:'mirrors',lens:'a glass lens',
  solar:'a solar panel',power_cable:'a power cable',tackle:'a block and tackle',weight:'a weight',
  spring:'a spring',gear:'a gear',motor:'a motor',battery:'a battery',wire:'wires',bulb:'a bulb',
  switch:'a switch',resistor:'a resistor',capacitor:'a capacitor',water_tank:'a water tank',
  water_wheel:'a water wheel',water_chute:'a water chute',steam:'a boiler and piston',
  ignition:'a heating coil',cannon:'a cannon',catapult:'a counterweight catapult'};
export const LEVEL_MECHANISMS=Object.freeze({
  'easy-weight':'A falling weight pushes one end of the lever down, turning it around its pivot.',
  'easy-spring':'A compressed spring stores energy. Its latch holds a push plate until you release it; the plate must touch the box to lift it.',
  gap:'The marble rolls along supported surfaces. Your plank can bridge the gap between the tables.',
  'easy-tackle':'A falling counterweight pulls a rope through pulleys to lift the waiting crate.',
  'easy-lens':'A curved glass lens bends the laser beam. Its curvature and position change where the light concentrates.',
  'easy-cut':'Gravity swings the knife. Its edge must reach the cord and cut it to release the weight.',
  'easy-mirror':'The mirror reflects the laser. Turning its face changes the direction of the reflected beam.',
  'easy-catapult':'The raised counterweight falls and turns the arm. Its cradle pushes the marble into the air.',
  cut:'Gravity swings the knife. Cutting the supporting cord lets the weight fall into the bin.',
  tackle:'Extra rope passes reduce the counterweight needed, but the counterweight must travel farther for the same lift.',
  laser:'Mirrors redirect the laser around obstacles. Light reaching the cord heats and weakens it until the weight can fall.',
  'easy-gears':'A powered gear pushes on the teeth of its neighbour. Gear size and spacing determine whether the teeth can engage.',
  'easy-motor':'A connected battery supplies the motor. The motor applies torque to the axle; its direction determines which way it turns.',
  'easy-bulb':'The bulb needs enough voltage and power from the shared supply. Changing its size changes its power demand.',
  'easy-loop':'Current needs a complete path from the supply, through the lamp, and back to the supply. Crossing wires do not join.',
  'advanced-resistor':'A series resistor limits current and takes part of the supply voltage, leaving less power for the lamp.',
  'easy-switch':'Moving the handle brings its metal contacts together, completing the path that powers the lamp.',
  'easy-marble-light':'The marble presses a broad deck. That lowers a metal contact onto its pad and closes the lamp circuit.',
  'easy-power':'The battery supplies voltage. A complete feed and return carry current; thin wires can lose voltage along the way.',
  'advanced-parallel':'Series lamps share the supply voltage. Parallel branches each have a path across the supply.',
  'advanced-capacitor':'Current charges the capacitor through a resistor. Its capacitance and voltage determine how much energy it stores.',
  'easy-solar':'Sunlight reaching the panel produces electrical power. Its cable carries that power to the battery.',
  'easy-charge-lift':'The panel captures sunlight and charges the connected battery. The battery supplies a motor and a shared bulb load.',
  sun:'Sunlight reaching the panel supplies the connected winch. Shade and panel angle change how much power is available.',
  'easy-water-receiver':'Gravity pours water through the tap. A wider opening increases flow; the flow slows as the tank drains.',
  'easy-river-wheel':'Moving river water pushes on the immersed paddles and turns the wheel. Paddles on the bank receive no river drive.',
  'easy-water-wheel':'Falling water must hit the wheel’s paddles to turn it. The tank’s tap controls the flow.',
  'easy-river-lift':'River water turns the immersed paddles. The axle winds a connected rope to lift the gate.',
  'easy-water-gate':'Water from the separate tank turns the paddles. The wheel winds a connected rope to lift the gate.',
  'easy-divert-water':'Try It! starts the water automatically. The chute redirects it; gravity carries it downhill toward the receiving container.',
  steam:'Heat raises the pressure beneath the piston. That pressure pushes against the piston and moves it upward.',
  'easy-heat':'Click Clip to cord to attach the coil, choose Hot, then Place. Connect supply + to heater + and heater − to supply −. Current heats and weakens the cord until the weight drops.',
  chain:'The marble tips the seesaw and closes its metal contacts. Current heats the cannon’s igniter, releasing the shot.',
  fire:'Closing the wired trigger heats the cannon’s powder. Expanding gas pushes the ball, which must strike the block.'
});
function goalDescription(level,fallback){
  const rule=level.goal?.station?.done_when||{},family=level.variant?.family||level.id;
  if(rule.turned_deg){
    const target={'easy-weight':'lever','easy-gears':'big wheel','easy-river-wheel':'wheel','easy-water-wheel':'wheel'}[family];
    if(target)return `Turn the ${target} at least ${rule.turned_deg.deg}°.`;
  }
  if(rule.rose_m){
    const target={'easy-spring':'box','easy-tackle':'glass crate','easy-charge-lift':'flag','easy-river-lift':'gate','easy-water-gate':'gate'}[family];
    if(target)return `Lift the ${target} at least ${Number((rule.rose_m.m*100).toFixed(3))} cm.`;
  }
  if(rule.hinge_beyond_deg)return `Turn the axle past ${rule.hinge_beyond_deg.deg}° in the required direction.`;
  if(rule.lit_w)return `Aim the beam at the sensor and deliver at least ${rule.lit_w.w} W of light.`;
  if(rule.load_power_w){const r=rule.load_power_w;return `Keep ${r.devices?'both lamps':'the lamp'} powered at ${r.at_least_w} W${r.devices?' each':''} or more for ${r.for_s} s.`;}
  if(rule.capacitor_energy_j)return `Store at least ${rule.capacitor_energy_j.at_least_j} J in the capacitor.`;
  if(rule.charged_j)return `Charge the battery to at least ${rule.charged_j.at_least_j} J.`;
  if(rule.water_in_zone_l){const r=rule.water_in_zone_l;return `Collect at least ${r.l} litres in the receiver and keep it there for ${r.for_s} s.`;}
  if(rule.parted)return 'Heat the cord until it breaks and releases the weight.';
  const zones={gap:'Roll the marble into the cup.','easy-catapult':'Launch the marble into the receiving bin.',
    'easy-cut':'Cut the cord so the weight falls into the bin.',cut:'Cut the cord so the weight falls into the bin.',
    tackle:'Raise the crate to the shelf mark.',laser:'Burn through the cord so the weight falls into the bin.',
    sun:'Raise the weight to the green height mark.',steam:'Raise the piston into the marked height zone.',
    chain:'Knock the block into the green target zone.',fire:'Knock the block into the green target zone.'};
  return rule.in_zone&&zones[family]||fallback;
}
export function levelIntroduction(level,{title,objective}={}) {
  if(level.free)return null;
  const family=level.variant?.family||level.id;
  const names=(level.tray||[]).map(t=>t.piece==='mirror'&&t.count===1?'a mirror':pieces[t.piece]||t.title||t.piece.replaceAll('_',' '));
  const joined=names.length>1?names.slice(0,-1).join(', ')+' and '+names.at(-1):names[0]||'the available pieces';
  let works=LEVEL_MECHANISMS[family]||'Place the available pieces so their movement reaches the level’s goal.';
  if(family==='easy-spring'&&level.tray?.[0]?.knobs?.mechanism_version?.default!==3)
    works='A spring pushes or pulls its attached load toward its relaxed length. Its guide keeps the load on one axis.';
  if(family==='easy-heat'&&level.tray?.[0]?.knobs?.attachment_version?.default!==2)
    works='The connected heating coil heats its attached cord. Choose the hotter winding to weaken the cord and release the weight.';
  const goal=goalDescription(level,level.variant&&level.variant.version<3 ? level.brief : objective||level.brief);
  return {title:title||level.title,place:joined.charAt(0).toUpperCase()+joined.slice(1)+'.',works,
    goal:level.time_s?`${goal.replace(/\.$/,'')} within ${level.time_s} ${level.time_s===1?'second':'seconds'} of starting.`:goal};
}
