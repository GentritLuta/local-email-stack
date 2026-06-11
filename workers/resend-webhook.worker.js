/**
 * resend-webhook.worker.js — Cloudflare Worker that receives Resend webhook
 * events and writes the REAL bounce reason (and real-time delivery/complaint
 * status) into send_log, by resend_id.
 *
 * WHY: Resend's GET /emails/{id} API returns no bounce reason (only
 * last_event="bounced"), so the polling reconciler can never explain a bounce.
 * The detailed reason (Permanent/Transient + subType + SMTP message) is ONLY
 * delivered via webhooks. This captures it, in real time.
 *
 * Events handled: email.delivered, email.bounced, email.complained,
 * email.delivery_delayed. (opens/clicks are handled by track-open.worker.js.)
 *
 * Setup (one-time, ~5 min — mirrors workers/README.md):
 *   1. Cloudflare dash -> Workers & Pages -> Create Worker -> name "aureon-resend-webhook"
 *   2. Edit code -> paste this file -> Save and deploy
 *   3. Settings -> Variables and Secrets -> add as Secret:
 *        SUPABASE_URL           = https://<project-ref>.supabase.co
 *        SUPABASE_SERVICE_KEY   = service-role key (NOT anon)
 *        RESEND_WEBHOOK_SECRET  = whsec_...  (from the Resend webhook you create)
 *   4. Copy the Worker URL (https://aureon-resend-webhook.<acct>.workers.dev)
 *   5. Resend dash -> Webhooks -> Add Endpoint -> paste the URL, subscribe to
 *      email.delivered, email.bounced, email.complained, email.delivery_delayed
 *      -> copy its Signing Secret into RESEND_WEBHOOK_SECRET above.
 *      (Or run scripts/configure-resend-webhook.py once you have the URL.)
 */

async function patchByResendId(env, emailId, patch) {
    const url = `${env.SUPABASE_URL}/rest/v1/send_log?resend_id=eq.${encodeURIComponent(emailId)}`;
    const resp = await fetch(url, {
        method: "PATCH",
        headers: {
            "apikey": env.SUPABASE_SERVICE_KEY,
            "Authorization": `Bearer ${env.SUPABASE_SERVICE_KEY}`,
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        body: JSON.stringify(patch),
    });
    if (!resp.ok) console.log(`supabase patch ${resp.status}: ${await resp.text()}`);
    return resp.ok;
}

/** Hard-suppress a recipient (Permanent bounce only): stop all future sends. */
async function suppressProspect(env, email) {
    const url = `${env.SUPABASE_URL}/rest/v1/prospects?email=eq.${encodeURIComponent(email)}`;
    try {
        const resp = await fetch(url, {
            method: "PATCH",
            headers: {
                "apikey": env.SUPABASE_SERVICE_KEY,
                "Authorization": `Bearer ${env.SUPABASE_SERVICE_KEY}`,
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            body: JSON.stringify({ verified: false, unsubscribed: true }),
        });
        if (!resp.ok) console.log(`suppress ${resp.status}: ${await resp.text()}`);
    } catch (e) { console.log("suppress failed:", e.message); }
}

/** Verify the Svix signature Resend signs webhooks with. */
async function verify(env, headers, rawBody) {
    const secret = env.RESEND_WEBHOOK_SECRET;
    if (!secret) return true;                     // not yet configured -> accept (warn)
    const id = headers.get("svix-id");
    const ts = headers.get("svix-timestamp");
    const sigHeader = headers.get("svix-signature");
    if (!id || !ts || !sigHeader) return false;
    const keyB64 = secret.startsWith("whsec_") ? secret.slice(6) : secret;
    const keyBytes = Uint8Array.from(atob(keyB64), c => c.charCodeAt(0));
    const signed = `${id}.${ts}.${rawBody}`;
    const key = await crypto.subtle.importKey("raw", keyBytes,
        { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
    const mac = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(signed));
    const expected = btoa(String.fromCharCode(...new Uint8Array(mac)));
    // svix-signature is space-separated "v1,<b64>" pairs
    return sigHeader.split(" ").some(p => p.split(",")[1] === expected);
}

export default {
    async fetch(request, env) {
        if (request.method === "GET")
            return new Response("aureon resend-webhook ok\n", { headers: { "Content-Type": "text/plain" } });
        if (request.method !== "POST")
            return new Response("method not allowed", { status: 405 });

        const raw = await request.text();
        if (!(await verify(env, request.headers, raw)))
            return new Response("bad signature", { status: 401 });

        let evt;
        try { evt = JSON.parse(raw); } catch { return new Response("bad json", { status: 400 }); }
        const type = evt.type || "";
        const data = evt.data || {};
        const emailId = data.email_id || data.id;
        if (!emailId) return new Response("no email_id", { status: 200 });

        let patch = null;
        if (type === "email.bounced") {
            const b = data.bounce || {};
            const reason = [b.type, b.subType].filter(Boolean).join("/") +
                           (b.message ? `: ${b.message}` : "");
            patch = { bounced: true, delivered: false, error: (reason || "bounced").slice(0, 480) };
            // Hard/soft-aware suppression: permanently suppress the recipient ONLY
            // on a Permanent bounce. Transient bounces (greylisting, full mailbox,
            // temporary defer) are recoverable — record them for rate tracking but
            // let the sequence retry instead of killing a good lead.
            if (String(b.type || "").toLowerCase() === "permanent") {
                const to = Array.isArray(data.to) ? data.to[0] : data.to;
                if (to) await suppressProspect(env, to);
            }
        } else if (type === "email.complained") {
            patch = { complained: true, error: "complaint (spam report)" };
        } else if (type === "email.delivered") {
            patch = { delivered: true };
        } else if (type === "email.delivery_delayed") {
            patch = { error: "delivery delayed (transient)" };
        }
        if (patch) await patchByResendId(env, emailId, patch);
        return new Response("ok", { status: 200 });
    },
};
