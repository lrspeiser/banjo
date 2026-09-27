// The surface of a body made of cells.
//
// A lattice body arrives from the engine as a list of cell centres, and the
// page used to draw one solid cube at each of them. Most of those cubes are
// buried inside the body and can never be seen, and every cube that can be seen
// is drawn with all six of its faces, five of them pressed against a
// neighbour. A pane of glass a hundred cells across paid for tens of thousands
// of triangles nobody would ever look at.
//
// This takes the same cells and gives back the hull: only the faces with
// nothing behind them, and coplanar runs of those merged into as few rectangles
// as they will make. It also darkens each corner by how much matter is heaped
// up around it, which is the thing that makes a body of cells read as one solid
// object rather than as a pile of blocks.
//
// THE CELLS HAVE MOVED, and that is the whole difficulty. What arrives is not a
// tidy grid: it is where the lattice's nodes ARE, strained, sagging, or thrown
// about by the break that made the piece. So the grid is used for one thing
// only -- deciding which cell is next to which -- and every corner of the hull
// is then placed by AVERAGING where the cells touching it actually are. An
// undeformed body comes out exactly on its cell boundaries; a bent one comes
// out bent, by the amount it is really bent, with no cracks between its faces.
// Where the cells have moved so far that the grid can no longer say what is
// next to what, this gives back nothing and the caller draws cubes.
//
// IT IS A PICTURE AND NOTHING ELSE. The cells it is given are the cells the
// engine is colliding. Nothing here goes back to them: nothing is smoothed,
// nothing is straightened, and nothing is put where the engine has nothing.
// That is the same rule the C++ CellSkin states for the network world
// (src/fracture/CellSkin.hpp: "Does not mutate physics or invent
// fracture/forces. No smooth-surface claim"), and it is here for the same
// reason -- a drawing that flatters the matter is a drawing that lies about it.

// How bright a corner is, by how many of the cells crowding it are filled.
// Nothing around it is full brightness; matter on more than one side of it is
// the darkest, which is the inside of every right angle.
export const CORNER_SHADE = [0.42, 0.63, 0.83, 1.0];

// HOW MUCH OF A CELL THE EDGES ARE TAKEN OFF BY, as a share of one.
//
// Nothing in the world has an edge you could cut yourself on at this scale: a
// sawn board, a cast block and a broken shard all catch the light along their
// edges instead of ending in a perfect line, and a hull that ends in perfect
// lines is the last thing left saying "drawn by a machine" once it is lit.
//
// So the corners of the hull that stand PROUD are pulled in a little and the
// light is leaned over them, which chamfers every convex edge and leaves every
// flat face and every inside corner exactly where it was. A tenth of a cell is
// four millimetres at the forty-millimetre cells rooms use: far inside the
// √3·h/2 the voxelisation is already out by, and enough to catch a highlight.
//
// Zero turns it off, and the tests that check the hull encloses EXACTLY the
// volume of its cells run that way, because a chamfer really does take a
// little volume off and a test that hid that would be worth nothing.
export const BEVEL = 0.1;

// How far off its grid place a cell may have moved before the grid stops being
// able to say what is next to what. A third of a cell: past that a node is
// closer to its neighbour's place than to its own, and the faces this culls
// would be the wrong ones.
const MAX_OFF_GRID = 0.35;

// And how far one may have moved before the body counts as bent, after which
// its faces are no longer merged into long rectangles -- a rectangle laid
// across a curve is flat, and flattening a bend is the one thing this must not
// do. Two hundredths of a cell is under a millimetre at the sizes rooms use.
const BENT_OFF_GRID = 0.02;

// Past any of these the body is not worth meshing and the caller should fall
// back to drawing cubes: a lattice whose box dwarfs its cells, a slice too wide
// to lay a mask over, or a hull with more faces than the cubes would have cost.
const MAX_LATTICE = 1 << 24;
const MAX_SLICE = 1 << 18;
const MAX_FACES = 60000;

const SIX = [[0, -1], [0, 1], [1, -1], [1, 1], [2, -1], [2, 1]];

// How far the light is leaned over a chamfer, against the face's own normal. A
// chamfer four millimetres across would catch almost nothing on its own; the
// lean is what makes the edge read as an edge that has been taken off rather
// than as a line, and it costs no geometry at all.
const LEAN = 0.7;

