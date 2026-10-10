# Native thermal and closed reaction fields

## Implemented experimental adapter

`/thermal-fields` displays 24 real, fixed 10 mm material cubes, with editable
glass/oak/iron/ice properties, a chosen heater cell and measured scalar fields.
The display reads native temperature, liquid fraction, remaining fuel and
retained products. Colour is a view of those values, with its measured range
printed beside the scene; it does not change geometry or compute physics.
An iron sheet conducts heat faster because its declared conductivity is higher,
not because a renderer recognizes the material name.

The adapter uses the existing compiled `ThermalKernel` and `EnthalpyLaw` via
`banjo_thermal_fields`. Non-phase pair exchanges use the exact isolated-pair
solution. Forward and reverse half-edge passes compose a symmetric graph
operator; applying the heater before conduction and reaction after it makes
the complete forced graph update first order. Phase pairs use conservative
backward Euler, also first order. No exact whole-network claim is made.

Cells retain one thermal-energy store in J and four species reservoirs in kg.
Total audited energy is thermal energy plus remaining fuel times its declared
chemical specific energy. Heating is explicit external input. Reaction moves
fuel and oxygen into retained products and converts chemical energy to heat;
it does not add a second unaccounted energy store. Closed species mass remains
constant. There are no reaction impulses or moving bodies in this scalar model,
so this is not a mechanical momentum/energy conservation result.

The original solid mass defines a **fixed reference heat capacity**. The finite
local oxygen reservoir contributes conserved species mass but no additional
heat capacity; products retain the original capacity. This approximation comes
from the retained kernel and is unsuitable for calibrated combustion/gas flow.
Oak's composition is 90% demonstration fuel, 10% inert material plus independently
declared finite oxygen. Its activation/rate/heat/stoichiometry are explicit inputs:
600 K, 0.5/s, 16 MJ/kg fuel and 1.5 kg oxygen/kg fuel. Other catalog cells have no
enabled reaction. Glass and iron are constant-capacity conduction demonstrations;
they have no implemented melting law. Ice uses 2,100/4,180 J/kg/K, 273.15 K and
334,000 J/kg latent heat, with no flowing-water geometry.

The C API bounds cells, links, temperature and timestep and commits outputs only
after the whole graph's energy and species checks pass. The Python world restores
the entire requested interval after a late refusal. Export/reopen preserves cell
history and clock exactly under identical source and binary identity. Restore
rejects altered fixed properties, invalid species stoichiometry, fuel consumption
without a law, inconsistent reference budgets, non-tick clocks, heater-work/clock
inconsistency and chemical counters inconsistent with actual fuel consumption.
This is validation of a checkpoint's contract, not proof that arbitrary user-edited
fields follow a unique earlier physical trajectory.

Matter and object IDs are stable within this isolated experiment. They are not yet
attached to the canonical coupled-world object registry or mechanical ownership.
The worker supports bounded manual stepping, not the coupled world's generic
two-second scheduler. Request/response journals retain the actual accepted field
states and accounts delivered by each manual command; there is no outcome cache.

## What to test in 3D

1. Open `/thermal-fields`; heat the default iron sheet for 20 physical seconds.
   The heater cell and neighbours change colour as measured temperature spreads.
   Select any cube to read its temperature, energy and species.
2. Repeat with glass and oak under the same heater/initial conditions. Conductivity
   and density-derived thermal mass change the temperature distribution.
3. Choose **Ice phase test**, then **+ 1 second**. Liquid fraction becomes nonzero
   while temperature remains at 273.15 K; the latent account uses the heater energy.
4. Choose **Fuel + oxygen test**. A 20 W heater starts in a 550 K sheet below
   the declared activation threshold. Advance 20 seconds: products appear at
   the heated cell. Change the heater cell to move the calculated reaction.
   Switch to temperature or remaining fuel and inspect finite oxygen exhaustion,
   retained products and chemical-to-heat conversion. No artificial flames appear.
5. Save and reopen; continue both original and restored states and compare exact
   checkpoints. Strong heating beyond 3,000 K must refuse and restore its interval.

## Verified scope and evidence

Measured from the concurrent worktree based on `c79bcb847cc4d618191af160036f23f6e1cebfc1`;
the integrating checkpoint must record its final published revision separately.
Windows MSVC 19.44 Release, Python 3.13/NumPy 2.2.6 and WSL GCC 13.3 Release,
Python 3.12/NumPy 1.26.4 pass the independent scalar controls. This is not
cross-GPU determinism or physical phone verification.

Standalone-stage Windows thermal DLL SHA256 (before the persistent-matter extension below):
`7dee6d41209e1aa875a788e9399221033521320585db33497826701575db7558`.
Windows native test executable SHA256:
`11d4727cb52e25c9078595d63fef0b84bfc99a55f5dc01ca43fee42e7065d691`.

- `thermal_field_api_tests.cpp`: independent two-lump exponential temperatures
  for glass/oak/iron/ice, phase plateau, finite oxygen stoichiometry and unchanged
  output buffers after early and late native refusal.
- `thermal_fields_test.py`: 24-cell comparative worlds, independent graph
  eigensolution at common times, timestep refinement, latent budget, first-order
  reaction oracle, exhausted oxygen, exact continuation, edited-counter refusal
  and whole-request rollback.
- `physics_fields_gateway_test.py`: actual authenticated HTTP/native paths for
  mechanisms, flow and thermal fields; host/origin guards, missing-library refusal,
  declaration bounds, thermal isolation/200-step limit/export/reopen/logs and
  unsupported generic scheduler refusal.
