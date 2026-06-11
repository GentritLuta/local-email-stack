import os, subprocess
from pathlib import Path
env = dict(os.environ)
for l in Path('sequences/hostinger.env').read_text(encoding='utf-8').splitlines():
    if l.startswith('CF_API_TOKEN='):
        env['CLOUDFLARE_API_TOKEN'] = l.split('=', 1)[1].strip().strip('"').strip("'")
    if l.startswith('CF_ACCOUNT_ID='):
        env['CLOUDFLARE_ACCOUNT_ID'] = l.split('=', 1)[1].strip().strip('"').strip("'")

def run(cmd):
    print('>>>', cmd, flush=True)
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, shell=True)
    out = (p.stdout or '')[-2500:]
    err = (p.stderr or '')[-1800:]
    if out: print(out, flush=True)
    if err: print('[stderr]', err, flush=True)
    print(f'[exit {p.returncode}]', flush=True)
    return p.returncode

# create project (idempotent-ish; ignore "already exists")
run('npx -y wrangler@latest pages project create diraya-ghosts --production-branch main')
# deploy
run('npx -y wrangler@latest pages deploy out/diraya-ghosts-site --project-name diraya-ghosts --branch main --commit-dirty true')
