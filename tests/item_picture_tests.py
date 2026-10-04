"""A picture of each thing a person has, kept by the server (item_pictures.py).

Through the real server and the native room: the person who has a thing may
send its picture, which every inventory view then names by revision and which
a page reads back once; anybody else's thing, or anything but a small PNG, is
refused. In a browser: the world page pictures a held thing nobody has
pictured yet, and the strip and the Workshop's Inventory then show the kept
picture.
"""
import base64
import hashlib
import json
from pathlib import Path
import struct
import time
import unittest
import urllib.error
import zlib

import world_goods_tests as flow
import body_condition_tests as condition

ROOT = Path(__file__).resolve().parents[1]


def png(width=4, height=4, rgba=(200, 120, 40, 255)):
    """A real PNG of one colour, made here so the test needs no image library."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    rows = b"".join(b"\x00" + bytes(rgba) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def data_url(raw):
    return "data:image/png;base64," + base64.b64encode(raw).decode()


class ItemPictures(unittest.TestCase):
    setUp = flow.GoodsJourney.setUp
    tearDown = condition.BodyCondition.tearDown
    start = flow.GoodsJourney.start
    stop = flow.GoodsJourney.stop
    get = flow.GoodsJourney.get
    post = flow.GoodsJourney.post
    join = flow.GoodsJourney.join
    setup_world = flow.GoodsJourney.setup_world
    take_pick = condition.BodyCondition.take_pick

    def refused(self, body, world, player=None, path='/api/workshop/thumbnail'):
        with self.assertRaises(urllib.error.HTTPError) as refusal:
            self.post(path, body, world, player)
        self.assertEqual(400, refusal.exception.code)
        return json.load(refusal.exception)['error']

    def test_owner_keeps_a_picture_and_every_inventory_view_names_it(self):
        world, owner, app = self.setup_world(); self.take_pick(world, app); sid = app.live.session.id
        self.assertNotIn('thumbnail_rev', self.post('/api/world/inventory/shown', {'session': sid}, world)['hands']['right'])
        first = png()
        kept = self.post('/api/workshop/thumbnail', {'item_id': 'field pick', 'png_data_url': data_url(first)}, world)
        kept.pop('persistence', None)
        rev = hashlib.sha256(first).hexdigest()[:12]
        self.assertEqual({'ok': True, 'item_id': 'field pick', 'thumbnail_rev': rev}, kept)
        # What the pages poll carries the revision, not the picture.
        held = self.post('/api/world/inventory/shown', {'session': sid}, world)['hands']['right']
        self.assertEqual(rev, held['thumbnail_rev']); self.assertNotIn('png_data_url', held)
        carried = next(t for t in self.post('/api/workshop/inventory', {}, world)['carried'] if t['id'] == 'field pick')
        self.assertEqual(rev, carried['thumbnail_rev'])
        got = self.post('/api/workshop/thumbnails', {'items': ['field pick', 'no such thing']}, world)['thumbnails']
        self.assertEqual({'field pick': {'thumbnail_rev': rev, 'png_data_url': data_url(first)}}, got)
        # A newer picture replaces the older one.
        second = png(rgba=(30, 90, 200, 255))
        self.post('/api/workshop/thumbnail', {'item_id': 'field pick', 'png_data_url': data_url(second)}, world)
        got = self.post('/api/workshop/thumbnails', {'items': ['field pick']}, world)['thumbnails']['field pick']
        self.assertEqual(data_url(second), got['png_data_url'])
        rev = hashlib.sha256(second).hexdigest()[:12]; self.assertEqual(rev, got['thumbnail_rev'])
        # And it is kept with the world, through a restart.
        self.assertTrue(flow.server.keep_world(app, 'item picture persistence'))
        self.stop(); self.start()
        self.post('/api/world/player/join', {'token': owner['token']}, world)
        self.post('/api/world/open', {}, world); app = self.app.hub.get(world)
        held = self.post('/api/world/inventory/shown', {'session': app.live.session.id}, world)['hands']['right']
        self.assertEqual(rev, held['thumbnail_rev'])
        self.assertEqual(data_url(second), self.post('/api/workshop/thumbnails', {'items': ['field pick']}, world)
                         ['thumbnails']['field pick']['png_data_url'])

    def test_someone_elses_thing_and_anything_but_a_small_png_are_refused(self):
        world, owner, app = self.setup_world(); self.take_pick(world, app)
        good = data_url(png())
        peer = self.join(world, 'Picture peer')
        self.assertIn('Only the person who has this thing',
                      self.refused({'item_id': 'field pick', 'png_data_url': good}, world, peer['token']))
        self.assertIn('no such thing', self.refused({'item_id': 'nothing here', 'png_data_url': good}, world))
        # Not a PNG data URL, not base64, not a PNG inside, too big.
        for bad, why in ((f"data:image/jpeg;base64,{base64.b64encode(png()).decode()}", 'data:image/png'),
                         ('https://example.com/pick.png', 'data:image/png'),
                         ('data:image/png;base64,***', 'base64'),
                         (data_url(b'GIF89a' + b'\0' * 64), 'not a PNG'),
                         ('data:image/png;base64,' + 'A' * (65 * 1024), 'under 64 KB')):
            with self.subTest(why=why):
                self.assertIn(why, self.refused({'item_id': 'field pick', 'png_data_url': bad}, world))
        # Past the route's own body bound: refused before it is read as JSON.
        with self.assertRaises(urllib.error.HTTPError) as refusal:
            self.post('/api/workshop/thumbnail', {'item_id': 'field pick',
                                                  'png_data_url': 'data:image/png;base64,' + 'A' * (80 * 1024)}, world)
        self.assertEqual(400, refusal.exception.code)
        for body in ({'item_id': 'field pick'}, {'item_id': 7, 'png_data_url': good},
                     {'item_id': 'field pick', 'png_data_url': good, 'extra': 1}):
            with self.subTest(body=sorted(body)):
                self.refused(body, world)
        self.refused({'items': 'field pick'}, world, path='/api/workshop/thumbnails')
        self.refused({'items': [str(i) for i in range(41)]}, world, path='/api/workshop/thumbnails')
        # Nothing refused was kept.
        self.assertEqual({}, self.post('/api/workshop/thumbnails', {'items': ['field pick']}, world)['thumbnails'])
        self.assertNotIn('thumbnail_rev', self.post('/api/world/inventory/shown',
                                                    {'session': app.live.session.id}, world)['hands']['right'])

    def test_world_page_pictures_a_held_thing_and_every_view_shows_the_kept_picture(self):
        if not flow.qa_browser.CHROME.is_file():
            if flow.os.environ.get('BANJO_BROWSER_TESTS') == 'required': self.fail('Chrome is required')
            self.skipTest('Chrome not installed')
        world, owner, app = self.setup_world(); self.take_pick(world, app)
        chrome = flow.qa_browser.Chrome(1280, 800); self.chrome = chrome; self.addCleanup(chrome.close)
        p = chrome.page; p.send('Page.enable'); p.send('Runtime.enable')
        p.send('Page.addScriptToEvaluateOnNewDocument',
               {'source': f'localStorage.setItem("banjo.player.{world}",{json.dumps(owner["token"])});'})

        def wait(expr, seconds=45):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if p.evaluate('Boolean(' + expr + ')'): return
                time.sleep(.1)
            out = ROOT / 'build/resource-flow'; out.mkdir(parents=True, exist_ok=True)
            (out / 'item-picture-failure.png').write_bytes(
                base64.b64decode(p.send('Page.captureScreenshot', {'format': 'png'})['data']))
            self.fail(expr + '; ' + str(p.evaluate('document.body.innerText.slice(-1500)')))

        def kept():
            return self.post('/api/workshop/thumbnails', {'items': ['field pick']}, world)['thumbnails'].get('field pick')

        # Nobody has pictured the pick: the world page draws it from its mesh
        # and sends that, and the strip shows it.
        self.assertIsNone(kept())
        p.send('Page.navigate', {'url': self.base + f'/world?world={world}&hold=1'})
        wait('window.banjoRoom?.ready()')
        deadline = time.monotonic() + 45
        while kept() is None and time.monotonic() < deadline: time.sleep(.2)
        picture = kept(); self.assertIsNotNone(picture, 'The world page sent no picture of the held pick')
        raw = base64.b64decode(picture['png_data_url'].split(',', 1)[1])
        self.assertTrue(raw.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertEqual((128, 128), struct.unpack('>II', raw[16:24]))
        wait('document.querySelector("#inventory-strip .strip-item[data-hand] img")?.src===%s'
             % json.dumps(picture['png_data_url']))
        # A fresh page has no picture of its own: it reads the kept one.
        p.send('Page.navigate', {'url': self.base + f'/world?world={world}&hold=1'})
        wait('window.banjoRoom?.ready()')
        wait('document.querySelector("#inventory-strip .strip-item[data-hand] img")?.src===%s'
             % json.dumps(picture['png_data_url']))
        self.assertEqual(picture, kept(), 'A page re-sent a picture the server already had')
        out = ROOT / 'build/resource-flow'; out.mkdir(parents=True, exist_ok=True)
        (out / 'item-picture-strip.png').write_bytes(
            base64.b64decode(p.send('Page.captureScreenshot', {'format': 'png'})['data']))
        # And the Workshop's Inventory shows the same picture.
        p.send('Page.navigate', {'url': self.base + f'/world?world={world}&workshop=1&tab=inventory'})
        wait('document.querySelector(\'#ws-inv-grid [data-product="field pick"] img.item-picture\')?.src===%s'
             % json.dumps(picture['png_data_url']))
        self.assertEqual([], [e for e in p.events if e.get('method') == 'Runtime.exceptionThrown'])


if __name__ == '__main__':
    unittest.main()
