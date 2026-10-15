"""A trusted staging build on the existing server, mounted under /test.

Only the test process is replaced. Runtime packages come from this repository's
CI release assets; they are bounded, checked and never extracted over live code.
This is process separation/resource budgeting, not a sandbox for hostile code.
"""
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import unquote, urlsplit
import uuid

SCHEMA = 'banjo.test-build.v1'
MAX_ARCHIVE = 64 * 1024 * 1024
MAX_EXPANDED = 128 * 1024 * 1024
MAX_RESPONSE = 32 * 1024 * 1024
REPO = 'lrspeiser/banjo'
BRANCH = 'codex/staging'


def scoped_redirect(value):
    target = urlsplit(value)
    return (not target.scheme and not target.netloc and
            (target.path == '/test' or target.path.startswith('/test/')) and
            '\\' not in unquote(value) and '..' not in unquote(target.path).split('/'))


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or '\\' in name or path.is_absolute() or '..' in path.parts or
            str(path) != name.rstrip('/') or name.startswith('.')):
        raise ValueError('Unsafe test package path')
    return path


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked_build(root, expected=None):
    root = Path(root).resolve()
    receipt = root/'test-build.json'
    if receipt.stat().st_size > 1_000_000:
        raise ValueError('Test manifest is too large')
    data = json.loads(receipt.read_text(encoding='utf-8'))
    if not isinstance(data,dict):raise ValueError('Invalid test manifest')
    if (data.get('schema') != SCHEMA or data.get('branch') != BRANCH or
            data.get('platform') != sys.platform or
            not isinstance(data.get('revision'),str) or not re.fullmatch('[0-9a-f]{40}', data['revision']) or
            expected and data['revision'] != expected):
        raise ValueError('Test package identity does not match')
    files = data.get('files')
    if not isinstance(files, dict) or not 1 <= len(files) <= 5000:
        raise ValueError('Invalid test manifest files')
    for name, checksum in files.items():
        safe_name(name)
        path = root/name
        if (not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root) or
                not isinstance(checksum,str) or not re.fullmatch('[0-9a-f]{64}', checksum) or file_hash(path) != checksum):
            raise ValueError('Test package file checksum failed')
    actual = {str(path.relative_to(root)).replace('\\','/') for path in root.rglob('*') if path.is_file()}
    if actual != set(files) | {'test-build.json'}:
        raise ValueError('Unexpected test package files')
    native = data.get('native')
    if not isinstance(native,str) or native not in files or native != 'bin/banjo_live_world_run' + ('.exe' if os.name == 'nt' else ''):
        raise ValueError('Missing native test engine')
    return data


def remove_owned(root, target):
    # In particular, never recursively remove a computed Windows path until
    # its resolved absolute parent is the explicitly managed cache directory.
    root, target = Path(root).resolve(), Path(target).resolve()
    if target == root or target.parent != root:
        raise ValueError('Cleanup target is outside the test cache')
    if target.exists():shutil.rmtree(target)


def install_archive(archive, cache, expected):
    cache = Path(cache).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    if not re.fullmatch('[0-9a-f]{40}', expected):raise ValueError('Invalid revision')
    if Path(archive).stat().st_size > MAX_ARCHIVE:raise ValueError('Test archive is too large')
    target = cache/expected
    if target.exists():
        checked_build(target, expected)
        return target
    incoming = cache/('_incoming_' + uuid.uuid4().hex)
    incoming.mkdir()
    try:
        with tarfile.open(archive,'r:gz') as bundle:
            members = bundle.getmembers()
            size = sum(member.size for member in members)
            if len(members) > 5100 or size > MAX_EXPANDED:
                raise ValueError('Expanded test package is too large')
            if shutil.disk_usage(cache).free < size + 32 * 1024 * 1024:
                raise ValueError('Not enough space for the test update')
            names=set()
            for member in members:
                safe_name(member.name)
                if member.name in names or not (member.isfile() or member.isdir()):
                    raise ValueError('Duplicate or linked test package entry')
                names.add(member.name)
                path=incoming/member.name
                if not path.resolve().is_relative_to(incoming):raise ValueError('Test path escaped cache')
                if member.isdir():path.mkdir(parents=True,exist_ok=True);continue
                path.parent.mkdir(parents=True,exist_ok=True)
                with bundle.extractfile(member) as source,path.open('wb') as out:shutil.copyfileobj(source,out)
                path.chmod(0o755 if member.name.startswith('bin/banjo_live_world_run') else 0o644)
        checked_build(incoming, expected)
        incoming.rename(target)
        return target
    finally:
        if incoming.exists():remove_owned(cache,incoming)


