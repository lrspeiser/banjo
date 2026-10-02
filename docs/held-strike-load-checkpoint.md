# Finite lattice loads — October 2, 2026

## Scope and player behavior

This implements a CPU solver prerequisite for R3. Ordinary player tool use still
targets terrain. A held striker and its fixed constituents still lack complete
hand/joint coupling in the fracture island. Exact rigid solids have no internal
fracture law. **Picking up a pickaxe does not yet enable object destruction.**

The new C++ `LatticeBackend::setExternalForces` accepts world-space newtons in
schedule node order for a finite number of actual substeps. It integrates
velocity before prediction, allowing the existing elastic/plastic/failure laws
to respond. It assigns neither positions nor bond damage. No new shards,
fragment speeds, constitutive presets or contact responses were introduced.

Both CPU implementations share the ordered phase. The external ledger records
requested and actually delivered impulse (N s), angular impulse about the world
origin (kg m²/s), signed kinetic work (J), and loaded elapsed time (s).
The caller must account for the source reaction: this phase does not create a
physical hand or return a reaction to a live actor. It is not exposed through
the browser, LLM tools or C ABI. Running preview 8770 retains the R2 executables.

## Contract

- Loads continue across `run()` calls and expire after their actual substeps.
  Ordinary run stop conditions can stop them earlier.
- Empty forces plus zero substeps cancel. Upload clears forces and ledger;
  cancellation preserves the accumulated ledger.
- Wrong size, nonfinite/unrepresentable force, zero-span nonempty input and
  force on an immovable node refuse. Invalid replacement retains the old load.
  Velocity/work overflow is checked before any loaded velocity is written.
- An enabled fracture energy ceiling gains or loses measured signed external
  work. A depleted ceiling stops with reason 6; zero does not become unlimited.
  The existing zero-input unlimited convention remains.
- CUDA explicitly refuses nonempty loads. No GPU qualification is claimed.
  Existing laws, gravity, damping and contact tolerances are unchanged.

## Matched experiments

Windows x64, VS 2022 / MSVC 17.14.51, Release CPU, `BANJO_BUILD_LAB=OFF`,
separate `build/agent-paid-machine`. Source baseline `e626ef5` plus the
implementation recorded below. All three materials use a 120 mm cube,
40 mm cells, horizon 1, 27 nodes, four constraint iterations, `dt=1e-7 s`
(float: `1.00000001169e-7 s`), world origin (2, 0.6, -1) m. Gravity, support,
damping and sphere/node contacts are off. Loads act for 64 of 128 substeps.
No strength or density is substituted between materials.

| Material | Density kg/m³ | Young's modulus Pa | Total mass kg |
|---|---:|---:|---:|
| Glass | 2500 | 7.0e10 | 4.32 |
| Oak | 700 | 1.2e10 | 1.2096 |
| Iron | 7870 | 2.11e11 | 13.59936 |

The free-node analytical oracle starts with dead bonds; it is not a fracture
simulation. Opposite corners receive (8, -2, 1) and (-3, 4, -2) N.
`run(20)` then `run(108)` applies loads exactly 64 times, with identical CPU
states/ledgers. A further step must not apply an expired load.

| Material / precision | Final momentum minus delivered ledger N s | Angular residual kg m²/s | External work J | Final kinetic minus work J |
|---|---:|---:|---:|---:|
| Glass / double | 2.80424e-19 | 2.39049e-19 | 1.25440e-8 | 2.41537e-22 |
| Oak / double | 1.01997e-18 | 8.08998e-19 | 4.48000e-8 | -1.31025e-21 |
| Iron / double | 7.83648e-19 | 6.67782e-19 | 3.98475e-9 | -6.03842e-23 |
| Glass / float | 2.15551e-10 | 1.80391e-10 | 1.25440e-8 | -1.87535e-13 |
| Oak / float | 7.52645e-10 | 6.43979e-10 | 4.47998e-8 | -5.37139e-13 |
| Iron / float | 4.39981e-11 | 3.16091e-11 | 3.98475e-9 | 1.37544e-14 |

