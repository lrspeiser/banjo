# Physical property and capability coverage

Local source checkpoint: `d56611c`, September 4, 2026. This matrix describes consumers and current evidence, not certified material data. Iron, aluminum, glass, ceramic, oak, rubber, ice and concrete presets are examples with incomplete provenance and calibration. Read the [stage checkpoint](material-stage-checkpoint.md) for current conservation defects and the [transfer checkpoint](transfer-accounting-checkpoint.md) for finite-cell accounting.

| Property / capability | Current consumer and evidence | Remaining boundary |
|---|---|---|
| Density, size and sampled volume | Lattice mass, target inertia, fragment properties; mass and spinning-transfer tests | Geometry/resolution convergence; arbitrary/composite material distributions |
| Initial velocity and spin | Rigid initialization, finite-cell activation and fragment momentum; three-resolution rotated-sphere transfer tests | Full active-stage conservation; subcell torque/torsion; general debris angular dynamics |
| Young modulus / Poisson ratio | Contact effective modulus, bond compliance and strain thresholds; compiler/contact/constitutive tests | Macroscopic elastic calibration, horizon weighting and resolution convergence |
| Tensile/compressive/shear strength | Local strain damage channels sampled at accepted substep endpoints; analytical regression excludes predictor-only damage; constitutive tests | Resolved strain-peak convergence, validated coupon failure envelopes, rate dependence, crack-path convergence |
| Fracture energy | Activation screening and compiled material parameter | Energy-consistent crack work is absent; removed spring energy is only a diagnostic |
| Static/dynamic friction | Contact compilation, sphere/material/support and rigid contact paths; sliding/rolling/pair-contact tests | Consistent full contact-load model and general contact geometry |
| Restitution / contact damping | Combined-contact response and damping/restitution conversion tests | Empirical material/speed dependence; complete scene dissipation budget |
| Rolling resistance | Runtime resisting torque; regression verifies torque instead of forced no-slip | Measured support loads, arbitrary geometry and full work accounting |
| Internal damping | Central radial pair damping; measured loss and vacuum-drag separation tests | Calibrated frequency/rate behavior; viscoelastic memory |
| Yield strength / hardness | Contact screening and classification | No working ductile plasticity, indentation, permanent strain or plastic-work model |
| Anisotropy / reference temperature | Declared material fields | No complete directional elasticity/failure, thermal state/evolution or thermal coupling |
| Seed / strength variation | Deterministic bond strength variation | Physical defect-distribution calibration and statistical convergence |
| Gravity / slope / support enable | Rigid/material/debris paths; free-flight gravity reference and runtime tests | Full support impulse/torque/work ledger, finite/curved/moving supports and general activation |
| Solid spheres / generated fragments | Procedural sphere lattice, smooth rigid sphere and convex fragment proxies | Hollow spheres, cylinders, boxes, ellipsoids, irregular/composite authored shapes and proxy-error validation |
| Object interfaces / laws | Design documents and authoring examples | Assemblies, hinges, fastener failure, unit-aware loader and bounded law/AI APIs |

For every new property, add an explicit runtime consumer, units, a reference test, a stated validity domain and convergence evidence. A field, preset name, green unit test or visually plausible run alone is insufficient. Plasticity, viscoelasticity, anisotropy and thermal mechanics require distinct implemented laws and energy accounting before their names can describe supported behavior.
