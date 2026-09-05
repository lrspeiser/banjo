# Bounded isolated assembly test API

Local source `9ddcc4e32e3387107d098dcd17e09fdd8f9b214b`, September 5, 2026; not pushed or merged. Full goal active.

`test_assembly` uses the exact version-1 declaration accepted by `assess_assembly`; both now share the same compiler. The isolated fixture initializes the two at-rest compiled boxes with equal/opposite normal separating motion at a specified relative kinetic energy, then advances the distributed cohesive solver. It changes no live inventory, objects or clock and does not require inventory to be sufficient for this virtual test.

Command fields are exactly type, assembly and test. Test fields are test_version (1), relative_kinetic_energy_j, duration_s, energy_error_budget_j, state_error_tolerance, maximum_evaluations and minimum_separated_area_fraction. Input energy must be positive and at most 10000 J; resulting speed at most 10000 m/s. Duration and solver controls retain the adaptive limits (duration at most 1 s, positive energy budget, state tolerance at most 0.1, maximum 65536 evaluations and 256 sites). Requested numerical energy budget may not exceed 1% of input kinetic energy. Minimum separated-area fraction must lie in [0,1]. Work is bounded by evaluation/site/depth limits, not a guaranteed wall time.

The response retains declaration/specification and reports passed/failed from measured separated area divided by total geometric area. It includes initial/final kinetic energy, interface stored energy, damage work, numerical residual, accumulated absolute energy error, evaluation/accepted-step counts, both final body states and each site's opening/history/damage. There is no trajectory trace or saved job. Unsupported geometry or budget exhaustion yields the command's structured ok=false error, not a measured failed or passed test. Passing only establishes the requested separation fraction for this virtual fixture.

## Verification

All three reference materials use 0.02/0.03 m cubes, a 0.001 m gap, 0.00012 m2 centered face patch and 16 sites. Tests use initial energy 0.1 or 6 times A*Gc. High-energy duration is 8*failure_opening/initial_speed; low-energy duration is 0.5*failure_opening/initial_speed. Energy budget is A*Gc*1e-6 J and state tolerance 1e-5. All require fully separated area to pass: the three low cases report failed and the three high cases passed.

An exploratory low-energy iron run over the longer high-case interval reached unsupported coincident-point geometry after closing. That long case remains a rejection regression; the short low-energy fixture is declared explicitly rather than claiming the long simulation completed. The law and numerical tolerances were not altered to make it pass. Every material also rejects a three-evaluation work budget. Serialized live state is identical before/after completed, exhausted and unsupported tests.

An 18-command CLI run reproduces three measured passes and three measured failures, with inspect before/after every test. All six pairs of inspect results are identical. Exported commands and response JSON can be replayed with `banjo_creator_cli --commands COMMANDS.json`. Assessment regressions also remain passing after compiler extraction.

Full Windows MSVC 19.44 x64 Release build and all 21 CTest suites pass in 18.11 seconds. Environment remains CMake 4.1.2/Core Ultra 9 285K. The owned starter was intentionally stopped for relinking and restarted. No native assembly UI or real LLM assembly round trip is claimed.

This is the first public isolated assembly test, not live assembly creation, durable jobs or automatic LLM revisions. Gravity, external collision routing, general contact, shear/friction and calibrated cutting remain unsupported. Spatial damage-front convergence remains open. Next: connect inspectable assembly/test evidence to the creator conversation, then authoritative contact routing and material/energy-aware durable creation. All 40 scorecard rows and remaining goal gates stay active.
