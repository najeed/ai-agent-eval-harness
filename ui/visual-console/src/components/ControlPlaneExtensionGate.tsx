import React from 'react';
import { Shield, Server, ArrowRight, Cpu } from 'lucide-react';
import { Link } from 'react-router-dom';


export interface ControlPlaneExtensionGateProps {
  featureName: string;
  category: 'Fleet & Policy' | 'Compliance & Audit' | 'Governance & Publishing' | 'Analytics & Calibration' | 'CI/CD & Workflows';
  description: string;
  documentationAnchor?: string;
}

export const ControlPlaneExtensionGate: React.FC<ControlPlaneExtensionGateProps> = ({
  featureName,
  category,
  description,
  documentationAnchor = 'control-plane',
}) => {
  return (
    <div className="flex min-h-[calc(100vh-80px)] flex-col items-center justify-center p-8 text-center bg-navy-base">
      <div className="relative max-w-xl w-full p-8 rounded-3xl bg-slate-900/80 border border-slate-800 shadow-2xl backdrop-blur-xl overflow-hidden">
        {/* Glow effect */}
        <div className="absolute -top-24 -right-24 w-48 h-48 bg-indigo-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute -bottom-24 -left-24 w-48 h-48 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />

        {/* Badge & Icon */}
        <div className="flex flex-col items-center gap-4 mb-6">
          <div className="w-14 h-14 rounded-2xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 shadow-inner">
            <Shield className="w-7 h-7" />
          </div>
          <div className="flex items-center gap-2">
            <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold uppercase tracking-wider bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
              Control Plane Extension
            </span>
            <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold uppercase tracking-wider bg-slate-800 text-slate-400 border border-slate-700">
              {category}
            </span>
          </div>
        </div>

        {/* Content */}
        <h2 className="text-xl font-bold text-white mb-2">{featureName}</h2>
        <p className="text-xs text-slate-400 leading-relaxed max-w-md mx-auto mb-6">
          {description}
        </p>

        {/* Architecture Note */}
        <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800/80 text-left space-y-2 mb-6">
          <div className="flex items-center gap-2 text-[11px] font-bold text-slate-300">
            <Server className="w-3.5 h-3.5 text-indigo-400" />
            <span>Clean Runtime ↔ Control Plane Boundary</span>
          </div>
          <p className="text-[11px] text-slate-400 leading-normal font-sans">
            AgentV Runtime OSS provides the core execution, evaluation, canonical execution graph, and cryptographic verification engine.
            Enterprise governance, human-in-the-loop queues, and fleet policy are delivered via separate Control Plane micro-frontend extensions.
          </p>
        </div>

        {/* Actions */}
        <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
          <Link
            to={`/docs#${documentationAnchor}`}
            className="w-full sm:w-auto px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold transition flex items-center justify-center gap-2 shadow-lg shadow-indigo-500/20"
          >
            <span>Read Architecture Guide</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </Link>
          <Link
            to="/settings"
            className="w-full sm:w-auto px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold border border-slate-700 transition flex items-center justify-center gap-2"
          >
            <Cpu className="w-3.5 h-3.5" />
            <span>Configure Extensions</span>
          </Link>
        </div>
      </div>
    </div>
  );
};
