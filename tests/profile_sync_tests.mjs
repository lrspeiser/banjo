import test from 'node:test';
import assert from 'node:assert/strict';
import {setTimeout as delay} from 'node:timers/promises';
import {mergeProfiles, ProfileSync} from '../client/voxel-lab/profile-sync.mjs';

const copy = value => JSON.parse(JSON.stringify(value));
const turn = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
const design = (id, x = 0, extra = {}) => ({id, name: `Design ${id}`, at: '2026-10-11T00:00:00Z',
  draft: {base: null, placements: [{piece: 'plank', x_m: x}]},
  versions: [{number: 1, draft: {base: null, placements: []}}], nextVersion: 2, ...extra});
const profile = (items = []) => ({levels: {}, tools: {}, freshChallenges: [], sandbox: {items, last: items[0]?.id || null}});

test('earned progress merges independently and unknown profile fields survive', () => {
  const remote = profile([design('remote')]), local = profile([design('local')]);
  remote.levels.cut = {stars: 3, energy_j: 40, won_at: '2026-01-01T00:00:00Z', shared: true};
  local.levels.cut = {stars: 1, energy_j: 0, won_at: '2026-02-01T00:00:00Z', note: 'local'};
  remote.levels.sun = {stars: 2}; local.levels.loop = {stars: 1};
  remote.tools = {knife: 'cut'}; local.tools = {knife: 'other', wire: 'loop'};
  remote.freshChallenges = [{id: 'r', title: 'remote'}, {id: 'same', title: 'old'}];
  local.freshChallenges = [{id: 'same', title: 'recent'}, {id: 'l', title: 'local'}];
  remote.cloudOnly = {nested: [1]}; local.free = {placements: [{piece: 'marble'}]}; local.last = 'loop';
  const before = [copy(remote), copy(local)];
  const {profile: merged, remappedDesignIds} = mergeProfiles(remote, local);
  assert.deepEqual(merged.levels.cut, {stars: 3, energy_j: 0, won_at: '2026-01-01T00:00:00Z', shared: true, note: 'local'});
  assert.equal(merged.levels.sun.stars, 2); assert.equal(merged.levels.loop.stars, 1);
  assert.deepEqual(merged.tools, {knife: 'cut', wire: 'loop'});
  assert.deepEqual(merged.freshChallenges.map(row => row.id), ['same', 'l', 'r']);
  assert.equal(merged.freshChallenges[0].title, 'recent');
  assert.deepEqual(merged.sandbox.items.map(row => row.id), ['remote', 'local']);
  assert.equal(merged.sandbox.last, 'local'); assert.equal(merged.last, 'loop');
  assert.deepEqual(merged.free, local.free); assert.deepEqual(remappedDesignIds, {});
  merged.cloudOnly.nested.push(2); merged.sandbox.items[0].draft.placements[0].x_m = 99;
  assert.deepEqual([remote, local], before);
});

test('one-sided edits choose the changed design; property order does not create a conflict', () => {
  const original = design('a'), base = profile([original]);
  for (const side of ['remote', 'local']) {
    const remote = copy(base), local = copy(base);
    (side === 'remote' ? remote : local).sandbox.items[0].draft.placements[0].x_m = 2;
    const result = mergeProfiles(remote, local, base, () => assert.fail('one-sided edits need no recovered ID'));
    assert.equal(result.profile.sandbox.items.length, 1);
    assert.equal(result.profile.sandbox.items[0].draft.placements[0].x_m, 2);
  }
  const reordered = {...original, draft: {placements: copy(original.draft.placements), base: null}};
  assert.equal(mergeProfiles(base, profile([reordered]), undefined, () => assert.fail('equal designs need no new ID'))
    .profile.sandbox.items.length, 1);
});

