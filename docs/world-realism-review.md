# World realism without a difficult opening

October 3, 2026. Review of the current repository and ordinary player flows.
This is a product recommendation, with implementation evidence identified
below. It does not certify new physical laws or close the active owner scope.

## Recommendation

Use clearly colored, patterned ground cells with sharp material boundaries.
Keep the shape of products recognizable and assembled. Give the player one
useful first tool, a nearby supply route, and one next action. Introduce the
machinery and deeper physics as each becomes useful.

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

**Still needed:** human opening acceptance from loose wood, a broader supply
audit and additional supported processing alternatives. The reference AI
completes two opening chains on two terrains; that is not completion of the
whole ten-technique catalog or qualification of model-driven play.

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
2. Finish human opening and broader selected-project acceptance, including actual empty
   inputs and unavailable sources across the supported recipe catalog.
3. Qualify additional human/model-driven tech routes and LLM designs through
   ordinary paid actions, private inventories and restart.
4. Broaden the qualified hauling routes, then native avatars/water and physical cargo under
   the [R4/R5 acceptance gates](player-experience-checklist.md#remaining-work).

The full active scope remains material readability, useful opening progression,
shared guidance and broader physical behavior. This review does not resume the
owner-paused R3 repair effort or declare the platform complete.
