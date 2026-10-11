"""A Chrome to drive from a test: started headless with a profile of its own,
spoken to over the DevTools protocol (Page, Input, Emulation, Runtime).
tests/machine_game_browser_tests.py uses it to play the game as a person does.

BANJO_CHROME names the browser; by default, Chrome where Windows installs it.
"""
from __future__ import annotations

import atexit
import base64
import http.client
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "build" / "qa-chrome"
CHROME = Path(os.environ.get("BANJO_CHROME")
              or "C:/Program Files/Google/Chrome/Application/chrome.exe")
VIEWPORT = (1280, 800)

# ---------------------------------------------------------------------------

class _PlainSocket:
    """A WebSocket client from the standard library, enough for DevTools:
    text frames out, masked as a client's must be; frames back however long,
    in one or several; a ping answered. For where the `websockets` package is
    not installed -- CI's system Python refuses a pip install into it -- and
    only ever for a browser on this machine."""

    def __init__(self, url: str, timeout: float = 15.0) -> None:
        import secrets
        import socket
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        self._sock = socket.create_connection((parts.hostname, parts.port or 80), timeout=timeout)
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        path = parts.path + (f"?{parts.query}" if parts.query else "")
        self._sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {parts.hostname}:{parts.port}\r\n"
                            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("the browser closed the socket during the handshake")
            head += chunk
        head, _, self._buffer = head.partition(b"\r\n\r\n")
        if not head.startswith(b"HTTP/1.1 101"):
            raise ConnectionError(f"the browser refused the socket: {head.splitlines()[0]!r}")

    def _exactly(self, n: int, deadline: float) -> bytes:
        while len(self._buffer) < n:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("the browser did not answer in time")
            self._sock.settimeout(left)
            chunk = self._sock.recv(max(65536, n - len(self._buffer)))
            if not chunk:
                raise ConnectionError("the browser closed the socket")
            self._buffer += chunk
        out, self._buffer = self._buffer[:n], self._buffer[n:]
        return out

    def _frame(self, opcode: int, payload: bytes) -> None:
        import secrets
        import struct
        n = len(payload)
        head = bytes([0x80 | opcode]) + (bytes([0x80 | n]) if n < 126 else
                                         bytes([0x80 | 126]) + struct.pack("!H", n) if n < 65536 else
                                         bytes([0x80 | 127]) + struct.pack("!Q", n))
        mask = secrets.token_bytes(4)
        self._sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def send(self, text: str) -> None:
        self._frame(0x1, text.encode("utf-8"))

    def recv(self, timeout: float | None = None) -> str:
        import struct
        deadline = time.monotonic() + (3600.0 if timeout is None else timeout)
        message = b""
        while True:
            first, second = self._exactly(2, deadline)
            opcode, n = first & 0x0F, second & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._exactly(2, deadline))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._exactly(8, deadline))[0]
            mask = self._exactly(4, deadline) if second & 0x80 else b""
            payload = self._exactly(n, deadline)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:
                raise ConnectionError("the browser closed the socket")
            if opcode == 0x9:
                self._frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            message += payload
            if first & 0x80:
                return message.decode("utf-8")

    def close(self) -> None:
        try:
            self._frame(0x8, b"")
        except OSError:
            pass
        self._sock.close()


class DevTools:
    """One DevTools connection: commands out, their answers back, and every
    event that arrived in between kept in `events`."""

    def __init__(self, url: str) -> None:
        try:
            if os.environ.get("BANJO_DEVTOOLS_PLAIN"):
                raise ImportError("the plain socket was asked for")
            from websockets.sync.client import connect
        except ImportError:
            # Without the package (CI's system Python), or when asked for it.
            self.socket = _PlainSocket(url)
        else:
            # No size limit (a screenshot is megabytes of base64), no compression
            # and no keepalive pings: this is a local socket to a local browser.
            self.socket = connect(url, max_size=None, compression=None, ping_interval=None,
                                  open_timeout=15, max_queue=1024)
        self.next_id = 0
        self.events: list[dict[str, Any]] = []

    def send(self, method: str, params: dict[str, Any] | None = None,
             timeout: float = 30.0) -> dict[str, Any]:
        self.next_id += 1
        ident = self.next_id
        self.socket.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"DevTools did not answer {method} within {timeout:.0f} s")
            message = json.loads(self.socket.recv(timeout=left))
            if message.get("id") == ident:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error'].get('message')}")
                return message.get("result") or {}
            if "method" in message:
                self.events.append(message)

    def evaluate(self, expression: str, await_promise: bool = False,
                 timeout: float = 30.0) -> Any:
        """Run JavaScript in the page's own world -- where window.banjoRoom is."""
        answer = self.send("Runtime.evaluate", {"expression": expression, "returnByValue": True,
                                                "awaitPromise": await_promise}, timeout)
        if "exceptionDetails" in answer:
            detail = answer["exceptionDetails"]
            raise RuntimeError((detail.get("exception") or {}).get("description")
                               or detail.get("text") or "the page threw")
        return (answer.get("result") or {}).get("value")

    def close(self) -> None:
        try:
            self.socket.close()
        except Exception:
            pass


