# Native vibration representation preparation

October 9, 2026. Based on main `6292bf690cded64d081ccc54309a7b2e001df4a5`.
**Implemented CPU preparation and affine reference; world reduced motion,
strong sheet impact and full realtime remain OPEN.**

## What changed

[The compiler](../scripts/coupled_modes.py) prepares all modes of the installed
native force tangent at one accepted material-island state. It retains density-
derived translational mass, represented rotational inertia, native rest/history,
current velocity, fixed-body reaction rows and load-dependent contact energy.
It discards no eigenmode, including small/uncertain/negative eigenvalues.
This is private preparation for families 1/4 of the
[object representation design](object-representation-design.md), not a new
physical owner or an admitted approximation of the ongoing world.

The numerical derivative first moves each private sample along an actual native
trial, carrying its corresponding material history, then reads its stationary
endpoint force. Editing a pose while keeping unrelated old history creates work
without motion and is refused; that negative witness remains in the tests.
Translations use 1e-13 m and turns 1e-11 rad, with a half-scale comparison.
One-sided differences expose response-branch crossings. Raw tangent symmetry,
refinement error, eigen residual and orthogonality are reported.

Symmetrizing this measured tangent defines an explicitly approximate affine
reference M x'' = F0 - K x. Its all-mode closed-form evolution retains the constant
load and vibration; stable, zero and unstable modes use trigonometric, polynomial
and hyperbolic expressions respectively. Small-angle preload terms retain low
parts. Integrated displacement carries the affine fixed-body wrench impulses.
Its energy oracle is the **affine reference's** energy, not a proof of native
pipeline conservation, physical calibration or future contact accuracy.

A bounded native read-only surface-gap query distinguishes actual sphere/box
separation from overlapping enclosing spheres. In browser testing the existing
swept flight bound conservatively refused the 1 mm-clearance preparation, even
though there was no present contact. The new current-geometry query admits that
inspection; it does not replace the stricter future flight proof. An overlapping
ball refuses isolated preparation.

The state key includes exact native arrays, canonical body mapping, implementation
identity and derivative recipe. Accepted motion/history changes invalidate the
derived basis. It is not serialized as physical continuation and is rebuilt after
reopening. The canonical state/checkpoint remains unchanged by preparation and
by injected private allocation failure. Unsupported/oversized requests refuse.

## What you can inspect in the same 3D website

In `/coupled`, select **Connected sheet**, then Set up. Expand **Prepare sheet
vibration modes · CPU reference** and press **Prepare vibration basis**.
The sheet remains at its accepted physical time. Name/value results show all 54
modes, preparation time, fastest period, stored support energy, detected branch
changes and **Reduced motion: Not admitted**. Preparation is explicit; it does
not run on every frame or quietly freeze the sheet. The full solver still owns
all sheet dynamics. The API/journal includes the complete preparation receipt.

## Measured conditions and results

Windows MSVC 19.44 Release / Python 3.13 / NumPy 2.2.6; WSL Ubuntu 24.04 GCC 13.3
Release / Python 3.12 / NumPy 1.26.4. The native API compiled in separate build
directories on both platforms. These are local measurements, not Render speed.
The identical glass/oak/iron/ice fixture uses nine connected 10 mm cubes, fixed
supports, gravity, a separated 0.1 kg iron sphere at 10 m and a 240 Hz host clock.
Loaded preparations are made after one accepted detailed tick (0.004167 s), using
the reference contact clock. Initial preparations also retain the unloaded state.

| Material | Preparation Windows / Linux ms | Windows fastest local period µs | Windows derivative refinement relative |
|---|---:|---:|---:|
| glass | 303.1 / 178.8 | 0.609 | 5.76e-09 |
| oak | 282.1 / 200.5 | 1.797 | 2.80e-13 |
| iron | 261.6 / 172.8 | 4.808 | 2.60e-06 |
| ice | 291.9 / 193.3 | 6.990 | 1.85e-07 |

These timings are preparation cost, not a reduction in world calculation time.
Unloaded touching-contact states have one-sided derivative defects of about
0.17–0.49: there is no smooth reference across those contact branches. Loaded
local probes are more consistent, but three small modes remain inside derivative
uncertainty on each platform. They are retained and identified, not zeroed to
manufacture stability. Cross-platform bitwise eigensystems are not claimed.

[Windows evidence](evidence/native-mode-preparation/windows.json) and
[Linux evidence](evidence/native-mode-preparation/linux.json) record mass/inertia,
stored contact/material energy, exact identities, derivative/eigen defects and
actual private native-versus-affine comparisons at 2e-7, 1e-7 and 5e-8 s. Errors
shrink locally, but reach the native equation-tolerance floor; this is not a
complete trajectory/refinement qualification. Oak still lacks grain and iron's
connector law is not continuum J2 plasticity.

## Verification

The registered [test](../tests/cpu_coupled_modes_test.py) covers independent
loaded/stiff/zero/unstable/coupled oscillator oracles, retained modes, exact native
mass/history, state-key changes, no physical mutation, cache invalidation, next
accepted detailed-step parity, branch witnesses, body/DOF/mapping bounds, present
surface geometry, overlapping-ball refusal and private allocation failure.
Preparation leaves the entire exported checkpoint unchanged; subsequent detailed
steps match all physical checkpoint fields, excluding measured wall-time counters
and their enclosing checksum.

Hosted gateway tests exercise the real worker, unchanged export, journal receipt,
session isolation, extra-field rejection and unsupported freefall preparation.
Windows scoped suites include mode preparation, local Jacobian, CPU world/drop/
gateway/CUDA parity and coupled view. Linux runs the compiled native preparation
suite. Source registration remains 346/346. This is not full repository CI, a
physical-phone test or a new GPU material-law qualification.

A draft contact refusal witness used the sheet's nominal rest face after it had
actually sagged and was still separated. It was corrected to a measured overlap,
and the expanded preparation tests pass. No physical tolerance was widened.
The stiff long-time oscillator oracle bounds floating-point frequency/phase
roundoff explicitly rather than using an unrelated absolute velocity tolerance.

## Remaining gates

The earlier strong refined-contact failures were **accepted tiny steps exhausting
an interval budget**, not Newton/conservation refusals in those archived attempts.
The support/contact clock therefore remains the next live-world barrier.
This checkpoint changes no contact/material law, numerical world gate or budget.

Next bind the prepared affine reference to continuous contact/constitutive branch
bounds, retain actual vibration through accepted-time transfers, and audit the
full native mass/P/L/energy/work/reaction accounts. Compare always-detailed common-
time trajectories with temporal/spatial refinement and support edits. Then admit
bounded reduced continuation and promote back to detail before a strong impact;
an energy-only affine oracle is insufficient. Complete detailed ball/contact and
persistent fragment mappings afterward. Articulated, thermal/reaction/flowing
bindings and complete-pipeline realtime remain part of the unchanged goal.

Publication and public browser/API verification must be recorded separately;
a passing local control is not proof that the new Render image is live.
