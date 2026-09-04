# Scenario projection and precomputation

Banjo should not discover at the instant of contact that a requested material solve is too expensive. The scenario projection layer estimates the likely contact regime and computational cost before detailed material activation.

## Analytic projection

For two spheres, the current projector estimates:

- masses from density and radius
- reduced mass and reduced radius
- normal impact energy
- effective elastic modulus
- Hertz maximum indentation, peak force, contact radius, and peak pressure
- one-dimensional post-impact velocities from momentum and pair restitution
- brittle energy and tensile-stress screening ratios
- yielding, cracking, or fragmentation regime

For a sphere on a plane, it estimates:

- gravity components normal and tangent to the plane
- the static-friction requirement for rolling without slip
- sliding versus rolling versus rest
- rolling-resistance loss
- acceleration along the slope

These are fast screening calculations. They select a solver and budget; they do not replace the detailed fracture solver or claim to predict a unique crack surface.

## Deterministic keys

A cache key quantizes the material presets, radius, speed, slope, gravity, voxel size, and material seed. Exact keys make projections portable and reproducible. The CSV format is deliberately inspectable while the schema is evolving.

```bash
./build/dev/banjo_precompute build/dev/ball-scenarios.csv
```

The initial grid contains multiple striker materials, target materials, speeds, and slopes. A runtime can load this table before simulation and avoid repeating the analytic projection.

## Runtime strategy

The projector classifies each scenario as:

- `rigid realtime` — no detailed material solve is expected
- `material realtime` — the estimated bond workload fits the declared budget
- `adaptive hybrid` — local physicalization or reduced resolution is recommended
- `precompute recommended` — a full detailed solve is unlikely to fit the budget
- `cached material outcome` — an exact precomputed material result is available

The current CSV stores projection summaries only. The next cache level will store solver-generated canonical outcomes: broken-bond topology, component-local meshes, normalized fragment velocities, conservation totals, solver version, and validity ranges. Canonical sphere impacts can then be rotated into the contact frame and blended only within explicitly tested neighborhoods. Cache misses always fall back to simulation or a cheaper declared model; they never silently select an unrelated animation.
