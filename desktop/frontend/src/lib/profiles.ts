// Profile loader + active-profile state.
//
// In dev mode (browser), profiles are loaded from /profiles/<slug>.json which
// Vite serves from public/profiles/. In the native Tauri build the same path
// works because Tauri's asset protocol exposes the bundle resources.

export type Profile = {
  slug: string;
  name: string;
  created_at: string;
  active: boolean;
  identity: {
    from_name: string;
    from_addr: string;
    reply_to: string;
    role: string;
    company: string;
    site: string;
    signature: string;
  };
  voice: {
    register: string;
    quirks: string[];
    avoid: string[];
  };
  relay: {
    backend: "resend" | "smtp" | "postal";
    resend_api_key: string;          // "***" if redacted by backend
    from_domains: string[];
    domain_verified_at: string | null;
    dkim_selector: string;
  };
  warmup: {
    enabled: boolean;
    started_at: string | null;
    current_day: number;
    ramp_curve: string;
    max_daily_sends: number;
    warmup_targets: string[];
    real_send_mix: { until_day: number; warmup_pct: number }[];
    reputation: {
      bounce_rate_7d: number;
      complaint_rate_7d: number;
      delivered_7d: number;
      last_check: string | null;
    };
    auto_pause_thresholds: { bounce_rate: number; complaint_rate: number };
  };
  ramp_curve_snowball_v1: { from_day: number; daily: number }[];
};

export type WarmupStatus = {
  slug: string;
  current_day?: number;
  daily?: number;
  warmup_planned?: number;
  warmup_sent?: number;
  warmup_failed?: number;
  real_planned?: number;
  last_tick?: string;
  paused?: boolean;
  reason?: string;
  deferred?: boolean;
  skipped?: string;
};

const KNOWN_PROFILE_SLUGS = ["aureon", "bernhard", "algoalpha"];

export async function loadProfile(slug: string): Promise<Profile | null> {
  try {
    const r = await fetch(`/profiles/${slug}.json`);
    if (!r.ok) return null;
    return (await r.json()) as Profile;
  } catch {
    return null;
  }
}

export async function loadAllProfiles(): Promise<Profile[]> {
  // Frontend doesn't know the directory listing — uses a known slug index.
  // In native Tauri build, replace with a real `profiles_list` IPC.
  const out: Profile[] = [];
  for (const slug of KNOWN_PROFILE_SLUGS) {
    const p = await loadProfile(slug);
    if (p) out.push(p);
  }
  return out;
}

export async function loadWarmupStatus(slug: string): Promise<WarmupStatus | null> {
  try {
    const r = await fetch(`/profiles/${slug}.warmup.json`);
    if (!r.ok) return null;
    return (await r.json()) as WarmupStatus;
  } catch {
    return null;
  }
}

// ─── Active-profile state (localStorage in dev, will move to settings in Tauri) ─
const ACTIVE_KEY = "les.active_profile_slug";

export function getActiveSlug(): string | null {
  if (typeof localStorage === "undefined") return null;
  return localStorage.getItem(ACTIVE_KEY);
}

export function setActiveSlug(slug: string | null): void {
  if (typeof localStorage === "undefined") return;
  if (slug) localStorage.setItem(ACTIVE_KEY, slug);
  else localStorage.removeItem(ACTIVE_KEY);
  window.dispatchEvent(new CustomEvent("active-profile-changed", { detail: slug }));
}

// ─── Snowball ramp helpers (mirror profile_lib.py) ─────────────────────────

export function dailyTargetForDay(profile: Profile, day: number): number {
  if (day < 1) return 0;
  const curve = [...(profile.ramp_curve_snowball_v1 ?? [])].sort((a, b) => a.from_day - b.from_day);
  let t = 0;
  for (const row of curve) if (day >= row.from_day) t = row.daily;
  return Math.min(t, profile.warmup.max_daily_sends ?? t);
}

export function warmupPctForDay(profile: Profile, day: number): number {
  const mix = [...(profile.warmup.real_send_mix ?? [])].sort((a, b) => a.until_day - b.until_day);
  for (const row of mix) if (day <= row.until_day) return row.warmup_pct / 100;
  return 0.05;
}

export function reputationStatus(profile: Profile): { ok: boolean; reason?: string } {
  const r = profile.warmup.reputation;
  const t = profile.warmup.auto_pause_thresholds;
  if (r.bounce_rate_7d > t.bounce_rate)       return { ok: false, reason: `bounce ${(r.bounce_rate_7d*100).toFixed(2)}% > ${(t.bounce_rate*100).toFixed(1)}%` };
  if (r.complaint_rate_7d > t.complaint_rate) return { ok: false, reason: `complaint ${(r.complaint_rate_7d*100).toFixed(3)}% > ${(t.complaint_rate*100).toFixed(2)}%` };
  return { ok: true };
}
