// Player-facing explanations of the declared mechanisms, never solutions.
const pieces={plank:'a plank',ramp:'a ramp',knife:'a swinging knife',mirror:'mirrors',lens:'a glass lens',
  solar:'a solar panel',power_cable:'a power cable',tackle:'a block and tackle',weight:'a weight',
  spring:'a spring',gear:'a gear',motor:'a motor',battery:'a battery',wire:'wires',bulb:'a bulb',
  switch:'a switch',resistor:'a resistor',capacitor:'a capacitor',water_tank:'a water tank',
  water_wheel:'a water wheel',water_chute:'a water chute',steam:'a boiler and piston',
  ignition:'a heating coil',cannon:'a cannon',catapult:'a counterweight catapult',
  marble:'a marble',block:'a block',link:'a string',rope:'a rope',wall_track:'a wall track',
  wall_peg:'a round deflector peg',wall_water_wheel:'a paddle wheel',wall_marble:'a marble',
  wall_funnel:'a wall funnel',wall_lever:'a wall seesaw',wall_water_tank:'a wall water tank',wall_pendulum:'a hinged arm with a square weight (the bob)'};
export const LEVEL_MECHANISMS=Object.freeze({
  'pinball-01':'Gravity pulls the ball down the angled deck. Rolling contact converts height into motion; the green catcher shows where it must arrive.',
  'pinball-02':'A solid rail changes the marble’s direction through contact. Join its upstream end to the side lane so the marble cannot wedge behind it.',
  'pinball-03':'Holding the launcher compresses an axial spring. Release removes your hand force; the spring pushes the rod into the ball.',
  'pinball-04':'A diagonal guide redirects the launched ball through physical contact. Its position and heading determine whether the ball returns toward the playfield.',
  'pinball-05':'Your hand turns the bearing-mounted paddle. Let go and the return spring pulls it back. This lesson has no powered motor.',
  'pinball-06':'Holding the button closes two metal contacts and completes the indicator’s circuit. Its spring separates them when you release it.',
  'pinball-07':'Current needs both the supply and return leads. Holding the real button powers the motor; the paddle strikes the ball through contact.',
  'pinball-08':'Parallel circuits share a supply but each has its own physical button. One paddle can move while the other rests; both springs return after release.',
  'pinball-09':'The rubber bumper redirects the ball using material contact. It adds no energy. The hanging target swings only when struck.',
  'pinball-10':'The spring launcher, wired flippers, passive bumpers and guides work together on an inclined deck. The open drain ends a ball; Reset reloads it.',
  'easy-wall-lift':'The wired motor turns a cradle wheel. Put the marble in the low cradle; contact carries it upward and gravity tips it onto the upper track. Reset reloads this one-pass mechanism.',
  'easy-wall-water-lift':'Water pushes paddles on the same solid shaft as the cradle. Move the tank over the right paddles and open its tap. The wheel lifts and unloads the marble without an electric motor.',
  'easy-wall-generator':'Falling water turns a wheel and DC generator. Current in its two wires lights the indicator lamp and applies opposing torque to the shaft. There is no charged battery supplying the circuit.',
  'easy-wall-air':'An external air supply pushes the marble by drag. Increase Air speed to roll it along the level track and into the cup. With no wind, the level track gives it no starting push.',
  'easy-wall-steam':'Firebox heat boils the boiler’s water. Added vapour raises pressure under the piston and pushes it upward. The boiler starts at boiling temperature; increase Firebox heat to supply energy.',
  'easy-wall-pendulum':'The blue target stays on its rail. Add the pendulum at the gold mount. Increase Release angle to raise its square bob right, then Place and Run. Gravity swings it left into the target.',
  'easy-wall-trapdoor':'The hinged flap can hold the marble or open under gravity. Lower Hinge resistance until it opens and lets the marble fall into the cup.',
  'easy-wall-spring':'The latch holds a compressed spring and push plate. Increase Relaxed length, place the plate under the marble, select Run and press Release spring beside it. The plate lifts the marble by contact.',
  'easy-wall-mirror':'The mirror reflects the horizontal laser beam upward. Move it into the beam and turn its face; the traced rays show where the light actually goes.',
  'easy-wall-lens':'A curved glass lens bends a broad beam into a smaller spot. Move it into the beam and adjust Focus / face radius while watching the traced rays and sensor reading.',
  'easy-wall-gears':'The wired motor turns the left gear. Choose the middle gear’s size and height so its real teeth engage both neighbours and turn the big wheel.',
  'easy-wall-pipe':'The pipe is hollow, with real colliding walls. Place its inlet beneath the falling marble; the slope carries it through the tube toward the cup.',
  'easy-wall-resistor':'A series resistor limits current and takes part of the supply voltage. Lower Resistance until the lamp receives enough power; watch volts and current beside it.',
  'easy-wall-capacitor':'The resistor limits charging current. A capacitor stores energy in its electrical state. Increase Capacitance until it can store four joules within the deadline.',
  'easy-wall-solar':'The panel collects sunlight according to its face angle. Tilt it toward the sun, then click Output and the battery’s Input to draw a charging cable. Only a connected cable delivers the captured energy.',
  'easy-wall-parallel':'Each lamp needs its own feed across the same supply. The return leads are ready. Draw battery plus to each lamp plus; a series chain would divide the voltage.',
  'easy-weight':'A falling weight pushes one end of the lever down, turning it around its pivot.',
  'easy-roll':'Gravity pulls the marble down a slope, and it keeps rolling along the floor. On flat ground nothing makes it start.',
  'easy-wall-drop':'Gravity drops the marble straight down. Drag it above the cup; the wall already lines up its depth. Place it, then Run to watch it fall.',
  'easy-wall-funnel':'The funnel’s wide mouth catches the marble. Gravity rolls it down the sloping sides to the narrow opening. Line that opening up with the cup below.',
  'easy-wall-seesaw':'A marble landing away from the pivot pushes one end down and tips the seesaw. Drag an end beneath the marble’s falling path.',
  'easy-wall-track':'The track attaches to the wall. Gravity rolls the marble down its slope and into the waiting cup. Drag the track left/right and up/down; its depth and slope are already set.',
  'easy-wall-peg':'A round peg deflects a falling marble. A hit on its right shoulder pushes the marble toward the cup. Drag the peg across the wall to line up that contact.',
  'easy-wall-wheel':'The falling marble pushes a paddle and turns the wheel around its axle. Hitting beside the axle supplies torque; a miss leaves the wheel still. Drag the wheel across the wall to line up a paddle.',
  'easy-wall-loop':'Current needs a complete loop. The positive lead is ready; click the lamp’s minus socket and the battery’s minus socket to connect the return. Run to see current flow and the lamp light.',
  'easy-wall-switch':'The falling marble presses the broad deck. A metal leaf touches the output pad, completing the wired lamp circuit. Put the marble above the deck to the right of its pivot.',
  'easy-wall-fill':'The tank has four litres. Move its outlet above the receiver and open the tap. A wider opening gives more flow; falling water level slows it. The meter counts water inside the receiver.',
  'easy-wall-current':'Falling water pushes the paddles. A hit beside the axle gives turning force. Move the wheel into the stream; the source eventually runs dry.',
  'easy-block':'A block stays where you set it and holds up whatever rolls over it. Its top must be level with the tables.',
  'easy-rope':'A string pulls but never pushes. It stops the falling marble moving away from the knot, so the marble swings around it.',
  'easy-thread':'A rope over a pulley redirects the pull. Connect the crate’s gold ring, go over the wheel, and finish on the counterweight. The falling counterweight then lifts the crate.',
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
  'easy-switch':'Place the prewired switch, then select Run above the scene to unlock its handle. Drag the highlighted handle downward to bring its metal contacts together and light the lamp.',
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
  'easy-divert-water':'Run starts the water automatically. The chute redirects it; gravity carries it downhill toward the receiving container.',
  steam:'Heat raises the pressure beneath the piston. That pressure pushes against the piston and moves it upward.',
  'easy-heat':'Click Clip to cord to attach the coil. Open controls → Heating power → Hot, then Place device. Connect supply + to heater + and heater − to supply −. Run: current heats the cord until the weight drops.',
  chain:'The marble tips the seesaw and closes its metal contacts. Current heats the cannon’s igniter, releasing the shot.',
  fire:'Closing the wired trigger heats the cannon’s powder. Expanding gas pushes the ball, which must strike the block.'
});
function goalDescription(level,fallback){
  const rule=level.goal?.station?.done_when||{},family=level.variant?.family||level.id;
  if(rule.turned_deg){
    const target={'easy-weight':'lever','easy-gears':'big wheel','easy-wall-gears':'big wheel','easy-river-wheel':'wheel','easy-water-wheel':'wheel','easy-wall-wheel':'paddle wheel','easy-wall-current':'paddle wheel','easy-wall-seesaw':'seesaw'}[family];
    if(target)return `Turn the ${target} at least ${rule.turned_deg.deg}°.`;
  }
  if(rule.rose_m){
    const target={'easy-spring':'box','easy-wall-spring':'marble','easy-wall-steam':'piston','easy-tackle':'glass crate','easy-thread':'glass crate','easy-charge-lift':'flag','easy-river-lift':'gate','easy-water-gate':'gate'}[family];
    if(target)return `Lift the ${target} at least ${Number((rule.rose_m.m*100).toFixed(3))} cm.`;
  }
  if(rule.hinge_beyond_deg)return `Turn the axle past ${rule.hinge_beyond_deg.deg}° in the required direction.`;
  if(rule.lit_w)return `Aim the beam at the sensor and deliver at least ${rule.lit_w.w} W of light.`;
  if(rule.load_power_w){const r=rule.load_power_w;return `Keep ${r.devices?'both lamps':'the lamp'} powered at ${r.at_least_w} W${r.devices?' each':''} or more for ${r.for_s} s.`;}
  if(rule.capacitor_energy_j)return `Store at least ${rule.capacitor_energy_j.at_least_j} J in the capacitor.`;
  if(rule.charged_j)return `Charge the battery to at least ${rule.charged_j.at_least_j} J.`;
  if(rule.water_in_zone_l){const r=rule.water_in_zone_l;return `Collect at least ${r.l} ${r.l===1?'litre':'litres'} in the receiver and keep it there for ${r.for_s} s.`;}
  if(rule.parted)return 'Heat the cord until it breaks and releases the weight.';
  const zones={gap:'Roll the marble into the cup.','easy-roll':'Roll the marble into the cup.',
    'easy-wall-drop':'Drop the marble into the green cup.',
    'easy-wall-funnel':'Guide the marble through the funnel into the green cup.',
    'easy-wall-track':'Roll the marble along the wall track into the green cup.',
    'easy-wall-peg':'Deflect the falling marble off the peg into the green cup.',
    'easy-block':'Roll the ball across the trench into the cup.','easy-rope':'Swing the marble into the green zone.','easy-catapult':'Launch the marble into the receiving bin.',
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
  if(level.project?.id==='pinball')return {
    title:`Pinball ${level.project.step} of ${level.project.total}: ${title||level.title}`,
    place:joined.charAt(0).toUpperCase()+joined.slice(1)+'.',works,
    goal:level.brief+' Your completed parts are saved in your Sandbox project.'};
  if(family==='easy-spring'&&level.tray?.[0]?.knobs?.mechanism_version?.default!==3)
    works='A spring pushes or pulls its attached load toward its relaxed length. Its guide keeps the load on one axis.';
  if(family==='easy-heat'&&level.tray?.[0]?.knobs?.attachment_version?.default!==2)
    works='The connected heating coil heats its attached cord. Choose the hotter winding to weaken the cord and release the weight.';
  const goal=goalDescription(level,level.variant&&level.variant.version<3 ? level.brief : objective||level.brief);
  return {title:title||level.title,place:joined.charAt(0).toUpperCase()+joined.slice(1)+'.',works,
    goal:level.time_s?`${goal.replace(/\.$/,'')} within ${level.time_s} ${level.time_s===1?'second':'seconds'} of starting.`:goal};
}
