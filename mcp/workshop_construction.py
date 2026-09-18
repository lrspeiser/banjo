"""Building a Workshop design part by part, with joints the author declares.

An assembly such as ``cart`` is Python code: it lays its parts out from a few
numbers. That is a good starting point and a poor place to stop, because a
person cannot add a part to it, take one off it, or say how two parts are
fastened. This module makes those three things data:

* ``added``   -- parts the person put in, each a whole :class:`WirePart`;
* ``removed`` -- template parts the person took off, by name;
* ``joints``  -- how two parts are fastened, declared rather than guessed.

The block rides inside ``component_overrides`` under :data:`CONSTRUCTION_KEY`.
Every path that rebuilds a design already carries the overrides from the page
to the model and into every saved record, so a constructed design reaches the
Matter view, the bench, the library and the installer without any of them
learning a new field.

Joints matter beyond the Workshop. Nothing here says what a joint can carry:
that is :mod:`mcp.product_joints`, from the engine's own material strengths and
the contact this module measures. What this module owns is the contact itself:
where two parts meet, over what area, and about which axis.
"""
from __future__ import annotations

from copy import deepcopy
from math import asin, atan2, cos, degrees, isfinite, pi, radians, sin, sqrt
from typing import Any, Iterable

from mcp.workshop import ComponentLibrary, WirePart, WorkshopDesign

CONSTRUCTION_KEY = "@construction"
CONSTRUCTION_SCHEMA = "banjo.workshop-construction.v1"
CUSTOM_KIND = "custom"

MAX_ADDED = 120
MAX_JOINTS = 400
MAX_NAME = 120

#: What a joint does to the two parts' motion.
#:   fixed   -- they move as one;
#:   bearing -- one turns about the joint's axis in the other and is otherwise held.
JOINT_KINDS = ("fixed", "bearing")

#: How the joint is made, which decides what it can carry (mcp.product_joints).
#:   bonded  -- glued, welded or fused over the whole contact;
#:   pressed -- a shaft driven into a bore and held there;
#:   bearing -- a shaft free to turn in a bore.
JOINT_METHODS = ("bonded", "pressed", "bearing")

FACE_IDS = ("face-x-", "face-x+", "face-y-", "face-y+", "face-z-", "face-z+")

#: Two faces this close, facing each other, are in contact.
CONTACT_TOLERANCE_M = 0.003
_OPPOSED = -0.985          # two faces within about 10 degrees of square to each other
_MITRE = -0.5              # a member's end raked up to 60 degrees from the surface it meets
_SNAP = 0.08               # of a face's half-width: how near its middle or its edge a click settles
_ROUND_SIDES = 32

Vec = tuple[float, float, float]
Mat = tuple[Vec, Vec, Vec]


# ---------------------------------------------------------------------------
# Small vector and rotation arithmetic. Banjo builds a rotation z first, so the
# matrix is Rx.Ry.Rz (mcp.workshop._rotate), and these agree with it exactly.
# ---------------------------------------------------------------------------

def _add(a: Vec, b: Vec) -> Vec: return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def _sub(a: Vec, b: Vec) -> Vec: return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _scale(a: Vec, s: float) -> Vec: return (a[0] * s, a[1] * s, a[2] * s)
def _dot(a: Vec, b: Vec) -> float: return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def _norm(a: Vec) -> float: return sqrt(_dot(a, a))


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a: Vec) -> Vec:
    length = _norm(a)
    if length <= 1e-12:
        raise ValueError("a direction must not be zero")
    return _scale(a, 1.0 / length)


def rotation_matrix(rotation_deg: Iterable[float]) -> Mat:
    """Rx.Ry.Rz for Banjo's Euler degrees; columns are the part's axes in the product."""
    ax, ay, az = (radians(float(v)) for v in rotation_deg)
    ca, sa, cb, sb, cc, sc = cos(ax), sin(ax), cos(ay), sin(ay), cos(az), sin(az)
    return ((cb * cc, -cb * sc, sb),
            (ca * sc + sa * sb * cc, ca * cc - sa * sb * sc, -sa * cb),
            (sa * sc - ca * sb * cc, sa * cc + ca * sb * sc, ca * cb))


def euler_from_matrix(matrix: Mat) -> Vec:
    """The inverse of :func:`rotation_matrix`, in degrees."""
    sb = max(-1.0, min(1.0, matrix[0][2]))
    if abs(sb) > 1.0 - 1e-10:
        # Looking straight along x: z and x turn about the same line, so all of
        # that turn is given to x.
        return (degrees(atan2(matrix[2][1], matrix[1][1])), degrees(asin(sb)), 0.0)
    return (degrees(atan2(-matrix[1][2], matrix[2][2])), degrees(asin(sb)),
            degrees(atan2(-matrix[0][1], matrix[0][0])))


def _apply(matrix: Mat, v: Vec) -> Vec:
    return (_dot(matrix[0], v), _dot(matrix[1], v), _dot(matrix[2], v))


def _column(matrix: Mat, index: int) -> Vec:
    return (matrix[0][index], matrix[1][index], matrix[2][index])


