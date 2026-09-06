# Experiment logging and review checkpoint — September 6, 2026

Implemented execution events (`events.jsonl`), deterministic measured diagnostics, and on-demand GPT evidence review in the embedded 3D playground. Logs retain requested versus completed steps, solver/state/material validity, reported damage and energy fields, compiled package hashes, executable/source hashes, sampled motion checks, errors, and elapsed time. Analysis stores its exact input, input/prompt hashes, model, token usage, interpretation and next steps. API keys stay server-side; upstream error bodies are not exposed. Repeated review clicks reuse the saved result.

Use **View measured evidence** and **Analyze this run with GPT** below the authored controls in the scrollable 3D sidebar. Review is separate from native execution and never modifies the experiment. The viewport stays fixed while the evidence is inspected.

## Timing regression

The height control raised the drop to 1.391 m but previously left a 0.5 s recording. Ideal free-fall takes 0.53253 s; the old recording ended with a 0.159641 m gap and no velocity reversal. Height reruns now extend the observation through estimated fall plus 0.5 s, without shortening longer recordings. Other physical parameters are retained; the extension is disclosed in the plan explanation.

Corrected job: `1939654628ee422d82830172b213c50a`. Matched glass/oak/iron rigid panels, 80 mm iron balls, 1.391 m drop, fixed dt 1/480 s, 499 steps, final recorded time 1.039583 s, 101 samples. All lanes reach a sampled approximate gap of 0.0012501 m and show vertical velocity reversal. Native process/recording/diagnostics wall time was 0.0259964 s (one local measurement, not a game-world benchmark). These are rigid targets: fracture and deformation are disabled.

## Live review results and limits

Three actual gpt-5-mini calls exercised the before/after path and strengthened prompt. The final review took 8.6019 s and used 7,104 tokens. Its verdict was `insufficient_evidence`: it recognized completed execution and motion consistent with rebound, while declining to establish contact forces or validated material response. Early review suggestions included nonexistent options; the final instructions explicitly prohibit invented switches and treating validation flags as runtime settings. LLM conclusions can still be mistaken and are labeled interpretation. No automatic paid retry occurs.

The native report remains authoritative. Sampled axis-aligned gaps are approximate when targets tilt, and proximity/velocity reversal are not solver-contact force measurements. Direct contact manifolds, normal/tangential impulses, local stress/damage propagation telemetry and full transfer accounting are the next instrumentation work. General scene-specific expectation checks beyond bounded comparative drops remain to be added; unknown measurements remain unknown. No calibrated fracture or broad realtime claim is made.

## Verification

98 Python tests: 97 passed, one existing Windows archive/symlink privilege skip. Includes mocked HTTP/control/archive execution, diagnostic timing/sweep/terminal-frame checks, review schema/error/size tests, persistence/redaction/caching, scene/drop builders and typed planner. Native recorder cases and the exact live three-material timing regression ran; no native physics law changed and the complete 58-suite C++ run was not repeated for this Python/UI checkpoint. JavaScript syntax and diff whitespace checks pass. Browser verification exercised Play, frame scrubbing, evidence loading and a real GPT review; no browser errors reported. Exact saved-input SHA-256 and cached-review reuse were verified against the live API.

API: `GET /api/jobs/{job_id}/diagnostics/{case_index}` returns measured evidence. `POST /api/jobs/{job_id}/analyze` accepts `{"case_index":0}` with the existing local session token and returns a structured saved review. GPT input is capped at 64 KiB; oversized evidence is rejected. Events and reports remain on disk under the ignored per-job run directory. Old recordings can be analyzed, but source events absent from historical runs cannot be reconstructed.

All nine platform goals and 40 mechanics remain retained. This improves observability and corrects a control-duration bug; it does not complete the physics platform.
