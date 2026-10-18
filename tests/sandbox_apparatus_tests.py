"""Every prepared Sandbox group can move and be removed without corruption.

Pure declaration checks, split into four disjoint batches without changing the
compiler, assertions or 600-second deadlines. No native engine is substituted.
"""
import copy
import multiprocessing
import os
import sys
import unittest
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import machine_game as mg
import machine_world as mw
import sandbox_edit

SHARD=None
BATCH_COUNT=4


@lru_cache(maxsize=1)
def cases():
    tasks=[]
    for template in mg.sandbox_templates():
        if not template['base']:continue
        base=template['base'];initial=mw.compile_spec(base)
        tasks.extend((base,initial,obj) for obj in sandbox_edit.objects(base,compiled=initial))
    return tuple(tasks)


def partitions():
    return [cases()[i::BATCH_COUNT] for i in range(BATCH_COUNT)]


def audit(task):
    base,initial,obj=task
    check=unittest.TestCase();before=copy.deepcopy(base)
    old={p['name']:p for p in initial['parts']}
    # Meshing teeth cannot move into their neighbour. Three whole cells also
    # preserve thin optical glass's voxel phase, unlike a 5 cm translation.
    for delta in ([.06,0,0],[-.06,0,0],[0,0,.06],[0,0,-.06],[0,.06,0]):
        try:
            moved,selected,compiled=sandbox_edit.edit(base,obj['id'],delta,compiled=initial)
            break
        except mw.MachineRefused:check.assertEqual(base,before)
    else:check.fail((base['title'],obj['name'],'no clear edit'))
    for part in compiled['parts']:
        previous=old[part['name']]
        expected=[v+(delta[i] if part['name'] in selected['parts'] else 0) for i,v in enumerate(previous['at_m'])]
        for a,b in zip(part['at_m'],expected):check.assertAlmostEqual(a,b,places=6,msg=(base['title'],obj['name']))
        check.assertEqual(mg._volume(part),mg._volume(previous))
        check.assertEqual(part['material'],previous['material'])
    removed,_,after=sandbox_edit.edit(base,obj['id'],remove=True,compiled=initial)
    check.assertFalse(set(selected['parts']) & {p['name'] for p in after['parts']})
    check.assertEqual(base,before,'Editing must not mutate a shared template')
    return 1


class Apparatus(unittest.TestCase):
    def test_batches_are_disjoint_and_cover_every_group(self):
        keys=lambda rows:{(base['title'],obj['id']) for base,_,obj in rows}
        batches=partitions();sets=[keys(rows) for rows in batches]
        self.assertEqual(set.union(*sets),keys(cases()))
        self.assertEqual(sum(map(len,sets)),len(cases()))
        self.assertLessEqual(max(map(len,sets))-min(map(len,sets)),1)
        self.assertGreater(len(cases()),100)

    def test_selected_groups_move_and_remove_without_dangling_references(self):
        tasks=cases() if SHARD is None else partitions()[SHARD]
        print('APPARATUS BATCH',SHARD,'groups',len(tasks),'of',len(cases()),flush=True)
        with ProcessPoolExecutor(max_workers=min(4,os.cpu_count() or 1),
                mp_context=multiprocessing.get_context('spawn')) as pool:
            count=sum(pool.map(audit,tasks))
        self.assertEqual(count,len(tasks))


if __name__=='__main__':
    shard=next((arg for arg in sys.argv[1:] if arg.startswith('--shard=')),None)
    if shard:
        index,total=map(int,shard.split('=',1)[1].split('/'))
        if total!=BATCH_COUNT or not 0<=index<total:raise SystemExit('apparatus batches use INDEX/4')
        SHARD=index;sys.argv.remove(shard)
    unittest.main(verbosity=2)