def _from_columns(x: Vec, y: Vec, z: Vec) -> Mat:
    return ((x[0], y[0], z[0]), (x[1], y[1], z[1]), (x[2], y[2], z[2]))


def _times(a: Mat, b: Mat) -> Mat:
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
                 for i in range(3))  # type: ignore[return-value]


def _transpose(a: Mat) -> Mat:
    return _from_columns(a[0], a[1], a[2])


def _about(axis: Vec, angle_rad: float) -> Mat:
    """A turn about a unit axis (Rodrigues)."""
    x, y, z = axis
    c, s, t = cos(angle_rad), sin(angle_rad), 1.0 - cos(angle_rad)
    return ((t * x * x + c, t * x * y - s * z, t * x * z + s * y),
            (t * x * y + s * z, t * y * y + c, t * y * z - s * x),
            (t * x * z - s * y, t * y * z + s * x, t * z * z + c))


def _shortest_turn(source: Vec, target: Vec, fallback_axis: Vec) -> Mat:
    """The least turn taking one unit direction onto another.

    Straight back on itself has no least turn, so it is half a turn about
    ``fallback_axis``, which the caller picks square to both.
    """
    d = max(-1.0, min(1.0, _dot(source, target)))
    if d > 1.0 - 1e-12:
        return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    if d < -1.0 + 1e-12:
        return _about(_unit(fallback_axis), pi)
    return _about(_unit(_cross(source, target)), atan2(_norm(_cross(source, target)), d))


def to_product(part: WirePart, local: Vec) -> Vec:
    return _add(tuple(float(v) for v in part.center_m), _apply(rotation_matrix(part.rotation_deg), local))


def to_local(part: WirePart, point: Vec) -> Vec:
    return _apply(_transpose(rotation_matrix(part.rotation_deg)),
                  _sub(point, tuple(float(v) for v in part.center_m)))


# ---------------------------------------------------------------------------
# Faces
# ---------------------------------------------------------------------------

def _face_frame(face_id: str) -> tuple[int, int, int, float]:
    """(normal axis, u axis, v axis, sign), with u x v = the outward normal."""
    if face_id not in FACE_IDS:
        raise ValueError(f"{face_id!r} is not a face; a part has {', '.join(FACE_IDS)}")
    axis = "xyz".index(face_id[5])
    sign = 1.0 if face_id[6] == "+" else -1.0
    u, v = (axis + 1) % 3, (axis + 2) % 3
    if sign < 0:
        u, v = v, u
    return axis, u, v, sign


def face(part: WirePart, face_id: str) -> dict[str, Any]:
    """One face of a part in product coordinates."""
    axis, u, v, sign = _face_frame(face_id)
    size = tuple(float(s) for s in part.size_m)
    matrix = rotation_matrix(part.rotation_deg)
    normal = _scale(_column(matrix, axis), sign)
    local_centre = [0.0, 0.0, 0.0]
    local_centre[axis] = sign * size[axis] / 2.0
    # A cylinder's axis is its local y, so only its two y faces are flat; the
    # other four touch the curved surface along a line and enclose no area.
    round_end = part.shape == "cylinder" and axis == 1
    curved = part.shape == "cylinder" and axis != 1
    return {
        "id": face_id, "part": part.name,
        "centre_m": to_product(part, tuple(local_centre)),
        "normal": normal, "u": _column(matrix, u), "v": _column(matrix, v),
        "half_u_m": size[u] / 2.0, "half_v_m": size[v] / 2.0,
        "round": round_end, "curved": curved,
    }


def faces(part: WirePart) -> list[dict[str, Any]]:
    return [face(part, face_id) for face_id in FACE_IDS]


def nearest_face(part: WirePart, point_m: Iterable[float]) -> dict[str, Any]:
    """The face a point on the part's surface belongs to."""
    point = tuple(float(v) for v in point_m)
    local = to_local(part, point)
    size = tuple(float(s) for s in part.size_m)
    best, best_gap = FACE_IDS[0], float("inf")
    for face_id in FACE_IDS:
        axis, _, _, sign = _face_frame(face_id)
        gap = abs(sign * size[axis] / 2.0 - local[axis])
        if gap < best_gap:
            best, best_gap = face_id, gap
    return face(part, best)


# ---------------------------------------------------------------------------
# Contact between two parts
# ---------------------------------------------------------------------------

def _outline(side: dict[str, Any]) -> list[tuple[float, float]]:
    """A face's outline in its own (u, v) plane, about its centre."""
    hu, hv = side["half_u_m"], side["half_v_m"]
    if side["round"]:
        radius = min(hu, hv)
        return [(radius * cos(2 * pi * k / _ROUND_SIDES), radius * sin(2 * pi * k / _ROUND_SIDES))
                for k in range(_ROUND_SIDES)]
    return [(-hu, -hv), (hu, -hv), (hu, hv), (-hu, hv)]


