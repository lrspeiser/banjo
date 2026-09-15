# Inventory and two hands: the design of increment 1

Draft, 2026-09-14. This is how the owner's spec (docs/inventory-and-hands.md) is
built, starting from what the code does today. The engine half is still open:
whether a body can be taken out of a running world and back, and a second
hand.

## What there is today (read from the code)

- **Identity.** A thing is known by its body's name in the spec, the room, the
  server and the page. A broken piece is renamed "<name> piece N". Only the
  authored name survives a reload.
- **The hand.**
  - The engine has one hand (`LiveWorld` `Impl::holding`), which carries,
    hauls or grips.
  - The page owns what is held (`world.held`, 16 modes in `world.use`).
  - The server reads only `session.state.hand.holding`, and refuses a thing's
    action while the hand holds anything else (`run_action`).
- **E.** On the page it runs a cascade (`world.js` `pickUp`):
  1. a tool lying nearby;
  2. a thing with a profile (the bow);
  3. a tool's part;
  4. anchored: refused;
  5. a blade: wielded;
  6. a liftable loose thing: wielded at its middle;
  7. anything else: grabbed, so carried, or hauled on its joint.
- **What a room keeps.** `room_store` v1 keeps the authored spec (with the
  chat's builds and the ground's digs) and the conversation. Where things were
  moved by hand, and what broke, go with the running world. A change by the
  chat reopens the whole world.
- **The engine.** It cannot add a body to a running world, nor take one out and
  bring it back with its state.

## The model

