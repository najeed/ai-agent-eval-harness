/**
 * Round-trip losslessness tests for the canonical AES document model
 * ([P0-3]/[P0-4] exit criterion: loading and re-saving any supported AES
 * scenario produces no semantic loss).
 *
 * Run: npm run test:docmodel  (tsc → node --test, zero runtime deps)
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  DocumentProjectionError,
  computeScenarioHash,
  patchCanonicalDocument,
  projectToCanvas,
} from '../../src/lib/aesDocument.js';

const RICH_DOC = {
  aes_version: 1.4,
  id: 'rich-scenario',
  title: 'Rich Scenario',
  governance: { owner: 'platform-team', classification: 'INTERNAL' },
  evaluation: {
    consensus: { strategy: 'Majority_Vote', min_judges: 3, judge_panel: ['Luna-1'] },
    metrics: [{ metric: 'exact_match', threshold: 0.9 }],
  },
  industry: 'banking',
  workflow: {
    nodes: [
      {
        id: 'n1',
        task_description: 'verify identity',
        required_tools: ['id_checker'],
        expected_outcome: [{ target: 'message', expected: 'verified', mode: 'exact' }],
        retry_policy: { max_retries: 2, backoff: 'exponential' },
        human_in_loop: false,
      },
      {
        id: 'n2',
        task_description: 'disburse funds',
        required_tools: ['ledger'],
        expected_outcome: [],
        custom_metadata: { tier: 'gold' },
      },
    ],
    edges: [
      { from: 'n1', to: 'n2', condition: 'identity_verified == true', weight: 1.5 },
    ],
    subflows: [{ id: 'sf1', entry: 'n1' }],
    failure_policy: { on_error: 'compensate' },
  },
};

const unchangedUiPatchFrom = (doc: any) => ({
  metadata: {
    id: doc.metadata?.id ?? doc.id,
    name: doc.metadata?.name ?? doc.title,
    version: doc.metadata?.version ?? '1.0.0',
    status: doc.metadata?.status ?? 'Draft',
    compliance_level: doc.metadata?.compliance_level ?? 'Standard',
    description: doc.metadata?.description ?? '',
  },
  industry: doc.industry,
  nodes: projectToCanvas(doc).nodes,
  edges: projectToCanvas(doc).edges.map((e) => ({ source: e.source, target: e.target })),
});

test('round trip is lossless for unknown fields at every level', () => {
  const patched = patchCanonicalDocument(RICH_DOC, unchangedUiPatchFrom(RICH_DOC));

  // Unknown top-level fields preserved.
  assert.deepEqual(patched['governance'], RICH_DOC.governance);
  assert.equal(patched['id'], RICH_DOC.id);
  assert.equal(patched['title'], RICH_DOC.title);
  // Evaluation block untouched.
  assert.deepEqual(patched['evaluation'], RICH_DOC.evaluation);

  const wf: any = patched.workflow;
  // Unknown workflow-level keys preserved.
  assert.deepEqual(wf.subflows, RICH_DOC.workflow.subflows);
  assert.deepEqual(wf.failure_policy, RICH_DOC.workflow.failure_policy);

  // Unknown node-level fields preserved.
  assert.deepEqual(wf.nodes[0].retry_policy, RICH_DOC.workflow.nodes[0].retry_policy);
  assert.equal(wf.nodes[0].human_in_loop, false);
  assert.deepEqual(wf.nodes[1].custom_metadata, { tier: 'gold' });

  // Unknown edge-level fields preserved.
  assert.deepEqual(wf.edges[0], RICH_DOC.workflow.edges[0]);

  // Modeled fields survive with identical values.
  assert.equal(wf.nodes[0].task_description, 'verify identity');
  assert.deepEqual(wf.nodes[0].expected_outcome, RICH_DOC.workflow.nodes[0].expected_outcome);
});

test('round trip with no edits: zero mutation outside the additive metadata header', () => {
  const doc = JSON.parse(JSON.stringify(RICH_DOC));
  delete doc.metadata; // exercise the fallback identity path in the patch helper
  const patch = unchangedUiPatchFrom(doc);
  // Simulate a UI whose metadata state mirrors the unmodeled document fields.
  patch.metadata.description = '';
  const patched = patchCanonicalDocument(doc, patch);

  // Losslessness: every pre-existing field is preserved EXACTLY.
  const { metadata, ...rest } = patched;
  assert.deepEqual(rest, doc);

  // The only addition is the metadata header derived from UI state.
  assert.deepEqual(metadata, {
    id: doc.id,
    name: doc.title,
    version: '1.0.0',
    status: 'Draft',
    compliance_level: 'Standard',
    description: '',
  });
});

test('metadata edits change only modeled keys', () => {
  const doc = JSON.parse(JSON.stringify(RICH_DOC));
  doc.metadata = { id: 'm1', name: 'M', version: '2.0.0', status: 'Draft' };
  const before = JSON.parse(JSON.stringify(doc));

  const patched = patchCanonicalDocument(doc, {
    metadata: {
      id: 'm1',
      name: 'Renamed',
      version: '2.1.0',
      status: 'Validated',
      compliance_level: 'High',
      description: 'd',
    },
    nodes: [],
    edges: [],
  });

  assert.equal((patched.metadata as any).name, 'Renamed');
  assert.equal((patched.metadata as any).version, '2.1.0');
  assert.equal((patched.metadata as any).compliance_level, 'High');
  // Untouched top-level/workflow content identical to original.
  assert.deepEqual(patched['governance'], before['governance']);
  assert.deepEqual((patched.workflow as any).nodes, []);
});

test('duplicate node ids are refused, not degraded', () => {
  const bad = {
    workflow: {
      nodes: [
        { id: 'a' },
        { id: 'a' },
      ],
      edges: [],
    },
  };
  assert.throws(
    () => projectToCanvas(bad),
    (err: unknown) =>
      err instanceof DocumentProjectionError &&
      err.reasons.some(r => r.code === 'NODE_ID_DUPLICATE')
  );
});

test('dangling edge endpoints are refused', () => {
  const bad = {
    workflow: {
      nodes: [{ id: 'a' }],
      edges: [{ from: 'a', to: 'ghost' }],
    },
  };
  try {
    projectToCanvas(bad);
    assert.fail('expected DocumentProjectionError');
  } catch (e) {
    assert.ok(e instanceof DocumentProjectionError);
    assert.ok(e.reasons.some(r => r.code === 'EDGE_DANGLING_ENDPOINT'));
    assert.match(e.message, /ghost/);
  }
});

test('malformed collections and non-object documents are refused', () => {
  assert.throws(() => projectToCanvas(null), DocumentProjectionError);
  assert.throws(
    () => projectToCanvas({ workflow: { nodes: 'nope' } }),
    (err: unknown) =>
      err instanceof DocumentProjectionError &&
      err.reasons.some(r => r.code === 'NODES_NOT_ARRAY')
  );
  assert.throws(
    () => projectToCanvas({ workflow: 42 }),
    (err: unknown) =>
      err instanceof DocumentProjectionError &&
      err.reasons.some(r => r.code === 'WORKFLOW_NOT_OBJECT')
  );
});

test('deleting a canvas node removes exactly that node', () => {
  const patch = unchangedUiPatchFrom(RICH_DOC);
  const deletedPatch = {
    ...patch,
    nodes: patch.nodes.filter(n => n.id !== 'n1'),
    edges: [],
  };
  const patched = patchCanonicalDocument(RICH_DOC, deletedPatch);
  const wf: any = patched.workflow;
  assert.equal(wf.nodes.length, 1);
  assert.equal(wf.nodes[0].id, 'n2');
  assert.deepEqual(wf.nodes[0].custom_metadata, { tier: 'gold' });
  // Unknown workflow keys still intact after deletion edit.
  assert.deepEqual(wf.subflows, RICH_DOC.workflow.subflows);
});

test('scenario hash is order-insensitive but content-sensitive', () => {
  const a = computeScenarioHash({ x: 1, y: [2, 3] });
  const b = computeScenarioHash({ y: [2, 3], x: 1 });
  const c = computeScenarioHash({ x: 1, y: [2, 4] });
  assert.equal(a, b);
  assert.notEqual(a, c);
});