- `thermal_fields_view_test.mjs`: unique DOM/control wiring and native field
  observable selection; it does not replace normal browser/WebGL verification.

Four identical 5-second/0.025-second-step thermal experiments (24 cubes) take
roughly 9 ms in the Windows native/Python world and 6–7 ms on WSL, excluding
HTTP, journal encoding and drawing. Total energy residuals are below 3e-11 J;
species mass residuals are zero in the heating controls. The finest common-time
temperature errors at dt=0.005 s are approximately glass 4.47e-5 K,
oak 1.69e-5 K, iron 7.31e-4 K and ice 1.13e-4 K. Each halves on timestep refinement.
These are bounded reference-model measurements, not calibrated material realism
or realtime delivery qualification.

## Remaining work

Thermal expansion, temperature-dependent mechanical laws, heating during impact,
field transfer through fragmentation, adaptive-region refinement, free-surface
melting, vaporization, oxygen/product transport, environmental exchange, radiation,
calibrated reaction kinetics and coupled fluid/mechanical/thermal work are absent.
No name-driven combustion, prescribed deformation, smoke or shatter animation
fills those gaps. These systems require explicit shared ownership and conservative
transfer before the eight-family object design can be considered complete.

## Persistent matter/representation extension

`scripts/thermal_matter_adapter.py` now attaches native fields directly to the
coupled world's actual `ObjectRegistry.document()`. It reads finite occupied
primitives, their immutable material/density and geometric volume, actual
world/object/matter IDs and mechanical owner bindings. The infinite ground
boundary has no fabricated finite heat capacity and is excluded. Fixed finite
supports retain their real geometric material mass for thermal calculation;
their prescribed mechanical motion remains externally constrained.

`ThermalMatterTransfer` is compiled into `banjo_thermal_fields`. Its bounded
native rebind accepts one-to-one persistent matter tokens and owner assignments,
validates the full native thermal state, then copies every energy, species and
law value exactly. It refuses missing or duplicated matter, invalid owners and
invalid fields without touching either output. No averaging, heat injection,
chemical change, time advancement or mechanical impulse occurs during transfer.
Reordering output records is only storage remapping: the field associated with
each persistent matter ID stays identical. Hash-token collisions are checked
before invoking the native operation.

The Python adapter exposes `ThermalMatterAdapter(registry, config, library=None)`,
`advance(duration_s)`, `rebind(registry)`, `snapshot(bodies)`, `clone()`,
`export_checkpoint()` and `restore(checkpoint, registry)`. Snapshot positions are
read from current native body rows by their canonical body IDs. Owners may change
while fields continue; rebind requires the thermal and mechanical clocks to agree.
A private clone supports the enclosing world's atomic mechanical/field commit.
Heating uses declared external work; the original solid mass and material energy
remain attached to the same occupied matter while the rigid flight owner changes.
There is no oxidizer/fuel mass added to moving bodies: reaction must be false in
this first mechanical integration.

Only original authored cubic-cell faces conduct in this adapter. Duplicate native
cohesive quadrature records do not multiply a physical face's heat conductance.
Contacts do not conduct heat. The immutable registry alone does not provide an
evolving thermal fracture/plastic topology: the enclosing coupled runtime must
refuse damaged/plastic interfaces with these fields until a qualified topology
transfer is implemented. It must also distinguish scalar liquid-fraction
inspection from an admitted mechanical solid-to-flow transition. Fixed mechanical
constitutive properties are unchanged by temperature in this bounded stage.

The retained `ThermalMechanics` curves apply to older layer/core section models
and include explicit assumptions (including carbon-steel curves standing in for
catalog iron). They are not simply applied to native cohesive/connector cells:
changing their stiffness, rest state or load capacity requires a compatible
constitutive law and accounted mechanical/thermal energy exchange. This adapter
does not add name-only weakening or claim that earlier section laws establish
that exchange.

### Transfer verification

`thermal_matter_adapter_test.py` runs real native coupled registries for matched
glass/oak/iron/ice sheets and balls, at 10 mm sheet resolution and dt=1/960 s.
Each registry has 12 finite material cells/objects in addition to the excluded
infinite boundary. The actual initial ball owner changes from `coupled-world` to
`isolated-rigid-flight`; exactly one field owner changes, and every field value
survives unchanged through that rebind. The 2 W heater adds
0.0020833333333333333 J during the step. Field energy residuals are respectively
3.15e-12 J, -4.85e-13 J, -4.85e-13 J and -4.85e-13 J; species mass residuals are
zero. This is the thermal transfer account, not a substitute for the enclosing
mechanical pipeline's separate momentum/work/conservation checks.

The test also checks heterogeneous fields under arbitrary instance order
permutation, same-clock ownership, exact checkpoint/clone continuation,
missing/duplicate matter and altered clock/budget refusals, an independent
isolated heating oracle, and whole-interval restoration after a late native
temperature refusal. `thermal_matter_transfer_tests.cpp` independently checks
exact native per-ID copies, energy/species receipts and unchanged buffers on
duplicate matter or invalid-owner rejection. Source registration includes both
new C++ sources/tests: 354/354 at this extension.

Extension Windows DLL SHA256:
`05b2091fd2cf3c5bac32d7307c14e704fb10a2a5f76d2a6534fb073b65e28c79`.
These extension native and actual-registry adapter tests pass on Windows MSVC
Release and WSL GCC 13.3 Release; publication,
runtime integration, normal browser verification and final revision identity
must be recorded by the enclosing coupled checkpoint. The complete eight-family
physics goal, fracture field transfer, coupled thermal expansion/weakening,
reactive moving matter and phase-to-flow mechanics remain open.
