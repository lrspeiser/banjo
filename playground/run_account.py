"""What a run actually did, in the words the request used.

The chat used to hear one sentence back from a run: "Done in 3.9 s. 0 bonds
broken, 2 pieces." That sentence is identical whether the ball launched off the
ramp in a perfect arc or sat motionless for four seconds, so a model that asked
for a ramp and got a staircase had no way to find out. It could not learn,
because it was never told.

Everything here is arithmetic on the recording. No model is involved, and that is
deliberate: this is the one channel whose whole job is to tell the model the truth
about the world, and a summariser that could write "the ball struck the pins" when
it did not would teach the wrong lesson confidently -- worse than silence. So this
reports only what it can measure, and says plainly when it cannot measure
something. The model consumes these sentences; it never writes them.

The recording already carries the author's own names: a body's `material_id` is
"pin7 (glass)", the name the request chose. The account speaks that vocabulary
back, which is what lets a model connect what it asked for to what happened.

Contacts are read, not inferred. The recording carries Jolt's own contact
callbacks, aggregated per pair of named objects: when they first touched and how
hard the hardest touch was. Inferring them instead from how close two centres came
gets visibly wrong answers -- a ball resting on a lane from the first frame reads
as "reached the lane" the moment its centre falls inside the lane's longest
dimension -- so nothing here guesses at one. A pair with no recorded contact is
simply not mentioned.
"""
from __future__ import annotations

from typing import Any

# A body has moved when it has left its own starting position by a quarter of a
# cell. Below that is solver jitter and settling, not motion anyone asked about.
MOVED_CELLS = 0.25
# Slower than this at the end of the run counts as stopped. A millimetre a second
# is a body at rest being nudged by its neighbours.
RESTING_SPEED_M_S = 0.05
# Below the ground by this much and a body is gone rather than lying on the floor.
FELL_OUT_M = 1.0
# Beyond this many objects the per-object lines are grouped, so a rack of ten
# pins is one line rather than ten.
GROUP_ABOVE = 8
# Below this a contact is two things leaning on each other, which is how a scene
# starts and is not what anyone asked about. Above it something arrived.
STRUCK_SPEED_M_S = 0.5
# How many impacts are worth listing. They are sorted hardest first, so the cap
# keeps the strike and drops the rattle.
MOST_CONTACTS = 6
AXES = "xyz"


def _distance(a: list[float], b: list[float]) -> float:
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


def _tracks(playback: dict[str, Any]) -> dict[str, list[tuple[float, list[float]]]]:
    """The centroid of every authored object at every recorded frame.

    A body is drawn as many cells or as one primitive; either way its cells all
    carry the same `material_id`, so grouping on that recovers the object the
    request named. A centroid transforms rigidly, so it is the right summary of
    where an unbroken object is, and for a broken one it is where its pieces are
    on average -- which is still the honest answer to "where did it go".
    """
    group_of: dict[str, str] = {}
    for body in playback.get("bodies", []):
        group_of[body["id"]] = str(body.get("material_id") or body["id"])
    names = sorted(set(group_of.values()))
    out: dict[str, list[tuple[float, list[float]]]] = {name: [] for name in names}
    for frame in playback.get("frames", []):
        sums: dict[str, list[float]] = {}
        counts: dict[str, int] = {}
        for pose in frame.get("poses", []):
            name = group_of.get(pose["id"])
            if name is None:
                continue
            position = pose["position_m"]
            acc = sums.get(name)
            if acc is None:
                sums[name] = list(position)
                counts[name] = 1
            else:
                acc[0] += position[0]
                acc[1] += position[1]
                acc[2] += position[2]
                counts[name] += 1
        time_s = float(frame.get("time_s", 0.0))
        for name, acc in sums.items():
            n = float(counts[name])
            out[name].append((time_s, [acc[0] / n, acc[1] / n, acc[2] / n]))
    return {name: path for name, path in out.items() if len(path) >= 2}


