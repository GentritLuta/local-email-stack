import { useEffect, useState } from "react";
import { api, NicheSummary, NotConnectedError } from "../lib/api";
import { EmptyState } from "../components/EmptyState";

export function Sourcing() {
  const [niches, setNiches] = useState<NicheSummary[] | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => { api.nichesList().then(setNiches).catch(() => setNiches([])); }, []);

  async function runNiche(slug: string) {
    setMsg(`Triggering ${slug}…`);
    try {
      const res = await fetch("http://127.0.0.1:8086/source/run", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ niche_slug: slug, overrides: {}, auto_enrich: true }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setMsg(`Started job ${data.job_id}.`);
    } catch (e: any) {
      setMsg(`Could not reach sourcing service at 127.0.0.1:8086 — ${e?.message}. Start the stack first.`);
    }
  }

  if (niches === null) return (<><h1 className="page-title">Sourcing</h1><EmptyState variant="loading" /></>);
  return (
    <>
      <h1 className="page-title">Sourcing</h1>
      <p className="page-sub">Trigger niches manually. The pipeline runs them on schedule once active.</p>
      {msg && <div className="card" style={{ marginBottom: 12 }}>{msg}</div>}
      {niches.length === 0 ? (
        <EmptyState variant="not-connected"
                    message="The niches list comes from disk (niches/*.yaml in the stack repo)."
                    hint="Set the Stack repo path in Settings → General once the stack is cloned. The 7 example niches ship with the repo." />
      ) : (
        <div className="card">
          <table className="tbl">
            <thead><tr><th>Niche</th><th>Slug</th><th>Engines</th><th></th></tr></thead>
            <tbody>
              {niches.map(n => (
                <tr key={n.slug}>
                  <td>{n.name}</td>
                  <td><span className="pill">{n.slug}</span></td>
                  <td>{n.engines.map(e => <span key={e} className="pill cyan" style={{ marginRight: 4 }}>{e}</span>)}</td>
                  <td><button className="primary" onClick={() => runNiche(n.slug)}>Run now</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
