import { useEffect, useMemo, useState } from "react";
import { Plus, Trash2, RefreshCw, ShieldCheck, AlertCircle } from "lucide-react";
import { EmptyState } from "../components/EmptyState";
import {
  DbProfile, DbSendLog,
  fetchProfiles, fetchSendLog,
  isConfigured, subscribeToTable, getSupabase,
} from "../lib/supabase";

type DomainEntry = {
  domain: string;
  resend_domain_id?: string | null;
  verified_at?: string | null;
  warmup?: {
    enabled?: boolean;
    current_day?: number;
    started_at?: string | null;
    ramp_curve?: string;
    max_daily_sends?: number;
    reputation?: { bounce_rate_7d?: number; complaint_rate_7d?: number; delivered_7d?: number };
  };
};

const FRESH_WARMUP = {
  enabled: true, current_day: 0, started_at: null,
  ramp_curve: "snowball_v1", max_daily_sends: 90,
  reputation: { bounce_rate_7d: 0, complaint_rate_7d: 0, delivered_7d: 0, last_check: null as string | null },
};

function freshEntry(domain: string): DomainEntry {
  return { domain: domain.toLowerCase().trim(), resend_domain_id: null, verified_at: null, warmup: { ...FRESH_WARMUP } };
}

// ─── Component ─────────────────────────────────────────────────────────────

