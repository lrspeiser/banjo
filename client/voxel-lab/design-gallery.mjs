import {materialColor, wireRoute} from './machine-view.mjs';

const vector = value => Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
const rows = value => Array.isArray(value) ? value : [];
const identity = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
const apply = (matrix, point) => matrix.map(row => row.reduce((sum, value, i) => sum + value * point[i], 0));
const multiply = (a, b) => a.map(row => b[0].map((_, col) => row.reduce((sum, value, i) => sum + value * b[i][col], 0)));
const add = (a, b) => a.map((value, i) => value + b[i]);
function rotation(degrees) {
  const [x, y, z] = (vector(degrees) ? degrees : [0, 0, 0]).map(value => value * Math.PI / 180);
  const [cx, sx, cy, sy, cz, sz] = [Math.cos(x), Math.sin(x), Math.cos(y), Math.sin(y), Math.cos(z), Math.sin(z)];
  return multiply([[1, 0, 0], [0, cx, -sx], [0, sx, cx]],
    multiply([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]));
}
function hull(points) {
  const sorted = [...new Map(points.map(point => [point.join(','), point])).values()]
    .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (sorted.length < 3) return sorted;
  const cross = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  const half = values => { const out = []; for (const point of values) {
    while (out.length > 1 && cross(out.at(-2), out.at(-1), point) <= 0) out.pop(); out.push(point);
  } return out.slice(0, -1); };
  return [...half(sorted), ...half([...sorted].reverse())];
}

// Static top-view geometry from the saved setup. Unexpanded kits/placements
// are marked at declared anchors; no guessed bodies or simulated state.
export function previewGeometry(draft = {}) {
  const result = [], base = draft?.base || {};
  const wall = base.build_surface?.kind === 'wall';
  const project = point => [point[0], wall ? -point[1] : point[2]];
  const marker = (point, name) => { if (vector(point)) result.push({kind: 'marker', point: project(point), name}); };
  const line = (points, name, color = '#9ac8e4') => {
    if (points.length > 1 && points.every(vector)) result.push({kind: 'line', points: points.map(project), name, color});
  };
  const ground = base.ground;
  if (ground?.kind === 'flume' && Number.isFinite(ground.nx) && ground.nx > 0 && Number.isFinite(ground.cell_m)
      && ground.cell_m > 0 && Number.isFinite(ground.trench_z_m) && Number.isFinite(ground.trench_width_m) && ground.trench_width_m > 0) {
    const half = ground.nx * ground.cell_m / 2;
    for (const side of [-1, 1]) {
      const z = ground.trench_z_m + side * ground.trench_width_m / 2;
      line([[-half, 0, z], [half, 0, z]], 'channel bank', '#718d9b');
    }
  }
  function partGeometry(part, parent = identity, origin = [0, 0, 0], inheritedMaterial) {
    if (!part || !vector(part.at_m)) return;
    const at = add(origin, apply(parent, part.at_m)), matrix = multiply(parent, rotation(part.turn_deg));
    const material = part.material || inheritedMaterial, color = '#' + materialColor(material, part.color_rgba).toString(16).padStart(6, '0');
    if (part.shape === 'compound') {
      for (const sub of rows(part.parts)) partGeometry(sub, matrix, at, material);
      return;
    }
    if (!vector(part.size_m) || !part.size_m.every(value => value > 0)) { marker(at, part.name); return; }
    if (part.shape === 'sphere') {
      result.push({kind: 'circle', point: project(at), radius: part.size_m[0] / 2, name: part.name, color}); return;
    }
    const vertices = [];
    if (part.shape === 'cylinder') {
      for (const y of [-part.size_m[1] / 2, part.size_m[1] / 2]) for (let i = 0; i < 32; i++)
        vertices.push([Math.cos(i * Math.PI / 16) * part.size_m[0] / 2, y, Math.sin(i * Math.PI / 16) * part.size_m[0] / 2]);
    } else if (part.shape === 'box') {
      for (const x of [-.5, .5]) for (const y of [-.5, .5]) for (const z of [-.5, .5])
        vertices.push([x * part.size_m[0], y * part.size_m[1], z * part.size_m[2]]);
    } else { marker(at, part.name); return; }
    const points = hull(vertices.map(vertex => project(add(at, apply(matrix, vertex)))));
    result.push({kind: 'polygon', points, name: part.name, color});
  }
  for (const part of rows(base.parts)) if (!wall || !['workshop backing','workshop clear guard'].includes(part.name)) partGeometry(part);
  for (const kit of rows(base.kits)) {
    if (vector(kit.top_m) && vector(kit.bottom_m)) line([kit.top_m, kit.bottom_m], kit.name);
    else marker([kit.at_m, kit.pivot_m, kit.post_m, kit.centre_m, kit.start_m].find(vector), kit.name);
  }
  for (const joint of rows(base.joints)) if (vector(joint.at_m) && vector(joint.at_b_m))
    line([joint.at_m, joint.at_b_m], joint.name, '#c9b08a');
  const terminals = new Map();
  for (const device of rows(base.electrical?.devices)) for (const [key, at] of Object.entries(device.terminals || {}))
    if (vector(at)) terminals.set(`${device.name}:${key}`, at);
  for (const port of rows(base.electrical?.power_ports)) if (vector(port.at_m)) terminals.set(port.name, port.at_m);
  for (const [i, wire] of [...rows(base.electrical?.wires), ...rows(base.electrical?.power_cables)].entries()) {
    const a = terminals.get(wire.a), b = terminals.get(wire.b);
    if (a && b) line(wireRoute(a, b, i), wire.name, '#ffd16c');
  }
  for (const placement of rows(draft?.placements)) {
    if (vector(placement.at_m)) marker(placement.at_m, placement.piece);
    else if (Number.isFinite(placement.x_m) && Number.isFinite(wall ? placement.height_m : placement.z_m))
      marker([placement.x_m, wall ? placement.height_m : 0, wall ? .3 : placement.z_m], placement.piece);
  }
  return result;
}

