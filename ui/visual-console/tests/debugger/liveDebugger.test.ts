/**
 * LiveDebugger unit tests:
 * - Deterministic waterfall correlation by execution_instance_id
 * - O(N) single-pass telemetry diagnostics computation
 * - Sequential gap bookkeeping
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  buildWaterfall,
  computeTelemetryDiagnostics,
  mergeSeqGap,
  type LogEvent,
} from '../../src/lib/debuggerLogic.js';


test('buildWaterfall correlates markers by execution_instance_id', () => {
  const events: LogEvent[] = [
    {
      _seq: 1,
      timestamp: '2026-08-27T08:00:00.000Z',
      event: 'execution_graph_node',
      scenario_node_id: 'node_1',
      execution_instance_id: 'node_1#1',
      status: 'running',
    },
    {
      _seq: 2,
      timestamp: '2026-08-27T08:00:01.000Z',
      event: 'tool_call',
      execution_instance_id: 'node_1#1',
      tool_name: 'alpha_tool',
    },
    {
      _seq: 3,
      timestamp: '2026-08-27T08:00:02.000Z',
      event: 'execution_graph_node',
      scenario_node_id: 'node_1',
      execution_instance_id: 'node_1#1',
      status: 'completed',
      duration_ms: 2000,
    },
  ];

  const waterfall = buildWaterfall(events);
  assert.equal(waterfall.rows.length, 1);
  assert.equal(waterfall.rows[0].execId, 'node_1#1');
  assert.equal(waterfall.rows[0].status, 'completed');
  assert.equal(waterfall.rows[0].markers.length, 1);
  assert.equal(waterfall.rows[0].markers[0].kind, 'tool_call');
});

test('computeTelemetryDiagnostics executes in O(N) and detects structured error signals', () => {
  const events: LogEvent[] = [
    {
      _seq: 1,
      timestamp: '2026-08-27T08:00:00.000Z',
      event: 'agent_request',
      node_id: 'node_alpha',
    },
    {
      _seq: 2,
      timestamp: '2026-08-27T08:00:01.000Z',
      event: 'error',
      node_id: 'node_alpha',
      error: 'Simulated failure',
    },
    {
      _seq: 3,
      timestamp: '2026-08-27T08:00:02.000Z',
      event: 'node_start',
      node_id: 'node_beta',
    },
  ];

  const diagnostics = computeTelemetryDiagnostics(events);
  assert.equal(diagnostics.length, 2);

  const alpha = diagnostics.find(d => d.nodeId === 'node_alpha');
  assert.ok(alpha);
  assert.equal(alpha.suspectedStatus, 'failed');

  const beta = diagnostics.find(d => d.nodeId === 'node_beta');
  assert.ok(beta);
  assert.equal(beta.suspectedStatus, 'running');
});

test('mergeSeqGap merges contiguous sequence intervals', () => {
  const initial = [{ from: 1, to: 5 }, { from: 10, to: 15 }];
  const next = { from: 6, to: 9 };
  const merged = mergeSeqGap(initial, next);

  assert.equal(merged.length, 1);
  assert.equal(merged[0].from, 1);
  assert.equal(merged[0].to, 15);
});
