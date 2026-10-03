# World realism without a difficult opening

October 3, 2026. Expanded review against published main `0ba1032`, current
source contracts and the ordinary test world on port 8774. The owner's port
8771 was not restarted or changed for this review.
This is a product recommendation, with implementation evidence identified
below. It does not certify new physical laws or close the active owner scope.

**Ordinary player evidence:** the [opening/supply walkthrough](opening-human-supplies-checkpoint.md)
reaches collected wood, a paid useful pick, actual sand gathering and learned
skill, then a paid work table, with process restart retention. It exposed extra
funding clicks, stale selected-design advice and a live-battery race; this
checkpoint simplifies those boundaries. Processing still stops at confusing
machine/skill advice in the observed fresh world. The opening alone does not
qualify the entire tech tree or physical tabletop receiving.

**Subsequent measured progress:** the [exposed-layer/peer checkpoint](exposed-layer-peer-checkpoint.md)
verifies actual sand → soil excavation, private storage/restart and an observer's
material/color/thumbnail updates without reload. It records frame timing and
the full-geometry packet cost. Night recognition and wider hardware/multiplayer
load acceptance remain open; the recommendations below keep their stated scope.

## Recommendation

Use clearly colored, patterned ground cells with sharp material boundaries.
Keep the shape of products recognizable and assembled. Give the player one
useful first tool, a nearby supply route, and one next action. Introduce the
machinery and deeper physics as each becomes useful.

The recommended visual direction is **a readable material landscape with
recognizable assembled products**. Make the terrain visibly editable through
cells and exposed layers. Keep the lamp looking like a lamp and the rover like
a rover. A realistic world can have a deliberately simple visual language.
Its realism should come from consistent consequences: removed ground stays
removed, materials reach the inventory, machines consume actual inputs,
sunlight adds actual energy, and bodies respond to supported forces.

## What currently makes the game feel difficult

These findings concern the reviewed source and isolated test journey; they
are not a claim that every older preview server has the latest checkpoint.

| Friction | Current evidence | Recommended change |
|---|---|---|
| Seeing a material does not explain collecting it | Ground colors describe native material, but the ordinary field pick only gathers supported dry soil/sand; nearby mineral deposits can require a mining rover | Target card must show material, actual yield kind and one supported action or a specific tool requirement |
| A successful dig is several steps from a useful product | Gathered sand is a carried raw load, then requires storage, compatible machine input, heat/work, output collection and paid manufacture | Present one continuous supply path and contextual actions; retain those real transfers underneath |
| The second chapter exposes too many unrelated gates | After the observed pick/table journey, Skills shows 1/10 learned; the furnace needs copper ore while shared guidance leads with a wire prerequisite | Choose a supported, obtainable next batch before recommending a distant technique; separate the actual shortage from later prerequisites |
| Availability labels contradict useful equipment | The selected copper skill says unavailable while its related smelter says equipment present | Distinguish Needs input, Needs power, Needs skill and No compatible machine |
| Some prerequisites are not an obvious physical dependency | `melting-glass` requires `smelting-copper` in the technique catalog | Review each edge: retain a true supply/capability dependency; justify a teaching dependency explicitly or make it an optional recommendation |
| Some opening tasks repeat demonstrated behavior | First-tool gathers with the owned pick, then first-workshop asks for studying/gathering again | Existing personal evidence should satisfy repeated checks; a separate Study task should reveal a new useful capability |
| A work table can feel like a checklist prop | The goal credits an owned unparked surface before placement; a retained tabletop receiving trial is still unqualified | Teach placing and using a surface only after its actual receiving action passes; avoid making it the mandatory first reward in the meantime |
| Controls compete for attention | World chat appears before the target/action area; the next-action card may be below the fold | Put the targeted material and primary action first, then compact inventory/goal; collapse chat when unused |
| Administrative state is exposed as gameplay | Players must understand private stock, carried raw loads, workbench stock, stored charge and wallet credit | Show what is usable here and the next transfer; expose locations and exact accounts on expansion |

