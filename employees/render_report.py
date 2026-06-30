"""render_report.py — turn an employee report (markdown) into an official-looking
HTML document, the way it would appear to a tax official.

The employees return their work as markdown (headings, tables, bold, lists). This
wraps that in a clean Aureon Global Sh.P.K. letterhead with a fiscal-number header
and a "prepared, not submitted" stamp, and converts the markdown to real HTML. No
third-party markdown library is used (free, dependency-light).

    python render_report.py --latest bookkeeper           # render newest pending
    python render_report.py path/to/report.json [--desktop]
    python render_report.py path/to/report.json --pending  # search pending if bare name

Also importable: review.py calls write_official_html() when a report is approved.
"""
import argparse
import glob
import html as _html
import json
import re
import sys
from pathlib import Path

import _lib as L

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Official letterhead identity (matches the invoices / contracts).
SELLER = {
    "name": "Aureon Global L.L.C. (Sh.P.K.)",
    "addr": "Dushkaja 20, 71000 Kaçanik, Republic of Kosovo",
    "fiscal": "812368240",
    "email": "info@aureonglobal.de",
}


def _inline(text: str) -> str:
    text = _html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


def md_to_html(md: str) -> str:
    lines = md.split("\n")
    out, para = [], []
    list_open = [False]

    def flush_para():
        if para:
            out.append("<p>" + " ".join(_inline(x) for x in para) + "</p>")
            para.clear()

    def close_list():
        if list_open[0]:
            out.append("</ul>")
            list_open[0] = False

    i = 0
    while i < len(lines):
        s = lines[i].rstrip().strip()
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        is_table = (s.startswith("|") and "-" in nxt
                    and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", nxt))
        if is_table:
            flush_para(); close_list()
            header = [c.strip() for c in s.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            t = ["<table><thead><tr>"]
            t += [f"<th>{_inline(h)}</th>" for h in header]
            t.append("</tr></thead><tbody>")
            for r in rows:
                t.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>")
            t.append("</tbody></table>")
            out.append("".join(t))
            continue
        if not s:
            flush_para(); close_list()
        elif s.startswith("### "):
            flush_para(); close_list(); out.append(f"<h3>{_inline(s[4:])}</h3>")
        elif s.startswith("## "):
            flush_para(); close_list(); out.append(f"<h2>{_inline(s[3:])}</h2>")
        elif s.startswith("# "):
            flush_para(); close_list(); out.append(f"<h1>{_inline(s[2:])}</h1>")
        elif re.match(r"^(-{3,}|\*{3,})$", s):
            flush_para(); close_list(); out.append("<hr>")
        elif s.startswith("- ") or s.startswith("* "):
            flush_para()
            if not list_open[0]:
                out.append("<ul>"); list_open[0] = True
            out.append(f"<li>{_inline(s[2:])}</li>")
        else:
            close_list(); para.append(s)
        i += 1
    flush_para(); close_list()
    return "\n".join(out)


_CSS = """
*{box-sizing:border-box} body{margin:0;background:#f3f4f6;font-family:'Segoe UI',Inter,Arial,sans-serif;color:#1a1a1a;}
.page{max-width:820px;margin:24px auto;background:#fff;padding:48px 56px;box-shadow:0 1px 4px rgba(0,0,0,.12);position:relative;}
.lh{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid #0a0a0a;padding-bottom:14px;margin-bottom:8px;}
.lh .org{font-size:18px;font-weight:700;letter-spacing:.02em;}
.lh .sub{font-size:12px;color:#555;margin-top:3px;line-height:1.5;}
.lh .meta{font-size:12px;color:#333;text-align:right;line-height:1.6;}
.stamp{display:inline-block;border:2px solid #b00020;color:#b00020;font-size:12px;font-weight:700;letter-spacing:.08em;
  text-transform:uppercase;padding:5px 12px;border-radius:4px;transform:rotate(-1deg);margin:14px 0 4px;}
h1{font-size:20px;margin:18px 0 6px;} h2{font-size:16px;margin:22px 0 6px;border-bottom:1px solid #e5e5e5;padding-bottom:4px;}
h3{font-size:14px;margin:16px 0 4px;color:#222;}
p{font-size:13.5px;line-height:1.65;margin:8px 0;} li{font-size:13.5px;line-height:1.6;margin:3px 0;}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:12.5px;}
th,td{border:1px solid #d8d8d8;padding:7px 9px;text-align:left;vertical-align:top;}
th{background:#f0f1f3;font-weight:600;} tr:nth-child(even) td{background:#fafafa;}
code{background:#f0f1f3;padding:1px 5px;border-radius:3px;font-family:Consolas,monospace;font-size:12px;}
hr{border:none;border-top:1px solid #e5e5e5;margin:16px 0;}
.foot{margin-top:28px;border-top:1px solid #e5e5e5;padding-top:10px;font-size:11px;color:#777;line-height:1.6;}
@media print{body{background:#fff} .page{box-shadow:none;margin:0;max-width:none}}
"""


def official_html(role: str, item: dict) -> str:
    title = item.get("title", "Report")
    date = item.get("date", "")
    body = md_to_html(item.get("body", ""))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_html.escape(title)}</title><style>{_CSS}</style></head><body>
<div class="page">
  <div class="lh">
    <div>
      <div class="org">{_html.escape(SELLER['name'])}</div>
      <div class="sub">{_html.escape(SELLER['addr'])}<br>
        Fiscal No. (Numri Fiskal): {_html.escape(SELLER['fiscal'])} &middot; {_html.escape(SELLER['email'])}</div>
    </div>
    <div class="meta">Document date: {_html.escape(date)}<br>Role: {_html.escape(role)}<br>Currency: EUR</div>
  </div>
  <div class="stamp">Prepared &mdash; not submitted</div>
  <h1>{_html.escape(title)}</h1>
  {body}
  <div class="foot">Prepared by the Aureon bookkeeping assistant for internal review. This is a
  preparation document, not a filed return, and not licensed tax advice. Figures and any
  statute references must be confirmed with a licensed Kosovo accountant before submission to ATK.</div>
</div></body></html>"""


def write_official_html(role: str, item: dict, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(official_html(role, item), encoding="utf-8")
    return out_path


def _resolve(path_arg: str, latest_role: str | None):
    if latest_role:
        files = sorted(glob.glob(str(L.role_paths(latest_role)["pending"] / "*.json")))
        return Path(files[-1]) if files else None
    p = Path(path_arg)
    return p if p.exists() else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", nargs="?", help="path to a report .json")
    ap.add_argument("--latest", metavar="ROLE", help="render the newest pending report for ROLE")
    ap.add_argument("--desktop", action="store_true", help="also copy the HTML to the Desktop")
    args = ap.parse_args()

    src = _resolve(args.report, args.latest)
    if not src:
        print("no report found (give a path or --latest <role>)")
        return 1
    item = json.loads(src.read_text(encoding="utf-8"))
    role = item.get("role", "report")
    out = L.role_paths(role)["reports"] / f"{src.stem}.html"
    write_official_html(role, item, out)
    print(f"wrote {out}")
    if args.desktop:
        desk = Path.home() / "Desktop" / f"Aureon-{role}-{src.stem}.html"
        desk.write_text(official_html(role, item), encoding="utf-8")
        print(f"wrote {desk}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
