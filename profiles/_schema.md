# Profile schema

A profile is a self-contained sending identity: domain, voice, persona, warmup
state, reputation history. Each client / persona / sender you operate is one profile.

Profiles live in `profiles/<slug>.json` and are loaded by:
- The desktop app (Profiles route, sidebar profile picker)
- `sequences/profile-aware-send.py` (sender)
- `sequences/warmup-scheduler.py` (warmup loop)
- `sequences/warmup-webhook.py` (reputation ingester)

## Schema

```jsonc
{
  "slug": "algoalpha",                      // lowercase, used in filenames + URLs
  "name": "AlgoAlpha",                      // display name
  "created_at": "2026-05-17",
  "active": true,                           // can be temporarily disabled

  "identity": {
    "from_name": "Tomás Silva",
    "from_addr": "tomas@mail.algoalpha.io", // must be on a domain in 'relay.from_domains'
    "reply_to": "tomas@mail.algoalpha.io",
    "role": "Co-founder",
    "company": "AlgoAlpha",
    "site": "https://algoalpha.io",
    "signature": "Tomás · co-founder, AlgoAlpha\nhttps://algoalpha.io"
  },

  "voice": {                                 // injected into LLM prompts for personalization
    "register": "calm-technical",
    "quirks": ["specific numbers", "minimal fluff"],
    "avoid": ["hype", "vague metrics"]
  },

  "relay": {                                 // Resend by default — see SENDER_RELAY.md
    "backend": "resend",
    "resend_api_key": "",                    // set via Settings → Sender (never commit)
    "from_domains": ["mail.algoalpha.io"],   // domains verified in Resend
    "domain_verified_at": null,              // ISO ts, populated by resend-setup.py
    "dkim_selector": "resend"
  },

  "warmup": {
    "enabled": true,
    "started_at": null,                      // ISO date; set to today when warmup begins
    "current_day": 0,                        // advances daily, paused on reputation issues
    "ramp_curve": "snowball_v1",
    "max_daily_sends": 300,
    "warmup_targets": [                      // friendly inboxes you control; engagement-friendly
      "warmup1@gmail.com",
      "warmup2@gmail.com",
      "warmup3@outlook.com"
    ],
    "real_send_mix": [                       // % of daily sends that are warmup vs real
      { "until_day": 14,  "warmup_pct": 80 },
      { "until_day": 30,  "warmup_pct": 30 },
      { "until_day": 45,  "warmup_pct": 10 },
      { "until_day": 9999,"warmup_pct": 5  }
    ],
    "reputation": {
      "bounce_rate_7d": 0.0,
      "complaint_rate_7d": 0.0,
      "delivered_7d": 0,
      "last_check": null
    },
    "auto_pause_thresholds": {
      "bounce_rate":    0.05,                // 5% bounces → pause for review
      "complaint_rate": 0.001                // 0.1% complaints → pause for review
    }
  },

  // The snowball ramp — industry-standard cold-email warmup curve.
  "ramp_curve_snowball_v1": [
    { "from_day": 1,  "daily": 10  },
    { "from_day": 4,  "daily": 20  },
    { "from_day": 8,  "daily": 40  },
    { "from_day": 15, "daily": 80  },
    { "from_day": 22, "daily": 150 },
    { "from_day": 31, "daily": 250 },
    { "from_day": 46, "daily": 300 }
  ]
}
```

## Field rules

- **`slug`** is the canonical identifier. Used in filenames (`profiles/<slug>.json`,
  `sequences/<slug>-<...>/`), the app URL (`#/profile/<slug>`), and as the FK
  on sequence + warmup_log rows.
- **`identity.from_addr`** must have a domain that's in **`relay.from_domains`**
  AND verified in Resend (set `relay.domain_verified_at` when verification passes).
- **`relay.resend_api_key`** is *never* committed; the desktop Sender tab writes it to
  `profiles/<slug>.private.json` (gitignored) and merges at load time.
- **`warmup.warmup_targets`** should be 3–5 addresses you actually monitor.
  When a warmup email arrives, you open it, mark important, reply when sensible.
  This generates the engagement signals that build domain reputation.

## Lifecycle

1. **Create:** Profiles route → Add profile → fill in identity + domain.
2. **Connect Resend:** Sender tab → paste API key → click "Verify domain" → app calls
   `resend-setup.py`, gets DNS records, displays them. You paste into Cloudflare.
3. **Wait 5–10 min** for DNS propagation. App polls Resend until verification flips green.
4. **Start warmup:** Warmup tab → "Start warmup" → sets `warmup.started_at = today`,
   `current_day = 1`. The scheduler begins sending 10/day to warmup_targets.
5. **Ramp:** Each 24h the scheduler advances `current_day` and recalculates daily quota
   from the ramp curve. Mix shifts from 80% warmup → 5% maintenance over 45 days.
6. **Send real:** Sequences route → attach sequence to profile → enqueue. Sends go
   out alongside warmup traffic respecting the daily quota.
7. **React:** Resend webhook posts bounce/complaint events to `warmup-webhook.py`.
   Webhook updates `warmup.reputation`. Above threshold → ramp pauses automatically.
