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
      --target banjo_platform_cli banjo_c banjo_live_world_run banjo_voxel_world_run banjo_coupled_cpu banjo_thermal_fields banjo_mechanisms_cpu banjo_flow_cpu \
 && mkdir -p /out/bin \
 && cp -a build/linux/banjo_platform_cli build/linux/banjo_live_world_run \
       build/linux/libbanjo.so* build/linux/banjo_voxel_world_run build/linux/libbanjo_coupled_cpu.so \
       build/linux/libbanjo_thermal_fields.so build/linux/libbanjo_mechanisms_cpu.so build/linux/libbanjo_flow_cpu.so /out/bin/

FROM ubuntu:24.04
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      python3 python3-numpy libgomp1 ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# The source tree as a checkout has it -- about 5 MB, with .dockerignore leaving
# out the builds and git's own files -- because the server finds its modules and
# data from where it stands in a checkout: examples/authoring, mcp and bindings
# on its import path, docs and assets read from disk. Copied folder by folder it
# left out examples/authoring, and on Render it would not start.
COPY . /app
COPY --from=build /out/bin /app/bin
ARG RENDER_GIT_COMMIT
RUN python3 scripts/cpu-build-receipt.py --library /app/bin/libbanjo_coupled_cpu.so --native /app/bin/banjo_voxel_world_run --output /app/bin/build-receipt.json
ENV BANJO_LIBRARY=/app/bin/libbanjo.so \
    BANJO_TERRAIN_CACHE=/data/terrain-cache \
    BANJO_COUPLED_CPU_LIBRARY=/app/bin/libbanjo_coupled_cpu.so \
    BANJO_THERMAL_FIELDS_LIBRARY=/app/bin/libbanjo_thermal_fields.so \
    BANJO_MECHANISMS_LIBRARY=/app/bin/libbanjo_mechanisms_cpu.so \
    BANJO_FLOW_LIBRARY=/app/bin/libbanjo_flow_cpu.so \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    PYTHONUNBUFFERED=1
EXPOSE 8080
# On the port a host hands it in PORT -- Render sets one -- or else 8080, which
# fly.toml forwards to. The native studio windows are a desktop feature: not
# built here, and the page says so if asked for one.
# --site game: the deployed site is the game -- the levels and the sandbox
# they are built on -- and nothing else (docs/machine-game.md). --public: open
# to anyone, no password (BANJO_PASSWORD is then not asked for); the chat and
# the reliability checks are rationed per visitor and per day instead.
CMD ["sh", "-c", "exec python3 -u scripts/voxel-lab.py --host 0.0.0.0 --port \"${PORT:-8080}\" --native /app/bin/banjo_voxel_world_run --cpu-library /app/bin/libbanjo_coupled_cpu.so --logs /data/physics-lab-logs --site game --public"]
