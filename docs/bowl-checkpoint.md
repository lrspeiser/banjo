# Craft-and-release bowl lab

**Fracture component:** [Energy-accounted rupture](energy-rupture-checkpoint.md) now combines accepted elastic/contact motion with a transactional tensile break, explicit Gc-area work and a separate event-overshoot budget. Low/high glass impact cases and matched glass/oak/iron reference experiments pass; five affected suites pass, plus the new legacy test. Local `6b44c2f`. Whole-ball geometry, event convergence and live bowl fragment handoff remain unfinished; fracture is still disabled in the bowl.


September 5, 2026. Local source commit `c717509` on codex/physics-foundation; not on main. The complete bowl milestone remains unfinished.

## Owner acceptance gate

Craft glass, oak and iron balls from collected inventory. Place them in a concave bowl, release them and observe contact-driven rolling, collisions and rebound. Sufficiently loaded objects with a supported brittle law must fracture from material/geometry/state and available work; other objects remain intact or rebound according to their implemented laws. Adjust the bowl surface and tilt, repeat under declared conditions and export evidence. Finish this demonstration before advancing to another physics family. Retain the first-person world, experience/levels, gathering tools, energy economy and LLM-backed creation application as the eventual host.

## Implemented now

A separate `banjo_bowl` application uses the existing CreatorWorld compiler, material lots, requirements and allocation ledger. Collect 10 kg each of glass/oak/iron, craft up to nine 45 mm radius balls, then release or pause. The first three positions are near the center; the next six are near the rim. Each creation requires held material and publishes only after candidate construction succeeds. Inventory never credits reset/release operations. Three same-size balls consume approximately 2.86278 kg glass, 0.80158 kg oak or 9.01202 kg iron. The app shows each ball's required mass and disables unavailable recipes.

The bowl is the explicit parabolic surface y = depth*(x*x+z*z)/radius^2, rotated around Z. Defaults: radius 1.2 m, depth 0.55 m, 24 rings, 96 sectors, 4512 upward-facing triangles. Jolt and raylib consume the same triangle vertices. The interface selects concrete/glass/oak/iron contact properties and tilt from -20 to +20 degrees in 5-degree increments. Changes reset placement and initial energy; they are authoring operations, not a moving-support simulation. Runtime advances at 1/240 s with no repeated spin assignment or scripted outcome.

The native workspace is `build/bowl-play`; old starter/workshop saves are untouched. `stock.json` retains actual collected lots, crafted objects and allocation history. Restart resets the experiment to the default bowl and placement. `experiment.json` exports bowl settings, time, body position/velocities, initial/current mechanical energy, callback count and stock. It is evidence, not a portable contact-cache replay checkpoint. The stock's staging poses are separate from the bowl trajectory; its internal staging world is not advanced.

## Verification

Windows 11 / MSVC Release / Jolt 5.6 double positions / raylib 6 / RTX 5090. The bowl, creator and reversible-trial suites also pass in the legacy float-position build (3.25 s). Seven affected promoted suites pass: bowl, creator, reversible trials, runtime tensile contacts, contact ownership, pair impulses and runtime dynamics (7.91 s). The new bowl test passes geometry winding/bounds, resource rejection, three-material crafting and immutable stock, gravity-induced motion, peak contact-driven spin, analytical sphere inertia at this radius, restart allocations and six-ball support/contact cases. The preview placement bug found through normal UI input is fixed and covered by the shared next-recipe assessment test.

Eight additional six-ball experiments cover all four surfaces at 0 and 10 degrees, 480 ticks each. Every ball has finite velocity and remains above the bounded support floor; stock is unchanged. Initial/final mechanical energies (J):

| Surface | Tilt | Initial | At 2 seconds | Ball contact callbacks |
|---|---:|---:|---:|---:|
| Concrete | 0 | 19.26044 | 5.93687 | 8 |
| Concrete | 10 | 17.73222 | 3.36867 | 14 |
| Glass | 0 | 19.26044 | 4.42644 | 11 |
| Glass | 10 | 17.73222 | 4.30734 | 12 |
| Oak | 0 | 19.26044 | 4.90897 | 12 |
| Oak | 10 | 17.73222 | 4.71980 | 11 |
| Iron | 0 | 19.26044 | 3.81741 | 12 |
| Iron | 10 | 17.73222 | 3.34684 | 13 |

These are measured state quantities, not a closed dissipation ledger or calibrated surface ranking. Callbacks may be speculative and exclude supports. Equal geometry means different material masses; all three substances remain in every mixed experiment. Broader timesteps, surface resolution, rebound-law accuracy and reaction/work accounting are still required.

Normal native input verified collecting all three materials, crafting two balls each, inventory debits, release/pause at 5.10 simulated seconds, export, +5-degree tilt/reset and glass surface selection. Restart retained the six balls and stock. Capture verified the final enlarged viewport. The running app is staged with these six balls ready to release.

## Explicit remaining work

1. Connect actual collision loading to an energy-accounted material activation/failure/handoff path. Current lab explicitly reports `fracture_supported:false`; all balls use rigid contact. Do not use the old defective fracture path as evidence of realistic shattering and do not add precut chunks or launch impulses. Preserve no-break and break cases, Gc-area work, momentum, angular momentum, fragment mass/inertia and successive impacts. Include glass, oak and iron under the same declared conditions; unsupported wood grain/plasticity stays explicit.
2. Retain surface reactions/contact work and verify mesh/timestep/rebound convergence. The plane-only rolling-resistance approximation is intentionally not applied to curved supports. Present energy differences as losses plus numerical error until separated.
3. Expose ball placement/size and release height through inspectable recipes; add revision-bound test/export and first-person table/LLM integration. The new executable is a focused lab using the shared compiler, not yet a scene in the starter world.
4. Connect gathering/crafting work to the game energy/level contract. Fabrication energy is currently unsupported (null), not free physical work. The lab uses its own collected inventory and does not migrate or duplicate the player's existing starter inventory.
5. Persist experiment setup/trajectory with explicit compatibility and crash-safe save handling; current restart preserves stock only and resets setup.

The API credential pasted in chat was not copied, stored, committed or used. A replacement should be provided through a local secret mechanism for future LLM integration.
