# Object-on-object drop checkpoint

Implementation: `de8129f`. Windows MSVC Release, double-position runtime. This checkpoint is being published to main under the owner's regular-update policy.

Four new packages (18–21) cover sphere onto sphere, cube onto cube, sphere onto cube and cube onto sphere. Each shows glass, oak and iron side by side. The target rests freely at center height 0.09 m; the upper object's center starts at 1.25 m with zero velocity and spin. Sphere radius is 0.09 m; cube side is 0.18 m. Gravity is 9.81 m/s² downward. Targets are dynamic, not pinned. The concrete ground has half-length 1.4 m, half-width 0.7 m and physical thickness 0.2 m.

The shared platform API gains an optional finite-ground declaration and an explicit finite-ground capability on the rigid backend. Ground and bowl cannot coexist in this initial schema. Unsupported reference-ground requests, invalid dimensions and initial below-ground placement reject. Existing packages continue to load unchanged. The visual client accepts an optional initial example filename.

Rigid reports now retain the first 256 body-pair contact callbacks with IDs, tick, point and closing speed, plus an omitted-event count. These are solver callbacks, potentially speculative, not an exact collision impulse or fracture-causation ledger. Support contacts remain excluded. The measured velocity response is checked independently of callbacks.

## Verification

The platform regression suite passes in 0.11 s. All 21 packaged examples pass the automated matrix. All 12 new material/shape combinations check:
- After 0.2 s, the target remains within 5 mm of resting height and the falling object's height matches analytical gravity within 5 mm.
- During the one-second test, the falling object's vertical velocity changes upward by more than 0.1 m/s in a step.
- The intended pair produces a closing-speed callback above 1 m/s.
- Both centers remain above 0.06 m during the checked interval.

The first intended pair callbacks occur at tick 107 (0.44583 s), with reported closing speed about 4.333 m/s in every case. This is consistent across materials for matched geometry/initial height, but does not validate a full restitution law. Native inspection verifies elevated objects above grounded targets, Run advances the drop/collision, and Reset restores placements.

These are rigid drop/collision examples. They do not shatter or deform; box fracture and automatic rigid/material activation remain unsupported. Flat ground rendering currently shows the top surface; physical support has finite thickness. No claim of calibrated glass strength, wood grain, metal plasticity, or energy closure is added.

## Run

```powershell
build/win-joint-double/Release/banjo_platform_lab.exe assets/platform 18-drop-sphere-onto-sphere.json
```

Press Run. Next example selects cube onto cube, then the two mixed-shape variants. Reset package restores the starting drop.

Next: add supported material-ground coupling and contact-to-damage attribution, then validated activation/fracture under drops. Preserve this rigid reference and all three material comparisons.