def _clip(polygon: list[tuple[float, float]], axis: int, bound: float,
          keep_below: bool) -> list[tuple[float, float]]:
    """Sutherland-Hodgman against one side of an axis-aligned rectangle."""
    out: list[tuple[float, float]] = []
    for i, current in enumerate(polygon):
        previous = polygon[i - 1]
        inside_c = current[axis] <= bound if keep_below else current[axis] >= bound
        inside_p = previous[axis] <= bound if keep_below else previous[axis] >= bound
        if inside_c != inside_p:
            t = (bound - previous[axis]) / (current[axis] - previous[axis])
            out.append((previous[0] + t * (current[0] - previous[0]),
                        previous[1] + t * (current[1] - previous[1])))
        if inside_c:
            out.append(current)
    return out


def _clip_round(polygon: list[tuple[float, float]], radius: float) -> list[tuple[float, float]]:
    """Clip against a disc, as the polygon the disc is drawn with."""
    for k in range(_ROUND_SIDES):
        a0, a1 = 2 * pi * k / _ROUND_SIDES, 2 * pi * (k + 1) / _ROUND_SIDES
        p0 = (radius * cos(a0), radius * sin(a0))
        p1 = (radius * cos(a1), radius * sin(a1))
        edge = (p1[0] - p0[0], p1[1] - p0[1])
        out: list[tuple[float, float]] = []
        for i, current in enumerate(polygon):
            previous = polygon[i - 1]
            side_c = edge[0] * (current[1] - p0[1]) - edge[1] * (current[0] - p0[0])
            side_p = edge[0] * (previous[1] - p0[1]) - edge[1] * (previous[0] - p0[0])
            if (side_c >= 0) != (side_p >= 0):
                t = side_p / (side_p - side_c)
                out.append((previous[0] + t * (current[0] - previous[0]),
                            previous[1] + t * (current[1] - previous[1])))
            if side_c >= 0:
                out.append(current)
        polygon = out
        if not polygon:
            break
    return polygon


def _section(polygon: list[tuple[float, float]]) -> dict[str, float] | None:
    """Area, centroid and second moments of a polygon about its own centroid."""
    if len(polygon) < 3:
        return None
    area2 = cx = cy = ixx = iyy = ixy = 0.0
    for i, (x1, y1) in enumerate(polygon):
        x0, y0 = polygon[i - 1]
        step = x0 * y1 - x1 * y0
        area2 += step
        cx += (x0 + x1) * step
        cy += (y0 + y1) * step
        ixx += (y0 * y0 + y0 * y1 + y1 * y1) * step
        iyy += (x0 * x0 + x0 * x1 + x1 * x1) * step
        ixy += (x0 * y1 + 2 * x0 * y0 + 2 * x1 * y1 + x1 * y0) * step
    area = area2 / 2.0
    if abs(area) < 1e-12:
        return None
    cx, cy = cx / (3 * area2), cy / (3 * area2)
    ixx, iyy, ixy = ixx / 12.0, iyy / 12.0, ixy / 24.0
    if area < 0:
        area, ixx, iyy, ixy = -area, -ixx, -iyy, -ixy
    # Parallel axis, to the polygon's own centroid.
    ixx -= area * cy * cy
    iyy -= area * cx * cx
    ixy -= area * cx * cy
    return {"area": area, "cu": cx, "cv": cy, "i_uu": max(0.0, ixx), "i_vv": max(0.0, iyy), "i_uv": ixy}


def _overlap(flat: dict[str, Any], other: dict[str, Any], *, along_length: bool,
             tolerance_m: float) -> dict[str, Any] | None:
    """``other``'s outline on ``flat``'s plane, clipped to ``flat``; None if apart."""
    gap = _dot(_sub(other["centre_m"], flat["centre_m"]), flat["normal"])
    if abs(gap) > tolerance_m:
        return None
    outline = []
    for pu, pv in _outline(other):
        point = _add(other["centre_m"], _add(_scale(other["u"], pu), _scale(other["v"], pv)))
        if along_length:
            # Carried along the member's own length until it meets the surface.
            slope = _dot(other["normal"], flat["normal"])
            point = _add(point, _scale(other["normal"],
                                       _dot(_sub(flat["centre_m"], point), flat["normal"]) / slope))
        offset = _sub(point, flat["centre_m"])
        outline.append((_dot(offset, flat["u"]), _dot(offset, flat["v"])))
    if flat["round"]:
        outline = _clip_round(outline, min(flat["half_u_m"], flat["half_v_m"]))
    else:
        for axis, bound in ((0, flat["half_u_m"]), (1, flat["half_v_m"])):
            outline = _clip(outline, axis, bound, True) if outline else outline
            outline = _clip(outline, axis, -bound, False) if outline else outline
    section = _section(outline) if outline else None
    if section is None or section["area"] < 1e-9:
        return None
    centre = _add(flat["centre_m"], _add(_scale(flat["u"], section["cu"]), _scale(flat["v"], section["cv"])))
    return {
        "form": "planar", "centre_m": centre, "normal": flat["normal"], "u": flat["u"], "v": flat["v"],
        "gap_m": gap, "area_m2": section["area"],
        "i_uu_m4": section["i_uu"], "i_vv_m4": section["i_vv"], "i_uv_m4": section["i_uv"],
        "half_u_m": max(abs(p[0] - section["cu"]) for p in outline),
        "half_v_m": max(abs(p[1] - section["cv"]) for p in outline),
    }


