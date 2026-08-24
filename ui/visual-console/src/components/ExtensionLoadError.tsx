import React from 'react';
import { AlertTriangle } from 'lucide-react';

export interface ExtensionLoadErrorProps {
  /** Human-readable extension/feature display name */
  title?: string;
  entryUrl?: string;
  /** Specific contract or load violations */
  violations?: string[];
  message?: string;
}

/**
 * Generic fallback rendered whenever a dynamically-registered extension route
 * fails to load or violates the RuntimeExtension contract. Replaces the
 * former ControlPlane-branded gate so the OSS runtime stays brand-neutral.
 */
export const ExtensionLoadError: React.FC<ExtensionLoadErrorProps> = ({
  title = 'Extension unavailable',
  entryUrl,
  violations = [],
  message,
}) => (
  <div className="flex h-full min-h-[400px] flex-col items-center justify-center p-8 text-center">
    <div className="p-6 bg-red-500/10 border border-red-500/20 rounded-2xl max-w-lg shadow-xl backdrop-blur">
      <AlertTriangle className="w-10 h-10 mx-auto mb-3 text-red-400" />
      <h3 className="font-bold text-base text-red-300">{title}</h3>
      {entryUrl && (
        <p className="text-xs text-slate-400 mt-2 font-mono break-all bg-slate-950/60 p-2.5 rounded-lg border border-slate-900">
          {entryUrl}
        </p>
      )}
      {message && <p className="text-[11px] text-red-400/80 mt-2">{message}</p>}
      {violations.length > 0 && (
        <ul className="mt-3 text-left space-y-1 bg-slate-950/80 p-3 rounded-lg border border-red-500/20 font-mono text-[10px] text-red-300">
          {violations.map((v, i) => (
            <li key={i}>• {v}</li>
          ))}
        </ul>
      )}
      <p className="text-[11px] text-slate-500 mt-3">
        This route is served by a signed extension. The runtime refused to mount it because it
        failed integrity, trust or contract validation.
      </p>
    </div>
  </div>
);

export default ExtensionLoadError;
