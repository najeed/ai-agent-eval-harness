import React, { useState } from 'react';
import { ShieldCheck, ShieldAlert, Award, CheckCircle, XCircle, Search, Key } from 'lucide-react';
import { useRBAC } from '../context/RBACContext';

interface VerifyResult {
  run_id: string;
  verified: boolean;
  timestamp: string;
  method: string;
  manifest: any;
}

export const TrustCenter: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'verify' | 'certify'>('verify');
  const { canSignCert, role } = useRBAC();
  
  // Verify State
  const [verifyRunId, setVerifyRunId] = useState('');
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verifyError, setVerifyError] = useState('');
  
  // Certify State
  const [certifyRunId, setCertifyRunId] = useState('');
  const [identityId, setIdentityId] = useState('system_id');
  const [status, setStatus] = useState('pass');
  const [score, setScore] = useState('1.0');
  const [policyRef, setPolicyRef] = useState('NIST-AI-100');
  const [certifyResult, setCertifyResult] = useState<any>(null);
  const [certifying, setCertifying] = useState(false);
  const [certifyError, setCertifyError] = useState('');
  
  // Key State
  const [resolvedKey, setResolvedKey] = useState('');

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!verifyRunId.trim()) return;
    
    setVerifying(true);
    setVerifyError('');
    setVerifyResult(null);
    setResolvedKey('');
    
    try {
      const res = await fetch(`/api/v1/verify/${verifyRunId.trim()}`);
      const data = await res.json();
      
      if (res.ok) {
        setVerifyResult(data);
        // Automatically resolve public key if key id is present
        const identity = data.manifest?.provenance_chain?.signer_identity || data.manifest?.signer_identity;
        if (identity) {
          resolvePublicKey(identity);
        }
      } else {
        setVerifyError(data.error || 'Verification failed. Run may not be certified or log not found.');
      }
    } catch (err: any) {
      setVerifyError(`Network error: ${err.message}`);
    } finally {
      setVerifying(false);
    }
  };

  const resolvePublicKey = async (signer: string) => {
    try {
      const res = await fetch(`/api/v1/identity/${signer}/public_key`);
      const data = await res.json();
      if (res.ok) {
        setResolvedKey(data.public_key);
      }
    } catch (e) {
      console.error(e);
    } finally {
      // Done
    }
  };

  const handleCertify = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!certifyRunId.trim()) return;

    setCertifying(true);
    setCertifyError('');
    setCertifyResult(null);

    try {
      const res = await fetch('/api/v1/certify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          run_id: certifyRunId.trim(),
          identity: identityId,
          status,
          score: parseFloat(score) || 1.0,
          policy_ref: policyRef,
          ttl: 86400 * 365 // 1 year
        })
      });
      const data = await res.json();
      
      if (res.ok) {
        setCertifyResult(data);
      } else {
        setCertifyError(data.error || 'Failed to issue cryptographic certificate.');
      }
    } catch (err: any) {
      setCertifyError(`Network error: ${err.message}`);
    } finally {
      setCertifying(false);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white tracking-tight">Trust & Verification Portal</h1>
        <p className="text-slate-400 text-sm">Issue and verify cryptographically sealed Agent compliance certificates.</p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-800">
        <button
          onClick={() => setActiveTab('verify')}
          className={`px-4 py-2.5 text-xs font-bold uppercase tracking-wider border-b-2 transition-colors ${
            activeTab === 'verify' 
              ? 'border-indigo-500 text-indigo-400' 
              : 'border-transparent text-slate-500 hover:text-slate-350'
          }`}
        >
          Verify Running Audit Logs
        </button>
        <button
          onClick={() => setActiveTab('certify')}
          className={`px-4 py-2.5 text-xs font-bold uppercase tracking-wider border-b-2 transition-colors ${
            activeTab === 'certify' 
              ? 'border-indigo-500 text-indigo-400' 
              : 'border-transparent text-slate-500 hover:text-slate-350'
          }`}
        >
          Issue Cryptographic Certificate
        </button>
      </div>

      {activeTab === 'verify' ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
          {/* Verification Search */}
          <div className="border border-slate-800 bg-slate-900/40 rounded-xl p-6 space-y-4">
            <h2 className="text-sm font-bold uppercase tracking-wider text-slate-300">Run Log Cryptographic Audit</h2>
            <form onSubmit={handleVerify} className="space-y-3">
              <div className="space-y-1.5">
                <label className="text-xs text-slate-400">Target Run Identifier:</label>
                <div className="relative">
                  <Search className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
                  <input
                    type="text"
                    required
                    placeholder="e.g. run-loan-approval-2026-..."
                    value={verifyRunId}
                    onChange={(e) => setVerifyRunId(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800/80 rounded-lg pl-9 pr-4 py-2.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 font-mono"
                  />
                </div>
              </div>
              <button
                type="submit"
                disabled={verifying}
                className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors text-xs font-bold uppercase tracking-wider flex items-center justify-center gap-2"
              >
                <ShieldCheck className="w-4 h-4" />
                <span>{verifying ? 'Auditing Run Logs...' : 'Verify Cryptographic Integrity'}</span>
              </button>
            </form>

            {verifyError && (
              <div className="p-3 bg-red-500/5 border border-red-500/20 text-red-400 rounded-lg text-xs leading-relaxed flex gap-2">
                <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{verifyError}</span>
              </div>
            )}
          </div>

          {/* Verification Result Card */}
          {verifyResult && (
            <div className="border border-slate-800 bg-slate-900/50 rounded-xl p-6 space-y-4 shadow-2xl relative overflow-hidden">
              <div className="absolute top-0 right-0 w-24 h-24 bg-gradient-to-br from-indigo-500/10 to-transparent pointer-events-none rounded-bl-full" />
              
              <div className="flex items-start justify-between">
                <div className="space-y-1">
                  <span className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Verification Ledger Entry</span>
                  <h3 className="text-base font-bold text-white font-mono">{verifyResult.run_id}</h3>
                </div>
                <div className="flex items-center gap-1.5 px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-wider">
                  {verifyResult.verified ? (
                    <span className="bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 rounded flex items-center gap-1">
                      <CheckCircle className="w-3 h-3" /> VERIFIED
                    </span>
                  ) : (
                    <span className="bg-red-500/10 text-red-400 border border-red-500/20 px-2 py-0.5 rounded flex items-center gap-1">
                      <XCircle className="w-3 h-3" /> FAILED
                    </span>
                  )}
                </div>
              </div>

              <div className="space-y-2 border-t border-slate-800/80 pt-4 text-xs">
                <div className="flex justify-between">
                  <span className="text-slate-500">Method</span>
                  <span className="text-slate-350 font-medium">{verifyResult.method}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Audit Timestamp</span>
                  <span className="text-slate-350 font-mono">{new Date(verifyResult.timestamp).toLocaleString()}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Trace Integrity Hash</span>
                  <span className="text-slate-350 font-mono text-[10px] truncate max-w-[200px]">{verifyResult.manifest?.trace_hash || 'SHA3-256 matches'}</span>
                </div>
              </div>

              {/* Public Key Display */}
              {resolvedKey && (
                <div className="space-y-1.5 border-t border-slate-800/80 pt-3">
                  <span className="text-[9px] uppercase tracking-wider text-slate-500 font-bold flex items-center gap-1">
                    <Key className="w-3 h-3 text-indigo-400" />
                    <span>Resolving Digital Signer PEM Public Key</span>
                  </span>
                  <pre className="bg-slate-950 p-3 rounded-lg border border-slate-850 text-[10px] text-slate-400 font-mono max-h-[120px] overflow-y-auto leading-relaxed select-all">
                    {resolvedKey}
                  </pre>
                </div>
              )}

              <div className="pt-4 border-t border-slate-800/80">
                <a
                  href={`/api/v1/runs/${verifyResult.run_id}/report.pdf`}
                  className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-indigo-600 hover:bg-indigo-500 active:bg-indigo-700 text-white rounded text-xs font-bold uppercase tracking-wider transition-all"
                >
                  Download PDF Compliance Report
                </a>
              </div>
            </div>
          )}
        </div>
      ) : !canSignCert ? (
        <div className="max-w-lg mx-auto mt-6 border border-amber-500/20 bg-amber-950/5 rounded-xl p-6 space-y-4 text-center">
          <ShieldAlert className="w-12 h-12 text-amber-500 mx-auto" />
          <h2 className="text-sm font-bold text-white uppercase tracking-wider">Auditor Privileges Required</h2>
          <p className="text-slate-400 text-xs leading-relaxed">
            Your current active role (<span className="text-indigo-400 font-bold">{role}</span>) does not have cryptographic signing privileges. 
            Verification Certificate (VC) issuance requires <span className="text-slate-350 font-bold">Compliance Auditor</span> or <span className="text-slate-350 font-bold">System Admin</span> authorization keys.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
          {/* Certificate Generation Form */}
          <div className="border border-slate-800 bg-slate-900/40 rounded-xl p-6 space-y-4">
            <h2 className="text-sm font-bold uppercase tracking-wider text-slate-300">Sign & Certify Run Logs</h2>
            <form onSubmit={handleCertify} className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-xs text-slate-400">Run ID to Certify:</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. run-loan-approval-2026-..."
                  value={certifyRunId}
                  onChange={(e) => setCertifyRunId(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800/80 rounded-lg px-3 py-2 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 font-mono"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-xs text-slate-400">Signer Identity Key:</label>
                  <input
                    type="text"
                    value={identityId}
                    onChange={(e) => setIdentityId(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800/80 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs text-slate-400">Policy Reference:</label>
                  <input
                    type="text"
                    value={policyRef}
                    onChange={(e) => setPolicyRef(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800/80 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500 font-mono"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-xs text-slate-400">Audit Status:</label>
                  <select
                    value={status}
                    onChange={(e) => setStatus(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800/80 rounded-lg px-3 py-2 text-xs text-slate-350 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="pass">pass (Approved)</option>
                    <option value="fail">fail (Breached)</option>
                    <option value="pending-review">pending-review</option>
                  </select>
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs text-slate-400">Compliance Score:</label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    max="1"
                    value={score}
                    onChange={(e) => setScore(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800/80 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={certifying}
                className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition-colors text-xs font-bold uppercase tracking-wider flex items-center justify-center gap-2"
              >
                <Award className="w-4 h-4" />
                <span>{certifying ? 'Signing Manifest...' : 'Issue Cryptographic Certificate'}</span>
              </button>
            </form>

            {certifyError && (
              <div className="p-3 bg-red-500/5 border border-red-500/20 text-red-400 rounded-lg text-xs leading-relaxed flex gap-2">
                <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{certifyError}</span>
              </div>
            )}
          </div>

          {/* Certify Result Card */}
          {certifyResult && (
            <div className="border border-indigo-500/30 bg-slate-900/50 rounded-xl p-6 space-y-4 shadow-2xl relative">
              <div className="flex items-center gap-2 text-xs font-semibold text-emerald-400 uppercase tracking-wider">
                <CheckCircle className="w-4 h-4" />
                <span>Evaluation Cryptographically Certified</span>
              </div>

              <div className="p-6 bg-slate-950/60 border border-slate-850 rounded-lg space-y-4 text-xs font-mono relative overflow-hidden">
                <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-indigo-500/5 via-transparent to-transparent pointer-events-none" />
                
                <div className="flex justify-between items-center border-b border-slate-800/50 pb-3">
                  <div className="flex items-center gap-2">
                    <Award className="w-5 h-5 text-indigo-400" />
                    <span className="font-bold text-slate-200 text-xs">Verification Certificate</span>
                  </div>
                  <span className="text-[10px] text-slate-500">v3.0.0</span>
                </div>

                <div className="space-y-1">
                  <span className="text-[9px] text-slate-500 uppercase tracking-wider font-bold">Target Identity (Run ID)</span>
                  <p className="text-slate-350 text-xs leading-tight truncate">{certifyResult.run_id}</p>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-1">
                    <span className="text-[9px] text-slate-500 uppercase tracking-wider font-bold">Status</span>
                    <p className="text-emerald-400 text-xs font-bold uppercase tracking-wider">{certifyResult.status}</p>
                  </div>
                  <div className="space-y-1">
                    <span className="text-[9px] text-slate-500 uppercase tracking-wider font-bold">SHA3 Trace Hash</span>
                    <p className="text-slate-400 text-[10px] truncate">{certifyResult.manifest?.trace_hash || 'Verified'}</p>
                  </div>
                </div>

                <div className="space-y-1 border-t border-slate-800/50 pt-3">
                  <span className="text-[9px] text-slate-500 uppercase tracking-wider font-bold">Manifest Vault Path</span>
                  <p className="text-slate-400 text-[10px] truncate select-all">{certifyResult.manifest?.manifest_path}</p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

