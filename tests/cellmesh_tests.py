"""The hull a body of cells is drawn as (playground/cellmesh.js).

The mesher replaces one solid cube per cell with the cells' outside surface,
merged into as few rectangles as it will make and shaded at the corners. That
is a picture, so the way to check it is against the matter it is a picture of:

- it encloses exactly the volume of the cells it was given, which only comes
  out right if the hull is closed AND every face is wound outwards;
- every edge of it belongs to exactly two triangles, so it has no cracks;
- its area is exactly the exposed faces' area, so nothing was dropped, doubled
  or stretched over a gap;
- the rectangles it merges into are as few as the shading allows;
- a corner with matter piled against it is drawn darker than one in the open;
- and anything it cannot honestly mesh comes back as null, which tells the page
  to draw cubes.

WHAT ARRIVES IS NOT A TIDY GRID. The cells are where the lattice's nodes are,
strained and sagging and thrown about by whatever broke the piece off, so the
cases below include bodies that have moved: a little (still merged, still
sealed), a lot (drawn face by face so the bend is not flattened), and too far
to say what is beside what (given back, so the page draws cubes).

Node runs the module; the arithmetic is checked here.

    python tests/cellmesh_tests.py -v
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = (ROOT / "playground" / "cellmesh.js").as_uri()
NODE = shutil.which("node")

HARNESS = """
import {{ cellSurface, CORNER_SHADE }} from {module!r};
const cases = {cases};
const out = {{}};
for (const [name, {{cells, cell, bevel}}] of Object.entries(cases)) {{
  const mesh = cellSurface(cells, cell, {{bevel: bevel || 0}});
  if (!mesh) {{ out[name] = null; continue; }}
  const p = mesh.positions, s = mesh.shades;
  let volume = 0, area = 0;
  // Every edge of a closed surface belongs to exactly two triangles. Corners
  // are rounded to a tenth of a micrometre so that two faces meeting on one
  // count as meeting, and so that two that do not are seen not to.
  const edges = new Map();
  const at = (i) => [p[i], p[i+1], p[i+2]].map(v => Math.round(v * 1e7)).join(",");
  for (let t = 0; t < p.length; t += 9) {{
    const a = p.slice(t, t + 3), b = p.slice(t + 3, t + 6), c = p.slice(t + 6, t + 9);
    const u = [b[0]-a[0], b[1]-a[1], b[2]-a[2]], v = [c[0]-a[0], c[1]-a[1], c[2]-a[2]];
    const n = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]];
    volume += (a[0]*n[0] + a[1]*n[1] + a[2]*n[2]) / 6;
    area += Math.hypot(n[0], n[1], n[2]) / 2;
    const k = [at(t), at(t + 3), at(t + 6)];
    for (let e = 0; e < 3; ++e) {{
      const pair = [k[e], k[(e + 1) % 3]].sort().join("|");
      edges.set(pair, (edges.get(pair) || 0) + 1);
    }}
  }}
  let loose = 0;
  for (const count of edges.values()) if (count !== 2) ++loose;
  // How far the drawn normals have been leaned off the six square directions:
  // zero when every one of them is a face normal, more when edges are taken
  // off and the light is leaned over them.
  let leaned = 0;
  const n = mesh.normals;
  for (let t = 0; t < n.length; t += 3)
    if (Math.max(Math.abs(n[t]), Math.abs(n[t+1]), Math.abs(n[t+2])) < 0.999) ++leaned;
  out[name] = {{ quads: mesh.quads, faces: mesh.faces, triangles: p.length / 9,
                bent: !!mesh.bent, volume, area, loose_edges: loose,
                shades: [Math.min(...s), Math.max(...s)], leaned,
                verts: s.length / 3, normals: mesh.normals.length / 3 }};
}}
console.log(JSON.stringify(out));
"""


def box(nx, ny, nz, cell=0.04, at=(0.0, 0.0, 0.0)):
    """A solid block of cells, centred on `at` the way the engine reports one."""
    return [[at[0] + (i - (nx - 1) / 2) * cell,
             at[1] + (j - (ny - 1) / 2) * cell,
             at[2] + (k - (nz - 1) / 2) * cell]
            for i in range(nx) for j in range(ny) for k in range(nz)]


def moved(cells, by, cell=0.04):
    """The same cells, each shifted off its grid place by up to `by` of a cell.

    Deterministic, and deliberately not smooth: a real strained lattice has
    each node somewhere of its own, and a mesher that only survives a smooth
    displacement has not been tested on one."""
    out = []
    for n, at in enumerate(cells):
        push = [((n * 37 + a * 53) % 21 - 10) / 10.0 * by * cell for a in range(3)]
        out.append([at[a] + push[a] for a in range(3)])
    return out


def meshes(cases):
    script = HARNESS.format(module=MODULE, cases=json.dumps(cases))
    with tempfile.TemporaryDirectory() as folder:
        run = Path(folder) / "run.mjs"
        run.write_text(script, encoding="utf-8")
        done = subprocess.run([NODE, str(run)], capture_output=True, text=True, timeout=120)
    if done.returncode != 0:
        raise AssertionError(f"node failed: {done.stderr.strip()[:2000]}")
    return json.loads(done.stdout)


@unittest.skipUnless(NODE, "node is not on the path")
class CellHull(unittest.TestCase):
    CELL = 0.04

    @classmethod
    def setUpClass(cls):
        h = cls.CELL
        cls.cases = {
            "one": {"cells": box(1, 1, 1), "cell": h},
            "two by two": {"cells": box(2, 2, 2), "cell": h},
            "three cubed": {"cells": box(3, 3, 3), "cell": h},
            "slab": {"cells": box(10, 1, 10), "cell": h},
            "off centre": {"cells": box(3, 4, 5, at=(1.37, -0.22, 0.05)), "cell": h},
            # Two cells with a gap between them: two separate hulls in one body,
            # which is what a thing that has broken and not yet been swept looks
            # like.
            "apart": {"cells": [[0, 0, 0], [0, 0, 3 * h]], "cell": h},
            # A step, so some corners have matter against them and some do not.
            "step": {"cells": box(2, 1, 2) + [[0.02, 0.04, 0.02]], "cell": h},
            # A shell with a hollow inside it. The hollow's faces point inwards,
            # and the volume only comes out right if they are wound that way.
            "hollow": {"cells": [c for c in box(3, 3, 3)
                                 if max(abs(v) for v in c) > 0.5 * h],
                       "cell": h},
            # Strained, but hardly: still one grid, still merged.
            "barely moved": {"cells": moved(box(4, 4, 4), 0.01, h), "cell": h},
            # Bent: the grid still says what is beside what, but the body has
            # a shape of its own now and must not be merged flat.
            "bent": {"cells": moved(box(4, 4, 4), 0.2, h), "cell": h},
            "bent slab": {"cells": moved(box(8, 1, 8), 0.25, h), "cell": h},
            # Thrown about by the break that made it: no grid can say what is
            # beside what any more.
            "churned": {"cells": moved(box(4, 4, 4), 0.9, h), "cell": h},
            "not a lattice": {"cells": [[0, 0, 0], [0.017, 0, 0]], "cell": h},
            "two cells in one place": {"cells": box(2, 2, 2) + [[0.019, 0.019, 0.019]],
                                       "cell": h},
            "no cells": {"cells": [], "cell": h},
            # And the same shapes with their edges taken off, which is how the
            # page draws them.
            "one bevelled": {"cells": box(1, 1, 1), "cell": h, "bevel": 0.1},
            "three cubed bevelled": {"cells": box(3, 3, 3), "cell": h, "bevel": 0.1},
            "slab bevelled": {"cells": box(10, 1, 10), "cell": h, "bevel": 0.1},
            "step bevelled": {"cells": box(2, 1, 2) + [[0.02, 0.04, 0.02]], "cell": h,
                              "bevel": 0.1},
            "bent bevelled": {"cells": moved(box(4, 4, 4), 0.2, h), "cell": h, "bevel": 0.1},
        }
        cls.out = meshes(cls.cases)

    def cells_in(self, name):
        return len(self.cases[name]["cells"])

    STILL = ["one", "two by two", "three cubed", "slab", "off centre", "apart", "step", "hollow"]
    MOVED = ["barely moved", "bent", "bent slab"]
    BEVELLED = ["one bevelled", "three cubed bevelled", "slab bevelled", "step bevelled",
                "bent bevelled"]

    def test_it_encloses_exactly_the_volume_of_its_cells(self):
        # The one that catches a hole in the hull and a face wound inside out,
        # both of which draw perfectly well and are both wrong.
        for name in self.STILL:
            with self.subTest(name):
                want = self.cells_in(name) * self.CELL ** 3
                self.assertAlmostEqual(self.out[name]["volume"], want, places=9)

    def test_a_body_that_has_moved_still_holds_what_it_is_made_of(self):
        # Not to the cubic millimetre -- the matter has moved, and the drawing
        # follows it -- but a hull that has sprung a leak or turned a face
        # inside out is out by a long way, not by a few per cent.
        for name in self.MOVED:
            with self.subTest(name):
                want = self.cells_in(name) * self.CELL ** 3
                self.assertGreater(self.out[name]["volume"], 0.75 * want)
                self.assertLess(self.out[name]["volume"], 1.25 * want)

    def test_the_edges_are_taken_off_without_opening_the_hull(self):
        """Nothing in the world has an edge you could cut yourself on.

        The corners standing proud are pulled in, which chamfers every convex
        edge; every flat face and every inside corner stays exactly where it
        was. It really does take a little volume off, and saying how much is
        the difference between a finish and a fudge: a tenth of a cell off the
        edges of a single cube costs it about a twentieth of itself, and less
        and less of a body the bigger the body is."""
        for name in self.BEVELLED:
            plain = name.replace(" bevelled", "")
            with self.subTest(name):
                cut, whole = self.out[name], self.out[plain]
                # Still shut, where the faces are single cells and so have no
                # T-junction in them. A merged face's flat middle is drawn as
                # two triangles across a rim of one step per cell, which leaves
                # junctions along it -- exact ones, on a flat coplanar surface,
                # the same as merging has always left
                # (test_where_merging_leaves_a_junction_it_is_exact).
                if name in ("one bevelled", "bent bevelled"):
                    self.assertEqual(cut["loose_edges"], 0)
                # Smaller, by a little, and never bigger.
                self.assertLess(cut["volume"], whole["volume"])
                self.assertGreater(cut["volume"], 0.90 * whole["volume"])
                # And the light is leaned over the chamfers, which is what makes
                # an edge read as an edge rather than as a line. Nothing was
                # leaned before.
                self.assertEqual(whole["leaned"], 0)
                self.assertGreater(cut["leaned"], 0)

    def test_a_single_cube_loses_about_a_twentieth_of_itself(self):
        # A tenth of a cell off all twelve edges and eight corners of a cube.
        cut = self.out["one bevelled"]["volume"]
        whole = self.CELL ** 3
        self.assertGreater(cut, 0.93 * whole)
        self.assertLess(cut, 0.99 * whole)
        # A body a hundred times the size loses a far smaller share of itself,
        # because an edge is a length and a body is a volume.
        big = self.out["three cubed bevelled"]["volume"] / self.out["three cubed"]["volume"]
        self.assertGreater(big, cut / whole)

    def test_a_hull_drawn_face_by_face_is_sealed(self):
        # Corner averaging is what keeps a body that has moved meeting itself:
        # two faces on one corner ask for the same corner and get the same
        # answer. Every edge in exactly two triangles, or there is a hole.
        for name in self.MOVED + ["one", "two by two", "three cubed", "slab", "apart",
                                  "off centre", "hollow"]:
            with self.subTest(name):
                self.assertEqual(self.out[name]["loose_edges"], 0)

    def test_the_flat_of_a_face_is_not_touched(self):
        # A rectangle with no proud corner keeps to two triangles, which is
        # nearly all of them; only a face with an edge to take off pays for a
        # rim. A block is still six rectangles, bevelled or not, because its
        # flat middles are still flat.
        self.assertEqual(self.out["three cubed"]["triangles"], 12)
        self.assertGreater(self.out["three cubed bevelled"]["triangles"], 12)
        # The slab is ten cells across, so its rim is per cell and not per
        # corner: an edge is taken off along the whole of its length.
        rim = self.out["slab bevelled"]["triangles"] - self.out["slab"]["triangles"]
        self.assertGreater(rim, 4 * 10)

    def test_where_merging_leaves_a_junction_it_is_exact(self):
        # Where a merged rectangle meets faces of another size, the small ones
        # meet the long edge part way along it rather than at its ends -- a
        # T-junction, which every mesher that merges has. It is not a crack:
        # merging only happens while the body is still ON its grid, so the
        # junction sits exactly on a cell boundary and the two surfaces are the
        # same surface, which is what the volume being exact to the cubic
        # nanometre says. The step is the one shape here that makes one.
        junctions = {name: self.out[name]["loose_edges"] for name in self.STILL}
        self.assertEqual({name: count for name, count in junctions.items() if count},
                         {"step": 12})
        want = self.cells_in("step") * self.CELL ** 3
        self.assertAlmostEqual(self.out["step"]["volume"], want, places=9)

    def test_its_area_is_the_area_of_the_faces_that_are_exposed(self):
        for name in ["one", "three cubed", "slab", "step", "hollow"]:
            with self.subTest(name):
                got = self.out[name]
                self.assertAlmostEqual(got["area"], got["faces"] * self.CELL ** 2, places=9)

    def test_a_buried_cell_costs_nothing(self):
        # Twenty-seven cells, one of them inside: fifty-four faces, not a
        # hundred and sixty-two. This holds however far the body has moved,
        # because what is buried is decided on the grid.
        self.assertEqual(self.out["three cubed"]["faces"], 54)
        self.assertEqual(self.out["one"]["faces"], 6)
        self.assertEqual(self.out["bent"]["faces"], self.out["barely moved"]["faces"])

    def test_a_flat_face_is_one_rectangle(self):
        # A block is six rectangles however many cells across it is, because
        # every corner on a flat outside face is equally open.
        for name in ["one", "two by two", "three cubed", "slab", "barely moved"]:
            with self.subTest(name):
                self.assertEqual(self.out[name]["quads"], 6)
        self.assertEqual(self.out["three cubed"]["triangles"], 12)
        # A slab ten cells square: 240 faces drawn as 6 rectangles.
        self.assertEqual(self.out["slab"]["faces"], 240)

    def test_a_bent_body_is_drawn_face_by_face(self):
        # Laying one rectangle over a bend draws the bend flat. So a body that
        # has moved off its grid keeps a face per face -- still the hull, still
        # far cheaper than cubes, and still the shape it really has.
        for name in ["bent", "bent slab"]:
            with self.subTest(name):
                got = self.out[name]
                self.assertTrue(got["bent"])
                self.assertEqual(got["quads"], got["faces"])
                # Twelve triangles a cell is what the cubes cost.
                self.assertLess(got["triangles"], 12 * self.cells_in(name))
        self.assertFalse(self.out["barely moved"]["bent"])

    def test_two_pieces_in_one_body_are_two_hulls(self):
        self.assertEqual(self.out["apart"]["quads"], 12)
        self.assertEqual(self.out["apart"]["faces"], 12)

    def test_a_corner_with_matter_against_it_is_darker(self):
        # Nothing is crowded on a lone cube, so every corner is full brightness.
        self.assertEqual(self.out["one"]["shades"], [1.0, 1.0])
        # The step has an inside corner, and the inside of a right angle is the
        # darkest a corner gets.
        self.assertLess(self.out["step"]["shades"][0], 1.0)
        self.assertEqual(self.out["step"]["shades"][1], 1.0)

    def test_every_vertex_carries_a_normal_and_a_shade(self):
        for name, got in self.out.items():
            if got is None:
                continue
            with self.subTest(name):
                self.assertEqual(got["verts"], got["triangles"] * 3)
                self.assertEqual(got["normals"], got["verts"])

    def test_what_it_cannot_honestly_mesh_comes_back_as_cubes(self):
        # Null is the page's instruction to draw cubes, which are always right.
        for name in ["churned", "not a lattice", "two cells in one place", "no cells"]:
            with self.subTest(name):
                self.assertIsNone(self.out[name])


if __name__ == "__main__":
    unittest.main(verbosity=2)
