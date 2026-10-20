# Hosting the game

## Faster verification — October 20

The earlier release measured 41 minutes of CI and 49 minutes to finish its
separate test-package workflow. That graph compiled the engine 33 times.
The native CTest group alone spent 1,510 s testing, including 489 s of Pinball
and 365 s of wall mechanisms; packaging then repeated those and the full game
suite sequentially. The busiest browser batch took 1,182 s of its unchanged
1,200 s deadline. These are observed baseline times, not an estimate of new speed.

The revised graph:

- Builds one shared Release game engine for browser, game and recipe jobs,
  with a current-revision receipt and SHA-256 checked before every use. The
  independent native unit build remains, reducing 33 builds to two. Both use
  bounded compiler caches; compiler/flag/source validation remains in ccache.
- Runs wall and Pinball mechanisms as separate integration groups, retaining
  their cases and the existing 600 s deadlines. The native CTest exclusion
  removes only those now-delegated groups; all other existing exclusions stay.
- Divides the all-level UI audit by its three existing viewports and separates
  the precision-control phone audit. All prior assertions and level/viewpoint
  combinations remain, now in 218 disjoint browser methods. Optional onboarding
  timing reports gain a `-WIDTHxHEIGHT` suffix.
  CMake and CI both register the same sixteen browser batches.
- Packages the same engine only after `build-and-test` succeeds in that CI run.
  It repeats the installed-package routing/save isolation checks, not the
  already-passed gameplay suites. `test-site.yml` is manual recovery only;
  it requires full exact-revision CI before building a replacement package.
- Runs full verification on staging and PRs. Feature pushes do not launch a
  second copy alongside their PR. A main push reuses a completed, successful
  staging **push** run only when repository, workflow and exact commit all match.
  Source registration still runs; a changed revision, unavailable proof or a
  direct main fix runs the full suite. The aggregate records the reused run ID.

