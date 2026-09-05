# Interactive fracture microscope

**Fracture now runs in the bowl:** [Experimental bonded-cell checkpoint](bonded-bowl-checkpoint.md) connects crafted balls to local energy-driven failure, surviving internal networks and continued curved-support/multiple-body contact. Glass fractures during release; oak and iron retain elastic connections. Source `f55f996`, UI `a939df0`, local only. This is a slow, coarse 19-cell model with uncalibrated strength and contact geometry, not the completed realistic-fracture gate.

September 5, 2026. Source `413852a`, local `codex/physics-foundation`, not main. The existing bowl app now opens a separate microscope view of the [progressive connector solver](rupture-cascade-checkpoint.md). This makes its computed behavior inspectable; it does not enable shattering of crafted balls.

## Use

Open **Fracture microscope** from the bowl. Select 4, 60, 120 or 240 m/s to compute fresh glass, oak and iron trajectories. Play/Pause and Restart control playback; drag the timeline to inspect earlier states; Next fracture seeks the next glass event. Back to bowl returns to the paused experiment without spending or changing inventory. Save image exports `fracture-microscope.png` into the selected workspace. The native lab was left paused at the first 60 m/s glass fracture with the user's eight crafted balls retained in the bowl.

Blue connections are compressed; orange/red connections are extended; absent connections are broken. Node circles are point markers, not occupied fragment volumes. All rows and frames use one fixed metric position scale, with no exploded-view offsets, prescribed shard impulses or interpolation between incompatible topology. Connected group counts come from the actual live edges. The display slows 100 ns of simulated time to about 20 seconds of playback.

## Implementation and scope

`buildFracturePreview` belongs to the simulation core, independent of raylib. A background job computes a fresh bounded three-material experiment on each speed selection. The UI only publishes completed runs; a rejected experiment shows its error rather than a partial or stale trajectory.

The reference uses eight uniform regions with 10 micrometer spacing and 1e-10 m2 connector area. Density sets each node mass; the catalog modulus sets compliance h/(E*A). A finite 2 micrometer, 2.5e-12 kg impactor contacts the end. This is a microscopic connector experiment, not calibrated bulk glass or a whole-ball mesh. Oak and iron remain explicitly labeled elastic references with failure unsupported.

The cascade now optionally records accepted positions, impactor position and live edges. Initial, interval, event and final frames are retained without altering solver timesteps. Recording is bounded to 128 nodes and 2..4096 frames (default 2048); exceeding the frame budget rejects and rolls back the entire requested advance, including candidate fractures and traces. Playback chooses the latest recorded frame at or before the cursor. Event seeking includes only a tiny display-time rounding allowance, with no change to physical states.

The experiment retains a 20 ps maximum step, 1e-20 s refinement floor, 8e-15 J global event-overshoot budget and the existing contact residual limits. Capture interval is 100 ps, plus every glass event. Oak/iron nominal 20 ps steps subdivide failed contact trials within evaluation/depth limits. The native 240 m/s check exposed a fixed-step elastic rejection; bounded subdivision resolved it without loosening tolerances. This does not establish general convergence or supported wood/iron failure laws.

## Evidence

Windows/MSVC Release: both `banjo_fracture_preview_tests` and `banjo_rupture_cascade_tests` pass in the promoted double-position build (1.02 s) and legacy build (1.03 s). All 12 combinations of four speeds and three materials recompute successfully. Traces have finite positions, strictly increasing timestamps, bounded frame counts and complete edge masks. Recording-on/off comparisons retain the same solver outcomes and evaluation counts; every fracture event has its accepted topology frame; a two-frame budget rolls the entire candidate back.

| Impactor speed | Glass breaks | Oak breaks | Iron breaks |
|---:|---:|---:|---:|
| 4 m/s | 0 | 0 (elastic only) | 0 (elastic only) |
| 60 m/s | 2 | 0 (elastic only) | 0 (elastic only) |
| 120 m/s | 3 | 0 (elastic only) | 0 (elastic only) |
| 240 m/s | 5 | 0 (elastic only) | 0 (elastic only) |

At 60 m/s, native event stepping shows `6 + 2` around 19.987 ns, then `6 + 1 + 1` around 20.720 ns. The surviving six-region core remains connected. Conservation and timestep bounds for this fixture are recorded in the cascade checkpoint; this renderer adds no new physical calibration claim.

Normal native input verified opening, playback, rewind/scrub, both event steps, speed recomputation at 4/60/240 m/s and return to the eight-ball bowl with inventory retained. The automated regression additionally covers 120 m/s. The final Save image output was opened and visually checked after flushing the render batch. A full platform suite and cross-platform graphics verification were not repeated for this checkpoint.

## Next acceptance steps

1. Establish whole-ball discretization and area/material calibration, with geometry and spatial/timestep refinement comparisons for glass, oak and iron.
2. Couple localized surface impacts and curved bowl contact to one authoritative contact response with complete momentum/energy and reaction accounting.
3. Preserve surviving internal networks and fragment lineage after rupture; add fragment-to-fragment/bowl contact without duplicate collisions or arbitrary separation impulses.
4. Connect crafted inventory-backed balls to that path, verify partial fracture and later fragment failures alongside bounce/rolling, and expose supported/unsupported outcomes through the creator API.

All 40 retained mechanics/platform rows and the full project goal remain active. The current microscope does not complete the bowl fracture gate or the general crafting platform.
