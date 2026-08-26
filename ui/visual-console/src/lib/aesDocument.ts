/**
 * Canonical AES document model for the Scenario Composer ([P0-3]/[P0-4]).
 *
 * Doctrine: the canonical AES JSON is the single source of truth. Canvas
 * projections are DERIVED VIEWS. Edits patch the canonical document — they
 * never reconstruct it from UI state.
 *
 * Guarantees provided by this module:
 *   - Unknown top-level, workflow-level, node-level and edge-level fields are
 *     preserved byte-for-byte (deep-copied) through a load → edit → save cycle
 *     in which the operator did not explicitly delete them.
 *   - Constructs the canvas cannot represent structurally (duplicate node
 *     ids, dangling edges, malformed collections) are REFUSED with explicit
 *     reasons instead of being silently degraded.
 */

export interface DocumentProjectionErrorReason {
  code:
    | 'NOT_AN_OBJECT'
    | 'WORKFLOW_NOT_OBJECT'
    | 'NODES_NOT_ARRAY'
    | 'EDGES_NOT_ARRAY'
    | 'NODE_ID_MISSING'
    | 'NODE_ID_DUPLICATE'
    | 'EDGE_DANGLING_ENDPOINT'
    | 'EDGE_TYPE_UNKNOWN'
    | 'EDGE_PRIORITY_INVALID';
  message: string;
}

export class DocumentProjectionError extends Error {
  reasons: DocumentProjectionErrorReason[];

  constructor(reasons: DocumentProjectionErrorReason[]) {
    super(
      `Cannot project document to canvas: ${reasons.map(r => r.message).join('; ')}`
    );
    this.name = 'DocumentProjectionError';
    this.reasons = reasons;
  }
}

/** Plain node/edge view consumed by the canvas (React Flow agnostic). */
export interface ProjectedNode {
  id: string;
  task_description: unknown;
  required_tools: unknown;
  expected_outcome: unknown;
}

export interface ProjectedEdge {
  id: string;
  source: string;
  target: string;
  condition: unknown;
  /** Canonical edge type (document key 'type'); undefined when absent. */
  edge_type: unknown;
  /** Routing priority (canonical default 100); undefined when absent. */
  priority: unknown;
}

export interface CanvasProjection {
  nodes: ProjectedNode[];
  edges: ProjectedEdge[];
}

export const isRecord = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === 'object' && !Array.isArray(v);

/**
 * Canonical edge types — mirrors eval_runner.execution_ir.EdgeType (the
 * executable keys of _EDGE_TYPE_ALIASES). The composer only ever emits these
 * literals; anything else is refused at patch time, never degraded.
 */
export const EDGE_TYPES = [
  'sequential',
  'condition',
  'default',
  'error',
  'timeout',
  'retry',
  'compensation',
  'parallel',
  'join',
] as const;

export type EdgeTypeLiteral = (typeof EDGE_TYPES)[number];

export const isValidEdgeType = (v: unknown): v is EdgeTypeLiteral =>
  typeof v === 'string' && (EDGE_TYPES as readonly string[]).includes(v);

const deepCopy = <T>(v: T): T => JSON.parse(JSON.stringify(v));

/**
 * FNV-1a 32-bit hash, hex-encoded. Deterministic across sessions; used to
 * key debugger layout caches by scenario content (not just run id).
 */
export function fnv1a(input: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return ('00000000' + hash.toString(16)).slice(-8) + ('00000000' + ((hash ^ 0xffffffff) >>> 0).toString(16)).slice(-8);
}

/** Stable JSON.stringify (sorted keys) for hashing arbitrary documents. */
export function stableStringify(value: unknown): string {
  if (Array.isArray(value)) {
    return '[' + value.map(v => stableStringify(v)).join(',') + ']';
  }
  if (isRecord(value)) {
    const keys = Object.keys(value).sort();
    return (
      '{' +
      keys.map(k => JSON.stringify(k) + ':' + stableStringify(value[k])).join(',') +
      '}'
    );
  }
  return JSON.stringify(value) ?? 'null';
}

/** Content hash of an AES document (stable across key order). */
export function computeScenarioHash(doc: unknown): string {
  return fnv1a(stableStringify(doc ?? null));
}

