import React, { useState, useEffect, useMemo } from 'react';
import ReactDiffViewer from 'react-diff-viewer-continued';
import {
  Layers,
  PlayCircle,
  Save,
  Check,
  Sparkles,
  Copy,
  ArrowRight,
  HelpCircle,
  Shield,
  Sliders,
  FileText,
  Code2,
  Hash,
  AlertTriangle,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export interface MutationDescriptor {
  id: string;
  label: string;
  vector: string;
  operation: string;
  tier: string;
  source: string;
  description: string;
  target_field: string;
  regulatory_frameworks?: string[];
  org_id?: string | null;
  deterministic?: boolean;
  parameters_schema?: any;
}

interface ScenarioOption {
  id: string;
  title?: string;
  name?: string;
  industry: string;
  description?: string;
  metadata?: {
    id?: string;
    name?: string;
    description?: string;
    compliance_level?: string;
  };
  workflow?: {
    nodes?: Array<{
      id: string;
      task_description: string;
      required_tools?: string[];
      expected_outcome?: any;
    }>;
    edges?: any[];
  };
}

export const AdversarialMutator: React.FC = () => {
  const navigate = useNavigate();
  const [scenarios, setScenarios] = useState<ScenarioOption[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [mutationType, setMutationType] = useState('');
  const [seed, setSeed] = useState('42');
  const [loadingScenarios, setLoadingScenarios] = useState(false);

  // Dynamic Catalog State (strictly backend-confirmed, zero silent offline fallback)
  const [catalog, setCatalog] = useState<MutationDescriptor[]>([]);
  const [loadingCatalog, setLoadingCatalog] = useState<boolean>(true);
  const [catalogError, setCatalogError] = useState<string>('');
  const [selectedVector, setSelectedVector] = useState<string>('All');
  const [diffMode, setDiffMode] = useState<'prompt' | 'json'>('json');
  const [splitView, setSplitView] = useState(true);
  const [wrapLines, setWrapLines] = useState(false);

  const [mutating, setMutating] = useState(false);
  const [mutatedJson, setMutatedJson] = useState<any>(null);
  const [lintReport, setLintReport] = useState<any>(null);
  const [canonicalBaseScenario, setCanonicalBaseScenario] = useState<any>(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [copied, setCopied] = useState(false);

  // Search & Filter state
  const [industryFilter, setIndustryFilter] = useState('All');
  const [searchTerm, setSearchTerm] = useState('');

  // Fetch full canonical scenario specification when selectedId changes
  useEffect(() => {
    if (!selectedId) {
      setCanonicalBaseScenario(null);
      return;
    }
    let isCurrent = true;
    fetch(`/api/scenarios/${encodeURIComponent(selectedId)}`)
      .then((res) => res.json())
      .then((data) => {
        if (isCurrent && data.scenario) {
          setCanonicalBaseScenario(data.scenario);
        }
      })
      .catch((err) => {
        console.warn('Failed to load canonical scenario specification for diff:', err);
      });
    return () => {
      isCurrent = false;
    };
  }, [selectedId]);

  // 1. Fetch live mutation catalog from backend - strictly fail-closed, no hardcoded fallbacks
  const fetchCatalog = async () => {
    setLoadingCatalog(true);
    setCatalogError('');
    try {
      const res = await fetch('/api/v1/mutations');
      if (!res.ok) {
        throw new Error(`Server returned HTTP ${res.status}: Failed to retrieve mutation catalog`);
      }
      const data = await res.json();
      if (data.mutations && Array.isArray(data.mutations) && data.mutations.length > 0) {
        setCatalog(data.mutations);
        if (!mutationType) {
          setMutationType(data.mutations[0].id);
        }
      } else {
        throw new Error('Runtime reported empty mutation catalog (no active mutator engines registered)');
      }
    } catch (e: any) {
      const msg = e.message || 'Could not fetch dynamic mutations catalog from backend';
      console.error('Failed to fetch adversarial mutation catalog:', e);
      setCatalog([]);
      setCatalogError(msg);
    } finally {
      setLoadingCatalog(false);
    }
  };

  // 2. Fetch scenarios
  const fetchScenarios = async () => {
    setLoadingScenarios(true);
    try {
      const res = await fetch('/api/scenarios?limit=10000');
      const data = await res.json();
      if (res.ok && data.scenarios) {
        setScenarios(data.scenarios);
      }
    } catch (e) {
      console.error('Error fetching scenarios:', e);
    } finally {
      setLoadingScenarios(false);
    }
  };

  useEffect(() => {
    fetchCatalog();
    fetchScenarios();
  }, []);

  // Compute available vectors dynamically
  const vectors = useMemo(() => {
    const rawVectors = Array.from(new Set(catalog.map((m) => m.vector))).filter(Boolean);
    return ['All', ...rawVectors.sort()];
  }, [catalog]);

  // Filter mutations by selected vector
  const visibleMutations = useMemo(() => {
    if (selectedVector === 'All') return catalog;
    return catalog.filter((m) => m.vector === selectedVector);
  }, [catalog, selectedVector]);

  // Ensure selected mutation exists in current visible subset
  useEffect(() => {
    if (visibleMutations.length > 0) {
      if (!visibleMutations.some((m) => m.id === mutationType)) {
        setMutationType(visibleMutations[0].id);
      }
    } else {
      setMutationType('');
    }
  }, [selectedVector, visibleMutations, mutationType]);

  const selectedDescriptor = useMemo(() => {
    return catalog.find((m) => m.id === mutationType) || catalog[0] || null;
  }, [catalog, mutationType]);

  // Recommend diff mode based on vector type
  const isLinguistic = selectedDescriptor?.vector === 'INPUT' || selectedDescriptor?.vector === 'CONTEXT';

  const filteredOptions = scenarios.filter((s) => {
    const indMatch = industryFilter === 'All' || s.industry === industryFilter;
    const textMatch =
      !searchTerm ||
      s.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (s.metadata?.name || s.title || "").toLowerCase().includes(searchTerm.toLowerCase());
    return indMatch && textMatch;
  });

  const industries = [
    'All',
    ...Array.from(new Set(scenarios.map((s) => s.industry)))
      .filter(Boolean)
      .sort((a, b) => a.localeCompare(b)),
  ];

  useEffect(() => {
    if (filteredOptions.length > 0) {
      if (!filteredOptions.some((o) => o.id === selectedId)) {
        setSelectedId(filteredOptions[0].id);
      }
    } else {
      setSelectedId('');
    }
  }, [industryFilter, searchTerm, scenarios]);

  const handleMutate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedId || !mutationType) return;

    setMutating(true);
    setError('');
    setMutatedJson(null);
    setLintReport(null);
    setSaveMsg('');

    try {
      const parsedSeed = seed ? parseInt(seed, 10) : undefined;
      const res = await fetch('/api/v1/mutate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scenario_id: selectedId,
          type: mutationType,
          seed: Number.isInteger(parsedSeed) ? parsedSeed : 42,
        }),
      });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        setMutatedJson(data.mutated);
        setLintReport(data.lint_report || null);
        // Automatically default diff mode to the recommended view
        setDiffMode(isLinguistic ? 'prompt' : 'json');
        window.dispatchEvent(
          new CustomEvent('agentv-toast', {
            detail: {
              message: `Adversarial mutation (${selectedDescriptor?.label || mutationType}) executed.`,
              type: 'success',
            },
          })
        );
      } else {
        setError(data.message || 'Failed to mutate scenario.');
      }
    } catch (err: any) {
      setError(err.message || 'Network error executing mutation.');
    } finally {
      setMutating(false);
    }
  };

  const handleSaveMutant = async () => {
    if (!mutatedJson) return;
    setSaving(true);
    setSaveMsg('');
    setError('');

    const expectedSuffix = `_mutated_${mutationType}`;
    let targetId = mutatedJson.metadata?.id || mutatedJson.id || selectedId;
    if (!targetId.endsWith(expectedSuffix)) {
      targetId = `${targetId}${expectedSuffix}`;
    }

    const derivedName =
      mutatedJson.metadata?.name ||
      mutatedJson.name ||
      `${selectedId} (Mutated: ${selectedDescriptor?.label || mutationType})`;

    const mutantCopy = {
      ...mutatedJson,
      metadata: {
        ...(mutatedJson.metadata || {}),
        id: targetId,
        parent_scenario_id: selectedId,
        name: derivedName,
        adversarial_vector: selectedDescriptor?.vector,
        adversarial_tier: selectedDescriptor?.tier,
        adversarial_operation: selectedDescriptor?.operation,
      },
    };
    delete (mutantCopy as any).name;
    delete (mutantCopy as any).id;
    delete (mutantCopy as any).title;

    try {
      const res = await fetch('/api/scenarios', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mutantCopy),
      });
      if (res.ok) {
        const data = await res.json().catch(() => ({}));
        const savedId = data.id || data.scenario_id || targetId;
        setSaveMsg(`Mutated scenario saved to library: ${savedId}`);
        window.dispatchEvent(
          new CustomEvent('agentv-toast', {
            detail: { message: `Mutated scenario successfully saved: ${savedId}`, type: 'success' },
          })
        );
        setTimeout(() => navigate(`/scenarios?q=${encodeURIComponent(savedId)}`), 1500);
      } else {
        const errData = await res.json().catch(() => ({}));
        setError(errData.error || 'Failed to save mutated scenario.');
      }
    } catch (err: any) {
      setError(err.message || 'Network error saving mutated scenario.');
    } finally {
      setSaving(false);
    }
  };

  const handleCopy = () => {
    if (!mutatedJson) return;
    navigator.clipboard.writeText(JSON.stringify(mutatedJson, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const getScenarioText = (sc: any) => {
    if (!sc) return '';
    let text = `Scenario ID: ${sc.metadata?.id || sc.id || ''}\n`;
    text += `Title: ${sc.metadata?.name || sc.title || ''}\n`;
    text += `Description: ${sc.metadata?.description || sc.description || ''}\n\n`;

    if (sc.workflow?.nodes) {
      sc.workflow.nodes.forEach((n: any) => {
        text += `[Node ID: ${n.id}]\n`;
        text += `Task Description:\n${n.task_description || ''}\n`;
        if (n.parameters && Object.keys(n.parameters).length > 0) {
          text += `Parameters: ${JSON.stringify(n.parameters)}\n`;
        }
        if (n.retrieved_documents && n.retrieved_documents.length > 0) {
          text += `Retrieved Documents (${n.retrieved_documents.length}):\n${JSON.stringify(n.retrieved_documents, null, 2)}\n`;
        }
        text += '\n';
      });
    }
    return text;
  };

  const chosenScenario = scenarios.find((s) => s.id === selectedId) || null;

  // Provenance badge helper
  const renderSourceBadge = (source?: string) => {
    switch (source) {
      case 'enterprise':
        return (
          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-purple-500/20 text-purple-300 border border-purple-500/40">
            ENTERPRISE T5
          </span>
        );
      case 'plugin':
        return (
          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
            CUSTOM PLUGIN
          </span>
        );
      default:
        return (
          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-500/40">
            CORE RUNTIME
          </span>
        );
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-[1700px] w-full mx-auto min-h-screen flex flex-col">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-slate-900 pb-5">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Layers className="w-5 h-5 text-indigo-400" />
            <span>Adversarial Scenario Mutator</span>
          </h1>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            Test policy stability, safety constraints, and resilience across all perturbation vectors.
            Only strictly backend-confirmed, executable mutators are exposed.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-slate-500 font-mono">
            {catalog.length} Mutators Active ({vectors.length > 1 ? vectors.length - 1 : 0} Vectors)
          </span>
        </div>
      </div>

      {/* Explicit Backend Error Banner */}
      {catalogError && (
        <div className="p-4 rounded-xl bg-rose-950/40 border border-rose-800 text-rose-200 text-xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 shadow-lg">
          <div className="flex items-start gap-3">
            <AlertTriangle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
            <div>
              <p className="font-bold text-rose-100">Live Mutation Catalog Unavailable</p>
              <p className="text-rose-300/90 text-[11px] mt-0.5">
                The console requires verified mutators from <code className="font-mono bg-rose-900/60 px-1 py-0.5 rounded text-rose-100">/api/v1/mutations</code>.
                Silent fallback is disabled to prevent executing unsupported mutations. Details: {catalogError}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={fetchCatalog}
            className="px-3 py-1.5 bg-rose-800 hover:bg-rose-700 text-white rounded-lg text-xs font-semibold shrink-0 transition-colors self-end sm:self-center"
          >
            Retry Catalog Load
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-1">
        {/* Left column: Controls */}
        <div className="space-y-6 lg:col-span-1">
          <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4">
            <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
              <Sparkles className="w-4 h-4 text-indigo-400" />
              <span>Mutation Settings</span>
            </h3>

            {loadingScenarios ? (
              <div className="text-xs text-slate-500 italic py-4">Loading scenario choices...</div>
            ) : scenarios.length === 0 ? (
              <div className="text-xs text-rose-400 py-4">
                No scenarios available to mutate. Create a scenario first.
              </div>
            ) : (
              <form onSubmit={handleMutate} className="space-y-4">
                {/* Scenario Filters */}
                <div className="space-y-3 p-3 bg-slate-950/40 border border-slate-900 rounded-lg">
                  <span className="text-[9px] text-slate-500 font-bold uppercase font-mono">
                    Base Scenario Selector
                  </span>

                  <div className="space-y-1">
                    <label className="text-[9px] text-slate-400 font-medium">Search Keyword</label>
                    <input
                      type="text"
                      placeholder="Type to filter..."
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-850 rounded px-2 py-1.5 text-[11px] text-slate-350 focus:outline-none focus:border-indigo-500 font-mono"
                    />
                  </div>

                  <div className="space-y-1">
                    <label className="text-[9px] text-slate-400 font-medium">Sector</label>
                    <select
                      value={industryFilter}
                      onChange={(e) => setIndustryFilter(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-850 rounded px-2 py-1.5 text-[11px] text-slate-350 focus:outline-none focus:border-indigo-500 cursor-pointer"
                    >
                      {industries.map((ind) => (
                        <option key={ind} value={ind}>
                          {ind === 'All' ? 'All Sectors' : ind.replace(/_/g, ' ')}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="space-y-1">
                    <label className="text-[9px] text-slate-400 font-medium">
                      Target Scenario ({filteredOptions.length} available)
                    </label>
                    <select
                      value={selectedId}
                      onChange={(e) => setSelectedId(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-indigo-500 cursor-pointer font-mono"
                    >
                      {filteredOptions.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.metadata?.name || s.title || s.id} ({s.id})
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                {/* Catalog Loading / Error States in Form */}
                {loadingCatalog ? (
                  <div className="p-3 bg-slate-950/80 border border-slate-850 rounded-lg text-xs text-slate-500 italic">
                    Loading executable mutation catalog from runtime...
                  </div>
                ) : catalogError ? (
                  <div className="p-3 bg-rose-950/30 border border-rose-900 rounded-lg text-xs text-rose-300">
                    Cannot configure mutation: Catalog is currently unavailable.
                  </div>
                ) : catalog.length === 0 ? (
                  <div className="p-3 bg-amber-950/30 border border-amber-900 rounded-lg text-xs text-amber-300">
                    No executable mutators found on backend.
                  </div>
                ) : (
                  <>
                    {/* Vector Selection Tabs */}
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <label className="text-[9px] text-slate-500 font-bold uppercase font-mono flex items-center gap-1">
                          <Sliders className="w-3 h-3 text-indigo-400" />
                          <span>Perturbation Vector</span>
                        </label>
                        <span className="text-[9px] text-slate-600 font-mono">
                          {visibleMutations.length} options
                        </span>
                      </div>
                      <div className="flex flex-wrap gap-1 bg-slate-950/80 p-1 rounded-lg border border-slate-850 max-h-24 overflow-y-auto">
                        {vectors.map((vec) => (
                          <button
                            key={vec}
                            type="button"
                            onClick={() => setSelectedVector(vec)}
                            className={`px-2 py-1 rounded text-[10px] font-mono transition-colors ${
                              selectedVector === vec
                                ? 'bg-indigo-600 text-white font-bold'
                                : 'text-slate-400 hover:text-white hover:bg-slate-900'
                            }`}
                          >
                            {vec}
                          </button>
                        ))}
                      </div>
                    </div>

                    {/* Mutation Strategy Selector */}
                    <div className="space-y-1.5">
                      <label className="text-[9px] text-slate-500 font-bold uppercase font-mono">
                        Mutation Strategy ({visibleMutations.length})
                      </label>
                      <select
                        value={mutationType}
                        onChange={(e) => setMutationType(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-indigo-500 cursor-pointer font-medium"
                      >
                        {visibleMutations.map((m) => (
                          <option key={m.id} value={m.id}>
                            [{m.vector}] {m.label} ({m.tier.replace('T', 'Tier ')})
                          </option>
                        ))}
                      </select>
                    </div>

                    {/* Deterministic Seed */}
                    <div className="space-y-1.5">
                      <label className="text-[9px] text-slate-500 font-bold uppercase font-mono flex items-center gap-1">
                        <Hash className="w-3 h-3 text-indigo-400" />
                        <span>Deterministic Seed (PRNG)</span>
                      </label>
                      <input
                        type="number"
                        value={seed}
                        onChange={(e) => setSeed(e.target.value)}
                        placeholder="42"
                        className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-indigo-500 font-mono"
                      />
                      <span className="text-[9px] text-slate-600">
                        Controls pseudo-random character replacements & perturbation permutations.
                      </span>
                    </div>

                    {/* Strategy Details Card */}
                    {selectedDescriptor && (
                      <div className="p-3 bg-slate-950/80 border border-slate-850 rounded-lg space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="text-[9px] text-slate-500 font-bold uppercase font-mono flex items-center gap-1">
                            <HelpCircle className="w-3.5 h-3.5 text-indigo-400" />
                            <span>Strategy Details</span>
                          </span>
                          {renderSourceBadge(selectedDescriptor.source)}
                        </div>
                        <p className="text-[10px] text-slate-300 leading-relaxed font-sans">
                          {selectedDescriptor.description}
                        </p>
                        <div className="flex flex-wrap gap-1.5 pt-1 border-t border-slate-900">
                          <span className="px-1.5 py-0.5 rounded bg-slate-900 text-slate-400 text-[9px] font-mono">
                            Target: {selectedDescriptor.target_field}
                          </span>
                          <span className="px-1.5 py-0.5 rounded bg-slate-900 text-slate-400 text-[9px] font-mono">
                            Op: {selectedDescriptor.operation}
                          </span>
                          <span className="px-1.5 py-0.5 rounded bg-slate-900 text-slate-400 text-[9px] font-mono">
                            {selectedDescriptor.tier}
                          </span>
                        </div>

                        {selectedDescriptor.regulatory_frameworks && selectedDescriptor.regulatory_frameworks.length > 0 && (
                          <div className="flex flex-wrap gap-1 pt-1">
                            {selectedDescriptor.regulatory_frameworks.map((rf) => (
                              <span
                                key={rf}
                                className="px-1.5 py-0.5 rounded bg-indigo-950/40 text-indigo-300 border border-indigo-900/50 text-[8px] font-mono"
                              >
                                {rf}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}

                <button
                  type="submit"
                  disabled={mutating || !selectedId || catalog.length === 0 || !mutationType || !!catalogError}
                  className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-xs font-bold rounded-lg transition-colors flex items-center justify-center gap-1.5"
                >
                  <PlayCircle className="w-4 h-4" />
                  <span>{mutating ? 'Executing Mutator Engine...' : 'Execute Mutation Engine'}</span>
                </button>
              </form>
            )}
          </div>
        </div>

        {/* Right column: Comparative Diff & Save action */}
        <div className="lg:col-span-2 bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4 flex flex-col justify-between min-h-[700px] flex-1">
          <div className="space-y-4 flex-1 flex flex-col">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2 border-b border-slate-900/60 pb-3">
              <div>
                <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                  <Shield className="w-4 h-4 text-emerald-400" />
                  <span>Scenario State Attribution Diff</span>
                  {mutatedJson && (
                    <span className="text-[9px] text-slate-500 font-mono flex items-center gap-1 lowercase">
                      ({selectedId} <ArrowRight className="w-3 h-3" /> {mutatedJson.id || mutatedJson.metadata?.id})
                    </span>
                  )}
                </h3>
              </div>

              {/* Dual Diff View Selector & Layout Mode */}
              <div className="flex items-center gap-2">
                {mutatedJson && (
                  <>
                    <div className="flex items-center bg-slate-900 p-0.5 rounded-lg border border-slate-800">
                      <button
                        type="button"
                        onClick={() => setDiffMode('prompt')}
                        className={`px-2 py-1 rounded text-[10px] font-mono flex items-center gap-1 transition-colors ${
                          diffMode === 'prompt'
                            ? 'bg-indigo-600 text-white font-bold'
                            : 'text-slate-400 hover:text-white'
                        }`}
                      >
                        <FileText className="w-3 h-3" />
                        <span>Prompts {isLinguistic && '★'}</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => setDiffMode('json')}
                        className={`px-2 py-1 rounded text-[10px] font-mono flex items-center gap-1 transition-colors ${
                          diffMode === 'json'
                            ? 'bg-indigo-600 text-white font-bold'
                            : 'text-slate-400 hover:text-white'
                        }`}
                      >
                        <Code2 className="w-3 h-3" />
                        <span>Full Spec JSON {!isLinguistic && '★'}</span>
                      </button>
                    </div>

                    <div className="flex items-center bg-slate-900 p-0.5 rounded-lg border border-slate-800">
                      <button
                        type="button"
                        onClick={() => setSplitView(true)}
                        className={`px-2 py-1 rounded text-[10px] font-mono transition-colors ${
                          splitView
                            ? 'bg-indigo-600 text-white font-bold'
                            : 'text-slate-400 hover:text-white'
                        }`}
                        title="Side-by-side 50/50 split diff view"
                      >
                        <span>Split</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => setSplitView(false)}
                        className={`px-2 py-1 rounded text-[10px] font-mono transition-colors ${
                          !splitView
                            ? 'bg-indigo-600 text-white font-bold'
                            : 'text-slate-400 hover:text-white'
                        }`}
                        title="Single unified inline diff view"
                      >
                        <span>Unified</span>
                      </button>
                    </div>

                    <div className="flex items-center bg-slate-900 p-0.5 rounded-lg border border-slate-800">
                      <button
                        type="button"
                        onClick={() => setWrapLines(false)}
                        className={`px-2 py-1 rounded text-[10px] font-mono transition-colors ${
                          !wrapLines
                            ? 'bg-indigo-600 text-white font-bold'
                            : 'text-slate-400 hover:text-white'
                        }`}
                        title="Horizontal scroll view (no line wrap)"
                      >
                        <span>Scroll</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => setWrapLines(true)}
                        className={`px-2 py-1 rounded text-[10px] font-mono transition-colors ${
                          wrapLines
                            ? 'bg-indigo-600 text-white font-bold'
                            : 'text-slate-400 hover:text-white'
                        }`}
                        title="Wrap text lines within column"
                      >
                        <span>Wrap</span>
                      </button>
                    </div>
                  </>
                )}

                {mutatedJson && (
                  <button
                    onClick={handleCopy}
                    className="flex items-center gap-1 px-2.5 py-1 bg-slate-900 hover:bg-slate-850 border border-slate-850 rounded text-[10px] font-bold text-slate-300 hover:text-white transition-colors"
                  >
                    {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                    <span>{copied ? 'Copied' : 'Copy JSON'}</span>
                  </button>
                )}
              </div>
            </div>

            {error && (
              <div className="p-3 bg-rose-500/10 border border-rose-500/25 rounded-lg text-rose-400 text-xs">
                {error}
              </div>
            )}

            {saveMsg && (
              <div className="p-3 bg-emerald-500/10 border border-emerald-500/25 rounded-lg text-emerald-400 text-xs font-semibold">
                {saveMsg}
              </div>
            )}

            {mutating ? (
              <div className="min-h-[500px] flex flex-col justify-center items-center gap-3">
                <div className="w-6 h-6 border-2 border-indigo-500/20 border-t-indigo-500 rounded-full animate-spin" />
                <span className="text-xs text-slate-500">
                  Synthesizing adversarial perturbations across {selectedDescriptor?.vector || 'target'} vector...
                </span>
              </div>
            ) : !mutatedJson ? (
              <div className="min-h-[500px] border border-dashed border-slate-900 rounded-xl flex flex-col items-center justify-center p-6 text-center text-xs text-slate-600">
                <Layers className="w-8 h-8 text-slate-800 mb-2" />
                <p>Select target scenario and perturbation strategy, then execute the mutation engine.</p>
                <p className="text-[10px] text-slate-700 mt-1">
                  Attribution Diff compares the canonical baseline scenario specification against the mutated output.
                </p>
              </div>
            ) : (
              <div className="flex-1 flex flex-col gap-3 min-h-[600px] h-[calc(100vh-270px)]">
                {lintReport && (
                  <div
                    className={`p-3 rounded-lg border flex flex-col gap-2 shrink-0 ${
                      lintReport.status === 'pass'
                        ? 'bg-emerald-950/20 border-emerald-500/30'
                        : lintReport.status === 'warning'
                        ? 'bg-amber-950/20 border-amber-500/30'
                        : 'bg-rose-950/20 border-rose-500/30'
                    }`}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold tracking-wider font-mono uppercase ${
                            lintReport.tier === 'GOLD'
                              ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40'
                              : lintReport.tier === 'SILVER'
                              ? 'bg-slate-300/20 text-slate-200 border border-slate-400/40'
                              : lintReport.tier === 'BRONZE'
                              ? 'bg-orange-800/20 text-orange-400 border border-orange-700/40'
                              : 'bg-rose-950/40 text-rose-400 border border-rose-800/40'
                          }`}
                        >
                          {lintReport.tier} TIER
                        </span>
                        <span className="text-xs font-semibold text-slate-200">
                          Lint Score: <span className="font-mono">{lintReport.score}</span>/100
                        </span>
                        <span
                          className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
                            lintReport.status === 'pass'
                              ? 'text-emerald-400 bg-emerald-500/10'
                              : lintReport.status === 'warning'
                              ? 'text-amber-400 bg-amber-500/10'
                              : 'text-rose-400 bg-rose-500/10'
                          }`}
                        >
                          {lintReport.status === 'pass'
                            ? '100% AES 1.4 Validated'
                            : lintReport.status === 'warning'
                            ? 'AES 1.4 Adherent (Advisory Warnings)'
                            : 'AES Schema / Spec Validation Errors'}
                        </span>
                      </div>
                      <span className="text-[10px] text-slate-500 font-mono">
                        target: {lintReport.file || 'scenario.json'}
                      </span>
                    </div>

                    {lintReport.errors && lintReport.errors.length > 0 && (
                      <div className="space-y-1 pt-1 border-t border-rose-500/20">
                        {lintReport.errors.map((err: string, idx: number) => (
                          <div key={idx} className="text-[11px] text-rose-400 flex items-center gap-1.5 font-mono">
                            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                            <span>{err}</span>
                          </div>
                        ))}
                      </div>
                    )}

                    {lintReport.warnings && lintReport.warnings.length > 0 && (
                      <div className="space-y-1 pt-1 border-t border-amber-500/20">
                        {lintReport.warnings.map((warn: string, idx: number) => (
                          <div key={idx} className="text-[11px] text-amber-400 flex items-center gap-1.5 font-mono">
                            <span className="text-amber-500 shrink-0">⚠️</span>
                            <span>{warn}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <div className="border border-slate-900 rounded-xl bg-slate-950 text-xs leading-relaxed overflow-x-auto overflow-y-auto flex-1">
                  <ReactDiffViewer
                  oldValue={
                    diffMode === 'prompt'
                      ? getScenarioText(canonicalBaseScenario || chosenScenario)
                      : JSON.stringify(canonicalBaseScenario || chosenScenario, null, 2)
                  }
                  newValue={
                    diffMode === 'prompt'
                      ? getScenarioText(mutatedJson)
                      : JSON.stringify(mutatedJson, null, 2)
                  }
                  splitView={splitView}
                  leftTitle="Baseline Scenario (Original Specification)"
                  rightTitle={`Mutated Scenario (+ Perturbations: ${selectedDescriptor?.label || mutationType})`}
                  useDarkTheme={true}
                  summary={
                    <span
                      title="Expand/Fold unchanged blocks. The number indicates total changed lines; colored blocks show additions (green) vs deletions (red) ratio."
                      className="text-[10px] text-slate-400 font-sans cursor-help flex items-center gap-1.5 ml-2"
                    >
                      <span className="text-slate-600 font-mono">|</span>
                      <span>Fold/Expand toggle &amp; line diff metrics (green=added, red=deleted)</span>
                    </span>
                  }
                  styles={{
                    variables: {
                      dark: {
                        diffViewerBackground: '#020617',
                        diffViewerColor: '#cbd5e1',
                        addedBackground: '#064e3b',
                        addedColor: '#34d399',
                        removedBackground: '#7f1d1d',
                        removedColor: '#f87171',
                        wordAddedBackground: '#047857',
                        wordRemovedBackground: '#991b1b',
                        diffViewerTitleBackground: '#0b1329',
                        diffViewerTitleColor: '#cbd5e1',
                        diffViewerTitleBorderColor: '#1e293b',
                      },
                    },
                    diffContainer: {
                      tableLayout: 'fixed',
                      width: '100%',
                      minWidth: wrapLines ? '100%' : (splitView ? '1200px' : '800px'),
                      overflowX: 'auto',
                    },
                    splitView: {
                      width: '100%',
                    },
                    content: {
                      width: splitView ? '50%' : '100%',
                      overflowX: 'visible',
                    },
                    titleBlock: {
                      width: splitView ? '50%' : '100%',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      padding: '6px 12px',
                      fontSize: '11px',
                      fontWeight: 600,
                    },
                    line: {
                      fontSize: '11px',
                      fontFamily: 'monospace',
                      lineHeight: '1.4',
                      whiteSpace: wrapLines ? 'pre-wrap' : 'pre',
                      wordBreak: wrapLines ? 'break-all' : 'normal',
                    },
                    contentText: {
                      whiteSpace: wrapLines ? 'pre-wrap' : 'pre',
                      wordBreak: wrapLines ? 'break-all' : 'normal',
                    },
                  }}
                />
              </div>
            </div>
          )}
          </div>

          {mutatedJson && (
            <div className="border-t border-slate-900/60 pt-4 mt-4">
              <button
                onClick={handleSaveMutant}
                disabled={saving}
                className="w-full py-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-xs font-bold rounded-lg transition-colors flex items-center justify-center gap-1.5"
              >
                <Save className="w-4 h-4" />
                <span>
                  {saving ? 'Saving Mutant Scenario...' : 'Save Mutated Copy to Scenario Library'}
                </span>
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
