import { useEffect, useMemo, useState } from "react";
import { Plus, Send, Copy, Activity, CheckCircle2, AlertCircle, Clock, XCircle } from "lucide-react";
import { EmptyState } from "../components/EmptyState";
import {
  DbRun, DbSendLog, DbProfile, DbVariant,
  fetchProfiles, fetchVariants, fetchRuns, fetchSendLog,
  getSupabase, isConfigured, subscribeToTable,
} from "../lib/supabase";

type ProspectInput = { email: string; first?: string; last?: string };

export function Campaigns() {
  const [profiles, setProfiles] = useState<DbProfile[]>([]);
  const [variants, setVariants] = useState<DbVariant[]>([]);
  const [runs, setRuns] = useState<DbRun[]>([]);
  const [recentSends, setRecentSends] = useState<DbSendLog[]>([]);
  const [showNew, setShowNew] = useState(false);
  const [loaded, setLoaded] = useState(false);

  async function refresh() {
    if (!isConfigured()) { setLoaded(true); return; }
    const [ps, rs, sl] = await Promise.all([
      fetchProfiles(), fetchRuns({ limit: 200 }), fetchSendLog(100),
    ]);
    setProfiles(ps); setRuns(rs); setRecentSends(sl);
    setLoaded(true);
  }

  useEffect(() => {
    refresh();
    const u1 = subscribeToTable("runs",     () => refresh());
    const u2 = subscribeToTable("send_log", () => refresh());
    return () => { u1(); u2(); };
  }, []);

  if (!isConfigured()) {
    return (
      <>
        <h1 className="page-title">Campaigns</h1>
        <EmptyState
          variant="not-connected"
          title="Configure Supabase first"
          message="Campaigns live in Supabase so both PCs see the same state."
          hint="Settings → Cross-PC sync → paste Supabase URL + anon key, then Save."
        />
      </>
    );
  }

  if (!loaded) return (<><h1 className="page-title">Campaigns</h1><EmptyState variant="loading" /></>);

  // Aggregate stats per run
  const runStats = new Map<string, { sent: number; delivered: number; bounced: number; replied: number; complained: number }>();
  for (const log of recentSends) {
    const k = log.run_id || "";
    if (!k) continue;
    const s = runStats.get(k) || { sent: 0, delivered: 0, bounced: 0, replied: 0, complained: 0 };
    s.sent++;
    if (log.delivered)  s.delivered++;
    if (log.bounced)    s.bounced++;
    if (log.replied)    s.replied++;
    if (log.complained) s.complained++;
    runStats.set(k, s);
  }

  return (
    <>
      <div className="row justify">
        <div>
          <h1 className="page-title">Campaigns</h1>
          <p className="page-sub">Pick a profile, paste prospects, choose variants, launch. Live in Supabase — same on every PC.</p>
        </div>
        <button className="primary" onClick={() => setShowNew(true)}><Plus size={14} /> New campaign</button>
      </div>

      {/* KPI cards aggregate over all runs */}
      <div className="grid grid-4" style={{ marginBottom: 16 }}>
        <Kpi label="Active runs" value={String(runs.filter(r => r.status === "queued" || r.status === "running").length)} accent="cyan" />
        <Kpi label="Total sent" value={String(recentSends.length)} />
        <Kpi label="Replied"  value={String(runs.filter(r => r.status === "paused_replied").length)} accent="green" />
        <Kpi label="Bounced"  value={String(runs.filter(r => r.status === "paused_bounced").length)} accent="red" />
      </div>

      {/* Runs table */}
      <div className="card">
        <h3>Runs ({runs.length})</h3>
        {runs.length === 0 ? (
          <div style={{ color: "var(--fg-2)", padding: 12 }}>No campaigns yet. Click "New campaign".</div>
        ) : (
          <table className="tbl">
            <thead><tr><th>Run</th><th>Persona</th><th>Step</th><th>Status</th><th>Sent</th><th>Delivered</th><th>Bounced</th><th>Replied</th><th>Next send</th></tr></thead>
            <tbody>
              {runs.map(r => {
                const s = runStats.get(r.id) || { sent: 0, delivered: 0, bounced: 0, replied: 0, complained: 0 };
                return (
                  <tr key={r.id}>
                    <td title={r.id} style={{ fontFamily: "var(--mono)", fontSize: 11 }}>{r.id.slice(0, 8)}…</td>
                    <td>{r.persona_slug ? <span className="pill">{r.persona_slug}</span> : <span className="pill">auto</span>}</td>
                    <td>{r.current_step}</td>
                    <td><StatusPill status={r.status} /></td>
                    <td>{s.sent}</td>
                    <td>{s.delivered}</td>
                    <td>{s.bounced || ""}</td>
                    <td>{s.replied || ""}</td>
                    <td style={{ fontSize: 12 }}>{r.next_send_at ? new Date(r.next_send_at).toLocaleString() : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Recent send log (cross-PC live feed) */}
      <div className="card" style={{ marginTop: 16 }}>
        <h3>Live send feed</h3>
        {recentSends.length === 0 ? (
          <div style={{ color: "var(--fg-2)", padding: 12 }}>No sends recorded yet.</div>
        ) : (
          <table className="tbl">
            <thead><tr><th>When</th><th>Persona</th><th>From</th><th>To</th><th>Subject</th><th></th></tr></thead>
            <tbody>
              {recentSends.slice(0, 30).map(s => (
                <tr key={s.id}>
                  <td style={{ whiteSpace: "nowrap", fontSize: 12 }}>{new Date(s.sent_at).toLocaleString()}</td>
                  <td><span className="pill">{s.persona_slug || ""}</span></td>
                  <td style={{ fontSize: 12 }}>{s.from_addr}</td>
                  <td style={{ fontSize: 12 }}>{s.to_addr}</td>
                  <td style={{ maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.subject}</td>
                  <td>
                    {s.complained ? <span className="pill red">complaint</span>
                     : s.bounced  ? <span className="pill red">bounce</span>
                     : s.replied  ? <span className="pill green">reply</span>
                     : s.delivered? <span className="pill green">delivered</span>
                                  : <span className="pill">sent</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {showNew && (
        <NewCampaignModal
          profiles={profiles}
          onClose={() => { setShowNew(false); refresh(); }}
        />
      )}
    </>
  );
}

function Kpi(props: { label: string; value: string; accent?: "green"|"red"|"amber"|"cyan" }) {
  const color = props.accent === "green" ? "var(--accent-lime)"
              : props.accent === "red"   ? "var(--accent-red)"
              : props.accent === "amber" ? "var(--accent-amber)"
              : props.accent === "cyan"  ? "var(--accent-cyan)" : "var(--fg-0)";
  return (
    <div className="card">
      <h3>{props.label}</h3>
      <div className="big" style={{ color }}>{props.value}</div>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  if (status === "queued")          return <span className="pill"><Clock size={11} style={{verticalAlign:"-1px"}} /> queued</span>;
  if (status === "running")         return <span className="pill cyan"><Activity size={11} style={{verticalAlign:"-1px"}} /> running</span>;
  if (status === "paused_replied")  return <span className="pill green"><CheckCircle2 size={11} style={{verticalAlign:"-1px"}} /> replied</span>;
  if (status === "paused_bounced")  return <span className="pill red"><XCircle size={11} style={{verticalAlign:"-1px"}} /> bounced</span>;
  if (status === "completed")       return <span className="pill green">completed</span>;
  if (status === "cancelled")       return <span className="pill">cancelled</span>;
  return <span className="pill">{status}</span>;
}

// ─── New campaign modal ─────────────────────────────────────────────────────

function NewCampaignModal(props: { profiles: DbProfile[]; onClose: () => void }) {
  const { profiles, onClose } = props;
  const [profileSlug, setProfileSlug] = useState(profiles[0]?.slug ?? "");
  const [name, setName] = useState("Untitled campaign");
  const [prospects, setProspects] = useState("");
  const [maxVariant, setMaxVariant] = useState(3);
  const [delayDays, setDelayDays] = useState(4);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [variants, setVariants] = useState<DbVariant[]>([]);

  useEffect(() => {
    if (profileSlug) fetchVariants(profileSlug).then(setVariants);
  }, [profileSlug]);

  function parseProspects(): ProspectInput[] {
    return prospects
      .split(/\r?\n/)
      .map(s => s.trim())
      .filter(s => s && s.includes("@"))
      .map(line => {
        // Support "email" or "email,first,last"
        const parts = line.split(",").map(p => p.trim());
        return { email: parts[0], first: parts[1], last: parts[2] };
      });
  }

  async function launch() {
    const s = getSupabase();
    if (!s) { setMsg("Supabase not configured."); return; }
    const ps = parseProspects();
    if (ps.length === 0) { setMsg("Add at least one prospect email."); return; }
    if (variants.length === 0) { setMsg("This profile has no variants in Supabase yet — run `py sequences/supabase_sync.py push`."); return; }
    setBusy(true); setMsg(null);
    try {
      // 1. Create sequence
      const seqSlug = `${profileSlug}-${Date.now()}`;
      const { data: seqRows, error: seqErr } = await s.from("sequences")
        .insert({ profile_slug: profileSlug, slug: seqSlug, name, active: true,
                  stop_on_reply: true, stop_on_bounce: true })
        .select().single();
      if (seqErr) throw seqErr;
      const sequence_id = seqRows!.id;

      // 2. Create steps from variants 1..maxVariant
      const stepsRows = [];
      for (let i = 1; i <= maxVariant; i++) {
        const v = variants.find(v => v.n === i);
        if (!v) continue;
        stepsRows.push({
          sequence_id, step_n: i,
          delay_days: i === 1 ? 0 : delayDays,
          variant_id: v.id,
        });
      }
      const { error: stErr } = await s.from("sequence_steps").insert(stepsRows);
      if (stErr) throw stErr;

      // 3. Upsert prospects + collect ids
      const prospectInserts = ps.map(p => ({
        profile_slug: profileSlug, email: p.email,
        first_name: p.first ?? null, last_name: p.last ?? null,
      }));
      // Use upsert (on conflict do nothing) by reading back ids after a plain insert with ignoreDuplicates
      await s.from("prospects").upsert(prospectInserts, { onConflict: "profile_slug,email" });
      const { data: prospectRows } = await s.from("prospects")
        .select("id,email")
        .eq("profile_slug", profileSlug)
        .in("email", ps.map(p => p.email));

      // 4. Create runs
      const now = new Date().toISOString();
      const runsRows = (prospectRows ?? []).map(pr => ({
        sequence_id, prospect_id: pr.id, status: "queued",
        current_step: 1, next_send_at: now,
      }));
      const { error: runErr } = await s.from("runs").insert(runsRows);
      if (runErr) throw runErr;

      setMsg(`Created ${runsRows.length} runs. Run \`py sequences\\sequence-runner.py tick\` to begin sending.`);
      setTimeout(onClose, 1500);
    } catch (e: any) {
      setMsg(`Failed: ${e?.message ?? e}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ width: 640 }}>
        <h3 style={{ marginTop: 0 }}>New campaign</h3>
        <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: 10, alignItems: "center" }}>
          <label>Campaign name</label>
          <input value={name} onChange={e => setName(e.target.value)} />

          <label>Profile (sender)</label>
          <select value={profileSlug} onChange={e => setProfileSlug(e.target.value)}>
            {profiles.map(p => <option key={p.slug} value={p.slug}>{p.name}</option>)}
          </select>

          <label>Prospects</label>
          <textarea rows={8} placeholder="one email per line&#10;optional: email,first,last"
                    value={prospects} onChange={e => setProspects(e.target.value)} />

          <label>Number of steps</label>
          <input type="number" min={1} max={20} value={maxVariant}
                 onChange={e => setMaxVariant(Math.max(1, Math.min(20, parseInt(e.target.value || "1"))))} />

          <label>Days between steps</label>
          <input type="number" min={0} max={30} value={delayDays}
                 onChange={e => setDelayDays(Math.max(0, parseInt(e.target.value || "0")))} />
        </div>

        <div style={{ fontSize: 12, color: "var(--fg-1)", marginTop: 12 }}>
          Using variants 1..{maxVariant} from profile <code>{profileSlug}</code>.
          {variants.length === 0 && <span style={{ color: "var(--accent-red)" }}> — no variants found in Supabase. Push first.</span>}
        </div>

        {msg && <div style={{ marginTop: 12, padding: 10, background: msg.startsWith("Failed") ? "rgba(248,113,113,0.1)" : "rgba(163,230,53,0.08)", borderRadius: 6, fontSize: 13 }}>{msg}</div>}

        <div className="row gap-2" style={{ marginTop: 16, justifyContent: "flex-end" }}>
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy} onClick={launch}><Send size={14} /> {busy ? "Creating…" : "Launch"}</button>
        </div>

        <details style={{ marginTop: 14, color: "var(--fg-1)" }}>
          <summary style={{ cursor: "pointer" }}>What happens when I click Launch?</summary>
          <ol style={{ paddingLeft: 20, fontSize: 13 }}>
            <li>New row in <code>sequences</code> (one per campaign)</li>
            <li>{`{N} rows in `}<code>sequence_steps</code> (one per email in the sequence)</li>
            <li>Prospects upserted to <code>prospects</code></li>
            <li>One <code>runs</code> row per prospect, queued for immediate send</li>
            <li>Run <code>py sequences\sequence-runner.py tick</code> locally (or scheduled task) to actually fire sends via Resend</li>
            <li>Auto-pauses on reply / bounce; status visible here in real time</li>
          </ol>
        </details>
      </div>
    </div>
  );
}
