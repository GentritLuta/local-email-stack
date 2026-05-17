import { useEffect, useState } from "react";
import { DbReply, fetchReplies, isConfigured, subscribeToTable } from "../lib/supabase";
import { EmptyState } from "../components/EmptyState";
import { notifyReply } from "../lib/notify";

export function Replies() {
  const [items, setItems]       = useState<DbReply[] | null>(null);
  const [filter, setFilter]     = useState<string>("all");
  const [selected, setSelected] = useState<DbReply | null>(null);

  async function load(previousLen?: number) {
    if (!isConfigured()) { setItems([]); return; }
    const fresh = await fetchReplies(200);
    if (typeof previousLen === "number" && fresh.length > previousLen) {
      const newOnes = fresh.slice(0, fresh.length - previousLen).filter(r => r.class === "reply");
      for (const r of newOnes) {
        notifyReply({ from: r.from_addr, subject: r.subject ?? "(no subject)", sequence: "aureon",
                      snippet: (r.body_snippet ?? "").slice(0, 200) });
      }
    }
    setItems(fresh);
  }

  useEffect(() => {
    load();
    const u = subscribeToTable("replies", () => load(items?.length));
    return () => { u(); };
  }, []);

  if (!isConfigured()) {
    return (<><h1 className="page-title">Replies</h1>
      <EmptyState variant="not-connected"
                  title="Configure Supabase first"
                  message="Replies live in Supabase so both PCs see the same inbox."
                  hint="Settings → Cross-PC sync. Replies are populated by sequences/imap-poll.py (polling info@aureonglobal.de) and by the Resend webhook." /></>);
  }
  if (items === null) return (<><h1 className="page-title">Replies</h1><EmptyState variant="loading" /></>);

  const filtered = items.filter(i => filter === "all" || i.class === filter);

  return (
    <>
      <h1 className="page-title">Replies inbox</h1>
      <p className="page-sub">Real human replies + bounces + complaints — pulled by IMAP poller from <code>info@aureonglobal.de</code> + Resend webhook. Live across PCs.</p>

      {items.length === 0 ? (
        <EmptyState variant="no-data"
                    title="No inbound mail yet"
                    message="Replies land here as soon as the IMAP poller picks them up."
                    hint="Run `py sequences/imap-poll.py once` to ingest now, or schedule it." />
      ) : (
        <>
          <div className="toolbar">
            <select value={filter} onChange={e => setFilter(e.target.value)}>
              <option value="all">All</option><option value="reply">Replies</option>
              <option value="bounce">Bounces</option><option value="complaint">Complaints</option>
              <option value="unrelated">Unrelated</option>
            </select>
            <span style={{ color: "#94a3b8", marginLeft: "auto" }}>{filtered.length} of {items.length}</span>
          </div>
          <div className="grid grid-2" style={{ gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <div className="card" style={{ maxHeight: "calc(100vh - 280px)", overflow: "auto" }}>
              <table className="tbl">
                <thead><tr><th>When</th><th>From</th><th>Subject</th><th>Class</th></tr></thead>
                <tbody>
                  {filtered.map(r => (
                    <tr key={r.id} onClick={() => setSelected(r)}
                        style={{ cursor: "pointer", background: selected?.id === r.id ? "rgba(34,211,238,0.06)" : undefined }}>
                      <td style={{ whiteSpace: "nowrap", fontSize: 12 }}>{new Date(r.received_at).toLocaleString()}</td>
                      <td style={{ fontSize: 12 }}>{r.from_addr}</td>
                      <td style={{ maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.subject}</td>
                      <td><span className={`pill ${classPill(r.class)}`}>{r.class}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="card">
              {selected ? (
                <>
                  <h3>{selected.subject}</h3>
                  <div className="page-sub">From {selected.from_addr} → {selected.to_addr} ·{" "}
                    {new Date(selected.received_at).toLocaleString()} ·{" "}
                    <span className={`pill ${classPill(selected.class)}`}>{selected.class}</span>
                    {selected.run_id && <> · run <code style={{ fontSize: 11 }}>{selected.run_id.slice(0, 8)}…</code></>}
                  </div>
                  <pre style={{ background: "#000", padding: 12, borderRadius: 8, fontFamily: "var(--mono)", fontSize: 12,
                                color: "#cbd5e1", whiteSpace: "pre-wrap", marginTop: 8 }}>{selected.body_snippet ?? ""}</pre>
                </>
              ) : <div style={{ color: "#64748b" }}>Select a message.</div>}
            </div>
          </div>
        </>
      )}
    </>
  );
}

function classPill(c: string) {
  return { reply: "green", bounce: "amber", complaint: "red", unrelated: "" }[c] ?? "";
}
