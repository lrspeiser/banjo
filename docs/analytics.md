# Banjo usage analytics

October 20, 2026. Explicit events use the [PostHog Capture API](https://posthog.com/docs/api/capture)
and the owner's dedicated **Banjo US project**, confirmed in chat. The public
ingestion token is in `client/voxel-lab/analytics.mjs`; it is not a personal
API key and cannot administer another project. No existing project settings,
dashboards, SDK globals, cookies or identities are modified. There is no
remote analytics script, autocapture, replay or per-frame analytics loop.

Only HTTPS `banjo.is` and `www.banjo.is`, with the server's production marker
and no `/test` prefix, send to `https://us.i.posthog.com/i/v0/e/`. Localhost,
Render's direct service hostname, test builds and automated browsers send
nothing. Local/test production-like integration uses a captured transport,
never the real project. The CSP allows this ingestion origin in production;
the test site's restricted CSP remains unchanged.

## Events and useful reports

| Event | What it measures |
| --- | --- |
| `$pageview`, `$pageleave` | Visits to Levels, a level, Sandbox, a design or Community; time before navigation |
| `banjo_level_opened`, `banjo_level_left` | Level choice, elapsed time, attempts and whether a win happened before leaving |
| `banjo_run_started` | Each new physical run, with attempt number and placed-piece count; pause/resume does not add an attempt |
| `banjo_level_result` | Engine score: success/failure, stars, help/test flags, world time and energy versus par |
| `banjo_retry` | Reset or Try again, including whether pieces were kept |
| `banjo_help_requested` | Hint, guided help or word builder usage; never the question or answer |
| `banjo_builder_result` | Word-builder application success/failure and placed-piece count; success means applied, not a newly certified goal |
| `banjo_design_created`, `banjo_design_saved`, `banjo_design_restored` | Sandbox creation, successfully synced save and restored-version usage |
| `banjo_course_shared`, `banjo_course_copied` | Successful run-only share/publication or editable copy; no course contents or ID |
| `banjo_api_error` | Non-frame machine HTTP 5xx/429 failures, at most once per operation/status per 30 s; no message or request body |
| `banjo_run_pace` | One summary per stopped run: world time, maximum simulation lag and longest frame wait |

Useful initial PostHog Product analytics insights:

1. Unique and returning visitors from `$pageview`, grouped by screen,
   touch/desktop and referring **domain**.
2. Funnel: `banjo_level_opened` → `banjo_run_started` →
   `banjo_level_result` filtered to `success = true`, broken down by `level_id`.
3. Completion rate, attempts to win, help rate and elapsed time by level.
   A run result is per attempt; level-left completion is per level visit.
4. Levels left without a win, compared with zero-attempt exits, to distinguish
   confusing setup from difficult physics.
5. Sandbox creation → saved version → share, plus word-builder failures.
6. Simulation lag and machine request failures by build revision. Do not infer
   a full client CPU profile from these summary measurements.

The signed-in owner authorized creation of
[Banjo Player Overview](https://us.posthog.com/project/676387/dashboard/2235687)
in the dedicated Banjo project on October 20. Its eight saved native Trends
insights cover visitors, players, completed level runs, daily activity, activity
by level, scored-attempt win rates, median winning attempt and median time to
win. All eight returned production data when refreshed. The dashboard defaults
to seven days. First-day comparison badges are hidden because there is no
earlier tracking history. Counts are anonymous browsers; repeat wins are
separate completed runs. Winning time is wall-clock time, including thinking
and background tabs. No other PostHog project was edited.

The public project token can ingest events, but cannot create dashboards or
query stored events; dashboard work used the owner's signed-in PostHog session.

## Identity, privacy and limits

A random, Banjo-only anonymous browser ID is stored under
`banjo.analytics.v1.id`. Sessions use UUIDv7 IDs and expire after 30 minutes
without a tracked event. This counts browsers, not known people or cross-device
save owners. It never uses the bearer visitor token, return link or design ID.
Events contain allowlisted numbers, booleans and short catalogue labels. Full
URLs, queries, hashes, referrer paths, chat/bug text, names, saved machine
contents and electrical/physics snapshots are excluded. Page URLs are synthetic
`/play`, `/machine` or `/community`; `level_id` carries the lesson selection.
Person-profile processing and IP geolocation enrichment are disabled.

**Changes → Settings → Share anonymous usage to improve Banjo** opts out
immediately and removes the analytics IDs; other open tabs check that setting
before sending. Browser Do Not Track and Global Privacy Control disable capture.
Opting out affects future events, not data already ingested. Analytics uses
non-awaited, bounded keepalive requests; blocked delivery is dropped without
retrying or interrupting the game. Ad blockers, closed tabs and offline users
make counts approximate. Page elapsed time includes background-tab time;
it is not active solving time. No continuous physics data is sent.

The supplied wizard was inspected but requires Node ≥22.22.0; this computer
has 22.18.0. Integration uses the documented Capture API directly in the existing
vanilla-JavaScript/Python stack; no system Node upgrade is needed.

## Verification

`node --test tests/analytics_tests.mjs` checks project/host isolation, local/test
exclusion, privacy signals, URL/property scrubbing, persistent anonymous identity,
session expiry, other-project storage preservation, cross-tab opt-out and blocked
or stalled transport. CMake registers this as `banjo_analytics_tests`.
The browser regression runs an actual winning and failing Mind the Gap attempt,
checks attempt/result/retry events, and then verifies opt-out stops capture.

The release also restores previously interpolated body meshes before applying
a native delta. A final frame can omit a body that has stopped; discarding the
interpolation bookkeeping first left that body a few millimetres behind its
last measured position. Physics, scoring and tolerances are unchanged.
