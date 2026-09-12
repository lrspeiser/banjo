# Heat, chemistry and gas

A general thermochemical system, not a "cannon firing" feature: matter holds
finite inventories, reactions change what it holds and release energy, heat
moves along physical paths, and gas pushes on bodies. A hearth and a heated
piston are two consumers of the same system; a cannon will be a third.

Branch `agent/thermochemistry`. Engine: `src/thermo/` (library `banjo_thermo`,
which owns no geometry and no motion) and the coupling in
`src/fastlattice/LiveWorld.cpp`.

## One energy convention

Every substance has a specific internal energy measured from 0 K,

    u(T) = u0 + cv * T

where `u0` is its **reference** energy on the model's scale and `cv` is constant
over the model's declared range (150-3000 K). A parcel of matter stores **one**
number, its internal energy U. Its temperature is derived, never assigned:

    T = (U - sum m_i u0_i) / (sum m_i cv_i)

"Chemical" and "thermal" energy are the reference part and the sensible part of
that one U -- two views, not two stores added together. A reaction converts
reactants to products at constant U; it heats what it happens in because the
products' reference energies are lower. Nothing adds a separate heat of
reaction, which is the double count a reacting model is prone to.

Matter that crosses a parcel's boundary carries its **enthalpy**,
h = u + p/rho (for an ideal gas, u0 + cp T). Oxygen drawn from the air brings
h(T_air); flue gas and steam leave with h(T_surface). The existing
`ThermalKernel` measures sensible energy from 0 K the same way.

## The ledger

    change in stored energy = energy crossing the boundary + reported numerical error

Every crossing is added up where it happens:

| line | what crosses |
|---|---|
| `heater_in_j` | external work from heaters (kindling, a torch, a stove) |
| `heat_to_surroundings_j` | convection and radiation to the surroundings, conduction into the floor, gas-region walls |
| `matter_in_j` / `_kg` | environment reactants (oxygen), inflow through an opening |
| `matter_out_j` / `_kg` | released products (CO2, steam), outflow through an opening |
| `joined_j` / `left_j` | bodies drawn into the network by heat reaching them; bodies swept out of the world with what they held |
| `work_to_bodies_j` | boundary work delivered to bodies, net of the atmosphere |
| `work_to_atmosphere_j` | p_ambient dV |
| `numerical_j` | energy the arithmetic had to add to keep a parcel physical. Reported, never hidden: **zero in every run so far** |

`residual_j` is what is left: rounding. Measured:

| run | residual |
|---|---|
| closed reaction fixture (network only) | lands on the closed-form adiabatic temperature to 1e-6 relative |
| open wood fire, 180 s (network only) | < 1e-10 of the stored energy |
| heated piston in a live world, 120 s | 1.6e-11 J |
| two-log hearth over the line protocol, 90 s | 8.7e-6 J on 1.8e8 J stored (5e-14) |
| hearth recipe built through the MCP, 240 s | ~1e-5 J |

