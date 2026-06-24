import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";

export default function ResetPassword() {
  const { session, setPassword, sendReset, loading } = useAuth();
  const nav = useNavigate();

  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  // Brief grace period: supabase-js consumes the token from the URL hash on
  // mount (detectSessionInUrl) and fires onAuthStateChange, so the session may
  // not be present on the very first render.
  const [settling, setSettling] = useState(true);
  const [email, setEmail] = useState("");

  useEffect(() => {
    const t = setTimeout(() => setSettling(false), 1500);
    return () => clearTimeout(t);
  }, []);

  const ready = !loading && !settling;
  const hasSession = Boolean(session);

  async function doSet() {
    setErr(null);
    if (pw.length < 12) { setErr("Use at least 12 characters."); return; }
    if (pw !== pw2) { setErr("Passwords do not match."); return; }
    setBusy(true);
    try {
      await setPassword(pw);
      setDone(true);
      setTimeout(() => nav("/", { replace: true }), 1200);
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setErr(null);
    if (!email.includes("@")) { setErr("Enter your email."); return; }
    try {
      await sendReset(email.trim());
      setErr(null);
      alert("A new reset link is on its way.");
    } catch (e: any) {
      setErr(e?.message || String(e));
    }
  }

  if (done) {
    return (
      <div className="card">
        <h2>Password set</h2>
        <p className="sub">You are signed in. Taking you to your portal…</p>
      </div>
    );
  }

  return (
    <div className="card">
      <h2>Set your password</h2>
      {!ready && <p className="sub">Verifying your link…</p>}

      {ready && hasSession && (
        <>
          <p className="sub">Choose a password for your AUREON portal. At least 12 characters.</p>
          {err && <div className="banner">{err}</div>}
          <label>New password</label>
          <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} placeholder="At least 12 characters" />
          <label>Confirm password</label>
          <input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)}
            placeholder="Repeat it" onKeyDown={(e) => e.key === "Enter" && doSet()} />
          <button className="btn block" disabled={busy || !pw || !pw2} onClick={doSet}>
            {busy ? "Saving…" : "Set password"}
          </button>
        </>
      )}

      {ready && !hasSession && (
        <>
          <div className="banner">This link is invalid or has expired.</div>
          <p className="sub">Enter your email and we will send a fresh link.</p>
          {err && <div className="banner">{err}</div>}
          <label>Email</label>
          <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" />
          <button className="btn block" onClick={resend}>Send a new link</button>
        </>
      )}
    </div>
  );
}
