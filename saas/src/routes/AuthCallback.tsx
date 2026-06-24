import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";

export default function AuthCallback() {
  const { session, loading } = useAuth();
  const nav = useNavigate();
  const [waited, setWaited] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setWaited(true), 1500);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    if (!loading && session) nav("/", { replace: true });
  }, [loading, session, nav]);

  return (
    <div className="card">
      <h2>Signing you in…</h2>
      {waited && !session && (
        <p className="sub">
          This link may have expired. <a href="/login" style={{ color: "var(--accent)" }}>Back to sign in</a>.
        </p>
      )}
    </div>
  );
}
