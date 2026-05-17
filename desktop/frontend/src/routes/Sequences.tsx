import { useEffect, useState } from "react";
import { CheckCircle2, XCircle, Clock, AlertCircle, Settings as SettingsIcon, Copy } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api, Sequence, SequenceStepResult } from "../lib/api";
import { EmptyState } from "../components/EmptyState";
import { Profile, getActiveSlug, loadAllProfiles, loadProfile } from "../lib/profiles";

export function Sequences() {
  const [seq, setSeq] = useState<Sequence | null>(null);
  const [results, setResults] = useState<SequenceStepResult[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [selectedN, setSelectedN] = useState<number | null>(null);
  const [activeProfile, setActiveProfile] = useState<Profile | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    (async () => {
      const s = await api.getSequence("algoalpha_aureon_test");
      const r = await api.getSequenceResults("algoalpha_aureon_test");
      setSeq(s); setResults(r); setLoaded(true);
      if (s && s.steps[0]) setSelectedN(1);
      const slug = getActiveSlug();
      if (slug) setActiveProfile(await loadProfile(slug));
    })();
    const h = async (e: Event) => {
      const slug = (e as CustomEvent).detail as string;
      setActiveProfile(await loadProfile(slug));
    };
    window.addEventListener("active-profile-changed", h);
    return () => window.removeEventListener("active-profile-changed", h);
  }, []);

  const sendCmd = activeProfile && seq
    ? `py sequences\\profile-aware-send.py ${activeProfile.slug} sequences\\algoalpha-aureon-2026-05-17\\sequence.json --resume-from 2`
    : null;

  if (!loaded) return (<><h1 className="page-title">Sequences</h1><EmptyState variant="loading" /></>);
  if (!seq) {
    return (
      <>
        <h1 className="page-title">Sequences</h1>
        <EmptyState
          variant="no-data"
          title="No sequences"
          message="No sequence JSON files found under public/sequences/."
          hint="Create one by running sequences/send-sequence.py against a sequence.json file." />
      </>
    );
  }

  const sent    = results.filter(r => r.sent).length;
  const failed  = results.filter(r => !r.sent && !r.skipped && r.error).length;
  const pending = seq.steps.length - sent - failed;
  const selected = seq.steps.find(s => s.n === selectedN);
  const selectedResult = results.find(r => r.step === selectedN);

  return (
    <>
      <div className="row justify">
        <div>
          <h1 className="page-title">Sequences</h1>
          <p className="page-sub">Multi-step cold-email sequences with auto-stop on reply, bounce, or complaint.</p>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="row justify">
          <div>
            <div style={{ fontSize: 16, fontWeight: 600 }}>{seq.name}</div>
            <div className="page-sub" style={{ margin: "4px 0 0" }}>
              From <span className="pill cyan">{seq.sender.from_addr}</span> →
              {" "}<span className="pill">{seq.recipient.email}</span>
              {" "}· <span className="pill">{seq.steps.length} steps</span>
              {" "}· {seq.stop_on_reply && <span className="pill green">stop on reply</span>}
            </div>
          </div>
          <div className="row gap-2">
            <button className="primary"
                    onClick={() => navigate("/settings?tab=sender")}>
              <SettingsIcon size={14} /> Sender setup
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-4" style={{ marginBottom: 16 }}>
        <div className="card"><h3>Sent</h3><div className="big" style={{ color: "var(--accent-cyan)" }}>{sent}</div></div>
        <div className="card"><h3>Failed</h3><div className="big" style={{ color: failed > 0 ? "var(--accent-red)" : "var(--fg-1)" }}>{failed}</div></div>
        <div className="card"><h3>Pending</h3><div className="big">{pending}</div></div>
        <div className="card"><h3>Replied</h3><div className="big" style={{ color: "var(--fg-2)" }}>0</div></div>
      </div>

      {failed > 0 && (
        <div className="card" style={{ marginBottom: 16, borderColor: "var(--accent-amber)" }}>
          <div className="row" style={{ alignItems: "flex-start", gap: 12 }}>
            <AlertCircle size={20} color="var(--accent-amber)" />
            <div style={{ flex: 1 }}>
              <strong>Why steps 2–10 failed:</strong> sent direct-to-MX from a residential IP without SPF/DKIM/DMARC.
              {" "}<code>mx2.hostinger.com</code> rate-limited connections after the first delivery (which is normal anti-spam behavior).
              {" "}<strong>To make them deliver to inbox:</strong> set up a Resend-backed profile (≈5 min),{" "}
              then re-send via the profile-aware sender:
              {sendCmd && (
                <div className="row gap-2" style={{ marginTop: 10, alignItems: "center" }}>
                  <code style={{ flex: 1, background: "#000", padding: "6px 10px", borderRadius: 6, color: "var(--accent-lime)", fontSize: 11, overflow: "auto" }}>{sendCmd}</code>
                  <button onClick={() => navigator.clipboard.writeText(sendCmd)}><Copy size={12} /></button>
                </div>
              )}
              <div style={{ marginTop: 8, fontSize: 12 }}>
                Active profile: {activeProfile
                  ? <span className="pill cyan">{activeProfile.name}</span>
                  : <span className="pill amber">no profile selected — pick one in the sidebar</span>}
                {activeProfile && !activeProfile.relay.resend_api_key && <span className="pill amber" style={{marginLeft:6}}>add Resend API key in Sender setup</span>}
              </div>
              See <code>DELIVERABILITY.md</code> for the full inbox-placement playbook.
            </div>
          </div>
        </div>
      )}

      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div className="card">
          <h3>Steps</h3>
          <table className="tbl">
            <thead><tr><th>#</th><th>Day</th><th>Subject</th><th>Status</th></tr></thead>
            <tbody>
              {seq.steps.map(step => {
                const r = results.find(x => x.step === step.n);
                let badge;
                if (r?.sent) badge = <span className="pill green"><CheckCircle2 size={11} style={{verticalAlign:"-1px"}} /> sent {r.backend ? `via ${r.backend}` : ""}</span>;
                else if (r?.error) badge = <span className="pill red" title={r.error}><XCircle size={11} style={{verticalAlign:"-1px"}} /> failed</span>;
                else badge = <span className="pill"><Clock size={11} style={{verticalAlign:"-1px"}} /> pending</span>;
                return (
                  <tr key={step.n} onClick={() => setSelectedN(step.n)}
                      style={{ cursor: "pointer", background: selectedN === step.n ? "rgba(34,211,238,0.05)" : undefined }}>
                    <td>{step.n}</td><td>+{step.day}d</td>
                    <td style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{step.subject}</td>
                    <td>{badge}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h3>Preview · step {selectedN ?? "—"}</h3>
          {selected ? (
            <>
              <div className="page-sub" style={{ margin: "0 0 8px" }}>
                From <span className="pill cyan">{seq.sender.from_addr}</span> →
                {" "}<span className="pill">{seq.recipient.email}</span>
              </div>
              <div style={{ fontWeight: 600, marginBottom: 8 }}>{selected.subject}</div>
              <pre style={{
                background: "#000", color: "#cbd5e1", padding: 12, borderRadius: 8,
                fontFamily: "var(--mono)", fontSize: 12, whiteSpace: "pre-wrap",
                maxHeight: 380, overflow: "auto", margin: 0,
              }}>{selected.body}

--
{seq.sender.signature}</pre>
              {selectedResult && (
                <div className="page-sub" style={{ marginTop: 8 }}>
                  {selectedResult.sent
                    ? <>Delivered {selectedResult.mx && <>via <code>{selectedResult.mx}</code></>}{selectedResult.backend && <> · backend: <code>{selectedResult.backend}</code></>}. Message-ID: <code>{selectedResult.message_id}</code></>
                    : selectedResult.error
                    ? <>Send error: <code>{selectedResult.error}</code></>
                    : <>Not yet attempted.</>}
                </div>
              )}
            </>
          ) : (
            <div style={{ color: "var(--fg-2)" }}>Pick a step on the left.</div>
          )}
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <h3>About this run</h3>
        <p className="page-sub" style={{ margin: 0 }}>{seq.schedule_explainer}</p>
      </div>
    </>
  );
}