The processing observation includes a concrete mixed message: **Learn from a
working machine** → **Stop and report current blockers; never invent supplies
or success** → **Drawing wire first needs: smelting-copper**. That is an agent
instruction shown to a human. A human-facing result should instead name the
actual machine shortage and a reachable supply route. The furnace detail
correctly reports that its copper intake is empty; choosing a usable alternative
must still check current recipe, chamber, inputs, energy and saved observation.

The repository also has a consistency risk to resolve before qualifying that
alternative: `machine_process.py` changes the live routine recipe, while
`machine_witness.machines()` currently resolves the recipe from the original
program declaration. A real alternate batch must bind to its actual live
recipe and durable evidence. This review identifies the issue; it does not
claim that it has been repaired or that merely changing the recipe earns a skill.

The simplicity the owner describes in Minecraft comes from recognizing a
resource, predicting an action and getting useful feedback. Banjo currently
asks people to learn several systems together: material identification,
gathering permissions, private stock, machine inputs, battery energy, currency,
workbench funding, installation grids and skills. Better terrain alone cannot
remove those dependencies. Both the presentation and opening need work.

## 1. Finding materials

Smoothed terrain and product skins can obscure the underlying material cells.
The visible surface, target thumbnail and collection result must agree.
An exposed sand cell should look like sand, show the sand sample, and report
the actual sand quantity gathered. Once excavation exposes soil, all three
should change together. Buried resources must remain unknown until exposed
or discovered by an implemented observation mechanism.

Recommended presentation:

| Surface | What the player sees | Interaction feedback |
|---|---|---|
| Soil | Dark, coarse pattern | Soil thumbnail and available gathering action |
| Sand | Light, fine pattern | Sand thumbnail; newly exposed layer after digging |
| Clay | Distinct warm color and pattern | Clay sample and supported collection route |
| Rock | Gray, angular pattern | Rock sample and required supported equipment |
| Ore | Distinct mineral flecks and pattern | Actual ore sample and mining route |
| Water | Clearly separate surface and shore | Depth/current readings and measured response |

Color should be reinforced by pattern and silhouette, including at night.
Use a small local cell outline at the crosshair, without restoring the old
floating circles and labels. Clicking a product should show component
thumbnails while keeping the assembly usable. Advanced inspection may reveal
its cells, connections and declared laws.

**Current implementation:** the [material checkpoint](readable-world-plan.md)
uses nearest-cell colors and patterns on the existing terrain triangles.
It keeps collider agreement and the default generated terrain's 25 cm columns.
It is not a switch to cubic collision steps. Native collection permissions
are unchanged: a field pick gathers supported dry soil/sand; an ore color
does not make that tool an ore miner.

### Should we use smaller voxels?

First improve the readability of the existing cells. Smaller cells can make
the environment more detailed but also make each material harder to recognize
at walking distance. Terrain columns and manufactured-item lattice resolution
are separate settings; changing one does not fix the other.

For the same dense three-dimensional extent, halving cell length gives eight
times as many cells. A two-dimensional column grid gives four times as many
columns. Sparse runs, adaptive geometry, contacts and solver iterations make
actual memory/frame/physics costs depend on the implementation. These ratios
are geometric estimates, not measured Banjo performance predictions.

Recommended next comparison: identical seeded worlds with current material
cells, stepped render geometry on the same sampling, and finer sampling.
Measure recognition at walking distance, excavation/layer agreement,
day/night readability, frame time, native step time, memory and reload size.
Keep simulation and rendering independent and report any collider mismatch.

### Visual alternatives and the recommended experiment

| Option | Benefit | Tradeoff | Decision |
|---|---|---|---|
| Smooth terrain, sharp material cells | Natural slopes, inexpensive presentation change, current collider agreement | Editable depth is less obvious; a grid texture alone can still feel like painted ground | Keep as the current baseline |
| Visibly stepped terrain at the current 25 cm sampling | Shows removed volumes and material layers; stronger excavation cues | More exposed faces and harder movement at steps; requires matching native contact behavior | Prototype and compare before choosing as default |
| Finer terrain sampling, for example 12.5 cm | More detailed cuts and smaller material features | More storage/work; distant cells become harder to distinguish | Measure only after the baseline and stepped comparison |
| Coarse cubic terrain everywhere | Strongest simple block identity | Coarser cuts, shorelines and placements may conflict with Banjo's intended physical scale | Useful comparison, not the initial recommendation |

