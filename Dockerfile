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
RUN cmake -S . -B build/linux -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DBANJO_BUILD_LAB=OFF -DBANJO_BUILD_HEADLESS=ON \
      -DBANJO_BUILD_PRECOMPUTE=OFF -DBANJO_BUILD_TESTS=OFF \
 && cmake --build build/linux --parallel \
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
COPY --from=build /out/bin /app/bin
COPY --from=build /src/playground /app/playground
COPY --from=build /src/mcp /app/mcp
COPY --from=build /src/bindings /app/bindings
COPY --from=build /src/docs /app/docs
ENV BANJO_LIBRARY=/app/bin/libbanjo.so \
    BANJO_TERRAIN_CACHE=/data/terrain-cache \
    PYTHONUNBUFFERED=1
EXPOSE 8080
# The native studio windows are a desktop feature: not built here, and the
# page says so if asked for one.
CMD ["python3", "-u", "playground/server.py", "--host", "0.0.0.0", "--port", "8080", \
     "--engine", "/app/bin/banjo_platform_cli", "--studio", "/app/bin/banjo_network_lab", \
     "--runs", "/data/runs", "--rooms", "/data/rooms"]
