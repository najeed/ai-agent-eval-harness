import assert from 'node:assert/strict';
import test from 'node:test';

import {
  getRuntimeAuthContext,
  getRuntimeHandoff,
  authorizedRuntimeFetch,
  clearRuntimeAuthCaches,
  switchRuntimeContext,
} from '../../src/auth/runtimeAuthContext.js';

const first = {
  authenticated: true,
  context_version: '2',
  context: { org_id: 'o-a', tenant_id: 't-a', workspace_id: 'w-a', active_environment: 'sandbox' },
  authorized_contexts: [{ org_id: 'o-a', tenant_id: 't-a', workspace_id: 'w-a', environments: ['sandbox', 'staging'] }],
};

test('runtime context switch sends only workspace/environment and refreshes the read model', async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  let reads = 0;
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    if (url === '/api/auth/context') return new Response(JSON.stringify({ context_version: '2' }), { status: 200 });
    reads += 1;
    const current = reads === 1 ? first : {
      ...first,
      context: { ...first.context, active_environment: 'staging' },
    };
    return new Response(JSON.stringify(current), { status: 200 });
  };
  await getRuntimeAuthContext();
  const refreshed = await switchRuntimeContext('w-a', 'staging');
  assert.equal(refreshed.context?.active_environment, 'staging');
  assert.deepEqual(JSON.parse(String(calls[1].init?.body)), { workspace_id: 'w-a', active_environment: 'staging' });
  assert.equal(calls[1].url, '/api/auth/context');
});

test('authorized fetch issues a handoff, retries once, and never adds scope headers', async () => {
  clearRuntimeAuthCaches();
  let handoffs = 0;
  let requests = 0;
  globalThis.fetch = async (url, init) => {
    if (url === '/api/auth/handoff') return new Response(JSON.stringify({ token: `token-${++handoffs}` }), { status: 200 });
    requests += 1;
    const headers = new Headers(init?.headers);
    assert.equal(headers.get('X-Handoff-Token'), `token-${requests}`);
    assert.equal(headers.has('X-Tenant-Id'), false);
    return new Response('', { status: requests === 1 ? 401 : 200 });
  };
  assert.equal((await authorizedRuntimeFetch('signed-extension', '/extension-data')).status, 200);
  assert.equal(handoffs, 2);
});

test('handoff tokens are reused only for the same extension until Core clears them', async () => {
  clearRuntimeAuthCaches();
  let handoffs = 0;
  globalThis.fetch = async (url) => {
    assert.equal(url, '/api/auth/handoff');
    return new Response(JSON.stringify({ token: `token-${++handoffs}` }), { status: 200 });
  };

  assert.equal(await getRuntimeHandoff('extension-a'), 'token-1');
  assert.equal(await getRuntimeHandoff('extension-a'), 'token-1');
  assert.equal(await getRuntimeHandoff('extension-b'), 'token-2');
  assert.equal(handoffs, 2);

  clearRuntimeAuthCaches();
  assert.equal(await getRuntimeHandoff('extension-a'), 'token-3');
  assert.equal(handoffs, 3);
});

test('denied switch rejects and clears a cached handoff credential', async () => {
  let handoffRequests = 0;
  globalThis.fetch = async (url) => {
    if (url === '/api/auth/handoff') {
      handoffRequests += 1;
      return new Response(JSON.stringify({ token: 'cached' }), { status: 200 });
    }
    return new Response(JSON.stringify({ error: 'denied' }), { status: 403 });
  };
  await getRuntimeHandoff('generic-extension');
  await assert.rejects(() => switchRuntimeContext('w-a', 'production'));
  await getRuntimeHandoff('generic-extension');
  assert.equal(handoffRequests, 2);
});