test('conflicting drafts and versions recover local copy without losing or renumbering checkpoints', () => {
  const base = profile([design('a')]), remote = copy(base), local = copy(base);
  remote.sandbox.items[0] = design('a', 2, {versions: [{number: 1}, {number: 2, label: 'remote'}], nextVersion: 3});
  local.sandbox.items[0] = design('a', 3, {name: 'N'.repeat(60), versions: [{number: 1}, {number: 2, label: 'local'}, {number: 8}], nextVersion: 9});
  const before = [copy(base), copy(remote), copy(local)];
  const result = mergeProfiles(remote, local, base, () => 'recovered');
  assert.deepEqual(result.profile.sandbox.items[0], remote.sandbox.items[0]);
  const recovered = result.profile.sandbox.items[1];
  assert.equal(recovered.id, 'recovered'); assert.equal(recovered.name.length, 60);
  assert.ok(recovered.name.endsWith(' (recovered copy)'));
  assert.deepEqual(recovered.versions, local.sandbox.items[0].versions);
  assert.equal(recovered.nextVersion, 9); assert.equal(recovered.draft.placements[0].x_m, 3);
  assert.deepEqual(result.remappedDesignIds, {a: 'recovered'}); assert.equal(result.profile.sandbox.last, 'recovered');
  recovered.versions[1].label = 'changed after merge';
  assert.deepEqual([base, remote, local], before);
});

test('no baseline preserves differing local design and recovered IDs cannot collide', () => {
  const remote = profile([design('a'), design('taken')]), local = profile([design('a', 1), design('local')]);
  const ids = ['a', 'local', 'taken', 'new'];
  const result = mergeProfiles(remote, local, undefined, () => ids.shift());
  assert.deepEqual(result.profile.sandbox.items.map(row => row.id), ['a', 'taken', 'local', 'new']);
  assert.deepEqual(result.remappedDesignIds, {a: 'new'});
  assert.equal(result.profile.sandbox.items[0].draft.placements[0].x_m, 0);
  assert.equal(result.profile.sandbox.items.at(-1).draft.placements[0].x_m, 1);
  assert.throws(() => mergeProfiles(remote, local, undefined, () => 'a'), /allocate an ID/);
});

test('pre-initialization edits remain dirty and debounce reports pending without premature commit', async () => {
  let local = profile(); const calls = [], commits = [], states = [];
  const sync = new ProfileSync({read: () => local, request: async payload => { calls.push(payload); return {revision: 1}; },
    onCommit: row => commits.push(row), onChange: state => states.push(state)});
  local.levels.cut = {stars: 1}; sync.schedule();
  assert.deepEqual(sync.state(), {ready: false, pending: true, error: null, id: null, revision: null, dirty: true});
  await delay(275); assert.equal(calls.length, 0);
  sync.initialize({visitor: 'visitor', revision: 0, profile: profile()});
  await delay(150); assert.equal(calls.length, 0); assert.equal(commits.length, 0);
  local.levels.cut.stars = 2; sync.schedule();
  await delay(150); assert.equal(calls.length, 0, 'each edit restarts the 250 ms debounce');
  await delay(150);
  assert.equal(calls.length, 1); assert.equal(calls[0].profile.levels.cut.stars, 2);
  assert.equal(commits.length, 1); assert.equal(sync.state().pending, false); assert.equal(sync.state().dirty, false);
  assert.ok(states.some(row => row.pending && row.dirty));
});

test('held first request plus a newer mutation flushes serial snapshots through final acknowledgement', async () => {
  const initial = profile(), local = copy(initial), calls = [], waits = [], commits = [];
  let active = 0, maxActive = 0;
  const sync = new ProfileSync({read: () => local, request: async payload => {
    active++; maxActive = Math.max(active, maxActive); calls.push(payload);
    const wait = deferred(); waits.push(wait);
    try { return await wait.promise; } finally { active--; }
  }, onCommit: row => { commits.push(copy(row)); row.profile.levels.cut.stars = 99; }});
  sync.initialize({visitor: 'visitor', revision: 0, profile: initial});
  initial.tools.externalMutation = 'outside';
  await sync.flush(); assert.equal(calls.length, 0, 'initialization clones its baseline');
  local.levels.cut = {stars: 1}; sync.schedule(); const firstFlush = sync.flush();
  assert.equal(calls.length, 1); assert.equal(sync.state().revision, 0); assert.equal(sync.state().pending, true);
  local.levels.cut.stars = 3; sync.schedule(); const secondFlush = sync.flush();
  assert.equal(calls[0].profile.levels.cut.stars, 1, 'in-flight payload cannot alias the editable profile');
  waits[0].resolve({revision: 1}); await turn();
  assert.equal(calls.length, 2); assert.equal(maxActive, 1); assert.equal(sync.state().revision, 1);
  assert.equal(sync.state().pending, true); assert.equal(calls[1].profile.levels.cut.stars, 3);
  assert.deepEqual(calls.map(row => row.revision), [0, 1]);
  waits[1].resolve({revision: 2}); await Promise.all([firstFlush, secondFlush]);
  assert.equal(local.levels.cut.stars, 3, 'onCommit also receives an isolated snapshot');
  assert.deepEqual(commits.map(row => row.profile.levels.cut.stars), [1, 3]);
  assert.deepEqual(sync.state(), {ready: true, pending: false, error: null, id: 'visitor', revision: 2, dirty: false});
});