Start with current-sized cells, clearly colored faces and exposed vertical
layers. Compare the stepped version on the same seed, camera, lighting and
resource placement. If a stepped visual mesh disagrees with the collider,
label it a presentation experiment and do not ship it as the normal terrain.
Do not add invisible stairs or silently alter contact tolerances to hide the
mismatch. Stepped collision geometry changes are separate physics work.

Use material identity at two scales:

- **Walking distance:** a coherent patch of sand, clay or mineral-bearing rock
  that is recognizable without a label. Tiny checkerboard mixtures should be
  uncommon in the opening area. Resource distribution changes need their own
  generator tests and finite material accounting.
- **Working distance:** local cell boundaries, an exposed-layer face and a
  matching material sample. Show the real mixture when a stroke crosses layers;
  do not promise a pure material from a mixed native removal.

Suggested palette direction: sand pale gold/speckled, soil dark brown/mottled,
clay a warm distinct hue with bands, rock cool gray/fractured, and ore a host
rock containing distinctive inclusions. These are art directions, not material
laws or mining permissions. Preserve pattern and lightness contrast for
color-vision differences; validate dusk/night rather than relying on hue alone.
Water needs a separate shoreline silhouette and visible surface. Object skins
must not conceal whether the selected thing can be picked up, dismantled or
used through an implemented action.

Suggested target card:

| Field | Example |
|---|---|
| Thumbnail / material | Sand |
| Action | Gather with field pick |
| Result | Actual sand received, after the native action |
| Inventory feedback | +1.55 kg, only for the observed saved receipt |
| Unavailable action | Copper ore · Needs mining rover |

The example quantity is from the observed first dig, not a fixed yield per
click. Before digging, show supported material/action and capacity, not a
fabricated guaranteed result. Do not restore the old floating circles/labels
or display unobserved buried ore as if the player can already see it.

## 2. A shorter opening

The first goal should produce something the player immediately uses. Banking
currency and buying a stool teach several administrative steps before the
player understands the world.

The published [personal tool opening](opening-tool-checkpoint.md) is:

1. Collect nearby finite wood into personal supplies.
2. Make a personal field pick with actual stock and workbench energy.
3. Equip it and successfully gather dry soil or sand.

Market purchases and wallet deposits are optional. Physical energy still pays
for manufacture; this distinction must be visible. The player should see a
compact requirement, the exact gap and one action to resolve it. Detailed
kilogram/joule accounting belongs in an expandable build review.

Continue with a useful worktable and a supported processing batch, then a
product that makes gathering, lighting or power more convenient. Introduce one
new concept per chapter. Every required recipe needs an obtainable source,
working processor, funded construction route and useful implemented action.
An unavailable alternative must not block a supported route to the same skill.

### Make the opening a short chain of useful outcomes

The existing tool opening is a good foundation. The next chapters should be
organized around improvements the player wants, with a supply path that has
already passed an ordinary playthrough:

| Chapter | Player action | Immediate payoff | Qualification needed |
|---|---|---|---|
| Gather | Collect finite nearby wood, make/equip pick, dig supported sand/soil | Own working tool, visible terrain edit and material in Inventory | Tool opening observed; broader generation/readability still needed |
| Process | Store the gathered sand, choose a compatible furnace process, load it, run and collect | First useful processed material | Supported native sand-to-glass fixture exists; ordinary opening guidance/evidence still needs qualification |
| Use | Make and use a small supported product, such as a working light | Something visibly improves the camp | Retain the complete item supply quote and actual light/action test; glass alone does not imply a lamp's other components exist |
| Power | Add an obtainable solar design and see collected sunlight bank to its builder | Visible income and less waiting for supported builds | Automatic banking exists; qualify each array's material/component/build path |
| Automate | Give a rover one reachable source-to-machine delivery | Less manual hauling and a visibly filling input | Some routes pass; expand shore/obstacle/recovery acceptance before requiring it |

This is a proposed chapter structure, not five already qualified chapters.
Do not make a light mandatory unless its complete material, electrical,
energy and native installation path is available on the generated map. A
simple useful alternative is preferable to a pretty reward with hidden gates.
Likewise, do not make a work table mandatory until it provides a reliable
receiving or other implemented action that the player needs.

