import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Play, Pause, Copy, ExternalLink, ShieldCheck } from "lucide-react";
import {
  Profile, WarmupStatus, dailyTargetForDay, getActiveSlug, loadAllProfiles,
  loadWarmupStatus, reputationStatus, warmupPctForDay,
} from "../lib/profiles";
import { EmptyState } from "../components/EmptyState";

const TICK_CMD = (slug: string) => `py sequences\\warmup-scheduler.py tick --profile ${slug}`;
const START_CMD = (slug: string) => `py sequences\\warmup-scheduler.py start ${slug}`;
const PAUSE_CMD = (slug: string) => `py sequences\\warmup-scheduler.py pause ${slug}`;

export function Warmup() {
  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [statuses, setStatuses] = useState<Record<string, WarmupStatus | null>>({});
  const [slug, setSlug] = useState<string | null>(getActiveSlug());

  useEffect(() => {
    (async () => {
      const all = await loadAllProfiles();
      setProfiles(all);
      if (!slug && all[0]) setSlug(all[0].slug);
      const sMap: Record<string, WarmupStatus | null> = {};
      for (const p of all) sMap[p.slug] = await loadWarmupStatus(p.slug);
      setStatuses(sMap);
    })();
    const h = (e: Event) => setSlug((e as CustomEvent).detail);
    window.addEventListener("active-profile-changed", h);
    return () => window.removeEventListener("active-profile-changed", h);
  }, []);

  const profile = profiles?.find(p => p.slug === slug) || profiles?.[0];

  if (!profiles) return (<><h1 className="page-title">Warmup</h1><EmptyState variant="loading" /></>);
  if (!profile) return (<><h1 className="page-title">Warmup</h1>
    <EmptyState variant="no-data" title="No profiles" message="Create a profile first on the Profiles page." /></>);

  const status = statuses[profile.slug] ?? null;
  const day = profile.warmup.current_day || 0;
  const today_quota = dailyTargetForDay(profile, day);
  const today_warmup_pct = warmupPctForDay(profile, day);
  const rep = reputationStatus(profile);

  return (
    <>
      <div className="row justify">
        <div>
          <h1 className="page-title">Warmup — {profile.name}</h1>
          <p className="page-sub">Snowball ramp from 10 → {profile.warmup.max_daily_sends} sends/day over ~45 days, with auto-pause on bounce/complaint thresholds.</p>
        </div>
        <div className="row gap-2">
          {profile.warmup.enabled
            ? <span className="pill green"><ShieldCheck size={11} style={{verticalAlign:"-1px"}} /> warmup enabled</span>
            : <span className="pill amber">warmup paused</span>}
          {!rep.ok && <span className="pill red"><AlertCircle size={11} style={{verticalAlign:"-1px"}} /> {rep.reason}</span>}
        </div>
      </div>

      <div className="grid grid-4" style={{ marginBottom: 16 }}>
        <Kpi label="Current day" value={profile.warmup.enabled ? String(day) : "—"}
             accent={profile.warmup.enabled ? "cyan" : undefined} />
        <Kpi label="Today's quota" value={String(today_quota)} accent="cyan" />
        <Kpi label="Warmup share today" value={`${Math.round(today_warmup_pct * 100)}%`} />
        <Kpi label="Max daily" value={String(profile.warmup.max_daily_sends)} />
      </div>

      <div className="grid grid-2" style={{ gap: 16 }}>
        <RampCurveCard profile={profile} />
        <ReputationCard profile={profile} />
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>Warmup targets ({profile.warmup.warmup_targets.length})</h3>
        {profile.warmup.warmup_targets.length === 0
          ? (
            <div style={{ color: "var(--accent-amber)" }}>
              <AlertCircle size={14} style={{verticalAlign:"-2px"}} /> No warmup targets configured.
              Add 3–5 friendly inboxes (your own Gmail/Outlook, a partner's address) under <code>profile.warmup.warmup_targets</code>.
              These should be inboxes you'll occasionally open + reply to so engagement signals build domain reputation.
            </div>
          )
          : (
            <table className="tbl" style={{ marginTop: 6 }}>
              <thead><tr><th>Address</th></tr></thead>
              <tbody>{profile.warmup.warmup_targets.map(t => <tr key={t}><td>{t}</td></tr>)}</tbody>
            </table>
          )}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>Operate the ramp</h3>
        <p className="page-sub" style={{ marginTop: 0 }}>
          The scheduler is a Python script. Run it once a day (manually, scheduled task, or cron).
          Each tick advances the ramp by one day if today's send quota completes &gt;60%.
        </p>
        <div className="grid" style={{ gridTemplateColumns: "120px 1fr auto", gap: 8, alignItems: "center" }}>
          <span style={{ fontSize: 12, color: "var(--fg-2)" }}>Start warmup</span>
          <code style={{ background: "#000", padding: "6px 10px", borderRadius: 6, color: "var(--accent-lime)" }}>{START_CMD(profile.slug)}</code>
          <button onClick={() => navigator.clipboard.writeText(START_CMD(profile.slug))}><Copy size={12} /></button>

          <span style={{ fontSize: 12, color: "var(--fg-2)" }}>Daily tick</span>
          <code style={{ background: "#000", padding: "6px 10px", borderRadius: 6, color: "var(--accent-lime)" }}>{TICK_CMD(profile.slug)}</code>
          <button onClick={() => navigator.clipboard.writeText(TICK_CMD(profile.slug))}><Copy size={12} /></button>

          <span style={{ fontSize: 12, color: "var(--fg-2)" }}>Pause</span>
          <code style={{ background: "#000", padding: "6px 10px", borderRadius: 6, color: "var(--accent-lime)" }}>{PAUSE_CMD(profile.slug)}</code>
          <button onClick={() => navigator.clipboard.writeText(PAUSE_CMD(profile.slug))}><Copy size={12} /></button>
        </div>
        <p className="page-sub" style={{ marginTop: 12 }}>
          To run daily on Windows: <code>schtasks /Create /TN "LES-warmup-{profile.slug}" /TR "{TICK_CMD(profile.slug)}" /SC DAILY /ST 10:00</code>
        </p>
        {status && (
          <div className="page-sub" style={{ marginTop: 14, borderTop: "var(--border)", paddingTop: 12 }}>
            <strong>Last tick:</strong>{" "}
            {status.last_tick ?? "(never)"} ·{" "}
            sent {status.warmup_sent ?? 0} / {status.warmup_planned ?? 0} warmup
            {status.warmup_failed ? <span style={{ color: "var(--accent-red)" }}> · {status.warmup_failed} failed</span> : null}
            {status.paused && <span style={{ color: "var(--accent-red)" }}> · PAUSED: {status.reason}</span>}
            {status.deferred && <span style={{ color: "var(--accent-amber)" }}> · deferred (outside send window)</span>}
            {status.skipped && <span style={{ color: "var(--accent-amber)" }}> · skipped: {status.skipped}</span>}
          </div>
        )}
      </div>
    </>
  );
}

function Kpi(props: { label: string; value: string; accent?: "green"|"red"|"amber"|"cyan" }) {
  const color = props.accent === "green" ? "var(--accent-lime)"
              : props.accent === "red"   ? "var(--accent-red)"
              : props.accent === "amber" ? "var(--accent-amber)"
              : props.accent === "cyan"  ? "var(--accent-cyan)"
              : "var(--fg-0)";
  return (
    <div className="card">
      <h3>{props.label}</h3>
      <div className="big" style={{ color }}>{props.value}</div>
    </div>
  );
}

function RampCurveCard(props: { profile: Profile }) {
  const { profile } = props;
  const today = profile.warmup.current_day || 0;
  const curve = useMemo(() => {
    const days = 50;
    const out: { day: number; daily: number; warmupPct: number }[] = [];
    for (let d = 1; d <= days; d++) {
      out.push({ day: d, daily: dailyTargetForDay(profile, d), warmupPct: warmupPctForDay(profile, d) });
    }
    return out;
  }, [profile]);
  const maxDaily = Math.max(...curve.map(x => x.daily));
  return (
    <div className="card">
      <h3>Snowball ramp curve</h3>
      <p className="page-sub" style={{ marginTop: 0 }}>
        Industry-standard escalation; auto-pauses on bounce/complaint thresholds.
      </p>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 160, marginTop: 12 }}>
        {curve.map(c => {
          const h = (c.daily / maxDaily) * 100;
          const isToday = c.day === today;
          return (
            <div key={c.day} title={`Day ${c.day}: ${c.daily}/day, ${Math.round(c.warmupPct*100)}% warmup`}
                 style={{
                   flex: 1, height: `${h}%`, minHeight: 2,
                   background: isToday ? "var(--accent-lime)"
                     : c.warmupPct >= 0.5 ? "rgba(34,211,238,0.65)"
                     : c.warmupPct >= 0.15 ? "rgba(34,211,238,0.35)"
                     : "rgba(34,211,238,0.15)",
                   borderRadius: "2px 2px 0 0",
                 }} />
          );
        })}
      </div>
      <div className="row" style={{ marginTop: 6, fontSize: 11, color: "var(--fg-2)" }}>
        <span>Day 1</span><span style={{ flex: 1 }} /><span>Day 50</span>
      </div>
      <div className="row gap-2" style={{ marginTop: 12, fontSize: 11 }}>
        <span><span style={{display:"inline-block",width:12,height:12,background:"rgba(34,211,238,0.65)",verticalAlign:"-2px",borderRadius:2,marginRight:4}}/>heavy warmup (≥50%)</span>
        <span><span style={{display:"inline-block",width:12,height:12,background:"rgba(34,211,238,0.35)",verticalAlign:"-2px",borderRadius:2,marginRight:4}}/>mixed</span>
        <span><span style={{display:"inline-block",width:12,height:12,background:"rgba(34,211,238,0.15)",verticalAlign:"-2px",borderRadius:2,marginRight:4}}/>maintenance</span>
        <span><span style={{display:"inline-block",width:12,height:12,background:"var(--accent-lime)",verticalAlign:"-2px",borderRadius:2,marginRight:4}}/>today</span>
      </div>
      <table className="tbl" style={{ marginTop: 12 }}>
        <thead><tr><th>From day</th><th>Daily sends</th><th>Warmup share</th></tr></thead>
        <tbody>
          {profile.ramp_curve_snowball_v1.map((row, i) => (
            <tr key={i}>
              <td>{row.from_day}</td>
              <td>{row.daily}</td>
              <td>{Math.round(warmupPctForDay(profile, row.from_day) * 100)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReputationCard(props: { profile: Profile }) {
  const { profile } = props;
  const r = profile.warmup.reputation;
  const t = profile.warmup.auto_pause_thresholds;
  const Bar = ({ label, value, threshold, fmt }: { label: string; value: number; threshold: number; fmt: (n: number) => string }) => {
    const pct = Math.min(100, (value / threshold) * 100);
    const overThreshold = value > threshold;
    return (
      <div style={{ marginBottom: 10 }}>
        <div className="row justify" style={{ fontSize: 12 }}>
          <span>{label}</span>
          <span style={{ color: overThreshold ? "var(--accent-red)" : "var(--fg-1)" }}>
            {fmt(value)} / threshold {fmt(threshold)}
          </span>
        </div>
        <div style={{ height: 6, background: "var(--bg-2)", borderRadius: 3, overflow: "hidden", marginTop: 4 }}>
          <div style={{
            width: `${pct}%`, height: "100%",
            background: overThreshold ? "var(--accent-red)" : pct > 70 ? "var(--accent-amber)" : "var(--accent-lime)",
          }} />
        </div>
      </div>
    );
  };
  return (
    <div className="card">
      <h3>Reputation (7d window)</h3>
      <p className="page-sub" style={{ marginTop: 0 }}>
        Resend webhook events feed this in real time. Crossing a threshold auto-pauses the ramp.
      </p>
      <div style={{ marginTop: 12 }}>
        <Bar label="Bounce rate"    value={r.bounce_rate_7d}    threshold={t.bounce_rate}    fmt={n => `${(n*100).toFixed(2)}%`} />
        <Bar label="Complaint rate" value={r.complaint_rate_7d} threshold={t.complaint_rate} fmt={n => `${(n*100).toFixed(3)}%`} />
        <div className="row justify" style={{ fontSize: 12, marginTop: 14 }}>
          <span>Delivered (7d)</span>
          <span>{r.delivered_7d}</span>
        </div>
        {r.last_check && <div style={{ fontSize: 11, color: "var(--fg-2)", marginTop: 8 }}>
          Last webhook event: {new Date(r.last_check).toLocaleString()}
        </div>}
      </div>
      <div style={{ marginTop: 14, fontSize: 12, color: "var(--fg-1)", borderTop: "var(--border)", paddingTop: 12 }}>
        <strong>To enable live reputation:</strong>
        <ol style={{ marginTop: 6, paddingLeft: 18 }}>
          <li>Run <code>py sequences\warmup-webhook.py</code></li>
          <li>Expose with <code>cloudflared tunnel --url http://127.0.0.1:7878</code></li>
          <li>Resend → Webhooks → paste public URL + signing secret</li>
        </ol>
      </div>
    </div>
  );
}
