# Banjo as a tool a model can use

A model asked "does a glass ball break if I drop it two metres onto concrete"
will give you a confident paragraph. This gives it a way to find out.

`mcp/banjo_mcp.py` speaks the Model Context Protocol over stdio, so anything
that can launch a subprocess — Claude, ChatGPT, your own agent loop — can build
a world out of real matter, run it, and be told what actually happened.

**No dependencies.** The protocol is JSON-RPC 2.0 over newline-delimited stdio,
which is short enough to speak directly; a server that needs a package installed
first is a server that does not get installed.

## Install

Build the library once:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release --target banjo_c
```

Then register it. For Claude Code:

```bash
claude mcp add banjo -- python /path/to/banjo/mcp/banjo_mcp.py
```

Or in any client's config file:

```json
{
  "mcpServers": {
    "banjo": {
      "command": "python",
      "args": ["/path/to/banjo/mcp/banjo_mcp.py"]
    }
  }
}
```

If the library is somewhere unusual, set `BANJO_LIBRARY` to its path in the
server's environment. Otherwise it is found next to the repository.

## The tools

Deliberately above the level of the C API. A model does not want to take four
hundred and eighty steps; it wants to set something up, run it, and be told what
broke.

| tool | what it does |
|---|---|
| `list_materials` | the eight materials and what each actually does, with measured speeds. **Worth calling first** — the numbers are not the ones you would guess. |
| `create_world` | build a world from a list of objects; returns an id |
| `run` | let time pass and say what happened: every break, every dent, and the hardest contacts with the speeds they would have needed |
| `drop` | the common experiment: put an object a given distance above a point, let it fall, report. The height is measured from **what it lands on**, not from the floor. |
| `describe_world` | every object, where it is, and what has happened to it |
| `add_object` / `remove_object` | change a world |
| `pick_up` / `place` / `let_go` | the hand: take hold of something already in the world and move it. Without this a model can only add new objects from above — it can build a scene but never rearrange one. |
| `collect` | sweep up the loose pieces near a point and say what they were made of, by material and by weight |
| `carried` | what has been swept up in this world so far |
| `cast_ray` | what a ray meets first — what is above or below something, what is in the way |
| `close_world` | free it |

`run` holds the **break conversation** itself. That is the part of this engine a
caller can get wrong: ignore it and the world freezes at the first impact for
ever. Nothing using these tools has to know that.

## What a session looks like

> **Build a glass pane on two piers and drop an iron ball on it from three
> metres.**

```
create_world  → world_id "a3f91c02", 3 objects
drop          → fall_m 3.0, iron ball, over [0,0,0]
```

```json
{
 "dropped": {"object": "iron ball", "fall_m": 3.0, "onto": "pane"},
 "simulated_s": 2.283,
 "computing_took_s": 0.85,
 "what_happened": [
  {"what": "broke", "object": "pane", "into_pieces": 40,
   "because": {"hit_by": "iron ball", "at_m_s": 7.62, "breaks_above_m_s": 4.51}}
 ],
 "hardest_contacts": [
  {"struck": "iron ball", "by": "pane piece 27", "at_m_s": 10.27,
   "breaks_above_m_s": 25.03, "bends_above_m_s": 10.01},
  {"struck": "pane", "by": "iron ball", "at_m_s": 7.62,
   "breaks_above_m_s": 4.51, "bends_above_m_s": null}
 ]
}
```

Every event carries **what caused it**, read before the fracture — afterwards
the body is gone and its pieces report their own collisions instead. Without
that, the answer is a list of shards hitting each other and no sign of what
actually happened.

`bends_above_m_s` is `null` for the pane because glass is brittle: it has no
speed at which it bends, which is a real answer rather than a missing one. The
iron ball has one, because iron does.

Then the follow-up nobody used to be able to ask:

> **Sweep up the glass and tell me how much there is.**

```
collect → near [0,0,0], radius 4.0
```

```json
{
 "picked_up": [{"material": "glass", "grams": 2040.0, "pieces": 93}],
 "objects_before": 109, "objects_now": 16,
 "carried": {"glass": {"grams": 2040.0, "pieces": 93}}
}
```

A hundred and nine bodies down to sixteen, which is the other half of why this
exists: the next experiment in that world would have found the pane unbreakable.

And when nothing happens, it says why:

```json
{
 "what_happened": "nothing broke or bent",
 "hardest_contacts": [
  {"struck": "pane", "by": "iron ball", "at_m_s": 2.34, "breaks_above_m_s": 4.51}
 ],
 "why_nothing_happened":
  "Every contact was under the speed it would have taken. Drop it from higher,
   or use something denser to do the hitting: a threshold depends on what is
   doing the striking as much as how fast it goes."
}
```

That is the answer someone actually needs. A tool that reports silence when a
thing bounced off teaches nothing.

## What the server tells the model about itself

On `initialize` it returns instructions, so a client that reads them starts in
the right frame:

> Banjo simulates matter: objects are cells joined by bonds that carry tension
> and compression, yield, and fail. Call `list_materials` first — what a thing
> is made of decides what happens to it, and the numbers are not the ones you
> would guess. Build with `create_world`, then `run` or `drop`. **Never say
> something broke unless a tool reported that it did.**

That last line is the point of the whole thing.

## Bounds

| | |
|---|---|
| 8 worlds open at once | each is a physics engine with its scene resident in it |
| 60 objects per world | plenty for an experiment |
| 20 s simulated per `run` | so a caller cannot ask for an hour |
| 25 s of computing per `run` | so one scene of shattering concrete cannot fail to return |

The wall-clock bound is the one that matters. The engine is far faster than real
time when nothing is breaking — a room at rest runs at 0.02× — and far slower
for the moments when something is. If `run` stops early it says so, with how
much it managed.

## Things the model will get wrong unless told

These are worth putting in your system prompt if you are building on this:

- **The centre is the middle.** An object at y = 0 is buried half in the floor.
  A thing resting on the floor has its centre at half its own height.
- **A plate on the floor will not break.** What breaks a plate is a span under
  it. Bridge it between piers.
- **A threshold is not a promise.** Clearing it means a break is *possible*.
  5.4 m/s on a 4.5 m/s pane still held.
- **Mass does not help.** 111 kg and 0.9 kg at the same speed are judged the
  same.
- **Iron is the hammer.** Aluminium is springy and transmits less of the blow.
- **A world that shatters fills up, and a full world stops breaking.** Fracture
  needs a step the engine can take back, and that cannot run past a couple of
  thousand bodies. Past it the room keeps running perfectly and quietly stops
  being able to break anything: the same iron ball onto the same 20 mm pane
  broke it into 71 pieces in a room of 58 bodies and left it whole in a room of
  430. One shattered pane is a hundred bodies, so this arrives sooner than
  anyone expects. **Call `collect` between experiments.**
- **A dented thing is not debris.** Something that bends is rebuilt from where
  its matter ended up, which makes it the same kind of shape a shard is — but it
  is still the object it was, and `collect` leaves it alone. So does anything
  anchored, and whatever is in the hand.

## Sweeping, and what it is for

```
collect(world_id, near_m=[0, 0, 0], radius_m=1.5)
-> {"picked_up": [{"material": "glass", "grams": 2040.0, "pieces": 93}],
    "objects_before": 109, "objects_now": 16,
    "carried": {"glass": {"grams": 2040.0, "pieces": 93}}}
```

Added up by material rather than by shard, because that is the form anything
built out of them wants: nobody needs ninety-three entries called
`"glass pane piece 31"`, they need to know there are two kilograms of glass. The
weight is the matter that was actually there — a piece's cells are its volume,
and volume times the material's density is what has been carried away.

`carried` accumulates per world, so a session can break several things and ask
what it has.

## Implementation

Roughly 700 lines of Python over the [C API](c-api.md), through
[the ctypes binding](../../bindings/python/banjo.py). It holds worlds by id,
converts the engine's refusals into sentences a model can act on, and turns
every non-finite number into `null` on the way out — infinity is a real answer
here (a brittle material's bending threshold *is* infinite) and JSON has no way
to write it.

Fifteen tests in [`tests/banjo_mcp_tests.py`](../../tests/banjo_mcp_tests.py)
drive it as a real subprocess through the real protocol, because calling the
handlers directly would miss everything that goes wrong at a protocol
boundary — a notification answered when it should not be, a schema a client will
reject, an exception escaping as a crash instead of an answer.