- **Item.**
  - An item is a portable thing with a stable id: `item` on its bodies in the
    spec.
  - Every body of a join group shares one id, and so does an assembly whose
    parts are joined only to each other (a stool's legs are not five items).
  - An item is **installed** when any part is anchored, or joined through
    attached joints to anything anchored (a gate on its post). An installed
    item is operated, never taken.
- **Where an item is.** `world`, `stowed`, `hand` (left, right or both), or
  `reserved` by an action. Stowed and in a hand are both possession: an
  equipped item is still in the inventory, not a second copy.
- **Hands.**
  - There are two, left and right. Each is free, holding an item, supporting
    one held with the other hand, or reserved by an action.
  - One hand is dominant, the right unless the person says so, and takes a
    one-handed tool.
- **Who owns the record.** The server keeps the record, and the page shows it
  and never decides it:
  `{revision, dominant, hands: {left, right}, items: {id: {where, hand}}}`.
- **E asks the server.** What E does here is the server's answer, the same for
  the page, the chat and the API:
  - a portable tool is taken and equipped if the hands it needs are free;
  - an ordinary thing goes into the inventory;
  - an installed thing is operated;
  - a thing in reach but too heavy to lift says so.

## The record as built (playground/inventory.py)

- **`items_of(spec)`** works the items out from the room's spec every time, so
  they are never kept twice:
  - it joins every body of a join group, and both ends of every joint;
  - an item is installed when any part is anchored;
  - it is `one_piece` when the engine holds it as one body joined to nothing,
    which is what can be set aside as it is;
  - its id is the smallest id among its bodies, and its name is its first part's
    name, which is also the engine's name for a join group's piece.
- **`Inventory`** is the record: `{revision, dominant, hands: {right, left},
  stowed: [ids]}`. An item not in it is in the world.
- **The ops:**
  - `take`: from the world into the inventory;
  - `take_up`: into a free hand, the dominant hand first. With both hands full it
    goes into the inventory instead, so what is being used is never dropped or
    replaced;
  - `equip`: from the inventory into a free hand. With both hands full it is
    refused;
  - `stow`: from a hand into the inventory;
  - `drop`: from a hand or the inventory into the world.
- **`request(id, expected_revision, op, item, items, act)`:**
  - it answers a repeated id as the first time, without acting again;
  - it refuses a stale revision, with the record as it is now;
  - it asks `act(plan)` to do the room's part, meaning park, unpark, the hand or
    putting the thing down, and changes nothing if that raises;
  - it keeps the last 64 answers.

## Transactions

- `POST /api/world/inventory {session, request, expected_revision, op, item,
  hand}`. The op is one of `take`, `stow`, `equip`, `unequip` or `drop`.
- The same request sent twice gets the first answer, so a retry never takes a
  thing twice.
- An `expected_revision` that is out of date is refused, with the record as it
  is now.
- Every op checks and moves under one lock, so an item is never in two places.
- A refusal says what is wrong in the person's words: "Cannot stow while
  drawn", "The gate is fixed to its post: it can be opened, not taken".

## What can be stowed at first

- An item can be stowed when all of these hold:
  - it is whole, never broken or dented;
  - it is not anchored and joined to nothing outside itself;
  - it is not burning or hot;
  - it holds no stored energy (a drawn bow);
  - it is not moving;
  - it is within what the hands can lift.
- Anything else stays in the world or in the hand, with the reason.
- No state is quietly paused, repaired or thrown away by stowing.

## What a room keeps (`room_store` v2)

- With the spec and the chat, the room keeps two more things:
  - the inventory record;
  - the pose of every item where it was left in the world.
- So a reload puts things where they were, a stowed thing stays stowed, and
  nothing comes back as an old copy.
- A v1 file still reads, with an empty inventory and the authored poses.
- Damage is not kept yet. A thing that has broken or dented cannot be stowed,
  and says so, and a reload restores it as authored. That stays open.

## The engine half (read from the code, 2026-09-14)

- **The bow needs no second hand today.**
  - Its grips are anchored scenery, and the hand hauls only the string
    (banjo_mcp `RECIPES["bow"]`, world.js `takeUpBow`).
  - A bow carried in one hand would need a second hand holding its grip while
    the other draws. That is increment 4, with the bow's profile made to go
    unloaded, loaded, drawing and releasing.
  - There is no re-nock today, and a nock that came off stays in the engine's
    list of joints.
- **Nothing takes a body out of a running world and back.** Every `RemoveBody`
  is followed by `DestroyBody`, and `AddBody` is used only for new fragments.
  So stowing needs a new primitive: park, and unpark.
  - **JoltWorld:**
    - Take the body out of the broadphase without destroying it: `RemoveBody`,
      keeping the Body and its id. Put it back at a pose: set the pose, then
      `AddBody` and activate.
    - Only between steps, behind the guard on changes, never inside the
      reversible trial. Jolt's saved state covers only the bodies in the
      broadphase, and adding or removing one inside a trial throws.
    - JoltWorld keeps throwing when asked about a body it no longer holds.
      LiveWorld guards every call instead (13 of them were unguarded), so a
      mistake shows up as an error, never as a body quietly doing nothing.
    - The loops over every body (`contactPairUpperBound`, `mechanicalTotals`)
      leave it out. So a thing's energy leaves the world's account when it is
      set aside, and comes back with it.
    - `removeAndDestroy` destroys a parked body too, so nothing can leak one.
  - **LiveWorld:**
    - A parked slot is left out of `poses()`, so the runner says it is gone and
      the page stops drawing it.
    - It is left out of foresight, fracture, the surveys, heat and water:
      `contains()` says no.
    - The hand lets go of it first, and any stroke on it stops.
    - A parked body is recorded by name, since names survive the reindexing
      that happens when bodies break.
    - It is refused, with the reason in words, when it is:
      - anchored ("fixed in place");
      - named by any joint;
      - part of a fracture that is running, queued or guessed;
      - being cut;
      - carrying a tool point that is in the ground.
    - Its heat, contents and fuel stay exactly as they were. It is coupled to
      nothing while it is set aside: time stands still for it thermally. Before
      this, the heat network would have forgotten the thing and booked its heat
      as leaving the world.
    - A tool's point is skipped while its tool is parked, not detached, so it
      works again when the tool comes back.
  - **The runner, the C API and the Python binding:**
    - The runner gets `park {name}` and `unpark {name, at, q}`.
    - The C API and the Python binding get the same, for the MCP and the
      in-process lane.
- **What the page draws.**
  - It draws a held thing only where the engine has it. There is no
    first-person view model.
  - A stowed item's picture in the panel is built from the last reply's shape,
    size, material and cells, since the workbench already draws bodies that are
    not in the engine.
- **A room that reopens** (the chat built something) opens its stowed items
  with it and parks them before the first step.
- **A second hand** (increment 4): a hand index through the engine's hand, its
  operations and its reply. Each hand has its own force and torque, and the
  whole person shares one limit, rather than the single hand's budget doubled.

## The first slice's page

- **E on an ordinary liftable thing puts it in the bag** (`take`), and the page
  says "Oak cup added to inventory."
  - Alt+E still takes a direct grip, as the advanced hold does today.
  - Tools, bows, blades and things on joints keep their own E.
- **The panel's "Holding" row becomes three rows:** the right hand, the left
  hand, and "In your bag".
  - Each thing in the bag has two buttons, Hold (`equip`) and Put down (`drop`).
  - A thing in the hand has Stow (`stow`), and Put down, which goes through the
    page's own careful putDown.
  - The rows are drawn from the server's record, which arrives with each room
    opened or rebuilt and each change. The page never decides it.
- **The engine has one hand.** The dominant hand is the one that holds, and the
  left hand's row says so until the second hand comes with the bow.
- **Panel buttons are not the canvas,** so clicking one never also acts in the
  world. Tab stays as it is until increment 2 makes it the inventory.

## The first slice to test in 3D

1. E on a small loose thing (a cup, the sword):
   - the page says "Oak cup added to inventory";
   - the thing leaves the world, parked and not destroyed;
   - the panel lists it under the inventory, with both hands free.
2. From the inventory (Tab):
   - Equip puts it in the dominant hand, out of the park into the hand's grip;
   - Stow puts it back;
   - Drop sets it down in front.
3. After a page reload and a server restart, it is still in the inventory, and
   nothing is duplicated.
4. E on the gate operates it and does not take it. E on something too heavy says
   what it weighs.

Tests go with it:

- C++: parking a body keeps its mass, shape, contents and temperature.
- Python:
  - a retry takes nothing twice;
  - a stale revision is refused;
  - two callers cannot both take one item;
  - v1 and v2 files both read.
- Browser: steps 1-4 in headless Chrome.