def _behaviour(path: list[tuple[float, list[float]]], moved_m: float,
               ground_y: float) -> dict[str, Any]:
    start, end = path[0][1], path[-1][1]
    displacement = _distance(start, end)
    axis = max(range(3), key=lambda i: abs(end[i] - start[i]))
    onset = None
    for time_s, centre in path:
        if _distance(centre, start) > moved_m:
            onset = time_s
            break
    (t0, c0), (t1, c1) = path[-2], path[-1]
    final_speed = _distance(c0, c1) / max(t1 - t0, 1e-9)
    # The last moment it was still going, which is when it came to rest.
    settled_at = None
    if final_speed <= RESTING_SPEED_M_S:
        settled_at = path[-1][0]
        for index in range(len(path) - 1, 0, -1):
            (ta, ca), (tb, cb) = path[index - 1], path[index]
            if _distance(ca, cb) / max(tb - ta, 1e-9) > RESTING_SPEED_M_S:
                settled_at = tb
                break
    fell_out_at = None
    if end[1] < ground_y - FELL_OUT_M:
        for time_s, centre in path:
            if centre[1] < ground_y - FELL_OUT_M:
                fell_out_at = time_s
                break
    return {"moved_m": displacement, "axis": AXES[axis],
            "sign": "+" if end[axis] >= start[axis] else "-",
            "onset_s": onset, "final_speed_m_s": final_speed,
            "settled_at_s": settled_at, "fell_out_at_s": fell_out_at,
            "moved": displacement > moved_m}


def _stem(name: str) -> str:
    """"pin7 (glass)" and "pin10 (glass)" share the stem "pin (glass)"."""
    head, _, tail = name.partition(" (")
    return head.rstrip("0123456789_- ") + (" (" + tail if tail else "")


def _describe(name: str, b: dict[str, Any], anchored: bool, launched: bool) -> str:
    if not b["moved"]:
        return f"{name}: did not move" + (" (anchored)" if anchored else "")
    where = f"moved {b['moved_m']:.2f} m ({b['sign']}{b['axis']})"
    if b["fell_out_at_s"] is not None:
        return f"{name}: {where}, then fell out of the scene at t={b['fell_out_at_s']:.2f} s"
    if b["settled_at_s"] is not None:
        started = "" if launched else f"started moving at t={b['onset_s']:.2f} s, " if b["onset_s"] else ""
        return f"{name}: {started}{where}, came to rest by t={b['settled_at_s']:.2f} s"
    started = "" if launched else f"started moving at t={b['onset_s']:.2f} s, " if b["onset_s"] else ""
    return (f"{name}: {started}{where}, still moving at "
            f"{b['final_speed_m_s']:.1f} m/s when the recording ended")


