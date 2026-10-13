import { expect, test } from '@playwright/test';
import { createHash } from 'node:crypto';

const sri = (source: string) => `sha256-${createHash('sha256').update(source).digest('base64')}`;

const initialContext = {
  org_id: 'northstar-health', tenant_id: 'northstar-health',
  workspace_id: 'utilization-management', active_environment: 'staging',
};

function authenticatedPayload(context = initialContext) {
  return {
    authenticated: true,
    user: { id: 'elena', permissions: ['console:read'] },
    context_version: '2',
    context,
    authorized_contexts: [{
      org_id: 'northstar-health', tenant_id: 'northstar-health',
      workspace_id: 'utilization-management', environments: ['sandbox', 'staging'],
    }],
  };
}

test('a signed peer-React extension resolves a relative chunk and receives only Runtime context', async ({ page }) => {
  const chunk = "export const label = (context) => `${context.context.workspace_id}/${context.context.active_environment}`;";
  const entry = [
    "import { label } from './chunks/context-label.js';",
    'const React = globalThis.__AGENTV_EXTENSION_REACT__;',
    "export default function Extension({ context, switchContext, route }) { return route ? React.createElement('div', null, `Extension page: ${route.path} ${label(context)}`) : React.createElement('button', { onClick: () => switchContext('utilization-management', 'sandbox') }, `Extension context: ${label(context)}`); }",
  ].join('\n');
  const manifest = {
    extension_id: 'generic-context-header', display_name: 'Generic Context Header', version: '1.0.0',
    api_version: '1.0.0', compatibility_version: '1.0.0', compatible_runtime_versions: ['1.0.0'],
    capabilities: ['header', 'routes'], required_permissions: [], routes: [{ path: '/generic-page', label: 'Generic page' }], nav_group: 'System',
    remote_entry: '/extensions/generic/entry.js', sri_hash: sri(entry), publisher: 'test-publisher',
    signature: 'verified-by-runtime', lifecycle: {}, host_apis: [], slot: 'header', react_peer: true, tier: null,
    verified_chunks: { './chunks/context-label.js': sri(chunk) },
  };
  let current = initialContext;

  await page.route('**/api/status', route => route.fulfill({ json: { status: 'ok' } }));
  await page.route('**/api/nav', route => route.fulfill({ json: { nav: [{
    id: 'generic-context-header', name: 'Generic context header', path: '/', slot: 'header',
    remoteEntry: '/extensions/generic/entry.js', sriHash: sri(entry), required_permissions: [],
  }, {
    id: 'generic-page', name: 'Generic page', path: '/generic-page',
    remoteEntry: '/extensions/generic/entry.js', sriHash: sri(entry), required_permissions: [],
  }] } }));
  await page.route('**/api/v1/extensions/verify-publisher', route => route.fulfill({ json: { valid: true, tier: 'official' } }));
  await page.route('**/extensions/generic/entry.manifest.json', route => route.fulfill({ json: manifest }));
  await page.route('**/extensions/generic/chunks/context-label.js**', route => route.fulfill({ contentType: 'application/javascript', body: chunk }));
  await page.route('**/extensions/generic/entry.js**', route => route.fulfill({ contentType: 'application/javascript', body: entry }));
  await page.route('**/api/auth/context', async route => {
    const requested = route.request().postDataJSON();
    // The fixture mirrors Runtime's authority boundary: it accepts no org or
    // tenant input and resolves the tuple from its authenticated entitlement.
    expect(requested).toEqual({ workspace_id: 'utilization-management', active_environment: 'sandbox' });
    current = { ...initialContext, active_environment: 'sandbox' };
    await route.fulfill({ json: authenticatedPayload(current) });
  });
  await page.route('**/api/auth/me', route => route.fulfill({ json: authenticatedPayload(current) }));

  // Query inputs are deliberately hostile browser inputs; the rendered scope
  // remains the Runtime-provided entitlement context.
  await page.goto('/?tenant_id=attacker&workspace_id=attacker&active_environment=production');
  const selector = page.getByRole('button', { name: 'Extension context: utilization-management/staging' });
  await expect(selector).toBeVisible();
  await selector.click();
  await expect(page.getByRole('button', { name: 'Extension context: utilization-management/sandbox' })).toBeVisible();
  await page.goto('/generic-page');
  await expect(page.getByText('Extension page: /generic-page utilization-management/sandbox')).toBeVisible();
});

test('a tampered signed extension chunk never mounts', async ({ page }) => {
  const expectedChunk = "export const label = () => 'trusted';";
  const entry = [
    "import { label } from './chunks/context-label.js';",
    'const React = globalThis.__AGENTV_EXTENSION_REACT__;',
    "export default function Header({ context }) { return React.createElement('span', null, label(context)); }",
  ].join('\n');
  const manifest = {
    extension_id: 'tampered-header', display_name: 'Tampered Header', version: '1.0.0', api_version: '1.0.0',
    compatibility_version: '1.0.0', compatible_runtime_versions: ['1.0.0'], capabilities: ['header'],
    required_permissions: [], routes: [], nav_group: 'System', remote_entry: '/extensions/tampered/entry.js',
    sri_hash: sri(entry), publisher: 'test-publisher', signature: 'verified-by-runtime', lifecycle: {}, host_apis: [],
    slot: 'header', react_peer: true, verified_chunks: { './chunks/context-label.js': sri(expectedChunk) },
  };
  await page.route('**/api/status', route => route.fulfill({ json: { status: 'ok' } }));
  await page.route('**/api/nav', route => route.fulfill({ json: { nav: [{ id: 'tampered-header', name: 'Tampered', path: '/', slot: 'header', remoteEntry: '/extensions/tampered/entry.js', sriHash: sri(entry) }] } }));
  await page.route('**/api/v1/extensions/verify-publisher', route => route.fulfill({ json: { valid: true, tier: 'official' } }));
  await page.route('**/extensions/tampered/entry.manifest.json', route => route.fulfill({ json: manifest }));
  await page.route('**/extensions/tampered/chunks/context-label.js**', route => route.fulfill({ contentType: 'application/javascript', body: "export const label = () => 'TAMPERED';" }));
  await page.route('**/extensions/tampered/entry.js**', route => route.fulfill({ contentType: 'application/javascript', body: entry }));
  await page.route('**/api/auth/me', route => route.fulfill({ json: authenticatedPayload() }));

  await page.goto('/');
  await expect(page.getByText('TAMPERED')).toHaveCount(0);
  await expect(page.getByText('Extension context:')).toHaveCount(0);
});
