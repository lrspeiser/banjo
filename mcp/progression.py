"""What a person knows, kept apart from what the world is.

The knowledge layer of docs/knowledge-and-progression.md, increment 2: the
registries of techniques, processes and designs (progression/*.json), one
person's journal, and the evaluator that turns what the ENGINE measured a tool
doing into scoped evidence.

Nothing here imports the engine or changes a world. The engine has no parameter
a journal could travel in, and this has no call that makes anything happen: a
query spends nothing, and there is no tool that awards anything. A journal
changes only when the evaluator reads a result the engine accepted -- never one
it is handed to believe, never a scratch-world trial, never "not supported".

Shared by the MCP server (read_knowledge) and the playground's server, which
keeps a person's journal on disk beside their rooms and evaluates what their
own hand did in their own world.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import interaction_profiles

DEFINITIONS = Path(__file__).resolve().parents[1] / "progression"
JOURNAL_FORMAT = "banjo.journal.v1"
# The flags a design's standing is made of: not a ladder, any can come first
# (docs/knowledge-and-progression.md, 3.4).
STANDINGS = ("proposed", "instructions", "built", "found", "demonstrated")


class DefinitionError(ValueError):
    """The starting graph does not hold together. Said when it is loaded, so a
    graph that could strand a player is never served."""


def _read(folder: Path, name: str, form: str, key: str) -> dict[str, Any]:
    path = folder / name
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as failure:
        raise DefinitionError(f"{name}: {failure}") from None
    if document.get("format") != form or not isinstance(document.get(key), list):
        raise DefinitionError(f"{name} is not {form} with a list of {key}")
    return document


def _by_id(items: list[dict[str, Any]], what: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        ident = item.get("id")
        if not isinstance(ident, str) or not ident:
            raise DefinitionError(f"a {what} has no id: {json.dumps(item)[:120]}")
        if ident in out:
            raise DefinitionError(f"two {what}s are called {ident!r}")
        out[ident] = item
    return out


class Registry:
    """The curated graph: what can be known, made and used, checked when it is
    loaded. Small on purpose -- no graph database -- and versioned JSON."""

    def __init__(self, folder: Path | str = DEFINITIONS) -> None:
        folder = Path(folder)
        self.techniques = _by_id(_read(folder, "techniques.json", "banjo.progression.techniques.v1",
                                       "techniques")["techniques"], "technique")
        self.processes = _by_id(_read(folder, "processes.json", "banjo.progression.processes.v1",
                                      "processes")["processes"], "process")
        designs = _read(folder, "designs.json", "banjo.progression.designs.v1", "designs")
        self.designs = _by_id(designs["designs"], "design")
        self.material_classes: dict[str, list[str]] = dict(designs.get("material_classes") or {})
        start = json.loads((folder / "start.json").read_text(encoding="utf-8"))
        if start.get("format") != "banjo.progression.start.v1":
            raise DefinitionError("start.json is not banjo.progression.start.v1")
        self.start = start
        self.check()

    # -- the checks the doc asks for (3.3) -----------------------------------

    def check(self) -> None:
        for technique in self.techniques.values():
            for process in technique.get("processes") or []:
                if process not in self.processes:
                    raise DefinitionError(f"technique {technique['id']} names the process "
                                          f"{process!r}, which is not registered")
            for need in (technique.get("prerequisites") or {}).get("all_of") or []:
                if need not in self.techniques:
                    raise DefinitionError(f"technique {technique['id']} needs {need!r}, "
                                          f"which is not a technique")
            # What earns it, if anything does. A technique with no earned_by
            # and no prerequisites can only be taught, which is a real kind of
            # technique and not an error -- but a condition that names a design
            # nobody has is a dead rung, and the point of checking the graph at
            # load is that a dead rung is found here and not by a player.
            for route in (technique.get("earned_by") or {}).get("any_of") or []:
                if not route.get("all_of"):
                    raise DefinitionError(f"technique {technique['id']}: the route "
                                          f"{route.get('id')!r} asks for nothing, so it is "
                                          f"already earned by everybody")
                for need in route["all_of"]:
                    design = need.get("design")
                    if design not in self.designs:
                        raise DefinitionError(f"technique {technique['id']}, route "
                                              f"{route.get('id')!r}: {design!r} is not a design")
                    if "found" not in need and "demonstrated" not in need:
                        raise DefinitionError(f"technique {technique['id']}, route "
                                              f"{route.get('id')!r}: a condition is met by "
                                              f"finding a design or by demonstrating one")
                    test = need.get("test")
                    if test is not None and test not in {t.get("id") for t
                                                         in self.designs[design].get("tests") or []}:
                        raise DefinitionError(f"technique {technique['id']}, route "
                                              f"{route.get('id')!r}: {design} has no test "
                                              f"called {test!r}")
        for design in self.designs.values():
            template = (design.get("interaction") or {}).get("template")
            if template is not None and template not in interaction_profiles.TEMPLATES:
                raise DefinitionError(f"design {design['id']} is used as {template!r}, which is "
                                      f"not a registered interaction template")
            roles = {c.get("role") for c in design.get("components") or []}
            routes = (design.get("routes") or {}).get("any_of")
            if not isinstance(routes, list) or not routes:
                raise DefinitionError(f"design {design['id']} has no route: any_of is empty")
            for route in routes:
                for need in route.get("all_of") or []:
                    if "component" in need and need["component"] not in roles:
                        raise DefinitionError(f"design {design['id']}, route {route.get('id')}: "
                                              f"no component is called {need['component']!r}")
                    if "process" in need and need["process"] not in self.processes:
                        raise DefinitionError(f"design {design['id']}, route {route.get('id')}: "
                                              f"the process {need['process']!r} is not registered")
                    if "technique" in need and need["technique"] not in self.techniques:
                        raise DefinitionError(f"design {design['id']}, route {route.get('id')}: "
                                              f"the technique {need['technique']!r} is not registered")
        self._no_cycles()
        for first in self.start.get("first_tools") or []:
            if first not in self.designs:
                raise DefinitionError(f"the start's first tool {first!r} is not a design")
            holds, knows = self.start.get("holds") or [], set(self.start.get("teaches") or [])
            if not any(not self.blockers(self.designs[first], route, holds, knows)
                       for route in self.designs[first]["routes"]["any_of"]):
                raise DefinitionError(f"no route to {first} is open from the start: a player "
                                      f"would be stranded")

    def _no_cycles(self) -> None:
        """A depth-first walk over requirement edges, refusing any back edge:
        a technique's prerequisites, and a component that is itself a design."""
        edges: dict[str, list[str]] = {}
        for technique in self.techniques.values():
            edges[f"technique:{technique['id']}"] = [
                f"technique:{t}" for t in (technique.get("prerequisites") or {}).get("all_of") or []]
        for design in self.designs.values():
            out = []
            for component in design.get("components") or []:
                inner = (component.get("requires") or {}).get("design")
                if inner:
                    out.append(f"design:{inner}")
            for route in design["routes"]["any_of"]:
                out += [f"technique:{n['technique']}" for n in route.get("all_of") or [] if "technique" in n]
            edges[f"design:{design['id']}"] = out
        state: dict[str, str] = {}

        def walk(node: str, path: list[str]) -> None:
            state[node] = "open"
            for nxt in edges.get(node, []):
                if state.get(nxt) == "open":
                    raise DefinitionError("a requirement cycle: " + " -> ".join(path + [node, nxt]))
                if nxt not in state:
                    walk(nxt, path + [node])
            state[node] = "done"

        for node in edges:
            if node not in state:
                walk(node, [])

    # -- what stands between a person and a route ----------------------------

    def blockers(self, design: dict[str, Any], route: dict[str, Any],
                 holds: list[dict[str, Any]], knows: set[str]) -> list[str]:
        """What keeps this route to this design from being taken, in words a
        person reads; empty when it is open. A found thing short-circuits its
        own subtree: knowing how it was made is never needed to use it."""
        if "all_of" not in route:
            if {"found": design["id"]} in holds:
                return []
            return [f"no {design.get('name', design['id'])} has been found"]
        out: list[str] = []
        for need in route["all_of"]:
            if "component" in need and not any(h.get("component") == need["component"] for h in holds):
                out.append(f"no {need['component']} to make it from")
            if "process" in need:
                process = self.processes[need["process"]]
                if not process.get("supported"):
                    out.append(f"the engine does not run {process['id']} yet: it arrives with "
                               f"{process.get('arrives_with', 'work not yet planned')}")
            if "technique" in need and need["technique"] not in knows:
                out.append(f"the technique {self.techniques[need['technique']]['name']} is not known")
            for item in need.get("equipment") or []:
                if not any(h.get("equipment") == item for h in holds):
                    out.append(f"no {item}")
        return out


