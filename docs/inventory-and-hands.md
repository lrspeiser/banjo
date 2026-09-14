# Inventory and two hands: the owner's spec

The owner's instructions for the next program of work, given 2026-09-14 after the one world
landed, word for word below. The owner set the order of work: the world first (8289505), then the
pick as a generic tool capability (37a0c02, bdeac52, c39399c), then this. The design and the
state of each increment are in docs/development-status.md.

---

**Yes—move to an inventory-and-two-hands model, with one obvious action for each situation and precision manipulation available when the user asks for it.** The default experience should be "use this object," not "manually position every part until something happens."

The rule I would use is:

> **Automate the handling, not the physical outcome.** Choose sensible grips, orientations, and action sequences automatically; let the engine determine whether the object can actually do the job.

## What the latest main already gives us

I reviewed `main` at **`8085afe`**, reconfirmed that revision at the end, and checked that **CI run 223 passed**. Local cloning was unavailable, so this is a source-and-CI review, not a fresh test of your deployed simulator.

There is useful work to preserve: single-click inspection, model-authored `offer_actions` programs, built-in placement actions, and the latest automatic turn/slide operations for joints. **The notebook has also landed since my previous review.**

But the underlying interaction model is still fragmented. The browser has one `held` object, separate drawing/releasing state, and material-total "stock," rather than a general inventory of intact objects. Its controls expose six rotation keys, an upright key, reach adjustment, throwing, and object-specific behavior. My assessment is that adding more shortcuts to this structure will not resolve the confusion.

**One important prerequisite:** current room persistence saves the authored scene and conversation, but explicitly does not preserve where objects were moved by hand or what broke. Inventory cannot be just a new panel on top of that save model.

# Instructions for the coding agent

## 1. Introduce one consistent model: world, inventory, and hands

Create a server-owned actor inventory and equipment model. Keep it separate from physical material laws, but connect it to the engine's actual objects.

**Inventory means possession. Hands mean immediate use.** An equipped item is still part of the player's inventory; it is not a second copy.

Every portable object should have a stable identity and a location such as:

```text
In the world
Stowed in the player's inventory
Equipped in one hand
Equipped using both hands
Temporarily reserved by an action
```

Hands and inventory slots should reference that same object record. Preserve its geometry, materials, internal joints, damage, contents, temperature where supported, interaction profile, and design identity.

### Make pickup straightforward

Use **E** as the normal contextual interaction:

* On a portable tool, take it and equip it when the required hands are available.
* On an ordinary collectible object, put it into inventory; let the user equip it from its card.
* On an installed mechanism, operate or take hold of it—not detach it into inventory.

When taking another object with occupied hands, stow it rather than silently replacing or dropping what the player is using. Show a brief, specific result: **"Oak cup added to inventory."**

Do not require double-click timing. The existing double-click pickup can remain as an optional shortcut, but it should not be necessary.

### Preserve the distinction between items and raw material

A wooden pick in inventory remains **that wooden pick**. It does not become kilograms of oak that later regenerate into a pristine pick.

Keep raw soil, sand, and genuinely collected material in their existing material accounting. Converting an intact object into raw material must be an explicit supported operation, not a side effect of pickup.

Treat a portable assembly as one inventory item with its internal parts and joints intact. A stool's legs should not become five unrelated inventory entries. Conversely, a gate attached to a building must not become portable just because the user selected its handle.

### Start with bounded storage support

Initially, support stowing ordinary, nonreacting, unloaded objects whose state can be preserved correctly. A burning object, drawn bow, or actively spilling container should remain in the world or hands until its storage behavior is implemented.

Say **"Cannot stow while drawn"**, not simply "Inventory failed." Do not pause combustion, restore damage, or erase stored energy by putting an item in a bag.

---

## 2. Model two hands, including temporary hand requirements

Do not reduce this to an item property called `two_handed`. There are at least three different cases:

| Item or activity                         | Requirement                                                           |
| ---------------------------------------- | --------------------------------------------------------------------- |
| Small cup or ordinary one-handed tool    | One hand holds it.                                                    |
| Large beam or designated two-handed tool | Both hands hold the same item.                                        |
| Bow                                      | One hand holds the bow; the other must be available to load and draw. |
| Winch                                    | A hand may remain occupied maintaining the load after turning.        |

Each hand needs a visible state: **free, holding, supporting, or reserved for an action**.

Support a dominant-hand preference. Normally put a one-handed tool in the dominant hand and a bow in the other hand. Do not force the user to micromanage left/right assignment for ordinary use.

