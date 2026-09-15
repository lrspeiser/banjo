# One floating-point model

Everything compiled into the engine, Jolt included, uses one floating-point
model: IEEE arithmetic in the order the source writes it, with no fused
multiply-add the source did not ask for and no reassociation. On MSVC that is
`/fp:precise` without `/fp:contract`. On GCC and Clang it is
`-ffp-contract=off` without any of `-ffast-math`. `cmake/FloatingPointModel.cmake`
applies it and refuses a configure in which any target or file asks for
another. This note records why, what was measured, and what the choice cost.

Everything below was measured on 2026-09-15, on `9317a5b` (main), with
Visual Studio 2022 17.14 (MSVC 14.44), Release, on a 24-core Windows desktop,
unless it says otherwise.

## The hazard

An inline function or a template instantiation is compiled into every object
file that uses it, as a COMDAT. The linker keeps one copy, the first it meets,
and drops the others. GNU ld does the same with weak definitions. If two objects
were compiled under different floating-point rules, then which copy survives,
and so what the arithmetic gives, depends on link order.

Jolt sets its own flags in its own directory (its `Build/CMakeLists.txt`), where
none of our targets inherits them. It uses `/fp:fast` on MSVC, or
`-ffp-contract=fast` on GCC and Clang on x86, which contracts `a*b + c` into a
fused multiply-add and, on MSVC, also lets the compiler reassociate. Before this
change our targets used MSVC's default, `/fp:precise`. GCC's default for C++ is
`-ffp-contract=fast`. So a file of ours that uses a Jolt inline with float
arithmetic made its own copy under other rules than Jolt's.

That is how adding `rigid/DrumRope.cpp`, a Jolt constraint of our own, moved
`banjo_blade_tests`' 800 N cut from 4.67583 J to 4.19157 J. Its copy of
`AxisConstraintPart` replaced Jolt's in Jolt's own SixDOF kerf. `db32cc5` then
gave that one file Jolt's `/fp:fast`.

## What main still had

Four of our files include Jolt's headers: `rigid/JoltWorld.cpp`,
`physics/TetrahedronContact.cpp`, `rigid/DrumRope.cpp` and
`app/runtime_cohesive_probe_main.cpp`. Each object's code COMDATs were read from
the COFF files and compared with the same symbols in `Jolt.lib`'s members. The
comparison masks relocated fields, and it compares the constants a function
reads by their bytes.

| object | Jolt inlines it also defines | same code | different code |
|---|---:|---:|---:|
| `JoltWorld.obj` | 133 | 93 | 40 |
| `TetrahedronContact.obj` | 15 | 5 | 10 |
| `DrumRope.obj` (already `/fp:fast`) | 23 | 18 | 5 |
| `runtime_cohesive_probe_main.obj` | 8 | 6 | 2 |

The floating-point model caused the differences that went away once both sides
used the same model: 9 of `TetrahedronContact.obj`'s 10, which are Jolt's GJK and
EPA (`ClosestPoint::GetBaryCentricCoordinates`, `GetClosestPointOnTriangle`,
`GetClosestPointOnTetrahedron`, `GJKClosestPoint::GetClosest` and
`CalculatePointAAndB`, and `EPAConvexHullBuilder`'s triangle, `AddPoint`,
`Initialize` and sorter). The rest differ in every build measured. They come
from Jolt's other flags: no C++ exceptions, `/GS-`, no RTTI and C++17. They are
`std::stringbuf` and `std::string` members, Jolt's destructors, and
`MotionProperties::GetInverseInertiaForRotation`. That one is 636 bytes in
`JoltWorld.obj`, 549 in Jolt at `/fp:fast` and 620 in Jolt at `/fp:precise`.

The link maps (`/MAP`) of `banjo.dll`, `banjo_blade_tests.exe` and
`banjo_live_world_run.exe` show which copies ran:

- `MotionProperties::GetInverseInertiaForRotation` came from `JoltWorld.obj`.
  So Jolt's own constraint solver, which asks it for every body it turns, ran
  our `/fp:precise` copy of it.
- The GJK and EPA routines came from Jolt's `ConvexShape.obj`. So our
  tetrahedron contact ran Jolt's `/fp:fast` copies.

The hazard ran both ways, in shipped binaries, on main.

## The options, and what each did

- **(a)** Jolt's floating-point flags on every file of ours that includes Jolt's
  headers: `/fp:fast` on `JoltWorld.cpp`, `TetrahedronContact.cpp` and
  `runtime_cohesive_probe_main.cpp`, as `DrumRope.cpp` already had.