class TestSite:
    def __init__(self, cache, upstream, hosts='', auto=True, source=None, native=None):
        self.cache=Path(cache).resolve();self.cache.mkdir(parents=True,exist_ok=True)
        self.upstream,self.hosts,self.auto,self.source,self.native=upstream,hosts,auto,source,native
        self.lock=threading.RLock();self.stop=threading.Event();self.process=None;self.port=None
        self.revision=None;self.root=None;self.previous=None;self.error=None;self.updating=False
        self.busy=threading.BoundedSemaphore(8)
        self.thread=None

    def start(self):
        self.thread=threading.Thread(target=self._run,daemon=True);self.thread.start()

    def status(self):
        with self.lock:
            return dict(ready=self.process is not None and self.process.poll() is None,
                        revision=self.revision,branch=BRANCH,updating=self.updating,last_error=self.error)

    def _close_process(self, process):
        if process is None:return
        if os.name=='nt':
            if process.poll() is None:
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL,timeout=10)
        else:
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name!='nt':
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            else:process.kill()
            process.wait(timeout=5)

    def activate(self, root, development=False):
        if self.stop.is_set():raise RuntimeError('Test runner is closing')
        root=Path(root).resolve()
        manifest=None if development else checked_build(root)
        native=Path(self.native).resolve() if development else root/manifest['native']
        revision=None if development else manifest['revision']
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
        logs=self.cache.parent/'test-logs';logs.mkdir(parents=True,exist_ok=True)
        env=dict(os.environ)
        # A branch has its own engine/session pool and save scope, never a disk
        # migration. Test reports do not drain the production Linear outbox.
        for key in ('LINEAR_API_KEY','BANJO_PROFILE_DB','BANJO_PASSWORD'):env.pop(key,None)
        env.update(BANJO_ENVIRONMENT='test',BANJO_BASE_PATH='/test',BANJO_TEST_SITE='0',
            BANJO_PUBLIC_HOSTS=self.hosts,BANJO_PUBLIC_HOST='',
            BANJO_PROFILE_UPSTREAM=self.upstream,BANJO_PROFILE_NAMESPACE='test',
            BANJO_MACHINE_SESSIONS='1',BANJO_CHAT_PER_HOUR='3',BANJO_CHAT_PER_DAY='30',
            BANJO_PREVIEWS_PER_HOUR='60',BANJO_PREVIEWS_PER_DAY='300',
            BANJO_TRIALS_PER_HOUR='3',BANJO_TRIALS_PER_DAY='30',
            RENDER_GIT_BRANCH=BRANCH,PYTHONDONTWRITEBYTECODE='1')
        if revision:env['RENDER_GIT_COMMIT']=revision
        with (logs/'server.log').open('ab') as stream:
            process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('test-child.py')),str(root),
                '--native',str(native),'--host','127.0.0.1','--port',str(port),
                '--logs',str(logs/'machines'),'--site','game','--public'],env=env,cwd=root,
                stdout=stream,stderr=stream,start_new_session=os.name!='nt',
                creationflags=(subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP) if os.name=='nt' else 0)
        try:
            deadline=time.monotonic()+20
            while time.monotonic()<deadline and process.poll() is None:
                try:
                    connection=http.client.HTTPConnection('127.0.0.1',port,timeout=1)
                    connection.request('GET','/test/api/checkpoint',headers={'Host':'127.0.0.1'})
                    response=connection.getresponse();checkpoint=json.loads(response.read());connection.close()
                    if (response.status==200 and checkpoint.get('environment')=='test' and
                            checkpoint.get('base_path')=='/test' and
                            (development or checkpoint.get('website_revision')==revision and
                             checkpoint.get('server_revision')==revision and not checkpoint.get('restart_pending') and
                             checkpoint.get('engine_sha256')==manifest['files'][manifest['native']])):
                        break
                except (OSError,ValueError):pass
                if self.stop.wait(.15):raise RuntimeError('Test runner is closing')
            else:raise RuntimeError('Test build did not become healthy')
            with self.lock:
                if self.stop.is_set():raise RuntimeError('Test runner is closing')
                old=self.process;self.previous=self.root;self.root=root
                self.process,self.port,self.revision=process,port,checkpoint['website_revision']
                self.error=None
            self._close_process(old)
        except BaseException:
            self._close_process(process);raise

    def _download_latest(self):
        request=urllib.request.Request(f'https://api.github.com/repos/{REPO}/git/ref/heads/{BRANCH}',
            headers={'User-Agent':'Banjo-test-runner','Accept':'application/vnd.github+json'})
        with urllib.request.urlopen(request,timeout=20) as response:
            data=response.read(100_001)
        if len(data)>100_000:raise ValueError('Invalid branch reply')
        revision=json.loads(data)['object']['sha']
        if not re.fullmatch('[0-9a-f]{40}',revision):raise ValueError('Invalid staging revision')
        if revision==self.revision and self.status()['ready']:return
        target=self.cache/revision
        if not target.exists():
            archive=self.cache/('_download_'+uuid.uuid4().hex+'.tar.gz')
            try:
                url=f'https://github.com/{REPO}/releases/download/banjo-test-{revision}/banjo-test.tar.gz'
                with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Banjo-test-runner'}),timeout=30) as response,archive.open('wb') as out:
                    size=0
                    while block:=response.read(1024*1024):
                        size+=len(block)
                        if size>MAX_ARCHIVE:raise ValueError('Test download is too large')
                        out.write(block)
                install_archive(archive,self.cache,revision)
            finally:
                if archive.exists():archive.unlink()
        self.activate(target)
        for old in self.cache.iterdir():
            if old.is_dir() and re.fullmatch('[0-9a-f]{40}',old.name) and old not in (self.root,self.previous):
                try:remove_owned(self.cache,old)
                except OSError:pass

    def _memory_budget(self):
        # Linux aggregate resident-memory stop, in addition to each process's
        # inherited 768 MiB address-space bound. Sampling is not a cgroup guarantee.
        if sys.platform!='linux' or self.process is None:return
        rows={}
        for status in Path('/proc').glob('[0-9]*/status'):
            try:
                fields={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in status.read_text().splitlines() if ':' in line}
                rows[int(status.parent.name)]=(int(fields['PPid']),int(fields.get('VmRSS','0 kB').split()[0]))
            except (OSError,ValueError,KeyError):pass
        selected={self.process.pid}
        while True:
            children={pid for pid,(parent,_) in rows.items() if parent in selected}
            if children<=selected:break
            selected|=children
        if sum(rows.get(pid,(0,0))[1] for pid in selected)>512*1024:
            with self.lock:
                process=self.process;self.process=None;self.error='The test build exceeded its memory budget.'
            self._close_process(process)

    def _run(self):
        try:
            if self.source:self.activate(self.source,development=True)
            else:
                for root in sorted(self.cache.iterdir(),key=lambda item:item.stat().st_mtime,reverse=True):
                    if root.is_dir() and re.fullmatch('[0-9a-f]{40}',root.name):
                        try:self.activate(root);break
                        except (OSError,ValueError,RuntimeError):self.error='A cached test build could not be started.'
            due=0
            while not self.stop.is_set():
                self._memory_budget()
                if self.auto and time.monotonic()>=due:
                    self.updating=True
                    try:self._download_latest()
                    except urllib.error.HTTPError as error:
                        self.error='The latest test build is still being prepared.' if error.code==404 else 'The test download is unavailable.'
                    except (OSError,ValueError,KeyError,RuntimeError):self.error='The test update could not be verified; the previous build was kept.'
                    finally:self.updating=False;due=time.monotonic()+300
                self.stop.wait(2)
        except (OSError,ValueError,RuntimeError):self.error='The test build could not be started.'

    def proxy(self, handler, method, body=None):
        with self.lock:port=self.port;process=self.process
        if process is None or process.poll() is not None:
            handler.send(503,b'{"error":"The test build is not ready yet. Production is still available at /play."}');return
        if not self.busy.acquire(timeout=5):
            handler.send(503,b'{"error":"The test site is busy; try again shortly."}');return
        connection=None
        try:
            headers={name:handler.headers[name] for name in ('Host','Origin','Content-Type','Cookie','X-Forwarded-Proto') if name in handler.headers}
            headers['X-Forwarded-For']=handler.visitor()
            connection=http.client.HTTPConnection('127.0.0.1',port,timeout=65)
            connection.request(method,handler.path,body=body,headers=headers)
            response=connection.getresponse();result=response.read(MAX_RESPONSE+1)
            if len(result)>MAX_RESPONSE:raise ValueError('Test response exceeds limit')
            extra={name:value for name,value in response.getheaders() if name.lower() in ('set-cookie','location','content-disposition')}
            if any(name.lower() == 'location' and not scoped_redirect(value) for name,value in extra.items()):
                raise ValueError('Test redirect escaped its mount')
            handler.send(response.status,result,response.getheader('Content-Type','application/json'),extra)
        except (OSError,ValueError,http.client.HTTPException):
            handler.send(503,b'{"error":"The test build changed or stopped; reload to continue. Your saved versions are kept."}')
        finally:
            if connection:connection.close()
            self.busy.release()

    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=2)
        with self.lock:process=self.process;self.process=None
        self._close_process(process)
