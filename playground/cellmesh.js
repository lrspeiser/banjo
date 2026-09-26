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

// How bright a corner is, by how many of the three cells crowding it are
// filled. Nothing around it is full brightness; matter on two sides of it is
// the darkest, which is the inside of every right angle.
export const CORNER_SHADE = [0.42, 0.63, 0.83, 1.0];

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

// cells: local cell centres in metres, as the engine reports them.
// cellSize: the room's cell size in metres.
//
// Gives back {positions, normals, shades, quads, faces, bent} as plain arrays
// ready for a buffer, or null when the caller should draw cubes instead. Null
// is never a failure to be reported -- it is this saying the cubes are the
// better picture here, and the cubes are always correct.
export function cellSurface(cells, cellSize) {
  const h = Number(cellSize);
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
    for (let i = ci - 1; i <= ci; ++i)
      for (let j = cj - 1; j <= cj; ++j)
        for (let k = ck - 1; k <= ck; ++k) {
          if (!has(i, j, k)) continue;
          const at = cells[place.get(i * strideD + j * strideU + k)];
          x += Number(at[0]) + (i < ci ? half : -half);
          y += Number(at[1]) + (j < cj ? half : -half);
          z += Number(at[2]) + (k < ck ? half : -half);
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
    corners.set(key, at);
    return at;
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

  // How bright one corner of one face is: the three cells that crowd it, all of
  // them on the empty side of the face, where `du` and `dv` say which corner.
  const cornerShade = (d, s, a, b, side, du, dv) => {
    const beside = near(d, s + side, a + du, b);
    const along = near(d, s + side, a, b + dv);
    if (beside && along) return 0;
    const corner = near(d, s + side, a + du, b + dv);
    return 3 - ((beside ? 1 : 0) + (along ? 1 : 0) + (corner ? 1 : 0));
  };

  const facing = [0, 0, 0];
  const vertex = (at, shade) => {
    positions.push(at[0], at[1], at[2]);
    normals.push(facing[0], facing[1], facing[2]);
    shades.push(shade, shade, shade);
  };

  // One rectangle of hull, from cell `aMin..aMax` across and `bMin..bMax` along
  // in its slice, with the four corner brightnesses it was merged under.
  const quad = (d, s, side, aMin, aMax, bMin, bMax, ao) => {
    const u = (d + 1) % 3, v = (d + 2) % 3;
    // A cell at index i owns the grid corners i and i + 1 along each axis.
    const onD = s + (side > 0 ? 1 : 0);
    const u0 = aMin, u1 = aMax + 1, v0 = bMin, v1 = bMax + 1;
    const corner = (a, b) => {
      here[d] = onD; here[u] = a; here[v] = b;
      return cornerAt(here[0], here[1], here[2]);
    };
    // Corners anticlockwise seen from outside. The canonical order runs
    // (-,-) (+,-) (+,+) (-,+) across then along, which is already anticlockwise
    // from the +axis side; from the -axis side it has to go round the other way
    // or the face is drawn inside out and disappears.
    const us = side > 0 ? [u0, u1, u1, u0] : [u0, u0, u1, u1];
    const vs = side > 0 ? [v0, v0, v1, v1] : [v0, v1, v1, v0];
    const bright = side > 0 ? [ao[0], ao[1], ao[2], ao[3]] : [ao[0], ao[3], ao[2], ao[1]];
    const at = [corner(us[0], vs[0]), corner(us[1], vs[1]),
                corner(us[2], vs[2]), corner(us[3], vs[3])];
    facing[0] = facing[1] = facing[2] = 0;
    facing[d] = side;
    // Which way the rectangle is split matters when its corners are not all
    // the same brightness: run the seam between the pair that differ least, or
    // the shading kinks along the diagonal and reads as a crease in the matter.
    const flip = Math.abs(bright[0] - bright[2]) > Math.abs(bright[1] - bright[3]);
    const order = flip ? [1, 2, 3, 1, 3, 0] : [0, 1, 2, 0, 2, 3];
    for (const c of order) vertex(at[c], CORNER_SHADE[bright[c]]);
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
            const ao = [cornerShade(d, s, a, b, side, -1, -1),
                        cornerShade(d, s, a, b, side, 1, -1),
                        cornerShade(d, s, a, b, side, 1, 1),
                        cornerShade(d, s, a, b, side, -1, 1)];
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
              const packed = key - 1;
              quad(d, s, side, aLow + a, aLow + a + tall - 1, bLow + b, bLow + b + wide - 1,
                   [packed & 3, (packed >> 2) & 3, (packed >> 4) & 3, (packed >> 6) & 3]);
              b += wide - 1;
            }
          }
        } else {
          // Bent, or too wide to lay a mask over, so each face stands on its
          // own. Still the hull, still shaded; only the merging is given up.
          for (const c of list) {
            const a = grid[c * 3 + u], b = grid[c * 3 + v];
            if (near(d, s + side, a, b)) continue;
            quad(d, s, side, a, a, b, b,
                 [cornerShade(d, s, a, b, side, -1, -1), cornerShade(d, s, a, b, side, 1, -1),
                  cornerShade(d, s, a, b, side, 1, 1), cornerShade(d, s, a, b, side, -1, 1)]);
          }
        }
      }
    }
  }

  return { positions, normals, shades, quads, faces, bent };
}
