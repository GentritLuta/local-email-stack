// heal.js — innovation #1, AI-healing scraper layer.
//
// Strategy:
//   1. Tier 1: run the source's CSS selectors from selectors.yaml. If yield is
//      healthy (>= 60% of expected, all required fields present on >= 70% of rows),
//      return the rows. ~50ms per result.
//
//   2. Tier 2 (vision fallback): if Tier 1 yield is low, screenshot the page
//      and ask Qwen2-VL via Ollama to extract listings directly. Slower (~5s per
//      page) but resilient to DOM changes.
//
//   3. Tier 3 (selector regeneration): with Tier 2 successful, ask Qwen2-VL again,
//      this time given the full HTML structure, to produce updated CSS selectors.
//      Commit them back to selectors.yaml.
//
// Result: scrapers self-repair without human intervention.

import fs from 'node:fs/promises';
import path from 'node:path';
import yaml from 'js-yaml';

const OLLAMA_URL = process.env.OLLAMA_URL || 'http://ollama:11434';
const VISION_MODEL = process.env.VISION_MODEL || 'qwen2-vl:7b';
const SELECTORS_PATH = process.env.SELECTORS_PATH || '/app/selectors.yaml';

// ─── Quality assessment ────────────────────────────────────────────────────

const REQUIRED_BY_SOURCE = {
  google_maps: ['name', 'address'],
  yelp: ['name'],
  bing_places: ['name'],
};

const EXPECTED_BY_SOURCE = {
  google_maps: 15,  // typically returns 20 per page; flag if < 15
  yelp: 8,
  bing_places: 8,
};

export function assessYield(source, rows) {
  const required = REQUIRED_BY_SOURCE[source] || ['name'];
  const expected = EXPECTED_BY_SOURCE[source] || 5;
  const fillRate = (field) =>
    rows.length === 0 ? 0 : rows.filter(r => r[field] && r[field].length > 0).length / rows.length;

  const lowVolume = rows.length < expected * 0.6;
  const fieldHoles = required.some(f => fillRate(f) < 0.7);
  return { healthy: !lowVolume && !fieldHoles, lowVolume, fieldHoles, rowCount: rows.length };
}

// ─── Tier 2: vision extraction ─────────────────────────────────────────────

export async function extractWithVision(source, page, screenshotPath) {
  await page.screenshot({ path: screenshotPath, fullPage: true });
  const imgB64 = (await fs.readFile(screenshotPath)).toString('base64');

  const sourceHints = {
    google_maps: 'Google Maps search results — each card has a business name, rating, address, phone, website, and category.',
    yelp: 'Yelp search results — each card has a name, rating, review count, address, phone, category.',
    bing_places: 'Bing local-business results — each card has a name, address, phone, website.',
  };

  const prompt = `You are extracting structured data from a screenshot.

Source context: ${sourceHints[source] || 'a list of local businesses.'}

Return ONLY a JSON array. Each element MUST have:
  { "name": "...", "address": "...", "phone": "...", "website": "...", "rating": "...", "category": "..." }

Missing fields → empty string. Do NOT invent data. Do NOT add commentary.`;

  const res = await fetch(`${OLLAMA_URL}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: VISION_MODEL,
      messages: [{ role: 'user', content: prompt, images: [imgB64] }],
      format: 'json',
      stream: false,
    }),
  });
  const body = await res.json();
  try {
    const parsed = JSON.parse(body.message.content);
    return Array.isArray(parsed) ? parsed : (parsed.results || []);
  } catch {
    return [];
  }
}

// ─── Tier 3: regenerate selectors ──────────────────────────────────────────

export async function regenerateSelectors(source, page, sampleRows) {
  if (sampleRows.length < 3) return null; // need a few examples

  // Hand the LLM the trimmed page HTML + the rows we recovered via vision, and ask
  // it to produce CSS selectors that would have extracted these rows directly.
  const html = await page.content();
  const trimmedHtml = html.length > 60000 ? html.slice(0, 30000) + '...[truncated]...' + html.slice(-30000) : html;

  const prompt = `Given this HTML page and these rows we extracted from it, produce CSS selectors that would extract the rows directly from the DOM. Return JSON matching this schema:
{
  "results_container": "...",
  "result_row": "...",
  "fields": { "name": "...", "address": "...", "phone": "...", "website": "...", "rating": "...", "category": "..." }
}

Use Playwright selector syntax. ">>text" suffix means "innerText of matched element". ">>attr" means "attribute named attr".

HTML (truncated):
\`\`\`html
${trimmedHtml}
\`\`\`

Sample rows we extracted:
\`\`\`json
${JSON.stringify(sampleRows.slice(0, 5), null, 2)}
\`\`\``;

  const res = await fetch(`${OLLAMA_URL}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: VISION_MODEL,
      messages: [{ role: 'user', content: prompt }],
      format: 'json',
      stream: false,
    }),
  });
  const body = await res.json();
  try {
    return JSON.parse(body.message.content);
  } catch {
    return null;
  }
}

export async function commitSelectors(source, newSelectors) {
  const current = yaml.load(await fs.readFile(SELECTORS_PATH, 'utf8'));
  const today = new Date().toISOString().slice(0, 10);
  current[source] = {
    ...current[source],
    ...newSelectors,
    _auto_healed_at: today,
  };
  await fs.writeFile(
    SELECTORS_PATH,
    `# selectors.yaml — auto-edited by heal.js on ${today}\n` + yaml.dump(current, { lineWidth: 100 }),
    'utf8'
  );
}

// ─── Combined: scrape with auto-heal ───────────────────────────────────────

export async function scrapeWithHeal({ source, page, runTier1, telemetry = () => {} }) {
  // Tier 1
  let rows;
  try { rows = await runTier1(); }
  catch (e) { telemetry({ tier: 1, ok: false, error: e.message }); rows = []; }

  const t1 = assessYield(source, rows);
  if (t1.healthy) { telemetry({ tier: 1, ok: true, rowCount: rows.length }); return rows; }

  telemetry({ tier: 1, ok: false, ...t1 });

  // Tier 2 — vision
  const screenshotPath = `/tmp/heal-${source}-${Date.now()}.png`;
  const visionRows = await extractWithVision(source, page, screenshotPath);
  const t2 = assessYield(source, visionRows);
  telemetry({ tier: 2, ok: t2.healthy, rowCount: visionRows.length });

  // Tier 3 — selector regeneration (only if vision worked)
  if (t2.healthy) {
    const newSelectors = await regenerateSelectors(source, page, visionRows);
    if (newSelectors) {
      await commitSelectors(source, newSelectors);
      telemetry({ tier: 3, ok: true, action: 'selectors_committed' });
    } else {
      telemetry({ tier: 3, ok: false, action: 'regeneration_failed' });
    }
  }

  // Return whatever we have — vision rows preferred; fall back to tier-1 stragglers.
  return visionRows.length > 0 ? visionRows : rows;
}
