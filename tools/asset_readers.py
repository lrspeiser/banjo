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


def read_mesh(path: Path, *, deflection_mm: float = DEFAULT_DEFLECTION_MM,
              angular_deflection_rad: float = DEFAULT_ANGULAR_DEFLECTION_RAD) -> dict[str, Any]:
    """Triangles from whatever this file is, by the reader that handles it."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".obj":
        return read_obj(path)
    if suffix in STEP_SUFFIXES:
        if not available()["step"]:
            raise ValueError(f"{path.name}: reading STEP needs Open Cascade; install "
                             "tools/asset-compiler-requirements.txt into a virtual environment")
        return read_step(path, deflection_mm=deflection_mm,
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


def read_step(path: Path, *, deflection_mm: float = DEFAULT_DEFLECTION_MM,
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

    reader = STEPControl_Reader()
    if reader.ReadFile(str(path)) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise ValueError(f"{path.name}: Open Cascade would not read this as STEP")
    reader.TransferRoots()
    return tessellate(reader.OneShape(), deflection_mm=deflection_mm,
                      angular_deflection_rad=angular_deflection_rad)


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
