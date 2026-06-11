import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createSubmission, OnboardingAnswers } from "../lib/api";
import { HAS_CONFIG } from "../lib/supabase";

const EMPTY: OnboardingAnswers = {
  company: "", website: "", contact_email: "", offer: "", icp: "", proof: "",
  cta: "", sending_root: "", dns_host: "cloudflare", reply_to: "",
  lead_source: "icp_sourcing", notes: "",
};

export default function Onboard() {
  const nav = useNavigate();
  const [a, setA] = useState<OnboardingAnswers>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function set<K extends keyof OnboardingAnswers>(k: K, v: OnboardingAnswers[K]) {
    setA((prev) => ({ ...prev, [k]: v }));
  }

  const required: (keyof OnboardingAnswers)[] = ["company", "contact_email", "offer", "icp", "sending_root"];
  const valid = required.every((k) => String(a[k]).trim().length > 0);

  async function submit() {
    setErr(null); setBusy(true);
    try {
      const sub = await createSubmission(a);
      nav(`/status/${sub.id}`);
    } catch (e: any) {
      setErr(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="card">
        <h2>Start your campaign</h2>
        <p className="sub">
          Tell us about your offer. When you submit, we draft your cold-email sequence,
          provision your sending domains, and load your leads automatically. Takes about 5 minutes.
        </p>

        {!HAS_CONFIG && (
          <div className="banner">
            Backend not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in saas/.env.
          </div>
        )}
        {err && <div className="banner">{err}</div>}

        <div className="row">
          <div>
            <label>Company *</label>
            <input value={a.company} onChange={(e) => set("company", e.target.value)} placeholder="Acme Co" />
          </div>
          <div>
            <label>Website</label>
            <input value={a.website} onChange={(e) => set("website", e.target.value)} placeholder="https://acme.co" />
          </div>
        </div>

        <label>Contact email *</label>
        <input value={a.contact_email} onChange={(e) => set("contact_email", e.target.value)} placeholder="you@acme.co" />

        <label>What do you sell? (the offer) *</label>
        <textarea value={a.offer} onChange={(e) => set("offer", e.target.value)}
          placeholder="Done-for-you X that gets clients Y without Z. Pricing, guarantee, what makes it different." />

        <label>Who are your ideal customers? (ICP) *</label>
        <textarea value={a.icp} onChange={(e) => set("icp", e.target.value)}
          placeholder="Job titles, industry, company size, region. The more specific the better." />

        <label>Proof / numbers you can cite</label>
        <textarea value={a.proof} onChange={(e) => set("proof", e.target.value)}
          placeholder="e.g. 47 clients, 14.1M chart adds, 22% less downtime in 90 days." />

        <label>Desired call to action</label>
        <input value={a.cta} onChange={(e) => set("cta", e.target.value)}
          placeholder="Book a 15-min call / reply with your zip / request the free audit" />

        <div className="row">
          <div>
            <label>Sending domain (root) *</label>
            <input value={a.sending_root} onChange={(e) => set("sending_root", e.target.value)} placeholder="tryacme.com" />
            <div className="hint">We send from subdomains of this (hello.tryacme.com, etc). Use a domain separate from your main site.</div>
          </div>
          <div>
            <label>Where is its DNS hosted?</label>
            <select value={a.dns_host} onChange={(e) => set("dns_host", e.target.value)}>
              <option value="cloudflare">Cloudflare</option>
              <option value="hostinger">Hostinger</option>
              <option value="other">Other / not sure</option>
            </select>
            <div className="hint">Cloudflare/Hostinger = auto. Other = we hand you records to paste.</div>
          </div>
        </div>

        <label>Reply-to mailbox</label>
        <input value={a.reply_to} onChange={(e) => set("reply_to", e.target.value)} placeholder="replies@acme.co" />
        <div className="hint">Where prospect replies land. Must be a mailbox you monitor.</div>

        <label>Leads</label>
        <select value={a.lead_source} onChange={(e) => set("lead_source", e.target.value as any)}>
          <option value="icp_sourcing">Source leads for me from my ICP</option>
          <option value="csv">I'll upload a CSV later</option>
        </select>

        <label>Anything else?</label>
        <textarea value={a.notes} onChange={(e) => set("notes", e.target.value)} placeholder="Constraints, tone, do-not-contact lists, timing." />

        <button className="btn" disabled={!valid || busy || !HAS_CONFIG} onClick={submit}>
          {busy ? "Submitting…" : "Submit & kick off my campaign"}
        </button>
        {!valid && <div className="hint">Fill the fields marked * to continue.</div>}
      </div>
    </>
  );
}
