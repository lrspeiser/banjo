# Conservative material contact: development checkpoint

This branch is an experimental continuation of the working material laboratory. It is
not yet a validated continuum/fracture simulator. Keep main as the tested baseline.

## Changes in this checkpoint

- Rolling diagnostics measure tangential contact-point velocity, not just whether
  the sphere rotates. They classify supported motion as resting, rolling, or slipping,
  and distinguish airborne motion. The default striker starts with omega = n cross v / r.
- `L` in the viewer switches the launch between no-slip spin and zero spin. Readouts
  report actual translation, rolling-surface speed, and contact slip.
- Rolling resistance applies a resisting angular impulse (`mu_rr N r dt`) rather
  than forcibly assigning the no-slip angular velocity. Contact friction determines
  subsequent sliding/rolling behavior.
- Rigid-body damping is no longer derived from internal material damping. Internal
  damping must not act as unexplained aerodynamic drag on a rigid ball in vacuum.
- Activating sphere contacts are made sensor-like in the Jolt callback. The callback
  changes contact settings only; body lifecycle changes occur after Jolt Update.
- The experiment disables its synthetic impact pulse. Point material nodes exchange
  normal/friction impulses with a finite-mass rigid sphere, including angular reaction.
  The updated sphere state returns to Jolt between synchronized microsteps.
- Contact-energy dissipation and reaction-impulse diagnostics were added. These do
  not constitute a complete energy audit of the XPBD/fracture/handoff pipeline.
- Finite support-footprint checks were added to material/debris support and rolling
  resistance; arbitrary-shape environments are not implemented.

## Locally verified

The Linux headless/core build succeeded and all seven CTest executables passed.
The runtime suite includes 12 checks; the new conservative-contact suite includes
seven checks. Verification covers analytical elastic point/sphere collision,
frictional momentum conservation and non-increasing kinetic energy, Galilean
invariance of contact, speculative normal contact, measured rolling/sliding,
slide-to-roll convergence, rolling resistance as torque, internal damping versus
vacuum drag, sensor handoff, and contact-driven fracture.

One frictionless runtime test initially used an excessively tight angular tolerance.
Measured angular drift was 2.611e-5 rad/s (surface speed 6.53e-6 m/s at r=0.25 m).
The test now permits less than 1e-5 m/s of spin surface-speed drift, with an explicit
comment, while still checking unchanged COM speed. This records the numerical
precision bound rather than claiming exactly zero spin.

The initially sliding solid-sphere test starts at 2 m/s with no spin, and measured
1.42857 m/s after settling into rolling (the analytical result is 2 / 1.4 m/s).

The default headless collision completed with 1,285 material nodes, 17,097 initial
bonds, 17,076 broken bonds, 1,264 components, 64 Jolt fragments, and 1,200 debris
particles. All 163.6089 kg of represented target mass was accounted for.
**The severe over-fragmentation is a known limitation, not a realistic glass result.**

The visual code was edited but was not locally compiled or rendered for this
checkpoint. The standard GitHub CI workflow builds and captures the viewer; inspect
that run before treating the graphical build as verified. macOS/Windows execution
has not been verified here.

## Build and test

```sh
cmake -S . -B build/contact-test -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/contact-test --parallel 4
ctest --test-dir build/contact-test --output-on-failure
./build/contact-test/banjo_lab
```

For a headless machine add `-DBANJO_BUILD_LAB=OFF` at configure time and run
`./build/contact-test/banjo_headless`.

## Codex continuation priorities

1. Inspect CI and compile/run the graphical viewer. Confirm `L` and the motion
   readouts work and do not overlap existing controls.
2. Audit synchronized contact integration and split positional correction, including
   whole-system angular momentum and energy under contact, gravity, fracture, and
   rigid-fragment handoff. Pairwise impulse tests are not a whole-system proof.
3. Fix over-fragmentation through calibrated constitutive laws and fracture-energy
   accounting; do not restore an explosion pulse or precut pieces for visual effect.
4. Validate timestep, voxel-size, impact-angle and density sweeps. Improve arbitrary
   rigid-shape contact, material self-contact, floor-triggered activation, striker
   fracture, repeated fragment activation, and contact support detection.
5. Audit lattice/rigid moment-of-inertia equivalence during activation and fragment
   conversion, including finite cell inertia and internal angular momentum.
6. Integrate precomputed solver outcomes only behind complete material/solver/state
   keys and applicability checks. The existing analytical projection cache is not
   an authoritative cached fracture simulation.

Do not label every declared material parameter as implemented. This remains an
approximate material law and contact solver with explicit numerical stabilization.