/**
 * Validates an AES document for canvas projection and returns the reduced
 * view. Throws DocumentProjectionError listing EVERY structural problem —
 * the caller must refuse the projection rather than degrade silently.
 */
export function projectToCanvas(doc: unknown): CanvasProjection {
  const reasons: DocumentProjectionErrorReason[] = [];

  if (!isRecord(doc)) {
    throw new DocumentProjectionError([
      { code: 'NOT_AN_OBJECT', message: 'document is not a JSON object' },
    ]);
  }

  const wf = doc.workflow;
  if (wf !== undefined && !isRecord(wf)) {
    reasons.push({
      code: 'WORKFLOW_NOT_OBJECT',
      message: "'workflow' is not an object",
    });
  }

  const rawNodes = isRecord(wf) ? wf.nodes : undefined;
  if (rawNodes !== undefined && !Array.isArray(rawNodes)) {
    reasons.push({ code: 'NODES_NOT_ARRAY', message: "'workflow.nodes' is not an array" });
  }
  const rawEdges = isRecord(wf) ? wf.edges : undefined;
  if (rawEdges !== undefined && !Array.isArray(rawEdges)) {
    reasons.push({ code: 'EDGES_NOT_ARRAY', message: "'workflow.edges' is not an array" });
  }

  if (reasons.length > 0) throw new DocumentProjectionError(reasons);

  const seenIds = new Set<string>();
  const nodeIds = new Set<string>();
  for (const n of (rawNodes as unknown[]) || []) {
    const nid = isRecord(n) ? n['id'] : undefined;
    if (typeof nid !== 'string' || nid === '') {
      reasons.push({
        code: 'NODE_ID_MISSING',
        message: `node without a non-empty string id: ${JSON.stringify(nid ?? null)}`,
      });
      continue;
    }
    if (seenIds.has(nid)) {
      reasons.push({
        code: 'NODE_ID_DUPLICATE',
        message: `duplicate node id '${nid}'`,
      });
    }
    seenIds.add(nid);
    nodeIds.add(nid);
  }

  for (const e of (rawEdges as unknown[]) || []) {
    if (!isRecord(e)) continue;
    const src = typeof e.from === 'string' ? e.from : e.source;
    const dst = typeof e.to === 'string' ? e.to : e.target;
    if (
      (typeof src !== 'string' || !nodeIds.has(src)) ||
      (typeof dst !== 'string' || !nodeIds.has(dst))
    ) {
      reasons.push({
        code: 'EDGE_DANGLING_ENDPOINT',
        message: `edge ${JSON.stringify(src)}→${JSON.stringify(dst)} references unknown node(s)`,
      });
    }
  }

  if (reasons.length > 0) throw new DocumentProjectionError(reasons);

  return {
    nodes: ((rawNodes as unknown[]) || []).map((n: any) => ({
      id: String(n.id),
      task_description: n.task_description,
      required_tools: n.required_tools,
      expected_outcome: n.expected_outcome,
    })),
    edges: ((rawEdges as unknown[]) || []).map((e: any, idx: number) => {
      const src = String(e.from ?? e.source);
      const dst = String(e.to ?? e.target);
      const edgeId =
        typeof e.id === 'string' && e.id
          ? e.id
          : typeof e.edge_id === 'string' && e.edge_id
            ? e.edge_id
            : `edge_${src}_${dst}_${idx}`;
      return {
        id: edgeId,
        source: src,
        target: dst,
        condition: e.condition,
        edge_type: e.type,
        priority: e.priority,
      };
    }),
  };
}

export interface MetadataPatch {
  id: string;
  name: string;
  version: string;
  status: string;
  compliance_level: string;
  description: string;
}

export interface UiEditPatch {
  metadata: Partial<MetadataPatch>;
  industry?: string;
  /** Nodes present on the canvas after operator edits. */
  nodes: Array<{ id: string; task_description?: unknown; required_tools?: unknown; expected_outcome?: unknown }>;
  /** Edges present on the canvas after operator edits. */
  edges: Array<{
    id?: string;
    source: string;
    target: string;
    condition?: unknown;
    /** Canonical EdgeType literal (validated against EDGE_TYPES). */
    edge_type?: string;
    /** Routing priority; canonical default 100. */
    priority?: number;
  }>;
}

