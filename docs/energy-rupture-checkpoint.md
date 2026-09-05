# Energy-accounted rupture: collision-driven reference

September 5, 2026. Local source `6b44c2f` on codex/physics-foundation; not on main. This is a new opt-in reference component. The running bowl still reports fracture unsupported; the old brittle solver and its recorded defects have not been replaced or validated by this work.

## Implemented contract

`EnergyRupture` accepts an explicitly selected ideal tensile connector law with compliance c (m/N), a geometry-supplied interface area A (m2), toughness Gc (J/m2) and a minimum tensile strength. The intact connector stores U = q^2/(2c). Rupture occurs only for current positive extension with U >= Gc*A. The energy-derived critical extension is sqrt(2*c*Gc*A); its stress must meet the declared strength lower bound. Incompatible inputs reject, without changing stiffness, strength or toughness. The lower bound is not an independently fitted peak stress. This ideal law is not a calibrated bulk glass model.

Each accepted break removes its stored elastic energy and records Gc*A as fracture work. Any discrete overshoot is recorded separately as unresolved numerical energy removal, never heat or additional fracture work. Exceeding the caller's overshoot budget rejects the entire transition. The caller must replay/refine the preceding motion step and retain a cumulative work/error ledger. Old peak strain, compression or projected collision energy cannot fund a break. No velocities, mass, poses or finite-cell spin are changed by rupture; no launch pulse or prescribed shards exist.

The bounded transition preflights every interface before publication (up to 4096 edges and 2048 nodes). A malformed final interface cannot partially break earlier ones. Partially damaged legacy live edges require explicit migration. Already-broken edges cannot spend energy twice. Dynamic wrappers reject an initially failure-ready live edge until its initial topology is resolved explicitly.

Two transactional wrappers combine the transition with the existing conservative elastic step or compliant finite-sphere contact step. Both material and impactor roll back when contact convergence or event work fails. One compliant contact owner advances the participants on the same clock. The first contract excludes static/curved support, Jolt contact, friction and live-world handoff. Endpoint checking is not an adaptive event finder: a crossing and return within a step can be missed, so temporal event convergence remains a required gate.

`compileMaterialRuptureInterfaces` dispatches by declared model, not name. Glass's brittle model is eligible when connector parameters are compatible. Oak and iron catalog models reject this adapter. Their comparative impacts remain explicitly isotropic elastic reference networks; wood grain, metal plasticity and bulk failure are unsupported. Low-level three-material-property connector oracles explicitly choose the mathematical interface law and do not change those catalog capabilities.

## Evidence

All five affected promoted suites pass (6.61 s): energy rupture, constitutive, conservative step, compliant step and transfer accounting. The new rupture suite also passes in the legacy build (0.08 s). Windows/MSVC Release, existing CPU reference. No GUI rebuild or new native fracture verification is claimed.

Tests cover insufficient energy, compression, budget rejection, invalid final interfaces, incompatible strength, repeat calls, initial failure state, material-model gating and immutable motion during rupture. Connectivity yields two components only after the loaded edge fails. Single-cell and rotated multi-cell component checks retain mass, linear/angular momentum, finite-cell spin and kinetic energy through mass-property compilation. These checks do not yet test rigid collision-shape publication or whole-ball fragment surfaces.

Dynamic glass connector tests start with relative kinetic energy, not prescribed extension: input 0.5*GcA stays intact, while 2*GcA breaks. The latter takes 106 accepted steps and 49 rejected/refined trials in this bounded test. The energy residual is -6.20e-25 J. This is energy/momentum evidence, not a proof of event-time accuracy.

A finite moving sphere also loads the initially intact connector through compliant contact. Low input (0.1*GcA) stays intact; high input (20*GcA) breaks after contact-generated deformation. High-input residual: 6.95e-23 J; finite-system linear momentum residual: 2.58e-25 kg m/s. The initial default nonlinear stopping settings failed the strict momentum check; explicit residual-impulse/work budgets tightened the solve without relaxing the test.

Matched catalog comparisons use 10 micrometer connector length, 1e-10 m2 interface area, material-derived mass/compliance, a 2 micrometer radius / 2.5e-12 kg impactor, 2.8e6 N/m normal contact stiffness, zero damping, 4e-11 s nominal steps and 1e-7 s duration. The same 4 or 120 m/s initial impactor speed is used for all substances. Contact/event failures refine the complete step.

| Material | Speed (m/s) | Rupture | Fracture work (J) | Energy residual (J) |
|---|---:|---|---:|---:|
| Glass | 4 | No | 0 | 3.54e-23 |
| Glass | 120 | Yes | 8e-10 | 3.84e-22 |
| Oak | 4 | Unsupported; elastic reference intact | 0 | 2.65e-23 |
| Oak | 120 | Unsupported; elastic reference intact | 0 | -1.70e-21 |
| Iron | 4 | Unsupported; elastic reference intact | 0 | -8.36e-23 |
| Iron | 120 | Unsupported; elastic reference intact | 0 | 3.04e-21 |

These microscopic two-node fixtures are not 45 mm bowl balls, and their speeds are not a claimed glass-ball break threshold. They establish a collision-to-stored-work-to-topology path under a declared ideal law. The old full-pipeline fracture energy defects and all prior convergence failures remain open.

## Next bowl acceptance work

1. Compile physical fracture areas from actual occupied geometry; avoid counting every arbitrary lattice edge as an independent full crack face. Check the compliance/strength/toughness compatibility before selecting spatial resolution or another constitutive law.
2. Refine time around damage onset, including crossings within a step, and compare topology/event timing under timestep and spatial changes. Preserve a global event-error budget.
3. Couple actual bowl contact and any third bodies under one clock/owner. Restore all motion, contact caches and damage histories on rejection. Support work and friction must retain explicit accounting.
4. Build collision/render surfaces and material-derived mass/inertia for emergent fragments; test publication, landing and repeated damage without double responses or fabricated launch motion.
5. Only then enable the bowl's fracture capability and verify the complete inventory/craft/release/shatter experience with glass, wood and iron. Do not move to a new physics family yet.

The supplied API key is stored only in the local `.env`, with `.env` and `.env.*` ignored and an empty `.env.example` tracked. Git confirms `.env` is untracked/ignored. No API request was made and no provider integration changed in this physics checkpoint. The credential is not present in this document, test output or commit.