def contact_patch(a: WirePart, b: WirePart, *,
                  tolerance_m: float = CONTACT_TOLERANCE_M) -> dict[str, Any] | None:
    """Where two parts meet over a flat area, or None when they do not.

    Two faces square to each other meet over their overlap. A member that meets
    a surface at an angle -- a splayed leg under a top, a raked handle arm on a
    deck -- is cut to sit flat on it, so its END bears over its own section
    carried along its length onto that surface: more area than the square
    section, by one over the cosine of the rake.

    The patch's area and second moments are what a joint's strength is worked
    out over, so they are measured from the parts as they stand, never stored.
    ``normal`` points out of the part named ``on``.
    """
    best: dict[str, Any] | None = None
    sides_a, sides_b = faces(a), faces(b)
    for flat_part, flat_sides, other_part, other_sides in ((a, sides_a, b, sides_b), (b, sides_b, a, sides_a)):
        for flat in flat_sides:
            if flat["curved"]:
                continue
            for other in other_sides:
                if other["curved"]:
                    continue
                facing = _dot(flat["normal"], other["normal"])
                square = facing <= _OPPOSED
                mitred = not square and facing <= _MITRE and other["id"][5] == "y"
                # Two square faces are found from either side; count them once.
                if not (square or mitred) or (square and flat_part is b):
                    continue
                found = _overlap(flat, other, along_length=mitred, tolerance_m=tolerance_m)
                if found is None or (best is not None and found["area_m2"] <= best["area_m2"]):
                    continue
                found.update(on=flat_part.name, on_face=flat["id"],
                             against=other_part.name, against_face=other["id"], mitred=mitred)
                best = found
    return best


def shaft_engagement(a: WirePart, b: WirePart) -> dict[str, Any] | None:
    """A round part running into or through the other, or None.

    The shaft is whichever of the two is a cylinder whose axis passes through
    the other's box. What is measured is how much of its length lies inside.
    """
    best: dict[str, Any] | None = None
    for shaft, housing in ((a, b), (b, a)):
        if shaft.shape != "cylinder":
            continue
        diameter = min(float(shaft.size_m[0]), float(shaft.size_m[2]))
        half = tuple(float(s) / 2.0 for s in housing.size_m)
        if housing.shape == "cylinder":
            # Inside a disc only when it fits the disc, not its bounding box.
            if diameter >= min(float(housing.size_m[0]), float(housing.size_m[2])):
                continue
        elif diameter >= 2.0 * max(half) :
            continue
        start, end = shaft.ends_m()
        p0, p1 = to_local(housing, tuple(start)), to_local(housing, tuple(end))
        # Clip the shaft's axis against the housing's box (Liang-Barsky).
        t0, t1, inside = 0.0, 1.0, True
        for axis in range(3):
            delta = p1[axis] - p0[axis]
            if abs(delta) < 1e-12:
                if abs(p0[axis]) > half[axis] + 1e-9:
                    inside = False
                    break
                continue
            ta, tb = (-half[axis] - p0[axis]) / delta, (half[axis] - p0[axis]) / delta
            if ta > tb:
                ta, tb = tb, ta
            t0, t1 = max(t0, ta), min(t1, tb)
            if t0 >= t1:
                inside = False
                break
        if not inside:
            continue
        span = _sub(tuple(end), tuple(start))
        length = _norm(span)
        engaged = (t1 - t0) * length
        if engaged < 1e-4:
            continue
        axis_dir = _unit(span)
        centre = _add(tuple(start), _scale(span, (t0 + t1) / 2.0))
        found = {"form": "cylindrical", "shaft": shaft.name, "housing": housing.name,
                 "centre_m": centre, "axis": axis_dir, "diameter_m": diameter,
                 "engaged_m": engaged, "through": t0 > 1e-6 and t1 < 1.0 - 1e-6}
        if best is None or engaged > best["engaged_m"]:
            best = found
    return best


def interface(a: WirePart, b: WirePart) -> dict[str, Any] | None:
    """How two parts meet: a shaft in a bore if there is one, else face to face."""
    return shaft_engagement(a, b) or contact_patch(a, b)


# ---------------------------------------------------------------------------
# The construction block
# ---------------------------------------------------------------------------

def _name(value: Any, what: str) -> str:
    name = str(value or "").strip()
    if not name or len(name) > MAX_NAME or name.startswith("@"):
        raise ValueError(f"{what} needs a name of 1-{MAX_NAME} characters that does not begin with @")
    return name