Teach one new concept per chapter. Studying a tool belongs in an optional
inspection lesson unless it changes what the player can actually do. A player
who already performed a supported operation should see that evidence without
another artificial checkpoint. Skills should explain the earned ability and
next useful action; they should not be a page of absent machines.

### Guarantee an achievable start, then preserve player freedom

For newly generated worlds, validate a bounded starter supply graph:

1. An accessible finite wood source and a supported dry gathering target.
2. Enough actual initial or collectible solar energy for the first build,
   without a mandatory Market purchase or wallet deposit.
3. A reachable compatible processor and obtainable inputs for the chosen
   next chapter; account for other machines consuming shared stock/energy.
4. A supported useful output with all its required materials, goods and
   installation checks, not just its headline ingredient.
5. A viable route after interruption, depleted shared sources or another
   player taking the same resource. Reserve per-player supplies only through
   explicit ownership mechanics, or provide finite alternative sources.

A generator may place a finite starter cache and machine deliberately. That
is a world-generation design choice, not evidence that tree cutting or machine
construction exists. Show where supplies come from. For already depleted
worlds, explain the actual alternative, renewable source or exhausted state;
do not silently refill ore or invent inventory to keep the tutorial moving.

The larger tech tree should branch. Copper/wire/electric mechanisms, glass/
lighting, and clay/ceramic construction can be meaningful different pursuits
where their complete capabilities exist. A prerequisite should represent
necessary knowledge or a real supply/capability dependency. A mechanically
unnecessary copper gate before a working glass experiment deserves review.
The final edge change needs progression tests and preservation of existing
players' evidence; this review changes no prerequisites.

**Still needed:** later human processing acceptance, a broader supply
audit and additional supported processing alternatives. The reference AI
completes two opening chains on two terrains; that is not completion of the
whole ten-technique catalog or qualification of model-driven play.

The [reachable gathering checkpoint](reachable-ground-guidance-checkpoint.md)
also fixes a smaller source of friction: recommending ground at the player's
feet, then requiring a backstep. Guidance now prefers an exposed dry column
inside the held tool's actual reach. Ordinary browser gathering completes the
skill and retains the material thumbnail/quantity through Inventory reload.

## 3. One next action, fewer competing instructions

World, Inventory, Goals, Skills, Recipes, Market and AI Guide should agree on
the active goal, exact missing requirement and destination. Goals explain
the sequence; the action happens where it belongs. The player should not have
to discover which page's recommendation is authoritative.

The [shared guidance checkpoint](shared-guidance-checkpoint.md) implements
an authenticated next-action result and exact reviewed workbench readiness.
Recipe geometry is labeled **Shape fits**, rather than implying that a
workbench has supplies. Pending owned work takes priority over starting again.

Default information:

- World: targeted material/product, supported action, tool progress and next action.
- Inventory: product thumbnails, quantities, stored energy and measured rates.
- Recipes: thumbnail, uses, material gap, skill gate and build review.
- Lab: selected design, parts, exact funding/build status and test result.
- Goals: current objective, a short sequence and the next destination.
- Skills: demonstrated evidence, useful unlock and one achievable route.
- Market: wallet, supported offers, actual shortages and optional alternatives.

Source registration, raw IDs, grid budgets, solver caveats and save-format
limitations should be available in diagnostics. A specific refusal should
explain its actionable cause in ordinary terms. Repeated technical startup
notices and unavailable mass readings still deserve cleanup.

### Make each action resolve the nearest real obstacle

An unavailable recipe should offer one specific route, for example **Sand
1.55 / 2 kg → Gather more**, **Input empty → Load your stored sand**, or
**Power needed → Connect battery**. The numbers must come from current
authenticated state and the exact recipe; these are UI examples, not new
fixed recipe amounts. Next-action readiness should consider obtainable input,
compatible processor, actual private/shared ownership, current charge and
supported skill evidence together.

