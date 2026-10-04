// The ground beyond the valley, as the engine streams it in (docs/streamed-regions.md).
//
// The valley is drawn by world.js from its own grid. Each region beside it is
// the same picture on a grid of its own -- the valley's size, one cell past the
// valley's last column -- so a region is added by drawing it, and nothing that
// is already drawn is touched: its column tops are one mesh, its cut faces are
// built in 32 x 32 column chunks as the valley's are, and a dig out there
// patches only the columns it changed.
//
// Presentation only: heights, what each column is made of and the faces a cut
// exposes, all from the engine's numbers. Regions have no water.
import * as THREE from "/vendor/three.module.js";
import { GROUND_APPEARANCE, columnTopData, walkColumnFaces, columnChunkIds, columnChunkBox, terrainCellAt }
  from "/material_appearance.js";
import { terrainMaterial } from "/terrain_material.js";

const COLOURS = GROUND_APPEARANCE.map(row => new THREE.Color(`#${row.color}`));
const RUN_VOID = 8;

function bytesOf(b64) {
  const s = atob(b64 || "");
  const out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; ++i) out[i] = s.charCodeAt(i);
  return out;
}

// Runs, as the valley's: a fixed stride of room per column, heights in
// millimetres above this region's own floor.
function decodeRuns(raw, at, into, c, floor) {
  const count = raw[at++];
  into.count[c] = count;
  for (let k = 0; k < count; ++k) {
    if (k < into.stride) {
      into.kind[c * into.stride + k] = raw[at];
      into.top[c * into.stride + k] = floor + (raw[at + 1] | (raw[at + 2] << 8)) / 1000;
    }
    at += 3;
  }
  return at;
}

function takeRuns(raw, cells, floor) {
  let most = 4;
  for (let c = 0, at = 0; c < cells && at < raw.length; ++c) { most = Math.max(most, raw[at]); at += 1 + 3 * raw[at]; }
  const runs = { stride: most + 2, count: new Uint8Array(cells),
                 kind: new Uint8Array(cells * (most + 2)), top: new Float32Array(cells * (most + 2)) };
  for (let c = 0, at = 0; c < cells && at < raw.length; ++c) at = decodeRuns(raw, at, runs, c, floor);
  return runs;
}

function growRuns(region, needed) {
  const was = region.runs, cells = was.count.length, stride = Math.max(needed, was.stride + 2);
  const runs = { stride, count: was.count, kind: new Uint8Array(cells * stride), top: new Float32Array(cells * stride) };
  for (let c = 0; c < cells; ++c)
    for (let k = 0; k < was.stride; ++k) {
      runs.kind[c * stride + k] = was.kind[c * was.stride + k];
      runs.top[c * stride + k] = was.top[c * was.stride + k];
    }
  region.runs = runs;
}

function kindOf(region, c) {
  const runs = region.runs;
  return runs && runs.count[c] > 0 ? runs.kind[c * runs.stride + runs.count[c] - 1] : region.surfaces[c];
}

function paint(region, c) {
  const colour = COLOURS[kindOf(region, c)] || COLOURS[1];
  region.colors[3 * c] = colour.r; region.colors[3 * c + 1] = colour.g; region.colors[3 * c + 2] = colour.b;
}

