import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import test from 'node:test';

test('Settings.tsx presents Signed remote extension and Server-registered component, never host', () => {
  const settingsSrc = readFileSync(resolve('src/pages/Settings.tsx'), 'utf8');

  // Must include the exact required labels
  assert.match(settingsSrc, /Signed remote extension/);
  assert.match(settingsSrc, /Server-registered component/);

  // Must have renamed Extension Host -> Extension Inventory
  assert.match(settingsSrc, /Extension Inventory/);
  assert.doesNotMatch(settingsSrc, /Extension Host/);

  // Must not label any item as "remote host" or "in-process host"
  assert.doesNotMatch(settingsSrc, /remote host/i);
  assert.doesNotMatch(settingsSrc, /in-process host/i);

  // Must not refer to extension registrations as hosts or execution workers
  assert.doesNotMatch(settingsSrc, /Registered extension hosts/i);
  assert.doesNotMatch(settingsSrc, /No extension hosts registered/i);
});

test('Settings.tsx consumes buildExtensionInventory for deduplication and relationship display', () => {
  const settingsSrc = readFileSync(resolve('src/pages/Settings.tsx'), 'utf8');

  // Uses buildExtensionInventory
  assert.match(settingsSrc, /buildExtensionInventory/);
  assert.match(settingsSrc, /ExtensionInventoryItem/);

  // Queries view=inventory from /api/nav
  assert.match(settingsSrc, /\/api\/nav\?view=inventory/);

  // Displays implementation details and declared relationships
  assert.match(settingsSrc, /relatedRegistrationIds/);
  assert.match(settingsSrc, /componentName/);
  assert.match(settingsSrc, /remoteEntry/);
});
