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
   nlohmann/json from GitHub while it configures. It compiles two files at a
   time (`BUILD_JOBS`, default 2), because one compile per core ran Render's
   8 GB build machine out of memory.
2. **Run.** Ubuntu 24.04 with Python 3 and nothing else. The image holds the
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
The owner reported completing this configuration; the runtime and recovery checks below still need to confirm it.

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
