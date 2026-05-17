import { useState } from "react";
import { Save, AlertCircle } from "lucide-react";
import { getSupabase } from "../lib/supabase";

type Form = {
  slug: string;
  name: string;
  company_name: string;
  company_site: string;
  from_addr: string;             // info@yourdomain.com or daniel@mail.yourdomain.com
  from_domain: string;           // mail.yourdomain.com (the verified sending subdomain)
  reply_to: string;              // where replies route (defaults to from_addr)
  num_personas: number;          // 1–5 — generates daniel/anna/marco/lena/tomas-style
  voice_register: string;
};

const DEFAULT_PERSONAS = [
  { slug: "daniel", from_name: "Daniel", voice: { register: "warm-direct",   quirks: ["short paragraphs"], avoid: ["corporate speak"] } },
  { slug: "anna",   from_name: "Anna",   voice: { register: "calm-precise",  quirks: ["specific numbers"], avoid: ["hype"] } },
  { slug: "marco",  from_name: "Marco",  voice: { register: "friendly",      quirks: ["warmer opener"],    avoid: ["templates"] } },
  { slug: "lena",   from_name: "Lena",   voice: { register: "personal",      quirks: ["one observation up front"], avoid: ["generic openers"] } },
  { slug: "tomas",  from_name: "Tomás",  voice: { register: "technical",     quirks: ["specific data"],    avoid: ["fluff"] } },
];

