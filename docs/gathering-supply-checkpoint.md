# Gathering and recursive supply checkpoint — October 1, 2026

Implementation accompanies this checkpoint; the published revision is recorded
after publication. The fourteen-item goal remains active: four verified, nine
partial, durability/repair pending.

## Implemented

- A held gathering tool's primary button invokes its native stroke even if its
  design also declares Study. The displayed primary action agrees. Study remains
  available as an explicit inspection action.
- Ordinary generated-world F uses that same tool stroke. With no tool it explains
  how to take one up, equip one or make one. Debug's bounded raw ground edit remains.
- The World load card offers Find tool and Make tool / Recipes. Find turns toward
  an actual tool and pins its details without moving the player; it reports distance.
- Full native capacity refuses another stroke and explains H heaping for sand/soil.
  The load card retains the visible mass, progress and Inventory link.
- The player inventory report now sums the actual native sand/soil/rock mass and
  the whole held item's mass, then recomputes remaining capacity. It previously
  read a nonexistent `ground_kg` field and omitted the excavated ground.
- Recipe process inputs expand into current raw supplies and equipment, with
  required hopper mass calculated from the declared output/input yield. These
  are estimates, not simulated future production. Expansion detects cycles and
  stops at six levels or 128 expanded nodes per bill-of-material line.

## Measured acceptance

Windows 11, Python 3.13, installed Chrome 1280 × 800 / 1440 × 900. Native runner:
existing MSVC Release build from `a64c1e5`, 50 mm cells and `dt=1/240 s`.
No native material, contact, ground-work or energy law changes.

`tests/gathering_journey_tests.py` is registered as
`banjo_gathering_journey_tests`. CTest passes in 21.62 s. Actual browser input:
no-tool F refuses without excavation; Find preserves position; E takes up the
pick; J and F both run measured native strokes; full capacity starts no stroke;
H deposits the carried sand/soil; F gathers again. Native receipts in the final
run loosen 55.39305, 14.98638 and 7.675 kg with reported ground work of 137.97034,
47.49662 and 103.45806 J. Total load reaches 80 kg, including the 1.925 kg pick.
H leaves zero sand/soil and only the held pick; the next stroke loosens 31.03846 kg.
The browser reports zero JavaScript exceptions, and full/empty screenshots were
reviewed. Timing and placement affect measured stroke outcomes; these values
are one observed run, not fixed yields or calibration.

`banjo_recipe_guidance_tests` now has three cases and passes in 23.20 s. The
browser expands copper inputs and actually opens the ore extraction card in
World, then retains targeted Market navigation and paid Make. The API case
runs a real smelting batch, manually collects remaining hopper stock through
the ordinary API, then verifies the empty-hopper target uses the 0.3 copper
yield and actual raw deposit reserve/equipment. A circular declarative recipe
returns a visible blocked route. This case does not prove automated resupply.

Affected regressions: all 15 native goods/player/browser cases pass (CTest
103.66 s); 17 inventory cases pass (2.591 s), including actual native excavation
and an actor's corrected total/remaining capacity; 20 tool-use cases pass
(4.839 s), including refusal without starting a stroke; nine Workshop tab cases
pass (1.055 s); seven Market cases pass (0.449 s). Native source registration:
286/286, zero exclusions. Python compilation and changed-file whitespace checks
pass. Ignored evidence: `build/resource-flow/gathering-journey.json`,
`gathering-*.png`, `recipe-guidance-ore-source.png` and suite logs.

## Remaining requirements

Items 7 and 8 remain partial. Recipe acceptance still needs an ordinary
process/output-to-build journey and broader saved-design shortage coverage.
The single-player native gathering/capacity/heap loop is verified, but native
excavated ground still uses one shared carry account across players. Personal
goods credits and separate held items do not establish private ground ownership
or physical bag/cargo mass. Next give native ground carrying/depositing an
actor-specific account and test two simultaneous gatherers plus restart and
accounted transfers. Preserve native tool work and terrain mass accounting.

The test observer stands on surveyed ground for repeatability; Find itself does
not teleport. Physical avatar locomotion, bag inertia, full mechanical energy
conservation, calibrated material durability and repair remain separate open
gates. H only returns sand/soil; it does not promise to empty rock or products.

```sh
ctest --test-dir build/agent-progression -C Release -R '^banjo_(gathering_journey|recipe_guidance|world_goods)_tests$' --output-on-failure
python scripts/check-source-registration.py
```
