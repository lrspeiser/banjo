# Automatic creator assistant checkpoint

Tested implementation: `ae821677da0e430695417a753921e105273321cc`, local `codex/physics-foundation`. The Windows workshop now makes an automatic Codex request from Ask assistant, receives a proposed recipe or clarification, independently validates it, and leaves Build to the user. The model does not advance physics or own the inventory. All 15 Windows CTest executables pass. The full platform goal remains active; new shapes, safe modifications of existing objects and the deeper physics gates remain open.

## User flow and reproduction

Build as in the [creator checkpoint](creator-checkpoint.md), then run `banjo_workshop`. The workshop detects `codex.exe` on PATH. The tested CLI is **0.153.3**, already signed in with ChatGPT. Install/sign in through the normal Codex CLI if needed; no API key is embedded or copied into Banjo. The [official non-interactive guide](https://learn.chatgpt.com/docs/non-interactive-mode) documents saved-auth reuse, structured output and scripting.

From the Windows repository root:

```powershell
& ./build/win-integration/Release/banjo_workshop.exe --workspace build/my-workshop --assistant-exe (Get-Command codex).Source
```

Collect a material, type a request, and press Ask assistant. A valid reply updates the preview and independently calculated cost without spending inventory. Build commits the object and allocation. Run/Space starts physics; another Space pauses. A normal workshop opens paused so saved objects do not move while the user is authoring. F follows the last object; F12 saves `workshop.png` in the workspace. In the request field, Ctrl+A clears the prompt, Ctrl+V pastes supported text and Backspace deletes. The initial editor accepts at most 500 ASCII characters; full Unicode/editing controls are future UI work.

Use `--assistant manual` to retain the earlier file bridge. On platforms without this Windows process adapter, or when Codex cannot be found, the manual bridge remains explicit. This checkpoint is not Linux/macOS automatic-assistant validation. Provider/model configuration remains outside the physics layer; this version uses the CLI's default model with user config ignored. The JSONL evidence does not identify a model ID, so these are CLI-workflow results, not claims about a particular model release.

The provider needs a supported installed CLI, valid account authentication and network access. A missing provider, failed process, invalid/stale response or output limit produces a retryable error. The request folder retains diagnostics. Failures do not debit inventory; there is no automatic retry loop that silently spends more model usage. Cancelling stops the owned local process tree, but cannot promise to refund remote work already performed.

## What changed

`CodexAssistant` receives a serialized snapshot, current design and previous explanation. It has no mutable `CreatorWorld` reference. It writes a unique `assistant-<request_id>` directory, starts a background Codex process and polls without waiting for completion. `ChildProcess` invokes the executable directly with an argument vector encoded for Windows, never through cmd or PowerShell. Only its three standard streams are inherited. A Windows job owns the process tree and ends it on cancellation, destruction or failure.

The invocation selects read-only execution and no approvals, ignores user configuration, disables project-document injection and switches off shell execution, shell snapshots, apps/plugins, browsing, computer use, hooks, agent spawning, image generation and related execution helpers. Code-mode execution fails closed with its host disabled. The configuration uses supported CLI overrides; see the [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference). This is a constrained local provider adapter, not a complete sandbox for arbitrary published worlds or untrusted provider executables. Managed account policies still apply.

The request is passed through stdin; accepted output is read only after the process exits successfully. Schema 1 replies contain exactly `reply_version`, `request_id`, `status`, `explanation` and `recipe`. A `proposal` requires a recipe; a `clarification` requires null. The bounded parser rejects extra, missing, duplicate, malformed or mismatched fields. The sphere/compiler/inventory rules are then checked again against the current world, including resources that may have changed while the model was working. Structured output cannot bypass that validation.

Each request has a five-minute wall-clock deadline checked during polling, a 1 MiB limit per output file checked at polls and bounded document nesting. These are not hard disk quotas against a malicious executable. Request folders must be new and IDs may contain only letters, numbers, hyphens and underscores. The process wrapper preserves spaces, embedded quotes, trailing backslashes, metacharacters and empty arguments without shell evaluation.

Only one request is active per workshop. Cancelling or editing a manual draft cancels the prior process and clears its pending ID, so a late reply cannot overwrite the new draft. Build is disabled while awaiting a reply. Clarifications and errors retain inventory and do not construct an object. Existing object modification, refund/reclamation and a full multi-turn revision history remain unsupported. A model explanation is still untrusted text; the sample evaluations below are not proof of correct interpretation of every possible natural-language request.

## Verified behavior

Windows 11 Pro 26200, Intel Core Ultra 9 285K, RTX 5090 / NVIDIA 580.88, MSVC 19.44.35228 x64 Release, SDK 10.0.26100, CMake 4.1.2, Jolt 5.6.0, raylib 6.0 and Codex CLI 0.153.3. Full build and **15/15 CTest executables passed in 9.99 s**. Subsequent viewer-only keyboard handling was rebuilt and checked normally. The final binary also completed a 45-frame automated three-material capture at 0.75 s, showing all three created objects and measured rolling diagnostics, then exited successfully. That fixture makes no model call. No material/contact law or existing physics tolerance changed.

The new deterministic assistant suite tests proposal versus clarification, stale request identity, duplicate/extra fields, request immutability, background success, failed/oversized output, cancellation of a process observed live, retry and native argument preservation. Its fake provider is explicitly a test fixture; the real model exchanges below are separate. Standard CTest runs make no model calls.

Four real CLI-provider trials at the pinned implementation used the same collected 10 kg lots and world. The three material prompts asked for a **12 cm diameter** ball at rest on the ramp. All three returned radius **0.06 m**, the requested substance, tangent −2 m, bitangent 0, clearance 0.002 m and zero initial velocity/spin. Each independently validated recipe was explicitly applied by the headless probe, stepped for 1 s at 1/240 s on the same 10-degree concrete support and saved. The existing compiler derived the mass and allocation; the LLM only supplied design inputs.

| Request | Result | Cost (kg) | Speed after 1 s (m/s) | Slip after 1 s (m/s) | Request/probe elapsed (s) |
|---|---|---:|---:|---:|---:|
| Glass ball | Proposal / created / rolling | 2.261946711 | 1.115621809 | 0.001568171 | 9.5998 |
| Oak ball | Proposal / created / rolling | 0.633345079 | 1.055466520 | 0.001621150 | 8.9417 |
| Iron ball | Proposal / created / rolling | 7.120608245 | 1.108843351 | 0.001550669 | 7.6960 |
| Hinged wood door | Clarification / no creation | — | — | — | 8.1004 |

The [machine-readable comparison](evidence/assistant-materials.csv) includes request token counts and compiler/physics measurements. These four trials ran concurrently; elapsed time includes CLI startup, model response, validation and the short physical probe. It is a small observed sample, not a latency percentile or service guarantee. Responses and accepted recipes are retained for reproduction without another model call. The same original 1e−12 material ledger tolerance and <0.02 m/s rolling-slip bound apply. Contact coefficients differ across substances; these results do not calibrate material realism or close the complete support energy ledger.

The door request asked for working hinges and received a clarification identifying unsupported geometry/assemblies, with no recipe and no saved created world. It did not silently turn the door into a ball. Broader semantic, adversarial and follow-up-design evaluation remains work.

Normal interactive evidence:

- A live workshop spawned Codex PID 24100 for request `workshop-1788584919748891-2`. Cancel returned promptly; an OS process query confirmed that exact process was gone. The world retained 10 kg of collected oak, zero objects and zero simulation ticks.
- Retry `workshop-1788584919748891-3` returned an oak-ball proposal automatically. Build spent **0.6333450789637022 kg**, leaving **9.366654921036298 kg**. Run showed **1.977 m/s speed and 0.003 m/s slip** at the observed 1.88 s timestamp; it later left the finite ramp and became airborne.
- In a fresh world, typed input “Make a glass ball 12 cm across that rolls down the ramp.” returned a glass proposal automatically. Build spent **2.2619467105846507 kg**, leaving **7.738053289415349 kg**, with oak/iron still uncollected. Keyboard Run showed rolling at 0.45 s with approximately **0.508 m/s speed and 0.001 m/s slip**. Follow, pause, image export and save worked. The exported current-workshop image is after edge departure at 4.63 s; it must not be labeled a rolling frame.
- Short Ctrl+A input initially exposed the same state-polling issue already fixed in the main lab: a complete key tap can occur between rendered frames. The workshop now consumes the key event queue. Clear, typed replacement, F/Space and F12 were checked after the fix. Prior UI runs were closed normally and terminal process state was confirmed before replacement.

## Reproduce the live checks

The native probe takes `--world`, `--prompt-file`, `--workspace` and `--request-id`; `--apply` explicitly creates and steps a validated proposal. Without that option it only previews. A clarification never applies. To run the committed glass/oak/iron/door prompts using an authenticated CLI:

```powershell
& ./scripts/run-assistant-check.ps1
```

This makes real model requests and saves an evidence folder under `build/`. Use a fresh output directory for a new run; do not overwrite old request identities. `-Cases oak` can exercise the wrapper alone, while physical comparisons must retain the full glass/oak/iron set. The script's one-case execution was checked separately from the four pinned trials.

## Next checkpoint

Add a second geometry through the same recipe/compiler/inventory/provider path, with actual occupied volume, full inertia and collision geometry. Compare sphere versus box/cylinder for glass, oak and iron under declared common conditions. Then support safe object revision and material reuse/waste accounting. Keep the [40-row scorecard](mechanics-scorecard.md) current. The detailed conservation/friction/activation, deformation/fracture and publishing gates in the [roadmap](roadmap.md) remain open; an automatic ball creator does not complete the general platform.
