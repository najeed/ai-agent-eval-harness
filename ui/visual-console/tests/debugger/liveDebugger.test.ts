/**
 * LiveDebugger unit tests:
 * - Deterministic waterfall correlation by execution_instance_id
 * - O(N) single-pass telemetry diagnostics computation
 * - Sequential gap bookkeeping
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  buildTraceGraph,
  buildWaterfall,
  computeTelemetryDiagnostics,
  computeTraceIntegrity,
  mergeSeqGap,
  projectTraceGraphTopology,
  subtractSeqFromGaps,
  type LogEvent,
} from '../../src/lib/debuggerLogic.js';

test('buildTraceGraph projects retries, divergence, edges, positions, and late hydration', () => {
  const events: LogEvent[] = [
    { _seq: 1, event: 'execution_graph_node', scenario_node_id: 'intake', status: 'failed', attempt: 1 },
    { _seq: 2, event: 'execution_graph_node', scenario_node_id: 'intake', status: 'completed', attempt: 2, duration_ms: 25 },
    { _seq: 3, event: 'execution_graph_node', scenario_node_id: 'runtime_review', status: 'completed' },
    { _seq: 4, event: 'execution_graph_edge', from_scenario_node_id: 'intake', to_scenario_node_id: 'review' },
    { _seq: 5, event: 'execution_graph_edge', from_scenario_node_id: 'intake', to_scenario_node_id: 'review', edge_type: 'retry' },
    { _seq: 6, event: 'execution_graph_edge', from_scenario_node_id: 'missing', to_scenario_node_id: 'review' },
  ];
  const scenario = {
    workflow: {
      nodes: [{ id: 'intake' }, { id: 'review' }, { id: 'notify' }],
      edges: [{ from: 'intake', to: 'review' }],
    },
  };
  const positions = new Map([['intake', { x: 7, y: 9 }]]);
  const key = (id: string) => id;

  assert.equal(buildTraceGraph(events, null, null, 'executed', false, new Map(), key).provenance, 'TOPOLOGY_UNAVAILABLE');
  const graph = buildTraceGraph(events, scenario, null, 'divergence', true, positions, key);
  assert.equal(graph.provenance, 'CANONICAL');
  assert.deepEqual(graph.flowNodes.map(node => node.id), ['intake', 'review', 'notify', 'runtime_review']);
  const intake = graph.flowNodes.find(node => node.id === 'intake')!;
  assert.equal(intake.data.maxAttempt, 2);
  assert.equal(intake.data.passCount, 1);
  assert.equal(intake.data.failCount, 1);
  assert.deepEqual(intake.position, { x: 7, y: 9 });
  assert.equal(graph.flowNodes.find(node => node.id === 'notify')!.data.isSkipped, true);
  assert.equal(graph.flowNodes.find(node => node.id === 'runtime_review')!.data.isUnplanned, true);
  assert.equal(graph.droppedEdgeCount, 1);
  assert.equal(graph.flowEdges.length, 3);
  assert.deepEqual(graph.flowEdges.map(edge => edge.data.pathOffset).filter(Boolean), [20, 36, 52]);
});

test('graph topology keeps planned, executed, and divergence nodes distinct', () => {
  const scenario = {
    workflow: {
      nodes: [{ id: 'intake' }, { id: 'eligibility' }, { id: 'notify' }],
    },
  };
  const events: LogEvent[] = [
    { _seq: 3, event: 'execution_graph_node', scenario_node_id: 'eligibility' },
    { _seq: 1, event: 'execution_graph_node', scenario_node_id: 'intake' },
    { _seq: 4, event: 'execution_graph_node', scenario_node_id: 'unplanned_review' },
  ];
  const ids = (mode: 'planned' | 'executed' | 'divergence') =>
    projectTraceGraphTopology(events, scenario, mode).visibleNodes.map(node => node.id);

  assert.deepEqual(ids('planned'), ['intake', 'eligibility', 'notify']);
  assert.deepEqual(ids('executed'), ['intake', 'eligibility', 'unplanned_review']);
  assert.deepEqual(ids('divergence'), ['intake', 'eligibility', 'notify', 'unplanned_review']);
});


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

test('gap recovery subtracts a middle sequence into two exact intervals', () => {
  assert.deepEqual(subtractSeqFromGaps([{ from: 2, to: 4 }], 3), [
    { from: 2, to: 2 }, { from: 4, to: 4 },
  ]);
});

test('gap subtraction is order-independent for arbitrary recovered members', () => {
  const recover = (order: number[]) => order.reduce(
    (gaps, seq) => subtractSeqFromGaps(gaps, seq), [{ from: 2, to: 9 }]
  );
  assert.deepEqual(recover([3, 6, 8]), recover([8, 3, 6]));
  assert.deepEqual(recover([3, 6, 8]), [
    { from: 2, to: 2 }, { from: 4, to: 5 }, { from: 7, to: 7 }, { from: 9, to: 9 },
  ]);
});

test('buildWaterfall handles zero-duration and single-event traces deterministically', () => {
  const events: LogEvent[] = [
    {
      _seq: 1,
      timestamp: '2026-08-27T08:00:00.000Z',
      event: 'execution_graph_node',
      scenario_node_id: 'instant_node',
      execution_instance_id: 'instant_node#1',
      status: 'completed',
      duration_ms: 0,
    },
  ];

  const waterfall = buildWaterfall(events);
  assert.equal(waterfall.rows.length, 1);
  assert.equal(waterfall.rows[0].execId, 'instant_node#1');
  assert.equal(waterfall.tMin, waterfall.tMax);
});

test('computeTraceIntegrity identifies absent sequence IDs and marks gaps & missingSequences', () => {
  const eventsWithoutSeq: LogEvent[] = [
    { event: 'run_start', timestamp: '2026-08-27T08:00:00.000Z' },
    { event: 'tool_call', timestamp: '2026-08-27T08:00:01.000Z' },
    { event: 'run_end', timestamp: '2026-08-27T08:00:02.000Z' },
  ];
  const res = computeTraceIntegrity(eventsWithoutSeq, false);
  assert.equal(res.hasEvents, true);
  assert.equal(res.missingSequences, true);
  assert.equal(res.hasValidSequences, false);
  assert.equal(res.gaps, true);
  assert.ok(res.issues.some(i => i.includes('lack server-assigned _seq identifiers')));
});

test('computeTraceIntegrity identifies partially missing sequence IDs', () => {
  const eventsPartialSeq: LogEvent[] = [
    { _seq: 1, event: 'run_start', timestamp: '2026-08-27T08:00:00.000Z' },
    { event: 'tool_call', timestamp: '2026-08-27T08:00:01.000Z' },
    { _seq: 2, event: 'run_end', timestamp: '2026-08-27T08:00:02.000Z' },
  ];
  const res = computeTraceIntegrity(eventsPartialSeq, false);
  assert.equal(res.missingSequences, true);
  assert.equal(res.hasValidSequences, false);
  assert.equal(res.gaps, true);
  assert.ok(res.issues.some(i => i.includes('1 event(s) lack server-assigned _seq identifiers')));
});

test('computeTraceIntegrity identifies duplicate sequence IDs', () => {
  const eventsWithDuplicates: LogEvent[] = [
    { _seq: 1, event: 'run_start', timestamp: '2026-08-27T08:00:00.000Z' },
    { _seq: 2, event: 'tool_call', timestamp: '2026-08-27T08:00:01.000Z' },
    { _seq: 2, event: 'tool_result', timestamp: '2026-08-27T08:00:02.000Z' },
    { _seq: 3, event: 'run_end', timestamp: '2026-08-27T08:00:03.000Z' },
  ];
  const res = computeTraceIntegrity(eventsWithDuplicates, false);
  assert.equal(res.gaps, true);
  assert.equal(res.hasValidSequences, false);
  assert.ok(res.issues.some(i => i.includes('1 duplicate frame(s)')));
});

test('computeTraceIntegrity identifies reordered sequence IDs', () => {
  const eventsReordered: LogEvent[] = [
    { _seq: 1, event: 'run_start', timestamp: '2026-08-27T08:00:00.000Z' },
    { _seq: 3, event: 'tool_call', timestamp: '2026-08-27T08:00:01.000Z' },
    { _seq: 2, event: 'tool_result', timestamp: '2026-08-27T08:00:02.000Z' },
    { _seq: 4, event: 'run_end', timestamp: '2026-08-27T08:00:03.000Z' },
  ];
  const res = computeTraceIntegrity(eventsReordered, false);
  assert.equal(res.reordered, true);
  assert.equal(res.hasValidSequences, false);
  assert.ok(res.issues.some(i => i.includes('out of monotonic _seq order')));
});

test('computeTraceIntegrity identifies gapped sequence intervals', () => {
  const eventsGapped: LogEvent[] = [
    { _seq: 1, event: 'run_start', timestamp: '2026-08-27T08:00:00.000Z' },
    { _seq: 2, event: 'tool_call', timestamp: '2026-08-27T08:00:01.000Z' },
    { _seq: 5, event: 'run_end', timestamp: '2026-08-27T08:00:03.000Z' },
  ];
  const res = computeTraceIntegrity(eventsGapped, false);
  assert.equal(res.gaps, true);
  assert.equal(res.hasValidSequences, false);
  assert.ok(res.issues.some(i => i.includes('missing _seq 3, 4')));
});

test('computeTraceIntegrity marks contiguous valid sequences as clean and valid', () => {
  const eventsValid: LogEvent[] = [
    { _seq: 1, event: 'run_start', timestamp: '2026-08-27T08:00:00.000Z' },
    { _seq: 2, event: 'tool_call', timestamp: '2026-08-27T08:00:01.000Z' },
    { _seq: 3, event: 'tool_result', timestamp: '2026-08-27T08:00:02.000Z' },
    { _seq: 4, event: 'run_end', timestamp: '2026-08-27T08:00:03.000Z' },
  ];
  const res = computeTraceIntegrity(eventsValid, false);
  assert.equal(res.gaps, false);
  assert.equal(res.reordered, false);
  assert.equal(res.missingSequences, false);
  assert.equal(res.hasValidSequences, true);
  assert.equal(res.missingStart, false);
  assert.equal(res.missingEnd, false);
  assert.equal(res.issues.length, 0);
});
