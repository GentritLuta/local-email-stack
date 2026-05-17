import { useEffect, useState } from "react";
import Editor from "@monaco-editor/react";
import { Save, Download, Upload, Wrench, Send } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { api, AppSettings, NotConnectedError } from "../lib/api";
import { SyncCard } from "./SyncCard";

type Tab = "general" | "sync" | "sender" | "env" | "portable" | "smoke";

export function SettingsPage() {
  const [searchParams] = useSearchParams();
  const [tab, setTab] = useState<Tab>((searchParams.get("tab") as Tab) || "general");
  const [s, setS] = useState<AppSettings | null>(null);
  const [env, setEnv] = useState<string>("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [smoke, setSmoke] = useState<[string, boolean, string][]>([]);

  // Sender (relay) settings — stored separately in localStorage in dev,
  // moves to bootstrap.env via Tauri in native.
  type RelayConfig = {
    backend: "resend" | "smtp" | "postal";
    resend_api_key: string;
    smtp_host: string;
    smtp_port: string;
    smtp_user: string;
    smtp_pass: string;
    postal_smtp_host: string;
    postal_smtp_port: string;
    postal_smtp_user: string;
    postal_smtp_pass: string;
    from_name: string;
    from_addr: string;
  };
  const RELAY_KEY = "les.relay";
  const defaultRelay: RelayConfig = {
    backend: "resend",
    resend_api_key: "",
    smtp_host: "smtp.gmail.com", smtp_port: "587", smtp_user: "", smtp_pass: "",
    postal_smtp_host: "postal-mail", postal_smtp_port: "587", postal_smtp_user: "", postal_smtp_pass: "",
    from_name: "Tomás Silva", from_addr: "tomas@algoalpha.io",
  };
  const [relay, setRelay] = useState<RelayConfig>(() => {
    try { return { ...defaultRelay, ...JSON.parse(localStorage.getItem(RELAY_KEY) || "{}") }; }
    catch { return defaultRelay; }
  });
  function saveRelay(next: RelayConfig) {
    setRelay(next);
    localStorage.setItem(RELAY_KEY, JSON.stringify(next));
    setMsg("Relay configuration saved (browser localStorage). In the native build this writes to bootstrap.env.");
  }

  useEffect(() => { api.settingsGet().then(setS).catch(() => setS({ stack_repo_path: null, pg_dsn_override: null, n8n_url: null, auto_start_stack: false })); }, []);
  useEffect(() => { if (tab === "env") api.envGet().then(setEnv).catch(() => setEnv("")); }, [tab]);

  async function saveGeneral() {
    if (!s) return;
    try { await api.settingsSet(s); setMsg("Settings saved."); }
    catch (e) { setMsg(e instanceof NotConnectedError ? "Settings persist only in the native Tauri build." : String(e)); }
  }
  async function saveEnv() {
    try { await api.envSet(env); setMsg("bootstrap.env saved. Restart stack to apply."); }
    catch (e) { setMsg(e instanceof NotConnectedError ? "Editing bootstrap.env requires the native Tauri build." : String(e)); }
  }
  async function runSmoke() { setBusy("smoke"); setSmoke(await api.runSmokeTest()); setBusy(null); }

  if (!s) return <div style={{ color: "#94a3b8" }}>Loading…</div>;

  const TabBtn = (props: { id: Tab; label: string }) => (
    <button className={tab === props.id ? "primary" : ""} onClick={() => setTab(props.id)}>{props.label}</button>
  );

  return (
    <>
      <h1 className="page-title">Settings</h1>
      <p className="page-sub">App config, sender relay, secrets, smoke test, and portable backup/transfer.</p>
      <div className="toolbar">
        <TabBtn id="general" label="General" />
        <TabBtn id="sync" label="Cross-PC sync" />
        <TabBtn id="sender" label="Sender" />
        <TabBtn id="env" label="bootstrap.env" />
        <TabBtn id="portable" label="Portable" />
        <TabBtn id="smoke" label="Smoke test" />
        <span style={{ marginLeft: "auto", color: "var(--accent-lime)" }}>{msg}</span>
      </div>

      {tab === "general" && (
        <div className="card">
          <div style={{ display: "grid", gridTemplateColumns: "200px 1fr", gap: 12, alignItems: "center" }}>
            <label>Stack repo path</label>
            <input type="text" value={s.stack_repo_path ?? ""} onChange={e => setS({ ...s, stack_repo_path: e.target.value })} placeholder="C:\Users\you\local-email-stack" />
            <label>Postgres DSN (override)</label>
            <input type="text" value={s.pg_dsn_override ?? ""} onChange={e => setS({ ...s, pg_dsn_override: e.target.value })} placeholder="postgres://user:pw@host:5432/leads" />
            <label>n8n URL</label>
            <input type="text" value={s.n8n_url ?? ""} onChange={e => setS({ ...s, n8n_url: e.target.value })} placeholder="http://127.0.0.1:5678" />
            <label>Auto-start stack on launch</label>
            <input type="checkbox" checked={s.auto_start_stack} onChange={e => setS({ ...s, auto_start_stack: e.target.checked })} />
          </div>
          <div style={{ marginTop: 12 }}>
            <button className="primary" onClick={saveGeneral}><Save size={14} /> Save</button>
          </div>
        </div>
      )}

      {tab === "sync" && <SyncCard />}

      {tab === "sender" && (
        <div>
          <div className="card" style={{ marginBottom: 12 }}>
            <h3>Sender relay — for inbox placement</h3>
            <p style={{ color: "var(--fg-1)", margin: 0 }}>
              Direct-to-MX from your home IP lands in spam. Pick one of three real backends below. After saving, run
              {" "}<code>py sequences/relay-send.py sequences/algoalpha-aureon-2026-05-17/sequence.json --backend &lt;chosen&gt; --resume-from 2</code>
              {" "}to re-send the 9 emails that failed earlier — they go through with proper SPF/DKIM/DMARC and land in the inbox.
            </p>
          </div>

          <div className="card" style={{ marginBottom: 12 }}>
            <h3>From address</h3>
            <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: 10, alignItems: "center" }}>
              <label>From name</label>
              <input type="text" value={relay.from_name} onChange={e => setRelay({ ...relay, from_name: e.target.value })} />
              <label>From address</label>
              <input type="text" value={relay.from_addr} onChange={e => setRelay({ ...relay, from_addr: e.target.value })} />
            </div>
            <div className="page-sub" style={{ marginTop: 6 }}>
              For Resend: the address domain must be verified in Resend. For SMTP via Gmail/Outlook: usually the same as your SMTP_USER.
            </div>
          </div>

          <div className="card" style={{ marginBottom: 12 }}>
            <h3>Backend</h3>
            <div className="row gap-2">
              {(["resend", "smtp", "postal"] as const).map(b => (
                <button key={b} className={relay.backend === b ? "primary" : ""}
                        onClick={() => setRelay({ ...relay, backend: b })}>
                  {b === "resend" ? "Resend (free 100/day) — easiest"
                   : b === "smtp" ? "SMTP relay (Gmail / Outlook / custom)"
                   : "Postal on Oracle (full self-host)"}
                </button>
              ))}
            </div>
          </div>

          {relay.backend === "resend" && (
            <div className="card">
              <h3>Resend</h3>
              <ol style={{ marginTop: 0, paddingLeft: 20, color: "var(--fg-1)" }}>
                <li>Sign up at <a onClick={() => api.openInBrowser("https://resend.com")} style={{ cursor: "pointer" }}>resend.com</a> (free, no credit card).</li>
                <li>Add and verify your sending domain (paste the DNS records into Cloudflare).</li>
                <li>Create an API key → paste it below.</li>
              </ol>
              <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: 10, alignItems: "center", marginTop: 10 }}>
                <label>RESEND_API_KEY</label>
                <input type="password" value={relay.resend_api_key} onChange={e => setRelay({ ...relay, resend_api_key: e.target.value })} placeholder="re_..." />
              </div>
            </div>
          )}

          {relay.backend === "smtp" && (
            <div className="card">
              <h3>Generic SMTP relay</h3>
              <p style={{ color: "var(--fg-1)", margin: "0 0 10px" }}>
                For Gmail: SMTP_HOST <code>smtp.gmail.com</code>, generate an App Password at <a onClick={() => api.openInBrowser("https://myaccount.google.com/apppasswords")} style={{ cursor: "pointer" }}>myaccount.google.com/apppasswords</a>.<br/>
                For Outlook: SMTP_HOST <code>smtp-mail.outlook.com</code>, same flow.
              </p>
              <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: 10, alignItems: "center" }}>
                <label>Host</label><input type="text" value={relay.smtp_host} onChange={e => setRelay({ ...relay, smtp_host: e.target.value })} />
                <label>Port</label><input type="text" value={relay.smtp_port} onChange={e => setRelay({ ...relay, smtp_port: e.target.value })} />
                <label>User</label><input type="text" value={relay.smtp_user} onChange={e => setRelay({ ...relay, smtp_user: e.target.value })} />
                <label>Password</label><input type="password" value={relay.smtp_pass} onChange={e => setRelay({ ...relay, smtp_pass: e.target.value })} />
              </div>
            </div>
          )}

          {relay.backend === "postal" && (
            <div className="card">
              <h3>Postal on Oracle Free Tier</h3>
              <p style={{ color: "var(--fg-1)", margin: "0 0 10px" }}>
                Provision the Oracle VM per <code>SENDER_INFRA.md</code> and pull SMTP creds from Postal's admin UI ("Credentials" on each Mail Server).
                The host should resolve over Tailscale once both ends are joined to the tailnet.
              </p>
              <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: 10, alignItems: "center" }}>
                <label>Host</label><input type="text" value={relay.postal_smtp_host} onChange={e => setRelay({ ...relay, postal_smtp_host: e.target.value })} />
                <label>Port</label><input type="text" value={relay.postal_smtp_port} onChange={e => setRelay({ ...relay, postal_smtp_port: e.target.value })} />
                <label>User</label><input type="text" value={relay.postal_smtp_user} onChange={e => setRelay({ ...relay, postal_smtp_user: e.target.value })} />
                <label>Password</label><input type="password" value={relay.postal_smtp_pass} onChange={e => setRelay({ ...relay, postal_smtp_pass: e.target.value })} />
              </div>
            </div>
          )}

          <div className="card" style={{ marginTop: 12 }}>
            <div className="row gap-2">
              <button className="primary" onClick={() => saveRelay(relay)}><Save size={14} /> Save relay config</button>
              <button onClick={async () => {
                const lines: string[] = [];
                lines.push("# Generated by LocalEmailStack > Settings > Sender");
                if (relay.resend_api_key)    lines.push(`RESEND_API_KEY=${relay.resend_api_key}`);
                if (relay.smtp_host)         lines.push(`SMTP_HOST=${relay.smtp_host}`);
                if (relay.smtp_port)         lines.push(`SMTP_PORT=${relay.smtp_port}`);
                if (relay.smtp_user)         lines.push(`SMTP_USER=${relay.smtp_user}`);
                if (relay.smtp_pass)         lines.push(`SMTP_PASS=${relay.smtp_pass}`);
                if (relay.postal_smtp_host)  lines.push(`POSTAL_SMTP_HOST=${relay.postal_smtp_host}`);
                if (relay.postal_smtp_port)  lines.push(`POSTAL_SMTP_PORT=${relay.postal_smtp_port}`);
                if (relay.postal_smtp_user)  lines.push(`POSTAL_SMTP_USER=${relay.postal_smtp_user}`);
                if (relay.postal_smtp_pass)  lines.push(`POSTAL_SMTP_PASS=${relay.postal_smtp_pass}`);
                const blob = new Blob([lines.join("\n") + "\n"], { type: "text/plain" });
                const a = document.createElement("a");
                a.href = URL.createObjectURL(blob); a.download = "relay.env";
                a.click(); URL.revokeObjectURL(a.href);
                setMsg("relay.env downloaded — drop in sequences/ next to send-sequence.py.");
              }}><Download size={14} /> Download relay.env</button>
              <span style={{ color: "var(--fg-1)", marginLeft: "auto", fontSize: 12 }}>
                In the native build this writes directly to <code>sequences/relay.env</code>.
              </span>
            </div>
            <div className="page-sub" style={{ marginTop: 12 }}>
              <strong>Next step:</strong> open a PowerShell terminal in the stack root and run
              <pre style={{ background: "#000", color: "#a3e635", padding: 10, borderRadius: 6, marginTop: 8, fontFamily: "var(--mono)", fontSize: 12, overflowX: "auto" }}>
