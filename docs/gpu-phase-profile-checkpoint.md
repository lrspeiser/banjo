# GPU phase measurement, October 9

Implemented measurement, unchanged experimental rigid physics. **No useful
speedup or new material law is claimed.** The CUDA lab now exposes disjoint
SDK stepping, GPU observation and host audit time under **Where calculation
time goes**. Counters cover accepted batches; refused work cannot inflate
reported physical throughput. Every intermediate transform/contact audit is
retained. Startup, snapshot serialization, IPC, journal and rendering remain
outside these counters and inside the separate end-to-end measurement.

## What actually costs time

[Measured baseline and withdrawn trials](evidence/physx-gpu/phase-profile.json)
use Windows, an RTX 5090, ovphysx 0.6.3 and Warp 1.18.0. The baseline is source
`dedbcc00563e6a02a0014e4b26df2a97682695790dfeb79b3001817f9aa208a5`
on main `e770dfa678359d54abac6b4917976380558eef26`: glass's 27-cube yard,
1 kg iron ball from 10 m, zero restitution/friction, 1/960 s, two physical
seconds. The timing includes synchronized wall operations, **not separated
GPU kernel durations**.

| Stage | Wall seconds | Share |
| --- | ---: | ---: |
| Synchronized SDK stepping | 5.8774 | 60.5% |
| State/contact observation, copy and synchronization | 3.4741 | 35.7% |
| Remaining batch audit and loop work | 0.3703 | 3.8% |
| Total | 9.7219 | 100% |

Earlier statements that detailed reads dominate were unsupported; stepping
is larger in this measured fixture. These wall timings do not identify which
SDK kernels, launch costs or CPU/GPU waits cause that cost.

## Shortcuts tested and withdrawn

- Async `step()` followed by the same synchronized observation: 9.467 s.
- Headless contact-processing/USD-write flags: 9.457 s.
- Native bulk stepping with no intermediate observations: 5.321 s for two
  physical seconds. Endpoint energy agrees, but missing intermediate gates
  makes this **inadmissible** for the audited pipeline.
- Coarse CCD declarations: this adapter's required DirectGPU suppress-readback
  setting disables CCD at runtime. All actual coarse batches also fail the
  energy gate. This is not a test of working continuous collision detection.
- Four rather than sixteen TGS position iterations: glass/iron fail in the
  first batch; oak/ice retain 1.416667 s before refusal. Maximum candidate
  gains are respectively 0.00400, 0.01262, 1.71330 and 1.77174 J. All four
  variants are withdrawn. Original iterations and gates remain unchanged.

These are individual diagnostic runs, not controlled performance statistics
or calibrated material comparisons. The private four-iteration script had
copied sixteen-iteration qualification text; evidence explicitly records
the actual changed setting and does not use that copied field as proof.
No private probe bypass is exposed by the public API.

## Repeat the measurement

Use the pinned CUDA runtime and registered regression:

```powershell
build/gpu-runtime/Scripts/python.exe scripts/profile-gpu-contact.py --report build/gpu-phase-profile.json
ctest --test-dir build/voxel-contact-audit -C Release --output-on-failure -R banjo_physx_contact_tests
python scripts/check-source-registration.py
```

The profiler defaults to identical glass/oak/iron/ice refined controls. It
records declarations, actual final bodies, normal momentum residuals,
mechanical energy changes, accepted substep counts, phase time, source hashes
and rejection witnesses. It performs the ordinary safety gates and exits
nonzero for any refused experiment. A short startup check is available with
`--physical-seconds 0.02`; it does not exercise the 10 m impact.

## Verification of the implemented counters

[Fresh phase regression](evidence/physx-gpu/phase-regression.json) passes the unchanged four-material refined 10 m stack controls and four analytical pair controls, plus the actual gated bounce outcome and retained failures. At 1/1920 s, the stacks take 19.12-19.30 wall s for two physical seconds. Accepted batch stepping takes 11.15-11.36 s; observation takes 6.82-6.95 s. Physical mass, mechanical-energy change and normal-only impulse residual checks retain their original bounds. Full work/reactions remain unqualified.

Five scoped CTests pass: PhysX 132.59 s, Newton 26.72 s, gateway 3.30 s, pipeline 7.01 s and playback 0.04 s. Source registration is 342/342 with no exclusions; Python compilation, JavaScript syntax and changed-file whitespace checks pass. The profiler's four-material short startup check passes at 38 substeps (0.019792 physical s); that startup check is not an impact test. These are Windows RTX 5090 measurements, not full repository regression or cross-GPU qualification.

## Remaining work

Measure CUDA kernel/launch/wait cost inside stepping before choosing a new
solver architecture. A faster pipeline must retain all substep gates and
resolve connected contacts, not reduce iteration accuracy or remove reads
without equivalent resident audit records. Port shared CPU material laws and
persistent bond/plastic history with explicit energy/reaction accounting and
glass/oak/iron/ice refinement. Density is currently implemented; elasticity,
grain, fracture, plasticity and heat are not implemented by this rigid GPU
comparator. The independent CPU material lab remains available.
