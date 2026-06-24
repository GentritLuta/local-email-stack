# -*- coding: utf-8 -*-
"""Diagnose under-sending: per active profile, compare theoretical daily cap vs
actual sends today vs pool/enrollment. Read-only."""
import json, sys, datetime as dt, urllib.request, urllib.parse, glob
from pathlib import Path
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = Path(__file__).resolve().parent.parent

def _load_env(p):
    out = {}
    if Path(p).exists():
        for ln in Path(p).read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1); out[k.strip()] = v.strip()
    return out
SENV = _load_env(REPO / "sequences" / "supabase.env")
U = SENV["SUPABASE_URL"].rstrip("/") + "/rest/v1"
K = SENV.get("SUPABASE_SERVICE_KEY") or SENV.get("SUPABASE_ANON_KEY")
H = {"apikey": K, "Authorization": "Bearer " + K}

def count(table, q):
    req = urllib.request.Request(f"{U}/{table}?{q}&select=id&limit=1",
        headers={**H, "Prefer": "count=exact", "Range-Unit": "items", "Range": "0-0"})
    with urllib.request.urlopen(req, timeout=40) as r:
        cr = r.headers.get("Content-Range", "*/0")
        return int(cr.split("/")[-1]) if "/" in cr else 0

def rows(table, q):
    req = urllib.request.Request(f"{U}/{table}?{q}", headers=H)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def quota_today(cfg):
    ramp = cfg.get("send_ramp") or {}
    curve = ramp.get("curve") or []
    if not curve: return cfg.get("rotation", {}).get("max_sends_per_persona_per_day", 30), "static"
    start = ramp.get("started_at")
    if not start: return int(curve[0].get("per_persona", 1)), "not-started"
    try: days = max(1, (dt.date.today() - dt.date.fromisoformat(start)).days + 1)
    except Exception: return int(curve[0].get("per_persona", 1)), "bad-start"
    sc = sorted(curve, key=lambda r: int(r.get("from_day", 0)))
    qd = int(sc[0].get("per_persona", 1))
    for t in sc:
        if days >= int(t.get("from_day", 0)): qd = int(t.get("per_persona", qd))
    return qd, f"day{days}"

today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
print(f"{'profile':16}{'pers':>5}{'q/p':>5}{'cap':>6}{'sentTd':>7}{'pool':>6}{'enrl':>6}{'due':>6}  ramp")
print("-"*72)
for p in sorted(glob.glob(str(REPO/"profiles"/"*.json"))):
    if p.endswith(".private.json"): continue
    try: cfg = json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: continue
    if not cfg.get("active"): continue
    slug = cfg["slug"]
    personas = cfg.get("personas", [])
    doms = [d["domain"] for d in (cfg.get("relay", {}).get("from_domains") or [])]
    root = ".".join(doms[0].split(".")[1:]) if doms else slug
    q, label = quota_today(cfg)
    cap = len(personas) * q
    # sends today: send_log from_addr LIKE %root%, sent_at >= today
    sent = count("send_log", f"from_addr=like.*{urllib.parse.quote(root)}*&sent_at=gte.{today}")
    # pool: verified, not unsubscribed
    pool = count("prospects", f"profile_slug=eq.{slug}&verified=eq.true&unsubscribed=eq.false")
    # enrolled + due via sequences
    seqs = rows("sequences", f"profile_slug=eq.{slug}&select=id")
    sids = [s["id"] for s in seqs]
    enrolled = due = 0
    if sids:
        inlist = "(" + ",".join(sids) + ")"
        enrolled = count("runs", f"sequence_id=in.{inlist}")
        due = count("runs", f"sequence_id=in.{inlist}&status=in.(queued,running)&next_send_at=lte.{now}")
    print(f"{slug:16}{len(personas):>5}{q:>5}{cap:>6}{sent:>7}{pool:>6}{enrolled:>6}{due:>6}  {label}")
