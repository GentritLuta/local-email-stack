# local-email-stack — VPS Dockerfile
#
# One image, multiple entry points. Cron schedules the per-task commands.
# Includes Chromium + Playwright deps for lead_scrape / seed_discover /
# tradingview_scrape.

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Europe/Berlin

# Cron + Chromium prerequisites for Playwright headless
RUN apt-get update && apt-get install -y --no-install-recommends \
    cron tzdata ca-certificates curl \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxkbcommon0 \
    libatspi2.0-0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 libxshmfence1 \
    fonts-liberation fonts-noto-color-emoji \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps (install before code copy for layer caching)
COPY deploy/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
 && python -m playwright install chromium --with-deps || true

# Code + niche / profile config. Secrets come in via /app/secrets at runtime.
COPY sequences/ /app/sequences/
COPY scripts/   /app/scripts/
COPY profiles/  /app/profiles/
COPY niches/    /app/niches/

# Persistent state — mounted from host volume in compose
RUN mkdir -p /app/warmup-state /app/out

# Crontab (also mountable via compose for runtime tweaks)
COPY deploy/crontab /etc/cron.d/les-tasks
RUN chmod 0644 /etc/cron.d/les-tasks && crontab /etc/cron.d/les-tasks

# Default: start cron in foreground so docker-compose can supervise it.
# Override with `docker compose run app py scripts/<one-shot>.py` for ad-hoc.
CMD ["sh", "-c", "echo \"$(date -Iseconds)  container start\" >> /app/warmup-state/cron.log && cron -f"]
