# Puzzles on the machine (/play)

October 10, 2026. The machine page has a game: open `/play`. Each level is a small machine you cannot change, a goal, and a tray of pieces you add to make the goal happen. The engine runs the whole thing; nothing about the outcome is decided by the game.

## Playing a level

- **The goal** is a green box drawn in the scene ("the ball is in the cup") and a time limit. The engine checks it on every step: the goal happens when the named part's centre is inside the box.
- **The tray** lists the pieces you may add and what each costs. Press Add, and the piece appears with sliders for its knobs: where it goes, how high, how long, how much powder. Moving a slider rebuilds the machine in the engine, so the scene always shows what will run.
- **Run it** builds the machine afresh and plays it at real time.
- **Stars**, from what the engine measured: one for the goal in time, one for staying at or under the level's par cost, one for style (using enough different pieces, on levels that ask for it). If the chat placed the pieces, one star at most.
- **Is it reliable?** runs your machine three times with every loose part nudged by up to 1.5 mm, as fast as the engine goes, and says in how many the goal happened. Real chains of events are fragile; a machine that works 3 of 3 is a good one.

## The six levels

| Level | What it teaches | The pieces | A solution, as tested |
|---|---|---|---|
| 1. Mind the gap | rolling | a plank | a plank from x = -0.04 to 0.64 m, top at 0.3 m: the ball reaches the cup at 1.8 s |
| 2. Cut it down | cutting | a knife pendulum | pivot at x = -0.08 m, 1.31 m up, a 0.6 m arm: the edge cuts the oak rope and the weight is in the bin at 0.7 s |
| 3. Knock it off | a powder charge | a cannon | muzzle at x = 1.4 m, bore 0.48 m up, 1 g of powder: the block is knocked into the zone at 1.4 s |
| 4. Up she goes | steam | a steam engine | over the marker with a 12 kW firebox: the piston reaches the zone at 3.4 s |
| 5. Chain reaction | a chain | a ramp with a ball | the ball tips the lever, which closes the switch; the coil lights the cannon's powder; the ball knocks the block into the zone at 1.5 s |
| 6. Bounce the beam | light: reflection, and light heating what it lands on | two mirrors | a 5 kW laser's beam bounced around a wall by two mirrors at 45 and -45 degrees burns through the cord; the weight is in the bin at 20.3 s |

How forgiving they are, measured: in level 2 the knife works with its pivot anywhere from 16 cm behind the rope's line to level with it, across about 25 cm of height. In level 3, 1 g of powder works from several places; 0.5 g falls short and 2 g throws the block past the zone.

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

Level 6 is slow for a real laser: the engine spreads a body's heat through the whole of it, so the beam has to warm the entire cord before it burns. A model of the lit spot heating faster than the rest of the body is being built; then the cord goes in seconds, as it would.

## The site

The deployed site is the game and nothing else: `scripts/voxel-lab.py --site game` (the Dockerfile's command) serves `/play`, the sandbox `/machine` it is built on, and what those pages load; `/` goes to `/play`; every other page and API answers 404. The other labs stay in the code and run locally without `--site game`.

## Real time

A level plays at real time. When something breaks or dents, the engine solves the impact in its lattice of cells. Played live, that solve runs on the engine's worker while everything else carries on and the pair that met is held still, for at most 50 ms of world time. If the answer is not back by then, the machine waits for it, because a body held longer misses what it should have been doing. Rehearsals, tests and reliability runs always wait, so their answers are exactly the physics'. How long a solve takes is being worked on (see docs/machine-physics-roadmap.md).
