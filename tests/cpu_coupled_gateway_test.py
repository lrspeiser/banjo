"""Hosted password/host/origin checks, real CPU session, isolation and exact logs."""
from unittest.mock import patch
import argparse,http.cookiejar,importlib.util,json,os,sys,tempfile,threading,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
p=argparse.ArgumentParser();p.add_argument('--library',type=Path,required=True);p.add_argument('--native',type=Path,required=True);a=p.parse_args()
os.environ['BANJO_COUPLED_CPU_LIBRARY']=str(a.library.resolve())
spec=importlib.util.spec_from_file_location('cpu_gateway',ROOT/'scripts/voxel-lab.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as folder:
    server=m.Server(('127.0.0.1',0),a.native.resolve(),Path(folder),cpu_library=a.library.resolve(),password='regression-only-password',public_host='test.example')
    threading.Thread(target=server.serve_forever,daemon=True).start();base='http://127.0.0.1:'+str(server.server_port)
    client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def request(path,data=None,headers=None,auth=True):
        req=urllib.request.Request(base+path,None if data is None else json.dumps(data).encode(),headers or ({'Content-Type':'application/json'} if data is not None else {}))
        try:
            r=(client.open if auth else urllib.request.urlopen)(req,timeout=120);return r.status,r.read(),r.headers
        except urllib.error.HTTPError as e:return e.code,e.read(),e.headers
    def command(data):
        status,body,_=request('/api/coupled',data);reply=json.loads(body);assert status==200,(status,reply);return reply
    try:
        assert request('/api/checkpoint',auth=False)[0]==401
        for _ in range(20):assert request('/api/coupled',{'op':'create','declaration':{}},auth=False)[0]==401
        assert request('/login')[0]==200
        # Login follows redirect to the protected machine page with the same
        # cookie; the physics lab stays one link away behind the same login.
        code,html,headers=request('/login',{'password':'regression-only-password'});assert code==200 and b'Banjo Machine' in html
        code,html,_=request('/coupled');assert code==200 and b'Physics lab' in html
        assert request('/api/checkpoint',headers={'Host':'attacker.example'})[0]==403
        assert request('/api/coupled',{'op':'create','declaration':{}},headers={'Content-Type':'application/json','Origin':'https://attacker.example'})[0]==400
        build=json.loads(request('/api/checkpoint')[1]);assert build['cpu_coupled_available'] and not build['gpu_available']
        # Hosted identity follows the image's source + implementation + native
        # receipt, rather than an older local measurement checkpoint.
        receipt={'schema':'banjo.cpu-image-identity.v1','cpu_source_sha256':build['cpu_coupled_source_sha256'],
                 'cpu_implementation_sha256':build['cpu_coupled_implementation_sha256'],'native_sha256':build['native_sha256']}
        read_text=Path.read_text
        def receipt_read(path,*args,**kwargs):
            return json.dumps(receipt) if path==ROOT/'bin/build-receipt.json' else read_text(path,*args,**kwargs)
        with patch.object(Path,'read_text',receipt_read):
            observed=server.checkpoint_status()
            assert observed['cpu_image_identity_verified'] and observed['cpu_coupled_source_verified']
            for field in ('cpu_source_sha256','cpu_implementation_sha256','native_sha256','schema'):
                original=receipt[field];receipt[field]='mismatch';observed=server.checkpoint_status()
                assert not observed['cpu_image_identity_verified'] and not observed['cpu_coupled_source_verified']
                receipt[field]=original
        x=command({'op':'create','declaration':{'solver_backend':'cpu-implicit-body','experiment':'freefall','height_m':10.,'representation_policy':'partitioned-flight'}});assert x['ok'] and not x['state']['qualification']['gpu'];key=x['session']
        y=command({'op':'create','declaration':{'experiment':'freefall','height_m':10.}});other=y['session']
        flying=command({'op':'advance','session':key,'steps':16})['state'];assert flying['time_s']>0
        assert all(all(all(v==0 for v in row) for row in account['interaction_wrench_n_nm']) for account in flying['substep_accounts']),'free flight must not fabricate contact heat'
        assert command({'op':'snapshot','session':other})['state']['time_s']==0
        saved=command({'op':'export','session':key})['checkpoint'];r=command({'op':'restore','checkpoint':saved});assert r['ok']
        assert command({'op':'export','session':r['session']})['checkpoint']==saved
        sheet=command({'op':'create','declaration':{'material':'glass','height_m':10.,'pipeline':'local-jacobian','representation_policy':'partitioned-flight'}})
        sheet_key=sheet['session'];untouched=command({'op':'export','session':sheet_key})['checkpoint']
        modes=command({'op':'inspect_modes','session':sheet_key})
        assert modes['ok'] and modes['mode_preparation']['retained_modes']==54
        assert not modes['mode_preparation']['execution_admitted']
        guard=modes['mode_preparation']['continuous_contact_envelope']
        assert guard['native_sites']>0 and guard['possible_contact_changes']>0 and not guard['execution_admitted']
        assert command({'op':'export','session':sheet_key})['checkpoint']==untouched
        assert command({'op':'snapshot','session':other})['state']['time_s']==0
        mode_log=[json.loads(row) for row in request('/api/log/'+sheet_key)[1].splitlines()]
        assert any(row.get('response',{}).get('mode_preparation',{}).get('state_key')==modes['mode_preparation']['state_key'] for row in mode_log)
        assert request('/api/coupled',{'op':'inspect_modes','session':sheet_key,'steps':1})[0]==400
        refused=command({'op':'inspect_modes','session':other});assert not refused['ok'] and refused['state']['time_s']==0
        assert command({'op':'close','session':sheet_key})['ok']
        for k in (other,r['session']):assert command({'op':'close','session':k})['ok']
        log=json.loads(request('/api/log/'+key)[1].splitlines()[-1]);assert log['response']['checkpoint']==saved
        assert command({'op':'close','session':key})['ok']
        assert not command({'op':'create','declaration':{'device':'cuda:0'}})['ok']
        assert request('/api/gpu',{'op':'create','declaration':{}})[0]==400
        # HTTPS same-origin remains usable through the reverse proxy.
        d={'op':'create','declaration':{'experiment':'freefall'}}
        code,body,_=request('/api/coupled',d,headers={'Content-Type':'application/json','Origin':'https://127.0.0.1:'+str(server.server_port)});assert code==200 and json.loads(body)['ok']
        print('PASS hosted auth / cross-origin / CPU sessions / resume / journal / no CUDA fallback')
    finally:
        for s in server.sessions.values():s.close()
        server.shutdown();server.server_close()
