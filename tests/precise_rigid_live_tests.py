"""Bounded live precise-rigid admission and real native placement/persistence."""
from __future__ import annotations
from copy import deepcopy
import dataclasses
import json
import math
import os
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'playground')]
import fracture_lab, inventory, inventory_room, live_session, precise_rigid, rigid_assembly, room_store, world_room, workshop_install as install
from mcp import core_use, interaction_points, workshop_components, workshop_rigid
ENGINE = Path(os.environ['BANJO_LIVE_ENGINE']).resolve() if os.environ.get('BANJO_LIVE_ENGINE') else None


def candidate(material='oak'):
    c = {'kind':'table','design_id':'thin-live-table', 'parameters':{'material':material,'top_thickness_m':.005,'leg_section_m':.015}}
    d, _ = workshop_components.design_from_spec(c)
    c['component_overrides'] = {p.name:{'mechanics':{'model':'rigid'}} for p in d.parts}
    return c


def artifact(material='oak'):
    d,o = workshop_components.design_from_spec(candidate(material))
    return workshop_rigid.compile_rigid(d,o)


def cart_design():
    return workshop_components.design_from_spec({'kind':'cart','design_id':'cart','parameters':{}})


def box(name='box', pos=(0,.5,0), material='iron'):
    return {'name':name,'material':material,'position_m':list(pos),
            'parts':[{'dimensions_m':[.02,.02,.02],'center_local_m':[0,0,0]}]}


class PreciseAdmission(unittest.TestCase):
    def test_thin_geometry_and_mass_frame_are_independent_of_room_grid(self):
        for material in ('glass','oak','iron'):
            a=artifact(material);b,_=precise_rigid.placement(a,'thin',[3.123,0])
            for h in (.04,.02):
                spec=world_room.yard();spec['cell_m']=h
                out=precise_rigid.normalise([b],spec)[0]
                self.assertEqual(b,out)
                self.assertEqual(5,len(out['parts']))
                self.assertEqual(.005,out['parts'][0]['dimensions_m'][1])
                self.assertAlmostEqual(3.123,out['position_m'][0])
                lo,hi=precise_rigid.bounds(out['parts'],out['position_m'],out['orientation_wxyz'])
                self.assertAlmostEqual(.002,lo[1]);self.assertAlmostEqual(.762,hi[1])

    def test_rooms_with_ground_water_joints_and_loose_bodies_are_admitted(self):
        # Exact bodies share a room with everything made of cells, its terrain,
        # its water and its joints -- a cart in the Explore valley.
        spec=world_room.yard();spec['bodies'][0]['anchored']=False
        self.assertEqual(1,len(precise_rigid.normalise([box()],spec)))
        for key,value in (('terrain',{'generate':'valley'}),('water',{'discharge_m3_s':.35}),
                          ('joints',[{'kind':'hinge','a':'box','b':'other','at_mm':[0,0,0]}])):
            spec=world_room.yard();spec[key]=value
            with self.subTest(key=key):self.assertEqual(1,len(precise_rigid.normalise([box()],spec)))

    def test_heat_tools_and_rich_actions_are_refused_not_downgraded(self):
        # Machines are not among them: a cart carries a battery, a motor and
        # a controller with its sensors (tests/cart_room_tests.py).
        for key in ('thermo','blades','tool_points','interactions','actions'):
            spec=world_room.yard();spec[key]=[{}]
            with self.subTest(key=key), self.assertRaises(ValueError):precise_rigid.normalise([box()],spec)
        spec=world_room.yard();spec['machines']={'stores':[{'name':'battery','capacity_j':1000}]}
        self.assertEqual(1,len(precise_rigid.normalise([box()],spec)))

    def test_bad_geometry_and_unknown_fields_never_fall_back(self):
        cases=[]
        for change in ({'mass_kg':1}, {'material':'unknown'}, {'position_m':[True,0,0]}, {'orientation_wxyz':[2,0,0,0]}):
            cases.append({**box(),**change})
        for d in ([0,1,1],[float('nan'),1,1],[.0001,.02,.02]):
            b=box();b['parts'][0]['dimensions_m']=d;cases.append(b)
        for change in ({'shape':'sphere'}, {'rotation_wxyz':[1,0,0,.1]}, {'material':'rubber'}, {'name':''}):
            b=box();b['parts'][0].update(change);cases.append(b)
        b=box();b['parts'][0].update(shape='cylinder',dimensions_m=[.3,.06,.2]);cases.append(b)
        for b in cases:
            with self.subTest(body=b),self.assertRaises(ValueError):precise_rigid.normalise([b],world_room.yard())
        with self.assertRaises(ValueError):precise_rigid.normalise([box(),box()],world_room.yard())

    def test_budget_is_refused_and_round_turned_parts_are_kept_as_given(self):
        with self.assertRaises(ValueError):precise_rigid.normalise([box(str(i)) for i in range(33)],world_room.yard())
        # Overlaps, the centre of mass and whether the parts meet are the
        # engine's to settle (NativePreciseInstallation below): what this keeps
        # is what was drawn -- a turned cylinder of its own material.
        b=box('wheelset',material='oak')
        b['parts']=[{'shape':'cylinder','material':'iron','dimensions_m':[.03,.76,.03],'center_local_m':[0,0,0],
                     'rotation_wxyz':[math.sqrt(.5),0,0,math.sqrt(.5)],'name':'axle'},
                    {'shape':'cylinder','dimensions_m':[.32,.06,.32],'center_local_m':[.38,0,0],
                     'rotation_wxyz':[math.sqrt(.5),0,0,math.sqrt(.5)]}]
        out=precise_rigid.normalise([b],world_room.yard())[0]
        self.assertEqual(b['parts'],out['parts'])
        lo,hi=precise_rigid.bounds(out['parts'],[0,1,0],[1,0,0,0])
        self.assertAlmostEqual(.41,hi[0]);self.assertAlmostEqual(1.16,hi[1])

    def test_validation_and_scene_document_preserve_precise_geometry(self):
        spec=world_room.yard();spec['precise_rigid_bodies']=[box()]
        normalized=fracture_lab.validate(spec)
        doc=fracture_lab.scene_document(normalized)
        self.assertEqual(normalized['precise_rigid_bodies'],doc['precise_rigid_bodies'])
        self.assertEqual([.02]*3,doc['precise_rigid_bodies'][0]['parts'][0]['dimensions_m'])


