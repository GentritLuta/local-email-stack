// Typed wrapper around the Tauri commands exposed by src-tauri/src/commands.rs.
//
// Real data only — no placeholders, no mocks.
//
// When running inside the Tauri shell, every call is a real IPC roundtrip into
// Rust. When running in the dev browser (`npm run dev` without `cargo tauri
// dev`), most calls return null/[] and the UI shows honest "stack not
// connected" states. The exception is the sequence files — they're real JSON
// on disk served by Vite from /public/sequences/, so they load identically in
// both modes.

import type { UnlistenFn } from "@tauri-apps/api/event";

const IN_TAURI = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export class NotConnectedError extends Error {
  constructor() {
    super("Stack not connected (running in dev browser without Tauri, or backend services down).");
    this.name = "NotConnectedError";
  }
}

async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  if (IN_TAURI) {
    const mod = await import("@tauri-apps/api/core");
    return mod.invoke<T>(cmd, args);
  }
  return browserInvoke<T>(cmd, args ?? {});
}

async function listen<T>(event: string, cb: (e: { payload: T }) => void): Promise<UnlistenFn> {
  if (IN_TAURI) {
    const mod = await import("@tauri-apps/api/event");
    return mod.listen<T>(event, cb);
  }
  // No event stream without Tauri.
  return (() => {}) as UnlistenFn;
}

// ─── Types ─────────────────────────────────────────────────────────────────
export type ServiceStatus = {
  name: string; state: string; health: string | null;
  uptime: string | null; image: string | null;
};
export type DashboardMetrics = {
  leads_raw_total: number; leads_enriched_total: number; leads_verified_total: number;
  leads_queued: number; leads_sent_today: number; replies_today: number; bounces_today: number;
  avg_reply_rate_7d: number; active_personas: number; active_niches: number;
  last_sent_at: string | null; warmup_spam_rate_7d: number;
  services_healthy: number; services_total: number;
};
export type StageBucket = { stage: string; count: number };
export type LeadSummary = {
  id: string; source: string; display_name: string; niche_slug: string;
  stage: string; last_event_at: string | null;
};
export type PipelineSnapshot = { by_stage: StageBucket[]; recent_leads: LeadSummary[] };
export type WarmupRow = {
  subdomain: string; day_of_ramp: number; spam_rate_7d: number;
  sends_today: number; receives_today: number; replies_today: number; status: string;
};
export type WarmupHealth = { per_subdomain: WarmupRow[] };
export type BanditRow = {
  kind: string; persona: string; text: string;
  impressions: number; rewards: number; rate: number;
};
export type InboundReply = {
  id: string; received_at: string; from_addr: string; to_addr: string;
  subject: string; class: string; snippet: string;
};
export type NicheSummary = {
  slug: string; name: string; engines: string[]; path: string;
};
export type AppSettings = {
  stack_repo_path: string | null;
  pg_dsn_override: string | null;
  n8n_url: string | null;
  auto_start_stack: boolean;
};
export type BundleMeta = {
  version: string; created_at: string; source_machine: string;
  bundle_id: string; includes_models: boolean; volumes: string[];
};
export type SequenceStep = {
  n: number; day: number; kind: string; subject: string; body: string;
};
export type Sequence = {
  name: string; slug: string; created_at: string;
  sender: { from_name: string; from_addr: string; reply_to: string; company: string; site: string; signature: string };
  recipient: { email: string; first_name: string; company: string };
  stop_on_reply: boolean; stop_on_bounce: boolean;
  schedule: string; schedule_explainer: string;
  steps: SequenceStep[];
};
export type SequenceStepResult = {
  step: number; subject: string; sent: boolean;
  message_id: string; mx?: string; smtp_response?: string; error?: string; backend?: string;
  attempted_at?: string; skipped?: boolean;
};
export type SequenceResults = {
  sequence: string; ran_at: string; backend?: string;
  results: SequenceStepResult[];
};

