import { useEffect, useState } from "react";
import { api, BanditRow } from "../lib/api";
import { EmptyState } from "../components/EmptyState";

export function Bandit() {
  const [rows, setRows] = useState<BanditRow[] | null>(null);
  const [kind, setKind] = useState<string>("subject");
  useEffect(() => { api.banditLeaderboard(100).then(setRows).catch(() => setRows([])); }, []);
  if (rows === null) return (<><h1 className="page-title">Bandit</h1><EmptyState variant="loading" /></>);
  const filtered = rows.filter(r => r.kind === kind);
  return (
    <>
      <h1 className="page-title">Bandit leaderboard</h1>
      <p className="page-sub">Thompson sampling chooses the winning variant for every send. The leaderboard shows what's converting.</p>
      <div className="toolbar">
        <select value={kind} onChange={e => setKind(e.target.value)}>
          <option value="subject">Subjects</option>
          <option value="opening">Openings</option>
          <option value="cta">CTAs</option>
        </select>
      </div>
      {rows.length === 0 ? (
        <EmptyState variant="not-connected"
                    message="Bandit state lives in the variants table in Postgres."
                    hint="Once the stack is running and you've sent enough variants to cross the impression threshold, ranked results appear here." />
      ) : filtered.length === 0 ? (
        <div className="card" style={{ color: "var(--fg-2)" }}>No variants in this category yet.</div>
      ) : (
        <div className="card">
          <table className="tbl">
            <thead><tr><th>Persona</th><th>Variant</th><th>Sent</th><th>Replied</th><th>Rate</th></tr></thead>
            <tbody>
              {filtered.map((r, i) => (
                <tr key={i}>
                  <td><span className="pill">{r.persona}</span></td>
                  <td style={{ maxWidth: 480, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.text}</td>
                  <td>{r.impressions}</td><td>{r.rewards}</td>
                  <td><span className={`pill ${r.rate > 0.05 ? "green" : r.rate > 0.02 ? "cyan" : ""}`}>{(r.rate * 100).toFixed(1)}%</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
