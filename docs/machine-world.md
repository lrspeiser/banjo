# The machine world

The owner, 2026-09-15:

> "I'm thinking of making banjo a planet where there are no organics, just
> mechanical, meaning that life on this planet is not things like plants but
> they are things like machines. The reason I'm considering this is so that we
> can make animals and people that are machines vs. trying to create all the
> physics of organic creators. ... we can also have a separte canvas for complex
> machinery that doesn't have to be limited to the voxel sizes of the main
> world, and when they run they can have input/outputs/energy usage etc. that
> are just passed and used in the main world"

Once the restart slice landed, they chose this as the next piece of work. Its
first milestone is a battery driving a motor on a real load, with the energy
used and lost adding up. The second hand arrives on this road as a powered
gripper, and the wood chain (the pick, shaping wood, the valley) folds into it
rather than being built as wood content first.

**Status, 2026-09-15.** The store, the motor, the brake and the drum are built
in the engine and checked in `tests/motor_tests.cpp`:

- a flywheel spun up stays within 0.2% of the motor's own curve, turn after
  turn, and the motor's work is its spin to 0.33%;
- a stalled motor's heat is I²R exactly;
- a flat battery stops the motor and never goes below empty;
- a battery gives no more than its power;
- a brake holds without drawing, and lets go;
- a load driving the motor gives nothing back, and its lost spin all becomes
  heat (0.17%);
- a hoist's drum winds its rope on for as many turns as there is rope
  (`rigid/DrumRope.hpp`):
  - braked, the rope carries the 26.6 kg crate's weight to 0.03%;
  - lifting, the crate rises 0.834 m as the drum turns 1.33 times, which is
    the drum's radius times its turn;
  - the motor's work is the crate's height and motion to 0.26%;
  - braked at the top, the crate does not move.

A hoist can be worked in the page at `/world?scene=tests-machines`. That is
a test room off the menu, like the others:

- look at the drum, and E winds the crate up;
- Tab and E stop it, with the brake on;
- Tab and E again let it down;
- the Machines panel shows the battery's charge, what the motor is doing and
  what it drew, as work and heat, and the rope.

The C API (ABI 23) and the Python binding carry all of it:
`banjo_make_energy_store`, `banjo_make_motor`, `banjo_drive_motor`, `banjo_drum`
and `banjo_inertia_about`, with what each did read back from
`banjo_energy_stores`, `banjo_motors` and `banjo_drum_ropes` (docs/api/c-api.md,
"Machines"). `tests/banjo_ffi_tests.py` drives the flywheel and the hoist above
through the library and gets the same numbers. A saved world keeps the stores,
the motors and the ropes on drums.

The room's chat builds one with its own tools: `drum`, `store`, `motor` and
`drive` in the MCP, a `drive` step for a thing's actions, and `build_recipe`
`"hoist"` ([docs/api/mcp.md](api/mcp.md), "Machines"). Built by the recipe on the
world's terrace and worked by its own actions on the live runner:

- "Wind it up" lifted the 32 kg crate 0.4470 m in a second, for 0.4471 m of the
  drum's radius times its turn, and the battery gave the 267.251 J the motor
  drew;
- "Stop" held it still, drawing nothing;
- "Let it down" brought it down at 0.4170 m/s, where the motor's line says
  0.4173, and the battery gave nothing.

The controller comes next.

## What this is

It is a ruleset for the world, not a new engine. Creatures, tools and
factories become one kind of thing: rigid parts held by joints, some of the
joints driven, drawing on a store of energy, with sensors that limit what the
machine knows and a controller that decides what it does. The engine that runs
the room already does everything a machine does to the world. A machine's leg
pushes the ground the way the hand pushes a crate.

The first thing to build is the smallest machine that makes energy real: a
battery turns a motor, and the motor lifts a load. Every joule taken from the
battery is accounted for.

## What the engine has today

Checked against the code on 2026-09-15.

