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

Asked to wind it up, stop it or let it down, the chat presses the hoist's own
action on the room as it stands (`use_action`), just as E does, and `drive`
tells the running room's motor too. Neither opens the room again, so the crate
goes on from where it hangs and the battery keeps what it has given. The owner,
2026-09-15: "nothing should be resetting rooms".

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

## Operating a machine: its controller and its panel

The owner's review, 2026-09-15: "Operate in the world. Design and test on a
workbench. Use the same machine definitions, controller, and physics underneath
both." A powered machine is worked from a panel, like an appliance, not by
grabbing its drum or pressing E through a list of actions: the Machines panel
reads out, and E's choice goes back to the first whenever the crosshair or the
hand changes, so pressing E again is not "stop what I just started". The panel
and the controller come before the workbench.

**One machine, one definition.** The room's `machines` block gains `controls`:
each a machine by name, the motor it drives (by the two things its pin joins),
the parts that make it up (selecting any selects the whole machine), and what
its directions mean -- for a hoist, which way raises and its travel limits as
rope out; for a shaft, which way is forward. The chat's `build_recipe "hoist"`
writes one; a room can too.

**The controller runs in the engine, at the step rate** (planned above as
"readings and a controller"). It takes intentions -- power on or off, forward,
reverse, stop and hold, a drive setting, and later jog and move to a target --
and turns them into the motor's command and brake before each step. It governs
effort; the physics decides motion: it never sets a pose, and an overloaded
motor is never given more torque than its line.
- A hoist stops at its travel limits, slowing near them, and holds on its brake.
- Reversing is a bounded sequence: stop, then the other way.
- Every command carries a sequence number, per machine. A command older than
  the last one applied is dropped, so a delayed "raise" cannot restart a
  machine after a newer "stop"; states are said outright (power false), never
  toggled.
- It reports four things apart: **enabled** (power), **commanded** (what was
  asked), **measured** (what the shaft and load are doing) and **condition**
  (what stands in the way): brake holding, at the upper or lower limit, no
  progress under load, power limited, battery empty, or another controller or
  the hand working it. "Command accepted" is never shown as motion.
- A stop goes straight to the machine: not through a thing's action program,
  the chat or the hand, and it is acknowledged when the engine has applied it.

**Machines are addressed by identity.** The panel and the controller name a
machine and its motor by id, never "the first motor that turns this part".

**The panel.** Selecting a part of a machine selects the whole machine, and its
panel stays until it is closed or another thing is selected:
- Power, on and off;
- for a hoist **Lower · Stop & hold · Raise**, for a shaft **Reverse · Stop ·
  Forward** -- "Stop & hold" only where there is a brake, otherwise "Stop --
  it will coast";