**Do not simply double the existing force budget because there are two hand slots.** Hand forces, torque, and any shared actor limits must be explicit. Nor should the existing lifting limit become a universal interaction limit: the latest code specifically distinguishes moving a heavy gate around a hinge from lifting its weight.

### Make the bow the reference example

The desired sequence is:

**Equip bow → select a compatible arrow automatically → load → draw → release.**

The player should not have to drag an arrow onto a tiny connection point.

However, the arrow must be an actual available item. Reserve it when loading starts, move that same item into the loaded state, and release that same physical projectile. Cancellation must not duplicate ammunition.

The current `draw-and-release` profile names a particular projectile and nock. Extend it to represent **unloaded, loaded, drawing, and releasing** states, rather than assuming that an arrow is always already attached. Preserve the existing physical release mechanism.

When the other hand is occupied, show:

> **Right hand needed to draw. Stow the cup and draw.**

That should be one available action, not several inventory chores. Under the default assistance policy, safe stowing can happen as part of the requested action, with the consequence shown beforehand. Never automatically drop an item, extinguish it, or release a load to free a hand.

---

## 3. Turn the side panel into the primary interaction surface

Use the side panel to answer three questions continuously:

**What do I have? What am I using? What can I do next?**

At the top, show persistent left-hand and right-hand slots. Below those, show the active object's compact preview, state, and actions. Put the broader inventory behind **Tab** or an inventory button.

A bow card might read:

> **Oak bow — left hand**
> Right hand: free · Compatible arrows: 6
> **Draw** · Place · Stow
> More: inspect construction, change ammunition, manual manipulation

A pick card might read:

> **Oak pick — right hand**
> Target: dry soil
> **Dig here** · Place · Stow
> Last action: soil loosened; tool intact

These are proposed layouts, not claims about the current UI.

### Keep the object preview separate from the physics object

Render the preview from the actual item's mesh and state, but do not create another simulated body for the panel. It should depict the current damaged or modified item, not always a pristine catalogue image.

The equipped object can also appear in the appropriate side of the first-person view. Its world collision and motion remain engine-owned; a view presentation must not make it pass through obstacles.

### Limit the primary choices

Show **one prominent recommended action and two or three secondary actions**. Put detailed manipulation and diagnostics under **More**.

Do not make nine numbered actions plus a long controls paragraph the normal experience. Keep installed-object selection persistent while the player moves the cursor into its panel; looking slightly away must not make the controls disappear.

Clearly label whether the panel describes **"In your hand"** or **"Selected in the world."** Selecting a gate must not quietly change which inventory item is equipped.

### Use consistent input meanings

| Input                                 | Default meaning                                                           |
| ------------------------------------- | ------------------------------------------------------------------------- |
| **E**                                 | The displayed contextual interaction: take, equip, or operate.            |
| **Left mouse**                        | Use the equipped item's primary action; with empty hands, inspect/select. |
| **Right mouse**                       | Secondary action or cancellation, as visibly labelled.                    |
| **Tab**                               | Inventory and equipment.                                                  |
| **Place button / placement shortcut** | Enter ghost placement.                                                    |
| **Escape**                            | Cancel the current UI operation or close its panel.                       |

Never let a panel click also trigger a world action. The mouse release after equipping an item must not become a throw or a shot.

Keep semantic actions in the binding table, provide remapping and hold/toggle alternatives, and generate displayed prompts from the actual bindings. Microsoft's game-accessibility guidance specifically recommends remappable actions, alternatives to prolonged holds, and correctly updated prompts. ([Microsoft Learn][1])

---

## 4. Build a shared action resolver—not more object-specific browser code

Extend the existing **interaction profiles and `offer_actions` system**. Do not create a third independent way to define object behavior.

Currently, profiles provide `draw-and-release` and `swing-and-lever`, while `offer_actions` provides validated programs such as carrying, placing, pushing, turning, and sliding. Those are useful foundations.

Add a shared resolver that evaluates:

```text
Object capabilities and current condition
Actor inventory and both hand states
Selected target
Supported physical operations
Current action state
Game mode and permissions
```

It should return a stable action ID, readable label, default priority, hand requirements, required inputs, enabled/blocked state, reason, and the supported execution program.

**The browser, chat, and API must receive the same answer.** Do not duplicate availability rules in JavaScript, Python prompts, and native code.

### Provide useful defaults by capability

