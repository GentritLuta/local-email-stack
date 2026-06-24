import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getSubmission, getProvSteps, Submission, ProvStep } from "../lib/api";

const STEP_ORDER = ["contract", "profile", "copy", "domains", "leads", "warmup", "golive"];
const STEP_LABEL: Record<string, string> = {
  contract: "Sign your service agreement",
  profile: "Create your account profile",
  copy: "Draft your email sequence",
  domains: "Provision & verify sending domains",
  leads: "Load your leads",
  warmup: "Start domain warmup",
  golive: "Go live",
};

function icon(state: string) {
  if (state === "done") return "✓";
  if (state === "running") return "•";
  if (state === "error") return "!";
  if (state === "needs_input") return "?";
  return "";
}

export default function Status() {
  const { id } = useParams();
  const [sub, setSub] = useState<Submission | null>(null);
  const [steps, setSteps] = useState<ProvStep[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let alive = true;
    async function tick() {
      try {
        const [s, st] = await Promise.all([getSubmission(id!), getProvSteps(id!)]);
        if (!alive) return;
        setSub(s); setSteps(st); setErr(null);
      } catch (e: any) {
        if (alive) setErr(e?.message || String(e));
      }
    }
    tick();
    const iv = setInterval(tick, 4000); // poll while the PC pipeline works
    return () => { alive = false; clearInterval(iv); };
  }, [id]);

  const byStep = Object.fromEntries(steps.map((s) => [s.step, s]));
  const live = sub?.status === "live";
  const profileSlug = byStep["profile"]?.payload?.profile_slug || "";
  const doneCount = STEP_ORDER.filter((k) => byStep[k]?.state === "done").length;
  const pct = Math.round((doneCount / STEP_ORDER.length) * 100);

  return (
    <div className="card">
      <div className="eyebrow">Setup in progress</div>
      <h2>{sub?.raw_answers?.company || "Your campaign"}</h2>
      <p className="sub">
        This page updates live. You can close it and come back any time.{" "}
        {sub && <span className={`pill ${live ? "live" : sub.status === "error" ? "error" : "pending"}`}>{sub.status}</span>}
      </p>
      {sub && (
        <div style={{ margin: "0 0 22px" }}>
          <div style={{ height: 6, borderRadius: 99, background: "var(--field)", overflow: "hidden" }}>
            <div style={{
              width: `${pct}%`, height: "100%", borderRadius: 99,
              background: "var(--gold-grad)", transition: "width .6s var(--ease)",
              boxShadow: "0 0 12px rgba(230,197,88,.5)",
            }} />
          </div>
          <div className="hint" style={{ marginTop: 6 }}>{doneCount} of {STEP_ORDER.length} steps complete</div>
        </div>
      )}
      {err && <div className="banner">{err}</div>}
      {!sub && !err && <p className="sub">Loading…</p>}

      {sub && STEP_ORDER.map((key) => {
        const s = byStep[key];
        const state = s?.state || "pending";
        return (
          <div className="step" key={key}>
            <div className={`ico ${state}`}>{icon(state)}</div>
            <div className="body">
              <div className="name">{STEP_LABEL[key]}</div>
              {s?.detail && <div className="detail">{s.detail}</div>}
              {state === "needs_input" && s?.payload?.records && (
                <>
                  <div className="detail">Add these DNS records at your host, then we verify automatically:</div>
                  <pre className="records">{
                    (s.payload.records as any[]).map((r) =>
                      `${r.type}  ${r.name}  ->  ${r.value}`).join("\n")
                  }</pre>
                </>
              )}
            </div>
          </div>
        );
      })}

      {profileSlug && (
        <Link className="btn" to={`/dashboard/${profileSlug}`} style={{ display: "inline-block", textDecoration: "none" }}>
          Open my campaign dashboard
        </Link>
      )}
    </div>
  );
}
