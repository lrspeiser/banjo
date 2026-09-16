"""The password in front of a playground anyone can reach (docs/deploy.md).

On a desktop the server listens on 127.0.0.1, only whoever sits at it can reach
it, and there is no password: nothing here does anything. Hosted, it listens on
every interface, and anyone who found the address could open the room and
spend its owner's model credits through the chat. So a server that listens
anywhere but loopback must have BANJO_PASSWORD -- main() will not start without
one -- and with one, every request (the page, its scripts and every API) needs a
session that only the right password gets: an HttpOnly, SameSite=Strict cookie,
Secure when the request came over HTTPS. Sessions are held in memory, so a
server started again asks again.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
from pathlib import Path
import re
import secrets
import threading
import time
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlsplit

COOKIE = "banjo_session"
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
# What a person opens by its address: asked for without a session, it goes to
# the login page. Anything else asked for without one is told to log in.
PAGES = frozenset({"/", "/index.html", "/world", "/world.html"})
WRONG_PASSWORD_DELAY_S = 1.0
# The same policy the server's other answers carry: nothing inline, nothing
# from anywhere else. The world page has one deliberately inline module, which
# chooses between the normal room driver and the isolated Workshop, and one
# deliberately inline stylesheet, which is the Workshop's whole layout. Rather
# than weakening this policy with unsafe-inline, authorize exactly those two
# blocks by their SHA-256 hashes when /world is served; see
# _install_world_csp_hashes().
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'")
_lock = threading.Lock()

LOGIN_CSS = """:root { color-scheme: dark; }
body { margin: 0; min-height: 100vh; display: grid; place-items: center;
       background: #10151b; color: #d8dee6; font: 16px/1.5 system-ui, sans-serif; }
main { width: min(22rem, 90vw); }
h1 { margin: 0 0 0.25rem; font-size: 1.1rem; letter-spacing: 0.12em; }
p { margin: 0 0 1.25rem; color: #93a0ad; }
form { display: grid; gap: 0.6rem; }
input, button { font: inherit; padding: 0.6rem 0.75rem; border-radius: 6px; }
input { border: 1px solid #2c3743; background: #161d25; color: inherit; }
input:focus-visible, button:focus-visible { outline: 2px solid #6fb3ff; outline-offset: 2px; }
button { border: 0; background: #2f6fb3; color: #fff; cursor: pointer; }
.said { margin-top: 1rem; color: #ffb4a8; }
"""


def _world_inline_hashes(pattern: str) -> list[str]:
    """CSP source hashes for world.html's inline blocks matching `pattern`.

    The hash covers a block's exact text content, which is what the browser
    hashes too: an HTML parser normalizes CRLF to LF before tokenizing, and
    read_text() does the same, so a CRLF checkout still agrees.
    """
    try:
        text = (Path(__file__).resolve().parent / "world.html").read_text(encoding="utf-8")
    except OSError:
        return []
    found = []
    for match in re.finditer(pattern, text, re.DOTALL):
        digest = hashlib.sha256(match.group(1).encode("utf-8")).digest()
        found.append("'sha256-" + base64.b64encode(digest).decode("ascii") + "'")
    return found


def _install_world_csp_hashes() -> None:
    """Authorize world.html's exact inline blocks, without unsafe-inline.

    The world page has one inline module, which chooses between the normal room
    driver and the isolated Workshop, and one inline stylesheet, which is the
    Workshop's whole layout. Both must be named in the policy or the browser
    drops them silently: with the stylesheet dropped, world.css's full-viewport
    `#stage` canvas -- never given a WebGL context on the Workshop page, so
    invisible -- stays on top of the Workshop and swallows every click.

    server.py owns the ordinary response header and access_gate owns the hosted
    login response. Both ultimately call BaseHTTPRequestHandler.send_header, so
    wrapping it here keeps the policies aligned without duplicating the hashes
    in two places. Only /world and /world.html are changed, and only the
    script-src and style-src directives are extended.
    """
    wanted = {
        "script-src 'self'": _world_inline_hashes(r'<script\s+type=["\']module["\']>(.*?)</script>'),
        "style-src 'self'": _world_inline_hashes(r"<style\b[^>]*>(.*?)</style>"),
    }
    wanted = {needle: hashes for needle, hashes in wanted.items() if hashes}
    if not wanted:
        return
    original = BaseHTTPRequestHandler.send_header
    if getattr(original, "_banjo_world_csp_hash", False):
        return

    def send_header(handler: Any, keyword: str, value: str) -> None:
        if keyword.lower() == "content-security-policy":
            path = urlsplit(getattr(handler, "path", "")).path
            if path in {"/world", "/world.html"}:
                for needle, hashes in wanted.items():
                    missing = [h for h in hashes if h not in value]
                    if missing and needle in value:
                        value = value.replace(needle, " ".join([needle, *missing]), 1)
        original(handler, keyword, value)

    send_header._banjo_world_csp_hash = True  # type: ignore[attr-defined]
    BaseHTTPRequestHandler.send_header = send_header


_install_world_csp_hashes()


def refusal(host: str, password: str | None) -> str | None:
    """Why the server must not listen on `host`, or None when it may."""
    if host in LOOPBACK or password:
        return None
    return (f"listening on {host} lets anyone reach this playground, and it has no password: "
            f"set BANJO_PASSWORD (docs/deploy.md), or listen on 127.0.0.1")


def _sessions(app: Any) -> set[str]:
    with _lock:
        if not isinstance(getattr(app, "sessions", None), set):
            app.sessions = set()
        return app.sessions


def _session_of(handler: Any) -> str | None:
    cookie = SimpleCookie()
    try:
        cookie.load(handler.headers.get("Cookie", ""))
    except CookieError:
        return None
    morsel = cookie.get(COOKIE)
    return morsel.value if morsel else None


def signed_in(handler: Any) -> bool:
    token = _session_of(handler)
    return bool(token) and token in _sessions(handler.server.app)


def _login_page(said: str = "") -> bytes:
    note = f'<p class="said" role="alert">{html.escape(said)}</p>' if said else ""
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Banjo</title><link rel="stylesheet" href="/login.css"></head>'
            '<body><main><h1>BANJO</h1><p>This playground is behind a password.</p>'
            '<form method="post" action="/login"><label for="password">Password</label>'
            '<input id="password" name="password" type="password" autocomplete="current-password"'
            ' required autofocus><button type="submit">Log in</button></form>'
            f'{note}</main></body></html>').encode()


def _offered(handler: Any, body: bytes) -> str | None:
    kind = handler.headers.get("Content-Type", "").split(";")[0].strip()
    try:
        if kind == "application/json":
            value = json.loads(body or b"{}").get("password")
        else:
            value = (parse_qs(body.decode("utf-8")).get("password") or [None])[0]
    except (ValueError, AttributeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, str) else None


def _send(handler: Any, status: int, data: bytes, content_type: str,
          extra: dict[str, str] | None = None) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type + "; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    if handler.close_connection:
        handler.send_header("Connection", "close")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Security-Policy", CSP)
    for name, value in (extra or {}).items():
        handler.send_header(name, value)
    handler.end_headers()
    handler.wfile.write(data)


def answered(handler: Any, method: str, body: bytes = b"") -> bool:
    """Deal with the request here when it is the gate's: the login page, logging
    in or out, or anything asked for without a session while there is a
    password. True when an answer has been sent; False when the request goes on
    as it always did."""
    app = handler.server.app
    password = getattr(app, "password", None)
    if not password:
        return False
    path = urlsplit(handler.path).path
    if method == "GET" and path == "/login":
        _send(handler, 200, _login_page(), "text/html")
        return True
    if method == "GET" and path == "/login.css":
        _send(handler, 200, LOGIN_CSS.encode(), "text/css")
        return True
    if method == "POST" and path == "/login":
        offered = _offered(handler, body)
        if offered is not None and hmac.compare_digest(offered.encode(), password.encode()):
            token = secrets.token_urlsafe(32)
            _sessions(app).add(token)
            secure = "; Secure" if handler.headers.get("X-Forwarded-Proto", "").lower() == "https" else ""
            _send(handler, 303, b"", "text/plain",
                  {"Location": "/world",
                   "Set-Cookie": f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/{secure}"})
        else:
            # Guessing costs a second a try.
            time.sleep(WRONG_PASSWORD_DELAY_S)
            _send(handler, 401, _login_page("That is not the password."), "text/html")
        return True
    if path == "/logout":
        token = _session_of(handler)
        if token:
            _sessions(app).discard(token)
        _send(handler, 303, b"", "text/plain",
              {"Location": "/login",
               "Set-Cookie": f"{COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
        return True
    if signed_in(handler):
        return False
    if method == "GET" and path in PAGES:
        _send(handler, 303, b"", "text/plain", {"Location": "/login"})
    else:
        _send(handler, 401, json.dumps({"error": "log in first", "login": "/login"}).encode(),
              "application/json")
    return True
