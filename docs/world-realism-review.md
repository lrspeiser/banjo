# A realistic world that is easy to read and play

Reviewed October 3, 2026 against GitHub main `f73c59b0d486ffbdba9db38abbb4ec7b596c2abe` after fetching origin. Source review, existing checkpoint evidence, and ordinary browser observation of the isolated port 8776 preview inform this recommendation. The owner's port 8771 tab displayed Opening the room during inspection; its current gameplay could not be assessed. Existing worlds and servers were not restarted for this review.

## Recommendation

Make terrain visibly editable through colored cells, readable material patches and exposed layers. Keep tools and machines recognizable as assembled products. Make early progress a short sequence of useful outcomes, with one action and one understandable obstacle at a time.

Prototype stepped terrain at the existing **25 cm spacing** before reducing voxel size. Smaller cells add detail, but recognition depends on material contrast, patch size, lighting and truthful interactions. Realism should come from consistent consequences: excavation removes actual material, processing consumes it, useful products work, sunlight provides energy, and supported bodies respond to forces.

This is a design review. Proposed balance, controls and acceptance targets below are not newly implemented or validated behavior. The subsequent [material-column comparison](column-terrain-checkpoint.md) now implements optional 25 cm stepped terrain with matching native collision, void preservation and real tool/private storage/peer/restart evidence. Smooth remains default; movement, hauling, night recognition and frame costs still need qualification. On one map the column mesh has roughly four times the smooth top triangle count, while its material packet stays essentially unchanged.

## 1. What makes Banjo feel harder

Minecraft's official first-day guide proceeds from collected wood to a crafting table and wooden tools, then stone tools and useful lighting. My inference is that the useful pattern for Banjo is a short, repeatable collection/build/use loop with visible upgrades. That inference is a product judgment, not a measured comparison of first-time players. [Official first-day guide](https://www.minecraft.net/en-us/article/how-survive-your-first-day).

Banjo currently adds several layers to that loop:

| Friction | Current evidence | Adjustment |
|---|---|---|
| Ground can look like a continuous surface | The shader gives material cells sharp colors, while the native height-field surface remains triangular | Compare visible steps and layered cuts at the current spacing |
| A visible resource does not imply the held tool can gather it | The ordinary field pick gathers dry soil/sand; ore routes require the mining rover | Before an action, show actual yield and compatible tool; keep these consistent with the simulation |
| There are many transfers before a reward | Carried ground, private storage, machine input, processing output and paid construction are separate accounts | Offer contextual loading/collection and a reviewed supply preparation action; preserve all actual transfers underneath |
| The opening can emphasize prerequisites over benefits | The current second chapter still requires a work surface before a watched batch | Make the next goal a useful result; require a table when a working operation needs it |
| A new player sees much of the catalog immediately | The observed Skills page shows 0/10 learned, mostly unavailable; Recipes mixes starter furniture and advanced machines | Default to achievable next projects; keep the full catalog available |
| Shape, supplies and function are easy to conflate | Recipes shows Materials 100%, Shape Fits, and declared uses; exact power/work review follows | Separate supply availability, build readiness and verified useful behavior |
| Early scale can jump sharply | The observed solar-array recipe asks for 200 kg copper, 81 kg glass and 164.84 kg oak | Design a smaller, lower-output starter collector with a complete supply path |
| Darkness hides distinctions | In the observed night view, the lit sand is legible but surrounding resources are difficult to distinguish | Ensure the starting area can be read at dusk/night and provide an obtainable light early |

The current prototype is easier to test than to learn unaided. A passing automated journey proves a route exists under its declared conditions; it does not prove someone knows which action to take.

### Current progress that should be retained

- The [personal tool route](opening-human-supplies-checkpoint.md) has ordinary browser evidence for finite wood, paid manufacture, numbered equip and actual sand gathering.
- [Processing guidance](processing-guidance-checkpoint.md) binds machine input, recipe and saved observation to the real live process.
- The [Camp light route](camp-light-opening-checkpoint.md) continues through collected processed output, paid construction, placement/use and full restart without purchases.
- [Progression simplification](opening-progression-simplification-checkpoint.md), published in `c0005c5`, removes repeated Study/Gather goals from chapter two and removes the copper prerequisite for learning glass. An actual saved glass experiment is still required.
- [Exposed-layer delivery](exposed-layer-peer-checkpoint.md) verifies sand removal exposing soil, matching peer geometry/material feedback, private storage and restart.

Remaining issues therefore include readability, interaction effort, recipe scale and complete supply coverage. The earlier glass prerequisite and live-recipe mismatch are repaired within those checkpoints; they should not be listed as current defects.

## 2. Terrain: visible voxels, readable patches

### Three independent choices

