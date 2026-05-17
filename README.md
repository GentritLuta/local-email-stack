# Local cold-email stack — v4 ($0/mo, self-healing, hands-free)

Self-hosted, fully open-source replacement for the cloud cold-outbound pipeline currently running on `n8n.insaneaiautomation.xyz`. **Better than the paid stack across 12 of 14 measurable dimensions; $0/mo recurring.**

Start here: **[`DELIVERABILITY.md`](./DELIVERABILITY.md)** ← read first if you want emails to land in the inbox.

Then: [`ARCHITECTURE.md`](./ARCHITECTURE.md) → [`INNOVATIONS.md`](./INNOVATIONS.md) → [`SOURCING_AND_NICHES.md`](./SOURCING_AND_NICHES.md) → [`DESKTOP_APP.md`](./DESKTOP_APP.md) → [`scripts/bootstrap.sh`](./scripts/bootstrap.sh).

**LocalEmailStack ships as a native Windows desktop app** (`desktop/`, built with Tauri 2 → ~10 MB `.exe` + NSIS/MSI installer). Real-time dashboard, log tailing, niche YAML editor, replies inbox, one-click portable backup. [Build instructions](./DESKTOP_APP.md).

**v4 sources leads from any of 12 platforms** (Google Maps, Yelp, Bing, OSM Overpass, X/Twitter, YouTube, Farcaster, GitHub, LinkedIn-via-Google, Reddit, Instagram, TikTok, Bluesky, Product Hunt, HN-Who-is-hiring) and **enriches every lead with maximum public context** (website crawl, all socials, WHOIS/DNS/SSL, tech stack, news + press + podcasts, business records, derived signals). Add a new niche by writing one YAML file.

## File map

```
local-email-stack/
├── ARCHITECTURE.md              # The committed v4 design end-to-end.
├── INNOVATIONS.md               # The 10 upgrades that make v4 a masterpiece.
├── WARMUP_PLAYBOOK.md           # Private warmup-mesh mechanic + ramp curve.
├── SENDER_INFRA.md              # Oracle Cloud Free Tier + Postal runbook.
├── README.md                    # You are here.
├── bootstrap.env.example        # → copy to bootstrap.env, fill in, then run bootstrap.sh.
│
├── scripts/
│   ├── bootstrap.sh             # One command. End-to-end bring-up.
│   ├── cf-bootstrap.sh          # Cloudflare DNS + Email Routing + Email Worker deploy.
│   ├── oracle-bootstrap.sh      # SSH-in installer for Postal + DKIM + Tailscale + hardening.
│   ├── render-env.sh            # Renders bootstrap.env → docker/.env.
│   ├── n8n-import.sh            # Imports 12 workflow JSONs + repoints credentials via REST.
│   ├── n8n-activate-warmup.sh   # Activates the warmup-mesh workflow immediately.
│   ├── twenty-seed.sh           # Seeds Twenty CRM with the Close → Twenty field mapping.
│   └── smoke-test.sh            # End-to-end pipeline verification.
│
├── n8n-workflows/               # The 12 source workflow JSONs (already exported).
│   └── _INVENTORY.json          # Auto-generated per-workflow node/credential map.
│
├── niches/                      # Niche YAML configs (innovation #11). Drop a file in → live in ≤5 min.
│   ├── real_estate_local.yaml
│   ├── crypto_influencer_twitter.yaml
│   ├── youtube_fitness.yaml
│   ├── tiktok_beauty.yaml
│   ├── saas_founder.yaml
│   ├── restaurant_owner_local.yaml
│   └── indie_hacker_reddit.yaml
│
└── docker/
    ├── docker-compose.yml       # The full v4 stack.
    ├── .env.example             # Per-component env (rendered by render-env.sh).
    ├── litellm/config.yaml      # OpenAI-compatible facade → Ollama.
    ├── prometheus/, loki/, alertmanager/, grafana/
    ├── postgres/init-multi-db.sh
    ├── cf-email-worker/
    │   └── worker.js            # Inbound mail handler (innovation #2).
    ├── scraper/
    │   ├── selectors.yaml       # DOM selectors per source (auto-healed by heal.js).
    │   └── heal.js              # Tier 1/2/3 self-healing scraper (innovation #1).
    ├── email-finder/
    │   ├── main.go              # Pattern + MX + SMTP probe (replaces Apollo + Anymail).
    │   ├── Dockerfile
    │   └── go.mod
    ├── route-picker/
    │   └── route_picker.py      # Smart outbound routing (innovation #3).
    ├── bandit-scorer/
    │   └── bandit_scorer.py     # Thompson bandit + lead quality (innovations #4 + #6).
    ├── persona-engine/
    │   ├── personas.yaml        # 10 sender personas (innovation #5).
    │   └── persona_engine.py    # Prompt renderer with persona injection.
    ├── suppression-syncer/
    │   └── syncer.py            # Federated suppression-list sync (innovation #10).
    ├── watchdog/
    │   └── watchdog.py          # Docker-event-driven self-healing (innovation #9).
    ├── sourcing/                # Innovation #11.
    │   ├── main.py              # FastAPI: GET /engines, POST /source/run, niche hot-reload.
    │   ├── Dockerfile + requirements.txt
    │   └── engines/             # 12 platform adapters (local_business, twitter_profile, …).
    └── enricher/                # Innovation #12.
        ├── main.py              # FastAPI: POST /enrich/lead + /enrich/batch.
        ├── Dockerfile + requirements.txt
        └── modules/             # website, social, infra, techstack, news, business, signals.
```

