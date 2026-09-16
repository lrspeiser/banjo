"""Readers for the formats the standard library cannot open.

One interface, `read_mesh`, behind which OBJ is read by tools/asset_compiler.py
with the standard library and everything else by a package that may not be
installed. The compiler defers its import, so neither it nor its suite ever
needs any of this: the pure-Python path is the supported one, and a reader that
is missing is reported rather than worked around.

Measured on Windows, CPython 3.13.5, 2026-09-15:

- `pythonocc-core` has no distribution for this platform at all -- pip answers
  "from versions: none" -- so Open Cascade is reached through `cadquery-ocp`,
  which does ship a cp313 win_amd64 wheel and carries the same OCCT.
- `openvdb` likewise has no distribution, so there are no narrow-band level
  sets here and nothing below pretends otherwise. Occupancy stays the dense
  scan in asset_compiler.py, which the fixtures measure at milliseconds.

No CAD file may be downloaded for this work, so the fixture the STEP reader is
tested against is written by the same library that reads it (`write_step_box`).
That tests this module's tessellation and winding, not Open Cascade's file
format. When a real STEP file arrives it is pointed at `read_mesh` unchanged.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from asset_compiler import read_obj

STEP_SUFFIXES = (".step", ".stp")
# What trimesh reads that is worth offering. Every one of these carries
# triangles already, so nothing here tessellates them.
MESH_SUFFIXES = (".stl", ".ply", ".off", ".glb", ".gltf", ".3mf")

# A tenth of a millimetre: two orders below the 10 mm cell the fixtures use, so
# the tessellation is never what decides whether a cell centre is inside.
DEFAULT_DEFLECTION_MM = 0.1
DEFAULT_ANGULAR_DEFLECTION_RAD = 0.5


def _installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def available() -> dict[str, bool]:
    """Which readers THIS interpreter has, which is not a matter of opinion."""
    return {"obj": True, "step": _installed("OCP"), "mesh": _installed("trimesh")}


def read_mesh(path: Path, *, solid: str | None = None,
              deflection_mm: float = DEFAULT_DEFLECTION_MM,
              angular_deflection_rad: float = DEFAULT_ANGULAR_DEFLECTION_RAD) -> dict[str, Any]:
    """Triangles from whatever this file is, by the reader that handles it.

    `solid` names one labelled solid inside a STEP assembly, by its XCAF entry
    (the "0:1:1:3" form). That is what lets a part be converted once: the five
    solids of an assembly are read as five parts, not as the eighteen shapes
    its instances flatten to.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".obj":
        return read_obj(path)
    if suffix in STEP_SUFFIXES:
        if not available()["step"]:
            raise ValueError(f"{path.name}: reading STEP needs Open Cascade; install "
                             "tools/asset-compiler-requirements.txt into a virtual environment")
        return read_step(path, solid=solid, deflection_mm=deflection_mm,
                         angular_deflection_rad=angular_deflection_rad)
    if suffix in MESH_SUFFIXES:
        if not available()["mesh"]:
            raise ValueError(f"{path.name}: reading {suffix} needs trimesh; install "
                             "tools/asset-compiler-requirements.txt into a virtual environment")
        return read_with_trimesh(path)
    raise ValueError(f"{path.name}: no reader for {suffix or 'a file with no suffix'}; "
                     f"this compiler reads .obj, {', '.join(STEP_SUFFIXES + MESH_SUFFIXES)}")


