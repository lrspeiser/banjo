# Sheet selection and damage visibility — October 8, 2026

## Scope: presentation repair; physical qualification stays BLOCKED

The owner reported no visible reaction when clicking glass and ice, expecting an
iron ball released from 10 m. Inspection found an older loaded `sheets.html`
view: it ran a 6 m/s rigid pick reference against a 40 × 40 × 4 mm sheet,
not the shared ball drop. Off-centre contact remains a documented native
refusal; perimeter clicks could also do nothing beyond a status message.

An iron reference pick has mass 1.76288 g and initial kinetic energy
0.03173184 J. A 1 kg ball released from rest through 10 m in vacuum would
reach about 14.0 m/s with 98.1 J before impact. These are different
experiments. Whether it penetrates requires actual dimensions, support,
material/contact/fracture laws and validated continuation; the display name
does not establish that outcome.

There is no native table in the pick reference. Its perimeter is ideally
fixed; the pictured posts/frame are decorative. The shared ball world has
two actual free posts and a floor, with a 240 × 240 × 80 mm target. That
thick target is not the requested thin pane. Rigid drop mode has no internal
damage. Complete deformable 10 m falls remain too slow; short declared
14 m/s impacts do not simulate that fall. These limitations stay open.

## Changes

- Whole specimen clicks and accessible material-name buttons select without
  silently substituting a different strike location. Run explicitly starts
  the centre pick reference. The page says it is not a ball drop.
- A link carries selected target/striker materials to the shared ball world.
  Its rigid/deformable modes and physical declarations remain explicit.
- Red diagnostic lines join the **current native endpoints** of each actual
  broken bond. They do not draw authored crack surfaces, displace matter,
  create fragments or alter the native law. Orange marks detached cells.
  The overlay can be hidden without changing the accepted state.
- Actual pick mass/energy, elapsed physical time, broken bonds, detached
  cells and clear through-thickness probes are shown separately. Broken
  bonds are not reported as a hole or calibrated shattering. Native refusals
  retain the last accepted state and remain visible.

The visible topology markers improve inspection, not continuum rendering or
fracture accuracy. Original cubes can remain touching after their axial
connections fail. No new fracture, bending, contact, gravity or settling
law is introduced by this checkpoint.

## Fresh native and browser verification

Windows / MSVC Release, relinked sheet binary SHA256
`acd13562bb60e896c21975a1f79f7033d7e18798875195401ec84221d5037fbd`.
The new native fixture compares the same iron striker, geometry, support and
6 m/s initial speed through 20 µs, rounded down to within one native timestep.
All 800 cells are retained. This is a diagnostic comparison, not calibrated
material behavior; oak has no grain model, iron no validated continuum dent.

| Target | dt ns | Observed µs | Broken bonds | Detached cells | Clear probes | Max vertical movement mm |
|---|---:|---:|---:|---:|---:|---:|
| Glass | 16.903 | 19.996 | 76 | 0 | 0 | 0.1749 |
| Ice | 28.550 | 19.985 | 144 | 28 | 0 | 0.1259 |
| Oak | 21.602 | 19.982 | 60 | 0 | 0 | 0.2181 |
| Iron | 17.274 | 19.986 | 44 | 0 | 0 | 0.1048 |

Full attributed E/P/L histories retain this reference's existing assumptions;
the fresh fixture checks its E residual below 1e-9 J, not temporal or spatial
convergence. Material-dependent timestep/density/stiffness remain native inputs.
These fracture counts do not qualify oak rupture or iron cracking.

Registered native fixture + Node diagnostic mapping + existing native-backed
gateway checks pass (3/3, 5.17 s, after a successful Windows relink).
Node consumes fresh native snapshots and verifies every plotted endpoint,
intact states, damage/opening descriptions and invalid-ID refusal. These are
not independent raster QA or full repository regression. Source registration
remains 324/324. No native physics source or tolerance changes; the tool
executable was relinked. The first relink was refused by Windows while the
server owned running sheet executables; those scoped sessions were closed
and the build rerun successfully.

The ice centre continuation reproduces a native contact refusal at 1,937 steps,
55.30 µs, with 348 broken bonds, 56 detached cells and zero clear probes.
The regression retains that last accepted state exactly and requires its refusal
in the explanatory text. This passing diagnostic test proves failure visibility,
**not** successful ice fracture/penetration.

Ordinary browser glass selection, Run, Pause, overlay on/off and Continue reach
60,000 steps: 408 broken bonds, 136 detached cells, 16 clear probes, 8.70 mm
maximum vertical movement at 1.014185 ms. The red overlay follows accepted bond
endpoints; no renderer-created shatter occurs. That screenshot was captured
before the same-source relink, with binary `4b777db8…` from the previous checkpoint.

[Fresh native snapshots and ice refusal](evidence/material-lab/sheet-feedback-results-20261008.json).
[Glass diagnostic screenshot](evidence/material-lab/glass-bond-diagnostic-20261008.png).
[Ice native refusal screenshot](evidence/material-lab/ice-bond-diagnostic-20261008.png)
records the relinked executable and persistent refusal feedback, including
after Pause and overlay toggling. It remains unqualified.

## Next physical gates

1. Build the requested thin, genuinely supported target in the shared world;
   use finite occupied contact geometry rather than gapped sphere proxies.
2. Resolve and benchmark contact/finite-cell rotational response and stable
   substeps so a full gravity fall, impact, unloading and settling is usable.
3. Qualify physical fracture/openings and permanent metal dents with matched
   glass/oak/iron experiments, refinement and full attributed E/P/L.
4. Add native event capture and independent render silhouette/depth/topology
   checks; diagnostic overlays alone are not render accuracy certification.

Publication is the main commit containing this note, reported in the task
response. The actual requested 10 m smash-through demonstration is unfinished.