/**
 * Patches the canonical document with canvas edits. Unknown fields at every
 * level survive: the base document is deep-copied and only the exact keys the
 * canvas models are overwritten. Deleted nodes/edges disappear because the
 * operator removed them on the canvas — an explicit edit, not corruption.
 */
export function patchCanonicalDocument(
  rawDoc: unknown | null,
  patch: UiEditPatch
): Record<string, unknown> {
  const base: Record<string, unknown> = rawDoc
    ? deepCopy(rawDoc as Record<string, unknown>)
    : {
        aes_version: 1.4,
        evaluation: {
          consensus: {
            strategy: 'Majority_Vote',
            min_judges: 1,
          },
        },
      };

  const existingWf = isRecord(base.workflow) ? base.workflow : {};
  const existingNodes = Array.isArray(existingWf.nodes) ? existingWf.nodes : [];
  const existingEdges = Array.isArray(existingWf.edges) ? existingWf.edges : [];

  const nodeById = new Map<string, any>();
  for (const n of existingNodes) {
    if (isRecord(n) && typeof n.id === 'string') nodeById.set(n.id, n);
  }

  const edgeById = new Map<string, any>();
  existingEdges.forEach((e: any, idx: number) => {
    if (isRecord(e)) {
      const eid = typeof e.id === 'string' && e.id ? e.id : (typeof e.edge_id === 'string' && e.edge_id ? e.edge_id : `edge_${String(e.from ?? e.source)}_${String(e.to ?? e.target)}_${idx}`);
      edgeById.set(eid, e);
    }
  });

  const workflowNodes = patch.nodes.map(n => {
    const existing = nodeById.get(n.id) || {};
    return {
      ...existing,
      id: n.id,
      ...(n.task_description !== undefined
        ? { task_description: n.task_description }
        : {}),
      ...(n.required_tools !== undefined ? { required_tools: n.required_tools } : {}),
      ...(n.expected_outcome !== undefined ? { expected_outcome: n.expected_outcome } : {}),
    };
  });

  const workflowEdges = patch.edges.map((e, idx) => {
    const fallbackId = `edge_${e.source}_${e.target}_${idx}`;
    const eid = e.id || fallbackId;
    const existing = edgeById.get(eid) || {};
    if (e.edge_type !== undefined && !isValidEdgeType(e.edge_type)) {
      throw new DocumentProjectionError([
        {
          code: 'EDGE_TYPE_UNKNOWN',
          message: `edge ${e.source}→${e.target} has unknown type '${String(e.edge_type)}' (valid: ${EDGE_TYPES.join(', ')})`,
        },
      ]);
    }
    let priority: number | undefined;
    if (e.priority !== undefined) {
      priority = Number(e.priority);
      if (!Number.isFinite(priority)) {
        throw new DocumentProjectionError([
          {
            code: 'EDGE_PRIORITY_INVALID',
            message: `edge ${e.source}→${e.target} has non-numeric priority '${String(e.priority)}'`,
          },
        ]);
      }
    }
    return {
      ...existing,
      ...(existing.id ? { id: existing.id } : (e.id && !e.id.startsWith('edge_') ? { id: e.id } : {})),
      from: e.source,
      to: e.target,
      ...(e.condition !== undefined ? { condition: e.condition } : {}),
      ...(e.edge_type !== undefined ? { type: e.edge_type } : {}),
      ...(priority !== undefined ? { priority } : {}),
    };
  });

  const meta = isRecord(base.metadata) ? base.metadata : {};
  base.metadata = {
    ...meta,
    ...(patch.metadata.id !== undefined ? { id: patch.metadata.id } : {}),
    ...(patch.metadata.name !== undefined ? { name: patch.metadata.name } : {}),
    ...(patch.metadata.version !== undefined ? { version: patch.metadata.version } : {}),
    ...(patch.metadata.status !== undefined ? { status: patch.metadata.status } : {}),
    ...(patch.metadata.compliance_level !== undefined
      ? { compliance_level: patch.metadata.compliance_level }
      : {}),
    ...(patch.metadata.description !== undefined
      ? { description: patch.metadata.description }
      : {}),
  };
  if (patch.industry !== undefined) base.industry = patch.industry;
  base.workflow = {
    ...existingWf,
    nodes: workflowNodes,
    edges: workflowEdges,
  };

  return base;
}
