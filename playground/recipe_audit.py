"""Can every recipe really be made, here: an audit over the Recipes book.

For each recipe in the room's book (built-in starters, the catalog, and
designs saved by players or the AI) it asks five questions and says which
fail, in words a player could act on:

  shape    the design compiles as drawn (Make is not refused outright);
  supply   every material and good has a source in THIS world that is not
           the Market: a loose pile, a seam with a machine that digs it, or a
           process whose machine stands here and whose inputs are themselves
           supplied (recursively);
  power    every process on those routes runs on a machine with a battery
           that holds charge or a panel that refills it;
  use      the design declares something it does beyond being a shape;
  recovery when the first source of a material runs out there is another
           (a second pile or seam, a process, or a restocking Market lot).

It reads the same acquisition routes the Recipes screen shows, so what it
reports is what a player is told. It does not simulate a future batch.
"""
from __future__ import annotations

from typing import Any


def _routes_ok(routes: list[dict[str, Any]], power: dict[str, bool], issues: list[str],
               depth: int = 0) -> tuple[bool, int, bool]:
    """(supplied without Market, how many independent non-Market sources,
    Market offers it)."""
    sources, market = 0, False
    for route in routes or []:
        kind = route.get('kind')
        if kind == 'pile' and route.get('available_kg', 0) > 0:
            sources += 1
        elif kind == 'deposit':
            if route.get('equipment'):
                sources += 1
            elif depth == 0:
                issues.append(f"{route.get('substance')}: {route.get('name')} has no machine to dig it")
        elif kind == 'process':
            machines = route.get('machines') or []
            if not machines:
                continue
            for machine in machines:
                if not power.get(machine['name'], False):
                    issues.append(f"{route['name']}: {machine['name']} has no charged battery or panel")
                    continue
                inputs_ok = all(_routes_ok(line.get('acquisition'), power, [], depth + 1)[0]
                                for line in machine.get('inputs') or [])
                if inputs_ok:
                    sources += 1
                    break
        elif kind == 'market':
            market = True
    return sources > 0, sources, market


def _powered(app: Any) -> dict[str, bool]:
    """Which machine programs have a store with charge or a panel on it."""
    spec = getattr(getattr(app, 'room', None), 'spec', None) or {}
    machines = spec.get('machines') or {}
    session = getattr(getattr(app, 'live', None), 'session', None)
    native = ((getattr(session, 'state', None) or {}).get('machines') or {}) if session else {}
    charge = {s.get('name'): float(s.get('charge_j') or 0) for s in native.get('stores') or []}
    stores = {s.get('name'): s for s in machines.get('stores') or []}
    panels = {p.get('store') for p in machines.get('panels') or []}
    out = {}
    for program in machines.get('programs') or []:
        store = program.get('store')
        held = charge.get(store, float((stores.get(store) or {}).get('charge_j') or 0))
        out[program.get('name')] = bool(store) and (held > 0 or store in panels)
    return out


def audit(app: Any, book: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    import workshop_tabs
    book = book or workshop_tabs.recipes(app)
    power = _powered(app)
    rows = []
    for t in book['templates']:
        issues: list[str] = []
        if t.get('problem'):
            rows.append({'name': t['name'], 'source': t.get('source'), 'ok': False,
                         'issues': ['shape: ' + t['problem']]})
            continue
        if not (t.get('readiness') or {}).get('ready_as_drawn'):
            reason = ((t.get('readiness') or {}).get('workshop') or {}).get('reason') or 'needs design changes'
            issues.append('shape: ' + reason)
        for line in [*(t.get('materials') or []), *(t.get('goods') or [])]:
            what = line.get('material') or line.get('substance')
            # Recipes lists routes only for what is short; ask for the whole
            # amount so a recipe you can already afford is still audited.
            routes = line.get('acquisition') or []
            supplied, count, market = _routes_ok(routes, power, issues)
            if not routes and line.get('enough'):
                continue
            if not supplied:
                issues.append(f"supply: no source of {what} in this world"
                              + (" except the Market" if market else ""))
            elif count < 2 and not market:
                issues.append(f"recovery: {what} has one finite source and no Market lot")
        uses = [c for c in t.get('capabilities') or [] if c.get('label') != 'Shape only']
        if not uses:
            issues.append('use: declares nothing it does beyond its shape')
        rows.append({'name': t['name'], 'source': t.get('source'), 'ok': not issues, 'issues': issues})
    return rows
