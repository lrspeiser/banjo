"""Verify the deployed test revision and CI, then optionally fast-forward main.

Dry run is the default. --push is an explicit production release; Render
deploys main automatically. No reset, force push, rebuild or database migration.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def validate_checkpoint(checkpoint, revision, branch):
    if (checkpoint.get('environment') != 'test' or checkpoint.get('branch') != branch or
            checkpoint.get('website_revision') != revision or checkpoint.get('server_revision') != revision or
            checkpoint.get('local_changes') is not False or checkpoint.get('restart_pending') is not False or
            not re.fullmatch('[0-9a-f]{64}', checkpoint.get('engine_sha256') or '')):
        raise ValueError('The test site must serve this exact clean branch revision and its running engine.')


def validate_checks(checks, revision):
    for name in ('source-registration', 'build-and-test'):
        relevant = [item for item in checks if item.get('name') == name and item.get('head_sha') == revision
                    and item.get('app', {}).get('slug') == 'github-actions']
        latest = max(relevant, key=lambda item: item['id']) if relevant else None
        if latest is None or latest.get('status') != 'completed' or latest.get('conclusion') != 'success':
            raise ValueError(f'{name} must pass for the exact tested commit before promotion.')


def run(*args):
    return subprocess.check_output(args, cwd=ROOT, text=True, stderr=subprocess.STDOUT).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', required=True, help='the HTTPS test origin, without a private return URL')
    parser.add_argument('--branch', default='codex/staging')
    parser.add_argument('--push', action='store_true', help='release the verified revision to main')
    args = parser.parse_args()
    site = urlsplit(args.site)
    if (site.scheme != 'https' or not site.hostname or site.username or site.password or
            site.query or site.fragment or site.path not in ('', '/')):
        parser.error('--site must be an HTTPS origin without credentials, path, query or fragment')
    if run('git', 'status', '--porcelain'):
        parser.error('Commit or preserve local changes before promoting.')
    run('git', 'check-ref-format', '--branch', args.branch)
    run('git', 'fetch', 'origin', 'main', args.branch)
    revision = run('git', 'rev-parse', 'refs/remotes/origin/' + args.branch)
    # Refuse to publish a stage that omits concurrently published main changes.
    run('git', 'merge-base', '--is-ancestor', 'refs/remotes/origin/main', revision)
    with urllib.request.urlopen(args.site.rstrip('/') + '/api/checkpoint', timeout=30) as response:
        checkpoint = json.load(response)
    validate_checkpoint(checkpoint, revision, args.branch)
    # Only the newest runs for these named jobs on this exact SHA count.
    checks = json.loads(run('gh', 'api', '--paginate', '--slurp',
        f'repos/lrspeiser/banjo/commits/{revision}/check-runs?per_page=100'))
    validate_checks([item for page in checks for item in page['check_runs']], revision)
    commits = run('git', 'log', '--oneline', 'refs/remotes/origin/main..' + revision)
    print('Verified test revision:', revision)
    print(commits or 'Main already contains this revision.')
    if args.push:
        # An ordinary push rejects a concurrent main update; never overwrite it.
        print(run('git', 'push', 'origin', revision + ':refs/heads/main'))
        print('Main updated. Verify the production header, checkpoint and ordinary play after Render deploys.')
    else:
        print('Dry run only. After reviewing the test site, repeat with --push to release.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from None
