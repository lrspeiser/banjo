"""Compare ground types on one map: smooth, 25 cm cells and 12.5 cm cells.

Starts its own playground server on a free port with its own rooms folder,
creates the same valley (same terrain and goods seeds) in each ground type,
and opens each in headless Chrome to measure what a player's machine pays and
what the player sees:

- how long the world takes to generate and the page to become ready;
- triangles drawn and the frame-time percentiles while standing still;
- bytes the page downloaded, and the saved world's size on disk;
- whether the page's ground agrees with the engine's (native survey vs
  banjoRoom.groundAt at the same points, the collision agreement);
- a screenshot from the same place by day and, after the world clock has
  carried the sun down, by night.

The native step cost is measured separately by opening each valley in a bare
engine session and stepping it, so it is not mixed with page cost.

This measures; it does not judge recognition. Whether people can name the
materials in the pictures is the human test in docs/human-playtest-protocol.md.

    python tools/terrain_compare.py --build build/rel/Release --out build/terrain-compare
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "playground"), str(ROOT / "tools"), str(ROOT)]

MODES = (("smooth", "Smooth slopes"), ("columns", "25 cm material cells"),
         ("columns-fine", "12.5 cm material cells"))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def http(base: str, path: str, body=None, token=None, timeout=300):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token: headers["X-Banjo-Token"] = token
    with urllib.request.urlopen(urllib.request.Request(base + path, data=data, headers=headers),
                                timeout=timeout) as reply:
        return json.loads(reply.read())


def folder_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def native_step_ms(engine: Path, seed: int, surface: str, cell_m: float, steps: int = 240) -> dict:
    """A bare valley in the engine: open time and wall time per 1/120 s step."""
    import fracture_lab, live_session
    from build_explore_world import CELL_M, WATER, valley
    spec = fracture_lab.validate({"algorithm": "lattice", "cell_m": CELL_M, "duration_s": 1.0,
        "terrain": {"surface": surface, "generate": valley(seed, cell_m)}, "water": dict(WATER),
        "bodies": [{"name": "s", "shape": "box", "material": "oak", "size_mm": [100, 100, 100],
                    "center_mm": [0, 8000, 0]}]})
    with tempfile.TemporaryDirectory() as tmp:
        began = time.perf_counter()
        session = live_session.Session(engine, spec, Path(tmp))
        try:
            opened = time.perf_counter() - began
            session.send(op="step", dt=1 / 120, n=12)          # settle the first frame
            began = time.perf_counter()
            for _ in range(steps // 12): session.send(op="step", dt=1 / 120, n=12)
            per = (time.perf_counter() - began) / steps
        finally:
            session.close()
    return {"open_s": round(opened, 2), "step_ms": round(per * 1000, 3), "steps": steps}


PAGE_STATS = """(async () => {
  const r = banjoRoom, dts = [];
  let last = performance.now();
  await new Promise(done => {
    const tick = now => { dts.push(now - last); last = now;
      if (dts.length < 300) requestAnimationFrame(tick); else done(); };
    requestAnimationFrame(tick);
  });
  dts.shift(); dts.sort((a, b) => a - b);
  const q = p => dts[Math.min(dts.length - 1, Math.floor(p * dts.length))];
  const bytes = performance.getEntriesByType("resource").reduce((s, e) => s + (e.transferSize || 0), 0);
  const g = r.groundDrawn();
  return {frame_ms_p50: q(.5), frame_ms_p95: q(.95), frame_ms_p99: q(.99),
          triangles: r.renderer.info.render.triangles, draw_calls: r.renderer.info.render.calls,
          geometries: r.renderer.info.memory.geometries,
          downloaded_bytes: bytes, js_heap_bytes: performance.memory ? performance.memory.usedJSHeapSize : null,
          grid: {nx: g.nx, nz: g.nz, cell_m: g.dx, surface: g.surface, x0: g.x0, z0: g.z0}};
})()"""

AGREEMENT = """(async (n, token) => {
  const r = banjoRoom, s = r.status().session, g = r.groundDrawn(), errs = [];
  const world = new URLSearchParams(location.search).get("world");
  let seed = 12345;
  const rand = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  for (let i = 0; i < n; i++) {
    const x = g.x0 + (2 + rand() * (g.nx - 4)) * g.dx, z = g.z0 + (2 + rand() * (g.nz - 4)) * g.dx;
    const reply = await fetch("/api/live/act", {method: "POST",
      headers: {"Content-Type": "application/json", "X-Banjo-Token": token, "X-Banjo-World": world,
                "X-Banjo-Player": localStorage.getItem(`banjo.player.${world}`)},
      body: JSON.stringify({session: s, op: "survey", at: [x, z]})}).then(a => a.json());
    const native = reply.survey && (reply.survey.ground_m ?? reply.survey.floor_m);
    const page = r.groundAt(x, z);
    if (Number.isFinite(native) && Number.isFinite(page)) errs.push(Math.abs(native - page));
  }
  errs.sort((a, b) => a - b);
  return {points: errs.length, max_m: errs[errs.length - 1], p95_m: errs[Math.floor(.95 * errs.length)],
          mean_m: errs.reduce((a, b) => a + b, 0) / errs.length};
})"""


def wait_for(page, expression: str, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if page.evaluate(f"Boolean({expression})"): return True
        time.sleep(.25)
    return False


def shot(page, path: Path) -> None:
    path.write_bytes(base64.b64decode(page.send("Page.captureScreenshot", {"format": "png"})["data"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", type=Path, default=ROOT / "build/rel/Release")
    parser.add_argument("--out", type=Path, default=ROOT / "build/terrain-compare")
    parser.add_argument("--terrain-seed", type=int, default=4, choices=(4, 7))
    parser.add_argument("--goods-seed", type=int, default=851269742)
    parser.add_argument("--night-wait-s", type=float, default=420.0,
                        help="most wall time to wait for the world clock to bring night")
    parser.add_argument("--no-night", action="store_true")
    parser.add_argument("--modes", default=",".join(m for m, _ in MODES),
                        help="comma-separated subset of smooth,columns,columns-fine")
    args = parser.parse_args()
    exe = ".exe" if os.name == "nt" else ""
    engine, cli = args.build / f"banjo_live_world_run{exe}", args.build / f"banjo_platform_cli{exe}"
    args.out.mkdir(parents=True, exist_ok=True)
    import qa_browser
    modes = [m for m in MODES if m[0] in args.modes.split(",")]

    report = {"terrain_seed": args.terrain_seed, "goods_seed": args.goods_seed, "modes": {}}
    for mode, label in modes:
        surface, cell = ("columns", .125) if mode == "columns-fine" else (mode, .25)
        report["modes"][mode] = {"label": label, "native": native_step_ms(cli, args.terrain_seed, surface, cell)}
        print(mode, report["modes"][mode]["native"], flush=True)

    rooms = Path(tempfile.mkdtemp(prefix="terrain-compare-"))
    port = free_port()
    server = subprocess.Popen([sys.executable, "-u", str(ROOT / "playground/server.py"), "--port", str(port),
                               "--engine", str(cli), "--rooms", str(rooms), "--runs", str(rooms / "runs")],
                              cwd=ROOT, stdout=subprocess.DEVNULL, stderr=open(args.out / "server.log", "w"))
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try: token = http(base, "/api/status")["csrf_token"]; break
            except Exception: time.sleep(.5)
        else: raise RuntimeError("the server did not start")
        for mode, label in modes:
            row = report["modes"][mode]
            began = time.perf_counter()
            made = http(base, "/api/worlds", {"name": label, "surface": mode,
                        "seeds": {"terrain": args.terrain_seed, "goods": args.goods_seed}}, token)
            row["create_s"] = round(time.perf_counter() - began, 1)
            chrome = qa_browser.Chrome(1280, 800)
            try:
                page = chrome.page
                page.send("Page.enable"); page.send("Runtime.enable")
                began = time.perf_counter()
                page.send("Page.navigate", {"url": base + made["url"]})
                if not wait_for(page, "window.banjoRoom?.ready?.()", 180):
                    row["error"] = "page never became ready"; continue
                row["page_ready_s"] = round(time.perf_counter() - began, 1)
                time.sleep(3)
                row["page"] = page.evaluate(PAGE_STATS, await_promise=True)
                row["agreement"] = page.evaluate(f"{AGREEMENT}(200, {json.dumps(token)})", await_promise=True)
                # The same place for every mode: the arrival, looking across
                # the valley towards its river, where several materials show.
                page.evaluate("(()=>{const r=banjoRoom,y=r.groundAt(-6,2);r.standAt(-6,y+1.7,2);"
                              "r.lookAt(0,r.groundAt(0,-2),-2)})()")
                time.sleep(2)
                shot(page, args.out / f"{mode}-day.png")
                world_dir = rooms / "worlds" / made["id"]
                row["saved_bytes"] = folder_bytes(world_dir) if world_dir.is_dir() else None
                if not args.no_night:
                    began = time.monotonic()
                    night = wait_for(page, "(banjoRoom.light().sun?.elevation_deg ?? 90) < -6", args.night_wait_s)
                    row["night_reached"] = night
                    row["night_wait_s"] = round(time.monotonic() - began)
                    if night:
                        page.evaluate("(()=>{const r=banjoRoom,y=r.groundAt(-6,2);r.standAt(-6,y+1.7,2);"
                                      "r.lookAt(0,r.groundAt(0,-2),-2)})()")
                        time.sleep(2)
                        shot(page, args.out / f"{mode}-night.png")
            finally:
                chrome.close()
            print(mode, json.dumps({k: v for k, v in row.items() if k != "label"}), flush=True)
    finally:
        server.terminate()
        try: server.wait(20)
        except subprocess.TimeoutExpired: server.kill()
        shutil.rmtree(rooms, ignore_errors=True)
    (args.out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("wrote", args.out / "report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