py sequences\relay-send.py sequences\algoalpha-aureon-2026-05-17\sequence.json --backend {relay.backend} --resume-from 2
              </pre>
              Emails 2–10 will go out through the new backend with proper auth, hitting the inbox.
            </div>
          </div>
        </div>
      )}

      {tab === "env" && (
        <div className="card">
          <div className="toolbar">
            <span style={{ color: "#94a3b8" }}>bootstrap.env — sensitive. Don't share this file.</span>
            <button className="primary" style={{ marginLeft: "auto" }} onClick={saveEnv}><Save size={14} /> Save</button>
          </div>
          <Editor height="calc(100vh - 330px)" theme="vs-dark" language="ini" value={env}
                  onChange={v => setEnv(v ?? "")}
                  options={{ minimap: { enabled: false }, fontSize: 13, wordWrap: "on" }} />
        </div>
      )}

      {tab === "portable" && (
        <div className="card">
          <h3>Backup & transfer</h3>
          <p className="page-sub">Export the full stack state as a single .zip. On another PC: install LocalEmailStack → Settings → Portable → Import.</p>
          <p style={{ color: "var(--fg-1)", marginTop: 12 }}>
            <em>Export/import works only in the native Tauri build</em> — it shells out to Docker to dump/restore named volumes.
          </p>
        </div>
      )}

      {tab === "smoke" && (
        <div className="card">
          <div className="toolbar">
            <button className="primary" disabled={busy !== null} onClick={runSmoke}><Wrench size={14} /> Run smoke test</button>
          </div>
          {smoke.length === 0
            ? <div style={{ color: "var(--fg-2)", padding: 12 }}>Click "Run smoke test" to probe every service's /healthz.</div>
            : (
              <table className="tbl">
                <thead><tr><th>Service</th><th>URL</th><th>Status</th></tr></thead>
                <tbody>
                  {smoke.map(([name, ok, url]) => (
                    <tr key={name}>
                      <td>{name}</td>
                      <td><code style={{ color: "#94a3b8" }}>{url}</code></td>
                      <td><span className={`pill ${ok ? "green" : "red"}`}>{ok ? "ok" : "down"}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
        </div>
      )}
    </>
  );
}