test('transport failure preserves dirty data and only explicit flush retries', async () => {
  const local = profile(); const calls = []; let online = false;
  const sync = new ProfileSync({read: () => local, request: async payload => {
    calls.push(copy(payload)); if (!online) throw new Error('offline'); return {revision: 1};
  }});
  sync.initialize({visitor: 'visitor', revision: 0, profile: copy(local)});
  local.levels.cut = {stars: 2}; sync.schedule();
  await assert.rejects(sync.flush(), /offline/);
  assert.equal(sync.state().revision, 0); assert.equal(sync.state().dirty, true);
  assert.equal(sync.state().pending, false); assert.equal(sync.state().error, 'offline');
  local.levels.sun = {stars: 1}; sync.schedule(); await delay(300);
  assert.equal(calls.length, 1, 'neither a timer nor a later edit retries failed transport');
  online = true; await sync.flush();
  assert.equal(calls.length, 2); assert.equal(calls[1].profile.levels.sun.stars, 1);
  assert.equal(sync.state().dirty, false); assert.equal(sync.state().error, null);
});

test('409 uses latest local mutation and keeps both version histories and independent designs', async () => {
  const base = profile([design('a')]), remote = copy(base); let local = copy(base);
  local.levels.cut = {stars: 1, energy_j: 5, won_at: '2026-02-01T00:00:00Z'};
  remote.levels.cut = {stars: 3, energy_j: 10, won_at: '2026-01-01T00:00:00Z'};
  remote.sandbox.items[0].draft.placements[0].x_m = 2;
  remote.sandbox.items[0].versions.push({number: 2, label: 'remote'}); remote.sandbox.items[0].nextVersion = 3;
  remote.sandbox.items.push(design('remote'));
  const waits = [], calls = [], merges = [];
  const sync = new ProfileSync({read: () => local, request: payload => {
    calls.push(copy(payload)); const wait = deferred(); waits.push(wait); return wait.promise;
  }, onMerge: row => { merges.push(copy(row)); local = copy(row.profile); return true; }});
  sync.initialize({visitor: 'visitor', revision: 0, profile: base});
  local.sandbox.items[0].draft.placements[0].x_m = 1; sync.schedule(); const flushed = sync.flush();
  local.sandbox.items[0].versions.push({number: 2, label: 'local'}, {number: 3, label: 'newer during request'});
  local.sandbox.items[0].nextVersion = 4; local.sandbox.items.push(design('local')); sync.schedule();
  waits[0].reject(Object.assign(new Error('conflict'), {status: 409, data: {revision: 5, profile: remote}}));
  await turn();
  assert.equal(calls.length, 2); assert.equal(calls[1].revision, 5);
  assert.equal(sync.state().revision, 0, 'unacknowledged conflict revisions are not advertised as saved');
  const id = merges[0].remappedDesignIds.a, recovered = calls[1].profile.sandbox.items.find(row => row.id === id);
  assert.notEqual(id, 'a'); assert.deepEqual(recovered.versions.map(row => row.number), [1, 2, 3]);
  assert.equal(recovered.nextVersion, 4);
  assert.equal(calls[1].profile.sandbox.items.find(row => row.id === 'a').versions[1].label, 'remote');
  assert.ok(calls[1].profile.sandbox.items.some(row => row.id === 'local'));
  assert.ok(calls[1].profile.sandbox.items.some(row => row.id === 'remote'));
  assert.deepEqual(calls[1].profile.levels.cut, {stars: 3, energy_j: 5, won_at: '2026-01-01T00:00:00Z'});
  waits[1].resolve({revision: 6}); await flushed;
  assert.equal(sync.state().revision, 6); assert.equal(sync.state().dirty, false);
});

