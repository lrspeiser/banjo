"""Upgrade one stopped server's saved room to cube digging, with native restore.

python tools/upgrade_cube_world.py --room <rooms/new-game.json> --build <Release>
No map generation, ledger adjustment, or inventory reset. The original file is
backed up beside it. Do not run while a server is writing that room.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'playground')]
import live_session
from world_upgrades import cube_digging_record


def verify(record, build):
    suffix = '.exe' if os.name == 'nt' else ''
    runner = build / f'banjo_live_world_run{suffix}'
    if not runner.is_file():
        raise ValueError('Build the native runner before upgrading a saved world')
    os.environ['BANJO_LIVE_ENGINE'] = str(runner.resolve())
    before = record['world']
    with tempfile.TemporaryDirectory(prefix='banjo-cube-upgrade-') as folder:
        live = live_session.Live()
        try:
            app = SimpleNamespace(engine_path=build / f'banjo_platform_cli{suffix}',
                                  runs_path=Path(folder), live_inprocess=False, on_live_reply=None)
            opened = live.open(app, {'spec': record['spec'], 'snapshot': before})
            if (opened.get('restored') or {}).get('tier') != 'whole':
                raise ValueError('The native engine refused whole restore; original world retained')
            after, why = live.snapshot()
            if after is None:
                raise ValueError(f'Could not verify the restored world: {why}')
            for key in ('t_s', 'water', 'native_players', 'player_hands', 'hand',
                        'energy_stores', 'dead_bonds_b64', 'plastic', 'bodies'):
                if before.get(key) != after.get(key):
                    raise ValueError(f'Native restore changed {key}; original world retained')
            # Rendering/collider metadata can change with the chosen surface;
            # matter, exports, accounts, saved bed heights and clock cannot.
            for key in ('grid', 'beds', 'soil', 'sand', 'loose', 'moisture', 'ledger',
                        'carried', 'carriers', 'exported', 'returned', 'time_s'):
                if before['ground'].get(key) != after['ground'].get(key):
                    raise ValueError(f'Native restore changed ground {key}; original world retained')
        finally:
            live.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--room', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--check', action='store_true', help='verify without replacing the file')
    args = parser.parse_args()
    original = args.room.read_bytes()
    record = json.loads(original)
    candidate = cube_digging_record(record)
    verify(candidate, args.build.resolve())
    if candidate == record:
        print('Already using cube digging; whole native restore verified.')
        return
    if args.check:
        print('Whole native restore verified; no file changed.')
        return
    if args.room.read_bytes() != original:
        raise ValueError('Room changed during verification; stop the server before upgrading')
    backup = args.room.with_name(args.room.name + '.before-cube-digging')
    with backup.open('xb') as kept:
        kept.write(original)
    partial = args.room.with_name(args.room.name + '.cube-upgrade.partial')
    partial.write_text(json.dumps(candidate, allow_nan=False), encoding='utf-8')
    os.replace(partial, args.room)
    print(f'Cube digging ready; original saved in {backup}')


if __name__ == '__main__':
    main()
