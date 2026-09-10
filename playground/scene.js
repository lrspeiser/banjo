import * as THREE from "/vendor/three.module.js";
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const dynamicTimeToleranceS = 1e-10;
const color = (v) =>
  Number.isInteger(v)
    ? new THREE.Color(
        ((v >>> 24) & 255) / 255,
        ((v >>> 16) & 255) / 255,
        ((v >>> 8) & 255) / 255,
      )
    : Array.isArray(v)
      ? new THREE.Color(
          ...v.slice(0, 3).map((x) => x / (v.some((n) => n > 1) ? 255 : 1)),
        )
      : new THREE.Color(0x63d6a6);
function create(container, hooks = {}) {
  let renderer,
    camera,
    scene,
    solids,
    edges,
    references,
    supports,
    bonds,
    frames = [],
    bodies = [],
    continuum = false,
    dynamic = false,
    thermal = false,
    thermalRange = null,
    xray = false,
    fitBounds = null,
    groundY = 0,
    frame = 0,
    playing = false,
    speed = 1,
    magnification = 1,
    last = 0,
    elapsed = 0,
    pointer = null,
    dead = false,
    target = new THREE.Vector3(),
    radius = 5,
    azimuth = 0.75,
    polar = 1.05;
  // Moving objects by hand. The stage is a recording, so a grab cannot fall
  // where it stands: dragging repositions the object and the app re-runs the
  // engine from there, which is what makes the fall real physics rather than an
  // animation. Everything here is the reposition half.
  let grabMode = false;
  let grab = null;
  const ray = new THREE.Raycaster(),
    mouse = new THREE.Vector2();
  ray.params.Line.threshold = 0.004;
  try {
    // preserveDrawingBuffer keeps the rendered frame readable after the
    // compositor has taken it, which is what makes captureFrame() below
    // possible. A published result that cannot be shown outside the tab it
    // was rendered in is not much of a publishing platform.
    renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  } catch (e) {
    throw new Error(`WebGL could not start: ${e.message}`);
  }
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setClearColor(0x091013);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  container.replaceChildren(renderer.domElement);
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(42, 1, 0.0001, 1e4);
  scene.add(new THREE.HemisphereLight(0xdfffee, 0x172128, 2.1));
  const sun = new THREE.DirectionalLight(0xffffff, 2.2);
  sun.position.set(4, 8, 5);
  scene.add(sun);
  const grid = new THREE.GridHelper(12, 24, 0x36514d, 0x1b302f);
  grid.material.transparent = true;
  grid.material.opacity = 0.35;
  scene.add(grid);
  solids = new THREE.Group();
  edges = new THREE.Group();
  references = new THREE.Group();
  supports = new THREE.Group();
  bonds = new THREE.Group();
  scene.add(references, supports, solids, edges, bonds);
  const dispose = (g) => {
    while (g.children.length) {
      const o = g.children.pop();
      o.traverse((n) => {
        n.geometry?.dispose();
        if (Array.isArray(n.material)) n.material.forEach((m) => m.dispose());
        else n.material?.dispose();
      });
    }
  };
  const cameraUpdate = () => {
    camera.position.set(
      target.x + radius * Math.sin(polar) * Math.sin(azimuth),
      target.y + radius * Math.cos(polar),
      target.z + radius * Math.sin(polar) * Math.cos(azimuth),
    );
    camera.lookAt(target);
  };
  function fit() {
    const box = fitBounds?.clone() || new THREE.Box3().setFromObject(solids);
    if (box.isEmpty()) return;
    box.getCenter(target);
    const d = box.getSize(new THREE.Vector3()).length();
    radius = Math.max(d * 1.35, 0.03);
    camera.far = Math.max(1e4, radius * 20);
    camera.updateProjectionMatrix();
    grid.scale.setScalar(Math.max(d / 12, 0.005));
    grid.position.y = continuum || dynamic ? box.min.y : groundY;
    cameraUpdate();
  }
  function primitive(b) {
    let g;
    if (b.shape === "sphere")
      g = new THREE.SphereGeometry((b.dimensions_m?.[0] || 0.1) / 2, 18, 12);
    else if (b.shape === "mesh" && b.local_triangles_m) {
      g = new THREE.BufferGeometry();
      g.setAttribute(
        "position",
        new THREE.Float32BufferAttribute(b.local_triangles_m.flat(2), 3),
      );
      g.computeVertexNormals();
    } else g = new THREE.BoxGeometry(...(b.dimensions_m || [0.1, 0.1, 0.1]));
    const m = new THREE.Mesh(
      g,
      new THREE.MeshStandardMaterial({
        color: color(b.color_rgba),
        roughness: 0.55,
        metalness: 0.08,
        transparent: true,
      }),
    );
    m.userData = {
      kind: "constituent cell",
      id: b.id,
      object_id: b.object_id,
      element_id: b.element_id,
      material_id: b.material_id,
    };
    return m;
  }
  function wire(mesh, data) {
    const w = new THREE.LineSegments(
      new THREE.EdgesGeometry(mesh.geometry, 20),
      new THREE.LineBasicMaterial({
        color: 0xd8eee7,
        transparent: true,
        opacity: 0.55,
      }),
    );
    w.userData = {
      kind: "cell structure",
      id: data.id,
      material_id: data.material_id,
    };
    edges.add(w);
    return w;
  }
  function triangleLines(ts) {
    const a = [];
    (ts || []).forEach((t) => {
      if (Array.isArray(t?.[0]))
        [
          [0, 1],
          [1, 2],
          [2, 0],
        ].forEach(([i, j]) => a.push(...t[i], ...t[j]));
    });
    if (!a.length) return;
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(a, 3));
    const l = new THREE.LineSegments(
      g,
      new THREE.LineBasicMaterial({
        color: 0x8fa19f,
        transparent: true,
        opacity: 0.65,
      }),
    );
    l.userData = { kind: "support boundary" };
    supports.add(l);
  }
  // Every drawn piece of one authored object. A body is drawn as many cells or
  // as one primitive, and they all carry the name the request gave it.
  function partsOf(name) {
    return bodies.filter((b) => String(b.material_id) === String(name));
  }

  // Where a grab should move things. Sideways follows the camera's own right
  // vector flattened onto the ground, so a drag goes where it looks like it
  // goes from any angle; up and down is world up, because "lift it" has only
  // one meaning.
  function dragBasis() {
    const right = new THREE.Vector3();
    camera.getWorldDirection(right);
    right.y = 0;
    if (right.lengthSq() < 1e-9) right.set(1, 0, 0);
    right.normalize().cross(new THREE.Vector3(0, 1, 0)).normalize();
    return { right, up: new THREE.Vector3(0, 1, 0) };
  }

  function beginGrab(clientX, clientY) {
    const r = canvas.getBoundingClientRect();
    mouse.set(((clientX - r.left) / r.width) * 2 - 1,
              (-(clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(mouse, camera);
    const hit = ray.intersectObjects([solids], true)[0];
    const name = hit?.object?.userData?.material_id;
    if (!name) return false;
    const parts = partsOf(name);
    if (!parts.length) return false;
    const centre = new THREE.Vector3();
    parts.forEach((b) => centre.add(b.mesh.position));
    centre.multiplyScalar(1 / parts.length);
    // The distance from the camera decides how far a pixel of drag moves the
    // object, so it tracks the pointer instead of crawling or bolting away.
    const scale = camera.position.distanceTo(centre) * 0.0016;
    grab = { name, parts, x: clientX, y: clientY, basis: dragBasis(), scale,
             moved: new THREE.Vector3(), start: centre.clone() };
    // A recording that keeps playing would fight the pointer for the object.
    setPlaying(false);
    parts.forEach((b) => { b.mesh.material.emissive?.setHex(0x224433); });
    hooks.onGrab?.({ name, held: true, moved_m: [0, 0, 0] });
    return true;
  }

  function moveGrab(clientX, clientY) {
    if (!grab) return;
    const dx = (clientX - grab.x) * grab.scale;
    const dy = -(clientY - grab.y) * grab.scale;
    const next = grab.basis.right.clone().multiplyScalar(dx)
      .add(grab.basis.up.clone().multiplyScalar(dy));
    const step = next.clone().sub(grab.moved);
    grab.parts.forEach((b) => {
      b.mesh.position.add(step);
      if (b.edge) b.edge.position.copy(b.mesh.position);
    });
    grab.moved.copy(next);
    hooks.onGrab?.({ name: grab.name, held: true,
                     moved_m: [grab.moved.x, grab.moved.y, grab.moved.z] });
  }

  function endGrab() {
    if (!grab) return;
    grab.parts.forEach((b) => { b.mesh.material.emissive?.setHex(0x000000); });
    const moved = grab.moved;
    const name = grab.name;
    const to = grab.start.clone().add(moved);
    grab = null;
    // A drag of less than a millimetre is a click, not a move.
    if (moved.length() < 0.001) { hooks.onGrab?.({ name, held: false, moved_m: [0, 0, 0] }); return; }
    hooks.onGrab?.({ name, held: false, moved_m: [moved.x, moved.y, moved.z] });
    hooks.onRelease?.({ name, moved_m: [moved.x, moved.y, moved.z],
                        to_m: [to.x, to.y, to.z] });
  }

  function buildNetwork(d) {
    continuum = false;
    const ys = (d.supports || []).flat(2).filter((_, i) => i % 3 === 1);
    groundY = ys.length ? Math.min(...ys) : 0;
    bodies = d.bodies || [];
    bodies.forEach((b) => {
      b.mesh = primitive(b);
      solids.add(b.mesh);
      b.edge = wire(b.mesh, b);
    });
    triangleLines(d.supports);
    frames = d.frames || [];
  }
  function internalLines(ps, es, offset, material) {
    const pairs = [];
    (es || []).forEach((e) => {
      for (let i = 0; i < e.length; i++)
        for (let j = i + 1; j < e.length; j++)
          if (ps[e[i]] && ps[e[j]]) pairs.push([e[i], e[j]]);
    });
    if (!pairs.length) return null;
    const g = new THREE.BufferGeometry();
    g.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(
        pairs.flatMap(([i, j]) => [...ps[i], ...ps[j]]),
        3,
      ),
    );
    const line = new THREE.LineSegments(
      g,
      new THREE.LineBasicMaterial({
        color: 0xd8eee7,
        transparent: true,
        opacity: 0.22,
      }),
    );
    line.position.copy(offset);
    line.userData = {
      kind: "deformed element structure",
      material_id: material,
    };
    line.onBeforeRender = () => {
      const b = bodies.find((x) => x.material_id === material),
        s = b?.frames[Math.min(frame, b.frames.length - 1)],
        ds = s?.displacements_m || [],
        a = line.geometry.attributes.position;
      let n = 0;
      pairs.forEach(([i, j]) =>
        [i, j].forEach((k) => {
          const p = ps[k],
            d = ds[k] || [0, 0, 0];
          a.setXYZ(
            n++,
            p[0] + d[0] * magnification,
            p[1] + d[1] * magnification,
            p[2] + d[2] * magnification,
          );
        }),
      );
      a.needsUpdate = true;
    };
    edges.add(line);
    return { line, pairs };
  }
  function buildContinuum(d) {
    continuum = true;
    const sets = Array.isArray(d.cases)
        ? d.cases
        : Array.isArray(d.materials)
          ? d.materials
          : [d],
      palette = [0x62d6a5, 0xe7bf74, 0x89bff0];
    let count = 0;
    sets.forEach((s, i) => {
      const ps = s.reference_positions_m || d.reference_positions_m || [],
        tris = s.boundary_triangles || d.boundary_triangles || [],
        offset = new THREE.Vector3(i * 0.06, 0, 0),
        g = new THREE.BufferGeometry();
      g.setAttribute(
        "position",
        new THREE.Float32BufferAttribute(ps.flat(), 3),
      );
      if (tris.length) g.setIndex(tris.flat());
      g.computeVertexNormals();
      const material = s.material_id || `material-${i + 1}`,
        m = new THREE.Mesh(
          g,
          new THREE.MeshStandardMaterial({
            color: palette[i % 3],
            side: THREE.DoubleSide,
            roughness: 0.7,
            transparent: true,
          }),
        );
      m.position.copy(offset);
      m.userData = {
        kind: "material column",
        material_id: material,
        status: s.status,
      };
      solids.add(m);
      const ref = new THREE.LineSegments(
        new THREE.WireframeGeometry(g.clone()),
        new THREE.LineBasicMaterial({
          color: 0xa8bbb7,
          transparent: true,
          opacity: 0.32,
        }),
      );
      ref.position.copy(offset);
      ref.userData = { kind: "reference shape", material_id: material };
      references.add(ref);
      const structure = internalLines(
        ps,
        s.elements || d.elements,
        offset,
        material,
      );
      const accepted = (s.frames || d.frames || []).filter(
        (f) => f?.accepted !== false,
      );
      count = Math.max(count, accepted.length);
      bodies.push({
        mesh: m,
        structure,
        positions: ps,
        frames: accepted,
        status: s.status,
        material_id: material,
      });
    });
    frames = Array.from({ length: count }, (_, i) => {
      const samples = bodies
          .map((b) => b.frames[Math.min(i, b.frames.length - 1)])
          .filter(Boolean),
        r = samples[0] || {};
      return {
        phase: r.phase,
        load_fraction: r.load_fraction,
        load_frame: i + 1,
        material_states: bodies.map((b, j) => ({
          material_id: b.material_id,
          status: b.status,
          phase: samples[j]?.phase,
          load_fraction: samples[j]?.load_fraction,
          maximum_equivalent_plastic_strain:
            samples[j]?.maximum_equivalent_plastic_strain,
          maximum_displacement_m: samples[j]?.maximum_displacement_m,
        })),
      };
    });
  }
  function dynamicEdges(positions, tetrahedra, offset, materialId) {
    const pairs = [],
      seen = new Set();
    for (const tetrahedron of tetrahedra)
      for (let i = 0; i < 4; i++)
        for (let j = i + 1; j < 4; j++) {
          const pair = [tetrahedron[i], tetrahedron[j]].sort((a, b) => a - b),
            key = pair.join(":");
          if (!seen.has(key)) {
            seen.add(key);
            pairs.push(pair);
          }
        }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(
        pairs.flatMap(([i, j]) => [...positions[i], ...positions[j]]),
        3,
      ),
    );
    const line = new THREE.LineSegments(
      geometry,
      new THREE.LineBasicMaterial({
        color: 0xd8eee7,
        transparent: true,
        opacity: 0.24,
      }),
    );
    line.position.copy(offset);
    line.userData = {
      kind: "tetrahedral edge structure",
      material_id: materialId,
    };
    edges.add(line);
    return { line, pairs };
  }
  function validateDynamic(d) {
    const vector = (v) =>
      Array.isArray(v) && v.length === 3 && v.every(Number.isFinite);
    if (
      d.physical_response_validated !== false ||
      !["complete", "solver_limit"].includes(d.status) ||
      !Array.isArray(d.cases) ||
      !d.cases.length
    )
      throw new Error("Dynamic playback metadata is invalid.");
    for (const c of d.cases) {
      const m = c.mesh,
        f = c.frames;
      if (
        !c.material_id ||
        !["complete", "solver_limit"].includes(c.status) ||
        !m ||
        !Array.isArray(m.reference_positions_m) ||
        !m.reference_positions_m.length ||
        !m.reference_positions_m.every(vector) ||
        !Array.isArray(m.tetrahedra) ||
        !Array.isArray(m.boundary_triangles) ||
        !m.boundary_triangles.length ||
        !Array.isArray(f) ||
        !f.length ||
        !Number.isFinite(c.sphere_radius_m) ||
        c.sphere_radius_m <= 0 ||
        !Number.isFinite(c.sphere_mass_kg) ||
        c.sphere_mass_kg <= 0
      )
        throw new Error("Dynamic playback case is invalid.");
      let time = -Infinity;
      for (const x of f) {
        if (
          !Number.isFinite(x.time_s) ||
          x.time_s <= time ||
          !Array.isArray(x.positions_m) ||
          x.positions_m.length !== m.reference_positions_m.length ||
          !x.positions_m.every(vector) ||
          !vector(x.sphere_center_m) ||
          !vector(x.sphere_velocity_m_s) ||
          !Number.isFinite(x.maximum_equivalent_plastic_strain) ||
          !Number.isFinite(x.plastic_dissipation_j)
        )
          throw new Error(
            "Dynamic playback frames must contain finite monotonic accepted states.",
          );
        time = x.time_s;
        if (x.boundary_triangles !== undefined) {
          if (!Array.isArray(x.boundary_triangles) || x.boundary_triangles.length > 65536)
            throw new Error("Dynamic fracture surface count is invalid.");
          for (const face of x.boundary_triangles)
            if (!Array.isArray(face) || face.length !== 3 || new Set(face).size !== 3 ||
                face.some(index => !Number.isInteger(index) || index < 0 || index >= m.reference_positions_m.length))
              throw new Error("Dynamic fracture surface topology is invalid.");
        }
        if (x.component_by_tetrahedron !== undefined &&
            (!Array.isArray(x.component_by_tetrahedron) ||
             x.component_by_tetrahedron.length !== m.tetrahedra.length ||
             x.component_by_tetrahedron.some(id => !Number.isInteger(id) || id < 0 || id >= m.tetrahedra.length) ||
             new Set(x.component_by_tetrahedron).size !== x.components))
          throw new Error("Dynamic fracture components are invalid.");
        for (const field of ["maximum_damage", "fracture_dissipation_j", "fully_separated_facets", "components"])
          if (x[field] !== undefined && (!Number.isFinite(x[field]) || x[field] < 0))
            throw new Error("Dynamic fracture evidence is invalid.");
      }
      for (const [list, size] of [
        [m.tetrahedra, 4],
        [m.boundary_triangles, 3],
      ])
        for (const cell of list) {
          if (!Array.isArray(cell) || cell.length !== size)
            throw new Error("Dynamic playback mesh topology is invalid.");
          for (const index of cell)
            if (
              !Number.isInteger(index) ||
              index < 0 ||
              index >= m.reference_positions_m.length
            )
              throw new Error("Dynamic playback mesh index is invalid.");
        }
    }
  }
  function buildDynamic(d) {
    validateDynamic(d);
    dynamic = true;
    continuum = false;
    magnification = 1;
    fitBounds = new THREE.Box3();
    const palette = [0x62d6a5, 0xe7bf74, 0x89bff0];
    let cursor = 0;
    for (const [i, c] of d.cases.entries()) {
      const ps = c.mesh.reference_positions_m,
        tris = c.mesh.boundary_triangles;
      let min = Infinity,
        max = -Infinity;
      for (const p of ps) {
        min = Math.min(min, p[0] - c.sphere_radius_m);
        max = Math.max(max, p[0] + c.sphere_radius_m);
      }
      for (const f of c.frames) {
        min = Math.min(min, f.sphere_center_m[0] - c.sphere_radius_m);
        max = Math.max(max, f.sphere_center_m[0] + c.sphere_radius_m);
      }
      const width = Math.max(max - min, 1e-4),
        offset = new THREE.Vector3(cursor - min, 0, 0);
      cursor += width + Math.max(width * 0.35, c.sphere_radius_m * 3);
      const g = new THREE.BufferGeometry();
      g.setAttribute(
        "position",
        new THREE.Float32BufferAttribute(ps.flat(), 3),
      );
      g.setIndex(tris.flat());
      const componentColors = c.frames.some(f => f.component_by_tetrahedron);
      if (componentColors)
        g.setAttribute("color", new THREE.Float32BufferAttribute(new Float32Array(ps.length * 3).fill(1), 3));
      g.computeVertexNormals();
      const mat = new THREE.MeshStandardMaterial({
        color: componentColors ? 0xffffff : palette[i % palette.length],
        vertexColors: componentColors,
        side: THREE.DoubleSide,
        roughness: 0.68,
        transparent: true,
      });
      const mesh = new THREE.Mesh(g, mat);
      mesh.position.copy(offset);
      solids.add(mesh);
      const ref = new THREE.LineSegments(
        new THREE.WireframeGeometry(g.clone()),
        new THREE.LineBasicMaterial({
          color: 0xa8bbb7,
          transparent: true,
          opacity: 0.3,
        }),
      );
      ref.position.copy(offset);
      ref.userData = {
        kind: "undeformed reference",
        material_id: c.material_id,
      };
      references.add(ref);
      const structure = dynamicEdges(
        ps,
        c.mesh.tetrahedra,
        offset,
        c.material_id,
      );
      const sphere = new THREE.Mesh(
        new THREE.SphereGeometry(c.sphere_radius_m, 24, 16),
        new THREE.MeshStandardMaterial({
          color: 0xf2f6f4,
          roughness: 0.28,
          metalness: 0.05,
          transparent: true,
        }),
      );
      solids.add(sphere);
      bodies.push({
        dynamic: true,
        mesh,
        sphere,
        structure,
        offset,
        frames: c.frames,
        status: c.status,
        material_id: c.material_id,
        name: c.material?.name || c.material_id,
        reference: ps,
        tetrahedra: c.mesh.tetrahedra,
        boundaryTriangles: tris,
        summary: c.summary,
        error: c.error,
      });
      for (const p of ps)
        fitBounds.expandByPoint(new THREE.Vector3(...p).add(offset));
      for (const f of c.frames) {
        for (const p of f.positions_m)
          fitBounds.expandByPoint(new THREE.Vector3(...p).add(offset));
      }
      for (const f of c.frames) {
        const q = new THREE.Vector3(...f.sphere_center_m).add(offset),
          r = c.sphere_radius_m;
        fitBounds.expandByPoint(new THREE.Vector3(q.x - r, q.y - r, q.z - r));
        fitBounds.expandByPoint(new THREE.Vector3(q.x + r, q.y + r, q.z + r));
      }
    }
    const sampledTimes = [
      ...new Set(bodies.flatMap((b) => b.frames.map((f) => f.time_s))),
    ].sort((a, b) => a - b);
    const times = sampledTimes.reduce((merged, time) => {
      if (!merged.length || time - merged.at(-1) > dynamicTimeToleranceS)
        merged.push(time);
      return merged;
    }, []);
    frames = times.map((time_s) => ({
      time_s,
      material_states: bodies.map((b) => {
        let i = 0;
        while (
          i + 1 < b.frames.length &&
          b.frames[i + 1].time_s <= time_s + dynamicTimeToleranceS
        )
          i++;
        const f = b.frames[i],
          stopped =
            b.status === "solver_limit" &&
            time_s > b.frames.at(-1).time_s + dynamicTimeToleranceS;
        return {
          material_id: b.material_id,
          status: b.status,
          current_time_s: f.time_s,
          stopped,
          maximum_equivalent_plastic_strain:
            f.maximum_equivalent_plastic_strain,
          plastic_dissipation_j: f.plastic_dissipation_j,
          ...(f.components !== undefined ? {components: f.components,
            fully_separated_facets: f.fully_separated_facets,
            fracture_dissipation_j: f.fracture_dissipation_j} : {}),
        };
      }),
    }));
  }
  function validateThermal(d) {
    const finite = (v) => typeof v === "number" && Number.isFinite(v);
    const triple = (v, integer = false) => Array.isArray(v) && v.length === 3 &&
      v.every((x) => finite(x) && (!integer || Number.isInteger(x)));
    if (d?.schema !== "banjo.thermal-experiment-response.v1" ||
        !["complete", "solver_limit"].includes(d.status) || !d.request ||
        d.request.schema !== "banjo.thermal-experiment-request.v1" ||
        !finite(d.request.voxel_size_m) || d.request.voxel_size_m <= 0 ||
        !Array.isArray(d.request.cells) || !d.request.cells.length ||
        d.request.cells.length > 16 || !Array.isArray(d.frames) || !d.frames.length ||
        d.frames.length > 1024)
      throw new Error("Thermal playback metadata is invalid.");
    const addresses = new Set();
    for (const cell of d.request.cells) {
      if (!triple(cell?.chunk, true) || !triple(cell?.local, true) ||
          cell.local.some((x) => x < 0 || x > 15) ||
          !Number.isInteger(cell.material) || !finite(cell.temperature_k))
        throw new Error("Thermal authored cell geometry is invalid.");
      const key = `${cell.chunk.join(":")}/${cell.local.join(":")}`;
      if (addresses.has(key)) throw new Error("Thermal authored cells are duplicated.");
      addresses.add(key);
    }
    let previous = -Infinity;
    const requiredLedger = ["products_kg", "chemical_energy_j", "thermal_enthalpy_j",
      "external_work_j", "reaction_heat_j", "combined_energy_residual_j",
      "mass_kg", "mass_residual_kg"];
    for (const sample of d.frames) {
      if (!finite(sample?.time_s) || sample.time_s <= previous ||
          !Array.isArray(sample.cells) || sample.cells.length !== addresses.size ||
          !sample.ledger || requiredLedger.some((key) => !finite(sample.ledger[key])))
        throw new Error("Thermal playback frames or ledgers are invalid.");
      previous = sample.time_s;
      const seen = new Set();
      for (const cell of sample.cells) {
        const key = triple(cell?.chunk, true) && triple(cell?.local, true)
          ? `${cell.chunk.join(":")}/${cell.local.join(":")}` : "";
        if (!addresses.has(key) || seen.has(key) || !Number.isInteger(cell.material) ||
            !finite(cell.temperature_k) || cell.temperature_k < 0 ||
            !finite(cell.fuel_kg) || cell.fuel_kg < 0 ||
            !finite(cell.oxygen_kg) || cell.oxygen_kg < 0 ||
            !finite(cell.liquid_fraction) || cell.liquid_fraction < 0 ||
            cell.liquid_fraction > 1 || typeof cell.phase_change !== "boolean")
          throw new Error("Thermal playback cell state is invalid.");
        seen.add(key);
      }
    }
    if (!finite(d.completed_time_s) || Math.abs(previous - d.completed_time_s) > 1e-9 ||
        !finite(d.requested_horizon_s) || !finite(d.remaining_duration_s) ||
        Math.abs(d.completed_time_s + d.remaining_duration_s - d.requested_horizon_s) > 1e-9 ||
        d.final_ledger !== d.frames.at(-1).ledger &&
          JSON.stringify(d.final_ledger) !== JSON.stringify(d.frames.at(-1).ledger))
      throw new Error("Thermal playback completion accounting is invalid.");
  }
  function thermalColor(value, low, high) {
    const fraction = high > low ? clamp((value - low) / (high - low), 0, 1) : 0.5;
    return new THREE.Color().setHSL(0.64 - fraction * 0.62, 0.86, 0.54);
  }
  function buildThermal(d) {
    validateThermal(d);
    thermal = true;
    continuum = false;
    dynamic = false;
    magnification = 1;
    frames = d.frames;
    const size = d.request.voxel_size_m;
    const temperatures = frames.flatMap((sample) => sample.cells.map((cell) => cell.temperature_k));
    thermalRange = {minimum_temperature_k: Math.min(...temperatures),
                    maximum_temperature_k: Math.max(...temperatures)};
    const centers = d.request.cells.map((cell) => cell.chunk.map(
      (chunk, axis) => (chunk * 16 + cell.local[axis] + 0.5) * size));
    const origin = centers.reduce((sum, p) => sum.map((x, i) => x + p[i]), [0, 0, 0])
      .map((x) => x / centers.length);
    for (const [index, authored] of d.request.cells.entries()) {
      const mesh = new THREE.Mesh(
        new THREE.BoxGeometry(size * 0.94, size * 0.94, size * 0.94),
        new THREE.MeshStandardMaterial({roughness: 0.72, metalness: 0,
          color: thermalColor(authored.temperature_k,
            thermalRange.minimum_temperature_k, thermalRange.maximum_temperature_k)}));
      mesh.position.fromArray(centers[index].map((x, axis) => x - origin[axis]));
      solids.add(mesh);
      const edge = wire(mesh, {id: index, material_id: authored.material});
      edge.position.copy(mesh.position);
      bodies.push({thermal: true, mesh, edge, key: `${authored.chunk.join(":")}/${authored.local.join(":")}`,
                   authored, worldCenter: centers[index]});
    }
    fitBounds = new THREE.Box3().setFromObject(solids);
  }
  function bondLines(list) {
    dispose(bonds);
    if (!list?.length) return;
    const p = [],
      c = [];
    list.forEach((b) => {
      p.push(...b.a_m, ...b.b_m);
      const x = new THREE.Color(
        b.live === false ? 0xf18b88 : b.damage > 0 ? 0xf6c572 : 0x8de6be,
      );
      c.push(x.r, x.g, x.b, x.r, x.g, x.b);
    });
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(p, 3));
    g.setAttribute("color", new THREE.Float32BufferAttribute(c, 3));
    const l = new THREE.LineSegments(
      g,
      new THREE.LineBasicMaterial({
        vertexColors: true,
        transparent: true,
        opacity: 0.85,
      }),
    );
    l.userData = {
      kind: "bond network",
      bond_count: list.length,
      broken_count: list.filter((b) => b.live === false).length,
      damaged_count: list.filter((b) => b.damage > 0).length,
    };
    bonds.add(l);
  }
  function setPlaying(v) {
    playing = !!v;
    elapsed = 0;
    hooks.onPlayState?.(playing);
    return playing;
  }
  function update(i) {
    frame = clamp(Math.round(i), 0, Math.max(0, frames.length - 1));
    const f = frames[frame] || {};
    if (thermal)
      bodies.forEach((b) => {
        const states = new Map(f.cells.map((cell) =>
          [`${cell.chunk.join(":")}/${cell.local.join(":")}`, cell]));
        const state = states.get(b.key);
        b.mesh.material.color.copy(thermalColor(state.temperature_k,
          thermalRange.minimum_temperature_k, thermalRange.maximum_temperature_k));
        b.mesh.material.opacity = xray ? 0.32 : 1;
        b.mesh.material.transparent = xray;
        const evidence = {kind: "thermal cell", chunk: b.authored.chunk.join(","),
          local: b.authored.local.join(","), material_id: state.material,
          center_m: b.worldCenter.join(","), temperature_k: state.temperature_k,
          fuel_kg: state.fuel_kg, oxygen_kg: state.oxygen_kg,
          products_kg_region: f.ledger.products_kg,
          liquid_fraction: state.liquid_fraction, phase_change: state.phase_change,
          thermal_enthalpy_j_region: f.ledger.thermal_enthalpy_j,
          chemical_energy_j_region: f.ledger.chemical_energy_j,
          external_work_j_region: f.ledger.external_work_j,
          reaction_heat_j_region: f.ledger.reaction_heat_j,
          energy_residual_j_region: f.ledger.combined_energy_residual_j};
        b.mesh.userData = evidence;
        b.edge.userData = evidence;
      });
    else if (dynamic)
      bodies.forEach((b) => {
        let k = 0;
        while (
          k + 1 < b.frames.length &&
          b.frames[k + 1].time_s <= f.time_s + dynamicTimeToleranceS
        )
          k++;
        const s = b.frames[k],
          a = b.mesh.geometry.attributes.position;
        for (let n = 0; n < s.positions_m.length; n++)
          a.setXYZ(n, ...s.positions_m[n]);
        a.needsUpdate = true;
        const surface = s.boundary_triangles || b.boundaryTriangles;
        if (surface !== b.displayedSurface) {
          b.mesh.geometry.setIndex(surface.flat());
          b.displayedSurface = surface;
        }
        if (s.component_by_tetrahedron && s.component_by_tetrahedron !== b.displayedComponents) {
          const colors = b.mesh.geometry.attributes.color;
          for (const [tet, id] of s.component_by_tetrahedron.entries()) {
            const color = new THREE.Color().setHSL((0.43 + id * 0.61803398875) % 1, 0.58, 0.61);
            for (const node of b.tetrahedra[tet]) colors.setXYZ(node, color.r, color.g, color.b);
          }
          colors.needsUpdate = true;
          b.displayedComponents = s.component_by_tetrahedron;
        }
        b.mesh.geometry.computeVertexNormals();
        for (const [j, l] of b.structure.pairs.entries()) {
          const q = s.positions_m[l[0]],
            r = s.positions_m[l[1]],
            p = b.structure.line.geometry.attributes.position;
          p.setXYZ(j * 2, ...q);
          p.setXYZ(j * 2 + 1, ...r);
          p.needsUpdate = true;
        }
        b.sphere.position.fromArray(s.sphere_center_m).add(b.offset);
        const stopped =
          b.status === "solver_limit" &&
          f.time_s > b.frames.at(-1).time_s + dynamicTimeToleranceS;
        const opacity = xray ? 0.32 : stopped ? 0.48 : 1;
        b.mesh.material.opacity = opacity;
        b.sphere.material.opacity = opacity;
        b.mesh.material.transparent = xray || stopped;
        b.sphere.material.transparent = xray || stopped;
        let deformation = 0;
        for (let n = 0; n < s.positions_m.length; n++)
          deformation = Math.max(
            deformation,
            new THREE.Vector3(...s.positions_m[n]).distanceTo(
              new THREE.Vector3(...b.reference[n]),
            ),
          );
        const info = {
          material_id: b.material_id,
          material: b.name,
          status: b.status,
          stopped,
          current_time_s: s.time_s,
          ...(s.components !== undefined ? {components: s.components,
            fully_separated_facets: s.fully_separated_facets,
            maximum_damage: s.maximum_damage,
            fracture_dissipation_j: s.fracture_dissipation_j} : {}),
          deformation: "actual positions",
          maximum_deformation_m: deformation,
          sphere_speed_m_s: new THREE.Vector3(
            ...s.sphere_velocity_m_s,
          ).length(),
          maximum_equivalent_plastic_strain:
            s.maximum_equivalent_plastic_strain,
          plastic_dissipation_j: s.plastic_dissipation_j,
          error: b.error,
        };
        b.mesh.userData = { kind: "dynamic material surface", ...info };
        b.sphere.userData = {
          kind: "sphere",
          radius_m: b.sphere.geometry.parameters.radius,
          ...info,
        };
      });
    else if (continuum)
      bodies.forEach((b) => {
        const s = b.frames[Math.min(frame, b.frames.length - 1)];
        if (!s) return;
        const ds = s.displacements_m || [],
          a = b.mesh.geometry.attributes.position;
        for (let n = 0; n < b.positions.length; n++) {
          const p = b.positions[n],
            q = ds[n] || [0, 0, 0];
          a.setXYZ(
            n,
            p[0] + q[0] * magnification,
            p[1] + q[1] * magnification,
            p[2] + q[2] * magnification,
          );
        }
        a.needsUpdate = true;
        b.mesh.geometry.computeVertexNormals();
        b.mesh.userData = {
          kind: "material column",
          material_id: b.material_id,
          status: b.status,
          phase: s.phase,
          load_fraction: s.load_fraction,
          max_eqp: s.max_eqp ?? s.maxeqp,
        };
      });
    else {
      const poses = new Map((f.poses || []).map((p) => [p.id, p]));
      const held = grab ? new Set(grab.parts.map((b) => b.id)) : null;
      bodies.forEach((b) => {
        // A body being held stays where the hand put it. The recording still
        // says where it was, and writing that back every frame would drag it
        // out of the pointer.
        if (held && held.has(b.id)) return;
        const m = b.mesh,
          p = poses.get(b.id);
        m.visible = !!p;
        b.edge.visible = !!p;
        if (!p) return;
        m.position.fromArray(p.position_m || [0, 0, 0]);
        const q = p.orientation_wxyz || [1, 0, 0, 0];
        m.quaternion.set(q[1], q[2], q[3], q[0]);
        b.edge.position.copy(m.position);
        b.edge.quaternion.copy(m.quaternion);
        m.userData.component_id = p.component_id;
      });
      bondLines(f.bonds || []);
    }
    hooks.onFrame?.({
      index: frame,
      count: frames.length,
      frame: f,
      continuum,
      dynamic,
      thermal,
    });
  }
  function load(d) {
    setPlaying(false);
    [solids, edges, references, supports, bonds].forEach(dispose);
    bodies = [];
    frames = [];
    fitBounds = null;
    frame = 0;
    continuum = false;
    dynamic = false;
    thermal = false;
    thermalRange = null;
    groundY = 0;
    if (d?.schema === "banjo.playback.v1") {
      magnification = 1;
      buildNetwork(d);
    } else if (d?.schema === "banjo.continuum-patch-trial.v1")
      buildContinuum(d);
    else if (d?.schema === "banjo.dynamic-material-playback.v1")
      buildDynamic(d);
    else if (d?.schema === "banjo.thermal-experiment-response.v1")
      buildThermal(d);
    else throw new Error("This result has no supported playback geometry.");
    references.visible = false;
    edges.visible = true;
    bonds.visible = true;
    update(0);
    fit();
    return { continuum, dynamic, thermal, magnification, thermalRange };
  }
  // The fracture is a blink. In a two-second recording the lattice phase is
  // about 26 ms of simulated time in 8 of 88 frames, so at 1x it is over in
  // less than two animation frames and every run looks like the same pile of
  // debris settling. Holding each lattice frame for a fixed spell turns that
  // into about a second of watchable fracture and leaves the rigid settle at
  // real time. It changes nothing about the physics and nothing about what was
  // computed -- only how long a computed frame stays on screen -- and the
  // control that turns it off is next to the scene.
  const kLatticeFrameMs = 110;
  let holdFracture = true;
  // Whether this recording contains a failure at all.
  const anyFailure = () => frames.some((f) => (f.fracture_count || 0) > 0);
  const delay = () => {
    if (continuum) return 150;
    const real =
      Number.isFinite(frames[frame]?.time_s) && frames[frame + 1]?.time_s > frames[frame].time_s
        ? (frames[frame + 1].time_s - frames[frame].time_s) * 1000
        : 120;
    // Only where something actually breaks. A run that breaks no bonds has no
    // fracture to slow down, and holding its opening frames shows a motionless
    // scene for the better part of a second and then snaps to full speed: a
    // bowling ball that "starts slow and then rockets to the pins" is this, not
    // the physics.
    if (!holdFracture || !anyFailure() || frames[frame]?.phase !== "lattice") return real;
    return Math.max(real, kLatticeFrameMs);
  };
  function loop(now) {
    if (dead) return;
    const w = Math.max(1, container.clientWidth),
      h = Math.max(1, container.clientHeight);
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    if (playing && frames.length > 1) {
      elapsed += (now - last) * speed;
      let d = delay();
      while (playing && elapsed >= d) {
        elapsed -= d;
        if (frame >= frames.length - 1) {
          setPlaying(false);
          break;
        }
        update(frame + 1);
        if (frame >= frames.length - 1) setPlaying(false);
        d = delay();
      }
    }
    if (continuum)
      bodies.forEach((b) => {
        const s = b.frames[Math.min(frame, b.frames.length - 1)];
        if (s)
          b.mesh.userData = {
            kind: "material column",
            material_id: b.material_id,
            status: b.status,
            phase: s.phase,
            load_fraction: s.load_fraction,
            maximum_equivalent_plastic_strain:
              s.maximum_equivalent_plastic_strain,
            maximum_displacement_m: s.maximum_displacement_m,
          };
      });
    last = now;
    cameraUpdate();
    renderer.render(scene, camera);
    requestAnimationFrame(loop);
  }
  const canvas = renderer.domElement;
  canvas.addEventListener("pointerdown", (e) => {
    canvas.setPointerCapture(e.pointerId);
    // In grab mode a drag that starts on an object moves it; a drag that starts
    // on empty space still orbits, so the camera is never taken away.
    if (grabMode && beginGrab(e.clientX, e.clientY)) { pointer = null; return; }
    pointer = { x: e.clientX, y: e.clientY, azimuth, polar, moved: false };
  });
  canvas.addEventListener("pointermove", (e) => {
    if (grab) { moveGrab(e.clientX, e.clientY); return; }
    if (!pointer) return;
    const dx = e.clientX - pointer.x,
      dy = e.clientY - pointer.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) pointer.moved = true;
    azimuth = pointer.azimuth - dx * 0.007;
    polar = clamp(pointer.polar + dy * 0.007, 0.08, Math.PI - 0.08);
  });
  canvas.addEventListener("pointerup", (e) => {
    if (grab) { endGrab(); pointer = null; return; }
    if (pointer && !pointer.moved) {
      const r = canvas.getBoundingClientRect();
      mouse.set(
        ((e.clientX - r.left) / r.width) * 2 - 1,
        (-(e.clientY - r.top) / r.height) * 2 + 1,
      );
      ray.setFromCamera(mouse, camera);
      hooks.onInspect?.(
        ray.intersectObjects(
          [solids, edges, bonds, references, supports],
          true,
        )[0]?.object?.userData || null,
      );
    }
    pointer = null;
  });
  canvas.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      radius = clamp(radius * Math.exp(e.deltaY * 0.001), 0.002, 1e4);
    },
    { passive: false },
  );
  requestAnimationFrame(loop);
  return {
    load,
    // The current frame as a PNG data URL, rendered synchronously at the
    // requested pixel size so a capture does not depend on the pane`s size
    // or on catching an animation frame.
    captureFrame(width, height) {
      const w = Math.max(1, Math.round(width || container.clientWidth || 1200));
      const h = Math.max(1, Math.round(height || container.clientHeight || 800));
      const previous = renderer.getSize(new THREE.Vector2());
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.render(scene, camera);
      const url = renderer.domElement.toDataURL("image/png");
      renderer.setSize(previous.x, previous.y, false);
      camera.aspect = previous.x / Math.max(1, previous.y);
      camera.updateProjectionMatrix();
      return url;
    },
    // Re-frame for the container's current shape without disturbing playback.
    // The stage moves between tabs, and a camera framed for one aspect ratio
    // shows a corner of the scene in the other.
    refit() {
      fit();
    },
    // Let the pointer move objects instead of orbiting the camera. A grab is
    // only a reposition: the fall itself is simulated by re-running the engine
    // from where the object was let go.
    setGrabMode(v) {
      grabMode = v !== false;
      if (!grabMode && grab) endGrab();
      return grabMode;
    },
    get grabbing() {
      return grab != null;
    },
    // Whether lattice frames are held on screen. Off is true elapsed time.
    holdFracture(v) {
      holdFracture = v !== false;
    },
    // How much of this recording is the fracture, so the panel can say whether
    // holding it is doing anything.
    get fractureFrames() {
      // Frames that are actually being held. A run with no failure holds none,
      // so the caption does not claim a slowed strike it is not showing.
      return anyFailure() ? frames.filter((f) => f.phase === "lattice").length : 0;
    },
    // How long the current frame will stay on screen, in milliseconds. The only
    // way to check the hold without waiting on animation frames, which a hidden
    // pane never delivers.
    get frameDelayMs() {
      return delay();
    },
    get framePhase() {
      return frames[frame]?.phase ?? "";
    },
    play: (v) => setPlaying(v ?? !playing),
    reset() {
      setPlaying(false);
      update(0);
      fit();
    },
    step(n) {
      setPlaying(false);
      update(frame + n);
    },
    setFrame(i) {
      setPlaying(false);
      update(i);
    },
    setSpeed(v) {
      speed = clamp(Number(v) || 1, 0.001, 4);
    },
    setMagnification(v) {
      magnification = dynamic ? 1 : clamp(Number(v) || 1, 1, 100);
      update(frame);
    },
    showReference(v) {
      references.visible = !!v;
    },
    showBonds(v) {
      bonds.visible = !!v;
    },
    showComponents(v) {
      edges.visible = !!v;
    },
    setXray(v) {
      xray = !!v;
      update(frame);
      if (!dynamic)
        solids.traverse((o) => {
          if (o.material) {
            o.material.opacity = xray ? 0.32 : 1;
            o.material.transparent = xray;
          }
        });
    },
    get frameCount() {
      return frames.length;
    },
    get frame() {
      return frame;
    },
    dispose() {
      dead = true;
      renderer.dispose();
      [solids, edges, references, supports, bonds].forEach(dispose);
    },
  };
}
window.BanjoScene = { create, THREE_VERSION: THREE.REVISION };
window.dispatchEvent(new Event("banjo-scene-ready"));
