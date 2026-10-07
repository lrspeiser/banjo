"""Actual file identity, secret exclusion and unknown native provenance."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import threading
from unittest import mock
from types import SimpleNamespace
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "playground"))
import build_manifest


class Identity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "playground/vendor").mkdir(parents=True)
        (self.root / "src").mkdir()
        (self.root / "playground/world.js").write_text("client")
        (self.root / "playground/vendor/three.js").write_text("dependency")
        (self.root / "src/world.cpp").write_text("kernel")
        (self.root / ".env").write_text("OPENAI_API_KEY=private-fixture")
        self.native = self.root / "engine.exe"
        self.native.write_bytes(b"native build A")

    def capture(self):
        return build_manifest.capture(root=self.root, native={"live": self.native})

    def test_source_client_and_binary_changes_are_distinguished(self):
        first = self.capture()
        (self.root / "src/world.cpp").write_text("kernel changed")
        second = self.capture()
        self.assertNotEqual(first["application"]["sha256"], second["application"]["sha256"])
        self.assertEqual(first["client"], second["client"])
        self.assertEqual(first["native"], second["native"])
        (self.root / "playground/vendor/three.js").write_text("changed dependency")
        third = self.capture()
        self.assertNotEqual(second["client"], third["client"])
        self.assertEqual(second["application"], third["application"])
        self.native.write_bytes(b"native build B with other content")
        fourth = self.capture()
        self.assertNotEqual(third["native"], fourth["native"])
        self.assertNotEqual(first["id"], fourth["id"])

    def test_credentials_and_local_paths_are_never_returned(self):
        before = self.capture()
        (self.root / ".env").write_text("changed-secret")
        after = self.capture()
        self.assertEqual(before, after)
        encoded = json.dumps(after)
        self.assertNotIn(str(self.root), encoded)
        self.assertNotIn("secret", encoded)
        self.assertIsNone(after["actual_native_abi"])
        self.assertEqual(after["native"]["live"]["build_provenance"], "unrecorded")

    def test_missing_native_is_explicit(self):
        self.native.unlink()
        manifest = self.capture()
        self.assertFalse(manifest["native"]["live"]["available"])
        self.assertIsNone(manifest["native"]["live"]["sha256"])

    def test_manifest_is_served_over_http_with_host_checks(self):
        import server
        from http.server import ThreadingHTTPServer
        manifest = self.capture()
        manifest['configuration']['clock_enabled'] = True
        host = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        host.app = SimpleNamespace(build_manifest=manifest)
        thread = threading.Thread(target=host.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{host.server_port}'
            with urlopen(base+'/api/build', timeout=5) as response:
                self.assertEqual(json.load(response), manifest)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
            with self.assertRaises(HTTPError) as refused:
                urlopen(Request(base+'/api/build', headers={'Host':'untrusted.invalid'}), timeout=5)
            self.assertEqual(refused.exception.code, 400)
        finally:
            host.shutdown()
            host.server_close()
            thread.join(timeout=5)

    def test_effective_mode_updates_without_rehashing_startup_files(self):
        with mock.patch.dict('os.environ', {'BANJO_WORLD_CLOCK':'0'}), \
                mock.patch.object(build_manifest, 'startup_source', return_value=self.capture()) as source:
            app = SimpleNamespace()
            first = build_manifest.for_app(app)
            self.assertFalse(first['configuration']['clock_enabled'])
            app.live_inprocess = True
            second = build_manifest.for_app(app)
            self.assertTrue(second['configuration']['inprocess'])
            self.assertNotEqual(first['id'], second['id'])
            self.assertEqual(first['application'], second['application'])
            source.assert_called_once()


if __name__ == "__main__":
    unittest.main()
