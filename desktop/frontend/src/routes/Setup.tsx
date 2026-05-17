import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { api, AppSettings } from "../lib/api";

const STEPS = ["Welcome", "Repo path", "Postgres", "n8n", "Done"];

export function SetupWizard() {
  const navigate = useNavigate();
  const [step, setStep] = useState<number>(0);
  const [s, setS] = useState<AppSettings>({
    stack_repo_path: null,
    pg_dsn_override: null,
    n8n_url: "http://127.0.0.1:5678",
    auto_start_stack: false,
  });

  async function pickRepo() {
    const p = await openDialog({ directory: true, title: "Pick the local-email-stack repo folder" });
    if (p) setS((prev) => ({ ...prev, stack_repo_path: p as string }));
  }

  async function finish() {
    await api.settingsSet(s);
    navigate("/", { replace: true });
  }

  return (
    <div style={{ maxWidth: 720, margin: "40px auto" }}>
      <div className="row" style={{ alignItems: "center", gap: 12, marginBottom: 24 }}>
        <img src="/icon.svg" width={48} height={48} alt="" />
        <div>
          <h1 className="page-title" style={{ margin: 0 }}>Welcome to LocalEmailStack</h1>
          <p className="page-sub" style={{ margin: 0 }}>5-step setup, takes ~2 minutes.</p>
        </div>
      </div>

      <div className="card" style={{ minHeight: 280 }}>
        <div className="row gap-2" style={{ marginBottom: 16 }}>
          {STEPS.map((label, i) => (
            <span key={label} className={`pill ${i === step ? "cyan" : i < step ? "green" : ""}`}>{i + 1}. {label}</span>
          ))}
        </div>

        {step === 0 && (
          <div>
            <h3>What this is</h3>
            <p>LocalEmailStack is the control panel for your self-hosted cold-email pipeline. The pipeline itself runs as Docker containers on this machine.</p>
            <p>Before going on, make sure you have:</p>
            <ul>
              <li>Docker Desktop or Docker Engine installed and running</li>
              <li>The <code>local-email-stack</code> repo cloned somewhere on disk</li>
              <li>(optional) An Oracle Cloud Free Tier VM ready for the outbound SMTP layer</li>
            </ul>
          </div>
        )}

        {step === 1 && (
          <div>
            <h3>Where is your stack repo?</h3>
            <p style={{ color: "#94a3b8" }}>Pick the folder containing <code>docker/docker-compose.yml</code> + <code>niches/</code>.</p>
            <div className="row gap-2">
              <input type="text" style={{ flex: 1, padding: 8 }} value={s.stack_repo_path ?? ""} readOnly placeholder="No path selected" />
              <button className="primary" onClick={pickRepo}>Browse…</button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div>
            <h3>Postgres DSN (optional)</h3>
            <p style={{ color: "#94a3b8" }}>The app auto-derives the DSN from <code>bootstrap.env</code>. Override here only if your Postgres lives elsewhere.</p>
            <input type="text" style={{ width: "100%", padding: 8 }} value={s.pg_dsn_override ?? ""}
                   onChange={(e) => setS({ ...s, pg_dsn_override: e.target.value || null })}
                   placeholder="postgres://stackadmin:pw@127.0.0.1:5432/leads" />
          </div>
        )}

        {step === 3 && (
          <div>
            <h3>n8n URL</h3>
            <p style={{ color: "#94a3b8" }}>Used by the "Open n8n" shortcut on the dashboard.</p>
            <input type="text" style={{ width: "100%", padding: 8 }} value={s.n8n_url ?? ""}
                   onChange={(e) => setS({ ...s, n8n_url: e.target.value })}
                   placeholder="http://127.0.0.1:5678" />
            <label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 16 }}>
              <input type="checkbox" checked={s.auto_start_stack}
                     onChange={(e) => setS({ ...s, auto_start_stack: e.target.checked })} />
              Auto-start the stack whenever the app launches
            </label>
          </div>
        )}

        {step === 4 && (
          <div>
            <h3>You're set</h3>
            <p>Open the dashboard. From there: Start stack → Pipeline → trigger your first niche.</p>
            <p style={{ color: "#94a3b8" }}>If something looks off, Settings → Smoke test gives you a per-service /healthz probe.</p>
          </div>
        )}

        <div className="row" style={{ marginTop: 24 }}>
          <button onClick={() => setStep(Math.max(0, step - 1))} disabled={step === 0}>Back</button>
          <span style={{ flex: 1 }} />
          {step < STEPS.length - 1
            ? <button className="primary" onClick={() => setStep(step + 1)}
                      disabled={step === 1 && !s.stack_repo_path}>Next</button>
            : <button className="primary" onClick={finish}>Finish</button>}
        </div>
      </div>
    </div>
  );
}