class Journal:
    """One person's knowledge: the techniques they know, each design by its
    standing, and the evidence each standing rests on.

    Kept whole on disk -- written to a new file, then put in place -- beside the
    person's rooms, so it outlives every room rebuild and server restart. Nothing
    that happens to an object shortens it: breaking the pick removes nothing
    here. Evidence is added once per engine result, whatever asks twice."""

    def __init__(self, path: Path | str | None = None, owner: str = "you") -> None:
        self.path = Path(path) if path is not None else None
        self.lock = threading.Lock()
        self.data: dict[str, Any] = {"format": JOURNAL_FORMAT, "owner": {"player": owner},
                                     "revision": 0, "techniques": {}, "designs": {},
                                     "evidence": {}, "events": []}
        if self.path is not None and self.path.is_file():
            try:
                kept = json.loads(self.path.read_text(encoding="utf-8"))
                if kept.get("format") == JOURNAL_FORMAT:
                    self.data = kept
            except (OSError, ValueError):
                # Set aside with the time, never deleted, and started again.
                self.path.replace(self.path.with_name(
                    f"{self.path.name}.unreadable-{time.strftime('%Y%m%d-%H%M%S')}"))

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        partial = self.path.with_name(self.path.name + ".partial")
        partial.write_text(json.dumps(self.data, allow_nan=False, indent=1), encoding="utf-8")
        os.replace(partial, self.path)

    def add_evidence(self, record: dict[str, Any]) -> bool:
        """Keep one evidence record and what it shows. False, and nothing
        changed, when this engine result was already counted."""
        with self.lock:
            if record["id"] in self.data["evidence"]:
                return False
            self.data["evidence"][record["id"]] = record
            design = self.data["designs"].setdefault(record["design"], {"standing": {}})
            standing = design["standing"]
            if record.get("source") == "found-example":
                standing.setdefault("found", {"since": record["at"], "object": record["object"]})
            if record.get("passes"):
                shown = standing.setdefault("demonstrated", {})
                shown.setdefault(record["test"], []).append(record["id"])
                self.data["events"].append(f"{record['id']}:demonstrated:{record['test']}")
            else:
                self.data["events"].append(f"{record['id']}:recorded:{record['test']}")
            self.data["revision"] += 1
            self._save()
            return True

    def add_note(self, key: str, text: str) -> bool:
        """A regime the engine said it does not model, met by this person's own
        tool: a note, never evidence. Once per result, like evidence."""
        with self.lock:
            notes = self.data.setdefault("notes", {})
            if key in notes:
                return False
            notes[key] = text
            self.data["revision"] += 1
            self._save()
            return True

    def learn(self, technique: str, source: dict[str, Any], at: str) -> bool:
        """Write one technique into the journal. False, and nothing changed,
        when it was already known: a technique is learned once and no source
        overwrites another.

        Nothing about matter is touched here, and nothing here can be read by a
        physics law. Learning stoneworking does not harden a wooden pick.
        """
        with self.lock:
            if technique in self.data["techniques"]:
                return False
            self.data["techniques"][technique] = {"since": at, "source": source}
            self.data["events"].append(f"{technique}:learned:{source.get('kind', 'unknown')}")
            self.data["revision"] += 1
            self._save()
            return True

    def standing_of(self, design: str) -> dict[str, Any]:
        """How a design stands with this person, by its id, whatever revision
        they met: found, built, demonstrated. Flags, not a ladder."""
        out: dict[str, Any] = {}
        with self.lock:
            for key, entry in self.data["designs"].items():
                if key.split("@", 1)[0] != design:
                    continue
                for name, value in (entry.get("standing") or {}).items():
                    if name == "demonstrated":
                        shown = out.setdefault("demonstrated", {})
                        for test, records in (value or {}).items():
                            shown.setdefault(test, []).extend(records)
                    else:
                        out.setdefault(name, value)
        return out

    def knows(self) -> set[str]:
        return set(self.data["techniques"])

    def copy(self) -> dict[str, Any]:
        with self.lock:
            return json.loads(json.dumps(self.data))


