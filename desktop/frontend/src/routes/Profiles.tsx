import { useEffect, useState } from "react";
import { CheckCircle2, XCircle, AlertCircle, Copy, ExternalLink } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Profile, getActiveSlug, loadAllProfiles, setActiveSlug, reputationStatus, dailyTargetForDay, warmupPctForDay } from "../lib/profiles";
import { EmptyState } from "../components/EmptyState";
import { api } from "../lib/api";

export function Profiles() {
  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [active, setActive] = useState<string | null>(getActiveSlug());
  const navigate = useNavigate();

  useEffect(() => {
    loadAllProfiles().then(setProfiles);
  }, []);

  if (!profiles) return (<><h1 className="page-title">Profiles</h1><EmptyState variant="loading" /></>);

  return (
    <>
      <div className="row justify">
        <div>
          <h1 className="page-title">Profiles</h1>
          <p className="page-sub">Each profile is a sending identity — own domain, own voice, own warmup state.</p>
        </div>
      </div>

      {profiles.length === 0 ? (
        <EmptyState variant="no-data" title="No profiles" message="Add at least one profile to start sending." />
      ) : (
        <div className="grid" style={{ gridTemplateColumns: "1fr", gap: 16 }}>
          {profiles.map(p => {
            const isActive = p.slug === active;
            const day = p.warmup.current_day || 0;
            const daily = dailyTargetForDay(p, day);
            const pct = warmupPctForDay(p, day);
            const rep = reputationStatus(p);
            return (
              <div key={p.slug} className="card" style={{ borderColor: isActive ? "var(--accent-cyan)" : undefined }}>
                <div className="row justify">
                  <div>
                    <div style={{ fontSize: 16, fontWeight: 600 }}>{p.name}</div>
                    <div className="page-sub" style={{ margin: "4px 0 0" }}>
                      <span className="pill cyan">{p.identity.from_addr}</span>{" "}
                      <span className="pill">{p.identity.role}</span>{" "}
                      <span className="pill">{p.identity.company}</span>
                    </div>
                  </div>
                  <div className="row gap-2">
                    {isActive
                      ? <span className="pill green"><CheckCircle2 size={11} style={{verticalAlign:"-1px"}} /> active</span>
                      : <button onClick={() => { setActiveSlug(p.slug); setActive(p.slug); }}>Set active</button>}
                  </div>
                </div>

                <div className="grid grid-4" style={{ marginTop: 12 }}>
                  <Mini label="Domain verified"
                        value={p.relay.domain_verified_at ? "yes" : "no"}
                        accent={p.relay.domain_verified_at ? "green" : "amber"} />
                  <Mini label="Resend API key"
                        value={p.relay.resend_api_key && p.relay.resend_api_key !== "***" ? "set" :
                              p.relay.resend_api_key === "***" ? "set (redacted)" : "missing"}
                        accent={p.relay.resend_api_key ? "green" : "red"} />
                  <Mini label="Warmup day" value={p.warmup.enabled ? String(day) : "off"}
                        accent={p.warmup.enabled ? "cyan" : undefined} />
                  <Mini label="Today's quota" value={String(daily)}
                        accent={daily > 0 ? "cyan" : undefined} />
                </div>

                <div className="grid grid-2" style={{ marginTop: 12, gap: 12 }}>
                  <div>
                    <div style={{ fontSize: 12, color: "var(--fg-2)", textTransform: "uppercase", letterSpacing: ".04em", marginBottom: 4 }}>Warmup mix today</div>
                    <div className="row gap-2">
                      <span className="pill cyan">{Math.round(pct * 100)}% warmup</span>
                      <span className="pill">{Math.round((1 - pct) * 100)}% real prospects</span>
                    </div>
                    <div style={{ fontSize: 12, color: "var(--fg-1)", marginTop: 8 }}>
                      Warmup targets: {p.warmup.warmup_targets.length}
                      {p.warmup.warmup_targets.length < 3 && <span style={{ color: "var(--accent-amber)", marginLeft: 6 }}>(add ≥3 friendly inboxes)</span>}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 12, color: "var(--fg-2)", textTransform: "uppercase", letterSpacing: ".04em", marginBottom: 4 }}>Reputation (7d)</div>
                    <div className="row gap-2">
                      <span className={`pill ${p.warmup.reputation.bounce_rate_7d < p.warmup.auto_pause_thresholds.bounce_rate ? "green" : "red"}`}>
                        bounce {(p.warmup.reputation.bounce_rate_7d * 100).toFixed(2)}%
                      </span>
                      <span className={`pill ${p.warmup.reputation.complaint_rate_7d < p.warmup.auto_pause_thresholds.complaint_rate ? "green" : "red"}`}>
                        complaint {(p.warmup.reputation.complaint_rate_7d * 100).toFixed(3)}%
                      </span>
                      <span className="pill">delivered {p.warmup.reputation.delivered_7d}</span>
                    </div>
                    {!rep.ok && (
                      <div style={{ fontSize: 12, color: "var(--accent-red)", marginTop: 8 }}>
                        <AlertCircle size={12} style={{verticalAlign:"-2px"}} /> Paused: {rep.reason}
                      </div>
                    )}
                  </div>
                </div>

                <div className="row gap-2" style={{ marginTop: 14, flexWrap: "wrap" }}>
                  <button className="primary" onClick={() => navigate(`/settings?tab=sender&profile=${p.slug}`)}>
                    Configure sender
                  </button>
                  <button onClick={() => navigate(`/warmup?profile=${p.slug}`)}>Warmup details</button>
                  <button onClick={() => navigate(`/sequences?profile=${p.slug}`)}>Sequences</button>
                  <button onClick={async () => {
                    const cmd = `py sequences\\warmup-scheduler.py tick --profile ${p.slug}`;
                    try { await navigator.clipboard.writeText(cmd); alert("Tick command copied — paste in PowerShell."); }
                    catch { alert(cmd); }
                  }}><Copy size={12} /> Copy "tick" command</button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="card" style={{ marginTop: 16 }}>
        <h3>Add a new profile</h3>
        <p className="page-sub" style={{ margin: 0 }}>
          For now: copy <code>profiles/algoalpha.json</code> to <code>profiles/&lt;new-slug&gt;.json</code>,
          edit identity + relay.from_domains, then refresh this page. A guided "new profile" wizard
          ships in the native Tauri build.
        </p>
      </div>
    </>
  );
}

function Mini(props: { label: string; value: string; accent?: "green"|"red"|"amber"|"cyan" }) {
  const color = props.accent === "green" ? "var(--accent-lime)"
              : props.accent === "red"   ? "var(--accent-red)"
              : props.accent === "amber" ? "var(--accent-amber)"
              : props.accent === "cyan"  ? "var(--accent-cyan)"
              : "var(--fg-0)";
  return (
    <div>
      <div style={{ fontSize: 11, color: "var(--fg-2)", textTransform: "uppercase", letterSpacing: ".04em" }}>{props.label}</div>
      <div style={{ fontSize: 18, fontWeight: 600, color }}>{props.value}</div>
    </div>
  );
}