export function NewProfileModal(props: { onClose: () => void; onCreated: (slug: string) => void }) {
  const [f, setF] = useState<Form>({
    slug: "", name: "", company_name: "", company_site: "",
    from_addr: "", from_domain: "", reply_to: "",
    num_personas: 3, voice_register: "warm-direct",
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const slugAuto = f.slug || f.name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");

  async function save() {
    const s = getSupabase();
    if (!s) { setMsg("Supabase not configured. Settings → Cross-PC sync."); return; }
    if (!f.name || !f.from_addr || !f.from_domain) {
      setMsg("Name, From address, and Sending domain are required.");
      return;
    }
    if (!f.from_addr.includes("@")) { setMsg("From address must look like name@domain"); return; }
    setBusy(true); setMsg(null);

    const personas = DEFAULT_PERSONAS.slice(0, f.num_personas).map(p => ({
      slug:       p.slug,
      from_name:  p.from_name,
      from_addr:  `${p.slug}@${f.from_domain}`,
      reply_to:   f.reply_to || f.from_addr,
      voice:      p.voice,
      signature:  `${p.from_name.toLowerCase()}\n${f.company_name || f.name}`,
    }));

    const config = {
      slug: slugAuto,
      name: f.name,
      created_at: new Date().toISOString().slice(0, 10),
      active: true,
      company: {
        name: f.company_name || f.name,
        site: f.company_site || f.from_domain,
        tagline: "",
      },
      relay: {
        backend: "resend",
        from_domain: f.from_domain,
        resend_domain_id: null,
        resend_region: "eu-west-1",
        resend_api_key: "",
        domain_verified_at: null,
        _note: "Domain must be verified in Resend. If you don't have a Full-access Resend key, add the domain in Resend's dashboard. Then push DNS records — for Hostinger domains run `py sequences/resend-setup.py add <slug>`. Once Resend marks the domain verified, set domain_verified_at."
      },
      personas,
      rotation: {
        strategy: "round_robin_by_persona",
        max_sends_per_persona_per_day: 30,
        min_seconds_between_sends_same_persona: 180,
      },
      warmup: {
        enabled: true,
        started_at: null,
        current_day: 0,
        ramp_curve: "snowball_v1",
        max_daily_sends: 30 * f.num_personas,
        warmup_targets: [],
        real_send_mix: [
          { until_day: 14,   warmup_pct: 80 },
          { until_day: 30,   warmup_pct: 30 },
          { until_day: 45,   warmup_pct: 10 },
          { until_day: 9999, warmup_pct: 5  },
        ],
        reputation: { bounce_rate_7d: 0, complaint_rate_7d: 0, delivered_7d: 0, last_check: null },
        auto_pause_thresholds: { bounce_rate: 0.05, complaint_rate: 0.001 },
      },
      ramp_curve_snowball_v1: [
        { from_day: 1,  daily: 3 * f.num_personas  },
        { from_day: 4,  daily: 6 * f.num_personas  },
        { from_day: 8,  daily: 12 * f.num_personas },
        { from_day: 15, daily: 20 * f.num_personas },
        { from_day: 22, daily: 30 * f.num_personas },
      ],
    };

    try {
      const { error } = await s.from("profiles")
        .insert({ slug: slugAuto, name: f.name, config, active: true });
      if (error) throw error;
      setMsg(`Profile ${slugAuto} created. Visible on every PC connected to this Supabase project.`);
      setTimeout(() => props.onCreated(slugAuto), 1200);
    } catch (e: any) {
      setMsg(`Failed: ${e?.message ?? e}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={props.onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} style={{ width: 680 }}>
        <h3 style={{ marginTop: 0 }}>New client profile</h3>
        <p className="page-sub" style={{ marginTop: 0 }}>
          Creates a sending identity with {DEFAULT_PERSONAS.length}-persona rotation built in. Writes to Supabase so every PC sees it instantly.
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "160px 1fr", gap: 10, alignItems: "center" }}>
          <label>Display name *</label>
          <input value={f.name} onChange={e => setF({ ...f, name: e.target.value })}
                 placeholder="Aureon Global / ClientName" />

          <label>Slug (auto)</label>
          <input value={slugAuto} onChange={e => setF({ ...f, slug: e.target.value })}
                 placeholder="auto from name" />

          <label>Company name</label>
          <input value={f.company_name} onChange={e => setF({ ...f, company_name: e.target.value })} />

          <label>Company site</label>
          <input value={f.company_site} onChange={e => setF({ ...f, company_site: e.target.value })}
                 placeholder="aureonglobal.de" />

          <label>From address *</label>
          <input value={f.from_addr} onChange={e => setF({ ...f, from_addr: e.target.value })}
                 placeholder="info@yourdomain.com — reply-to default" />

          <label>Sending subdomain *</label>
          <input value={f.from_domain} onChange={e => setF({ ...f, from_domain: e.target.value })}
                 placeholder="mail.yourdomain.com (verified at Resend)" />

          <label>Reply-To (override)</label>
          <input value={f.reply_to} onChange={e => setF({ ...f, reply_to: e.target.value })}
                 placeholder="(defaults to From address)" />

          <label>Persona count</label>
          <input type="number" min={1} max={5} value={f.num_personas}
                 onChange={e => setF({ ...f, num_personas: Math.max(1, Math.min(5, parseInt(e.target.value || "1"))) })} />
        </div>

        <div className="card" style={{ marginTop: 14, background: "rgba(34,211,238,0.04)", borderColor: "rgba(34,211,238,0.2)" }}>
          <div className="row" style={{ alignItems: "flex-start", gap: 10 }}>
            <AlertCircle size={16} color="var(--accent-cyan)" />
            <div style={{ fontSize: 13, color: "var(--fg-1)" }}>
              <strong>Domain verification</strong> at Resend is a manual one-time step until you create a Full-access Resend API key.
              After saving:
              <ol style={{ paddingLeft: 18, marginTop: 6 }}>
                <li>Resend dashboard → Domains → Add domain → <code>{f.from_domain || "mail.<yours>"}</code></li>
                <li>If the domain is on Hostinger, push DNS records: <code>py sequences/resend-setup.py add {slugAuto || "<slug>"}</code></li>
                <li>Otherwise paste the records into your DNS provider manually</li>
                <li>Click Verify in Resend → status flips to green in ~5 min</li>
                <li>Update the profile's <code>relay.domain_verified_at</code> via the Sequences/runner once tests pass</li>
              </ol>
            </div>
          </div>
        </div>

        {msg && (
          <div style={{ marginTop: 12, padding: 10, borderRadius: 6, fontSize: 13,
                        background: msg.startsWith("Failed") ? "rgba(248,113,113,0.1)" : "rgba(163,230,53,0.08)" }}>
            {msg}
          </div>
        )}

        <div className="row gap-2" style={{ marginTop: 16, justifyContent: "flex-end" }}>
          <button onClick={props.onClose}>Cancel</button>
          <button className="primary" disabled={busy} onClick={save}><Save size={14} /> {busy ? "Creating…" : "Create profile"}</button>
        </div>
      </div>
    </div>
  );
}
