# Coupled contact reference checkpoint

R03 is active: a finite-mass sphere now exchanges impulses with the moving surface of a tetrahedral material patch. The sphere and material advance on the same clock, and accepted displacement and plastic state drive the recorded geometry. This is a small-strain CPU reference, not a completed glass-shatter, metal-dent, rubber, or realtime gate. The browser playground does not yet call this new path.

## Implemented behavior

`SpherePatchWorld` accepts a patch definition, sphere mass/radius and initial motion, gravity/forces, friction and explicit work/tolerance bounds. It uses the existing isotropic elastic, orthotropic elastic and J2 laws through `DynamicPatch`. Neither the contact kernel nor the material update dispatches on material names. The two drop-probe targets are explicitly fictional coefficient sets, not calibrated rubber or metal.

The force kick updates material and sphere velocities. Swept sphere/triangle queries find the earliest closing surface event during the linear drift. Both objects advance to that event; the contact point's barycentric weights distribute the opposite impulse to the triangle's nodes. Fixed degrees of freedom report their support reaction. A friction impulse includes sphere spin and the mass of moving nodes. Further events consume the remaining step time.

Normal contact uses zero restitution at the discrete collision event. Rebound comes from the material's stored elastic energy and later forces. The instantaneous normal projection has a measured nonnegative kinetic-energy loss; it is a numerical contact-model assumption requiring spatial convergence, not a measured physical damping law. No explosion force, position correction, prescribed rebound speed, or material-name override is applied.

Contact events, sweep work, external work, contact loss, stored energy, plastic dissipation, linear momentum residuals and contact-impulse angular residuals are reported. The angular check covers contact impulses and support reactions only; it is not a proof of full small-strain pipeline angular conservation. The step commits sphere motion, nodal displacement/velocity, constitutive history, revisions and time together. Geometry, validity or work failure rejects the entire step and retains diagnostics.

## Collision failure and correction

The first full-duration probes stopped near the first rebound at approximately 0.0126 s because conservative advancement exhausted its iteration budget. Halving the timestep reproduced the same failure time. Recordings stopped at the first bounce would have hidden this defect.

The corrected query uses the current separating support plane and the largest projected vertex closing speed, rather than a bound dominated by tangential speed. It advances conservatively toward physical contact and uses the declared distance tolerance as a stopping band. Advancing toward the outside of that same band had caused asymptotic stalling. Rigidly translating triangles retain an exact face/edge/vertex sweep. Invalid geometry and exhausted budgets remain explicit failures.

The probe uses a 1 micrometre contact band and a 10 micrometre maximum penetration guard. These values are unchanged by the convergence fix. The general API defaults are smaller. Rejected sweep diagnostics include the triangle, its positions/velocities, sphere state, query duration, iteration count and distance for reproduction.

## Recorded experiment

`banjo_sphere_patch_probe` drops a 12 mm radius iron-density sphere from rest with 0.5 mm clearance above an 80 by 20 by 80 mm supported block. Both bodies receive gravity. The target density is 1000 kg/m3, Young's modulus 1 MPa and Poisson ratio 0.25. One target is linear elastic; the other uses J2 yield stress 1.2 kPa and hardening modulus 20 kPa. These soft fictional coefficients keep this reference experiment inside its declared small-strain scope. Both cases record the complete requested 0.1 s; neither stops at its first rebound.

The output contains numeric input properties, reference mesh, accepted sampled positions and sphere motion, full-duration counters and energy/momentum evidence. Optional timestep and mesh refinement preserve the physical inputs. Final displacement while the body is still loaded or vibrating is not an unloaded residual dent.

## Acceptance boundary and next work

The tested slice covers contact timing, no tunneling, reaction/impulse accounting, passive friction, no normal-induced sphere spin, transactional failure and full-duration elastic/plastic trajectories. Numerical energy residual must be assessed cumulatively and under timestep refinement; a small per-step value alone is insufficient.

R03 remains open until spatial contact response and energy transfer converge across materials and resolutions. Next add an accuracy-controlled timestep strategy and qualify mesh/contact discretization. R04 still needs objective finite-strain and viscoelastic laws. R05 needs unloaded, retained impact dent geometry with real material coefficients. R06 needs stable progressive fracture. R07/R08 must connect accepted dynamic state to persistence, public experiment contracts and actual playground playback. R09 needs measured active-world budgets; fast replay is not realtime physics. All nine original workstreams and 40 mechanics remain retained.

## Measured checkpoint results

Every row completes the full 0.1 s. The timestep fraction multiplies the mesh's conservative material stability limit. All targets use the same physical input values across resolutions. Values are model output, not physical calibration.

| Mesh nodes / tetrahedra | Timestep fraction | Elastic peak upward speed (m/s) | J2 peak upward speed (m/s) | Elastic / J2 normalized cumulative energy residual |
|---|---|---|---|---|
| 18 / 24 | 0.05 | 0.063047 | 0.046328 | 8.014% / 7.295% |
| 18 / 24 | 0.0125 | 0.063026 | 0.046322 | 2.084% / 1.934% |
| 18 / 24 | 0.00625 | 0.063022 | 0.046320 | 1.055% / 0.977% |
| 75 / 192 | 0.0125 | 0.088847 | 0.045477 | 7.578% / 4.699% |
| 196 / 648 | 0.0125 | 0.093912 | 0.045940 | 12.055% / 6.613% |

The normalized residual divides the absolute cumulative energy imbalance by absolute accumulated external work plus contact dissipation plus final mechanical energy. It is a declared comparison metric, not a relative error oracle for the true solution. For the coarse mesh, time refinement reduces this metric from about 8% to 1%. At finer meshes the contact response and integration error change substantially. Spatial acceptance therefore fails; this checkpoint leaves R03 open. At the finest sampled mesh J2 final displacement is about 0.182 mm while the target is still loaded/vibrating; this is not proof of an unloaded dent.

Fine-mesh recordings took tens of seconds for 0.1 simulated seconds. These one-shot times include output and concurrent checks, but establish that this explicit reference is not a realtime engine. The next gate needs contact/time accuracy control and a measured integration strategy before active-world optimization.

The same-geometry glass, orthotropic oak and J2 iron contact controls use the same iron-density sphere, initial velocity and timestep (1.0234e-7 s), reaching contact in all three cases. These low-energy controls verify numeric scale and coupling, not fracture, wood failure or iron dents. Separate tests cover a 500 m/s full-thickness traversal, free/support impulses, spin/friction, initial overlap, late rollback after tentative impulse work, and work-budget exhaustion.

Windows MSVC 19.44 Release: full build and all 61 native suites pass (85.94 s). A subsequent small-geometry normal fix passes all three affected suites, including nine geometry cases and eight coupled-world cases; the full drop's sampled positions remain exactly unchanged. The 8 Python material-descriptor and 4 native property-path tests pass. No UI source was changed and no new visual-playground validation is claimed. Original nine goal IDs and all 40 unique mechanics were checked as retained. Changed-file credential and whitespace checks pass.

Machine-readable measurements are in [coupled-contact-results.json](coupled-contact-results.json). Build the `banjo_sphere_patch_probe` target; run `banjo_sphere_patch_probe evidence.json 0.0125 1` for the base mesh, changing the last argument to 2 or 3 for spatial refinement. The first argument after the output path is the timestep fraction; the following argument is mesh refinement. Generated recordings retain actual mesh positions, diagnostic failures and numeric inputs.
