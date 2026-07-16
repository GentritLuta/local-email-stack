import { useState } from "react";
import { connectInstagram } from "../lib/api";

// Self-service Instagram connect. A logged-in client pastes a long-lived Graph API
// token; the auth-admin Edge Function verifies it against Meta and stores it on
// their credentials row. The token is never shown back in the browser.
export default function ConnectInstagram() {
  const [token, setToken] = useState("");
  const [saving, setSaving] = useState(false);
  const [ok, setOk] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function save() {
    const t = token.trim();
    if (!t) { setErr("Paste your Instagram access token first."); return; }
    setErr(null); setOk(null); setSaving(true);
    try {
      const r = await connectInstagram(t);
      setOk(`Connected to Instagram @${r.username}. You're all set — we can now publish to this account on your behalf.`);
      setToken("");
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card">
      <div className="eyebrow">Connect your Instagram</div>
      <h2>Link your Instagram account</h2>
      <p className="sub">
        Paste a long-lived access token for your Instagram Business account so we can publish
        content for you. Your token is verified and stored securely, and is never shown back in
        your browser. We never ask for your account password.
      </p>

      {err && <div className="banner">{err}</div>}
      {ok && (
        <div className="banner" style={{ background: "rgba(57,217,138,.12)", borderColor: "rgba(57,217,138,.45)", color: "#1c7a4f" }}>
          {ok}
        </div>
      )}

      <label>Access token *</label>
      <input type="password" value={token} onChange={(e) => setToken(e.target.value)}
        placeholder="Paste your long-lived token (starts with EAA…)" autoComplete="off" />
      <div className="hint">
        In Meta's <b>Graph API Explorer</b>, generate a token with the permissions
        instagram_basic, instagram_content_publish, pages_show_list, pages_read_engagement and
        business_management, then exchange it for a long-lived token. Your Instagram must be a
        Business or Creator account linked to a Facebook Page.
      </div>

      <button className="btn block" disabled={saving} onClick={save} style={{ marginTop: 16 }}>
        {saving ? "Verifying…" : "Connect Instagram"}
      </button>
      <div className="hint" style={{ marginTop: 10 }}>
        We verify the token with Instagram before saving. If it can't connect, you'll see exactly
        what to fix. You can revoke access any time from your Meta settings.
      </div>
    </div>
  );
}