Keep Goals explanatory. It should link to the place where a player acts;
pressing a goal button must not create products or grant mastery. Market is
an optional shortcut or exchange, with the gather/process alternative visible.
Recipes holds building blocks and saved designs. Inventory holds products,
raw supplies and energy. Lab edits only the explicitly selected design/item;
saving a design, manufacturing a product and placing it remain distinct.

The World sidebar priority should be: target thumbnail and action, compact
held/bag inventory, current goal/progress, then expandable chat. Chat can say
"Your furnace has no sand loaded; you have sand in your bag" using the same
facts as the UI. Its answers should distinguish a physical power store from
spendable banked energy, and explain the actually observed bottleneck rather
than speculate about sunlight or mastery.

## Realism and complexity budget

The useful question for each new mechanic is whether the player can predict
its result, see that result and use it to make a decision.

| Mechanic | Player-facing consequence worth keeping | Detail to keep behind inspection |
|---|---|---|
| Finite materials | Excavation changes the world; gathered mass reaches the right owner | Run indices, exact receipt IDs and residuals |
| Material differences | Supported tools work differently; compatible processes produce distinct useful goods | Constitutive inputs, calibration and unsupported laws |
| Power | Solar collection, storage, visible machine demand and automatic bank income | Solver meters, accounting records and wiring diagnostics |
| Temperature | Machine cold/heating/working states; supported process readiness | Thermal field arrays and detailed coefficients |
| Capacity and hauling | Full hopper, real transfer, route obstruction and recovery | Controller horizons, port guards and raw native readings |
| Water and cargo | Bodies sink/float/drift where supported; loads change handling | Buoyancy/drag parameters, reactions and conservation audit |
| Skills | Demonstrated ability and useful unlock | Evidence provenance and unsupported alternative designs |

Do not introduce hunger, dozens of ore grades, mandatory manual bookkeeping,
repetitive study clicks or a separate crafting interface for every machine
while the supported opening is still hard to finish. Fewer well-observed
mechanics can feel more realistic than many declared features with unclear
actions.

Keep interaction feedback brief and interruptible. A fast tool input should
not wait for a long cosmetic spin. Show the saved material transfer and actual
container fill. Cosmetic transfer particles, if used, represent a committed
receipt and do not create fragments, add impulses or certify fracture. A
refused action should show its cause immediately; it must not animate successful
collection. Machine input/output motion must match the actual amounts and
destination, including private output collection.

## 4. Realism that makes a useful difference

Prioritize mechanics the player can predict and observe:

1. **Reliable collection and processing:** finite sources, visible transfers,
   compatible inputs and collectible private outputs.
2. **Hauling:** machines negotiate declared slopes/obstacles and recover
   through native motion. The [close-arrival/recovery checkpoint](rover-close-arrival-checkpoint.md)
   resolves the two retained failures; additional terrain families remain.
3. **Water:** avatars and objects have native contact, buoyancy, drag/current
   and reactions. The existing camera swimming approximation is insufficient.
4. **Cargo:** carried loads change actual mass/inertia and handling, with
   physical receiving geometry and conserved transfers.
5. **Damage and repair:** preserve supported connection failure and original
   condition. Keep replacement distinct from genuine repair. Wear, fatigue
   and blunting must not be claimed until implemented and qualified.

Expose these effects through handling, sound, short progress cues and compact
values. Do not make the player enter constitutive parameters to perform an
ordinary action. Glass, oak and iron must retain their declared differences
under matched experiments; visual resemblance is not material realism.

## 5. LLM-created designs

Use the same bounded authoring and paid-build contracts as built-in recipes:

- Name the intended use and required supported action.
- Declare unit-bearing components/materials, joints, grips and machine bindings.
- Preserve dimensions; assess both Lab and actual installation resolution.
- Derive the material/goods/energy quote from admitted geometry and process.
- Trace every missing input to a supported source or report the exact blocker.
- Test the intended function through ordinary native interaction.
- Save the design separately from manufacturing the player's physical item.
- Reuse the same inventory, ownership, skill evidence and recovery routes.

An LLM can propose, modify and explain these records. Its words cannot create
supplies, prove strength, unlock a technique or substitute for a simulation.
Selected Lab conversations now receive the
[focused draft guidance](selected-project-guidance-checkpoint.md), including
fresh paid quotes after edits. Broader custom/machine and unavailable-source
acceptance, full provider-wait concurrency and functional item tests remain.

