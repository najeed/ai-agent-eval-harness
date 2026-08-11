import React, { useState, useEffect } from 'react';
import ReactDiffViewer from 'react-diff-viewer-continued';
import { Layers, PlayCircle, Save, Check, Sparkles, Copy, ArrowRight, HelpCircle } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

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
  const [mutationType, setMutationType] = useState('typo');
  const [loadingScenarios, setLoadingScenarios] = useState(false);

  const [mutating, setMutating] = useState(false);
  const [mutatedJson, setMutatedJson] = useState<any>(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [copied, setCopied] = useState(false);

  // Search & Filter state
  const [industryFilter, setIndustryFilter] = useState('All');
  const [searchTerm, setSearchTerm] = useState('');

  const fetchScenarios = async () => {
    setLoadingScenarios(true);
    try {
      const res = await fetch('/api/scenarios');
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
    fetchScenarios();
  }, []);

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
    if (!selectedId) return;

    setMutating(true);
    setError('');
    setMutatedJson(null);
    setSaveMsg('');

    try {
      const res = await fetch('/api/v1/mutate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scenario_id: selectedId,
          type: mutationType
        })
      });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        setMutatedJson(data.mutated);
        window.dispatchEvent(new CustomEvent('agentv-toast', {
          detail: { message: `Adversarial mutation (${mutationType}) executed.`, type: 'success' }
        }));
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

    // Ensure parent reference is linked to prevent orphaned mutants
    const mutantCopy = {
      ...mutatedJson,
      metadata: {
        ...(mutatedJson.metadata || {}),
        parent_scenario_id: selectedId
      }
    };

    try {
      const res = await fetch('/api/scenarios', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mutantCopy)
      });
      if (res.ok) {
        setSaveMsg(`Mutated scenario saved to library: ${mutantCopy.id}`);
        window.dispatchEvent(new CustomEvent('agentv-toast', {
          detail: { message: 'Mutated scenario successfully saved!', type: 'success' }
        }));
        setTimeout(() => navigate('/scenarios'), 1500);
      } else {
        const errData = await res.json();
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

  const getScenarioText = (sc: ScenarioOption | null) => {
    if (!sc) return '';
    let text = `Scenario ID: ${sc.metadata?.id || sc.id}\n`;
    text += `Title: ${sc.metadata?.name || sc.title || ''}\n`;
    text += `Description: ${sc.metadata?.description || sc.description || ''}\n\n`;
    
    if (sc.workflow?.nodes) {
      sc.workflow.nodes.forEach((n) => {
        text += `[Node ID: ${n.id}]\n`;
        text += `Task Description:\n${n.task_description || ''}\n\n`;
      });
    }
    return text;
  };

  const chosenScenario = scenarios.find((s) => s.id === selectedId) || null;

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-slate-900 pb-5">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Layers className="w-5 h-5 text-indigo-400" />
            <span>Adversarial Scenario Mutator</span>
          </h1>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            Test policy stability limits. Mutate workflow prompts with typographical errors, vagueness hedging, or prompt injections.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
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
              <div className="text-xs text-rose-400 py-4">No scenarios available to mutate. Create a scenario first.</div>
            ) : (
              <form onSubmit={handleMutate} className="space-y-4">
                <div className="space-y-3 p-3 bg-slate-950/40 border border-slate-900 rounded-lg">
                  <span className="text-[9px] text-slate-500 font-bold uppercase font-mono">Filters (5000+ available)</span>
                  
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
                      {industries.map(ind => (
                        <option key={ind} value={ind}>{ind === 'All' ? 'All Sectors' : ind.replace(/_/g, ' ')}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="space-y-1.5">
                  <label className="text-[9px] text-slate-500 font-bold uppercase font-mono">Target Base Scenario ({filteredOptions.length} matching)</label>
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

                <div className="space-y-1.5">
                  <label className="text-[9px] text-slate-500 font-bold uppercase font-mono">Mutation Strategy</label>
                  <select
                    value={mutationType}
                    onChange={(e) => setMutationType(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-indigo-500 cursor-pointer"
                  >
                    <option value="typo">Typo (character errors)</option>
                    <option value="ambiguity">Ambiguity (hedging/vague statements)</option>
                    <option value="injection">Injection (prompt override attempts)</option>
                  </select>
                </div>

                {/* Strategy Descriptions */}
                <div className="p-3 bg-slate-950/80 border border-slate-850 rounded-lg space-y-1">
                  <span className="text-[9px] text-slate-500 font-bold uppercase font-mono flex items-center gap-1">
                    <HelpCircle className="w-3.5 h-3.5 text-indigo-400" />
                    <span>Strategy Details</span>
                  </span>
                  <p className="text-[10px] text-slate-400 leading-relaxed">
                    {mutationType === 'typo' && 'Injects keyboard slip errors and spelling mutations into the task prompt.'}
                    {mutationType === 'ambiguity' && 'Appends vague, non-committal hedging clauses requesting permission.'}
                    {mutationType === 'injection' && 'Appends instructions to bypass prompt systems and override boundaries.'}
                  </p>
                </div>

                <button
                  type="submit"
                  disabled={mutating || !selectedId}
                  className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-xs font-bold rounded-lg transition-colors flex items-center justify-center gap-1.5"
                >
                  <PlayCircle className="w-4 h-4" />
                  <span>{mutating ? 'Executing Mutator...' : 'Execute Mutation Engine'}</span>
                </button>
              </form>
            )}
          </div>
        </div>

        {/* Right column: Comparative Diff & Save action */}
        <div className="lg:col-span-2 bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4 flex flex-col justify-between">
          <div className="space-y-4 flex-1">
            <div className="flex justify-between items-center border-b border-slate-900/60 pb-3">
              <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1">
                <span>Scenario State Attribution Diff</span>
                {mutatedJson && (
                  <span className="text-[9px] text-slate-500 font-mono flex items-center gap-1 lowercase">
                    ({selectedId} <ArrowRight className="w-3 h-3" /> {mutatedJson.id})
                  </span>
                )}
              </h3>
              {mutatedJson && (
                <button
                  onClick={handleCopy}
                  className="flex items-center gap-1 px-2.5 py-1 bg-slate-900 hover:bg-slate-850 border border-slate-800 rounded text-[10px] font-bold text-slate-300 hover:text-white transition-colors"
                >
                  {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                  <span>{copied ? 'Copied' : 'Copy JSON'}</span>
                </button>
              )}
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
              <div className="h-[360px] flex flex-col justify-center items-center gap-3">
                <div className="w-6 h-6 border-2 border-indigo-500/20 border-t-indigo-500 rounded-full animate-spin" />
                <span className="text-xs text-slate-500">Injecting adversarial states...</span>
              </div>
            ) : !mutatedJson ? (
              <div className="h-[360px] border border-dashed border-slate-900 rounded-xl flex items-center justify-center text-xs text-slate-700 italic">
                Select parameters and trigger mutator execution to preview comparative state diffs.
              </div>
            ) : (
              <div className="border border-slate-900 rounded-xl overflow-hidden bg-slate-950 text-xs leading-relaxed max-h-[380px] overflow-y-auto">
                <ReactDiffViewer
                  oldValue={getScenarioText(chosenScenario)}
                  newValue={getScenarioText(mutatedJson)}
                  splitView={true}
                  leftTitle="Base Scenario"
                  rightTitle={`Mutated Scenario (${mutationType})`}
                  useDarkTheme={true}
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
                      }
                    },
                    line: {
                      fontSize: '11px',
                      fontFamily: 'monospace',
                      lineHeight: '1.4'
                    }
                  }}
                />
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
                <span>{saving ? 'Saving Mutant Scenario...' : 'Save Mutated Copy to Scenario Library'}</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
