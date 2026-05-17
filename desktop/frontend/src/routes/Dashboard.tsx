import { useEffect, useState } from "react";
import { Play, Square, RefreshCw, ExternalLink } from "lucide-react";
import { api, DashboardMetrics, ServiceStatus, NotConnectedError } from "../lib/api";
import { EmptyState } from "../components/EmptyState";

export function Dashboard() {
  const [m, setM] = useState<DashboardMetrics | null>(null);
  const [services, setServices] = useState<ServiceStatus[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  async function refresh() {
    try {
      const [metrics, status] = await Promise.all([
        api.dashboardMetrics().catch(() => null),
        api.stackStatus().catch(() => [] as ServiceStatus[]),
      ]);
      setM(metrics);
      setServices(status);
    } finally {
      setLoaded(true);
    }
  }

  useEffect(() => {
    refresh();
    const i = setInterval(refresh, 10_000);
    return () => clearInterval(i);
  }, []);

  const stackDown = services.length === 0;
  const noMetrics = m === null;

  return (
    <>
      <div className="row justify">
        <div>
          <h1 className="page-title">Overview</h1>
          <p className="page-sub">Live view of your self-hosted cold-email stack.</p>
        </div>
        <div className="row gap-2">
          <button onClick={refresh}><RefreshCw size={14} /> Refresh</button>
          <button className="primary" disabled={busy !== null} onClick={async () => {
            setBusy("up");
            try { await api.stackUp(); await refresh(); }
            catch (e) { if (e instanceof NotConnectedError) alert("Need the native Tauri build + Docker installed."); }
            finally { setBusy(null); }
          }}><Play size={14} /> Start stack</button>
          <button className="danger" disabled={busy !== null} onClick={async () => {
            setBusy("down");
            try { await api.stackDown(); await refresh(); }
            catch (e) { if (e instanceof NotConnectedError) alert("Need the native Tauri build + Docker installed."); }
            finally { setBusy(null); }
          }}><Square size={14} /> Stop stack</button>
        </div>
      </div>

      {!loaded ? (
        <EmptyState variant="loading" />
      ) : stackDown && noMetrics ? (
        <EmptyState
          variant="not-connected"
          message="Docker stack isn't running, or this build can't reach it."
          hint="Install Docker Desktop + run docker compose up in the stack repo. From dev browser mode you'll still see the Sequences page with real .eml send results."
        />
      ) : (
        <>
          <div className="grid grid-4" style={{ marginBottom: 16 }}>
            <Kpi label="Services healthy"
                 value={m ? `${m.services_healthy}/${m.services_total}` : "—"}
                 accent={m && m.services_total > 0 && m.services_healthy === m.services_total ? "green" : "amber"} />
            <Kpi label="Leads sourced"   value={fmt(m?.leads_raw_total)} />
            <Kpi label="Leads enriched"  value={fmt(m?.leads_enriched_total)} />
            <Kpi label="Queued to send"  value={fmt(m?.leads_queued)} />
          </div>
          <div className="grid grid-4" style={{ marginBottom: 16 }}>
            <Kpi label="Sent today"    value={fmt(m?.leads_sent_today)} accent="cyan" />
            <Kpi label="Replies today" value={fmt(m?.replies_today)} accent="green" />
            <Kpi label="Bounces today" value={fmt(m?.bounces_today)}
                 accent={m?.bounces_today && m.bounces_today > 10 ? "red" : undefined} />
            <Kpi label="Reply rate 7d" value={pct(m?.avg_reply_rate_7d)} accent="green" />
          </div>

          <div className="grid grid-2">
            <div className="card">
              <h3>Services</h3>
              {services.length === 0 ? (
                <div style={{ color: "var(--fg-2)", padding: "20px 0" }}>
                  No services. Click "Start stack" once Docker is installed.
                </div>
              ) : (
                <table className="tbl">
                  <thead><tr><th>Name</th><th>State</th><th>Health</th><th>Uptime</th></tr></thead>
                  <tbody>
                    {services.map((s) => (
                      <tr key={s.name}>
                        <td>{s.name}</td>
                        <td><span className={`pill ${s.state === "running" ? "green" : "red"}`}>{s.state}</span></td>
                        <td>{s.health ? <span className={`pill ${s.health === "healthy" ? "green" : "amber"}`}>{s.health}</span> : <span className="pill">–</span>}</td>
                        <td>{s.uptime ?? ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div className="card">
              <h3>Quick actions</h3>
              <div className="row gap-2" style={{ flexWrap: "wrap" }}>
                <button onClick={() => api.openInBrowser("https://n8n.insaneaiautomation.xyz")}><ExternalLink size={14} /> Open n8n</button>
                <button onClick={() => api.openInBrowser("http://127.0.0.1:8080")}><ExternalLink size={14} /> NocoDB</button>
                <button onClick={() => api.openInBrowser("http://127.0.0.1:3000")}><ExternalLink size={14} /> Twenty CRM</button>
                <button onClick={() => api.openInBrowser("http://127.0.0.1:3001")}><ExternalLink size={14} /> Grafana</button>
              </div>
              <h3 style={{ marginTop: 16 }}>Warmup</h3>
              <div className="row justify">
                <div>
                  <div className="big">{pct(m?.warmup_spam_rate_7d)}</div>
                  <div className="delta">spam-folder rate (7d) — target &lt; 2%</div>
                </div>
                <div>
                  <div className="big">{fmt(m?.active_personas)}</div>
                  <div className="delta">active personas</div>
                </div>
                <div>
                  <div className="big">{fmt(m?.active_niches)}</div>
                  <div className="delta">active niches</div>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}

function Kpi(props: { label: string; value: string; accent?: "green" | "red" | "amber" | "cyan" }) {
  return (
    <div className="card">
      <h3>{props.label}</h3>
      <div className="big" style={{ color: props.accent === "green" ? "var(--accent-lime)" :
                                          props.accent === "red"   ? "var(--accent-red)" :
                                          props.accent === "amber" ? "var(--accent-amber)" :
                                          props.accent === "cyan"  ? "var(--accent-cyan)" :
                                                                     "var(--fg-0)" }}>
        {props.value}
      </div>
    </div>
  );
}

function fmt(n: number | undefined | null): string {
  if (n === undefined || n === null) return "—";
  return Intl.NumberFormat().format(n);
}
function pct(n: number | undefined | null): string {
  if (n === undefined || n === null) return "—";
  return (n * 100).toFixed(1) + "%";
}