// Every region the engine has sent, and what is drawn of each.
export function makeRegions(scene, dressMaterial) {
  const regions = new Map();
  let faceMaterial = null;
  const trace = [];

  function remove(region) {
    scene.remove(region.mesh);
    region.mesh.geometry.dispose();
    region.materialCells.dispose();
    region.materialCells.material.dispose();
    for (const mesh of region.faceChunks.values()) { scene.remove(mesh); mesh.geometry.dispose(); }
    region.faceChunks.clear();
  }

  // A region whole: drawn new, or drawn again in place of what was there.
  function add(block) {
    const started = performance.now();
    const key = `${block.at[0]},${block.at[1]}`;
    const { nx, nz, cell_m: dx, x0_m: x0, z0_m: z0 } = block.grid;
    const was = regions.get(key);
    // Already drawn (a page sent the whole ground in the same reply): only
    // what differs is drawn again.
    if (was && was.grid.nx === nx && was.grid.nz === nz && was.grid.x0 === x0 && was.grid.z0 === z0 &&
        was.floor === (Number(block.floor_m) || 0)) {
      patch({ at: block.at, box: [0, 0, nx, nz], heights_b64: block.heights_b64, ground_b64: block.ground_b64,
              runs_b64: block.runs_b64 });
      return was;
    }
    if (was) remove(was);
    const grid = { nx, nz, dx, x0, z0, surface: block.surface || "columns" };
    const count = nx * nz, floor = Number(block.floor_m) || 0;
    const region = {
      key, at: block.at, grid, floor,
      heights: new Float32Array(bytesOf(block.heights_b64).buffer),
      surfaces: bytesOf(block.ground_b64),
      colors: new Float32Array(3 * count),
      faceChunks: new Map(), dirty: new Set(),
    };
    region.runs = takeRuns(bytesOf(block.runs_b64), count, floor);
    for (let c = 0; c < count; ++c) paint(region, c);
    const top = columnTopData(grid, region.heights, region.colors);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(top.positions, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(top.colors, 3));
    geometry.setIndex(new THREE.BufferAttribute(top.indices, 1));
    geometry.computeVertexNormals();
    region.materialCells = terrainMaterial(grid, region.colors, c => kindOf(region, c), () => true);
    region.mesh = new THREE.Mesh(geometry, region.materialCells.material);
    region.mesh.castShadow = region.mesh.receiveShadow = true;
    region.mesh.userData.groundRegion = key;
    scene.add(region.mesh);
    for (const id of columnChunkIds(grid, [0, 0, nx, nz], 0)) region.dirty.add(id);
    regions.set(key, region);
    if (trace.length < 32) trace.push({ added: key, columns: count, ms: +(performance.now() - started).toFixed(2) });
    return region;
  }

  // A rectangle of one, as the valley's patchTerrain.
  function patch(change) {
    const region = regions.get(`${change.at[0]},${change.at[1]}`);
    if (!region) return false;
    const [i0, j0, ni, nj] = change.box, g = region.grid;
    const heights = new Float32Array(bytesOf(change.heights_b64).buffer);
    const surfaces = bytesOf(change.ground_b64);
    const raw = change.runs_b64 ? bytesOf(change.runs_b64) : null;
    const pos = region.mesh.geometry.attributes.position, col = region.mesh.geometry.attributes.color;
    const runs = () => region.runs;
    let at = 0, changed = 0;
    for (let j = 0; j < nj; ++j)
      for (let i = 0; i < ni; ++i) {
        const c = (j0 + j) * g.nx + (i0 + i);
        // Only what is different is drawn again: a whole region sent again
        // because something somewhere changed redraws nothing of it.
        let different = region.heights[c] !== heights[j * ni + i] || region.surfaces[c] !== surfaces[j * ni + i];
        if (raw) {
          const n = raw[at];
          if (n > runs().stride) growRuns(region, n);
          const r = runs();
          different ||= n !== r.count[c];
          for (let k = 0; k < n && !different; k++) {
            const b = at + 1 + 3 * k;
            different = r.kind[c * r.stride + k] !== raw[b] ||
              r.top[c * r.stride + k] !== Math.fround(region.floor + (raw[b + 1] | raw[b + 2] << 8) / 1000);
          }
          at = decodeRuns(raw, at, r, c, region.floor);
        }
        region.heights[c] = heights[j * ni + i];
        region.surfaces[c] = surfaces[j * ni + i];
        if (!different) continue;
        changed++;
        paint(region, c);
        for (let v = 0; v < 4; v++) {
          pos.array[12 * c + 3 * v + 1] = region.heights[c];
          col.array.set(region.colors.subarray(3 * c, 3 * c + 3), 12 * c + 3 * v);
        }
        region.materialCells.update(c);
        for (const id of columnChunkIds(g, [i0 + i, j0 + j, 1, 1], 1)) region.dirty.add(id);
      }
    if (!changed) return true;
    pos.needsUpdate = col.needsUpdate = true;
    region.mesh.geometry.computeBoundingSphere();
    return true;
  }

  // The faces of every chunk whose columns changed: a few a frame at most, so
  // a region arriving does not stall the page that draws it.
  function buildFaces(most = 4) {
    if (!faceMaterial) faceMaterial = dressMaterial(new THREE.MeshStandardMaterial({
      vertexColors: true, roughness: .97, metalness: 0, side: THREE.DoubleSide }), "ground");
    let built = 0;
    for (const region of regions.values()) {
      for (const id of [...region.dirty]) {
        if (built >= most) return;
        region.dirty.delete(id);
        built++;
        const was = region.faceChunks.get(id);
        if (was) { scene.remove(was); was.geometry.dispose(); region.faceChunks.delete(id); }
        const points = [], colours = [];
        walkColumnFaces(region.grid, region.heights, region.runs, region.floor, face => {
          if (face.top) return;
          const colour = COLOURS[face.kind] || COLOURS[0];
          for (const k of [0, 1, 2, 0, 2, 3]) { points.push(...face.points[k]); colours.push(colour.r, colour.g, colour.b); }
        }, columnChunkBox(region.grid, id));
        if (!points.length) continue;
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(points), 3));
        geometry.setAttribute("color", new THREE.BufferAttribute(new Float32Array(colours), 3));
        geometry.computeVertexNormals();
        geometry.computeBoundingSphere();
        const mesh = new THREE.Mesh(geometry, faceMaterial);
        mesh.receiveShadow = true;
        region.faceChunks.set(id, mesh);
        scene.add(mesh);
      }
    }
  }

  function clear() {
    for (const region of regions.values()) remove(region);
    regions.clear();
  }

  // The region holding a point, and the column of it there.
  function columnAt(x, z) {
    for (const region of regions.values()) {
      const c = terrainCellAt(x, z, region.grid);
      if (c >= 0) return { region, c };
    }
    return null;
  }

  // The ground under a point: a column's flat top, as the collider has it.
  function heightAt(x, z) {
    const at = columnAt(x, z);
    return at ? at.region.heights[at.c] : null;
  }

  // The top of the highest solid run at or below `y`: inside a working, its
  // floor, as world.js's standingOn says for the valley.
  function standingOn(x, z, y) {
    const at = columnAt(x, z);
    if (!at) return null;
    const { region, c } = at, runs = region.runs;
    for (let k = runs.count[c] - 1; k >= 0; --k) {
      const n = c * runs.stride + k;
      if (runs.kind[n] === RUN_VOID) continue;
      if (runs.top[n] <= y + 0.05) return runs.top[n];
    }
    return region.heights[c];
  }

  // How far the ground reaches, valley and regions together.
  function extent(valley) {
    const box = valley ? { x0: valley.x0 - valley.dx / 2, z0: valley.z0 - valley.dx / 2,
                           x1: valley.x0 + (valley.nx - .5) * valley.dx, z1: valley.z0 + (valley.nz - .5) * valley.dx }
                       : { x0: Infinity, z0: Infinity, x1: -Infinity, z1: -Infinity };
    for (const { grid: g } of regions.values()) {
      box.x0 = Math.min(box.x0, g.x0 - g.dx / 2); box.z0 = Math.min(box.z0, g.z0 - g.dx / 2);
      box.x1 = Math.max(box.x1, g.x0 + (g.nx - .5) * g.dx); box.z1 = Math.max(box.z1, g.z0 + (g.nz - .5) * g.dx);
    }
    return box;
  }

  // Every region in a whole terrain block: drawn where new, drawn again where
  // the engine's is not what is drawn, and let go where the engine has none.
  function refresh(blocks) {
    const keep = new Set();
    for (const block of blocks || []) {
      const key = `${block.at[0]},${block.at[1]}`;
      keep.add(key);
      const was = regions.get(key);
      if (!was) { add(block); continue; }
      patch({ at: block.at, box: [0, 0, block.grid.nx, block.grid.nz], heights_b64: block.heights_b64,
              ground_b64: block.ground_b64, runs_b64: block.runs_b64 });
    }
    for (const [key, region] of [...regions]) if (!keep.has(key)) { remove(region); regions.delete(key); }
  }

  return { regions, add, patch, refresh, buildFaces, clear, heightAt, standingOn, extent, columnAt, trace,
           get count() { return regions.size; },
           get dirty() { for (const r of regions.values()) if (r.dirty.size) return true; return false; } };
}
