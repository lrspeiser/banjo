"""The QA: the whole playground, asked for in words, checked by the engine, and seen.

    python tests/qa.py                           every case twice, then the pictures
    python tests/qa.py --trials 1 --cases bow,tower
    python tests/qa.py --recipes                 the guide's own builds only: no model, no cost
    python tests/qa.py --no-3d                   no pictures
    python tests/qa.py --list

In order:

1. RECIPES. Every case has one: the thing built through the MCP by hand, then
   given the case's own check. A recipe that fails means the engine -- or the
   check -- cannot do it, and no model will.
2. TRIALS. Each sentence goes to the real chat agent (world_chat.ask, with the
   MCP's own tools). What it leaves in the room is opened in the real engine and
   USED: shoved, turned, hauled, loosed, heated, watched. A model is not
   deterministic, so each case is tried more than once and the answer is a rate.
3. THE OWNER'S RULES, on every check. The realtime rule is enforced, not just
   reported: a check whose engine falls behind 1.1x realtime is stopped there
   and fails as TOO SLOW. And every check ends by letting the room come to rest
   and saying how it looks: still moving, sunk through the floor, flown off.
4. PICTURES. Every build -- the recipes' and the agent's -- is opened in the
   real playground page in a headless browser and photographed as it opens and
   after it has run (tests/qa_browser.py), on a playground of its own.
5. THE REPORT. build/agent-regression/<time>/index.html: every case, recipe and
   trial, with the engine's numbers and the pictures, and a link that opens
   each build in the owner's own playground to be tried by hand
   (http://127.0.0.1:8765/world?qa=<time>/<case>-<trial>).

Trials cost money: they talk to the model in the local .env, 140k to 230k
tokens in per trial as measured so far. Recipes and pictures cost nothing.

The engine comes from BANJO_BUILD_DIR (default build/integration/Release).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXE = ".exe" if os.name == "nt" else ""
BUILD = Path(os.environ.get("BANJO_BUILD_DIR") or ROOT / "build" / "integration" / "Release")
os.environ.setdefault("BANJO_LIBRARY", str(BUILD / ("banjo.dll" if os.name == "nt" else "libbanjo.so")))
os.environ.setdefault("BANJO_LIVE_ENGINE", str(BUILD / f"banjo_live_world_run{EXE}"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "playground"))

import agent_build_tests as abt  # noqa: E402
import qa_cases  # noqa: E402

CASES = abt.CASES + qa_cases.CASES
RECIPES = {**abt.RECIPES, **qa_cases.RECIPES}
BY_ID = {c.id: c for c in CASES}
OWNER_PLAYGROUND = os.environ.get("BANJO_PLAYGROUND", "http://127.0.0.1:8765")
DEFAULT_SHOW_S = 4.0


def recipes_for(cases: list[abt.Case]) -> list[str]:
    wanted = {c.id for c in cases}
    return [rid for rid, entry in RECIPES.items() if entry[0] in wanted]


def state_of(record: dict[str, Any]) -> str:
    if record.get("passed"):
        return "pass"
    if record.get("too_slow"):
        return "slow"
    if "changed nothing" in str(record.get("reason") or ""):
        return "idle"
    return "fail"


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------

def run_recipes(cases: list[abt.Case], folder: Path) -> list[dict[str, Any]]:
    """One at a time, so no check's clock is shared with another's."""
    records = []
    for rid in recipes_for(cases):
        try:
            record = abt.run_recipe(rid, RECIPES, CASES, folder)
        except Exception:
            record = {"recipe": rid, "case": RECIPES[rid][0], "passed": False,
                      "reason": "the recipe crashed: " + traceback.format_exc()[-600:]}
        records.append(record)
        print(f"  recipe {state_of(record):4s}  {rid}: {record.get('reason')}", flush=True)
    return records


UNREACHED = "could not be reached"


def run_trials(work: list[tuple[abt.Case, int]], api_key: str, model: str, folder: Path,
               jobs: int) -> list[dict[str, Any]]:
    speaking = threading.Lock()
    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = {pool.submit(abt.run_trial, c, t, api_key, model, folder): (c, t) for c, t in work}
        for future in as_completed(futures):
            case, trial = futures[future]
            try:
                record = future.result()
            except Exception:
                record = {"case": case.id, "trial": trial, "passed": False,
                          "reason": "the trial crashed: " + traceback.format_exc()[-600:]}
            records.append(record)
            with speaking:
                print(f"  trial  {state_of(record):4s}  {case.id} #{trial}: {record.get('reason')}",
                      flush=True)
    order = [c.id for c in CASES]
    records.sort(key=lambda r: (order.index(r["case"]), r["trial"]))
    return records


# ---------------------------------------------------------------------------
# Pictures: the builds in the real playground page
# ---------------------------------------------------------------------------

def _names(measured: dict[str, Any]):
    for value in measured.values():
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            yield from (v for v in value if isinstance(v, str))


def framing(spec: dict[str, Any], record: dict[str, Any]) -> tuple[list[float], float]:
    """Where to look: at what the check named, or else at everything built."""
    bodies = {b["name"]: ([v / 1000.0 for v in b["center_mm"]], [v / 1000.0 for v in b["size_mm"]])
              for b in spec.get("bodies", []) if b["name"] != "marker stone"}
    named = [bodies[n] for n in _names(record.get("measured") or {}) if n in bodies]
    pick = named or list(bodies.values()) or [([0.0, 0.5, 0.0], [1.0, 1.0, 1.0])]
    lo = [min(c[i] - s[i] / 2.0 for c, s in pick) for i in range(3)]
    hi = [max(c[i] + s[i] / 2.0 for c, s in pick) for i in range(3)]
    return [(lo[i] + hi[i]) / 2.0 for i in range(3)], max(0.3, max(hi[i] - lo[i] for i in range(3)) / 2.0)


def start_playground(port: int, log_path: Path) -> subprocess.Popen:
    log = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-u", str(ROOT / "playground" / "server.py"), "--port", str(port),
         "--engine", str(BUILD / f"banjo_platform_cli{EXE}"),
         "--studio", str(BUILD / f"banjo_network_lab{EXE}")],
        cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    for _ in range(120):
        if proc.poll() is not None:
            break
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/world", timeout=2) as reply:
                if reply.status == 200:
                    return proc
        except Exception:
            time.sleep(0.5)
    stop_playground(proc)
    raise RuntimeError(f"the playground on port {port} did not start; see {log_path}")


def stop_playground(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        # By PID, with what it started: the engine processes are its children.
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.terminate()


def photograph(records: list[dict[str, Any]], folder: Path, port: int) -> dict[str, dict[str, Any]]:
    try:
        import qa_browser
    except ImportError:
        print("  tests/qa_browser.py is not here, so there are no pictures this run", flush=True)
        return {}
    builds = []
    for record in records:
        if not record.get("spec"):
            continue
        spec = json.loads((folder / record["spec"]).read_text(encoding="utf-8"))
        focus, extent = framing(spec, record)
        stem = record["spec"][: -len(".spec.json")]
        builds.append((stem, {"id": f"{folder.name}/{stem}", "focus_m": focus, "extent_m": extent,
                              "show_s": qa_cases.SHOW_S.get(record["case"], DEFAULT_SHOW_S)}))
    if not builds:
        return {}
    print(f"  photographing {len(builds)} builds on port {port}", flush=True)
    proc = start_playground(port, folder / "playground.log")
    try:
        seen = qa_browser.capture([b for _, b in builds], port, folder)
    finally:
        stop_playground(proc)
    return {stem: shot for (stem, _), shot in zip(builds, seen)}


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

LABEL = {"pass": "PASS", "fail": "FAIL", "slow": "TOO SLOW", "idle": "NO CHANGE"}


def _pictures(shot: dict[str, Any] | None, folder: Path) -> list[tuple[str, str]]:
    """(file, caption) for whatever pictures the 3D pass left."""
    if not shot:
        return []
    found = []
    for key, value in shot.items():
        if isinstance(value, str) and value.lower().endswith(".png"):
            # Linked from index.html, which sits in the run folder beside them.
            try:
                name = Path(os.path.relpath(value, folder)).as_posix()
            except ValueError:
                name = Path(value).as_uri()
            caption = "as it opened" if "start" in key else ("after it ran" if "later" in key else key)
            found.append((name, caption))
    found.sort(key=lambda p: 0 if p[1] == "as it opened" else 1)
    return found


def _rest_line(record: dict[str, Any]) -> str:
    rest, clock = record.get("rest") or {}, record.get("realtime") or {}
    bits = []
    if rest:
        if rest.get("at_rest"):
            bits.append("came to rest" + (f" after {rest['waited_s']:.0f} s" if rest.get("waited_s") else ""))
        elif record.get("case") in qa_cases.KEEPS_MOVING:
            bits.append("still moving, as it should: " + qa_cases.KEEPS_MOVING[record["case"]])
        else:
            bits.append("still moving: " + ", ".join(f"{n} at {v} m/s" for n, v in rest.get("still_moving") or []))
        if rest.get("sunk"):
            bits.append("SUNK THROUGH THE FLOOR: " + ", ".join(rest["sunk"]))
        if rest.get("flew_off"):
            bits.append("FLEW OFF: " + ", ".join(rest["flew_off"]))
    if clock:
        bits.append(f"{clock.get('check_s')} s to show {clock.get('simulated_s')} s"
                    + ("" if clock.get("within_rule", True) else " (slower than the rule allows)"))
    return "; ".join(bits)


def _entry(record: dict[str, Any], title: str, folder: Path, shots: dict[str, Any]) -> str:
    e = html.escape
    state = state_of(record)
    stem = (record.get("spec") or "")[: -len(".spec.json")] if record.get("spec") else ""
    parts = [f'<div class="entry {state}"><div class="entry-head"><span class="chip {state}">'
             f'{LABEL[state]}</span><span class="entry-title">{e(title)}</span>']
    if stem:
        link = f"{OWNER_PLAYGROUND}/world?qa={folder.name}/{stem}"
        parts.append(f'<a class="open" href="{e(link)}">Open in your playground</a>')
    parts.append("</div>")
    parts.append(f'<p class="reason">{e(str(record.get("reason") or ""))}</p>')
    line = _rest_line(record)
    if line:
        parts.append(f'<p class="meta">{e(line)}</p>')
    usage = record.get("usage") or {}
    if usage or record.get("rounds"):
        parts.append(f'<p class="meta">{record.get("rounds")} rounds, {len(record.get("calls") or [])} '
                     f'tool calls, {usage.get("input_tokens", 0):,} tokens in, '
                     f'{usage.get("output_tokens", 0):,} out, {record.get("ask_s")} s asking</p>')
    if record.get("reply"):
        parts.append(f'<blockquote>{e(str(record["reply"])[:900])}</blockquote>')
    for refusal in (record.get("refusals") or [])[:6]:
        parts.append(f'<p class="refused">refused {e(refusal["tool"])}: {e(refusal["error"][:300])}</p>')
    pictures = _pictures(shots.get(stem), folder) if stem else []
    if pictures:
        parts.append('<div class="pictures">' + "".join(
            f'<figure><img src="{e(name)}" alt="{e(title)}, {e(caption)}" loading="lazy">'
            f'<figcaption>{e(caption)}</figcaption></figure>' for name, caption in pictures) + "</div>")
    if record.get("measured"):
        parts.append(f'<details><summary>what the engine measured</summary><pre>'
                     f'{e(json.dumps(record["measured"], indent=1, default=str))}</pre></details>')
    parts.append("</div>")
    return "".join(parts)


def write_report(folder: Path, model: str, recipes: list[dict[str, Any]],
                 trials: list[dict[str, Any]], shots: dict[str, Any], cases: list[abt.Case],
                 started: float) -> Path:
    e = html.escape
    ran = {r["case"] for r in recipes + trials}
    grouped, placed = [], set()
    for title, ids in qa_cases.GROUPS:
        members = [BY_ID[i] for i in ids if i in BY_ID and i in ran]
        placed.update(c.id for c in members)
        if members:
            grouped.append((title, members))
    others = [c for c in cases if c.id in ran and c.id not in placed]
    if others:
        grouped.append(("Other", others))
    most_trials = max((r["trial"] for r in trials), default=0)

    def cell(record: dict[str, Any] | None, anchor: str) -> str:
        if record is None:
            return '<td class="none">&middot;</td>'
        state = state_of(record)
        return (f'<td><a class="chip {state}" href="#{anchor}" title="{e(str(record.get("reason") or ""))}">'
                f'{LABEL[state]}</a></td>')

    rows, details = [], []
    for title, members in grouped:
        rows.append(f'<tr class="group"><th colspan="{3 + most_trials}">{e(title)}</th></tr>')
        for case in members:
            mine = [r for r in recipes if r["case"] == case.id]
            tried = {r["trial"]: r for r in trials if r["case"] == case.id}
            recipe_cells = "".join(
                f'<a class="chip {state_of(r)}" href="#{case.id}" title="{e(r["recipe"])}: '
                f'{e(str(r.get("reason") or ""))}">{LABEL[state_of(r)]}</a>' for r in mine) or "&middot;"
            rows.append(
                f'<tr><td class="case"><a href="#{case.id}">{e(case.id)}</a>'
                f'<span class="tests">{e(case.tests)}</span></td>'
                f'<td class="said">{e(case.message)}</td><td>{recipe_cells}</td>'
                + "".join(cell(tried.get(t), case.id) for t in range(1, most_trials + 1)) + "</tr>")
            entries = [_entry(r, f"recipe: {r['recipe']}", folder, shots) for r in mine]
            entries += [_entry(r, f"trial {r['trial']}", folder, shots) for _, r in sorted(tried.items())]
            failing = any(state_of(r) != "pass" for r in mine + list(tried.values()))
            details.append(
                f'<section id="{case.id}" class="case-detail"><h3>{e(case.id)}</h3>'
                f'<p class="said">&ldquo;{e(case.message)}&rdquo; <span class="scene">in the '
                f'{e(case.scene)}</span></p><p class="tests">Tests {e(case.tests)}.</p>'
                f'<details{" open" if failing else ""}><summary>{len(entries)} runs</summary>'
                + "".join(entries) + "</details></section>")

    def tally(records: list[dict[str, Any]]) -> str:
        passed = sum(1 for r in records if r.get("passed"))
        return f"{passed} of {len(records)}" if records else "none run"

    tokens_in = sum((r.get("usage") or {}).get("input_tokens", 0) for r in trials)
    tokens_out = sum((r.get("usage") or {}).get("output_tokens", 0) for r in trials)
    slow = sum(1 for r in recipes + trials if r.get("too_slow"))
    moving = sum(1 for r in recipes + trials if (r.get("rest") or {}).get("at_rest") is False)
    sunk = sum(1 for r in recipes + trials if (r.get("rest") or {}).get("sunk"))
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(started))
    stats = [("Recipes passed", tally(recipes)), ("Trials passed", tally(trials)),
             ("Stopped by the realtime rule", str(slow)), ("Still moving at the end", str(moving)),
             ("Sank through the floor", str(sunk)),
             ("Tokens", f"{tokens_in:,} in, {tokens_out:,} out" if trials else "none")]
    page = f"""<title>Banjo QA {e(folder.name)}</title>
<meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Spectral:wght@500;600&family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono:wght@500;600&display=swap">
<style>
:root {{
  --ground:#f3f4f0; --card:#fcfcfa; --ink:#1c211e; --muted:#5b655f; --line:#d8dcd4;
  --moss:#34503f; --pass:#1d6b45; --pass-bg:#dff0e6; --fail:#a3271f; --fail-bg:#f8e3e0;
  --slow:#7d5200; --slow-bg:#f7ebcf; --idle:#4f5a54; --idle-bg:#e7e9e4;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --ground:#121513; --card:#191d1b; --ink:#e3e8e4; --muted:#98a39c; --line:#2a312d;
  --moss:#9cc3ab; --pass:#8fd6ae; --pass-bg:#16301f; --fail:#f0a39c; --fail-bg:#3a1b18;
  --slow:#e8c27a; --slow-bg:#352812; --idle:#b4bdb7; --idle-bg:#262b28; }} }}
:root[data-theme="dark"] {{
  --ground:#121513; --card:#191d1b; --ink:#e3e8e4; --muted:#98a39c; --line:#2a312d;
  --moss:#9cc3ab; --pass:#8fd6ae; --pass-bg:#16301f; --fail:#f0a39c; --fail-bg:#3a1b18;
  --slow:#e8c27a; --slow-bg:#352812; --idle:#b4bdb7; --idle-bg:#262b28; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--ground); color:var(--ink);
  font:15px/1.5 "IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:1180px; margin:0 auto; padding:32px 24px 64px; }}
h1,h2,h3 {{ font-family:Spectral,"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  font-weight:600; text-wrap:balance; margin:0; }}
h1 {{ font-size:30px; letter-spacing:.01em; }}
h2 {{ font-size:21px; margin:40px 0 12px; }}
h3 {{ font-size:18px; }}
.lede {{ color:var(--muted); max-width:70ch; margin:8px 0 20px; }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:1px;
  background:var(--line); border:1px solid var(--line); border-radius:6px; overflow:hidden; }}
.stats div {{ background:var(--card); padding:12px 14px; }}
.stats dt {{ color:var(--muted); font-size:12px; letter-spacing:.04em; text-transform:uppercase; }}
.stats dd {{ margin:4px 0 0; font:600 17px/1.3 "IBM Plex Mono",ui-monospace,"Cascadia Mono",Consolas,monospace;
  font-variant-numeric:tabular-nums; }}
.matrix-wrap {{ overflow-x:auto; border:1px solid var(--line); border-radius:6px; background:var(--card); }}
table {{ border-collapse:collapse; width:100%; min-width:760px; }}
th,td {{ text-align:left; vertical-align:top; padding:9px 12px; border-top:1px solid var(--line); }}
thead th {{ border-top:0; color:var(--muted); font-size:12px; letter-spacing:.04em;
  text-transform:uppercase; font-weight:600; }}
tr.group th {{ background:var(--ground); color:var(--moss); font-size:13px; letter-spacing:.03em; }}
td.case a {{ color:var(--ink); font-weight:600; text-decoration:none; }}
td.case .tests {{ display:block; color:var(--muted); font-size:13px; max-width:30ch; }}
td.said {{ color:var(--muted); font-size:13px; max-width:46ch; }}
td.none {{ color:var(--muted); }}
.chip {{ display:inline-block; font:600 11px/1 ui-monospace,Consolas,monospace; letter-spacing:.05em;
  padding:5px 7px; border-radius:4px; text-decoration:none; margin:0 4px 4px 0; white-space:nowrap; }}
.chip.pass {{ color:var(--pass); background:var(--pass-bg); }}
.chip.fail {{ color:var(--fail); background:var(--fail-bg); }}
.chip.slow {{ color:var(--slow); background:var(--slow-bg); }}
.chip.idle {{ color:var(--idle); background:var(--idle-bg); }}
.case-detail {{ border-top:1px solid var(--line); padding:18px 0; }}
.case-detail .said {{ margin:4px 0 0; }}
.case-detail .scene, .case-detail .tests {{ color:var(--muted); font-size:13px; }}
details > summary {{ cursor:pointer; color:var(--moss); font-size:13px; margin:6px 0; }}
.entry {{ background:var(--card); border:1px solid var(--line); border-radius:6px; padding:12px 14px; margin:10px 0; }}
.entry.fail {{ border-left:3px solid var(--fail); }}
.entry.slow {{ border-left:3px solid var(--slow); }}
.entry-head {{ display:flex; gap:10px; align-items:baseline; flex-wrap:wrap; }}
.entry-title {{ font-weight:600; }}
.open {{ margin-left:auto; color:var(--moss); font-size:13px; }}
.reason {{ margin:6px 0 2px; }}
.meta, .refused {{ color:var(--muted); font-size:13px; margin:2px 0; }}
.refused {{ color:var(--fail); }}
blockquote {{ margin:8px 0; padding:6px 12px; border-left:2px solid var(--line); color:var(--muted);
  font-size:13px; max-width:90ch; }}
.pictures {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:10px; margin:10px 0; }}
figure {{ margin:0; }}
figure img {{ width:100%; border-radius:4px; border:1px solid var(--line); display:block; }}
figcaption {{ color:var(--muted); font-size:12px; margin-top:3px; }}
pre {{ font:12px/1.45 ui-monospace,Consolas,monospace; background:var(--ground); padding:10px;
  border-radius:4px; overflow-x:auto; }}
a:focus-visible {{ outline:2px solid var(--moss); outline-offset:2px; }}
</style>
<main>
<h1>Banjo QA</h1>
<p class="lede">{e(when)} &middot; {e(model)}. Every case is a sentence a person might type into the room.
The chat builds it with the MCP's own tools, and the engine then uses what was built and measures it.
A recipe is the same thing built by hand: if a recipe fails, the engine or the check cannot do it.</p>
<dl class="stats">{"".join(f"<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>" for k, v in stats)}</dl>
<h2>Every case</h2>
<div class="matrix-wrap"><table>
<thead><tr><th>Case</th><th>What was asked</th><th>Recipe</th>{"".join(f"<th>Trial {t}</th>" for t in range(1, most_trials + 1))}</tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
<h2>What happened</h2>
{"".join(details)}
</main>
"""
    target = folder / "index.html"
    target.write_text(page, encoding="utf-8")
    return target


def share(folder: Path) -> Path:
    """A copy of the report small enough to send or publish: every picture an
    800-pixel JPEG beside it. The playground links still point at the owner's
    own playground, which is where a build can be tried by hand."""
    from PIL import Image
    out = folder / "share"
    pictures = out / "pics"
    pictures.mkdir(parents=True, exist_ok=True)

    def swap(match: re.Match) -> str:
        source = folder / match.group(1)
        if not source.is_file():
            return match.group(0)
        target = pictures / (source.stem + ".jpg")
        with Image.open(source) as image:
            image = image.convert("RGB")
            image.thumbnail((800, 800))
            image.save(target, "JPEG", quality=80, optimize=True)
        return f'src="pics/{target.name}"'

    page = (folder / "index.html").read_text(encoding="utf-8")
    page = re.sub(r'src="([^"]+\.png)"', swap, page)
    page = re.sub(r"<title>.*?</title>", "<title>Banjo Playground QA</title>", page, count=1)
    (out / "index.html").write_text(page, encoding="utf-8")
    return out


def summary_text(model: str, recipes: list[dict[str, Any]], trials: list[dict[str, Any]],
                 cases: list[abt.Case]) -> str:
    lines = [f"QA -- {model}", "", "recipes:"]
    for r in recipes:
        lines.append(f"  {LABEL[state_of(r)]:9s} {r['recipe']:22s} {r.get('reason')}")
        extra = _rest_line(r)
        if extra:
            lines.append(f"            {extra}")
    lines.append("")
    if trials:
        lines.append(abt.summarise(trials, model, cases))
    return "\n".join(lines)


# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cases", default="", help="comma-separated parts of case ids")
    parser.add_argument("--trials", type=int, default=2)
    parser.add_argument("--jobs", type=int, default=3, help="trials at once")
    parser.add_argument("--model", default=None)
    parser.add_argument("--recipes", action="store_true", help="recipes only: no model, no cost")
    parser.add_argument("--no-recipes", action="store_true")
    parser.add_argument("--no-3d", action="store_true")
    parser.add_argument("--port", type=int, default=8772, help="the playground the pictures use")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--rebuild", metavar="RUN",
                        help="write a run's report again from its report.json (a folder name "
                             "under build/agent-regression)")
    parser.add_argument("--share", action="store_true",
                        help="also write <run>/share/: the report with small JPEG pictures")
    parser.add_argument("--photos", metavar="RUN",
                        help="photograph a finished run's builds again, and write its report again")
    parser.add_argument("--retry", metavar="RUN",
                        help="ask again, into the same run, for the trials that never reached "
                             "the model")
    args = parser.parse_args(argv)

    wanted = [w.strip() for w in args.cases.split(",") if w.strip()]
    cases = [c for c in CASES if not wanted or any(w in c.id for w in wanted)]
    if args.rebuild:
        folder = ROOT / "build" / "agent-regression" / args.rebuild
        data = json.loads((folder / "report.json").read_text(encoding="utf-8"))
        model = data.get("model") or "recipes only"
        page = write_report(folder, model, data["recipes"], data["trials"], data.get("seen") or {},
                            CASES, data.get("started") or time.time())
        (folder / "summary.txt").write_text(
            summary_text(model, data["recipes"], data["trials"], CASES), encoding="utf-8")
        print(f"report: {page}")
        if args.share:
            print(f"shareable: {share(folder) / 'index.html'}")
        return 0
    if args.photos or args.retry:
        # A run finished, and one part of it done again: its pictures, or the
        # trials a network failure kept from ever reaching the model -- which
        # say nothing about the chat and should not count against it.
        folder = ROOT / "build" / "agent-regression" / (args.photos or args.retry)
        data = json.loads((folder / "report.json").read_text(encoding="utf-8"))
        recipes, trials, shots = data["recipes"], data["trials"], data.get("seen") or {}
        model = data.get("model") or ""
        fresh = recipes + trials
        if args.retry:
            import server
            api_key, configured = server.local_configuration()
            model = args.model or model or configured
            again = [(BY_ID[r["case"]], r["trial"]) for r in trials
                     if UNREACHED in str(r.get("reason") or "") and r["case"] in BY_ID]
            print(f"asking again for {len(again)} trial(s) that never reached the model", flush=True)
            fresh = run_trials(again, api_key, model, folder, args.jobs)
            redone = {(c.id, t) for c, t in again}
            order = [c.id for c in CASES]
            trials = sorted([r for r in trials if (r["case"], r["trial"]) not in redone] + fresh,
                            key=lambda r: (order.index(r["case"]), r["trial"]))
        if not args.no_3d:
            shots.update(photograph(fresh, folder, args.port))
        (folder / "report.json").write_text(json.dumps(
            {**data, "model": model, "trials": trials, "seen": shots}, indent=1, default=str),
            encoding="utf-8")
        (folder / "summary.txt").write_text(summary_text(model, recipes, trials, CASES),
                                            encoding="utf-8")
        page = write_report(folder, model, recipes, trials, shots, CASES,
                            data.get("started") or time.time())
        print(f"report: {page}")
        if args.share:
            print(f"shareable: {share(folder) / 'index.html'}")
        return 0
    if args.list:
        for c in cases:
            recipes = ", ".join(recipes_for([c])) or "-"
            print(f"{c.id:24s} [{c.scene}] recipes: {recipes}\n{'':24s} {c.message}")
        return 0
    if abt.ENGINE is None:
        print(f"no live engine in {BUILD}: set BANJO_BUILD_DIR to a Release build")
        return 2
    model, api_key = args.model or "", ""
    if not args.recipes:
        import server
        api_key, configured = server.local_configuration()
        model = args.model or configured
        if not api_key:
            print("OPENAI_API_KEY is not configured in the local .env; trials ask a real model. "
                  "--recipes runs without one.")
            return 2
    started = time.time()
    folder = ROOT / "build" / "agent-regression" / time.strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    print(f"QA of {len(cases)} case(s) into {folder}", flush=True)

    recipes = [] if args.no_recipes else run_recipes(cases, folder)
    trials: list[dict[str, Any]] = []
    if not args.recipes:
        print(f"{len(cases)} case(s) x {args.trials} trial(s) against {model}", flush=True)
        trials = run_trials([(c, t) for c in cases for t in range(1, args.trials + 1)],
                            api_key, model, folder, args.jobs)
    shots: dict[str, Any] = {}
    if not args.no_3d:
        try:
            shots = photograph(recipes + trials, folder, args.port)
        except Exception:
            print("  the pictures failed: " + traceback.format_exc()[-600:], flush=True)
    (folder / "report.json").write_text(json.dumps(
        {"model": model, "started": started, "recipes": recipes, "trials": trials, "seen": shots},
        indent=1, default=str), encoding="utf-8")
    summary = summary_text(model or "recipes only", recipes, trials, cases)
    (folder / "summary.txt").write_text(summary, encoding="utf-8")
    page = write_report(folder, model or "recipes only", recipes, trials, shots, cases, started)
    print()
    print(summary)
    print(f"\nreport: {page}")
    if args.share:
        print(f"shareable: {share(folder) / 'index.html'}")
    return 0 if all(r.get("passed") for r in recipes + trials) else 1


if __name__ == "__main__":
    sys.exit(main())
