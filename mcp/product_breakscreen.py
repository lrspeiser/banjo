"""Would a blow break this product apart at its joints? A fast first answer.

The owner's two-stage break (docs/product-framework.md): a product that is hit
is first asked whether the forces across its JOINTS can part it into
sub-components; only then is the one part that was struck asked whether it
deforms, shatters or softens. This module is the first question, for a design
on the bench. The engine asks it of a product in the world with its own
fixings (LiveWorld ``partOverloadedLinks``); both rate a joint the same way
(mcp/product_joints.py).

The model is a rigid-body-spring one (Kawai 1978): every part is rigid, every
joint an elastic interface with a stiffness from its contact and its materials.
The loads are the blow, gravity, the floor's reactions, and -- for whatever the
product is free to do -- the inertia of accelerating it ("inertia relief"), so
the set is in equilibrium and what each joint transmits follows by one linear
solve. For a product whose joints form a tree the stiffnesses cancel out of the
answer, which is then plain free-body statics; they only share a load between
joints that carry it side by side.

It is a SCREEN, and says so:

* static-equivalent. A blow shorter than the structure's own period can load a
  joint up to about twice this, or much less; so an answer between half and the
  whole of a joint's capacity is "uncertain", not "holds";
* the parts themselves are rigid and unbreakable here (stage two is theirs);
* a bearing's hold along its own axis is not rated;
* small displacements, no contact between parts other than at their joints.
"""
from __future__ import annotations

from math import isfinite, pi, sqrt
from typing import Any

from mcp import engine_materials, product_joints, workshop_construction as construction
from mcp.workshop import WorkshopDesign, WirePart
from mcp.workshop_statics import G_M_S2, _reactions, _supports

SCREEN_SCHEMA = "banjo.joint-screen.v1"
MAX_PARTS = 60
UNCERTAIN_FROM = 0.5      # a dynamic factor of two separates "holds" from "gives way"
_FREE = 1.0e-9            # stiffness of a direction a joint leaves free, relative to its stiffest

Vec = tuple[float, float, float]


def _add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def _sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _scale(a, s): return (a[0] * s, a[1] * s, a[2] * s)
def _dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def _cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def _norm(a): return sqrt(_dot(a, a))


def _unit(a: Vec) -> Vec:
    length = _norm(a)
    if length <= 1e-12:
        raise ValueError("a direction must not be zero")
    return _scale(a, 1.0 / length)


def _perpendiculars(axis: Vec) -> tuple[Vec, Vec]:
    helper = (1.0, 0.0, 0.0) if abs(axis[0]) < 0.8 else (0.0, 1.0, 0.0)
    first = _unit(_cross(axis, helper))
    return first, _cross(axis, first)


def _inertia(part: WirePart, mass: float) -> list[list[float]]:
    """A part's inertia about its own centre, in the product's axes."""
    w, h, d = (float(v) for v in part.size_m)
    if part.shape == "cylinder":
        radius = min(w, d) / 2.0
        local = (mass * (3 * radius ** 2 + h ** 2) / 12.0, mass * radius ** 2 / 2.0,
                 mass * (3 * radius ** 2 + h ** 2) / 12.0)
    else:
        local = (mass * (h * h + d * d) / 12.0, mass * (w * w + d * d) / 12.0, mass * (w * w + h * h) / 12.0)
    turn = construction.rotation_matrix(part.rotation_deg)
    return [[sum(turn[i][k] * local[k] * turn[j][k] for k in range(3)) for j in range(3)] for i in range(3)]