test('three merged retries are bounded, preserve remote changes, and can be explicitly retried', async () => {
  let local = profile(); let conflict = true; const calls = [];
  const sync = new ProfileSync({read: () => local, request: async payload => {
    calls.push(copy(payload));
    if (conflict) { const remote = profile(); remote.levels[`remote${calls.length}`] = {stars: 1};
      throw Object.assign(new Error('conflict'), {status: 409, data: {revision: calls.length, profile: remote}}); }
    return {revision: 5};
  }, onMerge: row => { local = row.profile; }});
  sync.initialize({visitor: 'visitor', revision: 0, profile: copy(local)});
  local.levels.local = {stars: 3}; sync.schedule();
  await assert.rejects(sync.flush(), /repeatedly/);
  assert.deepEqual(calls.map(row => row.revision), [0, 1, 2, 3]);
  assert.equal(sync.state().revision, 0); assert.equal(sync.state().dirty, true); assert.equal(sync.state().pending, false);
  for (const id of ['local', 'remote1', 'remote2', 'remote3', 'remote4']) assert.ok(local.levels[id]);
  await delay(300); assert.equal(calls.length, 4);
  conflict = false; await sync.flush();
  assert.equal(calls[4].revision, 4); assert.equal(sync.state().revision, 5); assert.equal(sync.state().dirty, false);
});

test('unapplied merge and malformed acknowledgement do not claim a saved revision', async () => {
  for (const mode of ['merge', 'ack']) {
    const local = profile(); let calls = 0;
    const sync = new ProfileSync({read: () => local, request: async () => {
      calls++;
      if (mode === 'merge') throw Object.assign(new Error('conflict'), {status: 409, data: {revision: 5, profile: profile()}});
      return {};
    }, onMerge: () => false});
    sync.initialize({visitor: 'visitor', revision: 0, profile: copy(local)});
    local.levels.cut = {stars: 1}; sync.schedule();
    await assert.rejects(sync.flush(), mode === 'merge' ? /could not be applied/ : /acknowledge/);
    assert.equal(calls, 1); assert.equal(sync.state().revision, 0); assert.equal(sync.state().dirty, true);
    assert.equal(local.levels.cut.stars, 1);
  }
});

test('stale or skipped revisions and invalid acknowledged profiles cannot clear dirty data', async () => {
  for (const response of [{revision: 0}, {revision: 2}, {revision: 1, profile: null},
    {revision: 1, profile: []}, {revision: 1, profile: 'not a profile'}]) {
    const local = profile(); let commits = 0;
    const sync = new ProfileSync({read: () => local, request: async payload => {
      assert.equal(payload.revision, 0); return response;
    }, onCommit: () => { commits++; }});
    sync.initialize({visitor: 'visitor', revision: 0, profile: copy(local)});
    local.levels.cut = {stars: 3}; sync.schedule();
    await assert.rejects(sync.flush(), /did not acknowledge/);
    assert.equal(commits, 0); assert.equal(sync.state().revision, 0);
    assert.equal(sync.state().dirty, true); assert.equal(sync.state().pending, false);
    assert.equal(local.levels.cut.stars, 3);
  }
});

test('blueprints from both devices are kept and a synced deletion stays deleted', () => {
  const a = {id: 'a', name: 'Ramp', placements: [{piece: 'plank'}]};
  const b = {id: 'b', name: 'Lift', placements: [{piece: 'tackle'}]};
  const c = {id: 'c', name: 'Old', placements: []};
  const {profile} = mergeProfiles({blueprints: [b, c]}, {blueprints: [a]}, {blueprints: [c]});
  assert.deepEqual(profile.blueprints.map(r => r.id), ['a', 'b'], 'deleted here after sync: c stays deleted');
  const edited = mergeProfiles({blueprints: [{...a, name: 'Remote'}]}, {blueprints: [{...a, name: 'Here'}]}, {});
  assert.deepEqual(edited.profile.blueprints.map(r => r.name), ['Here']);
  assert.equal('blueprints' in mergeProfiles({}, {}, {}).profile, false);
});
