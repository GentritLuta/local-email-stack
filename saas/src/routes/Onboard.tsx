import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createSubmission, OnboardingAnswers } from "../lib/api";
import { HAS_CONFIG } from "../lib/supabase";
import LegalConsent, { LegalAcceptance, allAccepted } from "../components/LegalConsent";

const EMPTY: OnboardingAnswers = {
  service_type: "",
  company: "", website: "", contact_email: "", offer: "", icp: "", proof: "",
  give_first: "", cta: "", sending_root: "", dns_host: "cloudflare", reply_to: "",
  lead_source: "icp_sourcing",
  platforms: "", handles: "", posting_cadence: "",
  notes: "",
  rep: "", rep_title: "", jurisdiction: "", office: "",
};

const SERVICES: { id: "email" | "social" | "both"; title: string; desc: string }[] = [
  { id: "email", title: "Email marketing", desc: "Cold-email campaigns: we write the sequences, provision your sending domains, and source or load your leads." },
  { id: "social", title: "Social media management", desc: "We run your Instagram and TikTok: content calendar, posting, and replies, with a monthly report." },
  { id: "both", title: "Both", desc: "Email marketing and social media management, run together." },
];

const PLATFORMS = ["Instagram", "TikTok", "Facebook", "YouTube", "X (Twitter)", "LinkedIn"];

