import React, { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  ReactFlow, Controls, Background, useNodesState, useEdgesState, addEdge
} from '@xyflow/react';
import type { Connection } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  Save, Trash2, Plus, Upload, AlertTriangle
} from 'lucide-react';
import { Editor } from '@monaco-editor/react';
import { useRBAC } from '../context/RBACContext';
import {
  DocumentProjectionError,
  EDGE_TYPES,
  patchCanonicalDocument,
  projectToCanvas,
  type CanvasProjection,
} from '../lib/aesDocument';

interface AssertionItem {
  target: string;
  property?: string;
  expected: string;
  mode: 'exact' | 'regex' | 'numerical_tolerance';
}

// Client mirror of the server-authoritative lifecycle state machine
// (eval_runner.console.routes.scenarios.LEGAL_TRANSITIONS). Used ONLY to
// enable/disable controls with explanatory reasons — the server transition
// API remains the sole authority and re-validates every request.
const LEGAL_TRANSITIONS: Record<string, string[]> = {
  Draft: ['Validated', 'Deprecated'],
  Validated: ['Ready', 'Draft', 'Deprecated'],
  Ready: ['Deprecated'],
  Deprecated: [],
  Published: ['Deprecated'],
};

export const ScenarioComposer: React.FC = () => {
  const [searchParams] = useSearchParams();
  const scenarioIdParam = searchParams.get('scenario_id');
  const { canEditScenario } = useRBAC();

  // Authoritative full canonical AES document
  const [rawDoc, setRawDoc] = useState<any>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Core metadata
  const [scenarioId, setScenarioId] = useState('untitled-draft');
  const [title, setTitle] = useState('Untitled Draft');
  const [version, setVersion] = useState('1.0.0');
  const [lifecycleStatus, setLifecycleStatus] = useState<
    'Draft' | 'Validated' | 'Ready' | 'Deprecated' | 'Published'
  >('Draft');
  const [industry, setIndustry] = useState('generic');
  const [complianceLevel, setComplianceLevel] = useState('Standard');
  const [description, setDescription] = useState('Custom evaluation scenario.');

  // React Flow State
  const [nodes, setNodes, onNodesChange] = useNodesState<any>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<any>([]);

  // Selection & Form editing
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [nodeDesc, setNodeDesc] = useState('');
  const [nodeTools, setNodeTools] = useState('');
  const [assertions, setAssertions] = useState<AssertionItem[]>([]);

  // Edge Inspector selection (edge edits apply directly to the edges state's
  // data.* so getAESJson picks them up — the canonical doc is never rebuilt
  // from a separate edge form buffer).
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);

  // JSON/YAML Toggle
  const [viewMode, setViewMode] = useState<'canvas' | 'json'>('canvas');
  const [rawJson, setRawJson] = useState('');
  // P0-1: synchronous JSON syntax error state. When set, Save/Run are blocked.
  const [jsonParseError, setJsonParseError] = useState<string | null>(null);

  // Spec import modal
  const [showImportModal, setShowImportModal] = useState(false);
  const [importText, setImportText] = useState('');

  // [P0-review] Import results are STAGED, never committed implicitly: the
  // parsed document waits here until the operator explicitly reviews and
  // applies it on the canvas.
  const [pendingImport, setPendingImport] = useState<{
    doc: any;
    preview: { nodes: number; edges: number };
    ambiguities: string[];
  } | null>(null);

  const [message, setMessage] = useState('');
  const [saving, setSaving] = useState(false);
  const [transitioning, setTransitioning] = useState(false);

  // [C3b] True once the scenario exists in the catalog (loaded by id, or
  // saved at least once). Lifecycle transitions require a server-side
  // document; unsaved drafts cannot transition.
  const isPersistedScenario = !!rawDoc && (!!scenarioIdParam || !!rawDoc.metadata?.content_hash);

  // [P0-3] Generate AES JSON by PATCHING the canonical document — never
  // reconstructing from canvas state. Unknown fields at every level survive.
  const getAESJson = () =>
    patchCanonicalDocument(rawDoc, {
      metadata: {
        id: scenarioId,
        name: title,
        version: version,
        status: lifecycleStatus,
        compliance_level: complianceLevel,
        description,
      },
      industry,
      nodes: nodes.map((n: any) => ({
        id: n.id,
        task_description: n.data.task_description,
        required_tools: n.data.required_tools,
        expected_outcome: n.data.expected_outcome,
      })),
      edges: edges.map((e: any) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        condition: e.data?.condition,
        edge_type: e.data?.edge_type,
        priority: e.data?.priority,
      })),
    });


  const syncJsonToCanvas = (jsonStr: string) => {
    // P0-1/P0-4: parse failures AND structurally unrepresentable documents
    // (duplicate ids, dangling edges, malformed collections) both REFUSE the
    // projection with explicit reasons — no silent degradation.
    const parsed = JSON.parse(jsonStr);
    const projection = projectToCanvas(parsed);
    setRawDoc(parsed);
    if (parsed.metadata?.id) setScenarioId(parsed.metadata.id);
    if (parsed.metadata?.name) setTitle(parsed.metadata.name);
    if (parsed.metadata?.version) setVersion(parsed.metadata.version);
    if (parsed.metadata?.status) setLifecycleStatus(parsed.metadata.status as any);
    if (parsed.industry) setIndustry(parsed.industry);
    if (parsed.metadata?.compliance_level) setComplianceLevel(parsed.metadata.compliance_level);
    if (parsed.metadata?.description) setDescription(parsed.metadata.description);

    const flowNodes = projection.nodes.map((n, idx) => ({
      id: n.id,
      type: 'default',
      position: { x: 150 + idx * 220, y: 150 },
      data: {
        label: n.id,
        task_description: n.task_description,
        required_tools: n.required_tools || [],
        expected_outcome: n.expected_outcome || []
      },
      style: {
        background: '#0f172a',
        color: '#fff',
        border: '1px solid #334155',
        borderRadius: '8px',
        fontSize: '11px',
        width: 160
      }
    }));
    setNodes(flowNodes);

    const flowEdges = projection.edges.map((e, idx) => ({
      id: e.id || `edge-${idx}`,
      source: e.source,
      target: e.target,
      data: { condition: e.condition, edge_type: e.edge_type, priority: e.priority }
    }));
    setEdges(flowEdges);
    return parsed;
  };

  const handleToggleMode = (mode: 'canvas' | 'json') => {
    if (mode === 'canvas' && viewMode === 'json') {
      // P0-4/P0-7: refuse the switch (and any canvas projection of invalid or
      // unsupported JSON) instead of silently degrading it.
      try {
        syncJsonToCanvas(rawJson);
        setJsonParseError(null);
      } catch (e: any) {
        const detail = e instanceof DocumentProjectionError
          ? e.reasons.map(r => r.message).join('; ')
          : e?.message || 'Invalid JSON';
        setJsonParseError(detail);
        setMessage(`Cannot project to canvas: ${detail}. Fix the JSON first.`);
        return;
      }
    }
    setViewMode(mode);
  };

  // Sync state to Monaco editor on toggle
  useEffect(() => {
    if (viewMode === 'json') {
      setRawJson(JSON.stringify(getAESJson(), null, 2));
    }
  }, [viewMode, nodes, edges, scenarioId, title, version, lifecycleStatus, industry, complianceLevel, description]);

  // Load canonical scenario document
  useEffect(() => {
    if (scenarioIdParam) {
      setLoadError(null);
      fetch(`/api/scenarios/${encodeURIComponent(scenarioIdParam)}`)
        .then(res => {
          if (!res.ok) {
            throw new Error(`Canonical scenario '${scenarioIdParam}' not found.`);
          }
          return res.json();
        })
        .then(data => {
          const doc = data.scenario;
          if (doc) {
            // [P0-4] Catalog documents pass the SAME projection validation as
            // pasted JSON — an unrepresentable document is refused, not degraded.
            let projection: CanvasProjection;
            try {
              projection = projectToCanvas(doc);
            } catch (e: any) {
              const detail = e instanceof DocumentProjectionError
                ? e.reasons.map(r => r.message).join('; ')
                : String(e?.message || e);
              setLoadError(`Scenario cannot be safely edited on canvas: ${detail}`);
              window.dispatchEvent(new CustomEvent('agentv-toast', {
                detail: { message: `Load Refused: ${detail}`, type: 'error' }
              }));
              return;
            }
            setRawDoc(doc);
            setScenarioId(doc.metadata?.id || doc.id || scenarioIdParam);
            setTitle(doc.metadata?.name || doc.title || 'Loaded Scenario');
            setVersion(doc.metadata?.version || '1.0.0');
            setLifecycleStatus((doc.metadata?.status || 'Draft') as any);
            setIndustry(doc.industry || 'generic');
            setComplianceLevel(doc.metadata?.compliance_level || 'Standard');
            setDescription(doc.metadata?.description || doc.description || '');

            const flowNodes = projection.nodes.map((n, idx) => ({
              id: n.id,
              type: 'default',
              position: { x: 150 + idx * 220, y: 150 },
              data: {
                label: n.id,
                task_description: n.task_description,
                required_tools: n.required_tools || [],
                expected_outcome: n.expected_outcome || []
              },
              style: {
                background: '#0f172a',
                color: '#fff',
                border: '1px solid #334155',
                borderRadius: '8px',
                fontSize: '11px',
                width: 160
              }
            }));

            const flowEdges = projection.edges.map((e, idx) => ({
              id: e.id || `edge-${idx}`,
              source: e.source,
              target: e.target,
              data: { condition: e.condition, edge_type: e.edge_type, priority: e.priority }
            }));

            setNodes(flowNodes);
            setEdges(flowEdges);
          }
        })
        .catch(err => {
          setLoadError(err.message);
          window.dispatchEvent(new CustomEvent('agentv-toast', {
            detail: { message: `Load Error: ${err.message}`, type: 'error' }
          }));
        });
    } else {
      const draft = localStorage.getItem('aes-draft');
      if (draft) {
        try {
          const parsed = JSON.parse(draft);
          // [P0-4] Drafts from the Spec Importer pass the same projection
          // validation; unrepresentable drafts are refused, never degraded.
          const projection = projectToCanvas(parsed);
          setRawDoc(parsed);
          if (parsed.metadata?.id) setScenarioId(parsed.metadata.id);
          if (parsed.metadata?.name) setTitle(parsed.metadata.name);
          if (parsed.industry) setIndustry(parsed.industry);
          if (parsed.metadata?.compliance_level) setComplianceLevel(parsed.metadata.compliance_level);
          if (parsed.metadata?.description) setDescription(parsed.metadata.description);

          setNodes(projection.nodes.map((n, idx) => ({
            id: n.id,
            type: 'default',
            position: { x: 150 + idx * 220, y: 150 },
            data: {
              label: n.id,
              task_description: n.task_description,
              required_tools: n.required_tools || [],
              expected_outcome: n.expected_outcome || []
            },
            style: {
              background: '#0f172a',
              color: '#fff',
              border: '1px solid #334155',
              borderRadius: '8px',
              fontSize: '11px',
              width: 160
            }
          })));

          setEdges(projection.edges.map((e, idx) => ({
            id: e.id || `edge-${idx}`,
            source: e.source,
            target: e.target,
            data: { condition: e.condition, edge_type: e.edge_type, priority: e.priority }
          })));

          window.dispatchEvent(new CustomEvent('agentv-toast', {
            detail: { message: 'Draft scenario loaded from Spec Importer.', type: 'success' }
          }));
        } catch (e) {
          const detail = e instanceof DocumentProjectionError
            ? `Draft cannot be safely edited on canvas: ${e.reasons.map(r => r.message).join('; ')}`
            : 'Failed to load draft scenario.';
          console.warn(detail, e);
          window.dispatchEvent(new CustomEvent('agentv-toast', {
            detail: { message: detail, type: 'error' }
          }));
        } finally {
          localStorage.removeItem('aes-draft');
        }
      } else {
        // Default initial canvas node
        setNodes([
          {
            id: 'start_node',
            type: 'default',
            position: { x: 100, y: 150 },
            data: {
              label: 'start_node',
              task_description: '',
              required_tools: [],
              expected_outcome: []
            },
            style: {
              background: '#0f172a',
              color: '#fff',
              border: '1px solid #334155',
              borderRadius: '8px',
              fontSize: '11px',
              width: 160
            }
          }
        ]);
      }
    }
  }, [scenarioIdParam]);


  const onConnect = useCallback((params: Connection) => {
    const newEdgeId = `edge_${params.source}_${params.target}_${Date.now()}`;
    setEdges((eds) =>
      addEdge(
        {
          ...params,
          id: newEdgeId,
          animated: true,
          data: { edge_type: 'sequential', priority: 100 },
        },
        eds
      )
    );
  }, [setEdges]);

  // Handle node selection in React Flow
  const onNodeClick = (_: any, node: any) => {
    setSelectedEdgeId(null);
    setSelectedNodeId(node.id);
    setNodeDesc(node.data.task_description || '');
    setNodeTools((node.data.required_tools || []).join(', '));
    setAssertions(node.data.expected_outcome || []);
  };

  // Handle edge selection — routes the inspector to the selected edge.
  const onEdgeClick = (_: any, edge: any) => {
    setSelectedNodeId(null);
    setSelectedEdgeId(edge.id);
  };

  // Edge Inspector edits write straight onto the edges state's data.* so
  // getAESJson patches them into the canonical document (patch-not-rebuild).
  const updateEdgeField = (edgeId: string, field: 'condition' | 'edge_type' | 'priority', value: any) => {
    setEdges(eds => eds.map(e => {
      if (e.id !== edgeId) return e;
      return { ...e, data: { ...e.data, [field]: value } };
    }));
  };

  // Save updates from panel back to Node object
  const saveNodeSettings = () => {
    if (!selectedNodeId) return;
    setNodes(nds => nds.map(n => {
      if (n.id === selectedNodeId) {
        return {
          ...n,
          data: {
            ...n.data,
            task_description: nodeDesc,
            required_tools: nodeTools.split(',').map(t => t.trim()).filter(Boolean),
            expected_outcome: assertions
          }
        };
      }
      return n;
    }));
    setMessage('Node changes staged. Don\'t forget to save to Catalog.');
  };

  const addNode = () => {
    const existingIds = new Set(nodes.map(n => n.id));
    let counter = nodes.length + 1;
    let nextId = `node_${counter}`;
    while (existingIds.has(nextId)) {
      counter += 1;
      nextId = `node_${counter}`;
    }
    const newNode = {
      id: nextId,

      type: 'default',
      position: { x: 200 + nodes.length * 50, y: 200 + (nodes.length % 2) * 50 },
      data: {
        label: nextId,
        task_description: 'Describe agent goal...',
        required_tools: [],
        expected_outcome: []
      },
      style: {
        background: '#0f172a',
        color: '#fff',
        border: '1px solid #334155',
        borderRadius: '8px',
        fontSize: '11px',
        width: 160
      }
    };
    setNodes(nds => [...nds, newNode]);
  };

  // [C3b] Lifecycle transitions go through the server state machine
  // (POST /api/scenarios/<id>/transition). The server validates legality,
  // requires audit reasons for sensitive regressions, and appends transition
  // history — the client never mutates lifecycle status locally.
  const handleLifecycleTransition = async (target: string) => {
    if (target === lifecycleStatus) return;
    if (!isPersistedScenario) {
      setMessage('Lifecycle transitions require a saved catalog scenario. Save first.');
      return;
    }
    const legal = LEGAL_TRANSITIONS[lifecycleStatus] || [];
    if (!legal.includes(target)) {
      setMessage(
        `Illegal transition: '${lifecycleStatus}' → '${target}'. Legal next states: ${legal.length ? legal.join(', ') : '(none — terminal state)'
        }.`
      );
      return;
    }

    setTransitioning(true);
    setMessage('');
    try {
      const res = await fetch(
        `/api/scenarios/${encodeURIComponent(scenarioId)}/transition`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ target_status: target })
        }
      );
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        setLifecycleStatus(data.lifecycle_status);
        if (rawDoc?.metadata) {
          setRawDoc({
            ...rawDoc,
            metadata: {
              ...rawDoc.metadata,
              status: data.lifecycle_status,
              content_hash: data.content_hash ?? rawDoc.metadata.content_hash,
            },
          });
        }
        setMessage(`Lifecycle transitioned to ${data.lifecycle_status} (server-authoritative).`);
      } else {
        const legalFromServer: string[] = data.legal_transitions || [];
        setMessage(
          `Transition rejected: ${data.error || 'Unknown error.'}${legalFromServer.length ? ` Legal next states: ${legalFromServer.join(', ')}.` : ''
          }`
        );
      }
    } catch (e: any) {
      setMessage(`Transition request failed: ${e.message}`);
    } finally {
      setTransitioning(false);
    }
  };

  const validateScenario = () => {
    const errors: string[] = [];
    if (!scenarioId.trim()) {
      errors.push('Scenario ID is required.');
    } else if (!/^[a-zA-Z0-9_\-]+$/.test(scenarioId)) {
      errors.push('Scenario ID must contain only alphanumeric characters, underscores, or hyphens.');
    }
    if (!title.trim()) errors.push('Scenario Name is required.');
    if (nodes.length === 0) {
      errors.push('At least one workflow node is required.');
    }

    nodes.forEach((n: any) => {
      if (!n.data.task_description?.trim() || n.data.task_description === 'Describe agent goal...') {
        errors.push(`Node [${n.id}] requires a goal description.`);
      }
    });

    return errors;
  };

  const handleSaveToCatalog = async () => {
    if (!canEditScenario) {
      setMessage('Error: Read-Only Mode. Designer privileges required to save scenarios.');
      return;
    }

    // [P0-1] In JSON mode the JSON document is the single authoritative draft.
    // We never round-trip through React Flow state: parse synchronously and
    // POST the parsed document directly. This guarantees lossless preservation
    // of fields the canvas does not model.
    // Resolve the authoritative document for BOTH authoring surfaces first.
    let authoritativeDoc: any = null;
    if (viewMode === 'json') {
      if (jsonParseError) {
        setMessage(`JSON Syntax Error: ${jsonParseError}. Fix the document before saving.`);
        return;
      }
      try {
        authoritativeDoc = JSON.parse(rawJson);
      } catch (e: any) {
        setJsonParseError(e?.message || 'Invalid JSON');
        setMessage(`JSON Syntax Error: ${e?.message}`);
        return;
      }
    } else {
      authoritativeDoc = getAESJson();
    }

    // [P0-unified] ONE validation contract for canvas AND JSON authoring:
    // every save path passes POST /api/scenarios/validate before persisting.
    try {
      const vRes = await fetch('/api/scenarios/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario: authoritativeDoc })
      });
      const vData = await vRes.json();
      if (!vData.valid) {
        const serverErrors: string[] = vData.errors || ['Validation failed without details.'];
        setMessage(`Server Validation Failed: ${serverErrors.join(' | ')}`);
        return;
      }
    } catch (e: any) {
      setMessage(`Validation request failed: ${e.message}`);
      return;
    }

    const errs = validateScenario();
    if (errs.length > 0) {
      setMessage(`Validation Failed: ${errs.join(' | ')}`);
      return;
    }

    setSaving(true);
    setMessage('');
    try {
      const payload = viewMode === 'json' ? authoritativeDoc : getAESJson();
      // Attach expected revision hash for optimistic concurrency
      if (rawDoc?.metadata?.content_hash && !payload.expected_revision_hash) {
        payload.expected_revision_hash = rawDoc.metadata.content_hash;
      }

      const res = await fetch('/api/scenarios', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (res.ok) {
        // Re-sync canvas FROM the server-echoed canonical document (never
        // from stale client-side state).
        const savedDoc = data.scenario || payload;
        syncJsonToCanvas(JSON.stringify(savedDoc));
        if (savedDoc?.metadata?.content_hash || data.scenario_hash) {
          setRawDoc({
            ...savedDoc,
            metadata: {
              ...(savedDoc.metadata || {}),
              content_hash: savedDoc.metadata?.content_hash || data.scenario_hash,
            },
          });
        }
        setMessage(`Success: Scenario saved successfully (Hash: ${data.scenario_hash?.slice(0, 12) || 'OK'}).`);
      } else {
        setMessage(`Error: ${data.error || 'Failed to save.'}`);
      }
    } catch (e: any) {
      setMessage(`Error: ${e.message}`);
    } finally {
      setSaving(false);
    }
  };


  // [P0-review] Ambiguity scan over a freshly parsed document: nodes missing
  // task_description; edges lacking condition where their source has >1
  // outgoing route (routing ambiguity); absent evaluation block.
  const buildImportAmbiguities = (doc: any): string[] => {
    const out: string[] = [];
    const wfNodes: any[] = Array.isArray(doc?.workflow?.nodes) ? doc.workflow.nodes : [];
    const wfEdges: any[] = Array.isArray(doc?.workflow?.edges) ? doc.workflow.edges : [];

    for (const n of wfNodes) {
      if (!n?.task_description || String(n.task_description).trim() === '') {
        out.push(`Node '${n?.id}' is missing task_description.`);
      }
    }

    const outgoingCount = new Map<string, number>();
    for (const e of wfEdges) {
      const src = String(e?.from ?? e?.source ?? '');
      outgoingCount.set(src, (outgoingCount.get(src) || 0) + 1);
    }
    for (const e of wfEdges) {
      const src = String(e?.from ?? e?.source ?? '');
      const dst = String(e?.to ?? e?.target ?? '');
      const noCondition =
        e?.condition === undefined || e?.condition === null || String(e.condition).trim() === '';
      if (noCondition && (outgoingCount.get(src) || 0) > 1) {
        out.push(`Edge ${src} → ${dst} has no condition while '${src}' routes to multiple targets.`);
      }
    }

    if (
      !doc?.evaluation ||
      typeof doc.evaluation !== 'object' ||
      Object.keys(doc.evaluation).length === 0
    ) {
      out.push('No evaluation block present — consensus/metrics defaults will apply.');
    }
    return out;
  };

  const handleImportSpec = async () => {
    if (!importText.trim()) return;
    try {
      const res = await fetch('/api/v1/spec-to-eval', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ markdown: importText })
      });
      const data = await res.json();
      if (res.ok && data.scenario) {
        const parsed = data.scenario;
        // [P0-4] Imported specs pass projection validation like every other path;
        // an unrepresentable parse is refused before anything is staged.
        let preview: { nodes: number; edges: number };
        try {
          const projection = projectToCanvas(parsed);
          preview = { nodes: projection.nodes.length, edges: projection.edges.length };
        } catch (e: any) {
          const detail = e instanceof DocumentProjectionError
            ? e.reasons.map(r => r.message).join('; ')
            : String(e?.message || e);
          alert(`Cannot review import on canvas: ${detail}`);
          return;
        }
        // [P0-review] DO NOT commit. Stage for explicit operator review.
        setPendingImport({
          doc: parsed,
          preview,
          ambiguities: buildImportAmbiguities(parsed),
        });
        setShowImportModal(false);
        setMessage('Spec parsed. Review the staged result before applying it.');
      } else {
        alert(`Parsing Failed: ${data.error || 'Syntax validation issue.'}`);
      }
    } catch (e: any) {
      alert(`Import error: ${e.message}`);
    }
  };

  // Explicit Apply: only here does the staged import mutate canvas/document state.
  const commitPendingImport = () => {
    if (!pendingImport) return;
    const parsed = pendingImport.doc;
    // Projection was validated at stage time; re-run defensively so a stale or
    // tampered staged doc can never bypass the refusal contract.
    const projection = projectToCanvas(parsed);
    setRawDoc(parsed);
    setScenarioId(parsed.metadata?.id || 'imported-scenario');
    setTitle(parsed.metadata?.name || 'Imported AES Scenario');
    setIndustry(parsed.industry || 'generic');
    setComplianceLevel(parsed.metadata?.compliance_level || 'Standard');
    setDescription(parsed.metadata?.description || '');

    setNodes(projection.nodes.map((n, idx) => ({
      id: n.id,
      type: 'default',
      position: { x: 100 + idx * 200, y: 150 },
      data: {
        label: n.id,
        task_description: n.task_description,
        required_tools: n.required_tools || [],
        expected_outcome: n.expected_outcome || [],
      },
      style: { background: '#0f172a', color: '#fff', border: '1px solid #334155', borderRadius: '8px', fontSize: '11px', width: 160 }
    })));

    setEdges(projection.edges.map((e, idx) => ({
      id: e.id || `edge_${e.source}_${e.target}_${idx}`,
      source: e.source,
      target: e.target,
      data: { condition: e.condition || '', edge_type: e.edge_type, priority: e.priority },
    })));

    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    setPendingImport(null);
    setShowImportModal(false);
    setMessage('Successfully parsed spec into scenario canvas nodes!');
  };

  const discardPendingImport = () => {
    setPendingImport(null);
    setMessage('Staged import discarded — current scenario untouched.');
  };

  const addAssertion = () => {
    setAssertions(prev => [...prev, { target: 'message', expected: '', mode: 'exact' }]);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-56px)] bg-navy-base text-slate-100 overflow-hidden select-none">
      {/* Top action toolbar */}
      <div className="h-14 border-b border-slate-900 bg-slate-950/20 px-6 flex items-center justify-between shrink-0 text-xs">
        <div className="flex flex-wrap items-center gap-3">
          {/* Scenario ID Field */}
          <div className="flex items-center gap-1.5 bg-slate-950/80 border border-slate-850 rounded px-2 py-0.5">
            <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider font-mono">ID:</span>
            <input
              type="text"
              disabled={!canEditScenario}
              value={scenarioId}
              onChange={(e) => setScenarioId(e.target.value)}
              placeholder="scenario_id"
              className="bg-transparent border-none w-32 text-slate-200 focus:outline-none focus:text-indigo-400 font-mono font-bold text-xs disabled:opacity-60"
            />
          </div>

          {/* Scenario Name Field */}
          <div className="flex items-center gap-1.5 bg-slate-950/80 border border-slate-850 rounded px-2 py-0.5">
            <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider font-mono">Name:</span>
            <input
              type="text"
              disabled={!canEditScenario}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Scenario Name"
              className="bg-transparent border-none w-40 text-slate-200 focus:outline-none focus:text-white font-medium text-xs disabled:opacity-60"
            />
          </div>

          {/* Version Field */}
          <div className="flex items-center gap-1 bg-slate-950/80 border border-slate-850 rounded px-2 py-0.5">
            <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider font-mono">Ver:</span>
            <input
              type="text"
              disabled={!canEditScenario}
              value={version}
              onChange={(e) => setVersion(e.target.value)}
              placeholder="1.0.0"
              className="bg-transparent border-none w-14 text-slate-300 font-mono text-[11px] focus:outline-none disabled:opacity-60 text-center"
            />
          </div>

          {/* [C3b] Lifecycle Status Selector — transitions are server-gated.
              Options not legally reachable from the current state are disabled
              with the reason surfaced in the tooltip. */}
          <div className="flex items-center gap-1 bg-slate-950/80 border border-slate-850 rounded px-2 py-0.5">
            <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider font-mono">Status:</span>
            {(() => {
              const options = ['Draft', 'Validated', 'Ready', 'Deprecated', 'Published'] as const;
              const legal = LEGAL_TRANSITIONS[lifecycleStatus] || [];
              return (
                <select
                  disabled={!canEditScenario || transitioning}
                  value={lifecycleStatus}
                  onChange={(e) => handleLifecycleTransition(e.target.value)}
                  title={
                    !canEditScenario
                      ? 'Read-only mode.'
                      : !isPersistedScenario
                        ? 'Save this scenario to the Catalog before changing lifecycle state.'
                        : `Legal next states from '${lifecycleStatus}': ${legal.length ? legal.join(', ') : 'none (terminal state)'
                        }. Transitions are validated server-side.`
                  }
                  className="bg-transparent border-none text-indigo-400 font-bold text-[11px] focus:outline-none disabled:opacity-60 cursor-pointer"
                >
                  {options.map((opt) => {
                    const isCurrent = opt === lifecycleStatus;
                    const isLegal = legal.includes(opt);
                    return (
                      <option key={opt} value={opt} disabled={!isCurrent && !isLegal}>
                        {opt}
                        {!isCurrent && !isLegal ? ' (disallowed from ' + lifecycleStatus + ')' : ''}
                      </option>
                    );
                  })}
                </select>
              );
            })()}
          </div>

          {!canEditScenario && (
            <span className="bg-amber-500/10 border border-amber-500/20 text-amber-400 font-bold px-2 py-0.5 rounded text-[10px] uppercase tracking-wider">
              Read-Only
            </span>
          )}
        </div>


        <div className="flex items-center gap-3">
          {/* View toggle */}
          <div className="flex bg-slate-950 border border-slate-900 rounded p-0.5 font-semibold">
            <button
              onClick={() => handleToggleMode('canvas')}
              className={`px-3 py-1 rounded ${viewMode === 'canvas' ? 'bg-slate-900 text-indigo-400 font-bold' : 'text-slate-500'}`}
            >
              Visual Canvas
            </button>
            <button
              onClick={() => handleToggleMode('json')}
              className={`px-3 py-1 rounded ${viewMode === 'json' ? 'bg-slate-900 text-indigo-400 font-bold' : 'text-slate-500'}`}
            >
              Raw Config JSON
            </button>
          </div>

          <button
            onClick={() => canEditScenario && setShowImportModal(true)}
            disabled={!canEditScenario}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-950 border border-slate-900 rounded text-slate-400 hover:text-slate-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors font-semibold"
          >
            <Upload className="w-3.5 h-3.5" />
            <span>Import Spec</span>
          </button>

          <button
            onClick={handleSaveToCatalog}
            disabled={saving || !canEditScenario || (viewMode === 'json' && !!jsonParseError)}
            title={viewMode === 'json' && jsonParseError ? `Cannot save: ${jsonParseError}` : undefined}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded font-bold transition-colors"
          >
            <Save className="w-3.5 h-3.5" />
            <span>{saving ? 'Saving...' : 'Save to Catalog'}</span>
          </button>
        </div>
      </div>

      {loadError && (
        <div className="bg-red-500/10 border-b border-red-500/20 px-6 py-2 flex items-center justify-between text-xs text-red-300 shrink-0">          <div className="flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
          <span>{loadError}</span>
        </div>
          <span className="text-[10px] text-red-400/80 font-mono">Canonical Document Load Failed</span>
        </div>
      )}

      {jsonParseError && viewMode === 'json' && (
        <div className="bg-red-500/10 border-b border-red-500/20 px-6 py-2 flex items-center gap-2 text-xs text-red-300 shrink-0">
          <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
          <span className="font-mono">JSON Syntax Error: {jsonParseError}</span>
          <span className="ml-auto text-[10px] text-red-400/80 font-mono">
            Save &amp; Run blocked until fixed
          </span>
        </div>
      )}

      {message && (
        <div className="bg-slate-950 border-b border-slate-900 px-6 py-2 text-center text-xs text-indigo-300 italic shrink-0">
          {message}
        </div>
      )}

      {/* Main Workspace Body */}
      <div className="flex-1 flex overflow-hidden">
        {viewMode === 'canvas' ? (
          <>
            {/* Canvas Pane */}
            <div className="flex-1 h-full bg-slate-950/20 relative">
              <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onNodeClick={onNodeClick}
                onEdgeClick={onEdgeClick}
                fitView
              >
                <Background color="#334155" gap={16} />
                <Controls />
              </ReactFlow>

              <button
                onClick={() => canEditScenario && addNode()}
                disabled={!canEditScenario}
                className="absolute top-4 left-4 p-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg shadow-lg flex items-center gap-1.5 text-xs font-bold transition-all"
              >
                <Plus className="w-4 h-4" />
                <span>Add Workflow Node</span>
              </button>
            </div>

            {/* Right Form Inspector Panel */}
            <div className="w-96 border-l border-slate-900 bg-slate-950/30 overflow-y-auto p-5 space-y-4 shrink-0 text-xs">
              <h3 className="font-bold text-slate-400 uppercase tracking-wider text-[10px]">
                {selectedEdgeId && !selectedNodeId ? 'Edge Inspector' : 'Node Inspector'}
              </h3>
              {selectedEdgeId && !selectedNodeId ? (
                (() => {
                  const selectedEdge = edges.find((e: any) => e.id === selectedEdgeId);
                  if (!selectedEdge) {
                    return (
                      <p className="text-slate-500 italic py-4">Selected edge no longer exists on the canvas.</p>
                    );
                  }
                  const edgeType = selectedEdge.data?.edge_type || 'sequential';
                  return (
                    <div className="space-y-4">
                      <div className="p-3 bg-slate-950/60 border border-slate-850 rounded-lg space-y-1">
                        <span className="text-[10px] text-slate-500 font-bold uppercase font-mono">Edge Route</span>
                        <p className="text-white font-mono font-bold text-sm">
                          {selectedEdge.source} &rarr; {selectedEdge.target}
                        </p>
                      </div>

                      <div className="space-y-1">
                        <label className="text-slate-400 font-semibold">Edge Type:</label>
                        <select
                          value={edgeType}
                          disabled={!canEditScenario}
                          onChange={(ev) => updateEdgeField(selectedEdgeId, 'edge_type', ev.target.value)}
                          className="w-full bg-slate-950 border border-slate-850 rounded px-2 py-1.5 text-slate-200 focus:outline-none focus:border-indigo-500 disabled:opacity-60"
                        >
                          {EDGE_TYPES.map((t) => (
                            <option key={t} value={t}>{t}</option>
                          ))}
                        </select>
                        <p className="text-[9px] text-slate-500 leading-snug">
                          Mirrors the canonical interpreter enum (eval_runner.execution_ir.EdgeType).
                          Unknown types are refused at patch time.
                        </p>
                      </div>

                      <div className="space-y-1">
                        <label className="text-slate-400 font-semibold">Priority (canonical default 100):</label>
                        <input
                          type="number"
                          disabled={!canEditScenario}
                          value={
                            selectedEdge.data?.priority === undefined ||
                              selectedEdge.data?.priority === null ||
                              Number.isNaN(Number(selectedEdge.data?.priority))
                              ? ''
                              : Number(selectedEdge.data?.priority)
                          }
                          placeholder="100"
                          onChange={(ev) => {
                            const raw = ev.target.value;
                            if (raw === '') {
                              updateEdgeField(selectedEdgeId, 'priority', undefined);
                              return;
                            }
                            const num = Number(raw);
                            if (!Number.isNaN(num)) updateEdgeField(selectedEdgeId, 'priority', num);
                          }}
                          className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-slate-200 focus:outline-none font-mono disabled:opacity-60"
                        />
                      </div>

                      {edgeType === 'condition' && (
                        <div className="space-y-1">
                          <label className="text-slate-400 font-semibold">Condition (routing predicate):</label>
                          <textarea
                            value={selectedEdge.data?.condition ?? ''}
                            disabled={!canEditScenario}
                            onChange={(ev) => updateEdgeField(selectedEdgeId, 'condition', ev.target.value)}
                            rows={3}
                            placeholder="e.g. approved == true"
                            className="w-full bg-slate-950 border border-slate-850 rounded p-2 text-slate-200 font-mono focus:outline-none focus:border-indigo-500 disabled:opacity-60"
                          />
                        </div>
                      )}

                      <button
                        onClick={() => setSelectedEdgeId(null)}
                        className="w-full py-2 bg-slate-900 hover:bg-slate-800 text-slate-300 rounded font-bold transition-all uppercase tracking-wider"
                      >
                        Deselect edge
                      </button>
                    </div>
                  );
                })()
              ) : selectedNodeId ? (
                <div className="space-y-4">
                  <div className="p-3 bg-slate-950/60 border border-slate-850 rounded-lg space-y-1">
                    <span className="text-[10px] text-slate-500 font-bold uppercase font-mono">Node Identifier</span>
                    <p className="text-white font-mono font-bold text-sm">{selectedNodeId}</p>
                  </div>

                  <div className="space-y-1">
                    <label className="text-slate-400 font-semibold">Goal Description:</label>
                    <textarea
                      value={nodeDesc}
                      onChange={(e) => setNodeDesc(e.target.value)}
                      rows={3}
                      className="w-full bg-slate-950 border border-slate-850 rounded p-2 text-slate-200 focus:outline-none focus:border-indigo-500 leading-normal"
                    />
                  </div>

                  <div className="space-y-1">
                    <label className="text-slate-400 font-semibold">Required Tools (comma separated):</label>
                    <input
                      type="text"
                      value={nodeTools}
                      onChange={(e) => setNodeTools(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-slate-200 focus:outline-none font-mono"
                    />
                  </div>

                  <div className="space-y-2">
                    <div className="flex justify-between items-center">
                      <label className="text-slate-400 font-semibold">Expected Outcomes (Assertions):</label>
                      <button
                        onClick={addAssertion}
                        className="text-[10px] text-indigo-400 hover:text-indigo-300 font-bold"
                      >
                        + Add Check
                      </button>
                    </div>

                    <div className="space-y-2 max-h-[220px] overflow-y-auto pr-1">
                      {assertions.map((a, i) => (
                        <div key={i} className="p-2.5 bg-slate-950 border border-slate-850 rounded-lg space-y-2 relative">
                          <button
                            onClick={() => setAssertions(prev => prev.filter((_, idx) => idx !== i))}
                            className="absolute top-2 right-2 text-slate-500 hover:text-red-400"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>

                          <div className="grid grid-cols-2 gap-2">
                            <div>
                              <span className="text-[9px] text-slate-500 font-bold uppercase">Target</span>
                              <input
                                type="text"
                                value={a.target}
                                onChange={(e) => {
                                  const val = e.target.value;
                                  setAssertions(prev => prev.map((item, idx) => idx === i ? { ...item, target: val } : item));
                                }}
                                className="w-full bg-slate-900 border border-slate-800 rounded px-1.5 py-1 text-[10px]"
                              />
                            </div>
                            <div>
                              <span className="text-[9px] text-slate-500 font-bold uppercase">Mode</span>
                              <select
                                value={a.mode}
                                onChange={(e) => {
                                  const val = e.target.value as any;
                                  setAssertions(prev => prev.map((item, idx) => idx === i ? { ...item, mode: val } : item));
                                }}
                                className="w-full bg-slate-900 border border-slate-800 rounded px-1.5 py-1 text-[10px] text-slate-300"
                              >
                                <option value="exact">Exact Match</option>
                                <option value="regex">Regex Pattern</option>
                                <option value="numerical_tolerance">Numerical Tolerance (±)</option>
                                <option value="json_schema">JSON Schema Match</option>
                              </select>
                            </div>
                          </div>

                          <div>
                            <span className="text-[9px] text-slate-500 font-bold uppercase">Expected Value / Range</span>
                            <input
                              type="text"
                              value={a.expected}
                              onChange={(e) => {
                                const val = e.target.value;
                                setAssertions(prev => prev.map((item, idx) => idx === i ? { ...item, expected: val } : item));
                              }}
                              className="w-full bg-slate-900 border border-slate-800 rounded px-1.5 py-1 text-[10px]"
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <button
                    onClick={saveNodeSettings}
                    className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded font-bold transition-all uppercase tracking-wider"
                  >
                    Apply changes
                  </button>
                </div>
              ) : (
                <p className="text-slate-500 italic py-4">Click a node or an edge on the canvas to inspect and edit its parameters.</p>
              )}
            </div>
          </>
        ) : (
          /* Monaco Editor split pane */
          <div className="flex-1 h-full bg-[#1e1e1e]">
            <Editor
              height="100%"
              defaultLanguage="json"
              theme="vs-dark"
              value={rawJson}
              onChange={(val) => {
                const text = val || '';
                setRawJson(text);
                // P0-1: synchronous parse validation. A syntax error must
                // block Save/Run and surface inline — never silently degrade.
                try {
                  JSON.parse(text);
                  setJsonParseError(null);
                } catch (e: any) {
                  setJsonParseError(e?.message || 'Invalid JSON');
                }
              }}
              options={{
                minimap: { enabled: false },
                fontSize: 12,
                fontFamily: 'JetBrains Mono',
                automaticLayout: true
              }}
            />
          </div>
        )}

      </div>

      {/* Markdown Import Modal */}
      {showImportModal && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-lg w-full p-6 space-y-4 text-slate-100 shadow-2xl flex flex-col max-h-[85vh]">
            <div className="flex items-center gap-2">
              <Upload className="w-5 h-5 text-indigo-400" />
              <h3 className="text-base font-bold text-white uppercase tracking-wider">Spec-to-Eval Markdown Parser</h3>
            </div>

            <p className="text-slate-400 text-xs leading-relaxed">
              Paste your raw Markdown PRD or test description text. The parser will translate it into a structured sequence of AES nodes.
            </p>

            <textarea
              value={importText}
              onChange={(e) => setImportText(e.target.value)}
              rows={12}
              placeholder="# Requirement description...&#10;- Verify customer refund is issued.&#10;- Ensure status code is 200."
              className="w-full bg-slate-950 border border-slate-850 rounded-lg p-3 text-xs text-slate-200 font-mono focus:outline-none focus:border-indigo-500 leading-normal flex-1"
            />

            <div className="flex justify-end gap-3 pt-2 text-xs shrink-0">
              <button
                onClick={() => setShowImportModal(false)}
                className="px-4 py-2 bg-slate-800 rounded-lg hover:bg-slate-700 text-slate-300 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleImportSpec}
                className="px-4 py-2 bg-indigo-600 rounded-lg hover:bg-indigo-500 text-white font-bold transition-colors"
              >
                Compile Spec Markdown
              </button>
            </div>
          </div>
        </div>
      )}
      {/* [P0-review] Import Review modal — staged imports are committed ONLY
          via the explicit "Review in canvas" action. */}
      {pendingImport && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-lg w-full p-6 space-y-4 text-slate-100 shadow-2xl flex flex-col max-h-[85vh]">
            <div className="flex items-center gap-2">
              <Upload className="w-5 h-5 text-indigo-400" />
              <h3 className="text-base font-bold text-white uppercase tracking-wider">Review Imported Scenario</h3>
            </div>

            <p className="text-slate-400 text-xs leading-relaxed">
              The parsed spec is staged and has NOT been applied. Current canvas state is untouched until you commit.
            </p>

            <div className="flex gap-3 text-[11px] font-mono">
              <span className="px-2 py-1 bg-slate-950 border border-slate-850 rounded">
                nodes: <b className="text-indigo-300">{pendingImport.preview.nodes}</b>
              </span>
              <span className="px-2 py-1 bg-slate-950 border border-slate-850 rounded">
                edges: <b className="text-indigo-300">{pendingImport.preview.edges}</b>
              </span>
            </div>

            {pendingImport.ambiguities.length > 0 ? (
              <div className="p-3 bg-amber-500/5 border border-amber-500/20 rounded-lg space-y-1.5 overflow-y-auto min-h-0">
                <span className="text-[10px] text-amber-400 font-bold uppercase tracking-wider flex items-center gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  Ambiguities requiring review ({pendingImport.ambiguities.length})
                </span>
                <ul className="list-disc list-inside space-y-1 text-[11px] text-amber-200/90 leading-snug">
                  {pendingImport.ambiguities.map((a, i) => (
                    <li key={i}>{a}</li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="text-emerald-400/90 text-xs">No ambiguities detected in the staged document.</p>
            )}

            <div className="flex justify-end gap-3 pt-2 text-xs shrink-0">
              <button
                onClick={discardPendingImport}
                className="px-4 py-2 bg-slate-800 rounded-lg hover:bg-slate-700 text-slate-300 transition-colors"
              >
                Discard
              </button>
              <button
                onClick={commitPendingImport}
                className="px-4 py-2 bg-indigo-600 rounded-lg hover:bg-indigo-500 text-white font-bold transition-colors"
              >
                Review in canvas
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

