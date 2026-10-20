"""Bind a shared CI engine artifact to its exact source revision and bytes."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

SCHEMA = 'banjo.ci-engine.v1'
REPO = 'lrspeiser/banjo'


def verified_staging_run(run, revision):
    return (isinstance(run, dict) and isinstance(run.get('repository'), dict) and
            type(run.get('id')) is int and run['id'] > 0 and
            run.get('head_sha') == revision and run.get('head_branch') == 'codex/staging' and
            run.get('event') == 'push' and run.get('status') == 'completed' and
            run.get('conclusion') == 'success' and run.get('path') == '.github/workflows/ci.yml' and
            run.get('repository', {}).get('full_name') == REPO)


def main_reuse_proof(revision, ref, event):
    if ref != 'refs/heads/main' or event != 'push':
        return None
    if not re.fullmatch('[0-9a-f]{40}', revision or ''):
        raise ValueError('An exact source revision is required.')
    try:
        data = json.loads(subprocess.check_output(['gh', 'api',
            f'repos/{REPO}/actions/workflows/ci.yml/runs?head_sha={revision}&branch=codex/staging&event=push&status=success&per_page=10'], text=True, timeout=30))
        return next((r['id'] for r in data.get('workflow_runs', []) if verified_staging_run(r, revision)), None)
    except (OSError, ValueError, subprocess.SubprocessError):
        # Missing/unavailable evidence must run the full suite, never waive it.
        return None


def engine_receipt(binary, revision):
    binary = Path(binary)
    if not re.fullmatch('[0-9a-f]{40}', revision or ''):
        raise ValueError('An exact source revision is required.')
    if not binary.is_file() or binary.is_symlink():
        raise ValueError('The built native engine must be a regular file.')
    with binary.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(schema=SCHEMA, revision=revision, sha256=digest,
                size=binary.stat().st_size, platform=sys.platform, machine=platform.machine())


def verify_engine(binary, receipt, revision):
    expected = engine_receipt(binary, revision)
    if json.loads(Path(receipt).read_text(encoding='utf-8')) != expected:
        raise ValueError('The shared engine revision, platform or checksum does not match.')
    return expected


def require_checks(revision):
    # Manual package recovery retains the same exact-SHA CI requirement as
    # ordinary promotion. It does not weaken or replace the promotion guard.
    path = Path(__file__).with_name('promote-test.py')
    spec = importlib.util.spec_from_file_location('test_promotion', path)
    promotion = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(promotion)
    if not re.fullmatch('[0-9a-f]{40}', revision or ''):
        raise ValueError('An exact source revision is required.')
    pages = json.loads(subprocess.check_output(['gh', 'api', '--paginate', '--slurp',
        f'repos/lrspeiser/banjo/commits/{revision}/check-runs?per_page=100'], text=True))
    promotion.validate_checks([item for page in pages for item in page['check_runs']], revision)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['create', 'verify', 'require-checks', 'reuse-main'])
    parser.add_argument('--revision', required=True)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    if args.operation == 'reuse-main':
        proof = main_reuse_proof(args.revision, os.environ.get('GITHUB_REF'), os.environ.get('GITHUB_EVENT_NAME'))
        output = f'reuse={str(proof is not None).lower()}\nrun_id={proof or ""}\n'
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
                stream.write(output)
        print(output, end='')
    elif args.operation == 'require-checks':
        require_checks(args.revision)
    else:
        if args.binary is None or args.receipt is None:
            parser.error('--binary and --receipt are required for engine artifacts')
        if args.operation == 'create':
            args.receipt.write_text(json.dumps(engine_receipt(args.binary, args.revision), sort_keys=True), encoding='utf-8')
        else:
            verify_engine(args.binary, args.receipt, args.revision)
    print('CI step complete:', args.operation, args.revision)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from None
