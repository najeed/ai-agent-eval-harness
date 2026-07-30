import React, { useState, useEffect } from 'react';
import Editor from '@monaco-editor/react';
import { Layers, PlayCircle, Save, Check, Sparkles, Copy } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

interface ScenarioOption {
  id: string;
  name: string;
  industry: string;
  difficulty: string;
  raw_json?: any;
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

  const fetchScenarios = async () => {
    setLoadingScenarios(true);
    try {
      const res = await fetch('/api/scenarios');
      const data = await res.json();
      if (res.ok && data.scenarios) {
        setScenarios(data.scenarios);
        if (data.scenarios.length > 0) {
          setSelectedId(data.scenarios[0].id);
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingScenarios(false);
    }
  };

  useEffect(() => {
    fetchScenarios();
  }, []);

  const handleMutate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedId) return;

    setMutating(true);
    setError('');
    setMutatedJson(null);
    setSaveMsg('');

    // Fetch the scenario raw JSON first if not cached
    const chosen = scenarios.find((s) => s.id === selectedId);
    if (!chosen) return;

    try {
      // Direct raw JSON mutation query
      const res = await fetch('/api/v1/mutate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          raw_json: chosen.raw_json || chosen, // fallback to object structure
          type: mutationType
        })
      });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        setMutatedJson(data.mutated);
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

    // Assign a mutated unique ID to prevent namespace collisions
    const mutantCopy = {
      ...mutatedJson,
      id: `${mutatedJson.id || 'scenario'}_mutant_${mutationType}`
    };

    try {
      const res = await fetch('/api/scenarios', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mutantCopy)
      });
      const data = await res.json();
      if (res.ok) {
        setSaveMsg(`Scenario saved to Scenario Library as: ${mutantCopy.id}`);
        setTimeout(() => navigate('/scenarios'), 1500);
      } else {
        setError(data.error || 'Failed to save mutated scenario.');
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
            Generate fuzzing mutations, typos, and adversarial prompts for existing scenarios to test agent policy robustness.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Side: Mutator configurations Form */}
        <div className="space-y-6 lg:col-span-1">
          <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4">
            <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
              <Sparkles className="w-4 h-4 text-indigo-400" />
              <span>Mutation Parameters</span>
            </h3>

            {loadingScenarios ? (
              <div className="text-xs text-slate-500 italic py-4">Loading scenario choices...</div>
            ) : scenarios.length === 0 ? (
              <div className="text-xs text-rose-400 py-4">No scenarios available to mutate. Create a scenario first.</div>
            ) : (
              <form onSubmit={handleMutate} className="space-y-4">
                <div className="space-y-1">
                  <label className="text-[9px] text-slate-500 font-bold uppercase">Select Target Scenario</label>
                  <select
                    value={selectedId}
                    onChange={(e) => setSelectedId(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-xs text-slate-350 focus:outline-none focus:border-indigo-500 cursor-pointer"
                  >
                    {scenarios.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.id} ({s.industry})
                      </option>
                    ))}
                  </select>
                </div>

                <div className="space-y-1">
                  <label className="text-[9px] text-slate-500 font-bold uppercase">Mutation Strategy</label>
                  <select
                    value={mutationType}
                    onChange={(e) => setMutationType(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-xs text-slate-350 focus:outline-none focus:border-indigo-500 cursor-pointer"
                  >
                    <option value="typo">typo (simulate user keyboard noise)</option>
                    <option value="adversarial">adversarial (injection payloads)</option>
                    <option value="ambiguous">ambiguous (vague request inputs)</option>
                  </select>
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

        {/* Right Side: Mutated Scenario output in Monaco */}
        <div className="lg:col-span-2 bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4 flex flex-col justify-between">
          <div className="space-y-4 flex-1">
            <div className="flex justify-between items-center border-b border-slate-900/60 pb-3">
              <h3 className="text-xs font-bold text-white uppercase tracking-wider">Mutated Scenario Output</h3>
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
              <div className="p-3 bg-emerald-500/10 border border-emerald-500/25 rounded-lg text-emerald-400 text-xs">
                {saveMsg}
              </div>
            )}

            {mutating ? (
              <div className="h-[360px] flex flex-col justify-center items-center gap-3">
                <div className="w-6 h-6 border-3 border-indigo-500/20 border-t-indigo-500 rounded-full animate-spin" />
                <span className="text-xs text-slate-500">Injecting typos and fuzzing structures...</span>
              </div>
            ) : !mutatedJson ? (
              <div className="h-[360px] border border-dashed border-slate-900 rounded-xl flex items-center justify-center text-xs text-slate-700 italic">
                Select a scenario and trigger mutations to display outputs.
              </div>
            ) : (
              <div className="h-[360px] border border-slate-900 rounded-xl overflow-hidden bg-slate-950">
                <Editor
                  height="100%"
                  defaultLanguage="json"
                  theme="vs-dark"
                  value={JSON.stringify(mutatedJson, null, 2)}
                  options={{
                    readOnly: true,
                    minimap: { enabled: false },
                    fontSize: 11,
                    lineNumbers: 'on',
                    scrollBeyondLastLine: false,
                    automaticLayout: true,
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
                <span>{saving ? 'Saving Mutant Scenario...' : 'Save Mutated Copy as New Scenario'}</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