class RigidAssembly(unittest.TestCase):
    """A Workshop design as exact rigid bodies on pins (rigid_assembly): the
    cart, the product it was built for."""

    def test_the_cart_is_a_chassis_and_two_wheelsets_on_pins_through_their_axles(self):
        design, over = cart_design()
        a = rigid_assembly.compile_design(design, over, root='cart')
        self.assertEqual(['cart', 'cart-1', 'cart-2'], [b['name'] for b in a['bodies']])
        chassis, front, back = a['bodies']
        self.assertEqual({'deck', 'handle', 'handle-arm-1', 'handle-arm-2', 'bearing-mount-11', 'bearing-mount-12',
                          'bearing-mount-21', 'bearing-mount-22'}, {p['name'] for p in chassis['parts']})
        for body, axle, wheels in ((front, 'axle-1', ('wheel-11', 'wheel-12')),
                                   (back, 'axle-2', ('wheel-21', 'wheel-22'))):
            parts = {p['name']: p for p in body['parts']}
            self.assertEqual({axle, *wheels}, set(parts))
            # Oak by mass, with its iron axle marked as its own; all of it round.
            self.assertEqual('oak', body['material'])
            self.assertEqual('iron', parts[axle]['material'])
            self.assertTrue(all('material' not in parts[w] for w in wheels))
            self.assertTrue(all(p['shape'] == 'cylinder' for p in parts.values()))
            # Listed first, so the space it runs through the wheels is iron.
            self.assertEqual(axle, body['parts'][0]['name'])
        # One pin per wheelset, through its axle, free all the way round.
        pins = {(j['a'], j['b']): j for j in a['joints']}
        self.assertEqual({('cart', 'cart-1'), ('cart', 'cart-2')}, set(pins))
        for name, z in (('cart-1', -320.0), ('cart-2', 320.0)):
            pin = pins[('cart', name)]
            self.assertEqual('hinge', pin['kind'])
            for got, want in zip(pin['at_mm'], (0.0, 160.0, z)):
                self.assertAlmostEqual(want, got, delta=1e-9)
            self.assertAlmostEqual(1.0, abs(pin['axis'][0]), delta=1e-12)
            self.assertEqual((-180.0, 180.0, 0.0), (pin['lower_deg'], pin['upper_deg'], pin['friction_n_m']))
            self.assertEqual(2, len(pin['stands_for']))              # both of its bearings
        # Drawn in what it is made of, as a lattice body of that material is.
        for body in a['bodies']:
            self.assertEqual(int(fracture_lab.MATERIAL_COLORS[body['material']], 16), body['color_rgba'])
        spec = world_room.yard(); spec['precise_rigid_bodies'] = rigid_assembly.scene_bodies(a)
        self.assertEqual(3, len(precise_rigid.normalise(spec['precise_rigid_bodies'], spec)))

    def test_placing_turns_its_bodies_and_pins_as_one_and_stands_it_on_its_wheels(self):
        design, over = cart_design()
        a = rigid_assembly.compile_design(design, over, root='cart')
        yaw = 0.7
        placed = rigid_assembly.placed(a, [1.0, 2.0, 3.0], yaw)
        q = [math.cos(yaw / 2), 0.0, math.sin(yaw / 2), 0.0]
        for body in placed['bodies']:
            self.assertEqual([1.0, 2.0, 3.0], body['position_m'])
            for got, want in zip(body['orientation_wxyz'], q):
                self.assertAlmostEqual(want, got, delta=1e-12)
        # A turn about y takes (x, y, z) to (x cos + z sin, y, z cos - x sin).
        c, s = math.cos(yaw), math.sin(yaw)
        for pin, source in zip(placed['joints'], a['joints']):
            x, y, z = source['at_mm']
            for got, want in zip(pin['at_mm'], (1000 + x * c + z * s, 2000 + y, 3000 + z * c - x * s)):
                self.assertAlmostEqual(want, got, delta=1e-9)
            x, y, z = source['axis']
            for got, want in zip(pin['axis'], (x * c + z * s, y, z * c - x * s)):
                self.assertAlmostEqual(want, got, delta=1e-12)
        # Its lowest points are its wheels' rims, on the floor it was set on.
        self.assertAlmostEqual(2.0, min(low for low, _, _ in rigid_assembly.footprint(placed)), delta=1e-9)

    def test_the_chassis_carries_its_use_and_every_point_stays_where_it_was_drawn(self):
        design, over = cart_design()
        a = rigid_assembly.compile_design(design, over, root='cart')
        actions, records = rigid_assembly.room_entries(design, a)
        self.assertEqual(['cart', 'cart-1', 'cart-2'], [x['body'] for x in actions])
        self.assertEqual(core_use.installed(design, 'cart'), actions[0])
        # Every point the design draws -- its deck, and the grip at its handle --
        # is on the chassis, about the chassis's centre of mass.
        self.assertEqual(['cart', 'cart-1', 'cart-2'], [r['body'] for r in records])
        centre = a['bodies'][0]['_centre_m']
        where = {pt['id']: [pt['position_m'][k] + centre[k] for k in range(3)] for pt in records[0]['points']}
        drawn = interaction_points.for_design(design)
        self.assertEqual({pt['id'] for pt in drawn}, set(where))
        for pt in drawn:
            for got, want in zip(where[pt['id']], pt['position_m']):
                self.assertAlmostEqual(want, got, delta=1e-9)
        # A wheelset has what every passive thing has: a grip and a use at its middle.
        for record in records[1:]:
            self.assertEqual({'grip', 'use'}, {pt['id'] for pt in record['points']})
            self.assertTrue(all(pt['position_m'] == [0.0, 0.0, 0.0] for pt in record['points']))

    def test_what_has_no_exact_rigid_form_is_refused_not_approximated(self):
        design, over = cart_design()

        def without(name):
            return dataclasses.replace(design, parts=[p for p in design.parts if p.name != name])

        def changed(name, **fields):
            return dataclasses.replace(design, parts=[dataclasses.replace(p, **fields) if p.name == name else p
                                                      for p in design.parts])
        cases = {'wheels on no axle': (without('axle-1'), 'held by a bearing'),
                 'an oval wheel': (changed('wheel-11', size_m=(.32, .06, .30)), 'oval cylinder'),
                 'a rubber wheel': (changed('wheel-11', material='rubber'), 'glass, oak, iron or concrete')}
        for label, (broken, words) in cases.items():
            with self.subTest(label), self.assertRaisesRegex(ValueError, words):
                rigid_assembly.compile_design(broken, over, root='cart')
        with self.assertRaisesRegex(ValueError, 'An assembly root'):
            rigid_assembly.compile_design(design, over, root='cart/../x')

    def test_a_wheel_turned_on_its_axle_is_set_down_by_its_rim_not_its_box(self):
        # Placing measures an exact body by its own parts (placement._span): a
        # round wheel reaches 160 mm below its axle however far it has turned,
        # where the box round it reaches 226 mm at 45 degrees -- the preview
        # said one height and the engine set it down at another. A body of
        # cells is still measured by its box.
        sys.path.append(str(ROOT/'mcp'))
        import placement
        design, over = cart_design()
        wheelset = rigid_assembly.compile_design(design, over, root='cart')['bodies'][1]
        centre = wheelset['_centre_m']
        parts = [dict(part, center_local_m=[part['center_local_m'][k]-centre[k] for k in range(3)])
                 for part in wheelset['parts']]
        body = {'dimensions_m': [.82, .32, .32], 'rigid_parts_local': parts}
        for degrees in (0, 20, 45, 70, 90):
            half = math.radians(degrees)/2
            spun = [math.cos(half), math.sin(half), 0.0, 0.0]        # on its own axle, x
            with self.subTest(degrees=degrees):
                for axis, reach in ((1, .16), (0, .41), (2, .16)):
                    low, high = placement._span(body, spun, axis)
                    self.assertAlmostEqual(-reach, low, delta=1e-8)     # the turns are built from degrees
                    self.assertAlmostEqual(reach, high, delta=1e-8)
        boxed = {'dimensions_m': [.1, .2, .3]}
        tilt = [math.cos(.3), .2, math.sin(.3), .1]
        norm = math.sqrt(sum(v*v for v in tilt)); tilt = [v/norm for v in tilt]
        for axis in range(3):
            self.assertEqual((-placement._reach(boxed, tilt, axis), placement._reach(boxed, tilt, axis)),
                             placement._span(boxed, tilt, axis))

    def test_a_workshop_rigid_install_is_drawn_in_its_own_material(self):
        for material in ('glass', 'oak', 'iron'):
            body, _ = precise_rigid.placement(artifact(material), 'table', [0, 0])
            self.assertEqual(int(fracture_lab.MATERIAL_COLORS[material], 16), body['color_rgba'])


