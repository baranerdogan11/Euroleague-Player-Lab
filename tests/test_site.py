#!/usr/bin/env python3
"""Site smoke test: the built page is served to headless Chrome and must open, route and draw without an error.

build.py runs this at the end of every build (set PL_NO_SMOKE=1 to skip), so a page that throws, a club file that
no longer parses or a service worker that cannot compile fails the pipeline before anything is committed.

Checks, in order:
  1. no git conflict markers in the built files (index.html, sw.js, the club JSON, the template and the dictionary)
  2. sw.js compiles (Chrome's own parser, through the DevTools protocol)
  3. desktop (1280 px): the opening page lists every club; the Open button lands on a player page with a name, a drawn
     shot chart and a game log; the standings, leaders, compare, lineups and games pages each show up on their hash; the
     opening page's Last night strip opens a game page with both box scores, whose totals match the final score, a shot
     chart and the fives, and a player in the box opens his page on that game
  4. phone (390 px): the same entry and the same game page, and the page never scrolls sideways
  5. throughout: no uncaught exception, no console.error, no failed request for a page, script or JSON file

Chrome is found through $CHROME, then the usual names on PATH, then the macOS bundle. A Chrome that does not start is
retried once. On a laptop, no Chrome (or one that will not start) skips the test with a notice; in CI ($GITHUB_ACTIONS
or $CI set) it is a failure, so a build is never published untested (PL_SMOKE_REQUIRED=1 forces the failure anywhere,
PL_SMOKE_REQUIRED=0 allows the skip in CI). No third-party package: the DevTools connection is a small WebSocket
client over the standard library.
"""
import base64
import glob
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEASON = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("SEASON", "E2026")
CHROME_NAMES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium"]


def required():
    """A missing or dead Chrome fails the test in CI and when PL_SMOKE_REQUIRED=1, and skips it elsewhere."""
    v = os.environ.get("PL_SMOKE_REQUIRED")
    if v is not None and v != "":
        return v != "0"
    return bool(os.environ.get("GITHUB_ACTIONS") or os.environ.get("CI"))


def find_chrome():
    for c in [os.environ.get("CHROME")] + CHROME_NAMES:
        if not c:
            continue
        p = shutil.which(c) or (c if os.path.isfile(c) and os.access(c, os.X_OK) else None)
        if p:
            return p
    return None


# ---- a minimal WebSocket client (text frames, client-side masking, ping answered), enough for the DevTools protocol
class WS:
    def __init__(self, url, timeout=30):
        m = re.match(r"ws://([^:/]+):(\d+)(/.*)", url)
        host, port, path = m.group(1), int(m.group(2)), m.group(3)
        self.s = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.s.recv(4096)
            if not chunk:
                raise RuntimeError("websocket handshake: connection closed")
            buf += chunk
        if b" 101 " not in buf.split(b"\r\n", 1)[0]:
            raise RuntimeError("websocket handshake refused: " + buf.split(b"\r\n", 1)[0].decode(errors="replace"))
        self.rest = buf.split(b"\r\n\r\n", 1)[1]

    def _read(self, n):
        out = self.rest[:n]
        self.rest = self.rest[n:]
        while len(out) < n:
            chunk = self.s.recv(min(65536, n - len(out)))
            if not chunk:
                raise RuntimeError("websocket: connection closed")
            out += chunk
        return out

    def send(self, text):
        data = text.encode()
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else bytes([0x80 | 127]) + struct.pack(">Q", n))
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        while True:
            b0, b1 = self._read(2)
            op, n = b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if b1 & 0x80 else None
            payload = self._read(n)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if op == 1:
                return payload.decode()
            if op == 8:
                raise RuntimeError("websocket closed by Chrome")
            if op == 9:   # ping
                self.s.sendall(bytes([0x8A, 0x80]) + b"\0\0\0\0")


