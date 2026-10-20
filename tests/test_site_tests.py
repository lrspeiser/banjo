"""Real co-hosted routing/process isolation plus bounded runtime-package checks."""
import argparse
import hashlib
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid
import urllib.error

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import test_site
ci_engine_spec=importlib.util.spec_from_file_location('ci_engine',ROOT/'scripts/ci-engine.py')
ci_engine=importlib.util.module_from_spec(ci_engine_spec);ci_engine_spec.loader.exec_module(ci_engine)
parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--engine');parser.add_argument('--bundle',type=Path)
args,remaining=parser.parse_known_args();ENGINE=Path(args.engine or os.environ.get('BANJO_LIVE_ENGINE',''))


class Bundles(unittest.TestCase):
    def test_main_ci_reuse_requires_a_complete_successful_staging_run_for_the_same_revision(self):
        revision='a'*40
        run=dict(id=42,head_sha=revision,head_branch='codex/staging',event='push',status='completed',
                 conclusion='success',path='.github/workflows/ci.yml',repository={'full_name':'lrspeiser/banjo'})
        self.assertTrue(ci_engine.verified_staging_run(run,revision))
        for key,value in [('id',None),('head_sha','b'*40),('head_branch','main'),('event','pull_request'),
                          ('status','in_progress'),('conclusion','failure'),('path','.github/workflows/other.yml'),
                          ('repository',{'full_name':'another/banjo'})]:
            changed=dict(run);changed[key]=value
            self.assertFalse(ci_engine.verified_staging_run(changed,revision),(key,value))
        with patch.object(ci_engine.subprocess,'check_output',return_value=json.dumps({'workflow_runs':[run]})):
            self.assertEqual(ci_engine.main_reuse_proof(revision,'refs/heads/main','push'),42)
        with patch.object(ci_engine.subprocess,'check_output',side_effect=OSError('unavailable')):
            self.assertIsNone(ci_engine.main_reuse_proof(revision,'refs/heads/main','push'))
        with patch.object(ci_engine.subprocess,'check_output',side_effect=AssertionError('must not query')):
            self.assertIsNone(ci_engine.main_reuse_proof(revision,'refs/heads/codex/staging','push'))
            self.assertIsNone(ci_engine.main_reuse_proof(revision,'refs/pull/1/merge','pull_request'))

    def test_shared_ci_engine_is_bound_to_revision_platform_and_exact_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            binary=Path(folder)/'banjo_live_world_run';binary.write_bytes(b'fixture native bytes')
            receipt=Path(folder)/'engine-receipt.json';revision='a'*40
            original=ci_engine.engine_receipt(binary,revision)
            receipt.write_text(json.dumps(original))
            self.assertEqual(ci_engine.verify_engine(binary,receipt,revision),original)
            with self.assertRaises(ValueError):ci_engine.verify_engine(binary,receipt,'b'*40)
            for key,value in [('platform','wrong'),('machine','wrong'),('sha256','0'*64),('size',0)]:
                changed=dict(original);changed[key]=value;receipt.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):ci_engine.verify_engine(binary,receipt,revision)
            receipt.write_text(json.dumps(original));binary.write_bytes(b'changed native bytes')
            with self.assertRaises(ValueError):ci_engine.verify_engine(binary,receipt,revision)
            with self.assertRaises(ValueError):ci_engine.engine_receipt(binary,'branch-name')

    def test_packaged_revision_does_not_consult_a_parent_checkout(self):
        spec=importlib.util.spec_from_file_location('receipt_server',ROOT/'scripts/voxel-lab.py')
        lab=importlib.util.module_from_spec(spec);spec.loader.exec_module(lab)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'bin').mkdir()
            (root/'test-build.json').write_text('{}')
            (root/'bin/build-receipt.json').write_text(json.dumps(dict(revision='a'*40,branch='codex/staging')))
            with patch.object(lab,'ROOT',root),patch.dict(os.environ,{},clear=True),patch.object(lab.subprocess,'check_output') as git:
                self.assertEqual(lab.repository_state(),('a'*40,False))
                self.assertEqual(lab.repository_branch(),'codex/staging')
                git.assert_not_called()

    def test_redirects_cannot_leave_the_test_mount(self):
        for value in ('/test/play', '/test/machine?design=example'):
            self.assertTrue(test_site.scoped_redirect(value))
        for value in ('/play', '//banjo.is/play', 'https://banjo.is/test/play', '/test\\play',
                      '/test/../api/profile', '/test/%2e%2e/api/profile'):
            self.assertFalse(test_site.scoped_redirect(value))

    def archive(self,path,files,revision='a'*40,extra=None):
        manifest=dict(schema=test_site.SCHEMA,revision=revision,branch=test_site.BRANCH,
            platform=sys.platform,native='bin/banjo_live_world_run'+('.exe' if os.name=='nt' else ''),
            files={name:hashlib.sha256(data).hexdigest() for name,data in files.items()})
        files=dict(files,**{'test-build.json':json.dumps(manifest).encode()})
        with tarfile.open(path,'w:gz') as out:
            for name,data in files.items():
                info=tarfile.TarInfo(name);info.size=len(data);out.addfile(info,io.BytesIO(data))
            if extra:out.addfile(extra)

    def test_checksums_identity_and_expected_files_are_required_before_install(self):
        native='bin/banjo_live_world_run'+('.exe' if os.name=='nt' else '')
        with tempfile.TemporaryDirectory() as folder:
            cache=Path(folder)/'cache';archive=Path(folder)/'bundle.tar.gz'
            self.archive(archive,{native:b'unit fixture','scripts/voxel-lab.py':b'fixture'})
            root=test_site.install_archive(archive,cache,'a'*40)
            self.assertEqual(test_site.checked_build(root)['revision'],'a'*40)
            (root/native).write_bytes(b'tampered')
            with self.assertRaises(ValueError):test_site.checked_build(root)
            with self.assertRaises(ValueError):test_site.install_archive(archive,cache,'b'*40)

    def test_archive_paths_links_and_duplicates_never_escape_the_managed_cache(self):
        native='bin/banjo_live_world_run'+('.exe' if os.name=='nt' else '')
        with tempfile.TemporaryDirectory() as folder:
            for name,kind in (('../outside',tarfile.REGTYPE),('/absolute',tarfile.REGTYPE),
                              ('bad\\..\\outside',tarfile.REGTYPE),('linked',tarfile.SYMTYPE),
                              ('linked',tarfile.LNKTYPE),(native,tarfile.REGTYPE)):
                cache=Path(folder)/uuid.uuid4().hex;archive=Path(folder)/'bundle.tar.gz'
                member=tarfile.TarInfo(name);member.type=kind;member.linkname='../../outside'
                self.archive(archive,{native:b'fixture'},extra=member)
                with self.subTest(name=name,kind=kind),self.assertRaises(ValueError):
                    test_site.install_archive(archive,cache,'a'*40)
                self.assertFalse((Path(folder)/'outside').exists())
                self.assertEqual(list(cache.iterdir()),[])
            with self.assertRaises(ValueError):test_site.remove_owned(Path(folder)/'cache',Path(folder))


