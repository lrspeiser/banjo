"""Returning navigation, identity isolation and required profile persistence."""
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'playground'))
import player_world


class ReturningIdentity(unittest.TestCase):
    def setUp(self):
        self.profile={'id':'alice','token':'a'*64,'name':'Alice','color':'#66b8b2',
                      'inventory':{'hands':{'right':'damaged-tool'}},'pose':None}
        self.app=SimpleNamespace(world_id='world',room=SimpleNamespace(player_records={'alice':self.profile}),
                                 store=SimpleNamespace(save=mock.Mock(side_effect=OSError('disk full'))))

    def test_returning_and_unchanged_name_preserve_inventory_without_writes(self):
        before=deepcopy(self.app.room.player_records)
        for name in (None,'Alice',' Alice '):
            result=player_world.join(self.app,'a'*64,name)
            self.assertEqual('alice',result['id']);self.assertNotIn('inventory',result)
        self.assertEqual(before,self.app.room.player_records)
        self.app.store.save.assert_not_called()

    def test_new_guest_and_rename_still_require_save_and_rollback_on_failure(self):
        before=deepcopy(self.app.room.player_records)
        self.assertIsNone(player_world.resume(self.app))
        self.assertIsNone(player_world.resume(self.app,'a'*64,'Changed'))
        for token,name in ((None,'Bob'),('a'*64,'Changed')):
            with self.assertRaisesRegex(ValueError,'could not be saved'):
                player_world.join(self.app,token,name)
            self.assertEqual(before,self.app.room.player_records)
        self.assertEqual(2,self.app.store.save.call_count)

    def test_unknown_tokens_and_invalid_names_cannot_replace_or_write_identity(self):
        before=deepcopy(self.app.room.player_records)
        for token,name in (('b'*64,None),('bad',None),(123,None),('a'*64,''),('a'*64,True)):
            with self.assertRaises(ValueError):player_world.join(self.app,token,name)
        self.assertEqual(before,self.app.room.player_records)
        self.app.store.save.assert_not_called()


if __name__=='__main__':unittest.main()