export default function Onboard() {
  const nav = useNavigate();
  const [a, setA] = useState<OnboardingAnswers>(EMPTY);
  const [legal, setLegal] = useState<LegalAcceptance>({ terms: false, privacy: false, agb: false });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function set<K extends keyof OnboardingAnswers>(k: K, v: OnboardingAnswers[K]) {
    setA((prev) => ({ ...prev, [k]: v }));
  }

  const isEmail = a.service_type === "email" || a.service_type === "both";
  const isSocial = a.service_type === "social" || a.service_type === "both";
  const picked = a.service_type !== "";

  function togglePlatform(p: string) {
    const cur = a.platforms ? a.platforms.split(", ").filter(Boolean) : [];
    const next = cur.includes(p) ? cur.filter((x) => x !== p) : [...cur, p];
    set("platforms", next.join(", "));
  }

  const required: (keyof OnboardingAnswers)[] = [
    "company", "contact_email", "offer", "icp", "rep", "rep_title",
    ...(isEmail ? (["give_first", "sending_root"] as (keyof OnboardingAnswers)[]) : []),
    ...(isSocial ? (["platforms"] as (keyof OnboardingAnswers)[]) : []),
  ];
  const valid = picked && required.every((k) => String(a[k]).trim().length > 0) && allAccepted(legal);

  async function submit() {
    setErr(null); setBusy(true);
    try {
      const sub = await createSubmission({
        ...a,
        accepted_terms: legal.terms, accepted_privacy: legal.privacy, accepted_agb: legal.agb,
        accepted_at: new Date().toISOString(),
      } as OnboardingAnswers);
      // Straight to signing: the pilot agreement is auto-prepared from these
      // answers, and setup does not begin until it is signed.
      nav(`/sign/${sub.id}`);
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
          First, pick what you want us to run. We tailor the rest of the form to your
          choice, then prepare your service agreement from your answers for you to sign.
        </p>

        {!HAS_CONFIG && (
          <div className="banner">
            Backend not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY in saas/.env.
          </div>
        )}
        {err && <div className="banner">{err}</div>}

        {/* ─── Step 1: pick the service (before anything else) ─── */}
        <label>What do you want us to run? *</label>
        <div className="svc-pick">
          {SERVICES.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => set("service_type", s.id)}
              className={"svc-card" + (a.service_type === s.id ? " sel" : "")}
              style={{
                textAlign: "left", padding: "14px 16px", borderRadius: 10, cursor: "pointer",
                border: a.service_type === s.id ? "2px solid var(--accent, #2563eb)" : "1px solid #d8dbe0",
                background: a.service_type === s.id ? "rgba(37,99,235,0.06)" : "#fff", flex: 1,
              }}
            >
              <b style={{ display: "block", marginBottom: 4 }}>{s.title}</b>
              <span style={{ fontSize: 13, color: "#6b7280" }}>{s.desc}</span>
            </button>
          ))}
        </div>

        {!picked && (
          <div className="hint" style={{ marginTop: 10 }}>Pick one to continue.</div>
        )}

        {picked && (
          <>
            <div className="row" style={{ marginTop: 20 }}>
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

            <label>{isSocial && !isEmail ? "Your brand / what you sell *" : "What do you sell? (the offer) *"}</label>
            <textarea value={a.offer} onChange={(e) => set("offer", e.target.value)}
              placeholder={isSocial && !isEmail
                ? "What the brand is, what you sell, the vibe and what makes it different."
                : "Done-for-you X that gets clients Y without Z. Pricing, guarantee, what makes it different."} />

            <label>{isSocial && !isEmail ? "Who is your audience? *" : "Who are your ideal customers? (ICP) *"}</label>
            <textarea value={a.icp} onChange={(e) => set("icp", e.target.value)}
              placeholder={isSocial && !isEmail
                ? "Age, interests, where they hang out, what makes them buy."
                : "Job titles, industry, company size, region. The more specific the better."} />

            {/* ─── Email marketing block ─── */}
            {isEmail && (
              <>
                <h3 style={{ marginTop: 24, marginBottom: 4 }}>Email marketing</h3>

                <label>Your give-first offer: the free value that makes people reply *</label>
                <div className="hint" style={{ marginTop: 0, marginBottom: 6 }}>
                  The single biggest lever on whether the campaign works. A brilliant email with a weak give-first
                  offer still gets ignored; a plain email with an irresistible one gets replies. Spend real thought here.
                </div>
                <div style={{ background: "rgba(212,175,55,0.07)", border: "1px solid rgba(212,175,55,0.28)", borderRadius: 12, padding: "13px 15px", color: "var(--text2)", fontSize: 13, lineHeight: 1.55, marginBottom: 8 }}>
                  <div style={{ fontWeight: 700, color: "var(--accent)", marginBottom: 4 }}>A strong give-first offer meets all four</div>
                  <ol style={{ margin: "0 0 10px 18px", padding: 0 }}>
                    <li>Valuable enough that you would normally <b style={{ color: "var(--text)" }}>charge</b> for it (a real gift, not a brochure).</li>
                    <li><b style={{ color: "var(--text)" }}>Near-zero effort</b> for you to make, so we can templatise it and automate the delivery.</li>
                    <li>Delivered <b style={{ color: "var(--text)" }}>instantly</b> when they reply one word. No call, no form, no waiting.</li>
                    <li>Hits your prospect's <b style={{ color: "var(--text)" }}>number-one</b> nagging problem, or the question they always ask.</li>
                  </ol>
                  <div style={{ fontWeight: 700, color: "var(--accent)", marginBottom: 4 }}>Formats that work (pick the closest, make it specific to your world)</div>
                  <ul style={{ margin: "0 0 10px 18px", padding: 0 }}>
                    <li><b style={{ color: "var(--text)" }}>Audit / teardown</b> &mdash; a written breakdown of where their result is leaking (SEO, ads, funnels, ops, hiring).</li>
                    <li><b style={{ color: "var(--text)" }}>Curated list</b> &mdash; a hand-built list of vetted people, tools, or vendors for their exact situation.</li>
                    <li><b style={{ color: "var(--text)" }}>Checklist / template</b> &mdash; the step-by-step checklist or ready-to-use template you use for the job.</li>
                    <li><b style={{ color: "var(--text)" }}>Sample / done-for-you</b> &mdash; one finished piece made for them, free, so they see your quality first.</li>
                    <li><b style={{ color: "var(--text)" }}>Report / number</b> &mdash; their key figure worked out for them (what their X is worth, or what it is costing).</li>
                  </ul>
                  <div style={{ marginBottom: 8 }}><b style={{ color: "var(--text)" }}>Avoid:</b> a free consultation, a discovery call, a demo, or a generic ebook. Those make the prospect do the work or read like a pitch.</div>
                  <div><b style={{ color: "var(--text)" }}>Stuck?</b> Answer one of these in the box: what do your best clients always ask for before they buy, or what do you already have that a stranger would pay for and you could send in a single email? Or just write <i>"help me design one"</i> and we will propose it with you.</div>
                </div>
                <textarea value={a.give_first} onChange={(e) => set("give_first", e.target.value)} rows={3}
                  placeholder="Describe your give-first offer. e.g. A free written teardown of where a roofer's Google Business Profile is losing them calls, sent as a branded PDF the moment they reply AUDIT." />

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
              </>
            )}

            {/* ─── Social media management block ─── */}
            {isSocial && (
              <>
                <h3 style={{ marginTop: 24, marginBottom: 4 }}>Social media management</h3>
                <label>Which platforms? *</label>
                <div className="svc-platforms" style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 4 }}>
                  {PLATFORMS.map((p) => {
                    const on = a.platforms.split(", ").filter(Boolean).includes(p);
                    return (
                      <button key={p} type="button" onClick={() => togglePlatform(p)}
                        style={{
                          padding: "6px 12px", borderRadius: 20, cursor: "pointer", fontSize: 13,
                          border: on ? "2px solid var(--accent, #2563eb)" : "1px solid #d8dbe0",
                          background: on ? "rgba(37,99,235,0.08)" : "#fff",
                        }}>
                        {on ? "✓ " : ""}{p}
                      </button>
                    );
                  })}
                </div>

                <label>Account handles or links</label>
                <textarea value={a.handles} onChange={(e) => set("handles", e.target.value)}
                  placeholder="@yourbrand on Instagram, tiktok.com/@yourbrand, etc." />

                <label>Posting cadence</label>
                <input value={a.posting_cadence} onChange={(e) => set("posting_cadence", e.target.value)}
                  placeholder="e.g. daily stories + 3 posts/week, or leave it to us" />
                <div className="hint">How often you want to post. Not sure? We recommend a cadence at the kickoff call.</div>
              </>
            )}

            {/* ─── Agreement / signer details ─── */}
            <h3 style={{ marginTop: 24, marginBottom: 4 }}>For your service agreement</h3>
            <div className="hint" style={{ marginBottom: 10 }}>
              These go into the agreement you will sign on the next step.
            </div>
            <div className="row">
              <div>
                <label>Authorised signer (full legal name) *</label>
                <input value={a.rep} onChange={(e) => set("rep", e.target.value)} placeholder="Jane Doe" />
              </div>
              <div>
                <label>Position / title *</label>
                <input value={a.rep_title} onChange={(e) => set("rep_title", e.target.value)} placeholder="Owner / Founder / CEO / Director" />
              </div>
            </div>
            <div className="row">
              <div>
                <label>Jurisdiction of incorporation</label>
                <input value={a.jurisdiction} onChange={(e) => set("jurisdiction", e.target.value)} placeholder="Texas, United States" />
              </div>
              <div>
                <label>Registered office address</label>
                <input value={a.office} onChange={(e) => set("office", e.target.value)} placeholder="123 Main St, Austin, TX" />
              </div>
            </div>

            <label>Anything else?</label>
            <textarea value={a.notes} onChange={(e) => set("notes", e.target.value)}
              placeholder={isSocial && !isEmail
                ? "Tone, anything we should not post, brand rules, timing."
                : "Constraints, tone, do-not-contact lists, timing."} />

            <h3 style={{ marginTop: 24, marginBottom: 4 }}>Legal</h3>
            <div className="hint" style={{ marginBottom: 6 }}>
              Please review and accept. Hover the ⓘ to learn what each is and where to find it.
            </div>
            <LegalConsent value={legal} onChange={setLegal} />

            <button className="btn block" disabled={!valid || busy || !HAS_CONFIG} onClick={submit}>
              {busy ? "Preparing your agreement…" : "Continue to sign your agreement"}
            </button>
            {!valid && (
              <div className="hint">
                {required.every((k) => String(a[k]).trim()) && !allAccepted(legal)
                  ? "Accept the Terms, Privacy Policy, and AGB to continue."
                  : "Fill the fields marked * to continue."}
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}
