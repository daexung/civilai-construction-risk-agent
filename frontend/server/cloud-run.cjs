'use strict';
const { isIP } = require('node:net');

const upstream = 'https://poomsemi-api-691785957289.asia-northeast3.run.app';
const provider = '//iam.googleapis.com/projects/691785957289/locations/global/workloadIdentityPools/poomsemi-vercel/providers/vercel';
const caller = 'poomsemi-vercel-caller@civil-ai-jds.iam.gserviceaccount.com';

function createProxy({ fetchImpl = fetch, oidc = async () => {
  const { getVercelOidcToken } = await import('@vercel/oidc');
  return getVercelOidcToken();
} } = {}) {
  let cached, pending;
  async function token() {
    if (cached && cached.until > Date.now()) return cached.value;
    if (pending) return pending;
    pending = (async () => {
      const exchanged = await fetchImpl('https://sts.googleapis.com/v1/token', {
        method: 'POST', signal: AbortSignal.timeout(15000),
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ audience: provider,
          grantType: 'urn:ietf:params:oauth:grant-type:token-exchange',
          requestedTokenType: 'urn:ietf:params:oauth:token-type:access_token',
          subjectTokenType: 'urn:ietf:params:oauth:token-type:jwt',
          subjectToken: await oidc(), scope: 'https://www.googleapis.com/auth/cloud-platform' }),
      });
      if (!exchanged.ok) throw new Error('GCP_TOKEN_EXCHANGE_FAILED');
      const { access_token: accessToken } = await exchanged.json();
      if (!accessToken) throw new Error('GCP_TOKEN_EXCHANGE_FAILED');
      const signed = await fetchImpl(`https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/${caller}:generateIdToken`, {
        method: 'POST', signal: AbortSignal.timeout(15000),
        headers: { Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ audience: upstream, includeEmail: true }),
      });
      if (!signed.ok) throw new Error('GCP_ID_TOKEN_FAILED');
      const { token: value } = await signed.json();
      const expires = JSON.parse(Buffer.from(value.split('.')[1], 'base64url').toString()).exp;
      if (!Number.isFinite(expires) || expires * 1000 <= Date.now() + 60000) throw new Error('GCP_ID_TOKEN_FAILED');
      cached = { value, until: expires * 1000 - 60000 };
      return value;
    })();
    try { return await pending; } finally { pending = null; }
  }
  return async function proxy(req, res) {
    res.setHeader('Cache-Control', 'no-store');
    const method = req.method || 'GET';
    if (!['GET', 'POST', 'PATCH', 'DELETE'].includes(method)) return res.status(405).json({ detail: 'METHOD_NOT_ALLOWED' });
    const raw = req.url || '';
    const path = raw.split('?')[0];
    // Never accept a caller-supplied host or path traversal, including encoded traversal.
    if (!/^\/api\/[A-Za-z0-9_./-]+$/.test(path) || path.includes('..') || path.includes('//')) {
      return res.status(404).json({ detail: 'NOT_FOUND' });
    }
    // Vercel overwrites this header at its edge. Do not accept custom client-IP headers.
    const ip = req.headers['x-forwarded-for'];
    if (typeof ip !== 'string' || !isIP(ip.trim())) return res.status(503).json({ detail: 'CLIENT_IP_UNAVAILABLE' });
    let body;
    if (method === 'POST' || method === 'PATCH' || method === 'DELETE') {
      if (req.body != null) body = typeof req.body === 'string' ? req.body : JSON.stringify(req.body);
      if (body && Buffer.byteLength(body) > 2 * 1024 * 1024) return res.status(413).json({ detail: 'REQUEST_TOO_LARGE' });
    }
    try {
      const headers = {
        'X-Serverless-Authorization': `Bearer ${await token()}`,
        'X-Poomsemi-Client-IP': ip.trim(),
      };
      for (const name of ['authorization', 'x-guest-session', 'content-type', 'accept']) {
        const value = req.headers[name];
        if (typeof value === 'string') headers[name] = value;
      }
      const response = await fetchImpl(upstream + raw, {
        method, headers, body, redirect: 'manual', signal: AbortSignal.timeout(115000),
      });
      // Never send credentials to a redirect or return internal auth failure pages.
      if (response.status >= 300 && response.status < 400) throw new Error('UPSTREAM_REDIRECT');
      for (const name of ['content-type', 'content-disposition', 'retry-after']) {
        const value = response.headers.get(name);
        if (value) res.setHeader(name, value);
      }
      res.status(response.status).send(Buffer.from(await response.arrayBuffer()));
    } catch (error) {
      // Log only a bounded category, never tokens, URLs with queries, or request bodies.
      const category = ['GCP_TOKEN_EXCHANGE_FAILED', 'GCP_ID_TOKEN_FAILED', 'UPSTREAM_REDIRECT'].includes(error.message)
        ? error.message : 'UPSTREAM_UNAVAILABLE';
      console.error('cloud_run_proxy', category);
      res.status(502).json({ detail: 'BACKEND_UNAVAILABLE' });
    }
  };
}
module.exports = { createProxy };
