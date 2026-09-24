# What is left

The working list. `docs/roadmap.md` is the history -- what was done and what was
measured; this is what has not been done yet. Keep it current: when something
lands, move it up and say what was measured; when something is found to be
missing, put it in.

Last touched 2026-09-24, branch `agent/fracture-truth` (pushed, not merged).

## Ready to try

These work and are watchable. `python playground/server.py --port <p> --engine
<build>/banjo_platform_cli.exe`, then:

- **A robot goes to a stool and sits on it** -- `/world?scene=tests-sit`. Look
  at the robot, E for its panel, On. 12.5 s, stops 0.51 m from the stool's
  middle and 3.4 degrees off square, its torso resting 24 mm above the seat.
- **What a break costs** -- `/world?scene=tests-break`. Drop the ball on the
  plank; every break reports what it cost.
- **A rover that roams by itself** -- `/world?scene=tests-rover`, and the same
  rover on solar (`tests-solar`) and through a night (`tests-day`).
- **The Workshop** -- `/world?workshop=1`. Ask the chat for something, Check it,
  Make it, Back to the world. The rack at the bottom holds the stock a design
  spends; a design short of stock is refused until the rack has it.
- **A thing the Workshop made, opened on the bench again** -- make something,
  then ask the world which design made it: it hands back the recipe, and the
  bench loads it.

## Next

1. **The chat-built robot cannot turn.** Nine tool calls build it, the bench
   takes it as drawn, it compiles into six bodies on five pins and the Workshop
   installs it as a machine -- but on the ground it drives and will not come
   round, so it never reaches the stool. The hand-built one does. First thing to
   test: the bench only fastens parts that TOUCH, so a butt-jointed swivel sits
   face to face with the deck it hangs from and the two faces rub, where the
   hand-built caster hangs from a pin with clearance. The compiler already
   speaks of "explicit clearance".
2. **Ask the model to design it.** The nine calls above are the ones a model
   could make, and they are written by hand. Nothing has yet asked the chat for
   a robot and watched what it draws.
3. **Behaviours written down as data, not code** (docs/how-robots-think.md).
   Start by re-expressing "roam" and "sit" in that form and checking the engine
   tests pass with the same numbers. If they cannot be expressed, the vocabulary
   is wrong, and that is worth knowing on the first day.
4. **A behaviour's trial**: the room, the start, and what must be true at the
   end. `tools/build_sit_room.py` already does this by hand; make it the shape.
5. **The chat writes a behaviour**, and it passes its trial before it is
   offered.
6. **A library and a price for behaviours**: shared between machines, and a room
   that would miss the realtime gate refused with the number.

## Waiting on the owner

From docs/how-robots-think.md:

- **D1.** When a person asks for a behaviour, does the chat show its trial
  running before it is installed, or does it go straight into the room?
  *Recommended: show the trial.*
- **D2.** May a person edit a behaviour by hand, in a panel that lists its
  states in plain English? *Recommended: yes, the numbers at least.*
- **D3.** Does a stuck machine ask for help by itself? *Recommended: no. It says
  why and waits.*
- **D4.** The body cap: a room holds 32 exact bodies, so five robots of this
  shape, where the processor would carry many more. Raise it before a small
  ecosystem of machines is attempted.

## Known gaps, in the order they will bite

- **A room holds 32 exact bodies.** Measured: one thinking robot runs at 33x
  realtime, four at 20x, about 27 us a step for each one added -- the cost of
  its bodies, not its thinking. The cap, not the processor, is the ceiling.
- **The ground slides the same whatever it is made of.** Terrain rolling
  resistance varies by ground material; terrain sliding friction is one material
  for the whole patch, so ice and sand slide alike.
- **A break spends about 41 J/m2 where oak charges 1,000.** The failure law
  reports the cost honestly and the energy that goes into it does not match it
  yet (docs/what-a-break-costs.md).
- **check_validity dead-ends on a vertical pin.** Drawing a caster the natural
  way -- a pin through the deck -- can never compile at any cell size, and the
  bench refuses it with "nothing here answers" rather than saying that a butt
  joint under a flat face is how a swivel is drawn.
- **A machine with a program owns its wheels.** An off program still tells them
  every step, so a person cannot drive a programmed machine by hand. Deliberate,
  but it should be said in the panel rather than discovered.
- **The rover journey flakes.** One CI red that passed on a re-run and was shown
  not to be the change under it.
- **`agent/fracture-truth` is not merged.** Five commits: the bench round trip,
  the sit program, the tests-sit room, the plan, and the chat-built robot.
