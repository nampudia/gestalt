#!/usr/bin/env python3
"""Run the Screentest demo locally:  python3 serve.py
Opens http://localhost:8000 in your browser. Ctrl+C to stop.

For Claude-written Audience notes, set your API key first (from platform.claude.com):
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 serve.py
The key stays on your computer: the page asks this server, and only this server talks to Claude.
(Plain `python3 -m http.server` can't skip around inside videos, which breaks the film strip.)"""
import http.server, json, os, re, socketserver, threading, urllib.error, urllib.request, webbrowser

PORT = int(os.environ.get("PORT", 8000))
MODEL = os.environ.get("SCREENTEST_MODEL", "claude-sonnet-5-5")
os.chdir(os.path.dirname(os.path.abspath(__file__)))

NOTES_PROMPT = """You are the head of audience research for a film test-screening service. A studio just ran a screening.
Below is the data: scene list (auto-detected, named from the picture and dialogue), per-scene engagement (0-100) and the peak share of
the room showing each reaction, key moments, stretches where the audience drifted, walkouts, survey answers and audience-group breakdowns.

Write the 5 to 7 most useful notes for the director, editor and marketing team, most important first.
Rules:
- Every note must be specific and actionable, and refer to scenes by name with timestamps.
- Back every note with the numbers from the data (counts like "9 of 14", engagement vs average). Never invent numbers.
- These are audience notes, not orders. Suggest, don't command. Never claim certainty about why something happened.
- If a group or the whole audience is small (under 30 people, or a group under 10), say the note is directional and lower its confidence.
- Cover editing first (trims, clarity, pacing, joke timing, the ending), then marketing (who to target, trailer and clip moments), then release.
Reply with ONLY a JSON array, no prose, each item:
{"area": "Edit" | "Marketing" | "Release" | "Next screening", "priority": 1 | 2 | 3, "title": "short headline", "body": "2-3 sentences", "evidence": [{"t": seconds, "label": "short label"}], "confidence": "low" | "medium" | "high"}"""


def ask_claude(payload):
    key = os.environ.get("ANTHROPIC_API_KEY")
    body = json.dumps({"model": MODEL, "max_tokens": 2500, "messages": [{"role": "user", "content": NOTES_PROMPT + "\n\nSCREENING DATA:\n" + json.dumps(payload)}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.load(r)
    text = "".join(b.get("text", "") for b in data.get("content", []))
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        raise ValueError("Claude didn't return notes in the expected format")
    return json.loads(m.group(0))


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    def _json(self, code, obj):
        out = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):
        if self.path.startswith("/api/status"):
            return self._json(200, {"claude": bool(os.environ.get("ANTHROPIC_API_KEY")), "model": MODEL})
        return super().do_GET()

    def do_POST(self):
        if not self.path.startswith("/api/notes"):
            return self._json(404, {"error": "not found"})
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return self._json(400, {"error": "Set ANTHROPIC_API_KEY and restart serve.py"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(min(n, 2_000_000)))
            return self._json(200, {"notes": ask_claude(payload), "model": MODEL})
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="ignore")[:300]
            return self._json(502, {"error": f"Claude API {e.code}: {detail}"})
        except Exception as e:
            return self._json(500, {"error": str(e)[:300]})

    def send_head(self):
        rng = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not rng or not os.path.isfile(path):
            return super().send_head()
        m = re.match(r"bytes=(\d*)-(\d*)", rng)
        size = os.path.getsize(path)
        start = int(m.group(1)) if m and m.group(1) else 0
        end = int(m.group(2)) if m and m.group(2) else size - 1
        if m and not m.group(1) and m.group(2):          # suffix range: last N bytes
            start, end = max(0, size - int(m.group(2))), size - 1
        if start >= size:
            self.send_error(416)
            return None
        end = min(end, size - 1)
        f = open(path, "rb")
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        self._remaining = end - start + 1
        return f

    def copyfile(self, src, dst):
        left = getattr(self, "_remaining", None)
        if left is None:
            return super().copyfile(src, dst)
        try:
            while left > 0:
                chunk = src.read(min(64 * 1024, left))
                if not chunk:
                    break
                dst.write(chunk)
                left -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        self._remaining = None

    def end_headers(self):
        if "Accept-Ranges" not in str(self._headers_buffer):
            self.send_header("Accept-Ranges", "bytes")
        super().end_headers()

    def log_message(self, *a):
        pass


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    with Server(("", PORT), RangeHandler) as httpd:
        url = f"http://localhost:{PORT}/"
        print(f"Screentest demo running at {url}  (Ctrl+C to stop)")
        print(f"Claude notes: {'on (' + MODEL + ')' if os.environ.get('ANTHROPIC_API_KEY') else 'off, set ANTHROPIC_API_KEY to turn on'}")
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")
