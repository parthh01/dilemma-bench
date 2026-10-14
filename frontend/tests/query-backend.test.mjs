import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

// Execute the actual route exports; only Next's response wrapper and fetch are mocked.
const source = fs.readFileSync(new URL('../src/app/api/query-backend/route.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function loadRoute(backend, fetchImpl) {
  const exports = {};
  const context = vm.createContext({
    exports, URL, Headers,
    process: { env: { BACKEND_URL: backend, BACKEND_UI_SECRET: 'synthetic-proxy-secret' } },
    console: { error() {} },
    fetch: fetchImpl,
    require(name) {
      assert.equal(name, 'next/server');
      return { NextResponse: { json: (body, init) => Response.json(body, init) } };
    },
  });
  new vm.Script(compiled, { filename: 'query-backend/route.ts' }).runInContext(context);
  return exports;
}

function requestFor(method, endpoint) {
  const url = new URL('https://frontend.example/api/query-backend');
  url.searchParams.set('endpoint', endpoint);
  return new Request(url, {
    method,
    headers: { Authorization: 'Bearer synthetic-user-token', 'Content-Type': 'application/json' },
    ...(method === 'POST' ? { body: JSON.stringify({ action: 'cooperate' }) } : {}),
  });
}

for (const method of ['GET', 'POST']) {
  test(`${method} rejects origin changes, traversal, and ambiguous paths before fetch`, async () => {
    let calls = 0;
    const route = loadRoute('https://backend.example/service', async () => {
      calls += 1;
      return Response.json({ unexpected: true });
    });
    const attacks = [
      '.recipient.example/api', 'https://recipient.example/api', '//recipient.example/api',
      '/\\recipient.example/api', '/api\\admin', '/api#fragment', '/api\r\nX-Injected:value',
      '/api/%0aadmin', '/api/%5cadmin', '/%2frecipient.example/api', '/api//admin',
      '/../admin', '/api/../../admin', '/%2e%2e/admin', '/api/%252e%252e/admin', '/api?bad=%0a',
    ];
    for (const endpoint of attacks) {
      const response = await route[method](requestFor(method, endpoint));
      assert.equal(response.status, 400, endpoint);
      assert.equal(calls, 0, endpoint);
      assert.equal((await response.json()).error, 'Invalid endpoint path');
    }
  });

  test(`${method} preserves legitimate query paths beneath each configured backend base`, async () => {
    for (const base of ['https://backend.example', 'https://backend.example/', 'https://backend.example/service', 'https://backend.example/service/']) {
      const calls = [];
      const route = loadRoute(base, async (...args) => {
        calls.push(args);
        return Response.json({ ok: true });
      });
      const response = await route[method](requestFor(method, '/api/matches/history/test-id?limit=50&filter=some%20value'));
      assert.equal(response.status, 200);
      assert.deepEqual(await response.json(), { ok: true });
      assert.equal(calls.length, 1);
      const [target, options] = calls[0];
      const url = new URL(target);
      assert.equal(url.origin, 'https://backend.example');
      assert.equal(url.pathname, (base.includes('/service') ? '/service' : '') + '/api/matches/history/test-id');
      assert.equal(url.searchParams.get('limit'), '50');
      assert.equal(url.searchParams.get('filter'), 'some value');
      assert.equal(options.method, method);
      assert.equal(options.headers['X-API-Key'], 'synthetic-proxy-secret');
      assert.equal(options.headers.Authorization, 'Bearer synthetic-user-token');
      assert.equal(options.redirect, 'error');
      if (method === 'POST') assert.deepEqual(JSON.parse(options.body), { action: 'cooperate' });
    }
  });

  test(`${method} refuses redirect following and returns an error without another request`, async () => {
    let calls = 0;
    const route = loadRoute('https://backend.example', async (_target, options) => {
      calls += 1;
      // Native fetch rejects a redirect under redirect:error rather than forwarding headers.
      assert.equal(options.redirect, 'error');
      throw new TypeError('fetch failed: unexpected redirect');
    });
    const response = await route[method](requestFor(method, '/api/redirect'));
    assert.equal(response.status, 500);
    assert.equal(calls, 1);
    const result = await response.json();
    assert.equal(result.error, 'Failed to fetch from backend');
    assert.ok(!JSON.stringify(result).includes('synthetic-proxy-secret'));
  });
}