## Ordered remaining work

1. Finish material gathering/exposed-layer/reload/peer consistency and measure
   recognition/performance, using the readable cells already published.
2. Extend the observed human tool/table opening and selected-project acceptance, including actual empty
   inputs and unavailable sources across the supported recipe catalog.
3. Qualify additional human/model-driven tech routes and LLM designs through
   ordinary paid actions, private inventories and restart.
4. Broaden the qualified hauling routes, then native avatars/water and physical cargo under
   the [R4/R5 acceptance gates](player-experience-checklist.md#remaining-work).

The full active scope remains material readability, useful opening progression,
shared guidance and broader physical behavior. This review does not resume the
owner-paused R3 repair effort or declare the platform complete.

## Acceptance plan for this recommendation

Separate usability qualification from physical validation. Both matter, and
neither substitutes for the other.

| Check | Proposed gate | Status |
|---|---|---|
| Material recognition | First-time players identify the supported opening materials at working and walking distance without labels; test daylight, dusk and color-vision variants | Not measured; define sample size and error/time threshold before testing |
| Terrain experiment | Same seed/camera/actions compare sharp smooth cells, matching stepped geometry and finer sampling; record frame/native step time, memory, save/reload and collision agreement | Comparison still needed |
| Opening usability | Fresh player reaches a working tool and useful processed product through ordinary controls, no grants/teleports/mandatory purchases; record clicks, time, wrong turns and refusals | Tool/table observed; useful processing continuation not qualified |
| Supply graph | Every recommended built-in or LLM recipe traces each required input to an obtainable source/processor and handles depletion/power loss explicitly | Broader catalog remains open |
| Guidance agreement | World, Inventory, Recipes, Skills, Goals, Market and chat report the same current blocker/destination, including recipe changes and pending work | Shared result exists; alternate process and broader adverse cases remain |
| Multiplayer | Two fresh owners in one world progress independently, contend honestly for shared resources and retain private items/evidence through restart | Some private/peer cases pass; full supply contention/load still needed |
| AI player | Same authenticated actions, paid materials, native results and restart gates as a human; distinguish reflex/controller from actual model-driven play | Reference openings exist; full live-model progression unqualified |
| Physical response | Declared matched experiments with reaction/work/mass/momentum/energy accounts; compare glass, oak and iron for material claims | Existing boundaries only; native avatar/water/cargo and wider hauling remain open |

Suggested usability targets for a playtest are a useful first tool within five
minutes and a clearly useful next product within fifteen, without external
instructions. Those are proposed product targets, not observed timing results
or a reason to shorten physical process time by inventing energy. Record where
waiting is caused by real energy/process limits and where it is caused by UI,
walking, save latency or an unavailable supply.

Prioritize the actual processing dead end first, then material recognition
and the matched terrain experiment. Add deeper native water/cargo behavior
in qualified increments after the core gather → process → make → use loop is
legible. R3 repair stays owner-paused. This documentation update publishes no
terrain geometry, progression law, process fix or new physics validation.

## Review sources and publication scope

- [Material appearance catalog](../playground/material_appearance.js) and
  [terrain shader](../playground/terrain_material.js): current cells, patterns,
  samples and triangle-based surface.
- [Goal chapters](../progression/goals.json),
  [techniques/prerequisites](../progression/techniques.json) and
  [goal evaluation](../playground/goal_chains.py): current sequence and evidence.
- [Shared guidance](../playground/player_guidance.py),
  [process selection](../playground/machine_process.py) and
  [machine witness](../playground/machine_witness.py): current readiness and
  the live-recipe/declaration consistency issue above.
- The linked opening, exposed-layer, sand/glass and hauling checkpoints provide
  their exact experiment conditions, passing checks and retained failures.

Only this review and documentation pointers are part of this publication.
An in-progress input-readiness extraction in `playground/world_goods.py` is
left outside the documentation commit. It has no newly qualified behavior.
Validation for the review: local link targets, changed-file scope, whitespace
and the mandatory source-registration guard. No new physical experiment or
full tech-tree completion is claimed.
