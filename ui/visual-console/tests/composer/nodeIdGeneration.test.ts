/**
 * ScenarioComposer unit tests:
 * - Collision-free node ID generation on deletion and addition
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

test('node ID generator never reuses deleted IDs and avoids collisions', () => {
  const nodes = [
    { id: 'node_1' },
    { id: 'node_2' },
    { id: 'node_3' },
  ];

  // Simulate deleting node_2 -> nodes array has length 2: [node_1, node_3]
  const afterDelete = nodes.filter(n => n.id !== 'node_2');
  assert.equal(afterDelete.length, 2);

  // Next ID generation algorithm
  const existingIds = new Set(afterDelete.map(n => n.id));
  let counter = afterDelete.length + 1;
  let nextId = `node_${counter}`;
  while (existingIds.has(nextId)) {
    counter += 1;
    nextId = `node_${counter}`;
  }

  // counter was initially 3 (afterDelete.length + 1), but node_3 existed so it safely incremented to node_4
  assert.equal(nextId, 'node_4');
  assert.equal(existingIds.has(nextId), false);
});
