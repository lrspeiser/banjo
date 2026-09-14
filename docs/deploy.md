# Hosting the playground

The playground -- `playground/server.py` and the engine it drives -- runs
anywhere a Linux container runs and stays running. This page puts it on
Fly.io, from this folder, with no GitHub connection needed.

## Why not Vercel, or any serverless host

The room is a world held in one running process. The page steps it about thirty
times a second, and between steps it is still there. A serverless function
starts for one request and is gone after it, so each step would find a new,
empty world. The engine is native code that wants a whole machine: a break is
worked out on every core there is, and on four cores one took 1.08 s against
the 0.49 s of warning the engine gives. And the rooms need a disk to be kept
on. A container host with an always-on machine and a volume has all three.

## What runs

`Dockerfile` builds the engine for Linux -- headless: `banjo_platform_cli`,
`banjo_live_world_run` and `libbanjo.so` -- and runs the same Python server as a
desktop, listening on every interface. Two things make that safe:

- **A password.** With `BANJO_PASSWORD` set, every page, script and API needs a
  session that only the password gets (`playground/access_gate.py`). The server
  will not listen anywhere but `127.0.0.1` without one.
- **One name.** The server answers only to `BANJO_PUBLIC_HOST` (and to
  localhost), so a page on another site cannot drive it.

The image holds the whole source tree, as a checkout does, with the three
programs in `/app/bin`. The server finds its modules and data from where it
stands in a checkout: `examples/authoring`, `mcp` and `bindings` on its import
path, `docs` and `assets` read from disk. An image that copied folders one by one
left out `examples/authoring`, and on Render the server stopped at its first
import (`ModuleNotFoundError: No module named 'banjo_authoring'`).

The rooms, the valley's generated ground and recorded runs are kept under
`/data`, a volume: what the chat built and what was dug is there after a restart
or a new deploy (`playground/room_store.py`). Where things were moved by hand
goes with the running world, as it does on a desktop.

## Deploying to Fly.io

You need flyctl (https://fly.io/docs/flyctl/install/) and a Fly account
(`fly auth login`).

1. From the repository root, `fly launch --no-deploy --copy-config`. Pick a name
   and a region near you; it writes both into `fly.toml` and keeps the rest.
2. In `fly.toml`, set `BANJO_PUBLIC_HOST` to `<your-app>.fly.dev`.
3. Make the volume, in the same region:
   `fly volumes create banjo_data --size 10 --region <region>`.
4. Set the secrets, in your own terminal, so they never go in a file:
   `fly secrets set OPENAI_API_KEY=... BANJO_PASSWORD=...`. The room's chat uses
   `gpt-5-mini` unless `OPENAI_MODEL` says otherwise.
5. `fly deploy --ha=false`. Fly builds the image on its own builders, so this
   computer needs no Docker; `--ha=false` keeps it to one machine, since there is
   one world and one volume.
6. Open `https://<your-app>.fly.dev/world` and enter the password.

The machine stops by itself when nobody is connected (`auto_stop_machines`) and
starts on the next visit, which then takes a little longer. `fly scale count 0`
stops it until you scale it back to 1.

## Deploying to Render

Render builds the same image: make a **Web Service** with the **Docker**
runtime. Render's native Python runtime has no CMake to build the engine with.

- **Source:** Render builds from a connected repository, or pulls an image
  already built into a registry. Point it at the branch that has these files.
- **Start command:** the image's own, so leave Render's *Docker Command* empty.
  It is
  `sh -c 'exec python3 -u playground/server.py --host 0.0.0.0 --port ${PORT:-8080} --engine /app/bin/banjo_platform_cli --studio /app/bin/banjo_network_lab --runs /data/runs --rooms /data/rooms'`,
  which listens on the port Render hands it in `PORT`.
- **Environment:** `OPENAI_API_KEY` and `BANJO_PASSWORD` as secret values, and
  `BANJO_PUBLIC_HOST` set to the service's hostname, `<name>.onrender.com` (or
  your own domain).
- **Disk:** a persistent disk mounted at `/data`, so what is built is kept
  across restarts and deploys. A service with a disk runs as one instance,
  which is what one world wants.
- **Health check path:** `/login`. Everything else asks for the password first.
- **Instance:** as many CPUs as you will pay for. With fewer, a break takes
  longer than the warning the engine gives, and the room waits for it.
- **Build memory:** the image compiles two files at a time (`BUILD_JOBS`,
  default 2). Render's builder has 8 GB, and a build with one compile per core
  ran out of it. With two, the compilers and the linker together peak at
  1.4 GB -- measured, with the largest single compile at 846 MB.

## What it costs

- **The machine:** 8 dedicated cores and 16 GB, billed while it runs (Fly's
  pricing page has the rate). Fewer cores cost less, but then a break takes
  longer than the warning the engine gives, and the room waits for it.
- **The volume:** 10 GB, billed while it exists.
- **The chat:** each request to the room's chat sends 160,000 to 270,000 input
  tokens to your OpenAI account (measured, `gpt-5-mini`).

## One world, one person

The server holds one live world. Two people with the password share it: opening
a room opens it for both, and the chat builds in the one room. Share the
password accordingly.

## Checking it before deploying

The image's steps by hand in Ubuntu 24.04 -- WSL's, on Windows. The build
stage, from a checkout:

    cmake -S . -B build/linux -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DBANJO_BUILD_LAB=OFF -DBANJO_BUILD_HEADLESS=ON \
      -DBANJO_BUILD_PRECOMPUTE=OFF -DBANJO_BUILD_TESTS=OFF
    cmake --build build/linux --parallel 8 \
      --target banjo_platform_cli banjo_c banjo_live_world_run

Then the image's start, from the files the image holds and nothing else. Run
from the checkout itself, the server finds files the image leaves out: that is
how `examples/authoring` went missing on Render with this check passing.

    rm -rf /tmp/banjo-image && mkdir -p /tmp/banjo-image/app/bin
    git archive HEAD | tar -x -C /tmp/banjo-image/app
    cp -a build/linux/banjo_platform_cli build/linux/banjo_live_world_run \
          build/linux/libbanjo.so* /tmp/banjo-image/app/bin/
    cd /tmp/banjo-image/app
    BANJO_PASSWORD=... BANJO_LIBRARY=$PWD/bin/libbanjo.so \
      python3 -S -u playground/server.py --host 0.0.0.0 --port 8090 \
      --engine bin/banjo_platform_cli --studio bin/banjo_network_lab \
      --rooms /tmp/banjo-image/data/rooms --runs /tmp/banjo-image/data/runs

`-S` keeps Python to its standard library, as the image's is: a module installed
on the machine but not in the image would fail the same way. Then open
http://localhost:8090/login from Windows.
