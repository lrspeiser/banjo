# Realtime is a failed release gate

October 9, 2026. Diagnostic evidence and viewer wording; **no new physical model or faster solver is delivered here**. Published physics remains main `8e6d3f5116e918cde1c115e2c43af06bedded5fe`, coupled fingerprint `f1cb8651d27c90b5fa46a1d985fc105a846421b77407cfe07f500180202a7dca`.

## What the current result means

1.425 physical seconds / 43 wall seconds is 0.0331× realtime: **30.2 times slower**. The [last published phase comparison](gpu-active-graph-checkpoint.md) improved the full attempt to 36.397 wall seconds, still 25.5 times slower. Both stop before completing impact. Earlier passing trial/parity/rollback tests do not admit this drop or playable realtime.

This scene has thirteen bodies: nine 10 mm sheet cells, two fixed supports, a fixed plane and a primitive sphere. Its material island has 54 dynamic coordinates, and a full coupled solve has 60. This is not a demonstrated hardware capacity limit for a large voxel world. The sphere already has eligible independent rigid flight; the connected sheet still runs its gravity/support/material equations throughout that flight. Small cohesive ranges, stiff connections, repeated numerical derivative candidates, bounded subdivision and CPU/GPU observations make those equations expensive. Rendering is independent and cannot repair this calculation delay. See the [original cost audit](drop-performance-audit.md).

The supported sphere remains primitive rigid matter: it does not yet fracture internally. The sheet laws are isotropic mixed-mode cohesive interfaces for glass/oak/ice and six-mode plastic connectors for iron. Passing conservation is necessary but does not establish correct impact timing, cracks, dents or calibrated material realism.

## A rejected optimization, retained for reproducibility

The [withdrawn experiment](evidence/gpu-representations/withdrawn-local-forces.json) compared the unchanged residual derivative with local endpoint force differences and an exact inertia derivative. The [patch](evidence/gpu-representations/withdrawn-local-forces.patch) applies to the pinned main above. Both still evaluate the full nonlinear trial and retain the original 24-update, energy, momentum, angular momentum and work limits. The experiment changes neither a material law nor a tolerance.

Windows x64, RTX 5090, CuPy 13.5.1 / NumPy 2.5.3, CUDA FP64 `--fmad=false`. Same declared glass sheet, iron 0.01 kg ball, 10 m clearance, dt 1/240 s, independent rigid flight. One warmed diagnostic run per method; constructor, HTTP and rendering excluded, full advance/snapshot included. These are not repeated throughput measurements.

| Derivative path | Accepted physical s | Wall s | Result |
|---|---:|---:|---|
| Residual reference | 1.425 | 31.375 | Newton budget exceeded |
| Local endpoint forces | 1.43333 | 53.595 | Interval trial/time budget exceeded |

The local method changes nonlinear root selection and the refusal boundary. It is **withdrawn from executable source**, not delivered as an improvement. The archive retains actual failed inputs, private candidate history and residuals. Advancing eight milliseconds farther is not completing an impact, and no crack/trajectory equivalence is claimed. This glass-only experiment makes no general comparative material claim; the previously recorded matched glass/oak/iron/ice reference measurements remain the retained boundary.

## Work that can satisfy the gate

1. **Reduce genuinely eligible material work.** Establish and validate equilibrium/reduced elastic continuation for the supported sheet, retaining prestress, vibrations and constitutive history. Do not freeze it or discard stored energy merely because the ball is distant. Wake before contact or support/edit changes, with audited transfers and an always-detailed comparison.
2. **Replace whole-scene derivatives with a qualified local solve.** Build local analytical/block derivatives and compact active work, then move the bounded nonlinear controller and audit decisions onto the GPU. The withdrawn local numerical experiment is evidence that a small assembly change alone is insufficient.
3. **Complete impact and qualify its accuracy.** Preserve one response owner and full external work/reactions. Compare glass/oak/iron/ice at common times under timestep/spatial refinement. Qualify detailed ball and damaged-fragment transfers separately.
4. **Measure delivery separately.** Compact accepted snapshots, journal/HTTP timing and actual browser frame delivery must also meet the budget. Computation speed is not automatically end-to-end speed.

For the current small-scene scope, require **a completed two-physical-second drop in no more than two wall seconds**, including contact, while the independent physical gates also pass. Require repeated warm/cold and tail measurements before a broader realtime claim. The current gate fails explicitly:

```powershell
build/gpu-runtime/Scripts/python.exe scripts/gpu_active_graph_benchmark.py --check-record docs/evidence/gpu-representations/ordered-graph-performance.json
```

That nonzero result is an unresolved capability, not an error to suppress. The viewer now says how many times calculation is slower/faster than realtime and shows this failed full-drop boundary. No new physical validation is inferred from the wording or checkpoint identity. The complete [object representation goal](object-representation-design.md) remains unfinished.
