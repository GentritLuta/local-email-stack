import { supabase } from "./supabase";

// ─── Types (mirror supabase/migration_005_onboarding.sql) ──────────────────
export type OnboardingAnswers = {
  company: string;
  website: string;
  contact_email: string;
  offer: string;            // what they sell / the core offer
  icp: string;              // who they target
  proof: string;            // social proof / numbers
  cta: string;              // desired call to action
  sending_root: string;     // e.g. tryacme.com — the domain to send from
  dns_host: string;         // cloudflare | hostinger | other
  reply_to: string;         // where replies should land
  lead_source: "csv" | "icp_sourcing";
  notes: string;
};

export type Submission = {
  id: string;
  client_id: string | null;
  raw_answers: OnboardingAnswers;
  status: "pending" | "provisioning" | "needs_dns" | "ready" | "live" | "error";
  error: string | null;
  created_at: string;
  updated_at: string;
};

export type ProvStep = {
  id: string;
  submission_id: string;
  step: "profile" | "copy" | "domains" | "leads" | "warmup" | "golive";
  state: "pending" | "running" | "done" | "needs_input" | "error";
  detail: string | null;
  payload: any;
  updated_at: string;
};

// ─── Mutations / queries ───────────────────────────────────────────────────
export async function createSubmission(answers: OnboardingAnswers) {
  // Create a client row, then the submission that the PC pipeline consumes.
  const { data: client, error: cErr } = await supabase
    .from("clients")
    .insert({ email: answers.contact_email, company: answers.company, status: "onboarding" })
    .select("id")
    .single();
  if (cErr) throw cErr;

  const { data: sub, error: sErr } = await supabase
    .from("onboarding_submissions")
    .insert({ client_id: client.id, raw_answers: answers, status: "pending" })
    .select("*")
    .single();
  if (sErr) throw sErr;
  return sub as Submission;
}

export async function getSubmission(id: string) {
  const { data, error } = await supabase
    .from("onboarding_submissions").select("*").eq("id", id).single();
  if (error) throw error;
  return data as Submission;
}

export async function getProvSteps(submissionId: string) {
  const { data, error } = await supabase
    .from("provisioning_status").select("*")
    .eq("submission_id", submissionId)
    .order("step", { ascending: true });
  if (error) throw error;
  return (data ?? []) as ProvStep[];
}

// Client campaign metrics, scoped to a profile_slug once provisioned.
export async function getCampaignMetrics(profileSlug: string) {
  const sinceMidnight = new Date(); sinceMidnight.setHours(0, 0, 0, 0);
  const seqs = await supabase.from("sequences").select("id").eq("profile_slug", profileSlug);
  const seqIds = (seqs.data ?? []).map((s: any) => s.id);

  const [{ count: leads }, { count: replied }] = await Promise.all([
    supabase.from("prospects").select("id", { count: "exact", head: true })
      .eq("profile_slug", profileSlug).eq("verified", true).eq("unsubscribed", false),
    seqIds.length
      ? supabase.from("runs").select("id", { count: "exact", head: true })
          .in("sequence_id", seqIds).eq("status", "paused_replied")
      : Promise.resolve({ count: 0 } as any),
  ]);

  const replies = await supabase.from("replies").select("id", { count: "exact", head: true })
    .eq("profile_slug", profileSlug).eq("class", "reply");

  return {
    leads: leads ?? 0,
    replied_runs: replied ?? 0,
    replies: replies.count ?? 0,
  };
}
