# Knowledge and progression: a capability graph with a technology tree on top

**Status:** design recorded 2026-09-13 on branch `agent/progression`. Increment 1
(the physics: a tool's point, a swing, and what the ground does about it) is
described in [ground work](ground-work.md) and measured in section 7 below.
Increments 2 to 5 are plans, not claims: each moves to the
[development status](development-status.md) only with its own tests, a check in
the playground in 3D and green CI.

The rule this whole design serves is the owner's:

> **Knowledge determines which plans the player can understand and reproduce.
> Resources and equipment determine what they can manufacture. Physics
> determines what the finished object can do.**

Nothing in the knowledge or progression layer can reach the engine. The engine
has no input for what a player knows, so a swing is the same swing whatever
the notebook says -- that is measured, not asserted (section 7).

---

## 1. The source: the owner's concept (verbatim)

The owner's request, 2026-09-13: "add a sub agent to begin working on this
concept:"

---

**Yes—designs should be central, but I would make the underlying system a "knowledge and capability graph," with a technology-tree view on top.** The player learns how to make components, combine them, and use processes. Those capabilities open new possibilities, while the physics determines whether the resulting objects actually work.

For Banjo, the rule should be:

> **Knowledge determines which plans the player can understand and reproduce. Resources and equipment determine what they can manufacture. Physics determines what the finished object can do.**

Learning "stoneworking" must not magically make an existing wooden pickaxe stronger.

I checked the relevant code on `main` at **`a63fa77c4c27`**. Your older `StarterWorld` already has designs with recipes, level requirements, and stamina costs, while your newer interaction-profile system validates how an assembled object is operated. Those are useful foundations, but I would generalize them rather than make the technology tree another hard-coded list of levels and items.

### 1. Put progression above the physics—not inside its laws

I would separate the framework into four layers:

| Layer | What it owns | What it must not decide |
|---|---|---|
| **Physics engine** | Materials, geometry, forces, heat, work, deformation, fracture, and actual outcomes. | Whether a player has unlocked a technology. |
| **Manufacturing system** | Supported processes, material inputs, workpieces, equipment, energy delivery, waste, and completion. | Whether an unsupported transformation becomes possible because the player gained experience. |
| **Knowledge and progression system** | Learned techniques, discovered designs, experimental evidence, shared knowledge, and available next steps. | Material strength, arbitrary mining damage, or fabricated test results. |
| **LLM guide** | Explaining requirements, suggesting experiments, proposing designs, and helping the player choose a route. | Awarding itself discoveries, inventing resources, or declaring that a tool succeeded. |

This lets you publish different kinds of worlds using the same engine. A survival world can require learning and manufacturing. A creative world can reveal all designs. An educational world can emphasize experiments. **The same physical object behaves the same way in all three.**

Your existing energy-system proposal already separates gameplay progression from physical manufacturing and requires the LLM to work through supported processes and resource checks. This would extend that architecture to knowledge.

### 2. What a "design" should contain

**A design should describe an object, a way to manufacture it, and a way to check its intended function.** It should not just say "three wood plus two sticks makes a pickaxe."

I would give each design these sections:

| Design section | Example for a handled digging tool |
|---|---|
| **Purpose** | Loosen a specified class of ground using hand-driven impacts and levering. This is an intended function, not a guaranteed ability. |
| **Physical construction** | Handle, head, attachment, geometry, material assignments, and local attachment frames. |
| **Component requirements** | A handle of suitable dimensions; a head with the required shape; a compatible connection. |
| **Manufacturing routes** | Make it from one suitable piece, or make separate parts and join them. |
| **Knowledge requirements** | Relevant shaping or joining techniques for the selected route. |
| **Process requirements** | Supported tools, fixtures, materials, energy sources, and operating conditions. |
| **Interaction profile** | Where it is held, how it is swung or levered, and what measurements the player sees. |
| **Tests and evidence** | What it has successfully done, under which conditions, using which version of the physics model. |

A design can be parametric. The player might change the handle length, head shape, or connection. That creates a new design revision, and relevant performance claims need to be checked again.

**Does the player need to know how to build every component? Only the components they are actually manufacturing.** Suppose a pick requires a handle, a head, and a connection:
* Finding a finished head should bypass the need to know how to manufacture that head.
* Making the head from raw stock should require a supported process and the knowledge to use it.
* Assembling the tool should require the relevant joining technique.
* Using a found, complete tool should not require knowing its manufacturing history.

That distinction creates much more interesting progression than requiring every player to traverse every earlier node. A player who finds a metal pick head can learn to fit a handle without first discovering mining, ore processing, and metallurgy.

**Use requirements, not exact ingredient names.** For interchangeable components, specify dimensions, interfaces, material classes, and relevant properties. Do not require an object named exactly `"oak_handle_v1"` when another suitable handle would work. Luanti's recipe system illustrates the useful general idea: recipes can accept members of a group rather than one exact named item (https://api.luanti.org/groups/). For Banjo, I would extend that approach with geometry, physical state, and interface checks instead of treating a category tag as proof of physical suitability.

### 3. Build knowledge from techniques, designs, and evidence

**Techniques: "I know how to do this."** Examples include selecting stock, shaping a point, fitting a handle, making a particular joint, operating a furnace, and recognizing when a workpiece has reached a required condition. These are reusable across designs. Learning to fit a handle should help with multiple tools rather than unlocking only one pickaxe recipe.

**Designs: "I know how this object is constructed."** A design is a reproducible plan composed from techniques and components. Knowing a design does not mean the player currently has its materials or equipment. The interface might say "**Design known. Construction blocked: no supported way to make the head.**" That is different from "**Design known and manufacturable. Missing one suitable handle.**"

**Evidence: "I have reason to believe this works."** Record observations separately from general knowledge: "This prototype loosened this soil sample." That is not equivalent to "Wooden pickaxes can mine every rock." Each experimental record should identify the design revision, tool condition, target material and state, action performed, measured result, and applicable model limitations. A useful progression is **proposed → instructions acquired → built → demonstrated for a stated use**. These should not be mandatory sequential achievements: a player can learn instructions from a teacher before experimenting, or invent a working object before knowing its conventional name. **Do not require repeated crafting just to fill a knowledge bar.** Reward a new capability, a meaningful comparison, or a reproducible improvement. Repeating an identical result can confirm evidence without continually granting the same discovery.

**Knowledge should survive objects.** Breaking a tool should not erase its blueprint. Losing a blueprint might remove access to detailed instructions in a particular game mode, but that is a gameplay policy—not a physics effect. For shared worlds, support both personal notebooks and shared libraries. A village can retain a design discovered by one player, while individual practice or access permissions remain separate.

### 4. The "tree" should allow alternative routes

I would use explicit **all-of** and **any-of** requirements. For example:

```text
Make a handled digging tool
    requires:
        a usable handle
        a usable head
        a compatible connection
    obtain a handle by:
        finding suitable stock
        OR manufacturing one using a known shaping process
    obtain a head by:
        finding a suitable finished piece
        OR manufacturing one using a supported process
    connect them by:
        a known, supported joining method
```

A one-piece wooden design is another route that avoids the connection entirely. This allows discoveries to combine naturally. Handle-making plus a suitable head plus a joining method can make several tools possible. The engine does not need a separate arbitrary unlock for every combination.

For the first release, I would provide **a curated starting graph with room for player inventions**. The LLM may propose a new design using existing components and supported processes, but it may not invent a new material law or manufacturing operation to make its plan succeed. Also validate the starting graph for circular dependencies. A player must not need a pickaxe to obtain the only material capable of making their first pickaxe.

### 5. Your example: Wood → wooden pickaxe → mining

I would make this the first end-to-end progression scenario.

**Step 1: Start with accessible materials and basic actions.** Give the starting area fallen wood, suitable naturally shaped branches, and a reachable patch of loose ground. Include whatever primitive shaping aid the starter process actually requires. The player should be able to collect loose material without first needing a tool made from inaccessible resources. Do not require punching a standing tree unless that is explicitly a fictional rule of the world. For the very first wooden pick, **I would use a one-piece design made from a suitable forked or angled piece of wood**. That avoids making the player learn bindings and head attachment before they can try anything. An assembled version can follow. The guide might say: "This branch has a long section you can hold and a shorter arm that could become a digging point. We can try a simple wooden pick without attaching a separate head." The knowledge gained here is modest: the player has identified a possible stock shape and a candidate design—not proven a mining capability.

**Step 2: Learn the simplest relevant process.** Provide a starter lesson for a declared rough-shaping process. Its requirements must be real within the simulation: stock, a supported shaping method, and a source of work. This is where the manufacturing system from our previous discussion enters. The engine should quote the inputs, expected leftovers, required process, and estimated work. Manufacturing then changes a workpiece as the process receives energy. The current energy-system document still describes this fabrication layer as a proposed capability. So the prototype should implement one supported process—not disguise `add_object` as energy-aware crafting. A reduced-order shaping model is acceptable initially. It should be labeled, versioned, and account for retained wood and removed material. You do not need to simulate every abrasive grain to establish the progression framework.

**Step 3: Construct an actual tool and give it usable controls.** The completed wooden pick should have its actual geometry, mass distribution, material, grip, and current condition. Attach a reusable **swing-and-lever interaction profile**. The player chooses where to work and performs a simple action; the engine drives a bounded physical motion. Do not make them manipulate every joint individually. Your existing profile framework already separates controls from physical outcomes, but its shared template registry currently contains only `draw-and-release`. Swinging, levering, and tool use should become additional reusable profiles rather than a pickaxe-specific browser script. The tool's intended purpose can be "digging." Its physical capability must still be measured.

**Step 4: Try it on a deliberately suitable ground sample.** For the first scenario, choose a declared soil model and tool geometry that tests establish can interact usefully. The player strikes, scrapes, or levers the ground. The engine computes the work, reaction forces, tool motion, and resulting material displacement. **This requires a new physical excavation connection.** The current terrain interface exposes `dig()` and `cut()` as host edits with geometric arguments; those calls do not accept a tool, its applied work, or a contact history. They are useful terrain operations, but they do not establish tool-driven mining. The implementation should therefore add a tool–terrain process that determines what material can be displaced, and only then commits the corresponding terrain change. A mouse click must not simply call "delete a fixed amount of ground because the held object is a pickaxe". It should request something like "perform a bounded tool action against this patch of material". The physical/process model determines the result.

**Step 5: Turn the result into a bounded discovery.** After a successful trial, the progression system receives an accepted result from the engine. The notebook could record: "**Demonstrated: this wooden digging pick loosens the tested soil.** Head and handle remained usable. Tool condition and recovered material recorded." The guide can explain what happened and suggest another test: "It moved this ground without the wooden arm breaking. Try the compacted patch next, or compare it with your bare-hand method." Do not invent numerical measurements in the guide's response. It should use the engine's actual report.

**Step 6: Try a harder target and learn from the limitation.** Let the player attempt the nearby rock. Do not prohibit the swing because "stone mining is locked." The tool might rebound, deform, wear, break, or produce a small amount of material damage. The selected material and contact models determine the result. For a tutorial, choose and validate a comparison in which the harder target exposes a limitation of the prototype. The guide should diagnose the observed limitation: "The wooden point deformed, and the target did not release a useful piece. Changing the head material or shape is a more promising next experiment than repeating the same strike." That is a **conditional example of the desired feedback**, not a claim that the present engine already produces that outcome. Crucially, distinguish a physical failure from an unsupported model. When the engine cannot model a contact regime, report "not supported yet," not "your tool failed" or "you need more research."

**Step 7: Open the next branch from the demonstrated need.** The next opportunity could be **separate heads and handles**, not simply "pickaxe level two." The player now has a reason to learn a joining technique and search for a more suitable head. That reusable knowledge can later support other tools. The first stone component need not be mined from solid bedrock. It can be found loose or obtained through another supported route. Likewise, finding a ready-made component should let the player skip manufacturing it. A longer progression might develop from this: **Useful wooden tool → interchangeable heads → supported stoneworking → improved material collection → suitable heat/process equipment → metalworking.** That is an example curriculum, not a mandatory historical sequence or a guarantee that every branch is currently simulated.

### 6. What the LLM should do

**Use the LLM as a tutor and planner over structured world state—not as the database holding the technology tree.** Give it the player's goal, known techniques, visible designs, inventory, available equipment and power, supported engine capabilities, and recent experimental results. It should return a small next step with its reason: "You can make the handle now. The remaining blocker is a way to attach a separate head. Here is a supported joining lesson and the stock it needs." Or: "You already know this design. The issue is missing material, not missing knowledge." The guide should be able to work backward from a goal and compare alternative routes, but I would start with a deterministic prerequisite resolver rather than ask the LLM to rediscover the entire dependency graph on every turn. Voyager (https://arxiv.org/abs/2305.16291) provides a useful architectural precedent: it separates an automatic curriculum, a reusable skill library, and an iterative loop informed by environment feedback. I would borrow that separation for Banjo, while making your server—not an LLM self-assessment—authoritative for progression awards and physical evidence.

**Keep learning paced without making the guide omniscient.** Offer a hint, a suggested experiment, or full instructions depending on the player's chosen guidance level. The world should define what the guide is allowed to teach directly and what requires a discovery, teacher, document, or experiment. Otherwise an omniscient assistant could reveal every design immediately and make the knowledge system irrelevant. But do not prevent genuine invention. A player-proposed assembly using understood operations should be testable even when it has no prewritten recipe.

### 7. The framework I would provide

I would implement a small, optional progression module alongside the manufacturing system. Start with versioned JSON definitions and durable player/world records; this does not initially require a separate graph database.

| Framework component | Responsibility |
|---|---|
| **Technique registry** | Descriptions, prerequisites, permitted learning sources, and supported process references. |
| **Design registry** | Parametric constructions, component requirements, manufacturing routes, interaction profiles, and test specifications. |
| **Knowledge journal** | What a player or group knows, where it was learned, design revisions, and supporting evidence. |
| **Requirement resolver** | Explain precisely what blocks a goal: knowledge, inputs, equipment, energy, or unsupported physics. |
| **Experiment evaluator** | Convert accepted engine results into scoped observations and progression events. |
| **Curriculum service** | Identify useful, attainable next lessons and experiments for the LLM to explain. |

The proposed API operations would be:

```text
assess_goal(player, goal)
list_learning_opportunities(player)
inspect_design(player, design_id)
propose_design(player, declaration)
quote_manufacture(player, design_revision)
start_manufacture(player, quote_id)
evaluate_experiment(accepted_run_id)
read_knowledge(player)
```

The names are proposals. The important contracts are that queries spend nothing, manufacturing owns resource changes, and experiment evaluation reads trusted results. **Do not expose an unrestricted player-facing `unlock_technology()` command to the LLM.** Knowledge grants should come through validated events or explicitly authorized teaching rules. Keep administrative content creation separate. Also keep previews separate from lived experience. A scratch-world trial can support a design estimate, but it should not silently consume live resources or award the player an achievement for something they never performed.

### 8. The first implementation milestone

I would scope the first release to **one small learning loop**, not a hundred-node tree:

> Collect suitable wood, learn a supported shaping process, manufacture a primitive wooden pick, use it through a physical tool action, record its demonstrated limits, and discover a justified next improvement.

The essential tests are:
- **Physics independence:** changing the player's knowledge alone does not change the outcome of the same tool action.
- **Alternative routes:** a found component can replace manufacturing that component; the starting scenario contains a reachable path without circular prerequisites.
- **Evidence integrity:** failures can teach limitations, repeated events cannot award knowledge twice, and unsupported physics cannot masquerade as an experimental result.
- **Resource integrity:** quotes spend nothing; production preserves material and energy accounting; cancellation and reload retain the actual workpiece.
- **Playground integration:** the player can complete the loop through ordinary controls and LLM guidance, with the same APIs available to external programs.

Keep these checks in regular regression testing, update the public APIs and documentation with each increment, and integrate small tested changes into `main`.

**The progression should be "I learned a reusable way to do something, and that made new designs possible"—not "I reached level five, so wood now breaks stone."** That would make Banjo's technology system reinforce its physics rather than bypass it.

---

## 2. The four layers, in this code

| Layer | Where it lives | What it may call | What can never reach it |
|---|---|---|---|
| **Physics engine** | `src/` (the C++ engine), exposed by the C API (`include/banjo/banjo.h`), the Python binding (`bindings/python/banjo.py`), the line protocol (`tools/live_world_run.cpp`) and the playground | nothing above it | knowledge, levels, unlocks, notebooks. No engine call takes a player, a journal or a technique |
| **Manufacturing** | increment 3: an engine process (a workbench shaping wood) with quote, start, read and cancel; its accounts in the engine | the physics | knowledge: a process runs or does not run on its physical inputs. Whether the player is ALLOWED to start it is asked of the knowledge layer by the host before the call, never by the process |
| **Knowledge and progression** | increment 2: `mcp/progression.py` (registries, journal, resolver, evaluator), `progression/` JSON definitions, the MCP tools and a notebook panel in the page | engine reports, read-only; manufacturing quotes, read-only | the engine's state. It holds references to engine results (a run's id and its report), never copies it may edit |
| **LLM guide** | the playground's chat (`playground/world_chat.py`) over the MCP's tools | the MCP's tools only | the journal's write path. It has read tools and teaching rules; there is no tool that awards anything |

