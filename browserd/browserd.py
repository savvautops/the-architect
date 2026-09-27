#!/usr/bin/env python3
"""browserd — The Architect's shared browser lane (v0.1).

A browser Nelson and Sock can both drive, externally:
  - Chromium runs here (Spine/nucbox), headless, with a persistent profile.
  - This service wraps Chrome DevTools Protocol over a local websocket and
    exposes a small REST API over HTTPS for remote driving (Sock's sandbox
    only gets HTTPS egress, so the API is plain HTTPS — no websocket needed
    on the driver's side).
  - A phone-first web UI (ui/index.html) gives Nelson tap-to-click control.

Stdlib only — same philosophy as appctl. JSON evidence on every operation:
calling the actuator is not evidence of success.

Env:
  BROWSERD_TOKEN   (required, fail-closed) bearer token for all routes except /healthz
  BROWSERD_PORT    HTTP listen port (default 8901)
  BROWSERD_DEBUG_PORT  Chromium remote-debugging port (default 9222)
  CHROME_BIN       chromium binary (default: chromium on PATH)
  BROWSERD_PROFILE profile dir for session persistence (default ./profile)
"""

import base64
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.1.0"
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class WSError(Exception):
    pass


class CDPError(Exception):
    pass


# ---------------------------------------------------------------- websocket
class WS:
    """Minimal RFC6455 client: text frames, ping/pong, fragmentation. Stdlib."""

    def __init__(self, url, timeout=10):
        assert url.startswith("ws://"), url
        rest = url[5:]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET /{path} HTTP/1.1\r\n"
            f"Host: {hostport}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise WSError("handshake: connection closed")
            resp += chunk
        head, _, self._buf = resp.partition(b"\r\n\r\n")
        head = head.decode("latin1")
        if " 101 " not in head.split("\r\n", 1)[0]:
            raise WSError(f"handshake failed: {head.splitlines()[0]}")
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        if accept not in head:
            raise WSError("handshake: bad accept key")

    def _read(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise WSError("connection closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _send_frame(self, opcode, payload=b""):
        mask = os.urandom(4)
        n = len(payload)
        hdr = bytearray([0x80 | opcode])
        if n < 126:
            hdr.append(0x80 | n)
        elif n < 1 << 16:
            hdr += bytes([0x80 | 126]) + n.to_bytes(2, "big")
        else:
            hdr += bytes([0x80 | 127]) + n.to_bytes(8, "big")
        hdr += mask
        self.sock.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def send_text(self, text):
        self._send_frame(0x1, text.encode())

    def recv_message(self):
        """Next complete text message as str. Answers pings automatically."""
        chunks = []
        while True:
            b1, b2 = self._read(2)
            fin, opcode = b1 & 0x80, b1 & 0x0F
            masked, ln = b2 & 0x80, b2 & 0x7F
            if ln == 126:
                ln = int.from_bytes(self._read(2), "big")
            elif ln == 127:
                ln = int.from_bytes(self._read(8), "big")
            mask = self._read(4) if masked else None
            payload = self._read(ln)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:
                raise WSError("peer closed")
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode in (0x1, 0x0):
                chunks.append(payload)
                if fin:
                    return b"".join(chunks).decode("utf-8")
            # other opcodes ignored


# ---------------------------------------------------------------- CDP driver
class Driver:
    """One attached page target. All calls serialized; auto-reconnects once."""

    def __init__(self, debug_port):
        self.port = debug_port
        self.lock = threading.Lock()
        self.ws = None
        self._id = 0
        self.pending = []
        self.target_id = None
        self._ensure()

    # -- low level -------------------------------------------------
    def _http_get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10) as r:
            return json.loads(r.read())

    def _ensure(self, attach_id=None):
        targets = self._http_get("/json/list")
        page = None
        if attach_id:
            page = next((t for t in targets if t.get("id") == attach_id), None)
        if page is None:
            page = next((t for t in targets if t.get("type") == "page"), None)
        if page is None:
            page = self._http_get("/json/new?about:blank")
        if self.ws:
            try:
                self.ws.sock.close()
            except OSError:
                pass
        self.ws = WS(page["webSocketDebuggerUrl"])
        self.target_id = page["id"]
        self.pending = []
        self.call("Page.enable")
        self.call("Runtime.enable")

    def call(self, method, params=None, timeout=15):
        with self.lock:
            self._id += 1
            cid = self._id
            self.ws.send_text(json.dumps({"id": cid, "method": method, "params": params or {}}))
            deadline = time.time() + timeout
            while True:
                for i, m in enumerate(self.pending):
                    if m.get("id") == cid:
                        del self.pending[i]
                        if "error" in m:
                            raise CDPError(m["error"])
                        return m.get("result", {})
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise CDPError(f"timeout waiting for {method}")
                self.ws.sock.settimeout(remaining)
                try:
                    msg = json.loads(self.ws.recv_message())
                except socket.timeout:
                    raise CDPError(f"timeout waiting for {method}")
                if msg.get("id") == cid:
                    if "error" in msg:
                        raise CDPError(msg["error"])
                    return msg.get("result", {})
                self.pending.append(msg)

    def wait_event(self, name, timeout=15):
        deadline = time.time() + timeout
        with self.lock:
            while True:
                for i, m in enumerate(self.pending):
                    if m.get("method") == name:
                        del self.pending[i]
                        return m.get("params", {})
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None
                self.ws.sock.settimeout(remaining)
                try:
                    msg = json.loads(self.ws.recv_message())
                except (socket.timeout, WSError):
                    return None
                if msg.get("method") == name:
                    return msg.get("params", {})
                self.pending.append(msg)

    def _eval(self, expr):
        r = self.call("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        res = r.get("result", {})
        if "exceptionDetails" in r or res.get("subtype") == "error":
            raise CDPError(str(r.get("exceptionDetails", res.get("description", "eval failed"))))
        return res.get("value")

    # -- verified actions (evidence on every op) -------------------
    def current_url(self):
        try:
            return self._eval("location.href")
        except CDPError:
            return None

    def navigate(self, url):
        before = self.current_url()
        self.call("Page.navigate", {"url": url})
        loaded = self.wait_event("Page.loadEventFired", 20) is not None
        after = self.current_url()
        return {"before": before, "after": after, "loaded": loaded,
                "navigated": bool(after) and after != before}

    def history(self, direction):
        before = self.current_url()
        self._eval({"back": "history.back()", "forward": "history.forward()"}[direction])
        loaded = self.wait_event("Page.loadEventFired", 15) is not None
        after = self.current_url()
        return {"action": direction, "before": before, "after": after, "loaded": loaded}

    def reload(self):
        before = self.current_url()
        self.call("Page.reload")
        loaded = self.wait_event("Page.loadEventFired", 20) is not None
        return {"before": before, "after": self.current_url(), "loaded": loaded}

    def screenshot(self):
        r = self.call("Page.captureScreenshot", {"format": "png"})
        return base64.b64decode(r["data"])

    def click(self, selector=None, x=None, y=None):
        if selector:
            pt = self._eval(
                "(()=>{const el=document.querySelector(" + json.dumps(selector) + ");"
                "if(!el)return null;"
                "el.scrollIntoView({block:'center',inline:'center'});"
                "const r=el.getBoundingClientRect();"
                "return {x:r.x+r.width/2,y:r.y+r.height/2,w:r.width,h:r.height};})()"
            )
            if not pt:
                return {"ok": False, "selector": selector, "error": "not-found"}
            x, y = pt["x"], pt["y"]
        if x is None or y is None:
            raise CDPError("click needs a selector or x,y")
        before = self.current_url()
        for t in ("mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent",
                      {"type": t, "x": x, "y": y, "button": "left", "clickCount": 1})
        time.sleep(0.4)  # let click-driven navigation begin
        return {"ok": True, "selector": selector, "point": {"x": x, "y": y},
                "url_before": before, "url_after": self.current_url()}

    def type_text(self, text, selector=None):
        if selector:
            ok = self._eval(
                "(()=>{const el=document.querySelector(" + json.dumps(selector) + ");"
                "if(!el)return false;el.focus();if('select' in el)el.select();return true;})()"
            )
            if not ok:
                return {"ok": False, "selector": selector, "error": "not-found"}
        self.call("Input.insertText", {"text": text})
        return {"ok": True, "selector": selector, "chars": len(text)}

    KEYS = {"Enter": 13, "Tab": 9, "Escape": 27, "Backspace": 8, "Delete": 46,
            "ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40}

    def key(self, name):
        params = {"key": name}
        if name in self.KEYS:
            params["windowsVirtualKeyCode"] = self.KEYS[name]
            params["code"] = name
        for t in ("keyDown", "keyUp"):
            self.call("Input.dispatchKeyEvent", dict(params, type=t))
        return {"ok": True, "key": name, "url": self.current_url()}

    def dom(self, limit=200):
        """Simplified accessibility tree — the A-tier substrate."""
        self.call("Accessibility.enable")
        r = self.call("Accessibility.getFullAXTree", {})
        all_nodes = r.get("nodes", [])
        nodes = []
        for n in all_nodes:
            role = (n.get("role") or {}).get("value")
            name = (n.get("name") or {}).get("value")
            if role in ("StaticText", "generic", "none") and not name:
                continue
            nodes.append({"role": role, "name": name})
            if len(nodes) >= limit:
                break
        return {"nodes": nodes, "shown": len(nodes), "total": len(all_nodes)}

    def tabs(self):
        ts = self._http_get("/json/list")
        return [{"id": t["id"], "title": t.get("title"), "url": t.get("url"),
                 "active": t["id"] == self.target_id}
                for t in ts if t.get("type") == "page"]

    def new_tab(self, url="about:blank"):
        t = self._http_get("/json/new?" + urllib.parse.quote(url, safe=""))
        return {"id": t["id"], "url": t.get("url")}

    def close_tab(self, tid):
        self._http_get("/json/close/" + tid)
        if tid == self.target_id:
            self._ensure()
        return {"closed": tid}

    def activate_tab(self, tid):
        self._http_get("/json/activate/" + tid)
        self._ensure(attach_id=tid)
        return {"active": tid, "url": self.current_url()}

    def status(self):
        v = self._http_get("/json/version")
        return {"browserd": VERSION,
                "browser": v.get("Browser"),
                "current_url": self.current_url(),
                "viewport": self._eval("({w: window.innerWidth, h: window.innerHeight})"),
                "tabs": self.tabs()}


# ---------------------------------------------------------------- chromium
def ensure_chromium(debug_port, profile_dir, chrome_bin):
    def alive():
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{debug_port}/json/version",
                                       timeout=3) as r:
                json.loads(r.read())
            return True
        except Exception:
            return False

    if alive():
        return "already-running"
    os.makedirs(profile_dir, exist_ok=True)
    subprocess.Popen(
        [chrome_bin, "--headless=new", f"--remote-debugging-port={debug_port}",
         f"--user-data-dir={profile_dir}", "--no-sandbox",
         "--disable-gpu", "--disable-dev-shm-usage", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        if alive():
            return "launched"
        time.sleep(0.5)
    raise RuntimeError("chromium did not expose remote debugging in time")

# ---------------------------------------------------------------- HTTP API
TOKEN = os.environ.get("BROWSERD_TOKEN") or ""
DRIVER = None
UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")


class Handler(BaseHTTPRequestHandler):
    server_version = "browserd/" + VERSION

    def log_message(self, *a):
        pass

    # -- helpers ---------------------------------------------------
    def _send(self, code, body=b"", ctype="application/json"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, indent=1))

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return None

    def _authed(self):
        if self.path == "/healthz":
            return True
        auth = self.headers.get("Authorization") or ""
        return auth == f"Bearer {TOKEN}"

    def _drive(self, fn, *a, **k):
        """Run a driver call; reconnect once on transport failure, then report."""
        try:
            return True, fn(*a, **k)
        except (WSError, CDPError, ConnectionError, socket.timeout, OSError) as e:
            first = f"{type(e).__name__}: {e}"
            try:
                DRIVER._ensure()
                return True, fn(*a, **k)
            except Exception as e2:
                return False, {"ok": False, "error": f"{first} | reconnect: {e2}"}

    # -- routing ---------------------------------------------------
    def do_GET(self):
        if not self._authed():
            return self._json(401, {"ok": False, "error": "unauthorized"})
        parsed = urllib.parse.urlparse(self.path)
        path, q = parsed.path, urllib.parse.parse_qs(parsed.query)

        if path == "/healthz":
            return self._json(200, {"ok": True, "browserd": VERSION})
        if path == "/":
            return self._file("index.html")
        if path.startswith("/ui/"):
            return self._file(path[4:])
        if path == "/api/status":
            ok, res = self._drive(DRIVER.status)
            return self._json(200 if ok else 502, res)
        if path == "/api/screenshot":
            ok, res = self._drive(DRIVER.screenshot)
            if not ok:
                return self._json(502, res)
            return self._send(200, res, "image/png")
        if path == "/api/dom":
            ok, res = self._drive(DRIVER.dom, int(q.get("limit", [200])[0]))
            return self._json(200 if ok else 502, res)
        if path == "/api/tabs":
            ok, res = self._drive(DRIVER.tabs)
            return self._json(200 if ok else 502, res)
        return self._json(404, {"ok": False, "error": "not-found"})

    def do_POST(self):
        if not self._authed():
            return self._json(401, {"ok": False, "error": "unauthorized"})
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self._body()
        if body is None:
            return self._json(400, {"ok": False, "error": "bad-json"})

        if path == "/api/navigate":
            url = body.get("url")
            if not url:
                return self._json(400, {"ok": False, "error": "url required"})
            ok, res = self._drive(DRIVER.navigate, url)
            return self._json(200 if ok else 502, {"ok": ok, **res})
        if path == "/api/back":
            ok, res = self._drive(DRIVER.history, "back")
            return self._json(200 if ok else 502, {"ok": ok, **res})
        if path == "/api/forward":
            ok, res = self._drive(DRIVER.history, "forward")
            return self._json(200 if ok else 502, {"ok": ok, **res})
        if path == "/api/reload":
            ok, res = self._drive(DRIVER.reload)
            return self._json(200 if ok else 502, {"ok": ok, **res})
        if path == "/api/click":
            ok, res = self._drive(DRIVER.click, body.get("selector"), body.get("x"), body.get("y"))
            return self._json(200 if ok and res.get("ok", True) else 502, res)
        if path == "/api/type":
            text = body.get("text")
            if text is None:
                return self._json(400, {"ok": False, "error": "text required"})
            ok, res = self._drive(DRIVER.type_text, text, body.get("selector"))
            return self._json(200 if ok and res.get("ok", True) else 502, res)
        if path == "/api/key":
            name = body.get("key")
            if not name:
                return self._json(400, {"ok": False, "error": "key required"})
            ok, res = self._drive(DRIVER.key, name)
            return self._json(200 if ok else 502, res)
        if path == "/api/tabs":
            ok, res = self._drive(DRIVER.new_tab, body.get("url", "about:blank"))
            return self._json(200 if ok else 502, res)
        if path == "/api/tabs/activate":
            tid = body.get("id")
            if not tid:
                return self._json(400, {"ok": False, "error": "id required"})
            ok, res = self._drive(DRIVER.activate_tab, tid)
            return self._json(200 if ok else 502, res)
        return self._json(404, {"ok": False, "error": "not-found"})

    def do_DELETE(self):
        if not self._authed():
            return self._json(401, {"ok": False, "error": "unauthorized"})
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/tabs":
            tid = urllib.parse.parse_qs(parsed.query).get("id", [None])[0]
            if not tid:
                return self._json(400, {"ok": False, "error": "id required"})
            ok, res = self._drive(DRIVER.close_tab, tid)
            return self._json(200 if ok else 502, res)
        return self._json(404, {"ok": False, "error": "not-found"})

    def _file(self, name):
        safe = os.path.normpath(name).lstrip("/")
        fp = os.path.join(UI_DIR, safe)
        if not fp.startswith(UI_DIR) or not os.path.isfile(fp):
            return self._json(404, {"ok": False, "error": "not-found"})
        ctype = "text/html" if fp.endswith(".html") else \
                "application/javascript" if fp.endswith(".js") else \
                "text/css" if fp.endswith(".css") else "application/octet-stream"
        with open(fp, "rb") as f:
            self._send(200, f.read(), ctype)


def main():
    if not TOKEN:
        sys.exit("BROWSERD_TOKEN is required (fail-closed: refusing to start without it)")
    debug_port = int(os.environ.get("BROWSERD_DEBUG_PORT", "9222"))
    port = int(os.environ.get("BROWSERD_PORT", "8901"))
    profile = os.environ.get("BROWSERD_PROFILE", os.path.join(os.getcwd(), "profile"))
    chrome_bin = os.environ.get("CHROME_BIN", "chromium")

    state = ensure_chromium(debug_port, profile, chrome_bin)
    global DRIVER
    DRIVER = Driver(debug_port)
    print(f"browserd {VERSION}: chromium {state}, listening on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
