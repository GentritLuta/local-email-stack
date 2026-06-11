import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getSubmission, getProvSteps, Submission, ProvStep } from "../lib/api";

const STEP_ORDER = ["profile", "copy", "domains", "leads", "warmup", "golive"];
const STEP_LABEL: Record<string, string> = {
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

  return (
    <div className="card">
      <h2>Setting up {sub?.raw_answers?.company || "your campaign"}</h2>
      <p className="sub">
        This page updates live. You can close it and come back, your progress is saved.{" "}
        {sub && <span className={`pill ${live ? "live" : sub.status === "error" ? "error" : "pending"}`}>{sub.status}</span>}
      </p>
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

      {live && sub?.client_id && (
        <Link className="btn" to={`/dashboard/${byStep["profile"]?.payload?.profile_slug || ""}`}>
          Open my campaign dashboard
        </Link>
      )}
    </div>
  );
}
