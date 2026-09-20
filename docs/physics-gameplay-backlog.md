# Physics gameplay implementation backlog

The player capability list is an implementation backlog, not 30 completed
features. The first delivered increment is the shared
[experiment contract and regression lane](physics-trials.md). Build new
features from physical primitives and preserve one authoritative world state.

## Rules for every increment

A product declares geometry, materials, connections, stored state, interaction
points and a bounded primary-use program. The LLM edits these declarations.
The engine determines forces, flow, motion and failure. Human and LLM controls
use the same validator. Construction in a sandbox explicitly supplies initial
resources; survival manufacture must consume inventory, work and time.

Every new operation needs an observable success case, an insufficient-resource
or blocked case, persistence coverage, an API/MCP contract and a native QA
fixture. Use glass, oak and iron for general material claims; introduce other
materials without dropping those comparisons. Add cross-system conservation
checks as the necessary ledgers become executable. A custom experiment passing
its own checks never replaces a fixed regression.

## Player expectations and generic work

| Player capability | Reusable model / remaining acceptance gate |
|---|---|
| 1. Mine and excavate | Terrain/material removal; removed volume becomes collected material and debris with matching mass |
| 2. Cut, drill and shape | Geometry transformation with removed stock, work and tool wear; no free mass on undo |
| 3. Build from parts | Assembly declarations and inventory debit; sandbox bodies exist, physical construction remains |
| 4. Join and separate | Rated connections; first QA now checks strong/weak fixing failure and restart; paid joining and general disassembly remain |
| 5. Support loads | Contact and structural connections; first QA checks raised supports; beam bending, buckling and larger buildings remain |
| 6. Pick up, carry and push | Force-limited interaction; first QA compares equal-volume wood/iron under the same force; player carrying policies remain |
| 7. Use tools | Bounded primary-use programs already exist; expand native contact/work/wear oracles for cutting, striking and prying |
| 8. Store and move cargo | Container interaction points and contact; support checks now exist; moving cargo, payload limits and spills remain |
| 9. Build vehicles | Wheels, axles, suspension, drivetrain and ground reaction; add loaded hill, braking and traction cases |
| 10. Use ropes and lifting machines | Existing native rope/pulley/drum foundations; add shared primitive recipes for load, slack, overload and supported power |
| 11. Divert water | Existing terrain/shallow-water coupling; test dams, channels, displaced water and downstream changes |
| 12. Fill, pour and contain fluids | Material-containing vessels and flow networks; conserve mass/composition/enthalpy through spills and phase changes |
| 13. Light fires and cook | Existing heat/finite reactions; connect arbitrary fuel inventories and heat paths; test extinction and depleted fuel |
| 14. Build shelter and insulation | Thermal networks, enclosure boundaries and weather ingress; finite-room heat balance remains |
| 15. Generate, store and distribute power | Existing circuits/stores/motors; expand network recipes and generation/charging with loss destinations |
| 16. Automate production | Bounded material transformations retaining work in progress; generic machine manufacture remains |
| 17. Sense and control | Reusable physical measurements and bounded actuator commands; add thermostat/pressure/load control loops |
| 18. Forge, cast and process | Work/heat/material-state transformations; finite inventories and real intermediate states |
| 19. Repair and maintain | Resource/work/time changes to physical state; no resetting temperature, damage or pressure on edit |
| 20. Dismantle and salvage | Recover actual retained materials and connections; account for unrecoverable waste |
| 21. Survive surroundings | Explicit temperature, exposure and hazard models; avoid hidden damage unrelated to measured conditions |
| 22. Grow and harvest | Bounded biomass/water/nutrient/light model if selected; not implemented by these trials |
| 23. Measure and experiment | First increment: editable experiments, native playback and numerical checks; more sensor types remain |
| 24. Diagnose failures | Native connection failure reasons and measured comparisons now visible; full energy/material causal tracing remains |
| 25. Save and reuse designs | Preserve construction and operating state separately; parameter changes must revalidate limits and compatibility |
| 26. Ask the LLM to build/change | First increment: validated recipe editing over generic primitives; arbitrary product compilation remains |
| 27. Leave and return | First QA checks moving bodies and broken/attached fixing persistence; coupled heat, contents and damage need expanded gates |
| 28. Cooperate in one world | Authoritative ordered actions, ownership and shared budgets; multiplayer synchronization remains |
| 29. Run a creative lab | Isolated native experiments now available; distinguish externally supplied initial conditions from physical manufacture |
| 30. Build at world scale | Active-region budgets, sleeping, state-preserving refinement and catch-up; true lazy per-brick detail remains planned |

## Next connected increments

1. Material-funded shaping and assembly: excavate stock, form/cut a part,
   account for offcuts and work, join it, load it, dismantle it. Reuse the
   existing catalog, ProductGraph and interaction points; never infer laws
   from a named game feature.
2. Moving cargo and lifting: wheel/axle/rope primitives with force-limited
   input, payload and mount reactions, slope/overload tests and restart.
3. Electrical–mechanical–thermal operation: finite supply, wire/switch/fuse,
   motor, ratio/load and heat network; shared-supply, stall, open-wire,
   depleted-store and thermal failure tests.
4. Containers and production: material/energy ports, vessels, flow, phase
   changes and interrupted work, then sensing and automation.

Each increment adds examples to the lab and stable native gates to CI. It does
not require inventing a dedicated cart, door, furnace or factory simulation.
