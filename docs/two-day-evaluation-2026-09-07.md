# Two-day evaluation, 2026-09-06 to 2026-09-07

This is an honest account of what the last two days produced, what they wasted,
and why. It exists because the owner could not load anything from those two days
into Banjo and watch it work in 3D, and that is the only standard that counts.

## What is real

Verified, on `main` (pushed):

| commit | what | proof |
|---|---|---|
| `e5854ff` | CI guard: no source file can sit uncompiled | passes clean, fails on a planted orphan, catches stale allowlist |
| `da7127c` | Tetrahedron contact query fixed and built | 85/85; test file byte-untouched |
| `35377ac` | Convergence study: fracture converges nowhere in the network lane | reproduced independently: at-rest glass breaks 322 bonds from 0 J |
| `99f2995` | Glass "shatter" was the floor injecting 1.75e7 J; three defects fixed | explicit lane reproduces published numbers to every digit after refactor |
| `73d570d`, `1d2d89f` | Predict-then-measure physics suite; trust panel | 15 cases; sealed predictions; invariants separate from model grades |

Verified, committed locally, not pushed:

| commit / branch | what | proof |
|---|---|---|
| `5603b8a` | Network lane runs on its own stability clock; at-rest lattice now stays at rest | glass 322 -> 0 broken, iron 1.13e6 J -> exactly 0 |
| `agent/implicit-fracture` | Implicit Newton/GMRES lane can fracture; one criterion shared by both lanes | 85/85; 17,097-bond run lands on the identical broken set |
| `agent/realtime-envelope` | Where 1x realtime sits: implicit lane at 365 nodes, 1/120 s | reproduced: 4.064 s wall for 4.0 s simulated |
| `agent/playground-rebuild` | Builder tab; cubic-cell guard; cost estimate before running; refusal with reason | 7.5:1 geometry refused; 6 mm pane refused with nearest buildable |

Measured but not built into anything (numpy in a scratch directory):

- The pre-fracture response is linear to 4 decimals, and a basis built once from
  the lattice's eigenmodes reproduces the solver's strain field with the solver
  converging *toward* it under refinement (1.49% -> 0.64% -> 0.17%).
- The fracture cascade is 61 discrete rounds, not thousands of timesteps.

## What was wasted

- About six hours of engine compute on scenes whose cells were 7.5:1 slabs. The
  engine assumes cubic cells: each cell collides as a sphere of radius 0.49 x its
  smallest spacing while carrying the mass of the whole box, so those fragments
  collided over 13% of their width and passed through each other. Two published
  3D artifacts (the five-strike viewer and the drop lab) are built on that
  geometry and are worthless. Nothing refused the geometry because nothing
  checked it.
- A job estimated at 1.5 hours was allowed to start, because the estimate was
  displayed but not enforced.
- Repeatedly, validations and measurements were reported as though the engine
  had changed. The modal-basis result is true and important; it made the engine
  faster by zero microseconds, and it was presented in a way that let the owner
  believe otherwise.

## Root causes

1. Authoring geometry the engine silently accepted. Fixed: `validate_network_geometry`
   now refuses aspect > 2:1 (`agent/playground-rebuild`).
2. Cost invisible until after the wait. Fixed in part: the Builder shows an
   estimate. Not fixed: nothing refuses to run. That is the next change.
3. Measuring instead of shipping. Not fixed by any code. Fixed by the goal below:
   no stage counts until it can be loaded into the playground and watched in 3D.

## The controlling fact

Under the owner's rule -- no job may take more than 1.1x the simulated duration
of the whole interaction, through to rest -- today's engine can run:

- rigid bodies (Jolt): yes, well inside 1x
- the implicit elastic lane, no fracture, up to 365 nodes at 1/120 s: 1.00-1.03x
- any fracture, on either lane: **no** -- 3,000x to 10,000x over

So no fracture scene is runnable today. The only measured route to instant
fracture is the precomputed basis, which is unbuilt, and whose fourth step
(updating the basis across the 61-round cascade) is a research bet. The goal is
therefore structured so every stage produces something watchable, and the first
two stages are reachable with what exists.