export function Domains() {
  const [profiles, setProfiles] = useState<DbProfile[]>([]);
  const [sends, setSends]       = useState<DbSendLog[]>([]);
  const [selectedSlug, setSelectedSlug] = useState<string>("");
  const [loaded, setLoaded]     = useState(false);
  const [busy, setBusy]         = useState(false);
  const [msg, setMsg]           = useState<string | null>(null);

  const [single, setSingle]     = useState("");
  const [bulk, setBulk]         = useState("");

  async function refresh() {
    if (!isConfigured()) { setLoaded(true); return; }
    const [ps, sl] = await Promise.all([fetchProfiles(), fetchSendLog(5000)]);
    setProfiles(ps); setSends(sl); setLoaded(true);
    if (!selectedSlug && ps.length) setSelectedSlug(ps[0].slug);
  }

  useEffect(() => {
    refresh();
    const u = [subscribeToTable("profiles", refresh), subscribeToTable("send_log", refresh)];
    return () => u.forEach(fn => fn());
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selected = profiles.find(p => p.slug === selectedSlug) || null;
  const pool: DomainEntry[] = (selected?.config?.relay?.from_domains ?? []) as DomainEntry[];

  // Today's send count per subdomain for this profile (drives "headroom today")
  const sendsByDomainToday = useMemo(() => {
    const m = new Map<string, number>();
    if (!selected) return m;
    const today = new Date(); today.setHours(0, 0, 0, 0);
    for (const s of sends) {
      if (new Date(s.sent_at) < today) continue;
      const dom = (s.from_addr.split("@")[1] || "").toLowerCase();
      // We assume from_addr's local part doesn't collide across profiles.
      m.set(dom, (m.get(dom) ?? 0) + 1);
    }
    return m;
  }, [sends, selected]);

  async function patchProfilePool(slug: string, next: DomainEntry[], successMsg: string) {
    const s = getSupabase();
    if (!s) { setMsg("Supabase not configured (Settings → Cross-PC sync)."); return; }
    setBusy(true); setMsg(null);
    try {
      // Read fresh config, mutate from_domains, write back
      const { data, error } = await s.from("profiles").select("config").eq("slug", slug).single();
      if (error) throw error;
      const cfg = (data?.config as any) || {};
      cfg.relay = { ...(cfg.relay || {}), from_domains: next };
      const { error: ue } = await s.from("profiles").update({ config: cfg, updated_at: new Date().toISOString() }).eq("slug", slug);
      if (ue) throw ue;
      setMsg(successMsg);
      await refresh();
    } catch (e: any) {
      setMsg(`Failed: ${e?.message ?? e}`);
    } finally {
      setBusy(false);
    }
  }

  async function addSingle() {
    if (!selected || !single.trim()) return;
    const dom = single.trim().toLowerCase();
    if (!/^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(dom)) { setMsg(`"${dom}" doesn't look like a domain.`); return; }
    if (pool.some(d => d.domain.toLowerCase() === dom)) { setMsg(`${dom} is already in the pool.`); return; }
    const next = [...pool, freshEntry(dom)];
    await patchProfilePool(selected.slug, next, `Queued ${dom} for provisioning. The autoprovision worker will publish DNS + verify within ~10 min.`);
    setSingle("");
  }

  async function addBulk() {
    if (!selected) return;
    const lines = bulk.split(/[\n,]+/).map(l => l.trim().toLowerCase()).filter(Boolean);
    const valid = lines.filter(l => /^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(l));
    const fresh = valid.filter(d => !pool.some(p => p.domain.toLowerCase() === d));
    if (!fresh.length) { setMsg("Nothing new to add — all entries are already in the pool or invalid."); return; }
    const next = [...pool, ...fresh.map(freshEntry)];
    await patchProfilePool(selected.slug, next, `Queued ${fresh.length} subdomains. Autoprovision worker will pick them up on next tick.`);
    setBulk("");
  }

  async function removeOne(dom: string) {
    if (!selected) return;
    if (!confirm(`Remove ${dom} from the pool? Sends already in flight from this subdomain will complete; future sends will rotate to the others.`)) return;
    const next = pool.filter(d => d.domain.toLowerCase() !== dom.toLowerCase());
    await patchProfilePool(selected.slug, next, `Removed ${dom}.`);
  }

  async function bulkSuggest() {
    if (!selected) return;
    const root = (selected.config?.relay?.from_domains?.[0]?.domain ?? "").toLowerCase().split(".").slice(1).join(".")
      || (selected.config?.brand?.site ?? "").toLowerCase()
      || "aureonglobal.de";
    const prefixes = ["outreach", "team", "hi", "desk", "connect", "news", "partners", "hub", "send", "pulse"];
    const fresh = prefixes
      .map(pref => `${pref}.${root}`)
      .filter(d => !pool.some(p => p.domain.toLowerCase() === d));
    setBulk(fresh.join("\n"));
  }

  if (!isConfigured()) {
    return (<><h1 className="page-title">Domains</h1>
      <EmptyState variant="not-connected"
                  title="Configure Supabase first"
                  message="Domain pools live in profiles.config.relay.from_domains[] on Supabase."
                  hint="Settings → Cross-PC sync → paste URL + anon key." /></>);
  }
  if (!loaded) return (<><h1 className="page-title">Domains</h1><EmptyState variant="loading" /></>);
  if (!profiles.length) {
    return (<><h1 className="page-title">Domains</h1>
      <EmptyState variant="no-data"
                  title="No client profiles yet"
                  message="Create a profile first under Profiles → New client profile."
                  hint="Each profile owns its own pool of sending subdomains." /></>);
  }

  return (
    <>
      <div className="row justify" style={{ alignItems: "center", marginBottom: 8 }}>
        <h1 className="page-title" style={{ margin: 0 }}>Sending domains</h1>
        <div className="row gap-2">
          <select value={selectedSlug} onChange={e => setSelectedSlug(e.target.value)}>
            {profiles.map(p => <option key={p.slug} value={p.slug}>{p.name}</option>)}
          </select>
          <button onClick={refresh} title="Refresh"><RefreshCw size={14} /></button>
        </div>
      </div>
      <p className="page-sub">
        Each client owns a pool of sending subdomains. Each one warms independently; the rotation picks whichever has the most headroom today.
        Add subdomains here — the autoprovision worker runs every 10 min, calls Resend to register the domain, pushes DKIM/SPF/DMARC to Hostinger, and stamps <code>verified_at</code> once Resend confirms.
      </p>

      {/* Bulk add */}
      <div className="card" style={{ marginBottom: 16 }}>
        <div className="row justify" style={{ alignItems: "flex-start" }}>
          <div>
            <h3 style={{ marginTop: 0 }}>Bulk add</h3>
            <p className="page-sub" style={{ marginTop: 0 }}>Paste one subdomain per line (or comma-separated). The worker provisions them in order.</p>
          </div>
          <button onClick={bulkSuggest} disabled={busy}>Suggest 10 standard names</button>
        </div>
        <textarea
          rows={6}
          value={bulk}
          onChange={e => setBulk(e.target.value)}
          placeholder={"outreach.aureonglobal.de\nteam.aureonglobal.de\nhi.aureonglobal.de"}
          style={{ width: "100%", fontFamily: "var(--mono)", fontSize: 13, padding: 10 }}
        />
        <div className="row justify" style={{ marginTop: 8 }}>
          <div style={{ fontSize: 12, color: "var(--fg-2)" }}>
            {bulk ? `${bulk.split(/[\n,]+/).filter(l => l.trim()).length} candidate(s)` : ""}
          </div>
          <button className="primary" disabled={busy || !bulk.trim()} onClick={addBulk}>
            <Plus size={14} /> Queue all
          </button>
        </div>
      </div>

      {/* Single add */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Add one</h3>
        <div className="row gap-2" style={{ alignItems: "center" }}>
          <input
            value={single}
            onChange={e => setSingle(e.target.value)}
            placeholder="outreach.aureonglobal.de"
            style={{ flex: 1 }}
          />
          <button className="primary" disabled={busy || !single.trim()} onClick={addSingle}>
            <Plus size={14} /> Add
          </button>
        </div>
      </div>

      {msg && (
        <div className="card" style={{ marginBottom: 16, background: msg.startsWith("Failed") ? "rgba(248,113,113,0.08)" : "rgba(163,230,53,0.06)" }}>
          {msg}
        </div>
      )}

      {/* Pool table */}
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Pool — {pool.length} subdomain{pool.length === 1 ? "" : "s"}</h3>
        {!pool.length ? (
          <div style={{ color: "var(--fg-2)", padding: 12 }}>
            No subdomains in this pool yet. Add one above to start warming.
          </div>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Domain</th><th>Status</th><th>Day</th><th>Today (sent / ceiling)</th><th>Bounce 7d</th><th>Reputation</th><th></th>
              </tr>
            </thead>
            <tbody>
              {pool.map(d => {
                const w = d.warmup || {};
                const day = w.current_day ?? 0;
                const ceiling = w.max_daily_sends ?? 90;
                const sentToday = sendsByDomainToday.get(d.domain.toLowerCase()) || 0;
                const bounce = w.reputation?.bounce_rate_7d ?? 0;
                const bAlert = bounce > 0.05;
                return (
                  <tr key={d.domain}>
                    <td style={{ fontFamily: "var(--mono)" }}>{d.domain}</td>
                    <td>
                      {d.verified_at
                        ? <span className="pill green"><ShieldCheck size={11} style={{verticalAlign:"-1px"}} /> verified</span>
                        : d.resend_domain_id
                          ? <span className="pill amber">awaiting verify</span>
                          : <span className="pill"><AlertCircle size={11} style={{verticalAlign:"-1px"}} /> queued</span>}
                    </td>
                    <td>{day}</td>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span>{sentToday} / {ceiling}</span>
                        <div style={{ height: 6, width: 120, background: "rgba(255,255,255,0.05)", borderRadius: 3, overflow: "hidden" }}>
                          <div style={{ height: "100%", width: `${Math.min(100, (sentToday / Math.max(ceiling, 1)) * 100).toFixed(1)}%`,
                                        background: "var(--accent-cyan)", opacity: 0.7 }} />
                        </div>
                      </div>
                    </td>
                    <td style={{ color: bAlert ? "var(--accent-red)" : undefined }}>
                      {(bounce * 100).toFixed(2)}%
                    </td>
                    <td>
                      {bAlert
                        ? <span className="pill red">over limit</span>
                        : w.reputation?.delivered_7d === 0 && day === 0
                          ? <span className="pill">new</span>
                          : <span className="pill green">ok</span>}
                    </td>
                    <td>
                      <button onClick={() => removeOne(d.domain)} disabled={busy}
                              style={{ color: "var(--accent-red)" }}
                              title="Remove from pool (won't undo DNS — handle in Hostinger separately)">
                        <Trash2 size={13} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="card" style={{ marginTop: 16, background: "rgba(34,211,238,0.04)", borderColor: "rgba(34,211,238,0.2)" }}>
        <div className="row" style={{ alignItems: "flex-start", gap: 10 }}>
          <AlertCircle size={16} color="var(--accent-cyan)" />
          <div style={{ fontSize: 13, color: "var(--fg-1)" }}>
            <strong>How autoprovision works.</strong> Once a subdomain is queued in this pool the
            <code>LES-domain-autoprovision</code> scheduled task picks it up on its next tick (~10 min).
            It POSTs the domain to Resend with the full-access API key, gets back the DKIM record,
            pushes DKIM + SPF + DMARC to Hostinger via the DNS API, then polls Resend until verified —
            at which point <code>verified_at</code> is stamped here and the subdomain starts at warmup day 0.
            Required credentials in <code>sequences/hostinger.env</code>:
            <code style={{ marginLeft: 6 }}>RESEND_FULL_ACCESS_API_KEY</code> and
            <code style={{ marginLeft: 6 }}>HOSTINGER_API_TOKEN</code>.
            Without them, queued domains stay <em>queued</em> and you can run
            <code style={{ marginLeft: 4 }}>py sequences/provision_subdomain.py add &lt;profile&gt; &lt;domain&gt;</code> manually.
          </div>
        </div>
      </div>
    </>
  );
}
