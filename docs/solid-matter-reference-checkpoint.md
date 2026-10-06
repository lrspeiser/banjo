# Constituent solid reference — October 5, 2026

Source base: main `de2bbabb`, Windows x64, MSVC 17.14 Release,
`banjo-cpu-precise-v1`, serial double CPU. This checkpoint implements a bounded
free-solid reference. **It does not replace game excavation.** The old cube
extraction and host pile paths remain explicitly unqualified in the
[ground audit](ground-matter-audit.md).

## Implemented and tested

`src/fastlattice/SolidMatterPatch.*` builds an initially whole, uniform solid
from exact cubic constituent volumes. Dimensions must be whole multiples of
cell spacing. A 25 cm block at 5 cm spacing contains 125 cells; 25 cm at 4 cm
spacing is refused rather than silently rounded. Each exported cell retains
its source ID/index, grid coordinate, volume, density-derived mass, position
and velocity. Connected components are computed from surviving bonds; they
are not an authored shard distribution. Components may remain large even
after internal damage.

The patch uses the existing isotropic central-bond elastic/strength reference
and serial velocity Verlet integrator. Catalog density, stiffness and strength
drive response. It does not change oak's catalog model to a brittle preset or
implement oak grain, iron plasticity, a calibrated fracture-energy surface,
rate effects or granular/cohesive soil. Removed **stored bond energy** is
reported separately; it must not be called calibrated crack work.

External force pulses keep the same live backend between calls, preserving
motion, damage, dead bonds and physical clock. Forces are finite and bounded
to 100 MN per cell, patches to 1,024 cells and calls to 2,048 substeps. The
timestep defaults to 10% of the initial stability estimate (configuration is
bounded to at most 20%) and at most
the declared maximum; this fixture uses 100 ns. These are resource/numerical
bounds, not material parameters or a claim about an appropriate handheld tool.
Every attempted substep measures signed external work. Positive work cannot
exceed the caller's budget; the first over-budget trial restores motion,
damage, history, load ledger and clock. Negative work does not recharge that
budget. No launch velocities, visual trajectories or fixed hit counts exist
in this module.

## Comparative experiment

All materials: 0.25 m cube, 0.05 m cells, horizon 2, seed 17; initially at rest.
Opposed 400 kN tractions on the central top/bottom cells: 256 then 128 substeps,
100 ns per step, 50 kJ maximum positive work **per pulse**. The preceding 64
unloaded steps do not damage the patch. Both pulses accept their complete time
span in every material. This is a deliberately strong external traction
fixture, **not a finite pickaxe collision or human-strength calibration**.

| Material | Mass kg | Supplied signed work J | Dead bonds | Components | Removed bond energy J | Signed integration error J |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Glass | 39.0625 | 680.291 | 168 | 1 | 16.985 | 0.000454561 |
| Oak | 10.9375 | 1705.68 | 20 | 1 | 475.572 | 0.00717215 |
| Iron | 122.96875 | 37.5512 | 0 | 1 | 0 | 0.000729899 |
| Concrete (existing terrain-rock surrogate) | 37.5 | 780.525 | 264 | 3 | 0.737067 | 0.00000856525 |

Equal force/time does not mean equal work: motion and therefore supplied work
differ with density/stiffness/damage. Iron remains whole under this experiment;
glass and oak acquire internal damage while remaining connected. Concrete
separates. This is not proof of realism for natural stone.

The **free-patch** energy balance includes kinetic/elastic energy, measured
source work, removed stored bond energy and signed numerical integration error.
Residual magnitudes are at most 1.85e-12 J in this run; linear/angular residuals
are below 1e-14 in SI units after recorded kick roundoff. Integration error is
tested separately below 0.01% of supplied work. The external source's opposite
impulse/moment is reported, but a finite holder/tool/source is not simulated.
These results do not close the full-world conservation gate.

Halving dt and doubling step counts preserves component counts and dead-bond
counts in this fixture, and reduces integration error by about fourfold.
Source work changes slightly; topology convergence for other loads and spatial
refinement remain open. Every component's constituent cells are unique and
retain the exact original volume/mass. Nonzero translation/torque tests at an
offset world origin check source impulse, moment and analytic kinetic work for
all four materials. Unloading, zero budget, invalid inputs and incompatible
resolutions are tested without state leakage.

First pulse wall time: approximately 50–80 ms here, including a reversible
snapshot each substep. This is a 125-cell local reference measurement, not a
world-scale, debris-settling, browser-frame or 10-foot excavation benchmark.

## Verification and next integration gate

- `python scripts/check-source-registration.py`: 302/302 sources registered.
- CMake compiles the new module into `banjo_fastlattice` and registers
  `banjo_solid_matter_patch_tests` with CTest.
- Solid patch, existing external-load, Verlet and ground-work CTest targets
  pass on Windows Release. Existing ground-work cases still test their current
  reduced/extraction laws; they do not qualify this as integrated excavation.
- The pickup checkpoint separately passes 10 client and 19 native inventory
  tests, the actual E/Q/retrieve/reload journey and the ordinary click-dig journey.

Exact native commands used:

```powershell
cmake --build build/agent-column-terrain --config Release --target banjo_solid_matter_patch_tests banjo_ground_work_tests banjo_lattice_external_load_tests banjo_lattice_verlet_tests --parallel 4
ctest --test-dir build/agent-column-terrain -C Release --output-on-failure -R 'banjo_(solid_matter_patch|lattice_external_load|lattice_verlet|ground_work)_tests'
python scripts/check-source-registration.py
```

The existing build cache emits test executables in
`build/pickaxe-preview/Release`; CTest resolves that location. New solid tests
run the in-process native CPU module. The three browser journeys use the
unchanged `C:/play/bin` live engine: pickup/reload (11.033 s), ordinary digging
(22.683 s), emulated phone targeting (12.209 s). They leave ignored reports and
screenshots in `build/player-regression`. Client tool/terrain suites pass 39
cases. Page reload aborts outstanding HTTP replies; no browser errors were
recorded. Physical phone and interactive native-lab acceptance are not claimed.

Next: reproduce a selected terrain patch **with neighboring attachment and
retained material history**, couple an actual finite tool/actuator and its
work/reactions, then transfer only genuinely detached cells into collision and
settling. The free traction fixture cannot substitute for these boundaries.
After this is qualified, remove both fixed-count extraction branches, replace
host piles with native settled matter, and retain those same cells through
collection/storage/manufacture. Soil/sand and water require their own laws.

Gameplay acceptance must include an explicitly dimensioned 10 ft (3.048 m)
excavation completed in minutes, repeated green click/touch targets, a stated
work/energy source, bounded per-use latency, collection and reopening. That
timing gate is **not passed yet**. Do not make it pass by granting free work,
weakening the declared material, or measuring the old fixed-hit shortcut.