def _solve(matrix: list[list[float]], rhs: list[list[float]]) -> list[list[float]]:
    """Gaussian elimination with partial pivoting, for several right-hand sides."""
    n, m = len(matrix), len(rhs)
    a = [row[:] + [rhs[k][i] for k in range(m)] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-300:
            raise ValueError("the joint model is singular: a part is held by nothing at all")
        a[col], a[pivot] = a[pivot], a[col]
        head, inv = a[col], 1.0 / a[col][col]
        for r in range(col + 1, n):
            row = a[r]
            factor = row[col] * inv
            if factor != 0.0:
                for c in range(col, n + m):
                    row[c] -= factor * head[c]
    out = [[0.0] * n for _ in range(m)]
    for k in range(m):
        for r in range(n - 1, -1, -1):
            total = a[r][n + k] - sum(a[r][c] * out[k][c] for c in range(r + 1, n))
            out[k][r] = total / a[r][r]
    return out


class _Model:
    """The design as rigid parts and elastic joints, assembled once."""

    def __init__(self, design: WorkshopDesign) -> None:
        design.validate()
        engine_materials.synchronize_workshop_model()
        if len(design.parts) > MAX_PARTS:
            raise ValueError(f"the quick joint screen takes at most {MAX_PARTS} parts; this design has {len(design.parts)}")
        if not construction.of(design).get("joints_authored"):
            raise ValueError("this design has no joints of its own yet; show its joints in Build first")
        self.design = design
        self.parts = list(design.parts)
        self.index = {p.name: i for i, p in enumerate(self.parts)}
        self.centre = [tuple(float(v) for v in p.center_m) for p in self.parts]
        self.mass = []
        for part in self.parts:
            try:
                self.mass.append(part.volume_m3() * engine_materials.density(part.material))
            except KeyError as problem:
                raise ValueError(f"{part.name} is made of {part.material}, which the engine has no strength for") from problem
        self.inertia = [_inertia(p, m) for p, m in zip(self.parts, self.mass)]
        self.joints = [j for j in construction.joints(design) if not j["open"]]
        self.open = [j for j in construction.joints(design) if j["open"]]
        self.rated = {j["id"]: product_joints.capacity(j, self.parts[self.index[j["a"]]], self.parts[self.index[j["b"]]])
                      for j in self.joints}
        self.frames: dict[str, dict[str, Any]] = {}
        n = 6 * len(self.parts)
        self.stiffness = [[0.0] * n for _ in range(n)]
        for joint in self.joints:
            self._add_joint(joint)
        self.modes = self._free_modes()

    # -- joints -------------------------------------------------------------
    def _moduli(self, part: WirePart) -> tuple[float, float]:
        m = engine_materials.mechanics(part.material)
        return m["young_modulus_pa"], m["young_modulus_pa"] / (2.0 * (1.0 + m["poisson_ratio"]))

    def _add_joint(self, joint: dict[str, Any]) -> None:
        ia, ib = self.index[joint["a"]], self.index[joint["b"]]
        a, b, how = self.parts[ia], self.parts[ib], joint["interface"]
        at = tuple(float(v) for v in how["centre_m"])
        (ea, ga), (eb, gb) = self._moduli(a), self._moduli(b)
        if how["form"] == "planar":
            n = _unit(tuple(how["normal"])); u = _unit(tuple(how["u"])); v = _cross(n, u)
            # The part named ``on`` owns the normal; the joint pulls apart when b
            # moves away from a, which is along +n only if a is that part.
            sign = 1.0 if how["on"] == joint["a"] else -1.0
            ha = max(1e-3, abs(_dot(_sub(at, self.centre[ia]), n)))
            hb = max(1e-3, abs(_dot(_sub(at, self.centre[ib]), n)))
            direct, across = ha / ea + hb / eb, ha / ga + hb / gb
            area, i_uu, i_vv = float(how["area_m2"]), float(how["i_uu_m4"]), float(how["i_vv_m4"])
            k_lin = (area / direct, area / across, area / across)
            k_rot = ((i_uu + i_vv) / across, i_uu / direct, i_vv / direct)
        else:
            n = _unit(tuple(how["axis"])); u, v = _perpendiculars(n); sign = 1.0
            d, length = float(how["diameter_m"]), float(how["engaged_m"])
            e_both = 2.0 / (1.0 / ea + 1.0 / eb); g_both = 2.0 / (1.0 / ga + 1.0 / gb)
            radial = e_both * length
            grip = g_both * pi * length
            k_lin = (grip if joint["kind"] == "fixed" else radial, radial, radial)
            k_rot = (grip * (d / 2.0) ** 2, radial * length ** 2 / 12.0, radial * length ** 2 / 12.0)
        if joint["kind"] == "bearing":                 # free to turn about its own axis
            k_rot = (max(k_rot) * _FREE, k_rot[1], k_rot[2])
        self.frames[joint["id"]] = {"at": at, "n": n, "u": u, "v": v, "sign": sign,
                                    "k_lin": k_lin, "k_rot": k_rot, "a": ia, "b": ib}
        axes = (n, u, v)
        # Rows of G: the joint's three relative displacements, then its three
        # relative rotations, in terms of the two parts' twelve freedoms.
        rows: list[list[float]] = []
        for axis in axes:
            row = [0.0] * 12
            for side, part_index, s in ((0, ia, -1.0), (6, ib, 1.0)):
                arm = _sub(at, self.centre[part_index])
                turn = _cross(arm, axis)               # axis . (theta x arm) = theta . (arm x axis)
                for k in range(3):
                    row[side + k] = s * axis[k]
                    row[side + 3 + k] = s * turn[k]
            rows.append(row)
        for axis in axes:
            row = [0.0] * 12
            for side, s in ((0, -1.0), (6, 1.0)):
                for k in range(3):
                    row[side + 3 + k] = s * axis[k]
            rows.append(row)
        self.frames[joint["id"]]["rows"] = rows
        stiff = list(k_lin) + list(k_rot)
        where = [6 * ia + k for k in range(6)] + [6 * ib + k for k in range(6)]
        for row, k in zip(rows, stiff):
            for p in range(12):
                if row[p] == 0.0:
                    continue
                scaled = k * row[p]
                target = self.stiffness[where[p]]
                for q in range(12):
                    if row[q] != 0.0:
                        target[where[q]] += scaled * row[q]

    # -- what the product is free to do ---------------------------------------
    def bodies(self, without: set[str] = frozenset()) -> list[list[str]]:
        """Parts that move as one: joined through fixed joints that still hold."""
        parent = {p.name: p.name for p in self.parts}

        def find(name: str) -> str:
            while parent[name] != name:
                parent[name] = parent[parent[name]]
                name = parent[name]
            return name
        for joint in self.joints:
            if joint["kind"] == "fixed" and joint["id"] not in without:
                parent[find(joint["b"])] = find(joint["a"])
        groups: dict[str, list[str]] = {}
        for part in self.parts:
            groups.setdefault(find(part.name), []).append(part.name)
        return sorted(groups.values(), key=lambda g: -sum(self.mass[self.index[n]] for n in g))

    def pieces(self, without: set[str]) -> list[list[str]]:
        """What the product comes apart into when the joints in ``without`` have gone."""
        parent = {p.name: p.name for p in self.parts}

        def find(name: str) -> str:
            while parent[name] != name:
                parent[name] = parent[parent[name]]
                name = parent[name]
            return name
        for joint in self.joints:
            if joint["id"] not in without:
                parent[find(joint["b"])] = find(joint["a"])
        groups: dict[str, list[str]] = {}
        for part in self.parts:
            groups.setdefault(find(part.name), []).append(part.name)
        return sorted(groups.values(), key=lambda g: -sum(self.mass[self.index[n]] for n in g))

    def _rigid_mode(self, axis: Vec | None, about: Vec, turn: Vec | None, names: list[str]) -> list[float]:
        mode = [0.0] * (6 * len(self.parts))
        for name in names:
            i = self.index[name]
            if axis is not None:
                for k in range(3):
                    mode[6 * i + k] = axis[k]
            else:
                swing = _cross(turn, _sub(self.centre[i], about))
                for k in range(3):
                    mode[6 * i + k] = swing[k]
                    mode[6 * i + 3 + k] = turn[k]
        return mode

    def _free_modes(self) -> list[list[float]]:
        everyone = [p.name for p in self.parts]
        total = sum(self.mass)
        com = tuple(sum(self.mass[i] * self.centre[i][k] for i in range(len(self.parts))) / total for k in range(3))
        unit = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        modes = [self._rigid_mode(axis, com, None, everyone) for axis in unit]
        modes += [self._rigid_mode(None, com, axis, everyone) for axis in unit]
        # One more for each body that turns in the rest on a single line of bearings.
        bodies = self.bodies()
        home = {name: k for k, group in enumerate(bodies) for name in group}
        links: dict[tuple[int, int], list[dict[str, Any]]] = {}
        for joint in self.joints:
            if joint["kind"] == "bearing":
                pair = tuple(sorted((home[joint["a"]], home[joint["b"]])))
                if pair[0] != pair[1]:
                    links.setdefault(pair, []).append(joint)
        reach: dict[int, set[int]] = {}
        for first, second in links:
            reach.setdefault(first, set()).add(second)
            reach.setdefault(second, set()).add(first)
        for (first, second), held in links.items():
            frames = [self.frames[j["id"]] for j in held]
            line, point = frames[0]["n"], frames[0]["at"]
            in_line = all(abs(abs(_dot(f["n"], line)) - 1.0) < 1e-6 and
                          _norm(_cross(_sub(f["at"], point), line)) < 1e-4 for f in frames)
            if not in_line:
                continue                               # two lines of bearings lock the pair
            # Everything on the far side from the heaviest body turns with it.
            seen, frontier = {second}, [second]
            while frontier:
                for other in reach.get(frontier.pop(), ()):
                    if other not in seen and other != first:
                        seen.add(other); frontier.append(other)
            if 0 in seen:                              # turn the lighter side instead
                seen, frontier = {first}, [first]
                while frontier:
                    for other in reach.get(frontier.pop(), ()):
                        if other not in seen and other != second:
                            seen.add(other); frontier.append(other)
            names = [name for k in seen for name in bodies[k]]
            modes.append(self._rigid_mode(None, point, line, names))
        return modes

    # -- loads ----------------------------------------------------------------
    def _mass_times(self, vector: list[float]) -> list[float]:
        out = [0.0] * len(vector)
        for i in range(len(self.parts)):
            for k in range(3):
                out[6 * i + k] = self.mass[i] * vector[6 * i + k]
                out[6 * i + 3 + k] = sum(self.inertia[i][k][j] * vector[6 * i + 3 + j] for j in range(3))
        return out

    def relieved(self, load: list[float]) -> tuple[list[float], list[float]]:
        """The load with the inertia of what it accelerates taken off; and that acceleration."""
        weighed = [self._mass_times(mode) for mode in self.modes]
        gram = [[sum(x * y for x, y in zip(mode, other)) for other in weighed] for mode in self.modes]
        drive = [sum(x * y for x, y in zip(mode, load)) for mode in self.modes]
        scale = max(abs(gram[k][k]) for k in range(len(gram))) or 1.0
        for k in range(len(gram)):
            gram[k][k] += 1e-12 * scale
        share = _solve(gram, [drive])[0]
        motion = [sum(share[k] * self.modes[k][i] for k in range(len(self.modes))) for i in range(len(load))]
        inertia = self._mass_times(motion)
        return [f - g for f, g in zip(load, inertia)], motion

    def push(self, load: list[float], name: str, at: Vec, force: Vec) -> None:
        i = self.index[name]
        moment = _cross(_sub(at, self.centre[i]), force)
        for k in range(3):
            load[6 * i + k] += force[k]
            load[6 * i + 3 + k] += moment[k]

    def displacements(self, loads: list[list[float]]) -> list[list[float]]:
        n = 6 * len(self.parts)
        lin = max((self.stiffness[i][i] for i in range(n) if i % 6 < 3), default=1.0) or 1.0
        rot = max((self.stiffness[i][i] for i in range(n) if i % 6 >= 3), default=1.0) or 1.0
        matrix = [row[:] for row in self.stiffness]
        for i in range(n):                             # held softly, so a free product still solves
            matrix[i][i] += _FREE * (lin if i % 6 < 3 else rot)
        return _solve(matrix, loads)

    def transmitted(self, joint: dict[str, Any], moved: list[float]) -> dict[str, float]:
        frame = self.frames[joint["id"]]
        q = moved[6 * frame["a"]:6 * frame["a"] + 6] + moved[6 * frame["b"]:6 * frame["b"] + 6]
        gap = [sum(r * x for r, x in zip(row, q)) for row in frame["rows"]]
        force = [k * g for k, g in zip(list(frame["k_lin"]) + list(frame["k_rot"]), gap)]
        across = sqrt(force[1] ** 2 + force[2] ** 2)
        if joint["interface"]["form"] == "planar":
            return {"axial_n": frame["sign"] * force[0], "shear_n": across, "torsion_n_m": force[3],
                    "moment_u_n_m": force[4], "moment_v_n_m": force[5]}
        return {"axial_n": force[0], "shear_n": across, "torsion_n_m": force[3],
                "prying_n_m": sqrt(force[4] ** 2 + force[5] ** 2)}


def _finite3(value: Any, what: str) -> Vec:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{what} must be three numbers")
    out = tuple(float(v) for v in value)
    if not all(isfinite(v) for v in out):
        raise ValueError(f"{what} must be finite")
    return out  # type: ignore[return-value]


def screen(design: WorkshopDesign, *, component_name: str, point_m: Any, direction: Any,
           force_n: float, resting: bool = True, floor_friction: float = 0.5) -> dict[str, Any]:
    """What each joint carries, and which would give way first, under one blow.

    ``resting`` stands the product on the floor: the floor carries its weight and
    the blow's downward part, and holds it against sliding up to
    ``floor_friction`` times that. Otherwise it floats free and the blow
    accelerates it, which is the state of something struck in mid-air.
    """
    model = _Model(design)
    if component_name not in model.index:
        raise ValueError(f"there is no component {component_name!r}")
    point, way = _finite3(point_m, "point_m"), _unit(_finite3(direction, "direction"))
    force = float(force_n)
    if not isfinite(force) or not 0.0 < force <= 1.0e7:
        raise ValueError("force_n must be between 0 and 10,000,000")
    friction = float(floor_friction)
    if not isfinite(friction) or not 0.0 <= friction <= 2.0:
        raise ValueError("floor_friction must be between 0 and 2")
    n = 6 * len(model.parts)
    weight, blow = [0.0] * n, [0.0] * n
    for i, mass in enumerate(model.mass):
        weight[6 * i + 1] -= mass * G_M_S2
    model.push(blow, component_name, point, _scale(way, force))

    notes: list[str] = []
    standing = "free"
    if resting:
        try:
            standing = _stand(model, weight, blow, component_name, point, _scale(way, force), friction)
        except ValueError as problem:
            notes.append(f"Not held by the floor under this blow ({problem}); screened as if free.")
    relieved_weight, falling = model.relieved(weight)
    relieved_blow, driven = model.relieved(blow)
    motion = [f + d for f, d in zip(falling, driven)]
    moved_weight, moved_blow = model.displacements([relieved_weight, relieved_blow])

    def at_scale(factor: float) -> list[dict[str, Any]]:
        moved = [w + factor * b for w, b in zip(moved_weight, moved_blow)]
        rows = []
        for joint in model.joints:
            load = model.transmitted(joint, moved)
            rows.append({"joint": joint["id"], "a": joint["a"], "b": joint["b"], "kind": joint["kind"],
                         "method": joint["method"], "load": load,
                         **product_joints.utilisation(model.rated[joint["id"]], load)})
        return rows

    rows = at_scale(1.0)
    for row in rows:
        used = row.get("utilisation")
        row["verdict"] = ("unrated" if used is None else "gives way" if used >= 1.0
                          else "uncertain" if used >= UNCERTAIN_FROM else "holds")
        row["load"] = {k: round(v, 4) for k, v in row["load"].items()}
        if used is not None:
            row["utilisation"] = float(f"{used:.9g}")
    rated = [r for r in rows if r.get("utilisation") is not None]
    rated.sort(key=lambda r: -r["utilisation"])
    failing = {r["joint"] for r in rated if r["verdict"] == "gives way"}

    # The force, along this same line, at which the first joint reaches its capacity.
    first = None
    if rated:
        worst_at = lambda f: max((r["utilisation"] for r in at_scale(f) if r.get("utilisation") is not None), default=0.0)  # noqa: E731
        if worst_at(0.0) >= 1.0:
            first = {"force_n": 0.0, "why": "a joint is already past its capacity under the product's own weight"}
        else:
            low, high = 0.0, 1.0
            while worst_at(high) < 1.0 and high < 1.0e6:
                low, high = high, high * 4.0
            if worst_at(high) >= 1.0:
                for _ in range(40):
                    mid = (low + high) / 2.0
                    low, high = (mid, high) if worst_at(mid) < 1.0 else (low, mid)
                there = max((r for r in at_scale(high) if r.get("utilisation") is not None),
                            key=lambda r: r["utilisation"])
                first = {"force_n": round(high * force, 2), "joint": there["joint"],
                         "a": there["a"], "b": there["b"], "would_be": there["would_be"]}

    total = sum(model.mass)
    return {
        "schema": SCREEN_SCHEMA, "evidence": "analytical-screen", "design_id": design.design_id,
        "blow": {"component": component_name, "point_m": [round(v, 6) for v in point],
                 "direction": [round(v, 6) for v in way], "force_n": round(force, 4)},
        "standing": standing, "mass_kg": round(total, 6),
        "joints": rated + [r for r in rows if r.get("utilisation") is None],
        "gives_way": sorted(failing),
        "comes_apart_into": model.pieces(failing) if failing else [],
        "first_to_give": first,
        "open_joints": [j["id"] for j in model.open],
        "runtime_bodies": model.bodies(),
        "acceleration_m_s2": [round(v, 4) for v in _acceleration(model, motion)],
        "bands": {"holds": f"below {UNCERTAIN_FROM:g} of capacity", "uncertain": f"{UNCERTAIN_FROM:g} to 1",
                  "gives way": "at or above capacity"},
        "limitations": notes + [
            "Static-equivalent: a blow shorter than the structure's own period can load a joint up to about "
            "twice this, or much less. Between half and the whole of a capacity is therefore uncertain.",
            "The parts are rigid and unbreakable here; whether the struck part itself dents, breaks or softens "
            "is the second question, asked of that part alone.",
            "Joint strength is the weaker material's declared strength over the measured contact: "
            + "; ".join(product_joints.NOT_MODELLED) + " are not modelled.",
            "A bearing's hold along its own axis is not rated.",
        ],
    }


def _acceleration(model: _Model, motion: list[float]) -> Vec:
    total = sum(model.mass)
    return tuple(sum(model.mass[i] * motion[6 * i + k] for i in range(len(model.parts))) / total
                 for k in range(3))  # type: ignore[return-value]


def _feet(design: WorkshopDesign) -> tuple[list[dict[str, Any]], float]:
    """Every point at which the design touches the floor, and the part it belongs to.

    Points, not parts: a single post stands on the four corners of its foot, and
    the floor's reaction then enters the post where it really does, with the
    moment that carries. A roller touches along the line under its axis.
    """
    measured = design.measure()
    floor = float(measured["lowest_m"])
    standing = set(measured["standing_on"])
    feet = []
    for part in design.parts:
        if part.name not in standing:
            continue
        if part.shape == "cylinder":
            touching = [(float(x), float(z)) for x, z in part.ground_contacts_m()]
        else:
            touching = [(c[0], c[2]) for c in part.corners_m() if c[1] <= floor + 0.002]
        feet += [{"name": part.name, "at_m": point} for point in touching]
    return feet, floor


def _stand(model: _Model, weight: list[float], blow: list[float], name: str, point: Vec,
           force: Vec, friction: float) -> str:
    """Add the floor's reactions to the two load cases; say how it stands.

    Nothing is added until all of it is known, so a product the floor turns out
    not to hold is left exactly as it was for the free case.
    """
    supports, floor = _feet(model.design)
    if len(supports) < 3:
        raise ValueError("it touches the floor at fewer than three points")
    places = [(s["at_m"][0], s["at_m"][1]) for s in supports]
    total = sum(model.mass)
    com = [sum(model.mass[i] * model.centre[i][k] for i in range(len(model.parts))) / total for k in range(3)]
    own, down = total * G_M_S2, -force[1]
    if own + down <= 0:
        raise ValueError("the blow lifts it off the floor")
    # Held against sliding up to the floor's friction, the sideways part of the
    # blow is carried out through the feet.
    push = sqrt(force[0] ** 2 + force[2] ** 2)
    hold = min(push, friction * (own + down))
    held = (-force[0] * hold / push, 0.0, -force[2] * hold / push) if push > 1e-12 else (0.0, 0.0, 0.0)
    # Where the reactions' resultant must act. Moments about the floor: the
    # weight, the blow (its downward part where it lands, its sideways part at
    # its height), and -- when it slides -- the inertia of the sliding, which
    # acts at the height of the centre of mass. The floor's grip acts at the
    # floor and has no arm. A push at the top of a table loads the far legs.
    height, high = point[1] - floor, com[1] - floor
    load_x = (own * com[0] + down * point[0] + force[0] * height - (force[0] + held[0]) * high) / (own + down)
    load_z = (own * com[2] + down * point[2] + force[2] * height - (force[2] + held[2]) * high) / (own + down)
    alone = _reactions(places, own, com[0], com[2])
    with_blow = _reactions(places, own + down, load_x, load_z)
    for support, before, after in zip(supports, alone, with_blow):
        at = (float(support["at_m"][0]), floor, float(support["at_m"][1]))
        share = after / (own + down)
        model.push(weight, support["name"], at, (0.0, before, 0.0))
        model.push(blow, support["name"], at, (held[0] * share, after - before, held[2] * share))
    if push > 1e-12 and hold < push - 1e-9:
        return "resting, and sliding: the floor holds only part of the sideways push"
    return "resting on the floor"
