// Explicit, bounded events through PostHog's Capture API. No autocapture,
// session replay, remote script, save identity, URL query or chat content.
// This is a public ingestion token for the owner's dedicated Banjo US project.
const PROJECT_KEY = 'phc_mvMsqemTW8kwtFa7h9Kx2UhgH8VMkeiU5eQV2rwNWCda';
const ENDPOINT = 'https://us.i.posthog.com/i/v0/e/';
const PREFIX = 'banjo.analytics.v1.';
const EVENTS = new Set(['$pageview', '$pageleave', 'banjo_level_opened', 'banjo_level_left',
  'banjo_run_started', 'banjo_level_result', 'banjo_retry', 'banjo_help_requested',
  'banjo_design_created', 'banjo_design_saved', 'banjo_design_restored',
  'banjo_course_shared', 'banjo_course_copied', 'banjo_builder_result',
  'banjo_api_error', 'banjo_run_pace']);
const NUMBERS = new Set(['attempt', 'attempts', 'elapsed_ms', 'world_s', 'stars', 'energy_j',
  'par_energy_j', 'piece_count', 'version_count', 'status', 'duration_ms', 'behind_s', 'wait_ms']);
const BOOLEANS = new Set(['success', 'helped', 'tested', 'keep_pieces', 'published', 'completed', 'read_only']);
const LABELS = new Set(['screen', 'level_id', 'chapter', 'activity', 'mode', 'operation']);
const SCREENS = new Set(['levels', 'sandbox', 'community', 'level', 'design']);
const label = value => typeof value === 'string' && /^[a-zA-Z0-9 _-]{1,80}$/.test(value) ? value : undefined;

export function analyticsAllowed({location, environment, base = '', navigator = {}}) {
  return environment === 'production' && !base && location?.protocol === 'https:' &&
    ['banjo.is', 'www.banjo.is'].includes(location.hostname) &&
    !/^\/test(?:\/|$)/.test(location.pathname) &&
    navigator.doNotTrack !== '1' && !navigator.globalPrivacyControl && !navigator.webdriver;
}

export function createAnalytics({location = globalThis.location, navigator = globalThis.navigator,
  environment = globalThis.document?.documentElement.dataset.banjoEnvironment,
  base = globalThis.document?.documentElement.dataset.banjoBase || '',
  storage, fetch: send = globalThis.fetch?.bind(globalThis), crypto = globalThis.crypto,
  now = Date.now, referrer = globalThis.document?.referrer || ''} = {}) {
  try { storage ??= globalThis.localStorage; } catch { /* Private browsing: memory only. */ }
  const read = key => { try { return storage?.getItem(PREFIX + key); } catch { return null; } };
  const write = (key, value) => { try { storage?.setItem(PREFIX + key, value); } catch { /* optional */ } };
  const remove = key => { try { storage?.removeItem(PREFIX + key); } catch { /* optional */ } };
  const allowed = analyticsAllowed({location, environment, base, navigator});
  let enabled = allowed && read('optout') !== '1', distinct = null, visit = null;
  let context = {}, revision = 'unknown', screenAt = now(), pageOpen = false;
  let referral = '';
  try { referral = new URL(referrer).hostname; } catch { /* Direct arrival. */ }
  // PostHog session IDs are time-sortable UUIDv7 values. Independent from
  // Banjo's bearer return-link token and from every other project's identity.
  function uuid7() {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    let t = BigInt(now());
    for (let i = 5; i >= 0; i--) { bytes[i] = Number(t & 255n); t >>= 8n; }
    bytes[6] = (bytes[6] & 15) | 0x70; bytes[8] = (bytes[8] & 63) | 0x80;
    const hex = [...bytes].map(b => b.toString(16).padStart(2, '0')).join('');
    return [hex.slice(0,8), hex.slice(8,12), hex.slice(12,16), hex.slice(16,20), hex.slice(20)].join('-');
  }
  const validID = value => typeof value === 'string' && /^[0-9a-f-]{36}$/.test(value);
  function identity() {
    if (!distinct) { const stored = read('id'); distinct = validID(stored) ? stored : uuid7(); write('id', distinct); }
    try {
      const stored = JSON.parse(read('session'));
      if (validID(stored?.id) && stored.at <= now() && now() - stored.at < 30 * 60 * 1000) visit = stored;
    } catch { /* New session. */ }
    if (!visit || now() - visit.at >= 30 * 60 * 1000) visit = {id: uuid7()};
    visit.at = now(); write('session', JSON.stringify(visit));
  }
  function clean(properties) {
    const result = {};
    for (const [key, value] of Object.entries(properties)) {
      if (NUMBERS.has(key) && Number.isFinite(value)) result[key] = Math.max(0, Math.min(1e15, value));
      if (BOOLEANS.has(key) && typeof value === 'boolean') result[key] = value;
      if (LABELS.has(key) && label(value)) result[key] = value;
    }
    return result;
  }
  function track(event, properties = {}) {
    // Re-read opt-out so another Banjo tab can turn tracking off immediately.
    if (!enabled || read('optout') === '1' || !EVENTS.has(event)) return false;
    try {
      identity();
      const page = context.screen === 'design' || context.screen === 'sandbox' ? '/machine' :
        context.screen === 'community' ? '/community' : '/play';
      const props = {...clean(context), ...clean(properties), app: 'banjo', environment: 'production',
        build_revision: revision, $lib: 'banjo-web', $lib_version: '1', $session_id: visit.id,
        $device_id: distinct, $process_person_profile: false, $geoip_disable: true,
        $current_url: 'https://banjo.is' + page, $pathname: page, $host: 'banjo.is',
        $device_type: navigator.maxTouchPoints > 0 ? 'Touch' : 'Desktop',
        ...(referral ? {$referring_domain: referral} : {})};
      const body = JSON.stringify({api_key: PROJECT_KEY, event, distinct_id: distinct,
        properties: props, timestamp: new Date(now()).toISOString(), uuid: uuid7()});
      // Fire-and-forget; no event is ever awaited by the game/physics. A
      // blocked endpoint drops analytics, without retries or gameplay errors.
      Promise.resolve(send?.(ENDPOINT, {method: 'POST', headers: {'Content-Type': 'text/plain'},
        body, keepalive: true, credentials: 'omit', referrerPolicy: 'no-referrer'})).catch(() => {});
      return true;
    } catch { return false; }
  }
  function leave() {
    if (!pageOpen) return;
    track('$pageleave', {elapsed_ms: now() - screenAt}); pageOpen = false;
  }
  function screen(screen, properties = {}) {
    if (!SCREENS.has(screen)) return;
    const next = {...clean(properties), screen};
    if (pageOpen && JSON.stringify(next) === JSON.stringify(context)) return;
    leave(); context = next; screenAt = now(); pageOpen = true;
    track('$pageview');
    if (screen === 'level') track('banjo_level_opened');
  }
  return {track, screen, leave, allowed,
    enabled: () => enabled && read('optout') !== '1',
    setRevision: value => { if (/^[a-f0-9]{7,40}$/.test(value)) revision = value; },
    setEnabled(value) {
      enabled = allowed && Boolean(value); write('optout', value ? '0' : '1');
      if (!value) { remove('id'); remove('session'); distinct = visit = null; }
    }};
}
