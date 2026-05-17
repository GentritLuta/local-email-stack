import { useEffect, useState } from "react";
import { EmptyState } from "../components/EmptyState";
import {
  DbProfile, DbSendLog, DbReply,
  fetchProfiles, fetchSendLog, fetchReplies,
  isConfigured, subscribeToTable,
} from "../lib/supabase";

export function Analytics() {
  const [profiles, setProfiles] = useState<DbProfile[]>([]);
  const [sends, setSends]       = useState<DbSendLog[]>([]);
  const [replies, setReplies]   = useState<DbReply[]>([]);
  const [loaded, setLoaded]     = useState(false);

  async function refresh() {
    if (!isConfigured()) { setLoaded(true); return; }
    const [ps, sl, rp] = await Promise.all([
      fetchProfiles(),
      fetchSendLog(1000),
      fetchReplies(500),
    ]);
    setProfiles(ps); setSends(sl); setReplies(rp);
    setLoaded(true);
  }

  useEffect(() => {
    refresh();
    const u1 = subscribeToTable("send_log", refresh);
    const u2 = subscribeToTable("replies",  refresh);
    return () => { u1(); u2(); };
  }, []);

  if (!isConfigured()) {
    return (<><h1 className="page-title">Analytics</h1>
      <EmptyState variant="not-connected"
                  title="Configure Supabase first"
                  message="Analytics aggregate live data from Supabase."
                  hint="Settings → Cross-PC sync → paste URL + anon key." /></>);
  }
  if (!loaded) return (<><h1 className="page-title">Analytics</h1><EmptyState variant="loading" /></>);

  // Aggregate
  const total      = sends.length;
  const delivered  = sends.filter(s => s.delivered).length;
  const bounced    = sends.filter(s => s.bounced).length;
  const complained = sends.filter(s => s.complained).length;
  const opened     = sends.filter(s => s.opened_at).length;
  const clicked    = sends.filter(s => s.clicked_at).length;
  const realReplies = replies.filter(r => r.class === "reply").length;

  const pct = (n: number) => total === 0 ? "—" : `${(n / total * 100).toFixed(1)}%`;

  // Per-persona breakdown
  const byPersona = new Map<string, { sent: number; delivered: number; bounced: number; replied: number }>();
  for (const s of sends) {
    const k = s.persona_slug || "(none)";
    const row = byPersona.get(k) || { sent: 0, delivered: 0, bounced: 0, replied: 0 };
    row.sent++;
    if (s.delivered) row.delivered++;
    if (s.bounced)   row.bounced++;
    if (s.replied)   row.replied++;
    byPersona.set(k, row);
  }

  return (
    <>
      <h1 className="page-title">Analytics</h1>
      <p className="page-sub">Live cross-PC view of send + reply outcomes. All data from Supabase.</p>

      <div className="grid grid-4" style={{ marginBottom: 16 }}>
        <Kpi label="Total sent"  value={String(total)} />
        <Kpi label="Delivered"   value={pct(delivered)} accent="green" />
        <Kpi label="Bounce rate" value={pct(bounced)} accent={bounced / Math.max(total,1) > 0.05 ? "red" : "green"} sub={`target < 5%`} />
        <Kpi label="Complaint rate" value={pct(complained)} accent={complained / Math.max(total,1) > 0.001 ? "red" : "green"} sub={`target < 0.1%`} />
      </div>

      <div className="grid grid-4" style={{ marginBottom: 16 }}>
        <Kpi label="Opened"  value={pct(opened)}  accent="cyan" />
        <Kpi label="Clicked" value={pct(clicked)} accent="cyan" />
        <Kpi label="Replies" value={String(realReplies)} accent="green" />
        <Kpi label="Reply rate" value={pct(realReplies)} accent="green" />
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h3>Per-persona</h3>
        {byPersona.size === 0 ? (
          <div style={{ color: "var(--fg-2)", padding: 12 }}>No sends yet.</div>
        ) : (
          <table className="tbl">
            <thead><tr><th>Persona</th><th>Sent</th><th>Delivered</th><th>Bounced</th><th>Replied</th><th>Reply rate</th></tr></thead>
            <tbody>
              {[...byPersona.entries()].sort((a, b) => b[1].sent - a[1].sent).map(([slug, r]) => (
                <tr key={slug}>
                  <td><span className="pill">{slug}</span></td>
                  <td>{r.sent}</td>
                  <td>{r.delivered}</td>
                  <td>{r.bounced || "—"}</td>
                  <td>{r.replied || "—"}</td>
                  <td>{r.sent > 0 ? `${(r.replied / r.sent * 100).toFixed(1)}%` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h3>Recent replies (live)</h3>
        {replies.length === 0 ? (
          <div style={{ color: "var(--fg-2)", padding: 12 }}>No replies recorded yet. The IMAP poller writes here.</div>
        ) : (
          <table className="tbl">
            <thead><tr><th>When</th><th>From</th><th>Subject</th><th>Class</th></tr></thead>
            <tbody>
              {replies.slice(0, 30).map(r => (
                <tr key={r.id}>
                  <td style={{ whiteSpace: "nowrap", fontSize: 12 }}>{new Date(r.received_at).toLocaleString()}</td>
                  <td style={{ fontSize: 12 }}>{r.from_addr}</td>
                  <td style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.subject}</td>
                  <td>
                    {r.class === "reply"     ? <span className="pill green">reply</span>
                   : r.class === "bounce"    ? <span className="pill red">bounce</span>
                   : r.class === "complaint" ? <span className="pill red">complaint</span>
                                             : <span className="pill">{r.class}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function Kpi(props: { label: string; value: string; accent?: "green"|"red"|"amber"|"cyan"; sub?: string }) {
  const color = props.accent === "green" ? "var(--accent-lime)"
              : props.accent === "red"   ? "var(--accent-red)"
              : props.accent === "amber" ? "var(--accent-amber)"
              : props.accent === "cyan"  ? "var(--accent-cyan)" : "var(--fg-0)";
  return (
    <div className="card">
      <h3>{props.label}</h3>
      <div className="big" style={{ color }}>{props.value}</div>
      {props.sub && <div className="delta">{props.sub}</div>}
    </div>
  );
}
