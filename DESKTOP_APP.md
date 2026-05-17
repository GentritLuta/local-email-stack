# Desktop App — Build, Run, Distribute, Transfer

The `desktop/` folder is a **Tauri 2** application that turns the LocalEmailStack into a native Windows `.exe` (≈10 MB) with its own logo, real-time dashboard, log tailing, niche editor, replies inbox, and one-click portable backup for transferring everything to another PC.

It does **not** package the Docker stack itself into the .exe — Docker is the runtime. The app is a control panel that drives `docker compose` and queries the running services for live state. This keeps the app tiny, portable, and trustworthy (no opaque mega-installer).

## What's in the app

| Screen | Purpose |
|---|---|
| **Overview** | Top-of-funnel KPIs, service-health table, start/stop the stack, quick links to n8n / NocoDB / Twenty / Grafana. |
| **Pipeline** | Live count per stage (`sourced → enriched → queued → sent → replied → bounced`) + last 50 leads with current stage. |
| **Sourcing** | List of niches; "Run now" triggers `POST /source/run` on the sourcing service. |
| **Warmup** | Per-subdomain ramp day, spam-folder rate, sends/receives/replies today, status. |
| **Bandit** | Thompson-bandit leaderboard per persona (subjects / openings / CTAs), with reply rate. |
| **Replies** | Cloudflare Email Worker inbox: classified (reply / bounce / complaint / unrelated), with preview pane. |
| **Niches** | YAML editor (Monaco) for `niches/*.yaml`; save reloads the sourcing service. |
| **Personas** | YAML editor for `docker/persona-engine/personas.yaml`; save restarts persona-engine. |
| **Logs** | Real-time `docker logs --follow` for any container, with substring filter, 2,000-line rolling buffer. |
| **Settings** | General app config + `bootstrap.env` editor + **Portable export/import** + service smoke-test. |
| **Setup wizard** | 5-step first-run flow (shown automatically on a fresh install). |

## Architecture

```
LocalEmailStack.exe (Tauri 2)
├── Rust backend (src-tauri/)
│   ├── lib.rs / main.rs     – Tauri app + plugin registration
│   ├── paths.rs             – stack repo discovery + app-data paths
│   ├── docker.rs            – wraps `docker compose ps/up/down/restart/logs`
│   │                          and `docker run busybox tar` for volume backup
│   ├── stats.rs             – queries Postgres for live dashboard metrics
│   ├── portable.rs          – export/import bundle (zip with repo + env + volumes)
│   └── commands.rs          – the Tauri command surface (called from JS)
└── React + Vite frontend (frontend/)
    ├── App.tsx              – router + sidebar shell
    ├── routes/*.tsx         – Dashboard, Pipeline, Sourcing, Warmup, Bandit,
    │                          Replies, Niches, Personas, Logs, Settings, Setup
    ├── lib/api.ts           – typed `invoke()` wrapper for every Tauri command
    └── styles/global.css    – dark theme matched to the orbit logo
```

## Prerequisites (one-time, on the build machine)

1. **Rust** (stable): https://rustup.rs/
2. **Node 20 LTS + npm**: https://nodejs.org/
3. **Tauri prerequisites** for your OS: https://v2.tauri.app/start/prerequisites/
   - Windows: WebView2 runtime (already installed on Win10 22H2 + Win11)
   - Visual Studio Build Tools with the "Desktop development with C++" workload

Verify:
```powershell
rustc --version       # 1.78+
node --version        # 20+
cargo install tauri-cli --version "^2"
```

## Develop

```powershell
cd desktop\frontend
npm install
cd ..\src-tauri
cargo tauri dev
```

That opens the app with hot-reload on the frontend and a debug Rust build.

## Build the .exe + installer

```powershell
cd desktop\src-tauri
cargo tauri build
```

