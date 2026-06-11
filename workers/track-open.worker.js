/**
 * track-open.worker.js — Cloudflare Worker that serves as Aureon's
 * self-hosted open-tracking pixel + click-tracking redirector.
 *
 * Resend's domain-level open_tracking flag is set true on all 10 Aureon
 * subdomains but their pipeline doesn't actually inject the pixel into
 * outbound HTML. So we inject our own pixel pointing here.
 *
 * Routes:
 *   GET /open/{send_log_id}            → log open, return 1x1 transparent GIF
 *   GET /click/{send_log_id}?u=<url>   → log click, 302 redirect to <url>
 *   GET /                              → tiny health check
 *
 * Setup (one-time):
 *   1. Cloudflare dashboard → Workers & Pages → Create Worker
 *   2. Paste this file as the Worker code
 *   3. Add secret bindings (Settings → Variables → Add secret):
 *        SUPABASE_URL=https://YOUR_PROJECT.supabase.co
 *        SUPABASE_SERVICE_KEY=eyJ...     (service-role key, NOT anon)
 *   4. (Optional) Add a custom domain: track.aureonglobal.de
 *   5. Deploy
 *
 * Then update email_render.py to inject:
 *   <img src="https://<worker-domain>/open/{send_log_id}" width="1" height="1"
 *        alt="" style="display:block">
 *
 * Privacy: we log only opened_at timestamp and clicked_at + URL. No IP, no
 * user agent persisted — only the send_log row we already own is touched.
 */

const PIXEL_GIF_B64 = "R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==";

/**
 * The track token in the URL is the hex part of the Message-ID we
 * generated in build_payload (e.g. msg_id = "<HEX.TS@DOMAIN>"). We look
 * up the send_log row via PostgREST `like` against message_id.
 */
async function patchSendLogByToken(env, token, patch) {
    const tokenCleaned = token.replace(/[^a-f0-9]/gi, "");
    if (!tokenCleaned || tokenCleaned.length < 12) return false;
    const url = `${env.SUPABASE_URL}/rest/v1/send_log?message_id=like.*${tokenCleaned}*`;
    const resp = await fetch(url, {
        method: "PATCH",
        headers: {
            "apikey": env.SUPABASE_SERVICE_KEY,
            "Authorization": `Bearer ${env.SUPABASE_SERVICE_KEY}`,
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        },
        body: JSON.stringify(patch)
    });
    if (!resp.ok) {
        console.log(`supabase patch failed ${resp.status}: ${await resp.text()}`);
        return false;
    }
    return true;
}

function pixelResponse() {
    return new Response(Uint8Array.from(atob(PIXEL_GIF_B64), c => c.charCodeAt(0)), {
        headers: {
            "Content-Type": "image/gif",
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "X-Robots-Tag": "noindex, nofollow"
        }
    });
}

export default {
    async fetch(request, env) {
        const url = new URL(request.url);
        const parts = url.pathname.split("/").filter(Boolean);

        // GET /open/{send_log_id}
        if (parts[0] === "open" && parts[1]) {
            const sendLogId = parts[1].replace(/\.gif$/, "");
            // Fire-and-forget: don't block pixel response on Supabase
            const now = new Date().toISOString();
            await patchSendLogByToken(env, sendLogId, { opened_at: now });
            return pixelResponse();
        }

        // GET /click/{send_log_id}?u=<url>
        if (parts[0] === "click" && parts[1]) {
            const sendLogId = parts[1];
            const target = url.searchParams.get("u");
            if (!target) return new Response("missing u", { status: 400 });
            const now = new Date().toISOString();
            await patchSendLogByToken(env, sendLogId, { clicked_at: now });
            return Response.redirect(target, 302);
        }

        // GET / — health
        if (parts.length === 0) {
            return new Response("aureon track ok\n", {
                headers: { "Content-Type": "text/plain" }
            });
        }

        return new Response("not found", { status: 404 });
    }
};
