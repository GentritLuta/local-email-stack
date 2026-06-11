// Leads.tsx — per-client lead table with lifecycle status.
//
// For the active profile (set via the sidebar ProfilePicker), shows:
//   - every prospect in that client's bucket
//   - latest lifecycle status derived from send_log + replies + unsubscribe state
//   - categorization columns (audience, geo, tags, quality_score) when enriched
//
// Filters: status, source platform, industry tag, min audience, min quality.
// Sort: created_at desc by default; click headers to re-sort.

import { useEffect, useMemo, useState } from "react";
import { Rocket } from "lucide-react";
import {
  DbProspect, DbSendLog, DbReply, DbSequence,
  fetchProspects, fetchSendLog, fetchReplies, fetchSequences,
  isConfigured, subscribeToTable, getSupabase,
} from "../lib/supabase";
import { getActiveSlug } from "../lib/profiles";
import { EmptyState } from "../components/EmptyState";

// ─── Status derivation ───────────────────────────────────────────────────

type LeadStatus =
  | "untouched" | "sent" | "delivered" | "opened" | "clicked"
  | "replied"   | "bounced" | "complained" | "unsubscribed";

const STATUS_ORDER: LeadStatus[] = [
  "untouched", "sent", "delivered", "opened", "clicked",
  "replied", "bounced", "complained", "unsubscribed",
];

const STATUS_COLOR: Record<LeadStatus, string> = {
  untouched:    "#475569",
  sent:         "#0ea5e9",
  delivered:    "#0284c7",
  opened:       "#10b981",
  clicked:      "#06b6d4",
  replied:      "#16a34a",
  bounced:      "#ef4444",
  complained:   "#f59e0b",
  unsubscribed: "#94a3b8",
};

function deriveStatus(
  p: DbProspect,
  sendsByEmail: Map<string, DbSendLog[]>,
  repliesByEmail: Map<string, DbReply[]>,
): LeadStatus {
  if (p.unsubscribed) return "unsubscribed";

  const sends = sendsByEmail.get(p.email.toLowerCase()) ?? [];
  const replies = repliesByEmail.get(p.email.toLowerCase()) ?? [];
  if (sends.length === 0 && replies.length === 0) return "untouched";

  // Use the latest send as the lifecycle anchor; replies and bounces
  // override it (terminal states).
  if (sends.some(s => s.complained)) return "complained";
  if (sends.some(s => s.bounced))    return "bounced";
  if (replies.some(r => r.class === "reply") || sends.some(s => s.replied))
    return "replied";
  if (sends.some(s => s.clicked_at)) return "clicked";
  if (sends.some(s => s.opened_at))  return "opened";
  if (sends.some(s => s.delivered))  return "delivered";
  return "sent";
}

// ─── Component ───────────────────────────────────────────────────────────

type SortKey = "created" | "name" | "quality" | "audience" | "status";

