import assert from 'node:assert/strict';
import test from 'node:test';

import { Box, CircleHelp, ClipboardCheck, GitBranch } from 'lucide-react';

import {
  normalizeNavigationIconName,
  resolveNavigationIcon,
  SUPPORTED_NAVIGATION_ICON_NAMES,
} from '../../src/utils/navigationIcons.js';

test('normalizes signed Lucide navigation icon names consistently', () => {
  assert.equal(normalizeNavigationIconName('clipboardCheck'), 'clipboard-check');
  assert.equal(normalizeNavigationIconName('git_branch'), 'git-branch');
  assert.equal(normalizeNavigationIconName('File Check'), 'file-check');
});

test('resolves every supported navigation icon to its declared Lucide component', () => {
  for (const name of SUPPORTED_NAVIGATION_ICON_NAMES) {
    assert.notEqual((resolveNavigationIcon(name) as any).type, CircleHelp, name);
  }
  for (const required of ['box', 'clipboard-check', 'file-check', 'lock', 'users', 'trending-up', 'git-branch', 'database']) {
    assert.ok(SUPPORTED_NAVIGATION_ICON_NAMES.includes(required));
  }
  assert.equal((resolveNavigationIcon('box') as any).type, Box);
  assert.equal((resolveNavigationIcon('clipboard-check') as any).type, ClipboardCheck);
  assert.equal((resolveNavigationIcon('gitBranch') as any).type, GitBranch);
});

test('uses a neutral fallback for an unknown signed navigation icon', () => {
  assert.equal((resolveNavigationIcon('not-a-lucide-icon') as any).type, CircleHelp);
});