export function preview(document, draft) {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.classList.add('design-preview'); svg.setAttribute('viewBox', '0 0 240 112');
  svg.setAttribute('aria-hidden', 'true'); svg.setAttribute('focusable', 'false');
  const geometry = previewGeometry(draft), points = geometry.flatMap(row => row.points || (row.kind === 'circle'
    ? [[row.point[0] - row.radius, row.point[1] - row.radius], [row.point[0] + row.radius, row.point[1] + row.radius]] : [row.point]));
  if (!points.length) {
    const text = document.createElementNS(svg.namespaceURI, 'text'); text.setAttribute('x', '120'); text.setAttribute('y', '60');
    text.setAttribute('text-anchor', 'middle'); text.textContent = rows(draft?.placements).length || draft?.base ? 'Saved setup' : 'Empty design';
    svg.append(text); return svg;
  }
  const min = [0, 1].map(i => Math.min(...points.map(p => p[i]))), max = [0, 1].map(i => Math.max(...points.map(p => p[i])));
  const scale = Math.min(216 / Math.max(.2, max[0] - min[0]), 88 / Math.max(.2, max[1] - min[1]));
  const project = p => [120 + (p[0] - (max[0] + min[0]) / 2) * scale, 56 + (p[1] - (max[1] + min[1]) / 2) * scale];
  for (const row of geometry) {
    const shape = document.createElementNS(svg.namespaceURI, ['circle', 'marker'].includes(row.kind) ? 'circle' : row.kind === 'polygon' ? 'polygon' : 'polyline');
    shape.setAttribute('fill', row.kind === 'line' ? 'none' : row.color || '#8ac9f4');
    shape.setAttribute('stroke', row.kind === 'line' ? row.color : '#d9e8f0'); shape.setAttribute('stroke-width', row.kind === 'line' ? '2' : '1');
    if (row.point) { const [x, y] = project(row.point); shape.setAttribute('cx', String(x)); shape.setAttribute('cy', String(y));
      shape.setAttribute('r', String(row.kind === 'circle' ? row.radius * scale : 3)); }
    else shape.setAttribute('points', row.points.map(project).map(p => p.join(',')).join(' '));
    svg.append(shape);
  }
  return svg;
}

