import { useEffect, useState } from "react";
import { api, PipelineSnapshot } from "../lib/api";
import { EmptyState } from "../components/EmptyState";

const STAGE_ORDER = ["sourced", "enriched", "queued", "sent", "replied", "bounced"];

export function Pipeline() {
  const [snap, setSnap] = useState<PipelineSnapshot | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const load = () => api.pipelineSnapshot().then(setSnap).catch(() => setSnap(null)).finally(() => setLoaded(true));
    load();
    const i = setInterval(load, 8_000);
    return () => clearInterval(i);
  }, []);

  return (
    <>
      <h1 className="page-title">Pipeline</h1>
      <p className="page-sub">Lead flow from sourcing through reply, end-to-end.</p>
      {!loaded ? <EmptyState variant="loading" /> :
        !snap ? <EmptyState
                  variant="not-connected"
                  message="Pipeline data lives in Postgres on the stack."
                  hint="Once Docker + the stack are running, this view shows live per-stage counts and the latest 50 leads as they move through the funnel." />
        : (
          <>
            <div className="pipeline" style={{ marginBottom: 24 }}>
              {STAGE_ORDER.map((stage, i) => (
                <div key={stage}>
                  <div className="stage">
                    <div className="num">{Intl.NumberFormat().format(snap.by_stage.find(s => s.stage === stage)?.count ?? 0)}</div>
                    <div className="lbl">{stage}</div>
                  </div>
                  {i < STAGE_ORDER.length - 1 && <div className="arrow">→</div>}
                </div>
              ))}
            </div>
            <div className="card">
              <h3>Latest 50 leads</h3>
              {snap.recent_leads.length === 0
                ? <div style={{ color: "var(--fg-2)", padding: 12 }}>No leads in the warehouse yet.</div>
                : (
                  <table className="tbl">
                    <thead><tr><th>Name</th><th>Niche</th><th>Source</th><th>Stage</th><th>Last event</th></tr></thead>
                    <tbody>
                      {snap.recent_leads.map(l => (
                        <tr key={l.id}>
                          <td>{l.display_name}</td>
                          <td><span className="pill cyan">{l.niche_slug}</span></td>
                          <td>{l.source}</td>
                          <td><span className={`pill ${l.stage === "replied" ? "green" : l.stage === "bounced" ? "red" : "cyan"}`}>{l.stage}</span></td>
                          <td>{l.last_event_at ?? ""}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
            </div>
          </>
        )}
    </>
  );
}
