import React, { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { 
  ReactFlow, Controls, Background, useNodesState, useEdgesState, addEdge 
} from '@xyflow/react';
import type { Connection } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { 
  Save, Trash2, Plus, Upload, AlertTriangle, ShieldCheck, CheckCircle2 
} from 'lucide-react';
import { Editor } from '@monaco-editor/react';
import { useRBAC } from '../context/RBACContext';

interface AssertionItem {
  target: string;
  property?: string;
  expected: string;
  mode: 'exact' | 'regex' | 'numerical_tolerance';
}

export const ScenarioComposer: React.FC = () => {
  const [searchParams] = useSearchParams();
  const scenarioIdParam = searchParams.get('scenario_id');
  const { canEditScenario } = useRBAC();

  // Authoritative full canonical AES document
  const [rawDoc, setRawDoc] = useState<any>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Core metadata
  const [scenarioId, setScenarioId] = useState('new-scenario');
  const [title, setTitle] = useState('New AES Scenario');
  const [version, setVersion] = useState('1.0.0');
  const [lifecycleStatus, setLifecycleStatus] = useState<'Draft' | 'Validated' | 'Approved' | 'Published'>('Draft');
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
  
  // JSON/YAML Toggle
  const [viewMode, setViewMode] = useState<'canvas' | 'json'>('canvas');
  const [rawJson, setRawJson] = useState('');
  
  // Spec import modal
  const [showImportModal, setShowImportModal] = useState(false);
  const [importText, setImportText] = useState('');
  
  const [message, setMessage] = useState('');
  const [saving, setSaving] = useState(false);

  // Generate AES JSON preserving all canonical document keys without semantic loss
  const getAESJson = () => {
    const workflowNodes = nodes.map((n: any) => ({
      id: n.id,
      task_description: n.data.task_description || '',
      required_tools: n.data.required_tools || [],
      expected_outcome: n.data.expected_outcome || []
    }));

    const workflowEdges = edges.map((e: any) => ({
      from: e.source,
      to: e.target,
      condition: e.data?.condition || ''
    }));

    // Start with the base canonical document or clean template
    const base = rawDoc ? { ...rawDoc } : {
      aes_version: 1.4,
      evaluation: {
        consensus: {
          strategy: 'Majority_Vote',
          min_judges: 1,
          judge_panel: ['Luna-1']
        }
      }
    };

    base.metadata = {
      ...(base.metadata || {}),
      id: scenarioId,
      name: title,
      version: version,
      status: lifecycleStatus,
      compliance_level: complianceLevel,
      description
    };
    base.industry = industry;
    base.workflow = {
      ...(base.workflow || {}),
      nodes: workflowNodes,
      edges: workflowEdges
    };

    return base;
  };

  const syncJsonToCanvas = (jsonStr: string) => {
    try {
      const parsed = JSON.parse(jsonStr);
      setRawDoc(parsed);
      if (parsed.metadata?.id) setScenarioId(parsed.metadata.id);
      if (parsed.metadata?.name) setTitle(parsed.metadata.name);
      if (parsed.metadata?.version) setVersion(parsed.metadata.version);
      if (parsed.metadata?.status) setLifecycleStatus(parsed.metadata.status);
      if (parsed.industry) setIndustry(parsed.industry);
      if (parsed.metadata?.compliance_level) setComplianceLevel(parsed.metadata.compliance_level);
      if (parsed.metadata?.description) setDescription(parsed.metadata.description);

      if (parsed.workflow?.nodes) {
        const flowNodes = parsed.workflow.nodes.map((n: any, idx: number) => ({
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
      }

      if (parsed.workflow?.edges) {
        const flowEdges = parsed.workflow.edges.map((e: any, idx: number) => ({
          id: `edge-${idx}`,
          source: e.from,
          target: e.to,
          data: { condition: e.condition }
        }));
        setEdges(flowEdges);
      }
    } catch (e) {
      console.warn("Invalid JSON in editor, skipping canvas sync:", e);
    }
  };

  const handleToggleMode = (mode: 'canvas' | 'json') => {
    if (mode === 'canvas' && viewMode === 'json') {
      syncJsonToCanvas(rawJson);
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
            setRawDoc(doc);
            setScenarioId(doc.metadata?.id || doc.id || scenarioIdParam);
            setTitle(doc.metadata?.name || doc.title || 'Loaded Scenario');
            setVersion(doc.metadata?.version || '1.0.0');
            setLifecycleStatus(doc.metadata?.status || 'Draft');
            setIndustry(doc.industry || 'generic');
            setComplianceLevel(doc.metadata?.compliance_level || 'Standard');
            setDescription(doc.metadata?.description || doc.description || '');

            const workflow = doc.workflow || { nodes: [], edges: [] };
            const flowNodes = (workflow.nodes || []).map((n: any, idx: number) => ({
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

            const flowEdges = (workflow.edges || []).map((e: any, idx: number) => ({
              id: `edge-${idx}`,
              source: e.from,
              target: e.to,
              data: { condition: e.condition }
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
          setRawDoc(parsed);
          if (parsed.metadata?.id) setScenarioId(parsed.metadata.id);
          if (parsed.metadata?.name) setTitle(parsed.metadata.name);
          if (parsed.industry) setIndustry(parsed.industry);
          if (parsed.metadata?.compliance_level) setComplianceLevel(parsed.metadata.compliance_level);
          if (parsed.metadata?.description) setDescription(parsed.metadata.description);

          if (parsed.workflow?.nodes) {
            const flowNodes = parsed.workflow.nodes.map((n: any, idx: number) => ({
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
          }

          if (parsed.workflow?.edges) {
            const flowEdges = parsed.workflow.edges.map((e: any, idx: number) => ({
              id: `edge-${idx}`,
              source: e.from,
              target: e.to,
              data: { condition: e.condition }
            }));
            setEdges(flowEdges);
          }
          window.dispatchEvent(new CustomEvent('agentv-toast', {
            detail: { message: 'Draft scenario loaded from Spec Importer.', type: 'success' }
          }));
        } catch (e) {
          console.warn("Failed to load draft scenario:", e);
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
              task_description: 'Agent should verify user identity',
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
    setEdges((eds) => addEdge({ ...params, animated: true }, eds));
  }, [setEdges]);

  // Handle node selection in React Flow
  const onNodeClick = (_: any, node: any) => {
    setSelectedNodeId(node.id);
    setNodeDesc(node.data.task_description || '');
    setNodeTools((node.data.required_tools || []).join(', '));
    setAssertions(node.data.expected_outcome || []);
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
    const nextId = `node_${nodes.length + 1}`;
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
    const errs = validateScenario();
    if (errs.length > 0) {
      setMessage(`Validation Failed: ${errs.join(' | ')}`);
      return;
    }

    setSaving(true);
    setMessage('');
    try {
      const payload = getAESJson();
      const res = await fetch('/api/scenarios', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (res.ok) {
        setMessage(`Success: Scenario saved successfully to catalog.`);
      } else {
        setMessage(`Error: ${data.error || 'Failed to save.'}`);
      }
    } catch (e: any) {
      setMessage(`Error: ${e.message}`);
    } finally {
      setSaving(false);
    }
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
        setScenarioId(parsed.metadata?.id || 'imported-scenario');
        setTitle(parsed.metadata?.name || 'Imported AES Scenario');
        setIndustry(parsed.industry || 'generic');
        setComplianceLevel(parsed.metadata?.compliance_level || 'Standard');
        setDescription(parsed.metadata?.description || '');
        
        // Load nodes
        const parsedNodes = (parsed.workflow?.nodes || []).map((n: any, idx: number) => ({
          id: n.id,
          type: 'default',
          position: { x: 100 + idx * 200, y: 150 },
          data: {
            label: n.id,
            task_description: n.task_description,
            required_tools: n.required_tools || [],
            expected_outcome: n.expected_outcome || []
          },
          style: { background: '#0f172a', color: '#fff', border: '1px solid #334155', borderRadius: '8px', fontSize: '11px', width: 160 }
        }));
        setNodes(parsedNodes);
        setEdges([]);
        setShowImportModal(false);
        setMessage('Successfully parsed spec into scenario canvas nodes!');
      } else {
        alert(`Parsing Failed: ${data.error || 'Syntax validation issue.'}`);
      }
    } catch (e: any) {
      alert(`Import error: ${e.message}`);
    }
  };

  const addAssertion = () => {
    setAssertions(prev => [...prev, { target: 'message', expected: '', mode: 'exact' }]);
  };

  return (
    <div className="flex flex-col h-[calc(100vh-56px)] bg-navy-base text-slate-100 overflow-hidden select-none">
      {/* Top action toolbar */}
      <div className="h-14 border-b border-slate-900 bg-slate-950/20 px-6 flex items-center justify-between shrink-0 text-xs">
        <div className="flex items-center gap-3">
          <input 
            type="text"
            disabled={!canEditScenario}
            value={scenarioId}
            onChange={(e) => setScenarioId(e.target.value)}
            placeholder="Scenario ID"
            className="bg-slate-950 border border-slate-800 rounded px-2.5 py-1 w-36 text-slate-200 focus:outline-none focus:border-indigo-500 font-mono font-bold disabled:opacity-60"
          />
          <input 
            type="text"
            disabled={!canEditScenario}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Scenario Name"
            className="bg-slate-950 border border-slate-800 rounded px-2.5 py-1 w-44 text-slate-200 focus:outline-none disabled:opacity-60"
          />
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-slate-500 font-mono">v</span>
            <input 
              type="text"
              disabled={!canEditScenario}
              value={version}
              onChange={(e) => setVersion(e.target.value)}
              placeholder="1.0.0"
              className="bg-slate-950 border border-slate-800 rounded px-1.5 py-1 w-16 text-slate-300 font-mono text-[11px] focus:outline-none disabled:opacity-60 text-center"
            />
          </div>
          <select
            disabled={!canEditScenario}
            value={lifecycleStatus}
            onChange={(e) => setLifecycleStatus(e.target.value as any)}
            className="bg-slate-950 border border-slate-850 text-indigo-400 font-bold rounded px-2 py-1 text-[11px] focus:outline-none disabled:opacity-60 cursor-pointer"
          >
            <option value="Draft">Draft</option>
            <option value="Validated">Validated</option>
            <option value="Approved">Approved</option>
            <option value="Published">Published</option>
          </select>
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
            disabled={saving || !canEditScenario}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded font-bold transition-colors"
          >
            <Save className="w-3.5 h-3.5" />
            <span>{saving ? 'Saving...' : 'Save to Catalog'}</span>
          </button>
        </div>
      </div>

      {loadError && (
        <div className="bg-red-500/10 border-b border-red-500/20 px-6 py-2 flex items-center justify-between text-xs text-red-300 shrink-0">
          <div className="flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
            <span>{loadError}</span>
          </div>
          <span className="text-[10px] text-red-400/80 font-mono">Canonical Document Load Failed</span>
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
              <h3 className="font-bold text-slate-400 uppercase tracking-wider text-[10px]">Node Inspector</h3>
              {selectedNodeId ? (
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
                                <option value="exact">Exact</option>
                                <option value="regex">Regex</option>
                              </select>
                            </div>
                          </div>

                          <div>
                            <span className="text-[9px] text-slate-500 font-bold uppercase">Expected Value</span>
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
                    Staging Node Settings
                  </button>
                </div>
              ) : (
                <p className="text-slate-500 italic py-4">Click a node on the canvas to inspect and edit its parameters.</p>
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
                try {
                  const parsed = JSON.parse(val || '{}');
                  // Re-load metadata if typed directly in editor
                  if (parsed.metadata?.id) setScenarioId(parsed.metadata.id);
                  if (parsed.metadata?.name) setTitle(parsed.metadata.name);
                } catch (e) {}
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
    </div>
  );
};
