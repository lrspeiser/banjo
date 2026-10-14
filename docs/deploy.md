# Hosting the game

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

The `/play?visitor=<UUID>` link is the credential for that anonymous profile:
anyone with it can restore and change its saves. Keep it private, outside public
screenshots, issues and shared machine links. The database indexes profiles by
a SHA-256 hash of the UUID; this is not encryption of the saved designs.

Successful profile opens set an HttpOnly, SameSite=Lax cookie for one year;
public HTTPS cookies are Secure. An explicit return link takes precedence over
the cookie, then the cached browser identity. The application omits request
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

Requested October 14, 2026. **Provisioning is pending**: the branch-aware server,
shared-storage bridge and promotion guard are implemented and locally tested;
a separate Render test service and the production `/test` destination are not
yet provisioned. Existing production remains on main.

The intended entry is `https://banjo.is/test`, an operator-configured redirect
to the separate test service's `/play`. It is not a second engine hidden inside
the production process. Assets and APIs stay at their normal root paths on the
test origin, so a branch can change the server, page and native engine together.
Test builds carry a yellow TEST badge, a commit header and a branch tooltip.
Their share links stay on the test origin; production shares still use banjo.is.
The redirect does not forward private return credentials or arbitrary query
parameters. Its destination is never taken from a visitor request.

Create one Docker web service named **banjo-test**, from `lrspeiser/banjo`,
tracking **codex/staging**, using the existing Dockerfile and its default command.
Use **1c-2g** (1 CPU, 2 GB) to compare physics under the same compute allocation
as production. Its displayed cost must be approved before creating it. Do not
attach a second persistent disk or create a new Postgres database. Set:

| Variable | Test service value |
| --- | --- |
| `BANJO_ENVIRONMENT` | `test` |
| `BANJO_PROFILE_UPSTREAM` | `https://banjo.is/api/profile` |
| `BANJO_PROFILE_NAMESPACE` | `test` |
| `BANJO_PUBLIC_HOSTS` | `test.banjo.is` (optional future custom domain) |
| `BANJO_MACHINE_SESSIONS` | `3` |

Render's own `RENDER_EXTERNAL_HOSTNAME` is allowed automatically in test mode.
Do not copy production's Linear credential to staging: the test outbox and
machine logs are ephemeral without a disk. The test service needs its own
configured model credential if LLM help is to be tested; no credential is
embedded in code or a browser. Provider keys remain operator-managed secrets.
After verifying the actual test URL, set **BANJO_TEST_URL** on the production
service to that URL ending in `/play`; the validated server supports HTTPS
only, without embedded credentials, query or fragment.

SQLite remains on production's existing mounted disk. Render cannot mount that
disk in two services. The test service uses the ordinary HTTPS profile API;
only saves/restores use production compute, while rehearsals and live physics
run entirely on the test service. Existing API limits and storage capacity
apply to both. If the production save API is unavailable, testing retains local
drafts and refuses remote acknowledgement; it never falls back to a disposable
local SQLite store while claiming persistence.

By default, test visitor UUIDs are deterministically mapped to distinct UUIDv4
credentials before reaching the existing database. Production's UUID hashing,
rows, revision checks, schema and backups are unchanged. Test saves and live
saves are separate rows in **the same database**, with the same durability.
The mapping prevents accidental live edits; it is not a security boundary
against someone who already possesses a bearer credential. Cookies remain
host-only; no domain-wide credential cookie is added. Restore a test profile
with its test return link. To test a live design, open its shared machine setup
on the test origin and save a test copy. Deliberately choosing the namespace
`production` would edit live records and must be an explicit owner choice;
do not change the default casually. No schema migrations run during promotion.

Development flow:

1. Start a feature branch from current main; preserve unrelated changes.
2. Verify the changed scope, update Recent Changes, and integrate it into
   `codex/staging`. Fetch first and preserve any other staging work.
3. Push staging and wait for the test header and `/api/checkpoint` to report
   the expected SHA, branch, environment and native binary; play ordinary flows
   on desktop and phone. Validate saves and expected physics, not just page load.
4. Review the test site with the owner. Run the guard below; it requires the
   newest source-registration and build-and-test CI jobs to succeed on this SHA.
5. With owner release authorization, repeat using `--push`. The ordinary
   fast-forward push updates main to the **exact** tested SHA. A concurrent
   main update rejects promotion and requires incorporating/retesting it.
6. Check production's header/checkpoint and ordinary play after Render deploys.
   Saved data is already in the existing store; promoting code does not copy or
   replace the database. Retain independent backups for recovery.

```sh
python scripts/promote-test.py --site https://ACTUAL-TEST-HOST
# Release only after review and explicit release authorization:
python scripts/promote-test.py --site https://ACTUAL-TEST-HOST --push
```

The guard defaults to a dry run and does not reset local files or force-push.
It refuses a stale/running-old server, a dirty build, a non-test site, a different
branch, missing/failed/pending CI, and a staging history missing current main.

Verification before provisioning: 39 HTTP tests pass (6.425 s), exercising
both real servers against one SQLite store, isolated live/test rows, restore
after recreating the proxy, stale-device conflicts, body limits, cookie and
Origin handling, unavailable upstream and refusal to follow credential-bearing
redirects. Eight SQLite tests, four identity-client tests, eleven profile-sync
tests and two promotion guard tests pass. This changes no native physical laws;
the previously verified native binary remains in use. Browser and hosted
provisioning receipts follow when measured.

Local browser receipt: ordinary level GO → add weight → Try It! starts the
native simulation and displays the physical missed-goal result. A Sandbox
marble was placed, the design renamed, and Version 1 saved and recovered after
reload through the shared API at profile revision 8. Its setup share URL uses
the test origin. The yellow badge and scene controls remain visible at
390×844 and 844×390; screenshots are under ignored `build/ui-proof/test-site-*`.
Final HTTP run: 39 tests in 6.147 s; the three registered CTest suites for
profiles, promotion and HTTP pass in 7.38 s. Native SHA-256 remains
`35230eb7ee76ee0209ff034558ea6110061babd072635561b98d988b92c3f67a`.
An existing localhost cookie from another local server initially referred to
an unknown test profile; explicitly opening the isolated QA return identity
resolved it. Missing explicit/cookie identities remain refused instead of
silently discarding old data. Hosted test cookies will be host-only on the
separate test origin.