| Capability                        | Default experience                                                              |
| --------------------------------- | ------------------------------------------------------------------------------- |
| Tool point over supported soil    | **Dig here:** swing, lever, withdraw, and report the accepted result.           |
| Bow with compatible ammunition    | **Draw / release:** handle loading and grip setup automatically.                |
| Hinged gate                       | **Open / close:** move toward the appropriate stop using the bounded hand.      |
| Winch connected to a gate         | **Raise / lower:** operate its actual mechanism and report what moved.          |
| Ordinary portable prop            | **Place** or **stow**, with throw under a deliberate secondary choice.          |
| Supported cutting edge and target | **Cut here:** perform a bounded stroke without requiring a fast camera gesture. |

These are interaction conveniences, not success guarantees. "Dig here" can return that the ground stopped the tool. "Open" can stop because the gate hits its post.

For an unfamiliar object, fall back to inspection and generic physical manipulation. Do not invent "Sit," "Drink," or "Smelt" merely because the object has a suggestive name.

### Use meaningful labels and stable semantics

Prefer **"Open gate"** over "Turn it all the way."

For continuously rotating wheels, distinguish **"Turn another 90°"** from **"Move to 90°."** The former is relative; the latter is an absolute target. Do not label half a revolution "fully" unless the mechanism has a meaningful corresponding endpoint.

Deduplicate actions by their semantic IDs, not by whether their English labels happen to match.

### Let the LLM author capabilities, not run every interaction

The LLM can propose a profile or compose a supported action program when creating something. Validate and store that declaration.

Afterwards, basic use must work without another model call. Grip selection, target checks, hand reservation, action availability, and routine execution should be deterministic.

---

## 5. Make ghost placement the normal way to put things down

**Place** should enter a dedicated preview mode.

Show a translucent copy of the complete item or assembly at the proposed destination. The real object remains equipped or stowed until the placement is accepted.

Choose sensible defaults: a stool upright on its feet, a plank flat, and a cup on its base. Use declared support surfaces or validated geometry, not the object's name alone.

In preview mode, expose simple rotation and surface snapping. Put pitch, roll, exact angles, and local/world axes under **Precise placement**. The existing six rotation keys should remain available for expert manipulation, not be required for setting down a cup.

### Validate what matters

The preview should indicate:

**Fits here; collides; out of reach; insufficient support; or requires a capability the player does not have.**

Use text or icons as well as colour. Distinguish **"the geometry fits"** from **"tested to remain stable"**—a collision-free pose is not proof that a top-heavy object will stand.

Validate the whole assembly, including its actual shape and attachments. Preserve its local geometry and relative part transforms.

This matters particularly because the latest development notes document joined-part problems at certain grid offsets, including missing material. **Inventory and placement must not rebuild an item at a new position in a way that changes its mass or loses parts.**

### Preview must not mutate the world

Moving or rotating the ghost must not spend inventory, push objects, reset a mechanism, or advance an experimental test.

Use a cheap local display preview and authoritative validation. Tag responses with the placement request revision so an old response cannot approve a newer pose.

On confirmation, revalidate against the current world. A support may have moved since the preview was generated.

For an item in the hand, execute the placement through supported bounded handling, then release it. For a stowed item, validate the equip/extraction and placement sequence. Do not teleport an object through a wall because its destination is clear.

**Creative placement and physical placement can differ, but they must be explicitly different modes.** An editor may permit direct transforms; normal physical interaction must not silently gain those powers.

---

## 6. Make assistance helpful without becoming surprising

Use **Assisted** as the default, with **Manual manipulation** available per object or action.

Assisted mode should automatically choose a grip, orient a tool for its declared operation, select compatible available ammunition, reserve required hands, choose a reasonable placement orientation, and execute short validated sequences.

It should not automatically choose a new goal. Looking at something must not shoot, dig, heat, consume resources, or release a mechanism.

The interface should display the next action before the user initiates it. Context and labels should make its consequences understandable; this is also consistent with Microsoft's guidance on predictable UI context and clearly identified functions. ([Microsoft Learn][2])

### Do not turn every action into a confirmation dialogue

Safe, routine preparation can happen within the action the user requested. For example, **"Draw bow"** can select an arrow and stow an eligible cup.

But a pinned item, burning item, or hand maintaining a load must produce an explicit alternative. Never silently discard it.

Also, do not automatically change targets halfway through an action. Lock the selected target for that action and revalidate it; failure should stop with a reason, not redirect the tool somewhere else.

### Cancellation must respect physical progress

Cancelling a ghost should simply remove the ghost.