class Chrome:
    """One headless Chrome on a profile of its own, closed by its PID."""

    def __init__(self, width: int = VIEWPORT[0], height: int = VIEWPORT[1]) -> None:
        if not CHROME.is_file():
            raise RuntimeError(f"Chrome is not at {CHROME}; set BANJO_CHROME to it")
        PROFILES.mkdir(parents=True, exist_ok=True)
        # A profile per Chrome. A second Chrome on a profile that is already open
        # hands its command line to the first and exits -- leaving a PID that is
        # gone and a browser nobody launched.
        self.profile = PROFILES / f"chrome-{os.getpid()}-{time.time_ns()}"
        self.page: DevTools | None = None
        self.process: subprocess.Popen | None = subprocess.Popen(
            [str(CHROME), "--headless=new", "--remote-debugging-port=0",
             f"--user-data-dir={self.profile}", f"--window-size={width},{height}",
             "--no-first-run", "--no-default-browser-check", "--disable-extensions",
             "--disable-sync", "--mute-audio", "--hide-scrollbars",
             # A page that is not being looked at is throttled to about one tick
             # a second, which reads as the room running at a fraction of real
             # time. Headless is always looked at; these make sure of it.
             "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
             "--disable-backgrounding-occluded-windows",
             # Whatever else this machine's Chrome needs, as BANJO_CHROME_ARGS
             # says: CI's Ubuntu keeps its sandbox from the user namespaces it
             # wants (--no-sandbox), and has no GPU for WebGL but SwiftShader.
             *os.environ.get("BANJO_CHROME_ARGS", "").split(),
             "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.pid = self.process.pid
        atexit.register(self.close)
        try:
            self.port, self.browser_path = self._devtools_port()
            self.page = DevTools(self._page_socket())
            # A new player starts as a body now. Suites about other things keep
            # the camera walk they were written against, unless they choose a
            # movement themselves (BANJO_TEST_MOVEMENT, or localStorage).
            movement = os.environ.get("BANJO_TEST_MOVEMENT", "gravity")
            if movement:
                self.page.send("Page.addScriptToEvaluateOnNewDocument", {"source":
                    "try{if(!localStorage.getItem('banjo.movement'))"
                    f"localStorage.setItem('banjo.movement','{movement}')}}catch(e){{}}"})
        except Exception:
            self.close()
            raise

    def _devtools_port(self, timeout_s: float = 30.0) -> tuple[int, str]:
        """Chrome picks its own port (so no other session's browser is in the
        way) and writes it, with the browser's socket path, into the profile."""
        marker = self.profile / "DevToolsActivePort"
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            assert self.process is not None
            if self.process.poll() is not None:
                raise RuntimeError(f"Chrome exited while starting (code {self.process.returncode})")
            try:
                lines = marker.read_text(encoding="utf-8").split()
                if len(lines) >= 2:
                    return int(lines[0]), lines[1]
            except (OSError, ValueError):
                pass
            time.sleep(0.05)
        raise RuntimeError("Chrome never opened its DevTools port")

    def _http(self, method: str, path: str) -> Any:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path)
            return json.loads(connection.getresponse().read() or b"null")
        finally:
            connection.close()

    def _page_socket(self) -> str:
        for target in self._http("GET", "/json/list") or []:
            if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                return target["webSocketDebuggerUrl"]
        return self._http("PUT", "/json/new?about:blank")["webSocketDebuggerUrl"]

    def close(self) -> None:
        """Close Chrome and make sure of it: by PID, the whole tree, never by
        image name -- other sessions' browsers share that name."""
        process, self.process = self.process, None
        if process is None:
            return
        if self.page is not None:
            self.page.close()
        try:
            browser = DevTools(f"ws://127.0.0.1:{self.port}{self.browser_path}")
            try:
                browser.send("Browser.close", timeout=5)
            finally:
                browser.close()
        except Exception:
            pass   # it went before it could answer, or never came up
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               capture_output=True)
            else:
                process.kill()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        for _ in range(20):
            shutil.rmtree(self.profile, ignore_errors=True)
            if not self.profile.exists():
                break
            time.sleep(0.25)


# ---------------------------------------------------------------------------
# In the page
# ---------------------------------------------------------------------------

# null while the page being left is still the one answering, or before the
# room's handle exists.
