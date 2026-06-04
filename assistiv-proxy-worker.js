/* ============================================================
   ASSISTIV SYSTEMS — Anthropic API Proxy
   Cloudflare Worker · v1.0

   Environment variables to set in Cloudflare dashboard:
   - ANTHROPIC_API_KEY : your key from console.anthropic.com
   - ALLOWED_ORIGIN    : https://assistiv.health

   Also works for:
   - silegrand.github.io/assistivagents  (FEP tools / Ada)
   - www.resiliencetools.xyz              (RESILIENCE screening)
   ============================================================ */

const ALLOWED_ORIGINS = [
  'https://assistiv.health',
  'https://www.assistiv.health',
  'https://silegrand.github.io',
  'https://www.resiliencetools.xyz',
  'http://localhost',        // local dev
  'http://127.0.0.1',        // local dev
];

const MAX_TOKENS_LIMIT = 1000;  // hard ceiling regardless of what the client requests

export default {
  async fetch(request, env) {

    const origin = request.headers.get('Origin') || '';

    // ── CORS preflight ──────────────────────────────────────────────
    if (request.method === 'OPTIONS') {
      return corsResponse(null, 204, origin);
    }

    // ── Only allow POST ─────────────────────────────────────────────
    if (request.method !== 'POST') {
      return new Response('Method not allowed', { status: 405 });
    }

    // ── Origin check ────────────────────────────────────────────────
    const originAllowed = ALLOWED_ORIGINS.some(o => origin.startsWith(o));
    if (!originAllowed) {
      console.log(`Blocked origin: ${origin}`);
      return new Response('Forbidden', { status: 403 });
    }

    // ── API key present? ────────────────────────────────────────────
    if (!env.ANTHROPIC_API_KEY) {
      return corsResponse(
        JSON.stringify({ error: 'API key not configured' }),
        500, origin, 'application/json'
      );
    }

    // ── Parse and sanitise the request body ─────────────────────────
    let body;
    try {
      body = await request.json();
    } catch {
      return corsResponse(
        JSON.stringify({ error: 'Invalid JSON body' }),
        400, origin, 'application/json'
      );
    }

    // Enforce max_tokens ceiling — protect against runaway requests
    if (!body.max_tokens || body.max_tokens > MAX_TOKENS_LIMIT) {
      body.max_tokens = MAX_TOKENS_LIMIT;
    }

    // Require a model — default to Sonnet if missing
    if (!body.model) {
      body.model = 'claude-sonnet-4-20250514';
    }

    // ── Forward to Anthropic ─────────────────────────────────────────
    try {
      const anthropicResp = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: {
          'Content-Type':      'application/json',
          'x-api-key':         env.ANTHROPIC_API_KEY,
          'anthropic-version': '2023-06-01',
        },
        body: JSON.stringify(body),
      });

      const data = await anthropicResp.json();

      // Pass Anthropic errors back clearly
      if (!anthropicResp.ok) {
        console.error('Anthropic error:', anthropicResp.status, data);
        return corsResponse(
          JSON.stringify({ error: data?.error?.message || 'Anthropic API error', status: anthropicResp.status }),
          anthropicResp.status, origin, 'application/json'
        );
      }

      return corsResponse(
        JSON.stringify(data),
        200, origin, 'application/json'
      );

    } catch (err) {
      console.error('Worker fetch error:', err);
      return corsResponse(
        JSON.stringify({ error: 'Worker error — please try again' }),
        500, origin, 'application/json'
      );
    }
  }
};

// ── CORS helper ─────────────────────────────────────────────────────────────
function corsResponse(body, status, origin, contentType = 'text/plain') {
  const headers = {
    'Access-Control-Allow-Origin':  origin || '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age':       '86400',
  };
  if (contentType) headers['Content-Type'] = contentType;

  return new Response(body, { status, headers });
}
