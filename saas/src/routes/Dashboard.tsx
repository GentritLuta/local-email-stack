import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getCampaignMetrics } from "../lib/api";

export default function Dashboard() {
  const { slug } = useParams();
  const [m, setM] = useState<{ leads: number; replied_runs: number; replies: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) return;
    let alive = true;
    async function tick() {
      try {
        const data = await getCampaignMetrics(slug!);
        if (alive) { setM(data); setErr(null); }
      } catch (e: any) {
        if (alive) setErr(e?.message || String(e));
      }
    }
    tick();
    const iv = setInterval(tick, 15000);
    return () => { alive = false; clearInterval(iv); };
  }, [slug]);

  return (
    <div className="card">
      <h2>Your campaign</h2>
      <p className="sub">Live numbers for {slug}. Updates every 15 seconds.</p>
      {err && <div className="banner">{err}</div>}
      <div className="metrics">
        <div className="metric"><div className="big">{m?.leads ?? "—"}</div><div className="lbl">Active leads</div></div>
        <div className="metric"><div className="big">{m?.replies ?? "—"}</div><div className="lbl">Replies</div></div>
        <div className="metric"><div className="big">{m?.replied_runs ?? "—"}</div><div className="lbl">Conversations</div></div>
      </div>
    </div>
  );
}
