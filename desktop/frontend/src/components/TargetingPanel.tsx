// TargetingPanel.tsx — define WHAT kind of leads a client wants and
// trigger an automated search.
//
// Saves to profiles.lead_intent (JSONB) on Supabase. Clicking "Start
// search" writes a row to search_jobs which the search_dispatch_worker
// picks up within 5 minutes and enqueues candidates into prospect_candidates.

import { useEffect, useState } from "react";
import { Search, Save, AlertTriangle } from "lucide-react";
import { getSupabase, isConfigured, fetchSequences, DbSequence } from "../lib/supabase";

export type LeadIntent = {
  target_audience:     string;
  industries:          string[];
  location_geos:       string[];
  platforms:           string[];
  audience_size_min:   number;
  default_sequence_slug: string;
  search_keywords:     string[];
  notes:               string;
};

const EMPTY_INTENT: LeadIntent = {
  target_audience: "",
  industries: [],
  location_geos: [],
  platforms: ["youtube"],
  audience_size_min: 0,
  default_sequence_slug: "",
  search_keywords: [],
  notes: "",
};

const ALL_INDUSTRIES = [
  "trading_crypto", "trading_general", "fitness", "fashion", "beauty",
  "food", "real_estate", "gaming", "tech_saas", "marketing", "education",
  "finance_macro",
];

const ALL_PLATFORMS = [
  { v: "youtube",     label: "YouTube" },
  { v: "tradingview", label: "TradingView" },
  { v: "instagram",   label: "Instagram" },
  { v: "twitter",     label: "Twitter/X" },
  { v: "tiktok",      label: "TikTok" },
  { v: "twitch",      label: "Twitch" },
];

