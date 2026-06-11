import { useEffect, useMemo, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid,
} from "recharts";
import { EmptyState } from "../components/EmptyState";
import {
  DbProfile, DbSendLog, DbReply, DbProspect,
  fetchProfiles, fetchSendLog, fetchReplies, fetchProspects,
  isConfigured, subscribeToTable,
} from "../lib/supabase";

type RangeKey = "today" | "7d" | "30d" | "90d" | "all";
const RANGES: { key: RangeKey; label: string; days: number | null }[] = [
  { key: "today", label: "Today", days: 1 },
  { key: "7d",    label: "7 days", days: 7 },
  { key: "30d",   label: "30 days", days: 30 },
  { key: "90d",   label: "90 days", days: 90 },
  { key: "all",   label: "All time", days: null },
];

// ─── Helpers ──────────────────────────────────────────────────────────────

const day = (iso: string) => iso.slice(0, 10);  // YYYY-MM-DD
const pct = (n: number, d: number, digits = 1) =>
  d === 0 ? "—" : `${((n / d) * 100).toFixed(digits)}%`;
const dec = (n: number) => n.toLocaleString();

function inRange(iso: string, since: Date | null): boolean {
  if (!since) return true;
  return new Date(iso) >= since;
}

function withinDays(iso: string | null, days: number): boolean {
  if (!iso) return false;
  return Date.now() - new Date(iso).getTime() <= days * 86400_000;
}

// Build email → niche_slug lookup keyed by `${profile_slug}|${email}` so the
// same email reused across two clients keeps its right niche.
function buildNicheLookup(prospects: DbProspect[]): Map<string, string | null> {
  const m = new Map<string, string | null>();
  for (const p of prospects) m.set(`${p.profile_slug}|${p.email.toLowerCase()}`, p.niche_slug);
  return m;
}

// ─── Production-only filter ──────────────────────────────────────────────
// Supabase contains months of pre-system test data (legacy personas like
// daniel/marco/olivia, business-correspondence replies to info@aureonglobal.de
// from CRM tools, invoices, Wolt signup emails, etc). The dashboard is for
// the LIVE outreach campaigns only — filter everything to current production.
//
// A send counts as production iff persona_slug is one of the live ones AND
// from_addr's subdomain is part of an active profile's pool.
//
// A reply counts as a real outreach reply iff it was matched to one of our
// sends (run_id is not null) OR its To: address is an outreach sender
// subdomain (where prospect replies land — never info@aureonglobal.de
// which is the operator's main business inbox).
const PRODUCTION_PERSONAS = new Set(["anna", "tomas", "lukas"]);
const ACTIVE_PROFILE_SLUGS = new Set(["aureon", "algoalpha", "f2-malergipser"]);

function buildActiveSubdomains(profiles: DbProfile[]): Set<string> {
  const out = new Set<string>();
  for (const p of profiles) {
    if (!ACTIVE_PROFILE_SLUGS.has(p.slug)) continue;
    const pool = (p.config?.relay?.from_domains ?? []) as any[];
    for (const d of pool) if (d?.domain) out.add(d.domain);
  }
  return out;
}

function isProductionSend(s: DbSendLog, activeSubdomains: Set<string>): boolean {
  if (!PRODUCTION_PERSONAS.has(s.persona_slug ?? "")) return false;
  const domain = (s.from_addr.split("@")[1] || "").toLowerCase();
  return activeSubdomains.has(domain);
}

function isProductionReply(r: DbReply, activeSubdomains: Set<string>): boolean {
  if (r.class !== "reply") return false;
  if (r.run_id) return true;
  const domain = (r.to_addr.split("@")[1] || "").toLowerCase();
  return activeSubdomains.has(domain);
}

// ─── Reply-intent classifier ──────────────────────────────────────────────
// Computed client-side so we don't need a schema migration. Operates on the
// subject + body_snippet + from_addr of a reply row. Order matters: auto and
// unsubscribe are checked first because their keywords sometimes also appear
// in a "positive" interpretation ("yes please remove" is unsubscribe, not
// positive). Returns one of:
//   positive    - explicit interest / scheduling / yes
//   negative    - explicit no / not interested / wrong contact
//   auto_reply  - out-of-office / vacation / autoresponder
//   unsubscribe - hard remove / GDPR / "don't email"
//   neutral     - has reply markers but no clear intent (forwards, questions)
export type ReplyIntent = "positive" | "negative" | "auto_reply" | "unsubscribe" | "neutral";

