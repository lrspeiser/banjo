# The earth plan's two spikes

Two standalone programs, run 2026-09-27, that tested the two load-bearing
assumptions in [the earth and mining plan](../../earth-and-mining-plan.md) before
any of it was built. What they measured is in that plan, §9. **Neither is part of
the engine**: they are not in CMake, nothing builds or runs them, and they are
here so the measurements can be made again.

- `roof_spike.cpp` — can a tunnel be made of Jolt height fields? A hill with a
  hole in it, a chamber floor, and a ceiling on a static body turned half a turn
  about X so its surface faces down. Five checks. All five hold.
- `runs_walk_spike.cpp` — does holding a ground column as a list of runs cost
  anything to walk? The valley's 19,500 columns, both layouts, the four shapes of
  access the engine makes. No Jolt, no engine.

## Making them again

`roof_spike.cpp` needs only the Jolt the checkout has already built. Compile it
with that library's own flags, taken from `_deps/joltphysics-build/Jolt.vcxproj`,
Release|x64 — a define like `JPH_DOUBLE_PRECISION` changes what Jolt's types are,
so a spike built without them is not talking to the same library:

    rem vcvars finds vswhere through this, and without it the environment it
    rem leaves behind produces a binary that dies at startup (see below).
    set "ProgramFiles(x86)=C:\Program Files (x86)"
    call "<VS>\VC\Auxiliary\Build\vcvars64.bat"
    set JOLT=<checkout>\build\win-joint-double\_deps\joltphysics-src
    set JOLTLIB=<checkout>\build\win-joint-double\_deps\joltphysics-build\Release\Jolt.lib
    cl /nologo /std:c++17 /O2 /EHsc /MD /arch:AVX2 /fp:fast /DNDEBUG /DWIN32 /D_WINDOWS ^
       /DJPH_FLOATING_POINT_EXCEPTIONS_ENABLED /DJPH_DOUBLE_PRECISION /DJPH_OBJECT_STREAM ^
       /DJPH_USE_AVX2 /DJPH_USE_AVX /DJPH_USE_SSE4_1 /DJPH_USE_SSE4_2 /DJPH_USE_LZCNT ^
       /DJPH_USE_TZCNT /DJPH_USE_F16C /DJPH_USE_FMADD /I"%JOLT%" roof_spike.cpp ^
       /Fe:roof_spike.exe /link "%JOLTLIB%"

It exits 0 when all five checks hold and prints what each one measured.

**The trap that cost the first run.** The first build of this died with 0xC0000409
before printing a single line. It was tempting to blame the flags, so that was
tested: the program was compiled three ways afterwards — c++17 without
`JPH_FLOATING_POINT_EXCEPTIONS_ENABLED`, c++20 with it, and c++20 without it,
which is exactly what the crashing build used — and **all three run and pass**. The
flags were not the cause. What had changed in between was the batch file: without
`ProgramFiles(x86)` set, `vcvars64.bat` cannot find `vswhere.exe`, says so, and
carries on to leave an environment that compiles and links a binary which then
fails at startup. So if a spike dies at 0xC0000409 with no output, suspect the
environment vcvars left rather than the ABI. Match the library's flags anyway,
because an ABI that does not match is a real way to get the same crash.

`runs_walk_spike.cpp` needs nothing but a compiler:

    cl /nologo /std:c++17 /O2 /EHsc /MD /arch:AVX2 /fp:fast /DNDEBUG runs_walk_spike.cpp
