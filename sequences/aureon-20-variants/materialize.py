"""Generates an .eml file per variant for review (no send)."""
from __future__ import annotations
import datetime as dt, email.utils, json, time, uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

HERE = Path(__file__).resolve().parent
data = json.loads((HERE / "variants.json").read_text(encoding="utf-8"))
sender = data["sender"]
domain = sender["from_addr"].split("@", 1)[1]
out_dir = HERE / "eml"
out_dir.mkdir(exist_ok=True)

for v in data["variants"]:
    msg = MIMEMultipart("alternative")
    msg_id = f"<v{v['n']:02d}.{uuid.uuid4().hex}.{int(time.time())}@{domain}>"
    msg["From"] = email.utils.formataddr((sender["from_name"], sender["from_addr"]))
    msg["To"] = "RECIPIENT@example.com"
    msg["Subject"] = v["subject"]
    msg["Reply-To"] = sender["reply_to"]
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = msg_id
    msg["MIME-Version"] = "1.0"
    msg["X-Mailer"] = "Local Email Stack 0.4"
    msg["List-Unsubscribe"] = f"<mailto:{sender['reply_to']}?subject=unsubscribe>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    body_plain = v["body"] + "\n\n" + sender["signature"]
    html = "<!doctype html><html><body style='font-family:-apple-system,Segoe UI,sans-serif;font-size:14px;line-height:1.55;color:#1f2937;max-width:600px'>" + \
           "".join(f"<p>{p}</p>" for p in body_plain.strip().split("\n\n")) + "</body></html>"
    msg.attach(MIMEText(body_plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    path = out_dir / f"{v['n']:02d}-{v['angle']}.eml"
    path.write_bytes(msg.as_bytes())
    print(f"  wrote {path.name}  ({len(msg.as_bytes())} bytes)  {v['subject']!r}")
print(f"\n{len(data['variants'])} .eml files in {out_dir}")
