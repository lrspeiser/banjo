# Physical pulley and rope qualification — October 17, 2026

The new Rope piece uses the existing articulated native cable model as a
homogeneous fibre strand: radius 6 mm, density 700 kg/m³, effective bending and
twist rigidity 1e-7 N·m², internal loss time 0.002 s, contact friction 0.5 and
terminal retention 1000 N. These are declared effective properties, not a
calibration of a commercial braided rope, wood grain or fibre fracture.
Mass is πr²ρ times manufactured length; contact capsule caps overlap the same
material and do not add mass. There is no electrical branch in a fibre strand.

A wheel consists of three disjoint oak cylinders: hub and two flanges. Union
geometry supplies its mass and inertia. A native hinge connects it to a fixed
or moving carrier. Contact friction supplies its torque; no angular velocity,
trajectory, ratio or outcome is assigned. Translation constraints join strand
rods; angular springs supply passive bending/twist. Axle bearings and the
moving carrier's load bolt remain ideal joints. Strand failure, braiding,
wear, resolved bearings and conductor/insulation effects are not modeled.
The score's strand fabrication cost uses Banjo's generic 20 MJ/kg estimate;
it is not a measured fibre-manufacturing property or part of native input work.

Wrapped, heavily loaded strands need a smaller coupled step than electrical
leads. The authored 4 cm maximum rods use 1/1920 s or smaller steps. LiveWorld
subdivides the entire coupled step, including connector retention checks;
setup settling uses the same subdivision while its device fixtures keep puzzle
time at zero. Ordinary electrical leads retain their existing timestep and
128/16 solver settings. New fibre constraints use 64 velocity and 64 position
iterations. Higher iteration counts were tested and rejected: single-precision
roundoff increased free-apparatus momentum residuals. At 1/960 s, the selected
settings also exceeded the unchanged 3 mm hub-clearance allowance.

`banjo_physical_rope_tests` builds and runs 30 scenarios. Fixed-wheel tests
compare 4 cm and 2 cm requested rod lengths, with steps 1/1920 and 1/3840 s
for 4 cm, 1/3840 and 1/7680 s for 2 cm. Free-frame and moving-wheel tests use
1/1920 and 1/3840 s. The same geometry, forcing and friction are used with
glass, oak and iron supports. Fixed supports have external reactions, so
their momentum change is reported but is not called conservation.

| Support | Max fixed-route joint gap | Min hub centre clearance (R=150 mm) | Max free-frame ΔP | Max free-frame ΔL | Max moving-wheel travel error |
|---|---:|---:|---:|---:|---:|
| Glass | 0.108 mm | 153.526 mm | 1.22e-4 kg·m/s | 2.50e-5 kg·m²/s | 6.13 mm |
| Oak | 0.108 mm | 153.526 mm | 8.29e-5 kg·m/s | 1.27e-5 kg·m²/s | 6.13 mm |
| Iron | 0.108 mm | 153.526 mm | 4.42e-5 kg·m/s | 1.52e-5 kg·m²/s | 6.13 mm |

Free-frame accounting includes every body and rod, supplied force impulse,
torque impulse and midpoint external work. Linear/angular residual limits stay
2e-4 kg·m/s and 5e-4 kg·m²/s. Its energy residual (final mechanical plus elastic,
minus initial and supplied work) is −0.0205 to −0.0319 J. Fixed-route energy
residuals are −0.369 to −0.462 J; moving-wheel residuals are negative too.
Frictional/internal dissipation and numerical loss are not separately exported
as heat, so these results establish passivity and measured residuals, not a
closed thermodynamic ledger or loss calibration. No correction impulse or
unmeasured compensating work is added. Slip is measured at rope/wheel contact;
it is nonzero (about 0.02–0.04 m/s RMS), never forcibly set to no-slip.

The moving route passes under a moving wheel, over a fixed wheel, then to the
counterweight. Two rope spans support the moving wheel; measured counterweight
travel differs from twice pulley-centre travel by at most 6.13 mm after 0.5 s.
The lightweight negative counterweight makes the load fall instead of rise.
The carrier can rock; measuring its centre rather than the pulley axle would
incorrectly treat that rotation as a rope-length error.

`physical_rope_game_tests.py` verifies strict route construction (surface end
attachments, no buried routes, bounded rods and one qualified material), three
nudged successful runs per lesson, failing negative controls and a rotated
assembly. Published height goals/deadlines are unchanged. Local native rehearsals
first reached Thread a pulley at 0.433 s, Raise the crate at 0.833 s and Lift
with less at 1.000 s in the initial voxel-counterweight probe; subsequent exact
compound counterweights pass the same goals and negative controls. The five
integration checks include the new exact-mass and rotated geometry. A sixth
check moves and resizes the starter lift for the heavier crate, using saved
body-relative surface attachments; its native run reaches the same Lift with
less goal without deleting or manually relocating rope endpoints. These are
manufacturing edits before a run, not runtime changes to rod lengths.
Live browser Thread a pulley used roughly 1.1–1.3 s of engine work for 0.6–0.7 s
of world time locally. It is heavier than the old ideal pulley. Hosting and
physical-phone performance need measurement; no real-time guarantee is made.

Old `tackle`, tie and drum recipes keep their published laws. Easy tackle v3
uses individual parts; v1/v2 shared recipes reconstruct the old apparatus.
The new tutorial estimates are author review, not the previous blind probe.
