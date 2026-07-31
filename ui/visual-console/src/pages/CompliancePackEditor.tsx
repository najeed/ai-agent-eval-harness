import React, { useState, useEffect } from 'react';
import { ShieldCheck, Plus, Save, Send, Eye, Trash2 } from 'lucide-react';

interface CheckRule {
  type: string;
  params: {
    dimension?: string;
    min_score?: number;
    min_confidence?: number;
    judge_name?: string;
    required_rubrics?: string[];
  };
}

interface CompliancePack {
  id: string;
  name: string;
  description: string;
  applicable_industries: string[];
  version: number;
  checks: CheckRule[];
  last_updated?: string;
}

interface RunOption {
  run_id: string;
  scenario: string;
  timestamp: string;
}

export const CompliancePackEditor: React.FC = () => {
  const [packs, setPacks] = useState<CompliancePack[]>([]);
  const [selectedPack, setSelectedPack] = useState<CompliancePack | null>(null);
  const [loadingPacks, setLoadingPacks] = useState(false);
  const [runs, setRuns] = useState<RunOption[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>('');

  // Form State
  const [packName, setPackName] = useState('');
  const [packDesc, setPackDesc] = useState('');
  const [packIndustries, setPackIndustries] = useState<string[]>([]);
  const [checks, setChecks] = useState<CheckRule[]>([]);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);

  // Test Evaluation Results
  const [testing, setTesting] = useState(false);
  const [testResults, setTestResults] = useState<any>(null);

  const loadPacks = async () => {
    setLoadingPacks(true);
    try {
      const res = await fetch('/api/v1/compliance-packs');
      if (res.ok) {
        const data = await res.json();
        setPacks(data.packs || []);
        if (data.packs && data.packs.length > 0 && !selectedPack) {
          handleSelectPack(data.packs[0]);
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingPacks(false);
    }
  };

  const loadRuns = async () => {
    try {
      const res = await fetch('/api/runs');
      if (res.ok) {
        const data = await res.json();
        setRuns(data.runs || []);
        if (data.runs && data.runs.length > 0) {
          setSelectedRunId(data.runs[0].run_id);
        }
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    loadPacks();
    loadRuns();
  }, []);

  const handleSelectPack = (pack: CompliancePack) => {
    setSelectedPack(pack);
    setPackName(pack.name);
    setPackDesc(pack.description);
    setPackIndustries(pack.applicable_industries || []);
    setChecks(pack.checks || []);
    setTestResults(null);
  };

  const handleCreateNewPack = () => {
    const newPack: CompliancePack = {
      id: `custom_${Math.random().toString(36).substr(2, 9)}`,
      name: 'Custom Compliance Pack',
      description: 'Define audit rules for standard and custom policy checks.',
      applicable_industries: ['Finance'],
      version: 1,
      checks: [
        { type: 'pqc_required', params: {} }
      ]
    };
    setSelectedPack(newPack);
    setPackName(newPack.name);
    setPackDesc(newPack.description);
    setPackIndustries(newPack.applicable_industries);
    setChecks(newPack.checks);
    setTestResults(null);
  };

  const handleAddRule = () => {
    setChecks([...checks, { type: 'wsm_threshold', params: { dimension: 'security', min_score: 0.85 } }]);
  };

  const handleRemoveRule = (index: number) => {
    setChecks(checks.filter((_, i) => i !== index));
  };

  const handleRuleChange = (index: number, field: string, value: any) => {
    const updated = [...checks];
    if (field === 'type') {
      updated[index].type = value;
      if (value === 'pqc_required') {
        updated[index].params = {};
      } else if (value === 'wsm_threshold') {
        updated[index].params = { dimension: 'security', min_score: 0.85 };
      } else if (value === 'rubric_required') {
        updated[index].params = { dimension: 'safety', min_confidence: 0.80 };
      } else if (value === 'independent_judge') {
        updated[index].params = { judge_name: 'Claude-3.5-Sonnet', min_score: 0.90 };
      }
    } else {
      updated[index].params = {
        ...updated[index].params,
        [field]: value
      };
    }
    setChecks(updated);
  };

  const handleSavePack = async () => {
    if (!selectedPack) return;
    setSaving(true);
    try {
      const res = await fetch('/api/v1/compliance-packs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: selectedPack.id,
          name: packName,
          description: packDesc,
          applicable_industries: packIndustries,
          checks: checks
        })
      });
      if (res.ok) {
        await res.json();
        loadPacks();
        window.dispatchEvent(new CustomEvent('agentv-toast', {
          detail: { message: 'Compliance Pack saved successfully!', type: 'success' }
        }));
      }
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  const handlePublishPack = async () => {
    if (!selectedPack) return;
    setPublishing(true);
    try {
      const res = await fetch(`/api/v1/compliance-packs/${selectedPack.id}/publish`, {
        method: 'POST'
      });
      if (res.ok) {
        window.dispatchEvent(new CustomEvent('agentv-toast', {
          detail: { message: 'Compliance Pack published successfully!', type: 'success' }
        }));
        loadPacks();
      }
    } catch (e) {
      console.error(e);
    } finally {
      setPublishing(false);
    }
  };

  const handleTestPack = async () => {
    if (!selectedPack || !selectedRunId) return;
    setTesting(true);
    setTestResults(null);
    try {
      const res = await fetch(`/api/v1/compliance-packs/${selectedPack.id}/test?run_id=${selectedRunId}`, {
        method: 'POST'
      });
      if (res.ok) {
        const data = await res.json();
        setTestResults(data);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6 text-slate-200">
      {/* Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-slate-900 pb-5">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-indigo-400" />
            <h1 className="text-lg font-bold text-white uppercase tracking-wider">Compliance Packs & Rules Editor</h1>
          </div>
          <p className="text-xs text-slate-500">Formulate and test standard audit rules (NIST AI RMF, EU AI Act) against historical evaluation logs.</p>
        </div>
        <button
          onClick={handleCreateNewPack}
          className="flex items-center gap-2 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700 text-white rounded text-xs font-bold uppercase tracking-wider transition-all"
        >
          <Plus className="w-4 h-4" />
          <span>New Custom Pack</span>
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Left Sidebar: Standard Packs List */}
        <div className="space-y-4">
          <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4">
            <h2 className="text-xs font-bold text-slate-400 uppercase tracking-wider">Standard Rules Packs</h2>
            {loadingPacks ? (
              <div className="py-6 flex justify-center"><div className="w-5 h-5 border-2 border-indigo-500/25 border-t-indigo-500 rounded-full animate-spin" /></div>
            ) : (
              <div className="space-y-2">
                {packs.map(p => {
                  const isSelected = selectedPack?.id === p.id;
                  return (
                    <button
                      key={p.id}
                      onClick={() => handleSelectPack(p)}
                      className={`w-full text-left p-3 rounded-lg border text-xs transition-all flex flex-col space-y-1 ${
                        isSelected 
                          ? 'bg-indigo-500/5 border-indigo-500/30 text-indigo-300' 
                          : 'bg-slate-900/30 border-slate-900/60 hover:bg-slate-900/50 text-slate-350'
                      }`}
                    >
                      <span className="font-bold text-slate-200">{p.name}</span>
                      <span className="text-[10px] text-slate-500 truncate max-w-[200px]">{p.description}</span>
                      <span className="text-[9px] text-indigo-400 font-bold uppercase tracking-wider pt-1">Version {p.version}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Center: Rules Builder Form */}
        <div className="lg:col-span-2 space-y-4">
          {selectedPack && (
            <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-6 space-y-5">
              <div className="space-y-3 pb-3 border-b border-slate-900">
                <div className="flex justify-between items-start">
                  <h2 className="text-sm font-bold text-white uppercase tracking-wider">Edit Pack Configuration</h2>
                  <span className="px-2 py-0.5 bg-slate-900 border border-slate-800 text-indigo-400 text-[9px] font-bold uppercase rounded font-mono">
                    ID: {selectedPack.id}
                  </span>
                </div>
                <div className="space-y-3">
                  <div className="space-y-1">
                    <label className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Pack Name:</label>
                    <input
                      type="text"
                      value={packName}
                      onChange={(e) => setPackName(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-900 hover:border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-250 focus:outline-none focus:border-indigo-500 font-sans"
                    />
                  </div>
                  <div className="space-y-1">
                    <label className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Description:</label>
                    <textarea
                      value={packDesc}
                      onChange={(e) => setPackDesc(e.target.value)}
                      rows={2}
                      className="w-full bg-slate-950 border border-slate-900 hover:border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-250 focus:outline-none focus:border-indigo-500 font-sans resize-none"
                    />
                  </div>
                </div>
              </div>

              {/* Checks Rules Builder */}
              <div className="space-y-3">
                <div className="flex justify-between items-center">
                  <span className="text-[10px] text-slate-400 font-bold uppercase tracking-wider">Rule Checks ({checks.length})</span>
                  <button
                    onClick={handleAddRule}
                    className="flex items-center gap-1 px-2.5 py-1 bg-slate-900 hover:bg-slate-800 text-indigo-400 border border-slate-800 rounded text-[10px] font-bold uppercase tracking-wider transition-colors"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>Add Check Rule</span>
                  </button>
                </div>

                <div className="space-y-3">
                  {checks.map((rule, idx) => (
                    <div key={idx} className="p-4 bg-slate-950 border border-slate-900 rounded-lg space-y-3 text-[11px] relative">
                      <button
                        onClick={() => handleRemoveRule(idx)}
                        className="absolute top-3 right-3 text-slate-600 hover:text-rose-400 transition-colors"
                        title="Delete Rule"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>

                      <div className="grid grid-cols-2 gap-3 pr-8">
                        <div className="space-y-1">
                          <label className="text-[9px] text-slate-500 font-bold uppercase tracking-wider">Rule Type</label>
                          <select
                            value={rule.type}
                            onChange={(e) => handleRuleChange(idx, 'type', e.target.value)}
                            className="w-full bg-slate-900 border border-slate-850 rounded px-2 py-1 text-xs text-slate-300 focus:outline-none"
                          >
                            <option value="pqc_required">PQC Required (Quantum Signing)</option>
                            <option value="wsm_threshold">WSM Dimension Threshold</option>
                            <option value="rubric_required">LLM Rubric Confidence</option>
                            <option value="independent_judge">Independent Judge Verdict</option>
                          </select>
                        </div>

                        {rule.type === 'wsm_threshold' && (
                          <div className="space-y-1">
                            <label className="text-[9px] text-slate-500 font-bold uppercase tracking-wider">Dimension</label>
                            <select
                              value={rule.params.dimension || 'security'}
                              onChange={(e) => handleRuleChange(idx, 'dimension', e.target.value)}
                              className="w-full bg-slate-900 border border-slate-850 rounded px-2 py-1 text-xs text-slate-300 focus:outline-none"
                            >
                              <option value="safety">Safety</option>
                              <option value="security">Security</option>
                              <option value="reliability">Reliability</option>
                              <option value="privacy">Privacy</option>
                              <option value="transparency">Transparency</option>
                            </select>
                          </div>
                        )}

                        {rule.type === 'rubric_required' && (
                          <div className="space-y-1">
                            <label className="text-[9px] text-slate-500 font-bold uppercase tracking-wider">Dimension</label>
                            <select
                              value={rule.params.dimension || 'safety'}
                              onChange={(e) => handleRuleChange(idx, 'dimension', e.target.value)}
                              className="w-full bg-slate-900 border border-slate-850 rounded px-2 py-1 text-xs text-slate-300 focus:outline-none"
                            >
                              <option value="safety">Safety</option>
                              <option value="security">Security</option>
                            </select>
                          </div>
                        )}

                        {rule.type === 'independent_judge' && (
                          <div className="space-y-1">
                            <label className="text-[9px] text-slate-500 font-bold uppercase tracking-wider">Judge Model Name</label>
                            <input
                              type="text"
                              value={rule.params.judge_name || 'Claude-3.5-Sonnet'}
                              onChange={(e) => handleRuleChange(idx, 'judge_name', e.target.value)}
                              className="w-full bg-slate-900 border border-slate-850 rounded px-2 py-1 text-xs text-slate-300 focus:outline-none"
                            />
                          </div>
                        )}
                      </div>

                      {/* Score Fields */}
                      {(rule.type === 'wsm_threshold' || rule.type === 'independent_judge') && (
                        <div className="w-1/2 space-y-1">
                          <label className="text-[9px] text-slate-500 font-bold uppercase tracking-wider">Min Score Value ({rule.params.min_score || 0.85})</label>
                          <input
                            type="range"
                            min="0.1"
                            max="1.0"
                            step="0.05"
                            value={rule.params.min_score || 0.85}
                            onChange={(e) => handleRuleChange(idx, 'min_score', parseFloat(e.target.value))}
                            className="w-full h-1 bg-slate-900 rounded-lg appearance-none cursor-pointer accent-indigo-500"
                          />
                        </div>
                      )}

                      {rule.type === 'rubric_required' && (
                        <div className="w-1/2 space-y-1">
                          <label className="text-[9px] text-slate-500 font-bold uppercase tracking-wider">Min Confidence Threshold ({rule.params.min_confidence || 0.80})</label>
                          <input
                            type="range"
                            min="0.1"
                            max="1.0"
                            step="0.05"
                            value={rule.params.min_confidence || 0.80}
                            onChange={(e) => handleRuleChange(idx, 'min_confidence', parseFloat(e.target.value))}
                            className="w-full h-1 bg-slate-900 rounded-lg appearance-none cursor-pointer accent-indigo-500"
                          />
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* Form Action Buttons */}
              <div className="pt-4 border-t border-slate-900 flex gap-3 justify-end">
                <button
                  onClick={handleSavePack}
                  disabled={saving}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-900 hover:bg-slate-850 text-indigo-400 border border-slate-800 rounded text-xs font-bold uppercase tracking-wider transition-colors"
                >
                  <Save className="w-4 h-4" />
                  <span>{saving ? 'Saving...' : 'Save Pack'}</span>
                </button>
                <button
                  onClick={handlePublishPack}
                  disabled={publishing}
                  className="flex items-center gap-1.5 px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700 text-white rounded text-xs font-bold uppercase tracking-wider transition-all"
                >
                  <Send className="w-4 h-4" />
                  <span>{publishing ? 'Publishing...' : 'Publish & Register'}</span>
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Right Sidebar: Historical Run Previewer */}
        <div className="space-y-4">
          <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4">
            <h2 className="text-xs font-bold text-slate-400 uppercase tracking-wider">Compliance Auditor Simulator</h2>
            <p className="text-[10px] text-slate-500 leading-relaxed">
              Verify compliance rules on historical run trajectories. Select a target run and trigger audit checks.
            </p>

            <div className="space-y-3">
              <div className="space-y-1">
                <label className="text-[9px] text-slate-500 font-bold uppercase tracking-wider">Target Historical Run:</label>
                <select
                  value={selectedRunId}
                  onChange={(e) => setSelectedRunId(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-900 rounded px-2 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-indigo-500 font-mono"
                >
                  {runs.map(r => (
                    <option key={r.run_id} value={r.run_id}>{r.run_id}</option>
                  ))}
                </select>
              </div>

              <button
                onClick={handleTestPack}
                disabled={testing || !selectedPack || !selectedRunId}
                className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-cyan-600 hover:bg-cyan-500 active:bg-cyan-700 text-white rounded text-xs font-bold uppercase tracking-wider transition-all"
              >
                <Eye className="w-4 h-4" />
                <span>{testing ? 'Auditing...' : 'Evaluate Pack'}</span>
              </button>
            </div>

            {testResults && (
              <div className="pt-4 border-t border-slate-900 space-y-4 animate-scale-in">
                <div className="p-3.5 bg-slate-900/60 border border-slate-850 rounded-lg space-y-1 text-xs">
                  <div className="flex justify-between items-center text-[10px] text-slate-500 uppercase tracking-wider font-bold">
                    <span>Audit Status</span>
                    <span>Score Verdict</span>
                  </div>
                  <div className="flex justify-between items-center font-bold">
                    <span>Suite Compliance:</span>
                    {testResults.compliance === 'PASS' ? (
                      <span className="text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded text-[10px] tracking-wider uppercase">COMPLIANT</span>
                    ) : (
                      <span className="text-rose-400 bg-rose-500/10 border border-rose-500/20 px-2 py-0.5 rounded text-[10px] tracking-wider uppercase">NON-COMPLIANT</span>
                    )}
                  </div>
                </div>

                <div className="space-y-2">
                  <span className="text-[9px] text-slate-500 font-bold uppercase tracking-wider">Rule Verification Logs:</span>
                  <div className="space-y-2 max-h-[220px] overflow-y-auto pr-1">
                    {testResults.results?.map((res: any, idx: number) => (
                      <div key={idx} className="p-2.5 bg-slate-950 border border-slate-900 rounded text-[10px] space-y-1">
                        <div className="flex justify-between items-center font-bold uppercase">
                          <span className="text-slate-400 truncate max-w-[120px]">{res.type}</span>
                          {res.status === 'PASS' ? (
                            <span className="text-emerald-400 font-bold">PASS</span>
                          ) : (
                            <span className="text-rose-450 font-bold">FAIL</span>
                          )}
                        </div>
                        <p className="text-slate-500 leading-normal">{res.details}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
