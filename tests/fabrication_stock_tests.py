"""Real rack funding, durable escrow recovery and retained native damage."""
from copy import deepcopy
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
import urllib.error
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'playground'),str(ROOT/'tests')]
from mcp import fabrication as model
from fabrication_tests import settings,candidate
import fabrication_room as api
import fabrication_stock as stock
import workshop_library as library
import live_session,room_store,world_room,workshop_install
ENGINE=Path(os.environ['BANJO_LIVE_ENGINE']).resolve() if os.environ.get('BANJO_LIVE_ENGINE') else None


class StockModel(unittest.TestCase):
    def fixture(self):
        state=model.new(settings(stock_kg={},energy_j=0),0)
        packet={'schema':'banjo.fabrication-stock-transfer.v1','scene':'fabrication',
            'source_owner':'alice','requested_by':'alice','material':'oak','mass_kg':1.,
            'reference_state':'cold-inventory-reservoir-v1'}
        action={'op':'fund_stock','material':'oak','mass_kg':1.,'pool':'personal','rack_hash':'test',
            'request_id':'stock-credit-0001','revision':0,'requested_by':'alice'}
        return state,action,packet

    def test_zero_initial_resources_import_mass_and_recovery_receipt(self):
        state,action,packet=self.fixture(); original=deepcopy(state)
        out,replayed=model.receive_stock(state,action,packet)
        self.assertFalse(replayed);self.assertEqual(state,original)
        self.assertEqual(out['stock_kg'],{'oak':1.})
        self.assertEqual(model.audit(out)['rack_material_received_kg'],{'oak':1.})
        self.assertEqual(model.audit(out)['material_residual_kg'],{'oak':0.})
        loaded=json.loads(json.dumps(out))
        self.assertEqual(model.receive_stock(loaded,action,packet),(loaded,True))
        with self.assertRaises(ValueError):model.receive_stock(loaded,{**action,'mass_kg':2},packet)
        bad=deepcopy(out);bad['stock_imports']={}
        with self.assertRaises(ValueError):model.validate_state(bad)
        bad=deepcopy(out);bad['stock_imports']['stock-credit-0001']['mass_kg']=2
        with self.assertRaises(ValueError):model.validate_state(bad)
        for changes in ({'material':'sand'},{'mass_kg':True},{'reference_state':'measured-temperature'},
                        {'requested_by':''},{'unknown':1}):
            with self.assertRaises(ValueError):model.stock_packet({**packet,**changes})