- a **Drive setting** (a share of the battery's voltage, not a speed), with the
  measured turns a minute beside it;
- the four readings above, in words.
E on a machine opens its panel; E still picks up, places and uses ordinary
things. Working a machine by hand becomes an advanced choice. The buttons are
real buttons, with focus and pressed and disabled states.

**Increments.**
1. Control ownership and commands: an action lets go only of what it took hold
   of (a drive pressed with a ball in the hand dropped it); machines and motors
   by id; a machine-command path of its own, ordered and acknowledged.
2. The controller and the panel, with hoist limits and truthful conditions;
   then the direction on the machine -- an arrow in the shaft's own frame and a
   stripe on the drum that turns with it.
3. The workbench: an orbit camera, "inspect the installed machine" (the real
   one, running) and "design and test a draft" (a copy that cannot touch the
   world's battery or anything else).
4. Designs kept as versions, and installing one without resetting the room.

Release checks drive the page with real input: start, stop and reverse while
holding an unrelated thing; two motors on one frame; both hoist limits; a
blocked load; a reload; a start arriving late after a stop.

**What is built: increments 1 and 2 (agent/machine-control, 2026-09-15).**

- **The controller** is in the engine (`LiveControl`, `LiveWorld::control` and
  `LiveWorld::operate`). It runs before every step, on the motor's own line.
  - It is told power, a direction (-1, 0 or 1) and a drive setting, each said
    outright.
  - A hoist's travel is its rope out. Which way raises is worked out from the
    pin, the drum and which way the rope winds.
  - A hoist slows for each end of its travel and stops at it. Its command near
    an end comes from the motor's line and the load's weight.
  - Reversing, it stops first.
  - Lowering comes on from the share that holds the load still, so the rope
    never goes slack. It stops when the load comes to rest on something.
  - Raising a slack rope, it takes the slack up gently.
  - A stretch of driving that gets nowhere stops it, saying why.
  - Commands are ordered by sender and count: one no newer than the last
    applied from its sender is stale and changes nothing.
  - It is saved with the world and carried through a change, as a motor is.
  - `drive` on a motor with a controller tells the controller.
- **The runner** takes `control` and `operate`, and every step's `machines`
  carries `controls`, each with the things its machine is made of (`parts`).
  The C API is ABI 24 (`banjo_make_control`, `banjo_operate`,
  `banjo_control_count`, `banjo_controls`), and the MCP has `control` and
  `operate`, which the room's chat works the running room with.
- **A room's `machines`** gain `controls`, and every motor has one. A controller
  the room does not declare is given to it, told nothing of its own: it passes
  on what its motor was told. `build_recipe "hoist"` gives its hoist one.
- **The page's panel.** E on any part of a machine opens it, and it stays until
  it is closed.
  - Its buttons go to the controller by `POST /api/world/machine`, with the
    page's own sender and count. The answer is the acknowledgement.
  - It reads out Enabled, Commanded, Measured and Condition.
  - The turning part carries a painted stripe that turns with it, and an arrow
    round its shaft shows the way the motor drives it.
  - The Machines list and the ropes are updated in place rather than rebuilt
    every step.
- **Identity:** the page's action runner no longer takes the first motor on a
  thing. On the frame two motors share, it names both.
- **Found on the way.** A motor that started to drive did not wake what hung on
  its drum. A crate asleep under a braked drum missed the first step, the drum
  wound its rope in under it, and the crate snatched the rope. A motor starting
  to drive now wakes its pin's two bodies and what hangs from either.

**Measured.** In the engine (`tests/machine_control_tests.cpp`, at 1/60 s). The
hoist is motor_tests' own: a 26.6 kg crate on a 0.1 m drum, and a motor that
stalls at 60 N m, runs at 10 rad/s unloaded and brakes with 200 N m.

| check | result |
|---|---|
| raised at full, its top at 0.4 m of rope out | at the top in 3.03 s, with 0.4007 m out. It came in at 0.565 m/s, and at 0.111 m/s at most within 5 cm of the top |
| lowered at full, its bottom at 1.6 m | at the bottom in 2.35 s, with 1.5994 m out. It went out at up to 1.433 m/s where the motor's line says 1.434, and at 0.110 m/s within 5 cm |
| the rope, lowering | it carried at least 206.7 N of the crate's 260.6 N. Before the soft start it went slack, and the crate snatched it at 2.24 m/s |
| told to lower while raising | it stopped first for 0.017 s, and was coming down 0.07 s after it was told |
| a start (count 5) arriving after a stop (count 6) | stale, and nothing moved |
| raised into a fixed beam | "stalled: it made no progress, so it stopped" after 3.03 s, and it drew nothing after |
| raised at 0.3 of its voltage | "too weak at this setting: the load turned it back, so it stopped" after 1.52 s |
| lowered onto a slab | "the load is down: its rope is slack" after 0.70 s, with 1.705 m out; the crate met the slab at 1.65 |
| a flywheel forward at half its voltage, then reversed | 39.8 rpm, against 47.7 unloaded at half. It stopped first for 0.52 s, then turned at -27.4 rpm |
| saved and opened again | on, stopped, setting 0.9, last told by the page's count 4; a start older than that count is still stale |

In the page, with real input:

- **`tests/world_page_journey_tests.py`, which CI runs.** Power On and Raise,
  clicked, raised the crate 0.874 m in 1.5 s, by exactly the 0.874 m of rope
  wound on. It stopped by itself at 0.300 m out, and the panel said "at the
  top". A press the browser cancelled did nothing.
- **In the valley, on a room the room's chat built (`headless_panel.py`):**
  - the top was 0.300 m of rope out against 0.300, and the bottom 1.750 m
    against 1.750, and the panel said so each time;
  - a Raise held back behind a later Stop was dropped, and the panel said the
    machine did not take it;
  - after a reload mid-raise it went on raising;
  - raised into a block the chat fixed over the crate, it stopped and said it
    had stalled;
  - a second drum and motor the chat put on the same post raised its own crate
    1.142 m, while the first stayed still;
  - it ran at 99.5% of realtime.

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
`machines`, and so does the opening of a world opened again from a saved one:

- each store's charge and what it has given;
- each motor's state, readings and account, and the two things its pin joins;
- each drum rope's rope out, rope wound on and tension, and where it leaves
  the drum and meets the load, for drawing.

A saved world keeps the stores, the motors and the ropes on drums, so a
restart gives a machine back as it stood.

**A controller's sensors** go on the controller in the room's `machines`, each
where it is as the room is made, in millimetres, like a pin:

```json
"controls": [{"name": "cart", "on": ["cart", "cart-1"],
              "sensors": [{"kind": "water", "body": "cart", "at_mm": [0, 1603, -12355],
                           "depth_mm": 10, "stops": 1}]}]
```

- `kind` is `"water"`, the only kind so far. It reads the depth of the room's
  water under the point.
- `stops` is the direction it stops the machine going: 1 forward, -1 back.
- `depth_mm` is more than 0 and at most 10 m.
- A controller has at most 8 sensors.

The runner's `sense` operation puts one on:
`{"op": "sense", "control": id, "kind": "water", "body": "cart", "at_m": [x, y, z], "depth_m": 0.01, "stops": 1}`.
Each controller that `machines` reports carries its `sensors`: for each, where
it is now (`at_m`), what it reads (`reading_m`), and whether it sees more than
its depth (`sees`). A controller's `parts` are its motor pin's two things, a
hoist's load, and whatever else turns on a pin through a part of the machine
that moves with it, and on through those; nothing is followed through anchored
scenery.

**A machine's program** goes in the room's `machines` too, on its wheels'
controllers by their names:

```json
"programs": [{"name": "rover", "kind": "roam", "left": "left wheel", "right": "right wheel",
              "body": "rover", "setting": 1, "climb_deg": 8, "power": false,
              "sensors": [{"kind": "water", "body": "rover", "at_mm": [550, 1028, -7966],
                           "depth_mm": 3}]}]
```

- `kind` is `"roam"`, the only kind so far.
- `left` and `right` name the controllers of two shafts on pins through
  `body`, which no other program works.
- `setting` is the drive setting it tells its wheels, and `climb_deg` the
  steepest ground it goes on.
- `power` says whether it starts running.
- Its sensors stop nothing themselves, so they say no `stops`.

The runner's `program` operation makes one
(`{"op": "program", "name", "kind", "left": control id, "right": control id,
"body", "setting", "climb_deg"}`); `sense` with `"program"` in place of
`"control"` puts a sensor on it; and `run` turns it on or off, by a sender and
its count as `operate` does (`{"op": "run", "program": id, "sender", "seq",
"power"}`). `machines` reports each program: what it is `doing` and `why`, for
how long, how far it has turned, how many `turns` it has made, the slope under
it (`pitch_deg`, `roll_deg`), its sensors with their `side`, and its `parts`. A
saved world keeps its programs.

## Milestone 2, its first step: a cart that stops at the water's edge

**Status, 2026-09-22.** The Workshop's cart drives itself down a shore and
stops at the water's edge. It is three exact bodies turning on two pins, a
chassis and two wheelsets, with:

- a 24 V battery holding 100 kJ, in its chassis;
- a DC motor with a brake on the pin of its back wheels: 20 N m at a standstill
  and 60 turns a minute unloaded, which is about 1 m/s on its 320 mm wheels,
  and 40 N m of brake;
- a controller with a **water sensor**. The sensor looks straight down at the
  ground 0.6 m in front of the deck. Where the water there is more than 10 mm
  deep, the controller will not drive forward, and brakes.

These are a demonstration machine's numbers, which the room declares. They were
not measured from a real cart.

A sensor is a point on one of the machine's parts, and it moves with that part.
Each step it reads the depth of the room's water under that point. It has a
depth and a direction it stops: deeper than its depth, and the controller will
not drive that way, and says why ("water ahead: it stopped at the water's
edge"). It can still drive the other way, so a cart stopped at the edge can back
away. Nothing in the world is changed by a sensor. It reads only what is there.

Measured in the engine:

- On a flat floor, driven for 3 s, the cart went 2.60 m and reached 0.995 m/s.
  The battery gave 52.9 J, which was the motor's work (27.5 J) plus its heat
  (25.4 J).
- On the test room's shore, it went 6.0 m in 5.2 s and stopped on its brake. The
  sensor had seen 19 mm of water, and the front wheels were 0.13 m short of the
  water's edge. Told forward again, it does not move. Told back, it backs away.
- Downhill, gravity drives the cart faster than the motor's unloaded speed, so
  the motor mostly holds it back: the battery gave 26 J, the motor's work was
  -83 J, and 110 J became heat. Nothing goes back into the battery (D2).

It can be worked in the page at `/world?scene=tests-cart`. That is a test room
off the menu, built and driven before it is written by
`tools/build_cart_room.py`:

- a round lake in a basin 32 m across, with the cart 13.5 m out on its shore,
  facing the middle;
- E on any part of the cart opens its panel. A machine is everything that turns
  on a pin through either of its motor's two things, so the front wheels count,
  though the motor does not turn them;
- Power On and Forward send it down the shore. The sensor is drawn as a bead on
  a thread down to the ground. The bead is blue while the sensor reads less than
  its depth, and turns amber when it sees more;
- the panel's Measured line gives the sensor's reading, and its Condition says
  why the cart stopped.

What made it possible:

- **Rooms of exact bodies take machines.** A battery can be in an exact body,
  and a motor can sit on a pin between exact bodies. A saved world keeps the
  motors and controllers of a room with exact bodies, which the engine refused
  to carry before.
- **The sensors are declared in the room** and kept in a saved world
  (`tests/cart_drive_tests.cpp`, `tests/cart_room_tests.py`).
- **A browser journey drives it** as a person would
  (`tests/world_page_journey_tests.py`, `ACartDrivesItselfToTheWater`).

Not built yet: the bump sensor, roaming, and finding a charging post and
docking at it. These are the rest of this milestone. The room and the runner
carry sensors; the C API, the Python binding and the chat's tools do not yet.

## Milestone 2, its second step: a rover that roams

**Status, 2026-09-22.** A rover roams a lake's shore by itself: it goes
forward, turns away wherever it sees water, turns back from ground too steep
to climb, and never puts a wheel in the water. Nothing tells it where the lake
is. It knows only what its sensors and its own slope tell it.

**Its body** is exact bodies on pins:

- an oak deck;
- a 320 mm oak wheel on each side at the back, each on a pin of its own
  through a bearing mount;
- at the front, an iron caster fork on a swivel, with a 160 mm oak wheel
  trailing 60 mm behind the swivel's axis, so it swings round to follow.

**Its machine** is a 24 V battery in the deck and a DC motor with a brake on
each back wheel: 20 N m at a standstill, 60 turns a minute unloaded (about
1 m/s), 40 N m of brake. Each motor is worked by a controller of its own.
Driven alike, the two wheels send it straight; driven against each other,
they turn it on the spot.

**Its program** is a new layer above the controllers. It works them the way
a person works their panels, from what its sensors read, and is turned on and
off from its own panel. The one kind so far, "roam":

- It goes forward.
- Where a sensor sees water ahead, it backs off for 1.2 s, then turns away on
  the spot from the side that saw it. When both sensors see water, it turns
  one way and then the other in turn.
- Where the ground is steeper than 8 degrees, rising ahead or falling away to
  one side, it turns towards the lower side.
- Where its wheels stop for want of progress, it backs off and turns. For now
  that stands in for a bump sensor.
- It turns until it has turned at least as far as it meant to and nothing is
  in its way, or for 6 s at most.
- Turned off, it stops on its brakes.

Its two water sensors sit half a metre ahead of the deck, 0.55 m either side
of its middle, and look for more than 3 mm of water. That is the depth the
water itself counts as wet. Which side a sensor is on, and which way is
forward, the program works out from where the wheels are.

These are a demonstration machine's numbers, which the room declares.

Measured in the engine:

- Driven alike for 3 s, it went 2.84 m and veered 0.02 degrees. From rest,
  driven against each other for 3 s, it turned 200 degrees and stayed within
  a metre of where it began.
- Roaming for a minute on the test room's shore, it went 50.3 m and turned
  away 5 times. It kept between 5.7 m and 12.4 m from the lake's middle (the
  water's edge is 4.9 m out), and no wheel was ever in water. The battery gave
  2,283 J, all of it the two motors' work and heat.
- Saved while roaming and opened again, it came back doing the same thing, as
  far into it, and roamed on.

What it took, each found by the tests' own check that no wheel is ever in the
water:

- **Back off before turning.** Turned on the spot where it saw the water, it
  swung its front round over the edge, and the caster went in.
- **Sensors wider than the wheels, looking for less water.** Set inside the
  wheels' track and looking for a centimetre, they let a back wheel run along
  the shore into water they had not seen. On a curve the back wheels cut
  inside the line the front takes.
- **A slope to the side counts.** Checking only the slope ahead, it ran along
  a steep contour and spiralled up towards the basin's rim.

It can be worked in the page at `/world?scene=tests-rover`. That is a test room
off the menu, built by `tools/build_rover_room.py`, which lets the rover roam a
minute in the engine and refuses to write the room unless it stayed dry and in
the basin:

- E on any part of the rover opens its program's panel. The panel offers only
  On and Off, since the wheels are the program's to drive.
- The panel says what the program has the wheels doing, how many times it has
  turned away, the slope under it and what each sensor reads, and why it is
  doing what it does.
- The sensors are drawn as beads on threads ahead of it, blue while dry and
  amber over water. Each wheel's arrow shows which way its motor drives it.

Checked by `tests/rover_roam_tests.cpp`, `tests/rover_room_tests.py` and the
browser journey `ARoverRoamsTheShore`.

Not built yet: a bump sensor that feels a knock rather than a stall, and
finding a charging post and docking at it, which waits on decision D1. The
C API, the Python binding and the chat's tools do not carry programs yet.

## After the hoist

These follow the owner's analysis. Each is a milestone of its own, and each is
seen working in the page.

2. **One autonomous creature.** Wheels before legs: a battery cart with two
   driven wheels, a bump sensor, and a controller that roams, finds a charging
   post and docks. Its first two steps are built: a cart whose water sensor
   stops it at a lake's edge, and a rover that roams a lake's shore by itself
   (above).
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
