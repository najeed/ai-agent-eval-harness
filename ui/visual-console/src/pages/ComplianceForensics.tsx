import React, { useState, useEffect } from 'react';
import { ShieldCheck, Cpu } from 'lucide-react';

interface ComplianceDetail {
  run_id: string;
  quantum_safe: boolean;
  algorithm: string;
  provider?: string;
  timestamp?: string;
  reason?: string;
}

interface SummaryData {
  total_certified: number;
  quantum_safe: number;
  classical_only: number;
  percent_quantum_safe: number;
  details: ComplianceDetail[];
}

export const ComplianceForensics: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'pqc' | 'diff'>('pqc');

  // Tab A: PQC Compliance States
  const [summary, setSummary] = useState<SummaryData | null>(null);
  const [loadingSummary, setLoadingSummary] = useState(false);
  const [rangeFilter, setRangeFilter] = useState('');

  // Tab B: Diff State Sandbox Inputs
  const [oldStateInput, setOldStateInput] = useState(
    JSON.stringify(
      [
        { id: 101, name: 'Alice Smith', credit_score: 720, loan_status: 'pending' },
        { id: 102, name: 'Bob Johnson', credit_score: 580, loan_status: 'pending' },
        { id: 103, name: 'Charlie Rose', credit_score: 640, loan_status: 'pending' }
      ],
      null,
      2
    )
  );
  const [newStateInput, setNewStateInput] = useState(
    JSON.stringify(
      [
        { id: 101, name: 'Alice Smith', credit_score: 720, loan_status: 'approved' },
        { id: 102, name: 'Bob Johnson', credit_score: 580, loan_status: 'rejected' },
        { id: 103, name: 'Charlie Rose', credit_score: 650, loan_status: 'pending' },
        { id: 104, name: 'Diana Prince', credit_score: 800, loan_status: 'approved' }
      ],
      null,
      2
    )
  );
  const [diffResult, setDiffResult] = useState<any>(null);
  const [diffing, setDiffing] = useState(false);
  const [diffError, setDiffError] = useState('');

  const fetchSummary = async () => {
    setLoadingSummary(true);
    try {
      const res = await fetch(`/api/compliance/summary?range=${encodeURIComponent(rangeFilter)}`);
      const json = await res.json();
      if (res.ok) {
        setSummary(json);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingSummary(false);
    }
  };

  useEffect(() => {
    if (activeTab === 'pqc') {
      fetchSummary();
    }
  }, [activeTab, rangeFilter]);

  const handleRunDiff = async () => {
    setDiffing(true);
    setDiffError('');
    setDiffResult(null);
    try {
      const oldObj = JSON.parse(oldStateInput);
      const newObj = JSON.parse(newStateInput);
      
      const res = await fetch('/api/forensics/diff', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ old: oldObj, new: newObj }),
      });
      const json = await res.json();
      if (res.ok) {
        setDiffResult(json);
      } else {
        setDiffError(json.error || 'Failed to compute differential.');
      }
    } catch (err: any) {
      setDiffError(err.message || 'Invalid JSON input strings.');
    } finally {
      setDiffing(false);
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-slate-900 pb-5">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-indigo-400" />
            <span>Compliance & Forensics</span>
          </h1>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            NIST AI-100-1 proof verification. Audit Post-Quantum Cryptographic signatures and state differentials to trace env mutations.
          </p>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="flex gap-2 border-b border-slate-900 pb-3">
        <button
          onClick={() => setActiveTab('pqc')}
          className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
            activeTab === 'pqc'
              ? 'bg-slate-900 text-white border border-slate-800'
              : 'text-slate-500 hover:text-slate-300'
          }`}
        >
          Post-Quantum Signature Verification
        </button>
        <button
          onClick={() => setActiveTab('diff')}
          className={`px-4 py-1.5 rounded-lg text-xs font-bold transition-all ${
            activeTab === 'diff'
              ? 'bg-slate-900 text-white border border-slate-800'
              : 'text-slate-500 hover:text-slate-300'
          }`}
        >
          Forensic Environment Diff
        </button>
      </div>

      {activeTab === 'pqc' ? (
        <div className="space-y-6">
          {/* Summary Metric Cards */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="bg-slate-950/40 border border-slate-900 p-4 rounded-xl">
              <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Quantum-Safe Capacity</span>
              <div className="text-2xl font-bold text-indigo-400 mt-1 font-mono">
                {summary ? `${summary.percent_quantum_safe}%` : '0.0%'}
              </div>
              <div className="text-xs text-slate-500 mt-0.5">ML-DSA-65 signed runs</div>
            </div>
            <div className="bg-slate-950/40 border border-slate-900 p-4 rounded-xl">
              <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Total Certified Audit Logs</span>
              <div className="text-2xl font-bold text-white mt-1 font-mono">
                {summary ? summary.total_certified : 0}
              </div>
              <div className="text-xs text-slate-500 mt-0.5">Secured with signature chain</div>
            </div>
            <div className="bg-slate-950/40 border border-slate-900 p-4 rounded-xl">
              <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Quantum Proofs (ML-DSA-65)</span>
              <div className="text-2xl font-bold text-emerald-400 mt-1 font-mono">
                {summary ? summary.quantum_safe : 0}
              </div>
              <div className="text-xs text-slate-500 mt-0.5">Immutable post-quantum blocks</div>
            </div>
            <div className="bg-slate-950/40 border border-slate-900 p-4 rounded-xl">
              <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Classical Signature Fallbacks</span>
              <div className="text-2xl font-bold text-amber-500 mt-1 font-mono">
                {summary ? summary.classical_only : 0}
              </div>
              <div className="text-xs text-slate-500 mt-0.5">Ed25519 / RSA fallback nodes</div>
            </div>
          </div>

          {/* Range filter input & grid */}
          <div className="bg-slate-950/20 border border-slate-900 rounded-xl overflow-hidden p-5 space-y-4">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
              <h3 className="text-xs font-bold text-white uppercase tracking-wider">Fleet Cryptographic Certifications</h3>
              <input
                type="text"
                value={rangeFilter}
                onChange={(e) => setRangeFilter(e.target.value)}
                placeholder="Filter by run key date (e.g. 2026-07)..."
                className="bg-slate-950 border border-slate-850 rounded px-2.5 py-1 text-[11px] text-slate-300 focus:outline-none focus:border-indigo-500 max-w-xs font-mono"
              />
            </div>

            {loadingSummary ? (
              <div className="flex justify-center items-center h-48 text-xs text-slate-500">
                Loading compliance index...
              </div>
            ) : !summary || summary.details.length === 0 ? (
              <div className="h-48 border border-dashed border-slate-900 rounded-xl flex items-center justify-center text-xs text-slate-700 italic">
                No certified compliance logs discovered matching filter.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-slate-900 text-[10px] uppercase font-bold tracking-wider text-slate-500 bg-slate-950/30">
                      <th className="px-4 py-3">Certified Run ID</th>
                      <th className="px-4 py-3">Audit Security Status</th>
                      <th className="px-4 py-3">Cryptographic Key Algorithm</th>
                      <th className="px-4 py-3">Authority / Provider</th>
                      <th className="px-4 py-3">Seal Timestamp</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-900">
                    {summary.details.map((row) => (
                      <tr key={row.run_id} className="hover:bg-slate-950/30">
                        <td className="px-4 py-3 font-semibold font-mono text-slate-300">{row.run_id}</td>
                        <td className="px-4 py-3">
                          {row.quantum_safe ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-[10px] font-bold">
                              ✓ Quantum-Safe
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-amber-500 text-[10px] font-bold">
                              ⚠ Classical Only
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 font-mono text-slate-400">{row.algorithm}</td>
                        <td className="px-4 py-3 text-slate-400">{row.provider || 'unknown'}</td>
                        <td className="px-4 py-3 font-mono text-slate-500">
                          {row.timestamp ? new Date(row.timestamp).toLocaleString() : 'N/A'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Sandbox Editor Inputs */}
          <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4">
            <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
              <Cpu className="w-4 h-4 text-indigo-400" />
              <span>Snapshot Sandbox</span>
            </h3>
            <p className="text-[10px] text-slate-500 leading-relaxed">
              Input database tables or key-value states to check changes computed by the server-side primary-key list diff engine.
            </p>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1">
                <span className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">Prior State snapshot (old)</span>
                <textarea
                  value={oldStateInput}
                  onChange={(e) => setOldStateInput(e.target.value)}
                  className="w-full h-64 bg-slate-950 border border-slate-850 p-3 rounded-lg text-[10px] font-mono text-slate-300 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 resize-none leading-relaxed"
                />
              </div>
              <div className="space-y-1">
                <span className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">Mutated State snapshot (new)</span>
                <textarea
                  value={newStateInput}
                  onChange={(e) => setNewStateInput(e.target.value)}
                  className="w-full h-64 bg-slate-950 border border-slate-850 p-3 rounded-lg text-[10px] font-mono text-slate-300 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 resize-none leading-relaxed"
                />
              </div>
            </div>

            <button
              onClick={handleRunDiff}
              disabled={diffing}
              className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-xs font-bold rounded-lg transition-colors flex items-center justify-center gap-2"
            >
              {diffing ? 'Computing Differential...' : 'Execute list_diff Engine'}
            </button>
          </div>

          {/* Differential Outputs */}
          <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4">
            <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
              <Cpu className="w-4 h-4 text-indigo-400" />
              <span>Attribution Diff Report</span>
            </h3>

            {diffError && (
              <div className="p-3 bg-rose-500/10 border border-rose-500/25 rounded-lg text-rose-400 text-xs">
                {diffError}
              </div>
            )}

            {diffing ? (
              <div className="h-80 flex flex-col justify-center items-center gap-3">
                <div className="w-6 h-6 border-3 border-indigo-500/20 border-t-indigo-500 rounded-full animate-spin" />
                <span className="text-xs text-slate-500">Executing diff algorithms...</span>
              </div>
            ) : !diffResult ? (
              <div className="h-80 border border-dashed border-slate-900 rounded-xl flex items-center justify-center text-xs text-slate-700 italic">
                Input snapshot JSON arrays and click execute to verify differential.
              </div>
            ) : diffResult.identical ? (
              <div className="h-80 bg-slate-950/20 border border-slate-900 rounded-xl flex flex-col justify-center items-center gap-2 p-10 text-center">
                <ShieldCheck className="w-8 h-8 text-emerald-500" />
                <h4 className="text-xs font-bold text-slate-300">Snapshots Identical</h4>
                <p className="text-[10px] text-slate-600 mt-1 max-w-xs leading-relaxed">
                  No added, modified, or deleted records found. Immutability status verified.
                </p>
              </div>
            ) : (
              <div className="space-y-4 max-h-[360px] overflow-y-auto pr-2">
                <div className="flex justify-between items-center text-[10px] text-slate-500 font-mono border-b border-slate-900 pb-2">
                  <span>DISCOVERED PRIMARY KEY: <span className="text-indigo-400 font-bold font-mono">"{diffResult.detected_primary_key || 'none'}"</span></span>
                  <span className="text-amber-500">MUTATIONS ATTESTED</span>
                </div>

                {/* Diff Output Representation */}
                {diffResult.diff?.["__LIST_DIFF__"] && (
                  <div className="space-y-4">
                    {/* Added */}
                    {diffResult.diff["__LIST_DIFF__"].added?.length > 0 && (
                      <div className="space-y-2">
                        <span className="text-[9px] bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 px-2 py-0.5 rounded font-bold">
                          ADDED RECORDS (+{diffResult.diff["__LIST_DIFF__"].added.length})
                        </span>
                        <div className="space-y-1.5">
                          {diffResult.diff["__LIST_DIFF__"].added.map((item: any, idx: number) => (
                            <pre key={idx} className="text-[10px] font-mono text-emerald-300 bg-emerald-950/10 border border-emerald-950/25 p-2 rounded max-h-24 overflow-y-auto">
                              {JSON.stringify(item, null, 2)}
                            </pre>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Modified */}
                    {diffResult.diff["__LIST_DIFF__"].modified?.length > 0 && (
                      <div className="space-y-2">
                        <span className="text-[9px] bg-amber-500/10 border border-amber-500/20 text-amber-400 px-2 py-0.5 rounded font-bold">
                          MODIFIED RECORDS ({diffResult.diff["__LIST_DIFF__"].modified.length})
                        </span>
                        <div className="space-y-1.5">
                          {diffResult.diff["__LIST_DIFF__"].modified.map((item: any, idx: number) => (
                            <div key={idx} className="bg-amber-950/10 border border-amber-950/25 p-2 rounded space-y-1 max-h-32 overflow-y-auto">
                              <div className="text-[9px] font-mono text-slate-500 font-bold border-b border-slate-900/50 pb-1">
                                KEY ID: {item[diffResult.detected_primary_key || 'id']}
                              </div>
                              <pre className="text-[10px] font-mono text-amber-300">
                                {JSON.stringify(item, null, 2)}
                              </pre>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Deleted */}
                    {diffResult.diff["__LIST_DIFF__"].deleted?.length > 0 && (
                      <div className="space-y-2">
                        <span className="text-[9px] bg-rose-500/10 border border-rose-500/20 text-rose-400 px-2 py-0.5 rounded font-bold">
                          DELETED RECORD ID KEYS (-{diffResult.diff["__LIST_DIFF__"].deleted.length})
                        </span>
                        <div className="flex flex-wrap gap-1.5">
                          {diffResult.diff["__LIST_DIFF__"].deleted.map((id: any, idx: number) => (
                            <span key={idx} className="px-2 py-1 bg-rose-950/20 border border-rose-900/30 text-rose-300 rounded font-mono text-[10px]">
                              {id}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