The seam that matters most is the one between the engine and everything above
it, and it is enforced by construction: the engine's API has no parameter a
knowledge state could travel in. Section 7 measures the consequence.

## 3. The data model

Versioned JSON definitions, and durable records per player and per group. No
graph database: the graph is small, curated, and checked when it is loaded.

### 3.1 Techniques -- "I know how to do this"

```json
{"id": "rough-shaping-wood", "version": 1,
 "name": "Rough-shaping wood",
 "describes": "Taking wood off a piece of stock with a supported shaping process until it has a wanted outline",
 "prerequisites": {"all_of": []},
 "learn_from": ["lesson", "teacher", "document", "experiment"],
 "processes": ["shape-wood-v1"]}
```

A technique names the supported processes it lets someone operate. It is
reusable: "fit a handle" serves every handled tool, not one recipe. A technique
is never a property of matter and has no field a physics law could read.

### 3.2 Designs -- "I know how this object is constructed"

A design is a parametric construction with the eight sections the concept asks
for. Requirements are properties, never names:

```json
{"id": "one-piece-wooden-pick", "revision": 1,
 "purpose": {"function": "loosen ground by hand-driven strikes and levering",
             "claim": "intended, not guaranteed"},
 "construction": {"one_piece": true, "material_class": "wood",
                  "parts": [{"role": "handle", "size_m": [0.8, 0.04, 0.04]},
                            {"role": "arm", "size_m": [0.04, 0.28, 0.04], "angle_to_handle_deg": 90}],
                  "tool_point": {"on": "arm", "width_m": 0.04, "thickness_m": 0.04, "angle_deg": 30}},
 "components": [{"role": "stock", "requires": {"material_class": "wood", "shape": "angled",
                                               "long_m": [0.7, 1.0], "arm_m": [0.2, 0.35],
                                               "section_m": [0.03, 0.06], "state": "sound"}}],
 "routes": {"any_of": [
   {"id": "found-whole", "obtain": "the whole tool, found"},
   {"id": "shaped-from-angled-stock",
    "all_of": [{"component": "stock"},
               {"process": "shape-wood-v1", "technique": "rough-shaping-wood",
                "equipment": ["workbench"], "work": "quoted by the process"}]}]},
 "interaction": {"template": "swing-and-lever"},
 "tests": [{"id": "loosens-soil", "action": "swing, then lever", "target": {"ground": "soil"},
            "passes_when": {"loosened_m3": ">0", "tool": "whole"}},
           {"id": "on-rock", "action": "swing", "target": {"ground": "rock"},
            "records": "whatever the engine reports"}]}
```