- **Parts and joints.** A machine can already be built from separate bodies.
  The joints are pins, slides, rope links, pulleys, fixings and springs
  (`LiveJoint::kind`), and each part keeps its own material. A *join* is
  different: it makes one piece out of one material, the first body's. So a
  machine is built from parts held by joints, never joined into one piece.
- **Nothing is driven.** No joint has a motor in the public API.
  - Jolt's hinge has one: a velocity or position motor with a torque limit,
    whose impulse can be read (`HingeConstraint::GetMotorSettings`,
    `SetTargetAngularVelocity`, `GetTotalLambdaMotor`).
  - Banjo uses Jolt motors only inside a cut (the kerf) and for a tool point in
    the ground.
  - The only thing that drives anything is the person's hand. It is a bounded
    force and torque, pushed inside the step's reversible trial, and its work
    is measured one kept step at a time (`LiveHand::work_j`). A motor should
    work the same way.
- **No store of energy.** [The energy contract](energy-system.md) sets out what
  a store must be. It has an identity, a capacity and power limits. Its balance
  is kept with the residual reported, and it takes no energy back without a
  supported path. None of this is built.
  - The heat model keeps one ledger (`ThermoWorld`'s `Ledger`). It already takes
    heat handed over by the mechanical side
    (`ThermoWorld::receiveMechanicalWork`).
  - That is where a motor's losses and a brake's heat should go.
- **Half a turn.** A hinge turns at most 180° each way (Jolt's range), and its
  reading wraps there. The world's winch ties the portcullis rope to a point on
  the wheel's rim, and the rope runs over two fixed sheaves. So it lifts only
  as far as that point swings, about half a turn. Nothing winds a rope onto a
  drum.
- **A drag on everything but balls.** Every moving piece except a whole ball
  loses 0.02 of its speed each second. This is Jolt's damping, kept on
  everything else when rolling resistance replaced it for balls. It is a
  numerical stand-in, not a law, and no account names it.
  - The first motor test found it: a flywheel on a frictionless pin lost 6% of
    the work put into it, and slowed by itself once the battery was flat.
  - A motor now takes the drag off what it turns, because what it turns runs
    in bearings, whose loss is the pin's friction.
  - Whether it should go from everything on a pin is decision D4.
- **Gears, unused.** Jolt also has gears and a rack and pinion
  (`GearConstraint`, `RackAndPinionConstraint`). Each couples two joints and
  reports the force it carries. Banjo uses neither yet.
- **Thin sensing.**
  - Rays report no surface normal.
  - Impacts are reported, resting contacts are not.
  - Joint readings have no rate and no reaction torque.
  - Poses have no angular velocity.
- **No controller in the engine.** `offer_actions` has no sensing, branching or
  loops. `run_action` blocks in Python. Nothing can drive a creature at the
  step rate.

## Milestone 1: a battery hoist

What a person sees and does:

- They ask the room's chat for "a battery hoist over the crate". The chat builds
  it with its own tools, since the owner's rule is that the chat builds the
  playground. The hoist is a frame, a drum on an axle with a motor, a battery on
  the frame, a switch, and a rope from the drum to the crate.
- E on the switch starts the motor. It winds the rope, and the crate rises.
  At the top it stops, and the brake holds it. E again lowers it.
- Beside the hoist, the page shows the battery's charge, the motor's power and
  speed, and the crate's height. It also shows the account: what left the
  battery and where it went.
  - into the crate's height;
  - into moving parts;
  - heat in the motor;
  - heat in the brake and bearings;
  - what is left unexplained.
- A battery that runs flat stops the crate where it is, and the page says so.
- A crate too heavy for the motor does not rise. The motor stalls and heats,
  and the page says why.
- After a restart, the battery has the charge it had and the crate is where it
  was.

Acceptance, in the page, on the real engine:

- A 20 kg crate lifted 2.00 m gains 392 J of height. The battery gives that,
  plus the motor's heat, plus friction.
- The account closes within a bound the tests justify. The proposal is 1% of
  what the battery gave. The residual is shown, and never folded into a loss.
- The flat battery, the stall and the restart all behave as above.
- The room keeps within 10% of wall clock throughout, including the settling at
  the end.
- CI runs the whole thing as a browser journey.

## The engine work for milestone 1

1. **A store (the battery).**
   - It sits on a body, with its charge and capacity in joules, a voltage, and
     a maximum power out in watts.
   - Only a kept step debits it. A refused step takes its debit back, the way
     the hand's push is taken back.
   - It is saved with the world (`banjo.world`), so a restart keeps its charge.
   - It is refilled only from a declared source (decision D1).
2. **A motor** on a hinge, wired to a store.
   - It follows a DC motor's torque–speed line. Two numbers a maker would give
     set that line: the stall torque and the no-load speed at the store's
     voltage.
   - The controller's command u runs from −1 to 1. It is the fraction of the
     voltage applied.
   - Each step, Jolt's velocity motor aims at the no-load speed for that
     command. Its torque limit is set from the line at the present speed
     (`MotorSettings::SetTorqueLimits`). The solver then applies what the line
     allows, and no more. The command and its limit are set before the step's
     reversible trial opens, as a tool's bite in the ground is: they change a
     constraint, which the trial does not allow inside it. The battery is
     debited only once the step is kept, from the motor's impulse in that step.
     A refused step debits nothing, and its retry sets the same limit again.
   - The motor's impulse gives the step's numbers:
     - the mechanical work, τω dt;
     - the current, I = τ/k, where k is the motor's torque per amp;
     - the heat in the windings, I²R dt, where R is their resistance, handed to
       the motor's body as heat.
   - The battery gives the sum of the work and the heat. That closes by
     construction. What the tests check is the other side: that the motor's
     work turns up as the crate's height and motion, and as friction.
   - No energy goes back into the battery (decision D2). When the load drives
     the motor, that energy becomes heat in the motor.
3. **A brake.** Holding is done by friction, not by current.
   - When stopped, the controller sets the hinge's friction above what the load
     can turn it with (`LiveWorld::setJointFriction`). A held crate draws
     nothing.
   - The friction's work comes from the same impulse reading. It is heat in
     the brake.
4. **A drum: a rope that winds on.**
   - The rope leaves the drum at its tangent point, so its tension turns the
     drum at the drum's radius. Its free length changes by the radius times the
     turn, for as many turns as the rope is long.
   - The turn is counted unwrapped, not wrapped at ±180°. The drum and the
     controller both need that.
   - It is a small constraint of our own (`rigid/DrumRope.hpp`). Jolt's rope
     (`DistanceConstraint`) fixes where it is tied on each body when it is
     made, and only its length can change afterwards. A rope made again every
     step would start each step with none of its tension, as a new kerf does.
     So the drum's rope is Jolt's rope with its drum end moved, as each step
     begins, to where it leaves the drum. For the step that end is a point of
     the drum, and it keeps its tension from step to step.
5. **Readings and a controller.**
   - Each motor reports its command, speed, torque, current and power.
   - Each drum reports its turns and how much rope is out.
   - Each store reports its charge.
   - A small controller runs in the engine at the step rate. It takes a command
     (run up, run down, stop and hold, or go to a height) and carries it out,
     slowing near the end and braking there. No language model is in that loop.
6. **The account.** Taking the hoist as the boundary, the battery's output
   equals:
   - the change in the moving parts' height and motion;
   - plus motor heat;
   - plus brake and bearing heat;
   - plus a residual.

   It is reported with the machine, kept in the snapshot, and shown in the page.

Owner rules 4 and 6 mean this goes through every layer:

- the C API and its docs;
- the Python binding;
- the runner's ops;
- the MCP tools the chat uses: a store, a motor, a drum, a command, and a hoist
  in `build_recipe`;
- the room spec's joint kinds;
- the page's panel and switch;
- the API-docs and chat-tool parity tests.

## The room's spelling

A room's spec gains three things, which `playground/live_session.py` opens.

- **A joint of kind `drum`:**

  ```json
  {"kind": "drum", "a": "hoist drum", "b": "crate", "at_mm": [0, 2000, 0], "axis": [0, 0, 1],
   "radius_mm": 100, "to_mm": [100, 500, 0], "winds": 1, "length_mm": 2000, "out_mm": 0}
  ```

  - `a` is the drum, a thing on a pin of its own, and `b` is the load.
  - `at_mm` and `axis` are the drum's centre and axle.
  - `to_mm` is where the rope is made off on the load.
  - `winds` is +1 if turning the drum the positive way about its axle takes
    rope on.
  - `out_mm` is how much rope is off the drum. Nothing means "as it hangs".
- **`machines`, put in after the joints:**

  ```json
  "machines": {
    "stores": [{"name": "battery", "body": "post", "capacity_j": 5000, "charge_j": 5000,
                "voltage_v": 24, "max_power_w": 0}],
    "motors": [{"on": ["post", "hoist drum"], "store": "battery", "stall_torque_n_m": 60,
                "no_load_rpm": 95.5, "brake_torque_n_m": 200}]
  }
  ```

  - A motor names its pin by the two things the pin joins, because the world
    numbers pins as they go in.
  - It gives its unloaded speed in turns a minute, as a maker would.
  - It starts with its brake on when it has one, so a crate hanging on a hoist
    does not fall when the room opens.
- **An action step `{"do": "drive", "part": "hoist drum", "command": 1}`:**
  - It tells the motor that turns the part a command from −1 to 1.
  - A command of 0 stops the motor and puts its brake on.
  - It does not need the hand.

The runner (`tools/live_world_run.cpp`) takes the operations `store`,
`motor`, `drive` and `drum`. Every step that has any machines carries
`machines`:

- each store's charge and what it has given;
- each motor's state, readings and account, and the two things its pin joins;
- each drum rope's rope out, rope wound on and tension, and where it leaves
  the drum and meets the load, for drawing.

A saved world keeps the stores, the motors and the ropes on drums, so a
restart gives a machine back as it stood.

## After the hoist

These follow the owner's analysis. Each is a milestone of its own, and each is
seen working in the page.

2. **One autonomous creature.** Wheels before legs: a battery cart with two
   driven wheels, a bump sensor, and a controller that roams, finds a charging
   post and docks.
3. **Repair and persistence.** Parts fail by what they do, such as a burnt
   motor or a cut wire, and can be repaired. A creature's identity is kept
   apart from its body.
4. **A small ecosystem.** Collectors, carriers and recyclers share the valley's
   energy.
5. **Player-built life.** The person builds a creature from parts and programs
   it.

**The machine canvas**, the owner's second idea, comes once there is a machine
to put on it. It is a separate space where a complex mechanism is built at any
scale and run on the same engine. There it is measured: its shaft torque and
speed, the power it draws, and its losses. Those measurements become a reduced
model, which the main world uses as a black box under the same account. The
reduced model is always measured, never invented.

## Decisions for the owner

- **D1. How a battery is charged at first.**
  - A charging post in the workshop that fills any battery set on it, labelled
    as unlimited for now. *Recommended: the first machine can run all day while
    the rest is built.*
  - Only from something you build, such as a hand crank or a water wheel, so
    energy is scarce from the start.
- **D2. Lowering a load.**
  - The brake and the motor turn it into heat, and the battery gets nothing
    back. *Recommended for now: nothing can make energy by mistake.*
  - The motor charges the battery as the load comes down, less its losses.
- **D3. The first machine.**
  - A battery hoist that lifts a crate 2 m. *Recommended: its account is the
    cleanest, since the lift is weight times height.*
  - A battery cart that drives across the valley. It puts wheels first, but
    rolling and ground losses cannot be counted yet.
- **D4. Things on pins slowing by themselves.** Today a door, a bell, a winch
  wheel or a seesaw slows a little every second even when its pin has no
  friction, because the engine drags on every moving piece.
  - Take the drag off anything on a pin or in a groove, and give each pin a
    real bearing friction, so doors and bells still come to rest. *Recommended:
    a bell then swings for as long as its bearing lets it, and every joule it
    loses is named.*
  - Keep today's slowing on everything except what a motor turns.