def tessellate(shape, *, deflection_mm: float = DEFAULT_DEFLECTION_MM,
               angular_deflection_rad: float = DEFAULT_ANGULAR_DEFLECTION_RAD) -> dict[str, Any]:
    """An Open Cascade shape as triangles, wound so that the normal points out.

    Two things have to be right or the winding-number scan reads the solid
    inside out. A face whose orientation is REVERSED lists its triangles the
    other way round, so two of its indices are swapped here; measured, every
    face of a plain OCCT box comes back REVERSED, so this is the ordinary case
    and not an edge case. And a triangulation's nodes are in the face's own
    frame, so the location's transformation has to be applied.

    Faces do not share nodes, so the same corner arrives once per face. That is
    what mesh_report's weld is for, and why closure is counted on welded
    positions rather than on file indices.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    BRepMesh_IncrementalMesh(shape, deflection_mm, False, angular_deflection_rad, True)
    faces = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        faces.append(TopoDS.Face(explorer.Current()))
        explorer.Next()

    vertices: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    for face in faces:
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        if triangulation is None:
            continue
        transformation = location.Transformation()
        offset = len(vertices)
        for index in range(1, triangulation.NbNodes() + 1):
            point = triangulation.Node(index).Transformed(transformation)
            vertices.append((point.X(), point.Y(), point.Z()))
        flip = face.Orientation() == TopAbs_REVERSED
        for index in range(1, triangulation.NbTriangles() + 1):
            a, b, c = triangulation.Triangle(index).Get()
            if flip:
                b, c = c, b
            triangles.append((offset + a - 1, offset + b - 1, offset + c - 1))
    if not triangles:
        raise ValueError("Open Cascade produced no triangles for this shape")
    return {"vertices": vertices, "triangles": triangles}


def read_step(path: Path, *, solid: str | None = None,
              deflection_mm: float = DEFAULT_DEFLECTION_MM,
              angular_deflection_rad: float = DEFAULT_ANGULAR_DEFLECTION_RAD) -> dict[str, Any]:
    """A STEP solid, tessellated.

    Open Cascade normalises a STEP file's own units to millimetres as it reads,
    so what comes back is millimetres whatever the file declared. The assembly
    document must therefore declare `mm` for a STEP part. Reading the file's
    unit declaration and checking the two against each other is the obvious
    next step and is not done here: a part declared wrongly would be caught by
    nothing, which is exactly the failure units_ambiguous exists for.
    """
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.STEPControl import STEPControl_Reader

    if solid is not None:
        return tessellate(_labelled_shape(path, solid), deflection_mm=deflection_mm,
                          angular_deflection_rad=angular_deflection_rad)
    reader = STEPControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise ValueError(f"{path.name}: Open Cascade would not read this as STEP")
    reader.TransferRoots()
    return tessellate(reader.OneShape(), deflection_mm=deflection_mm,
                      angular_deflection_rad=angular_deflection_rad)


# One parsed document per file. Reading the AS1 bracket assembly costs 15 ms to
# parse and 33 ms to transfer, and the compiler asks for five solids out of it
# and then walks it for the instances: without this the 48 ms would be paid six
# times over for one file that has not changed.
_DOCUMENTS: dict[tuple[str, int, float], Any] = {}


def _document(path: Path):
    """The XCAF document for this file, parsed once.

    XCAF rather than STEPControl_Reader because the plain reader answers with
    one flattened shape: the AS1 assembly comes back as 18 solids with the
    instance transforms already baked in, and the fact that 8 of them are the
    same nut is gone. The product structure is the thing worth having.
    """
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, stat.st_mtime)
    cached = _DOCUMENTS.get(key)
    if cached is not None:
        return cached
    document = TDocStd_Document(TCollection_ExtendedString("banjo-asset"))
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    if reader.ReadFile(str(path)) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise ValueError(f"{path.name}: Open Cascade would not read this as STEP")
    if not reader.Transfer(document):
        raise ValueError(f"{path.name}: Open Cascade read the file but transferred no shape")
    _DOCUMENTS[key] = (document, XCAFDoc_DocumentTool.ShapeTool_s(document.Main()))
    return _DOCUMENTS[key]


def _entry(label) -> str:
    from OCP.TCollection import TCollection_AsciiString
    from OCP.TDF import TDF_Tool

    text = TCollection_AsciiString()
    TDF_Tool.Entry_s(label, text)
    return text.ToCString()


def _name(label) -> str:
    from OCP.TDataStd import TDataStd_Name

    attribute = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attribute):
        return attribute.Get().ToExtString()
    return ""


def _labelled_shape(path: Path, solid: str):
    from OCP.TDF import TDF_Label
    from OCP.TDF import TDF_Tool

    document, tool = _document(Path(path))
    label = TDF_Label()
    TDF_Tool.Label_s(document.GetData(), solid, label)
    if label.IsNull():
        raise ValueError(f"{Path(path).name}: no shape is labelled {solid!r}")
    return tool.GetShape_s(label)


def _quarter_turn_degrees(matrix: tuple[float, ...]) -> tuple[float, float, float]:
    """The x, y, z turns that build this rotation, or a refusal.

    Searched rather than solved. Extracting Euler angles from a matrix has
    branches at the poles that are easy to get subtly wrong, and there are only
    64 combinations of quarter turns to try; comparing against the same
    rotation_matrix the placer uses means the answer agrees with the placer by
    construction rather than by argument.
    """
    from asset_compiler import rotation_matrix

    for x in (0.0, 90.0, 180.0, 270.0):
        for y in (0.0, 90.0, 180.0, 270.0):
            for z in (0.0, 90.0, 180.0, 270.0):
                built = rotation_matrix((x, y, z))
                if all(abs(built[r][c] - matrix[r * 3 + c]) < 1.0e-9 for r in range(3)
                       for c in range(3)):
                    return (x, y, z)
    raise ValueError(f"the instance rotation {matrix} is not a quarter turn about each axis, so it "
                     "cannot be re-indexed onto the shared grid; it would have to be voxelised "
                     "again in world space, which is a different cell count")


def step_assembly(path: Path, *, unit: str = "mm") -> dict[str, Any]:
    """The canonical assembly this STEP file declares: unique parts, and placements.

    Every solid the product structure names once becomes one part, and every
    leaf of the assembly tree becomes one instance carrying the transform
    accumulated from the root. A sub-assembly used twice is walked twice, so
    the instance count is the number of solids that end up in the world rather
    than the number of parent-to-child links the file declares. Measured on the
    AS1 bracket assembly: 5 parts, 13 declared usage links and 18 placements,
    8 of them the same nut.

    No rights are invented here: a STEP file does not say who may use it, so
    the caller supplies that and an assembly without it is reported
    `rights_unverified` like any other.
    """
    from OCP.TDF import TDF_Label
    from OCP.TopLoc import TopLoc_Location
    from OCP.collections import Sequence_TDF_Label

    path = Path(path)
    _, tool = _document(path)
    parts: dict[str, dict[str, Any]] = {}
    instances: list[dict[str, Any]] = []

    def walk(label, location, trail: str) -> None:
        if tool.IsAssembly_s(label):
            components = Sequence_TDF_Label()
            tool.GetComponents_s(label, components)
            for index in range(1, components.Length() + 1):
                component = components.Value(index)
                referred = TDF_Label()
                if not tool.GetReferredShape_s(component, referred):
                    continue
                walk(referred, location.Multiplied(tool.GetLocation_s(component)),
                     f"{trail}/{_name(component) or index}")
            return
        entry = _entry(label)
        part_id = _name(label) or entry.replace(":", "-")
        parts.setdefault(part_id, {"mesh": path.name, "solid": entry, "unit": unit})
        transform = location.Transformation()
        rotation = tuple(transform.Value(row, column) for row in (1, 2, 3) for column in (1, 2, 3))
        instances.append({
            "id": trail.lstrip("/") or part_id,
            "part": part_id,
            "translation_mm": [transform.Value(row, 4) for row in (1, 2, 3)],
            "rotation_deg": list(_quarter_turn_degrees(rotation)),
        })

    free = Sequence_TDF_Label()
    tool.GetFreeShapes(free)
    for index in range(1, free.Length() + 1):
        root = free.Value(index)
        walk(root, TopLoc_Location(), f"/{_name(root) or index}")
    return {"schema": "banjo.asset-assembly.v1", "parts": parts, "instances": instances}


def read_with_trimesh(path: Path) -> dict[str, Any]:
    """An STL, PLY or glTF, as its own triangles.

    `process=False`: trimesh merges vertices and drops degenerate faces by
    default, and this compiler would rather see the file as it is and report on
    it than be handed a quietly repaired mesh.
    """
    import trimesh

    loaded = trimesh.load_mesh(str(path), process=False)
    if isinstance(loaded, trimesh.Scene):
        loaded = trimesh.util.concatenate(tuple(loaded.geometry.values()))
    return {"vertices": [tuple(float(v) for v in vertex) for vertex in loaded.vertices],
            "triangles": [tuple(int(i) for i in face) for face in loaded.faces]}


def write_step_box(path: Path, size_mm: tuple[float, float, float]) -> Path:
    """A box written as STEP, so the reader has something to be tested on.

    The corner is the origin and the extents are as given, which is the same
    box tools/asset_fixtures.py writes as OBJ; a conversion through each has to
    land on the same cells.
    """
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.STEPControl import STEPControl_StepModelType, STEPControl_Writer

    writer = STEPControl_Writer()
    writer.Transfer(BRepPrimAPI_MakeBox(*size_mm).Shape(),
                    STEPControl_StepModelType.STEPControl_AsIs)
    if writer.Write(str(path)) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise ValueError(f"{path.name}: Open Cascade would not write this as STEP")
    return path
