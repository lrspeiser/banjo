"""Display source matching and frozen names do not change product identity."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'playground'),str(ROOT)]
import product_labels
import starter_goals
import workshop_store
import room_store
from mcp import workshop


class ProductNames(unittest.TestCase):
    def test_named_source_matches_geometry_not_client_design_id(self):
        with tempfile.TemporaryDirectory() as temp:
            app=SimpleNamespace(workshop_store=Path(temp))
            source=starter_goals.recipe(); source['design_id']='arbitrary-model-id'
            self.assertEqual('Camp stool',product_labels.from_recipe(app,source)['label'])
            source['parameters']['width_m']=.48
            self.assertEqual('Stool',product_labels.from_recipe(app,source)['label'])
            # Normalized defaults allow sparse authoring and the full saved
            # source to name the same item without using a tutorial body id.
            sparse=starter_goals.recipe(); sparse['parameters'].pop('leg_style',None)
            self.assertEqual('Camp stool',product_labels.from_recipe(app,sparse)['label'])

    def test_saved_label_is_frozen_and_changed_source_cannot_borrow_it(self):
        with tempfile.TemporaryDirectory() as temp:
            app=SimpleNamespace(workshop_store=Path(temp))
            design=workshop.assemble('table',design_id='my-table')
            saved=workshop_store.save(Path(temp),design,label='My receiving table')
            recipe={k:saved[k] for k in ('kind','design_id','parameters','component_overrides')}
            presentation=product_labels.from_recipe(app,recipe)
            self.assertEqual('My receiving table',presentation['label'])
            receipt={'status':'installed','root_body':'native-id-42','design_id':design.design_id,
                     'recipe':recipe,'presentation':presentation}
            room=SimpleNamespace(scene='world',spec={'bodies':[{'name':'native-id-42'}]},chat=[],
                                 workshop_installs=[receipt])
            app.room=room
            store=room_store.RoomStore(Path(temp)/'rooms');self.assertTrue(store.save(room))
            workshop_store.rename(Path(temp),'my-table','Renamed later')
            app.room=store.load('world')
            item={'name':'native-id-42','id':'stable-42','bodies':['native-id-42']}
            self.assertEqual('My receiving table',product_labels.for_item(app,item)['label'])
            self.assertEqual('My receiving table',product_labels.body_labels(app)['native-id-42'])
            self.assertEqual('native-id-42',item['name'])
            altered=deepcopy(recipe);altered['parameters']['width_m']+=.1
            self.assertEqual('Table',product_labels.from_recipe(app,altered)['label'])

    def test_unknown_legacy_receipt_is_not_guessed_from_an_id(self):
        app=SimpleNamespace(room=SimpleNamespace(spec={},workshop_installs=[
            {'status':'installed','root_body':'workshop-abcdef','design_id':'Camp stool'}]))
        item={'name':'workshop-abcdef','bodies':['workshop-abcdef']}
        self.assertEqual('Built item',product_labels.for_item(app,item)['label'])

    def test_next_use_comes_from_implemented_tool_profile(self):
        item={'name':'handle','bodies':['handle','head']}
        app=SimpleNamespace(room=SimpleNamespace(spec={'interactions':[
            {'tool':'head','object':'Survey pick','template':'swing-and-lever'}]},workshop_installs=[]))
        shown=product_labels.for_item(app,item)
        self.assertEqual('Survey pick',shown['label'])
        self.assertEqual('Study / gather in World',shown['next_use'][0])
        app.room.spec['interactions'][0]['template']='unimplemented-future-tool'
        self.assertEqual('Hold / place in World',product_labels.for_item(app,item)['next_use'][0])

    def test_packed_mass_requires_every_saved_native_part(self):
        import inventory_room, inventory, workshop_tabs
        thing={'id':'compound','name':'part-a','bodies':['part-a','part-b']}
        room=SimpleNamespace(spec={'bodies':[{'name':'part-a'},{'name':'part-b'}]},
            workshop_installs=[],world_record={'t_s':4,'bodies':[
                {'name':'part-a','parked':{'mass_kg':2}},
                {'name':'part-b','parked':{'mass_kg':3}}]})
        app=SimpleNamespace(room=room)
        shown={'hands':{},'stowed':[{'id':'compound','name':'part-a','parts':thing['bodies']}]}
        with mock.patch.object(inventory_room,'shown',return_value=shown), \
             mock.patch.object(inventory_room,'whole_kg',return_value=None), \
             mock.patch.object(inventory,'items_of',return_value=[thing]):
            product=workshop_tabs.carried(app)[0]
            self.assertEqual(5,product['kg'])
            self.assertEqual('Saved native checkpoint',product['mass_source'])
            room.world_record['bodies'].pop()
            product=workshop_tabs.carried(app)[0]
            self.assertNotIn('kg',product,'A partial saved mass was presented as the whole item')
            self.assertEqual('Unreported',product['mass_source'])


if __name__=='__main__':unittest.main()
