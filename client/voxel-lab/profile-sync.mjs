// Browser profiles contain setup declarations, never live simulation state.
const clone = value => value === undefined ? undefined : JSON.parse(JSON.stringify(value));
const object = value => value && typeof value === 'object' && !Array.isArray(value) ? value : {};
const array = value => Array.isArray(value) ? value : [];
const canonical = value => JSON.stringify(value, (_, item) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item);
const equal = (a, b) => canonical(a) === canonical(b);

function mergeLevels(remote, local) {
  const rows = {};
  for (const id of new Set([...Object.keys(remote), ...Object.keys(local)])) {
    const a = object(remote[id]), b = object(local[id]);
    const row = {...clone(a), ...clone(b)};
    const stars = [a.stars, b.stars].filter(value => Number.isFinite(value));
    if (stars.length) row.stars = Math.max(...stars);
    const energy = [a.energy_j, b.energy_j].filter(value => Number.isFinite(value) && value >= 0);
    if (energy.length) row.energy_j = Math.min(...energy);
    const wins = [a.won_at, b.won_at].filter(value => typeof value === 'string' && Number.isFinite(Date.parse(value)));
    if (wins.length) row.won_at = wins.reduce((first, next) => Date.parse(next) < Date.parse(first) ? next : first);
    Object.defineProperty(rows, id, {value: row, enumerable: true, configurable: true, writable: true});
  }
  return rows;
}

export function mergeProfiles(remote, local, base, makeId = () => globalThis.crypto.randomUUID()) {
  remote = object(remote); local = object(local); base = object(base);
  const profile = {...clone(remote), ...clone(local)};
  profile.levels = mergeLevels(object(remote.levels), object(local.levels));
  profile.tools = {...clone(object(local.tools)), ...clone(object(remote.tools))};
  const seen = new Set();
  profile.freshChallenges = [];
  for (const row of [...array(local.freshChallenges), ...array(remote.freshChallenges)]) {
    const key = row?.id ?? canonical(row);
    if (!seen.has(key)) { seen.add(key); profile.freshChallenges.push(clone(row)); }
  }
  const remoteStore = object(remote.sandbox), localStore = object(local.sandbox);
  const remoteItems = array(remoteStore.items), localItems = array(localStore.items);
  const originals = new Map(remoteItems.map(row => [row.id, clone(row)]));
  const baseline = new Map(array(base.sandbox?.items).map(row => [row.id, row]));
  const usedIds = new Set([...remoteItems, ...localItems].map(row => row.id));
  const recovered = [], remapped = new Map();
  for (const row of localItems) {
    const other = originals.get(row.id);
    if (!other) { originals.set(row.id, clone(row)); continue; }
    if (equal(other, row) || equal(row, baseline.get(row.id))) continue;
    if (equal(other, baseline.get(row.id))) { originals.set(row.id, clone(row)); continue; }
    let id;
    for (let attempt = 0; attempt < 32; attempt++) {
      const candidate = makeId();
      if (typeof candidate === 'string' && candidate && !usedIds.has(candidate)) { id = candidate; break; }
    }
    if (!id) throw new Error('Could not allocate an ID for a recovered design.');
    usedIds.add(id); remapped.set(row.id, id);
    const suffix = ' (recovered copy)';
    recovered.push({...clone(row), id, name: String(row.name || 'Untitled design').slice(0, 60 - suffix.length) + suffix});
  }
  profile.sandbox = {...clone(remoteStore), ...clone(localStore), items: [...originals.values(), ...recovered]};
  const selected = localStore.last || remoteStore.last || null;
  profile.sandbox.last = remapped.get(selected) || selected;
  return {profile, remappedDesignIds: Object.fromEntries(remapped)};
}

export class ProfileSync {
  constructor({request, read, onChange = () => {}, onCommit = () => {}, onMerge = () => false}) {
    if (typeof request !== 'function' || typeof read !== 'function') throw new TypeError('ProfileSync needs request and read functions.');
    Object.assign(this, {request, read, onChange, onCommit, onMerge});
    this._ready = false; this._id = null; this._revision = null; this._baseline = null;
    this._generation = 0; this._committed = 0; this._timer = null; this._running = null; this._error = null;
    this._retryRevision = null; this._retryBase = null;
  }

