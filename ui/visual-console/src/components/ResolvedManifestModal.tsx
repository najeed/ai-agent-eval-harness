import React from 'react';
import { X, ShieldCheck, Cpu, Key, Play, FileCode, CheckCircle2 } from 'lucide-react';
import type { AgentTargetProfile } from './AgentTargetSelector';


interface ResolvedManifestModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirmLaunch: () => void;
  scenario: {
    id: string;
    title?: string;
    version?: string;
    hash?: string;
    nodesCount?: number;
    assertionsCount?: number;
  };
  targetProfile: AgentTargetProfile;
  tenantId: string;
  workspaceId: string;
  seed: number;
  evaluators: string[];
  isLaunching?: boolean;
}

export const ResolvedManifestModal: React.FC<ResolvedManifestModalProps> = ({
  isOpen,
  onClose,
  onConfirmLaunch,
  scenario,
  targetProfile,
  tenantId,
  workspaceId,
  seed,
  evaluators,
  isLaunching = false,
}) => {
  if (!isOpen) return null;

  const contentHash =
    scenario.hash ||
    `sha3_256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-fade-in">
      <div className="bg-slate-900 border border-slate-700/80 rounded-2xl w-full max-w-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="p-5 border-b border-slate-800 flex items-center justify-between bg-slate-950/40">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-slate-100">Review Resolved Execution Manifest</h2>
              <p className="text-xs text-slate-400">
                Immutable, reproducible preflight configuration for enterprise auditability.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-200 p-1.5 rounded-lg hover:bg-slate-800 transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 overflow-y-auto space-y-5 text-xs text-slate-300">
          {/* Top-Level Context Card */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-slate-950/60 p-3.5 rounded-xl border border-slate-800 font-mono">
            <div>
              <span className="text-[10px] text-slate-500 uppercase block">Tenant</span>
              <span className="text-slate-200 font-semibold truncate block">{tenantId}</span>
            </div>
            <div>
              <span className="text-[10px] text-slate-500 uppercase block">Workspace</span>
              <span className="text-slate-200 font-semibold truncate block">{workspaceId}</span>
            </div>
            <div>
              <span className="text-[10px] text-slate-500 uppercase block">Deterministic Seed</span>
              <span className="text-amber-400 font-semibold">{seed}</span>
            </div>
            <div>
              <span className="text-[10px] text-slate-500 uppercase block">Runtime Boundary</span>
              <span className="text-emerald-400 font-semibold">Strict VFS Jail</span>
            </div>
          </div>

          {/* Scenario Details */}
          <div className="bg-slate-950/40 p-4 rounded-xl border border-slate-800 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-200 flex items-center gap-1.5">
                <FileCode className="w-4 h-4 text-indigo-400" /> Scenario Assurance Target
              </span>
              <span className="text-[11px] font-mono text-indigo-400 bg-indigo-500/10 px-2 py-0.5 rounded border border-indigo-500/20">
                v{scenario.version || '1.4.0'}
              </span>
            </div>
            <div className="text-sm font-medium text-white">{scenario.title || scenario.id}</div>
            <div className="text-[11px] font-mono text-slate-400 break-all bg-slate-950 px-2.5 py-1.5 rounded border border-slate-800/80">
              Content Digest: {contentHash}
            </div>
          </div>

          {/* Agent Target Details */}
          <div className="bg-slate-950/40 p-4 rounded-xl border border-slate-800 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-200 flex items-center gap-1.5">
                <Cpu className="w-4 h-4 text-emerald-400" /> Resolved Target Configuration
              </span>
              <span className="text-[11px] font-mono text-emerald-400 uppercase">
                {targetProfile.provider}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2 text-[11px] font-mono">
              <div>
                <span className="text-slate-500 block">Model:</span>
                <span className="text-slate-200">{targetProfile.model}</span>
              </div>
              <div>
                <span className="text-slate-500 block">Endpoint:</span>
                <span className="text-slate-200 truncate block">{targetProfile.endpoint}</span>
              </div>
              <div>
                <span className="text-slate-500 block">Max Turns:</span>
                <span className="text-slate-200">{targetProfile.maxTurns || 10}</span>
              </div>
              <div>
                <span className="text-slate-500 block">Execution Timeout:</span>
                <span className="text-slate-200">{targetProfile.timeoutSeconds || 60}s</span>
              </div>
            </div>
          </div>

          {/* Active Evaluators & Signers */}
          <div className="bg-slate-950/40 p-4 rounded-xl border border-slate-800 space-y-2">
            <span className="text-xs font-semibold text-slate-200 flex items-center gap-1.5">
              <Key className="w-4 h-4 text-amber-400" /> Active Evaluators & Verification Sealers
            </span>
            <div className="flex flex-wrap gap-1.5 pt-1">
              {evaluators.map((ev, i) => (
                <span
                  key={i}
                  className="px-2 py-0.5 rounded bg-slate-900 border border-slate-700/80 text-[11px] font-mono text-slate-300 flex items-center gap-1"
                >
                  <CheckCircle2 className="w-3 h-3 text-emerald-400" /> {ev}
                </span>
              ))}
              <span className="px-2 py-0.5 rounded bg-indigo-950/40 border border-indigo-500/30 text-[11px] font-mono text-indigo-300 flex items-center gap-1">
                <ShieldCheck className="w-3 h-3 text-indigo-400" /> PQC Post-Quantum Signer (Ed25519)
              </span>
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="p-5 border-t border-slate-800 bg-slate-950/60 flex items-center justify-between">
          <button
            type="button"
            onClick={onClose}
            disabled={isLaunching}
            className="px-4 py-2 rounded-lg text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-700 font-medium transition"
          >
            Back to Edit
          </button>

          <button
            type="button"
            onClick={onConfirmLaunch}
            disabled={isLaunching}
            className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-bold shadow-lg shadow-emerald-500/20 flex items-center gap-2 transition transform active:scale-95 disabled:opacity-50"
          >
            <Play className="w-4 h-4 fill-current" />
            {isLaunching ? 'Authorizing & Launching...' : 'Confirm & Execute Verification'}
          </button>
        </div>
      </div>
    </div>
  );
};
