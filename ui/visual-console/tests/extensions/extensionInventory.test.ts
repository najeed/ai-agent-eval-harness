import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildExtensionInventory,
  type ExtensionInventoryItem,
} from '../../src/types/extension-contract.js';

test('remote-only extension registration normalizes to signed remote extension', () => {
  const rawNav = [
    {
      id: 'ext-remote-1',
      name: 'Remote Analytics',
      path: '/analytics',
      remoteEntry: '/extensions/analytics/entry.js',
      sriHash: 'sha3-256-abcdef123456',
      extensionId: 'com.enterprise.analytics',
      capabilityId: 'analytics',
      publisher: 'Enterprise Corp',
      version: '1.2.0',
      trustTier: 'official',
    },
  ];

  const inventory = buildExtensionInventory(rawNav);
  assert.equal(inventory.length, 1);
  const item = inventory[0];
  assert.equal(item.capabilityId, 'analytics');
  assert.equal(item.extensionId, 'com.enterprise.analytics');
  assert.equal(item.registrationKind, 'remote_extension');
  assert.equal(item.remoteEntry, '/extensions/analytics/entry.js');
  assert.equal(item.sriHash, 'sha3-256-abcdef123456');
  assert.equal(item.componentName, undefined);
  assert.equal(item.publisher, 'Enterprise Corp');
  assert.equal(item.version, '1.2.0');
  assert.equal(item.trustTier, 'official');
  assert.deepEqual(item.relatedRegistrationIds, ['ext-remote-1']);
});

test('component-only registration normalizes to server-registered component', () => {
  const rawNav = [
    {
      id: 'server-comp-1',
      title: 'Health Diagnostics',
      path: '/health-ui',
      type: 'component',
      componentName: 'HealthConsoleView',
      capabilityId: 'system_health',
      extensionId: 'org.platform.health',
      publisher: 'Platform Core',
      version: '2.0.1',
      tier: 'official',
    },
  ];

  const inventory = buildExtensionInventory(rawNav);
  assert.equal(inventory.length, 1);
  const item = inventory[0];
  assert.equal(item.capabilityId, 'system_health');
  assert.equal(item.extensionId, 'org.platform.health');
  assert.equal(item.registrationKind, 'server_component');
  assert.equal(item.componentName, 'HealthConsoleView');
  assert.equal(item.remoteEntry, undefined);
  assert.equal(item.publisher, 'Platform Core');
  assert.equal(item.version, '2.0.1');
  assert.equal(item.trustTier, 'official');
  assert.deepEqual(item.relatedRegistrationIds, ['server-comp-1']);
});

test('paired registration merges into single canonical item declaring superseding relationship', () => {
  // A single capability represented by both remoteEntry and componentName
  const rawNav = [
    {
      id: 'audit-server-comp',
      name: 'Server Audit Component',
      path: '/audit',
      type: 'component',
      componentName: 'AuditTablePlugin',
      capabilityId: 'compliance_audit',
      extensionId: 'com.enterprise.audit',
    },
    {
      id: 'audit-signed-remote',
      name: 'Signed Remote Audit Bundle',
      path: '/audit',
      remoteEntry: '/extensions/audit/entry.mjs',
      sriHash: 'sha3-256-audit987',
      capabilityId: 'compliance_audit',
      extensionId: 'com.enterprise.audit',
      publisher: 'Enterprise Security',
      version: '3.4.0',
      trustTier: 'official',
    },
  ];

  const inventory = buildExtensionInventory(rawNav);
  // Must appear exactly once in inventory
  assert.equal(inventory.length, 1);
  const canonical = inventory[0];
  assert.equal(canonical.capabilityId, 'compliance_audit');
  assert.equal(canonical.extensionId, 'com.enterprise.audit');
  // Remote extension supersedes or wraps the server component
  assert.equal(canonical.registrationKind, 'remote_extension');
  assert.equal(canonical.remoteEntry, '/extensions/audit/entry.mjs');
  assert.equal(canonical.componentName, 'AuditTablePlugin');
  assert.equal(canonical.sriHash, 'sha3-256-audit987');
  assert.equal(canonical.publisher, 'Enterprise Security');
  assert.equal(canonical.version, '3.4.0');
  // Declared relationship preserves both registration IDs
  assert.ok(canonical.relatedRegistrationIds?.includes('audit-server-comp'));
  assert.ok(canonical.relatedRegistrationIds?.includes('audit-signed-remote'));
});

