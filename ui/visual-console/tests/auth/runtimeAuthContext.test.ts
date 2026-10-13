import assert from 'node:assert/strict';
import test from 'node:test';

import {
  getRuntimeAuthContext,
  getRuntimeHandoff,
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
