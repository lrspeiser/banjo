# Paid exact rigid machines — October 1, 2026

Published implementation: `7727056814152ccfe8c728f9b5711426b8d0a67d` on
GitHub main; remote revision verified after the ordinary fast-forward push.
Verification used base `d1fe1da` plus this checkpoint's changes, as recorded
in the retained evidence. Own 8770 preview now runs the verified new native
runner/DLL. Fresh entry/Inventory/pick take-and-stow/carried and empty Lab pass,
with one rated finite source, zero pending transfers and zero JS exceptions.
The prior preview world also opens with ten bodies and zero JS exceptions.
Existing room data is retained. The default process remains undeclared and
Lab explicitly refuses funded review until it is configured.
Preview: `http://127.0.0.1:8770/world?world=2d9adaf72b664763ae8ac9fd97252a94`.
The full player goal remains **four verified, ten partial**. Default workbench
integration, complete paid progression and damaged-tool-to-use are next.

## Implemented

Configured Make admits supported single-material exact fixed solids and exact
rigid assemblies/machines, including different materials within a fixed group.
Quotes for assemblies/machines open an isolated native probe without advancing
time. They use the native material allocation, not a sum of overlapping part
envelopes. Every required material is reserved atomically; per-material offcuts
and transfers close independently. Legacy scalar lattice jobs still load.

A product's declared initial battery charge is an additional cost. Start
reserves it from the finite buffer separately from shaping work; installation
verifies the new native stores and transfers that reserved energy once. Failed
saves retain the old world and pending workpiece. Retries/reopen retain one
output and one transfer. New processor inputs/outputs contain no free cargo.

Lab review shows material name/quantity, total energy, battery charge and time.
Personal/shared funding buttons name the actual material. Each operation
disables the other controls until its state refresh finishes, avoiding concurrent
charging clicks against stale meters. Unknown write acknowledgements retain
their exact retry; native stale-source checks still precede debit.

Recipes readiness and Check it now compile explicitly rigid designs through
the exact source compiler. Face-only lattice joint heuristics cannot reject
an overlapping native compound. This is a source check, not native strength,
placement or functional certification; Review/Preview perform native admission.
AI funding follows each required material in the character's own rack.

The native material allocation is additive JSON. It reports declared mass,
mechanical mass and both allocation/mechanical residuals separately. Creating
saved constraints used to wake sleeping existing machines during carry; saved
sleep is now restored after constraint creation, preserving explicit wake
decisions caused by changed/removed support. No contact, density, inertia,
overlap sampling, damping or constitutive law was changed.

World MCP **1.19.0**, platform MCP **1.22.0**, native ABI **25**. Old native
binaries cannot quote paid exact machines without the new allocation export;
they refuse explicitly. Existing unpaid authoring retains its older adapter.

Sources: [process ledger](../mcp/fabrication.py),
[quote adapter](../playground/fabrication_room.py),
[native quote measurement](../playground/rigid_assembly.py),
[installer](../playground/workshop_install.py),
[Lab controls](../playground/workshop.js),
[rigid allocation](../src/fastlattice/PreciseRigidScene.cpp),
[export/carry](../src/fastlattice/LiveWorld.cpp).

## Measured behavior

[Retained evidence](evidence/fabrication-machine-checkpoint.json) records exact
binary hashes, dirty verification base, cases and results. Windows, Python 3.13,
MSVC 19.44.35228, x64 Release; separate `build/agent-paid-machine`, Lab OFF.
Native work uses **40 mm scene cells, dt=1/240 s**, with exact rigid geometry
independent of that grid. The authored workbench uses **100 J/kg, 500 W,
efficiency 1**; these are estimates, not calibrated forming laws.

Matched isolated mass probes use the same support/arm geometry: 0.003072 m³.
Each job reserves 25 kg, spends 2500 J shaping work and transfers 100 J to its
new battery. Six accepted seconds finish work; failed-save rollback and whole
restart pass. Each motor subsequently operates for 0.1 s and draws positive
energy, with `remaining charge + given = 100 J`. Motor-use examples run
sequentially in one room to test preservation of previous machines; their work
values are not a controlled constitutive comparison.

