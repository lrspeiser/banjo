# Visible material and product-use QA

September 20, 2026. Host implementation on base `11e7d84`; existing Windows
Release binaries, hashed separately in [measured evidence](evidence/qa-demonstrations.json).
No native material/contact law, baseline or acceptance band was changed.

## Material impacts: `/qa`

The initial view now offers a four-case hard-strike demonstration: identical
120 x 120 x 20 mm specimens of glass, oak, iron and concrete hit by the same
40 mm iron ball at 12 m/s. A gentle set compares glass/oak/iron at 4 m/s.
The full 96-case matrix remains available, including all eight materials.
Cases are fixed in advance, not chosen from the current outcome.

The measured hard-strike cases fragment glass, oak and concrete; iron remains
connected without broken bonds. The gentle glass/oak/iron cases remain intact.
All seven match the existing baseline. The complete 96-case matrix also passes
the unchanged baseline and alignment checks: all eight materials, three
thicknesses and four speeds. Maximum horizontal offset is zero. Surviving a strike remains a useful
answer and is described explicitly, rather than looking like an unrun test.

The fixture is measured from native opening-frame geometry: ball center must
be on the specimen's x/z center within 1e-8 m, with 2 mm surface clearance
within the same tolerance. Missing striker/geometry, a side offset or overlap
fails the run. All seven measured offsets are zero. This is a deterministic
fixture tolerance, not physical accuracy. These recordings begin at the
declared impact speed; they do not include a simulated free fall.

The viewer frames the full recorded trajectory, automatically replays selected
results, offers slower playback and a first-response jump, and separates
physical outcomes from regression status. Older saved runs explicitly say
their alignment was not checked. All movement remains recorded native poses.

## Pick use: `/tool-qa`

Six isolated trials use the same monolithic pick in glass, oak and iron, over
dry soil and rock. The 800 x 40 x 40 mm haft and 40 x 280 x 40 mm arm fuse into
27 native 40 mm cells. This is a reference product, not a user's Workshop
assembly; it does not test a separate head-handle fixing.

The native hand has an 800 N force cap and 60 N m wrist. It requests a 110-degree
raised swing with 2 m/s grip target speed and a four-second time limit. This
target is not imposed body speed. All runs last 4.5 s at 1/240 s; recordings
sample native transforms at 1/120 s. Native cells are rendered individually so
the open pick shape is not replaced by its solid bounding box. The ground
view is a section of the actual flat surface, shown from the side by default.

| Pick | Mass (kg) | Soil penetration (mm) | Closing speed (m/s) | Ground work (J) | Rock outcome |
|---|---:|---:|---:|---:|---|
| Oak | 1.2096 | 65.74 | 4.66288 | 5.05002 | Stopped; zero excavation |
| Glass | 4.32 | 123.10 | 4.62715 | 15.09977 | Unsupported hard-point rock excavation |
| Iron | 13.59936 | 193.40 | 6.84463 | 48.06469 | Unsupported hard-point rock excavation |

Equal volume retains the expected density-dependent masses. Tool mass residual
is zero in all six. Peak measured hand force is below 800 N in all six. This
does not close a mechanical/thermal energy ledger. All tools report whole and
zero dent in these particular runs; the material range supplies examples of
actual fracture. These soil trials measure penetration, without the lever and
extraction phases required to collect loosened soil.

Every trial must contact the declared ground within 250 mm horizontally of the
target. Soil must penetrate at least 30 mm and no more than the 200 mm point
length plus one 40 mm cell. Rock must report no penetration or excavated mass.
Native hand-force and mass bounds are independent checks. Missing contact
fails; pending material refinement stops as unresolved. `unsupported` is
preserved in individual and aggregate reports and never displayed as a pass.

An initial 4 m/s grip-target experiment missed the ground with the glass pick
because the bounded swing did not maintain its intended orientation. The final
2 m/s command is shared across all three materials and all six fixtures; there
is no per-material motion override. The missed fast-swing case remains a
controller limitation, not evidence of tool survival or material strength.

## API and verification

| Route | Contract |
|---|---|
| GET `/api/tool-qa` | Fixed catalog, setup hash, limitations and engine availability |
| GET `/api/tool-qa/runs` | Saved summaries |
| POST `/api/tool-qa/run` | `{}` for six cases, or `{case_ids:[...]}` for a unique nonempty subset |
| GET `/api/tool-qa/runs/{run_id}` | Progress and results |
| GET `/api/tool-qa/runs/{run_id}/{case_id}` | Result |
| GET `/api/tool-qa/runs/{run_id}/{case_id}/request` | Executed setup and commands |
| GET `/api/tool-qa/runs/{run_id}/{case_id}/playback` | Native recording, including partial recordings on failure |
| POST `/api/tool-qa/cancel` | `{run_id}`; cancels only the owned trial process |

The existing local Host/CSRF authentication applies. No arbitrary executable,
script, path or custom recipe is accepted. Native startup and execution share
the trial watchdog's 45-second deadline. Reports use the existing atomic QA
artifact store; they retain setup/source hashes, measurements and native replies.
The user's live room is never opened or stepped by these routes.

```
BANJO_TRIAL_ENGINE=build/ci/banjo_live_world_run python tests/tool_qa_tests.py -v
python scripts/tool_qa.py --engine build/ci/banjo_live_world_run --out build/ci/tool-qa
python tests/material_qa_tests.py -v
```

The CLI returns success for operationally complete trials with explicit
unsupported boundaries; failed, cancelled or unresolved runs return nonzero.
CI separately checks the exact supported/unsupported case outcomes and retains
recordings. Windows checks cover all six native tool cases, HTTP isolation,
input/path rejection, cancellation and rigid cell transforms. Material tests
cover off-center starts, overlapping/gapped starts, absent striker and unchanged
baseline identity. Browser checks cover running, selecting, playback, contact
jump and explicit unsupported display with no observed console errors.

After integration with the concurrent starting-world update, 79 Python tests
pass (6 tool QA, 14 material QA, 14 physics trials, 11 API documentation and
34 playground tests). JavaScript syntax checks pass and all 275 native source
files are registered. The native evidence is Windows-only; CI runs are not
claimed by these local checks.

## Remaining product gates

This exposes an existing experimental `ground-work-v1` law; it does not implement
rock mining, wet soil, wear, calibrated fracture, compound tool joints or
automatic testing of a selected Workshop product. Next: carry the actual
Workshop tool and its interface into an isolated use trial, retain damage
through repeated strikes, and implement/qualify rock excavation before claiming
a built pick can mine stone. Every new product-use demonstration should define
its target, contact evidence, normal/overload conditions and unsupported result.
