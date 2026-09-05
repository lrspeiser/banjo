# World-scale runtime research notes

Research date: 2026-09-05. These notes are design input for a bounded Banjo runtime. The papers below establish numerical techniques and limits; they do not certify a game implementation, material calibration, or universal realtime performance.

## A scalable state model

Use a three-tier representation rather than allocating deformable matter everywhere:

1. **Cold chunks** retain occupancy, material IDs, aggregate mass/COM/inertia, thermal state, and a conservative interaction envelope. They use the ordinary rigid solver and can sleep. The envelope must include support/contact bounds and a wake margin; it cannot be an animation cache.
2. **Sparse active chunks** allocate cells/particles only around current contact, damage, thermal gradients, or explicit inspection. Neighboring chunks exchange equal-and-opposite forces, impulses, heat flux, mass flux, and reaction work through a bounded interface record. Activation transfers the cold aggregate state into active matter; demotion is allowed only after a residual test and stores the aggregate state plus unresolved-error budget.
3. **Refined local patches** increase spatial resolution around a blade, crack front, hot boundary, or phase interface. Refinement preserves mass, momentum, angular momentum, internal energy, material history, and damage; it does not reset an object to an intact template.

OpenVDB's 2012 paper describes a hierarchical sparse volume whose memory follows active values rather than the dense embedding volume and supports dynamic topology ([Museth, *VDB: High-resolution sparse volumes with dynamic topology*](https://dl.acm.org/doi/10.1145/2383796.2383805), 2012). NanoVDB provides a compact, portable C++/C99 sparse tree and GPU-friendly interpolation/gradient operations ([Museth, *NanoVDB*](https://research.nvidia.com/labs/prl/publication/nanovdb/), ACM SIGGRAPH 2021). These structures solve storage and traversal; they do not decide which cells are physically safe to keep cold. Banjo should use them for sparse occupancy/material fields and active-set indexing, with physics-driven wake/refinement predicates.

The initial complexity contract should be explicit: maximum active cells, links/particles, chunks awakened per frame, thermal substeps, and bytes per world. If a budget is exceeded, preserve the last accepted state and return a bounded “needs refinement/late” result. Never substitute a cached trajectory, RL prediction, or prerecorded fracture outcome as if it were a physical continuation.

## Local deformable and fracture solvers

The current axial spring/network path is an experimental comparator only. Its stiff-wave and cutting convergence are not established, so it must not be treated as the default cheap active tier. Keep its measured strain, reaction, damping, plastic, and fracture ledgers for comparison while selecting a local solver by material law and validated applicability. A higher-fidelity patch may use MPM when topology changes, severe plastic flow, or large deformation makes the network resolution-dependent.

Stomakhin et al.'s snow MPM combines Lagrangian particles with a background grid, an elastoplastic constitutive model, semi-implicit integration, and grid treatment of self-collision/fracture ([Disney Animation, *A Material Point Method for Snow Simulation*](https://www.disneyanimation.com/publications/a-material-point-method-for-snow-simulation/), SIGGRAPH 2013; DOI [10.1145/2461912.2461948](https://doi.org/10.1145/2461912.2461948)). It is a useful local-patch architecture, but its material parameters and visual demonstrations are not a calibration for wood, metal, or tissue.