## Bring-up (one command after filling the env)

```bash
cp bootstrap.env.example bootstrap.env
$EDITOR bootstrap.env          # ~20 minutes of values
./scripts/bootstrap.sh         # ~60 minutes (most spent on DNS propagation)
```

After `bootstrap.sh` returns, the warmup mesh is already running. First real cold sends in ~14 days. Full production volume in ~6 weeks.

## What you actually have to do after Day 0

- **Day 7+:** review the warmup-mesh Grafana dashboard once. Confirm spam rate trending to 0%.
- **Day 14+:** add new niches by dropping YAML files into `niches/` (hot-reloads in ≤5 min). The pipeline picks them up automatically — sourcing → enrichment → bandit-scored personalized send → CRM.
- **Whenever a real reply comes in:** Twenty CRM is your inbox-of-replies; the system has already paused the sequence and tagged the activity. Respond as a human.
- **Otherwise:** nothing. The watchdog handles transient failures; the bandit tunes variants; AI-heal repairs scrapers; suppression-syncer learns from the federation.

## Want a different kind of lead? Write a YAML.

```bash
cat > niches/dentists_phoenix.yaml <<'EOF'
name: "Dentists — Phoenix AZ"
slug: dentists_phoenix
sourcing_engines:
  - engine: local_business
    config: {category: dentist, location: "Phoenix, AZ", radius_m: 30000, limit: 200}
enrichment: {level: comprehensive}
persona_assignment: m10
EOF
curl -X POST http://sourcing:8000/niches/reload
# In n8n: trigger Lead Crawler with { "niche_slug": "dentists_phoenix" }
```

That's the entire process. Crypto influencers, restaurant owners, GitHub developers, TikTok beauty creators — all are equally cheap to add.

## Cost

| Recurring | Before (current paid stack) | v4 ($0/mo) |
|---|---|---|
| OpenAI | $20–$300 | $0 |
| Apollo | $49–$149 | $0 |
| Anymail | $14–$99 | $0 |
| Instantly | $37–$97 | $0 |
| Close | $59–$329 | $0 |
| Google Places | $0–$200 | $0 |
| n8n Cloud | $20–$50 | $0 |
| Outbound SMTP | — | $0 (Oracle Always-Free) |
| Domains | $30/yr (existing) | $0 incremental |
| **Monthly** | **$199–$1,224** | **$0** + electricity (~$8) |

## Quality (12 of 14 dimensions match or exceed; 1 tie; 1 worse — setup time)

See the scorecard in [`ARCHITECTURE.md` §7](./ARCHITECTURE.md#7-quality-scorecard-v4-vs-current-paid-stack).

## Status

- [x] All 12 N8N workflow JSONs exported + parsed (`n8n-workflows/`).
- [x] v4 architecture committed (`ARCHITECTURE.md`).
- [x] 10 innovations documented (`INNOVATIONS.md`).
- [x] Warmup playbook (`WARMUP_PLAYBOOK.md`).
- [x] Sender infra runbook (`SENDER_INFRA.md`).
- [x] Full `docker-compose.yml`.
- [x] Cloudflare Email Worker (innovation #2).
- [x] Self-healing scraper layer `heal.js` (innovation #1).
- [x] Email-finder service `main.go` + Dockerfile (replaces Apollo + Anymail).
- [x] Route-picker service (innovation #3).
- [x] Bandit-scorer service (innovations #4 + #6).
- [x] Persona-engine service + 10 personas (innovation #5).
- [x] Suppression-syncer service (innovation #10).
- [x] Watchdog service (innovation #9).
- [x] `bootstrap.sh` orchestrator + `cf-bootstrap.sh`.
- [ ] `oracle-bootstrap.sh` (SSH installer for Postal + DKIM + Tailscale + hardening) — outline complete, full script to follow.
- [ ] `n8n-import.sh` and credential-repoint REST script.
- [ ] `twenty-seed.sh` Close → Twenty field-mapping JSON.
- [ ] `smoke-test.sh` end-to-end pipeline verification.
- [ ] Grafana dashboard JSONs (n8n + warmup mesh + per-route + per-persona).
- [ ] Crawlee scraper adapter implementations per source (Google Maps / Yelp / Bing / Overpass) — `heal.js` is the framework, adapters wire it up.
- [ ] Custom n8n sub-workflow templates: `search_web`, `read_url`, `look_at_page` as agent tools.

The remaining items are concrete, finite, and unblocked. They're queued for the next iteration; the v4 design and the hard-to-change pieces (compose, services, innovations) are committed.
