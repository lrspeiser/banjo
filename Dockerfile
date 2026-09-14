# Banjo's playground in one container: the engine built for Linux, and the
# Python server that holds the live world and talks to the room's chat.
# docs/deploy.md says how to run it on Fly.io.
#
# The server is the playground as it runs on a desktop, listening on every
# interface (--host 0.0.0.0) and therefore behind a password (BANJO_PASSWORD,
# a secret): it will not start in public without one. The rooms, the valley's
# saved ground and the runs live under /data, a volume, so a restart or a new
# deploy keeps what was built.

FROM ubuntu:24.04 AS build
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential cmake ninja-build git ca-certificates python3 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY . .
# Headless: the three programs the playground runs and nothing that draws a
# window. CMake fetches Jolt and nlohmann/json from GitHub while it configures.
# Two compiles at a time, as CI builds this code: a bare --parallel runs one on
# every core the builder has, and Render's 8 GB builder ran out of memory.
ARG BUILD_JOBS=2
RUN cmake -S . -B build/linux -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DBANJO_BUILD_LAB=OFF -DBANJO_BUILD_HEADLESS=ON \
      -DBANJO_BUILD_PRECOMPUTE=OFF -DBANJO_BUILD_TESTS=OFF \
 && cmake --build build/linux --parallel "${BUILD_JOBS}" \
      --target banjo_platform_cli banjo_c banjo_live_world_run \
 && mkdir -p /out/bin \
 && cp -a build/linux/banjo_platform_cli build/linux/banjo_live_world_run \
       build/linux/libbanjo.so* /out/bin/

FROM ubuntu:24.04
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      python3 libgomp1 ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# The source tree as a checkout has it -- about 5 MB, with .dockerignore leaving
# out the builds and git's own files -- because the server finds its modules and
# data from where it stands in a checkout: examples/authoring, mcp and bindings
# on its import path, docs and assets read from disk. Copied folder by folder it
# left out examples/authoring, and on Render it would not start.
COPY . /app
COPY --from=build /out/bin /app/bin
ENV BANJO_LIBRARY=/app/bin/libbanjo.so \
    BANJO_TERRAIN_CACHE=/data/terrain-cache \
    PYTHONUNBUFFERED=1
EXPOSE 8080
# On the port a host hands it in PORT -- Render sets one -- or else 8080, which
# fly.toml forwards to. The native studio windows are a desktop feature: not
# built here, and the page says so if asked for one.
CMD ["sh", "-c", "exec python3 -u playground/server.py --host 0.0.0.0 --port \"${PORT:-8080}\" --engine /app/bin/banjo_platform_cli --studio /app/bin/banjo_network_lab --runs /data/runs --rooms /data/rooms"]
