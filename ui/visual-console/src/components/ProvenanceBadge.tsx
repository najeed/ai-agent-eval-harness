import React from 'react';

export type ProvenanceType = 'prod' | 'live' | 'simulation' | 'shim' | 'hybrid';

interface ProvenanceBadgeProps {
  provenance?: ProvenanceType | string;
  size?: 'sm' | 'md';
  className?: string;
}

export const ProvenanceBadge: React.FC<ProvenanceBadgeProps> = ({
  provenance = 'simulation',
  size = 'sm',
  className = '',
}) => {
  const norm = String(provenance).toLowerCase();
  const isProd = norm === 'prod' || norm === 'live';

  const baseClasses = size === 'sm'
    ? 'text-[9px] px-1.5 py-0.5 tracking-wider'
    : 'text-xs px-2.5 py-1 tracking-wide';

  if (isProd) {
    return (
      <span
        title="PROD / LIVE: Verified against live production endpoints and authenticated services."
        className={`inline-flex items-center gap-1.5 font-mono font-bold uppercase rounded border bg-emerald-500/10 text-emerald-400 border-emerald-500/30 ${baseClasses} ${className}`}
      >
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse shrink-0" />
        <span>PROD / LIVE</span>
      </span>
    );
  }

  return (
    <span
      title="SIMULATION / SHIM: Executing against virtualized, sandboxed, or synthetic test fixtures."
      className={`inline-flex items-center gap-1.5 font-mono font-bold uppercase rounded border bg-amber-500/10 text-amber-400 border-amber-500/30 ${baseClasses} ${className}`}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-amber-400 shrink-0" />
      <span>SIMULATION / SHIM</span>
    </span>
  );
};
