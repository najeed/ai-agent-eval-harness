import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import test from 'node:test';

import { validateExtensionManifest } from '../../src/types/extension-contract.js';

test('core host has no enterprise import, registry, or enterprise API path', () => {
  const app = readFileSync(resolve('src/App.tsx'), 'utf8');
  assert.doesNotMatch(app, /pages\/enterprise|\/api\/enterprise/i);
  assert.doesNotMatch(app, /required_role|requiredRole/);
});

test('generic header extensions are contract-valid and permission-gated', () => {
  const violations = validateExtensionManifest({
    extension_id: 'generic-header', display_name: 'Generic Header', version: '1.0.0',
    api_version: '1.0.0', compatibility_version: '1.0.0', compatible_runtime_versions: ['1.0.0'],
    capabilities: ['header'], required_permissions: [], routes: [], nav_group: 'System',
    remote_entry: '/extension.js', sri_hash: 'sha256-test', publisher: 'test', signature: 'signature',
    lifecycle: {}, host_apis: [], slot: 'header',
  });
  assert.deepEqual(violations, []);
});