Wolper et al. formulate dynamic fracture with energy-based continuum damage in MPM and a plastic return mapping path ([ACM DOI 10.1145/3306346.3322949](https://doi.org/10.1145/3306346.3322949), 2019). Their phase-field formulation prevents healing by clamping damage history and couples damage evolution to material energy. This is a candidate for a refined fracture patch, not a reason to replace every chunk with MPM: phase-field length scales, particle/grid resolution, constitutive parameters, and crack-energy convergence must be demonstrated for each material family.

For cutting and two-way rigid interaction, Hu et al.'s MLS-MPM with Compatible Particle-in-Cell (CPIC) adds displacement discontinuities, colored distance fields, material cutting, and rigid-body coupling ([project page and paper](https://yuanming.taichi.graphics/publication/2018-mlsmpm/), SIGGRAPH 2018; DOI [10.1145/3197517.3201293](https://doi.org/10.1145/3197517.3201293)). CPIC is a strong candidate for a blade/contact patch because it treats the discontinuity and rigid reaction in the same formulation. It still requires grid/particle convergence, contact and cutting-energy audits, and a material-specific law; the paper's performance is not a Banjo realtime guarantee.

Vertex Block Descent (VBD) solves the variational implicit-Euler problem by local vertex block updates and reports unconditional stability and budget-limited convergence for elastic dynamics ([Chen et al., ACM TOG 2024](https://doi.org/10.1145/3658179), [author project page](https://graphics.cs.utah.edu/research/projects/vbd/vbd-siggraph2024.pdf)). Augmented VBD extends the method to constraints and contacts ([Giles, Diaz & Yuksel, ACM TOG 2025 project/publication page](https://graphics.cs.utah.edu/research/projects/avbd/)). These are candidate local nonlinear solvers when implicit stability or large stiffness dominates; they do not supply constitutive laws, fracture energy, thermal chemistry, or universal convergence. Benchmark them against the existing CPU reference with reaction, work, timestep, and spatial residuals before adoption.

There is no mandatory rigid-to-network-to-MPM sequence. The transition contract is law-specific:

```text
rigid chunk -> validated local solver for the declared law
                     |-- axial network comparator (experimental)
                     |-- MPM/CPIC damage or cutting patch
                     `-- VBD/AVBD implicit deformable patch
```

Each transition requires a state audit: mass and COM, linear/angular momentum, kinetic energy, recoverable internal energy, plastic work, fracture work, thermal enthalpy, and boundary reactions. Failed audits reject the transition. Contact ownership must move atomically so rigid and local solvers never apply the same contact twice. External work and gravity work define the system boundary; numerical residuals are reported rather than relabeled as heat.

## Thermal and fire coupling

Add thermal state independently of mechanical stiffness: chunk/cell enthalpy (H), temperature (T), heat capacity, conductivity, phase/fuel mass, char/ash mass, and optional oxygen/mixture fraction. For a finite-volume chunk graph, use equal-and-opposite conductive fluxes on each shared face and account for convection/radiation separately. A simple bounded source model can be:

```text
H += conduction + convection + radiation + reaction_heat - phase_change_enthalpy
fuel -= reaction_rate * dt
char/ash += yield * reaction_rate * dt
```

Ignition must require local temperature/energy and available fuel/oxidizer. Burning must consume declared mass and release declared reaction energy; it must not be a visual flag that adds unexplained impulses. Mechanical weakening, shrinkage, and smoke are separate laws with explicit coupling coefficients.

The NIST Fire Dynamics Simulator mathematical reference is a useful boundary for what a fire model actually contains ([NIST SP 1018e6](https://doi.org/10.6028/NIST.SP.1018e6), 2013; current manuals list FDS 6.11.1 as of the research date: [NIST FDS manuals](https://pages.nist.gov/fds/manuals.html)). FDS solves low-speed thermally driven flow with a finite-volume formulation, uses LES assumptions, and commonly uses a mixing-controlled mixture-fraction combustion model with an effectively instantaneous reaction. That is suitable evidence for explicitly naming assumptions, source terms, radiation, oxygen, and validation boundaries; it is far beyond a cheap per-voxel fire and should not be copied wholesale into a Minecraft-scale loop.

For the first game-scale thermal tier, update cold chunks at a slower thermal clock and active hot boundaries at a faster clock. The first slice should be pure pairwise conduction plus a finite fuel/oxygen lumped reaction; it is not a Navier–Stokes fire solver. Subcycling is acceptable only when inter-tier fluxes are accumulated once and applied with equal-and-opposite signs. A conservative multirate explicit method for compressible flow demonstrates local time-step classes with conservative flux interpolation at their interfaces ([Computers & Fluids 229, 105102](https://doi.org/10.1016/j.compfluid.2021.105102), 2021). The applicable design rule is the flux interface, not the paper's fluid solver: each coarse interval must receive exactly the integrated heat/mass/momentum flux exported by the fine interval. Add a bounded interface correction and report its residual.

## Practical rollout and tests

The source-forward plan is:

- implement sparse chunk storage and a cold aggregate with explicit wake reasons;
- activate a law-specific local spring/particle/continuum patch around contact or a thermal gradient;
- add conservative thermal diffusion and a single fuel reaction with mass/enthalpy accounting;
- add a refined damage or cutting solver only after state-transfer, conservative-boundary, and contact-ownership tests pass;
- measure active-cell count, wake churn, wall time, conservation residuals, and error against a denser reference.

Required analytical tests include rigid/cold free flight, chunk activation with zero external work, heat diffusion on a two-chunk slab, thermal subcycling against a single-rate reference, fuel mass and reaction-energy closure, plastic indentation with permanent set, local fracture with surviving surrounding matter, and cutting/continuum convergence for the selected local solver. Repeat material-dependent cases for glass, oak, iron, soft tissue, and the ductile demonstrator where the declared law supports them; unsupported laws must reject or report explicitly.

No source above supports a claim that a sparse structure, multirate integrator, MPM patch, cached result, or learned surrogate is universally accurate or realtime. A surrogate may later reduce cost only inside a measured applicability envelope, with physical fallback and invalidation on state/material/geometry/solver changes.