Changing a parameter makes a new revision; evidence is kept per revision and a
new revision's claims have to be shown again.

### 3.3 Routes: all-of and any-of

Every "how do I get X" is an `any_of` of routes, and every route is an `all_of`
of requirements: a component (itself resolved the same way), a process with its
technique, equipment and inputs, or "found". A found component short-circuits
its own subtree: knowing how a thing was made is never a requirement for using
it. The starting graph is checked when it is loaded:

- **no cycles** (a depth-first walk over requirement edges, refusing any back edge);
- **reachable from the start**: at least one route to the first tool uses only
  what the starting area holds and techniques the start teaches -- "a player must
  not need a pickaxe to obtain the only material capable of making their first
  pickaxe";
- every process a technique names is one the engine supports, and every
  interaction template a design names is registered.

### 3.4 The knowledge journal

Per player, and per group for shared worlds; the two are kept apart (a village
library keeps a design one player found, individual practice stays individual):

```json
{"owner": {"player": "p1"}, "revision": 12,
 "techniques": {"rough-shaping-wood": {"since": "2026-09-13T20:10:00Z", "source": {"kind": "lesson", "id": "starter-lesson-1"}}},
 "designs": {"one-piece-wooden-pick@1": {"level": "instructions", "source": {"kind": "found-example", "object": "wooden pick"}}},
 "evidence": ["ev-3f2a"],
 "events": ["ev-3f2a:demonstrated:loosens-soil"]}
```

