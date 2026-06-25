# -*- coding: utf-8 -*-
"""generate-client-magnet.py — auto-design + produce a per-client lead magnet.

At kickoff (or on demand) this analyses a client's business and produces a REAL,
high-value lead magnet: a deliverable the prospect would normally pay a consultant
for, whose natural monthly continuation is exactly the recurring service the client
sells. It writes the spec into lead-magnets/magnet-specs.json and renders the
branded PDF. Because the catalog is the single source of truth, the keyword then
auto-registers for both reply-detection (reply-autodraft) and delivery
(fulfill-magnets) with no further wiring.

The design brief enforces the operator's rules: the magnet must (1) deliver real,
specific value worth paying for, (2) set up a recurring monthly need that maps to
the client's paid service, (3) lead naturally to the client's offer, and (4) stand
alone as a readable document. It reuses the SAME reply keyword the client's cold
email already asks for, so copy and magnet stay aligned.

Usage:
    py scripts/generate-client-magnet.py --profile diraya --preview   # non-destructive sample
    py scripts/generate-client-magnet.py --profile <new-slug>          # write live (new client)
    py scripts/generate-client-magnet.py --profile diraya --force      # overwrite existing
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys, tempfile, shutil
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPECS = REPO / "lead-magnets" / "magnet-specs.json"
MAGDIR = REPO / "lead-magnets"
_CLAUDE_EXE = r"D:\npm-global\node_modules\@anthropic-ai\claude-code\bin\claude.exe"
CLAUDE_CMD = os.environ.get("CLAUDE_CLI") or (_CLAUDE_EXE if os.path.exists(_CLAUDE_EXE) else r"D:\npm-global\claude.cmd")
SQL_URL = "https://api.supabase.com/v1/projects/ccmqkljsjiuavpydbkva/database/query"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _env(path: Path) -> dict:
    e = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and "=" in ln and not ln.startswith("#"):
                k, v = ln.split("=", 1); e[k.strip()] = v.strip().strip('"').strip("'")
    return e


_H = {"Authorization": f"Bearer {_env(REPO/'sequences'/'supabase.env').get('SUPABASE_ACCESS_TOKEN','')}",
      "Content-Type": "application/json", "User-Agent": "Mozilla/5.0 Chrome/123"}


def _sql(q: str) -> list:
    req = urllib.request.Request(SQL_URL, data=json.dumps({"query": q}).encode(), method="POST", headers=_H)
    return json.loads(urllib.request.urlopen(req, timeout=40).read())


def load_profile(slug: str) -> dict:
    f = REPO / "profiles" / f"{slug}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    rows = _sql(f"SELECT config FROM profiles WHERE slug='{slug}'")
    return rows[0]["config"] if rows else {}


def gather_context(slug: str, cfg: dict) -> dict:
    company = cfg.get("company") or {}
    brand = cfg.get("brand") or {}
    name = company.get("name") or company.get("legal_name") or slug
    offer = brand.get("offer_brief") or brand.get("tagline") or company.get("target_market") or ""
    if isinstance(offer, list):
        offer = " ".join(str(x) for x in offer)
    icp = company.get("target_market") or ""
    p0 = (cfg.get("personas") or [{}])[0]
    from_name = p0.get("from_name") or name
    from_addr = p0.get("from_addr") or f"hello@{company.get('site') or slug}"
    colors = brand.get("colors") or {}
    accent = (colors.get("primary") if isinstance(colors, dict) else None) or brand.get("accent_hex") or "#2563EB"
    copy = ""
    try:
        rows = _sql(f"SELECT subject, body FROM variants WHERE profile_slug='{slug}' AND n=1")
        if rows:
            copy = (rows[0].get("subject") or "") + "\n" + (rows[0].get("body") or "")
    except Exception:
        pass
    return dict(name=name, offer=offer, icp=icp, from_name=from_name,
                from_addr=from_addr, accent=accent, copy=copy)


FORMULA_FILE = REPO / "lead-magnets" / "hormozi-lead-magnet-formula.md"

_OUT_SCHEMA = (
    "Output ONLY a JSON object, no prose:\n"
    '{"language":"en"|"de","magnet_keyword":"WORD","deliverable_title":"...","one_line_promise":"...",'
    '"recurring_angle":"one sentence naming the monthly continuation the client sells",'
    '"email_subject":"...","cover_email":"... with {greeting} and {company} placeholders, signed by the sender ...",'
    '"sections":[{"heading":"...","body":"real multi-paragraph content"}]}'
)


def _load_formula() -> str:
    return FORMULA_FILE.read_text(encoding="utf-8") if FORMULA_FILE.exists() else ""


def _design_system(formula: str) -> str:
    return (
        "You design lead magnets that score high on the Hormozi Lead Magnet Formula below. Follow it "
        "strictly: solve ONE narrow problem COMPLETELY, maximise the Value Equation, build a clear bridge "
        "to the client's recurring paid offer, and name it with the MAGIC structure. The content must be "
        "real and specific (numbers, named tools, scripts, exact steps, thresholds), good enough that the "
        "prospect would have paid for it, and consumable as a 5 to 7 section PDF. Write in the language of "
        "the client's business. KEYWORD RULE: reuse the EXACT one-word reply keyword the client's cold email "
        "already asks prospects to reply with, IF it is a distinctive trigger; otherwise pick one clear "
        "UPPERCASE keyword that a prospect would only ever type to claim THIS resource. The keyword must be "
        "DISTINCTIVE: never a common word from the client's own industry or any word likely to appear by chance "
        "in a normal reply (for a seller-lead business do NOT use SELLERS or LEADS; for an audit business avoid "
        "AUDIT alone; prefer a vivid, specific trigger tied to the deliverable, e.g. the named kit, blueprint, "
        "or list). No em-dashes. The cover_email is the short note sent WITH the PDF; sign it as the named sender.\n\n"
        "=== THE FORMULA ===\n" + formula + "\n=== END FORMULA ===\n\n" + _OUT_SCHEMA
    )


def _score_system(formula: str) -> str:
    return (
        "You are a strict, honest grader. Grade the lead magnet against the Section 7 rubric of the Hormozi "
        "formula below: score each criterion 0 to 10, apply the weights, compute the weighted total out of 10, "
        "and apply the pass bar including the hard gates on narrow-and-complete and bridge-to-offer. Do not be "
        "generous.\n\n=== THE FORMULA ===\n" + formula + "\n=== END FORMULA ===\n\n"
        'Output ONLY JSON: {"weighted_total": number, "gates_ok": true|false, '
        '"weakest": "the lowest-scoring criterion and a one-line fix", "verdict": "ship"|"revise"}'
    )


def design(ctx: dict, formula: str, feedback: str = "") -> dict:
    prompt = (
        f"CLIENT: {ctx['name']}\n\n"
        f"WHAT THEY SELL / THEIR OFFER:\n{ctx['offer']}\n\n"
        f"THEIR IDEAL CUSTOMER (the prospect who will receive this magnet):\n{ctx['icp']}\n\n"
        f"MAGNET IS SIGNED BY: {ctx['from_name']}\n\n"
        f"THE CLIENT'S EXISTING COLD EMAIL (reuse the SAME reply keyword it already asks for):\n"
        f"{ctx['copy'][:1600]}\n"
    )
    if feedback:
        prompt += ("\nA PREVIOUS DRAFT SCORED BELOW THE SHIP BAR. In this version, fix this specifically "
                   "while keeping everything else at least as strong:\n" + feedback + "\n")
    def nd(s):  # scrub em-dashes to honour the house style
        return s.replace(" — ", ", ").replace("—", ", ").replace(" – ", ", ").replace("–", ", ")
    sysp = _design_system(formula)
    # The model occasionally emits malformed JSON on large outputs. Retry a few
    # times rather than failing the (kickoff) step on one bad roll.
    for attempt in range(2):
        work = tempfile.mkdtemp(prefix="les_magnet_")
        try:
            proc = subprocess.run(
                [CLAUDE_CMD, "-p", "--system-prompt", sysp,
                 "--disallowedTools", "Bash,Read,Glob,Grep,Edit,Write,WebFetch,WebSearch",
                 "--setting-sources", "user"],
                input=prompt, capture_output=True, text=True, timeout=420,
                encoding="utf-8", errors="replace", cwd=work,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            out = (proc.stdout or "").strip()
            m = re.search(r"\{[\s\S]*\}", out)
            if not m:
                print(f"  ~ design attempt {attempt+1}: no JSON in output, retrying")
                continue
            try:
                d = json.loads(m.group(0))
            except json.JSONDecodeError as je:
                print(f"  ~ design attempt {attempt+1}: malformed JSON ({je}), retrying")
                continue
            for f in ("deliverable_title", "one_line_promise", "cover_email", "email_subject", "recurring_angle"):
                d[f] = nd(d.get(f, ""))
            for s in d.get("sections", []):
                s["heading"] = nd(s.get("heading", "")); s["body"] = nd(s.get("body", ""))
            return d
        except Exception as e:
            print(f"  ~ design attempt {attempt+1} error: {e}")
        finally:
            shutil.rmtree(work, ignore_errors=True)
    print("  ! design failed after retries")
    return None


def _score(name: str, d: dict, formula: str) -> dict:
    """Grade a designed magnet against the Hormozi rubric (Section 7). Returns the verdict dict or None."""
    body = "\n\n".join(f"{s.get('heading','')}\n{s.get('body','')}" for s in d.get("sections", []))
    prompt = (f"LEAD MAGNET for {name}:\nTITLE: {d.get('deliverable_title','')}\n"
              f"PROMISE: {d.get('one_line_promise','')}\nRECURRING ANGLE: {d.get('recurring_angle','')}\n\n"
              f"SECTIONS:\n{body}")
    work = tempfile.mkdtemp(prefix="les_score_")
    try:
        proc = subprocess.run(
            [CLAUDE_CMD, "-p", "--system-prompt", _score_system(formula),
             "--disallowedTools", "Bash,Read,Glob,Grep,Edit,Write,WebFetch,WebSearch",
             "--setting-sources", "user"],
            input=prompt, capture_output=True, text=True, timeout=200,
            encoding="utf-8", errors="replace", cwd=work,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        m = re.search(r"\{[\s\S]*\}", proc.stdout or "")
        return json.loads(m.group(0)) if m else None
    except Exception as e:
        print(f"  ~ score error: {e}")
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def best_magnet(ctx: dict, formula: str, tries: int = 4) -> tuple:
    """Design and grade up to `tries` times, feeding each round's weakest point into the next
    draft so the magnet climbs toward the ship bar. Keep the highest-scoring version and stop
    early once one clears the bar. Returns (design, score_dict)."""
    best = None
    feedback = ""
    for i in range(tries):
        d = design(ctx, formula, feedback)
        if not d or not all(d.get(k) for k in
                            ("magnet_keyword", "deliverable_title", "one_line_promise", "cover_email", "sections")):
            continue
        sc = _score(ctx["name"], d, formula) or {}
        total = float(sc.get("weighted_total") or 0)
        print(f"  attempt {i+1}: Hormozi score {total:.1f}/10  verdict={sc.get('verdict','?')}  gates_ok={sc.get('gates_ok')}")
        if best is None or total > float(best[1].get("weighted_total") or 0):
            best = (d, sc)
        if sc.get("verdict") == "ship" and sc.get("gates_ok"):
            break
        feedback = sc.get("weakest") or ""
    return best if best else (None, None)


def assemble(slug: str, ctx: dict, d: dict) -> dict:
    kw = d.get("magnet_keyword") or "GUIDE"
    return {
        "client_slug": slug,
        "language": d.get("language", "en"),
        "magnet_keywords": [kw],
        "deliverable_title": d["deliverable_title"],
        "one_line_promise": d["one_line_promise"],
        "cover_email": d["cover_email"],
        "accent_hex": ctx["accent"],
        "sections": d["sections"],
        "email_subject": d.get("email_subject", "Your free resource"),
        "from_name": ctx["from_name"],
        "from_addr": ctx["from_addr"],
        "_recurring_angle": d.get("recurring_angle", ""),
        "_auto_generated": True,
    }


def upsert_spec(spec: dict, force: bool) -> tuple:
    specs = json.loads(SPECS.read_text(encoding="utf-8")) if SPECS.exists() else []
    idx = next((i for i, s in enumerate(specs) if s.get("client_slug") == spec["client_slug"]), None)
    if idx is not None and not force:
        return False, "exists"
    if idx is not None:
        specs[idx] = spec
    else:
        specs.append(spec)
    SPECS.write_text(json.dumps(specs, ensure_ascii=False, indent=2), encoding="utf-8")
    return True, ("replaced" if idx is not None else "added")


def render(slug: str) -> tuple:
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "render-magnet.py"), slug],
                       capture_output=True, text=True, timeout=180, encoding="utf-8", errors="replace")
    return r.returncode == 0, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--force", action="store_true", help="overwrite an existing magnet for this client")
    ap.add_argument("--preview", action="store_true", help="design + render a sample without touching the live catalog")
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--tries", type=int, default=4, help="design+grade rounds (lower = faster, higher = better score)")
    a = ap.parse_args()
    slug = a.profile

    cfg = load_profile(slug)
    if not cfg:
        sys.exit(f"no profile config for {slug}")
    ctx = gather_context(slug, cfg)
    formula = _load_formula()
    if not formula:
        print("  ! Hormozi formula missing; run scripts/research-hormozi-magnet.py first.")
        return 1
    print(f"designing magnet for {slug} ({ctx['name']}) ...")
    d, sc = best_magnet(ctx, formula)
    if not d:
        sys.exit("design failed")
    sc = sc or {}
    spec = assemble(slug, ctx, d)
    spec["_hormozi_score"] = {"weighted_total": sc.get("weighted_total"), "verdict": sc.get("verdict"),
                              "gates_ok": sc.get("gates_ok"), "weakest": sc.get("weakest")}
    print(f"  keyword:   {spec['magnet_keywords']}")
    print(f"  title:     {spec['deliverable_title']}")
    print(f"  recurring: {d.get('recurring_angle','')}")
    print(f"  sections:  {len(spec['sections'])}  language: {spec['language']}")
    print(f"  Hormozi:   {sc.get('weighted_total')}/10  verdict={sc.get('verdict')}  gates_ok={sc.get('gates_ok')}")
    if sc.get('weakest'):
        print(f"             weakest: {sc.get('weakest')}")

    if a.preview:
        orig = SPECS.read_text(encoding="utf-8") if SPECS.exists() else None
        before = {p.name: p.read_bytes() for p in MAGDIR.glob(f"{slug}--*.pdf")}
        try:
            upsert_spec(spec, force=True)
            ok, log = render(slug) if not a.no_render else (True, "")
            now = sorted(MAGDIR.glob(f"{slug}--*.pdf"), key=lambda p: p.stat().st_mtime)
            preview_pdf = None
            if ok and now:
                preview_pdf = MAGDIR / f"_preview-{now[-1].name}"
                shutil.copy(now[-1], preview_pdf)
        finally:
            if orig is not None:
                SPECS.write_text(orig, encoding="utf-8")             # restore catalog
            for p in MAGDIR.glob(f"{slug}--*.pdf"):                   # remove preview-render artifacts
                if p.name not in before:
                    p.unlink()
            for name, data in before.items():                        # restore any clobbered live PDF
                (MAGDIR / name).write_bytes(data)
        (MAGDIR / f"_preview-{slug}.spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  PREVIEW spec: lead-magnets/_preview-{slug}.spec.json")
        if a.preview and not a.no_render and preview_pdf:
            print(f"  PREVIEW pdf:  {preview_pdf.relative_to(REPO)}")
        print("  (live catalog NOT modified; rerun with --force to make it live)")
        return 0

    ok, msg = upsert_spec(spec, a.force)
    if not ok:
        sys.exit(f"{slug} already has a magnet (use --force to overwrite, or --preview to sample)")
    print(f"  spec {msg} in magnet-specs.json")
    if not a.no_render:
        ok, log = render(slug)
        print("  rendered PDF" if ok else f"  render FAILED: {log[-400:]}")
    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