The mechanical side is a separate view (`banjo_energy.mechanical_j`: the
solver's own kinetic and gravitational energy). Boundary work is the link
between the two, and in the live piston test the bodies' own energy rose
146.715 J while the gas paid them 147.016 J -- 0.2%, the difference being
the rigid solver's integration loss.

## Matter holds inventories

A body is made of what its material is made of (`Model::composition_of`): oak is
0.88 dry wood, 0.10 moisture and 0.02 ash, which is what lets an oak log burn;
iron is iron. A scene can say otherwise on the body:

```json
{"name": "wet log", "material": "oak", "contents": {"dry wood": 0.7, "moisture": 0.3}}
```

Fractions are of the body's own mass -- the rigid body stays the one owner of
how much matter there is. As fuel is used and gas leaves, the network tells the
rigid body its new mass (`JoltWorld::setMass`, Jolt's `ScaleToMass`), so
momentum and energy are about what is really there. Bodies do not shrink as
they burn (declared).

A body that conducts too poorly to be one temperature (Biot number above 0.1
against the film coefficient) is a **3 mm surface layer over a core**: the
layer is heated, radiates and burns; the core warms behind it; as the layer's
fuel is used the burning front advances into the core and brings its matter
with it. 3 mm is the thermal penetration depth of wood over about a minute.

Bodies nothing has heated are not in the network. A body joins when something
in it could move more than 20 mW into it, and the ledger records what it
brought (`joined_j`).

## Reactions are declared

A reaction names its reactants -- each from the **material** or from the
**surroundings** -- and its products -- each **retained** or **released** -- with a
rate law, a supported temperature range, a version and a provenance. One that
does not balance is refused. A reaction only takes what is there: finite
inventories, exhaustion to exactly zero, and none at all of a reactant the
surroundings do not hold ("requires oxygen" is a property of the reaction, not
of the material).

The demonstration model (`demonstrationModel()`):

| reaction | what | provenance |
|---|---|---|
| wood combustion v1 | dry wood + 1.184 kg O2 (from the air) -> 1.629 kg CO2 + 0.556 kg steam (released). Surface Arrhenius, 2000 kg/m2 s x exp(-10000/T), nothing below 500 K, in series with the oxygen the air can deliver (0.02 m/s x its density). Heating value 16.0 MJ/kg at 298.15 K. | stoichiometry is cellulose's; kinetics and transport are **demonstration** values |
| drying v1 | held moisture -> steam (released), 0.015 kg/m2 s at 373.15 K, Arrhenius, nothing below 300 K. Takes the latent heat (2.257 MJ/kg), so drying cools what it dries. | demonstration |
| rapid reaction v1 | an abstract finite-inventory reaction carrying its own oxidiser, 2.8 MJ/kg, 56% of its mass to gas. **Not a model of gunpowder**, and not yet used by any mechanism. | demonstration |

Gases (O2, N2, Ar, CO2, steam) use cp at 300 K held constant; argon's is exact
for a monatomic ideal gas. Solids use handbook room-temperature values. Every
substance and reaction carries its provenance into `banjo_thermo_report`.

The wood model is a **declared simplified model**: not validated against
ventilation, moisture, geometry or heat-loss variations.

## Heat moves along physical paths

Worked out from where the bodies are, every eighth accepted step:

- **contact**: bounding boxes meeting face to face; area is the overlap, and the
  conductance is a declared contact conductance in series with each side's
  own conduction path;
- **radiation** between separated bodies, by a point-source view factor: each
  body's mean projected area is a quarter of its surface (Cauchy), so a pair's
  exchange area is A_a A_b / (16 pi d^2), the same seen from either end.
  Capped when bodies are close. What a body does not see of other bodies it
  sees of the surroundings;
- **the floor**, under whatever rests on it;
- **the surroundings**: convection and radiation to an infinite reservoir at
  fixed temperature, pressure and composition (dry air).

There is no fire-damage radius: an iron block 0.25 m from a burning log warms
because of how much of the log it sees, and one 6 m away warms a thousandth as
much. Every pair update is the exact two-parcel exponential with capacities
held over the step, so it cannot overshoot; radiation is linearised the same
way, exact to first order.

## Burning is a result

Nothing has a burn time. `remaining_s` is the fuel left over the rate it is
being used **now** -- an estimate under current conditions -- and it changes as
conditions do.

Measured on the demonstration model:

- one log alone, 10 kW of kindling for 60 s: lights, burns at ~1000 K and
  18.6 kW, ~56 min at that rate. 5 kW for 60 s: warms, dries, goes out.
- the same kindling on ONE log of two on a stone hearth: peaks at 758 K and goes
  out -- the stone and the cold log beside it take the margin.
- 10 kW for 90 s under **each** of the two bottom logs: both burn at ~871 K,
  11.3 kW each, ~96 min at this rate; the stone warms to 351 K, an iron kettle
  0.2 m away gains 8.5 K in four minutes, and the log across the top dries.

## Gas pushes on bodies

A gas region is a zero-dimensional ideal-gas mixture: what it holds, its
internal energy and its volume. Temperature and pressure are derived. A
**piston** is a body the region pushes on along an axis; the volume is the
declared volume plus area times how far the piston has moved.

**The coupling policy, which is the part that has to be right:** the force on
the piston for a step is the pressure at the start of that step times the area,
pushed onto the body **inside the step's reversible trial** (Jolt's recorded
state includes the force accumulator; a push made outside it would survive a
rewind and be applied twice). After the step the gas is charged exactly that
force times the displacement that actually happened. The work the gas pays and
the work the mechanics receives are the same product, so they cannot disagree;
the time discretisation is first order and converges -- 0.44 mm off a
192.65 mm lift at 1/60 s, 0.11 mm at 1/240 s.

`balance: true` starts the gas at the pressure that holds up the piston and
whatever rests on it. A gas spring's stiffness gamma p A^2 / V must stay under
the step's Nyquist limit: the demonstration cylinder is omega dt = 0.08 at the
room's 1/240 s.

Measured in a live world: 800 W into 0.4 m of argon under an iron piston and
an iron weight lifted both 218.4 mm in 30 s (453 K, 112.9 kPa); cooled, they
came back to within 0.016 mm. At constant pressure the lift follows
V/V0 = T/T0 to 1%.

## Rollback, breaking, sweeping

- **A refused step takes its chemistry back.** The network is copied before the
  trial and restored if the step is refused: fuel, gas, internal energy and
  every ledger line are bit-for-bit what they were (`tests/thermo_live_tests.cpp`).
- **Breaking shares out what a body held**, by the cells each piece took. No
  fuel is made or lost and every piece is as hot as the body was: measured, a
  burning plank broke into 3 pieces holding 1.2096 of 1.2096 kg and 1.06445 of
  1.06445 kg of fuel.
- **Sweeping a body away** carries its matter out through the ledger.
- **Carrying a burning log** takes its fire with it: the log it was beside went
  from gaining 638 W to 7 W.

## Where it is reachable

| layer | what |
|---|---|
| engine | `thermo::ThermoWorld`, `LiveWorld::thermo() / declareThermo / heat / setVent / thermoReport / mechanicalEnergyJ` |
| C API (ABI 14) | `banjo_declare`, `banjo_heat`, `banjo_vent`, `banjo_bodies_heat`, `banjo_gas_regions`, `banjo_energy_ledger`, `banjo_thermo_report`, `banjo_thermo_model` |
| Python | `World.declare / heat / vent / heat_states / gas_regions / energy / thermo_report`, `banjo.thermo_model()` |
| scene | `contents`, `temperature_k` on bodies; a `thermo` block with `gas_regions`, `heaters`, `ambient` |
| line protocol | ops `heat`, `declare`, `vent`, `thermo`; a trimmed `heat` block on every reply that describes the world |
| MCP | `list_substances`, `enclose_gas`, `heat`, `thermal_state`; `contents` / `temperature_k` on `add_object`; a heat summary on every `run` |
| playground | built by the chat from the MCP's own tools; the room draws glow, flames and gas columns from the engine's numbers and has a **Heat it** button |

## The dependency decision

Banjo-owned, built around the existing thermal kernel's convention. Cantera,
SUNDIALS and CoolProp were not added:

- what this milestone needs -- a few lumped reactions with finite inventories,
  constant-property ideal gases, and a pressure boundary -- is checked against
  closed forms rather than against another code: a closed fixture lands on its
  adiabatic temperature to 1e-6, heating values come out to 1 J/kg of what was
  declared, quasi-static expansion follows V/V0 = T/T0 to 1%;
- the stiff part (the rapid reaction) is integrated by exact first-order
  exponentials with sub-steps that bound the temperature change, which has
  not needed an implicit solver; SUNDIALS becomes worth it when a network of
  coupled stiff reactions does;
- Cantera's own moving wall prescribes a velocity and its flow controllers can
  prescribe flow without the work it costs -- exactly the two traps the
  coupling here is built to avoid -- so it would be a reference, not the
  runtime. Its value is real species data and kinetics for offline
  comparison. CoolProp arrives with water and steam.

Nothing was downloaded. Before any of them is adopted its download size and
Windows build time should be measured and it should sit behind an optional
CMake switch with a pinned version.

## Not modelled

- constant heat capacities over 150-3000 K; no dissociation;
- a body is one lump, or one surface layer over one core; there is no
  temperature field inside a body;
- heat paths from bounding boxes as bodies are turned now;
- the surroundings are an infinite reservoir: no airflow, plume, smoke or flame
  gas phase. Flames in the playground are drawn from the heat-release rate
  (Heskestad's flame height) and are pictures, not heat;
- gas regions are zero-dimensional; openings are incompressible orifices
  (choked flow is not modelled); a region's pressure does not yet act on its
  container's walls;
- temperature does not yet change any mechanical property or cause failure.

## Milestones

| | status |
|---|---|
| 1. Unified accounting and generalised reactions | done: one convention, one ledger, declared reactions with provenance, finite inventories, rollback without double consumption |
| 2. A fuel-fed hearth | done: a declared wood model, oxygen from the air, heat to physical objects, a predicted burn time; move, add, remove and break burning fuel with its state |
| 3. Gas state and mechanical work | done: gas regions, openings, a piston on a real body, compression returning work, boundary work agreeing with the mechanics |
| 4. Reaction-driven motion | not started: the rapid reaction exists and is closed-tested in a sealed chamber; it has not been put on a piston, and there is no cannon |
| 5. Coupled material changes | not started |

## Tests

| file | what |
|---|---|
| `tests/thermochemistry_tests.cpp` | 16: the network on its own |
| `tests/thermo_live_tests.cpp` | 4: the network in a live world |
| `tests/thermo_ffi_tests.py` | 6: through the C library, from Python |
| `tests/agent_build_tests.py` | cases and `--recipes` for `hearth` and `heated-piston` |
| `tests/thermal_kernel_tests.cpp` | the original kernel's conservation tests, unchanged and passing |
