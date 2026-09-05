# Local fracture propagation and surviving fragments

September 5, 2026. Source `334454d`, local codex/physics-foundation, not main. This extends the opt-in reference solver; the graphical bowl still has no enabled fracture path.

## Owner requirement

An impact must load the portion of matter it actually contacts. Connected material transmits forces and motion; local damage changes the subsequent loading. Additional failures must arise from those evolving states. A first break must not automatically break every connection or activate pre-authored shards. Intact regions remain intact, and detached pieces retain internal state so they may fracture later. Preserve this requirement when promoting fracture into the crafting bowl.

## Implemented

`tryRuptureCascade` advances one finite impactor and the complete surviving elastic connector network with the existing compliant contact owner and energy-backed tensile rupture. After each accepted step it removes only locally failed edges, advances physical time, and continues solving the remaining network. Disconnected components keep their nodes, velocities, finite-cell spin and live bonds; they are not prematurely replaced with rigid pieces. Their stored deformation/motion can cause later internal failures.

A rejected contact or rupture trial recursively subdivides the time interval. The first accepted subinterval changes the state/topology used by the next. Recursion controls numerical refinement; it is not a rule that breaks neighboring material. Each further rupture still requires its own current tensile deformation and Gc-area work. Simultaneous locally justified failures are allowed; the engine does not impose one break per frame.

A stiffness/mass-based characteristic step cap limits coarse stepping through the network. This is a numerical resolution control, not proof of physical wave speed or a guarantee that every interior threshold crossing is found. One event-overshoot budget applies to the entire advance. Evaluation count, depth and minimum step are bounded. Any failed overall interval rolls back the complete material and impactor, including already computed candidate failures; its events, elapsed time and work are not published. A discarded-event count identifies aborted candidate work without reporting it as committed fracture.

Accepted event records include time relative to the advance, original failed-edge IDs, resulting component sizes, fracture work and numerical event overshoot. They allow topology history reconstruction against the original network. They are not a complete persistent fragment-lineage or contact replay format.

## Evidence

Four affected promoted suites pass: cascade, energy rupture, conservative step and compliant step (4.19 s). The final cascade suite also passes in the legacy build (0.45 s). The suite covers partial/cascading fracture, continuation inside a detached piece, finite-system energy/momentum, full rollback after candidate fracture, timestep comparison, high bulk velocity without local damage and glass/oak/iron early wave response. Windows/MSVC Release; no new native fracture claim.

The main fixture has eight equal material regions in a uniform chain, seven identical connectors, 10 micrometer spacing and 1e-10 m2 interface areas. A finite sphere impacts one end. No edge is marked in advance to fail. This is a microscopic ideal connector reference, not a whole glass ball or a calibrated bulk-material fracture threshold.

| Glass impactor speed | Failure events | Result |
|---:|---:|---|
| 4 m/s | 0 | All eight regions remain connected |
| 60 m/s | 2 | First 6 + 2 regions; later 6 + 1 + 1 |
| 120 m/s | 3 | Ends as 4 + 2 + 1 + 1; surviving multi-region pieces remain |
| 240 m/s | 5 | Ends as 2 + 2 + 1 + 1 + 1 + 1; even this case does not force every edge to break |

At 60 m/s the first event is about 19.9874 ns, breaking edge 5 and detaching the two-region end piece. At about 20.7203 ns, edge 6 fails inside that detached piece. The six-region core retains its five live connections. Total fracture work is 1.6e-9 J, and the energy residual including separate event loss is 4.18e-21 J. The initial load is at the opposite end: transmission/reflection through the network determines where failure first occurs, not a nearest-edge destruction traversal.

With maximum steps of 20 ps and 10 ps, the event order and surviving six-region core agree. Event times differ by 0.186 ps and 0.354 ps. This is bounded temporal evidence for this fixture, not general spatial/topological convergence. The common stiffness cap remains active.

An exhausted 1100-evaluation trial includes candidate failure events but returns no committed events, time or work; caller poses, velocities, connectivity, step index and impactor state remain unchanged. A uniformly translating 1000 m/s network and impactor produce no fracture without local relative loading, despite large total kinetic energy.

Identical early-impact geometry, 60 m/s impactor speed, contact settings and 20 ps maximum step compare glass/oak/iron at 3 ns. Near-contact versus distant-end speeds (m/s):

| Material | Near contact | Distant end |
|---|---:|---:|
| Glass | 40.4009 | 6.34e-13 |
| Oak | 90.3691 | 3.87e-13 |
| Iron | 14.5171 | 6.04e-13 |

All remain connected at that early time. These results show resolved near/far response lag within this discrete reference. The implicit solver can produce tiny numerical tails; this is not an assertion of exact finite wavefront support. Oak and iron retain explicitly elastic reference behavior and are not silently assigned brittle fracture. Their anisotropy/plasticity remain unsupported.

## Remaining bowl work

- Compile occupied ball geometry and defensible fracture interface areas; retain compliance/strength/toughness compatibility and spatial refinement tests.
- Extend contact to curved bowl supports, other deformable/fragment surfaces and secondary object impacts under one clock/owner. This reference currently has one finite rigid impactor and no component/component contact.
- Keep detached pieces deformable while internal waves/damage remain active. Coarsen only under a measured, history-preserving rule, with mass/inertia, momentum and discarded internal energy accounted for.
- Refine event timing further, including crossings inside a step, and validate broader orientations and loading modes. These chain results do not close the whole-ball fracture gate.
- Connect the accepted path to real crafted balls and verify native partial fracture, cascading failure, landing and repeated impacts across the retained materials.

The old fracture defects remain documented. No precut shards, bulk break command, synthetic excitation or arbitrary launch velocities were introduced. No API key or provider configuration changed in this checkpoint.
