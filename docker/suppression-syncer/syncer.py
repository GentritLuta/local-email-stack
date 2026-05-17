"""syncer.py — innovation #10, federated suppression list.

Two-direction sync:
 - PUSH: send our newly-suppressed HMAC(email, salt) entries to the federation
         (default: append-only git repo; alternative: HTTP POST to a public Worker).
 - PULL: fetch all federated entries; merge into our local suppression_list_federated.

Cron'd nightly. Optional — disabled if SUPPRESSION_FEDERATION_ENABLED=false.

Privacy:
 - Only hashed identifiers leave the node, never raw addresses.
 - Hashes use HMAC-SHA256 with SUPPRESSION_FEDERATION_SALT (configured in bootstrap.env).
 - Salt is shared across all participating nodes so hashes are comparable. This makes
   the privacy story: an attacker with rainbow-table resources could potentially
   reverse single addresses, but doing so at scale is infeasible. The protection is
   adequate for "list of people who complained about cold email"; it is NOT adequate
   for PHI or sensitive PII. Don't reuse this scheme for either of those.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import asyncpg

PG_DSN = os.environ["PG_DSN"]
SALT = os.environ["SUPPRESSION_FEDERATION_SALT"].encode()
ENABLED = os.environ.get("SUPPRESSION_FEDERATION_ENABLED", "false").lower() == "true"
REPO_DIR = Path(os.environ.get("FEDERATION_REPO_DIR", "/var/lib/federation"))
REPO_URL = os.environ.get("FEDERATION_REPO_URL", "https://github.com/yourorg/suppression-federation.git")
REPO_BRANCH = os.environ.get("FEDERATION_REPO_BRANCH", "main")


def hmac_email(addr: str) -> str:
    norm = addr.strip().lower()
    return hmac.new(SALT, norm.encode(), hashlib.sha256).hexdigest()


async def setup_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS suppression_list (
            email_hash TEXT PRIMARY KEY,
            email_plain TEXT,
            reason TEXT NOT NULL,
            added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            pushed BOOLEAN NOT NULL DEFAULT FALSE
        );
        CREATE TABLE IF NOT EXISTS suppression_list_federated (
            email_hash TEXT PRIMARY KEY,
            reason TEXT NOT NULL,
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO_DIR), *args],
        capture_output=True, text=True, check=True,
    ).stdout


def ensure_repo() -> None:
    if not REPO_DIR.exists():
        REPO_DIR.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--branch", REPO_BRANCH, REPO_URL, str(REPO_DIR)],
                       check=True)
    git("fetch", "origin", REPO_BRANCH)
    git("reset", "--hard", f"origin/{REPO_BRANCH}")


def read_federated_entries() -> Iterable[tuple[str, str]]:
    suppressions = REPO_DIR / "suppressions.tsv"
    if not suppressions.exists():
        return
    for line in suppressions.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            yield parts[0], parts[1]


def append_local_to_repo(new_rows: list[tuple[str, str]]) -> None:
    if not new_rows:
        return
    suppressions = REPO_DIR / "suppressions.tsv"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with suppressions.open("a", encoding="utf-8") as f:
        f.write(f"# added {today} from local node\n")
        for h, reason in new_rows:
            f.write(f"{h}\t{reason}\n")
    git("add", "suppressions.tsv")
    git("commit", "-m", f"node sync {today}")
    git("push", "origin", REPO_BRANCH)


async def run_once() -> dict:
    if not ENABLED:
        return {"enabled": False}

    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=2)
    async with pool.acquire() as conn:
        await setup_schema(conn)

        # PUSH new locally-suppressed entries
        new_local = await conn.fetch(
            "SELECT email_hash, reason FROM suppression_list WHERE pushed = FALSE"
        )
        new_local_rows = [(r["email_hash"], r["reason"]) for r in new_local]

        ensure_repo()
        append_local_to_repo(new_local_rows)
        if new_local_rows:
            await conn.execute(
                "UPDATE suppression_list SET pushed = TRUE WHERE email_hash = ANY($1)",
                [r[0] for r in new_local_rows],
            )

        # PULL federation back into local mirror
        pulled = 0
        for h, reason in read_federated_entries():
            res = await conn.execute(
                "INSERT INTO suppression_list_federated (email_hash, reason) VALUES ($1, $2) "
                "ON CONFLICT DO NOTHING",
                h, reason,
            )
            if res == "INSERT 0 1":
                pulled += 1

    await pool.close()
    return {"enabled": True, "pushed": len(new_local_rows), "pulled": pulled}


# Helper for the sender flow: O(1) suppression check against both lists.
async def is_suppressed(addr: str) -> bool:
    h = hmac_email(addr)
    pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=1)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1 WHERE EXISTS (
              SELECT 1 FROM suppression_list           WHERE email_hash = $1
              UNION
              SELECT 1 FROM suppression_list_federated WHERE email_hash = $1
            )
            """,
            h,
        )
    await pool.close()
    return row is not None


if __name__ == "__main__":
    result = asyncio.run(run_once())
    print(result)