def _three(value: Any, what: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{what} must contain three numbers")
    out = [float(v) for v in value]
    if not all(isfinite(v) for v in out):
        raise ValueError(f"{what} must contain finite numbers")
    return out


def _checked_part(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("an added part must be an object")
    unknown = set(value) - {"name", "role", "family", "shape", "size_m", "center_m",
                            "rotation_deg", "material", "source"}
    if unknown:
        raise ValueError("an added part has unknown field(s): " + ", ".join(sorted(unknown)))
    size = _three(value.get("size_m"), "size_m")
    if any(v <= 0 or v > 20 for v in size):
        raise ValueError("size_m must be positive and at most 20 m")
    shape = str(value.get("shape") or "box")
    if shape not in {"box", "tapered", "cylinder"}:
        raise ValueError("shape must be box, tapered or cylinder")
    material = str(value.get("material") or "").strip()
    if not material or len(material) > 80:
        raise ValueError("an added part needs a material")
    out: dict[str, Any] = {
        "name": _name(value.get("name"), "an added part"),
        "role": _name(value.get("role"), "an added part's role"),
        "shape": shape, "size_m": size,
        "center_m": _three(value.get("center_m"), "center_m"),
        "rotation_deg": _three(value.get("rotation_deg", [0, 0, 0]), "rotation_deg"),
        "material": material,
    }
    if value.get("family"):
        out["family"] = str(value["family"])[:80]
    if isinstance(value.get("source"), dict):
        out["source"] = {str(k)[:40]: str(v)[:160] for k, v in list(value["source"].items())[:6]}
    return out


def _checked_joint(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("a joint must be an object")
    unknown = set(value) - {"id", "kind", "method", "a", "b"}
    if unknown:
        raise ValueError("a joint has unknown field(s): " + ", ".join(sorted(unknown)))
    kind = str(value.get("kind") or "fixed")
    if kind not in JOINT_KINDS:
        raise ValueError("a joint's kind must be " + " or ".join(JOINT_KINDS))
    method = str(value.get("method") or ("bearing" if kind == "bearing" else "bonded"))
    if method not in JOINT_METHODS:
        raise ValueError("a joint's method must be one of " + ", ".join(JOINT_METHODS))
    if (kind == "bearing") != (method == "bearing"):
        raise ValueError("a bearing joint is made as a bearing, and only a bearing joint is")
    a, b = _name(value.get("a"), "a joint's first part"), _name(value.get("b"), "a joint's second part")
    if a == b:
        raise ValueError("a joint holds two different parts")
    return {"id": _name(value.get("id"), "a joint"), "kind": kind, "method": method, "a": a, "b": b}


def checked(value: Any) -> dict[str, Any]:
    """A construction block, validated and in canonical form."""
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise ValueError("construction must be an object")
    unknown = set(value) - {"schema", "added", "removed", "joints", "joints_authored"}
    if unknown:
        raise ValueError("construction has unknown field(s): " + ", ".join(sorted(unknown)))
    if value.get("schema") not in (None, CONSTRUCTION_SCHEMA):
        raise ValueError("unsupported construction schema")
    added_in, removed_in, joints_in = value.get("added") or [], value.get("removed") or [], value.get("joints") or []
    if not all(isinstance(v, list) for v in (added_in, removed_in, joints_in)):
        raise ValueError("construction added, removed and joints must be lists")
    if len(added_in) > MAX_ADDED:
        raise ValueError(f"a design holds at most {MAX_ADDED} added parts")
    if len(joints_in) > MAX_JOINTS:
        raise ValueError(f"a design holds at most {MAX_JOINTS} joints")
    added = [_checked_part(v) for v in added_in]
    names = [p["name"] for p in added]
    if len(names) != len(set(names)):
        raise ValueError("added parts need different names")
    removed = sorted({_name(v, "a removed part") for v in removed_in})
    if set(removed) & set(names):
        raise ValueError("a part cannot be both added and removed")
    joints = [_checked_joint(v) for v in joints_in]
    ids = [j["id"] for j in joints]
    if len(ids) != len(set(ids)):
        raise ValueError("joints need different ids")
    pairs = [tuple(sorted((j["a"], j["b"]))) for j in joints]
    if len(pairs) != len(set(pairs)):
        raise ValueError("two parts are held by at most one joint")
    out: dict[str, Any] = {"schema": CONSTRUCTION_SCHEMA}
    if added: out["added"] = added
    if removed: out["removed"] = removed
    if joints: out["joints"] = joints
    if value.get("joints_authored") or joints:
        out["joints_authored"] = True
    return out if len(out) > 1 else {}


def of_overrides(overrides: Any) -> dict[str, Any]:
    if not isinstance(overrides, dict):
        return {}
    return checked(overrides.get(CONSTRUCTION_KEY))


def of(design: WorkshopDesign) -> dict[str, Any]:
    lineage = design.lineage if isinstance(design.lineage, dict) else {}
    return of_overrides(lineage.get("component_overrides"))


def _part(record: dict[str, Any]) -> WirePart:
    return WirePart(name=record["name"], role=record["role"],
                    size_m=tuple(record["size_m"]), center_m=tuple(record["center_m"]),
                    material=record["material"], rotation_deg=tuple(record["rotation_deg"]),
                    shape=record["shape"], family=record.get("family"))


def apply(parts: list[WirePart], construction: dict[str, Any]) -> list[WirePart]:
    """The template's parts with the person's own taken off and put on."""
    if not construction:
        return list(parts)
    known = {p.name for p in parts}
    missing = sorted(set(construction.get("removed") or []) - known)
    if missing:
        raise ValueError("construction removes part(s) this design does not have: " + ", ".join(missing))
    kept = [p for p in parts if p.name not in set(construction.get("removed") or [])]
    clash = sorted({p["name"] for p in construction.get("added") or []} & {p.name for p in kept})
    if clash:
        raise ValueError("an added part has the name of a part already here: " + ", ".join(clash))
    built = kept + [_part(p) for p in construction.get("added") or []]
    names = {p.name for p in built}
    for joint in construction.get("joints") or []:
        gone = [n for n in (joint["a"], joint["b"]) if n not in names]
        if gone:
            raise ValueError(f"joint {joint['id']} holds {', '.join(gone)}, which this design does not have")
    return built


# ---------------------------------------------------------------------------
# Placing a new part against one that is there
# ---------------------------------------------------------------------------

def _snapped(target: dict[str, Any], point: Vec, half_u: float, half_v: float) -> Vec:
    """Settle a click where a person meant it: on the middle, or flush to an edge."""
    offset = _sub(point, target["centre_m"])
    out = []
    for axis, half_face, half_part in ((target["u"], target["half_u_m"], half_u),
                                       (target["v"], target["half_v_m"], half_v)):
        at = _dot(offset, axis)
        room = half_face - half_part
        if abs(at) <= _SNAP * half_face:
            at = 0.0
        elif room > 0 and abs(at) > room - _SNAP * half_face:
            at = room if at > 0 else -room
        out.append(at)
    return _add(target["centre_m"], _add(_scale(target["u"], out[0]), _scale(target["v"], out[1])))


def place(new: WirePart, *, by: str, onto: WirePart, at_m: Iterable[float],
          twist_deg: float = 0.0, depth_m: float = 0.0, snap: bool = True) -> WirePart:
    """Put ``new`` against ``onto``: its ``by`` face on the clicked point, facing in.

    The new part comes in square to the face it lands on, grows out of it along
    the face's normal, and can then be turned about that normal (``twist_deg``)
    or sunk into it (``depth_m``, positive inwards: a tenon, a shaft in a bore).
    """
    point = tuple(float(v) for v in at_m)
    if len(point) != 3 or not all(isfinite(v) for v in point):
        raise ValueError("at_m must be three finite numbers")
    twist, depth = float(twist_deg), float(depth_m)
    if not isfinite(twist) or not isfinite(depth) or abs(depth) > 20:
        raise ValueError("twist_deg and depth_m must be finite, and depth within 20 m")
    target = nearest_face(onto, point)
    axis, u, v, sign = _face_frame(by)
    size = tuple(float(s) for s in new.size_m)
    unit = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    # Start square to the part it lands on, turn it the least that brings its
    # ``by`` face round to meet the clicked face, then twist about that face.
    # A block set on a block therefore keeps the block's own axes.
    beside = rotation_matrix(onto.rotation_deg)
    facing_in = _scale(target["normal"], -1.0)
    matrix = _times(_shortest_turn(_apply(beside, _scale(unit[axis], sign)), facing_in, target["u"]), beside)
    matrix = _times(_about(target["normal"], radians(twist)), matrix)
    # The part's footprint on the target face, for snapping flush to an edge.
    spread_u = sum(abs(_dot(_apply(matrix, unit[k]), target["u"])) * size[k] / 2.0 for k in (u, v))
    spread_v = sum(abs(_dot(_apply(matrix, unit[k]), target["v"])) * size[k] / 2.0 for k in (u, v))
    on_plane = _sub(point, _scale(target["normal"], _dot(_sub(point, target["centre_m"]), target["normal"])))
    seat = _snapped(target, on_plane, spread_u, spread_v) if snap else on_plane
    seat = _sub(seat, _scale(target["normal"], depth))
    local_face = [0.0, 0.0, 0.0]
    local_face[axis] = sign * size[axis] / 2.0
    centre = _sub(seat, _apply(matrix, tuple(local_face)))
    return WirePart(name=new.name, role=new.role, size_m=new.size_m,
                    center_m=tuple(round(c, 9) for c in centre), material=new.material,
                    rotation_deg=tuple(round(a, 6) for a in euler_from_matrix(matrix)),
                    shape=new.shape, family=new.family)


def template_part(request: dict[str, Any], *, library: ComponentLibrary | None = None) -> WirePart:
    """The part a person asked for, at the origin in its own frame.

    Either a family with its parameters (a strut family also needs ``length_m``)
    or a saved component recipe from My library.
    """
    if not isinstance(request, dict):
        raise ValueError("the part to add must be an object")
    name = _name(request.get("name"), "the part to add")
    recipe = request.get("recipe")
    if isinstance(recipe, dict):
        if recipe.get("schema") != "banjo.workshop-component-recipe.v1":
            raise ValueError("that library item is not a reusable Workshop component")
        return WirePart(name=name, role=str(recipe.get("role") or "part"),
                        size_m=tuple(_three(recipe.get("size_m"), "saved component size_m")),
                        center_m=(0.0, 0.0, 0.0),
                        material=str(request.get("material") or recipe.get("material") or "oak"),
                        shape=str(recipe.get("shape") or "box"), family=recipe.get("family"))
    library = library or ComponentLibrary()
    family = library.family(str(request.get("family") or ""))
    parameters = dict(request.get("parameters") or {})
    material = str(request.get("material") or "oak")
    where: dict[str, Any] = {}
    if "start" in family.offers:                      # a strut: it spans two points
        length = float(request.get("length_m", 0.5))
        if not isfinite(length) or not 0.005 <= length <= 20:
            raise ValueError("length_m must be between 5 mm and 20 m")
        where = {"from_m": (0.0, -length / 2.0, 0.0), "to_m": (0.0, length / 2.0, 0.0)}
    else:
        where = {"at_m": (0.0, 0.0, 0.0)}
    made = library.make(family.name, name=name, material=material, parameters=parameters, **where)
    if len(made.parts) != 1:
        raise ValueError(f"the {family.name} family makes {len(made.parts)} parts; add them one at a time")
    part = made.parts[0]
    return WirePart(name=name, role=part.role, size_m=part.size_m, center_m=(0.0, 0.0, 0.0),
                    material=part.material, rotation_deg=(0.0, 0.0, 0.0),
                    shape=part.shape, family=part.family)


# ---------------------------------------------------------------------------
# Editing a construction. Each takes the overrides and the design as it stands
# and returns new overrides; nothing is changed in place.
# ---------------------------------------------------------------------------

def _with(overrides: dict[str, Any], construction: dict[str, Any]) -> dict[str, Any]:
    out = {k: deepcopy(v) for k, v in (overrides or {}).items() if k != CONSTRUCTION_KEY}
    block = checked(construction)
    if block:
        out[CONSTRUCTION_KEY] = block
    return out


def fresh_name(design: WorkshopDesign, stem: str) -> str:
    taken = {p.name for p in design.parts}
    stem = (str(stem or "part").strip() or "part")[:80]
    index = 1
    while f"{stem}-{index}" in taken:
        index += 1
    return f"{stem}-{index}"


def _fresh_joint_id(construction: dict[str, Any]) -> str:
    taken = {j["id"] for j in construction.get("joints") or []}
    index = 1
    while f"joint-{index}" in taken:
        index += 1
    return f"joint-{index}"


def default_method(kind: str, how: dict[str, Any] | None) -> str:
    if kind == "bearing":
        return "bearing"
    return "pressed" if how and how.get("form") == "cylindrical" else "bonded"


def adopted(design: WorkshopDesign) -> dict[str, Any]:
    """The design's construction with its connections written down as joints.

    A template's connections are worked out from which parts touch and what they
    are. Building on it starts by keeping those as joints of the person's own,
    which can then be changed; nothing is inferred after that.
    """
    construction = deepcopy(of(design))
    if construction.get("joints_authored"):
        return construction
    from mcp import workshop_graph
    joints = []
    for relation in workshop_graph.product(design).relationships:
        if relation.derived or relation.kind not in JOINT_KINDS:
            continue
        a = next(p for p in design.parts if p.name == relation.a)
        b = next(p for p in design.parts if p.name == relation.b)
        joints.append({"id": f"joint-{len(joints) + 1}", "kind": relation.kind,
                       "method": default_method(relation.kind, interface(a, b)),
                       "a": relation.a, "b": relation.b})
    construction["joints"] = joints
    construction["joints_authored"] = True
    construction.setdefault("schema", CONSTRUCTION_SCHEMA)
    return construction


def add_part(design: WorkshopDesign, overrides: dict[str, Any], *, part: WirePart,
             joint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Put a placed part into the design, fastened to ``joint['to']`` if asked."""
    construction = adopted(design)
    if any(p.name == part.name for p in design.parts):
        raise ValueError(f"there is already a part called {part.name!r}")
    record = {"name": part.name, "role": part.role, "shape": part.shape,
              "size_m": [float(v) for v in part.size_m], "center_m": [float(v) for v in part.center_m],
              "rotation_deg": [float(v) for v in part.rotation_deg], "material": part.material}
    if part.family:
        record["family"] = part.family
    construction.setdefault("added", []).append(record)
    if joint:
        other = next((p for p in design.parts if p.name == str(joint.get("to") or "")), None)
        if other is None:
            raise ValueError("the part to fasten it to is not in this design")
        kind = str(joint.get("kind") or "fixed")
        how = interface(part, other)
        if how is None:
            raise ValueError(f"{part.name} does not touch {other.name}, so nothing can fasten them; "
                             "move it against the part first")
        construction.setdefault("joints", []).append({
            "id": _fresh_joint_id(construction), "kind": kind,
            "method": str(joint.get("method") or default_method(kind, how)),
            "a": other.name, "b": part.name})
    return _with(overrides, construction)


def remove_part(design: WorkshopDesign, overrides: dict[str, Any], name: str) -> dict[str, Any]:
    """Take a part off, with the joints that held it and the edits made to it."""
    if not any(p.name == name for p in design.parts):
        raise ValueError(f"there is no part {name!r} in this design")
    if len(design.parts) == 1:
        raise ValueError("a design keeps at least one part")
    construction = adopted(design)
    added = construction.get("added") or []
    if any(p["name"] == name for p in added):
        construction["added"] = [p for p in added if p["name"] != name]
    else:
        construction["removed"] = sorted(set(construction.get("removed") or []) | {name})
    construction["joints"] = [j for j in construction.get("joints") or [] if name not in (j["a"], j["b"])]
    out = _with(overrides, construction)
    out.pop(name, None)
    return out


def set_joint(design: WorkshopDesign, overrides: dict[str, Any], *, a: str, b: str,
              kind: str | None, method: str | None = None) -> dict[str, Any]:
    """Fasten two parts, change how they are fastened, or (kind None) unfasten them."""
    parts = {p.name: p for p in design.parts}
    if a not in parts or b not in parts or a == b:
        raise ValueError("a joint holds two different parts of this design")
    construction = adopted(design)
    pair = tuple(sorted((a, b)))
    joints = construction.get("joints") or []
    current = next((j for j in joints if tuple(sorted((j["a"], j["b"]))) == pair), None)
    if kind is None:
        if current is None:
            raise ValueError(f"{a} and {b} are not fastened")
        construction["joints"] = [j for j in joints if j is not current]
        return _with(overrides, construction)
    how = interface(parts[a], parts[b])
    if how is None:
        raise ValueError(f"{a} does not touch {b}, so nothing can fasten them")
    made = {"id": current["id"] if current else _fresh_joint_id(construction), "kind": kind,
            "method": method or default_method(kind, how), "a": a, "b": b}
    construction["joints"] = [made if j is current else j for j in joints] if current else joints + [made]
    return _with(overrides, construction)


# ---------------------------------------------------------------------------
# What the rest of the Workshop reads
# ---------------------------------------------------------------------------

def _rounded(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 9)
    if isinstance(value, tuple):
        return [_rounded(v) for v in value]
    return value


def joints(design: WorkshopDesign) -> list[dict[str, Any]]:
    """Every declared joint with where it is now, measured from the parts.

    A joint whose parts no longer touch is reported ``open``: an edit moved one
    of them away. It is kept, so that moving the part back closes it again.
    """
    parts = {p.name: p for p in design.parts}
    out = []
    for joint in of(design).get("joints") or []:
        how = interface(parts[joint["a"]], parts[joint["b"]])
        row: dict[str, Any] = dict(joint)
        if how is None:
            row.update(open=True, why=f"{joint['a']} and {joint['b']} no longer touch")
        else:
            row["open"] = False
            row["interface"] = {k: _rounded(v) for k, v in how.items()}
            if joint["kind"] == "bearing" and how["form"] != "cylindrical":
                # A turning joint on a flat face turns about that face's normal.
                row["interface"]["axis"] = _rounded(how["normal"])
        out.append(row)
    return out


def unfastened(design: WorkshopDesign) -> list[str]:
    """Parts no joint holds, once the design has joints of its own at all."""
    construction = of(design)
    if not construction.get("joints_authored") or len(design.parts) < 2:
        return []
    held = {n for j in construction.get("joints") or [] for n in (j["a"], j["b"])}
    return sorted(p.name for p in design.parts if p.name not in held)


def _bounds(part: WirePart) -> tuple[Vec, Vec]:
    corners = part.corners_m()
    return (tuple(min(c[i] for c in corners) for i in range(3)),      # type: ignore[return-value]
            tuple(max(c[i] for c in corners) for i in range(3)))


def touching_unfastened(design: WorkshopDesign) -> list[list[str]]:
    """Pairs of parts that meet and that no joint holds: what could be fastened."""
    construction = of(design)
    if not construction.get("joints_authored"):
        return []
    held = {tuple(sorted((j["a"], j["b"]))) for j in construction.get("joints") or []}
    boxes = {p.name: _bounds(p) for p in design.parts}
    out = []
    for i, a in enumerate(design.parts):
        for b in design.parts[i + 1:]:
            if tuple(sorted((a.name, b.name))) in held:
                continue
            (alo, ahi), (blo, bhi) = boxes[a.name], boxes[b.name]
            if any(alo[k] > bhi[k] + CONTACT_TOLERANCE_M or blo[k] > ahi[k] + CONTACT_TOLERANCE_M
                   for k in range(3)):
                continue
            if interface(a, b) is not None:
                out.append([a.name, b.name])
    return out


def described(design: WorkshopDesign) -> dict[str, Any]:
    construction = of(design)
    return {"schema": CONSTRUCTION_SCHEMA,
            "joints_authored": bool(construction.get("joints_authored")),
            "added": [p["name"] for p in construction.get("added") or []],
            "removed": list(construction.get("removed") or []),
            "joints": joints(design), "unfastened": unfastened(design),
            "touching_unfastened": touching_unfastened(design)}