@unittest.skipUnless(ENGINE and ENGINE.is_file(), 'BANJO_LIVE_ENGINE is required')
class NativePreciseInstallation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);self.live=live_session.Live();self.addCleanup(self.live.shutdown)
        self.room=world_room.Room('yard');self.room.inventory=inventory.Inventory()
        self.app=SimpleNamespace(live=self.live,live_holder='world',room=self.room,engine_path=ENGINE,
            runs_path=root/'runs',store=room_store.RoomStore(root/'rooms'))
        self.live.open(self.app,{'spec':self.room.spec})
    def snap(self):return install._snapshot(self.live)
    def preview(self, material='oak', x=3.123):
        ctx=install.context(self.app,{})
        return install.preview(self.app,{'session':ctx['session'],'scene':'yard','mode':'authoring',
            'position_m':[x,0],'candidate':candidate(material)})
    def request(self,p,key='rigid-install-1'):
        return {'scene':'yard','session':p['session'],'preview_id':p['preview_id'],'request_id':key}
    def commit(self,p,key='rigid-install-1'):return install.commit(self.app,self.request(p,key))

    def test_three_material_installation_uses_actual_native_mass_and_exact_shapes(self):
        for i,material in enumerate(('glass','oak','iron')):
            before=self.snap();old=self.live.session;record=self.room.inventory.record()
            p=self.preview(material,3.123+i*2);self.assertEqual(before,self.snap());self.assertIs(old,self.live.session)
            a=artifact(material);self.assertEqual(0,p['cells']);self.assertEqual(5,p['collision_boxes'])
            result=self.commit(p,f'rigid-install-{i}');saved=self.snap()
            install._preserved(before,saved,p['root_body'])
            b=next(b for b in saved['bodies'] if b['name']==p['root_body'])
            self.assertEqual('',b['nodes_b64']);self.assertEqual('',b['offsets_b64'])
            self.assertAlmostEqual(a['mass_kg'],b['precise_mass_kg'],delta=a['mass_kg']*5e-6)
            self.assertEqual(record,self.room.inventory.record());self.assertTrue(old._closed)
            state=self.live.session.send(op='poses')
            body=next(b for b in state['bodies'] if b['name']==p['root_body'])
            self.assertEqual('precise-rigid-v1',body['mechanical_model']);self.assertEqual(5,len(body['rigid_parts_local']))
            self.assertEqual(.005,body['rigid_parts_local'][0]['dimensions_m'][1]);self.assertFalse(body['internal_failure_supported'])
            self.assertEqual({'box'},{part['shape'] for part in body['rigid_parts_local']})
            self.assertTrue(result['native_precise_geometry_verified']);self.assertFalse(result['strength_certified'])

    def test_motion_and_persistent_restart_keep_source_pose_and_unique_receipt(self):
        p=self.preview();req=self.request(p);first=install.commit(self.app,req)
        self.live.session.send(op='step',dt=1/240,n=240)
        current=self.snap();b=next(b for b in current['bodies'] if b['name']==p['root_body'])
        self.assertLess(b['pose']['com_m'][1],self.room.spec['precise_rigid_bodies'][0]['position_m'][1])
        self.room.world_record=current;self.app.store.save(self.room)
        self.live.shutdown();self.app.room=self.room=self.app.store.load('yard')
        opened=self.live.open(self.app,{'spec':self.room.spec,'snapshot':self.room.world_record})
        self.assertEqual('whole',opened['restored']['tier'])
        self.assertEqual(current,self.snap())
        replay=install.commit(self.app,req);self.assertTrue(replay['replayed']);self.assertEqual(first['root_body'],replay['root_body'])
        self.assertEqual(1,len(self.room.spec['precise_rigid_bodies']))

    def test_second_installation_keeps_moving_precise_body_and_elapsed_time(self):
        p=self.preview();self.commit(p)
        self.live.session.send(op='step',dt=1/240,n=5)
        before=self.snap();p2=self.preview(x=6.321);self.commit(p2,'rigid-install-2')
        install._preserved(before,self.snap(),p2['root_body'])

    def test_rotating_moving_compound_restarts_and_carries_without_pose_reset(self):
        a=artifact();b,_=precise_rigid.placement(a,'rotating',[0,0]);b['position_m'][1]+=3
        b['velocity_m_s']=[.15,0,.07];b['spin_rad_s']=[0,1.5,0]
        spec=world_room.yard();spec['precise_rigid_bodies']=[b];self.room.spec=spec
        self.live.open(self.app,{'spec':spec});self.live.session.send(op='step',dt=1/240,n=24)
        before=self.snap();body=next(x for x in before['bodies'] if x['name']=='rotating')
        self.assertNotEqual([1,0,0,0],body['pose']['q_wxyz'])
        self.assertNotEqual([0,0,0],body['pose']['w_rad_s'])
        p=self.preview(x=6);self.commit(p);install._preserved(before,self.snap(),p['root_body'])
        before=self.snap();self.live.shutdown();self.live.open(self.app,{'spec':self.room.spec,'snapshot':before})
        self.assertEqual(before,self.snap())

    def test_collision_stale_preview_and_disk_failure_do_not_change_world(self):
        p=self.preview();self.commit(p)
        before=self.snap();old=self.live.session
        with self.assertRaisesRegex(ValueError,'overlaps'):self.preview()
        self.assertEqual(before,self.snap());self.assertIs(old,self.live.session)
        p2=self.preview(x=6)
        with patch.object(self.app.store,'save',side_effect=OSError('disk full')),self.assertRaises(OSError):self.commit(p2,'rigid-install-2')
        self.assertEqual(before,self.snap());self.assertIs(old,self.live.session)
        self.live.session.send(op='step',dt=1/240,n=1)
        before=self.snap()
        with self.assertRaisesRegex(ValueError,'changed after preview'):self.commit(p2,'rigid-install-2')
        self.assertEqual(before,self.snap())

    def test_old_binary_is_refused_and_a_loose_body_no_longer_blocks_installation(self):
        original=self.snap()
        old=deepcopy(original);old['carry_readiness'].pop('precise_rigid_version')
        with patch.object(install,'_snapshot',return_value=old),self.assertRaisesRegex(ValueError,'Rebuild'):self.preview()
        self.assertEqual(original,self.snap())
        spec=world_room.yard();spec['bodies'].append({'name':'dynamic','shape':'box','material':'oak','size_mm':[80]*3,'center_mm':[0,40,0]})
        self.room.spec=spec;self.live.open(self.app,{'spec':spec})
        self.live.session.send(op='step',dt=1/240,n=48);before=self.snap()
        p=self.preview();self.assertEqual(before,self.snap())
        self.commit(p);install._preserved(before,self.snap(),p['root_body'])

    def test_native_picking_sees_the_thin_top_and_the_open_space_between_legs(self):
        p=self.preview();self.commit(p)
        top=self.live.session.send(op='pick', **{'from':[3.123,1,0],'dir':[0,-1,0],'max_m':1})
        self.assertTrue(top['hit']);self.assertEqual(p['root_body'],top['name'])
        self.assertAlmostEqual(.762,top['point_m'][1],delta=1e-5)
        hole=self.live.session.send(op='pick', **{'from':[3.123,.3,-1],'dir':[0,0,1],'max_m':2})
        self.assertFalse(hole['hit'],hole)

    def test_small_precise_body_lands_on_actual_five_millimetre_tabletop(self):
        table,_=precise_rigid.placement(artifact(),'table',[0,0])
        spec=world_room.yard();spec['precise_rigid_bodies']=[table,box('cube',(0,1,0))]
        self.room.spec=spec;self.live.open(self.app,{'spec':spec})
        self.live.session.send(op='step',dt=1/240,n=240)
        bodies={b['name']:b for b in self.snap()['bodies']}
        self.assertAlmostEqual(.77,bodies['cube']['pose']['com_m'][1],delta=.001)
        self.assertEqual('',bodies['table']['nodes_b64'])

    def test_held_precise_body_and_hand_survive_installation_and_restart(self):
        p=self.preview();self.commit(p)
        self.live.session.send(op='grab',name=p['root_body'])
        self.live.session.send(op='move',to=[3,1.5,0])
        self.live.session.send(op='step',dt=1/240,n=12)
        before=self.snap();self.assertEqual(p['root_body'],before['hand']['holding'])
        p2=self.preview(x=6);self.commit(p2,'rigid-install-2')
        install._preserved(before,self.snap(),p2['root_body'])
        current=self.snap();self.live.shutdown()
        self.live.open(self.app,{'spec':self.room.spec,'snapshot':current})
        self.assertEqual(current,self.snap())

    def test_unsupported_failure_and_heat_operations_are_explicit(self):
        p=self.preview();self.commit(p);before=self.snap()
        for op,kwargs in [('fracture',{'name':p['root_body']}),
                          ('heat',{'target':p['root_body'],'power_w':100,'seconds':1})]:
            with self.subTest(op=op),self.assertRaisesRegex(live_session.LiveError,'precise-rigid|precise rigid'):
                self.live.session.send(op=op,**kwargs)
            self.assertEqual(before,self.snap())

    def test_a_room_with_an_exact_body_still_heats_what_is_made_of_cells(self):
        # Heat skips exact bodies one by one, as breaking does: the table
        # itself is refused (above), and the stone of cells beside it takes
        # heat as it would in any room -- ice in the Explore valley melts with
        # the cart standing there.
        p=self.preview();self.commit(p)
        reply=self.live.session.send(op='heat',target='marker stone',power_w=10000,seconds=2)
        self.assertGreaterEqual(reply.get('heater',0),1)
        self.live.session.send(op='step',dt=1/240,n=480)
        report=self.live.session.send(op='thermo')['thermo']
        stone=next(b for b in report['bodies'] if b['name']=='marker stone')
        self.assertGreater(stone['temperature_k'],293.15+0.5)
        self.assertFalse(any(b['name']==p['root_body'] for b in report['bodies']))

    def test_an_exact_body_goes_in_the_bag_and_comes_back_where_it_is_put(self):
        # Set aside as a cell body is: out of the room, saved as set aside with
        # the mass the engine measured, and back at rest where it is put.
        p=self.preview();self.commit(p);root=p['root_body']
        was=next(b for b in self.live.session.send(op='poses')['bodies'] if b['name']==root)
        self.live.session.send(op='park',name=root)
        self.assertNotIn(root,{b['name'] for b in self.live.session.send(op='poses')['bodies']})
        saved=next(b for b in self.snap()['bodies'] if b['name']==root)
        self.assertIn('parked',saved)
        self.assertAlmostEqual(artifact('oak')['mass_kg'],saved['precise_mass_kg'],delta=1e-6)
        at=[was['position_m'][0]+1.0,was['position_m'][1]+.01,was['position_m'][2]]
        self.live.session.send(op='unpark',name=root,at=at,q=was['orientation_wxyz'])
        back=next(b for b in self.live.session.send(op='poses')['bodies'] if b['name']==root)
        for k in range(3):self.assertAlmostEqual(at[k],back['position_m'][k],delta=1e-6)

    def test_native_geometry_validator_independently_rejects_bad_raw_scenes(self):
        spec=world_room.yard();spec['precise_rigid_bodies']=[box()]
        doc=fracture_lab.scene_document(fracture_lab.validate(spec))
        for index,change in enumerate(('tiny','unknown','disconnected','bad-quaternion','oval','part-quaternion')):
            bad=deepcopy(doc);b=bad['precise_rigid_bodies'][0]
            if change=='tiny':b['parts'][0]['dimensions_m'][0]=.0001
            if change=='unknown':b['mass_kg']=1
            if change=='disconnected':b['parts']=[{'dimensions_m':[.02]*3,'center_local_m':[x,0,0]} for x in (-.1,.1)]
            if change=='bad-quaternion':b['orientation_wxyz']=[0,0,0,0]
            if change=='oval':b['parts'][0].update(shape='cylinder',dimensions_m=[.03,.02,.02])
            if change=='part-quaternion':b['parts'][0]['rotation_wxyz']=[1,0,0,.5]
            path=Path(self.tmp.name)/f'bad-{index}.json';path.write_text(json.dumps(bad))
            result=subprocess.run([str(ENGINE),'--scene',str(path),'--cell','.04'],input='',text=True,capture_output=True,timeout=10)
            self.assertNotEqual(0,result.returncode,(change,result.stdout))
            self.assertIn('precise',result.stderr.lower()+result.stdout.lower())

    def test_overlapping_and_off_centre_parts_are_one_body_about_its_centre_of_mass(self):
        # Two 20 mm iron cubes overlapping by half, given about the first one's
        # middle: one 30 mm body, standing at its own centre of mass.
        b=box('pair',(0,1,0));b['parts']=[{'dimensions_m':[.02]*3,'center_local_m':[0,0,0]},
                                           {'dimensions_m':[.02]*3,'center_local_m':[.01,0,0]}]
        spec=world_room.yard();spec['precise_rigid_bodies']=[b];self.room.spec=spec
        self.live.open(self.app,{'spec':spec})
        saved=next(x for x in self.snap()['bodies'] if x['name']=='pair')
        self.assertAlmostEqual(7870*.03*.02*.02,saved['precise_mass_kg'],delta=1e-9)
        self.assertAlmostEqual(.005,saved['pose']['com_m'][0],delta=1e-9)
        body=next(x for x in self.live.session.send(op='poses')['bodies'] if x['name']=='pair')
        self.assertAlmostEqual(-.005,body['rigid_parts_local'][0]['center_local_m'][0],delta=1e-9)

    def test_exact_bodies_turn_on_a_pin_without_jamming_on_each_other(self):
        # An iron axle through an oak block's foot, on a pin along the axle: the
        # pin holds them, and the overlap it runs through is not a jam.
        block={'name':'block','material':'oak','position_m':[0,.5,0],
               'parts':[{'dimensions_m':[.1,.2,.1],'center_local_m':[0,0,0]}]}
        wheel={'name':'wheel','material':'oak','position_m':[0,.4,0],'spin_rad_s':[3,0,0],
               'parts':[{'shape':'cylinder','material':'iron','dimensions_m':[.03,.3,.03],'center_local_m':[0,0,0],
                         'rotation_wxyz':[math.sqrt(.5),0,0,math.sqrt(.5)]},
                        {'shape':'cylinder','dimensions_m':[.2,.04,.2],'center_local_m':[.12,0,0],
                         'rotation_wxyz':[math.sqrt(.5),0,0,math.sqrt(.5)]}]}
        spec=world_room.yard();spec['precise_rigid_bodies']=[block,wheel]
        spec['joints']=[{'kind':'hinge','a':'block','b':'wheel','at_mm':[0,400,0],'axis':[1,0,0]}]
        self.room.spec=spec;self.live.open(self.app,{'spec':spec})
        pins=[j for j in self.live.session.send(op='joints')['joints'] if j['kind']=='hinge']
        self.assertEqual(1,len(pins));self.assertTrue(pins[0]['attached'])

    def test_the_compiled_cart_rolls_on_its_pins_as_far_as_its_wheels_turn(self):
        design, over = cart_design()
        placed = rigid_assembly.placed(rigid_assembly.compile_design(design, over, root='cart'), [0.0, 0.002, 0.0])
        bodies = rigid_assembly.scene_bodies(placed)
        for body in bodies:
            body['velocity_m_s'] = [0.0, 0.0, 1.0]        # along its own z, the way its wheels roll
        spec = world_room.yard(); spec['precise_rigid_bodies'] = bodies
        spec['joints'] = rigid_assembly.scene_joints(placed)
        self.room.spec = spec; self.live.open(self.app, {'spec': spec})
        # The wheelset as the engine measured it, against its parts by hand: the
        # iron axle, and two oak wheels less the 30 mm of axle inside each one.
        mass = {b['name']: b['precise_mass_kg'] for b in self.snap()['bodies'] if 'precise_mass_kg' in b}
        axle = math.pi * .015 ** 2 * .76 * 7870
        wheels = 2 * (math.pi * .16 ** 2 * .06 - math.pi * .015 ** 2 * .03) * 700
        self.assertAlmostEqual(axle + wheels, mass['cart-1'], delta=2e-3)
        self.assertAlmostEqual(axle + wheels, mass['cart-2'], delta=2e-3)

        def state():
            poses = {b['name']: b for b in self.live.session.send(op='poses')['bodies']}
            pins = [j for j in self.live.session.send(op='joints')['joints'] if j['kind'] == 'hinge']
            return poses, pins
        # Given nothing but a push, friction spins its wheels up; from then on
        # it goes as far as its 160 mm wheels turn. A free pin reads within
        # +-180 degrees, so it is read every eighth of a second -- well under
        # half a turn at this speed -- and the turns are added up.
        self.live.session.send(op='step', dt=1/240, n=120)
        poses0, pins = state()
        turned = [0.0] * len(pins)
        for _ in range(8):
            self.live.session.send(op='step', dt=1/240, n=30)
            poses1, now = state()
            for k, (before, after) in enumerate(zip(pins, now)):
                self.assertTrue(after['attached'])
                turned[k] += math.radians((after['degrees'] - before['degrees'] + 180.0) % 360.0 - 180.0)
            pins = now
        went = poses1['cart']['position_m'][2] - poses0['cart']['position_m'][2]
        self.assertGreater(went, .5)
        self.assertLess(abs(poses1['cart']['position_m'][0] - poses0['cart']['position_m'][0]), .01)
        for angle in turned:
            self.assertAlmostEqual(went, .16 * abs(angle), delta=.01 * went)
        w, x, y, z = poses1['cart']['orientation_wxyz']
        self.assertGreater(1 - 2 * (x * x + z * z), math.cos(math.radians(3)))   # still standing

    def test_the_compiled_cart_goes_in_the_bag_whole_and_comes_back_whole(self):
        # The owner's product rule, through the person's own bag: taken up by a
        # wheelset, the whole cart is in the hand; put in the bag, all three of
        # its bodies go, their pins in them; kept there through a restart; and
        # out into the hand and put down, it is one cart on its pins.
        design, over = cart_design()
        placed = rigid_assembly.placed(rigid_assembly.compile_design(design, over, root='cart'), [0.0, 0.002, -1.2])
        spec = world_room.yard(); spec['precise_rigid_bodies'] = rigid_assembly.scene_bodies(placed)
        spec['joints'] = rigid_assembly.scene_joints(placed)
        self.room.spec = spec; self.live.open(self.app, {'spec': spec})
        self.live.session.send(op='step', dt=1/240, n=240)
        person = {'standing_m': [0.0, 0.0, 0.6], 'facing': [0.0, 0.0, -1.0], 'eyes_m': [0.0, 1.62, 0.6]}
        cart = ('cart', 'cart-1', 'cart-2')

        def ask(request, op, item):
            return inventory_room.request(self.app, {'request': request, 'revision': None, 'op': op,
                                                     'item': item, 'person': person})

        def here():
            return {b['name']: b for b in self.live.session.send(op='poses')['bodies']}

        def pins():
            return [j for j in self.live.session.send(op='joints')['joints'] if j['kind'] == 'hinge']

        def standing_against_the_chassis(bodies):
            # Each wheelset's distance from the chassis: what its pin keeps.
            return [math.dist(bodies['cart']['position_m'], bodies[n]['position_m']) for n in cart[1:]]
        built = standing_against_the_chassis(here())
        whole = inventory_room.whole_kg(self.app, inventory_room.item_holding(self.app, 'cart'))
        self.assertAlmostEqual(21.144 + 2 * 10.954, whole, delta=0.01)
        took = ask('t1', 'take_up', 'cart-1')
        self.assertTrue(took['ok'], took)
        self.assertEqual(('cart', 'cart-1'), (took['room']['taken_up'], took['room']['by']))
        stowed = ask('s1', 'stow', 'cart-1')
        self.assertTrue(stowed['ok'], stowed)
        self.assertFalse(set(cart) & set(here()), 'part of the cart stayed in the room when it went in the bag')
        self.assertTrue(all(j['attached'] and j.get('away') for j in pins()), pins())
        # A restart with it in the bag: the room opens with it still there.
        saved = self.snap()
        self.live.shutdown()
        opened = self.live.open(self.app, {'spec': spec, 'snapshot': saved})
        self.assertEqual('whole', opened['restored']['tier'])
        inventory_room.after_open(self.app, opened)
        self.assertFalse(set(cart) & set(here()), 'reopened, the bagged cart was back in the room')
        self.assertEqual([inventory_room.item_holding(self.app, 'cart')['id']],
                         inventory_room.inventory_of(self.app).record()['stowed'][:1])
        # Out into the hand, and put down: one cart on its pins.
        out = ask('e1', 'equip', 'cart')
        self.assertTrue(out['ok'], out)
        self.assertTrue(set(cart) <= set(here()), 'out of the bag, part of the cart was not')
        self.assertTrue(all(j['attached'] and not j.get('away') for j in pins()), pins())
        down = ask('d1', 'drop', 'cart')
        self.assertTrue(down['ok'], down)
        self.live.session.send(op='step', dt=1/240, n=480)
        landed = here()
        for was, now in zip(built, standing_against_the_chassis(landed)):
            self.assertAlmostEqual(was, now, delta=0.005)
        self.assertTrue(all(j['attached'] for j in pins()), pins())

    def test_live_native_mass_and_inertia_agree_with_independent_initial_energy(self):
        # At t=0 there is no contact/solver work. An independent analytic oracle
        # checks the ACTUAL native mass/inertia, not duplicated descriptive JSON.
        for material in ('glass','oak','iron'):
            a=artifact(material);body,_=precise_rigid.placement(a,'table',[0,0])
            body['position_m'][1]+=3;body['velocity_m_s']=[.5,0,0];body['spin_rad_s']=[0,1.5,0]
            spec=world_room.yard();spec['precise_rigid_bodies']=[body]
            self.room.spec=spec;self.live.open(self.app,{'spec':spec})
            energy=self.live.session.send(op='thermo')['thermo']['ledger']['mechanical_j']
            expected=a['mass_kg']*(.5*.5**2+9.81*body['position_m'][1])+.5*a['inertia_kg_m2'][1][1]*1.5**2
            self.assertAlmostEqual(expected,energy,delta=abs(expected)*5e-6)

    def test_changed_saved_precise_definition_never_silently_resets_to_source(self):
        p=self.preview();self.commit(p);saved=self.snap();bad=deepcopy(saved)
        target=next(b for b in bad['bodies'] if b['name']==p['root_body'])
        target['precise_rigid_definition']['parts'][0]['dimensions_m'][1]=.006
        staging=live_session.Live();self.addCleanup(staging.shutdown)
        scratch=SimpleNamespace(engine_path=ENGINE,runs_path=Path(self.tmp.name)/'scratch',live_inprocess=False,on_live_reply=None)
        with self.assertRaises((ValueError,RuntimeError)):staging.open(scratch,{'spec':self.room.spec,'snapshot':bad})
        self.assertEqual(saved,self.snap())

if __name__=='__main__':
    if os.environ.get('BANJO_PRECISE_LIVE_TESTS')=='required' and not (ENGINE and ENGINE.is_file()):
        raise RuntimeError('BANJO_LIVE_ENGINE must be built for required live precise-rigid tests')
    unittest.main()