# -- which design a built thing is --------------------------------------------

def construction_of(spec: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """What a thing in a room IS, read from the room's own document (millimetres,
    as fracture_lab keeps it): its parts' sizes and materials, whether they are
    one piece (one join), and its tool's point. Properties only -- what it is
    called changes nothing, the way it changes nothing in the physics."""
    bodies = {b.get("name"): b for b in spec.get("bodies") or []}
    parts = [bodies[p] for p in profile.get("parts") or [] if p in bodies]
    names = {b["name"] for b in parts}
    joins = {b.get("join") or b["name"] for b in parts}
    point = next((p for p in spec.get("tool_points") or [] if p.get("body") in names), None)
    return {
        "template": profile.get("template"),
        "one_piece": len(joins) == 1,
        "parts": sorted(({"size_m": sorted(round(float(v) / 1000.0, 3) for v in b.get("size_mm") or []),
                          "material": b.get("material", ""), "shape": b.get("shape", "")}
                         for b in parts), key=lambda p: (p["size_m"], p["material"])),
        "point": None if point is None else {
            "width_m": round(float(point.get("width_mm", 40.0)) / 1000.0, 3),
            "thickness_m": round(float(point.get("thickness_mm", 40.0)) / 1000.0, 3),
            "angle_deg": round(float(point.get("angle_deg", 30.0)), 1),
            "length_m": round(float(point.get("length_mm", 150.0)) / 1000.0, 3)}}


def design_of(registry: Registry, construction: dict[str, Any]) -> str | None:
    """The registered design this construction is, as "id@revision" -- or None
    when it is a construction of its own. Every part must be one of the design's
    parts (each size within its tolerance, whichever way it is turned) in one of
    its material class's materials, one piece when the design is, used by the
    same template, with a point of the same width, thickness and angle."""
    for design in registry.designs.values():
        made = design.get("construction") or {}
        within = float(made.get("matches_within_m", 0.005))
        if (design.get("interaction") or {}).get("template") != construction["template"]:
            continue
        if bool(made.get("one_piece")) != construction["one_piece"]:
            continue
        materials = set(registry.material_classes.get(made.get("material_class", ""), []))
        wanted = [sorted(float(v) for v in part["size_m"]) for part in made.get("parts") or []]
        built = [part["size_m"] for part in construction["parts"]]
        if len(wanted) != len(built) or any(p["material"] not in materials for p in construction["parts"]):
            continue
        unmatched = list(built)
        for size in wanted:
            hit = next((b for b in unmatched if len(b) == 3
                        and all(abs(x - y) <= within for x, y in zip(size, b))), None)
            if hit is None:
                break
            unmatched.remove(hit)
        else:
            point, spec_point = construction["point"], made.get("tool_point")
            if spec_point is not None:
                if point is None:
                    continue
                if (abs(point["width_m"] - float(spec_point["width_m"])) > within
                        or abs(point["thickness_m"] - float(spec_point["thickness_m"])) > within
                        or abs(point["angle_deg"] - float(spec_point["angle_deg"])) > 1.0):
                    continue
            return f"{design['id']}@{design['revision']}"
    return None


def own_design_key(construction: dict[str, Any]) -> str:
    """A construction no registered design matches is a design of its own, and
    its evidence is kept under it: the same numbers are the same key, and any
    change is a new revision whose claims have to be shown again (3.2)."""
    canonical = json.dumps(construction, sort_keys=True, separators=(",", ":"))
    return "own:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:10]


# -- the experiment evaluator -------------------------------------------------
#
# A ground-work record is what the engine measured one meeting of a tool's point
# with the ground doing (docs/ground-work.md; the wire's field names). It carries
# no id of its own: the engine numbers points per world and forgets closed
# records. So a result is named by where it came from -- the live world's
# session, the point, the world time the meeting opened and how it ended -- and
# only a CLOSED record is read: an open one is still being measured, and repeats
# in every reply until it closes. The playground reads these only from its live
# room's own replies, so a scratch-world trial or the chat's copy never reaches
# here.

# What ground-work-v1 is not, in docs/ground-work.md's own words.
GROUND_WORK_LIMITS = ["ground-work-v1 is declared, not calibrated against a real pick in real soil",
                      "no wet ground", "no fracture of rock under a point", "no wear"]


# How long a strike's stroke lasts at most: LiveStrike gives up after 2 s.
STRIKE_WINDOW_S = 2.0


def from_a_strike(record: dict[str, Any], strikes: list[float],
                  window_s: float = STRIKE_WINDOW_S) -> bool:
    """Whether a ground-work record is what one of the person's strikes did: its
    point met the ground (at_s, the world time the meeting opened) within a
    strike's stroke. A pick put down onto the rock meets it too -- measured, at
    3.7 m/s -- and that is no test of what the pick is for."""
    at = float(record.get("at_s", -1.0))
    return any(s - 0.1 <= at <= s + window_s for s in strikes)


def _the(name: str) -> str:
    return name if name.lower().startswith(("the ", "a ", "an ")) else f"the {name}"


def result_key(session_id: str, record: dict[str, Any]) -> str:
    return (f"{session_id}:{record.get('point')}:{float(record.get('at_s', 0.0)):.5f}:"
            f"{record.get('kind')}")


def evidence_from(record: dict[str, Any], *, session_id: str, spec: dict[str, Any],
                  registry: Registry, at: str) -> dict[str, Any] | None:
    """One evidence record from one closed ground-work record, or None when it
    is not evidence of anything: still open, a glance, a tool that is not a
    swing-and-lever thing in this room, or a regime the engine does not model
    (a note of that is kept by the caller, not a claim). Scoped to what was
    tried: this design revision, this ground, this action."""
    if record.get("open") or record.get("kind") not in ("broke out", "pulled out", "stopped"):
        return None
    if not record.get("supported", True):
        return None
    tool = record.get("tool")
    profile = next((p for p in spec.get("interactions") or []
                    if p.get("template") == "swing-and-lever" and tool in (p.get("parts") or [])), None)
    if profile is None:
        return None
    construction = construction_of(spec, profile)
    design = design_of(registry, construction) or own_design_key(construction)
    loose = record.get("loosened") or {}
    loosened_m3 = float(loose.get("soil_m3", 0.0)) + float(loose.get("sand_m3", 0.0))
    ground, kind = str(record.get("ground", "")), record["kind"]
    whole = bool(record.get("tool_whole", True))
    depth_mm = float(record.get("depth_m", 0.0)) * 1000.0
    speed = float(record.get("closing_speed_m_s", 0.0))
    kept = "it stayed whole" if whole else "it did not stay whole"
    name = _the(str(profile["object"]))
    if kind == "stopped":
        test, action, passes = "on-rock", "swing", False
        said = f"the {ground} stopped {name} at {speed:.1f} m/s; {kept}"
        claim = f"recorded: {ground} stops it"
    else:
        test, action = "loosens-soil", ("swing then lever" if kind == "broke out" else "swing then pulled out")
        passes = ground in ("soil", "sand") and loosened_m3 > 0.0 and whole
        said = (f"{name} went {depth_mm:.0f} mm into the {ground} at {speed:.1f} m/s and "
                + (f"broke out {loosened_m3 * 1000.0:.1f} L ({float(record.get('loosened_kg', 0.0)):.1f} kg)"
                   if loosened_m3 > 0.0 else "broke nothing out")
                + f"; {kept}")
        claim = (f"demonstrated: loosens the tested {ground}" if passes
                 else f"recorded: did not loosen the {ground}")
    key = result_key(session_id, record)
    return {
        "id": "ev-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:10],
        "run": key, "at": at, "design": design, "object": profile["object"], "tool": tool,
        "source": "found-example", "test": test, "passes": passes, "action": action,
        "target": {"ground": ground},
        "result": {"loosened_m3": round(loosened_m3, 6), "loosened_kg": round(float(record.get("loosened_kg", 0.0)), 3),
                   "depth_m": round(float(record.get("depth_m", 0.0)), 4), "work_j": round(float(record.get("work_j", 0.0)), 3),
                   "closing_speed_m_s": round(speed, 3)},
        "tool_condition": {"after": {"whole": whole, "dent_mm": float(record.get("tool_dent_mm", 0.0))}},
        "models": [str(record.get("model") or "ground-work-v1")],
        "limitations": list(GROUND_WORK_LIMITS),
        "said": said, "claim": claim,
        "scope": f"for this design revision ({design}), this {ground or 'ground'}, {action}"}


#: Which design a recipe is worked by, and the test it passes by working it.
#: A recipe is a room's, and the machine that runs it is a design: watching one
#: work is how the other is learned.
MADE_BY = {
    "smelt copper": ("copper-smelter@1", "smelts-ore", "a smelter"),
    "draw wire": ("copper-mill@1", "draws-wire", "a mill"),
}


def evidence_from_batch(recipe: str, made: dict[str, float], used: dict[str, float],
                        *, session_id: str, at: str, batch: int) -> dict[str, Any] | None:
    """One batch of a recipe, as evidence that the machine does what it is for.

    A recipe nobody has named a machine for makes no evidence -- the room may
    carry any chemistry a person writes, and the knowledge graph only knows the
    ones it has designs for. Named by the session, the recipe and which batch
    it was, so reading the same reply twice awards nothing twice.
    """
    known = MADE_BY.get(str(recipe))
    if known is None or not made:
        return None
    design, test, what = known
    key = f"{session_id}:{recipe}:{batch}"
    words_in = ", ".join(f"{v:.2f} kg of {k}" for k, v in sorted(used.items()))
    words_out = ", ".join(f"{v:.2f} kg of {k}" for k, v in sorted(made.items()))
    return {
        "id": "ev-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:10],
        "run": key, "at": at, "design": design, "object": what,
        "source": "watched", "test": test, "passes": True, "action": f"work a batch of {recipe}",
        "target": {"substance": sorted(used)[0] if used else ""},
        "result": {"made_kg": round(sum(made.values()), 4), "used_kg": round(sum(used.values()), 4),
                   "made": {k: round(v, 4) for k, v in made.items()},
                   "used": {k: round(v, 4) for k, v in used.items()}},
        "models": ["machine_goods recipe ledger"],
        "limitations": ["the recipe's yield is declared by the room, not measured from chemistry",
                        "the work and the time it takes are the recipe's own numbers"],
        "said": f"{what} worked {words_in} into {words_out}",
        "claim": f"demonstrated: it makes {' and '.join(sorted(made))} of "
                 f"{' and '.join(sorted(used))}",
        "scope": "this recipe, in this room",
    }


def not_modelled(record: dict[str, Any]) -> str | None:
    """What a closed record the engine marked "not supported" says is not
    modelled -- kept as a note, never as evidence (3.5)."""
    if record.get("open") or record.get("supported", True):
        return None
    return str(record.get("why") or "the engine does not model this yet")


# -- what a person's notebook says ---------------------------------------------

# -- learning (docs/knowledge-and-progression.md, 3.1 learn_from) -------------

def _met(journal: Journal, condition: dict[str, Any]) -> bool:
    """Whether one condition of an `earned_by` route is answered by the journal.

    Two kinds, and both are things the journal already records without being
    asked. `found` is having a made example in your hands -- you learn how a
    thing was shaped by studying one, which is how anybody learns it and, more
    to the point here, does not require the technique you are trying to learn.
    `demonstrated` is having shown a design does what it is for, by evidence
    from an accepted engine result.
    """
    standing = journal.standing_of(str(condition.get("design") or ""))
    if "found" in condition:
        return "found" in standing
    if "demonstrated" in condition:
        shown = standing.get("demonstrated") or {}
        test = condition.get("test")
        return bool(shown.get(test)) if test else bool(shown)
    return False


def earn(journal: Journal, registry: Registry, at: str) -> list[str]:
    """Learn every technique this person has now earned, and say which.

    Once each: `Journal.learn` refuses a second source for a technique already
    known, so reading the same evidence twice awards nothing twice. A technique
    whose own prerequisites are not met is not earned yet however much has been
    shown -- the graph is walked, not skipped.
    """
    learned: list[str] = []
    for _pass in range(len(registry.techniques) + 1):
        moved = False
        for technique in registry.techniques.values():
            if technique["id"] in journal.knows():
                continue
            if not set((technique.get("prerequisites") or {}).get("all_of")
                       or []) <= journal.knows():
                continue
            for route in (technique.get("earned_by") or {}).get("any_of") or []:
                if all(_met(journal, need) for need in route.get("all_of") or []):
                    if journal.learn(technique["id"],
                                     {"kind": "experiment", "route": route.get("id"),
                                      "says": route.get("says", "")}, at):
                        learned.append(technique["id"])
                        moved = True
                    break
        if not moved:
            break
    return learned


def teach_the_start(journal: Journal, registry: Registry, at: str) -> list[str]:
    """What the starting area teaches, given once to a journal that has nothing.

    start.json has carried a `teaches` list since the registries were written
    and nothing has ever read it.
    """
    if journal.knows():
        return []
    given = []
    for technique in registry.start.get("teaches") or []:
        if technique in registry.techniques and journal.learn(
                technique, {"kind": "lesson", "id": "the starting area"}, at):
            given.append(technique)
    return given


def what_is_next(journal: Journal, registry: Registry) -> list[dict[str, Any]]:
    """Every technique not known yet: whether it is within reach, what would
    earn it, and what it would open.

    This is the ladder. Without it a person can be one demonstration away from
    a capability and have no way at all of knowing.
    """
    known = journal.knows()
    out = []
    for technique in registry.techniques.values():
        if technique["id"] in known:
            continue
        needs = [t for t in (technique.get("prerequisites") or {}).get("all_of") or []
                 if t not in known]
        routes = []
        for route in (technique.get("earned_by") or {}).get("any_of") or []:
            routes.append({"id": route.get("id"), "says": route.get("says", ""),
                           "done": all(_met(journal, need) for need in route.get("all_of") or [])})
        opens = sorted({design["id"] for design in registry.designs.values()
                        for way in design["routes"]["any_of"]
                        for need in way.get("all_of") or []
                        if need.get("technique") == technique["id"]})
        out.append({"technique": technique["id"], "name": technique["name"],
                    "describes": technique.get("describes", ""),
                    "within_reach": not needs and bool(routes),
                    "first_learn": needs, "earned_by": routes,
                    "would_open": opens,
                    "taught_only": not routes and not needs})
    out.sort(key=lambda row: (not row["within_reach"], row["technique"]))
    return out


def notebook(journal: Journal, registry: Registry) -> dict[str, Any]:
    """The journal as a person reads it, and as read_knowledge answers: what is
    known, what has been demonstrated -- each claim with its scope and the
    engine's numbers -- and what is blocked, and by what. Spends nothing."""
    data = journal.copy()
    evidence = list(data["evidence"].values())
    designs = []
    for key, entry in data["designs"].items():
        ident = key.split("@", 1)[0]
        known = registry.designs.get(ident)
        records = [e for e in evidence if e.get("design") == key]
        designs.append({
            "design": key,
            "name": known["name"] if known else (records[0]["object"] if records else key),
            "registered": known is not None,
            "standing": sorted(entry.get("standing") or {}),
            "demonstrated": sorted((entry.get("standing") or {}).get("demonstrated") or {}),
            "evidence": [{"id": e["id"], "said": e["said"], "claim": e["claim"], "scope": e["scope"],
                          "limitations": e.get("limitations", [])} for e in records]})
    holds = [{"found": key.split("@", 1)[0]} for key, entry in data["designs"].items()
             if "found" in (entry.get("standing") or {})]
    blocked = []
    for design in registry.designs.values():
        for route in design["routes"]["any_of"]:
            if "all_of" not in route:
                continue            # finding one is not a route anyone is blocked on
            why = registry.blockers(design, route, holds, journal.knows())
            if why:
                blocked.append({"design": design["id"], "name": design["name"],
                                "route": route["id"], "because": why})
    return {"revision": data["revision"],
            "techniques": [{"id": t, "name": registry.techniques[t]["name"],
                            "since": (data["techniques"][t] or {}).get("since"),
                            "learned_from": ((data["techniques"][t] or {}).get("source")
                                             or {}).get("kind")}
                           for t in sorted(data["techniques"]) if t in registry.techniques],
            # What is one step away, and what it would open. A person one
            # demonstration short of a capability should be told so.
            "next": what_is_next(journal, registry),
            "designs": designs, "blocked": blocked,
            # Regimes the engine said it does not model, met by their own tools.
            "not_modelled": sorted(set((data.get("notes") or {}).values()))}
