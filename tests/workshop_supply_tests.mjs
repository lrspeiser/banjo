import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync} from 'node:fs';

// Exercise the shipped planner/orchestrator with controlled transfer boundaries.
// Native debits, manufacture and restart are qualified separately by HTTP/UI.
const source=readFileSync(new URL('../playground/workshop.js',import.meta.url),'utf8');
const start=source.indexOf('function nextRemakeFunding('),end=source.indexOf('function renderRemakeFunding(');
assert.ok(start>=0 && end>start);
const code=source.slice(start,end);
function fixture() {
  const plan={available:true,occupied:false,build_readiness:{status:'Fund materials'},
    missing_materials_kg:{oak:1.925},missing_goods_kg:{},missing_energy_j:192.5,
    stock_sources:[{material:'oak',pool:'shared',mass_kg:12.4},{material:'oak',pool:'personal',mass_kg:25}],goods_sources:[]};
  const supply={configured:true,energy_sources:[{id:7,max_power_w:500,charge_j:1000,connected:false,transfer_available_j:0}]};
  const bench={inventorySelection:{id:'my-design'},revision:3},remake={plan,supply,store:null};
  const calls=[],pending=[];let waits=0,failOnce=false,meterChanges=0;
  const fundRemake=async(op,choice)=>{
    calls.push({op,choice});
    if(pending.length) {assert.equal(pending.shift(),op);return;}
    if(op==='fund_energy' && meterChanges>0) {meterChanges--;throw Error('Native source changed; read energy_sources before spending');}
    if(op==='fund_stock' || op==='fund_goods') {
      const gaps=op==='fund_stock'?plan.missing_materials_kg:plan.missing_goods_kg;
      const stocks=op==='fund_stock'?plan.stock_sources:plan.goods_sources;
      const stock=stocks.find(s=>s.material===choice.material && s.pool===choice.pool);
      assert.ok(stock.mass_kg>=choice.mass_kg && gaps[choice.material]>=choice.mass_kg);
      stock.mass_kg-=choice.mass_kg;gaps[choice.material]-=choice.mass_kg;
      if(failOnce) {failOnce=false;pending.push(op);throw Error('Receiving acknowledgement lost');}
    }else if(op==='connect_energy')supply.energy_sources[0].connected=true;
    else if(op==='fund_energy') {
      const battery=supply.energy_sources[0];assert.ok(battery.connected);
      assert.ok(battery.transfer_available_j>=choice.joules && battery.charge_j>=choice.joules);
      battery.charge_j-=choice.joules;battery.transfer_available_j-=choice.joules;
      plan.missing_energy_j-=choice.joules;
    }else assert.fail('Unexpected operation '+op);
  };
  const functions=new Function('bench','remake','REMAKE_FUNDING','fundingPending','fundRemake',
    'reviewRemake','waitRemakeSecond','titleCase',code+'\nreturn {nextRemakeFunding,remakeSupplyPools,prepareRemakeSupplies};')(
      bench,remake,['fund_stock','fund_goods','connect_energy','fund_energy'],op=>pending.includes(op),fundRemake,
      async()=>{},async()=>{waits++;calls.push({op:'wait'});supply.energy_sources[0].transfer_available_j+=500;},x=>x);
  return {plan,supply,bench,remake,calls,functions,waits:()=>waits,loseAck:()=>{failOnce=true;},changeMeter:n=>{meterChanges=n;}};
}

test('personal stock and actual charger allowance precede exact energy transfer',async()=>{
  const f=fixture(),original=structuredClone(f.plan);
  assert.equal(f.functions.remakeSupplyPools(f.plan),'Your stock');
  assert.deepEqual(f.functions.nextRemakeFunding(f.plan,f.supply,null),
    {op:'fund_stock',choice:{material:'oak',pool:'personal',mass_kg:1.925}});
  assert.deepEqual(f.plan,original,'Planning cannot reserve or debit');
  await f.functions.prepareRemakeSupplies();
  assert.deepEqual(f.calls.map(x=>x.op),['fund_stock','connect_energy','wait','fund_energy']);
  assert.equal(f.plan.stock_sources[0].mass_kg,12.4);assert.equal(f.plan.stock_sources[1].mass_kg,23.075);
  assert.equal(f.supply.energy_sources[0].charge_j,807.5);assert.equal(f.plan.missing_energy_j,0);
  assert.deepEqual(f.functions.nextRemakeFunding(f.plan,f.supply,null),{done:true});
});

