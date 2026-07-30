import React, { useState, useEffect } from 'react';
import { ShieldAlert, Trash2, HeartPulse, RefreshCw } from 'lucide-react';

interface DoctorAudit {
  status: string;
  project_root: string;
  plugins_loaded: boolean;
  catalog_size: number;
  simulator_count: number;
  pid: number;
  error?: string;
}

import { useRBAC } from '../context/RBACContext';

export const Settings: React.FC = () => {
  const { canAccessSettings, role } = useRBAC();
  const [audit, setAudit] = useState<DoctorAudit | null>(null);
  const [loading, setLoading] = useState(true);
  const [cleaning, setCleaning] = useState(false);
  const [retentionDays, setRetentionDays] = useState('0');
  const [showConfirm, setShowConfirm] = useState(false);
  const [message, setMessage] = useState('');

  if (!canAccessSettings) {
    return (
      <div className="p-6 max-w-lg mx-auto mt-12 border border-red-500/20 bg-red-950/10 rounded-xl space-y-4 text-center">
        <ShieldAlert className="w-12 h-12 text-red-500 mx-auto" />
        <h2 className="text-lg font-bold text-white uppercase tracking-wider">Access Denied</h2>
        <p className="text-slate-400 text-xs leading-relaxed">
          Your current active role (<span className="text-indigo-400 font-bold">{role}</span>) does not have privileges to view or modify System Settings. 
          Please contact your administrator or switch to <span className="text-slate-350 font-bold">System Admin</span> or <span className="text-slate-350 font-bold">MultiAgentOps Eng.</span> in the header layout toolbar.
        </p>
      </div>
    );
  }

  const fetchDoctor = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/v1/doctor');
      const data = await res.json();
      setAudit(data);
    } catch (e: any) {
      setAudit({
        status: 'unhealthy',
        project_root: '',
        plugins_loaded: false,
        catalog_size: 0,
        simulator_count: 0,
        pid: 0,
        error: e.message
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDoctor();
  }, []);

  const handleCleanup = async () => {
    setCleaning(true);
    setMessage('');
    try {
      const res = await fetch('/api/cleanup-runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ retention_days: parseInt(retentionDays) || 0 })
      });
      const data = await res.json();
      if (res.ok) {
        setMessage(`Success: ${data.message || 'Cleared historical runs.'}`);
      } else {
        setMessage(`Error: ${data.error || 'Failed to cleanup.'}`);
      }
    } catch (e: any) {
      setMessage(`Error: ${e.message}`);
    } finally {
      setCleaning(false);
      setShowConfirm(false);
      fetchDoctor();
    }
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-white tracking-tight">System Settings & Health</h1>
          <p className="text-slate-400 text-sm">Monitor harness engine state and clean up debug assets.</p>
        </div>
        <button 
          onClick={fetchDoctor}
          className="flex items-center gap-2 px-3 py-1.5 bg-slate-800 text-slate-300 rounded-lg hover:bg-slate-700 transition-colors text-xs font-semibold"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh Audit</span>
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Doctor Audit Card */}
        <div className="border border-slate-800 bg-slate-900/40 rounded-xl p-6 space-y-4">
          <div className="flex items-center gap-2">
            <HeartPulse className="w-5 h-5 text-indigo-400" />
            <h2 className="text-lg font-semibold text-white">System Health Audit (Doctor)</h2>
          </div>

          {loading ? (
            <p className="text-xs text-slate-500 italic">Performing audit check...</p>
          ) : audit ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between p-3 rounded-lg bg-slate-950/40 border border-slate-800/60">
                <span className="text-xs text-slate-400">System Status</span>
                <span className={`text-xs px-2 py-0.5 rounded-full font-bold uppercase tracking-wider ${
                  audit.status === 'healthy' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-red-500/10 text-red-400 border border-red-500/20'
                }`}>
                  {audit.status}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="p-3 rounded-lg bg-slate-950/40 border border-slate-800/60 space-y-1">
                  <span className="text-slate-500 text-[10px] uppercase font-semibold tracking-wider">Catalog Size</span>
                  <p className="text-xl font-bold text-slate-200">{audit.catalog_size} Scenarios</p>
                </div>
                <div className="p-3 rounded-lg bg-slate-950/40 border border-slate-800/60 space-y-1">
                  <span className="text-slate-500 text-[10px] uppercase font-semibold tracking-wider">Environment Simulators</span>
                  <p className="text-xl font-bold text-slate-200">{audit.simulator_count} Active</p>
                </div>
              </div>
              <div className="p-3 rounded-lg bg-slate-950/40 border border-slate-800/60 text-xs space-y-1">
                <span className="text-slate-500 uppercase font-semibold tracking-wider text-[10px]">Project Root</span>
                <p className="text-slate-300 font-mono text-[11px] truncate">{audit.project_root}</p>
              </div>
              <div className="flex justify-between text-xs text-slate-500 px-1">
                <span>VConsole Process PID: {audit.pid}</span>
                <span>Plugins Active: {audit.plugins_loaded ? 'Yes' : 'No'}</span>
              </div>
            </div>
          ) : (
            <p className="text-xs text-red-400">Failed to load system audit details.</p>
          )}
        </div>

        {/* Destructive Actions Card */}
        <div className="border border-slate-800 bg-slate-900/40 rounded-xl p-6 space-y-4">
          <div className="flex items-center gap-2">
            <Trash2 className="w-5 h-5 text-red-400" />
            <h2 className="text-lg font-semibold text-white">Destructive Tasks</h2>
          </div>

          <div className="p-4 bg-amber-500/5 border border-amber-500/10 rounded-lg flex items-start gap-3">
            <ShieldAlert className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <h4 className="text-xs font-bold text-amber-400 uppercase tracking-wider">Immutability Note (WORM Compliance)</h4>
              <p className="text-slate-400 text-xs leading-relaxed">
                AgentV specifies Write-Once-Read-Many (WORM) log retention for regulatory reporting. Log cleanup is physically disabled or audited in compliance instances. This action deletes all local database run fragments and trace log directories.
              </p>
            </div>
          </div>

          <div className="space-y-3 pt-2">
            <div className="flex items-center gap-3">
              <label className="text-xs text-slate-400 shrink-0">Retention Age (Days):</label>
              <input 
                type="number"
                min="0"
                value={retentionDays}
                onChange={(e) => setRetentionDays(e.target.value)}
                className="w-20 bg-slate-950 border border-slate-800 rounded px-2.5 py-1 text-xs text-slate-300 focus:outline-none focus:border-indigo-500"
              />
              <span className="text-[10px] text-slate-500 font-semibold italic">(0 = Delete everything)</span>
            </div>

            <button 
              onClick={() => setShowConfirm(true)}
              disabled={cleaning}
              className="flex items-center justify-center gap-2 w-full py-2 bg-red-950/20 hover:bg-red-950/40 border border-red-900/30 hover:border-red-900/60 text-red-400 rounded-lg transition-all text-xs font-semibold"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span>{cleaning ? 'Pruning Traces...' : 'Cleanup Historical Traces'}</span>
            </button>

            {message && (
              <p className="text-xs font-semibold p-2.5 rounded bg-slate-950/80 border border-slate-800/80 text-center text-slate-300">
                {message}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Confirmation Dialog Overlay */}
      {showConfirm && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 space-y-4 text-slate-100 shadow-2xl">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-red-500/10 text-red-400 rounded-lg">
                <Trash2 className="w-5 h-5" />
              </div>
              <h3 className="text-lg font-bold text-white">Verify Trace Cleanup</h3>
            </div>
            
            <p className="text-slate-300 text-xs leading-relaxed">
              Are you absolutely sure you want to delete trace history? 
              This will remove all run logs and evaluation reports older than <strong className="text-amber-400">{retentionDays} days</strong>.
              <br/><br/>
              This operation is **irreversible** and violates WORM log storage policies in production audit modes.
            </p>

            <div className="flex justify-end gap-3 pt-2 text-xs">
              <button 
                onClick={() => setShowConfirm(false)}
                className="px-4 py-2 bg-slate-800 rounded-lg hover:bg-slate-700 text-slate-300 transition-colors"
              >
                Cancel
              </button>
              <button 
                onClick={handleCleanup}
                className="px-4 py-2 bg-red-600 rounded-lg hover:bg-red-500 text-white font-semibold transition-colors"
              >
                Yes, Delete Traces
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