// cells: local cell centres in metres, as the engine reports them.
// cellSize: the room's cell size in metres.
//
// Gives back {positions, normals, shades, quads, faces, bent} as plain arrays
// ready for a buffer, or null when the caller should draw cubes instead. Null
// is never a failure to be reported -- it is this saying the cubes are the
// better picture here, and the cubes are always correct.
export function cellSurface(cells, cellSize, options = {}) {
  const h = Number(cellSize);
  // How far the proud corners are pulled in, in metres. A share of a cell, so
  // that a room at ten millimetres and one at forty get the same edge for their
  // size; never more than a third of one, or a single cell would vanish.
  const asked = options.bevel === undefined ? BEVEL : Number(options.bevel);
  const bevel = Number.isFinite(asked) && asked > 0 ? Math.min(asked, 0.33) * h : 0;
  if (!Array.isArray(cells) || cells.length === 0 || !Number.isFinite(h) || h <= 0) return null;
  const n = cells.length;
  const half = h / 2;

  // Where the cells sit against their own grid. Indices are counted from the
  // lowest cell on each axis rather than from the body's origin: what arrives
  // is offsets from a centre of mass, so they straddle zero and sit at half a
  // cell as often as on one, and counting from the lowest keeps every division
  // well away from the half where the rounding could go either way.
  const low = [Infinity, Infinity, Infinity];
  for (const at of cells) {
    if (!at || at.length < 3) return null;
    for (let d = 0; d < 3; ++d) {
      const x = Number(at[d]);
      if (!Number.isFinite(x)) return null;
      if (x < low[d]) low[d] = x;
    }
  }
  const grid = new Int32Array(n * 3);
  for (let c = 0; c < n; ++c)
    for (let d = 0; d < 3; ++d)
      grid[c * 3 + d] = Math.round((Number(cells[c][d]) - low[d]) / h);

  // Where the grid really sits, fitted rather than assumed.
  //
  // The lowest cell is a bad place to hang it from: it is the one cell that
  // has been pushed furthest that way, so measuring everything from it counts
  // that cell's own displacement against every other cell and makes a body
  // look about twice as bent as it is. So the places above are used once, to
  // number the cells, and then the origin is put where the cells on average
  // say it is -- which is a least-squares fit of the grid to the matter, and
  // costs one more pass.
  const origin = [0, 0, 0];
  for (let c = 0; c < n; ++c)
    for (let d = 0; d < 3; ++d)
      origin[d] += Number(cells[c][d]) - grid[c * 3 + d] * h;
  for (let d = 0; d < 3; ++d) origin[d] /= n;

  const least = [0, 0, 0], most = [0, 0, 0];
  let worstOff = 0;
  for (let c = 0; c < n; ++c) {
    for (let d = 0; d < 3; ++d) {
      const steps = (Number(cells[c][d]) - origin[d]) / h;
      const i = Math.round(steps);
      const off = Math.abs(steps - i);
      if (off > worstOff) worstOff = off;
      grid[c * 3 + d] = i;
      if (c === 0 || i < least[d]) least[d] = i;
      if (c === 0 || i > most[d]) most[d] = i;
    }
  }
  // Moved too far to say what is beside what.
  if (worstOff > MAX_OFF_GRID) return null;
  // Counted from zero, whatever the fit made the lowest index.
  for (let c = 0; c < n; ++c)
    for (let d = 0; d < 3; ++d) grid[c * 3 + d] -= least[d];
  const high = [most[0] - least[0], most[1] - least[1], most[2] - least[2]];
  const span = [high[0] + 1, high[1] + 1, high[2] + 1];
  if (span[0] * span[1] * span[2] > MAX_LATTICE) return null;

  const strideU = span[2], strideD = span[1] * span[2];
  // Grid place -> where that cell actually is. Two cells in one place means the
  // grid has stopped describing this body, and a hull built on it would have
  // holes in it: hand it back rather than draw one.
  const place = new Map();
  for (let c = 0; c < n; ++c) {
    const key = grid[c * 3] * strideD + grid[c * 3 + 1] * strideU + grid[c * 3 + 2];
    if (place.has(key)) return null;
    place.set(key, c);
  }

  const has = (i, j, k) => i >= 0 && i < span[0] && j >= 0 && j < span[1]
    && k >= 0 && k < span[2] && place.has(i * strideD + j * strideU + k);

  // A cell named in the (axis, slice, across, along) frame this walks in.
  const here = [0, 0, 0];
  const near = (d, s, a, b) => {
    here[d] = s; here[(d + 1) % 3] = a; here[(d + 2) % 3] = b;
    return has(here[0], here[1], here[2]);
  };

  // Where one corner of the grid is, in metres, averaged over the cells that
  // are really touching it. Each of the eight cells around a corner says where
  // it thinks that corner is -- its own middle, plus half a cell towards it --
  // and the corner goes where they agree. Two faces meeting on a corner ask for
  // the same corner and get the same answer, so the hull cannot crack open
  // along an edge however far the matter has moved.
  const corners = new Map();
  const spanAcross = [span[0] + 1, span[1] + 1, span[2] + 1];
  const cornerAt = (ci, cj, ck) => {
    const key = (ci * spanAcross[1] + cj) * spanAcross[2] + ck;
    const had = corners.get(key);
    if (had) return had;
    let x = 0, y = 0, z = 0, count = 0;
    // Which way the matter lies from this corner, counted on the grid rather
    // than on where the cells have got to, so that a strained body's edges are
    // taken off by the same amount as a still one's.
    let gx = 0, gy = 0, gz = 0;
    for (let i = ci - 1; i <= ci; ++i)
      for (let j = cj - 1; j <= cj; ++j)
        for (let k = ck - 1; k <= ck; ++k) {
          if (!has(i, j, k)) continue;
          const at = cells[place.get(i * strideD + j * strideU + k)];
          x += Number(at[0]) + (i < ci ? half : -half);
          y += Number(at[1]) + (j < cj ? half : -half);
          z += Number(at[2]) + (k < ck ? half : -half);
          gx += i < ci ? -1 : 1;
          gy += j < cj ? -1 : 1;
          gz += k < ck ? -1 : 1;
          ++count;
        }
    // Nothing touching it: on the fitted grid, where a corner of an empty cell
    // would be. Nothing asks for one of these -- a corner is only wanted for a
    // face, and a face always has a cell behind it -- but a corner has to have
    // somewhere to be.
    const at = count ? [x / count, y / count, z / count]
                     : [origin[0] + (least[0] + ci) * h - half,
                        origin[1] + (least[1] + cj) * h - half,
                        origin[2] + (least[2] + ck) * h - half];
    let lean = null;
    // A corner STANDS PROUD when the matter round it lies off to one side in
    // more than one direction at once: one cell touching it is the corner of a
    // block, two are its edge, three or four an angle of it. Five or more and
    // it is an inside corner, which a chamfer would only deepen. And a corner
    // in the middle of a FLAT face has matter lying straight inwards and
    // nothing else -- that one must not move, or the whole face sinks.
    if (bevel > 0 && count >= 1 && count <= 4) {
      const len = Math.hypot(gx, gy, gz);
      if (len > 1e-9) {
        const dx = gx / len, dy = gy / len, dz = gz / len;
        if (Math.max(Math.abs(dx), Math.abs(dy), Math.abs(dz)) < 0.93) {
          // `lean` points the way the matter lies, so the corner is moved
          // TOWARDS it -- a corner standing proud is cut off, never pushed out
          // -- and the chamfer's own outward normal is the other way, which is
          // what the light is leaned by.
          at[0] += dx * bevel; at[1] += dy * bevel; at[2] += dz * bevel;
          lean = [dx, dy, dz];
        }
      }
    }
    const made = { at, lean };
    corners.set(key, made);
    return made;
  };

  // Which cells are in each slice, one map per axis, so a slice's mask covers
  // only the cells in that slice and not the whole body's box.
  const slices = [new Map(), new Map(), new Map()];
  let faces = 0;
  for (let c = 0; c < n; ++c) {
    const i = grid[c * 3], j = grid[c * 3 + 1], k = grid[c * 3 + 2];
    for (let d = 0; d < 3; ++d) {
      const s = grid[c * 3 + d];
      let list = slices[d].get(s);
      if (!list) slices[d].set(s, list = []);
      list.push(c);
    }
    for (const [d, side] of SIX) {
      const p = [i, j, k];
      p[d] += side;
      if (!has(p[0], p[1], p[2])) ++faces;
    }
  }
  if (!faces || faces > MAX_FACES) return null;

  const bent = worstOff > BENT_OFF_GRID;
  const positions = [], normals = [], shades = [];
  let quads = 0;

  // How bright a corner of the hull is: how many of the four cells crowding it
  // on the EMPTY side of the face are filled. Written against the corner's own
  // grid place rather than against the cell that asked, so two faces meeting on
  // one corner get the same answer and the shading runs on across the seam.
  const shadeAt = (d, s, side, cu, cv) => {
    const off = s + side;
    const n = (near(d, off, cu - 1, cv - 1) ? 1 : 0) + (near(d, off, cu, cv - 1) ? 1 : 0)
            + (near(d, off, cu - 1, cv) ? 1 : 0) + (near(d, off, cu, cv) ? 1 : 0);
    return Math.max(0, 3 - n);
  };

  const facing = [0, 0, 0];
  const vertex = (at, shade, lean) => {
    positions.push(at[0], at[1], at[2]);
    if (!lean) {
      normals.push(facing[0], facing[1], facing[2]);
    } else {
      // The light leaned over the chamfer. The face is where it was and the
      // silhouette is where it was; this says only that the edge does not end
      // in a perfect line, which is true of every edge there has ever been.
      const nx = facing[0] - lean[0] * LEAN, ny = facing[1] - lean[1] * LEAN,
            nz = facing[2] - lean[2] * LEAN;
      const len = Math.hypot(nx, ny, nz) || 1;
      normals.push(nx / len, ny / len, nz / len);
    }
    shades.push(shade, shade, shade);
  };
  const triangle = (a, b, c) => { vertex(a[0], a[1], a[2]); vertex(b[0], b[1], b[2]);
                                  vertex(c[0], c[1], c[2]); };

  // One rectangle of hull, from cell `aMin..aMax` across and `bMin..bMax` along
  // in its slice.
  //
  // Drawn as a flat middle with a rim round it, one step of the rim per cell,
  // so that the corners standing proud can be pulled in along the WHOLE of an
  // edge and not only at the four ends of it. A rectangle whose corners are all
  // flush keeps to two triangles, which is nearly all of them.
  const quad = (d, s, side, aMin, aMax, bMin, bMax) => {
    const u = (d + 1) % 3, v = (d + 2) % 3;
    // A cell at index i owns the grid corners i and i + 1 along each axis.
    const onD = s + (side > 0 ? 1 : 0);
    const u0 = aMin, u1 = aMax + 1, v0 = bMin, v1 = bMax + 1;
    facing[0] = facing[1] = facing[2] = 0;
    facing[d] = side;
    const corner = (a, b) => {
      here[d] = onD; here[u] = a; here[v] = b;
      return cornerAt(here[0], here[1], here[2]);
    };
    // Where a grid corner of this face sits when it is NOT pulled: on the
    // face's own plane. The rim's inner ring is built from these, moved in by
    // the bevel, so the middle of the face stays exactly flat.
    const flat = (a, b) => {
      const got = corner(a, b);
      if (!got.lean) return got.at;
      return [got.at[0] - got.lean[0] * bevel, got.at[1] - got.lean[1] * bevel,
              got.at[2] - got.lean[2] * bevel];
    };

    // Round the rim, one vertex per cell boundary, anticlockwise seen from
    // outside: from the +axis side the canonical order across then along is
    // already anticlockwise, and from the -axis side it has to go the other way
    // round or the face is drawn inside out and disappears.
    const ring = [];
    const walk = (a, b) => ring.push([a, b]);
    if (side > 0) {
      for (let a = u0; a < u1; ++a) walk(a, v0);
      for (let b = v0; b < v1; ++b) walk(u1, b);
      for (let a = u1; a > u0; --a) walk(a, v1);
      for (let b = v1; b > v0; --b) walk(u0, b);
    } else {
      for (let b = v0; b < v1; ++b) walk(u0, b);
      for (let a = u0; a < u1; ++a) walk(a, v1);
      for (let b = v1; b > v0; --b) walk(u1, b);
      for (let a = u1; a > u0; --a) walk(a, v0);
    }

    const got = ring.map(([a, b]) => corner(a, b));
    const proud = got.some((c) => c.lean);
    const shade = ring.map(([a, b]) => CORNER_SHADE[shadeAt(d, s, side, a, b)]);
    if (!proud) {
      // Nothing stands proud: the plain rectangle, two triangles, as before.
      const ends = side > 0 ? [[u0, v0], [u1, v0], [u1, v1], [u0, v1]]
                            : [[u0, v0], [u0, v1], [u1, v1], [u1, v0]];
      const at = ends.map(([a, b]) => corner(a, b).at);
      const lit = ends.map(([a, b]) => CORNER_SHADE[shadeAt(d, s, side, a, b)]);
      // Which way the rectangle is split matters when its corners are not all
      // the same brightness: run the seam between the pair that differ least,
      // or the shading kinks along the diagonal and reads as a crease.
      const flip = Math.abs(lit[0] - lit[2]) > Math.abs(lit[1] - lit[3]);
      const order = flip ? [1, 2, 3, 1, 3, 0] : [0, 1, 2, 0, 2, 3];
      for (const c of order) vertex(at[c], lit[c], null);
      ++quads;
      return;
    }

    // The middle, flat and inset by the bevel on every side, and the rim
    // between it and the pulled corners. The middle's own corners are the
    // inset rectangle's; the rim's inner ring follows the outer one step for
    // step, so the two meet all the way round with nothing between them.
    const room = Math.min(bevel, 0.45 * h * Math.min(u1 - u0, v1 - v0));
    const inward = (a, b) => {
      const at = flat(a, b).slice();
      at[u] += (a === u0 ? room : a === u1 ? -room : 0);
      at[v] += (b === v0 ? room : b === v1 ? -room : 0);
      return at;
    };
    const inner = ring.map(([a, b]) => inward(a, b));
    for (let i = 0; i < ring.length; ++i) {
      const j = (i + 1) % ring.length;
      // The rim: outer to outer, then back along the inner ring.
      triangle([got[i].at, shade[i], got[i].lean], [got[j].at, shade[j], got[j].lean],
               [inner[j], shade[j], null]);
      triangle([got[i].at, shade[i], got[i].lean], [inner[j], shade[j], null],
               [inner[i], shade[i], null]);
      quads += 1;
    }
    // The flat middle. Its four corners are the inset rectangle's, and the rim
    // vertices along its sides lie exactly on those lines, so the places they
    // meet are places and not gaps.
    const ends = side > 0 ? [[u0, v0], [u1, v0], [u1, v1], [u0, v1]]
                          : [[u0, v0], [u0, v1], [u1, v1], [u1, v0]];
    const mid = ends.map(([a, b]) => inward(a, b));
    const lit = ends.map(([a, b]) => CORNER_SHADE[shadeAt(d, s, side, a, b)]);
    for (const c of [0, 1, 2, 0, 2, 3]) vertex(mid[c], lit[c], null);
    ++quads;
  };

  for (let d = 0; d < 3; ++d) {
    const u = (d + 1) % 3, v = (d + 2) % 3;
    for (const [s, list] of slices[d]) {
      let aLow = Infinity, aHigh = -Infinity, bLow = Infinity, bHigh = -Infinity;
      for (const c of list) {
        const a = grid[c * 3 + u], b = grid[c * 3 + v];
        if (a < aLow) aLow = a;
        if (a > aHigh) aHigh = a;
        if (b < bLow) bLow = b;
        if (b > bHigh) bHigh = b;
      }
      const across = aHigh - aLow + 1, along = bHigh - bLow + 1;
      // A bent body is drawn face by face: merging its faces into long
      // rectangles would lay something flat over the bend and draw it straight.
      const merging = !bent && across * along <= MAX_SLICE;
      for (const side of [-1, 1]) {
        if (merging) {
          // The slice as a mask: nothing where the face is buried, and
          // otherwise the four corner brightnesses packed into one number, so
          // that two faces merge exactly when they would be shaded the same.
          const mask = new Int32Array(across * along);
          for (const c of list) {
            const a = grid[c * 3 + u], b = grid[c * 3 + v];
            if (near(d, s + side, a, b)) continue;
            const ao = [shadeAt(d, s, side, a, b), shadeAt(d, s, side, a + 1, b),
                        shadeAt(d, s, side, a + 1, b + 1), shadeAt(d, s, side, a, b + 1)];
            mask[(a - aLow) * along + (b - bLow)] =
              1 + ao[0] + (ao[1] << 2) + (ao[2] << 4) + (ao[3] << 6);
          }
          for (let a = 0; a < across; ++a) {
            for (let b = 0; b < along; ++b) {
              const key = mask[a * along + b];
              if (!key) continue;
              let wide = 1;
              while (b + wide < along && mask[a * along + b + wide] === key) ++wide;
              let tall = 1;
              grow: while (a + tall < across) {
                for (let q = 0; q < wide; ++q)
                  if (mask[(a + tall) * along + b + q] !== key) break grow;
                ++tall;
              }
              for (let p = 0; p < tall; ++p)
                mask.fill(0, (a + p) * along + b, (a + p) * along + b + wide);
              quad(d, s, side, aLow + a, aLow + a + tall - 1, bLow + b, bLow + b + wide - 1);
              b += wide - 1;
            }
          }
        } else {
          // Bent, or too wide to lay a mask over, so each face stands on its
          // own. Still the hull, still shaded; only the merging is given up.
          for (const c of list) {
            const a = grid[c * 3 + u], b = grid[c * 3 + v];
            if (near(d, s + side, a, b)) continue;
            quad(d, s, side, a, a, b, b);
          }
        }
      }
    }
  }

  return { positions, normals, shades, quads, faces, bent };
}
