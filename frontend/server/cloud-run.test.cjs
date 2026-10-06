const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createProxy } = require('./cloud-run.cjs');

function response() {
  return { headers: {}, setHeader(k, v) { this.headers[k] = v; },
    status(code) { this.code = code; return this; },
    json(value) { this.body = value; return this; },
    send(value) { this.body = value; return this; } };
}
const idToken = `header.${Buffer.from(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600 })).toString('base64url')}.signature`;
function harness(upstreamResponse = () => new Response('{"ok":true}', { status: 200 })) {
  const calls = [];
  const proxy = createProxy({ oidc: async () => 'vercel-identity', fetchImpl: async (url, init) => {
    calls.push({ url, init });
    if (url.includes('sts.googleapis.com')) return Response.json({ access_token: 'google-access' });
    if (url.includes('iamcredentials.googleapis.com')) return Response.json({ token: idToken });
    return upstreamResponse();
  } });
  return { calls, proxy };
}
test('separate IAM and user tokens; strip spoofed IP, cookies and IAM headers; cache token', async () => {
  const { proxy, calls } = harness();
  for (const ip of ['203.0.113.1', '203.0.113.2']) {
    const res = response();
    await proxy({ method: 'POST', url: '/api/chat', body: { message: 'test' }, headers: {
      'x-forwarded-for': ip, authorization: 'Bearer supabase-user', 'x-guest-session': 'guest',
      'x-poomsemi-client-ip': 'spoof', 'x-serverless-authorization': 'spoof', cookie: 'private',
    } }, res);
    assert.equal(res.code, 200);
  }
  assert.equal(calls.length, 4);
  const headers = calls[3].init.headers;
  assert.equal(headers['X-Serverless-Authorization'], 'Bearer ' + idToken);
  assert.equal(headers.authorization, 'Bearer supabase-user');
  assert.equal(headers['X-Poomsemi-Client-IP'], '203.0.113.2');
  assert.equal(headers.cookie, undefined);
  assert.equal(headers['x-serverless-authorization'], undefined);
  assert.equal(calls[3].init.redirect, 'manual');
});
test('reject traversal, arbitrary hosts, missing or multi-valued IP before authentication', async () => {
  const { proxy, calls } = harness();
  for (const url of ['https://evil.test/api/chat', '/api/../admin', '/api/%2e%2e/admin', '/api//chat']) {
    const res = response();
    await proxy({ method: 'GET', url, headers: { 'x-forwarded-for': '203.0.113.1' } }, res);
    assert.equal(res.code, 404);
  }
  for (const ip of [undefined, '203.0.113.1, 203.0.113.2', 'spoof']) {
    const res = response();
    await proxy({ method: 'GET', url: '/api/usage', headers: { 'x-forwarded-for': ip } }, res);
    assert.equal(res.code, 503);
  }
  assert.equal(calls.length, 0);
});
test('preserve download bytes and filename, quota status and Retry-After', async () => {
  const { proxy } = harness(() => new Response(new Uint8Array([0, 255, 20]), {
    status: 429, headers: { 'content-disposition': "attachment; filename*=UTF-8''test.xlsx", 'retry-after': '60' },
  }));
  const res = response();
  await proxy({ method: 'GET', url: '/api/export/test.xlsx', headers: { 'x-forwarded-for': '203.0.113.1' } }, res);
  assert.equal(res.code, 429);
  assert.equal(res.headers['retry-after'], '60');
  assert.ok(res.headers['content-disposition'].includes('test.xlsx'));
  assert.deepEqual(res.body, Buffer.from([0, 255, 20]));
  assert.equal(res.headers['Cache-Control'], 'no-store');
});
test('failed token exchange is retried and never sends a backend request', async () => {
  let calls = 0;
  const proxy = createProxy({ oidc: async () => 'identity', fetchImpl: async () => {
    calls++; return new Response('failure', { status: 403 });
  } });
  for (let index = 0; index < 2; index++) {
    const res = response();
    await proxy({ method: 'GET', url: '/api/usage', headers: { 'x-forwarded-for': '203.0.113.1' } }, res);
    assert.equal(res.code, 502);
    assert.deepEqual(res.body, { detail: 'BACKEND_UNAVAILABLE' });
  }
  assert.equal(calls, 2);
});