test('duplicate navigation registration details collapse into one canonical inventory item', () => {
  // Same capability registered across multiple routes/nav details
  const rawNav = [
    {
      id: 'ops-dashboard-nav',
      name: 'Ops Dashboard',
      path: '/ops/v2',
      remoteEntry: '/extensions/ops/entry.js',
      sriHash: 'sha3-256-ops111',
      capabilityId: 'ops_suite',
      extensionId: 'com.enterprise.ops',
      version: '1.0.17',
    },
    {
      id: 'ops-metrics-nav',
      name: 'Ops Metrics',
      path: '/ops/v2/metrics',
      remoteEntry: '/extensions/ops/entry.js',
      sriHash: 'sha3-256-ops111',
      capabilityId: 'ops_suite',
      extensionId: 'com.enterprise.ops',
      version: '1.0.17',
    },
    {
      id: 'ops-settings-nav',
      name: 'Ops Settings',
      path: '/ops/v2/settings',
      remoteEntry: '/extensions/ops/entry.js',
      sriHash: 'sha3-256-ops111',
      capabilityId: 'ops_suite',
      extensionId: 'com.enterprise.ops',
      version: '1.0.17',
    },
  ];

  const inventory = buildExtensionInventory(rawNav);
  assert.equal(inventory.length, 1);
  const item = inventory[0];
  assert.equal(item.capabilityId, 'ops_suite');
  assert.equal(item.extensionId, 'com.enterprise.ops');
  assert.equal(item.version, '1.0.17');
  assert.equal(item.registrationKind, 'remote_extension');
  assert.equal(item.relatedRegistrationIds?.length, 3);
  assert.ok(item.relatedRegistrationIds?.includes('ops-dashboard-nav'));
  assert.ok(item.relatedRegistrationIds?.includes('ops-metrics-nav'));
  assert.ok(item.relatedRegistrationIds?.includes('ops-settings-nav'));
});

test('distinct capabilities remain separately visible', () => {
  const rawNav = [
    {
      id: 'cap-a-nav',
      componentName: 'ComponentA',
      capabilityId: 'cap_alpha',
    },
    {
      id: 'cap-b-nav',
      remoteEntry: '/extensions/b.js',
      capabilityId: 'cap_beta',
    },
    {
      id: 'cap-c-nav',
      remoteEntry: '/extensions/c.js',
      capabilityId: 'cap_gamma',
    },
  ];

  const inventory = buildExtensionInventory(rawNav);
  assert.equal(inventory.length, 3);
  const capIds = inventory.map(i => i.capabilityId);
  assert.deepEqual(capIds.sort(), ['cap_alpha', 'cap_beta', 'cap_gamma']);
});

test('core navigation items are excluded from extension inventory', () => {
  const rawNav = [
    { id: 'dashboard', title: 'Dashboard', path: '/', type: 'internal' },
    { id: 'scenarios', title: 'Scenarios', path: '/scenarios', type: 'internal' },
    { id: 'reports', title: 'Reports & Traces', path: '/reports', type: 'internal' },
    { id: 'community', title: 'Community', path: 'https://github.com', type: 'external' },
    {
      id: 'real-ext',
      remoteEntry: '/ext.js',
      capabilityId: 'real_ext',
    },
  ];

  const inventory = buildExtensionInventory(rawNav);
  assert.equal(inventory.length, 1);
  assert.equal(inventory[0].capabilityId, 'real_ext');
});

test('presentation kind never implies execution worker, host, or instance', () => {
  const rawNav = [
    { id: 'remote-1', remoteEntry: '/ext.js', capabilityId: 'cap1' },
    { id: 'comp-1', componentName: 'Comp1', capabilityId: 'cap2' },
  ];

  const inventory = buildExtensionInventory(rawNav);
  for (const item of inventory) {
    // Only 'remote_extension' or 'server_component' are permitted
    assert.ok(
      item.registrationKind === 'remote_extension' || item.registrationKind === 'server_component'
    );
    // Neither 'host' nor 'worker' nor 'instance' may be used as registrationKind
    assert.doesNotMatch(item.registrationKind, /host|worker|instance/i);
  }
});
