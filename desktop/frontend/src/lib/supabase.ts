// Supabase client + realtime helpers — the cross-PC sync layer.
//
// On first run the user pastes SUPABASE_URL + SUPABASE_ANON_KEY into Settings → Sync.
// We persist them in localStorage so all routes can grab the same singleton client.
// Other PCs running the desktop app with the same URL/key see the same data live.

import { createClient, SupabaseClient } from "@supabase/supabase-js";

const KEY_URL = "les.supabase.url";
const KEY_ANON = "les.supabase.anon";

let _client: SupabaseClient | null = null;
let _signature: string | null = null;

export function getSupabase(): SupabaseClient | null {
  const url = localStorage.getItem(KEY_URL) || "";
  const anon = localStorage.getItem(KEY_ANON) || "";
  if (!url || !anon) return null;
  const sig = `${url}::${anon.slice(-8)}`;
  if (_client && _signature === sig) return _client;
  _client = createClient(url, anon, {
    auth: { persistSession: false },
    realtime: { params: { eventsPerSecond: 5 } },
  });
  _signature = sig;
  return _client;
}

export function saveSupabaseConfig(url: string, anon: string): void {
  localStorage.setItem(KEY_URL, url.trim());
  localStorage.setItem(KEY_ANON, anon.trim());
  _client = null; // force re-init
  _signature = null;
  window.dispatchEvent(new CustomEvent("supabase-config-changed"));
}

export function getSupabaseConfig(): { url: string; anon: string } {
  return {
    url: localStorage.getItem(KEY_URL) || "",
    anon: localStorage.getItem(KEY_ANON) || "",
  };
}

export function isConfigured(): boolean {
  const { url, anon } = getSupabaseConfig();
  return Boolean(url && anon);
}

// ─── Domain shape (mirrors supabase/schema.sql) ─────────────────────────────

export type DbProfile = {
  slug: string; name: string;
  config: any; active: boolean;
  created_at: string; updated_at: string;
};

export type DbVariant = {
  id: string; profile_slug: string; n: number;
  angle: string; subject: string; body: string;
};

export type DbSequence = {
  id: string; profile_slug: string; slug: string;
  name: string; description: string | null;
  stop_on_reply: boolean; stop_on_bounce: boolean; active: boolean;
  created_at: string; updated_at: string;
};

export type DbSequenceStep = {
  id: string; sequence_id: string; step_n: number;
  delay_days: number; variant_id: string | null;
  inline_subject: string | null; inline_body: string | null;
  forced_persona: string | null;
};

export type DbRun = {
  id: string; sequence_id: string; prospect_id: string;
  persona_slug: string | null; status: string;
  current_step: number; next_send_at: string | null;
  created_at: string; updated_at: string;
};

export type DbSendLog = {
  id: string; run_id: string | null; step_n: number;
  persona_slug: string | null; from_addr: string; to_addr: string;
  subject: string; resend_id: string | null; message_id: string | null;
  delivered: boolean | null; bounced: boolean; replied: boolean; complained: boolean;
  opened_at: string | null; clicked_at: string | null;
  sent_at: string; error: string | null;
};

export type DbReply = {
  id: string; run_id: string | null; profile_slug: string | null;
  from_addr: string; to_addr: string; subject: string | null;
  class: string; body_snippet: string | null;
  received_at: string;
};

// ─── High-level fetch helpers ──────────────────────────────────────────────

export async function fetchProfiles(): Promise<DbProfile[]> {
  const s = getSupabase(); if (!s) return [];
  const { data, error } = await s.from("profiles").select("*").order("created_at");
  if (error) { console.error(error); return []; }
  return data ?? [];
}

export async function fetchVariants(profileSlug: string): Promise<DbVariant[]> {
  const s = getSupabase(); if (!s) return [];
  const { data, error } = await s.from("variants")
    .select("*").eq("profile_slug", profileSlug).order("n");
  if (error) { console.error(error); return []; }
  return data ?? [];
}

export async function fetchSequences(profileSlug?: string): Promise<DbSequence[]> {
  const s = getSupabase(); if (!s) return [];
  let q = s.from("sequences").select("*").order("created_at", { ascending: false });
  if (profileSlug) q = q.eq("profile_slug", profileSlug);
  const { data, error } = await q;
  if (error) { console.error(error); return []; }
  return data ?? [];
}

export async function fetchRuns(opts?: { status?: string; limit?: number }): Promise<DbRun[]> {
  const s = getSupabase(); if (!s) return [];
  let q = s.from("runs").select("*").order("created_at", { ascending: false });
  if (opts?.status) q = q.eq("status", opts.status);
  if (opts?.limit)  q = q.limit(opts.limit);
  const { data, error } = await q;
  if (error) { console.error(error); return []; }
  return data ?? [];
}

export async function fetchSendLog(limit = 50): Promise<DbSendLog[]> {
  const s = getSupabase(); if (!s) return [];
  const { data, error } = await s.from("send_log")
    .select("*").order("sent_at", { ascending: false }).limit(limit);
  if (error) { console.error(error); return []; }
  return data ?? [];
}

export type DbProspect = {
  id: string; profile_slug: string; email: string;
  first_name: string | null; last_name: string | null; company: string | null;
  niche_slug: string | null; title: string | null; phone: string | null;
  city: string | null; state: string | null; website: string | null;
  source_url: string | null;
  verified: boolean; verified_at: string | null; verification_method: string | null;
  unsubscribed: boolean; unsubscribed_at: string | null;
  // categorization columns (populated by enrichment_worker)
  source_platform: string | null;
  audience_size:   number | null;
  industry_tags:   string[] | null;
  geo:             string | null;
  quality_score:   number | null;
  enriched_categorization_at: string | null;
  created_at: string;
};

export async function fetchProspects(profileSlug?: string, limit = 5000): Promise<DbProspect[]> {
  const s = getSupabase(); if (!s) return [];
  let q = s.from("prospects")
    .select("id,profile_slug,email,first_name,last_name,company,niche_slug,title,phone,city,state,website,source_url,verified,verified_at,verification_method,unsubscribed,unsubscribed_at,source_platform,audience_size,industry_tags,geo,quality_score,enriched_categorization_at,created_at")
    .order("created_at", { ascending: false })
    .limit(limit);
  if (profileSlug) q = q.eq("profile_slug", profileSlug);
  const { data, error } = await q;
  if (error) { console.error(error); return []; }
  return data ?? [];
}

export async function fetchReplies(limit = 100): Promise<DbReply[]> {
  const s = getSupabase(); if (!s) return [];
  const { data, error } = await s.from("replies")
    .select("*").order("received_at", { ascending: false }).limit(limit);
  if (error) { console.error(error); return []; }
  return data ?? [];
}

// ─── Realtime subscriptions ────────────────────────────────────────────────

export function subscribeToTable(
  table: "profiles" | "sequences" | "runs" | "send_log" | "replies" | "warmup_state",
  cb: () => void,
): () => void {
  const s = getSupabase();
  if (!s) return () => {};
  const channel = s
    .channel(`live:${table}`)
    .on("postgres_changes", { event: "*", schema: "public", table }, () => cb())
    .subscribe();
  return () => { s.removeChannel(channel); };
}
