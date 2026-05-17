// Cloudflare Email Worker — inbound handler for the v4 cold-email stack.
//
// Receives every email landing on m1..m10.{PARENT_DOMAIN}.
// Classifies as: reply | bounce | complaint | unrelated.
// POSTs structured payload to n8n; n8n updates lead state and pauses sequences.
//
// Deployed by scripts/cf-bootstrap.sh. The literal __N8N_WEBHOOK_URL__ is rewritten
// at deploy time.
//
// Pricing: free tier is 100k invocations/day — orders of magnitude above any cold-email
// reply volume we'll ever see.

const N8N_WEBHOOK = '__N8N_WEBHOOK_URL__';

// ─── Classification helpers ────────────────────────────────────────────────

const BOUNCE_FROM_PATTERNS = [
  /mailer-daemon@/i,
  /postmaster@/i,
  /^bounces?\+/i,
  /^delivery-status/i,
];

const BOUNCE_SUBJECT_PATTERNS = [
  /undelivered/i,
  /delivery (status notification|failure)/i,
  /returned mail/i,
  /(mail|message) delivery failed/i,
  /address (not found|rejected)/i,
];

const COMPLAINT_HEADERS = [
  'X-Loop',
  'Feedback-Type', // ARF / Yahoo / AOL FBL
  'X-Complaints-To',
];

const COMPLAINT_FROM_PATTERNS = [
  /abuse@/i,
  /feedback-loop@/i,
];

function classify(message, headers) {
  const from = (headers.get('from') || '').toLowerCase();
  const subject = headers.get('subject') || '';

  // Complaint detection first (highest priority — suppression must happen)
  for (const h of COMPLAINT_HEADERS) {
    if (headers.has(h)) return 'complaint';
  }
  for (const re of COMPLAINT_FROM_PATTERNS) {
    if (re.test(from)) return 'complaint';
  }
  if (headers.get('feedback-type')) return 'complaint';

  // Bounce detection
  for (const re of BOUNCE_FROM_PATTERNS) {
    if (re.test(from)) return 'bounce';
  }
  for (const re of BOUNCE_SUBJECT_PATTERNS) {
    if (re.test(subject)) return 'bounce';
  }
  if (headers.get('x-failed-recipients')) return 'bounce';

  // If there's an In-Reply-To header pointing to one of our Message-IDs,
  // it's a reply. The n8n side will validate the Message-ID is one we sent.
  if (headers.get('in-reply-to') || headers.get('references')) {
    return 'reply';
  }

  // Otherwise it's mail we don't recognize — auto-responder, OOO, weird forward.
  return 'unrelated';
}

// ─── Body extraction ───────────────────────────────────────────────────────

async function readBody(message) {
  // Cloudflare Workers gives us a ReadableStream of the raw RFC822 message.
  // For lightweight classification we don't need full MIME parsing — just headers
  // (already provided) and the first ~4KB of text for n8n to log.
  const reader = message.raw.getReader();
  const chunks = [];
  let total = 0;
  const MAX = 4096; // bytes
  while (total < MAX) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    total += value.byteLength;
  }
  // Concatenate + decode as utf-8 (tolerant)
  const merged = new Uint8Array(total);
  let offset = 0;
  for (const c of chunks) { merged.set(c, offset); offset += c.byteLength; }
  return new TextDecoder('utf-8', { fatal: false }).decode(merged);
}

// ─── Main handler ──────────────────────────────────────────────────────────

export default {
  async email(message, env, ctx) {
    const headers = message.headers;
    const klass = classify(message, headers);
    const bodySnippet = await readBody(message);

    const payload = {
      class: klass,
      from: headers.get('from') || '',
      to: headers.get('to') || '',
      subject: headers.get('subject') || '',
      messageId: headers.get('message-id') || '',
      inReplyTo: headers.get('in-reply-to') || '',
      references: headers.get('references') || '',
      date: headers.get('date') || '',
      failedRecipients: headers.get('x-failed-recipients') || '',
      feedbackType: headers.get('feedback-type') || '',
      bodySnippet,
      receivedAt: new Date().toISOString(),
    };

    // Best-effort POST to n8n. Don't throw on failure — Cloudflare will retry the email
    // up to 3x if we throw, which would re-trigger this handler.
    try {
      await fetch(N8N_WEBHOOK, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch (e) {
      console.error('n8n webhook failed:', e.message);
    }

    // For replies we may want to forward to the human inbox too (so you actually see the reply).
    // For bounces/complaints, suppress (don't forward, don't reply).
    if (klass === 'reply') {
      try {
        await message.forward(env.HUMAN_INBOX || 'you@gmail.com');
      } catch (e) {
        // forwarding requires the destination to be verified in CF Email Routing
        console.error('forward failed:', e.message);
      }
    }

    // No further routing — drop the message after handling.
    // (If we wanted to silently bin and also acknowledge, we'd `message.setReject('')`.)
  },
};
