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

**Where the panel is (2026-09-26).** In the side view, under the conversation,
in the same column as everything else the room says. It floated over the room
at the bottom left until the owner said: "there are too many windows open, have
it open on the right under the chat." Nothing it does changed in the move; what
changed is that it no longer covers the machine it is about, and there is one
place to look. The column then has four things stacked in it instead of three,
so the panel takes what it needs up to a little under half the column and does
not shrink, and the conversation, the tabs and what-you-are-looking-at give way
around it. Measured before that rule was right: in a 960x600 window the panel
came out 84 px tall, with its own On button below its own fold.

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

- `kind` is `"water"` or `"ground"`. Water reads the room's depth under the
  point. Ground reads the signed drop/step from the chassis tangent plane to
  the native terrain triangles, and trips on the absolute difference.
- `stops` is the direction it stops the machine going: 1 forward, -1 back.
- `depth_mm` is more than 0 and at most 10 m.
- A controller or program has at most 16 sensors.

The runner's `sense` operation puts one on:
`{"op": "sense", "control": id, "kind": "water", "body": "cart", "at_m": [x, y, z], "depth_m": 0.01, "stops": 1}`.

A sensor stops whoever works the controller -- but not a machine a person has
ordered somewhere ("A person's order wins").
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
- Its sensors inform the program's avoidance; `stops` is 1 for the front or
  -1 for the rear (default 1 for old declarations).

The runner's `program` operation makes one
(`{"op": "program", "name", "kind", "left": control id, "right": control id,
"body", "setting", "climb_deg"}`); `sense` with `"program"` in place of
`"control"` puts a sensor on it; and `run` turns it on or off, by a sender and
its count as `operate` does (`{"op": "run", "program": id, "sender", "seq",
"power"}`). `machines` reports each program: what it is `doing` and `why`, for
how long, how far it has turned, how many `turns` it has made, the slope under
it (`pitch_deg`, `roll_deg`), its sensors with their `side`, and its `parts`. A
saved world keeps its programs.

**A room's sun** is a key of its own, and **its solar panels** go in its
`machines`:

```json
"sun": {"elevation_deg": 50, "azimuth_deg": 200, "irradiance_w_m2": 1000},
"machines": {"panels": [{"name": "solar panel", "body": "rover", "store": "rover battery",
                         "at_mm": [0, 1174, -9006], "normal": [0, 0.994, 0.111],
                         "area_m2": 0.2, "efficiency": 0.2}], ...}
```

- `elevation_deg` is 0 to 90 above the horizon, `azimuth_deg` is round from +z
  towards +x, and `irradiance_w_m2` is 0 to 1400.
- A panel names its part and its store. It is where it is as the room is made,
  like a pin, facing along `normal`. Its `area_m2` is up to 100, and its
  `efficiency` is above 0 and at most 1.
- A program can say `rest_below` and `rest_until`: the shares of full at which
  it stops to rest and at which it goes on.

