// auth-admin — privileged auth actions for the AUREON client portal.
//
// Runs server-side with the service-role key (NEVER in the browser). Three jobs:
//   submit  (public): the onboarding form posts here. Find-or-create the auth
//           user for the email, link clients.auth_user_id, insert the
//           onboarding_submission, send a set-password email, and return a
//           magic-link token_hash so the browser can mint an immediate session
//           (so the client can sign their contract right away).
//   invite  (admin only): invite a client by email (set-password email).
//   list_clients (admin only): all clients (admins can also read via RLS).
//
// Deployed with verify_jwt=false because `submit` must be callable by anon; each
// privileged action verifies the caller's JWT + is_admin itself.
//
// deno-lint-ignore-file no-explicit-any
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const SERVICE_ROLE_KEY = Deno.env.get("SERVICE_ROLE_KEY") ??
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
const PORTAL_URL = Deno.env.get("PORTAL_URL") ?? "http://localhost:5273";

const admin = createClient(SUPABASE_URL, SERVICE_ROLE_KEY, {
  auth: { persistSession: false, autoRefreshToken: false },
});

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, "Content-Type": "application/json" },
  });

const norm = (e: string) => (e ?? "").trim().toLowerCase();

// Find an existing auth user by email (case-insensitive), paging if needed.
async function findUserByEmail(email: string): Promise<any | null> {
  const target = norm(email);
  for (let page = 1; page <= 20; page++) {
    const { data, error } = await admin.auth.admin.listUsers({ page, perPage: 200 });
    if (error) throw error;
    const hit = (data?.users ?? []).find((u: any) => norm(u.email) === target);
    if (hit) return hit;
    if (!data || data.users.length < 200) break;
  }
  return null;
}

// Find-or-create the auth user; never throws on a duplicate email.
async function ensureUser(email: string): Promise<any> {
  const existing = await findUserByEmail(email);
  if (existing) return existing;
  const { data, error } = await admin.auth.admin.createUser({
    email,
    email_confirm: false, // confirmed when they click the set-password link
  });
  if (error) {
    // Race / already-exists: fall back to lookup.
    const again = await findUserByEmail(email);
    if (again) return again;
    throw error;
  }
  return data.user;
}

// Upsert one client row per email; set auth_user_id if missing. Returns the row.
async function upsertClient(email: string, company: string | null, userId: string) {
  const { data: found } = await admin
    .from("clients")
    .select("id, auth_user_id")
    .ilike("email", email)
    .limit(1)
    .maybeSingle();
  if (found) {
    if (!found.auth_user_id) {
      await admin.from("clients").update({ auth_user_id: userId }).eq("id", found.id);
    }
    return found.id as string;
  }
  const { data: ins, error } = await admin
    .from("clients")
    .insert({ email, company, status: "onboarding", auth_user_id: userId })
    .select("id")
    .single();
  if (error) throw error;
  return ins.id as string;
}

// Verify the caller is an authenticated admin (for privileged actions).
async function requireAdmin(req: Request): Promise<{ ok: boolean; msg?: string }> {
  const authz = req.headers.get("Authorization") ?? "";
  const jwt = authz.replace(/^Bearer\s+/i, "");
  if (!jwt) return { ok: false, msg: "missing bearer token" };
  const { data, error } = await admin.auth.getUser(jwt);
  if (error || !data?.user) return { ok: false, msg: "invalid token" };
  const { data: role } = await admin
    .from("user_roles")
    .select("is_admin")
    .eq("user_id", data.user.id)
    .maybeSingle();
  if (!role?.is_admin) return { ok: false, msg: "not an admin" };
  return { ok: true };
}