  state() {
    const dirty = this._generation > this._committed;
    return {ready: this._ready, pending: !this._error && Boolean(this._timer || this._running || dirty),
      error: this._error?.message || null, id: this._id, revision: this._revision, dirty};
  }

  _emit() { this.onChange(this.state()); }
  _clearTimer() { if (this._timer !== null) clearTimeout(this._timer); this._timer = null; }
  _arm() {
    this._clearTimer();
    if (!this._ready || this._error) return;
    this._timer = setTimeout(() => { this._timer = null; this.flush().catch(() => {}); }, 250);
  }

  initialize({visitor, revision, profile}) {
    if (this._running) throw new Error('Cannot replace a profile while a save is in flight.');
    if (typeof visitor !== 'string' || !visitor || !Number.isSafeInteger(revision) || revision < 0)
      throw new TypeError('Profile initialization needs a visitor and revision.');
    this._clearTimer(); this._id = visitor; this._revision = revision; this._baseline = clone(object(profile));
    this._ready = true; this._error = null; this._retryBase = null; this._retryRevision = null;
    if (!equal(object(this.read()), this._baseline) && this._generation === this._committed) this._generation++;
    if (this._generation > this._committed) this._arm();
    this._emit();
    return this.state();
  }

  schedule() {
    this._generation++;
    this._arm();
    this._emit();
  }

  async _drain() {
    let conflicts = 0;
    try {
      while (this._generation > this._committed) {
        const generation = this._generation, snapshot = clone(object(this.read()));
        const requestedRevision = this._retryRevision ?? this._revision;
        let response;
        try {
          response = await this.request({op: 'save', visitor: this._id,
            revision: requestedRevision, profile: clone(snapshot)});
        } catch (error) {
          if (error?.status !== 409 || !Number.isSafeInteger(error.data?.revision) || error.data.revision < 0
              || !error.data.profile || typeof error.data.profile !== 'object' || Array.isArray(error.data.profile)) throw error;
          const remote = clone(error.data.profile);
          const merged = mergeProfiles(remote, object(this.read()), this._retryBase ?? this._baseline);
          if (this.onMerge(clone(merged)) === false) throw new Error('The merged profile could not be applied.');
          this._retryBase = remote; this._retryRevision = error.data.revision;
          this._generation++;
          if (++conflicts > 3) throw new Error('The profile changed on another device repeatedly. Try saving again.');
          this._emit();
          continue;
        }
        if (!Number.isSafeInteger(response?.revision) || response.revision !== requestedRevision + 1)
          throw new Error('The server did not acknowledge the expected profile revision.');
        if (response.profile !== undefined && (!response.profile || typeof response.profile !== 'object' || Array.isArray(response.profile)))
          throw new Error('The server did not acknowledge a valid profile snapshot.');
        this._revision = response.revision;
        this._baseline = clone(response.profile === undefined ? snapshot : object(response.profile));
        this._retryBase = null; this._retryRevision = null;
        this._committed = generation;
        this.onCommit({visitor: this._id, revision: this._revision, profile: clone(this._baseline)});
        if (!equal(object(this.read()), this._baseline) && this._generation === this._committed) this._generation++;
        this._emit();
      }
    } catch (error) {
      this._error = error instanceof Error ? error : new Error(String(error));
      this._clearTimer(); this._emit();
      throw this._error;
    }
  }

  async flush() {
    this._clearTimer();
    if (!this._ready) throw new Error('The profile is not initialized yet.');
    this._error = null;
    if (!equal(object(this.read()), this._baseline) && this._generation === this._committed) this._generation++;
    do {
      if (!this._running && this._generation > this._committed) {
        this._running = this._drain().finally(() => { this._running = null; this._emit(); });
      }
      this._emit();
      if (this._running) await this._running;
    } while (this._generation > this._committed);
    this._clearTimer(); this._emit();
    return this.state();
  }
}
