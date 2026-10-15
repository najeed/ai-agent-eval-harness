import React, { useState, useEffect } from 'react';
import { Cpu, ShieldCheck, CheckCircle2, AlertTriangle, FileArchive, Download, Upload, Plus } from 'lucide-react';

interface Suite {
  suite_id: string;
  name: string;
  agent_name: string;
  created_by: string;
  created_at: string;
  run_ids: string[];
  zip_file?: string;
  manifest_file?: string;
}

interface RunOption {
  run_id: string;
  scenario: string;
  timestamp: string;
}

export const RegressionSuites: React.FC = () => {
  const [suites, setSuites] = useState<Suite[]>([]);
  const [selectedSuite, setSelectedSuite] = useState<Suite | null>(null);
  const [loadingSuites, setLoadingSuites] = useState(false);
  const [runs, setRuns] = useState<RunOption[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);

  // New Suite Form
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newName, setNewName] = useState('');
  const [newAgent, setNewAgent] = useState('Verified-Agent-v3');
  const [selectedRuns, setSelectedRuns] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);

  // Bundler Actions
  const [bundling, setBundling] = useState(false);

  // Auditor Verification
  const [verifyFile, setVerifyFile] = useState<File | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState<any>(null);

  // Load Saved Suites
  const loadSuites = async () => {
    setLoadingSuites(true);
    try {
      const res = await fetch('/api/v1/suites');
      if (res.ok) {
        const data = await res.json();
        setSuites(data.suites || []);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingSuites(false);
    }
  };

  // Load Runs List
  const loadRuns = async () => {
    setLoadingRuns(true);
    try {
      const res = await fetch('/api/runs');
      if (res.ok) {
        const data = await res.json();
        setRuns(data.runs || []);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingRuns(false);
    }
  };

  useEffect(() => {
    loadSuites();
    loadRuns();
  }, []);

  const handleCreateSuite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName || !newAgent || selectedRuns.length === 0) return;
    setCreating(true);
    try {
      const res = await fetch('/api/v1/suites', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newName,
          agent_name: newAgent,
          run_ids: selectedRuns
        })
      });
      if (res.ok) {
        setNewName('');
        setSelectedRuns([]);
        setShowCreateModal(false);
        loadSuites();
      }
    } catch (e) {
      console.error(e);
    } finally {
      setCreating(false);
    }
  };

  const handleBundleSuite = async (suiteId: string) => {
    setBundling(true);
    try {
      const res = await fetch(`/api/v1/suites/${suiteId}/bundle`, {
        method: 'POST'
      });
      if (res.ok) {
        const data = await res.json();
        loadSuites();
        // Update selected suite instance to show download button
        if (selectedSuite && selectedSuite.suite_id === suiteId) {
          setSelectedSuite(prev => prev ? { ...prev, zip_file: data.zip_file } : null);
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      setBundling(false);
    }
  };

  const handleVerifyBundle = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!verifyFile) return;
    setVerifying(true);
    setVerifyResult(null);
    const formData = new FormData();
    formData.append('file', verifyFile);
    try {
      const res = await fetch('/api/v1/bundles/verify', {
        method: 'POST',
        body: formData
      });
      if (res.ok) {
        const data = await res.json();
        setVerifyResult(data);
      } else {
        setVerifyResult({ status: 'error', message: 'Failed to verify manifest' });
      }
    } catch (e: any) {
      setVerifyResult({ status: 'error', message: e.message });
    } finally {
      setVerifying(false);
    }
  };

  const handleSelectRun = (runId: string) => {
    setSelectedRuns(prev => 
      prev.includes(runId) ? prev.filter(r => r !== runId) : [...prev, runId]
    );
  };

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6 text-slate-200">
      {/* Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-slate-900 pb-5">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Cpu className="w-5 h-5 text-indigo-400" />
            <h1 className="text-lg font-bold text-white uppercase tracking-wider">Regression Suites & Bundler</h1>
          </div>
          <p className="text-xs text-slate-500">Collect evaluations, compile compliance records, and export signed packages for auditing.</p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-2 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700 text-white rounded text-xs font-bold uppercase tracking-wider transition-all"
        >
          <Plus className="w-4 h-4" />
          <span>Assemble New Suite</span>
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Panel: Saved Suites */}
        <div className="lg:col-span-2 space-y-4">
          <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4">
            <h2 className="text-xs font-bold text-slate-400 uppercase tracking-wider">Suite Library</h2>
            {loadingSuites ? (
              <div className="py-12 flex justify-center"><div className="w-6 h-6 border-2 border-indigo-500/25 border-t-indigo-500 rounded-full animate-spin" /></div>
            ) : suites.length === 0 ? (
              <p className="text-xs text-slate-500 italic py-6 text-center">No regression suites registered. Assemble one to begin.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left border-collapse">
                  <thead>
                    <tr className="border-b border-slate-900 text-slate-500 text-[10px] uppercase font-bold tracking-wider">
                      <th className="py-2.5">Name</th>
                      <th>Target Agent</th>
                      <th>Member Runs</th>
                      <th>Created</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {suites.map(s => {
                      const isSelected = selectedSuite?.suite_id === s.suite_id;
                      return (
                        <tr
                          key={s.suite_id}
                          onClick={() => { setSelectedSuite(s); }}
                          className={`border-b border-slate-900/60 hover:bg-slate-900/20 cursor-pointer transition-colors ${
                            isSelected ? 'bg-indigo-500/5 text-indigo-300' : ''
                          }`}
                        >
                          <td className="py-3 font-semibold text-slate-200">{s.name}</td>
                          <td className="font-mono text-slate-400">{s.agent_name}</td>
                          <td className="font-semibold">{s.run_ids.length} traces</td>
                          <td className="text-slate-500">{new Date(s.created_at).toLocaleDateString()}</td>
                          <td>
                            {s.zip_file ? (
                              <span className="px-2 py-0.5 bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded text-[9px] font-bold uppercase tracking-wider">
                                BUNDLED
                              </span>
                            ) : (
                              <span className="px-2 py-0.5 bg-slate-500/10 text-slate-400 border border-slate-900 rounded text-[9px] font-bold uppercase tracking-wider">
                                UNBUNDLED
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Verification Portal */}
          <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4">
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-cyan-400" />
              <h2 className="text-xs font-bold text-slate-400 uppercase tracking-wider">Auditor Verification Portal</h2>
            </div>
            <p className="text-[11px] text-slate-500 leading-relaxed">
              Verify the cryptographic signature and hash chains of a suite manifest (`audit_manifest.json`) dynamic package.
            </p>
            <form onSubmit={handleVerifyBundle} className="flex flex-col sm:flex-row gap-3">
              <input
                type="file"
                accept=".json"
                onChange={(e) => setVerifyFile(e.target.files?.[0] || null)}
                className="flex-1 bg-slate-950 border border-slate-900 hover:border-slate-800 rounded px-3 py-1.5 text-xs text-slate-400 focus:outline-none focus:border-indigo-500"
              />
              <button
                type="submit"
                disabled={verifying || !verifyFile}
                className="flex items-center justify-center gap-2 px-4 py-1.5 bg-cyan-600 hover:bg-cyan-500 active:bg-cyan-700 disabled:bg-slate-900 disabled:text-slate-600 text-white rounded text-xs font-bold uppercase tracking-wider transition-all"
              >
                <Upload className="w-3.5 h-3.5" />
                <span>{verifying ? 'Verifying...' : 'Verify Manifest'}</span>
              </button>
            </form>

            {verifyResult && (
              <div className={`p-4 border rounded-lg text-xs space-y-2 ${
                verifyResult.status === 'success' ? 'bg-emerald-500/5 border-emerald-500/20 text-slate-300' : 'bg-red-500/5 border-red-500/20 text-red-400'
              }`}>
                <div className="flex items-center gap-2 font-bold uppercase tracking-wider text-[10px]">
                  {verifyResult.status === 'success' ? (
                    <>
                      <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                      <span className="text-emerald-400">Signature Valid (Ed25519)</span>
                    </>
                  ) : (
                    <>
                      <AlertTriangle className="w-4 h-4 text-red-400" />
                      <span className="text-red-400">Verification Failure</span>
                    </>
                  )}
                </div>
                {verifyResult.status === 'success' ? (
                  <div className="space-y-1 font-mono text-[10px]">
                    <p>Signature status: Integrity checks verified successfully.</p>
                    <p>Verified signer public key: {verifyResult.public_key?.substring(0, 24)}...</p>
                    <p>Checked files: {verifyResult.results?.length || 0} items verified.</p>
                  </div>
                ) : (
                  <p>{verifyResult.message || 'The manifest failed hash integrity validation.'}</p>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Right Panel: Selected Suite Details */}
        <div className="space-y-4">
          <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4 min-h-[400px] flex flex-col">
            <h2 className="text-xs font-bold text-slate-400 uppercase tracking-wider">Suite Details</h2>
            {!selectedSuite ? (
              <div className="flex-1 flex flex-col justify-center items-center text-slate-500 italic text-xs py-12">
                Select a suite from the library to inspect details and bundle artifacts.
              </div>
            ) : (
              <div className="flex-1 flex flex-col space-y-4">
                <div className="space-y-1 pb-3 border-b border-slate-900">
                  <h3 className="text-sm font-bold text-white leading-normal">{selectedSuite.name}</h3>
                  <div className="text-[10px] text-slate-500 font-mono flex flex-col space-y-0.5">
                    <span>Agent: {selectedSuite.agent_name}</span>
                    <span>Created: {new Date(selectedSuite.created_at).toLocaleString()}</span>
                  </div>
                </div>

                <div className="space-y-2 flex-1">
                  <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Included Evaluation Runs:</span>
                  <div className="max-h-[180px] overflow-y-auto space-y-1.5 border border-slate-900 rounded p-2.5 bg-slate-950/30 font-mono text-[11px] text-slate-350">
                    {selectedSuite.run_ids.map(rid => (
                      <div key={rid} className="flex justify-between items-center bg-slate-900/40 px-2 py-1 rounded">
                        <span className="truncate max-w-[180px]" title={rid}>{rid}</span>
                        <span className="text-[9px] text-emerald-400 font-bold">VERIFIED</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Staging & Bundle Actions */}
                <div className="pt-4 border-t border-slate-900 space-y-3 mt-auto">
                  {selectedSuite.zip_file ? (
                    <div className="space-y-2">
                      <div className="p-3 bg-emerald-500/5 border border-emerald-500/20 rounded-lg flex items-start gap-2.5 text-xs text-emerald-400">
                        <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" />
                        <div className="space-y-0.5">
                          <p className="font-bold uppercase tracking-wider text-[10px]">Bundle Deliverable Ready</p>
                          <p className="text-[10px] text-slate-400">Ed25519 signature manifest and companion PDF built successfully.</p>
                        </div>
                      </div>
                      <a
                        href={`/api/v1/suites/${selectedSuite.suite_id}/download`}
                        className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-white rounded text-xs font-bold uppercase tracking-wider transition-all"
                      >
                        <Download className="w-4 h-4" />
                        <span>Download ZIP Package</span>
                      </a>
                    </div>
                  ) : (
                    <button
                      onClick={() => handleBundleSuite(selectedSuite.suite_id)}
                      disabled={bundling}
                      className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700 disabled:bg-slate-900 disabled:text-slate-600 text-white rounded text-xs font-bold uppercase tracking-wider transition-all"
                    >
                      <FileArchive className="w-4 h-4" />
                      <span>{bundling ? 'Generating Bundle...' : 'Bundle for Audit'}</span>
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Assemble Suite Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg bg-navy-base border border-slate-900 rounded-xl shadow-2xl p-6 space-y-4 animate-scale-in text-xs text-slate-200">
            <h3 className="text-sm font-bold text-white uppercase tracking-wider border-b border-slate-900 pb-3">Assemble Regression Suite</h3>
            <form onSubmit={handleCreateSuite} className="space-y-4">
              <div className="space-y-1">
                <label className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Suite Title:</label>
                <input
                  type="text"
                  placeholder="e.g. Q3 Compliance Regression Set"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-900 hover:border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-250 focus:outline-none focus:border-indigo-500"
                  required
                />
              </div>

              <div className="space-y-1">
                <label className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Target Agent ID:</label>
                <input
                  type="text"
                  placeholder="e.g. Verified-Agent-v3"
                  value={newAgent}
                  onChange={(e) => setNewAgent(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-900 hover:border-slate-800 rounded px-2.5 py-1.5 text-xs text-slate-250 focus:outline-none focus:border-indigo-500"
                  required
                />
              </div>

              <div className="space-y-2.5">
                <label className="text-[10px] text-slate-500 font-bold uppercase tracking-wider block">Select Member Evaluation Runs ({selectedRuns.length} selected):</label>
                <div className="max-h-[160px] overflow-y-auto border border-slate-900 rounded bg-slate-950/40 p-2 space-y-1.5 font-mono text-[10px]">
                  {loadingRuns ? (
                    <div className="py-6 flex justify-center"><div className="w-5 h-5 border-2 border-indigo-500/25 border-t-indigo-500 rounded-full animate-spin" /></div>
                  ) : runs.length === 0 ? (
                    <p className="text-slate-500 italic p-2 text-center">No runs available to select.</p>
                  ) : (
                    runs.map(r => {
                      const isSelected = selectedRuns.includes(r.run_id);
                      return (
                        <button
                          key={r.run_id}
                          type="button"
                          onClick={() => handleSelectRun(r.run_id)}
                          className={`w-full flex items-center justify-between p-2 rounded transition-colors text-left border ${
                            isSelected ? 'bg-indigo-500/10 border-indigo-500/30 text-indigo-300' : 'bg-slate-900/40 border-slate-900/60 hover:bg-slate-900/80 text-slate-350'
                          }`}
                        >
                          <span className="truncate max-w-[280px] font-bold">{r.run_id}</span>
                          <span className="text-slate-500">{new Date(r.timestamp).toLocaleDateString()}</span>
                        </button>
                      );
                    })
                  )}
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-slate-900">
                <button
                  type="button"
                  onClick={() => { setShowCreateModal(false); setSelectedRuns([]); }}
                  className="px-3 py-1.5 border border-slate-850 hover:bg-slate-900 text-slate-400 rounded text-[11px] font-bold uppercase tracking-wider transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating || !newName || selectedRuns.length === 0}
                  className="px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700 disabled:bg-slate-900 disabled:text-slate-600 text-white rounded text-[11px] font-bold uppercase tracking-wider transition-all"
                >
                  {creating ? 'Saving...' : 'Save Suite'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