A design's standing is one of **proposed**, **instructions acquired**, **built**
and **demonstrated for a stated use** -- flags, not a ladder: any can come first.
Knowledge survives objects: breaking the pick removes nothing here.

### 3.5 Evidence records

```json
{"id": "ev-3f2a", "design": "one-piece-wooden-pick@1", "object": "wooden pick",
 "tool_condition": {"before": {"pieces": 1, "dent_m": 0.0}, "after": {"pieces": 1, "dent_m": 0.0}},
 "target": {"ground": "soil", "state": {"cohesion_pa": 2000, "friction_angle_deg": 30, "wet": false}},
 "action": "swing, then lever", "result": {"loosened_m3": 0.0011, "work_j": 41.2, "depth_m": 0.14},
 "models": ["ground-work-v1", "Jolt 5.6 rigid contact"],
 "limitations": ["the ground is Mohr-Coulomb soil, declared, not calibrated", "no wet soil"],
 "run": "<the engine's own id for the accepted result>",
 "claim": "demonstrated: loosens the tested soil", "scope": "this design revision, this soil"}
```

The claim is scoped to what was tried. An evidence record is only ever made from
an engine result read by its id; a result the engine marked "not supported"
makes no evidence, only a note that the regime is not modelled.

## 4. The API contracts

