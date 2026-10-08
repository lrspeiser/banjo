# Force/contact phase work audit — October 7, 2026

## Scope and implementation

Experimental CPU measurement on main base
`cdbbd2dd1afa687f0d737d8858a64d07cd98ff2e`, Windows x64 / MSVC Release,
default Jolt rotation. This advances the sustained-contact investigation in
[the previous checkpoint](double-geometry-contact-checkpoint.md). The
[complete editable live-world objective](world-physics-action-plan.md) remains
unfinished. No contact response, constitutive law, acceptance tolerance,
outcome key or browser-world solver is replaced by this checkpoint.

`physics/ForceContactPhase` measures three actual velocity states at identical
geometry, mass and inertia: before forces, after forces, and after contact.
It returns both sequential operator work and work evaluated at the common
force/contact phase midpoint. The force and contact cross-work terms have
equal and opposite sums. Linear/angular impulse and kinetic-work identities
are reported, including rigid spin with the actual world inertia tensor.
It refuses altered geometry/mass/tensor, nonunit/nonfinite orientation,
nonfinite kinematics, spinning material points, ill-conditioned inertia,
empty inputs and more than 1,024 translating points / 256 rigid members.

This is an attribution measurement, not a new normal/friction/restitution
law. In particular a small, zero, or positive signed concurrent contact work
does not establish physical dissipation, calibrated contact or conservation
of a complete surrounding world. Supports, external work, fracture losses,
bond corrections and numerical transfers still need their existing accounts.

The serial-double CPU Verlet backend retains the actual starting velocities
of each force half-kick and exposes their movable node identities only inside
the coupled callback. The possible bounded snapshot allocation is included in
the reversible-trial payload check. Scope is cleared on success and exception;
queries outside the callback or on unsupported backends refuse.
`DoubleFixedContact` audits both actual force/contact phases, retains the
sequential receipts, and checks that the phase contact work equals the existing
source-plus-target contact transfer. Full/fine diagnostic audits survive a
refused comparison without committing state. The accuracy controller continues
to check its existing raw operator ledgers and all state/topology bounds.

An intermediate diagnostic mistakenly used a partial `download()` as a source
of immutable node metadata and omitted the material DOFs. That output is not
evidence for this checkpoint. The corrected direct backend mobility query and
receipt equality preflight prevent that omission. Final evidence includes both
the actual material and source velocity states.

## Independent oracles

The registered/compiled `banjo_force_contact_phase_tests` covers:

- Two masses, 2 kg and 3 kg, starting together at 4 m/s. A -20 N force on the
  first mass gives the exact common acceleration -4 m/s². Maintained ideal
  normal contact does zero work. Separate force/contact operators report a
  projection loss of `60 h² J`; its contact cross-work term is `+60 h² J`.
- Coupled rotary inertias 2 and 3 kg m² starting at 5 rad/s, with -6 N m
  applied to the second: common acceleration -1.2 rad/s², zero ideal
  constraint work, and sequential projection loss `2.4 h² J`.
- Halved force intervals, Galilean translation with correct external-work
  transformation, and an unforced impact that retains its actual -8 J loss.
- Late malformed inputs, altered states, mass/inertia/orientation failures,
  nonfinite velocities, scope budgets and unchanged input state on refusal.

These analytical oracles are material-neutral. General material results use
the matched comparative experiment below.

## Matched glass/oak/iron measurements

[Machine-readable final cases, probes and fingerprints](evidence/material-lab/force-contact-work-results-20261007.json).

Same 40 mm cells, 120 mm target cube / 27 nodes / nine clamps, iron head widths
40/120 mm, laboratory oak handle, material-derived source masses
2.2835199755/6.3129599429 kg, initial source velocity (6, .2, .1) m/s, and zero
gravity/damping as the preceding experiment. Target glass/oak/iron densities
are 2500/700/7870 kg/m³ and Young's moduli 70/12/211 GPa; target masses are
4.32/1.2096/13.59936 kg. Oak is an uncalibrated isotropic axial comparison,
not gameplay wood or a grain law. Existing strength/plastic declarations and
their limitations are unchanged.

Each case runs 500 accepted intervals, then restores full/two-half trials at
100/50/25/12.5 ns. All 24 probes refuse the retained accuracy gate and restore
both states. Across all 144 contact phases, zero witnesses meet the existing
0.5 m/s restitution threshold. Repeated restitution is therefore not the cause
in these captured states. Error scales approximately quadratically with dt.

| Target | Head | Raw full-step contact work at 100 ns | Common-phase contact work | Full/fine common-phase work difference |
|---|---:|---:|---:|---:|
| Glass | 40 mm | -1.611097 mJ | -0.901175 nJ | 0.226015 nJ |
| Oak | 40 mm | -0.351009 mJ | +0.258948 nJ | 0.129730 nJ |
| Iron | 40 mm | -1.404123 mJ | -14.849231 nJ | 0.620901 nJ |
| Glass | 120 mm | -2.334733 mJ | -0.885915 nJ | 0.444511 nJ |
| Oak | 120 mm | -0.398928 mJ | -0.703538 nJ | 0.352001 nJ |
| Iron | 120 mm | -3.540385 mJ | +0.733462 nJ | 0.366672 nJ |

Largest full/fine phase work identity residual is 5.72e-17 J. The cross terms
explain nearly all the apparent operator loss in these near-maintained normal
contacts. This supports a phase-consistent force/contact integrator and work
ledger repair; merely disabling restitution would not address it. Signed
nanojoule work still needs geometry/constraint error and friction attribution.

All six sustained fracture gates remain open. The 500-interval runs reach only
6.328–8.775 microseconds, break zero bonds and intentionally exit 1; required
duration remains 204.8 microseconds with actual fracture. Whole-system energy,
linear and angular accounts retain the previous 1e-10 J / 1e-9 SI bounds.
These measurements are not a fracture, useful speed or ordinary-world result.

## Verification and next implementation

Seventeen rebuilt scoped CTest entries pass in 53.33 s, including the new
analytical test, actual geometry/controller, source, native/material contact,
Verlet, external load and constituent/patch coverage. Fifteen actual build
targets produce those 17 entries; two contact entries are modes of one
executable. Exact verification is recorded in the evidence file. Source registration is 322/322 across 31 CMake files.
No rendering/input code changes, interactive installation, full regression,
physical phone, native custody transition or other-platform claim is made.

Next implement the force/contact kick with a common work midpoint, including
actual external/gravity/actuator work and per-fixing/support reactions. Separate
true impact restitution from maintained-contact force response, retain signed
geometry/constraint and numerical error, and derive the accuracy comparisons
from that integrated physical account. Do not delete the failed operator
experiments, hide their cross-work terms, grant energy, relax bounds or classify
every negative operator work as physical dissipation. Qualify all six sustained
fracture cases and broad-patch cost before wiring fracture/constituent debris
into ordinary live 3D actions. The remaining deformation/structures/tools/
mechanisms and water/heat/energy/pressure scope is unchanged and unfinished.

```powershell
cmake --build build/local-cell-tools --config Release --parallel 4 --target banjo_force_contact_phase_tests banjo_double_geometry_contact_tests
ctest --test-dir build/local-cell-tools -C Release -R '^banjo_(force_contact_phase_tests|double_geometry_contact_tests)$' --output-on-failure
./build/local-cell-tools/Release/banjo_double_geometry_contact_tests.exe --probe 500
python scripts/check-source-registration.py
```

The probe command intentionally exits 1 while the acceptance gates remain open.
Raw logs and binaries stay ignored under `build/`; publication revision is
recorded in Git. Running browser worlds and saved gameplay are unchanged.
