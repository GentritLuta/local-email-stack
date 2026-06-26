import { supabase } from "./supabase";

// ─── Types (mirror supabase/migration_005_onboarding.sql) ──────────────────
export type OnboardingAnswers = {
  service_type: "" | "email" | "social" | "both"; // which service(s) the client wants
  company: string;
  website: string;
  contact_email: string;
  offer: string;            // what they sell / the core offer / their brand
  icp: string;              // who they target (email ICP) / audience (social)
  proof: string;            // social proof / numbers (email)
  give_first: string;       // the give-first free-value offer / lead magnet (email) — the hook that drives replies
  cta: string;              // desired call to action (email)
  sending_root: string;     // e.g. tryacme.com — the domain to send from (email)
  dns_host: string;         // cloudflare | hostinger | other (email)
  reply_to: string;         // where replies should land (email)
  lead_source: "csv" | "icp_sourcing";
  // ─── social media management (when service_type includes social) ───────────
  platforms: string;        // e.g. "Instagram, TikTok"
  handles: string;          // account handles or links
  posting_cadence: string;  // desired posting frequency
  notes: string;
  // ─── contract / signer details (drive the auto-prepared agreement) ─────────
  rep: string;              // authorised signer's full legal name
  rep_title: string;        // their title (Owner, Founder, CEO…)
  rep_chain: string;        // representation chain when signing through a holding/parent entity (optional; empty = signs directly)
  jurisdiction: string;     // jurisdiction of incorporation
  office: string;           // registered office address
  // ─── legal acceptances (T&C, Privacy, AGB) ─────────────────────────────────
  accepted_terms?: boolean;
  accepted_privacy?: boolean;
  accepted_agb?: boolean;
  accepted_at?: string;
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
  step: "profile" | "copy" | "pdf" | "unsub" | "domains" | "leads" | "warmup" | "golive";
  state: "pending" | "running" | "done" | "needs_input" | "error";
  detail: string | null;
  payload: any;
  updated_at: string;
};

// ─── Mutations / queries ───────────────────────────────────────────────────
export async function createSubmission(answers: OnboardingAnswers) {
  // The public form has no anon write access under RLS. The auth-admin Edge
  // Function (service role) creates/links the account, inserts the submission,
  // and returns a magic-link token so we can sign the client in immediately and
  // let them sign their contract without waiting for the email.
  const { data, error } = await supabase.functions.invoke("auth-admin", {
    body: { action: "submit", answers },
  });
  if (error) throw error;
  if (data?.error) throw new Error(data.error);

  // Auto-establish a session from the returned magic-link token (seamless).
  if (data?.magiclink_token_hash && data?.email) {
    // With a hashed token, verifyOtp takes token_hash + type only (no email —
    // passing both 400s). An admin-generated magiclink hashed token verifies
    // under type "email". This establishes the session so the now-authenticated
    // client can land on the protected /sign route.
    const { error: otpErr } = await supabase.auth.verifyOtp({
      type: "email",
      token_hash: data.magiclink_token_hash,
    });
    if (otpErr) {
      // Non-fatal: the client can still set their password from the emailed
      // link and sign in. Surface in console for debugging.
      console.warn("auto sign-in failed, falling back to email flow:", otpErr.message);
    }
  }
  return { id: data.submission_id as string } as Submission;
}

// Admin: invite a client by email (admin JWT sent automatically by supabase-js).
export async function inviteClient(email: string, company?: string) {
  const { data, error } = await supabase.functions.invoke("auth-admin", {
    body: { action: "invite", email, company: company ?? null },
  });
  if (error) throw error;
  if (data?.error) throw new Error(data.error);
  return data;
}

// Admin recovery: change a locked-out user's email.
export async function adminResetUserEmail(currentEmail: string, newEmail: string) {
  const { data, error } = await supabase.functions.invoke("auth-admin", {
    body: { action: "reset_user_email", current_email: currentEmail, new_email: newEmail },
  });
  if (error) throw error;
  if (data?.error) throw new Error(data.error);
  return data;
}

