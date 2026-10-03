# Native actor body foundation — October 3, 2026

Experimental implementation on main base `4101c2b5b06cfb8408b1ed00e8e8e3628147bb6e`,
Windows x64, MSVC 19.44.35228, CPU reference. This checkpoint adds a native body
and save contract, **not playable native walking or swimming**. The browser's
human camera and AI waypoint movement still use the existing reported poses.
The full active scope and R5 remain open; R3 remains owner-paused.

[Machine-readable evidence](evidence/native-player-foundation-checkpoint.json)
records the source/binary hashes, declared conditions and focused checks.

## Implemented boundary

`LiveWorld` admits one free rigid cylinder per stable actor, separately from
editable products and personal hands. The proxy is 0.24 m in diameter, 1.7 m
high and 70 kg, with analytic cylinder volume and inertia. Jolt integrates its
translation and rotation and supplies its contacts. The existing compound
water adapter receives the actual cylinder, native pose and mass.

This is a declared proxy, not an anatomical model. Its contact metadata is
E = 1 MPa, Poisson ratio 0.3, friction 0.6 and contact damping ratio 0.05.
These assumptions are not calibrated human tissue or footwear. The existing
pair law derives restitution from combined damping, so zero individual
restitution does **not** imply an inelastic pair: identical proxies have
coefficient 0.854468. Bodies can bounce and tip freely. No continued upright,
position, velocity or floating assignment has been added.

The diagnostic actuator supplies an explicitly external force/torque, bounded
to 600 N / 120 N m for at most 0.25 native seconds. Accepted steps retain
source impulse, angular impulse about the world origin, and trapezoidal source
work. Refused trials and invalid timesteps leave both body and account state
unchanged. This is **not foot propulsion**, does not debit metabolic energy,
and supplies no locomotion reaction to terrain or water.

Admission is bounded to 32 actors with reserved, collision-checked body IDs.
Duplicate spawn refuses rather than teleporting. Identity, finite physical
state, model, mass, dimensions and source accounts are checked on restoration.
The optional `native_players` snapshot section retains actual pose, velocity,
orientation, sleep state and cumulative accounts. Reopening clears transient
input. Older snapshots without it remain valid. Invalid actor snapshots cannot
silently fall back to a fresh world; incompatible partial carry is refused.

The native line protocol exposes `player-spawn`, `player-actuator` and
`native_players` observations at full numeric precision. These are trusted
diagnostic operations. They have no authenticated browser endpoint, movement
controller, player renderer or C API binding yet. Before exposing them to
clients, the host must derive actor identity and initial placement itself.

Ordinary lattice targets now identify a proxy striker as `native-player:<actor>`
and use its declared impedance, rather than treating every unknown body as the
ground. If contact would require a lattice run containing this exact rigid
striker, that unsupported run is explicitly declined and native contact remains
authoritative. No actor injury or fracture law is implemented.

## Measured checks

Unless stated otherwise, rigid dt = 1/240 s and ordinary lattice admission
spacing = 40 mm. Cylinder dimensions remain independent of that lattice.