- **(b)** Jolt built `CROSS_PLATFORM_DETERMINISTIC`: `/fp:precise` (or
  `-ffp-contract=off`), no FMA intrinsics, and its cross-platform code paths.
- **(c)** One model for everything: `/fp:precise` (or `-ffp-contract=off`) on
  Jolt and on every target of ours. Jolt keeps its FMA intrinsics
  (`JPH_USE_FMADD`). They are explicit instructions, the same in every object.

Each was built from the same export of `9317a5b` into its own build tree, with
the CI configuration (`LAB`, `HEADLESS`, `PRECOMPUTE` and `TESTS` on).

### `ctest -LE long`

These ran one build at a time, with `-j 4`. Base ran first and last, so the lines
that differ between its two runs could be set aside as noise.

| build | passed | failed |
|---|---|---|
| base, first run | 129 / 130 | `live_world` |
| **a** | 128 / 130 | `live_world`, **`motor_tests`** |
| **b** | 129 / 130 | `live_world` |
| **c** | 129 / 130 | `live_world` |
| base, last run | 130 / 130 | none |

`live_world`'s failure is its foresight timing check under `-j 4` load. On base,
a 1.5 m pane's first run cost 524.7 ms against 485.2 ms of warning. Run alone,
twice on each build, it passed every time: base 354 and 356 ms, (a) 363 and
363 ms, (b) 384 and 364 ms, (c) 393 and 374 ms, all against 485 ms.

(a) broke `motor_tests`: "the anchored post has an inertia that could be
turned". `JoltWorld::inertiaAbout` returns `HUGE_VAL` for a body that cannot
turn. Under `/fp:fast`, MSVC 14.44 compiles `HUGE_VAL`, and `INFINITY`, to
`1e+300`, not to infinity. A separate probe showed this and showed that under
`/fp:fast` `x != x` is false for a NaN. `JoltWorld.cpp` has about seventy such
guards (`!(x > 0) || !std::isfinite(x)`). (a) also puts every Banjo inline that
`JoltWorld.cpp` shares with the rest of our code under `/fp:fast`: 1,066 of its
COMDATs are also defined in our other engine objects. And `/fp:fast` does not
make two copies of one function agree. Under (a), 40 of `JoltWorld.obj`'s copies
of Jolt inlines still differed from Jolt's own, both at `/fp:fast`.

The tests that print different numbers are 21 under (a), 26 under (b) and 27
under (c); every other test printed exactly what base printed. Every
assertion held under (b) and (c). The moves that matter:

| test, line | base | (a) | (b) | (c) |
|---|---|---|---|---|
| blade, the 800 N cut (floor 4.2 J) | 4.67583 J | 4.65182 J | 4.67558 J | 4.67562 J |
| blade, drawn along its edge with 200 N | 18 bonds, 0 pieces | 24, 2 | 24, 2 | 13, 0 |
| valley, the oak log's drift in 20 s | to x = 2.27 m | 1.09 m | −2.05 m | −2.11 m |
| scene_joint, the pane struck by the door | 6 pieces | 9 | 8 | 7 |
| live_world, the pane alone / with the cup | 81 / 50 pieces | same | 66 / 67 | 66 / 67 |
| rolling resistance, live world 10 mm, level | −1.78 % of the law | −1.59 % | −0.50 % | −0.50 % |
| runtime, frictionless surface drift (bound 1.6e-5) | 9.89e-6 m/s | same | 5.96e-6 | 5.96e-6 |
| refracture, parity run | 671 bonds | 712 | 662 | 656 |
| bow, 8 kN/m arrow | 2.60504 m/s | same | 2.59774 | 2.59774 |
| motor, the hoist | same to 3e-5 | fails | same to 3e-5 | same to 3e-5 |

Fracture counts and a floating log's path are chaotic in their last digits.
They moved under every option, as they did when an unrelated body was added to a
room (`agent/trial-clock`). The laws' own checks did not get worse. (b) and
(c), where Jolt runs `/fp:precise`, agree with each other on most of the lines
that moved. The full side-by-side table is in the change's measurements (below).

### The playground, against the realtime rule

The rooms were opened through `live_session.Live`, as the server opens them, and
stepped as the page steps them: one call per 60 Hz frame of four 1/240 s steps,
starting a fracture without waiting whenever a step came back with something
breakable. The builds ran interleaved, three rounds. This table gives the
engine's compute over world time, the least and the median of the three rounds.
The owner's rule is 1.1 through to rest.