export function TargetingPanel(props: { profileSlug: string }) {
  const [intent,  setIntent]  = useState<LeadIntent>(EMPTY_INTENT);
  const [loaded,  setLoaded]  = useState(false);
  const [saving,  setSaving]  = useState(false);
  const [searching, setSearching] = useState(false);
  const [status,  setStatus]  = useState<string | null>(null);
  const [seqs,    setSeqs]    = useState<DbSequence[]>([]);

  // Load current intent
  useEffect(() => {
    (async () => {
      if (!isConfigured()) { setLoaded(true); return; }
      const s = getSupabase()!;
      const { data } = await s.from("profiles")
        .select("lead_intent,config")
        .eq("slug", props.profileSlug)
        .single();
      const live: LeadIntent | null = (data?.lead_intent
        ?? (data?.config as any)?.lead_intent
        ?? null);
      if (live) setIntent({ ...EMPTY_INTENT, ...live });
      setSeqs(await fetchSequences(props.profileSlug));
      setLoaded(true);
    })();
  }, [props.profileSlug]);

  async function save() {
    if (!isConfigured()) return;
    setSaving(true); setStatus(null);
    try {
      const s = getSupabase()!;
      const { error } = await s.from("profiles")
        .update({ lead_intent: intent })
        .eq("slug", props.profileSlug);
      if (error) throw error;
      setStatus("saved");
      setTimeout(() => setStatus(null), 2000);
    } catch (e: any) {
      setStatus("error: " + (e?.message ?? e));
    } finally {
      setSaving(false);
    }
  }

  async function startSearch() {
    if (!isConfigured()) return;
    setSearching(true); setStatus(null);
    try {
      const s = getSupabase()!;
      // Always save first so the snapshot reflects latest intent
      await s.from("profiles").update({ lead_intent: intent }).eq("slug", props.profileSlug);
      const { error } = await s.from("search_jobs").insert({
        profile_slug:  props.profileSlug,
        niche_slug:    "auto_search",
        intent_snap:   intent,
        requested_by:  "ui",
        status:        "pending",
      });
      if (error) throw error;
      setStatus("queued — dispatcher picks up within 5 min");
      setTimeout(() => setStatus(null), 5000);
    } catch (e: any) {
      setStatus("error: " + (e?.message ?? e));
    } finally {
      setSearching(false);
    }
  }

  function toggleArray(key: "industries" | "location_geos" | "platforms", v: string) {
    setIntent({ ...intent,
      [key]: intent[key].includes(v)
        ? intent[key].filter(x => x !== v)
        : [...intent[key], v]
    });
  }

  if (!loaded) return null;

  return (
    <div className="card" style={{ marginTop: 12 }}>
      <div className="row justify" style={{ alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 2 }}>Targeting</div>
          <div className="page-sub" style={{ margin: 0 }}>
            What kind of leads does this client want? Saved values drive the
            automated daily search + dashboard filtering.
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={save} disabled={saving}
                  style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <Save size={14} /> {saving ? "saving…" : "Save"}
          </button>
          <button className="primary" onClick={startSearch} disabled={searching}
                  style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <Search size={14} /> {searching ? "queueing…" : "Start lead search"}
          </button>
        </div>
      </div>

      {status && (
        <div style={{
          marginTop: 10, padding: "6px 10px", borderRadius: 6,
          background: status.startsWith("error") ? "rgba(239,68,68,0.1)" : "rgba(34,197,94,0.1)",
          color: status.startsWith("error") ? "#ef4444" : "#22c55e",
          fontSize: 12,
        }}>
          {status.startsWith("error") && <AlertTriangle size={12} style={{ marginRight: 4 }} />}
          {status}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 16 }}>
        {/* Left column */}
        <div>
          <Field label="Target audience (free text)">
            <textarea rows={2}
                      placeholder="e.g. Crypto influencers and TradingView indicator authors"
                      value={intent.target_audience}
                      onChange={e => setIntent({...intent, target_audience: e.target.value})} />
          </Field>

          <Field label="Industries">
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {ALL_INDUSTRIES.map(i => (
                <Chip key={i} label={i.replace(/_/g, " ")}
                      active={intent.industries.includes(i)}
                      onClick={() => toggleArray("industries", i)} />
              ))}
            </div>
          </Field>

          <Field label="Platforms">
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {ALL_PLATFORMS.map(p => (
                <Chip key={p.v} label={p.label}
                      active={intent.platforms.includes(p.v)}
                      onClick={() => toggleArray("platforms", p.v)} />
              ))}
            </div>
          </Field>

          <Field label="Location (ISO country codes, comma-separated)">
            <input value={intent.location_geos.join(", ")}
                   placeholder="US, DE, GB"
                   onChange={e => setIntent({...intent,
                     location_geos: e.target.value.split(/[,\s]+/).map(s => s.trim().toUpperCase()).filter(Boolean) })} />
          </Field>
        </div>

        {/* Right column */}
        <div>
          <Field label="Minimum audience size">
            <input type="number" min={0}
                   value={intent.audience_size_min || ""}
                   placeholder="0 = any"
                   onChange={e => setIntent({...intent, audience_size_min: +e.target.value || 0})} />
          </Field>

          <Field label="Default sequence (for 'Enroll filtered leads' button)">
            <select value={intent.default_sequence_slug}
                    onChange={e => setIntent({...intent, default_sequence_slug: e.target.value})}>
              <option value="">— pick a sequence —</option>
              {seqs.map(s => (
                <option key={s.slug} value={s.slug}>{s.name || s.slug}</option>
              ))}
            </select>
          </Field>

          <Field label="Search keywords (one per line, used for YouTube discovery)">
            <textarea rows={3}
                      placeholder={`crypto signals\ntradingview indicator review\nbest crypto trading bots`}
                      value={intent.search_keywords.join("\n")}
                      onChange={e => setIntent({...intent,
                        search_keywords: e.target.value.split("\n").map(s => s.trim()).filter(Boolean) })} />
          </Field>

          <Field label="Notes (operator only)">
            <textarea rows={2}
                      value={intent.notes}
                      onChange={e => setIntent({...intent, notes: e.target.value})} />
          </Field>
        </div>
      </div>
    </div>
  );
}

function Field(props: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 11, color: "var(--fg-2)", marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.5 }}>
        {props.label}
      </div>
      {props.children}
    </div>
  );
}

function Chip(props: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button onClick={props.onClick}
            style={{
              padding: "4px 10px",
              border: props.active ? "1px solid var(--accent-cyan)" : "var(--border)",
              background: props.active ? "rgba(34,211,238,0.1)" : "var(--bg-1)",
              color: props.active ? "var(--accent-cyan)" : "var(--fg-1)",
              borderRadius: 999, cursor: "pointer", fontSize: 11,
              fontWeight: props.active ? 600 : 400,
            }}>
      {props.label}
    </button>
  );
}
