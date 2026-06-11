# -*- coding: utf-8 -*-
"""Demo: what an agent gets when they reply to an Aureon email with their ZIP.
Renders (1) the avatar's branded email and (2) the attorney-referral CSV as a
styled table, both as PNGs for visual inspection. Demo ZIP 85254 -> Arizona list."""
import csv, html, json, subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
REPO = Path(r"C:\Users\bernh\local-email-stack")
LISTS = REPO / "referral-lists"
OUT = REPO / "out"

ZIP, METRO_LABEL, AGENT = "85254", "the Phoenix metro", "Marcus"
entry = next(e for e in json.loads((LISTS/"curated.json").read_text(encoding="utf-8"))["lists"] if e["metro"] == "Arizona")
rows = list(csv.reader((LISTS/entry["csv"]).open(encoding="utf-8-sig")))
header, data = rows[0], rows[1:]
n = len(data)

# ---------- 1) CSV -> styled PNG table ----------
FS = 15
font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", FS)
bold = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", FS)
big  = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 19)
pad, rowh, CAP, TITLE = 9, 30, 290, 44
tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
def trunc(t, mx):
    if tmp.textlength(t, font=font) <= mx: return t
    while t and tmp.textlength(t+"...", font=font) > mx: t = t[:-1]
    return t+"..."
ti = header.index("Type")
widths = [int(min(max([tmp.textlength(header[c], font=bold)]+[tmp.textlength(r[c], font=font) for r in data]), CAP))+2*pad for c in range(len(header))]
W = sum(widths); H = TITLE + rowh*(n+1)
img = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(img)
# gold title bar
d.rectangle([0,0,W,TITLE], fill="#0a0a0a"); d.rectangle([0,0,6,TITLE], fill="#d4af37")
d.text((16,12), f"Estate/Probate + Divorce Attorney Referral List  -  {METRO_LABEL.title()}  ({n} firms)", fill="#d4af37", font=big)
# header
d.rectangle([0,TITLE,W,TITLE+rowh], fill="#0f172a")
x=0
for c in range(len(header)): d.text((x+pad,TITLE+7), header[c], fill="white", font=bold); x+=widths[c]
for i,r in enumerate(data):
    y=TITLE+rowh*(i+1); is_div=r[ti].startswith("Divorce")
    d.rectangle([0,y,W,y+rowh], fill="#ffffff" if i%2 else "#f8fafc")
    x=0
    for c in range(len(header)):
        color="#1e293b"
        if c==ti:
            d.rectangle([x+4,y+5,x+widths[c]-4,y+rowh-5], fill="#dbeafe" if is_div else "#dcfce7")
            color="#1e40af" if is_div else "#166534"
        d.text((x+pad,y+7), trunc(r[c], widths[c]-2*pad), fill=color, font=font); x+=widths[c]
    d.line([0,y,W,y], fill="#e2e8f0")
x=0
for c in range(len(header)): x+=widths[c]; d.line([x,TITLE,x,H], fill="#e2e8f0")
csv_png = OUT/"_aureon_demo_csv.png"; img.save(csv_png)
print("CSV table ->", csv_png, f"({W}x{H}), {n} firms")

# ---------- 2) branded email -> HTML -> Chrome screenshot ----------
paras = [
 f"Hey {AGENT},",
 f"Here is the attorney referral list I promised for {METRO_LABEL} ({ZIP}), attached two ways: an Excel file and a CSV you can import straight into your CRM. It is {n} firms covering estate and probate plus divorce and family law, the two groups whose clients most often need to sell a home fast.",
 "For each firm you get the lead attorney to ask for, their practice focus, a direct phone, an email where the firm publishes one, the website, and the office address.",
 "The fastest way to use it: pick the firms closest to you, call or email the lead attorney, and offer to be the agent they send any client who needs to sell quickly. Probate and divorce sellers are usually motivated, so even one or two firms saying yes can mean steady listings.",
 "No call needed and no strings. If you ever want us to run the seller outbound that keeps a pipeline like this full for you, just reply and I will send the details.",
]
body_html = "".join(f'<p>{html.escape(p)}</p>' for p in paras)
email_html = f"""<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
body{{margin:0;background:#fafafa;font-family:Inter,system-ui,sans-serif;color:#0a0a0a}}
.wrap{{max-width:600px;margin:24px auto;background:#fff;border:1px solid #e5e7eb;border-radius:14px;overflow:hidden}}
.hdr{{background:#0a0a0a;padding:22px 28px;border-top:4px solid #d4af37}}
.wm{{color:#d4af37;font-weight:700;font-size:20px;letter-spacing:.5px}}
.tag{{color:#94a3b8;font-size:12px;margin-top:3px}}
.body{{padding:26px 28px;font-size:15px;line-height:1.6}}
.body p{{margin:0 0 14px}}
.att{{margin:18px 0;padding:14px 16px;background:#fafafa;border:1px solid #e5e7eb;border-radius:10px}}
.att .row{{display:flex;align-items:center;gap:10px;padding:6px 0}}
.chip{{display:inline-block;width:34px;height:34px;border-radius:8px;background:#d4af37;color:#0a0a0a;font-weight:700;font-size:11px;text-align:center;line-height:34px}}
.fn{{font-weight:600;font-size:14px}}.fs{{color:#94a3b8;font-size:12px}}
.sig{{margin-top:20px}}.sig b{{display:block}}.sig span{{color:#475569;font-size:13px}}
.ftr{{padding:16px 28px;border-top:1px solid #e5e7eb;color:#94a3b8;font-size:11px;line-height:1.5}}
</style></head><body><div class="wrap">
<div class="hdr"><div class="wm">AUREON GLOBAL</div><div class="tag">Performance Partner for Real Estate Agents &amp; Brokerages</div></div>
<div class="body">{body_html}
<div class="att">
  <div style="font-weight:600;font-size:13px;color:#475569;margin-bottom:6px">2 attachments</div>
  <div class="row"><span class="chip">XLSX</span><div><div class="fn">{entry['xlsx']}</div><div class="fs">{n} firms &middot; styled, filterable</div></div></div>
  <div class="row"><span class="chip">CSV</span><div><div class="fn">{entry['csv']}</div><div class="fs">{n} firms &middot; CRM-ready import</div></div></div>
</div>
<div class="sig"><b>Anna Bauer</b><span>Senior Partnership Manager, Aureon Global</span></div>
</div>
<div class="ftr">Aureon Global L.L.C. &middot; Dushkaja 20, 71000 Kacanik, Republic of Kosovo<br>You are receiving this because you replied to our outreach. Unsubscribe anytime.</div>
</div></body></html>"""
html_path = OUT/"_aureon_demo_email.html"; html_path.write_text(email_html, encoding="utf-8")
email_png = OUT/"_aureon_demo_email.png"
chrome = next((p for p in [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                           r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"] if Path(p).exists()), None)
if chrome:
    subprocess.run([chrome,"--headless=new",f"--screenshot={email_png}","--window-size=640,1000",
                    "--hide-scrollbars","--default-background-color=00000000",html_path.as_uri()],
                   capture_output=True, timeout=60)
    print("email ->", email_png, "(rendered)" if email_png.exists() else "(FAILED)")
else:
    print("chrome not found; email HTML at", html_path)
