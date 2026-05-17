"""infra — WHOIS, DNS, SSL cert, archive.org for a website."""

from __future__ import annotations

import asyncio
import logging
import socket
import ssl
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("enricher.infra")


async def collect(website: str) -> dict:
    if not website.startswith("http"):
        website = "https://" + website
    host = urlparse(website).netloc.split(":")[0]

    whois_d, dns_d, ssl_d, archive_d = await asyncio.gather(
        _whois(host),
        _dns(host),
        _ssl_cert(host),
        _archive_org(website),
        return_exceptions=True,
    )

    return {
        "whois":       whois_d if not isinstance(whois_d, Exception) else {},
        "dns":         dns_d if not isinstance(dns_d, Exception) else {},
        "ssl":         ssl_d if not isinstance(ssl_d, Exception) else {},
        "archive_org": archive_d if not isinstance(archive_d, Exception) else {},
    }


async def _whois(host: str) -> dict:
    """Use the free RDAP service at rdap.org."""
    domain = ".".join(host.split(".")[-2:])
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"https://rdap.org/domain/{domain}")
        if r.status_code != 200:
            return {}
        j = r.json()
        events = {e.get("eventAction"): e.get("eventDate") for e in j.get("events", [])}
        created = events.get("registration")
        age_years = None
        if created:
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                age_years = round((datetime.now(timezone.utc) - dt).days / 365, 1)
            except Exception:
                pass
        registrar = ""
        for ent in j.get("entities", []) or []:
            if "registrar" in (ent.get("roles") or []):
                vcard = ent.get("vcardArray") or []
                if len(vcard) > 1:
                    for item in vcard[1]:
                        if item[0] == "fn":
                            registrar = item[3]
                            break
        return {"created": created, "registrar": registrar, "age_years": age_years}


async def _dns(host: str) -> dict:
    """MX provider classification + TXT (SPF, DMARC presence)."""
    domain = ".".join(host.split(".")[-2:])

    def blocking():
        try:
            import dns.resolver
            mx = sorted([str(r.exchange).rstrip(".").lower() for r in dns.resolver.resolve(domain, "MX")])
        except Exception:
            mx = []
        try:
            import dns.resolver
            txt = [b"".join(r.strings).decode("utf-8", "ignore") for r in dns.resolver.resolve(domain, "TXT")]
        except Exception:
            txt = []
        return mx, txt

    mx, txt = await asyncio.to_thread(blocking)

    def mx_provider(records: list[str]) -> str:
        joined = " ".join(records)
        if "google.com" in joined or "googlemail" in joined: return "Google Workspace"
        if "outlook.com" in joined or "protection.outlook" in joined: return "Microsoft 365"
        if "zoho" in joined: return "Zoho Mail"
        if "yandex" in joined: return "Yandex"
        if "fastmail" in joined or "messagingengine" in joined: return "Fastmail"
        if "icloud" in joined or "apple" in joined: return "iCloud"
        if "improvmx" in joined: return "ImprovMX"
        return records[0] if records else "unknown"

    return {
        "mx_provider": mx_provider(mx),
        "mx_records": mx,
        "spf_present": any(t.startswith("v=spf1") for t in txt),
        "dmarc_present": False,  # would need separate _dmarc.domain lookup
        "txt_records": [t for t in txt if len(t) < 300],
    }


async def _ssl_cert(host: str) -> dict:
    def blocking() -> dict:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=8) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
        subj = {x[0][0]: x[0][1] for x in (cert.get("subject") or [])}
        issuer = {x[0][0]: x[0][1] for x in (cert.get("issuer") or [])}
        return {
            "issuer": issuer.get("organizationName") or issuer.get("commonName"),
            "subject_org": subj.get("organizationName"),
            "subject_cn": subj.get("commonName"),
            "not_after": cert.get("notAfter"),
        }
    try:
        return await asyncio.to_thread(blocking)
    except Exception as ex:
        logger.debug("ssl cert for %s failed: %s", host, ex)
        return {}


async def _archive_org(website: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        try:
            r = await c.get(
                "http://archive.org/wayback/available",
                params={"url": website, "timestamp": "1990"},
            )
            j = r.json()
            snap = j.get("archived_snapshots", {}).get("closest", {})
            first_seen = snap.get("timestamp")
            return {"first_seen": first_seen, "url": snap.get("url")}
        except Exception:
            return {}