export const api = {
  // Stack
  stackStatus:           () => invoke<ServiceStatus[]>("stack_status"),
  stackUp:               () => invoke<string>("stack_up"),
  stackDown:             () => invoke<string>("stack_down"),
  stackRestartService:   (service: string) => invoke<void>("stack_restart_service", { service }),

  // Logs
  streamLogs:            (container: string, streamId: string) =>
                            invoke<void>("stream_logs", { container, streamId }),
  stopLogStream:         (streamId: string) => invoke<void>("stop_log_stream", { streamId }),
  onLogLine:             (streamId: string, cb: (line: string) => void): Promise<UnlistenFn> =>
                            listen<string>(`logs:${streamId}`, (e) => cb(e.payload)),

  // Dashboard
  dashboardMetrics:      () => invoke<DashboardMetrics>("dashboard_metrics"),
  pipelineSnapshot:      () => invoke<PipelineSnapshot>("pipeline_snapshot"),
  warmupHealth:          () => invoke<WarmupHealth>("warmup_health"),
  banditLeaderboard:     (limit?: number) => invoke<BanditRow[]>("bandit_leaderboard", { limit }),
  repliesRecent:         (limit?: number) => invoke<InboundReply[]>("replies_recent", { limit }),
  runSmokeTest:          () => invoke<[string, boolean, string][]>("run_smoke_test"),

  // Niches
  nichesList:            () => invoke<NicheSummary[]>("niches_list"),
  nicheGet:              (path: string) => invoke<string>("niche_get", { path }),
  nicheSave:             (path: string, content: string) => invoke<void>("niche_save", { path, content }),
  nicheDelete:           (path: string) => invoke<void>("niche_delete", { path }),
  nicheReloadService:    () => invoke<void>("niche_reload_service"),

  // Personas
  personasGet:           () => invoke<string>("personas_get"),
  personasSave:          (content: string) => invoke<void>("personas_save", { content }),

  // bootstrap.env
  envGet:                () => invoke<string>("env_get"),
  envSet:                (content: string) => invoke<void>("env_set", { content }),

  // Settings
  settingsGet:           () => invoke<AppSettings>("settings_get"),
  settingsSet:           (settings: AppSettings) => invoke<void>("settings_set", { settings }),
  detectFirstRun:        () => invoke<boolean>("detect_first_run"),

  // Portable
  portableExport:        (destinationZip: string, includeModels: boolean) =>
                            invoke<string>("portable_export", { destinationZip, includeModels }),
  portableImport:        (sourceZip: string, targetRepo: string, restoreModels: boolean) =>
                            invoke<BundleMeta>("portable_import", { sourceZip, targetRepo, restoreModels }),

  // Sequences (real files on disk; served by Vite in dev)
  getSequence:           (slug: string) => fetchSequence(slug),
  getSequenceResults:    (slug: string) => fetchSequenceResults(slug),
  listSequences:         () => listSequences(),

  // Misc
  openInBrowser:         (url: string) => invoke<void>("open_in_browser", { url }),
};

// ─── Sequence loader (real files via fetch) ────────────────────────────────
const SEQUENCE_FOLDERS: Record<string, string> = {
  algoalpha_aureon_test: "algoalpha-aureon-2026-05-17",
};

async function fetchSequence(slug: string): Promise<Sequence | null> {
  const folder = SEQUENCE_FOLDERS[slug];
  if (!folder) return null;
  try {
    const r = await fetch(`/sequences/${folder}/sequence.json`);
    if (!r.ok) return null;
    return (await r.json()) as Sequence;
  } catch {
    return null;
  }
}

async function fetchSequenceResults(slug: string): Promise<SequenceStepResult[]> {
  const folder = SEQUENCE_FOLDERS[slug];
  if (!folder) return [];
  try {
    const r = await fetch(`/sequences/${folder}/results.json`);
    if (!r.ok) return [];
    const body = await r.json();
    return body.results ?? [];
  } catch {
    return [];
  }
}

async function listSequences(): Promise<{ slug: string; name: string }[]> {
  const out: { slug: string; name: string }[] = [];
  for (const slug of Object.keys(SEQUENCE_FOLDERS)) {
    const s = await fetchSequence(slug);
    if (s) out.push({ slug: s.slug, name: s.name });
  }
  return out;
}

// ─── Browser-mode invoke (no mocks, honest empties) ────────────────────────
async function browserInvoke<T>(cmd: string, _args: Record<string, unknown>): Promise<T> {
  switch (cmd) {
    case "detect_first_run":
      return false as unknown as T;
    case "settings_get":
      return ({
        stack_repo_path: null,
        pg_dsn_override: null,
        n8n_url: null,
        auto_start_stack: false,
      }) as unknown as T;
    case "settings_set":
    case "stack_up":
    case "stack_down":
    case "stack_restart_service":
    case "niche_save":
    case "niche_delete":
    case "niche_reload_service":
    case "personas_save":
    case "env_set":
    case "stream_logs":
    case "stop_log_stream":
    case "portable_export":
    case "portable_import":
      throw new NotConnectedError();
    case "stack_status":
    case "bandit_leaderboard":
    case "replies_recent":
    case "run_smoke_test":
    case "niches_list":
      return [] as unknown as T;
    case "dashboard_metrics":
    case "pipeline_snapshot":
    case "warmup_health":
      return null as unknown as T;
    case "niche_get":
    case "personas_get":
    case "env_get":
      return "" as unknown as T;
    case "open_in_browser":
      if (typeof window !== "undefined" && _args.url) {
        window.open(String(_args.url), "_blank", "noopener");
      }
      return undefined as unknown as T;
    default:
      throw new NotConnectedError();
  }
}