1. **Appearance:** color, pattern, lighting, face shading and local cell outlines.
2. **Geometry:** smooth slopes versus stepped, volumetric faces and exposed layers.
3. **Resolution:** horizontal terrain spacing and any vertical discretization. Manufactured-item lattice resolution is a separate setting.

Today terrain uses layered material runs under a height field, with 25 cm default columns. Coloring a surface cell does not make it a separate rigid cube or a fully cubic terrain volume. Switching to solid voxel terrain is a larger geometry/collision/storage change than changing the shader.

### Recommended visual contract

| Material | Walking-distance identity | Working-distance identity |
|---|---|---|
| Soil | Dark brown coherent patch | Coarse mottling and visible cut face |
| Sand | Pale gold patch, distinct brightness | Fine speckles, clean layer edge |
| Clay | Distinct warm/purple hue | Bands and smoother dense pattern |
| Rock | Cool gray mass | Angular fracture pattern |
| Ore-bearing rock | Host rock with distinctive inclusions | Recognizable mineral pattern and actual compatible gathering action |
| Water | Clear shore and separate surface | Depth/current and supported interaction |

Use color **and pattern**. Minecraft itself documents distinct ore patterns for people who have difficulty reading colors. [Official accessibility guidance](https://www.minecraft.net/en-us/accessibility).

Resources should form recognizable patches at walking distance. Making every tiny cell a different material produces visual noise. Near the crosshair, show a restrained outline and one sample thumbnail. Cutting should expose the next actual layer and update its identity immediately. Unknown buried resources stay unknown until exposed or discovered through a supported observation.

Keep products assembled. Selecting a lamp or rover shows component thumbnails in the right panel; an optional brief inspection overlay can reveal materials without leaving the object exploded. Object skins should preserve silhouette and material cues at useful contact points.

### Terrain alternatives

| Option | Main benefit | Main cost/risk | Recommendation |
|---|---|---|---|
| Existing smooth geometry with sharp material cells | Lowest implementation risk; current collider agreement | Can resemble painted ground | Baseline for comparison |
| Stepped terrain at 25 cm | Makes excavated volumes and layers obvious | More faces; stepping, wheel contact, shores and placement need matching collision | First prototype |
| Stepped terrain at 12.5 cm | More detailed excavation and silhouettes | More columns/geometry; smaller cells are less legible at distance | Compare after the 25 cm prototype |
| Large blocks everywhere | Strong resource identity and simple construction | Coarse shores and cuts; less suitable for Banjo's small products | Optional comparison |

My preferred direction is **25 cm material cells and clearly exposed layer faces**, with stepped terrain tested before becoming the default. Keep broad geological shapes coherent. Reduce distant visual detail through chunk meshes and level of detail while preserving the authoritative material data and nearby collision agreement.

### Cost of smaller cells

For an unchanged physical extent:

| Cell edge | Cells across a metre | Relative horizontal column count | Relative dense 3D cell count |
|---|---:|---:|---:|
| 50 cm | 2 | 0.25x | 0.125x |
| 25 cm | 4 | 1x | 1x |
| 12.5 cm | 8 | 4x | 8x |

These are geometric ratios, not measured frame-time, cloud-cost or RAM predictions. Banjo's layered columns do not store every vertical cube independently. Contacts, run counts, water resolution, changed-region packets and mesh construction have different costs.

A 12.5 cm experiment must retain the same world size, physical deposits and supply amounts. Leaving the grid dimensions unchanged would shrink the map and invalidate the comparison. If renderer detail changes without physics resolution, label that boundary explicitly. A player must not see a solid ledge that their body or rover falls through.

## 3. Simplify the first fifteen minutes

Organize progression around useful improvements:

```mermaid
flowchart LR
  A[Nearby wood] --> B[Own gathering tool]
  B --> C[Gather sand]
  C --> D[Process and collect glass]
  D --> E[Make and use a light]
  E --> F[Build a small solar collector]
  F --> G[Choose an automation project]
```

This is a proposed teaching path. The light also needs copper, oak and paid energy; each must have an explicit obtainable route. The solar step needs a newly reviewed starter design. The diagram does not imply that sand alone makes a working electrical item.

| Stage | Teach | Visible reward | Current boundary |
|---|---|---|---|
| Gather | Collect, make, equip, use | Own tool; altered ground; inventory increases | Published route exists |
| Process | Load compatible input, power, collect output | First usable glass | Published route exists; simplify transfers and waiting feedback |
| Use | Build and place a useful item | Light visibly improves the camp | Paid Camp light route exists |
| Power | Collection, storage, surplus banking | Measured income and longer operating time | Auto-banking exists; starter design/supply balance still needs qualification |
| Automate | Source, destination and one order | Rover input fills; product becomes collectible | Some hauling routes pass; broader route/physical cargo gates remain |

### Specific progression changes

- **Make the mandatory work table earn its place.** Current goal evaluation can credit the surface before placement. Keep it optional until its required operation has a reliable, qualified receiving/use path, or explicitly teach that operation before requiring it.
- **Offer a small solar collector before the industrial array.** Change actual geometry, area, capacity and output ratings together. Do not reduce consumed mass while retaining a full-sized product. The observed 200 kg copper array belongs later in the progression.
- **Default Recipes to Useful now and Next projects.** Group tools, lighting, power, processing, transport and furniture. Keep saved designs and parts accessible. Put invalid/experimental designs in a clearly labeled design section.
- **Separate the starter and catalog variants.** Personal field pick/Field Pick and Work table/Table coexist. Show one recommended starter with other variants grouped beneath it.
- **Teach skills through successful use.** After a committed action, show earned progress and a short unlock notification, then the next useful ability. Optional Study should add information rather than repeat a completed goal.
- **Review remaining prerequisite edges individually.** Copper to wire has an evident material route; copper knowledge to iron is a teaching choice that needs justification. Do not remove edges automatically or expose unsupported processes as obtainable unlocks.
- **Make Market an optional shortcut.** A new player should have an achievable gather/process route. Energy prices can support choices; prices cannot repair a missing source or nonfunctional recipe.

### A valid starter area

Generate finite nearby wood, a reachable dry gathering patch, sufficient physical energy and an accessible processor for the chosen opening. Ensure all inputs of the first useful product are obtainable. Check the actual path, capacities, processing time and power demand, not just a graph of material names.

For multiplayer, account for shared depletion and machine contention. Clearly identify personal possessions versus shared stores. Provide finite alternatives, deliberate starting allocations or a supported renewable route; do not secretly refill resources. Sunlight renews energy, while current timber and ore supplies remain finite. Energy growth alone does not make every material supply sustainable.

## 4. Fewer decisions, truthful feedback

Aim for **see resource → act → see result → use result**.

| Screen | Default contents | Expand for detail |
|---|---|---|
| World | Target thumbnail, compatible action, brief result, compact inventory, next goal | Components and physical analysis |
| Inventory | Product thumbnails, material quantities, usable energy and actual income rate | Storage locations and transfer history |
| Recipes | Thumbnail, useful function, supplies, actual blocker, primary action | Geometry, complete quote and skill evidence |
| Lab | Explicitly selected item/design, component thumbnails, Save / Make / Test | Dimensions, laws and diagnostics |
| Goals | Current benefit, a short sequence and links to the proper screen | Later chapters and evidence |
| Skills | Current practice, earned ability and useful next unlock | Full tree and provenance |
| Market | Relevant shortage, price and gather/process alternative | All offers and price history |

In the observed World layout, chat sits above target details. Put target/action first, then current progress and inventory; keep chat available in a compact expandable area. Keep the common screen navigation.

The observed Recipes view labels the personal pick Materials 100% while the next action says Get wood. This is not proof of a balance bug: visible supplies can include shared stock while the goal requires personal stock. It is a presentation ambiguity to resolve. Use **Available nearby** and **Ready to make**, distinguish ownership when it matters, and derive the primary action from the exact reviewed quote.

Four observed catalog recipes have disabled Make buttons because of shape/adapter problems: chair, shelf unit, cart and kettle. Buying their missing materials would not solve those refusals. They should not compete with the starter recipes as apparently achievable goals.

The Camp light's observed Uses list says Carry / Place despite the existing qualified light action. Prefer compact capability labels derived from supported behavior, such as Light and Battery, with declared versus tested status available on expansion. A solar panel-shaped block or solid hopper block should remain clearly marked as a shape until the necessary behavior/container walls are authored and admitted.

### Controls and feedback

- Tool inputs should remain responsive; use short contact/audio cues and committed material/count feedback rather than long cosmetic spins.
- Show machine input, Heating / Working / Waiting state, estimated progress when available, and collectible output. A completed batch and a player's collection are distinct events.
- Use one contextual Load input action from owned stock when the player is near a compatible machine. Let the server execute the same authenticated transfers and durable receipts.
- Explain one actual refusal: Wrong tool, Out of reach, Bag full, Input empty, Power low, Needs skill, or Design needs changes. Advanced diagnostics remain expandable.
- Preserve units and real quantities, using consistent rounded display. Exact kilograms/joules remain authoritative; an invented item count must not replace measured mass.

## 5. Realism worth prioritizing

| Priority | Consequence the player can understand | Qualification boundary |
|---|---|---|
| Collection/processing | Material removed here becomes useful stock there | Layer, ownership, capacity, receipt and restart checks |
| Power | Panels collect, machines consume, surplus banks | Actual source/store/work meters; no duplicate credit |
| Hauling | Slope, obstruction and load affect the route | Broader native route/recovery tests; physical cargo remains open |
| Water | Bodies sink, float and drift predictably | Exact compound water has matched glass/oak/iron evidence; human/AI movement is still a camera approximation |
| Damage | A real fixing can fail and retain condition | Supported connection failure is bounded; wear/fatigue and broad repair are not qualified; R3 remains owner-paused |

Introduce these consequences through normal play before asking players to understand their equations. Avoid adding hunger, many ore grades or additional mandatory bookkeeping while the basic supply loop remains difficult.

Physical truth needs its own tests: full reactions/work, mass, momentum and energy; timestep/resolution; glass/oak/iron comparisons for general material claims. Visual effects and passing local ledgers are not full-pipeline conservation. Cosmetic transfer particles may represent saved transfers, but must not create authoritative fragments or add forces.

## 6. LLM-created items and guidance

Use the same authoring and readiness contract as built-in items:

1. State the intended useful action.
2. Choose supported components, laws, joints, grips and machine bindings with units.
3. Preserve intended dimensions and validate Lab plus world installation geometry.
4. Derive all materials, goods, energy and skill requirements from the admitted design.
5. Trace shortages to obtainable sources and actual processors; report any missing capability.
6. Run the intended function through the ordinary simulation/action path.
7. Save the design separately from manufacturing and placing the player's item.
8. Retain ownership, condition, evidence and restart behavior.

For example: Build a button-operated pottery wheel should produce a supported turning assembly, control, power source and functional spin test, or a concrete capability refusal. Adding a wheel-shaped cylinder and saying it works is insufficient.

AI Guide should explain the exact same blocker as the visible UI. AI Actions should propose a bounded action and expose its actual result. Chat should help a player understand choices; the normal loop should remain usable without chat. Model-generated narration never grants materials, skills or physical validation.

## 7. Ordered work and acceptance

1. **Resolve starter presentation friction:** target before chat, consistent readiness/ownership labels, one recommended variant, useful capability badges and separate experimental designs.
2. **Run the terrain comparison:** current smooth cells versus matching 25 cm stepped geometry, then 12.5 cm with the same physical extent/resources. Record day/night recognition, cuts, collision agreement, performance and saves.
3. **Simplify the useful opening:** reduce navigation/transfers, make the table optional or useful, qualify the complete light route without outside instructions, and author a compact starter collector.
4. **Audit the complete supply graph:** every promoted recipe, including LLM designs, must have sources, compatible processing, sufficient power, meaningful function and depletion recovery.
5. **Broaden physical qualification:** hauling routes, native human/AI bodies, water response and physical cargo. Keep the paused repair scope separate.

### Proposed acceptance targets

These are proposed gates, not measurements. Fix the protocol before implementation evaluation.

- Test with 8–12 people unfamiliar with Banjo. Aim for at least 80% correct opening-material recognition within three seconds across controlled day/dusk views; also test patterns without hue cues.
- Aim for an unaided useful first tool within five minutes and a useful processed product within fifteen. Record wrong turns, actions, screens, refusals and energy/process waiting separately.
- Replay two distinct generated terrains and depleted/interrupted scenarios with two independent players. Use ordinary authenticated controls and retain private accounts/evidence through full restart.
- Use the same gather/build/use requirements for AI and human players. Label scripted/reflex results separately from actual model-driven play; no hidden grants or teleports.
- Benchmark identical routes and actions: frame-time percentiles, native step time, memory, mesh counts, packet bytes, save/load time and concurrent players. Select a representative machine and an explicit target frame/step budget before accepting a finer grid. No unmeasured claim of an eightfold runtime cost.

## Evidence and scope

Source anchors: [material catalog](../playground/material_appearance.js), [terrain shader](../playground/terrain_material.js), [World interactions](../playground/world.js), [terrain parameters](../src/terrain/TerrainGenerator.hpp), [goals](../progression/goals.json), [techniques](../progression/techniques.json), [generator supply graph](../playground/world_seed.py), [shared guidance](../playground/player_guidance.py) and [recipe UI](../playground/workshop.js).

Ordinary browser inspection reused fresh preview world `a6ce9c85e2d34ef2864e3b9739cbf682` on port 8776. It observed World, Recipes and Skills without collecting, making, buying or granting anything. Screenshots are local, ignored files under `build/realism-review-current/`: `world-night.png`, `recipes.png` and `skills.png`. Earlier linked checkpoints contain the simulation experiments and exact test conditions; no new simulation or complete tech-tree run was executed for this review.

This update changes documentation only. Validate changed-file scope, local links, whitespace and the mandatory source-registration guard. The review does not close remaining implementation/usability/physics work or resume R3.
