"""Package committed runtime sources and a built engine for the co-hosted test site."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile

SCHEMA = 'banjo.test-build.v1'
ROOT = Path(__file__).resolve().parents[1]


def package(output, native, revision, branch='codex/staging'):
    if not re.fullmatch('[0-9a-f]{40}', revision) or branch != 'codex/staging':
        raise ValueError('Only an exact staging revision may be packaged.')
    source = subprocess.check_output(['git', '-C', str(ROOT), 'archive', revision])
    files = {}
    with tarfile.open(fileobj=io.BytesIO(source)) as archive:
        for member in archive:
            if member.isfile() and (member.name.startswith(('scripts/', 'client/', 'docs/')) or member.name == 'README.md'):
                files[member.name] = archive.extractfile(member).read()
    files['bin/' + native.name] = native.read_bytes()
    if sys.platform == 'win32':
        for library in native.parent.glob('*.dll'):
            files['bin/' + library.name] = library.read_bytes()
    files['bin/build-receipt.json'] = json.dumps(dict(revision=revision, branch=branch)).encode()
    manifest = dict(schema=SCHEMA, revision=revision, branch=branch, platform=sys.platform,
        native='bin/' + native.name, files={name:hashlib.sha256(data).hexdigest() for name,data in files.items()})
    files['test-build.json'] = json.dumps(manifest, sort_keys=True).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, 'w:gz') as archive:
        for name, data in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(data), 0o755 if name == manifest['native'] else 0o644
            archive.addfile(member, io.BytesIO(data))
    print(f'Packaged {revision}: {len(files)} files, {output.stat().st_size} bytes')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--revision', default=None)
    args = parser.parse_args()
    revision = args.revision or subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    package(args.output, args.native.resolve(strict=True), revision)
