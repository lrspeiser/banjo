"""HTTP host aliases and same-origin API requests for the deployed game."""
import argparse
import concurrent.futures
import http.client
import importlib.util
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('banjo_game_server', ROOT / 'scripts/voxel-lab.py')
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--engine')
args, remaining = parser.parse_known_args()
ENGINE = Path(args.engine or os.environ.get('BANJO_LIVE_ENGINE', ''))


class Configuration(unittest.TestCase):
    def test_single_setting_and_aliases_are_combined_and_normalized(self):
        self.assertEqual(lab.public_hostnames('legacy.example', ' Banjo.is,WWW.BANJO.IS.,banjo.is '),
                         frozenset(('legacy.example', 'banjo.is', 'www.banjo.is')))

    def test_configuration_requires_explicit_hostnames(self):
        for value in ('https://banjo.is', '*.banjo.is', 'banjo.is:443', 'user@banjo.is', 'banjo.is/path'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                lab.public_hostnames(value)


class Requests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not ENGINE.is_file():
            raise RuntimeError('pass --engine or BANJO_LIVE_ENGINE: the verified game executable')
        cls.logs = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.server = lab.Server(('127.0.0.1', 0), ENGINE, Path(cls.logs.name), site='game', public=True,
                                public_host='banjo-f1sv.onrender.com', public_hosts='banjo.is,www.banjo.is')
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.machines.close_all()
        cls.server.server_close()
        cls.logs.cleanup()

    def request(self, hosts, method='GET', path='/play', origin=None, extra=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=10)
        body = json.dumps({'op': 'levels'}).encode() if method == 'POST' else b''
        connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        for host in hosts:
            connection.putheader('Host', host)
        if origin is not None:
            connection.putheader('Origin', origin)
        for key, value in (extra or {}).items():
            connection.putheader(key, value)
        connection.putheader('Content-Length', str(len(body)))
        connection.endheaders(body)
        response = connection.getresponse()
        result = response.status, response.read(), response.getheaders()
        connection.close()
        return result

    def test_pages_and_assets_accept_each_exact_alias_and_loopback(self):
        for host in ('banjo.is', 'www.banjo.is', 'banjo-f1sv.onrender.com', 'BANJO.IS:443',
                     'banjo.is.', 'localhost', '127.0.0.1', '[::1]:18893'):
            for path in ('/play', '/machine', '/machine.js', '/api/checkpoint'):
                with self.subTest(host=host, path=path):
                    self.assertEqual(self.request([host], path=path)[0], 200)
        status, _, headers = self.request(['banjo.is'], path='/')
        self.assertEqual(status, 303)
        self.assertEqual(dict(headers)['Location'], '/play')

    def test_simultaneous_bootstrap_scripts_return_every_complete_body(self):
        # Each browser's bootstrap needs the entire module before setup can
        # start. Exercise the real listener and handler, with no connection
        # retries: a refused/reset script cannot become a ready game.
        expected = (ROOT / 'client/voxel-lab/machine.js').read_bytes()
        for burst in range(3):
            barrier = threading.Barrier(65)
            def client():
                barrier.wait(timeout=10)
                return self.request(['127.0.0.1'], path='/machine.js')
            with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
                requests = [pool.submit(client) for _ in range(64)]
                barrier.wait(timeout=10)
                results = [request.result(timeout=10) for request in requests]
            for index, (status, body, headers) in enumerate(results):
                with self.subTest(burst=burst, request=index):
                    self.assertEqual(status, 200)
                    self.assertEqual(body, expected)
                    self.assertEqual(int(dict(headers)['Content-Length']), len(expected))
            # The same listener must remain usable after all three bursts.
            self.assertEqual(self.request(['127.0.0.1'], path='/play')[0], 200)

    def test_unknown_spoofed_and_malformed_hosts_are_refused(self):
        for hosts in ([], ['evil.example'], ['banjo.is.evil.example'], ['evil@banjo.is'],
                      ['banjo.is/path'], ['banjo.is:invalid'], ['[broken'], ['banjo.is evil'],
                      ['banjo.is', 'evil.example']):
            with self.subTest(hosts=hosts):
                status, body, _ = self.request(hosts, extra={'X-Forwarded-Host': 'banjo.is'})
                self.assertEqual(status, 403)
                self.assertEqual(json.loads(body)['error'], 'Host refused')

    def test_same_origin_api_works_on_each_alias(self):
        for host in ('banjo.is', 'www.banjo.is', 'banjo-f1sv.onrender.com'):
            with self.subTest(host=host):
                status, body, _ = self.request([host], 'POST', '/api/machine', 'https://' + host)
                self.assertEqual(status, 200)
                self.assertTrue(json.loads(body)['ok'])

    def test_allowing_aliases_does_not_allow_cross_origin_api_calls(self):
        for host, origin in (('banjo.is', 'https://evil.example'),
                             ('banjo.is', 'https://www.banjo.is'),
                             ('banjo.is', 'https://banjo-f1sv.onrender.com'),
                             ('evil.example', 'https://evil.example')):
            with self.subTest(host=host, origin=origin):
                status, body, _ = self.request([host], 'POST', '/api/machine', origin)
                self.assertEqual(status, 400)
                self.assertIn('refused', json.loads(body)['error'])


if __name__ == '__main__':
    unittest.main(argv=[__file__, *remaining], verbosity=2)