| Experiment | Conditions | Result |
|---|---|---|
| Independent translation | Zero gravity, separated human/AI proxies, +280 / −140 N for 0.25 s | Actual vx ≈ +1 / −0.5 m/s; source impulses +70 / −35 N s; expired input does no more work |
| Translation oracle | 70 kg proxy, isolated external work | Momentum residual −2.08616e−5 N s; work minus native kinetic change +2.06334e−5 J |
| Axial torque oracle | Zero gravity, 10 N m for 0.25 s; Iy = 0.504 kg m² | Angular momentum residual −1.36566e−6 kg m²/s; torque work residual +5.06095e−6 J |
| Two-body collision | Equal proxies approaching at ±2 m/s; no later actuator | Bodies remain ordered and reverse approach; outgoing vx ±1.58179 m/s, total translational plus rotational KE 175.236 J versus 280 J initially; total momentum residual bounded to 1e−3 N s |
| Submerged proxy | Declared 64 × 48 basin, 250 mm columns, lake level 3 m, feet at [0, 0.4, 0] m | Volume 0.0769062 m³; initial buoyancy 754.45 N versus weight 686.7 N; native first vy 0.00403272 m/s matches Archimedes acceleration within 1e−7 m/s; actual body rises |
| Dry terrain contact | Same basin with lake level 0 m; feet initially at y = 3 m | Gravity matches −9.81 dt; falling proxy rebounds and remains above the measured terrain within 35 mm contact tolerance through 1.5 s; it does not settle in that interval |
| Actual striker attribution | Identical 500 m/s diagnostic proxy against glass, oak and iron; dt = 1e−5 s | Actual actor name retained and no fake ground fracture run; break thresholds 747.487 / 994.685 / 8292.64 m/s reflect target differences and proxy impedance |
| Trial rollback | Existing glass/oak/iron contact refusal fixtures, grip/haul/fixed modes, two proxy actuators | Exact body/pose/input/account restoration on refusal and invalid timestep; accepted retry matches never-refused control |
| Whole reopening | Two actor IDs allocated in a different order from lexical names | Actual state and cumulative accounts retained; input cleared; duplicate/model/mass/size/ID/quaternion/account violations refuse |
| Process protocol | Two diagnostic actors through the native subprocess, snapshot, complete process shutdown and reopen | Independent response and exact restored observations; old input cannot replay source work |

The high-speed attribution fixture is a bounded engine diagnostic, not a
normal player impact or material realism claim. Those three fixtures are below
their break admission thresholds; they do not measure coupled actor fracture.
Existing glass/oak/iron compound buoyancy, native hand and water regressions are
retained. The cylinder mass/inertia oracles are material-neutral.

Two initial tests incorrectly assumed immediate inelastic stopping and settled
terrain support after 1.5 s. Reading the actual damping-derived contact law
explained both failures. Tests now check reversal, total kinetic-energy bound,
momentum, gravity and nonpenetration; the contact law was not changed to make
the assertions pass. A process test also caught rounding of native actor source
vectors; these new observations now retain full precision.

## Verification

Separate build: `build/agent-native-avatar`, Visual Studio 17 2022 generator,
Release, `BANJO_BUILD_LAB=OFF`, existing pinned dependency checkouts reused.
Compiled `banjo_valley_live_tests`, `banjo_hand_stroke_tests`,
`banjo_water_tests`, `banjo_live_world_run` and `banjo_c`.

```powershell
cmake --build build/agent-native-avatar --config Release --target banjo_valley_live_tests banjo_hand_stroke_tests banjo_water_tests banjo_live_world_run banjo_c --parallel 4
ctest --test-dir build/agent-native-avatar -C Release --output-on-failure -R '^(banjo_valley_live_tests|banjo_hand_stroke_tests|banjo_water_tests|banjo_environment_ffi_tests|banjo_precise_rigid_live_tests)$'
python scripts/check-source-registration.py
git diff --check
```

The focused run contains 103 checks: 21 valley, 9 hand, 21 water, 15 environment
FFI and 37 precise/protocol cases. Source registration covers 298/298 sources,
10 CMake files and zero exclusions. Provider calls are disabled in this run.
Builds retain existing unrelated MSVC warnings. No interactive-window, browser
movement, cross-platform or GPU qualification is implied.

## Remaining work

1. Specify and measure a grounded walking/upright controller with bounded
   contact forces, reactions, source work and traction; test slopes, steps,
   loss of support and useful movement speeds.
2. Implement swimming propulsion with an actual fluid reaction and source
   account; measure immersion, current, shore entry/exit and timestep response.
3. Bind both authenticated humans and AI to the same native actor controls and
   state. Derive camera/hand position from that body and close tool reactions.
4. Preserve actor state through world editing and nonexact receiving without
   silently resetting it; extend the C API if in-process sessions are used.
5. Qualify physical cargo, full contact/fluid/gravity work and momentum/energy
   closure, convergence and multiplayer performance. Local source ledgers and
   passing water-volume checks do not establish this full accounting.

The [world realism review](world-realism-review.md) continues to prioritize
material recognition and a shorter useful opening. This native foundation
does not change terrain presentation or complete that product work.
