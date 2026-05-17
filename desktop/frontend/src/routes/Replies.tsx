import { useEffect, useState } from "react";
import { api, InboundReply } from "../lib/api";
import { EmptyState } from "../components/EmptyState";

export function Replies() {
  const [items, setItems] = useState<InboundReply[] | null>(null);
  const [filter, setFilter] = useState<string>("all");
  const [selected, setSelected] = useState<InboundReply | null>(null);
  useEffect(() => {
    const load = () => api.repliesRecent(200).then(setItems).catch(() => setItems([]));
    load();
    const i = setInterval(load, 15_000);
    return () => clearInterval(i);
  }, []);
  if (items === null) return (<><h1 className="page-title">Replies</h1><EmptyState variant="loading" /></>);
  const filtered = items.filter(i => filter === "all" || i.class === filter);
  return (
    <>
      <h1 className="page-title">Replies inbox</h1>
      <p className="page-sub">Cloudflare Email Worker routes every inbound mail here. Classification + thread match are automatic.</p>
      {items.length === 0 ? (
        <EmptyState variant="not-connected"
                    title="No inbound mail yet"
                    message="Replies, bounces, and complaints land here as soon as the Cloudflare Email Worker is deployed."
                    hint="Deploy via scripts/cf-bootstrap.sh after Postal + DNS are configured. The worker POSTs each message to a webhook in n8n; n8n writes it to the inbound_mail table." />
      ) : (
        <>
          <div className="toolbar">
            <select value={filter} onChange={e => setFilter(e.target.value)}>
              <option value="all">All</option><option value="reply">Replies</option>
              <option value="bounce">Bounces</option><option value="complaint">Complaints</option>
              <option value="unrelated">Unrelated</option>
            </select>
            <span style={{ color: "#94a3b8", marginLeft: "auto" }}>{filtered.length} messages</span>
          </div>
          <div className="grid grid-2" style={{ gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <div className="card" style={{ maxHeight: "calc(100vh - 280px)", overflow: "auto" }}>
              <table className="tbl">
                <thead><tr><th>When</th><th>From</th><th>Subject</th><th>Class</th></tr></thead>
                <tbody>
                  {filtered.map(r => (
                    <tr key={r.id} onClick={() => setSelected(r)} style={{ cursor: "pointer", background: selected?.id === r.id ? "rgba(34,211,238,0.06)" : undefined }}>
                      <td style={{ whiteSpace: "nowrap" }}>{r.received_at}</td>
                      <td>{r.from_addr}</td><td>{r.subject}</td>
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
                  <div className="page-sub">From {selected.from_addr} → {selected.to_addr} · {selected.received_at} · <span className={`pill ${classPill(selected.class)}`}>{selected.class}</span></div>
                  <pre style={{ background: "#000", padding: 12, borderRadius: 8, fontFamily: "var(--mono)", fontSize: 12, color: "#cbd5e1", whiteSpace: "pre-wrap" }}>{selected.snippet}</pre>
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