export function Leads() {
  const [profile, setProfile] = useState<string | null>(getActiveSlug());
  useEffect(() => {
    const h = (e: Event) => setProfile((e as CustomEvent).detail);
    window.addEventListener("active-profile-changed", h);
    return () => window.removeEventListener("active-profile-changed", h);
  }, []);

  const [prospects, setProspects] = useState<DbProspect[] | null>(null);
  const [sends,     setSends]     = useState<DbSendLog[]>([]);
  const [replies,   setReplies]   = useState<DbReply[]>([]);

  async function load() {
    if (!isConfigured() || !profile) { setProspects([]); return; }
    const [pr, sl, rp] = await Promise.all([
      fetchProspects(profile, 10_000),
      fetchSendLog(10_000),
      fetchReplies(2_000),
    ]);
    setProspects(pr); setSends(sl); setReplies(rp);
  }
  useEffect(() => {
    load();
    const subs = [
      subscribeToTable("send_log", load),
      subscribeToTable("replies",  load),
    ];
    return () => subs.forEach(u => u());
  }, [profile]);

  // ─── filters ─────
  const [statusFilter,   setStatusFilter]   = useState<LeadStatus | "all">("all");
  const [platformFilter, setPlatformFilter] = useState<string>("all");
  const [tagFilter,      setTagFilter]      = useState<string>("all");
  const [geoFilter,      setGeoFilter]      = useState<string>("all");
  const [minAudience,    setMinAudience]    = useState<number>(0);
  const [minQuality,     setMinQuality]     = useState<number>(0);
  const [search,         setSearch]         = useState<string>("");

  const [sortKey, setSortKey] = useState<SortKey>("created");
  const [sortDesc, setSortDesc] = useState(true);

  // Sequences for the bulk-enroll dropdown
  const [seqs, setSeqs] = useState<DbSequence[]>([]);
  const [selectedSeq, setSelectedSeq] = useState<string>("");
  const [enrolling, setEnrolling] = useState(false);
  const [enrollMsg, setEnrollMsg] = useState<string | null>(null);
  useEffect(() => { if (profile) fetchSequences(profile).then(s => {
    setSeqs(s);
    if (s.length > 0 && !selectedSeq) setSelectedSeq(s[0].slug);
  }); }, [profile]);

  // Per-email indexes for status derivation
  const sendsByEmail = useMemo(() => {
    const m = new Map<string, DbSendLog[]>();
    for (const s of sends) {
      const k = s.to_addr.toLowerCase();
      const arr = m.get(k) ?? [];
      arr.push(s);
      m.set(k, arr);
    }
    return m;
  }, [sends]);

  const repliesByEmail = useMemo(() => {
    const m = new Map<string, DbReply[]>();
    for (const r of replies) {
      const k = r.from_addr.toLowerCase();
      const arr = m.get(k) ?? [];
      arr.push(r);
      m.set(k, arr);
    }
    return m;
  }, [replies]);

  // Build the displayable rows (prospect + derived status)
  const rows = useMemo(() => {
    if (!prospects) return [];
    return prospects.map(p => ({
      p,
      status: deriveStatus(p, sendsByEmail, repliesByEmail),
    }));
  }, [prospects, sendsByEmail, repliesByEmail]);

  // ─── filtering ─────
  const allTags = useMemo(() => {
    const s = new Set<string>();
    for (const { p } of rows) (p.industry_tags ?? []).forEach(t => s.add(t));
    return [...s].sort();
  }, [rows]);

  const allPlatforms = useMemo(() => {
    const s = new Set<string>();
    for (const { p } of rows) if (p.source_platform) s.add(p.source_platform);
    return [...s].sort();
  }, [rows]);

  const allGeos = useMemo(() => {
    const s = new Set<string>();
    for (const { p } of rows) if (p.geo) s.add(p.geo);
    return [...s].sort();
  }, [rows]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return rows.filter(({ p, status }) => {
      if (statusFilter !== "all" && status !== statusFilter) return false;
      if (platformFilter !== "all" && p.source_platform !== platformFilter) return false;
      if (tagFilter !== "all" && !(p.industry_tags ?? []).includes(tagFilter)) return false;
      if (geoFilter !== "all" && p.geo !== geoFilter) return false;
      if (minAudience > 0 && (p.audience_size ?? 0) < minAudience) return false;
      if (minQuality > 0 && (p.quality_score ?? 0) < minQuality) return false;
      if (q && !((p.email + " " + (p.first_name ?? "") + " " + (p.last_name ?? "") + " " + (p.company ?? "")).toLowerCase().includes(q))) return false;
      return true;
    });
  }, [rows, statusFilter, platformFilter, tagFilter, geoFilter, minAudience, minQuality, search]);

  // ─── sorting ─────
  const sorted = useMemo(() => {
    const arr = [...filtered];
    arr.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "name":
          cmp = ((a.p.first_name ?? "") + (a.p.last_name ?? ""))
                .localeCompare((b.p.first_name ?? "") + (b.p.last_name ?? ""));
          break;
        case "quality":
          cmp = (a.p.quality_score ?? -1) - (b.p.quality_score ?? -1);
          break;
        case "audience":
          cmp = (a.p.audience_size ?? -1) - (b.p.audience_size ?? -1);
          break;
        case "status":
          cmp = STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status);
          break;
        case "created":
        default:
          cmp = a.p.created_at.localeCompare(b.p.created_at);
      }
      return sortDesc ? -cmp : cmp;
    });
    return arr;
  }, [filtered, sortKey, sortDesc]);

  // ─── headline stats ─────
  const stats = useMemo(() => {
    const o: Record<LeadStatus, number> = {
      untouched: 0, sent: 0, delivered: 0, opened: 0, clicked: 0,
      replied: 0, bounced: 0, complained: 0, unsubscribed: 0,
    };
    for (const r of rows) o[r.status]++;
    return o;
  }, [rows]);

  // ─── render ─────
  if (!isConfigured()) {
    return (<><h1 className="page-title">Leads</h1>
      <EmptyState variant="not-connected"
                  title="Configure Supabase first"
                  message="Leads live in Supabase so all PCs see the same pipeline."
                  hint="Settings → Cross-PC sync." /></>);
  }
  if (!profile) {
    return (<><h1 className="page-title">Leads</h1>
      <EmptyState variant="no-data"
                  title="No active profile"
                  message="Pick a client profile from the sidebar dropdown."
                  hint="Top-left of the sidebar." /></>);
  }
  if (prospects === null) {
    return (<><h1 className="page-title">Leads</h1><EmptyState variant="loading" /></>);
  }

  // Bulk enroll the currently-filtered untouched leads into a sequence
  async function enrollFiltered() {
    const s = getSupabase();
    if (!s || !selectedSeq) return;
    const eligible = sorted
      .filter(r => r.status === "untouched" && !r.p.unsubscribed)
      .map(r => r.p);
    if (eligible.length === 0) {
      setEnrollMsg("No untouched leads in current filter.");
      setTimeout(() => setEnrollMsg(null), 3000);
      return;
    }
    setEnrolling(true);
    try {
      const { data: seqRows, error: e1 } = await s.from("sequences")
        .select("id").eq("slug", selectedSeq).limit(1);
      if (e1 || !seqRows || seqRows.length === 0) throw new Error("sequence not found");
      const seq_id = seqRows[0].id;
      const now = new Date().toISOString();
      const runs = eligible.map(p => ({
        sequence_id: seq_id, prospect_id: p.id,
        status: "queued", current_step: 1, next_send_at: now,
      }));
      // Insert in chunks of 500 to avoid PostgREST payload limits
      let inserted = 0;
      for (let i = 0; i < runs.length; i += 500) {
        const chunk = runs.slice(i, i + 500);
        const { error } = await s.from("runs")
          .upsert(chunk, { onConflict: "sequence_id,prospect_id", ignoreDuplicates: true });
        if (error) throw error;
        inserted += chunk.length;
      }
      setEnrollMsg(`Enrolled ${inserted} lead${inserted===1?"":"s"} in "${selectedSeq}". Sequence-runner picks them up on its next tick.`);
      setTimeout(() => setEnrollMsg(null), 7000);
    } catch (e: any) {
      setEnrollMsg("error: " + (e?.message ?? e));
    } finally {
      setEnrolling(false);
    }
  }

  return (
    <>
      <div className="row justify" style={{ alignItems: "flex-start" }}>
        <div>
          <h1 className="page-title">Leads — {profile}</h1>
          <p className="page-sub">
            Every prospect in this client&apos;s bucket with their lifecycle status
            (sent / opened / replied / bounced / unsubscribed) and enriched
            categorization. {rows.length.toLocaleString()} total ·
            {" "}<b>{stats.replied}</b> replied · <b>{stats.bounced}</b> bounced ·
            {" "}<b>{stats.unsubscribed}</b> unsubscribed.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <select value={selectedSeq} onChange={e => setSelectedSeq(e.target.value)}
                  style={{ minWidth: 200 }}>
            <option value="">— sequence —</option>
            {seqs.map(s => <option key={s.slug} value={s.slug}>{s.name || s.slug}</option>)}
          </select>
          <button className="primary" disabled={enrolling || !selectedSeq}
                  onClick={enrollFiltered}
                  style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <Rocket size={14} /> {enrolling ? "enrolling…" : "Enroll filtered into sequence"}
          </button>
        </div>
      </div>
      {enrollMsg && (
        <div style={{
          marginBottom: 8, padding: "8px 12px", borderRadius: 6,
          background: enrollMsg.startsWith("error") ? "rgba(239,68,68,0.1)" : "rgba(34,197,94,0.1)",
          color: enrollMsg.startsWith("error") ? "#ef4444" : "#22c55e",
          fontSize: 13,
        }}>{enrollMsg}</div>
      )}

      {/* Status pill bar */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, margin: "12px 0 16px" }}>
        <StatusPill label="all"        n={rows.length}              active={statusFilter==="all"}        onClick={() => setStatusFilter("all")} />
        {STATUS_ORDER.map(st => (
          <StatusPill key={st} label={st} n={stats[st]}
                      active={statusFilter===st}
                      color={STATUS_COLOR[st]}
                      onClick={() => setStatusFilter(st)} />
        ))}
      </div>

      {/* Filter row */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr 1fr 1fr", gap: 8, marginBottom: 12 }}>
        <input placeholder="search email / name / company"
               value={search} onChange={e => setSearch(e.target.value)} />
        <select value={platformFilter} onChange={e => setPlatformFilter(e.target.value)}>
          <option value="all">all platforms</option>
          {allPlatforms.map(p => <option key={p} value={p}>{p}</option>)}
        </select>
        <select value={tagFilter} onChange={e => setTagFilter(e.target.value)}>
          <option value="all">all industries</option>
          {allTags.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={geoFilter} onChange={e => setGeoFilter(e.target.value)}>
          <option value="all">all geos</option>
          {allGeos.map(g => <option key={g} value={g}>{g}</option>)}
        </select>
        <input type="number" placeholder="min audience" min={0}
               value={minAudience || ""} onChange={e => setMinAudience(+e.target.value || 0)} />
        <input type="number" placeholder="min quality (0-100)" min={0} max={100}
               value={minQuality || ""} onChange={e => setMinQuality(+e.target.value || 0)} />
      </div>

      {/* Lead table */}
      <div style={{ overflow: "auto", border: "var(--border)", borderRadius: 8 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ background: "var(--bg-2)" }}>
              <Th label="Email"     onClick={() => toggleSort("name")} active={sortKey==="name"} />
              <Th label="Name / company" />
              <Th label="Platform" />
              <Th label="Audience" onClick={() => toggleSort("audience")} active={sortKey==="audience"} />
              <Th label="Geo" />
              <Th label="Tags" />
              <Th label="Quality"  onClick={() => toggleSort("quality")}  active={sortKey==="quality"} />
              <Th label="Status"   onClick={() => toggleSort("status")}   active={sortKey==="status"} />
              <Th label="Added"    onClick={() => toggleSort("created")}  active={sortKey==="created"} />
            </tr>
          </thead>
          <tbody>
            {sorted.slice(0, 1000).map(({ p, status }) => (
              <tr key={p.id} style={{ borderTop: "var(--border)" }}>
                <td style={cell}>
                  <a href={`mailto:${p.email}`} style={{ color: "var(--accent-cyan)" }}>{p.email}</a>
                </td>
                <td style={cell}>
                  <div style={{ fontWeight: 500 }}>
                    {[p.first_name, p.last_name].filter(Boolean).join(" ") || "—"}
                  </div>
                  {p.company && <div style={{ color: "var(--fg-2)", fontSize: 11 }}>{p.company}</div>}
                </td>
                <td style={cell}>{p.source_platform ?? "—"}</td>
                <td style={{...cell, textAlign: "right"}}>
                  {p.audience_size ? p.audience_size.toLocaleString() : "—"}
                </td>
                <td style={cell}>{p.geo ?? "—"}</td>
                <td style={cell}>
                  {(p.industry_tags ?? []).map(t => (
                    <span key={t} className="pill"
                          style={{ fontSize: 10, marginRight: 4 }}>{t}</span>
                  ))}
                </td>
                <td style={{...cell, textAlign: "right"}}>
                  {p.quality_score != null ? p.quality_score : "—"}
                </td>
                <td style={cell}>
                  <span className="pill" style={{
                    background: STATUS_COLOR[status] + "22",
                    color: STATUS_COLOR[status],
                    fontWeight: 600,
                  }}>{status}</span>
                </td>
                <td style={cell}>
                  {new Date(p.created_at).toISOString().slice(0, 10)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sorted.length > 1000 && (
        <div style={{ color: "var(--fg-2)", fontSize: 12, marginTop: 8 }}>
          Showing first 1,000 of {sorted.length.toLocaleString()} matches. Narrow filters to see more.
        </div>
      )}
    </>
  );

  function toggleSort(k: SortKey) {
    if (sortKey === k) setSortDesc(!sortDesc);
    else { setSortKey(k); setSortDesc(true); }
  }
}

// ─── Small components ────────────────────────────────────────────────────

const cell: React.CSSProperties = { padding: "6px 8px", verticalAlign: "top" };

function Th(props: { label: string; onClick?: () => void; active?: boolean }) {
  return (
    <th onClick={props.onClick}
        style={{
          padding: "8px",
          textAlign: "left",
          fontSize: 11,
          textTransform: "uppercase",
          letterSpacing: 0.5,
          cursor: props.onClick ? "pointer" : undefined,
          color: props.active ? "var(--accent-cyan)" : "var(--fg-2)",
          fontWeight: 600,
        }}>
      {props.label}
    </th>
  );
}

function StatusPill(props: {
  label: string; n: number; active: boolean;
  onClick: () => void; color?: string;
}) {
  const c = props.color ?? "#475569";
  return (
    <button onClick={props.onClick}
            style={{
              padding: "6px 10px",
              border: props.active ? `1px solid ${c}` : "var(--border)",
              background: props.active ? c + "22" : "var(--bg-1)",
              color: props.active ? c : "var(--fg-1)",
              borderRadius: 999, cursor: "pointer", fontSize: 12,
              fontWeight: props.active ? 600 : 400,
            }}>
      {props.label} · {props.n.toLocaleString()}
    </button>
  );
}
