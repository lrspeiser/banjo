"""The playground keeps a connection open, so a room is not a new socket a step.

The room steps its world with one request per step, thirty times a second. The
server spoke HTTP/1.0, which closes the connection after every reply, and on
Windows each closed connection stands in TIME_WAIT for two minutes: about 35 a
second from one tab, thousands at a time on the server's port. On 2026-09-12 a
room stopped five minutes in with ERR_NO_BUFFER_SPACE (WSAENOBUFS) -- Windows
had run out of socket buffers -- while the server itself was fine.

These drive the real handler over a real socket, because the connection is the
thing under test, and they never start the engine.
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "playground"))

from playground_tests import PlaygroundTestCase, plan_for, playground_server  # noqa: E402


class ServedOverOneConnection(PlaygroundTestCase):
    def setUp(self):
        super().setUp()
        self.app = self.make_app(mock.Mock(return_value=(plan_for("unsupported"), {"model": "fake-model"})))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), playground_server.Handler)
        self.httpd.app = self.app
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.port = self.httpd.server_port

    def stop_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)

    def connect(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        self.addCleanup(connection.close)
        return connection

    def test_every_kind_of_reply_keeps_the_connection(self):
        """JSON, a page, a refusal and a miss, one after another down one socket.

        A refusal matters most: the room's world refusing a step must not cost
        the connection, or every refused step would be a new socket again.
        """
        connection = self.connect()
        json_body = {"X-Banjo-Token": self.app.csrf_token, "Content-Type": "application/json"}
        asks = [
            ("GET", "/api/status", None, {}, 200),
            ("GET", "/world.js", None, {}, 200),
            ("GET", "/no-such-page", None, {}, 404),
            ("POST", "/api/live/act", {"op": "step", "dt": 0.004, "n": 1}, json_body, 400),
            ("GET", "/api/status", None, {}, 200),
        ]
        first = None
        for method, path, body, headers, expected in asks:
            with self.subTest(method=method, path=path):
                payload = None if body is None else json.dumps(body).encode()
                connection.request(method, path, body=payload, headers=headers)
                response = connection.getresponse()
                response.read()
                self.assertEqual(response.status, expected)
                self.assertEqual(response.version, 11)
                self.assertIsNotNone(response.getheader("Content-Length"),
                                     "a kept connection needs every reply to say how long it is")
                self.assertFalse(response.will_close, f"{path} closed the connection")
                first = first or connection.sock
                self.assertIs(connection.sock, first, "a new connection was opened")

    def test_a_body_refused_before_it_is_read_closes_the_connection(self):
        """Whatever is left of an unread body would be taken for the next request.

        So the refusal says it is the last reply on that connection. The
        request here claims a body past the bound and sends none of it.
        """
        connection = self.connect()
        connection.putrequest("POST", "/api/live/act")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", "40000")
        connection.endheaders()
        response = connection.getresponse()
        response.read()
        self.assertEqual(response.status, 400)
        self.assertEqual(response.getheader("Connection"), "close")
        self.assertTrue(response.will_close)


if __name__ == "__main__":
    unittest.main(verbosity=2)
