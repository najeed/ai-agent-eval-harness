import React from 'react';
import { Terminal, Shield, Layers } from 'lucide-react';

interface ShellPageProps {
  title: string;
  description: string;
  endpoint?: string;
  details?: string;
}

export const ShellPage: React.FC<ShellPageProps> = ({ title, description, endpoint, details }) => {
  return (
    <div className="p-6 space-y-6">
      <div className="border border-slate-800 bg-slate-900/50 rounded-xl p-8 max-w-3xl space-y-4">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-indigo-500/10 text-indigo-400 rounded-lg border border-indigo-500/20">
            <Layers className="w-6 h-6" />
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">{title}</h1>
        </div>
        
        <p className="text-slate-400 text-sm leading-relaxed max-w-xl">
          {description}
        </p>

        {endpoint && (
          <div className="flex items-center gap-2 text-xs font-mono bg-slate-950/70 border border-slate-800/80 px-3 py-1.5 rounded-md text-emerald-400 w-fit">
            <Terminal className="w-3.5 h-3.5" />
            <span>Target API: {endpoint}</span>
          </div>
        )}

        <div className="pt-4 border-t border-slate-800/50 flex flex-col gap-2">
          <span className="text-xs text-slate-500 font-semibold uppercase tracking-wider">Module Status</span>
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-amber-500 animate-pulse" />
            <span className="text-xs text-amber-400 font-medium">Phase 2 Shell: Backed by CLI Engine</span>
          </div>
        </div>
      </div>

      {details && (
        <div className="border border-slate-800 bg-slate-950/20 rounded-xl p-6 max-w-3xl space-y-3">
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-400 uppercase tracking-wider">
            <Shield className="w-4 h-4 text-indigo-400" />
            <span>Engine Underlay Information</span>
          </div>
          <p className="text-slate-400 text-xs font-mono bg-slate-950 p-4 rounded-lg border border-slate-900 leading-relaxed overflow-x-auto whitespace-pre-wrap">
            {details}
          </p>
        </div>
      )}
    </div>
  );
};
