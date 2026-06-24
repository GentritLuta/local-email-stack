import { useEffect, useState } from "react";
import { supabase } from "../lib/supabase";

type Factor = { id: string; status: string; friendly_name?: string };

export default function Security() {
  const [factors, setFactors] = useState<Factor[]>([]);
  const [enrolling, setEnrolling] = useState(false);
  const [qr, setQr] = useState<string | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const [factorId, setFactorId] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function loadFactors() {
    const { data } = await supabase.auth.mfa.listFactors();
    const totp = (data?.totp ?? []) as any[];
    setFactors(totp.map((f) => ({ id: f.id, status: f.status, friendly_name: f.friendly_name })));
  }
  useEffect(() => { loadFactors(); }, []);

  const verified = factors.find((f) => f.status === "verified");

  async function startEnroll() {
    setErr(null); setNote(null); setBusy(true);
    try {
      const { data, error } = await supabase.auth.mfa.enroll({ factorType: "totp", friendlyName: `Authenticator ${Date.now()}` });
      if (error) throw error;
      setFactorId(data.id);
      setQr(data.totp.qr_code);   // an SVG data-URI
      setSecret(data.totp.secret);
      setEnrolling(true);
    } catch (e: any) { setErr(e?.message || String(e)); }
    finally { setBusy(false); }
  }

  async function verifyEnroll() {
    if (!factorId) return;
    setErr(null); setBusy(true);
    try {
      const ch = await supabase.auth.mfa.challenge({ factorId });
      if (ch.error) throw ch.error;
      const { error } = await supabase.auth.mfa.verify({ factorId, challengeId: ch.data.id, code: code.trim() });
      if (error) throw error;
      setNote("Two-factor authentication is now on.");
      setEnrolling(false); setQr(null); setSecret(null); setCode("");
      await loadFactors();
    } catch (e: any) { setErr(e?.message || "Wrong code, try again."); }
    finally { setBusy(false); }
  }

  async function disable(id: string) {
    setErr(null); setBusy(true);
    try {
      const { error } = await supabase.auth.mfa.unenroll({ factorId: id });
      if (error) throw error;
      setNote("Two-factor authentication removed.");
      await loadFactors();
    } catch (e: any) { setErr(e?.message || String(e)); }
    finally { setBusy(false); }
  }

  return (
    <div className="card" style={{ maxWidth: 520, margin: "8px auto" }}>
      <div className="eyebrow">Account security</div>
      <h2>Two-factor authentication</h2>
      <p className="sub">
        Add a second step at login using an authenticator app (Google Authenticator, Authy, 1Password).
      </p>

      {err && <div className="banner">{err}</div>}
      {note && <div className="banner" style={{ background: "#0f2a1a" }}>{note}</div>}

      {verified && !enrolling && (
        <>
          <div className="step"><div className="ico done">✓</div>
            <div className="body"><div className="name">Two-factor is ON</div>
              <div className="detail">You'll enter a 6-digit code from your app when you sign in.</div></div></div>
          <button className="btn ghost" style={{ marginTop: 14 }} disabled={busy} onClick={() => disable(verified.id)}>
            Turn off two-factor
          </button>
        </>
      )}

      {!verified && !enrolling && (
        <button className="btn block" disabled={busy} onClick={startEnroll}>
          {busy ? "Setting up…" : "Set up two-factor"}
        </button>
      )}

      {enrolling && qr && (
        <>
          <p className="sub" style={{ marginTop: 8, textAlign: "center" }}>1. Scan this QR code with your authenticator app.</p>
          <div style={{ display: "flex", justifyContent: "center", margin: "6px 0 12px" }}>
            <div className="qr-box" dangerouslySetInnerHTML={{ __html: qr }} />
          </div>
          {secret && (
            <div className="hint" style={{ marginTop: 10 }}>
              Can't scan? Enter this key manually: <code style={{ color: "var(--accent)" }}>{secret}</code>
            </div>
          )}
          <label style={{ marginTop: 16 }}>2. Enter the 6-digit code from the app</label>
          <input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            placeholder="123456" inputMode="numeric"
            onKeyDown={(e) => e.key === "Enter" && verifyEnroll()} />
          <button className="btn block" disabled={busy || code.length !== 6} onClick={verifyEnroll}>
            {busy ? "Verifying…" : "Turn on two-factor"}
          </button>
          <button className="btn ghost" style={{ marginTop: 10 }} onClick={() => { setEnrolling(false); setQr(null); if (factorId) supabase.auth.mfa.unenroll({ factorId }); }}>
            Cancel
          </button>
        </>
      )}
    </div>
  );
}
