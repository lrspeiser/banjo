# What works, and where you can reach it

The [README](../README.md) tells the story; this is the ledger behind it. Every
row says what has been built and how close it is to being something you can
walk up to in the world. Kept current with `main`: last checked
**27 September 2026**, at `dd79c66`, when the site became the world and the
bench in it and the other six pages were taken out.

The labels:

- **World** — you can try it in the main world at `/world`.
- **Test room** — in the live world, but in a room you reach only by typing its
  address, `/world?scene=<name>`.
- **Chat** — in the live world, but only if you ask the room's chat to build it.
- **Code only** — built and tested, but no page reaches it. You can run it from
  the C API, the MCP servers, a command-line tool or the tests.
- **Branch** — built on a branch that is not merged yet.
- **Not built** — designed, measured or planned only.

---

## Breaking, denting and cutting

| Capability | Status | How to try it |
|---|---|---|
| Objects break when hit hard enough; all eight materials | World | throw or drop things. The bench room, `/world?scene=bench` (20 mm cells), has plates of every material on piers |
| Pieces break again when they land hard | World | break something, then drop its pieces |
| Denting: iron, aluminium, oak and rubber take a permanent set | World, Test room | on in every room; in `/world?scene=tests-motion` an iron ball hits an aluminium plate at 30 m/s as the room opens |
| Breaking under a steady load (statics) | Test room | `/world?scene=courtyard`: load the thin concrete shelf. `/world?scene=armoury`: notch the loaded batten |
| A thing's bar for breaking depends on how big it is | World | automatic (`admitRefracture`); small chips stop shattering on every landing |
| Foresight and background fracture | World | automatic |
| Cells colliding with each other while something breaks | World | automatic |
| Heat weakening what breaks | World | heat a plank or beam, then load or hit it |
| Cutting with a blade | World, Test room | the sword in the world; `/world?scene=armoury` (10 mm cells) has a rope, a panel and a batten to cut |
| Every break says what it cost, against the material's own fracture energy | World | the room's own words after a break |
| The energy-scaled failure law | Test room | any room that asks for it: `/world?scene=tests-break`. A room that says nothing runs the strain-threshold law |
| Joints weaker than the material they join | Code only | built and tested, but every joint is held at full strength until the owner sets numbers ([issue #20](https://github.com/lrspeiser/banjo/issues/20)) |
| "Algorithm 3" (precomputed propagators) | Code only | a lane in the fracture lab, which went when the lab's page did |
| Implicit Newton, modal-basis, quasi-static and GPU (CUDA) fracture solvers | Code only | command-line tools; the GPU backend needs `-DBANJO_BUILD_CUDA=ON` |
| The older "network" solver, cohesive interfaces, tetrahedral contact, continuum and J2 plasticity references | Code only | tests and probes; the lab panels that ran some of them no longer have a way in |

**Not built:** calibration against laboratory data; piece counts that converge
as the cell size shrinks; a failure path for thin parts; keeping a crack in a
body that stays whole.

## Materials

| Behaviour | Status |
|---|---|
| Bond failure by strain; yielding and denting | World |
| Friction, bounce (restitution) and rolling resistance | World; rolling resistance also depends on the ground (rock 0.001, soil 0.06, sand 0.30) |
| Strength lost to heat (oak, iron, concrete) | World |
| Internal damping and random strength variation | Code only: in the catalogue but switched off in the world |
| Wood grain (oak's anisotropy) | Not built in the world: declared in the catalogue and never read. Directional laws exist only in the older solver and the continuum reference |
| Full (J2) plasticity with hardening | Code only: a reference solver; the world's plasticity is along each bond only, with no hardening |
| Material QA: 96 impacts across all eight materials | Code only (`scripts/material_qa.py` in CI, and the `/api/material-qa` API) |

## Heat, fire and thermodynamics

| Capability | Status | How to try it |
|---|---|---|
| Heating, conduction, radiation, energy ledger | World | aim at something and press **Heat it** (B), 10 kW for 60 s; the Room tab's Heat panel shows temperatures, power and the ledger |
| Burning wood | World | the hearth's logs burn from the start; heat any oak |
| Strength lost to heat; oak chars at 300 °C | World | heat a plank; the panel shows the strength left and the char depth |
| Burning away: objects shrink as they burn | World | keep heating a log |
| A heated peg or pin giving way | Chat | ask for a fixing made of a named member, then heat it (about 50 s under 2 kW) |
| Gas in a cylinder pushing a piston | Test room, Chat | `/world?scene=tests-motion`: heat the piston |
| Heat kept by things in the bag | World | a thing in the bag is kept exactly as it was put away |
| Ice melting, and its meltwater running into the room's water | World | heat an ice block (B): 10 kW melts 30 g a second. The Explorer's valley has one: `/world?scene=explore` |
| Freezing | Code only | only in a separate voxel thermal simulation (`SparseThermalWorld`, `EnthalpyLaw`), with no link to the world's heat |
| Small thermal experiments | Code only | `banjo_thermal_experiment_cli` |
| Circuit heat, manufacturing heat | Code only, Page | machine circuits; the manufacturing page's station heat |

**Not built:** freezing or boiling in the world; fires that go out; thermal
expansion; smoke, flame gas and airflow; heat into water or into the ground;
friction, impact, cutting or motor work turning into heat; gas pressure on a
container's walls.

## Water

| Capability | Status | How to try it |
|---|---|---|
| River and pond | World | the valley under `/world` (also `/world?scene=explore`, where the water is drawn but not updated) |
| Floating, drag and dams | World, Chat | drop things in the river; ask the chat to "dam the river with stone blocks" |
| Rivers beyond the valley: reservoir, reaches, a confluence and a lake | Test room | `/world?scene=watershed`; dam the river and watch the reservoir fill |
| Changing the river's flow | Chat | the chat's `set_river` |

**Not built:** waves and wakes; sediment moving while you play; rain,
infiltration and evaporation; wet soil; water and heat affecting each other;
switching regions between coarse and detailed simulation as you walk.

## Ground

| Capability | Status | How to try it |
|---|---|---|
| Digging and heaping, with slumping | World | **Dig here** (F) and **Heap here** (H) |
| Digging with a pick: swing and pry | World | take up the pick with E, swing with the left mouse |
| Carrying what you dig (80 kg budget shared with what you hold) | World | dig, then look at the bag |
| A machine digging a place it was sent to | Test room | `/world?scene=tests-dig`, `/world?scene=tests-mine` |
| Filling and cutting out blocks | Chat | the chat's `fill` and `cut_block` |
| Storing dug sand and soil | World | `/world?scene=fabrication` |
| The ground kept across reloads and restarts | World | automatic |

**Not built:** breaking rock (a pick stops on rock, or says the case is not
supported), wet soil, tool wear, and landslides that rotate rather than slump.

## Joints, machines and energy

| Capability | Status | How to try it |
|---|---|---|
| Hinges, slides, rope links, pulleys, latches (fixings), springs | World | the gate, door, bell, portcullis and winch; the bow's limbs |
| Fixings that fail in tension or shear | World | the arrow's nock; stacked or heated loads |
| Drum, DC motor, battery and brake | World | the hoist: E on the drum, or its Operate panel |
| Every joule of a machine accounted for | World | the Room tab's Machines panel |
| What a machine is spending, and how long that leaves | World | the machine panel in the world, and the Bench tab's drive box |
| Wheels on pins: a product made of exact bodies | World (`/world?scene=explore`) | the cart: J pushes it, Q puts all of it in the bag and it comes back whole |
| Which end of a motor turns | Test room | `/world?scene=tests-motor`: three turntables where both ends are free |
| A machine that stops itself by what a sensor reads | Test room | `/world?scene=tests-cart`: its water sensor stops it at the lake's edge |
| A machine with a program that roams by itself | Test room | `/world?scene=tests-rover` |
| A machine that digs a place, loads and hauls | Test room | `/world?scene=tests-dig` |
| A machine that goes to a thing and sits on it | Test room | `/world?scene=tests-sit` |
| A machine that flies, and rises and descends | Test room, Page | `/world?scene=tests-mine`; Space and Shift+Space at the bench |
| A machine that knows it is getting nowhere and backs out | World | automatic for any machine told to go somewhere |
| A machine that stops before it turns, and turns from rest | World | automatic when one is told to go to a place or face one |
| Solar panels that charge a battery from the room's sun | Test room | `/world?scene=tests-solar` |
| A sun that crosses the sky and sets | Test room | `/world?scene=tests-day` |
| Raw materials into finished goods | Test room | `/world?scene=tests-mine`: ore, copper, wire, and the Workshop's rack |
| Routines, conditions, watches and spoken orders | World, Page | a machine's panel, its chat, and the bench |
| Electrical and thermal circuits | Code only | the MCP's standalone world, the C API, `examples/authoring/circuit_drive.py`; the room refuses them |

**Not built:** gears; motor heat that warms anything; hinges with a strength;
joints that fail by bending or prying; a bearing's strength along its axis; a
bump sensor that feels a knock rather than a stall; seasons, clouds and the
moon.

## Hands, tools and handling

| Capability | Status |
|---|---|
| Pick up, carry, put down with a checked preview, the bag | World (and `/world?scene=explore`) |
| Throwing, the bow, swinging a sword, a pick | World |
| One saved "Use" per product (left mouse or J) | World (and `/world?scene=explore`) |
| A thing of several parts taken up whole, its moving parts still moving | World: the mace and the cart in `/world?scene=explore`, and `/world?scene=tests-carry` |
| Where a throw would land, drawn before you let go | Branch (`agent/throw-aim`) |
| Two hands | Not built; the second hand is planned as a powered gripper |
| Declared grip and use points | Not built: they are stored but never read; the hand holds wherever you point |

## The rooms

| Room | Cell | Reached by | What to try |
|---|---|---|---|
| `world` | 40 mm | menu | nearly everything: breaking, burning, water, digging, joints, the hoist, the bow, the sword, the pick |
| `expedition` | 40 mm | menu | gather stone and wood, build a dryer, dry timber (a bookkeeping model, not native physics) |
| `explore` | 40 mm | address | a block of every material, furniture, a mace on its chain and a cart on pins; picking up, placing, using |
| `bench` | 20 mm | address | plates of all eight materials, 20 and 40 mm thick, on piers: break them |
| `armoury` | 10 mm | address | cutting a rope, a panel and a loaded batten with a sword |
| `courtyard` | 40 mm | address | gate, portcullis with counterweight, chain, a shelf that breaks under load |
| `tests-gates` | 40 mm | address | hinges, a castle gate on a winch, a capstan |
| `tests-ropes` | 40 mm | address | ropes, pulleys, a pendulum, springs, the bow, cutting |
| `tests-motion` | 40 mm | address | breaking, denting, bouncing, sliding, burning, a gas piston |
| `tests-machines` | 50 mm | address | a motor, drum, battery and brake |
| `tests-carry` | 40 mm | address | a mace, a table and a chair, each taken up whole |
| `tests-cart` | 50 mm | address | a cart that drives down a shore until its water sensor stops it |
| `tests-rover` | 50 mm | address | a rover with a motor on each back wheel that roams a lake's shore |
| `tests-dig` | 50 mm | address | the rover digging its site until its hopper is full, then hauling the load to its depot |
| `tests-solar` | 50 mm | address | the rover with its battery nearly flat: it rests while its panel charges it |
| `tests-day` | 50 mm | address | the rover under a sun with a four-minute day, from four in the afternoon |
| `tests-motor` | 50 mm | address | three turntables that answer which end of a motor turns |
| `tests-sit` | 50 mm | address | a robot told where a stool is, which goes to it and sits down |
| `tests-mine` | 50 mm | address | a copper vein, a rover, a smelter, a drone and a mill: ore to wire |
| `tests-break` | 20 mm | address | an oak plank on piers and a ball dropped on it: the room says what breaking it cost |
| `watershed` | 40 mm | address | rivers beyond the valley; dam one and watch the reservoir fill |
| `valley` | 40 mm | address | the valley and its river, empty: dig, dam, float things |
| `clearing` | 40 mm | address | dry soil and bare rock, for digging and for tools |
| `yard` | 40 mm | address | a flat, empty yard for the chat to build in |
| `fabrication` | 40 mm | address | where manufactured parts are placed |

Twenty-five rooms; the menu offers two of them.
