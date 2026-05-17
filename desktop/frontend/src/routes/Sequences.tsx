import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, XCircle, Clock, Send } from "lucide-react";
import { EmptyState } from "../components/EmptyState";
import {
  DbProfile, DbSequence, DbRun, DbSendLog,
  fetchProfiles, fetchSequences, fetchRuns, fetchSendLog,
  isConfigured, subscribeToTable,
} from "../lib/supabase";

// Live sequences view, sourced entirely from Supabase tables:
//   sequences        — definitions (one row per sequence per profile)
//   runs             — per-prospect enrollment, with current_step + status
//   send_log         — every outbound, joined back to runs via run_id
// No hardcoded slugs, no stale historical failure narratives.

type SeqMetrics = {
  sequence: DbSequence;
  profile_name: string;
  total_runs: number;
  queued: number;
  paused_replied: number;
  paused_bounced: number;
  completed: number;
  cancelled: number;
  total_sent: number;
  total_delivered: number;
  total_bounced: number;
  total_replied: number;
};

export function Sequences() {
  const [profiles, setProfiles] = useState<DbProfile[]>([]);
  const [sequences, setSequences] = useState<DbSequence[]>([]);
  const [runs, setRuns] = useState<DbRun[]>([]);
  const [sends, setSends] = useState<DbSendLog[]>([]);
  const [loaded, setLoaded] = useState(false);

  async function refresh() {
    if (!isConfigured()) { setLoaded(true); return; }
    const [ps, sq, rs, sl] = await Promise.all([
      fetchProfiles(),
      fetchSequences(),
      fetchRuns({ limit: 5000 }),
      fetchSendLog(5000),
    ]);
    setProfiles(ps); setSequences(sq); setRuns(rs); setSends(sl); setLoaded(true);
  }

  useEffect(() => {
    refresh();
    const subs = [
      subscribeToTable("sequences", refresh),
      subscribeToTable("runs", refresh),
      subscribeToTable("send_log", refresh),
    ];
    return () => subs.forEach(u => u());
  }, []);

  const metrics = useMemo<SeqMetrics[]>(() => {
    const profileNameBySlug = new Map(profiles.map(p => [p.slug, p.name]));
    const sendsByRun = new Map<string, DbSendLog[]>();
    for (const s of sends) {
      if (!s.run_id) continue;
      const arr = sendsByRun.get(s.run_id) || [];
      arr.push(s); sendsByRun.set(s.run_id, arr);
    }
    const runsBySeq = new Map<string, DbRun[]>();
    for (const r of runs) {
      const arr = runsBySeq.get(r.sequence_id) || [];
      arr.push(r); runsBySeq.set(r.sequence_id, arr);
    }
    return sequences.map(seq => {
      const seqRuns = runsBySeq.get(seq.id) || [];
      let total_sent = 0, total_delivered = 0, total_bounced = 0, total_replied = 0;
      for (const r of seqRuns) {
        const ss = sendsByRun.get(r.id) || [];
        for (const s of ss) {
          total_sent++;
          if (s.delivered && !s.bounced) total_delivered++;
          if (s.bounced) total_bounced++;
          if (s.replied) total_replied++;
        }
      }
      return {
        sequence: seq,
        profile_name: profileNameBySlug.get(seq.profile_slug) ?? seq.profile_slug,
        total_runs:      seqRuns.length,
        queued:          seqRuns.filter(r => r.status === "queued").length,
        paused_replied:  seqRuns.filter(r => r.status === "paused_replied").length,
        paused_bounced:  seqRuns.filter(r => r.status === "paused_bounced").length,
        completed:       seqRuns.filter(r => r.status === "completed").length,
        cancelled:       seqRuns.filter(r => r.status === "cancelled").length,
        total_sent, total_delivered, total_bounced, total_replied,
      };
    }).sort((a, b) => b.total_runs - a.total_runs);
  }, [profiles, sequences, runs, sends]);

  if (!isConfigured()) {
    return (<><h1 className="page-title">Sequences</h1>
      <EmptyState variant="not-connected"
                  title="Configure Supabase first"
                  message="Sequence definitions and their runtime state live in Supabase tables."
                  hint="Settings → Cross-PC sync → paste URL + anon key." /></>);
  }
  if (!loaded) return (<><h1 className="page-title">Sequences</h1><EmptyState variant="loading" /></>);

  // Sequences live in the `sequences` table. They get inserted via
  // sequence-runner.py or by a campaign-creation flow that's still in
  // progress — so an empty state here is the honest answer until one exists.
  if (sequences.length === 0) {
    return (
      <>
        <h1 className="page-title">Sequences</h1>
        <p className="page-sub">Multi-step cold-email sequences with auto-stop on reply, bounce, or complaint.</p>
        <EmptyState
          variant="no-data"
          title="No sequences yet"
          message="Sequences are stored in Supabase under `sequences` + `sequence_steps`. None have been created yet for any profile."
          hint={"To enroll a verified prospect in a sequence: \n  py sequences/sequence-runner.py enqueue <sequence_slug> <prospect_email>\nor in bulk per niche: \n  py sequences/sequence-runner.py enqueue-niche <sequence_slug> <niche_slug>"}
        />
      </>
    );
  }

  return (
    <>
      <h1 className="page-title">Sequences</h1>
      <p className="page-sub">
        Each row is a sequence definition on Supabase, with live counts of every enrollment + every outbound that's been logged to <code>send_log</code> against its runs. No mocks — empty cells are real zeroes.
      </p>

      <div className="card">
        <table className="tbl">
          <thead>
            <tr>
              <th>Sequence</th><th>Client</th><th>Active</th>
              <th>Enrollments</th><th>Queued</th><th>Replied</th><th>Bounced</th><th>Completed</th>
              <th>Sent</th><th>Delivered</th><th>Reply rate</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map(m => {
              const s = m.sequence;
              return (
                <tr key={s.id}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{s.name}</div>
                    <div style={{ fontSize: 11, color: "var(--fg-2)" }}><code>{s.slug}</code></div>
                  </td>
                  <td>{m.profile_name}</td>
                  <td>{s.active
                        ? <span className="pill green"><CheckCircle2 size={11} style={{verticalAlign:"-1px"}} /> active</span>
                        : <span className="pill"><Clock size={11} style={{verticalAlign:"-1px"}} /> off</span>}</td>
                  <td>{m.total_runs}</td>
                  <td>{m.queued || "—"}</td>
                  <td>{m.paused_replied || "—"}</td>
                  <td style={{ color: m.paused_bounced ? "var(--accent-red)" : undefined }}>{m.paused_bounced || "—"}</td>
                  <td>{m.completed || "—"}</td>
                  <td>{m.total_sent || "—"}</td>
                  <td>{m.total_delivered || "—"}</td>
                  <td>{m.total_sent ? `${((m.total_replied / m.total_sent) * 100).toFixed(1)}%` : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="card" style={{ marginTop: 16, background: "rgba(34,211,238,0.04)", borderColor: "rgba(34,211,238,0.2)" }}>
        <div className="row" style={{ alignItems: "flex-start", gap: 10 }}>
          <Send size={16} color="var(--accent-cyan)" />
          <div style={{ fontSize: 13, color: "var(--fg-1)" }}>
            <strong>Where do sequences come from?</strong> They get inserted into <code>sequences</code> + <code>sequence_steps</code> on Supabase by your scripts (variant authoring tools, the niche yaml loader). Once a sequence row exists, run
            <code style={{ marginLeft: 4 }}>py sequences/sequence-runner.py enqueue-niche &lt;sequence_slug&gt; &lt;niche_slug&gt;</code>
            to enroll every verified prospect in that niche. The runner ticks every 5 min, sends the next due step, gates on verified=true and unsubscribed=false, advances current_step on success.
          </div>
        </div>
      </div>
    </>
  );
}
