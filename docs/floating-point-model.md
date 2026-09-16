# One floating-point model

Everything compiled into the engine, Jolt included, is compiled to one
floating-point profile, `banjo-cpu-precise-v1`: IEEE arithmetic in the order the
source writes it, with no fused multiply-add the source did not ask for and no
reassociation. `cmake/FloatingPointModel.cmake` applies it and
`scripts/check-fp-model.py` audits what CMake generated, before anything
compiles.

What it promises is narrow: within one build, every object's copy of a
function computes the same values, so which copy the linker keeps can no longer
change a result. It does not make Windows and Linux agree: our code calls each
platform's own `sin`, `exp` and `pow`.

This note says why, what was measured and on what, what ships, and what is not
covered. The measurements were made on 2026-09-15 with Visual Studio 2022 17.14
(MSVC 19.44.35228), Release, on a 24-thread Windows 11 desktop (Intel64 Family 6
Model 198), unless a section says otherwise.

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

## What main had (measured on `9317a5b`)

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

## The options, and what each did (measured on `9317a5b`)

- **(a)** Jolt's floating-point flags on every file of ours that includes Jolt's
  headers: `/fp:fast` on `JoltWorld.cpp`, `TetrahedronContact.cpp` and
  `runtime_cohesive_probe_main.cpp`, as `DrumRope.cpp` already had.
- **(b)** Jolt built `CROSS_PLATFORM_DETERMINISTIC`: `/fp:precise` (or
  `-ffp-contract=off`), no FMA intrinsics, and its cross-platform code paths.
- **(c)** One model for everything: `/fp:precise` (or `-ffp-contract=off`) on
  Jolt and on every target of ours. Jolt keeps its FMA intrinsics
  (`JPH_USE_FMADD`). They are explicit instructions, the same in every object.

