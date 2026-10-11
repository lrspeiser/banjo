# Banjo's Rube Goldberg game in one container: the engine built for Linux, and
# the Python server that holds each player's live machine world and talks to
# the chat. Render builds this from main (docs/deploy.md).

FROM ubuntu:24.04 AS build
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      build-essential cmake ninja-build git ca-certificates python3 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY . .
# The engine and nothing else. CMake fetches Jolt and nlohmann/json from GitHub
# while it configures. Two compiles at a time: a bare --parallel runs one on
# every core the builder has, and Render's 8 GB builder ran out of memory.
ARG BUILD_JOBS=2
RUN cmake -S . -B build/linux -G Ninja -DCMAKE_BUILD_TYPE=Release -DBANJO_BUILD_TESTS=OFF \
 && cmake --build build/linux --parallel "${BUILD_JOBS}" --target banjo_live_world_run \
 && mkdir -p /out/bin \
 && cp -a build/linux/banjo_live_world_run /out/bin/

FROM ubuntu:24.04
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      python3 ca-certificates \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . /app
COPY --from=build /out/bin /app/bin
# There is no git in the image: the revision the page shows is written here
# (Render passes the commit it builds).
ARG RENDER_GIT_COMMIT
RUN python3 -c "import json,sys; json.dump({'revision': sys.argv[1] or None}, open('/app/bin/build-receipt.json', 'w'))" "${RENDER_GIT_COMMIT}"
ENV PYTHONUNBUFFERED=1 \
    BANJO_MACHINE_SESSIONS=10 \
    BANJO_PUBLIC_HOSTS=banjo.is,www.banjo.is,banjo-f1sv.onrender.com
EXPOSE 8080
# On the port a host hands it in PORT -- Render sets one -- or else 8080.
# --site game: the levels, the free build and the sandbox they are built on.
# --public: open to anyone, no password (BANJO_PASSWORD is then not asked for);
# the chat and the reliability checks are rationed per visitor and per day.
CMD ["sh", "-c", "exec python3 -u scripts/voxel-lab.py --host 0.0.0.0 --port \"${PORT:-8080}\" --native /app/bin/banjo_live_world_run --logs /data/machine-logs --site game --public"]