class CoHosted(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ENGINE.is_file():raise RuntimeError('pass --engine: the verified native executable')
        spec=importlib.util.spec_from_file_location('cohost_server',ROOT/'scripts/voxel-lab.py')
        lab=importlib.util.module_from_spec(spec);spec.loader.exec_module(lab)
        cls.folder=tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cache=Path(cls.folder.name)/'cache';cls.bundle=None
        if args.bundle:
            with tarfile.open(args.bundle,'r:gz') as archive:
                manifest=json.load(archive.extractfile('test-build.json'))
            cls.bundle=test_site.install_archive(args.bundle,cache,manifest['revision'])
        cls.server=lab.Server(('127.0.0.1',0),ENGINE.resolve(),Path(cls.folder.name)/'live-logs',site='game',public=True,
            public_hosts='banjo.is',test_builds=cache,test_auto=False,test_source=None if cls.bundle else ROOT)
        threading.Thread(target=cls.server.serve_forever,daemon=True).start()
        deadline=time.monotonic()+25
        while not cls.server.test_site.status()['ready'] and time.monotonic()<deadline:time.sleep(.1)
        if not cls.server.test_site.status()['ready']:
            status=cls.server.test_site.status()
            cls.server.shutdown();cls.server.server_close();cls.folder.cleanup()
            raise RuntimeError(status)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.machines.close_all();cls.server.server_close();cls.folder.cleanup()

    def request(self,path,body=None,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=15)
        connection.request('POST' if body is not None else 'GET',path,
            body=json.dumps(body).encode() if body is not None else None,
            headers={'Host':'banjo.is','Content-Type':'application/json',**(headers or {})})
        response=connection.getresponse();result=(response.status,response.read(),dict(response.getheaders()))
        connection.close();return result

    def post(self,path,body,headers=None):
        status,data,out=self.request(path,body,headers);return status,json.loads(data),out

    def test_html_modules_navigation_manifest_and_cookie_stay_under_test(self):
        if self.bundle:
            status,checkpoint,_=self.request('/test/api/checkpoint');checkpoint=json.loads(checkpoint)
            self.assertEqual(checkpoint['website_revision'],test_site.checked_build(self.bundle)['revision'])
            self.assertFalse(checkpoint['local_changes']);self.assertFalse(checkpoint['restart_pending'])
        status,html,headers=self.request('/test/play')
        self.assertEqual(status,200)
        self.assertIn(b'data-banjo-base="/test"',html)
        self.assertIn(b'src="/test/machine.js"',html)
        self.assertIn(b'href="/test/machine"',html)
        self.assertIn('connect-src https://banjo.is/test/',headers['Content-Security-Policy'])
        self.assertNotIn('posthog.com',headers['Content-Security-Policy'])
        status,html,_=self.request('/play')
        self.assertEqual(status,200);self.assertNotIn(b'id="environment-badge">TEST',html)
        for name in ('machine.js','three.module.js','site-paths.mjs','machine-view.mjs','analytics.mjs'):
            self.assertEqual(self.request('/test/'+name)[0],200)
        status,manifest,_=self.request('/test/manifest.webmanifest')
        manifest=json.loads(manifest)
        self.assertEqual((status,manifest['start_url'],manifest['scope']),(200,'/test/play','/test/'))
        self.assertEqual(self.request('/test')[2]['Location'],'/test/play')
        self.assertEqual(self.request('/test/../../api/profile')[0],404)

    def test_test_saves_are_separate_in_the_same_database_and_restore(self):
        visitor=str(uuid.uuid4())
        self.post('/api/profile',dict(op='create',visitor=visitor,profile={'design':'Live'}))
        status,opened,headers=self.post('/test/api/profile',dict(op='open',cached_visitor=visitor),
            {'Cookie':'banjo-visitor='+visitor,'Origin':'https://banjo.is'})
        self.assertEqual((status,opened['profile']),(200,{}))
        self.assertIn('banjo-test-visitor=',headers['Set-Cookie']);self.assertIn('Path=/test/',headers['Set-Cookie'])
        status,saved,_=self.post('/test/api/profile',dict(op='save',visitor=visitor,revision=0,profile={'design':'Test'}))
        self.assertEqual(status,200)
        self.assertEqual(self.post('/api/profile',dict(op='open',visitor=visitor))[1]['profile'],{'design':'Live'})
        self.assertEqual(self.post('/test/api/profile',dict(op='open',visitor=visitor))[1]['profile'],{'design':'Test'})
        self.assertEqual(self.post('/test/api/profile',dict(op='save',visitor=visitor,revision=0,profile={}))[0],409)
        self.assertTrue(saved['storage']['shared'])
        self.assertEqual(self.post('/test/api/profile',dict(op='open'),{'Origin':'https://evil.example'})[0],400)

    def test_test_session_cannot_control_production_engine_and_test_stop_keeps_live_available(self):
        status,opened,_=self.post('/api/machine',dict(op='level_open',level='easy-weight',placements=[]))
        self.assertEqual(status,200);session=opened['session']
        try:
            self.assertEqual(self.post('/test/api/machine',dict(op='play',session=session,running=True))[0],410)
            self.assertEqual(self.post('/api/machine',dict(op='frame',session=session,after=0))[0],200)
            manager=self.server.test_site
            manager._close_process(manager.process)
            self.assertEqual(self.request('/test/play')[0],503)
            self.assertEqual(self.request('/play')[0],200)
            self.assertEqual(self.post('/api/machine',dict(op='frame',session=session,after=0))[0],200)
            manager.activate(self.bundle or ROOT,development=self.bundle is None)
        finally:self.post('/api/machine',dict(op='close',session=session))

    def test_stopped_test_child_recovers_the_verified_build_while_new_package_is_missing(self):
        manager=self.server.test_site
        root,revision,pid=manager.root,manager.revision,manager.process.pid
        status,opened,_=self.post('/api/machine',dict(op='level_open',level='easy-weight',placements=[]))
        self.assertEqual(status,200)
        try:
            with patch.object(manager,'_download_latest',side_effect=urllib.error.HTTPError('test-package',404,'pending',{},None)) as missing:
                manager._close_process(manager.process)
                manager.auto=True
                deadline=time.monotonic()+12
                while time.monotonic()<deadline and not (manager.status()['ready'] and missing.called):time.sleep(.1)
                self.assertTrue(manager.status()['ready'],manager.status())
                self.assertTrue(missing.called)
                self.assertEqual((manager.root,manager.revision),(root,revision))
                self.assertNotEqual(manager.process.pid,pid)
                self.assertEqual(self.request('/test/play')[0],200)
                self.assertEqual(self.post('/api/machine',dict(op='frame',session=opened['session'],after=0))[0],200)
        finally:
            manager.auto=False
            if not manager.status()['ready']:manager.activate(self.bundle or ROOT,development=self.bundle is None)
            self.post('/api/machine',dict(op='close',session=opened['session']))


if __name__=='__main__':unittest.main(argv=[__file__,*remaining],verbosity=2)
