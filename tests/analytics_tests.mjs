import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {createAnalytics, analyticsAllowed} from '../client/voxel-lab/analytics.mjs';

function fixture(overrides={}) {
  const values=new Map(), requests=[]; let clock=1792500000000;
  const storage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
  const options={location:{protocol:'https:',hostname:'banjo.is',pathname:'/play',
    search:'?visitor=private-return-token&design=private-design',hash:'#build=private-contents'},
    environment:'production',base:'',navigator:{maxTouchPoints:0},storage,crypto:webcrypto,
    now:()=>clock,referrer:'https://search.example/search?private=query',
    fetch:(url,options)=>{requests.push({url,options,body:JSON.parse(options.body)});return Promise.resolve({ok:true});},...overrides};
  return {options,values,requests,storage,advance:ms=>clock+=ms,client:createAnalytics(options)};
}

test('only the production Banjo domain can send events, never local, test, other apps or automation',()=>{
  const f=fixture();assert.equal(analyticsAllowed(f.options),true);
  for(const change of [{environment:'test'},{environment:'local'},{base:'/test'},
    {location:{...f.options.location,pathname:'/test/play'}},
    {location:{...f.options.location,hostname:'127.0.0.1'}},
    {location:{...f.options.location,hostname:'banjo-f1sv.onrender.com'}},
    {location:{...f.options.location,hostname:'other-project.example'}},
    {navigator:{webdriver:true}},{navigator:{doNotTrack:'1'}},{navigator:{globalPrivacyControl:true}}]) {
    const t=fixture(change);t.client.screen('level',{level_id:'gap'});t.client.track('banjo_run_started');
    assert.equal(t.requests.length,0);assert.equal(t.values.size,0);
  }
});

test('the dedicated US project receives only explicit allowlisted data and safe page URLs',()=>{
  const f=fixture();f.client.setRevision('a'.repeat(40));
  f.client.screen('level',{level_id:'easy-wall-drop',chapter:'1',visitor:'secret',design_id:'secret'});
  f.client.track('banjo_level_result',{success:true,stars:3,energy_j:42,message:'private chat',name:'private design',url:'secret',status:Infinity});
  assert.equal(f.requests.length,3);
  for(const r of f.requests){
    assert.equal(r.url,'https://us.i.posthog.com/i/v0/e/');
    assert.equal(r.body.api_key,'phc_mvMsqemTW8kwtFa7h9Kx2UhgH8VMkeiU5eQV2rwNWCda');
    assert.equal(r.options.keepalive,true);assert.equal(r.options.credentials,'omit');
    assert.equal(r.body.properties.$current_url,'https://banjo.is/play');
    assert.equal(r.body.properties.$referring_domain,'search.example');
    assert.equal(r.body.properties.build_revision,'a'.repeat(40));
    assert.equal(r.body.properties.$process_person_profile,false);
    assert.equal(r.body.properties.status,undefined);
    assert.doesNotMatch(JSON.stringify(r.body),/private|secret|visitor|design_id|chat|query/);
  }
  assert.equal(f.requests.at(-1).body.properties.success,true);
  assert.equal(f.client.track('arbitrary free text event'),false);
});

test('anonymous identity survives navigation, sessions expire after inactivity, other projects are untouched',()=>{
  const f=fixture();f.values.set('ph_other_project','untouched');f.values.set('banjo.visitor','private-save-token');
  f.client.screen('levels');const first=f.requests[0].body;
  const other=createAnalytics(f.options);other.screen('sandbox');
  assert.equal(f.requests.at(-1).body.distinct_id,first.distinct_id);
  assert.equal(f.requests.at(-1).body.properties.$session_id,first.properties.$session_id);
  assert.match(first.properties.$session_id,/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  f.advance(30*60*1000+1);other.track('banjo_design_saved');
  assert.equal(f.requests.at(-1).body.distinct_id,first.distinct_id);
  assert.notEqual(f.requests.at(-1).body.properties.$session_id,first.properties.$session_id);
  assert.equal(f.values.get('ph_other_project'),'untouched');
  assert.equal(f.values.get('banjo.visitor'),'private-save-token');
});

test('opt out immediately stops this and other tabs, clears only analytics IDs, and persists',()=>{
  const f=fixture();f.client.screen('levels');const other=createAnalytics(f.options);
  const count=f.requests.length;f.client.setEnabled(false);other.track('banjo_retry');
  assert.equal(f.requests.length,count);assert.equal(createAnalytics(f.options).enabled(),false);
  assert.equal(f.values.has('banjo.analytics.v1.id'),false);
  assert.equal(f.values.has('banjo.analytics.v1.session'),false);
  f.client.setEnabled(true);f.client.track('banjo_retry');assert.equal(f.requests.length,count+1);
});

test('screen changes send bounded dwell times; repeated renders and pagehide do not duplicate pageviews',()=>{
  const f=fixture();f.client.screen('levels');f.client.screen('levels');f.advance(1234);
  f.client.screen('level',{level_id:'gap'});f.client.leave();f.client.leave();
  assert.deepEqual(f.requests.map(r=>r.body.event),['$pageview','$pageleave','$pageview','banjo_level_opened','$pageleave']);
  assert.equal(f.requests[1].body.properties.elapsed_ms,1234);
  assert.equal(f.requests[1].body.properties.level_id,undefined);
});

test('storage restrictions and blocked or indefinitely slow analytics never block gameplay',async()=>{
  const f=fixture({storage:{getItem(){throw Error('blocked');},setItem(){throw Error('blocked');},removeItem(){throw Error('blocked');}},
    fetch:()=>Promise.reject(Error('blocked'))});
  assert.doesNotThrow(()=>{f.client.screen('levels');f.client.track('banjo_run_started');f.client.setEnabled(false);});
  const slow=fixture({fetch:()=>new Promise(()=>{})});assert.equal(slow.client.track('banjo_run_started'),true);
  await new Promise(resolve=>setTimeout(resolve,0));
});
