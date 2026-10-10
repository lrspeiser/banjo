# Measured impact-load inspection

October 9, 2026; based on main `6292bf690cded64d081ccc54309a7b2e001df4a5`.
Implemented visualization and accepted-state receipts; no new physical law.

## What the user can test

Open the hosted `/coupled` lab, turn on **Impact map**, run a drop, then use
**Inspect ball contact**. Each finite body is colored by the magnitude of its
accepted native interaction-force resultant in newtons, excluding gravity.
Blue, yellow and red indicate increasing load, with a displayed numerical scale.
**This frame** follows measured replay/contact frames; **Peak this drop** retains
each body's maximum measured load during this scene. Reset clears the peaks.

For the connected-sheet experiment, the nine visible cubes are the actual
material cells. The two supports also show their measured reaction loads. The
rigid ball remains one primitive, not a secretly simulated set of tiny voxels.
The infinite ground is not painted as a spatial load field: its total reaction
is reported numerically. No contact patch or stress distribution is invented.

The force is the accepted substep's average native resultant, including contact,
interfaces and their existing numerical work corrections. Opposing forces may
cancel within a body, so a low resultant does not prove low internal stress.
These colors do not show temperature, constitutive stress, fracture probability
or newly implemented damage. Supports carry loads before the ball arrives.
The scale is shared across the observed drop, not calibrated across experiments.

Missing observations, including a reopened scene without its old render journal,
are shown as unavailable. Replay carries the load receipt corresponding to each
accepted pose. Rejected private attempts never update the accepted heat map.
No rendering choice changes physical state, contact response or continuation.

## Eight representation families

**Physics views** gives direct controls for the existing rigid drop, limited
connected-cell experiment and private vibration-basis inspection. Preparation
does not advance physical time and does not admit reduced world motion.

The same menu explains the remaining observable acceptance tests: settled
structures waking after support removal; hinged mechanisms; qualified bending
and vibration; detailed fracture/deformation; conserved flowing water; heat
conduction; and fuel/oxygen-accounted reactions. These entries are not eight
finished physics modes. Sleeping, articulated motion, flowing, thermal and
reaction fields remain unavailable in this hosted world. Strong sheet impacts,
detailed ball response and runtime reduced deformation remain open.

## Verification

Eight scoped Windows Release CTests pass: native mode preparation, local CPU
Jacobian, CPU coupled world, high drop, hosted CPU gateway, CPU/CUDA private-trial
parity, playback and coupled view. The compiled mode-preparation suite also
passes on WSL Linux. Source registration passes 346/346. This is scoped
verification, not full repository regression or physical-phone certification.

The glass/oak/iron/ice sheet suite now independently checks each accepted body's
measured force against its momentum change and gravitational impulse, verifies
fixed-boundary reactions, and retains existing energy/P/L gates and exact restart.
Free-flight HTTP receipts have zero interaction load; private rollback preserves
accepted observations. View tests check cell mapping, missing/nonfinite data,
unchanged physical input, camera visibility and measured-frame replay.

Actual local browser testing completed a 10 m rigid drop/rebound and the low-energy
sheet contact, inspected colored cells/supports and exercised the direct physics
menu. New Render image identity and public browser/API tests must be checked
after publishing; local browser evidence alone does not establish deployment.

See [native vibration preparation](native-mode-preparation-checkpoint.md) for the
separate affine reference, conservation boundary and remaining admission gates.