def account(playback: dict[str, Any], report: dict[str, Any],
            spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """A factual account of one run. Returns {"lines": [...], "facts": {...}}."""
    measurements = (report or {}).get("measurements") or {}
    lattice = measurements.get("lattice") or {}
    cell_m = float(measurements.get("cell_size_m") or 0.02)
    moved_m = MOVED_CELLS * cell_m
    supports = playback.get("supports") or []
    ground_y = float(supports[0][0][1]) if supports and supports[0] else 0.0

    anchored: set[str] = set()
    launched: set[str] = set()
    for body in ((spec or {}).get("bodies") or []):
        material = body.get("material", "")
        name = f"{body.get('name')} ({material})"
        if body.get("anchored"):
            anchored.add(name)
        if any(body.get("velocity_m_s") or []):
            launched.add(name)

    tracks = _tracks(playback)
    behaviour = {name: _behaviour(path, moved_m, ground_y) for name, path in tracks.items()}

    lines: list[str] = []
    if len(behaviour) > GROUP_ABOVE:
        # Group siblings that behaved alike, so a rack of pins is one line.
        buckets: dict[tuple[str, bool], list[tuple[str, dict[str, Any]]]] = {}
        for name, b in behaviour.items():
            buckets.setdefault((_stem(name), b["moved"]), []).append((name, b))
        for (stem, moved), members in sorted(buckets.items()):
            if len(members) == 1:
                name, b = members[0]
                lines.append(_describe(name, b, name in anchored, name in launched))
            elif not moved:
                lines.append(f"{stem} x{len(members)}: none of them moved")
            else:
                low = min(m[1]["moved_m"] for m in members)
                high = max(m[1]["moved_m"] for m in members)
                onsets = [m[1]["onset_s"] for m in members if m[1]["onset_s"] is not None]
                when = f", first moved at t={min(onsets):.2f} s" if onsets else ""
                lines.append(f"{stem} x{len(members)}: all moved, "
                             f"{low:.2f} to {high:.2f} m{when}")
    else:
        for name in sorted(behaviour):
            lines.append(_describe(name, behaviour[name], name in anchored, name in launched))

    # What broke, and if nothing did, why not -- which is the lesson.
    broken = int(lattice.get("broken_bonds") or 0)
    window_end_s = max((float(f.get("time_s", 0.0)) for f in playback.get("frames", [])
                        if f.get("phase") == "lattice"), default=0.0)
    first_break_s = next((float(f["time_s"]) for f in playback.get("frames", [])
                          if f.get("fracture_count")), None)
    facts: dict[str, Any] = {"broken_bonds": broken, "window_end_s": window_end_s,
                             "first_break_s": first_break_s,
                             "max_damage": lattice.get("max_damage")}
    if broken:
        pieces = (measurements.get("handoff") or {}).get("components")
        at = "" if first_break_s is None else f", first at t={first_break_s:.4f} s"
        lines.append(f"BROKE: {broken} bonds into {pieces} pieces{at}")
    else:
        worst = float(lattice.get("max_damage") or 0.0)
        how_close = (f"the worst-stressed bond reached {100 * worst:.0f}% of what it "
                     f"takes to fail" if worst > 0.005 else
                     "nothing in the scene was measurably stressed")
        lines.append(f"NOTHING BROKE: {how_close}.")
        # The causal fact, and the one a request most often gets wrong. This
        # deliberately does not claim what hit what -- the recording carries no
        # contact events and guessing them from how close two centres came gets
        # visibly wrong answers. It states the window, which is measured, and
        # lets the timings above speak for themselves.
        moving_late = [b["onset_s"] for name, b in behaviour.items()
                       if b["onset_s"] is not None and b["onset_s"] > window_end_s
                       and name not in anchored]
        if moving_late:
            lines.append(
                f"  Fracture is only computed during the lattice window, which here was "
                f"t=0 to t={window_end_s * 1000:.0f} ms -- the first {window_end_s * 1000:.0f} "
                f"ms of the run. Everything after that is resolved as rigid bodies, which "
                f"collide and tumble but never break. Objects that only meet later (a ball "
                f"rolled into a stack, a piece landing) cannot fracture anything. For "
                f"something to break, it has to be under load in that first window.")
            facts["impact_after_window"] = True

    # Who hit what, hardest first. Measured by Jolt, not inferred here.
    contacts = [c for c in (playback.get("contacts") or [])
                if float(c.get("peak_closing_speed_m_s") or 0.0) >= STRUCK_SPEED_M_S]
    contacts.sort(key=lambda c: -float(c.get("peak_closing_speed_m_s") or 0.0))
    if contacts:
        lines.append("IMPACTS (measured, hardest first):")
        for c in contacts[:MOST_CONTACTS]:
            lines.append(f"  {c['a']} hit {c['b']} at t={float(c['first_time_s']):.2f} s, "
                         f"closing at {float(c['peak_closing_speed_m_s']):.1f} m/s")
        if len(contacts) > MOST_CONTACTS:
            lines.append(f"  ...and {len(contacts) - MOST_CONTACTS} more")
        facts["impacts"] = contacts
    elif playback.get("contacts") is not None:
        lines.append("IMPACTS: nothing struck anything; "
                     "every contact was two objects resting against each other.")

    ratio = measurements.get("realtime_ratio")
    if isinstance(ratio, (int, float)) and ratio > 0:
        verdict = "inside the 1.1x limit" if ratio <= 1.1 else "OVER the 1.1x limit"
        lines.append(f"COST: {ratio:.2f}x realtime, {verdict}.")
        facts["realtime_ratio"] = ratio
    facts["objects"] = {name: behaviour[name] for name in behaviour}
    return {"lines": lines, "facts": facts}


def render(result: dict[str, Any]) -> str:
    """The account as one block of text, which is what the chat turn carries."""
    return "\n".join(result["lines"])