// Base fields every onboarding submission needs. Service-specific fields are
// added per service_type below so this mirrors the adaptive frontend form
// (Onboard.tsx): email/both also need sending_root; social/both also need
// platforms. Keep these two in sync or a valid form submission 400s here.
const REQUIRED_BASE = ["company", "contact_email", "offer", "icp", "rep", "rep_title"];

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return json({ error: "POST only" }, 405);

  let payload: any;
  try {
    payload = await req.json();
  } catch {
    return json({ error: "invalid JSON" }, 400);
  }
  const action = payload?.action;

  try {
    // ── submit (public) ──────────────────────────────────────────────────
    if (action === "submit") {
      const answers = payload.answers ?? {};
      const st = answers.service_type || "email";  // legacy callers (no picker) = email
      const required = [
        ...REQUIRED_BASE,
        ...((st === "email" || st === "both") ? ["sending_root"] : []),
        ...((st === "social" || st === "both") ? ["platforms"] : []),
      ];
      const missing = required.filter((k) => !String(answers[k] ?? "").trim());
      if (missing.length) return json({ error: `missing fields: ${missing.join(", ")}` }, 400);

      const email = norm(answers.contact_email);
      if (!email.includes("@")) return json({ error: "bad email" }, 400);

      const user = await ensureUser(email);
      const clientId = await upsertClient(email, answers.company ?? null, user.id);

      // One in-flight submission per client: a resubmit on the same email reuses
      // the open submission (refreshing the answers) instead of stacking a new
      // row that would later spawn a duplicate profile. A partial unique index
      // (uq_one_open_submission_per_client) enforces this at the DB level too.
      const OPEN_STATUSES = ["pending", "provisioning", "needs_dns", "ready", "awaiting_signature"];
      const { data: openSub } = await admin
        .from("onboarding_submissions")
        .select("id")
        .eq("client_id", clientId)
        .in("status", OPEN_STATUSES)
        .order("created_at", { ascending: false })
        .limit(1)
        .maybeSingle();

      let sub: { id: string };
      if (openSub) {
        await admin.from("onboarding_submissions")
          .update({ raw_answers: answers }).eq("id", openSub.id);
        sub = openSub as { id: string };
      } else {
        const { data: ins, error: subErr } = await admin
          .from("onboarding_submissions")
          .insert({ client_id: clientId, raw_answers: answers, status: "pending" })
          .select("id")
          .single();
        if (subErr) throw subErr;
        sub = ins as { id: string };
      }

      // Set-password email: invite if the user has never confirmed, else recovery.
      const isNew = !user.email_confirmed_at;
      if (isNew) {
        await admin.auth.admin.inviteUserByEmail(email, {
          redirectTo: `${PORTAL_URL}/reset`,
        });
      } else {
        await admin.auth.admin.generateLink({
          type: "recovery",
          email,
          options: { redirectTo: `${PORTAL_URL}/reset` },
        });
      }

      // Magic-link token_hash so the browser can mint a session immediately and
      // proceed to sign the contract without waiting for the email.
      let magiclink_token_hash: string | null = null;
      try {
        const { data: link } = await admin.auth.admin.generateLink({
          type: "magiclink",
          email,
          options: { redirectTo: `${PORTAL_URL}/auth/callback` },
        });
        magiclink_token_hash = (link?.properties as any)?.hashed_token ?? null;
      } catch (_) {
        magiclink_token_hash = null;
      }

      return json({ submission_id: sub.id, client_id: clientId, email, magiclink_token_hash });
    }

    // ── invite (admin only) ──────────────────────────────────────────────
    if (action === "invite") {
      const gate = await requireAdmin(req);
      if (!gate.ok) return json({ error: gate.msg }, 403);

      const email = norm(payload.email);
      if (!email.includes("@")) return json({ error: "bad email" }, 400);
      const company = payload.company ?? null;

      const user = await ensureUser(email);
      const clientId = await upsertClient(email, company, user.id);
      await admin.auth.admin.inviteUserByEmail(email, {
        redirectTo: `${PORTAL_URL}/reset`,
      });
      return json({ ok: true, client_id: clientId, user_id: user.id });
    }

    // ── list_clients (admin only) ────────────────────────────────────────
    if (action === "list_clients") {
      const gate = await requireAdmin(req);
      if (!gate.ok) return json({ error: gate.msg }, 403);
      const { data, error } = await admin
        .from("clients")
        .select("id, email, company, status, profile_slug, auth_user_id, created_at")
        .order("created_at", { ascending: false });
      if (error) throw error;
      return json({ clients: data ?? [] });
    }

    // ── reset_user_email (admin only): change a locked-out user's email ───
    if (action === "reset_user_email") {
      const gate = await requireAdmin(req);
      if (!gate.ok) return json({ error: gate.msg }, 403);
      const current = norm(payload.current_email);
      const next = norm(payload.new_email);
      if (!next.includes("@")) return json({ error: "bad new email" }, 400);
      const user = await findUserByEmail(current);
      if (!user) return json({ error: "user not found" }, 404);
      // Update auth email (confirm immediately so they can use it) + the client row.
      const { error: e1 } = await admin.auth.admin.updateUserById(user.id, {
        email: next, email_confirm: true,
      });
      if (e1) throw e1;
      await admin.from("clients").update({ email: next }).eq("auth_user_id", user.id);
      return json({ ok: true, user_id: user.id, new_email: next });
    }

    // ── list_user_factors (admin only): see a user's enrolled 2FA factors ──
    if (action === "list_user_factors") {
      const gate = await requireAdmin(req);
      if (!gate.ok) return json({ error: gate.msg }, 403);
      const user = await findUserByEmail(norm(payload.email));
      if (!user) return json({ error: "user not found" }, 404);
      const { data, error } = await admin.auth.admin.mfa.listFactors({ userId: user.id });
      if (error) throw error;
      return json({ factors: (data?.factors ?? []).map((f: any) => ({ id: f.id, type: f.factor_type, status: f.status })) });
    }

    // ── reset_user_2fa (admin only): unenroll ALL of a locked-out user's
    //    2FA factors so they can sign in with just their password again ──────
    if (action === "reset_user_2fa") {
      const gate = await requireAdmin(req);
      if (!gate.ok) return json({ error: gate.msg }, 403);
      const user = await findUserByEmail(norm(payload.email));
      if (!user) return json({ error: "user not found" }, 404);
      const { data, error } = await admin.auth.admin.mfa.listFactors({ userId: user.id });
      if (error) throw error;
      let removed = 0;
      for (const f of data?.factors ?? []) {
        const { error: de } = await admin.auth.admin.mfa.deleteFactor({ userId: user.id, id: f.id });
        if (!de) removed++;
      }
      return json({ ok: true, user_id: user.id, factors_removed: removed });
    }

    // ── billing (client, own row): store billing-on-file + charge auth ─────
    // The just-signed client posts this from their authenticated session. We
    // verify the JWT and that the caller owns the submission's client, then
    // upsert their billing_profile with the signed authorization + an audit
    // hash. A local scheduled task (billing-sync.py) then drops the generator
    // profile JSON and emails info@ — the Edge runtime can't touch the local
    // C:\Aureon Invoices\ folder.
    if (action === "billing") {
      const authz = req.headers.get("Authorization") ?? "";
      const jwt = authz.replace(/^Bearer\s+/i, "");
      if (!jwt) return json({ error: "sign in first" }, 401);
      const { data: who, error: whoErr } = await admin.auth.getUser(jwt);
      if (whoErr || !who?.user) return json({ error: "invalid session" }, 401);

      const submissionId = String(payload.submission_id ?? "").trim();
      if (!submissionId) return json({ error: "missing submission_id" }, 400);

      // Resolve the client for this submission and confirm the caller owns it
      // (or is an admin filling it on their behalf).
      const { data: sub } = await admin
        .from("onboarding_submissions")
        .select("id, client_id, raw_answers")
        .eq("id", submissionId)
        .maybeSingle();
      if (!sub?.client_id) return json({ error: "submission not found" }, 404);

      const { data: client } = await admin
        .from("clients")
        .select("id, auth_user_id, company, email, profile_slug")
        .eq("id", sub.client_id)
        .maybeSingle();
      if (!client) return json({ error: "client not found" }, 404);

      const { data: role } = await admin
        .from("user_roles").select("is_admin").eq("user_id", who.user.id).maybeSingle();
      const isAdmin = Boolean(role?.is_admin);
      if (client.auth_user_id !== who.user.id && !isAdmin) {
        return json({ error: "not your account" }, 403);
      }

      const b = payload.billing ?? {};
      if (!b.authorized) return json({ error: "charge authorization required" }, 400);

      const ip = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim()
        || (payload.signer_ip ?? null);
      const ua = req.headers.get("user-agent") ?? (payload.signer_user_agent ?? null);
      const authText = String(b.authorization_text ?? "").trim();
      const nowIso = new Date().toISOString();

      // Audit hash over the authorization text + identity + timestamp.
      const hashInput = [
        authText, b.billing_name ?? "", b.legal_name ?? "", b.billing_email ?? "",
        b.payoneer_email ?? "", b.iban ?? "", ip ?? "", nowIso,
      ].join("|");
      const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(hashInput));
      const sha = Array.from(new Uint8Array(digest)).map((x) => x.toString(16).padStart(2, "0")).join("");

      const row = {
        client_id: client.id,
        profile_slug: client.profile_slug ?? null,
        billing_name: b.billing_name ?? null,
        legal_name: b.legal_name ?? null,
        billing_email: b.billing_email ?? client.email ?? null,
        address_line: b.address_line ?? null,
        city: b.city ?? null,
        postal_code: b.postal_code ?? null,
        country: b.country ?? null,
        vat_id: b.vat_id ?? null,
        payoneer_email: b.payoneer_email ?? null,
        iban: b.iban ?? null,
        authorized: true,
        authorization_text: authText,
        authorized_at: nowIso,
        signer_ip: ip,
        signer_user_agent: ua,
        authorization_sha: sha,
        payoneer_status: "pending",
        // reset the local-sync flags so billing-sync.py re-drops + re-notifies
        json_dropped_at: null,
        notified_at: null,
      };

      const { error: upErr } = await admin
        .from("billing_profiles")
        .upsert(row, { onConflict: "client_id" });
      if (upErr) throw upErr;

      return json({ ok: true, client_id: client.id, sha });
    }

    if (action === "credentials") {
      // After signing the pilot agreement the client hands over a SCOPED API
      // token for their DNS / domain host so the pipeline can provision sending
      // infrastructure. Mirrors the "billing" action: verify ownership, store
      // with an audit hash, reset the local-sync flags.
      const authz = req.headers.get("Authorization") ?? "";
      const jwt = authz.replace(/^Bearer\s+/i, "");
      if (!jwt) return json({ error: "sign in first" }, 401);
      const { data: who, error: whoErr } = await admin.auth.getUser(jwt);
      if (whoErr || !who?.user) return json({ error: "invalid session" }, 401);

      const submissionId = String(payload.submission_id ?? "").trim();
      if (!submissionId) return json({ error: "missing submission_id" }, 400);

      const { data: sub } = await admin
        .from("onboarding_submissions")
        .select("id, client_id, raw_answers")
        .eq("id", submissionId)
        .maybeSingle();
      if (!sub?.client_id) return json({ error: "submission not found" }, 404);

      const { data: client } = await admin
        .from("clients")
        .select("id, auth_user_id, company, email, profile_slug")
        .eq("id", sub.client_id)
        .maybeSingle();
      if (!client) return json({ error: "client not found" }, 404);

      const { data: role } = await admin
        .from("user_roles").select("is_admin").eq("user_id", who.user.id).maybeSingle();
      const isAdmin = Boolean(role?.is_admin);
      if (client.auth_user_id !== who.user.id && !isAdmin) {
        return json({ error: "not your account" }, 403);
      }

      const cr = payload.credentials ?? {};
      if (!cr.authorized) return json({ error: "authorization required" }, 400);

      const ip = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim()
        || (payload.signer_ip ?? null);
      const ua = req.headers.get("user-agent") ?? (payload.signer_user_agent ?? null);
      const authText = String(cr.authorization_text ?? "").trim();
      const nowIso = new Date().toISOString();

      // Audit hash over the authorization text + identity + access handed over + ts.
      // Covers both the email-infra token and the social-account access so the
      // hash attests to whatever the client actually authorized.
      const hashInput = [
        authText, cr.registrar ?? "", cr.dns_host ?? "", cr.api_token ?? "",
        cr.social_handles ?? "", cr.asset_link ?? "",
        String(cr.social_access_confirmed ?? ""), ip ?? "", nowIso,
      ].join("|");
      const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(hashInput));
      const sha = Array.from(new Uint8Array(digest)).map((x) => x.toString(16).padStart(2, "0")).join("");

      const row = {
        client_id: client.id,
        profile_slug: client.profile_slug ?? null,
        registrar: cr.registrar ?? null,
        dns_host: cr.dns_host ?? (sub.raw_answers?.dns_host ?? null),
        api_token: cr.api_token ?? null,
        other_access: cr.other_access ?? null,
        // Social-media account access (social / both clients).
        social_handles: cr.social_handles ?? null,
        social_access_confirmed: cr.social_access_confirmed ?? null,
        social_business_id: cr.social_business_id ?? null,
        asset_link: cr.asset_link ?? null,
        content_approver: cr.content_approver ?? null,
        notes: cr.notes ?? null,
        authorized: true,
        authorization_text: authText,
        authorized_at: nowIso,
        signer_ip: ip,
        signer_user_agent: ua,
        authorization_sha: sha,
        // reset local-sync flags so credentials-sync.py re-writes + re-notifies
        written_to_env_at: null,
        notified_at: null,
      };

      const { error: upErr } = await admin
        .from("client_credentials")
        .upsert(row, { onConflict: "client_id" });
      if (upErr) throw upErr;

      return json({ ok: true, client_id: client.id, sha });
    }

    if (action === "connect_instagram") {
      // A social/both client connects their own Instagram: they paste a long-lived
      // Graph API token. Verify it against Meta server-side (this function runs on
      // Supabase, not behind the operator's local network filters), derive the IG
      // Business account, and store it on the client's credentials row.
      const authz = req.headers.get("Authorization") ?? "";
      const jwt = authz.replace(/^Bearer\s+/i, "");
      if (!jwt) return json({ error: "sign in first" }, 401);
      const { data: who, error: whoErr } = await admin.auth.getUser(jwt);
      if (whoErr || !who?.user) return json({ error: "invalid session" }, 401);

      const token = String(payload.token ?? "").trim();
      if (!token) return json({ error: "missing token" }, 400);

      const { data: client } = await admin
        .from("clients")
        .select("id, auth_user_id, profile_slug")
        .eq("auth_user_id", who.user.id)
        .maybeSingle();
      if (!client) return json({ error: "no client account for this user" }, 404);

      // Verify the token + derive the IG Business account via the Graph API.
      const G = "https://graph.facebook.com/v21.0";
      const acc = await (await fetch(`${G}/me/accounts?fields=instagram_business_account,name&access_token=${encodeURIComponent(token)}`)).json();
      if (acc.error) return json({ error: "Meta rejected the token: " + (acc.error.message ?? "invalid token") }, 400);
      const page = (acc.data ?? []).find((p: any) => p.instagram_business_account);
      if (!page) return json({ error: "No Instagram Business account is linked to a Facebook Page this token manages. Convert the account to Business/Creator and link a Page." }, 400);
      const igId = page.instagram_business_account.id;
      const me = await (await fetch(`${G}/${igId}?fields=username&access_token=${encodeURIComponent(token)}`)).json();
      if (!me.username) return json({ error: "Could not read the Instagram account." }, 400);

      const nowIso = new Date().toISOString();
      const { error: upErr } = await admin
        .from("client_credentials")
        .upsert({
          client_id: client.id,
          profile_slug: client.profile_slug ?? null,
          ig_access_token: token,
          ig_user_id: igId,
          ig_username: me.username,
          ig_token_verified_at: nowIso,
          ig_written_to_env_at: null,
        }, { onConflict: "client_id" });
      if (upErr) throw upErr;

      return json({ ok: true, username: me.username, ig_user_id: igId });
    }

    return json({ error: `unknown action: ${action}` }, 400);
  } catch (e) {
    console.error("auth-admin error", action, e);
    return json({ error: String((e as any)?.message ?? e) }, 500);
  }
});
