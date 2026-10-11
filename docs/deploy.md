# Hosting the game

The game is hosted on Render as the web service **banjo**
(`srv-dajite67bikc73c8echg`), at <https://banjo-f1sv.onrender.com/play>. Render
builds it from the `main` branch of `lrspeiser/banjo` and deploys every new
commit by itself, so a push to main is a deploy. It takes about six minutes, and
Render keeps the old version serving until the new one is up.

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
  files those pages load, `/api/machine` and `/api/checkpoint`. `/` goes to
  `/play`; everything else is 404.
- `--public` opens it to anyone with no password. In return, what costs money
  or a lot of engine time is rationed per visitor: the chat, the reliability
  check, the path preview and feedback (the numbers and the variables that
  change them are in [machine-game.md](machine-game.md), "The site").
  `--public` is refused without `--site game`.
- The server runs at most `BANJO_MACHINE_SESSIONS` live levels at once (10 in
  the image). When it is full, a newcomer takes the place of a level whose page
  has closed or gone quiet, or else is told to try again in a minute or two.

A player's progress (stars, best energy, their free build) is kept in their own
browser, not on the server. The server writes only the machines' logs and
players' feedback, under `/data/machine-logs`. Without a persistent disk at
`/data`, those are lost when the service restarts or deploys.

## Render's settings

- **Runtime:** Docker, from the repository's `Dockerfile`. Leave *Docker
  Command* empty so the image's own command runs.
- **Environment:** `OPENAI_API_KEY` as a secret, for the chat; without it the
  chat says it is not available and the rest works. `OPENAI_MODEL` changes the
  model from `gpt-5-mini`. `BANJO_PUBLIC_HOST` is the site's hostname
  (`banjo-f1sv.onrender.com`): the server answers only to that name and to
  localhost, so another site's page cannot drive it.
- **Health check path:** none is set, so Render waits for the port to open.
  `/play` would do; `/login` would not, since a public server has no login.
- **Instance:** one CPU and 2 GB (`1c-2g`), with no persistent disk.

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
