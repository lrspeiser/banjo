# Puzzles on the machine (/play)

October 10, 2026. The machine page has a game: open `/play`. Each level is a small machine you cannot change, a goal, and a tray of pieces you add to make the goal happen. The engine runs the whole thing; nothing about the outcome is decided by the game.

## Playing a level

- **The goal** is a green box drawn in the scene ("the ball is in the cup") and a time limit. The engine checks it on every step: the goal happens when the named part's centre is inside the box.
- **The tray** lists the pieces you may add and what each costs. Press Add, and a see-through **ghost** of the piece appears: it is not in the machine yet.
- **The ghost follows the pointer** over the scene. Click, and it stays where you clicked. Then you can change it while it is still a ghost: cut it to length, set its height or its powder, all with its sliders. You can drag it with the mouse, click somewhere else to put it there, or nudge it with the arrow keys.
- **Turn it any way.** Every piece can be turned about the vertical (turn), tipped end up or down (tip), and rolled about its length (roll), by any angle: with the −15° and +15° buttons, with the sliders, or with keys (Q/E turn, R/F tip, Z/C roll; with Shift, one degree at a time). Shift and the mouse wheel turn it; Alt and the wheel tip it. Square it up puts it back level. Turning costs nothing. Everything the piece is made of turns with it: a cannon turned 20° fires 20° off to the side, and tipped up it fires upward. A piece tipped so far that part of it would go into the ground is lifted to stand on the ground.
- **Blue fits, red does not.** While you move, change and turn the ghost, the server works out where the piece would really be (a plank is lowered onto the highest thing under it) and whether it can go there. This takes a few milliseconds and runs nothing in the engine. A red ghost says why, for example "your mirror 1 goes 120 mm into wall; move it", and cannot be set down. Nothing of yours may go into anything solid, the level's or another of your pieces.
- **Set it down** (or press Enter) and the engine builds it. From then on a loose piece is held only by gravity and contact: a plank too short for the gap falls in, and one too long for the ledges rests on the tables' tops a step up. Cancel (or Esc) throws the ghost away. **Pick up** turns a piece you have set down back into a ghost; Cancel puts it back as it was. A ghost has to be set down or cancelled before you run the machine.
- **Run it** builds the machine afresh and plays it at real time.
- **Stars**, from what the engine measured: one for the goal in time, one for staying at or under the level's par cost, one for style (using enough different pieces, on levels that ask for it). If the chat placed the pieces, one star at most.
- **Is it reliable?** runs your machine three times with every loose part nudged by up to 1.5 mm, as fast as the engine goes, and says in how many the goal happened. Real chains of events are fragile; a machine that works 3 of 3 is a good one.

## The eight levels

| Level | What it teaches | The pieces | A solution, as tested |
|---|---|---|---|
| 1. Mind the gap | rolling | a plank | a plank cut to 0.7 m and set down at x = 0.3 drops into the ledges each table has at the gap, level with the tables: the ball reaches the cup at 1.9 s |
| 2. Cut it down | cutting | a knife pendulum | pivot at x = -0.08 m, 1.31 m up, a 0.6 m arm: the edge cuts the oak rope and the weight is in the bin at 0.7 s |
| 3. Knock it off | a powder charge | a cannon | muzzle at x = 1.4 m, bore 0.48 m up, 1 g of powder: the block is knocked into the zone at 1.4 s |
| 4. Up she goes | steam | a steam engine | over the marker with a 12 kW firebox: the piston reaches the zone at 3.4 s |
| 5. Chain reaction | a chain | a ramp with a ball | the ball tips the lever, which closes the switch; the coil lights the cannon's powder; the ball knocks the block into the zone at 1.5 s |
| 6. Bounce the beam | light: reflection, and light heating what it lands on | two mirrors | a 5 kW laser's beam bounced around a wall by two mirrors at 45 and -45 degrees burns through the cord; the weight is in the bin at about 5 s (within 12 s) |
| 7. Catch the sun | sunlight: a panel facing the sun catches the most | a solar panel | a sun 15 degrees up behind the shed; the panel at x = 1.0, z = 0.4, turned -45 degrees and tipped 75 to face the sun squarely, takes 250 W of sunlight and stores 50 W, and the solar winch lifts the weight to the mark at 2.4 s |
| 8. Lift with less | mechanical advantage: a block and tackle | a counterweight on a block and tackle | a 4.7 kg counterweight through 3 pulleys, hung 1.75 m up, lifts the 13.6 kg crate to the shelf mark at 3.65 s for a cost of 11.4 |

