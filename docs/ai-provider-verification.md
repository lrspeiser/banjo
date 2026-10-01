# Separate reference and live-provider qualification

`scripts/verify_ai_player.py` uses isolated native HTTP worlds across terrain
seeds 7 and 4, each with normal stock and a removed starting supply. Comparison
mode requires the local provider key, selected runner and adjacent platform CLI
**before creating a world**. Missing configuration is unavailable qualification,
never a green skip or reference substitution. User worlds/servers are untouched.

```powershell
python scripts/verify_ai_player.py --mode reference --runner build/agent-progression/Release/banjo_live_world_run.exe
python scripts/verify_ai_player.py --mode comparison --runner build/agent-progression/Release/banjo_live_world_run.exe
```

Acceptance requires actual goal receipts, both personal techniques, expanded
actions, own packed product, unchanged other-guest state and a saved checkpoint.
An **actual server stop/start** must preserve inventory, knowledge, evidence and
machine runtime. Scarcity must block without later rewards. The restart check
uses the active Inventory record; the profile field is only its initial load seed.

Each provider case allows 64 requests/decisions, no transport retries or
reference fallback, and 800 output tokens per request. Input token length and
currency cost are not capped. Configured model stays unless `--model` is given.
Unattended ticking is disabled in fixtures; ordinary shared wall-time step
budgets remain. They do not measure real-time throughput. Rover decisions use
reflexes to isolate character-provider usage.

Reports keep source commit/dirty scope, script/diff/runner hashes, environment,
bounded action choices, HTTP status, latency and measured usage. Unknown usage
stays null. Cached/reasoning counts are subsets of input/output totals, not extra
tokens, following the [official Responses usage schema](https://developers.openai.com/api/reference/cli/resources/responses/methods/create).
Prompts, raw responses, guest tokens and credentials are omitted. Partial reports
update atomically; authentication failure stops more cases.

## Evidence — September 30, 2026

Four reference cases pass: both normal worlds complete 8/8 goals and earn 2/10
techniques; both missing-supply cases block without rewards.
[Native report](evidence/ai-provider/reference-report.json).

**Live provider remains unverified.** No local API key is configured. Comparison
preflight creates no world or provider request.
[Unavailable report](evidence/ai-provider/provider-preflight.json).
Transport/schema mocks qualify measurement/refusal logic, not model quality.
Eight harness and seven adapter tests pass; CTest registers
`banjo_ai_verification_tests`.
