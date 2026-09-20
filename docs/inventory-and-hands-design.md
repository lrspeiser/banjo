# Inventory and two hands: the design of increment 1

See the [material collection contract](material-collection-contract.md) for the
owner's requirement to preserve collected object state and distinguish it from
raw stock and explicit salvage.

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
- **What a room keeps.** `room_store` keeps the authored spec (with the chat's
  builds and the ground's digs), the conversation, the inventory record and,
  since `banjo.room.v2`, the running world as the engine saves it. A reload
  rejoins the running world, and a restart opens the room into the saved one.
  A change by the chat reopens the whole world from its spec. See "What a room
  keeps" below.
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
  stowed, home, facing}`. An item not in it is in the world.
  - `stowed` is the bag's slots in order: an id, or `null` for an empty one.
  - `home` keeps, for a thing in a hand, the slot it came out of, so stowing it
    puts it back there: the number that took it out is the number that puts it
    back. A thing taken in goes to the first slot that is neither filled nor
    kept for another.
  - `facing` is how each thing faced as it went in, so it comes out the same.
- **The ops:**
  - `take`: from the world into the inventory;
  - `take_up`: into a free hand, the dominant hand first. With both hands full it
    goes into the inventory instead, so what is being used is never dropped or
    replaced;
  - `equip`: from the inventory into a free hand. With both hands full it is
    refused;
  - `stow`: from a hand into the inventory;
  - `drop`: from a hand or the inventory into the world.
  - A thing that is not one of the room's items -- a broken piece, which the
    spec does not have -- is refused as `unknown`, so the page can take it by
    its own grip instead.
- **`request(id, expected_revision, op, item, items, act)`:**
  - it answers a repeated id as the first time, without acting again;
  - it refuses a stale revision, with the record as it is now;
  - it asks `act(plan)` to do the room's part, meaning park, unpark, the hand or
    putting the thing down, and changes nothing if that raises;
  - it keeps the last 64 answers.

## Transactions

- `POST /api/world/inventory {session, request, revision, op, item, person,
  grip}`. The op is one of `take`, `take_up`, `equip`, `stow` or `drop`. `grip`
  (take_up) is where the hand takes hold -- a tool's handle -- and the thing's
  middle when it is not given. `POST /api/world/inventory/shown {session}` is
  the record as the page shows it.
- The page sends its changes one at a time, in the order they were made, so a
  thing put down and another picked up straight after reach the record in that
  order. One refused as stale is asked again once, against the record as it is.
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

## What a room keeps

This section says what the code does (checked 2026-09-15), not what was
planned. The plan here was a `room_store` v2 with every item's pose. What was
built instead keeps the engine's whole world, and "a damaged thing cannot be
stowed" was never checked by anything.
- On disk (`room_store`, `banjo.room.v2`; v1 still reads): the spec, the chat,
  the inventory record, and `world`, the running world as the engine saves it
  (`LiveWorld::snapshot`, "banjo.world.v1"). Written together, in one file, or
  not at all.
- What `world` holds:
  - every body by its cells (the scene's own node numbers) and their offsets in
    its frame, its name, body id, shape, dent, where it is and how it moves,
    and whether it was at rest (it comes back asleep);
  - the pieces things broke into, bonds a blade severed, each bond's permanent
    set, and kerfs;
  - joints, attached or parted, each reading the angle or travel it had;
  - edges and tool points in their bodies' frames;
  - what is set aside, where it was put away;
  - the hand: what it holds, grip or carry, the grip, where it wants it;
  - the clock and the counters, so what is made next is named and numbered
    after what there is;
  - the water, when the room has ground.
  - Not yet: heat, char and fuel, which are declared again from the spec for
    what is still there; and anything under way. A world is not saved while a
    break is being worked out, a stroke is being made, an edge is in a cut or a
    point is in the ground, and the last one saved is kept. A broken tool's
    pieces are not yet its inventory item: each piece carries `from`, the name
    of the authored thing it came from, for that.
- When it is saved (`server.keep_world`): after an accepted inventory change,
  after a break is worked out, every 5 s of the world's time while the page
  steps it, after the ground changes, after the room opens, and as the server
  stops (Ctrl+C or SIGTERM).
- A page reload rejoins the running room (`server._rejoin`,
  `live_session.Live.rejoin`). Every body is where it is and as it is: moved,
  broken into pieces, dented. The hand still holds what it held, and the bag is
  as the record has it.
- A server restart opens the room into the saved world, when that was saved
  from the spec the room has now (`live_session.spec_digest`, which leaves out
  the ground's edits and the carried water). Everything is where it was left
  and as it was; the hand still holds what it held, and the record keeps it in
  the hand (`inventory_room.after_open`). The engine's fingerprint of the
  scene's cells refuses a world saved from other cells -- another scene, or a
  build that lays them out another way. Then the room opens from its spec
  with each thing still whole and its own self put back where it was left, and
  the saved world is set aside beside the room with why, never deleted.
- "Start the room again" opens the room again from its spec, as a reload used
  to, and the world kept from then on is that one.
- A dented thing can be stowed: nothing checks for a dent. It comes back from
  the bag as it went in (park and unpark keep the body), and a restart keeps it
  in the bag, dent and all.

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

## The first slice's page (E into the bag: replaced by the second slice, below)

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

## The second slice: the side view and the keys (2026-09-14)

The owner, after trying the bag: "there is way too much text on the screen. we
need a simple chat sideview, and then all the other text needs to be in tabs in
part of the side view. also it's still really hard to interact with an item. I
pick it up and it goes in my bag, but then its not easy to put it back down
without escaping the mouse and clicking on it." Their answers to four
questions:
- E on a loose thing picks it up into the hand; E again puts it down; Q puts it
  in the bag; the left mouse throws.
- The bag's things sit in numbered slots along the bottom of the view: 1-9
  takes one into the hand, and the same number puts it back.
- The side view has the chat on top and tabs below.
- Over the view only the name of what the crosshair is on ("Iron Kettle"), with
  its details in the side view: "if needed we can have three windows on the
  side, chat, view details and tabs for inventory, etc."

As built:
- **E** on a loose thing a hand can lift is `take_up`: the room's hand grips it
  where it lies. E again puts it down with the page's careful putDown, and when
  the hand lets go -- put down, dropped or thrown -- the record is told `drop`.
  A thing the record does not keep (`unknown`) is taken by the page's own grip,
  as it always was, and so is anything with Alt+E.
- **A tool** is taken up the same way, by its handle (`grip`), and then held
  ready as before. One out of the bag is gripped by its handle once it is out.
- **A blade** is taken by its grip with E, the page's own hold as before. Q
  puts it in the bag (`take`), and out of the bag it is held by its grip again,
  its edge facing down.
- **Q** is `stow` for what the record says the hand holds, and `take` for
  anything else: what the crosshair is on, or a thing the page holds by its own
  grip.
- **1-9** is `equip` for that slot's thing. With the thing from that slot in the
  hand, the number is `stow` and it goes back into its slot. With another of the
  record's things in the hand, that one is stowed first, so a number swaps what
  is held. Anything else in the hand has to be put down first.
- **Tab** moves E on to the next of what can be done: a thing's own actions,
  the built-in ones, and taking hold of it by hand. So the number keys are the
  bag's, and every action is still on a key. It comes back to the first when
  the crosshair leaves the thing.
- **Down** moved from Q to Shift+Space.
- **The side view**: the conversation; the details of what is looked at or held
  (name, facts, what E, Tab, Q and the mouse do now, the measured meter, and
  what the last thing done came to); and tabs for the Bag, Notes, Room, Bench
  and Keys. What the hand does is said in the details, not the chat.
- **Found on the way:** a thing from the bag put down with E ended in the page's
  settleDown, which never told the record. The record kept it in the hand, and
  the next room opened would have put it in the bag.
