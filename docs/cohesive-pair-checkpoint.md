# Finite-mass cohesive dynamics reference

Source `2e9b061a9ba8210aa09471fea5324e3ffc604eaa`, local `codex/physics-foundation`, September 5, 2026. Not pushed or merged. Full goal and Gates 1–2 remain active.

The [opening-interface law](cohesive-interface-checkpoint.md) now drives a collinear two-mass reference through `advanceCohesivePair`. Opening is solved from motion rather than prescribed. Initial kinetic energy can be stored in the interface, dissipated by damage or retained as residual motion. Equal-and-opposite impulses act on both finite masses. No velocity correction, fabricated energy credit or release impulse is applied to make separation occur.

## Method and scope

The pair has finite masses, center-of-mass position, two axial velocities and persistent opening/history. Its midpoint update solves q1=q0+h*vrel0-(h²/2)*(1/ma+1/mb)*Fbar(q0,q1), where Fbar is the independently integrated work-conjugate interface force. Body impulses are +h*Fbar and -h*Fbar. COM translates with the conserved pair momentum. Consequently the discrete kinetic change is the negative interface work, up to the measured solve/roundoff residual.

Both elastic and softening slope magnitudes constrain the step; a bounded bracketed scalar solve finds the opening. A public call permits at most 4096 substeps and one second; excess required work rejects without modifying its const input. This is a uniqueness/stability guard, not an accuracy estimator. The implementation checks energy and momentum budgets before returning a candidate. It does not clamp a residual or label it as heat.

This model has only collinear motion. It includes no rotation, angular coupling, gravity, shear, compression contact, finite contact geometry or lattice topology. Negative opening has no cohesive compression force and must eventually be handled by a separate contact owner; the closing portion of a reference trajectory is not a nonpenetration simulation. It is not wired into the starter or default fracture pipeline. Caller-supplied masses need matter provenance; the tests derive them explicitly from density and coupon volume.

## Verification

Windows Release build and all 18 suites pass in 13.26 seconds. Tests compare elastic relative motion against the analytical two-mass oscillator with 16/32/64 steps, test refinement at 128/256/512 steps, check frame translation, equal/opposite impulses, finite-mass momentum, energy, separation thresholds and budget rejection. The finest opening agrees with the preceding resolution within 1% of critical opening; this is a bounded reference check, not general convergence of fracture trajectories or topology.

Glass, oak and iron use the prior illustrative interface parameters, area 0.0001 m², and masses derived from material density times area times 0.01 m and 0.02 m respectively. Initial relative kinetic energy is either 0.5 or 1.5 times A*Gc, with zero COM momentum. Each exported trajectory has 512 steps over 8*df/initial_relative_speed. Subcritical cases cannot completely separate; supercritical cases dissipate exactly A*Gc and have the analytically expected residual relative speed.

| Input set | Masses, kg | Subcritical damage work, J | Complete-separation work, J | Maximum whole-trajectory energy residual, J |
|---|---|---:|---:|---:|
| Glass | 0.0025 / 0.005 | 0.000146765 | 0.0008 | 6.41e-16 |
| Oak | 0.0007 / 0.0014 | 0.018345654 | 0.1 | 8.02e-14 |
| Iron | 0.00787 / 0.01574 | 1.834565386 | 10 | 8.01e-12 |

Reported momentum residual is zero at double precision in these symmetric-COM unequal-mass trials. That is not a claim of bit-exact general dynamics. Per-call energy acceptance is 1e-12 J + 1e-10 times initial accounted energy; the trajectory tests use max(1e-12 J, A*Gc*1e-8). No tolerances were relaxed. Duration and per-step state/work/momentum data are in the 3072-row CSV.

## Next work

Derive interface geometry and area from actual parts; couple finite-body rotation, force application points and angular momentum; establish one compression/shear/contact owner. Preserve damage through refinement and topology changes. Add dynamic and spatial convergence with physical calibration before applying this to branch cutting, adhesives or fasteners. Default correction energy and over-fragmentation remain unresolved. The illustrative oak/iron parameters are not grain or plasticity models. No realistic cutting or full-platform completion is claimed.

Reproduce with `banjo_cohesive_pair_tests` and `banjo_cohesive_pair_probe OUTPUT.csv`, using the standard Release build and CTest commands. Environment remains Windows 11 Pro 26200, MSVC 19.44 x64 Release, CMake 4.1.2 and Core Ultra 9 285K. This CPU reference changes no viewer controls; the starter is rebuilt and restored separately.