Delivered-minus-requested float impulse is 6.57383e-12 / 2.39472e-11 /
1.67166e-11 N s respectively. Most final residual follows the existing
`v=(u-u_prev)/dt` reconstruction. Downloaded states retain source double mass;
the float phase uses converted working mass. That difference is retained too.
No momentum correction hides either residual.

The new free-node test's initial fixed 2e-10 N s float bound failed. Its final
bound scales with steps/precision: `u=epsilon_float/2`,
`gamma=(8*128*u)/(1-8*128*u)`, momentum `gamma*sum(|F_i|*64*dt)`
(about 5.35e-9 N s), angular four times that (fixture lever arms below 4 m),
energy `2*gamma*abs(external_work)`. This conservative arithmetic bound is
specific to this free-node fixture; it is not constitutive accuracy or a change
to an existing test tolerance. Double bounds remain 2e-15 N s,
8e-15 kg m²/s and 2e-18 J.

An isolated phase oracle with nonzero initial motion checks linear/angular
momentum and signed kinetic work before reconstruction, plus unchanged positions
and bonds. Across three materials and both precisions, its work residual is
at most 3.97047e-23 J (bound 1e-20 J).

## Bonded response and numerical boundary

Uniform 20 N translation retains every bond and its law. Speeds follow mass:
glass 2.96296e-5, oak 1.05820e-4, iron 9.41221e-6 m/s. Local kinetic + elastic
minus external work residual is at most 2.73901e-22 J. Uniform motion tests mass,
not stiffness. Equal/opposite 20 N diagonal corner loads exercise the unchanged
elastic bonds, with identical CPU states and no failed bonds or altered laws:

| Material | Final elastic energy J | External work J | Momentum residual N s | Unclosed energy J |
|---|---:|---:|---:|---:|
| Glass | 5.21345e-8 | 9.64166e-8 | 3.49340e-18 | -1.35673e-9 |
| Oak | 1.74890e-7 | 3.52364e-7 | 5.78034e-18 | -3.11367e-9 |
| Iron | 1.65885e-8 | 3.07046e-8 | 1.03767e-17 | -4.14860e-10 |

Unclosed energy is final kinetic + elastic + recorded fracture/plastic/damping/
contact losses - external work. Remaining projection/integration residual is
reported, not declared physical loss. This is **not full-pipeline conservation**,
held-impact validation, fracture calibration, wood grain or physical avatar
validation. Free-node wall times are 0.00011–0.00015 s in this sample; tiny
fixtures do not establish game-scale performance.

## Verification and next gate

```powershell
cmake --build build/agent-paid-machine --config Release --target banjo_lattice_external_load_tests banjo_fast_lattice_tests banjo_lattice_plasticity_tests --parallel 4
ctest --test-dir build/agent-paid-machine -C Release -R '^banjo_(lattice_external_load|fast_lattice|lattice_plasticity)_tests$' --output-on-failure
python scripts/check-source-registration.py
git diff --check
```

New registered/compiled target: eight named cases pass, including refusal,
cancellation, expiry, zero-load identity, CPU parity and signed-budget withdrawal.
Existing lattice and plasticity regressions pass too: three CTest targets,
8.68 s on the final rerun. Source registration 288/288. Final new-test build has no new warning.
No interactive input behavior changed or was newly qualified by this checkpoint.

Next integrate the complete held assembly and bounded hand/joint forces with
opposite reactions and consistent elapsed time, preserving one contact response.
Then enable ordinary object targets and qualify repeated physical strikes,
damage/history, private inventory and paid reuse/restart. R3 remains open.

## Publication

Implementation `0d36e5675907bd945569d509d32f91d432836955` is published on GitHub
main. The recorded CPU tests were built from those exact implementation sources;
the following documentation record changes no native code. This is source/test
infrastructure, not deployed destruction gameplay. Preview 8770 remains on R2.