How forgiving they are, measured: in level 2 the knife works with its pivot anywhere from 16 cm behind the rope's line to level with it, across about 25 cm of height. In level 3, 1 g of powder works from several places; 0.5 g falls short and 2 g throws the block past the zone. In level 7 the winch needs about 185 W of sunlight on the panel: lying flat in the sun it gets 65 W and the weight never moves; tipped only 30 degrees, or tipped without being turned toward the sun, is not enough; tipped 45 degrees toward the sun it lifts the weight by 3.2 s; in the shed's shadow it gets nothing, however it faces. The ghost of a panel says how squarely it faces the sun and how much sunlight that gives, if nothing shades it. In level 8, measured: 21.6 kg on one pulley lifts the crate at 0.67 s but costs 45; 13.6 kg on one pulley, the crate's own weight, does not move it at all; 7.4 kg on two lifts it at 1.9 s for 16.8; 4.7 kg on three, hung 1.75 m up, lifts it at 3.65 s for 11.4, but hung at 1.4 m it reaches the ground first and the crate stops 6 cm short; 4 kg on four would have to fall from higher than the gantry allows.

## Asking for help

The chat box on a level does two things:

- **Ask for a hint** sends your question, your pieces and what the engine measured in your last run (where things went, how fast, what they hit) to the model, which answers with a hint. It is never shown the level's solution.
- **Place it for me** asks the model for up to three ways to place the tray's pieces. The engine rehearses each and uses the first that reaches the goal. A knob just outside its range is brought to the end of the range, as the slider would. If none works, the engine searches from the one that came nearest: sixteen random settings of the same pieces first (nearness can mislead -- a ball flying past a lever comes near its middle from a ramp in quite the wrong place), then one knob at a time, keeping each change that brings the goal nearer and going on in that direction while it helps, up to 48 runs. "Nearer" counts the steps of a chain not yet reached (a level's `milestones`: in level 5 the ball hitting the lever, the switch closing, the cannon firing) and how near the first of them came. Measured with gpt-5-mini: levels 1, 2 and 4 placed by the model itself; levels 3 and 5 finished by the engine's search (level 5 from a ramp over the lever in 4 to 29 runs, three seeds).

## Adding a level

Levels are in `client/voxel-lab/levels.json`. Each has:

- `machine`: the fixed machine, a `banjo.machine.v1` declaration;
- `goal`: a title and a station rule, usually `in_zone` with a part, the box's centre and its size;
- `tray`: the pieces, each with `count`, `cost` (and `cost_per` a knob), and its knobs' ranges;
- `budget`, `par`, `time_s`, `hints` (shown to the player and to the model);
- `solution`, which is never sent to the page or the model.

The pieces (`plank`, `knife`, `cannon`, `steam`, `ramp`) are in `scripts/machine_game.py`. `tests/machine_game_tests.py` checks that every level's solution reaches its goal in three nudged runs out of three, that no level is solved with no pieces, and that a misplaced piece fails for a physical reason.

Level 6 burns the cord in seconds, as a real laser would: light heats the spot it lands on and chars the oak there away ([light-spots.md](light-spots.md)). Its own solution puts the weight in the bin at about 5 s, 3 runs in 3 (it took 20.3 s when a body's heat was spread through all of it).

## The site

The deployed site is the game and nothing else, open to anyone with no login: `scripts/voxel-lab.py --site game --public` (the Dockerfile's command) serves `/play`, the sandbox `/machine` it is built on, and what those pages load; `/` goes to `/play`; every other page and API answers 404. With no password in front of it, what costs money or a lot of engine time is rationed instead: the chat (which spends the model's key) to 12 requests per visitor an hour and 400 a day, and the reliability check to 30 per visitor an hour and 2,000 a day (BANJO_CHAT_PER_HOUR, BANJO_CHAT_PER_DAY, BANJO_TRIALS_PER_HOUR, BANJO_TRIALS_PER_DAY). The server holds at most four live machines at once; a fifth visitor's machine closes the one used longest ago. `--public` is refused without `--site game`. The other labs stay in the code and run locally without these switches.

## Real time

A level plays at real time. When something breaks or dents, the engine solves the impact in its lattice of cells. Played live, that solve runs on the engine's worker while everything else carries on and the pair that met is held still, for at most 50 ms of world time. If the answer is not back by then, the machine waits for it, because a body held longer misses what it should have been doing. Rehearsals, tests and reliability runs always wait, so their answers are exactly the physics'. How long a solve takes is being worked on (see docs/machine-physics-roadmap.md).