| room, interaction | base | (a) | (b) | (c) | worst frame |
|---|---|---|---|---|---|
| the world, 10 s from open | 0.073 / 0.074 | 0.076 / 0.076 | 0.073 / 0.076 | 0.072 / 0.078 | 5 ms |
| gates, 8 s | 0.014 / 0.015 | 0.014 / 0.015 | 0.015 / 0.015 | 0.014 / 0.015 | 4 ms |
| ropes, 8 s | 0.055 / 0.056 | 0.057 / 0.057 | 0.053 / 0.056 | 0.058 / 0.058 | 4 ms |
| motion, 8 s (one break) | 0.082 / 0.085 | 0.085 / 0.085 | 0.083 / 0.084 | 0.081 / 0.085 | 31 ms |
| the hoist wound 6 s, braked 3 s | 0.029 / 0.029 | 0.028 / 0.029 | 0.029 / 0.031 | 0.029 / 0.030 | 3 ms |
| an iron ball dropped 1.5 m onto glass, to rest | 0.117 / 0.117 | 0.112 / 0.113 | 0.109 / 0.110 | 0.107 / 0.112 | 201 ms |

No option changes what the rooms cost. The worst frame is a fracture's first
run, the same on every build.

### The long physics

`long-physics.yml`'s six suites and its plate drop are being run for all four
builds on this desktop, and on Linux through the workflow for this branch.
Their results go here before this lands.

## The choice: (c)

- (c) is the only one of the three in which no object in the link, ours or
  Jolt's, is compiled to another model. Two `/fp:precise` compilations of one
  function compute the same values even when their code differs, so which copy
  the linker keeps can no longer change a result.
- (a) leaves the hazard in place and spreads `/fp:fast` into our own code. It
  broke a test on its first run.
- (b) is (c) with Jolt's cross-platform code paths and without its FMA
  intrinsics. It moved as much as (c) and cost the same. Its promise is the same
  rigid-body results on Windows and Linux, and it cannot keep that promise for
  the engine as a whole: our own code calls each platform's own `sin`, `exp` and
  `pow`. Set alone, it also leaves GCC's default `-ffp-contract=fast` on our
  code, so a GCC build would still be mixed. It could be added on top of (c)
  later if the rigid world alone should be identical across platforms.

On GCC and Clang (CI and Render), (c) also ends a mix inside our own code. Jolt's
`-mfma` is a usage requirement of the Jolt target, so every target that links
Jolt was compiled with FMA available and GCC's default contraction, while
`banjo_core` and `banjo_fastlattice` were not. Header helpers they share were
compiled both ways.

## The guard

`cmake/FloatingPointModel.cmake` is included before the first target. It adds
the model's option to the directory, so it comes after Jolt's own flags on every
command line and wins there too. Once the top-level `CMakeLists.txt` has been
read, it walks every target, Jolt's included, and every C++ file of every
target, for every configuration. It reads the options in the order a command
line has them: the language flags, the configuration's, the target's own and
those it takes from what it links, and the file's own. It stops the configure,
naming each target and file, when one would compile to anything but the model.
When the build configures, it says `Floating-point model: N C++ files checked`.

`banjo_fp_model_guard_tests` (`tests/fp_model_guard_tests.cmake`) checks how it
reads 25 option lists, Jolt's real ones among them, for both compiler families.
It also configures `tests/fp_model_guard`, a build that gives one target and one
file a fast option, and requires the refusal to name those two files and
nothing else. On the real project, a `/fp:fast` added to `banjo_runtime` and a
`/fp:contract` added to `LiveWorld.cpp` were refused with exactly those five
files named.

## Adding code

- Never give a target or a file a floating-point option. The configure will say
  which one it was.
- A class derived from a Jolt class whose type information lives in Jolt needs
  Jolt's RTTI setting. `DrumRope.cpp` has `/GR-` (`-fno-rtti`) for that reason,
  and only for that.
- A new dependency with floating-point flags of its own is refused like
  anything else. It takes the model, or it stays out of the link.

## Not covered

- Jolt's other flags still differ from ours: no C++ exceptions, `/GS-`, no RTTI
  and C++17. They change the code of the inlines both sides share, but not their
  arithmetic under one model. They can matter in another way: an exception
  thrown through a `std::` function whose kept copy came from Jolt, compiled
  without exceptions, would not run that frame's destructors. This was not
  looked into.
- `/arch:AVX2` (`-mavx2`) reaches only the targets that link Jolt, so
  `banjo_core` and `banjo_fastlattice` are compiled for SSE2. Without
  contraction or reassociation that does not change what they compute.