- **Queries spend nothing.** `read_knowledge`, `assess_goal`, `inspect_design`,
  `list_learning_opportunities` and `quote_manufacture` change no world, no
  journal and no inventory.
- **Manufacturing owns resource changes.** Only `start_manufacture` (and its
  process, as work is delivered) changes stock, workpieces and energy stores.
- **Experiment evaluation reads trusted results.** `evaluate_experiment` takes
  the id of an ACCEPTED engine result and reads the result from the engine's
  own record. It cannot be handed a result to believe.
- **No unlock tool.** Knowledge changes only through validated events (the
  evaluator), teaching rules the world declares (a lesson, a teacher, a
  document), and administrative content creation, which is a separate path the
  LLM does not have.
- **Previews are not lived experience.** A scratch-world trial -- the MCP's
  `interaction` trial -- can inform a design estimate. It spends nothing in the
  live world and earns nothing in a journal.

The engine side of increment 1 (the tool's point, the swing and the ground work)
is exposed through every way in, as every capability is:

| | declare a point on a body | a bounded tool action | what the ground did |
|---|---|---|---|
| C++ | `LiveWorld::toolPoint` | `LiveWorld::strike` | `LiveWorld::groundWork` |
| C API | `banjo_make_tool_point` | `banjo_strike` | `banjo_ground_works` |
| Python | `World.tool_point` | `World.strike` | `World.ground_work` |
| line protocol | `{"op":"tool_point"}` | `{"op":"strike"}` | `{"op":"ground_work"}`, and on every step reply that has news |
| MCP | `tool_point` | `strike` | `ground_work` (and `interaction`'s trial for `swing-and-lever`) |
| page | the pick's profile | click the primary button to swing at the ground under the crosshair; the secondary button levers | the line under the controls and the Carried list |

## 5. The increments

Each ends in something that can be tried in the playground in 3D, built by the
room's own chat.

1. **The physics first.** A found one-piece wooden pick, swung through the new
   reusable `swing-and-lever` profile, against a declared soil patch and a rock,
   in a starter room the chat builds. The engine gains a tool-terrain action:
   the swing's measured contact and a declared, versioned model decide what the
   ground gives up, and only then is it taken out through the existing dig
   path, into the carried account. The tool's own condition is the engine's
   material response; an unmodelled regime says "not supported yet". Measured:
   the same swing gives the same result whatever else is true (physics
   independence), and soil against rock.
2. **Knowledge.** The journal and the experiment evaluator (accepted engine
   results become scoped evidence, with no double awards); the deterministic
   requirement resolver (all-of and any-of, found components bypassing
   manufacture, cycle and reachability checks on the starting graph); MCP
   `read_knowledge`, `assess_goal`, `inspect_design` and
   `list_learning_opportunities`; a notebook panel in the page. The chat uses
   them. There is no unlock tool.
3. **Manufacturing** (the roadmap's review item 9, first milestone). One
   supported shaping process at a workbench: quote, start, read and cancel; work
   delivered by the bounded hand; a persistent workpiece; material and energy
   accounts. The one-piece pick is made from a suitable angled branch, and the
   shaping technique is a knowledge requirement.
4. **Assembled tools.** Separate heads and handles, a joining technique, found
   heads bypassing head-making.
5. **Curriculum and invention.** The curriculum service, and `propose_design`
   for player inventions built from existing components and supported processes.

The order is the owner's. Increment 1 comes first because nothing above the
engine means anything until a tool can do something physical to the ground.

## 6. What is deliberately not here yet

- No levels, experience points or stamina in this layer. The older
  `StarterWorld` keeps its own (gameplay units, not joules), untouched.
- No mining of solid rock: the ground's rock has no fracture law under a point,
  and the engine says so rather than guessing (see [ground work](ground-work.md)).
- No wet ground: no infiltration or pore pressure, so a point into ground under
  water is "not supported yet".

## 7. Measured

Increment 1's numbers are in [ground work](ground-work.md#measured), with the
page check and the regression it passed.
