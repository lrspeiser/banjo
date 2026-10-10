# Contact retains small physical displacements

October 9, 2026. Shared CPU/CUDA arithmetic repair; full sheet fracture,
detailed-ball response and the eight representation families remain unfinished.
Parent main: `8f0bfb766f9c3120dad0c89a298d51939a2484bb`.

## Defect and implemented change

The canonical object already stores a translation origin and accumulated
displacement. Material interfaces use that stable basis. Contact previously
collapsed it into one world-coordinate double before measuring compression.
A displacement smaller than the center's rounding unit consequently produced
zero contact force. At touching supports, the quantized spring can prevent a
private Newton trial from satisfying its unchanged equation tolerance.

`CoupledGpuKernel.hpp` now carries the low part of the existing position sum
through before/end/midpoint poses and sampled surface points. Compensated sums,
products, projections and distances retain it until evaluating the signed gap.
This is the existing occupied geometry and compliant-contact law, rather than
an added overlap epsilon or assigned response. Mass, inertia, forces, gravity,
constitutive histories, work correction, P/L/E gates and work limits are retained.
The derived CUDA trial buffer grows from 27 to 36 doubles per body; its compiled
layout assertion and actual caller allocation agree. No extra matter is owned.
Save/reopen reconstructs the low parts from the existing canonical basis.

The original weighted-velocity perturbation remains `1e-12`. The weighted
midpoint-displacement floor is reduced from `1e-16` to `1e-17 sqrt(kg) m` now
that contact no longer loses the translation first. This changes private
numerical derivatives, not accepted velocity assignments or material laws.
The original 24-update and equation-tolerance limits remain. A geometry-only
prototype regressed a retained glass root; the finer floor restores it on
Windows CPU, CUDA and Linux CPU. The passing historical replay remains a test.
No common-time equivalence with the preceding arithmetic revision is claimed.

## Independent evidence

The registered native contact test retains its 424 derivative checks, 1,000
work/reaction projections and four stiffness/timing controls. New plane/cube
and sampled-cube witnesses retain positive/negative `1e-18 m` motion under
common translations of 0, 1 and 100 m.

The previously rounded surface witness is retained. An independent 80-digit
Decimal evaluation of its implemented FP64 lever/axes places the unrounded
sample **inside** by `4.760854624018894e-19 m`. Its previous positive gap described
the prematurely rounded sample. Native and CUDA tests now require that signed
distance within `1e-31 m`, retaining finite/unit-normal and reaction checks.
This is a corrected geometric expectation; a physical acceptance tolerance was
not relaxed to conceal a failed response.

Twelve native private controls cover glass/oak/iron/ice and the three common
translations. For a touching 10 mm cube, `-1e-18 m` midpoint motion must generate
the independently computed four-face-sample force `k |u| / 2` and storage
`k uÂ² / 2`, with density-derived mass/inertia and harmonic-modulus stiffness.
The test demonstrably fails against a separately compiled parent native ABI.
It also checks the equal/opposite reaction and unchanged canonical input.
This is a numerical contact oracle, not material calibration at atomic scales.

Matched initial supported-sheet roots at 1/240 s, Windows MSVC 19.44:

| Sheet | Parent root | Repaired root residual | Repaired updates |
|---|---|---:|---:|
| Glass | Refuses at `1.400e-10` | `3.793e-11` | 3 |
| Oak | Accepts at `3.962e-11` | `1.147e-11` | 3 |
| Iron | Refuses at `1.123e-10` | `4.725e-11` | 3 |
| Ice | Accepts at `2.988e-11` | `6.446e-12` | 3 |

Every row uses the same installed geometry/supports, 10 m ball clearance,
material-derived mass, and unchanged `1e-10` equation tolerance. These are
private initial roots, not completed impacts. Single-run CPU root timings
are not a realtime qualification: the repaired root costs about 0.20â€“0.21 s;
already accepted parent oak/ice roots can be cheaper.

Linux GCC 13.3 / Python 3.12 / NumPy 1.26.4 passes the twelve small-displacement
oracles, retained actual glass root with full support/gravity work/P/L accounts,
four 1 mm / 10 g / nine-cell sheet controls, atomic rollback and exact restart.
Sixteen 10 m / 0.1 kg rigid-sphere controls cover all four materials at 240/960 Hz
and 0.25/0.0625 contact phase. Original independent trajectory bounds remain.
Maximum measured global energy residual is `1.59e-9 J`. Two physical seconds of
the Linux rigid control calculate in about 0.18â€“0.22 s at 240 Hz and 0.60â€“0.65 s
at 960 Hz; constructor, HTTP and drawing are excluded.

Retained CUDA sheet refinement attempts also complete 0.10417 physical seconds
for all four substances with a 0.1 kg iron ball / 5 mm clearance at 960/1920 Hz.
Maximum common-time position/speed differences are glass 2.29 mm / 0.299 m/s,
oak 0.287 mm / 0.101 m/s, iron 0.261 mm / 0.0177 m/s and ice 0.495 mm /
0.427 m/s. No sites separate and no faces yield in these controls. These
non-negligible differences keep material-trajectory accuracy unqualified;
conservation and completed short runs do not close the strong-impact gate.

All 16 affected Windows/CUDA CTests pass in 459.82 seconds. The source
registration guard reports 346/346 compiled sources. Native contact, coupled
worlds, representations, registry, rigid drops, pipeline/refinement/contact
timing, CPU/CUDA parity, gateways, playback and view checks are included.
Windows/CUDA and separately verified Linux evidence is recorded under
[evidence/contact-precision](evidence/contact-precision/). The publication and
actual Render deployment revision are reported separately; a Git push does not
prove that the public image is live. This checkpoint does not claim a whole
repository CI pass, physical-phone test, macOS or cross-GPU determinism.

## User test and remaining gates

The test website remains [Banjo on Render](https://banjo-f1sv.onrender.com/).
It opens the explicit CPU lab after login. **Set up â†’ Drop & rebound** retains
Before/Contact/After and exact scene saving. Backend/build identity is visible.
The page continues to label connected-sheet smashing blocked and no longer
presents an earlier GPU timing as the current CPU result.

Strong impact is not fixed by this precision repair. A preliminary CPU geometry
prototype still refused the 10 m glass attempt; it is not final-source speed or
fracture evidence. The former large-perturbation shortcut was withdrawn after
it failed matched initial glass/oak controls. No material preset, invented
fragment trajectory, changed work limit or silent fallback was installed.

Next: resolve coupled strong-impact continuation and awake-island cost; compare
completed glass/oak/iron/ice trajectories under temporal/spatial refinement;
connect detailed ball matter to contact and retained damaged-fragment transfers.
Then qualify equilibrium/reduced continuation and the remaining articulated,
flowing, thermal and reaction bindings. The complete objective remains active.
