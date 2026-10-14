"""Promotion rejects stale builds and failed/missing CI, without any push."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('promotion', Path(__file__).resolve().parents[1]/'scripts/promote-test.py')
promotion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(promotion)


class Promotion(unittest.TestCase):
    def test_only_the_exact_running_clean_test_revision_is_promotable(self):
        frame = dict(environment='test',branch='codex/staging',website_revision='a'*40,
                     server_revision='a'*40,local_changes=False,restart_pending=False,engine_sha256='b'*64)
        promotion.validate_checkpoint(frame,'a'*40,'codex/staging')
        for changes in ({'environment':'production'},{'branch':'main'},{'server_revision':'c'*40},
                        {'website_revision':'c'*40},{'local_changes':True},{'local_changes':None},
                        {'restart_pending':True},{'engine_sha256':''}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                promotion.validate_checkpoint(dict(frame,**changes),'a'*40,'codex/staging')

    def test_latest_complete_successful_jobs_must_belong_to_the_tested_commit(self):
        jobs=[dict(id=i,name=name,head_sha='a'*40,status='completed',conclusion='success',app={'slug':'github-actions'})
              for i,name in enumerate(('source-registration','build-and-test'),1)]
        promotion.validate_checks(jobs,'a'*40)
        for result in ('failure','cancelled','skipped',None):
            with self.assertRaises(ValueError):promotion.validate_checks([jobs[0],dict(jobs[1],conclusion=result)],'a'*40)
        with self.assertRaises(ValueError):promotion.validate_checks(jobs,'c'*40)
        with self.assertRaises(ValueError):promotion.validate_checks(jobs[:1],'a'*40)
        with self.assertRaises(ValueError):promotion.validate_checks([jobs[0],dict(jobs[1],app={'slug':'another-app'})],'a'*40)
        with self.assertRaises(ValueError):promotion.validate_checks([*jobs,dict(jobs[1],id=4,status='in_progress')],'a'*40)


if __name__=='__main__':unittest.main(verbosity=2)
