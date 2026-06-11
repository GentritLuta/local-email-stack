"""Local stand-in for the Cloudflare Worker — same routes, same behavior.
Lets us prove the open/click pipeline end-to-end without waiting for the
worker to be deployed.

Routes:
  GET /open/{token}.gif    -> PATCH send_log.opened_at + return 1x1 GIF
  GET /click/{token}?u=URL -> PATCH send_log.clicked_at + 302 redirect
  GET /                    -> health check
"""
from __future__ import annotations
import base64, datetime as dt, json, re, sys, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
env = {}
for line in (REPO / "sequences" / "supabase.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"]; KEY = env["SUPABASE_ANON_KEY"]
H_W = {"apikey": KEY, "Authorization": f"Bearer {KEY}",
       "Content-Type": "application/json", "Prefer": "return=minimal"}

PIXEL = base64.b64decode("R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==")


def patch_send_log_by_token(token: str, patch: dict) -> bool:
    token = re.sub(r'[^a-f0-9]', '', token, flags=re.I)
    if not token or len(token) < 12: return False
    url = f"{URL}/rest/v1/send_log?message_id=like.*{token}*"
    req = urllib.request.Request(
        url, method="PATCH", data=json.dumps(patch).encode(), headers=H_W)
    try:
        urllib.request.urlopen(req, timeout=10).read()
        return True
    except Exception as e:
        print(f"  ! patch failed: {e}")
        return False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  [tracker] {self.address_string()} - {fmt % args}")

    def do_GET(self):
        parts = self.path.lstrip("/").split("?", 1)
        path = parts[0]
        query = urllib.parse.parse_qs(parts[1]) if len(parts) > 1 else {}
        bits = path.split("/")
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        if bits[0] == "open" and len(bits) > 1:
            token = bits[1].rstrip(".gif")
            ok = patch_send_log_by_token(token, {"opened_at": now})
            print(f"  [tracker] OPEN token={token[:12]} patched={ok}")
            self.send_response(200)
            self.send_header("Content-Type", "image/gif")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(PIXEL)
            return
        if bits[0] == "click" and len(bits) > 1:
            token = bits[1]
            target = (query.get("u") or [""])[0]
            ok = patch_send_log_by_token(token, {"clicked_at": now})
            print(f"  [tracker] CLICK token={token[:12]} patched={ok} -> {target[:60]}")
            if target:
                self.send_response(302)
                self.send_header("Location", target)
                self.end_headers()
                return
            self.send_response(400); self.end_headers()
            return
        if path == "":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"aureon track ok (local)\n")
            return
        self.send_response(404); self.end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"local tracker listening on http://127.0.0.1:{port}")
    srv.serve_forever()