Artifacts land in `desktop\src-tauri\target\release\`:

| File | What |
|---|---|
| `local-email-stack.exe` | The single-binary executable. Portable — works alone if Docker is on PATH. |
| `bundle\nsis\LocalEmailStack_0.4.0_x64-setup.exe` | NSIS installer (per-user, no admin). Recommended for distribution. |
| `bundle\msi\LocalEmailStack_0.4.0_x64_en-US.msi` | MSI installer (admin-required, for managed Windows deployments). |

The installer registers the app in Start Menu, adds an uninstaller, and includes the orbit logo as the program icon.

## First run

1. Double-click the installer → installs to `%LOCALAPPDATA%\LocalEmailStack`.
2. Launch from Start Menu → **Setup wizard** runs automatically.
3. Step 1 — Welcome.
4. Step 2 — point at your local clone of the `local-email-stack` repo (the folder containing `docker/docker-compose.yml`).
5. Step 3 — Postgres DSN override (leave blank to auto-derive from `bootstrap.env`).
6. Step 4 — n8n URL + auto-start preference.
7. Step 5 — Finish. App opens to the Overview.
8. Click **Start stack** if you haven't run `docker compose up -d` yet.

## Transferring to another PC

Built into the app. **Two clicks on the source machine, two on the destination:**

### On the source PC
1. Settings → Portable tab → **Export (without LLM models)** (~50–500 MB)
   - or **Export with models** if the destination has no internet for re-pulling them (adds ~25 GB).
2. Pick where to save the `.zip` (USB stick, NAS share, encrypted cloud, etc.).

### On the destination PC
1. Install Docker Desktop + LocalEmailStack.exe.
2. Launch the app → skip the wizard (or fill in dummy values).
3. Settings → Portable tab → **Import bundle…** → pick the `.zip` → pick the folder to restore the repo to.
4. App restores all Docker volumes (Postgres, n8n, Twenty, MinIO, etc.) + the repo + `bootstrap.env`.
5. Settings → General → set **Stack repo path** to the restored folder → Save.
6. Overview → **Start stack**.
7. (If you didn't export models) Wait ~10 min while Ollama pulls Qwen 2.5 32B + Qwen2-VL 7B + nomic-embed-text on first start.

Everything works exactly as on the source machine — same leads, same warmup history, same bandit posteriors, same Twenty CRM contents, same n8n credentials.

### What's in the bundle

```
bundle.zip
├── META.json                                # version, source machine, bundle id
├── repo/                                    # the entire stack repo (compose, scripts, niches, personas, code)
├── env/bootstrap.env                        # all secrets — DO NOT publish unencrypted
└── volumes/                                 # docker named volumes, exported via busybox tar
    ├── local-email-stack_postgres_data.tar.gz
    ├── local-email-stack_n8n_data.tar.gz
    ├── local-email-stack_twenty_data.tar.gz
    ├── local-email-stack_minio_data.tar.gz
    ├── local-email-stack_qdrant_data.tar.gz
    ├── local-email-stack_redis_data.tar.gz
    ├── local-email-stack_nocodb_data.tar.gz
    ├── local-email-stack_grafana_data.tar.gz
    ├── local-email-stack_prometheus_data.tar.gz
    ├── local-email-stack_loki_data.tar.gz
    ├── local-email-stack_searxng_data.tar.gz
    ├── local-email-stack_federation_repo.tar.gz
    ├── local-email-stack_traefik_certs.tar.gz
    └── local-email-stack_ollama_models.tar.gz       # only if "with models" chosen
```

### Headless alternative

If you want to script the transfer (CI/CD, scheduled backups), the same code path is available as PowerShell:

```powershell
# Source PC — back up nightly
& "$PSScriptRoot\..\portable-scripts\export-state.ps1" `
  -Output "\\nas\backups\les-$(Get-Date -Format yyyyMMdd).zip"

# Destination PC — restore
& "$PSScriptRoot\..\portable-scripts\import-state.ps1" `
  -Source "\\nas\backups\les-20260517.zip" `
  -Repo   "C:\Users\me\local-email-stack"
```

## Auto-update (optional)

Tauri 2 ships an updater plugin. To enable:

1. Generate signing keys: `cargo tauri signer generate -w ~/.tauri/myapp.key`
2. Publish releases to GitHub Releases (or any HTTPS endpoint).
3. Add `tauri-plugin-updater` to `Cargo.toml` + the updater config to `tauri.conf.json` with the endpoint + public key.

Future updates land via a discrete in-app notification on launch.

## Code-signing for distribution

Unsigned `.exe` files trigger the Windows SmartScreen "Unknown publisher" warning. For real distribution:

1. Buy an OV/EV code-signing cert (DigiCert / Sectigo / SSL.com, ~$60–200/yr — this is **one of the few things in this whole stack that costs money**).
2. Set the cert thumbprint in `tauri.conf.json` → `bundle.windows.certificateThumbprint`.
3. Re-run `cargo tauri build`. Tauri signs the .exe + .msi + NSIS installer automatically.

You can skip signing for personal use across your own machines — just dismiss the SmartScreen prompt once.

## Permissions the app needs

| Resource | Why |
|---|---|
| `docker` CLI | Stack lifecycle, log streaming, volume export/import |
| Outbound HTTP to `127.0.0.1:*` | Probing service `/healthz` endpoints |
| Postgres TCP on `127.0.0.1:5432` | Dashboard metrics (requires Postgres port to be published from compose) |
| Read/write the app-data dir (`%APPDATA%\LocalEmailStack`) | Settings, portable working dir |
| Read/write the stack repo dir | YAML editors |
| Network: `searxng`, `sourcing`, `enricher`, etc. via Docker network → host port | Niche reload + sourcing job triggers |

It does **not** require admin privileges, internet access (unless you opt into auto-update), or any cloud APIs at runtime.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Dashboard shows all zeros | Postgres port 5432 not published. Edit `docker/docker-compose.yml` → `postgres.ports: ["127.0.0.1:5432:5432"]`. |
| "Stack repo path unset" | Settings → General → pick the folder containing `docker/docker-compose.yml`. |
| Smoke test all red | Stack not started. Overview → Start stack, then wait ~60 s for services to become healthy. |
| Logs panel empty | The container exists but hasn't logged in your selected window. Try a different container. |
| Import bundle fails on Windows with long paths | Enable long-path support: `git config --system core.longpaths true` + Group Policy "Enable Win32 long paths". |
| Niches list empty | Repo path is wrong, or `niches/` is empty. Check Settings → General. |
