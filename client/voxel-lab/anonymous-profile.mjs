// The return link selects an opaque save ID. Progress is synced separately;
// neither the cookie nor the URL contains a name or the saved designs.
export const VISITOR_COOKIE = 'banjo-visitor';
export function validVisitor(value) {
  return typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}
export function cookieVisitor(cookie) {
  const value = String(cookie || '').split(';').map(row => row.trim()).find(row => row.startsWith(VISITOR_COOKIE + '='))?.slice(VISITOR_COOKIE.length + 1);
  return validVisitor(value) ? value.toLowerCase() : null;
}
export function returnURL(origin, id, base = '') {
  if (!validVisitor(id)) throw new Error('Invalid anonymous save ID');
  if (!['', '/test'].includes(base)) throw new Error('Invalid application path');
  const url = new URL(base + '/play', origin);
  url.searchParams.set('visitor', id.toLowerCase());
  return url.href;
}
export function anonymousSave(raw, {visitor, cookie, makeId = () => crypto.randomUUID()} = {}) {
  const source = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
  const rows = source.players && typeof source.players === 'object' && !Array.isArray(source.players) ? source.players : {};
  const oldCurrent = Object.hasOwn(rows, source.current) ? source.current : Object.keys(rows)[0];
  const explicit = validVisitor(visitor) ? visitor.toLowerCase() : null;
  const remembered = cookieVisitor(cookie);
  const players = {};
  const migrated = [...(Array.isArray(source.migratedProfiles) ? source.migratedProfiles.filter(validVisitor) : [])];
  let migratedCurrent = null;
  for (const [key, row] of Object.entries(rows)) {
    if (!row || typeof row !== 'object' || Array.isArray(row)) continue;
    // Each old named profile becomes a separate anonymous save. Never attach
    // its data to an unrelated return link opened on this device.
    const id = validVisitor(key) ? key.toLowerCase() : makeId();
    if (!validVisitor(key)) migrated.push(id);
    if (key === oldCurrent) migratedCurrent = id;
    players[id] = {...row, levels: row.levels && typeof row.levels === 'object' && !Array.isArray(row.levels) ? row.levels : {}};
  }
  const current = explicit || (remembered && Object.hasOwn(players, remembered) ? remembered : null) || migratedCurrent || makeId();
  if (!Object.hasOwn(players, current)) players[current] = {levels: {}};
  return {...source, format: 2, current, players, migratedProfiles: [...new Set(migrated)]};
}