**Cables and lamps** ([Light underground](#light-underground)) go in `machines`
too, and a lamp names the run that feeds it:

```json
"machines": {"cables": [{"name": "the mine feeder", "store": "the farm battery",
                         "run_mm": [[2000, 9500, 0], [2000, 8200, -4000]], "area_mm2": 4}],
             "lamps": [{"name": "the heading lamp", "cable": "the mine feeder",
                        "at_mm": [2000, 8300, -3800], "watts": 20, "on": true}], ...}
```

- A cable names its store and the points it is pinned at, at least two and at
  most 256. Its `area_mm2` is above 0 and up to 1000 (2.5 if it says nothing),
  and `resistivity_ohm_m` is copper's 1.68e-8 unless it says otherwise.
- A lamp names its `cable`, or a `store` to be wired straight to, or NEITHER: a
  lamp with neither is a fitting nobody has wired yet, which is what comes out
  of the Workshop. `watts` is above 0 and up to 100 kW, `efficacy_lm_w` above 0
  and up to 1000 (120 if it says nothing), and `on` is false unless it says so.
  With a `body` it goes on that part and moves with it; with none it is pinned
  where it is put.

**A breaker** ([Breaking rock with a machine](#breaking-rock-with-a-machine))
goes in `machines` too:

```json
"machines": {"breakers": [{"name": "breaker", "body": "breaker", "store": "breaker battery",
                           "at_mm": [0, 2070, 9800], "along": [0, 0, 1],
                           "watts": 1500, "reach_m": 0.15}], ...}
```

- It names the thing its chisel is on and the store it draws on. `at_mm` is its
  point and `along` the way the chisel looks, as the room is made, like a pin.
  `watts` is 1 to 1e6 (1500 if it says nothing), `reach_m` 0 to 0.5 (0.12), and
  `on` is false unless it says so.
- The runner's `breaker` operation puts one on and `breaker_switch` holds its
  trigger. `machines` reports each with `breakers`: where its point is, what it
  drew, what that bought, how far through the cell it is, and why it is doing
  nothing.

**A sun with a day** ([A day for the sun](#a-day-for-the-sun)) says its day in
place of where it stands:

```json
"sun": {"day_s": 240, "noon_elevation_deg": 60, "hour": 16, "irradiance_w_m2": 1000}
```

- `day_s` is how many of the world's seconds a day lasts, from 10 to a real
  day's 86,400. `noon_elevation_deg` is from 1 to 90, `hour` is the hour the
  room begins at, 0 to 24, and `irradiance_w_m2`, 0 to 1400, is the sun's
  overhead.

The runner's `cable` operation runs a cable
(`{"op": "cable", "name", "store": store id, "run_m", "area_mm2",
"resistivity_ohm_m"}`), `lamp` hangs a lamp
(`{"op": "lamp", "name", "body", "cable": cable id, "store": store id, "at_m",
"watts", "efficacy_lm_w", "on"}`), and `lamp_switch` turns one on or off
(`{"op": "lamp_switch", "lamp": lamp id, "on"}`). `machines` reports each with
`cables` -- its run, its length and resistance, the current, the volts lost, what
it carried and what it lost -- and `lamps`: where each is, what it drew, the
lumens it gives, whether it is lit, and why not.

The runner's `sun` operation puts the sun in the sky and says it back, with
`toward`, the unit vector to it. `solar_panel` puts a panel on
(`{"op": "solar_panel", "name", "body", "store": store id, "at_m", "normal",
"area_m2", "efficiency"}`), and `program` takes `rest_below` and `rest_until`.
`machines` reports each panel with `panels`: where it is, the cosine of its
angle to the sun, whether it is in shade and by what, the sunlight on it and
the power it gives, and its account. It also reports what each store has
`taken_j`.

With `day_s`, the runner's `sun` operation gives the sun a day
(`{"op": "sun", "day_s", "noon_elevation_deg", "hour", "irradiance_w_m2",
"keep"}`). With `keep`, a world that already has that very day keeps its hour,
which is how a saved or carried world's day goes on. Every reply then carries
the `sun`, with its `hour`, `day_s`, `noon_elevation_deg` and
`zenith_irradiance_w_m2` as well as where it is.

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
- Where it has been told to go somewhere and has got nowhere for 20 s, it backs
  itself out, and after a few tries stops and says it cannot ("When a machine
  cannot get out"). It also takes care not to dig itself in ("Working a place
  without digging yourself in"), and it stops before it turns on the spot
  ("Following a line instead of weaving off it").
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

### A person's order wins

**Status, 2026-09-26.** Everything above is what the machine does of its own:
roaming, and the asks its routine and whatever decides for it make. All of it
is governed by the water reflex, and none of it will drive into a lake.

A person is not. The owner, having tried to send a rover into the water and
watched it turn away every time: *"your order wins"*. Told by somebody in its
chat, at its panel or at the keys to go somewhere, a machine goes there, water
or not. It is their machine and their mistake to make. It still sees the water
and still says so -- "I see water ahead on my left" -- it just does not turn.

The engine could not tell the two apart, and could not have. An ask carries a
sender's name (`asked_by`) and nothing else, and a name means nothing to it:
"talk", "routine", "jev" and "drive" are four strings. So the ask carries one
more thing, `by_person` (`LiveWorld::ProgramAsk`, `LiveProgram::asked_by_person`),
set by whoever makes the ask, because only they know. The chat sets it, and the
keys at the Workshop bench set it. A routine does not, and neither does a
decider: a machine thinking for itself is the machine, not a person.

An order outranks both of the things that keep a machine out of water:

- **The roaming reflex** does not interrupt it. It never backs off from water,
  never turns away, and never counts the three water scares that would make it
  give the ask up.
- **A wheel's own sensor** does not stop its motor either. The order has to win
  at both levels or it wins at neither: the program would drive at the lake and
  the wheels would refuse, and the machine would sit at the shore with its
  motors told forward. Nothing else overrules a sensor -- a person working a
  controller straight from its own panel, like the cart above, still stops at
  the water's edge and backs away by telling it the other way.

It stands the reflex aside; it does not take it away. The moment the order is
lifted -- asked nothing more, run down, turned off -- the machine is its own
again and backs out of the water it is standing in.

Measured in `tests/rover_roam_tests.cpp`, the same ask to the same point in the
same room, twice:

| | not a person's | a person's order |
|---|---|---|
| water under a wheel | 0.3 mm | 58.7 mm by 12 s |
| its reflexes took it | yes, three times | never |
| where it ended | back on the shore, the ask given up | in the lake, the order standing |

and through the playground's own route (the `tests-rover` room, `behave` with
`by_person`), 40 s after being told to approach the middle of the lake from
9 m up the shore: its own ask left it dry at z -6.4 saying "the water was in
the way of what it was asked, so it gave it up"; a person's order put it at
(0.15, -0.88), 152 mm of water under a wheel, waiting where it was sent.
## What has been seen

A room answered about ground nobody had ever been near as readily as about the
ground a machine was standing on. Every deposit in the spec went into every
machine's senses, and the page drew the whole basin from the first frame. A world
like that has nothing to find out, and a routine sent to a vein nobody had been
to was being told where to dig by the document rather than by anything that had
happened.

So a room keeps what has been SEEN (`playground/machine_sight.py`). It is a
coarse grid, a metre a cell over the ground the room covers, and it is kept with
the room, so a place stays known once someone has been there and a reload does
not forget it.

**Being there is what reveals it.** After every step, everything in the room
marks a circle round where it stands: six metres for a machine on the ground or a
person on foot, and a metre and a half more for every metre a machine is above
the ground, up to thirty. Nothing else reveals anything -- not a routine's
places, not a deposit declared in the spec, not anything the chat knows.

**Height is what a scout is for.** On the ground a machine takes in about a tenth
of a 32 m room from one spot. At ten metres up a flyer sees 21 m, twelve times the
ground, and somewhere above sixteen it takes in the whole room at once. Eight
metres and three per metre up lit two thirds of a room from three standing spots,
which is not a world with anything left to find out.

**What is held to it.** The sense that hands a machine the room's goods gives it
only the deposits and heaps in ground that has been seen, and says how many it
has not seen. The page draws ground nobody has been near as unknown -- flat and
colourless -- and does not draw water there at all, so a lake shows itself when
someone comes near enough to see it. The lie of the land is still drawn, because
hiding it would leave holes in the world; what is hidden is what is THERE.

**A survey says what is known of a place.** The `survey` tool reports the ground
round where a machine stands, or round a place it knows: its surface, how high
and how steep, what water is in it, the deposits and heaps and things standing
there, and how much of it nobody has seen. It reports; it does not reveal. Asked
about somewhere nobody has been it says so, which is the point of it, because a
place worth going to is one it cannot answer about yet.

**What it is not part of.** The record is not what the world is MADE of, so it is
left out of the word a saved world is checked against (`live_session.spec_digest`),
exactly as the goods ledger is. A room learns what is where as machines get about
it, and a world saved after they have is still that room's world.

Measured on the mine, opened fresh: nothing known, 227 of its 1,024 cells known
after one step as four machines see where they stand, and 313 after a minute of
them working -- 31% of the room. Checked by `tests/sight_tests.py`, which also
opens a real room and fails if the grid the record works out from what the room
declares ever stops matching the grid the engine reports.

Not done yet: things standing in ground nobody has seen are still drawn, so a
boulder beyond the fog is visible even though the ground under it is not. Hiding
those means deciding what a machine of your own looks like when it is out there
in the dark, which is a question about the game rather than about the ground.

### When a machine cannot get out

A machine can be held by the world without anything it watches saying so. In
the mine on 2026-09-26 the rover stood at one spot for 232 s of a 7-minute run,
driving and turning the whole time and going nowhere: it had dug 1.3 m ahead of
itself, on ground it then had to drive over, and sat against the spoil heap of
its own hole on a slope. Its wheels turned freely, so the motors were never
overloaded and the stall that stands in for a bump sensor never tripped; no
water sensor saw anything; its battery was full. Every layer above -- the
routine's three tries, the deciders, Jev -- was told only that it was
"approaching" the vein, which it was, for four minutes.

So a machine has a sense of getting nowhere, and a reflex about it.

**The sense.** While it is told to be going somewhere -- going forward, backing
off, turning either way, rising, descending -- the engine keeps where it stood
when it was told, and how long it has been inside half a metre of there. Getting
out of that circle opens a new one. Anything that is not trying to go (waiting,
digging, resting, stopped, off) clears it. The circle is the measure, not
standing still and not the wheels: in a hole a machine drives, rocks and turns
busily and gets nowhere, so the first thing tried -- reset the moment it moved
or turned five degrees -- never fired at all. The program reports it as
`stuck_s`, and how many times it has tried to get out as `stucks`; the senses
give a routine or a decider `not_getting_anywhere_for_s` and
`tried_to_get_out_times`, the conditions `getting_nowhere` (seconds, 5 by
default) and `stuck`, and a brain the events "it was not getting anywhere, so it
is getting itself out" and "it cannot get itself out of where it is" -- both
said even while something is asking it to do something, as a knock is, because
both happen to it rather than being anything it chose.

**And the one that says a thing is not over.** Every other reading a brain gets
is an EDGE: a sensor starts seeing, a wheel starts to stall, the ground turns
too steep. So a machine that is still in the same trouble a minute later has
said nothing since the first moment of it. Measured on the roaming rover, which
is the whole reason this exists: it raised one "water ahead on its left" at the
shore and then slid down the basin into the lake over the next thirty-nine
seconds without another word, because no sensor ever NEWLY saw anything. Every
sensor now keeps `seeing_s`, how long it has been seeing, zeroed the step it
stops; past eight seconds -- long enough that backing off and turning away have
had their go -- a brain is told "it is still in the <kind> and not getting
clear". It reads the same every time, deliberately: with the seconds in the
words a brain would answer each reading as a fresh thing instead of as the
thing it has not fixed yet, and it is asked again every three seconds for as
long as it is in, each question carrying what it has already tried. It is also
said THROUGH an ask, unlike the rest of the sensor readings, because a brain
that goes deaf the moment it says anything cannot tell a plan that worked from
one that did not, and so only ever gets one. None of this knows what a rover
is: any machine with a sensor that stops it gets it.

**And it gets a few goes, not endless ones.** A thing that repeats is a
timer, and a timer that asks a model is a bill: a machine stuck in front of
somebody would ask every three seconds for as long as they watched it. So a
decider gets `rover_brain.TRIES_MOST` goes at ONE episode -- three -- and
then the machine stops asking and leaves it to its reflexes, which is what
D3 below recommends. The count is per episode: the trouble clearing and
happening again is a new one, asked afresh. Nothing is asked at all while
nobody is watching (`Brains.unattended`), so a world left running overnight
still costs only the processor.

**The reflex, for a machine that drives.** Twenty seconds of getting nowhere and
it backs out: reverse, turn 110 degrees, reverse again along the new line.
Reversing alone barely rocked it; reversing again after the turn pulled it
clear. It reverses 4 s, then 8, then 12, turning the other way each time, and
once it has tried it waits only 5 s before trying again rather than 20. Three
tries at one place and it stops, holds its wheels, and says "it cannot get
itself out". Getting two metres from that place, by its own back-out or because
something else moved it, ends the episode and gives the next thing in its way
the same patience as the first. Being stuck does not make it deaf: asked to do
something it does it, so a person who comes to get it out can.

**The reflex, for a machine that flies.** It climbs over what is in its way
rather than backing round it: two metres on the height it holds, up to five
times. Then it holds where it is and says it cannot get past. It never stops its
rotors for this, whatever is in the way, because a flyer that gives up in the
air falls. Climbing is getting somewhere for the sense -- a flyer told to rise
and rising is not stuck -- but not for the place, which is measured across the
ground: without that, a walled-in drone climbed a metre at a time for ever.

**Which machines have it.** A machine that roams and a machine that flies. A
machine going to a thing to hold a pose there (the "sit" kind) has only its
older reflex, backing off where its wheels make no progress, and so has the
same blind spot: its wheels turn freely in a hole. A "still" machine is never
told to go anywhere.

Getting out of a hole is the reflex; not digging one is the other half, and that
is below.

Measured in the engine (`tests/rover_roam_tests.cpp`,
`tests/drone_hover_tests.cpp`):

| | |
|---|---|
| driven into a wall while roaming | nowhere for 20 s, one back-out, roaming again 6.5 s later, 5.4 m back from the wall; no wheel ever stalled |
| penned in 1.6 m of concrete, told to go through it | three back-outs, stuck after 45 s, never further than 0.30 m from where it began, then obeyed a person |
| a drone walled in a 14 m shaft | climbed from 1.5 m to 11.5 m in five lifts, then held, never coming below 1.75 m |

What it does not do is plan a way round. Told to approach a point through a
wall, a machine that drives backs out, turns away, and is turned straight back
at the wall by the ask. Getting itself out is not finding a route.

Getting nowhere does not count against the three water scares that make a
machine give up an ask of its own (a person's order is never given up for
water: "A person's order wins"). Backing out of something and carrying on is
the whole point of the reflex, and a machine that truly cannot get out stops and
says so on its own; counted together, one water scare and two back-outs made a
machine abandon a haul it could have finished, and it roamed for the rest of the
run.

### Working a place without digging yourself in

A machine cannot drive out of a hole as deep as its wheels are tall, and the
holes in its way are its own. So how a machine works a place is a rule of the
world, not a setting on a routine (`machine_tools`, all of it measured on the
mine's rover, 2026-09-26):

- **It bites the place it was sent to, never its own nose.** The `dig` tool
  takes a `place`, and a routine that digs passes its dig site. Biting 1.3 m
  straight ahead instead put a crater wherever the machine happened to stop and
  whichever way it was pointing: four trips to one vein left four holes 10 to
  18 cm deep spread over 2 m of ground it had to cross, and on the fifth the
  rover stood on the rim of one and could not get out.
- **It stands off the place.** `go_to` takes `stop_at_m` -- how far from the
  place to stop, since the place is about to become a pit -- and a machine told
  to stop "a metre off" rolls on while its brakes take hold, measured down to
  0.2 m. The dig routine stands 2.0 m off, which puts it between 1.2 m and
  2.0 m out: inside what it can reach, outside what it is digging.
- **It will not dig the ground under itself.** Closer than 1.2 m to the spot and
  it backs off first and says so, rather than digging where its own wheels are.
- **Each spot is scooped once, and the working is as wide as the place.** A bite
  goes into the highest ground of the place the machine can reach, and only while
  that ground is still within 30 mm of the ground around: so the working spreads
  across the place, the way an open pit is worked, and no hole is ever deepened.
  How wide it spreads is the deposit's own width where the place is in one, and
  half a metre where it is not. Biting always at the middle instead sank a shaft
  600 mm deep and 1.1 m across in ten minutes, which a machine on 160 mm wheels
  can only fall into; holding the width to half a metre gave three loads and
  then nothing, and the machine spent nine tenths of a twenty-minute run on a
  dig step it could not do.
- **Worked out is said, not scraped at.** Once every spot it can reach is down
  past that, the tool says the place is worked out and its routine goes on with
  what it has. Scraping the same exhausted spot brought up 3.8 kg, then 2.2,
  then 0.6, and would have gone on for ever.

What one scoop leaves is not a trap: driven at a hole 0.5 m wide and 150 mm
deep, the rover crosses it. What traps it is the same spot bitten over and over.

**A machine that flies digs too.** The Workshop's drone template has declared a
dig routine with a 20 kg hopper all along, and one load of it was tested, so
nothing had to be added to say it. What had to be added was the working of it:

- **It works the ground under it.** A flyer hovers over the place and scoops
  down, so it keeps no stand-off at all and nothing it digs is under its wheels;
  the reach is still measured across the ground, so it has to be over the place
  to reach it. It keeps the rest of the rules -- the high ground, one scoop a
  spot, worked out said rather than scraped at -- because the hole it leaves is
  in everyone's way, not only its own.
- **A machine out of reach goes back to the place.** Refusing outright left a
  routine sat on a dig step for the rest of the run, because the step that took
  the machine there is behind it: a drone given a dig routine wandered 4.8 m off
  the vein and said "it must go there first" for four minutes. It now asks itself
  to go to where it should stand and digs on the next go. That holds for a
  machine on wheels as much as one in the air.
- **A flyer leans back to arrive.** It has no brakes but its own rotors, and
  leaning forward the whole way in it sails past what it was sent to: measured at
  4.4 m/s over a 13 m flight, it "arrived" within a metre and then carried 8 m
  beyond the vein before it could turn round, the best part of a minute every
  trip. It leans back once what it has left to go is less than the way it would
  carry on at the speed it is going.

Measured on the mine's drone, its haul routine swapped for a dig, over five
minutes: 2 loads becomes 7, and it ends the run hovering 0.7 m from the vein
rather than 15 m away. Checked by `tests/workshop_drone_tests.py`, which now
follows it over several trips and fails if it sits out of reach of the ground it
is working.

Measured over ten minutes of the mine, the same engine both ways:

| | biting its own nose | working the place |
|---|---|---|
| loads delivered | 1 | 6 |
| the working's radius | 1.1 m | 3.3 m |
| deepest cut | 185 mm | 140 mm |
| time stuck, unable to move | 62 s | none |

Wider and shallower is the point of it: an open pit a machine drives over,
rather than a shaft it falls into.

Over twenty minutes it delivered 8 loads, took 69 kg of ore out of the vein's
400, put 18.2 kg of copper wire on the Workshop's rack, gave up no trip, never
had to back itself out, and was never once stuck.

### Following a line instead of weaving off it

A machine that turns with a driven wheel each side has no braking while it
turns: the two wheels push against each other and nothing pushes back along its
way, so one that starts a turn while it is still moving coasts onward through
the whole turn. Measured on the mine's rover, told to go from the vein to the
smelter over dry ground: it spun up to 108 degrees a second, sailed 50 degrees
past the mark, and then travelled 1.6 m at up to 80 degrees off its way while it
came round. A metre of that was northward every trip, and after a few trips it
was standing in the lake's shallows with its water reflex turning it away, which
is how a haul over dry ground gets nowhere near the ground it was about to
cross.

So a machine asked to go to a place or to face one **stops before it turns on
the spot, and stops again before it goes on**. Both stops hold its wheels on
their brakes, and it turns from rest, where it goes where it is pointed. What
counts as stopped is a sixth of a metre a second, and it waits at most a second
and a half for that, because on a slope it may never come to a complete stand.
This is the same stop-turn-go a machine holding a pose has always done
(`decideSit`), which is why that one lands on its mark, and the roaming reflexes
are untouched: getting clear of water or of a hole it is stuck in is still one
decisive turn at full effort.

Two things tried first and thrown away, both measured:

- **Aiming at where the nose will be** rather than where it is, by the swing it
  already has. It reads well and it does not work: the doing it goes into brakes
  the swing it just predicted would carry on, so the machine stopped 35 degrees
  off the mark and called itself faced.
- **Easing the turn as it closes**, at six tenths and then three tenths of its
  effort. At three tenths it could not come round on rough ground at all: it got
  itself stuck seven times in twenty minutes where it had been twice, and
  delivered nothing.

What it took, over twenty minutes of the mine each time:

| | before | after |
|---|---|---|
| loads delivered | 3 | 8 |
| copper wire on the Workshop's rack | 7.1 kg | 18.2 kg |
| time its reflexes had it for water | 288 s | 35 s |
| times it had to back itself out | 2 | none |
| time stuck, unable to move | none | none |

The haul was never the whole of it. Nine tenths of the twenty minutes had gone
on a dig step the machine could not do, because a place half a metre wide gives
three loads and is then worked out, and a machine on a step it cannot finish
roams while it waits. A place now spreads as wide as the deposit it is in, and
the mine's vein is 3 m across.

What holds the load count down is not the digging: 288 s of those 1,200 went on
its water reflex turning it away on the haul between the vein and the smelter,
which is the next thing to look at.


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
C API and the Python binding do not carry programs yet; the chat's tools carry
them as far as the bench (`set_program`).

## Milestone 2, its third step: a robot that goes somewhere and sits down

**Status, 2026-09-24.** A robot is told where a stool is. It comes round onto
it, drives at it, stops within reach, lowers its torso, and the seat stops the
torso short of the angle it was reaching for -- because the stool is carrying
it. It holds there. Nothing about the path is scripted: it is told where the
thing is, as a person across a room can see a chair, and everything after that
is the world's answer.

Measured: it crosses 3.8 m in 16.8 s, stops 0.62 m from the stool's middle and
3.5 degrees off square, and its torso comes to rest 24 mm above the seat and
45 mm in from its middle. Three seconds later it has not moved by a thousandth
of a millimetre, and the stool has moved 0.006 mm.

**The program**, `"sit"`, is the second kind. It is told four things besides
what a roaming program is told: the body it goes to (`toward`), how near that
body's middle its own chassis's middle comes before it is there (`close_m`),
the controller it works when it gets there (`pose`) and the angle it turns that
pin to (`pose_deg`, from where the pin was made). Then:

- It turns on the spot until its nose is within 3 degrees of the line to the
  thing, stops, and drives at it.
- Driving, it lets itself drift 8 degrees off that line before it stops and
  comes round again -- but not within the first 2.5 s of a leg, which is how
  long its caster takes to straighten.
- Where its wheels make no progress it backs off for 1.2 s and comes round;
  where it has turned for 2 s without coming round it backs off and tries
  again; where it has turned for 6 s it gives up and drives at the thing as it
  is.
- Within `close_m` it stops on its brakes and works its pose controller toward
  `pose_deg`. It holds what it has when it gets there, when the pin stops for
  want of progress -- it has come to rest on something -- or after 20 s.
- Sitting, everything is held on its brakes. Turned off, it stops.

**It stops before it changes what its wheels are doing**, and waits for the
MACHINE to stop, not its wheels. Three things were built and measured on the
way to that, and each is why a line of it is there:

- A wheel told to turn the other way stops first: a motor is not slammed into
  reverse while its shaft spins. A machine that went straight from driving into
  a turn coasted on with one wheel waiting to stop and the other still pushing,
  and drove 35 s straight past a stool 1.3 m away while the program said
  "turning left".
- Wheels on their brakes read nothing while the machine slides on, so waiting
  for the wheels is not waiting for the machine. And a machine still rolling
  cannot turn at all: its caster is trailing straight, which holds the front
  from swinging, so one wheel grips and drives it on at its own rolling speed
  while the other skids backwards. That state sustains itself, because going on
  is what keeps the caster straight.
- It cannot steer while it rolls, and does not try. Easing the inner wheel's
  drive does nothing: a drive setting is an effort, not a speed, and a rolling
  machine carries its wheels along whatever they are told -- the inner wheel
  turned 22.6 rpm on a seventh of the voltage while the outer turned 22.4 on
  all of it. Braking the inner wheel does not turn it either: the outer wheel
  skids instead, and the machine crawls at 40 mm a second holding its heading
  to a fifth of a degree a second. A turn on the spot from a standstill does
  work, at 23 degrees a second.

**The robot** is the rover's parts drawn short, because the rover cannot hold a
line after a turn. The rover's caster is 0.70 m in front of the axle its wheels
turn about, so coming round swings the caster through a wide circle and leaves
it lying across the way the machine then wants to go; driving off, it scrubs
round and pulls the machine about 20 degrees off for every metre travelled. A
rover told to go to a stool 3.8 m away zigzagged for 40 s and arrived 30
degrees off, its torso coming down beside the stool rather than on it.

So the robot's caster is 0.27 m in front of its axle -- a quarter of the arm,
so a quarter of the scrub. Three points on the ground and no more: a caster at
each end was built and measured first, and it could not turn at all. Four
points on a rigid deck are one too many; the casters took the weight, and the
driven wheels span at their unloaded speed while the robot stood still.

**Its torso** is an oak bar 500 mm long on a pin on a mast, 600 mm up. The mast
is there because a torso swinging up from below the seat catches its near edge:
measured, it stopped 15 mm off that edge with its far end still 127 mm above
the seat, and called itself sat down. A bar rising from a pin below the seat can
never land its end on the seat -- every part of it between the pin and the end
is lower than the end. Swinging down from above, it comes down onto the seat
with the rest of it in the air.

**What a room declares** is the program with its four extra words:

```json
{"name": "robot", "kind": "sit", "left": "left wheel", "right": "right wheel",
 "body": "robot", "toward": "stool", "close_m": 0.68,
 "pose": "torso", "pose_deg": 125.0}
```

`toward` is the room's own name for something already standing in it, which is
why the bench takes it as given: a design does not know what a room contains.
A `"sit"` program does not rest -- it is on its way somewhere -- so a
`rest_below` with it is refused rather than ignored.

**What it reports**, besides what a roaming program reports: how far away what
it goes to is and which way that is off its nose (`toward_m`, `bearing_deg`),
where its pose pin has got to (`pose_at_deg`), and how fast the machine itself
is going across the ground (`speed_m_s`).

**In the world**: `/world?scene=tests-sit`, flat ground with the robot and a
stool 3.8 m off and 23 degrees to its left. E on any part of the robot opens its
program's panel, which offers On and Off as a roaming machine's does. Laid out,
and watched sitting down before it is written, by `tools/build_sit_room.py`; in
the room it takes 12.5 s, stops 0.51 m from the stool's middle and 3.4 degrees
off square, and rests its torso 24 mm above the seat and 142 mm in from its
middle, moving the stool 18 mm.

Checked by `tests/rover_roam_tests.cpp` ("it goes to the stool and sits on it")
and `tests/rover_room_tests.py` (`SittingDown`).

Not built yet: nothing draws a sit program's panel differently from a roaming
one, and the robot is a test machine rather than one the Workshop bench has
drawn.

## Solar panels

**The owner's decision, 2026-09-22 (D1):** a machine's battery is charged by
solar panels.

**Status, 2026-09-22.** A room can have a sun, and a machine can carry solar
panels that charge its battery from it. The rover rests in the sun when its
battery runs low, and roams on once the panel has charged it.

**The sun** is the room's to declare: how high it stands, which way it lies,
and how strongly it shines on a surface square to its beam. A clear day's is
about 1000 W/m2. It stands where it is put, or it has a day and goes round
([A day for the sun](#a-day-for-the-sun)). The page is lit from where the
engine has it.

**A solar panel** is a flat collector fixed on a part and wired to a battery.
Each step, it puts into the battery the sunlight on its face times its
efficiency. The sunlight on its face is the sun's irradiance, times the
panel's area, times the cosine of the angle between its face and the sun.

- With the sun behind its face, it makes nothing.
- In shade it makes nothing. A ray from just off its face towards the sun
  finds anything in the way, a thing or the ground, and the panel names it.
- A full battery takes no more, and the rest is spilled.
- The sunlight it does not turn into charge is counted as heat, which warms
  nothing yet.
- A battery now counts what it takes in as well as what it gives. What it
  holds is what it began with, plus what it took in, less what it gave.

**The rover** has a glass panel on its deck, 0.4 m by 0.5 m, turning a fifth
of the sunlight on it into charge. Its program rests when the battery falls
below a share of full the room declares, and roams on at another. Resting, it
stops where it is, on its brakes, and says so: "its battery is low, so it
rests while its panel charges it". Roaming draws more than the panel gives
(about 40 W against 30 W), so a small battery runs down and the rover rests.

Measured in the engine:

- Square to an overhead sun, a 0.8 m2 panel at 20% gave 160 W and put exactly
  1,600 J into its battery in 10 s; the other 6,400 J was heat.
- With the sun 60 degrees up it gave cos 30 degrees of that, 138.6 W. Under an
  awning it gave nothing and named the awning. A battery with room for 10 J took
  10 J and spilled 150 J.
- The rover with a 5 kJ battery at 28%, under a sun 50 degrees up: it roamed,
  stopped to rest at 1,250 J (a quarter), and the panel charged it to 3,000 J
  (three fifths) at 29.8 W from 148.8 W of sunlight. Then it roamed on. What the
  battery held was exactly what it began with, plus the 2,119 J it took in from
  its panel, less the 667 J it gave.
- A saved world keeps its sun, its panels and every joule of their accounts.

It can be watched in the page at `/world?scene=tests-solar`. That is a test room
off the menu, built by `tools/build_rover_room.py`, which lets the rover run
down, rest and roam on in the engine before it writes the room. Turned on, the
rover rests within a minute. The Machines list shows what the panel gives, for
example "solar panel on rover: 29 W from 147 W of sun on it", and what the
battery has taken in. `/world?scene=tests-rover` has the same sun and panel,
with a full 100 kJ battery.

A lesson on the way: the rover's caster wheel was oak. At the page's own step,
1/240 s, it held, but at 1/120 s the light wheel under the rover's weight sank
27 mm into the ground in three seconds, and the rover stuck. It is iron now, as
a real caster's is. The solver holds a heavy machine up on a light wheel only at
short steps. The heavier caster also turns the rover on the spot more slowly,
68 degrees in 3 s where the oak one turned 200.

Checked by `tests/solar_panel_tests.cpp`, `tests/rover_roam_tests.cpp`,
`tests/solar_room_tests.py` and the browser journey `ARoverRestsInTheSun`.

Not built yet: a battery charged at a post from a panel elsewhere; heat from a
panel's losses warming anything; a panel that turns to follow the sun.

## Light underground

**The owner's decision, 2026-09-28:** light in a mine is electric, on cables
running up to a solar farm. Not torches.

**Status, 2026-09-28.** A room can run cables from a store and hang lamps on
them, the lamps draw real power and the page is lit by them, and inside a
working the daylight is not there, so they are the only light you have.

**A run of cable** goes from a store to wherever the light is wanted. It is
pinned where it is put and does not move again. Its resistance is the
conductor's own: the resistivity times **twice** the length of the run --
out and back, because a circuit needs two conductors -- over the area of the
conductor. Copper is 1.68e-8 ohm m.

**A lamp** hangs on a run, or is wired straight to a store. It asks for its
watts and gives `efficacy_lm_w` lumens for each one it gets: an LED is about
120 lumens the watt, a filament lamp about 15. It is on a part, and goes where
the part goes, or it is pinned where it is put. It starts switched off.

**The cable is in series with its lamps**, which is the whole reason for it
being a thing with a resistance rather than a line drawn between two machines.
A lamp rated `watts` at the store's voltage is a resistance of
voltage squared over watts. The lamps on one run together are one resistance,
and the run's own is in front of them:

```
I = V / (R_lamps + R_run)      to the lamps  I^2 R_lamps      lost in the run  I^2 R_run
```

So a long thin run dims its lamps **even off a full battery**, and a second
lamp on that run dims the first: more current, and the run keeps more of the
voltage. A cable reports the volts that never reached the far end, which is the
number that says whether a run is thick enough.

A store that cannot give even that does not cut some lamps off and leave the
rest at full: its voltage sags, power goes as the square of voltage, and
everything on the run -- the lamps and the run's own loss alike -- falls by the
same share of what it wanted. A lamp says why it is not giving what it asked
for: "switched off", "the store is flat", "dim: the store cannot give all this
run asks for", or "dim: the run drops some of the voltage on the way".

**Underground is dark.** The page's three daylight lights are directional and
the hill does not stop them, so a tunnel drawn from the inside was lit as
brightly as the meadow above it and a lamp in it was decoration. The daylight
reaching the eye is now turned down by how much rock is over it, read from the
same runs the tunnel walls are drawn from: out by half a metre of rock, nearly
out by two, with a little sky left so an unlit mine is gloom rather than a black
screen and you can find your way back to the daylight. It is the **eye's**
cover, not each thing's, so the meadow seen through the adit mouth darkens with
you -- the price of doing it with the scene's own lights instead of per
fragment, and from inside a 1.75 m adit there is not much of the meadow to see.

The lamps themselves are a pool of eight point lights, handed to the eight lit
lamps nearest the eye. Three.js compiles the number of lights into every
material, so a light appearing or going out rebuilds every shader in the scene:
a lamp flickering as its battery ran down would have stuttered the whole room.
The pool never changes size. Lamps beyond the eighth keep their bead.

Measured in the engine:

- A 20 W lamp wired straight to a battery at 120 lm/W drew exactly 20 W, gave
  2,400 lumens, and the battery paid for every joule.
- 60 m of 1.5 mm2 copper is 1.344 ohm. One 20 W lamp on it draws 0.796 A, loses
  1.07 V on the way, and gets 18.26 W of the 20 it asked for -- 0.85 W stays in
  the cable. The same run in 6 mm2 is a quarter of the resistance and the lamp
  gets 19.54 W.
- Six 100 W lamps on 120 m of 1 mm2 (4.032 ohm) lose 19.4 of the 24 volts in the
  run: each lamp gets 3.7 W and 93 W is wasted in the cable. One of those lamps
  alone on the same run gets 34.6 W -- nine times as much.
- A 2 J battery ran a 20 W lamp for 0.1 s and went out, saying so and saying
  what it could not give. A 1 m2 panel at 20% in an overhead 1000 W/m2 sun lit
  the same lamp again and the battery gained on it, which is what the wire going
  up to the farm is for.
- A saved world keeps its cables and its lamps, their accounts, and which are
  switched on, and lights the same on the next step.

Checked by `tests/solar_panel_tests.cpp` ("a lamp draws its watts and gives its
lumens", "a long thin run loses more of it", "a flat store puts the lights out",
"lamps on one run share it", "a saved world keeps its cables and lamps").

Not built yet: a switch you can reach in the world rather than an operation; a
lamp as a thing the Workshop builds and the Explorer carries; a cable that a
person strings point by point, rather than one the room declares; heat from a
lamp warming the air around it; a cable that can be cut or a lamp that can be
broken.

## Breaking rock with a machine

**The owner, 2026-09-28:** "prove that we can take the same parts from the
workshop, put them into our inventory, go into the world and dig a tunnel and
install the lights to a solar panel."

A pick swung by hand puts twenty-odd joules into rock a blow, and a cell of
fresh rock costs 469 kJ (docs/earth-and-mining-plan.md, rock-work-v1), so a
heading driven by arm alone is twenty thousand blows. A **powered breaker** is
what makes a tunnel a thing a person can drive: a chisel on a part, wired to a
store, that spends its store into whatever rock its point is against.

- It works the rock its point is IN, or the first rock within `reach_m` ahead of
  its point along the chisel. A collider will not let a tool inside a face, so a
  breaker held against a wall has its point a hair outside it.
- Nothing aims: where the point is and which way it looks is where the hand put
  it. Held in the air it breaks nothing, and says "its point is not against
  rock".
- What it spends is its store's own joules, and the rock comes out by the same
  law and the same rule a pick goes through: a cell only comes free if whoever
  is working can carry it.

Measured in the engine: a 1.5 kW breaker took **314 s of the world** to break
one 0.25 m cell out of fresh rock -- 15.7 L, 471 kJ of its 1.5 MJ battery -- and
the 37.5 kg of rock went into the hands of whoever broke it. One charge is three
cells.

**The loop, end to end.** Three things the Workshop makes from its own
templates:

- a `mine-lamp`: a glass globe on an iron bracket, on a foot you stand on the
  floor. It comes out UNWIRED -- it names no store and no cable -- because a
  lamp is a fitting, and it lights when somebody runs a cable to it.
- a `breaker`: a handle with a battery on it and a chisel down the front.
- a `solar-array`: the farm, which was already there.

A lamp's light is on the lamp's own body, so it goes where the body goes. Stowed
in a bag the body is parked and the lamp says it is not in the world; put down in
a heading, it is in the heading. In the page, **P** starts a run of cable at a
battery, pays it out as you walk, and makes it off at a fitting; **M** holds a
breaker's trigger.

Checked by `tests/mine_loop_tests.py` -- the Workshop's own templates, into the
bag and out again, a heading driven, and a run of cable from the array -- and
photographed by `tests/lamp_shots.py` on `/world?scene=tests-light`, which
drives the page's own wiring action: standing in the heading with an unwired lamp
in it the picture is 0.047 of full brightness, and 8.2 m of 4 mm2 later the lamp
draws 20.0 W, gives 2,397 lumens, and the picture is 0.197 -- four times.

Not built: a drum of cable as a thing you carry, with a length in it that runs
out; a breaker that wears; cutting a run, or taking a fitting down off one.

## A day for the sun

**The owner's choice, 2026-09-22:** the step after solar panels is a day for
the sun. It crosses the sky and sets, panels make nothing at night, and a
machine has to have saved enough, or rest until morning.

**Status, 2026-09-22.** A room's sun can have a day. In the `tests-day` room
the rover roams on into the evening on what its battery holds, rests when the
battery is low, and waits in the dark for the morning sun to charge it.

**The day** is the room's to declare: how long it lasts in the world's own
seconds, how high the sun stands at noon, the hour the room begins at, and how
strongly the sun shines when it is overhead. The sun goes round as it does at
an equinox. It rises due east (+x), stands due south (+z) at noon and sets due
west, 12 hours after it rose; at midnight it is as far below the horizon as it
was above it at noon. The room's noon height stands in for its latitude. The
hour comes from the world's clock, so the sun stops when the world is paused.

- Low in the sky the sun's beam comes through more air, and less of it reaches
  the ground. The share that does is the Meinel air-mass model, a standard
  clear-sky estimate: 0.7 to the power of the air mass to the 0.678, where the
  air mass is 1 overhead and 1 over the sine of the sun's height lower down.
  With 1000 W/m2 overhead, the sun 60 degrees up gives 964 W/m2, and 3.2
  degrees up, 117 W/m2.
- Below the horizon it shines on nothing, and a panel says it is night.
- A world opened again from its save keeps the hour it had got to, and so does
  a world carried into a room the chat has changed. A room that now declares a
  different day starts it at the room's hour.

**The page** lights the room from where the sun is. The sun's lamp is as bright
as the share of the sunlight that reaches the ground, and reddens towards the
horizon. The sky's own light fades through twilight to a dim night light by the
time the sun is 6 degrees below the horizon. Behind the room the sky is blue by
day, red near the horizon and black at night; a room whose sun has no day keeps
the black it always had. The Room tab's clock says the hour and how high the sun
is: "16:08, the sun 24° up", or "20:44, night". This is presentation only: what
a panel collects is the engine's, from the engine's sun.

**The rover** needs no new program for the night. At night its panel gives
nothing, so once its battery is low it rests until morning. It says why, and in
a night the reasons come in this order:

- "its battery is low and the sun is down, so it rests until morning";
- at dawn, its deck tipped on the slope away from the sun on the horizon, "its
  battery is low and its panel is turned away from the sun, so it rests until
  the sun comes round to it";
- while the low sun is behind the basin's rim, "its battery is low and its
  panel is in the shade of the ground, so it rests until the sun reaches it";
- and then "its battery is low, so it rests while its panel charges it".

Measured in the engine:

- Over a whole day of 240 s, a 0.8 m2 panel lying flat at 20% collected
  9,252.79 J. The model's sunlight on it summed in two million steps over the
  same day gives the same, to a ten-thousandth.
- From five in the evening, the panel collected 67.8 J by sunset and nothing
  in the hour after it.
- The rover in `tests-day`, a 240 s day from four in the afternoon, with 3,500 J
  of 5,000, as `tools/build_rover_room.py` watched it before writing the room:
  the sun set at 18:00, 20 s in, with 2,755 J left. The rover roamed on in the
  dark and rested at 20:34, 46 s in, at a quarter. Its battery took in nothing
  until the sun rose at 06:00, 140 s in. It woke at 11:00, 190 s in, at two
  fifths, having taken in 869 J in all, and roamed on, dry.
- In the engine test of the same night, the rover moved 1.9 mm while it rested.

It can be watched in the page at `/world?scene=tests-day`, a test room off the
menu. Turned on from its panel, the rover roams into the sunset; the night
lasts two minutes, and the rover rests within a minute of dark.

Checked by `tests/sun_day_tests.cpp`, `tests/rover_roam_tests.cpp`,
`tests/day_room_tests.py` and the browser journey `ARoverRestsThroughTheNight`.

Not built yet: seasons, since every day is an equinox's; the moon; clouds; the
day's heat warming anything; a machine that plans for the night rather than
running until it is low.

## The Workshop's robot parts

**Status, 2026-09-25.** A robot can be assembled on the bench from prebuilt
components, its machines declared there in full, and installed into the
room as the exact bodies on pins the room's own rover is made of, where its
program, its senses, its routine and the chat all work on it as on the
hand-written one. The owner's aim: the bench chat assembles it, the person
brings it into the world and talks to it.

**The components** are families in the Workshop's library
(`mcp/workshop.py`, `MACHINE_FAMILIES`), so the bench chat can search,
place and fasten them: `mount` (a bearing mount hung under a deck),
`drive-wheel` (a wheel on its own short iron stub, which turns in a mount; a
motor goes on the mount and the stub), `caster` (a swivel pin up into a
mount, a fork, and a trailing wheel: six parts), `battery` (a box that holds
a store), `solar-panel` (a glass collector facing up), `hopper` (a bin a dig
routine fills). Every one is the room's rover's own, as
`tools/build_rover_room.py` hand-writes it.

**The rover template** (`mcp/workshop_products.py`, kind `rover`) composes
them -- 17 parts -- and, being a machine, says everything about itself that
a template of furniture leaves to the bench: every joint is authored (13
fixed, 4 bearings: the two wheel stubs in their mounts, the swivel in the
caster mount, the caster wheel on its pin), its machines are declared
(battery, two motors, two controls named left and right wheel, a panel, a
roam program with two water eyes half a metre ahead of the deck and a dig
routine with a 40 kg hopper), and every part asks for the exact model. An
assembly may carry such overrides now (`Assembly.overrides`), and the bench
opens the template with them.

**What a design can now declare** (`mcp/workshop_machines.py`): a program's
`sensors` (a water eye at a point on a component, in the design's own
metres, and its depth) and its `routine` (kind, hopper, what a scoop costs;
the places it works between are the room's, given at install); a panel's
`at_m` and `normal`, or the installer takes its component's top. The bench
chat has `add_sensor` and `set_routine` beside `add_power_part` and
`set_program`, and Check Validity says when a sensor sits on nothing or a
dig routine has no hopper. A program's chassis is the body both wheels' pins
turn on, not the alphabetically first. The design side allows only the
program kinds the room has ("roam"), so nothing is refused at the door.

**Installing it** (`playground/workshop_install.py`, `_preview_exact`): a
design that asks for the exact model and has bearings or machines is
compiled by `rigid_assembly` -- its fixed groups as compounds of their own
parts, its bearings as pins -- set down facing +z at the point asked, lifted
so nothing starts below the ground, and written into the room as
`precise_rigid_bodies`, `joints`, actions, interaction points and a
`machines` block in the room's own words: sensor and panel points carried
from the design's frame to where it stands. A routine's places, when the
install names none, are its dig site three metres ahead and its depot three
metres behind, said in the receipt. A machine's names are kept apart from
the room's -- a second rover's battery is "rover battery 2", its program
"rover 2", and whatever names them follows -- since the room refuses two
stores of one name and a design does not know the room. The staged world is
checked as every install is: the old bodies exact, the new pins the
design's, a machine counter allowed to begin counting, and a hinge's
measured angle allowed a microradian (a pin between exact bodies that were
moving when the world was saved reads a few hundred float ULPs off, and
that refused every install into a room with a rover in it). Powering
happens when the room is next opened, as for every installed machine.

Seen on the page: the rover opened on the bench by its kind, checked by
the bench chat (gpt-5-mini: "powered by a single energy store with two
motors ... a roam program"), made with "Make it" into the rover room beside
the room's own rover, and talked to there: "I am backing off: water ahead:
its reflexes have it. My battery is at 100%." -- and "turn around and hold
still" turned it round.

Measured in `tests/workshop_rover_tests.py`, in the real engine: the rover
from the bench, installed in the empty basin by the lake, compiled to five
bodies on four pins, was powered as the room opened, roamed 14.1 m in 20 s
turning away once, with 0 mm of water under any wheel; its routine knew its
two places; opened to talk, it turned to the person and took "stop".

Not built yet: the bench's Check Validity redraws are the lattice bench's
and say nothing useful about an exact-body machine (the rover is checked by
compiling, not redrawing); a way to set a routine's places from the page; a
motor's own bench trial (`cart_roll` pushes a cart, it does not drive one);
and any component beyond the rover's.

## A machine's senses and its tools

**Status, 2026-09-25.** A machine knows the world only through its senses,
and whatever thinks for it works it only through its tools. The two are
registries in the playground, `machine_senses.SENSES` and
`machine_tools.TOOLS`, and everything above the engine's reflexes reads the
one and calls the other: the routine a machine follows on its own, Jev or
the chat's model picking what to do when something happens, a person
talking to it. Nothing in that layer is a rover's; a new sense or tool is
one entry, and a new kind of machine is what the engine reports of it plus
a routine.

**The senses**, each one named reading, with directions in degrees from the
machine's front (positive to its left) and distances in metres, so every
reader means the same thing by "turn left 40": `position` (where it is,
its heading, its speed, what its program is doing and why); `slope` (its
own tilt, and which way is downhill and uphill round it and how steep, from
the ground surveyed on rings at 1.5, 3 and 6 m); `ground` (the surface
under it and its layers); `water` (its sensors, the nearest water round it
and which bearings are dry); `sun` (where it stands, its bearing from the
machine's front, whether it is day, the hour); `battery` (share of full,
joules, what charges it); `wheels`; `load` (its hopper); `places` (how far
and which way each place it knows lies); `nearby` (things within eight
metres); `person`; `struck`. The engine reports the program's position and
heading now (`at_m`, `heading_deg`), so no reader does quaternion
arithmetic. Senses that survey the ground or ask for the sun are read on
demand, when something happens or a person asks, never every step.

**The tools**, each one named action with a description a model can read,
a schema for its arguments, and what to fill them with when whoever picks it
gives none: `go_forward`, `back_off`,
`turn_left`, `turn_right`, `hold_still`, `face` and `go_to` (a place it
knows by name, the person, a point, or a bearing and distance), `dig`,
`dump`, `survey` (what is known of a place, and how much of it nobody has
seen: "What has been seen"), and `carry_on` (nothing more is asked: its
routine and its reflexes have it back). The going tools are asks on the
program (`behave`); a tool answers what it did, in words, and never invents an outcome -- what the
machine then does is the world's answer, read back through the senses. A
decider is asked which tool, among these names with these descriptions as
the criteria, and the same call asks whether it is stuck and how urgent its
battery is.

**A decider fills the arguments too.** Each argument a decider can fill is
a typed question of its own in the same call, keyed `arg_<name>`: a
duration, a distance or a depth is a score over its declared levels ("a
moment, a second and a half" ... "a good while, twelve seconds"); a
direction is a choice of seven bearings from its front; a place is a choice
among the places the machine knows and the person. Everything is asked at
once and only the picked tool's answers are read -- one call however the
decision branches, which is how Jev is meant to be used and costs the model
nothing extra. Jev and the chat's model fill them the same way, since both
answer choice and score questions. An argument a decider cannot fill this
way -- a point in the world -- the routine and a person can. The decision's
words say what was filled: "go to 3 m at +90 deg, for 6 s".

**Digging.** The engine's `dig` needs no hand or tool: it is a terrain edit
whose volume goes into the ground's one carried account. The `dig` tool takes
one scoop 0.5 m wide and 0.15 m deep, at the place it was sent to work or, told
no place, 1.3 m ahead of the machine's centre (closer, its caster swung into the
hole when it turned to leave); how it chooses the spot is "Working a place
without digging yourself in" below. It moves what came out from the carried
account into the machine's
hopper with the engine's `ground_withdraw`, so the ground's ledger stays
whole and the person's carrying is untouched, cuts the scoop to what the
hopper has room for and puts the rest back where it came from, draws the
scoop's work from the machine's battery (the new `draw` op:
`LiveWorld::drawEnergy`, joules off its charge and onto its `given_j`, so
its account closes), and holds the machine still for as long as the scoop
takes. The work is DECLARED, not derived: `work_j_per_kg` on the routine, 50
J/kg by default (lifting a kilogram half a metre is 5 J; breaking it out is
several times that, docs/ground-work.md measures the hand's tools); so is
the time, a quarter second a kilogram. `dump` returns the hopper to the
carried account and heaps it on the ground ahead. The hopper is not saved
with the world: a restart empties it.

**A routine** is a list of steps, each one tool call with its arguments and
what ends it, run by one generic runner (`machine_routine.Routine`) that
knows nothing of digging: it issues the step's tool, waits until the world
says the step is done -- the machine arrived (its `approaching` ask ended
waiting), its hopper is full, its hopper is empty -- and goes on to the
next, round again at the end; a `go_to` that runs out of time is tried
again from where it stands, three times. The dig routine is five steps: go
to the dig site; dig until full; back off from the hole; go to the depot;
dump. It is declared on a
program in the room's spec and checked by the validator:

```
"routine": {"kind": "dig", "places": {"dig site": [2.0, -6.5], "depot": [-2.5, -9.5]},
            "hopper_kg": 40, "work_j_per_kg": 50}
```

The runner ticks before each step the page takes (`Brains.before`), on the
program's last reported state. While someone else has the machine -- a
decider on something that happened, a person talking to it, its own
program resting for want of charge -- the routine waits and says who has
it, and takes its step up again after. **An ask never drives it into the
water**: asked to go somewhere and its sensors seeing water, its reflexes
have it -- backing off, turning away -- until it has been going forward
clear for two seconds, and then the ask has it back (the program's
`interrupted`); turned back three times, it gives the ask up and says the
water was in the way, so an ask pointed into the lake ends dry rather than
with the machine turning on the spot at the shore. Measured in
`tools/build_rover_room.py` for `/world?scene=tests-dig`: the rover went to
its dig site, took 40 kg in one scoop drawing 2,000 J, carried it to the
depot, dumped it and went back for more, in 122 s of the world at 24x
realtime, dry, with the ground's carried account at 0.00 kg after the dump
and its battery's account closed.

**On the panel** a machine with a routine says which step it is on, what
its hopper holds, how many loads it has delivered, and who has it when it
waits. Talking to it, "dig" and "dump" are tools too.

Checked by `tests/rover_roam_tests.cpp` and `tests/rover_brain_tests.py`
(the senses and tools on a stand-in engine, the routine's steps and waits,
the validator, and the tests-dig room in the real engine).

Not built yet: a hopper saved with the world; a scoop that is a tool point
on the machine driven into the ground by its motors, so the work is
measured rather than declared (a tool point needs a lattice body, and the
rover is exact bodies); a decider filling a point in the world (it fills
places, bearings, distances, durations and depths); and resources beyond
the ground's sand and soil.

## What the rover decides by itself, and who it asks

**Status, 2026-09-25.** The rover's reflexes still drive it: the engine's
program reads its sensors and its slope before every step and works its
wheels, and that never waits on anything. Above them, when something happens
to it, a decision model is asked what it should do for the next couple of
seconds, and its pick is done. The person can also click the rover and talk
to it (below).

**A program can be asked.** `LiveWorld::behave` (the runner's `behave` op,
the session's the same) asks a program to do one thing for a while instead
of deciding for itself: `going forward`, `backing off`, `turning left`,
`turning right`, `waiting` (held on its brakes, still on), `facing` a point
in the world (turning on the spot until its front is towards it, then
waiting) or `approaching` one (facing, then going forward until it is within
a metre, then waiting); for so many seconds, or until asked otherwise; by a
sender and its count, stale as `run` is. It says why it was asked as its
`why`, and when the while is up it goes on as it would have. Turned off, or
run low, it drops the ask: those come first. A saved world gives it back
doing what it was asked, as far in.

The ask also carries `by_person`: true when a PERSON is ordering it -- the
chat, the panel, the keys at the bench -- and false for the machine's own
routine and for whatever decides for it. A person's order outranks the water
reflex ("A person's order wins"); nothing else does. Whoever makes the ask
sets it, because the engine only ever sees a sender's name.

Measured in `tests/rover_roam_tests.cpp`:
asked to back off it went 0.62 m back in its second second (a controller
told to reverse stops its wheel first); asked to face a point behind it, it
turned on the spot to it in 12 s and, driven forward from there, went to it
(cos 0.98).

**Who is asked.** Jev, TypeSafe AI's decision model: it is sent a state and
typed questions, and answers each with a typed value and a calibrated
probability, in a fraction of a second; it cannot write a word, invent a
number or call a tool, which is what makes it safe to put in the loop. One
call (`playground/rover_brain.py`), whenever something happens to the
rover -- water seen ahead, a wheel stalled, something striking it, the
ground too steep, its battery getting low -- asks three things at once:
what to do next, a choice among what its program can be asked (keep going,
back off, turn left, turn right, hold still); whether it is stuck; how
urgent its battery is. The state it reads is the program as the engine
reports it, its wheels' controllers, what struck it, and the last few
decisions: curated, not the whole step, since Jev reads 32k tokens and is
paid by the one. A pick it gives at least 55% confidence goes to the program
as a short ask (1.5 to 3 s) with Jev's words as its `why`; a less confident
one is left to the reflexes, and the panel says so. The same thing happening
again within 3 s is not asked about again.

**Off the step.** The question is asked on a thread; the answer is applied
before the next step the page takes (`Brains.before`, in the live act
route), so the page's frame rate never waits on the network. The server
hears every reply of the room for it (`app.reply_listeners`). Nothing is
asked while the person is talking to it.

**What a decider is asked is the machine's tools** (`machine_tools.TOOLS`,
above): a choice among their names with their descriptions as the
criteria, and the state it reads is the machine's senses. Nothing in the
layer knows what a rover is; `rover_brain.KINDS` holds only the words for
what each kind of program's machine is, for the question's preamble.

**Or the chat's model.** The same typed questions can be put to the room's
OpenAI model instead (`OpenAIDecider`): the Responses API with a strict JSON
schema built from the questions, so it can answer nothing but probabilities
over the options and levels, at its lightest reasoning (`minimal`), since a
pick among five things needs no long thought. Its answers are read into
Jev's shape -- the choice is the most probable option and the confidence is
that probability; a score is the probability-weighted level -- so the rest of
the layer does not know which decided. Measured 2026-09-25 on the rover
state with water seen on its left: gpt-5-mini picked turn right at 95% in
2.3 s, and sorted "come over here please" as come here in 1.7 s; gpt-5-nano
answered in 1.1 s but called a 70% battery low and the rover stuck, so
gpt-5-mini is the default (`OPENAI_DECIDER_MODEL` and
`OPENAI_DECIDER_EFFORT` in `.env` change it). Slower than Jev's tenth of a
second, and paid by the token; fine for events a few seconds apart.

**On the panel** a machine with a program says who decides for it -- its
reflexes, Jev, or the model -- and what was decided last, with the
decider's confidence. `BANJO_DECIDER` in `.env` (jev, openai or reflex)
says which decides when a room opens; without it, Jev when it has a key,
else the model, else the reflexes. A decider without its key cannot be
pressed, and its button says why.

**The key.** `TYPESAFE_API_KEY` in the local `.env` (the same files the
OpenAI key is read from) turns it on; `JEV_API_URL` there names another
host that speaks the same API in place of `https://api.typesafe.ai/v1/systemone`:
a reseller, a proxy, or `tests/scripted_jev_server.py`, which stands in for
Jev without a key and answers as a sensible Jev might. Every check runs on
that stand-in or on a Jev that is a function: nothing in the tests reaches
the network. The request and answer shapes follow TypeSafe's published API;
a live call with a working key has not been confirmed yet (the key to hand
was refused by the API with 401).

Checked by `tests/rover_roam_tests.cpp` (the ask) and
`tests/rover_brain_tests.py`: in the tests-rover room with a Jev that always
says back off, Jev was asked once at the water's edge ("water ahead on its
right") and its pick was done -- the program said "Jev said back off (90%
sure) when water ahead on its right" -- and the while up, its reflexes had it
back.

Not built yet: a routine beyond roaming (a rover that digs for something and
brings it back), which is engine work -- a scoop on the rover and the
machine driving it -- and then one more kind in the table; asking Jev when
a person comes near, rather than only when they click; and a browser
journey for the panel's switch and the chat.

## Talking to the rover

**Status, 2026-09-25.** Click the rover, open its panel, press "Talk to it".
It stops what it is doing and turns to face the person (an ask on its
program by the sender "talk": `facing` where they stand, until asked
otherwise), and the chat opens with what it was doing, in its own words: "I
am turning left: the person came to talk to it. My battery is at 80%; I rest
below 25%. My sensors see no water ahead. I have turned away from things 3
times." Every sentence it says of itself is drawn from its program as the
engine reports it, never invented (`rover_talk.describe`).

**What the person types** is sorted into what they mean by Jev -- one
choice among stop, go on, come here, turn round, back off, what are you
doing, why, or something else -- and each of those is done at once, to the
program: stop is `waiting` until asked otherwise; go on lifts the ask; come
here is `approaching` where they stand, for up to 30 s; turn round is
`turning left` for 5 s; back off is `backing off` for 2.5 s; what and why
are answered from its state, why with the last thing decided for it.
Everything the chat does to the machine is the person's order (`by_person`,
"A person's order wins"): told to come somewhere it comes, through water if
that is where they are standing, and its water reflex stands aside until the
order is lifted.

Anything else goes to the chat's model (`OPENAI_MODEL`, the same one the
room's chat uses), told to answer in one or two sentences in the rover's
voice from that state alone and to change nothing; without an OpenAI key
the rover says what it can take. Without a Jev key the sorting falls back to
plain words. "Let it go on" lifts the ask, and its reflexes -- and Jev --
have it back. Closing the panel does the same.

Measured in `tests/rover_brain_tests.py`, in the real engine: opened to
talk with the person 3 m behind it, the rover turned on the spot and waited
facing them, and nothing that happened to it meanwhile was put to Jev; told
"come here", it stopped 0.92 m from them 12 s on; told "stop", it held;
closed, it went on. A machine that is off says so and does nothing.

`POST /api/world/rover/talk {program, open | said | close, person}` and
`POST /api/world/rover/brain {program, mode}` (reflex, jev or openai) are
the two routes, on the room the page has open; the step reply carries
`brains` whenever one has changed. What a person says is sorted by
whichever decider is on, or by whichever has a key when the reflexes are.

## A rover that flies

**Status, 2026-09-25.** The same framework, on rotors instead of wheels. A
machine that flies needs three things the rover did not, and nothing else:
a part the air pushes on, a program that holds it up, and a Workshop
template that puts them together. Everything above the program -- its
senses, its tools, its routine, who decides for it and how a person talks
to it -- is the rover's, untouched: a flying machine is a program of kind
`hover` in the same tables the roam program sits in.

**A rotor is a declared propeller on a motor's pin.** A motor can carry a
`rotor` block: `thrust_n_per_rad2` and `drag_n_m_per_rad2`. Each step the
engine reads the pin's rate w and puts a thrust of k w^2 on the pin's first
body (the frame) along the pin at the pin's point, and a drag torque of k'
w^2 on the disc against its spin, with its reaction on the frame -- which is
how the machine yaws, and what its flight costs: the drag is the load the
motor works against, so the battery pays for the lift. (Jolt's own hinge
friction is applied only while the pin's motor is off, so drag as friction
loaded nothing and the machine flew for free; it is a torque now.) The
numbers are declared, as a motor's are: for the Workshop's drone, 17 kg of
machine needs 170 N, 43 N a rotor at 62 rad/s (k = 0.011), and the induced
power of 43 N on a 0.4 m disc is about 500 W (k' = 2.1e-3).

**The hover program** holds the machine's centre `hover_m` above the ground
under it and level, and takes the rover's asks -- going forward, backing
off, turning, facing a point, approaching one, waiting -- done by leaning
5 degrees and yawing, instead of by wheels. It reads its height and climb
off the ground below its centre, its pitch and roll off its body; a height
loop (a learnt share of the voltage for the weight, the error, the climb
held to 1 m/s), an attitude loop (a lean of so many degrees to go, held
level otherwise, and against its drift when it is holding a spot) and a yaw
rate are mixed onto the four rotors by where each stands on the chassis --
`rotors` names their controls in order round the machine from above -- and
which way each spins. Nothing tells the program the machine's mass: the
share of voltage that holds it is learnt from the height error. Low on
charge it lands where it is and rests; turned off in the air, its rotors
stop and it falls; a saved world gives it back flying.

**The Workshop's drone** is the rover's deck, battery, panel, hopper and
two water eyes on four arms with a rotor at the end of each -- a new
`rotor` family: an iron stub up through a mount with a disc on top -- and
four legs; 24 parts, 19 fixed joints and 4 bearings, all authored, and its
machines declared: one store, four motors each with a rotor block, four
controls, a panel, a hover program with the same dig routine. It compiles
to five exact bodies on four vertical pins and installs through the same
gate as the rover, taking its places three metres ahead and behind where
it is set down. The bench chat's `set_program` takes `hover`, `rotors` and
`hover_m`, and its `add_power_part` a motor's `rotor`.

Measured in the real engine (`tests/drone_hover_tests.cpp`): turned on, the
drone reached 1.5 m in 1.0 s and held between 1.507 and 1.513 m, tilting at
most 0.25 degrees, its rotors at 59 rad/s; asked to go forward for 4 s it
went 7.3 m the way it faced, its height between 1.496 and 1.5 m; asked to
face a point to its left it turned to within 7 degrees; asked to approach a
point 4 m off it stopped 0.98 m from it and hovered; ten seconds of flight
drew 28 kJ from the battery, 66% of it taken by the air, and the account
closed; turned off at 1.5 m it was on the ground five seconds on, and
opened again from a save it was flying. The Workshop's drone
(`tests/workshop_drone_tests.py`): installed in the basin and switched on,
it rose and held 1.8 m over its landed height; stepped as the page steps the
room, its routine flew it to its dig site, dug 20 kg, carried the load to
its depot in the air and dumped it, one load in under 40 s of the world; a person
opening its panel finds it 1.83 m up, holding 1.5 m, and can talk to it.

What the drone showed of the framework: the senses' `position` reads a
flying machine's height and climb, `wheels` reads its rotors in order; the
routine, the talk and the deciders needed no change. Two things it turned
up: the dig tool withdrew from the ground's account exactly what the scoop
reported, and the report is rounded, so a 0.0125 m3 share of an 80 kg
scoop was refused against 0.012499 m3 held, and the drone waited out its
whole approach ask before trying again -- it takes what the account holds
now; and the page's list of controls a program works did not include
rotors, so a rotor click opened the rotor, not the drone.

Not built: a landing pad or a place to land other than where it is; wind;
a rotor's own inertia (the disc spins up as fast as the motor can turn it);
a flying machine that carries a thing on a rope.

## Raw materials into finished goods

**Status, 2026-09-26.** Machines that make things out of what other machines
dig, in one language a person or a model writes, on the same framework the
rover and the drone run on. Open `/world?scene=tests-mine` and switch the
four machines on from the Room tab: the rover digs copper ore out of a vein,
the smelter makes copper of it, the drone flies the copper to the mill, the
mill draws it into wire, and the wire lands on the Workshop's goods rack,
where a machine built on the bench takes it.

**The room's account of goods** is one block, `goods`, kept with the room and
changed in place as machines work (`machine_goods`):

- *Deposits*: a patch of ground where a scoop brings up ore with the soil --
  its substance, where, how wide, its `grade` (the share of a scoop's mass
  that is ore) and how much is there in all. What is taken is booked; a vein
  runs out. The ore's share of a scoop's volume has left the ground for good,
  exported as a material packet is, so the ground's own ledger stays whole.
- *Stockpiles*: heaps of goods at a place, by substance and mass. A machine
  dumps onto one or takes off one from within two metres of its edge; a dump
  where there is none makes a heap. One marked `rack` is the Workshop's: what
  lands there goes onto the Workshop's goods rack (`workshop_library`).
- *Recipes*: what a machine that processes makes of what it is given, per
  kilogram in -- what it takes, what comes out (no more mass than went in;
  the rest is waste), the work it draws from its battery and the time it
  takes. Nothing here is copper's: a substance is a name, and the room's
  recipes are the only chemistry there is.

**A machine that goes nowhere** is a program of kind `still`: it stands on a
body, draws on a store of its own, has no wheels, and can only stand by,
wait as asked, rest when its battery is low, or be off (`LiveWorld::
decideStill`). What it makes is its routine, run by the playground over it.

**Rising and descending are tools too** (`machine_tools`): `rise` and
`descend`, with how long to do it for, so a routine, a decider or a person
talking can tell a flying machine to climb over something or come down,
not only a person at the keys. A machine on wheels is told it does not
fly, and does nothing.

**What a machine is spending.** Its panel in the world, and the Lab's
drive box, both say what its battery holds and what it is spending right
now: the joules it has of its capacity, the watts its motors are asking of
it this step (`LiveMotor::power_w`), the watts its panels are putting back,
and how long that leaves at this rate. A machine switched off asks for
nothing. A flying machine asked all the way down sets itself on the ground
and stops its rotors -- a landed machine is carried by the ground, not by
its rotors -- so its draw falls to nothing until it is asked up again.
Measured: the drone hovering asks 2.84 kW of its 2 MJ battery, about twelve
minutes; landed it asks nothing; asked up again it spends again.

**Three more tools**, for any machine (`machine_tools`): `take` (goods off
the stockpile it stands by, or the one at a place it knows, into its hopper,
one substance or whatever is there), `process` (one batch of its recipe: the
inputs off its intake stockpile, the work off its battery, the outputs onto
its output stockpile, and a wait for as long as the batch takes) and `dump`,
which now puts a load's goods onto the stockpile it stands by and its soil
on the ground. The senses gained `goods`: every deposit and stockpile, how
far and which way, what each holds, and the recipes. The deciders' argument
questions gained a substance to take. A person can say "take", "make" and
"dump" to any machine, and a still machine tells them it goes nowhere.

**The routine language.** A routine was a named kind whose steps were written
in code. It can now be written out: `kind: custom` with `steps`, each a tool,
its arguments (a `place` by name), an `until` (arrived, asked_done,
load_full, load_empty, done, or a number of seconds), `repeat` and
`retries`, checked against the tools the machines have and the places the
routine knows. Two more named kinds: `haul` (take at its source, carry to
its destination, put it there; when the source pile is empty it goes with
what it has) and `process` (its recipe, between its intake and output
stockpiles, `batch_kg` at a time). A step with nothing to do yet -- nothing
on the pile, nothing to work -- is asked again next time, quietly. The rover
in the mine runs a custom routine: go to the vein, dig until full, back off,
go to the smelter's intake, dump there. The bench chat's `set_routine` takes
all of it, and `set_program` takes `still` with its store.

**What machines are made of, beyond their matter.** A machine's power parts
take goods off the Workshop's goods rack when it is made, by a declared
table (`workshop_library.GOODS_PER`): a motor 0.05 kg of copper wire per
newton-metre of stall torque and at least half a kilogram, a store a
kilogram of copper per 100 kJ and at least half, a control a tenth of a
kilogram of wire, a panel half a kilogram per square metre. "What it needs"
lists them with the oak and the iron, and the install gate spends them in
the same transaction, all or none. A rover takes 2.3 kg of copper wire and a
kilogram of copper; without them the gate says so and keeps the design.

Measured in the real engine (`tools/build_mine_room.py`, which refuses to
write the room unless the chain closes): switched on together, the rover
reached the vein 4 s in and dug a 40 kg scoop with 12 kg of copper ore in
it; at 28 s it dumped the load on the smelter's intake, the soil on the
ground and the ore on the pile; the smelter worked its first 5 kg batch into
1.5 kg of copper at once, 10 kJ and 10 s; the drone, waiting at the output,
took the copper and flew it to the mill's intake by 40 s; the mill drew it
into 1.47 kg of copper wire, 750 J and 1.5 s, onto the rack stockpile, and
the same 1.47 kg went onto the Workshop's goods rack. Every battery's
account closed and the ground's carried account was back at 0.01 kg. The
vein had 388 kg left of 400. Checked by `tests/goods_tests.py`.

**On the bench**, a `bin` family and a `processor` template: a deck on legs with
an intake bin and an output bin, a battery and a panel, and a still program
with a process routine whose recipe is a parameter. Installed through the
gate, its bins become stockpiles of the room's where they stand, and the
recipe it brings is given to a room that lacks it.

A processor works the COLD half of the chain -- drawing wire, mixing
concrete. Smelting, firing and melting need a temperature, and a deck on
legs has no inside to make hot, so those belong to the electric furnace
below and the bench will not offer a processor that cannot work.

Not built: a hopper or a stockpile drawn on the
page; a routine that changes with what it senses (a step's `until` is one
condition, not a choice); a market or a price for goods.

## The electric furnace, and what a lining decides

**Status, 2026-09-26.** A smelter used to be a deck on legs that turned ore
into copper by arithmetic. It is now a furnace with a real inside: a steel
shell, a refractory lining, and the space the lining encloses -- a genuine
volume of air in the thermal network, which an element heats and the lining
leaks. A recipe with a temperature will not run until the engine says the
chamber is at it.

**What the lining decides.** Heat leaves the chamber at `U = k*A/t` -- the
lining's conductivity times the chamber's inner surface, divided by its
thickness -- and an element of `P` watts holds the chamber at `ambient +
P/U`. That one relation is the whole design space. On the default 0.4 x 0.4
x 0.3 m chamber with a 5 kW element, measured:

| lining | U | it tops out at | so it can |
| --- | --- | --- | --- |
| 20 mm | 12.0 W/K | 437 C | nothing |
| 40 mm | 6.0 W/K | 853 C | not even burn lime, at 900 C |
| 60 mm | 4.0 W/K | 1270 C | lime, aluminium, copper, ceramic |
| 80 mm | 3.0 W/K | 1687 C | everything, iron at 1538 C |
| 120 mm | 2.0 W/K | 2520 C | everything, with room to spare |

The bench works that out before anything is built and refuses the pair with
the reason -- "this furnace tops out at 853 C and smelt iron needs 1538 C:
thicken the lining, shrink the chamber, or fit a bigger element" -- rather
than letting somebody build one and watch it sit at 850 C. Chamber size
counts the same way, because losses go with surface: four times the volume
on the same element reaches nothing at all.

**A recipe's own temperature says which machine works it.** `needs_c` on the
recipe decides, so the generator stands furnaces for the hot steps and
processors for the cold ones, and a recipe that gained or lost its heat
would move between them on its own. Nothing keeps a list of which is which.

**A furnace is not its recipe.** The chamber is hot or it is not; what the
routine converts in it is the routine's business. A furnace whose chamber
reaches 1687 C will smelt iron at 1538 as readily as copper at 1085, which
is what makes one starting smelter enough to bootstrap a valley.

**The element only burns for work that exists.** It fires when there is
something on the intake to convert and the chamber is below temperature, and
the engine's own reading of the element decides whether to fire -- not a
clock on the playground's side. Two overlapping heat calls STACK: measured,
a second one issued during the first read 10 kW instead of 5 and took the
chamber to 3353 C instead of 1686, past the thermal model's own validity
range, which it reports and does not refuse.

**A gas region may stand among exact bodies.** Everything the Workshop builds
compiles to exact (precise rigid) bodies, and an exact body has no thermal
model, so heat on one is meaningless and the engine refuses it by name. A
gas region is not a body: one that pushes on nothing and contains nothing
names nothing the model lacks. That is why a chamber can be hot inside a
machine a person built, and why heating the machine itself still cannot be
done.

**What is not real, said plainly.** The chamber stores only its gas -- 43 J/K
for 48 litres of air. A real furnace's lining is 15-25 kg of refractory at
about 1000 J/kg/K, several hundred times that, so a real box of this size
takes hours to reach 1538 C and not the 35 seconds here. The steady state is
a real furnace's; the warm-up is a game's. The honest way to slow it down is
to give the lining thermal mass in the network, not to spoil the
conductance. The lining is insulating FIREBRICK -- alumina ceramic, the
thing this machine itself makes by `fire ceramic`, which closes the chain on
itself. Its conductivity is the porous form's, about 0.3 W/m/K, and NOT the
model's dense alumina at 30, which would need fifteen metres of wall to hold
1500 C. (It was cast refractory concrete until main's `fcc5a6b`, because an
exact body could not be ceramic and every Workshop machine compiles to exact
bodies.)

**Measured**, in the valley: the furnaces heat before they work and they do
it in temperature order, which is the physics and not a schedule -- lime
(900 C) at 14.5 s, aluminium (960) at 15.5, copper (1085) at 19.2, while
cold work runs at once. On the bench, smelting 7 kg of ore cost 144 kJ: 14 kJ
of conversion and 130 kJ of getting hot, in thirteen spells that did not
overlap. A furnace left alone is back at room temperature within a minute.
Checked by `tests/electric_furnace_tests.py`.

**Power is now the constraint, and that shaped the new game.** A furnace
draws 5 kW warming and loses 3.2 kW just holding copper heat, against 840 W
of solar for the whole valley. Eight machines stood at once emptied the farm
in two minutes and the valley never recovered. So a new game stands two --
the copper smelter and the wire mill -- and lays out the other six yards
with their ore heaped beside them, for machines you build when you can power
them. Over ten world minutes the rover keeps the smelter fed, seven batches
come out, copper on the rack goes 3.0 to 6.0 to 9.6 kg, and the farm never
empties.

Not built: a door that opens, a conveyor, or any charge inside the chamber
-- what reaches temperature is the chamber, and the goods in the heap are an
account in the ledger rather than matter in the thermal network. Fire, as
opposed to an element, is not built either: this is the electric furnace.

## A routine that responds, and standing requests

**Status, 2026-09-26.** Two things the framework lacked: a routine could not
answer what its senses read, and a person could ask a machine for nothing
that outlasted one sentence.

**Conditions** (`machine_conditions`) are named readings off the same senses
the deciders read, in words a person or a model writes: `hopper_full`,
`hopper_empty`, `hopper_has` (a substance, a mass), `battery_below` and
`battery_above` (a share), `pile_empty` and `pile_has` (the stockpile at a
place it knows, or by name, or within reach; a substance, a mass),
`water_ahead`, `person_near` (metres), `at_place`, `night`, `day`,
`stalled`, `getting_nowhere` (seconds), `stuck`, `struck`, `resting`,
`asked_by_someone`; and `not`, `all`, `any`
over them. A condition that needs what the machine lacks is false, never a
fault. A new one is one entry in CONDITIONS.

**A step may carry one**: `when` (the step is skipped unless it holds) or
`unless` (skipped while it holds), read as the step is about to be issued.
**A routine may watch**: `watch` is a list of `{when, do, then}`; the moment
a condition comes to hold -- on its rising edge, once, and never while its
own steps are running -- its steps interrupt whatever the routine was
doing, and when they are done the routine resumes the interrupted step
(`then: resume`) or starts its round over (`then: restart`). The runner
(`machine_routine`) keeps its work as frames: its own round at the bottom,
and above it whatever interrupted it, run first.

**Standing requests.** A person's words can be a job now: "bring copper
from the source to the destination", "dig at the vein and dump it at the
smelter intake", "go to the depot and wait", "make three batches". The
chat's model writes it as steps of the routine language over the places,
substances and recipes the machine knows (a strict schema, `ORDER_SCHEMA`),
or says why it cannot; without a key, plain words cover those shapes. The
steps are checked as a routine's are, queued on the machine as an order --
run before its own round, a second order behind the first -- and answered
("Will do: go to source; take source, copper; go to destination; dump
destination. Then back to my rounds."). "What are you doing" says what
orders it has; "never mind" drops them; and when an order runs to its end
the machine says so in the chat, whether or not the person is still there
("Done: go to the smelter intake. Back to my rounds."). A still machine
takes only batches and waiting. The bench chat's `set_routine` takes
`when`, `unless` and `watch`.

Measured in the real engine (`tests/routine_language_tests.py`): the mine's
rover, told "go to the smelter intake" while digging, left its round, got
there within 2 m, said "Done" in the chat and went back to digging; a watch
put on it -- a person within 3 m, hold still for 4 s -- held it the moment
the person walked up; the drone told "bring copper from the source to the
destination" answered with the four steps it would take, said it had one
order when asked, and dropped it at "never mind"; the smelter told to go
somewhere said it goes nowhere. The runner's own tests cover `when` and
`unless` skipping as a step is issued, a watch firing once per rising edge
and resuming or restarting, and orders queued, run first, cancelled and
reported once.

Not built: a condition on a whole routine ("only by day"); a decider asked
what to do when an order cannot be done; a person's order carried across a
restart (orders live with the brain, not the room).

## Devices that pair

The owner, 2026-09-26:

> "devices that are paired should be defined that way when built. for instance
> the smelter should have a port where new ore goes in and a port where
> finished goods exit. the rover has a port for where it stores the ore and
> those two ports match up so it can release its ore to the smelter. it should
> be clear where the port is on a device with some indicator."

**Status, 2026-09-26.** A machine declares its ports when it is built. The
mine's rover drives to the smelter's intake port -- the mouth on the smelter,
not a patch of ground beside it -- and releases its ore through its own store
port, and the page draws a ring on each mouth that goes green the moment the
two are paired.

**What was wrong.** A transfer was to a PLACE. A machine within two metres of a
heap on the ground could dump onto it or take off it, and that was all: nothing
on a machine said "ore goes in here", nothing said a rover's store and a
smelter's intake belonged together, and nothing was drawn, so a person watching
could not see why a transfer did or did not happen. The rover's job named the
heap, so the ore and the spoil went to the same spot because that was the only
thing a dump could aim at.

**A port is a mouth on a device** (`playground/machine_ports.py`), declared on
its program in the room's spec, on one of its parts, so it moves with it:

```json
"ports": [{"name": "smelter intake", "flow": "in", "body": "smelter",
           "at_mm": [-3000, 1100, -9180], "normal": [0, 0, 1],
           "holds": "smelter intake", "goods": ["copper ore"]}]
```

- `flow` is `"in"` (it takes goods) or `"out"` (it gives them). A mouth is one
  way; a device with a two-way mouth declares two ports at the same point.
- `fitting` is the coupling, the way a hose fits one tap and not another. Two
  ports pair only when theirs match. `"goods"` is the only one so far, and it
  is what a port that says none is given. Power and heat are their own systems
  and go nowhere near here.
- `body`, `at_mm` and `normal` are where the mouth is and which way it looks,
  in the room's own millimetres as the room is made, exactly as a solar panel's
  are. Where that lies on the body is worked out the first time the body is
  seen, and after that the mouth rides the body: the rover's store turns with
  the rover, an anchored smelter's does not move at all.
- `holds` says what is BEHIND the mouth: `"hopper"`, the machine's own load, or
  the name of one of the room's stockpiles.
- `goods` are the substances it will take or give; none means anything.

**A port does not replace a stockpile. It docks to what one holds.** This was
the design choice, and the reason is that the two are different things. A heap
on the ground is a place in the world a person can walk up to and see, that a
dump can make where there was none, that the Workshop's rack can be, and that a
still machine's recipe works between. A port is geometry and a contract: where
the mouth is, which way it faces, what it will accept. Making a port hold goods
itself would have meant a second ledger, a smelter whose ore is nowhere in the
world, and rewriting every room that dumps and takes by place. So a port
decides WHETHER and WHERE, and a hopper or a heap is WHAT HOLDS. The smelter's
intake port passes ore onto the same "smelter intake" heap its own recipe eats
from, and nothing about the recipe changed.

**Two ports pair** when one gives and the other takes, their fittings match,
they are no further apart than a dock, their two faces are opposed within the
allowance, and neither is behind the other. They must belong to different
machines: a device does not feed itself.

- **1.2 m, the dock.** A declared game constant, not a clearance off a real
  coupling. It is set by what a machine can do: one told to go to a point stops
  about a metre short of it (the `approaching` ask stops within a metre, and
  0.92 m, 0.98 m and 0.62 m are measured above in real rooms), so mouths that
  had to touch could never be brought together by a machine that drives to
  them. A person can still carry two things closer by hand, and then they dock.
- **60 degrees, the facing.** How far from exactly mouth to mouth the two faces
  may be turned. A game constant too, and deliberately loose: a machine that
  drives at a thing stops about 3.4 degrees off square and lets itself drift 8
  degrees on the way (both measured above), so past ten degrees is already
  slack -- but a mouth need not be on the machine's nose and the ground is not
  level, and a dock a machine can see and reach and still not make is the one
  thing a person watching cannot forgive. 90 degrees would have the mouths at
  right angles, where nothing could pass.
- **Neither behind the other.** A half turn each way: the other mouth has to be
  somewhere in front of this one's face. That is what refuses a machine that
  has driven past.

**The first rule was wrong, and the page showed it.** It asked instead that
each face look ALONG the line joining the two mouths, within the same 60
degrees, with the number derived from how far to one side a machine may stop.
In the mine the rover came alongside the smelter with its mouth 0.53 m from the
intake and was refused at 69 degrees. The derivation had used the full 1.2 m
dock; a dock actually happens at half a metre, and over half a metre a third of
a metre of lateral offset -- which a machine that stops within a metre of a
point has every right to -- swings that line by 30 degrees, and both mouths
swing. The line between two mouths is a worse measure of anything the closer
they get. Which way they look is not, so that is what the rule asks now.

**The transfer** is a tool, `dock`: goods from one of the machine's ports into
the port it is paired with -- its store into the other's intake, or the other's
outlet into its store -- whichever of its own mouths fits. What moves is what
the giver holds that the giver gives and the taker takes, as much as the taker
has room for. Nothing here is a place: a routine step is `{"do": "dock"}` and a
`go_to` can name a `port` instead of a place, so a machine is sent to a thing.
A person can say it too ("go to the smelter intake"), and an order that would
have dumped onto a port docks at it instead.

`dock` never answers "idle", unlike `take` and `process`. An idle answer is one
the runner asks again next tick without counting it, and a step that is only
ever idle can never end -- a machine that stopped a little too far off would
stand at the dock for ever. It answers plainly either way and a routine bounds
the step in seconds. Fixing that turned up a bug in the runner itself: a
repeating step reset its clock on every issue, so its seconds were never up. A
step bounded in seconds is now counted from when it was first issued.

**The indicator** (`playground/world.js`, `dressPorts`): a ring at each mouth,
lying in the plane of its face, with a cone through it pointing the way the
goods go -- out along the face for a port that gives, back into the device for
one that takes. So which end of a smelter is its intake is there on the
smelter. The ring is steel while nothing is alongside, amber while another
mouth is near but the two are not paired, and green while they are docked. The
playground works out which and sends it with every step, so the page and the
machine never disagree: what is drawn green is exactly what `dock` would move
goods through. The `ports` sense says the same in words, with the reason a
near mouth is not paired ("they are 0.39 m apart but turned 72 deg off each
other, and a dock allows 60").

**The mine's rover** now has a store port at the front lip of its deck, and the
smelter and the mill each have an intake on the face the ore comes from and an
outlet on the face their heap is on. Its routine goes to the smelter's intake
PORT, docks, and then carries the spoil -- what is left in the hopper once the
ore has gone, which the smelter has no use for -- to a spoil heap on the way
back. The ore goes to a thing and the dirt goes to a place.

Measured in the real engine (`tools/build_mine_room.py`, which refuses to write
the room unless the chain closes, and `tests/ports_tests.py`):

- the rover dug 40 kg with 12 kg of copper ore in it, reached the smelter's
  intake port and passed all 12 kg through it in 3.0 s at 29 s of the world;
  the smelter worked its first 5 kg batch at once, and copper wire reached the
  Workshop's rack at 41 s. Every battery's account closed and the ground's
  carried account was back at 0.01 kg;
- the rover's mouth moved 2.98 m with the rover in 15 s of driving, while the
  smelter's stayed within 50 mm of where the room put it;
- in the page, with the four machines switched on and the room stepped as a
  person steps it, the rover's store and the smelter's intake both went green
  the moment they paired, and both rings went back to amber with the reason
  written out as the rover pulled away ("they are 1.25 m apart, and a dock is
  1.2 m").

**What is NOT modelled.** There is no chute, no pipe, no hose and no valve in
the physics. Nothing is drawn between two paired mouths, no body travels along
one, and the goods are booked out of one holder and into the other in the same
call. A port carries goods only: no force, no heat, no charge, no readings. It
holds nothing itself. It does not open or shut, it cannot be blocked, jammed or
leak, and nothing about it wears out. Two mouths pair however much of the
machine stands between them: nothing checks that the way is clear. A dock costs
no energy -- the giving machine's battery pays nothing for it -- where a scoop
does; it takes time only, at the same declared quarter-second a kilogram a
scoop takes.

**Not built:** a port on a body with no program (every port belongs to a
machine); a port that carries anything but goods; the drone hauling through the
smelter's outlet port, which it cannot reach -- it hovers 1.8 m up and the
outlet is 0.4 m off the ground, four times the dock apart, so it still takes
off the heap; a dock that a person can make by hand; a port drawn on the
Workshop bench, so a machine built there declares none.

## What everything holds, in slots

The owner, 2026-09-26: "also have slots for anything that can hold things and
show the material being held it is so we can see it happen more as it goes."

A room that mines has four kinds of thing that hold material, and three of them
could not be seen at all. The person's hands, bag and carried sand and soil
were in the Bag tab. A machine's hopper was six words at the end of its routine
line, "hopper 12 of 40 kg". A heap on the ground was a number in the room's
spec that **never reached the page**: nothing drew it and nothing said it, so
the ore a rover tipped into the smelter simply vanished as far as anybody
watching could tell. Ore still in the ground was the same.

**The room's account now travels with its steps.** `Goods.holders()` is every
heap with what it holds by substance, and every deposit with what the ledger
says is still down there. `Brains.settle` sends it with the room when it opens,
and `Brains.attach` sends it with a step **when it has changed** -- a heap sits
still, and the account moves only when something is dug, dumped, taken or made.
It is a separate report from the ports' own `holds_kg`, which says what is
behind one mouth: a heap with no mouth on it -- a spoil heap, a heap a person
made with a spade -- is a holder too.

**They are all drawn the same way**, because the only difference between them
is where they are: a name, and one small square per substance with that
substance's mass. A holder with a capacity -- a hopper, a deposit's reserve --
gets a bar as well, so how full it is reads without arithmetic. The Room tab
lists every holder in the room, in the room's own order, never sorted by how
much is in them: a row that jumps up the list as it fills is a row you cannot
watch. A machine's panel lists that machine's own -- its hopper, and the heap
behind each of its mouths with which way the goods go and whether it is docked.

**A slot that moved since the last step lights for about a second**, green for
more in it and amber for less. That is what makes a chain legible while it runs
rather than after it. A card drawn for the first time lights nothing, because
at a room's open nothing has moved; after that a substance appearing where
there was none is a move like any other and lights green, and one leaving stays
at nothing while its light is on, so the last kilogram going is seen.

**Measured in the page** (`tests/world_page_journey_tests.py`,
`TheMineShowsWhatEachThingHolds`, on the real engine in headless Chrome). The
tests-mine room opened with all seven of its holders listed and all four heaps
saying "empty", the vein's bar full at 400 kg and the rover's hopper at 0 of
40 kg. Its four machines were switched on from the panel in the side view, one
at a time, through the Room tab's own Controls button. In 27 s of the room's
time: the vein went 400 kg to 388 kg, the rover's hopper held 12.0 kg of copper
ore and 28.0 kg of sand and soil, the smelter's intake heap took 7.0 kg of
ore, its output heap 1.5 kg of copper, the drone's hopper carried that 1.5 kg,
and 1.5 kg of copper wire reached the Workshop's rack. Every one of those slots
was seen lit as it moved.

**What is NOT modelled.** A slot is an account, not a picture of a pile.
Nothing is drawn on the ground where a heap is; a heap has no shape, no angle
of repose and no volume, two substances in one heap neither mix nor separate,
and a heap cannot be full. A deposit's mass is what the ledger says is left,
not a measurement of the ground. The goods ledger and the ground's own sand and
soil are two accounts, not one -- ore is the share of a scoop that leaves the
ground for good -- so what a person carries stays in the Bag tab and is not
mixed into this strip. The colours are tints picked from a substance's NAME so
that two slots can be told apart; nothing measures what colour copper ore is,
and a substance named after a material the room draws with borrows that
material's colour instead. The Workshop's own two racks are unchanged: they are
a database table shown in the Workshop's Inventory tab, and the world page sees
the rack as the room's `rack` stockpile filling.

## After the hoist

These follow the owner's analysis. Each is a milestone of its own, and each is
seen working in the page.

2. **One autonomous creature.** Wheels before legs: a battery cart with two
   driven wheels, a bump sensor, and a controller that roams, finds a charging
   post and docks. Its first steps are built: a cart whose water sensor
   stops it at a lake's edge, a rover that roams a lake's shore by itself,
   solar panels that charge its battery while it rests in the sun, a day
   for the sun, so that it rests through the night, and a robot told to go to a
   stool that goes and sits on it (above). The owner chose
   solar panels over a charging post (D1).
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

- **D1. How a battery is charged at first.** *Decided by the owner,
  2026-09-22: by solar panels* ([Solar panels](#solar-panels)). The options
  that were put:
  - A charging post in the workshop that fills any battery set on it, labelled
    as unlimited for now.
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

## A machine you are riding, and a slow frame

The ask that holds a ridden machine lapses on purpose: a page that dies must
not leave a machine driving for ever. That means the page has to renew it,
and the lapse has to beat the slowest frame by a wide margin -- because a
`roam` program with no standing ask does what it is for, and roams, with you
aboard.

It was 0.6 s renewed every 0.3 s, which is comfortable at 60 fps and loses
at 1.4 fps. On a CI runner at that rate the rover drove 3.3 m with nobody at
the keys. It is not a CI artefact: anyone on a slow machine, in a big room or
over a slow link gets the same. `RIDE_FOR_S` is 3 s now, renewed at a third
of it, which survives two 700 ms frames and the round trip.

A long ask needs an explicit release to match. `letGoOfTheMachine` tells the
machine to wait before dropping out, so the last thing you asked for cannot
drive a machine nobody is in; both ways out -- Escape and the Fly button --
go through it. Getting out keeps the machine's NAME, because that is what
going back puts you into; `whatIsRidden` already answers null while you are
flying.

## Carrying a thing to the bench

A thing in the bag can be picked up with the mouse. It carries its item id
under `application/x-banjo-item` -- its own type, so a slot cannot be
confused by a file, a selection or a link the browser happens to be holding
-- and there are two places to drop it.

A slot in the row over the room puts it there, swapping with whatever was in
that slot, and the slot is kept for it afterwards: take it out with its own
number and put it back and it returns to where you put it.

The Workshop link opens it on the bench: its own design where the bench made
it, else a bench copy of its shape, which are the same two routes the
Inventory tab's tiles take. Dropped after it has been put down, the Workshop
opens on the Inventory and says the thing is not being carried any more.

While something is being carried every slot shows itself -- an empty one is
hidden the rest of the time, and there is no aiming at what is not drawn.