class CDP:
    def __init__(self, url, port):
        self.ws = WS(url)
        self.n = 0
        self.port = port     # the local server, so a failed request for the site itself counts
        self.errors = []     # (kind, text) collected from the page the whole session long

    def call(self, method, params=None):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            self.event(msg)

    def event(self, msg):
        m, p = msg.get("method"), msg.get("params", {})
        if m == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails", {})
            self.errors.append(("exception", (d.get("exception") or {}).get("description") or d.get("text") or "?"))
        elif m == "Runtime.consoleAPICalled" and p.get("type") == "error":
            self.errors.append(("console.error", " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))[:300]))
        elif m == "Log.entryAdded":
            e = p.get("entry", {})
            if e.get("level") == "error":
                url = e.get("url") or ""
                if e.get("source") != "network" or re.search(r"\.(json|js|html|css|woff2)(\?|$)", url) or url.rstrip("/").endswith((":%d" % self.port,)):
                    self.errors.append(("log", f"{e.get('text', '')} {url}".strip()[:300]))

    def eval(self, expr):
        r = self.call("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True})
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise RuntimeError("evaluate failed: " + ((d.get("exception") or {}).get("description") or d.get("text") or expr))
        return r.get("result", {}).get("value")

    def wait(self, expr, what, timeout=15):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if self.eval(expr):
                    return True
            except RuntimeError:
                pass
            time.sleep(0.15)
        raise AssertionError(f"timed out waiting for {what}")


def serve():
    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=ROOT, **k)

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    sys.stdout.reconfigure(line_buffering=True)   # CI logs show when each step happened
    fails = []
    # 1. conflict markers never reach the built site
    files = ["index.html", "sw.js", "template.html", "manifest.webmanifest", os.path.join("lang", "tr.json")] + sorted(glob.glob(os.path.join("teams", SEASON, "*.json"))) + sorted(glob.glob(os.path.join("teams", SEASON, "games", "*.json")))
    for f in files:
        p = os.path.join(ROOT, f)
        if not os.path.exists(p):
            continue
        s = open(p, encoding="utf-8", errors="replace").read()
        if re.search(r"^(<<<<<<< |>>>>>>> )", s, re.M):
            fails.append(f"{f}: git conflict markers")
        elif f.endswith((".json", ".webmanifest")):
            try:
                json.loads(s)
            except ValueError as e:
                fails.append(f"{f}: not JSON ({e})")
    print(f"files: {len(files)} checked, {len(fails)} problem(s)")
    if fails:
        for f in fails:
            print("FAIL", f)
        return 1

    chrome = find_chrome()
    if not chrome:
        if required():
            print("FAIL no Chrome found (set CHROME=/path/to/chrome; in CI this is a failure: PL_SMOKE_REQUIRED=0 allows the skip)")
            return 1
        print("SKIP no Chrome found: site smoke test skipped (set CHROME=/path/to/chrome)")
        return 0

    srv = serve()
    port = srv.server_address[1]
    base = f"http://127.0.0.1:{port}/"

    profiles = []

    def launch():
        """Start headless Chrome; return (process, DevTools URL or None, last stderr lines)."""
        profiles.append(tempfile.mkdtemp(prefix="pl-smoke-"))
        prof = profiles[-1]
        proc = subprocess.Popen([chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run", "--disable-extensions", "--hide-scrollbars",
                                 "--disable-features=TranslateUI", "--disable-dev-shm-usage", f"--user-data-dir={prof}", "--remote-debugging-port=0",
                                 "--window-size=1280,900", "about:blank"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        tail, t0 = [], time.time()
        while time.time() - t0 < 60:
            line = proc.stderr.readline()
            if not line and proc.poll() is not None:
                break
            tail = (tail + [line.rstrip()])[-6:]
            m = re.search(r"DevTools listening on (ws://[^\s]+)", line)
            if m:
                return proc, m.group(1), tail
        proc.kill()
        return proc, None, tail

    proc, dev, tail = launch()
    if not dev:
        print("Chrome did not start (" + ("exited" if proc.returncode is not None else "no DevTools endpoint within 60 s") + "), retrying once")
        for line in tail:
            print("   ", line)
        proc, dev, tail = launch()
    if not dev:
        for line in tail:
            print("   ", line)
        if required():
            print("FAIL Chrome did not start twice (in CI this is a failure: PL_SMOKE_REQUIRED=0 allows the skip)")
            return 1
        print("SKIP Chrome did not start twice: site smoke test skipped (a runner problem, not a page problem)")
        return 0
    try:
        threading.Thread(target=lambda: [None for _ in proc.stderr], daemon=True).start()   # drain Chrome's logging
        devport = int(re.match(r"ws://[^:]+:(\d+)", dev).group(1))
        targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{devport}/json/list", timeout=10).read())
        page = next(t for t in targets if t.get("type") == "page")
        cdp = CDP(page["webSocketDebuggerUrl"], port)
        for m in ("Runtime.enable", "Log.enable", "Page.enable"):
            cdp.call(m)

        # 2. the service worker compiles
        sw = open(os.path.join(ROOT, "sw.js"), encoding="utf-8").read()
        r = cdp.call("Runtime.compileScript", {"expression": sw, "sourceURL": "sw.js", "persistScript": False})
        if "exceptionDetails" in r:
            fails.append("sw.js does not compile: " + (r["exceptionDetails"].get("text") or "?"))
        print("sw.js: compiles" if "exceptionDetails" not in r else "sw.js: FAIL")

        def device(width, height, mobile):
            cdp.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": mobile})
            if mobile:
                cdp.call("Emulation.setUserAgentOverride", {"userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"})
            cdp.call("Emulation.setTouchEmulationEnabled", {"enabled": mobile})

        def open_home():
            cdp.call("Page.navigate", {"url": base + "?smoke=1"})
            cdp.wait("document.readyState === 'complete' && document.body.classList.contains('cv-on')", "the opening page")
            cdp.wait("document.querySelectorAll('#cv-clubs a').length === META.clubs.length && META.clubs.length >= 16", "every club card on the opening page")

        def enter_app():
            cdp.eval("sessionStorage.clear(); localStorage.removeItem('pl-last'); document.querySelector('#cv-go').click()")
            cdp.wait("!document.body.classList.contains('cv-on') && document.querySelector('#fail').hidden", "the first page after the opening page")
            # the Open button lands on a club page (first visit) or the last player (a return); either way a player page must be reachable
            cdp.wait("typeof state !== 'undefined' && state.team && CLUBS[state.team]", "a club loaded")
            cdp.eval("location.hash = '#' + state.team + '/' + team().players[0].pid")
            cdp.wait("document.querySelector('#nm') && document.querySelector('#nm').textContent.trim().length > 1 && document.querySelector('#court').childElementCount > 3"
                     " && document.querySelectorAll('#log tbody tr').length >= 1 && document.querySelector('#fail').hidden", "a player page with a name, a shot chart and a game log")

        # the game page from the opening page's Last night strip: the first card, then every tab; the box totals must equal
        # the score in the header, and a player in the box opens his page on that game
        GAME_UP = ("document.body.classList.contains('gm-on') && !document.querySelector('.wipe.on') && document.querySelector('#fail').hidden"
                   " && document.querySelectorAll('#game .gm-box tbody tr').length >= 16 && !!document.querySelector('#game .gm-tm')")
        def game_page(where):
            cdp.wait("!document.querySelector('#cv-last').hidden && document.querySelectorAll('#cv-games a.cv-game').length >= 1", f"the Last night strip on the opening page ({where})")
            cdp.eval("document.querySelector('#cv-games a.cv-game').click()")
            # the game opens on its Summary: four leader duels and the team comparison, then the box score one tab over
            cdp.wait("document.body.classList.contains('gm-on') && !document.querySelector('.wipe.on') && document.querySelector('#fail').hidden"
                     " && document.querySelectorAll('#game .gm-ldr-c').length === 4 && document.querySelectorAll('#game .gm-cmp .row').length >= 10 && !!document.querySelector('#game .gm-tm')", f"a game page's summary ({where})")
            # the win probability chart on the Summary, and it ends on the club that won
            cdp.wait("!!document.querySelector('#gm-wp svg path.ln')", f"a game page's win probability chart ({where})")
            bad = cdp.eval("""(() => { const em = [...document.querySelectorAll('#game .gm-tm em')].map(e => +e.textContent), w = document.querySelector('#gm-wp').closest('.gm-wp') && document.querySelector('#gm-wp path.ln').getAttribute('d').trim().split(/[ML]/).filter(Boolean).pop().split(' ').map(Number);
                return w && (w[1] === 0) !== (em[0] > em[1]) ? JSON.stringify({score: em, end: w}) : ''; })()""")
            if bad:
                fails.append(f"{where}: the win probability chart ends on the wrong club: {bad}")
            cdp.eval("document.querySelector('#game button[data-tab=box]').click()")
            cdp.wait(GAME_UP, f"a game page with both box scores ({where})")
            bad = cdp.eval("""(() => { const em = [...document.querySelectorAll('#game .gm-tm em')].map(e => +e.textContent), tot = [...document.querySelectorAll('#game .gm-box tr.tot td.pts')].map(e => +e.textContent);
                              return em.length === 2 && tot.length === 2 && em[0] === tot[0] && em[1] === tot[1] ? '' : `header ${em} against box totals ${tot}`; })()""")
            if bad:
                fails.append(f"{where}: the game page's box totals disagree with its score: {bad}")
            for tab, probe in (("shots", "document.querySelectorAll('#gm-court circle').length >= 20"), ("fives", "document.querySelectorAll('#game .gm-fives tbody tr').length >= 3 && !!document.querySelector('#game .ln-strip')")):
                cdp.eval(f"document.querySelector('#game button[data-tab={tab}]').click()")
                cdp.wait(probe, f"the game page's {tab} tab ({where})")
            wide = cdp.eval("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            if wide > 2:
                fails.append(f"{where}: the game page scrolls sideways by {wide}px")
            cdp.eval("document.querySelector('#game button[data-tab=box]').click()")
            cdp.wait(GAME_UP, f"the box score tab again ({where})")
            cdp.eval("document.querySelector('#game .gm-box td.nm a').click()")
            cdp.wait("!document.body.classList.contains('gm-on') && !document.querySelector('.wipe.on') && state.data && state.game !== 'all' && /\\/g\\d+$/.test(location.hash)"
                     " && document.querySelector('#court').childElementCount > 3", f"a player page opened on that game from the box score ({where})")
            cdp.eval("localStorage.removeItem('pl-last')")   # the opening page's Open button is tested from a fresh browser next
            print(f"{where}: game page drawn from the Last night strip ({cdp.eval('document.title')}), overflow {wide}px, player link lands on the game")

        # 3. desktop
        device(1280, 900, False)
        open_home()
        game_page("desktop")
        open_home()
        enter_app()
        print("desktop: opening page, club and player page drawn (%s)" % cdp.eval("document.title"))
        for h, cls, probe, what in (("standings", "st-on", "document.querySelectorAll('#standings .st-tab tbody tr').length >= META.clubs.length", "the standings table"),
                                   ("leaders", "ld-on", "document.querySelector('#leaders').getBoundingClientRect().height > 300", "the leaders page"),
                                   ("compare", "cmp-on", "document.querySelector('#cmp-panel').getBoundingClientRect().height > 200", "the compare page"),
                                   # every game played so far, one card each, as many as the standings count
                                   ("games", "gs-on", "document.querySelectorAll('#gs-list a.cv-game').length === META.games.length && META.games.length === META.standings.reduce((a, r) => a + r.gp, 0) / 2", "the games page"),
                                   ("lineups", "ln-on", "document.querySelector('#lineups').getBoundingClientRect().height > 300", "the lineups page")):
            cdp.eval(f"location.hash = '#{h}'")
            cdp.wait(f"document.body.classList.contains('{cls}') && !document.querySelector('.wipe.on') && document.querySelector('#fail').hidden && ({probe})", what)
            print(f"desktop: #{h} drawn")
        # the lineups by-game tab: one game of one club, every five with a floor-time strip
        BYGAME = "document.querySelectorAll('#ln-wrap .ln-tab tbody tr').length >= 5 && !!document.querySelector('#ln-wrap .ln-strip')"
        cdp.eval("document.querySelector('#ln-tabs button[data-v=game]').click()")
        cdp.wait(BYGAME, "the lineups by-game table")
        print("desktop: #lineups by game drawn (%d fives)" % cdp.eval("document.querySelectorAll('#ln-wrap .ln-tab tbody tr').length"))

        # 4. phone
        device(390, 844, True)
        open_home()
        game_page("phone")
        open_home()
        enter_app()
        wide = cdp.eval("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        if wide > 2:
            fails.append(f"phone: the player page scrolls sideways by {wide}px")
        cdp.eval("location.hash = '#standings'")
        cdp.wait("document.body.classList.contains('st-on') && !document.querySelector('.wipe.on')", "the standings page on a phone")
        print("phone: opening page, player page and standings drawn, overflow %dpx" % wide)
        cdp.eval("location.hash = '#lineups'")
        cdp.wait("document.body.classList.contains('ln-on') && !document.querySelector('.wipe.on') && document.querySelector('#fail').hidden && document.querySelector('#lineups').getBoundingClientRect().height > 300", "the lineups page on a phone")
        cdp.eval("document.querySelector('#ln-tabs button[data-v=game]').click()")
        cdp.wait(BYGAME, "the lineups by-game table on a phone")
        wide = cdp.eval("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        if wide > 2:
            fails.append(f"phone: the lineups by-game page scrolls sideways by {wide}px")
        print("phone: #lineups by game drawn (%d fives), overflow %dpx" % (cdp.eval("document.querySelectorAll('#ln-wrap .ln-tab tbody tr').length"), wide))
        time.sleep(0.5)
        cdp.call("Runtime.evaluate", {"expression": "1"})   # flushes queued events
    finally:
        proc.kill()
        proc.wait()
        for prof in profiles:
            shutil.rmtree(prof, ignore_errors=True)
        srv.shutdown()

    # 5. anything the page complained about
    for kind, text in cdp.errors:
        fails.append(f"{kind}: {text}")
    for f in fails:
        print("FAIL", f)
    print("site smoke test:", "PASS" if not fails else f"{len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