Cancelling a partly completed physical operation cannot undo elapsed physics. If a digging stroke already removed soil, that soil stays removed. If a bow has been drawn, cancelling should use a supported let-down sequence rather than delete its stored energy.

The winch is an especially important case: **current actions can keep holding the handle because releasing it lets the gate drop.** Preserve that hand reservation and show **"Holding gate up."** Neither Escape, opening inventory, nor an action error should casually release that load.

---

## 7. Make state and persistence trustworthy before calling inventory finished

Implement inventory transfers as validated transactions with object IDs, request IDs, and expected state revisions.

A retry must not collect an object twice. A failed placement must not remove it from inventory. Two callers must not acquire the same item.

**Do not implement pickup by removing an object from the scene recipe, then implement equip by calling `add_object` with its original recipe.** That would lose its evolved state and risk duplication on reload.

Extend persistence beyond the authored room specification. Save item ownership, equipped hands, stowed items, actual object state, and relevant world changes together. Reuse the existing journal rather than creating a second knowledge store.

For the first release, reject storage of states that cannot be faithfully restored. Broader thermal or active-mechanism storage can follow with an explicitly supported simulation policy.

Keep physical primitives—grips, supported movement, object-state transfer—in the native engine and bindings. Keep inventory policy, action selection, and knowledge above the material laws. The browser should display accepted state, not own it.

---

## 8. Deliver this in four integrated increments

| Increment                          | Deliverable                                                                                                            | Main integration points                                                                                     |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| **1. Inventory and hands**         | Stable item identity, stow/equip, two-hand allocation, safe restrictions, and persistence.                             | Native hand/state interfaces; C/Python bindings where needed; `server.py`, `room_store.py`, and room state. |
| **2. One action system and panel** | Shared action resolver, hand cards, object preview, one primary action, consistent inputs, and safe hand reservations. | `mcp/interaction_profiles.py`, `mcp/banjo_mcp.py`, `room_world.py`, `world.js`, `interaction.js`.           |
| **3. Placement**                   | Whole-object ghost, sensible orientation, snapping, validation, cancellation, and accepted placement.                  | A focused placement module plus authoritative preview/commit operations.                                    |
| **4. Assisted workflows**          | Complete bow use, pick swing-and-lever, and gate/winch operation without low-level manipulation.                       | Extend existing programs and profiles; preserve manual control and notebook evidence.                       |

Add tests and persistence coverage with each increment—not at the end. Preserve existing scenes and profiles through migration or compatibility adapters.

Do not make routine inventory, placement, or action discovery depend on the LLM. Do not reopen the entire world for each hand or inventory change.

## Acceptance tests that define "easy to use"

| Scenario                             | Required result                                                                                                                  |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| **Pick up and use a tool**           | One contextual pickup, then the displayed primary action works without chat or grip adjustment.                                  |
| **Bow with an occupied second hand** | The UI explains the requirement and offers a single safe preparation action. No dropped item, extra arrow, or hidden third hand. |
| **Place a stool**                    | It previews upright, rotates as one assembly, and is placed without individual leg manipulation or changed mass.                 |
| **Cancel placement**                 | No inventory debit, movement of the real object, or world-state change.                                                          |
| **Operate the winch**                | Raise and lower work from the action panel; any continued holding is visible and occupies a hand.                                |
| **Heavy installed gate**             | It can be operated where physics permits, while pickup/stowing remains unavailable.                                              |
| **Reload after using items**         | Ownership, damage, equipped state, and placement persist without restoring old copies.                                           |
| **Click a panel or close a menu**    | No accidental swing, throw, shot, or load release.                                                                               |
| **Stale response or network retry**  | No duplicate items, double actions, or placement approved for an obsolete ghost.                                                 |

Add **real browser end-to-end tests** for these flows. The current development notes explicitly say recent crosshair/hinge behavior was tested outside CI because the page lacked JavaScript test coverage; Python handler tests alone will not catch these interaction failures.

Finally, test the basic flows with people who have not read the controls. Record first-attempt completion, unexpected actions, and where they ask for help. Treat "the endpoint returned success" and "a new user could do it" as separate acceptance criteria.

**The experience to aim for is: take it, see what it does, use it, and put it where intended—with the detailed physics still there, but no longer something the user has to operate manually.**

[1]: https://learn.microsoft.com/en-us/xbox/accessibility/xbox-accessibility-guidelines/107 "Xbox Accessibility Guideline 107"
[2]: https://learn.microsoft.com/en-us/xbox/accessibility/xbox-accessibility-guidelines/114 "Xbox Accessibility Guideline 114"