| Material | Catalog density kg/m³ | Product kg | Mechanical minus declared kg |
|---|---:|---:|---:|
| Glass | 2500 | 7.68 | 0 |
| Oak | 700 | 2.1504 | 1.105e-7 |
| Iron | 7870 | 24.17664 | -1.103e-6 |

The different masses follow density. Exact bodies have no internal stiffness,
grain, plasticity or fracture resolution; this does not validate those laws.
Allocation closes against declared double mass at 1e-8 relative/absolute.
Mechanical mass is reconstructed from Jolt's float inverse mass and checked
at **2e-7 relative, 1e-12 absolute**, bounding mass/inverse-mass float
conversion. Both values are retained; neither is corrected to hide a residual.
Existing solver/constitutive tolerances are unchanged.

Two half-overlapping 80 mm iron/oak boxes allocate **4.02944 kg iron,
0.17920 kg oak**. Shared space belongs to the first part under the existing
bounded quadrature (24 cells across, 0.2 mm finest; 2M pair/20M body samples).
Allocation residual is about **-2.193e-11 kg**; mechanical residual about
**2.068e-7 kg**. Missing oak refuses with no iron or charge reservation.
Local material residuals are zero; exact-machine process energy residuals
are below **3.7e-12 J**. These are local bookkeeping/admission checks, not a
complete momentum/energy audit of moving machines and external forces.

Chrome saved-design Recipes → Lab uses actual mouse clicks to fund each
material, charge, Start, Run and Place. The minimum overlapping housing uses
**4.20864 kg / 420.864 J work + 200 J battery charge**. Test material is an
explicit heap collected through the real personal inventory/SQL receipts;
energy comes from the actual generated solar battery. No JS exceptions.
An AI makes an oak/iron powered arm with **20.1472 kg iron + 0.3584 kg oak,
2050.56 J work + 100 J charge**, using the same actual funding/placement APIs.
Its human/shared racks remain unchanged. This uses explicit collected test
supplies and a configured process, not autonomous ore-to-machine progression.

## Checks

- Fixed Fabrication QA **64/64**, 69.156 s unittest time; machine, fixed solid,
  overlap, allocation, charge, rollback/restart and Chrome funding cases added.
  Original glass/oak/iron lattice, actual cuts and selected tool-use retained.
- AI controller/paid/restart/refusal **10/10**, 24.940 s. Unsupported mixed
  mechanics refuse before debit or unpaid fallback.
- Fitting **47/47**, 2.584 s; recipe guidance **3/3**, 22.732 s.
- Compiled native carry, precise parts and precise live suites **3/3**,
  9.17 s. Carry includes removed-support wake checks. Parts retain material
  contact comparisons and now check overlap allocation/total closure.
- Source-registration guard: **287/287** C++ sources registered, none excluded.
- Ordinary Chrome window/input runs along with automated screenshots; raylib
  Lab was not rebuilt/requalified in this headless configuration. No cross-GPU,
  macOS/Linux, material realism or complete platform claim.

Commands:

```powershell
cmake -S . -B build/agent-paid-machine -G 'Visual Studio 17 2022' -A x64 -DBANJO_BUILD_LAB=OFF -DBANJO_BUILD_TESTS=ON
cmake --build build/agent-paid-machine --config Release --target banjo_live_world_run banjo_platform_cli banjo_c banjo_precise_rigid_parts_tests banjo_room_carry_tests --parallel 4
ctest --test-dir build/agent-paid-machine -C Release -R '^(banjo_room_carry_tests|banjo_precise_rigid_parts_tests|banjo_precise_rigid_live_tests)$' --output-on-failure
$env:BANJO_LIBRARY=(Resolve-Path build/agent-paid-machine/Release/banjo.dll).Path
python scripts/fabrication_qa.py --engine build/agent-paid-machine/Release/banjo_live_world_run.exe --out build/resource-flow/paid-machines-final-20261001
python scripts/check-source-registration.py
```

## Remaining gates

Declare a finite ordinary starter workbench with no free stock/energy, migrate
complete player/AI/canonical machine builds, and test the actual damaged-tool
replacement-to-use journey. Mixed lattice interfaces and exact ground-tool
points remain unsupported. Exact thermal mechanics/internal damage, calibrated
forming, fatigue, joint health, physical cargo/transport and full-world
conservation retain their separate acceptance gates. Old damage is preserved;
this produces a separate replacement, with no bond healing.
