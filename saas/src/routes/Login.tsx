import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { HAS_CONFIG } from "../lib/supabase";
import { supabase } from "../lib/supabase";
import Logo from "../components/Logo";

export default function Login() {
  const { signInPassword, sendReset } = useAuth();
  const nav = useNavigate();
  const loc = useLocation() as any;
  const fromPath = loc.state?.from as string | undefined;

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  // MFA challenge state (shown after password if the account has 2FA)
  const [mfaFactorId, setMfaFactorId] = useState<string | null>(null);
  const [mfaCode, setMfaCode] = useState("");

  // After sign-in, send admins to /admin and clients to where they came from (or
  // their dashboard / the onboarding form).
  async function routeAfterLogin() {
    const { data: u } = await supabase.auth.getUser();
    let isAdmin = false;
    if (u?.user) {
      const { data: role } = await supabase
        .from("user_roles").select("is_admin").eq("user_id", u.user.id).maybeSingle();
      isAdmin = Boolean(role?.is_admin);
    }
    nav(isAdmin ? "/admin" : (fromPath || "/"), { replace: true });
  }

  async function doPassword() {
    setErr(null); setNote(null); setBusy(true);
    try {
      await signInPassword(email.trim(), password);
      // If the account has 2FA, Supabase needs an AAL2 step before we proceed.
      const { data: aal } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
      if (aal?.nextLevel === "aal2" && aal.nextLevel !== aal.currentLevel) {
        const { data: f } = await supabase.auth.mfa.listFactors();
        const totp = (f?.totp ?? []).find((x: any) => x.status === "verified");
        if (totp) { setMfaFactorId(totp.id); setBusy(false); return; }
      }
      await routeAfterLogin();
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  async function doMfa() {
    if (!mfaFactorId) return;
    setErr(null); setBusy(true);
    try {
      const ch = await supabase.auth.mfa.challenge({ factorId: mfaFactorId });
      if (ch.error) throw ch.error;
      const { error } = await supabase.auth.mfa.verify({
        factorId: mfaFactorId, challengeId: ch.data.id, code: mfaCode.trim(),
      });
      if (error) throw error;
      await routeAfterLogin();
    } catch (e: any) {
      setErr(e?.message || "Wrong code, try again.");
    } finally {
      setBusy(false);
    }
  }

  async function doReset() {
    setErr(null); setNote(null);
    if (!email.trim().includes("@")) { setErr("Enter your email first."); return; }
    setBusy(true);
    try {
      await sendReset(email.trim());
      setNote("If that email has an account, a password-reset link is on its way.");
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ maxWidth: 460, margin: "8px auto" }}>
      <div style={{ display: "flex", justifyContent: "center", marginBottom: 18 }}>
        <Logo size={56} showText={false} />
      </div>
      <div className="eyebrow" style={{ textAlign: "center" }}>AUREON Global · Client Portal</div>
      <h2 style={{ textAlign: "center" }}>Sign in</h2>
      <p className="sub" style={{ textAlign: "center", margin: "0 auto 22px" }}>
        Access your campaign, CRM, invoices, and agreement.
      </p>

      {!HAS_CONFIG && <div className="banner">Backend not configured.</div>}
      {err && <div className="banner">{err}</div>}
      {note && <div className="banner" style={{ background: "#0f2a1a" }}>{note}</div>}

      {mfaFactorId ? (
        <>
          <p className="sub" style={{ textAlign: "center" }}>
            Enter the 6-digit code from your authenticator app.
          </p>
          <input value={mfaCode} onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            placeholder="123456" inputMode="numeric" autoFocus
            onKeyDown={(e) => e.key === "Enter" && mfaCode.length === 6 && doMfa()} />
          <button className="btn block" disabled={busy || mfaCode.length !== 6} onClick={doMfa}>
            {busy ? "Verifying…" : "Verify"}
          </button>
          <div className="hint" style={{ marginTop: 12, textAlign: "center" }}>
            Locked out? Contact your AUREON admin to reset your access.
          </div>
        </>
      ) : (
      <>
      <label>Email</label>
      <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com"
        onKeyDown={(e) => e.key === "Enter" && password && doPassword()} />

      <label>Password</label>
      <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
        placeholder="Your password"
        onKeyDown={(e) => e.key === "Enter" && doPassword()} />

      <button className="btn block" disabled={busy || !email || !password || !HAS_CONFIG} onClick={doPassword}>
        {busy ? "Signing in…" : "Sign in"}
      </button>

      <button className="btn secondary block" style={{ marginTop: 12 }} disabled={busy || !HAS_CONFIG} onClick={doReset}>
        Forgot password
      </button>
      <div className="hint" style={{ marginTop: 14, textAlign: "center" }}>
        New here? <a href="/" style={{ color: "var(--accent)" }}>Start your campaign</a> — we
        create your account automatically.
      </div>
      </>
      )}
    </div>
  );
}
