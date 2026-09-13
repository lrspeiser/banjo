"""A playground anyone can reach is behind a password.

    python tests/access_gate_tests.py -v

On a desktop the server listens on 127.0.0.1 only and is used by whoever sits
at it. Hosted (docs/deploy.md), it listens on every interface, and anyone who
found the address could open the room and spend its owner's model credits
through the chat. So a server anyone can reach needs BANJO_PASSWORD, and with
one every request -- the page, its scripts and every API -- needs a session
that only the right password gets. These tests start the real handler with a
stand-in for the live world: no engine and no model.
"""
from __future__ import annotations

import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest import mock
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "playground"))

from playground_tests import PlaygroundTestCase, playground_server  # noqa: E402
from room_store_tests import StandInLive  # noqa: E402

PASSWORD = "correct horse battery staple"
PUBLIC = "banjo-playground.fly.dev"


class GateTestCase(PlaygroundTestCase):
    password: str | None = PASSWORD

    def setUp(self):
        super().setUp()
        self.app = self.make_app(mock.Mock())
        self.app.live = StandInLive()
        self.app.password = self.password
        self.app.public_host = PUBLIC
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), playground_server.Handler)
        self.httpd.app = self.app
        thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        thread.start()

        def stop():
            self.httpd.shutdown()
            self.httpd.server_close()
            thread.join(timeout=3)
        self.addCleanup(stop)
        self.port = self.httpd.server_port

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def log_in(self, password=PASSWORD, **headers):
        return self.request("POST", "/login", body=urlencode({"password": password}),
                            headers={"Content-Type": "application/x-www-form-urlencoded", **headers})

    def session(self):
        status, headers, _ = self.log_in()
        self.assertEqual(status, 303)
        return headers["Set-Cookie"].split(";")[0]      # "banjo_session=..."

    def open_room(self, cookie=None, **extra):
        headers = {"Content-Type": "application/json", "X-Banjo-Token": self.app.csrf_token, **extra}
        if cookie:
            headers["Cookie"] = cookie
        return self.request("POST", "/api/world/open", body=json.dumps({"scene": "yard"}),
                            headers=headers)


class WithAPassword(GateTestCase):
    def test_nothing_is_served_before_logging_in(self):
        status, headers, _ = self.request("GET", "/world")
        self.assertEqual((status, headers.get("Location")), (303, "/login"))
        for path in ("/api/status", "/world.js", "/vendor/three.module.js"):
            with self.subTest(path=path):
                status, _, body = self.request("GET", path)
                self.assertIn(status, (303, 401), body)
        status, _, body = self.open_room()
        self.assertEqual(status, 401, body)
        self.assertEqual(self.app.live.opened, [], "a world opened for someone who had not logged in")

    def test_the_login_page_asks_for_the_password(self):
        status, headers, body = self.request("GET", "/login")
        self.assertEqual(status, 200)
        self.assertIn(b'type="password"', body)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))

    def test_a_wrong_password_gets_no_session(self):
        status, headers, _ = self.log_in("guess")
        self.assertEqual(status, 401)
        self.assertNotIn("Set-Cookie", headers)

    def test_the_right_password_opens_everything(self):
        status, headers, _ = self.log_in()
        self.assertEqual((status, headers.get("Location")), (303, "/world"))
        cookie = headers["Set-Cookie"]
        for flag in ("HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(flag, cookie)
        session = cookie.split(";")[0]
        status, _, _ = self.request("GET", "/world", headers={"Cookie": session})
        self.assertEqual(status, 200)
        status, _, body = self.request("GET", "/api/status", headers={"Cookie": session})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["csrf_token"], self.app.csrf_token)
        status, _, body = self.open_room(session)
        self.assertEqual(status, 200, body)

    def test_a_session_still_needs_the_page_token(self):
        session = self.session()
        status, _, _ = self.request("POST", "/api/world/open", body=json.dumps({"scene": "yard"}),
                                    headers={"Content-Type": "application/json", "Cookie": session})
        self.assertEqual(status, 403)

    def test_a_made_up_session_is_refused(self):
        status, _, _ = self.open_room("banjo_session=not-one-the-server-gave")
        self.assertEqual(status, 401)

    def test_over_https_the_cookie_is_secure(self):
        status, headers, _ = self.log_in(**{"X-Forwarded-Proto": "https"})
        self.assertEqual(status, 303)
        self.assertIn("Secure", headers["Set-Cookie"])

    def test_the_public_name_is_a_host_it_answers_to(self):
        session = self.session()
        status, _, _ = self.request("GET", "/world", headers={"Cookie": session, "Host": PUBLIC})
        self.assertEqual(status, 200)
        status, _, _ = self.request("GET", "/world", headers={"Cookie": session, "Host": "evil.example"})
        self.assertEqual(status, 400)
        status, _, body = self.open_room(session, Host=PUBLIC, Origin=f"https://{PUBLIC}")
        self.assertEqual(status, 200, body)


class WithoutAPassword(GateTestCase):
    password = None

    def test_on_a_desktop_nothing_changes(self):
        status, _, _ = self.request("GET", "/world")
        self.assertEqual(status, 200)
        status, _, body = self.open_room()
        self.assertEqual(status, 200, body)


class WhoMayListenWhere(unittest.TestCase):
    def test_a_server_anyone_can_reach_needs_a_password(self):
        import access_gate   # playground/, put on the path above
        self.assertIn("BANJO_PASSWORD", access_gate.refusal("0.0.0.0", ""))
        self.assertIn("BANJO_PASSWORD", access_gate.refusal("192.168.1.20", None))
        for host in ("127.0.0.1", "localhost", "::1"):
            with self.subTest(host=host):
                self.assertIsNone(access_gate.refusal(host, ""))
        self.assertIsNone(access_gate.refusal("0.0.0.0", PASSWORD))


if __name__ == "__main__":
    unittest.main(verbosity=2)