test('missing goods, depleted energy and station limits stop before any debit',async()=>{
  for(const problem of ['goods','battery','occupied','limit']) {
    const f=fixture();
    if(problem==='goods')f.plan.missing_goods_kg.wire=.1;
    if(problem==='battery')f.supply.energy_sources[0].charge_j=0;
    if(problem==='occupied')f.plan.occupied=true;
    if(problem==='limit')f.plan.build_readiness.status='Workpiece limit reached';
    const before=structuredClone(f.plan);
    await assert.rejects(f.functions.prepareRemakeSupplies());
    assert.deepEqual(f.calls,[]);assert.deepEqual(f.plan,before);
  }
});

test('mixed stocks disclose shared use and consume personal amounts first',async()=>{
  const f=fixture();f.plan.stock_sources[1].mass_kg=1;
  f.plan.missing_goods_kg.wire=.2;
  f.plan.goods_sources=[{material:'wire',pool:'personal',mass_kg:.2}];
  assert.equal(f.functions.remakeSupplyPools(f.plan),'Your + shared stock');
  await f.functions.prepareRemakeSupplies();
  assert.deepEqual(f.calls.slice(0,3).map(x=>[x.op,x.choice.pool,x.choice.material,x.choice.mass_kg]),
    [['fund_stock','personal','oak',1],['fund_stock','shared','oak',.925],['fund_goods','personal','wire',.2]]);
});

test('lost acknowledgement stops later work and resumes the exact existing transfer',async()=>{
  const f=fixture();f.loseAck();
  await assert.rejects(f.functions.prepareRemakeSupplies(),/acknowledgement lost/);
  assert.deepEqual(f.calls.map(x=>x.op),['fund_stock']);
  await f.functions.prepareRemakeSupplies();
  assert.deepEqual(f.calls.map(x=>x.op),['fund_stock','fund_stock','connect_energy','wait','fund_energy']);
  assert.equal(f.plan.stock_sources[1].mass_kg,23.075,'An acknowledged retry cannot debit again');
  assert.equal(f.supply.energy_sources[0].charge_j,807.5);
});

test('long charging is bounded and resumes from measured remaining balances',async()=>{
  const f=fixture();f.plan.missing_energy_j=3000;f.supply.energy_sources[0].charge_j=5000;
  await f.functions.prepareRemakeSupplies();
  assert.equal(f.waits(),5);assert.equal(f.plan.missing_energy_j,3000);
  assert.equal(f.supply.energy_sources[0].charge_j,5000,'Waiting alone creates no station credit');
  await f.functions.prepareRemakeSupplies();
  assert.equal(f.waits(),6);assert.equal(f.plan.missing_energy_j,0);
  assert.equal(f.supply.energy_sources[0].charge_j,2000);
  assert.equal(f.calls.filter(x=>x.op==='fund_stock').length,1);
});

test('only a confirmed pre-debit meter refusal receives bounded refreshes',async()=>{
  const f=fixture();f.changeMeter(1);await f.functions.prepareRemakeSupplies();
  assert.equal(f.plan.missing_energy_j,0);assert.equal(f.supply.energy_sources[0].charge_j,807.5);
  assert.equal(f.calls.filter(x=>x.op==='fund_stock').length,1);
  const busy=fixture();busy.changeMeter(100);
  await assert.rejects(busy.functions.prepareRemakeSupplies(),/Native source changed/);
  assert.equal(busy.calls.filter(x=>x.op==='fund_energy').length,4);
  assert.equal(busy.supply.energy_sources[0].charge_j,1000);
  assert.equal(busy.plan.missing_energy_j,192.5);
});
