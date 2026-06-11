import os, subprocess, shutil
from pathlib import Path

# build deploy dir
d = Path('out/diraya-review-site'); d.mkdir(parents=True, exist_ok=True)
shutil.copy('lead-magnets/Diraya-Architecture-Review.pdf', d / 'Diraya-Architecture-Review.pdf')
(d / 'index.html').write_text(
 '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
 '<title>Diraya - Architecture Review</title>'
 '<meta name="viewport" content="width=device-width,initial-scale=1">'
 '<meta http-equiv="refresh" content="0; url=./Diraya-Architecture-Review.pdf">'
 '<style>body{font-family:-apple-system,Segoe UI,sans-serif;background:#0A0A0A;color:#fff;'
 'display:flex;min-height:90vh;align-items:center;justify-content:center;text-align:center}'
 'a{color:#FF6B00;font-weight:700}</style></head>'
 '<body><div><p>Opening your Architecture Review...</p>'
 '<p><a href="./Diraya-Architecture-Review.pdf">Download the PDF</a></p>'
 '<p style="color:#8A8A8A;font-size:13px">Diraya // diraya.ca</p></div></body></html>', encoding='utf-8')

env = dict(os.environ)
for l in Path('sequences/hostinger.env').read_text(encoding='utf-8').splitlines():
    if l.startswith('CF_API_TOKEN='): env['CLOUDFLARE_API_TOKEN'] = l.split('=', 1)[1].strip().strip('"').strip("'")
    if l.startswith('CF_ACCOUNT_ID='): env['CLOUDFLARE_ACCOUNT_ID'] = l.split('=', 1)[1].strip().strip('"').strip("'")

def run(cmd):
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, shell=True, encoding='utf-8', errors='replace')
    print(f'[exit {p.returncode}] {cmd[:60]}', flush=True)

run('npx -y wrangler@latest pages project create diraya-review --production-branch main')
run('npx -y wrangler@latest pages deploy out/diraya-review-site --project-name diraya-review --branch main --commit-dirty true')
print('done', flush=True)