export function renderDesignGallery({box, head, store, templates, wallTemplate, pinballTemplate, openDesign, createDesign}) {
  const document = box.ownerDocument;
  const element = (tag, properties = {}) => Object.assign(document.createElement(tag), properties);
  const gallery = element('section', {className: 'design-gallery'});
  const status = element('p', {className: 'design-gallery-status'}); status.setAttribute('role', 'alert'); status.hidden = true;
  const invoke = async (button, action) => {
    button.disabled = true; status.hidden = true;
    try { await action(); } catch (error) { status.textContent = error.message || String(error); status.hidden = false; }
    finally { button.disabled = false; }
  };
  const newButton = element('button', {type: 'button', className: 'primary gallery-add', textContent: 'Add New Design'});
  newButton.setAttribute('aria-label', 'Add New Design');
  newButton.addEventListener('click', () => invoke(newButton, async () => openDesign(await createDesign('Untitled design', {base: null, placements: []}))));
  head.append(newButton);
  if (wallTemplate) {
    const wallButton=element('button',{type:'button',className:'gallery-add',textContent:'Build on a wall'});
    wallButton.id='new-wall-design';
    wallButton.addEventListener('click',()=>invoke(wallButton,async()=>openDesign(await createDesign(wallTemplate.name,
      {base:wallTemplate.base,placements:wallTemplate.placements},wallTemplate))));
    head.append(wallButton);
  }
  if (pinballTemplate) {
    const pinballButton=element('button',{type:'button',className:'gallery-add',textContent:'Pinball'});
    pinballButton.id='new-pinball-design';
    pinballButton.addEventListener('click',()=>invoke(pinballButton,async()=>openDesign(await createDesign(pinballTemplate.name,
      {base:pinballTemplate.base,placements:pinballTemplate.placements},pinballTemplate))));
    head.append(pinballButton);
  }
  gallery.append(status); box.append(gallery);
  const entries = [
    {key: 'owned', label: 'Your designs', id: 'saved-designs', rows: [...rows(store?.items)].sort((a,b)=>String(b.at).localeCompare(String(a.at)))},
    {key: 'examples', label: 'Examples', id: 'prebuilt-designs', rows: rows(templates)},
  ];
  entries.forEach((entry, index) => {
    entry.panel = element('section', {id: `design-panel-${entry.key}`, className: 'gallery-panel'});
    const heading = element('h2', {id: `design-heading-${entry.key}`, textContent: entry.label});
    entry.panel.setAttribute('aria-labelledby', heading.id);
    entry.panel.append(heading); gallery.append(entry.panel);
    const list = element('div', {className: 'ls-list design-gallery-list', id: entry.id}); entry.panel.append(list);
    if (!entry.rows.length) entry.panel.append(element('p', {className: 'gallery-empty', textContent: index ? 'No examples available.' : 'No designs yet. Add New Design to start building.'}));
    for (const row of entry.rows) {
      const draft = index ? {base: row.base, placements: row.placements} : row.draft;
      const card = element('button', {type: 'button', className: 'ls-card design-card'});
      card.setAttribute('aria-label', index ? `Start from ${row.name}` : `Open design ${row.name}`);
      card.append(preview(document, draft), element('strong', {textContent: row.name}));
      const count = rows(draft?.placements).length, versions = rows(row.versions).length;
      card.append(element('span', {className: 'teaches', textContent: index ? row.description || 'Editable example'
        : `${count} tray ${count === 1 ? 'piece' : 'pieces'}${draft?.base ? ' + base machine' : ''} · ${versions} saved ${versions === 1 ? 'version' : 'versions'}`}));
      card.addEventListener('click', () => invoke(card, async () => openDesign(index
        ? await createDesign(row.name, JSON.parse(JSON.stringify(draft)), row) : row)));
      list.append(card);
    }
  });
  return {element: gallery};
}