@unittest.skipUnless(ENGINE and ENGINE.is_file(),'BANJO_LIVE_ENGINE is required')
class NativeStock(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.live=live_session.Live();self.addCleanup(self.live.shutdown)
        self.room=world_room.Room('fabrication')
        self.room.spec['machines']={'stores':[{'name':'measured battery','body':'marker stone',
            'capacity_j':4000.,'charge_j':4000.,'max_power_w':300.,'voltage_v':24.}]}
        self.app=SimpleNamespace(live=self.live,live_holder='world',room=self.room,engine_path=ENGINE,
            runs_path=root/'runs',store=room_store.RoomStore(root/'rooms'))
        self.live.open(self.app,{'spec':self.room.spec})
        self.call('configure',settings=settings(stock_kg={},energy_j=0),request_id='stock-config-0001')
        for material in ('glass','oak','iron'):library.set_rack(self.app,material,10.)

    def context(self):return {'scene':self.room.scene,'session':self.live.session.id}
    def call(self,operation,**body):return api.request(self.app,operation,{**self.context(),**body})
    def source(self,material='oak',pool='personal'):
        return next(r for r in stock.sources(self.app) if r['material']==material and r['pool']==pool)
    def request(self,mass=1.,material='oak',ident='stock-import-0001',pool='personal'):
        return {**self.context(),'material':material,'mass_kg':mass,'pool':pool,
            'rack_hash':self.source(material,pool)['rack_hash'],'request_id':ident,
            'revision':self.room.fabrication_record['revision']}

    def test_failed_save_retains_visible_escrow_release_restores_exact_rack_once(self):
        request=self.request();before=workshop_install._snapshot(self.live)
        with mock.patch.object(self.app.store,'save',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):api.request(self.app,'fund_stock',request)
            reading=self.call('state')
        self.assertEqual(self.source()['mass_kg'],9.)
        self.assertEqual(reading['state']['stock_kg'],{})
        self.assertEqual(reading['stock_recovery_status']['state'],'pending')
        self.assertEqual(reading['stock_reservations'][0]['mass_kg'],1.)
        self.assertEqual(workshop_install._snapshot(self.live),before)
        with mock.patch.object(self.live,'snapshot',return_value=(None,'unfinished native stroke')):
            reading=self.call('state')
            self.assertEqual('pending',reading['stock_recovery_status']['state'])
            self.assertEqual('unfinished native stroke',reading['stock_recovery_status']['reason'])
            self.assertEqual({},reading['state']['stock_kg'])
        release={**self.context(),'reservation_id':request['request_id'],'request_id':'release-stock-0001'}
        self.assertFalse(api.request(self.app,'release_stock',release)['replayed'])
        self.assertTrue(api.request(self.app,'release_stock',release)['replayed'])
        self.assertEqual(self.source()['mass_kg'],10.)
        self.assertEqual(self.call('state')['stock_reservations'],[])
        with self.assertRaisesRegex(ValueError,'released'):api.request(self.app,'fund_stock',request)
        with self.assertRaisesRegex(ValueError,'different'):
            api.request(self.app,'release_stock',{**release,'request_id':'release-stock-0002'})

    def test_source_debit_recovers_after_restart_without_duplicate_credit_or_rewinding_native_state(self):
        request=self.request()
        with mock.patch.object(self.app.store,'save',side_effect=OSError('power lost')):
            with self.assertRaises(OSError):api.request(self.app,'fund_stock',request)
        saved=self.app.store.load('fabrication')
        self.live.open(self.app,{'spec':saved.spec,'snapshot':saved.world_record})
        self.room=self.app.room=saved
        before=workshop_install._snapshot(self.live)
        reading=self.call('state')
        self.assertEqual(reading['state']['stock_kg'],{'oak':1.})
        self.assertEqual(reading['stock_reservations'],[])
        self.assertEqual(self.source()['mass_kg'],9.)
        self.assertEqual(workshop_install._snapshot(self.live),before)
        self.assertTrue(api.request(self.app,'fund_stock',request)['replayed'])
        self.assertEqual(self.app.store.load('fabrication').fabrication_record,self.room.fabrication_record)

    def test_lost_save_acknowledgement_cannot_refund_already_credited_stock(self):
        real_save=self.app.store.save
        def uncertain(record):real_save(record);raise OSError('reply lost after replace')
        request=self.request()
        with mock.patch.object(self.app.store,'save',side_effect=uncertain):
            with self.assertRaises(OSError):api.request(self.app,'fund_stock',request)
        self.assertEqual(self.room.fabrication_record['stock_kg'],{})
        with self.assertRaisesRegex(ValueError,'credited durably'):
            self.call('release_stock',reservation_id=request['request_id'],request_id='uncertain-release-0001')
        self.assertEqual(self.source()['mass_kg'],9.)
        self.assertEqual(self.call('state')['state']['stock_kg'],{'oak':1.})
        self.assertTrue(api.request(self.app,'fund_stock',request)['replayed'])
        self.assertEqual(self.room.fabrication_record['stock_kg'],{'oak':1.})

    def test_two_players_stale_sources_and_receiving_history_cannot_spend_peer_stock(self):
        self.app.world_id='private-stock-fixture'
        self.room.player_records={who:{'id':who,'token':who,'name':who,'inventory':{},'pose':None} for who in ('alice','bob')}
        with library._connect(self.app) as db:
            for who,mass in (('alice',3.),('bob',4.)):
                db.execute('INSERT INTO workshop_material_rack VALUES (?,?,?,?)',(who,'oak',mass,library._now()))
        token=library.REQUEST_OWNER.set('alice')
        try:
            request=self.request(2.)
            result=api.request(self.app,'fund_stock',request)
            self.assertEqual(result['state']['stock_kg'],{'oak':2.})
            self.assertEqual(self.source()['mass_kg'],1.)
            with self.assertRaisesRegex(ValueError,'rack changed'):
                api.request(self.app,'fund_stock',{**request,'revision':self.room.fabrication_record['revision'],'request_id':'stale-source-0001'})
            with self.assertRaisesRegex(ValueError,'Insufficient'):
                api.request(self.app,'fund_stock',self.request(2.,ident='poor-source-0001'))
            with self.assertRaises(ValueError):api.request(self.app,'fund_stock',{**self.request(),'source_owner':'bob'})
        finally:library.REQUEST_OWNER.reset(token)
        token=library.REQUEST_OWNER.set('bob')
        try:
            self.assertEqual(self.source()['mass_kg'],4.)
            with self.assertRaisesRegex(ValueError,'different transfer or player'):api.request(self.app,'fund_stock',request)
            self.assertEqual(stock.pending(self.app,self.room.scene),[])
        finally:library.REQUEST_OWNER.reset(token)
        # A complete source debit cannot be reused with an older receiving save.
        bad=deepcopy(self.room.fabrication_record);bad['stock_imports']={};bad['stock_kg']={};bad['receipts']={}
        with self.assertRaisesRegex(ValueError,'missing previously applied'):stock.validate(self.app,self.room.scene,bad)

    def test_rack_and_battery_funded_native_glass_oak_iron_outputs_from_zero_seeds(self):
        state=self.call('state');source=state['energy_sources'][0]
        self.call('connect_energy',store=source['id'],store_hash=source['store_hash'],power_w=250,
            revision=state['state']['revision'],request_id='stock-charger-0001')
        measurements=[]
        for index,material in enumerate(('glass','oak','iron')):
            api.request(self.app,'fund_stock',self.request(10.,material,'real-stock-'+material))
            self.assertEqual(self.source(material)['mass_kg'],0.)
            api.wait(self.app,{**self.context(),'seconds':4})
            state=self.call('state');source=state['energy_sources'][0]
            self.call('fund_energy',store_hash=source['store_hash'],joules=1000.,
                revision=state['state']['revision'],request_id='real-energy-'+material)
            ident='real-job-'+material
            self.call('start',candidate=candidate(material),stock_kg=10.,request_id=ident,
                revision=self.room.fabrication_record['revision'])
            api.wait(self.app,{**self.context(),'seconds':2})
            preview=api.preview(self.app,{**self.context(),'job_id':ident,'position_m':[index*.5,0]})
            result=api.commit(self.app,{**self.context(),'job_id':ident,'preview_id':preview['preview_id'],
                'request_id':'real-install-'+material})
            audit=model.audit(self.room.fabrication_record)
            self.assertTrue(all(abs(r)<1e-9 for r in audit['material_residual_kg'].values()))
            self.assertLess(abs(audit['energy_residual_j']),1e-7)
            self.assertEqual(stock.get(self.app,self.room.scene,'real-stock-'+material)['status'],'applied')
            measurements.append({'material':material,'rack_debit_kg':10.,'native_output_kg':result['mass_kg'],
                'offcut_kg':self.room.fabrication_record['waste_kg'][material],'battery_debit_j':1000.,
                'material_residual_kg':audit['material_residual_kg'][material],'energy_residual_j':audit['energy_residual_j']})
        self.assertEqual(self.room.fabrication_record['config']['stock_kg'],{})
        self.assertEqual(self.room.fabrication_record['config']['energy_j'],0)
        self.native_evidence=measurements
        print('REAL_STOCK_FABRICATION_EVIDENCE '+json.dumps(measurements,sort_keys=True))

    def test_funded_new_part_preserves_real_native_cut_and_original_body(self):
        # Explicit experiment authoring, before any transfer. Normal gravity;
        # high starting elevation keeps the falling stroke clear of the floor.
        self.room.spec['cell_m']=.01
        self.room.spec['bodies'] += [
            {'name':'old oak','shape':'box','material':'oak','size_mm':[100,100,100],
             'center_mm':[0,20000,0]},
            {'name':'edge','shape':'box','material':'iron','size_mm':[200,10,30],
             'center_mm':[0,20000,66],'velocity_m_s':[0,0,-6]}]
        self.room.spec['blades']=[{'body':'edge','heel_mm':[-90,20000,51],
            'tip_mm':[90,20000,51],'facing':[0,0,-1],'thickness_mm':10,
            'edge_radius_mm':.05,'bevel_deg':30,'grip_mm':[90,20000,66]}]
        self.live.open(self.app,{'spec':self.room.spec})
        def condition(name):
            return self.live.session.send(op='condition',names=[name])['condition']['bodies'][0]
        self.assertEqual(1,condition('old oak')['fraction'])
        for _ in range(120):
            result=self.live.session.send(op='step',dt=1/240,n=1)
            for name in result.get('breakable',[]):self.live.session.send(op='decline',name=name)
        cut=condition('old oak');self.assertGreater(cut['broken_bonds'],0)
        self.assertLess(cut['fraction'],1)
        self.live.session.send(op='grab',name='edge')
        edge=next(b for b in self.live.session.send(op='poses')['bodies'] if b['name']=='edge')
        target=edge['position_m'][:];target[2]+=.2
        self.live.session.send(op='move',to=target)
        self.live.session.send(op='step',dt=1/240,n=10)
        self.live.session.send(op='release')
        self.live.session.send(op='step',dt=1/240,n=10)
        for name in ('edge','old oak'):self.live.session.send(op='park',name=name)
        old=condition('old oak');before=workshop_install._snapshot(self.live)
        api.request(self.app,'fund_stock',self.request(1.,ident='cut-stock-0001'))
        state=self.call('state');source=state['energy_sources'][0]
        self.call('connect_energy',store=source['id'],store_hash=source['store_hash'],power_w=250.,
            revision=state['state']['revision'],request_id='cut-connect-0001')
        api.wait(self.app,{**self.context(),'seconds':1})
        state=self.call('state');source=state['energy_sources'][0]
        self.call('fund_energy',store_hash=source['store_hash'],joules=100.,
            revision=state['state']['revision'],request_id='cut-energy-0001')
        design=candidate();part=design['component_overrides']['@construction']['added'][0]
        part.update(size_m=[.1,.1,.1],center_m=[0,.05,0])
        self.call('start',candidate=design,stock_kg=1.,revision=self.room.fabrication_record['revision'],
            request_id='cut-new-part-0001')
        api.wait(self.app,{**self.context(),'seconds':1})
        preview=api.preview(self.app,{**self.context(),'job_id':'cut-new-part-0001','position_m':[0,0]})
        result=api.commit(self.app,{**self.context(),'job_id':'cut-new-part-0001',
            'preview_id':preview['preview_id'],'request_id':'cut-install-0001'})
        self.assertEqual(old,condition('old oak'),'Funding/admission healed or erased original damage')
        after=workshop_install._snapshot(self.live)
        self.assertEqual(next(b for b in before['bodies'] if b['name']=='old oak'),
                         next(b for b in after['bodies'] if b['name']=='old oak'))
        self.assertAlmostEqual(.7,result['mass_kg'],places=9)
        fresh=condition(result['root_body'])
        self.assertEqual(0,fresh['broken_bonds'])
        self.assertAlmostEqual(1,fresh['fraction'],places=12)
        self.assertAlmostEqual(.3,self.room.fabrication_record['waste_kg']['oak'],places=9)
        self.assertEqual(9.,self.source()['mass_kg'])
        self.assertLess(abs(model.audit(self.room.fabrication_record)['material_residual_kg']['oak']),1e-9)
        self.native_evidence={'old_condition':old,'new_mass_kg':result['mass_kg'],
            'stock_debit_kg':1.,'source_energy_j':100.,'cell_m':.01,'dt_s':1/240,
            'boundary':'New part admission; old cut retained. No bond healing or selected-item repair.'}


import world_goods_tests as flow
from workbench_tests import WorkbenchTestCase


@unittest.skipUnless(ENGINE and ENGINE.is_file(),'BANJO_LIVE_ENGINE is required')
class StockMCP(WorkbenchTestCase):
    def test_same_mcp_tools_reserve_release_and_credit_exact_rack(self):
        import fabrication_mcp_tools as tools
        from circuit_api import validate
        app=self.start();app.engine_path=ENGINE;app.live=live_session.Live();self.addCleanup(app.live.shutdown)
        opened=self.post(app,'/api/world/open',{'scene':'fabrication'})
        ctx={k:opened[k] for k in ('scene','session')}
        library.set_rack(app,'oak',5.)
        schemas={t['name']:t['inputSchema'] for t in tools.TOOLS}
        with mock.patch.dict(os.environ,{'BANJO_PLAYGROUND_URL':f'http://127.0.0.1:{app.port}'}):
            def call(op,**body):
                args={**ctx,**body};name='fabrication_'+op
                validate(args,schemas[name],'arguments');return tools.call(name,args)
            call('configure',settings=settings(stock_kg={},energy_j=0),request_id='mcp-stock-config-0001')
            reading=call('state');source=next(r for r in reading['stock_sources'] if r['material']=='oak' and r['pool']=='personal')
            request={'material':'oak','mass_kg':2.,'pool':'personal','rack_hash':source['rack_hash'],
                'revision':reading['state']['revision'],'request_id':'mcp-stock-return-0001'}
            with mock.patch.object(app.store,'save',side_effect=OSError('receiving save refused')):
                with self.assertRaisesRegex(ValueError,'receiving save refused'):call('fund_stock',**request)
            release={'reservation_id':request['request_id'],'request_id':'mcp-stock-release-0001'}
            self.assertFalse(call('release_stock',**release)['replayed'])
            self.assertTrue(call('release_stock',**release)['replayed'])
            request['request_id']='mcp-stock-fund-0001'
            funded=call('fund_stock',**request)
            self.assertEqual({'oak':2.},funded['state']['stock_kg'])
            self.assertTrue(call('fund_stock',**request)['replayed'])
            source=next(r for r in funded['stock_sources'] if r['material']=='oak' and r['pool']=='personal')
            self.assertEqual(3.,source['mass_kg'])
            self.assertEqual([],funded['stock_reservations'])
            self.assertEqual(app.room.fabrication_record,app.store.load('fabrication').fabrication_record)


@unittest.skipUnless(ENGINE and ENGINE.is_file(),'BANJO_LIVE_ENGINE is required')
class CollectedStock(unittest.TestCase):
    setUp=flow.GoodsJourney.setUp
    start=flow.GoodsJourney.start
    stop=flow.GoodsJourney.stop
    get=flow.GoodsJourney.get
    post=flow.GoodsJourney.post
    join=flow.GoodsJourney.join
    setup_world=flow.GoodsJourney.setup_world
    batch=flow.GoodsJourney.batch
    personal=flow.GoodsJourney.personal

    def tearDown(self):
        if getattr(self,'chrome',None):self.chrome.close()
        flow.GoodsJourney.tearDown(self)

    def test_collected_stock_private_escrow_browser_return_finish_and_reopen(self):
        self.assertTrue(flow.qa_browser.CHROME.is_file(),'Chrome required for player recovery acceptance')
        world,owner,app,_,_,_=self.batch(process=False)
        # Finite source explicitly authored for this isolated acceptance fixture.
        app.room.spec['bodies'].append({'name':'stock fixture battery host','shape':'box',
            'material':'iron','size_mm':[100,100,100],'center_mm':[25000,50,25000],'anchored':True})
        app.room.spec.setdefault('machines',{}).setdefault('stores',[]).append({
            'name':'stock fixture battery','body':'stock fixture battery host',
            'capacity_j':2000.,'charge_j':2000.,'max_power_w':300.,'voltage_v':24.})
        app.live.open(app,{'spec':app.room.spec})
        pile=next(p for p in app.brains.goods.stockpiles if (p.get('holds') or {}).get('oak',0)>25)
        at=pile['at_m'];sid=app.live.session.id
        floor=app.live.act({'session':sid,'op':'survey','at':at})['survey']['ground_m']
        self.post('/api/world/goods/collect',{'session':sid,'pile':pile['name'],
            'request_id':'stock-collected-oak','person':{'eyes_m':[at[0],floor+1.62,at[1]],'facing':[0,0,-1]}},world)
        self.assertEqual({'oak':25.},self.personal(app,owner))
        peer=self.join(world,'Private stock peer')
        context={'scene':app.room.scene,'session':sid}
        self.post('/api/world/fabrication/configure',{**context,'settings':settings(stock_kg={},energy_j=0),
            'request_id':'collected-config-0001'},world)
        claims=deepcopy(app.room.goods_claims)
        self.assertEqual(sid,self.post('/api/world/workshop/context',{},world)['session'])
        with self.assertRaises(urllib.error.HTTPError):
            self.post('/api/world/workshop/preview',{},world)
        def reserve(ident):
            reading=self.post('/api/world/fabrication/state',context,world)
            source=next(r for r in reading['stock_sources'] if r['pool']=='personal' and r['material']=='oak')
            request={**context,'material':'oak','mass_kg':1.,'pool':'personal','rack_hash':source['rack_hash'],
                'revision':reading['state']['revision'],'request_id':ident}
            with mock.patch.object(app.store,'save',side_effect=OSError('injected receiving disk failure')):
                with self.assertRaises(urllib.error.HTTPError) as failed:
                    self.post('/api/world/fabrication/fund_stock',request,world)
            self.assertEqual(503,failed.exception.code)
            return request
        first=reserve('collected-return-0001')
        self.assertEqual({'oak':24.},self.personal(app,owner))
        self.assertEqual([],self.post('/api/workshop/inventory',{},world,peer['token'])['fabrication_reservations'])
        with self.assertRaises(urllib.error.HTTPError):
            self.post('/api/world/fabrication/fund_stock',first,world,peer['token'])
        with self.assertRaises(urllib.error.HTTPError):
            self.post('/api/world/fabrication/fund_stock',{**first,'source_owner':peer['id']},world)
        self.assertEqual({},self.personal(app,peer))
        chrome=flow.qa_browser.Chrome(1280,800);self.chrome=chrome
        p=chrome.page;p.send('Page.enable');p.send('Runtime.enable')
        p.send('Page.addScriptToEvaluateOnNewDocument',{'source':
            f'localStorage.setItem("banjo.player.{world}",{json.dumps(owner["token"])});'})
        def wait(expr):
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                if p.evaluate('Boolean('+expr+')'):return
                time.sleep(.1)
            self.fail(expr+'; '+str(p.evaluate('({text:document.body.innerText.slice(-1500),notice:document.querySelector("#ws-notice")?.textContent})'))+'; exceptions '+str([e for e in p.events if e.get('method')=='Runtime.exceptionThrown']))
        url=self.base+f'/world?world={world}&workshop=1&tab=inventory'
        p.send('Page.navigate',{'url':url})
        wait('document.querySelector("[data-stock-reservation]")')
        wait('document.querySelector("#ws-inv-energy")?.dataset.updated')
        p.evaluate('document.querySelector("[data-stock-reservation]").scrollIntoView({block:"center"})')
        out=ROOT/'build/resource-flow';out.mkdir(parents=True,exist_ok=True)
        (out/'stock-reservation.png').write_bytes(base64.b64decode(p.send('Page.captureScreenshot',{'format':'png'})['data']))
        meter_time=int(p.evaluate('document.querySelector("#ws-inv-energy").dataset.updated'))
        p.evaluate('[...document.querySelectorAll("#ws-inv-reserved button")].find(b=>b.textContent==="Return to stock").click()')
        wait('!document.querySelector("[data-stock-reservation]")')
        wait(f'Number(document.querySelector("#ws-inv-energy").dataset.updated)>{meter_time}')
        self.assertEqual({'oak':25.},self.personal(app,owner))
        second=reserve('collected-finish-0001')
        p.send('Page.navigate',{'url':url})
        wait('document.querySelector("[data-stock-reservation]")')
        wait('document.querySelector("#ws-inv-energy")?.dataset.updated')
        meter_time=int(p.evaluate('document.querySelector("#ws-inv-energy").dataset.updated'))
        p.evaluate('[...document.querySelectorAll("#ws-inv-reserved button")].find(b=>b.textContent==="Finish transfer").click()')
        wait('!document.querySelector("[data-stock-reservation]")')
        wait(f'Number(document.querySelector("#ws-inv-energy").dataset.updated)>{meter_time}')
        self.assertEqual({'oak':24.},self.personal(app,owner))
        self.assertEqual({'oak':1.},app.room.fabrication_record['stock_kg'])
        self.assertEqual(claims,app.store.load(app.room.scene).goods_claims)
        self.assertEqual([], [e for e in p.events if e.get('method')=='Runtime.exceptionThrown'])
        chrome.close();self.chrome=None
        # Complete a real native product from that collected kilogram and battery.
        def call(op,**body):return self.post('/api/world/fabrication/'+op,{**context,**body},world)
        reading=call('state');source=next(s for s in reading['energy_sources'] if s['name']=='stock fixture battery')
        call('connect_energy',store=source['id'],store_hash=source['store_hash'],power_w=250.,
             revision=reading['state']['revision'],request_id='collected-connect-0001')
        call('wait',seconds=1);reading=call('state')
        source=next(s for s in reading['energy_sources'] if s['name']=='stock fixture battery')
        result=call('fund_energy',store_hash=source['store_hash'],joules=100.,
             revision=reading['state']['revision'],request_id='collected-energy-0001')
        context['session']=result['session']
        design=candidate();design['component_overrides']['@construction']['added'][0].update(
            size_m=[.1,.1,.1],center_m=[0,.05,0])
        call('start',candidate=design,stock_kg=1.,revision=result['state']['revision'],request_id='collected-job-0001')
        call('wait',seconds=1)
        preview=call('preview',job_id='collected-job-0001',position_m=[13,-7])
        result=call('commit',job_id='collected-job-0001',preview_id=preview['preview_id'],request_id='collected-install-0001')
        context['session']=result['session']
        self.assertAlmostEqual(.7,result['mass_kg'],places=9)
        self.assertEqual(claims,app.store.load(app.room.scene).goods_claims)
        final=deepcopy(app.room.fabrication_record)
        self.stop();self.start()
        self.post('/api/world/player/join',{'token':owner['token']},world)
        self.post('/api/world/open',{},world)
        app=self.app.hub.get(world);context['session']=app.live.session.id
        self.assertEqual({'oak':24.},self.personal(app,owner))
        reading=self.post('/api/world/fabrication/state',context,world)
        self.assertEqual(final['stock_kg'],reading['state']['stock_kg'])
        self.assertEqual('installed',reading['state']['jobs']['collected-job-0001']['status'])
        self.assertEqual([],reading['stock_reservations'])
        self.assertTrue(self.post('/api/world/fabrication/fund_stock',second,world)['replayed'])
        self.assertEqual(claims,app.room.goods_claims)
        source=next(r for r in reading['stock_sources'] if r['material']=='oak' and r['pool']=='shared')
        self.assertEqual(12.4,source['mass_kg'])
        funded=self.post('/api/world/fabrication/fund_stock',{**context,'material':'oak','mass_kg':1.,'pool':'shared',
            'rack_hash':source['rack_hash'],'revision':reading['state']['revision'],'request_id':'explicit-shared-stock-0001'},world)
        self.assertEqual({'oak':1.},funded['state']['stock_kg'])
        self.assertEqual({'oak':24.},self.personal(app,owner))
        self.assertEqual({},self.personal(app,peer))
        self.assertEqual(11.4,next(r for r in funded['stock_sources'] if r['material']=='oak' and r['pool']=='shared')['mass_kg'])


if __name__=='__main__':unittest.main()