// Admin recovery: remove ALL of a locked-out user's 2FA factors.
export async function adminResetUser2fa(email: string) {
  const { data, error } = await supabase.functions.invoke("auth-admin", {
    body: { action: "reset_user_2fa", email },
  });
  if (error) throw error;
  if (data?.error) throw new Error(data.error);
  return data;
}

// Admin: list all clients (RLS grants admins read-all; the function is an alt path).
export async function listClients() {
  const { data, error } = await supabase
    .from("clients")
    .select("id, email, company, status, profile_slug, created_at")
    .order("created_at", { ascending: false });
  if (error) throw error;
  return (data ?? []) as Array<{
    id: string; email: string; company: string | null; status: string;
    profile_slug: string | null; created_at: string;
  }>;
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

// ─── Contracts (self-hosted e-sign) ────────────────────────────────────────
export type Contract = {
  id: string;
  submission_id: string;
  contract_ref: string;
  contract_html: string;
  status: "draft" | "signed" | "sealed" | "void";
  kind?: "pilot" | "continuation";
  signer_name: string | null;
  signer_email: string | null;
  signer_title: string | null;
  signed_at: string | null;
  sealed_at: string | null;
  signed_pdf_path: string | null;
};

// The contract is auto-prepared by the PC pipeline (contract-sign.py prepare)
// within ~1 min of submission. The sign screen polls until the draft appears.
export async function getContractForSubmission(submissionId: string) {
  // The pilot agreement (kind defaults to 'pilot' for older rows too).
  const { data, error } = await supabase
    .from("contracts").select("*")
    .eq("submission_id", submissionId)
    .neq("kind", "continuation")
    .order("created_at", { ascending: true })
    .limit(1).maybeSingle();
  if (error) throw error;
  return (data ?? null) as Contract | null;
}

// Fetch a contract directly by its own id. Used as a fallback when a sign link
// was hand-issued with the contract id instead of the submission id (older
// re-sign links). maybeSingle so a non-matching id yields null, never throws.
export async function getContractById(contractId: string) {
  const { data, error } = await supabase
    .from("contracts").select("*")
    .eq("id", contractId)
    .maybeSingle();
  if (error) throw error;
  return (data ?? null) as Contract | null;
}

// The continuation agreement (issued ~90 days after the pilot is signed).
export async function getContinuationForSubmission(submissionId: string) {
  const { data, error } = await supabase
    .from("contracts").select("*")
    .eq("submission_id", submissionId)
    .eq("kind", "continuation")
    .limit(1).maybeSingle();
  if (error) throw error;
  return (data ?? null) as Contract | null;
}

// Client click-to-sign. Writes the sign intent; the pipeline then stamps the
// server-side audit trail (IP, SHA-256) and renders the locked PDF on seal.
export async function signContract(
  contractId: string,
  fields: { signer_name: string; signer_email: string; signer_title: string }
) {
  // Best-effort client IP for the audit trail (the pipeline treats this as
  // unverified and may overwrite with a trusted server-observed value).
  let ip: string | null = null;
  try {
    const r = await fetch("https://api.ipify.org?format=json");
    ip = (await r.json())?.ip ?? null;
  } catch { /* non-fatal */ }

  const { error } = await supabase
    .from("contracts")
    .update({
      status: "signed",
      signer_name: fields.signer_name,
      signer_email: fields.signer_email,
      signer_title: fields.signer_title,
      signature_text: fields.signer_name,
      consent: true,
      signed_at: new Date().toISOString(),
      signer_ip: ip,
      signer_user_agent: navigator.userAgent,
    })
    .eq("id", contractId);
  if (error) throw error;
}

export type CampaignMetrics = {
  leads: number;            // verified, contactable prospects
  enrolled: number;         // prospects in an active sequence
  sentTotal: number;        // emails sent (lifetime)
  delivered: number;
  replies: number;          // genuine prospect replies
  conversations: number;    // runs paused on a reply (live threads)
  deliveredPct: number;
  replyPct: number;
  recentReplies: Array<{ from: string; subject: string; at: string }>;
};

// Rich client campaign metrics, RLS-scoped to the client's own profile_slug.
export async function getCampaignMetrics(profileSlug: string): Promise<CampaignMetrics> {
  const seqs = await supabase.from("sequences").select("id").eq("profile_slug", profileSlug);
  const seqIds = (seqs.data ?? []).map((s: any) => s.id);

  const head = { count: "exact" as const, head: true };
  const [
    { count: leads },
    { count: enrolled },
    { count: conversations },
    { count: replies },
  ] = await Promise.all([
    supabase.from("prospects").select("id", head)
      .eq("profile_slug", profileSlug).eq("verified", true).eq("unsubscribed", false),
    seqIds.length
      ? supabase.from("runs").select("id", head).in("sequence_id", seqIds)
      : Promise.resolve({ count: 0 } as any),
    seqIds.length
      ? supabase.from("runs").select("id", head).in("sequence_id", seqIds).eq("status", "paused_replied")
      : Promise.resolve({ count: 0 } as any),
    supabase.from("replies").select("id", head).eq("profile_slug", profileSlug).eq("class", "reply"),
  ]);

  // Send volume + delivery from send_log, scoped to this client's sending
  // subdomains (root). RLS already restricts what the client can read, and the
  // subdomain filter narrows to their own brand.
  let sentTotal = 0, delivered = 0;
  const root = profileSlug.replace(/[^a-z0-9-]/gi, "");
  const slRows = await supabase.from("send_log")
    .select("delivered, from_addr").like("from_addr", `%${root}%`).limit(5000);
  const rows = (slRows.data ?? []) as Array<{ delivered: boolean | null }>;
  sentTotal = rows.length;
  delivered = rows.filter((r) => r.delivered).length;

  // Recent genuine replies (a few, for the live feed).
  const recent = await supabase.from("replies")
    .select("from_addr, subject, received_at")
    .eq("profile_slug", profileSlug).eq("class", "reply")
    .order("received_at", { ascending: false }).limit(5);

  const recentReplies = (recent.data ?? []).map((r: any) => ({
    from: r.from_addr ?? "", subject: r.subject ?? "", at: r.received_at ?? "",
  }));

  return {
    leads: leads ?? 0,
    enrolled: enrolled ?? 0,
    sentTotal,
    delivered,
    replies: replies ?? 0,
    conversations: conversations ?? 0,
    deliveredPct: sentTotal ? Math.round((delivered / sentTotal) * 100) : 0,
    replyPct: sentTotal ? Math.round((((replies ?? 0) / sentTotal) * 100) * 10) / 10 : 0,
    recentReplies,
  };
}

// ─── CRM: invoices, sales, reply outcomes, outreach report ──────────────────
export type Invoice = {
  id: string; invoice_ref: string; title: string | null;
  amount_cents: number; due_cents: number | null; currency: string;
  status: "draft" | "sent" | "paid" | "overdue" | "void";
  issued_at: string | null; due_at: string | null; pdf_path: string | null;
};
export type Sale = {
  id: string; prospect_email: string | null; amount_cents: number;
  currency: string; status: "won" | "pipeline" | "lost"; closed_at: string | null; note: string | null;
};
export type ReplyOutcome = { from: string; subject: string; at: string; outcome: string };
export type OutreachReport = {
  sent: number; delivered: number; bounced: number; replied: number;
  deliveredPct: number; bouncePct: number; replyPct: number;
  byStep: Record<string, number>;
};

export async function getInvoices(profileSlug?: string) {
  let q = supabase.from("invoices")
    .select("id, invoice_ref, title, amount_cents, due_cents, currency, status, issued_at, due_at, pdf_path")
    .order("issued_at", { ascending: false });
  if (profileSlug) q = q.eq("profile_slug", profileSlug);
  const { data, error } = await q;
  if (error) throw error;
  return (data ?? []) as Invoice[];
}

export async function getSales(profileSlug?: string) {
  let q = supabase.from("sales")
    .select("id, prospect_email, amount_cents, currency, status, closed_at, note")
    .order("closed_at", { ascending: false });
  if (profileSlug) q = q.eq("profile_slug", profileSlug);
  const { data, error } = await q;
  if (error) throw error;
  return (data ?? []) as Sale[];
}

// Genuine replies with an auto-classified outcome (from raw_headers markers).
export async function getReplyOutcomes(profileSlug: string): Promise<ReplyOutcome[]> {
  const { data, error } = await supabase.from("replies")
    .select("from_addr, subject, received_at, raw_headers")
    .eq("profile_slug", profileSlug).eq("class", "reply")
    .order("received_at", { ascending: false }).limit(50);
  if (error) throw error;
  return (data ?? []).map((r: any) => {
    const rh = r.raw_headers || {};
    let outcome = "Replied";
    if (rh.booking_sent) outcome = "Booked / call";
    else if (rh.seller_outreach_done || rh.seller_test_fulfilled) outcome = "In follow-up";
    else if (rh.autosent || rh.autodraft_sent) outcome = "Answered";
    return { from: r.from_addr ?? "", subject: r.subject ?? "", at: r.received_at ?? "", outcome };
  });
}

// Outreach report from send_log, scoped to the client's sending subdomains.
export async function getOutreachReport(profileSlug: string): Promise<OutreachReport> {
  const root = profileSlug.replace(/[^a-z0-9-]/gi, "");
  const { data } = await supabase.from("send_log")
    .select("delivered, bounced, replied, step_n, from_addr").like("from_addr", `%${root}%`).limit(8000);
  const rows = (data ?? []) as Array<{ delivered: boolean | null; bounced: boolean | null; replied: boolean | null; step_n: number | null }>;
  const sent = rows.length;
  const delivered = rows.filter((r) => r.delivered).length;
  const bounced = rows.filter((r) => r.bounced).length;
  const replied = rows.filter((r) => r.replied).length;
  const byStep: Record<string, number> = {};
  for (const r of rows) { const k = String(r.step_n ?? "?"); byStep[k] = (byStep[k] ?? 0) + 1; }
  const pct = (n: number) => (sent ? Math.round((n / sent) * 1000) / 10 : 0);
  return { sent, delivered, bounced, replied, deliveredPct: pct(delivered), bouncePct: pct(bounced), replyPct: pct(replied), byStep };
}

// ─── Admin CRM writes (admin JWT; RLS allows is_admin) ──────────────────────
export async function adminCreateInvoice(input: {
  client_id: string; profile_slug?: string; invoice_ref: string; title?: string;
  amount_cents: number; currency?: string; status?: string; issued_at?: string; due_at?: string;
}) {
  const { error } = await supabase.from("invoices").insert({ ...input, source: "manual" });
  if (error) throw error;
}
export async function adminSetInvoiceStatus(id: string, status: string) {
  const patch: any = { status };
  if (status === "paid") patch.paid_at = new Date().toISOString();
  const { error } = await supabase.from("invoices").update(patch).eq("id", id);
  if (error) throw error;
}
export async function adminCreateSale(input: {
  client_id: string; profile_slug?: string; prospect_email?: string;
  amount_cents: number; currency?: string; status?: string; note?: string;
}) {
  const { error } = await supabase.from("sales")
    .insert({ ...input, closed_at: new Date().toISOString() });
  if (error) throw error;
}

// Admin: all signed/sealed contracts (the signature evidence trail). RLS lets
// admins read every contract.
export async function adminListSignedContracts() {
  const { data, error } = await supabase
    .from("contracts")
    .select("id, contract_ref, status, signer_name, signer_email, signed_at, sealed_at, signer_ip, contract_sha256, contract_html")
    .in("status", ["signed", "sealed"])
    .order("signed_at", { ascending: false });
  if (error) throw error;
  return (data ?? []) as Array<{
    id: string; contract_ref: string; status: string; signer_name: string | null;
    signer_email: string | null; signed_at: string | null; sealed_at: string | null;
    signer_ip: string | null; contract_sha256: string | null; contract_html: string;
  }>;
}

// Contract for a client (latest), so the portal can always show + download it,
// before AND after signing. RLS scopes it to the client's own rows.
export async function getContractForClient() {
  const { data, error } = await supabase
    .from("contracts")
    .select("*")
    .order("created_at", { ascending: false })
    .limit(1).maybeSingle();
  if (error) throw error;
  return (data ?? null) as Contract | null;
}

// Download the contract HTML as a file (works pre-sign on the draft, post-sign on
// the sealed version with the certificate). The browser prints/saves to PDF.
export function downloadContractHtml(contract: Contract) {
  const html = contract.contract_html || "";
  const blob = new Blob([html], { type: "text/html" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${(contract.contract_ref || "agreement").replace(/\s+/g, "_")}.html`;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

// Open the contract in a new tab for viewing / browser "Print to PDF".
export function openContractForPrint(contract: Contract) {
  const w = window.open("", "_blank");
  if (w) { w.document.write(contract.contract_html || ""); w.document.close(); }
}

// ─── Billing on file (post-sign charge authorization) ──────────────────────
export type BillingInput = {
  billing_name: string;
  legal_name: string;
  billing_email: string;
  address_line: string;
  city: string;
  postal_code: string;
  country: string;
  vat_id?: string;
  payoneer_email?: string;
  iban?: string;
  authorized: boolean;
  authorization_text: string;
};

export type BillingProfile = {
  id: string;
  client_id: string;
  billing_name: string | null;
  legal_name: string | null;
  billing_email: string | null;
  address_line: string | null;
  city: string | null;
  postal_code: string | null;
  country: string | null;
  vat_id: string | null;
  payoneer_email: string | null;
  iban: string | null;
  card_last4: string | null;
  card_brand: string | null;
  authorized: boolean;
  authorized_at: string | null;
  authorization_sha: string | null;
  payoneer_status: string | null;
};

// The fields a client may edit themselves from the dashboard.
export type BillingEditable = {
  billing_name: string;
  legal_name: string;
  billing_email: string;
  address_line: string;
  city: string;
  postal_code: string;
  country: string;
  vat_id: string;
  payoneer_email: string;
  iban: string;
};

// The just-signed client submits their billing-on-file. The auth-admin Edge
// Function (service role) verifies they own this submission, stores the signed
// authorization with an audit hash, and a local task drops the generator JSON +
// emails info@. Best-effort client IP is collected for the audit trail.
export async function submitBilling(submissionId: string, billing: BillingInput) {
  let ip: string | null = null;
  try {
    const r = await fetch("https://api.ipify.org?format=json");
    ip = (await r.json())?.ip ?? null;
  } catch { /* non-fatal */ }

  const { data, error } = await supabase.functions.invoke("auth-admin", {
    body: { action: "billing", submission_id: submissionId, billing, signer_ip: ip,
            signer_user_agent: navigator.userAgent },
  });
  if (error) throw error;
  if (data?.error) throw new Error(data.error);
  return data as { ok: true; client_id: string; sha: string };
}

// Has the client already filed billing? (drives whether the step is shown.)
export async function getBillingForClient(): Promise<BillingProfile | null> {
  const { data, error } = await supabase
    .from("billing_profiles").select("*")
    .order("created_at", { ascending: false })
    .limit(1).maybeSingle();
  if (error) throw error;
  return (data ?? null) as BillingProfile | null;
}

// Client self-service: update their own billing details (address, funding
// method, VAT, etc.). RLS (billing_client_write) scopes this to their own row.
// The existing charge authorization stays valid; we reset the local-sync flags
// so billing-sync.py re-drops the generator profile JSON and re-emails info@.
export async function updateMyBilling(id: string, fields: BillingEditable) {
  const { error } = await supabase
    .from("billing_profiles")
    .update({ ...fields, json_dropped_at: null, notified_at: null })
    .eq("id", id);
  if (error) throw error;
}

// Admin: list all billing profiles for the dashboard evidence panel.
export async function adminListBillingProfiles() {
  const { data, error } = await supabase
    .from("billing_profiles")
    .select("id, client_id, billing_name, legal_name, billing_email, country, payoneer_email, iban, authorized, authorized_at, authorization_sha, payoneer_status, profile_slug")
    .order("created_at", { ascending: false });
  if (error) throw error;
  return (data ?? []) as Array<BillingProfile & { profile_slug: string | null }>;
}

// ─── Sending-infrastructure access (post-sign credential handover) ──────────
// After signing, the client hands over a SCOPED, REVOCABLE API token for their
// DNS / domain host so the pipeline can auto-provision sending infrastructure.
// We deliberately ask for a token, not an account password.
export type CredentialsInput = {
  // Email-infrastructure access (collected for email / both clients).
  registrar: string;        // "Hostinger", "Cloudflare", "GoDaddy"…
  dns_host: string;         // cloudflare | hostinger | other
  api_token: string;        // the scoped, revocable token
  other_access: string;     // any additional access notes
  // Social-media account access (collected for social / both clients).
  social_handles: string;        // the accounts to manage, e.g. "Instagram @x, TikTok @y"
  social_access_confirmed: boolean; // they granted partner/member access via the platforms' business tools
  social_business_id: string;    // Meta Business / TikTok Business Center id or the partner email invited (optional)
  asset_link: string;            // link to logo, brand guidelines, product photos, video footage
  content_approver: string;      // name + email of who approves the content calendar
  notes: string;
  authorized: boolean;
  authorization_text: string;
};

export type CredentialsProfile = {
  id: string;
  client_id: string;
  profile_slug: string | null;
  registrar: string | null;
  dns_host: string | null;
  other_access: string | null;
  notes: string | null;
  authorized: boolean;
  authorized_at: string | null;
  authorization_sha: string | null;
  written_to_env_at: string | null;
};

// The just-signed client submits their sending-infra access. The auth-admin Edge
// Function (service role) verifies they own this submission, stores it with an
// audit hash, and credentials-sync.py writes the token into hostinger.env and
// emails info@ the combined onboarding + access details.
export async function submitCredentials(submissionId: string, credentials: CredentialsInput) {
  let ip: string | null = null;
  try {
    const r = await fetch("https://api.ipify.org?format=json");
    ip = (await r.json())?.ip ?? null;
  } catch { /* non-fatal */ }

  const { data, error } = await supabase.functions.invoke("auth-admin", {
    body: { action: "credentials", submission_id: submissionId, credentials,
            signer_ip: ip, signer_user_agent: navigator.userAgent },
  });
  if (error) throw error;
  if (data?.error) throw new Error(data.error);
  return data as { ok: true; client_id: string; sha: string };
}

// Has the client already handed over access? (drives whether the step is shown).
// The api_token itself is never selected back to the browser.
export async function getCredentialsForClient(): Promise<CredentialsProfile | null> {
  const { data, error } = await supabase
    .from("client_credentials")
    .select("id, client_id, profile_slug, registrar, dns_host, other_access, notes, authorized, authorized_at, authorization_sha, written_to_env_at")
    .order("created_at", { ascending: false })
    .limit(1).maybeSingle();
  if (error) throw error;
  return (data ?? null) as CredentialsProfile | null;
}