const AUTO_RX = /\b(out of office|out-of-office|vacation|abwesenheits?notiz|automatic(?:ally)?\s+reply|auto[-\s]?reply|abwesend|ferien|on (?:vacation|holiday|leave)|away from|automatische antwort|paternity|maternity)\b/i;
const UNSUB_RX = /\b(unsubscribe|abmelden|austragen|remove me from|please remove|stop sending|stop emailing|do not (?:contact|email)|gdpr (?:request|removal)|cease and desist|nicht mehr (?:kontakt|email|mail))\b/i;
const NEG_RX  = /\b(not interested|nicht interess(?:iert|ant)|kein interesse|no thanks|nein danke|not relevant|wrong person|wrong contact|wrong number|please stop|stop contact|not for us|not a fit|won'?t be|nicht passend|no thank you)\b/i;
const POS_RX  = /\b(interested|interess(?:iert|ant)|let'?s (?:chat|talk|schedule|hop on|jump on)|gerne|sounds good|happy to (?:chat|talk|jump)|please send|share more|tell me more|book a call|book a time|schedule a (?:call|time|meeting)|when (?:are you|works for you)|sure|absolutely|yes,? (?:please|happy|absolutely)|let me know more|melde mich|melden sie sich|machen wir|passt mir|gerne ein gespr|gerne mehr)\b/i;

export function classifyReplyIntent(r: DbReply): ReplyIntent {
  const hay = `${r.subject || ""} \n ${r.body_snippet || ""}`;
  if (AUTO_RX.test(hay))   return "auto_reply";
  if (UNSUB_RX.test(hay))  return "unsubscribe";
  if (NEG_RX.test(hay))    return "negative";
  if (POS_RX.test(hay))    return "positive";
  return "neutral";
}

// Map persona_slug to its owning profile_slug. Persona slugs are unique
// across the personas array of every profile in our setup.
function buildPersonaToProfile(profiles: DbProfile[]): Map<string, string> {
  const m = new Map<string, string>();
  for (const p of profiles) {
    const personas = (p.config?.personas ?? []) as { slug: string }[];
    for (const persona of personas) m.set(persona.slug, p.slug);
  }
  return m;
}

// ─── Component ─────────────────────────────────────────────────────────────

export function Analytics() {
  const [profiles, setProfiles]   = useState<DbProfile[]>([]);
  const [prospects, setProspects] = useState<DbProspect[]>([]);
  const [sends, setSends]         = useState<DbSendLog[]>([]);
  const [replies, setReplies]     = useState<DbReply[]>([]);
  const [loaded, setLoaded]       = useState(false);
  const [range, setRange]         = useState<RangeKey>("30d");
  const [profileFilter, setProfileFilter] = useState<string>("__all__");

  async function refresh() {
    if (!isConfigured()) { setLoaded(true); return; }
    const [ps, pr, sl, rp] = await Promise.all([
      fetchProfiles(),
      fetchProspects(undefined, 10_000),
      fetchSendLog(10_000),
      fetchReplies(2_000),
    ]);
    // Filter raw send_log + replies down to production rows: live personas,
    // active subdomains, and replies actually tied to one of our sends.
    // Without this filter the dashboard double-counts pre-system test data
    // (legacy daniel/marco personas, business-mail replies to info@).
    const activeSub = buildActiveSubdomains(ps);
    setProfiles(ps);
    setProspects(pr);
    setSends(sl.filter(s => isProductionSend(s, activeSub)));
    setReplies(rp.filter(r => isProductionReply(r, activeSub)));
    setLoaded(true);
  }
  useEffect(() => {
    refresh();
    const subs = [
      subscribeToTable("send_log", refresh),
      subscribeToTable("replies",  refresh),
      subscribeToTable("profiles", refresh),
    ];
    return () => subs.forEach(u => u());
  }, []);

  // Derived: lookups + filters
  const personaToProfile = useMemo(() => buildPersonaToProfile(profiles), [profiles]);
  const nicheLookup      = useMemo(() => buildNicheLookup(prospects),     [prospects]);

  const rangeDays = RANGES.find(r => r.key === range)?.days ?? null;
  const sinceDate = rangeDays === null ? null
                    : new Date(Date.now() - rangeDays * 86400_000);

  // Filter sends to the selected range + profile
  const filteredSends = useMemo(() => sends.filter(s => {
    if (!inRange(s.sent_at, sinceDate)) return false;
    if (profileFilter === "__all__") return true;
    const profSlug = personaToProfile.get(s.persona_slug ?? "") ?? null;
    return profSlug === profileFilter;
  }), [sends, sinceDate, profileFilter, personaToProfile]);

  const filteredReplies = useMemo(() => replies.filter(r => {
    if (!inRange(r.received_at, sinceDate)) return false;
    if (profileFilter === "__all__") return true;
    // Match reply.from_addr → prospect (any profile) → profile_slug
    // Lazy match: fall back to "no profile filter" if we cannot resolve.
    const matchedProf = prospects.find(p => p.email.toLowerCase() === r.from_addr.toLowerCase());
    return matchedProf ? matchedProf.profile_slug === profileFilter : false;
  }), [replies, sinceDate, profileFilter, prospects]);

  const filteredProspects = useMemo(() => prospects.filter(p =>
    profileFilter === "__all__" || p.profile_slug === profileFilter
  ), [prospects, profileFilter]);

  // ─── Headline KPIs ──────────────────────────────────────────────────────
  const total       = filteredSends.length;
  const delivered   = filteredSends.filter(s => s.delivered && !s.bounced).length;
  const bounced     = filteredSends.filter(s => s.bounced).length;
  const complained  = filteredSends.filter(s => s.complained).length;
  const opened      = filteredSends.filter(s => s.opened_at).length;
  const clicked     = filteredSends.filter(s => s.clicked_at).length;
  const repliedSends = filteredSends.filter(s => s.replied).length;
  const realReplies = filteredReplies.filter(r => r.class === "reply").length;
  const uniqueSendees = new Set(filteredSends.map(s => s.to_addr.toLowerCase())).size;
  const unsubsInRange = filteredProspects.filter(p =>
    p.unsubscribed && inRange(p.unsubscribed_at || "", sinceDate)
  ).length;

  // ─── Trend (daily volume + replies) ─────────────────────────────────────
  const trendData = useMemo(() => {
    const m = new Map<string, { date: string; sent: number; delivered: number; bounced: number; replied: number }>();
    const winDays = Math.min(rangeDays ?? 90, 90);
    // Pre-fill all days in window so chart shows zeros, not gaps
    for (let i = winDays - 1; i >= 0; i--) {
      const d = new Date(Date.now() - i * 86400_000).toISOString().slice(0, 10);
      m.set(d, { date: d, sent: 0, delivered: 0, bounced: 0, replied: 0 });
    }
    for (const s of filteredSends) {
      const d = day(s.sent_at);
      const row = m.get(d); if (!row) continue;
      row.sent++;
      if (s.delivered && !s.bounced) row.delivered++;
      if (s.bounced) row.bounced++;
      if (s.replied) row.replied++;
    }
    return [...m.values()];
  }, [filteredSends, rangeDays]);

  // ─── Per-client (profile) breakdown ────────────────────────────────────
  const byProfile = useMemo(() => {
    const m = new Map<string, { name: string; sent: number; delivered: number; bounced: number; replied: number; complaint: number; opened: number; clicked: number; unsubs: number }>();
    for (const p of profiles)
      m.set(p.slug, { name: p.name, sent: 0, delivered: 0, bounced: 0, replied: 0, complaint: 0, opened: 0, clicked: 0, unsubs: 0 });
    for (const s of filteredSends) {
      const slug = personaToProfile.get(s.persona_slug ?? "") ?? "(unknown)";
      const row = m.get(slug) ?? m.set(slug, { name: slug, sent: 0, delivered: 0, bounced: 0, replied: 0, complaint: 0, opened: 0, clicked: 0, unsubs: 0 }).get(slug)!;
      row.sent++;
      if (s.delivered && !s.bounced) row.delivered++;
      if (s.bounced)    row.bounced++;
      if (s.replied)    row.replied++;
      if (s.complained) row.complaint++;
      if (s.opened_at)  row.opened++;
      if (s.clicked_at) row.clicked++;
    }
    for (const p of filteredProspects) {
      if (p.unsubscribed && inRange(p.unsubscribed_at || "", sinceDate)) {
        const row = m.get(p.profile_slug); if (row) row.unsubs++;
      }
    }
    return [...m.entries()]
      .map(([slug, r]) => ({ slug, ...r }))
      .filter(r => r.sent > 0 || r.unsubs > 0)
      .sort((a, b) => b.sent - a.sent);
  }, [profiles, filteredSends, filteredProspects, personaToProfile, sinceDate]);

  // ─── Per sending domain (warmup pool view) ──────────────────────────────
  // The sending pool is each profile's relay.from_domains[]. We attribute
  // every send_log row to its subdomain via from_addr, then surface volume
  // + reputation + warmup day per subdomain. This is the table to watch to
  // make sure no single domain is getting flagged.
  const byDomain = useMemo(() => {
    const m = new Map<string, {
      domain: string; profile: string;
      sent: number; delivered: number; bounced: number; replied: number; complained: number;
      currentDay: number; ceiling: number; verified: boolean;
    }>();
    // Seed from profile config so every configured domain is visible even
    // if it hasn't sent anything yet.
    for (const p of profiles) {
      if (profileFilter !== "__all__" && p.slug !== profileFilter) continue;
      const pool = (p.config?.relay?.from_domains ?? []) as any[];
      for (const d of pool) {
        const dn = d.domain;
        if (!dn) continue;
        m.set(`${p.slug}|${dn}`, {
          domain: dn, profile: p.name,
          sent: 0, delivered: 0, bounced: 0, replied: 0, complained: 0,
          currentDay: (d.warmup?.current_day ?? 0),
          ceiling:    (d.warmup?.max_daily_sends ?? 0),
          verified:   Boolean(d.verified_at),
        });
      }
    }
    for (const s of filteredSends) {
      const profSlug = personaToProfile.get(s.persona_slug ?? "") ?? "(unknown)";
      const dn = (s.from_addr.split("@")[1] || "").toLowerCase();
      const key = `${profSlug}|${dn}`;
      const row = m.get(key); if (!row) continue;
      row.sent++;
      if (s.delivered && !s.bounced) row.delivered++;
      if (s.bounced)    row.bounced++;
      if (s.replied)    row.replied++;
      if (s.complained) row.complained++;
    }
    return [...m.values()].sort((a, b) => b.sent - a.sent);
  }, [profiles, filteredSends, personaToProfile, profileFilter]);

  // ─── Per-persona ────────────────────────────────────────────────────────
  const byPersona = useMemo(() => {
    const m = new Map<string, { sent: number; delivered: number; bounced: number; replied: number }>();
    for (const s of filteredSends) {
      const k = s.persona_slug || "(none)";
      const row = m.get(k) ?? m.set(k, { sent: 0, delivered: 0, bounced: 0, replied: 0 }).get(k)!;
      row.sent++;
      if (s.delivered && !s.bounced) row.delivered++;
      if (s.bounced) row.bounced++;
      if (s.replied) row.replied++;
    }
    return [...m.entries()].map(([slug, r]) => ({ slug, ...r })).sort((a, b) => b.sent - a.sent);
  }, [filteredSends]);

  // ─── Per-niche ──────────────────────────────────────────────────────────
  const byNiche = useMemo(() => {
    const m = new Map<string, { sent: number; delivered: number; bounced: number; replied: number; prospects: number }>();
    for (const p of filteredProspects) {
      const k = p.niche_slug || "(none)";
      const row = m.get(k) ?? m.set(k, { sent: 0, delivered: 0, bounced: 0, replied: 0, prospects: 0 }).get(k)!;
      row.prospects++;
    }
    for (const s of filteredSends) {
      const profSlug = personaToProfile.get(s.persona_slug ?? "");
      if (!profSlug) continue;
      const key = `${profSlug}|${s.to_addr.toLowerCase()}`;
      const niche = nicheLookup.get(key) || "(none)";
      const row = m.get(niche) ?? m.set(niche, { sent: 0, delivered: 0, bounced: 0, replied: 0, prospects: 0 }).get(niche)!;
      row.sent++;
      if (s.delivered && !s.bounced) row.delivered++;
      if (s.bounced) row.bounced++;
      if (s.replied) row.replied++;
    }
    return [...m.entries()].map(([slug, r]) => ({ slug, ...r })).sort((a, b) => b.sent - a.sent);
  }, [filteredProspects, filteredSends, nicheLookup, personaToProfile]);

  // ─── Per-step (where does the conversion happen?) ───────────────────────
  const byStep = useMemo(() => {
    const m = new Map<number, { sent: number; delivered: number; replied: number }>();
    for (const s of filteredSends) {
      const row = m.get(s.step_n) ?? m.set(s.step_n, { sent: 0, delivered: 0, replied: 0 }).get(s.step_n)!;
      row.sent++;
      if (s.delivered && !s.bounced) row.delivered++;
      if (s.replied) row.replied++;
    }
    return [...m.entries()].map(([n, r]) => ({ step: n, ...r })).sort((a, b) => a.step - b.step);
  }, [filteredSends]);

  // ─── Reply-intent breakdown (positive / negative / auto / unsub) ────────
  // Live-classified via classifyReplyIntent. The raw `reply` rows from imap
  // include forwards, OOO bounces, and noise; this split is the real
  // "is this conversation going somewhere?" view.
  const replyIntents = useMemo(() => {
    const real = filteredReplies.filter(r => r.class === "reply");
    const buckets: Record<ReplyIntent, number> = {
      positive: 0, negative: 0, auto_reply: 0, unsubscribe: 0, neutral: 0,
    };
    for (const r of real) buckets[classifyReplyIntent(r)]++;
    return buckets;
  }, [filteredReplies]);

  // ─── Per-step engagement funnel ─────────────────────────────────────────
  // Each step row shows the cascade sent > delivered > opened > replied
  // > positive_replied, with rates relative to step's own sent count.
  // The drop-off pattern is the cadence signal: if step 6 sends a lot
  // but yields ~0 positive replies, the cadence is too long.
  const stepFunnel = useMemo(() => {
    type Row = { step: number; sent: number; delivered: number; opened: number;
                 replied: number; positive: number; };
    const m = new Map<number, Row>();
    // Build positive-reply lookup keyed by to_addr (lowercase). We do not
    // have a clean send_log↔reply join key, so attribute by recipient.
    const posByEmail = new Set(
      filteredReplies
        .filter(r => r.class === "reply" && classifyReplyIntent(r) === "positive")
        .map(r => r.from_addr.toLowerCase())
    );
    for (const s of filteredSends) {
      const row = m.get(s.step_n) ?? m.set(s.step_n,
        { step: s.step_n, sent: 0, delivered: 0, opened: 0, replied: 0, positive: 0 }
      ).get(s.step_n)!;
      row.sent++;
      if (s.delivered && !s.bounced) row.delivered++;
      if (s.opened_at) row.opened++;
      if (s.replied)   row.replied++;
      if (posByEmail.has(s.to_addr.toLowerCase())) row.positive++;
    }
    return [...m.values()].sort((a, b) => a.step - b.step);
  }, [filteredSends, filteredReplies]);

  // ─── Per-subdomain rolling 7-day health ─────────────────────────────────
  // The fast-warning view: any subdomain whose bounce-rate has spiked over
  // the last 7 days is the next one Resend will deactivate. We compute
  // independently from the global `sends` (not filtered by date range) so
  // the 7-day window is exact regardless of which range filter is active.
  const subdomainHealth = useMemo(() => {
    const cutoff = new Date(Date.now() - 7 * 86400_000);
    type Row = { domain: string; profile: string; sent: number; delivered: number;
                 bounced: number; complained: number; opened: number;
                 bounceRate: number; complaintRate: number; openRate: number; };
    const m = new Map<string, Row>();
    for (const p of profiles) {
      const pool = (p.config?.relay?.from_domains ?? []) as any[];
      for (const d of pool) {
        if (!d.domain) continue;
        m.set(d.domain, {
          domain: d.domain, profile: p.name,
          sent: 0, delivered: 0, bounced: 0, complained: 0, opened: 0,
          bounceRate: 0, complaintRate: 0, openRate: 0,
        });
      }
    }
    for (const s of sends) {
      if (new Date(s.sent_at) < cutoff) continue;
      const dn = (s.from_addr.split("@")[1] || "").toLowerCase();
      const row = m.get(dn); if (!row) continue;
      row.sent++;
      if (s.delivered && !s.bounced) row.delivered++;
      if (s.bounced)    row.bounced++;
      if (s.complained) row.complained++;
      if (s.opened_at)  row.opened++;
    }
    for (const r of m.values()) {
      r.bounceRate    = r.sent ? r.bounced / r.sent : 0;
      r.complaintRate = r.sent ? r.complained / r.sent : 0;
      r.openRate      = r.delivered ? r.opened / r.delivered : 0;
    }
    return [...m.values()]
      .filter(r => r.sent > 0)
      .sort((a, b) => b.bounceRate - a.bounceRate || b.sent - a.sent);
  }, [profiles, sends]);

  // ─── Persona head-to-head ───────────────────────────────────────────────
  // Same metrics across personas so anna vs tomas vs lukas can be compared
  // directly. Adds open-rate (now meaningful with tracker enabled) and
  // positive-reply rate (engagement-quality signal) on top of the simpler
  // byPersona aggregation that's already shown above.
  const personaCompare = useMemo(() => {
    const posByEmail = new Set(
      filteredReplies
        .filter(r => r.class === "reply" && classifyReplyIntent(r) === "positive")
        .map(r => r.from_addr.toLowerCase())
    );
    type Row = { persona: string; profile: string; sent: number; delivered: number;
                 opened: number; bounced: number; replied: number; positive: number; };
    const m = new Map<string, Row>();
    for (const s of filteredSends) {
      const k = s.persona_slug || "(none)";
      const profSlug = personaToProfile.get(s.persona_slug ?? "") ?? "(unknown)";
      const profName = profiles.find(p => p.slug === profSlug)?.name ?? profSlug;
      const row = m.get(k) ?? m.set(k,
        { persona: k, profile: profName, sent: 0, delivered: 0, opened: 0,
          bounced: 0, replied: 0, positive: 0 }
      ).get(k)!;
      row.sent++;
      if (s.delivered && !s.bounced) row.delivered++;
      if (s.opened_at) row.opened++;
      if (s.bounced)   row.bounced++;
      if (s.replied)   row.replied++;
      if (posByEmail.has(s.to_addr.toLowerCase())) row.positive++;
    }
    return [...m.values()].sort((a, b) => b.sent - a.sent);
  }, [filteredSends, filteredReplies, personaToProfile, profiles]);

  // ─── Reputation status (per profile) ────────────────────────────────────
  const reputation = useMemo(() => {
    return profiles
      .filter(p => profileFilter === "__all__" || p.slug === profileFilter)
      .map(p => {
        const wm = p.config?.warmup ?? {};
        const rep = wm.reputation ?? {};
        const th  = wm.auto_pause_thresholds ?? { bounce_rate: 0.05, complaint_rate: 0.001 };
        // Rolling 7d from local data (more accurate than the cached snapshot)
        const cutoff = new Date(Date.now() - 7 * 86400_000);
        const last7 = sends.filter(s => {
          if (new Date(s.sent_at) < cutoff) return false;
          const ps = personaToProfile.get(s.persona_slug ?? ""); return ps === p.slug;
        });
        const sent7      = last7.length;
        const bounced7   = last7.filter(s => s.bounced).length;
        const compl7     = last7.filter(s => s.complained).length;
        const delivered7 = last7.filter(s => s.delivered && !s.bounced).length;
        return {
          slug:  p.slug,
          name:  p.name,
          sent7, bounced7, complained: compl7, delivered7,
          bounce_rate_7d:    sent7 ? bounced7 / sent7 : 0,
          complaint_rate_7d: sent7 ? compl7  / sent7 : 0,
          bounce_threshold:    th.bounce_rate,
          complaint_threshold: th.complaint_rate,
          // Also report the profile's cached snapshot when present (some hooks
          // update reputation outside the IMAP pass, e.g. Resend webhooks).
          cached_bounce_rate:    rep.bounce_rate_7d ?? null,
          cached_complaint_rate: rep.complaint_rate_7d ?? null,
        };
      });
  }, [profiles, sends, personaToProfile, profileFilter]);

  // ─── List health (verified / unsubscribed / replied prospects per profile) ──
  const listHealth = useMemo(() => {
    const m = new Map<string, { total: number; verified: number; unsubscribed: number; replied: number; bounced: number }>();
    for (const p of filteredProspects) {
      const k = p.profile_slug;
      const row = m.get(k) ?? m.set(k, { total: 0, verified: 0, unsubscribed: 0, replied: 0, bounced: 0 }).get(k)!;
      row.total++;
      if (p.verified)     row.verified++;
      if (p.unsubscribed) row.unsubscribed++;
    }
    // Replied / bounced — derive from send_log + replies
    const repliedEmails = new Set(filteredReplies.filter(r => r.class === "reply").map(r => r.from_addr.toLowerCase()));
    const bouncedEmails = new Set(filteredSends.filter(s => s.bounced).map(s => s.to_addr.toLowerCase()));
    for (const p of filteredProspects) {
      const row = m.get(p.profile_slug); if (!row) continue;
      if (repliedEmails.has(p.email.toLowerCase())) row.replied++;
      if (bouncedEmails.has(p.email.toLowerCase())) row.bounced++;
    }
    return [...m.entries()].map(([slug, r]) => ({ slug, ...r })).sort((a, b) => b.total - a.total);
  }, [filteredProspects, filteredReplies, filteredSends]);

  // ─── Render ─────────────────────────────────────────────────────────────
  if (!isConfigured()) {
    return (<><h1 className="page-title">Analytics</h1>
      <EmptyState variant="not-connected"
                  title="Configure Supabase first"
                  message="Analytics aggregate live data from Supabase."
                  hint="Settings → Cross-PC sync → paste URL + anon key." /></>);
  }
  if (!loaded) return (<><h1 className="page-title">Analytics</h1><EmptyState variant="loading" /></>);

  const replyRate    = total ? realReplies / total : 0;
  const bounceRate   = total ? bounced / total : 0;
  const complaintRate = total ? complained / total : 0;
  const unsubRate    = uniqueSendees ? unsubsInRange / uniqueSendees : 0;
  const deliveryRate = total ? delivered / total : 0;

  return (
    <>
      <div className="row justify" style={{ alignItems: "center", marginBottom: 8 }}>
        <h1 className="page-title" style={{ margin: 0 }}>Campaign analytics</h1>
        <div className="row gap-2">
          <select value={profileFilter} onChange={e => setProfileFilter(e.target.value)}>
            <option value="__all__">All clients</option>
            {profiles.map(p => <option key={p.slug} value={p.slug}>{p.name}</option>)}
          </select>
          <div className="row gap-2" style={{ background: "rgba(255,255,255,0.04)", padding: "2px", borderRadius: 6 }}>
            {RANGES.map(r => (
              <button key={r.key}
                      onClick={() => setRange(r.key)}
                      className={range === r.key ? "primary" : ""}
                      style={{ padding: "4px 10px", fontSize: 12 }}>
                {r.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      <p className="page-sub">Live cross-PC view of every send, reply, bounce, complaint, open, click, and unsubscribe. Filtered to {profileFilter === "__all__" ? "all clients" : profiles.find(p => p.slug === profileFilter)?.name} over {RANGES.find(r => r.key === range)?.label.toLowerCase()}.</p>

      {/* Headline KPIs */}
      <div className="grid grid-4" style={{ marginBottom: 16 }}>
        <Kpi label="Sent"            value={dec(total)}      sub={`${dec(uniqueSendees)} unique recipients`} />
        <Kpi label="Delivered"       value={pct(delivered, total)} accent="green" sub={`${dec(delivered)} delivered`} />
        <Kpi label="Replied"         value={pct(realReplies, total)} accent="green" sub={`${dec(realReplies)} replies`} />
        <Kpi label="Unsubscribed"    value={pct(unsubsInRange, uniqueSendees)} accent={unsubRate > 0.02 ? "amber" : undefined} sub={`${dec(unsubsInRange)} in window`} />
      </div>

      {/* Quality KPIs */}
      <div className="grid grid-4" style={{ marginBottom: 16 }}>
        <Kpi label="Bounce rate"     value={pct(bounced, total)}      accent={bounceRate > 0.05 ? "red" : "green"}  sub="target < 5%" />
        <Kpi label="Complaint rate"  value={pct(complained, total, 2)} accent={complaintRate > 0.001 ? "red" : "green"} sub="target < 0.1%" />
        <Kpi label="Open rate"       value={pct(opened, delivered)}    accent="cyan"  sub="of delivered (tracker required)" />
        <Kpi label="Click rate"      value={pct(clicked, delivered)}   accent="cyan"  sub="of delivered" />
      </div>

      {/* Trend chart */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Daily volume</h3>
        <div style={{ height: 260 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={trendData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#9ca3af" }} />
              <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} />
              <Tooltip contentStyle={{ background: "#1f1f1f", border: "1px solid #2a2a2a", fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="delivered" stackId="a" fill="#22c55e" name="Delivered" />
              <Bar dataKey="bounced"   stackId="a" fill="#ef4444" name="Bounced" />
              <Bar dataKey="replied"   fill="#E6C259" name="Replied" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Funnel */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Funnel</h3>
        <FunnelRow label="Prospects (total)"    value={filteredProspects.length} bar={1} />
        <FunnelRow label="Verified prospects"   value={filteredProspects.filter(p => p.verified).length} bar={filteredProspects.filter(p => p.verified).length / Math.max(filteredProspects.length, 1)} />
        <FunnelRow label="Contacted (unique)"   value={uniqueSendees} bar={uniqueSendees / Math.max(filteredProspects.filter(p => p.verified).length, 1)} />
        <FunnelRow label="Delivered"            value={delivered} bar={delivered / Math.max(total, 1)} />
        <FunnelRow label="Opened"               value={opened} bar={opened / Math.max(delivered, 1)} sub="tracker pixel required" />
        <FunnelRow label="Replied"              value={realReplies} bar={realReplies / Math.max(delivered, 1)} />
        <FunnelRow label="Unsubscribed"         value={unsubsInRange} bar={unsubsInRange / Math.max(uniqueSendees, 1)} negative />
      </div>

      {/* Reply quality split — positive vs negative vs auto vs unsub */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Reply quality</h3>
        <p className="page-sub" style={{ marginTop: 0, marginBottom: 10 }}>
          Live-classified intent of every reply. <code>positive</code> + <code>neutral</code> are the conversations worth working; <code>auto_reply</code> + <code>unsubscribe</code> are noise to filter out of raw reply counts.
        </p>
        {realReplies === 0
          ? <div style={{ color: "var(--fg-2)", padding: 8 }}>No real replies in window yet.</div>
          : (<>
            <div className="grid grid-5" style={{ marginBottom: 8 }}>
              <Kpi label="Positive"    value={dec(replyIntents.positive)}    accent="green" sub={pct(replyIntents.positive, realReplies)} />
              <Kpi label="Neutral"     value={dec(replyIntents.neutral)}                    sub={pct(replyIntents.neutral, realReplies)} />
              <Kpi label="Negative"    value={dec(replyIntents.negative)}    accent="amber" sub={pct(replyIntents.negative, realReplies)} />
              <Kpi label="Auto-reply"  value={dec(replyIntents.auto_reply)}                 sub={pct(replyIntents.auto_reply, realReplies)} />
              <Kpi label="Unsubscribe" value={dec(replyIntents.unsubscribe)} accent="red"   sub={pct(replyIntents.unsubscribe, realReplies)} />
            </div>
            <div style={{ height: 220 }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={[
                  { name: "Positive",    n: replyIntents.positive,    fill: "#22c55e" },
                  { name: "Neutral",     n: replyIntents.neutral,     fill: "#9ca3af" },
                  { name: "Negative",    n: replyIntents.negative,    fill: "#f59e0b" },
                  { name: "Auto-reply",  n: replyIntents.auto_reply,  fill: "#3b82f6" },
                  { name: "Unsubscribe", n: replyIntents.unsubscribe, fill: "#ef4444" },
                ]} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke="rgba(255,255,255,0.05)" vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#9ca3af" }} />
                  <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} allowDecimals={false} />
                  <Tooltip contentStyle={{ background: "#1f1f1f", border: "1px solid #2a2a2a", fontSize: 12 }} />
                  <Bar dataKey="n" name="Replies" fill="#E6C259" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </>)}
      </div>

      {/* Per-step engagement funnel (cadence signal) */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Per-step engagement funnel</h3>
        <p className="page-sub" style={{ marginTop: 0, marginBottom: 10 }}>
          Where the conversation actually happens. If step 6+ shows healthy <code>sent</code> but tiny <code>positive</code>, the cadence is too long — cut it.
        </p>
        {stepFunnel.length === 0
          ? <div style={{ color: "var(--fg-2)", padding: 8 }}>No step-tagged sends in window.</div>
          : (<table className="tbl">
            <thead>
              <tr>
                <th>Step</th><th>Sent</th><th>Delivered</th>
                <th>Open rate</th><th>Reply rate</th><th>Positive</th><th>Pos rate</th>
              </tr>
            </thead>
            <tbody>
              {stepFunnel.map(r => (
                <tr key={r.step}>
                  <td><span className="pill">step {r.step}</span></td>
                  <td>{dec(r.sent)}</td>
                  <td>{dec(r.delivered)}</td>
                  <td>{pct(r.opened, r.delivered)}</td>
                  <td>{pct(r.replied, r.delivered)}</td>
                  <td style={{ color: r.positive > 0 ? "var(--accent-green)" : undefined }}>{r.positive || "—"}</td>
                  <td>{pct(r.positive, r.delivered, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>)}
      </div>

      {/* Per-subdomain rolling 7-day health */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Subdomain health (rolling 7 days)</h3>
        <p className="page-sub" style={{ marginTop: 0, marginBottom: 10 }}>
          Early-warning view. Subdomains with bounce ≥ 5% or complaint ≥ 0.1% are flagged red — Resend will deactivate them if these stay elevated.
        </p>
        {subdomainHealth.length === 0
          ? <div style={{ color: "var(--fg-2)", padding: 8 }}>No sends in last 7 days.</div>
          : (<table className="tbl">
            <thead>
              <tr>
                <th>Subdomain</th><th>Client</th><th>7d sent</th><th>Delivered</th>
                <th>Bounce %</th><th>Complaint %</th><th>Open %</th><th>Status</th>
              </tr>
            </thead>
            <tbody>
              {subdomainHealth.map(r => {
                const isBad = r.bounceRate > 0.05 || r.complaintRate > 0.001;
                const isWarn = r.bounceRate > 0.025 || r.complaintRate > 0.0005;
                const status = isBad ? "ALERT" : isWarn ? "warn" : "OK";
                const statusColor = isBad ? "var(--accent-red)" : isWarn ? "var(--accent-amber)" : "var(--accent-green)";
                return (
                  <tr key={r.domain}>
                    <td style={{ fontFamily: "var(--mono)" }}>{r.domain}</td>
                    <td>{r.profile}</td>
                    <td>{dec(r.sent)}</td>
                    <td>{dec(r.delivered)}</td>
                    <td style={{ color: r.bounceRate > 0.05 ? "var(--accent-red)" : r.bounceRate > 0.025 ? "var(--accent-amber)" : undefined }}>
                      {pct(r.bounced, r.sent)}
                    </td>
                    <td style={{ color: r.complaintRate > 0.001 ? "var(--accent-red)" : undefined }}>
                      {pct(r.complained, r.sent, 2)}
                    </td>
                    <td>{pct(r.opened, r.delivered)}</td>
                    <td style={{ color: statusColor, fontWeight: 600 }}>{status}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>)}
      </div>

      {/* Persona head-to-head */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Persona head-to-head</h3>
        <p className="page-sub" style={{ marginTop: 0, marginBottom: 10 }}>
          Side-by-side performance per sender persona, with open-rate and positive-reply-rate. Diverging open rates between personas signal signature/tone differences worth copying — diverging delivery rates signal an underlying domain/IP reputation issue isolated to one persona.
        </p>
        {personaCompare.length === 0
          ? <div style={{ color: "var(--fg-2)", padding: 8 }}>No sends in window.</div>
          : (<table className="tbl">
            <thead>
              <tr>
                <th>Persona</th><th>Client</th><th>Sent</th><th>Delivery %</th>
                <th>Open %</th><th>Reply %</th><th>Positive</th><th>Pos rate</th>
              </tr>
            </thead>
            <tbody>
              {personaCompare.map(r => (
                <tr key={r.persona}>
                  <td><span className="pill">{r.persona}</span></td>
                  <td>{r.profile}</td>
                  <td>{dec(r.sent)}</td>
                  <td>{pct(r.delivered, r.sent)}</td>
                  <td>{pct(r.opened, r.delivered)}</td>
                  <td>{pct(r.replied, r.delivered)}</td>
                  <td style={{ color: r.positive > 0 ? "var(--accent-green)" : undefined }}>{r.positive || "—"}</td>
                  <td>{pct(r.positive, r.delivered, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>)}
      </div>

      {/* Per-client (only when "All clients") */}
      {profileFilter === "__all__" && byProfile.length > 0 && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>Per client</h3>
          <table className="tbl">
            <thead><tr><th>Client</th><th>Sent</th><th>Delivered</th><th>Bounced</th><th>Replied</th><th>Reply rate</th><th>Bounce rate</th><th>Unsubs</th></tr></thead>
            <tbody>
              {byProfile.map(r => (
                <tr key={r.slug}>
                  <td>{r.name} <span className="pill" style={{ marginLeft: 6 }}>{r.slug}</span></td>
                  <td>{dec(r.sent)}</td>
                  <td>{dec(r.delivered)}</td>
                  <td style={{ color: r.bounced > 0 ? "var(--accent-red)" : undefined }}>{r.bounced || "—"}</td>
                  <td>{r.replied || "—"}</td>
                  <td>{pct(r.replied, r.sent)}</td>
                  <td style={{ color: r.sent && r.bounced / r.sent > 0.05 ? "var(--accent-red)" : undefined }}>{pct(r.bounced, r.sent)}</td>
                  <td>{r.unsubs || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Per-persona */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Per persona</h3>
        {byPersona.length === 0
          ? <div style={{ color: "var(--fg-2)", padding: 8 }}>No sends in window.</div>
          : (<table className="tbl">
            <thead><tr><th>Persona</th><th>Sent</th><th>Delivered</th><th>Bounced</th><th>Replied</th><th>Reply rate</th><th>Delivery rate</th></tr></thead>
            <tbody>
              {byPersona.map(r => (
                <tr key={r.slug}>
                  <td><span className="pill">{r.slug}</span></td>
                  <td>{dec(r.sent)}</td>
                  <td>{dec(r.delivered)}</td>
                  <td>{r.bounced || "—"}</td>
                  <td>{r.replied || "—"}</td>
                  <td>{pct(r.replied, r.sent)}</td>
                  <td>{pct(r.delivered, r.sent)}</td>
                </tr>
              ))}
            </tbody>
          </table>)}
      </div>

      {/* Per sending domain (warmup pool) */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Per sending domain (warmup pool)</h3>
        <p className="page-sub" style={{ marginTop: 0, marginBottom: 10 }}>
          Each subdomain in <code>relay.from_domains</code> warms independently. The rotation routes new sends to whichever subdomain has the most room left today, so no single one spikes.
        </p>
        {byDomain.length === 0
          ? <div style={{ color: "var(--fg-2)", padding: 8 }}>No domains in pool yet. Add one with <code>py sequences/provision_subdomain.py add &lt;profile&gt; &lt;subdomain&gt;</code>.</div>
          : (<table className="tbl">
            <thead>
              <tr>
                <th>Domain</th><th>Client</th><th>Verified</th><th>Day</th><th>Sent</th><th>Delivered</th>
                <th>Bounced</th><th>Replied</th><th>Reply rate</th><th>Bounce rate</th>
              </tr>
            </thead>
            <tbody>
              {byDomain.map(r => {
                const bRate = r.sent ? r.bounced / r.sent : 0;
                const bRed  = bRate > 0.05;
                return (
                  <tr key={r.domain}>
                    <td style={{ fontFamily: "var(--mono)" }}>{r.domain}</td>
                    <td style={{ fontSize: 12, color: "var(--fg-2)" }}>{r.profile}</td>
                    <td>{r.verified ? <span className="pill green">verified</span> : <span className="pill amber">pending</span>}</td>
                    <td>{r.currentDay}</td>
                    <td>{dec(r.sent)}</td>
                    <td>{dec(r.delivered)}</td>
                    <td style={{ color: r.bounced ? "var(--accent-red)" : undefined }}>{r.bounced || "—"}</td>
                    <td>{r.replied || "—"}</td>
                    <td>{pct(r.replied, r.sent)}</td>
                    <td style={{ color: bRed ? "var(--accent-red)" : undefined }}>{pct(r.bounced, r.sent)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>)}
      </div>

      {/* Per-niche */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Per niche (which audiences respond)</h3>
        {byNiche.length === 0
          ? <div style={{ color: "var(--fg-2)", padding: 8 }}>No prospects with niches yet.</div>
          : (<table className="tbl">
            <thead><tr><th>Niche</th><th>Prospects</th><th>Sent</th><th>Delivered</th><th>Replied</th><th>Reply rate</th></tr></thead>
            <tbody>
              {byNiche.map(r => (
                <tr key={r.slug}>
                  <td><span className="pill cyan">{r.slug}</span></td>
                  <td>{dec(r.prospects)}</td>
                  <td>{dec(r.sent)}</td>
                  <td>{dec(r.delivered)}</td>
                  <td>{r.replied || "—"}</td>
                  <td>{pct(r.replied, r.sent)}</td>
                </tr>
              ))}
            </tbody>
          </table>)}
      </div>

      {/* Per-step (where does the sequence convert) */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Per step (does the breakup email work?)</h3>
        {byStep.length === 0
          ? <div style={{ color: "var(--fg-2)", padding: 8 }}>No sends in window.</div>
          : (<table className="tbl">
            <thead><tr><th>Step</th><th>Sent</th><th>Delivered</th><th>Replied</th><th>Reply rate</th></tr></thead>
            <tbody>
              {byStep.map(r => (
                <tr key={r.step}>
                  <td><span className="pill">{r.step}</span></td>
                  <td>{dec(r.sent)}</td>
                  <td>{dec(r.delivered)}</td>
                  <td>{r.replied || "—"}</td>
                  <td>{pct(r.replied, r.sent)}</td>
                </tr>
              ))}
            </tbody>
          </table>)}
      </div>

      {/* Reputation health per profile (always show — it's the deliverability gate) */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Sender reputation (rolling 7-day)</h3>
        <table className="tbl">
          <thead><tr><th>Client</th><th>Sent 7d</th><th>Delivered</th><th>Bounce rate</th><th>vs limit</th><th>Complaint rate</th><th>vs limit</th></tr></thead>
          <tbody>
            {reputation.map(r => {
              const bAlert = r.bounce_rate_7d > r.bounce_threshold;
              const cAlert = r.complaint_rate_7d > r.complaint_threshold;
              return (
                <tr key={r.slug}>
                  <td>{r.name}</td>
                  <td>{dec(r.sent7)}</td>
                  <td>{dec(r.delivered7)}</td>
                  <td style={{ color: bAlert ? "var(--accent-red)" : undefined }}>{(r.bounce_rate_7d * 100).toFixed(2)}%</td>
                  <td style={{ fontSize: 12, color: "var(--fg-2)" }}>≤ {(r.bounce_threshold * 100).toFixed(1)}%</td>
                  <td style={{ color: cAlert ? "var(--accent-red)" : undefined }}>{(r.complaint_rate_7d * 100).toFixed(3)}%</td>
                  <td style={{ fontSize: 12, color: "var(--fg-2)" }}>≤ {(r.complaint_threshold * 100).toFixed(3)}%</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* List health */}
      <div className="card" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>List health</h3>
        {listHealth.length === 0
          ? <div style={{ color: "var(--fg-2)", padding: 8 }}>No prospects yet.</div>
          : (<table className="tbl">
            <thead><tr><th>Client</th><th>Total</th><th>Verified</th><th>Replied</th><th>Bounced</th><th>Unsubscribed</th></tr></thead>
            <tbody>
              {listHealth.map(r => (
                <tr key={r.slug}>
                  <td>{r.slug}</td>
                  <td>{dec(r.total)}</td>
                  <td>{dec(r.verified)} ({pct(r.verified, r.total, 0)})</td>
                  <td>{dec(r.replied)}</td>
                  <td>{dec(r.bounced)}</td>
                  <td>{dec(r.unsubscribed)}</td>
                </tr>
              ))}
            </tbody>
          </table>)}
      </div>

      {/* Recent replies */}
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Recent replies (live)</h3>
        {filteredReplies.length === 0
          ? <div style={{ color: "var(--fg-2)", padding: 8 }}>No replies in window yet. The IMAP poller writes here every 5 min.</div>
          : (<table className="tbl">
            <thead><tr><th>When</th><th>From</th><th>Subject</th><th>Class</th></tr></thead>
            <tbody>
              {filteredReplies.slice(0, 50).map(r => (
                <tr key={r.id}>
                  <td style={{ whiteSpace: "nowrap", fontSize: 12 }}>{new Date(r.received_at).toLocaleString()}</td>
                  <td style={{ fontSize: 12 }}>{r.from_addr}</td>
                  <td style={{ maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.subject}</td>
                  <td>
                    {r.class === "reply"     ? <span className="pill green">reply</span>
                   : r.class === "bounce"    ? <span className="pill red">bounce</span>
                   : r.class === "complaint" ? <span className="pill red">complaint</span>
                                             : <span className="pill">{r.class}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>)}
      </div>
    </>
  );
}

// ─── Building blocks ──────────────────────────────────────────────────────

function Kpi(props: { label: string; value: string; accent?: "green"|"red"|"amber"|"cyan"; sub?: string }) {
  const color = props.accent === "green" ? "var(--accent-lime)"
              : props.accent === "red"   ? "var(--accent-red)"
              : props.accent === "amber" ? "var(--accent-amber)"
              : props.accent === "cyan"  ? "var(--accent-cyan)" : "var(--fg-0)";
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>{props.label}</h3>
      <div className="big" style={{ color }}>{props.value}</div>
      {props.sub && <div className="delta">{props.sub}</div>}
    </div>
  );
}

function FunnelRow(props: { label: string; value: number; bar: number; sub?: string; negative?: boolean }) {
  const w = Math.max(0, Math.min(1, props.bar || 0));
  const color = props.negative ? "var(--accent-red)" : "var(--accent-cyan)";
  return (
    <div style={{ display: "grid", gridTemplateColumns: "200px 1fr 100px", gap: 12, alignItems: "center", padding: "6px 0" }}>
      <div style={{ fontSize: 13 }}>{props.label}{props.sub && <span style={{ color: "var(--fg-2)", fontSize: 11, marginLeft: 6 }}>· {props.sub}</span>}</div>
      <div style={{ height: 10, background: "rgba(255,255,255,0.05)", borderRadius: 4, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${(w * 100).toFixed(1)}%`, background: color, opacity: 0.8 }} />
      </div>
      <div style={{ textAlign: "right", fontSize: 14, fontWeight: 600 }}>{props.value.toLocaleString()}</div>
    </div>
  );
}