Each was built from the same export of `9317a5b` into its own build tree, with
the CI configuration (`LAB`, `HEADLESS`, `PRECOMPUTE` and `TESTS` on). (c) here
is the prototype that was measured; what ships is described under
[What ships](#what-ships).

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

`live_world`'s failure was its foresight timing check under `-j 4` load. On
base, a 1.5 m pane's first run cost 524.7 ms against 485.2 ms of warning. Run
alone, twice on each build, it passed every time: base 354 and 356 ms, (a) 363
and 363 ms, (b) 384 and 364 ms, (c) 393 and 374 ms, all against 485 ms. That
check is now a test of its own, run apart (see [The deadline](#the-deadline-latency)).

(a) broke `motor_tests`: "the anchored post has an inertia that could be
turned". `JoltWorld::inertiaAbout` returns `HUGE_VAL` for a body that cannot
turn. Under `/fp:fast`, MSVC 19.44 compiles `HUGE_VAL`, and `INFINITY`, to
`1e+300`, not to infinity, and `x != x` is false for a NaN. `JoltWorld.cpp` has
about seventy guards of the form `!(x > 0) || !std::isfinite(x)`. (a) also puts
every Banjo inline that `JoltWorld.cpp` shares with the rest of our code under
`/fp:fast`: 1,066 of its COMDATs are also defined in our other engine objects.
And `/fp:fast` does not make two copies of one function agree. Under (a), 40 of
`JoltWorld.obj`'s copies of Jolt inlines still differed from Jolt's own, both at
`/fp:fast`.

The tests that print different numbers are 21 under (a), 26 under (b) and 27
under (c); every other test printed exactly what base printed. Every
assertion held under (b) and (c). The lines that moved most:

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

The checks against a law did not get worse: the cut stays over its floor, the
rolling resistance came closer to its law, the frictionless drift fell, and the
hot cut's energy ledger closes to about 2e-9 J on every build. Whether the rest
is sensitivity or a real change is examined for the largest of them in
[Results that moved](#results-that-moved-the-valleys-oak-log).

### The playground, against the realtime rule (throughput)

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
run, the same on every build. This is throughput: how much of each second of
world time the engine spends. The deadline below is latency.

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

## What ships

### The profile, `banjo-cpu-precise-v1`

| C++ compiler | the profile | refused |
|---|---|---|
| MSVC (`cl`) | `/fp:precise` | `/fp:fast`, `/fp:strict`, `/fp:contract`, `/Qfast_transcendentals`, `/Qimprecise_fwaits`, any `/fp:` option the audit does not know |
| GCC, and Clang with its GNU command line | `-fno-fast-math -ffp-contract=off` | `-ffast-math`, `-Ofast`, `-ffp-contract=` anything but `off`, the rest of the fast-math family, any floating-point option the audit does not know |
| anything else, `clang-cl` included | none: the configure stops | |

`/fp:except-` (Jolt's) is allowed: it changes no result. MSVC 19.44 does not
contract under `/fp:precise`, even with `/arch:AVX2`; the probes below check it.
Jolt keeps `JPH_USE_FMADD`: its explicit FMA intrinsics are the same
instructions in every object. The options are added to the top directory, for
C++ only, before any target exists, so they reach Jolt's targets too and come
after Jolt's own flags on each command line, where the last one wins. The audit
checks that it did.

A change to what the profile means gets a new name (`-v2`), not an edit.

### Where the profile's name is

- `banjo_version_string()`: "banjo *date*, floating-point profile
  banjo-cpu-precise-v1" (and `banjo.version()` in Python).
- `BANJO_FP_PROFILE`, a definition every target that links `banjo_core` sees, and
  `banjo::fp::profile()` and `profileHash()` (`src/numeric/FpProfile.hpp`).
- `<build>/banjo-fp-profile.json`: the profile, its options, the compiler and
  its version, the generator, the platform and the build type.
- `<build>/fp-model-audit-<config>.json`: the audit's findings for that
  configuration.
- The workflows keep all three with the test results as evidence, named by the
  commit, whether the job passed or not.
- Every cache of computed results is keyed by it, so nothing computed under
  another profile is read back as if it were this one's:
  - the fast lattice's propagator cache (`fastlattice/Propagator.cpp`): the
    profile's hash is in the cache's key and file name;
  - the analytical scenario CSV (`prediction/ScenarioCache.cpp`): its first line
    is `# banjo.fp-profile banjo-cpu-precise-v1`, and a file without it or with
    another is not loaded;
  - the generated valley (`terrain/TerrainGenerator.cpp`): the profile's hash is
    in the file name's key;
  - material outcomes (`precompute/MaterialOutcome.*`): format 3 keeps the
    profile's hash in the key, and one computed under another profile is
    refused ("material outcome was computed under another numerical profile").

  A cache written before this change is not found, and is computed again once.

### The audit

`scripts/check-fp-model.py` does not approximate CMake. It reads what CMake
generated, after generation:

- CMake's File API reply (codemodel v2, toolchains v1), for each
  configuration: every target, every file each target compiles, and the
  ordered fragments of each compile command, with generator expressions,
  `SHELL:` options, per-file options and what each target takes from what it
  links already resolved by CMake. A build with no build type is audited as its
  one unnamed configuration.
- The generator's own commands, as a cross-check: for Ninja and Makefiles,
  `compile_commands.json`, response files expanded, where each compiled C++ file
  must appear once per target that compiles it; for Visual Studio, the
  generated projects' settings for each configuration and file, since MSBuild
  builds the command from them, and no `Directory.Build.props` or `.targets`
  may sit above the build.
- The environment the compiler will read: `CL` before and `_CL_` after the
  command for `cl`. `CCC_OVERRIDE_OPTIONS` is refused for Clang.
- Each command's options in the order the compiler reads them, against the
  table above. A floating-point option the audit does not know is refused, not
  skipped. On GCC and Clang the link lines too: fast math on a link line links
  `crtfastmath`, which flushes denormals for the whole program.
- Every compiled C++ file and every header it can reach through `#include`, for
  floating-point pragmas (`float_control`, `fp_contract`, `fenv_access`,
  `GCC optimize`, `clang fp`), optimize attributes and calls that change the
  floating-point environment (`_controlfp`, `_mm_setcsr`, `fesetround` and the
  like). A pragma that only makes arithmetic stricter is allowed anywhere (Jolt's
  `JPH_PRECISE_MATH_ON` and `_OFF`, contraction off). Each other use must be one
  the audit lists, with its reason: here, Jolt's `FPControlWord.h` and
  `FPFlushDenormals.h`, which only define the classes.
- Every file that can include Jolt's headers must see Jolt's own `JPH_`
  definitions, so Jolt's inline code takes the same paths in every object.

It runs three ways:

- `banjo_fp_model_audit`, a target built before every compiled target, audits
  the configuration being built. A file that would compile outside the profile
  stops the build before anything compiles, and the audit names the file, the
  option and the line of `CMakeLists.txt` that added it.
- The ctest `banjo_fp_model_audit` audits every configuration (`--all-configs`).
- `banjo_fp_model_audit_tests` checks the audit itself: how it splits command
  lines and reads response files (UTF-16 and nested), each rule, the `CL`/`_CL_`
  order, and the include search. Then it configures `tests/fp_model_audit`, a
  build with the build's own generator and compiler, once with `Release` and
  once with no build type. Its targets break the profile in each way the
  configure-time check in `85b19ca` did not see: a fast option written
  `SHELL:`; a file added through a generator expression; a fast option reaching a
  target through a usage requirement that applies in `Release` only; an unsafe
  option with a `Debug`-only safe one after it (CMake drops a repeated option, so
  the safe one never reaches the command line and the file is unsafe in every
  configuration); and a build with no build type, in which the old check looped
  over no configurations and passed. Also a plain fast option, one fast file in
  an otherwise good target, and a file of fast pragmas. The audit must refuse
  exactly those files in each configuration, found in both CMake's reply and
  the generator's commands, and nothing else; and, on MSVC, refuse a good file
  when `_CL_=/fp:fast` is set. It passes with Visual Studio 2022 and with GCC and
  Ninja (Ubuntu, under WSL). CI runs it with GCC and Ninja and may not skip it.

On this desktop's Visual Studio build the audit reads 422 C++ files in 186
targets, Jolt's among them, in each of the four configurations, all 422
commands cross-checked; 909 sources and headers searched, 9 allowed uses, none
refused. C files (raylib's and the C API's example: the viewer and a consumer,
no physics) are counted as outside the C++ profile. `85b19ca`'s configure-time
check is gone, not kept as a warning.

### The checks that run the arithmetic

`banjo_fp_profile_tests` runs the same probe (`src/numeric/FpProbe.inl`)
compiled into three libraries: `banjo_core`, `banjo_runtime`, and Jolt itself
(`src/numeric/FpProbeJolt.cpp` is added to Jolt's own target, so it is compiled
with Jolt's command line). Its inputs are read at run time, so no compiler can
fold them. Each copy must show:

- `a*b + c` not fused, in double and in float: 0 where a fused one gives −2⁻⁵⁴;
- `std::fma` fused;
- `(1e16 − 1e16) + 1` summed in the order written;
- a NaN unequal to itself, not greater than 0 and not finite; an infinity
  infinite; `HUGE_VAL` and `INFINITY` infinite (`/fp:fast` makes them 1e+300);
- `−0 + +0 = +0` and `−1 × +0 = −0`;
- half of `DBL_MIN` a denormal, not zero.

Jolt's explicit FMA must be fused, since `JPH_USE_FMADD` asks for it. The real
validation paths must hold: an anchored post's inertia is infinite
(`JoltWorld::inertiaAbout`), and an axis with a NaN in it, a pin on one
(`LiveWorld::hinge`) and a NaN command to a motor (`LiveWorld::driveMotor`) are
refused. It does not rewrite the seventy-odd guards; it checks that the profile
they rely on holds where they run.

`banjo_fp_link_order_tests` checks the hazard itself. A scene of Jolt's alone (a
floor, three irregular convex hulls, a motored hinge and a limited six-degree
joint, one thread, 180 steps of 1/60 s) is linked twice: once alone, and once
with `tests/fp_link_order_extra.cpp` first on the link line, a file of ours that
instantiates exactly the inlines that changed hands on main
(`GetInverseInertiaForRotation`, `AxisConstraintPart`, `AngleConstraintPart`,
and the closest-point routines under GJK and EPA, in both instantiations). The
two must print the same state, in hexadecimal floats, and the same digest. Here
both give `437cac74dc137a35`. As a negative control the same two programs were
built on main, where the model is mixed: `9e7719fa34eb13be` alone and
`0cbbd844d23d831c` with our copies first. The test fails there, as it should.

### The floating-point environment at run time

`banjo_fp_profile_tests` reads MXCSR where the arithmetic runs and requires
round-to-nearest, no flush-to-zero and no denormals-are-zero on each: the main
thread (0x1fb3), a plain thread (0x1f80) and one of Jolt's worker threads
(0x1900). Jolt's workers run with the invalid, divide-by-zero and overflow
exceptions unmasked (`JPH_FLOATING_POINT_EXCEPTIONS_ENABLED`, which Jolt sets for
this build): an operation giving a NaN inside a Jolt job traps. That was so
before this change. It is recorded, not changed.

### The deadline (latency)

The claim that a foreseen fracture's first run finishes inside its warning is
about the machine as much as the engine, so it is now a test of its own:
`banjo_live_world_deadline` (`banjo_live_world_tests --deadline`), labelled
`performance`, run serially. `banjo_live_world_tests` keeps its correctness
checks and runs serially too. The requirement is unchanged: a 1.5 m drop's cold
first run must cost less than its warning. It is checked only where there are
at least 8 hardware threads, so CI, on four cores, leaves it out
(`-LE "long|performance"`). It is run by `scripts/run-performance-gate.py`,
which runs each build's check in a fresh process, interleaved across builds,
only once the machine is under 15 % busy, and reports each margin.

On this desktop (24 hardware threads, the lattice using 16), MSVC 19.44,
Release, seven runs of each, the machine 7 to 14 % busy before each (the
owner's servers were up): base is main's `9317a5b` engine with this change's
test file, candidate is this branch.

| build | warning | cold margin, min / median | warm margin, min / median |
|---|---:|---:|---:|
| base | 485 ms | 110 / 117 ms | 105 / 124 ms |
| candidate | 485 ms | 122 / 125 ms | 102 / 127 ms |

Every run met the deadline, on both builds.

### The shipped build against the measured (c)

What ships was run through the same regression, `ctest -LE "long|performance"
-j 4` in Release, on this branch (`48fbee4` and this change): 134 of 134 passed.
Its output was compared line by line with the measured (c)'s, setting aside, as
before, the lines that differ between two runs of base. No line (c) printed
changed. What is new: the tests added since `9317a5b` (main's hoist and motor
tests, and this change's four), a duration, the generated valley's cache file
name, which now carries the profile, and `live_world`, which passes now that
its timing check is a test of its own.

## Results that moved: the valley's oak log

The largest move was the valley's oak log: after its 20 s drift it ends at
x = 2.27 m on main and at −2.11 m under (c). The log was started from x = −13 m
shifted by δ ∈ {0, ±1 nm, ±1 µm, ±1 mm}, on main (`9317a5b`) and on (c), and its
position printed each second.

- On main alone, a start 1 nm further on ends at −2.08 m instead of 2.27 m.
- The two builds' unshifted paths part by 1 µm within the first second, by
  1 mm within 2 s and by 10 cm by 11 s. Main against itself shifted by 1 nm:
  1 µm by 1 to 5 s, 1 mm by 1 to 7 s, 10 cm by 11 s. The change of profile is a
  perturbation of about that size.
- Over the seven starts the log ends between −2.09 and +2.78 m on main
  (standard deviation 2.26 m) and between −2.11 and +3.21 m under (c) (2.16 m).
  On each build three of the seven end between −2.11 and −1.81 m. Printed
  second by second, those lodge there at about 15 s and do not move again; the
  others pass.
- The valley test's checks (the log drifts downstream, floats at its draft, and
  the iron bar rests on the bed) passed in all fourteen runs.

So the two numbers are the two sides of a fork the log reaches at about 15 s,
and which side it takes is decided by differences under a micrometre. Both
builds take each side about as often. The fracture counts that moved were not
perturbed this way; they are counts of bonds past a threshold, and were only
compared between builds.

## The long physics

`long-physics.yml` never ran on main: every job stopped at Configure ("Could
NOT find X11"), because the lab is on by default and that runner has no X11. It
now configures with `-DBANJO_BUILD_LAB=OFF`. Its ctest now fails on a selection
that matches no test (`--no-tests=error`), writes JUnit, and keeps the results,
the profile and the audit, named by the commit, whether the suite passed or
not; the plate drop keeps its log too.

On `cff071c`, the commit that landed, on GitHub's Ubuntu runners, six of the
seven jobs passed: `network_adaptive` (13 min), `contact_capacity` (41 min),
`material_showcase` (44 min), the plate drop (44 min), `thermal_geometry_long`
(2 h 09 m) and `network_skin` (4 h 07 m). `banjo_network_runtime_tests` did not
finish. ctest stopped it at its 19,800 s (5.5 h) limit, with no check failed. It
did the same on `85b19ca` (5 h 32 m), where the other six passed as well
(`network_skin` 5 h 21 m, `thermal_geometry_long` 2 h 42 m).

That suite has never completed on a GitHub runner: before `b9e4d27` the workflow
could not run at all, so what it costs there was unknown. It is not this change
slowing it down. CI's own tests take the same time before and after on the same
kind of runner (706 s and 710 s on `4f26aad` and `48fbee4`, 711 s on `cff071c`),
and `network_skin` ran an hour faster here than on `85b19ca`. Making the long
suites fit the runner's budget, by sharding them rather than by asking less of
them, is its own task. Locally the long suites were started for all four
measurement builds and stopped unfinished.

Run to its end on this desktop, that suite fails a check -- and it failed before
this change too. On the landed build it ran 4 h 40 m and stopped at
`sharp-local-damage-and-blunt-control`: "equal-volume blunt tool control must
retain intact soft tissue", where a blunt tool of the sharp one's volume must
leave the tissue with no broken links, no damaged links and in one piece. The
same scenario, run alone, fails the same check on `9317a5b`, before the profile,
exactly as it does on the landed build: both were run side by side on this
machine, 3 h 09 m each, from identical test code and identical fixtures. So it is
a fault of its own, older than this change, unseen because the suite has never
run to its end anywhere. It has its own task.

## Adding code

- Never give a target or a file a floating-point option. The build stops before
  compiling and says which file, which option and where it was added.
- A floating-point pragma or a call that changes the floating-point environment
  is refused unless it only makes arithmetic stricter or the audit lists it
  with its reason.
- A class derived from a Jolt class whose type information lives in Jolt needs
  Jolt's RTTI setting. `DrumRope.cpp` has `/GR-` (`-fno-rtti`) for that reason,
  and only for that.
- A new dependency with floating-point flags of its own is refused like
  anything else. It takes the profile, or it stays out of the link.
- A new cache of computed results keys on `banjo::fp::profileHash()`.
- A new C++ compiler needs its own validated profile before it can build this.

## Not covered

- Jolt's other flags still differ from ours: no C++ exceptions, `/GS-`, no RTTI
  and C++17. They change the code of the inlines both sides share, but not their
  arithmetic under one profile. They can matter in another way: an exception
  thrown through a `std::` function whose kept copy came from Jolt, compiled
  without exceptions, would not run that frame's destructors. This was not
  looked into.
- Results across platforms and compilers: see the start of this note.
- CUDA is not in this profile. The CUDA lattice backend (`BANJO_BUILD_CUDA`, off
  by default) is compiled with `-fmad=false` unless `BANJO_CUDA_FMAD` is set; a
  profile for it would be its own, validated on its own. The audit counts CUDA
  files as outside the C++ profile.
- The audit sees what CMake generated and the environment variables above. A
  compiler launcher or wrapper that adds options of its own is not seen.
- `/arch:AVX2` (`-mavx2`) reaches only the targets that link Jolt, so
  `banjo_core` and `banjo_fastlattice` are compiled for SSE2. Without
  contraction or reassociation that does not change what they compute.