No physics law, goal, assertion, timestep or tolerance changes. Promotion still
uses `scripts/promote-test.py` and requires the running `/test` revision to match
staging with successful source-registration and build-and-test checks. Shared
artifacts use [GitHub Actions artifacts](https://github.com/actions/download-artifact)
within the same run; they are not downloaded from an unrelated branch/run.
New timing claims require a completed run of this graph; cold-cache and queued
runner time should be reported separately from test execution.
Local checks pass: actionlint 1.7.12 validates both workflows;
receipt/proof regressions reject changed bytes, wrong revisions,
platforms, branches and incomplete/failed runs. The new portrait catalogue and
phone precision-control methods pass in the ordinary browser (64.847 s total),
and the distribution regression covers every one of the 218 methods exactly
once for 1, 4 and 16 batches. These checks do not yet establish a new CI duration.

October 20 analytics: the dedicated Banjo US project token is a public ingestion
token bundled with the page; no Render secret or other-project change is needed.
Only production HTTPS banjo.is/www.banjo.is sends explicit events. Local and
`/test` stay excluded, including in browser CI; production CSP permits only the
US ingestion origin as an extra connection destination. See
[events, privacy controls and verification](analytics.md).

October 20 device-control release checks: the all-level nudge audit now has
its own 600-second game batch. The remaining engine scenarios are split
between two other batches; declarations and Pinball retain their own batches.
CMake, CI and the CLI use five disjoint batches, with a coverage regression
ensuring every method runs once. The unbatched test-package check still runs
the complete suite. Browser tests keep sixteen runners and their 1200-second
deadlines, with the expensive wall-wheel builder moved off the overloaded
runner and new control cases assigned to a lighter runner. No scenario,
goal, physical timestep or tolerance is removed or relaxed.

The expanded browser control audit took 563 s on its runner; combined with
the tackle and other UI checks it exhausted the unchanged 1200 s batch limit.
Both catalogue-wide audits now run with lighter groups, and the wall mechanisms
check moves off the next busiest group. All 215 scenarios remain disjoint and
covered exactly once, including the new analytics browser check. This changes
assignment only, not deadlines, assertions or game behavior.

October 19 test-child recovery: the supervisor now restarts its already
verified current package after a child exits or the existing memory budget
stops it. Recovery runs independently of the staging download, with retries
at most once every 30 seconds. A missing newer package can no longer leave
the accepted cached build offline indefinitely. The resource limits,
package checksum/health checks and production session pool are unchanged.
The cohosted regression stops the test child, returns 404 for the update,
checks that the accepted revision restarts, and keeps a production engine
session usable throughout. This does not make an unverified update available.

The game is hosted on Render as the web service **banjo**
(`srv-dajite67bikc73c8echg`), at <https://banjo-f1sv.onrender.com/play>. Render
builds it from the `main` branch of `lrspeiser/banjo` and deploys every new
commit by itself, so a push to main is a deploy. It takes about six minutes, and
Render keeps the old version serving until the new one is up while the service
has no persistent disk. Attaching the disk described below changes this:
deploys stop the previous instance before starting the next one, briefly
interrupting play. [Render's disk limitations](https://render.com/docs/disks#disk-limitations-and-considerations)
explain why.

## What runs

The `Dockerfile` has two stages:

1. **Build.** Ubuntu 24.04 compiles one program, the engine
   `banjo_live_world_run`, with no tests. CMake downloads Jolt Physics and
   nlohmann/json from GitHub while it configures. The build also installs
   `libngspice0-dev` for the electrical solver. It compiles two files at a
   time (`BUILD_JOBS`, default 2), because one compile per core ran Render's
   8 GB build machine out of memory.
2. **Run.** Ubuntu 24.04 with Python 3 and `libngspice0` (including its package
   dependencies and notices). The image holds the
   whole source tree, as a checkout does, with the engine in `/app/bin`. There
   is no git in it, so the commit the page shows is written to
   `/app/bin/build-receipt.json` from the commit Render builds
   (`RENDER_GIT_COMMIT`).

It starts:

    python3 -u scripts/voxel-lab.py --host 0.0.0.0 --port ${PORT:-8080} \
      --native /app/bin/banjo_live_world_run --logs /data/machine-logs \
      --site game --public

- `--site game` serves the game and nothing else: `/play`, `/machine`, the
  files those pages load, `/api/machine`, `/api/profile` and `/api/checkpoint`. `/` goes to
  `/play`; everything else is 404.
- `--public` opens it to anyone with no password. In return, what costs money
  or a lot of engine time is rationed per visitor: the chat, the reliability
  check, the path preview and feedback (the numbers and the variables that
  change them are in [machine-game.md](machine-game.md), "The site").
  `--public` is refused without `--site game`.
- The server runs at most `BANJO_MACHINE_SESSIONS` live levels at once (10 in
  the image). When it is full, a newcomer takes the place of a level whose page
  has closed or gone quiet, or else is told to try again in a minute or two.
  The co-hosted `/test` runner has one slot to limit its share of the server's
  CPU/RAM. Browsing Levels or the Sandbox library releases a page's world;
  returning rebuilds the placed setup. Close/open requests from one page wait
  for each other, so rebuilding does not consume a second slot. A genuinely
  busy slot asks players to close another game tab or retry shortly.

Anonymous profiles save progress, sandbox drafts and saved versions in SQLite
through `/api/profile`; the browser also keeps its local copy. Profile revisions
prevent a stale device from overwriting a newer save. This stores starting
designs and results, rather than running engine processes. Machine logs and
players' feedback remain under `/data/machine-logs`.

**Disk setup was reported complete by the owner on October 11, 2026.**
The requested setting is 1 GB mounted at `/data` on the existing Banjo service.
**Runtime persistence was verified on October 11, 2026.** Release `97931d7e`
reported `storage.persistent: true`. An isolated public profile completed the
native Turn the big wheel challenge with three stars, placed a plank of length
0.66, and saved Version 1 through ordinary controls. After Render deployed
`4953231d`, a new HTTP client with no cookies recovered the exact same profile
at revision 5: design, version and progress all matched the predeploy JSON.
Its SHA-256 was `2f05285d4f493b58cdebcf3f3feddbb43c5194b5dddad7aecb2eac30bb818a8e`.
The private return credential is retained only in ignored local QA files.
This measures redeploy retention for that profile; independent backups and
disk-loss recovery remain unconfigured. Merely creating `/data` inside the
image does not provide persistence.

## Render's settings

- **Runtime:** Docker, from the repository's `Dockerfile`. Leave *Docker
  Command* empty so the image's own command runs.
- **Environment:** `OPENAI_API_KEY` as a secret, for the chat; without it the
  chat says it is not available and the rest works. `OPENAI_MODEL` changes the
  model from `gpt-5-mini`. `BANJO_PUBLIC_HOST` accepts the existing single
  hostname setting. `BANJO_PUBLIC_HOSTS` adds a comma-separated list of exact
  hostnames; the image defaults to `banjo.is,www.banjo.is,banjo-f1sv.onrender.com`.
  Both settings are combined, so the existing Render environment need not change.
  Other hostnames are refused; API requests still require their Origin to match
  the request's own Host. Allowing aliases does not allow cross-origin requests
  between them. Render redirects `www.banjo.is` to `banjo.is`.
- **Health check path:** none is set, so Render waits for the port to open.
  `/play` would do; `/login` would not, since a public server has no login.
- **Instance:** one CPU and 2 GB (`1c-2g`); keep one service instance for the
  SQLite store. Runtime mount detection and saved-profile redeploy recovery passed.

## Persistent profiles: required service change

On the existing **banjo** service (`srv-dajite67bikc73c8echg`), open its **Disk**
page and attach **1 GB** at mount path **`/data`**. The Dockerfile sets
**`BANJO_PROFILE_DB=/data/banjo/profiles.sqlite3`**; any service environment
override must point below that mount too. The directory is created at
runtime; it need not exist during the image build. Saving the disk triggers a
deployment. Only files below its mount persist, and a disk-backed service
supports one instance. [Render's persistent disk setup](https://render.com/docs/disks#setup)
documents these requirements.

Render's published disk price, checked October 11, 2026, is **$0.25 per GB per
month**: this proposed 1 GB disk adds **$0.25/month** to the existing compute
bill. Recheck [Render pricing](https://render.com/pricing) before provisioning.
The owner completed this configuration. Runtime mount detection and an isolated
profile's redeploy recovery were verified on October 11 as recorded above.
Independent backups and disk-loss recovery remain unconfigured.

The server defaults to `--logs`' parent plus `profiles.sqlite3` when
`BANJO_PROFILE_DB` is absent, so the explicit setting above is required for the
documented location. SQLite uses WAL and synchronous FULL transactions. Profiles
are capped at 8 MB each; total JSON content defaults to 512 MB
(`BANJO_PROFILE_MAX_BYTES` can change it), and the main database is bounded at
640 MB. Machine logs, WAL files and backups also consume disk space. Monitor
usage; increasing a profile budget does not resize the disk. A full store
refuses the new save and preserves the prior one.

After provisioning, create a design and save a version. Copy its private return
link, then deploy or restart the service and open the link in another browser
with no local data. Confirm the design, version and progress return. The
successful `/api/profile` response must report `storage.persistent: true`.
On Render this flag requires a non-root mount ancestor of the database path;
it does not prove backups or replace this restart test. Check the page's commit
and `/api/checkpoint` as usual, and play a level after the deploy. Record that
evidence before changing the provisioning status above.

## Private return links

Community snapshots use a separate `community.sqlite3` beside the configured
profile database (`/data/banjo/community.sqlite3` in production), with WAL and
synchronous FULL transactions. `/api/community` offers public browse/get and
visitor-authorized share/mine/unpublish operations. Sharing reads only the
identified design from that visitor's acknowledged server save. Public replies
contain the published setup and description, never the profile, private history,
visitor token, owner hash or private design id. A copied course is saved through
the ordinary profile API under the copying visitor's own identity.

The cohosted test build keeps its own gallery at
`/data/test-logs/community.sqlite3`, outside replaceable packages, on the same
mounted disk. It does not migrate or open production's profile/gallery files.
Test courses stay on `/test`; they are not promoted as production content when
code is released. No new hosting or database purchase is required. Snapshots
are bounded to 1 MB each and 128 MB total, with a 160 MB SQLite page cap;
full-storage errors leave private saves unchanged. Include the gallery and its
WAL state in SQLite-aware backup/recovery alongside profiles. Existing backups
remain unconfigured as noted above.

The `/play?visitor=<UUID>` link is the credential for that anonymous profile:
anyone with it can restore and change its saves. Keep it private, outside public
screenshots, issues and shared machine links. The database indexes profiles by
a SHA-256 hash of the UUID; this is not encryption of the saved designs.

Successful profile opens set an HttpOnly, SameSite=Lax cookie for one year;
public HTTPS cookies are Secure. An explicit return link takes precedence over
the cookie, then the cached browser identity. A cookie the server does not know
(set by another server on the same host, such as a second local test server, or
kept across a lost database) is ignored: the cached browser identity opens, and
is made again with the browser's cached progress when it is gone, and the
cookie is replaced. Until October 17, 2026 such a cookie stopped the page at
"That visitor profile was not found" on every reload, because the page cannot
clear an HttpOnly cookie. A return link the server does not know still answers
404; the page then opens with the progress this browser kept for that link, or
with its own save, and the Levels screen says which. The application omits request
access logs and sends `Referrer-Policy: no-referrer`, but a token URL can still
remain in browser history or hosting/proxy request records. There is no Google
login, email recovery or independent account credential. Retain the return link
and a private backup.

## SQLite backups and recovery

Take a database-consistent backup with Python's
[SQLite backup API](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup).
It works while other connections access the source. Do not copy only the live
`profiles.sqlite3` file: committed data can still be in its `-wal` sidecar.

Run this in the running service's shell, with `BANJO_PROFILE_DB` set as above:

```python
import os
from pathlib import Path
import sqlite3

source_path = Path(os.environ['BANJO_PROFILE_DB']).resolve()
backup_path = Path('/tmp/banjo-profiles-backup.sqlite3')
source = sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True)
target = sqlite3.connect(backup_path)
try:
    source.backup(target)
    assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
finally:
    target.close()
    source.close()
```

Transfer that backup to private storage outside the service and retain dated
copies. `/tmp` is temporary, and a backup on the same disk is lost with that
disk. Backup scheduling and an off-service destination are not configured by
this change. Protect backups as saved player data; never commit them, the live
database or its WAL/SHM sidecars.

Render takes daily disk snapshots, but recommends database-native backups for
custom databases instead of disk-snapshot recovery.
[Render's recovery guidance](https://render.com/docs/disks#restoring-a-custom-database)
applies here. To recover, validate the chosen SQLite backup, stop all application
writers, retain the old database and sidecars separately, and replace the
database with the backup without old WAL/SHM sidecars beside it. Restart the
service and verify a known private return link before accepting new saves.
Recovery returns profiles to the backup's revisions; later saves are absent.

The custom-domain fix was checked on October 11, 2026 with six HTTP regressions
(`tests/machine_host_tests.py`, also registered with CTest): pages, assets and
same-origin game API calls accept each configured alias; unrelated, malformed,
duplicate and spoofed Host headers are refused. An allowed alias does not grant
another origin API access. Existing browser checks for placing, running and
sharing a machine also passed. This changes HTTP routing only, not the engine.

## Checking an image before deploying

There is no Docker on the development machine, so check the image's steps by
hand in Ubuntu 24.04 (WSL's, on Windows). Build as the image does:

    cmake -S . -B build/linux -G Ninja -DCMAKE_BUILD_TYPE=Release -DBANJO_BUILD_TESTS=OFF
    cmake --build build/linux --parallel 2 --target banjo_live_world_run

Then start the server from the files the image holds and nothing else. Run from
a full checkout, a server can find files the image leaves out, and the check
passes while Render fails:

    rm -rf /tmp/banjo-image && mkdir -p /tmp/banjo-image/app/bin
    git archive HEAD | tar -x -C /tmp/banjo-image/app
    cp -a build/linux/banjo_live_world_run /tmp/banjo-image/app/bin/
    cd /tmp/banjo-image/app
    python3 -S -u scripts/voxel-lab.py --host 127.0.0.1 --port 8090 \
      --native bin/banjo_live_world_run --logs /tmp/banjo-image/data \
      --site game --public

`-S` keeps Python to its standard library, as the image's is. Then open
<http://localhost:8090/play> and play a level.

## Bug reports to Linear

Help → Report a bug captures the player's note, setup, last result, screen size
and server revision. Public replay links use banjo.is; profile return credentials
and cookies are excluded. Delivery defaults to the owner's
[Banjo team (BAN)](https://linear.app/horizon3/team/BAN/overview), UUID
`7b265858-df39-4202-b1f4-0aed0f73dec7`. The original Banjo project in Kangaroo
(ROO), `9e5cee1b-625f-4961-be40-22efa4ab791d`, was archived on October 13 at
21:47:10 UTC; Linear can read it but rejects issue creation referencing it.

Set `LINEAR_API_KEY` as a server secret in Render Environment, with team read
and issue-creation access. Keep it out of chat, source and browser code.
No OAuth or webhook is required. `BANJO_LINEAR_TEAM_ID` can override the default
team UUID. `BANJO_LINEAR_PROJECT_ID` is optional: leave it unset or empty for
team-only reports, or configure an active project and a team belonging to it.
When only a project is configured, its single team is resolved automatically.
The integration uses [Linear's GraphQL API](https://linear.app/developers/graphql),
checking GraphQL errors even when HTTP succeeds. Successful creation must
return the expected issue ID and team, and the project when one is configured.

Reports are committed to `bug-reports.sqlite3` beside the profile database
before delivery. With `/data` configured, pending reports survive deployments.
The worker retries once a minute with exponential backoff capped at one hour.
A stable, derived version-4 UUID recovers a successful create whose response
was lost; Linear rejected version-5 issue IDs in direct validation. Migration
resumes the saved pending report without deleting records. Without a credential,
reports remain pending and the page says so. Existing limits allow 10 submissions
per visitor per hour and 500 globally per day; the outbox accepts at most 5,000
records and 60 KB per record. This adds no independent backups or automatic pruning.

`/api/checkpoint` includes `bug_reporting.configured`, the pending count,
team/project IDs and a sanitized `last_error`. It never exposes the provider's
raw error messages or credentials. Configured means a credential exists, not
that Linear accepted it. Verify one report's confirmed issue URL and destination
after configuring the key. Automated tests simulate provider success, failure,
restart and timeout recovery; direct tests confirmed team access, UUID validation
and the archived project's rejection. Live creation completes the release check.


## Branch testing and promotion

Requested October 14, 2026: run the test branch at **https://banjo.is/test**
inside the existing Render service, with **separate test saves in the same
storage**. No second Render service, disk or database is required. The prepared
paid-service form was canceled. The bootstrap release enables the co-hosted
route; check `/test/api/checkpoint` for the available branch revision after
deployment. The same-server path is verified locally and in the Linux package.

Production proxies `/test` to a separate loopback test process. Its source tree
and native executable are an immutable package from `codex/staging`; replacing
that process does not restart production or its live machines. The header shows
TEST and the branch revision. Test navigation, modules, APIs, manifest, return
URLs and setup shares remain under `/test`; production keeps its usual paths.
Scoped Content Security Policy and redirect checks catch accidental escapes.
These are trusted repository builds, **not a security sandbox for hostile code**:
both builds have the same host and filesystem.

### Installing branch revisions

The staging CI run builds the shared engine on a standard Ubuntu 24.04 runner,
requires every verification group, checks installed-package HTTP/co-host isolation,
and publishes the immutable prerelease asset
`banjo-test-<40-character-SHA>/banjo-test.tar.gz`. It packages committed runtime
sources, client files, documentation, the engine and checksummed build receipts.
It includes no database, logs, local drafts or credentials. This repository is
public; standard hosted runners are free under
[GitHub's runner policy](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
No compiler or Git checkout is added to the production runtime.

The Docker image enables `BANJO_TEST_SITE=1`. The supervisor polls staging every
five minutes, verifies archive limits, paths and file hashes, starts a candidate
and checks its revision and executable hash before switching test traffic.
Unavailable or invalid updates keep the previous build. Current and preceding
packages live under `/data/test-builds`; cached builds can boot without a download.
Test machine logs and its separate bug outbox live under `/data/test-logs`.
Updates end old **test** runs; saved test versions persist. New OS dependencies
still need a reviewed update to the production Docker image.

This shares production's CPU, memory and disk. Tests get one live machine and
one preview lane, Linux nice priority 10, an inherited 768 MiB virtual-address
limit per process, and a 512 MiB aggregate resident-memory stop sampled every
two seconds. Sampling is not cgroup isolation or a guarantee against all
resource contention. Preview/trial/chat budgets are lower for tests. Heavy
testing can still slow live play; a separate service remains an option later.
Physics detail, timestep and winning conditions are unchanged. Windows local
development does not apply the Linux limits.

### Shared storage with separate saves

SQLite remains on the existing mounted disk. The test process calls production's
profile API over loopback; it never opens or migrates live SQLite. Test UUIDs
map to distinct UUIDv4 credentials, so live/test profiles occupy different rows
with the same revision-conflict checks and durability. An unavailable save API
retains local drafts and refuses remote acknowledgement; it never reports a
failed upstream save as durable.

Test cookies use `banjo-test-visitor` with Path `/test/`, and browser progress uses
a distinct test storage key. Live cookies and progress are unchanged. Restore
test profiles on another device with their test return URL. To test a live
machine, open its shared setup under `/test/machine` and save a test copy. Tests
do not import live browser progress. Namespace mapping prevents ordinary
accidental edits, not access by someone who already possesses a bearer
credential. Promotion neither migrates nor copies the database. Keep backups.

Hosted test AI help can use the existing server's model configuration under
lower request budgets. The child does not inherit the Linear credential or
drain the live outbox. Test bug reports remain pending in its separate outbox;
confirmed Linear delivery remains a production check. Provider credentials are
never packaged or sent to the browser.

### Earlier verification measurements

Before the October 20 changes above, CI ran sixteen browser batches on separate
Ubuntu runners alongside the native test job. Each browser runner built the
checked-out engine with the existing 1200-second batch deadline. The
`build-and-test` check succeeded
only when source registration, every non-browser native check and all sixteen
browser batches succeed; failed, skipped or cancelled dependencies fail the
gate. Native JUnit/floating-point evidence remains attached to the run, and
browser progress and failure traces stream in the job logs. Failure screenshots
are retained as artifacts. This adds no Render service.

Saved-recipe verification uses six CTest batches, each with the existing
600-second deadline. Three disjoint subsets cover all 23 native recipe
families; historical heater validation has its own batch, and the remaining
20 test methods are split between two batches. Every previous method and
scenario remains covered. The unbatched CLI still runs all 22 methods.
The expanded native cable rehearsals had outgrown one 600-second suite slot;
no physical goal, nudge, negative control or numerical tolerance was relaxed.
The final unbatched local run passes all 22 methods in 961.844 s. The partition
check covers every method and all 23 native families exactly once; two native
family batches additionally pass in 143.871 s and 60.018 s.

At that earlier checkpoint, CI ran six recipe batches, sixteen browser batches
and seven game integration groups on independent runners. The native CTest job
excluded only those explicitly named groups; the aggregate required every group
to succeed. Game integration kept each suite's original 600-second deadline.
The remaining C++/API/client checks stayed in CTest. The then-current 149 browser
scenarios retained all layouts and assertions. Sixteen disjoint batches replaced
eight because the earlier batch 2 reached its 1200-second total
deadline after fifteen passing scenarios, before the remaining scenarios could
finish. The per-batch 1200-second deadline and required release gate remain.

### Development and promotion

The current verification graph is described under **Faster verification** above.
Local CTest registers the complete suite; the hosted graph changes scheduling,
not the game's CPU allocation or Render hosting.

1. Start a feature branch from current main, preserving unrelated changes.
2. Verify its scope, update Recent Changes and integrate into `codex/staging`.
   Fetch first and preserve concurrent staging work.
3. Push staging. Wait for the package and `/test/api/checkpoint` to show the
   exact SHA, branch, environment and native hash. Play ordinary desktop/phone
   flows and check saves and physical behavior.
4. Review with the owner. The guard requires the newest `source-registration`
   and `build-and-test` CI jobs to succeed on this exact SHA.
5. With release authorization, use `--push`. An ordinary fast-forward updates
   main to the tested SHA. Concurrent main work must be incorporated/retested.
6. Verify production after Render deploys. Code does not replace the database.

```sh
python scripts/promote-test.py
# Release only after review and release authorization:
python scripts/promote-test.py --push
```

The guard defaults to a dry run against `https://banjo.is/test`. It refuses stale
or dirty builds, a non-test site, wrong branch, missing/failed/pending CI and
staging history missing current main. It never resets or force-pushes.
The one-time routing/supervisor bootstrap must reach main before public `/test`
can host its first branch; verify the infrastructure locally and in the Linux
package workflow before enabling it. Subsequent changes use the review cadence.

For local development with the current checkout on both sides:

```sh
python scripts/voxel-lab.py --native <verified-build>/banjo_live_world_run.exe --port 18893 --test-source .
```

Local edits are marked honestly and cannot serve as a clean promotion receipt.
Published packages contain committed files and their own engine/build receipt.

Measured locally: real co-hosted tests cover scoped HTML/modules/manifest/
cookies, separate saves through one SQLite database, restore and stale-device
conflicts, origin rejection, inability to control a live machine through the
test API, and continued production play after the test process stops. Archive
tests reject traversal, links, duplicates, tampering and unexpected identity.
Existing HTTP, profile and client sync regressions also pass. A Sandbox marble
was placed and Version 1 saved/recovered through ordinary browser controls; its
share link stays under `/test/machine`. No native C++ laws changed. Windows hash:
`35230eb7ee76ee0209ff034558ea6110061babd072635561b98d988b92c3f67a`.
Verify hosted availability through the public checkpoint and ordinary
browser play after the bootstrap release. The test header identifies its exact
branch revision independently of the production header.

An actual Windows runtime package loaded its exact clean branch receipt and
verified executable hash. Replacing its runner changed the test PID while an
existing production machine session still returned native frames. Version 1
recovered after installation through ordinary Sandbox controls. The pipeline
also runs the installed Linux package before publishing it. Packaged receipts
take precedence over any parent checkout during local testing.

The seven focused registered CTest suites pass in 12.58 s (profiles, promotion,
co-hosting, HTTP, identity, synchronization and paths). All 271 native sources
remain registered; Python/JavaScript syntax and diff whitespace checks pass.

Linux package receipt: `f38281a45389509ab4bb546b576e7dabe18bb76d` passed
40 HTTP tests, seven co-hosted process/package checks, all 79 authored game
tests (155.749 s), then the same seven checks against the installed immutable
runtime (2.547 s). The broader engine/browser CI remains a separate release
gate for subsequent feature promotions; it is not claimed complete by these
focused infrastructure checks. No native source or physics law changed.

The electrical integration group now partitions its 49 existing methods into
25/24 disjoint cases, each with the original 600-second deadline. A full group
hit that deadline after 48 passing methods on one CI runner, although the prior
complete Linux run passed. Combinations have their own integration runner.
No test is removed and the unbatched CLI retains all 49 methods.

October 17 routed-rope checkpoint: the authored game group reached its 600 s
deadline near the end of its 94 cases on Linux. Game checks now run in two
disjoint batches (engine scenarios; declaration, free-build and goal checks),
each retaining the 600 s deadline. A partition regression verifies every case
runs exactly once. CMake and CI use the same partition; the unbatched CLI still
runs everything, as does the test-package job. No physical timestep, goal,
negative control or assertion tolerance changed in this scheduling correction.

October 18 six-wall-lesson release: the combined native game batch reached
600 s with its last wall-material case still running; the preceding scenarios
had passed. The game CLI and CMake now use three disjoint batches: alternating
native scenarios in batches 0/3 and 1/3, declaration/free-build/goal checks in
2/3. Each retains 600 s. CI's seven integration groups include all three and
its native CTest exclusion matches the three explicit independent runners.
The partition regression proves complete coverage without duplicates. No
scenario, physical goal, nudge or physics tolerance is removed or relaxed.
