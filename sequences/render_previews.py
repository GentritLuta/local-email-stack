"""render_previews.py — generate a docs/preview-sequence.html that shows
every step of a niche's sequence (HTML inbox view) so you can review them
before any go out.

Run:
    py sequences/render_previews.py real_estate_us
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from email_render import render_html  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def render_niche_previews(niche_slug: str) -> Path:
    niche = yaml.safe_load((REPO_ROOT / "niches" / f"{niche_slug}.yaml").read_text(encoding="utf-8"))
    profile_slug = niche.get("profile_slug")
    profile = json.loads((REPO_ROOT / "profiles" / f"{profile_slug}.json").read_text(encoding="utf-8"))
    persona = next(p for p in profile["personas"] if p["slug"] == niche["sequence"]["forced_persona"])
    brand = profile.get("brand")
    variants = json.loads(
        (REPO_ROOT / niche["sequence"]["variants_file"]).read_text(encoding="utf-8")
    )["variants"]

    # Sample prospect for merge fields
    sample = {"first_name": "Josh", "last_name": "Dilmaghani",
              "city": "Indianapolis", "company": "White Stag Realty"}
    sample_token = "preview-token-00000000-0000-0000-0000-000000000000"

    def merge(s: str) -> str:
        return (s.replace("{first_name}", sample["first_name"])
                 .replace("{last_name}", sample["last_name"])
                 .replace("{city}", sample["city"])
                 .replace("{company}", sample["company"]))

    cards = []
    for v in variants:
        subject = merge(v["subject"])
        body    = merge(v["body"])
        html    = render_html(body=body, persona=persona,
                              unsubscribe_token=sample_token, brand=brand)
        cards.append(f"""
        <section class="card">
          <header>
            <span class="step">Step {v['n']}</span>
            <span class="delay">{'send immediately' if v['n']==1 else f'+{v["delay_days"]} days after step {v["n"]-1}'}</span>
            <span class="angle">{v.get('angle','')}</span>
          </header>
          <div class="subject"><b>Subject:</b> {subject}</div>
          <details><summary>Plain copy</summary><pre>{body}</pre></details>
          <iframe srcdoc='{html.replace("'", "&apos;")}' loading="lazy"></iframe>
        </section>""")

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Preview — {niche['name']}</title>
<style>
  body {{ margin:0; padding:32px 16px; background:#0a0a0a; color:#f5f5f5;
          font-family:'Inter',ui-sans-serif,system-ui; }}
  h1 {{ font-size: 22px; max-width:880px; margin:0 auto 8px; color:#E6C259; }}
  .lede {{ max-width:880px; margin:0 auto 32px; color:#9ca3af; font-size:14px; }}
  .card {{ max-width:880px; margin:0 auto 40px; background:#1e1e1e; border-radius:8px;
           padding:20px; border:1px solid #2a2a2a; }}
  header {{ display:flex; gap:14px; align-items:center; margin-bottom:10px; flex-wrap:wrap; }}
  .step {{ background:#E6C259; color:#0a0a0a; padding:2px 10px; border-radius:4px; font-weight:600; font-size:13px; }}
  .delay {{ font-size:12px; color:#9ca3af; }}
  .angle {{ font-size:11px; color:#666; font-style:italic; margin-left:auto; }}
  .subject {{ font-size:14px; color:#ebebeb; margin-bottom:14px; }}
  details {{ font-size:12px; color:#aaa; margin-bottom:14px; }}
  summary {{ cursor:pointer; }}
  pre {{ white-space: pre-wrap; background:#0a0a0a; padding:12px; border-radius:6px; font-size:12px; }}
  iframe {{ width:100%; height:560px; border:1px solid #2a2a2a; border-radius:6px; background:#fafafa; }}
</style></head>
<body>
  <h1>{niche['name']} — 7-step sequence preview</h1>
  <div class="lede">Each card shows the SUBJECT, the PLAIN copy, and the rendered HTML
  exactly as it lands in a recipient's inbox. The HTML below uses the same
  template + brand that goes out via Resend.</div>
  {''.join(cards)}
</body></html>"""

    out = REPO_ROOT / "docs" / f"preview-{niche_slug}.html"
    out.write_text(page, encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("niche_slug")
    args = ap.parse_args()
    out = render_niche_previews(args.niche_slug)
    print(f"wrote: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
