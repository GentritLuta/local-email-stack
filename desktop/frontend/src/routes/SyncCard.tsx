import { useEffect, useState } from "react";
import { Save, Wifi, WifiOff, Database } from "lucide-react";
import {
  fetchProfiles, fetchRuns, fetchSendLog,
  getSupabaseConfig, isConfigured, saveSupabaseConfig,
} from "../lib/supabase";

export function SyncCard() {
  const [{ url, anon }, setCfg] = useState(getSupabaseConfig());
  const [connected, setConnected] = useState(false);
  const [counts, setCounts] = useState<{ profiles: number; runs: number; sends: number } | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function probe() {
    if (!isConfigured()) { setConnected(false); setCounts(null); return; }
    try {
      const [profiles, runs, sends] = await Promise.all([
        fetchProfiles(), fetchRuns({ limit: 1000 }), fetchSendLog(1000),
      ]);
      setCounts({ profiles: profiles.length, runs: runs.length, sends: sends.length });
      setConnected(true);
    } catch (e: any) {
      setConnected(false);
      setMsg(`Probe failed: ${e?.message ?? e}`);
    }
  }
  useEffect(() => { probe(); }, []);

  async function save() {
    if (!url || !anon) { setMsg("Both URL and anon key are required."); return; }
    saveSupabaseConfig(url, anon);
    setMsg("Saved. Probing…");
    await probe();
    setMsg("Connected. Cross-PC sync is live.");
  }

  return (
    <div className="card">
      <h3>Cross-PC sync (Supabase)</h3>
      <p className="page-sub" style={{ marginTop: 0 }}>
        Paste your Supabase project URL + anon key. Both PCs running this app pointed at the same project will see the same sequences, runs, sends, and replies in real time.
      </p>

      <div className="row gap-2" style={{ marginBottom: 12 }}>
        {connected
          ? <span className="pill green"><Wifi size={11} style={{ verticalAlign: "-1px" }} /> connected</span>
          : isConfigured()
            ? <span className="pill amber"><WifiOff size={11} style={{ verticalAlign: "-1px" }} /> configured · not reachable</span>
            : <span className="pill"><Database size={11} style={{ verticalAlign: "-1px" }} /> not configured</span>}
        {counts && (
          <>
            <span className="pill">{counts.profiles} profiles</span>
            <span className="pill">{counts.runs} runs</span>
            <span className="pill">{counts.sends} sends</span>
          </>
        )}
        <span style={{ marginLeft: "auto", color: "var(--accent-lime)" }}>{msg}</span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: 10, alignItems: "center" }}>
        <label>SUPABASE_URL</label>
        <input type="text" value={url}
               onChange={e => setCfg({ url: e.target.value, anon })}
               placeholder="https://<project-id>.supabase.co" />
        <label>SUPABASE_ANON_KEY</label>
        <input type="password" value={anon}
               onChange={e => setCfg({ url, anon: e.target.value })}
               placeholder="eyJhbGciOi..." />
      </div>

      <div className="row gap-2" style={{ marginTop: 12, alignItems: "center" }}>
        <button className="primary" onClick={save}><Save size={14} /> Save + connect</button>
        <button onClick={probe}>Re-probe</button>
        <span style={{ color: "var(--fg-2)", fontSize: 12, marginLeft: "auto" }}>
          Supabase dashboard → Settings → API for these values.
        </span>
      </div>

      <details style={{ marginTop: 14, color: "var(--fg-1)" }}>
        <summary style={{ cursor: "pointer" }}>How to set up Supabase (~2 min)</summary>
        <ol style={{ marginTop: 8, paddingLeft: 20, fontSize: 13, lineHeight: 1.6 }}>
          <li>Open <a onClick={() => window.open("https://supabase.com", "_blank")} style={{ cursor: "pointer" }}>https://supabase.com</a> → <strong>Start your project</strong> → sign in (GitHub or email).</li>
          <li>Click <strong>New project</strong>. Name: <code>local-email-stack</code>. Strong DB password. Region: closest to you. Pricing: <strong>Free</strong>.</li>
          <li>Wait ~60 sec for provisioning.</li>
          <li>Project → <strong>SQL Editor</strong> → <strong>New query</strong> → paste the contents of <code>supabase/schema.sql</code> from your repo → <strong>Run</strong>.</li>
          <li>Project → <strong>Settings → API</strong> → copy <strong>Project URL</strong> and <strong>anon public</strong> key. Paste both above. Save.</li>
          <li>Run <code>py sequences\supabase_sync.py push</code> in PowerShell to upload your local profiles + variants to Supabase. After this both PCs see them.</li>
        </ol>
      </details>
    </div>
  );
}
