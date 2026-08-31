import React from 'react';

interface ProvisionalBadgeProps {
  provisional?: boolean;
  executionMode?: string | null;
  className?: string;
  size?: 'sm' | 'md' | 'lg';
}

export const ProvisionalBadge: React.FC<ProvisionalBadgeProps> = ({
  provisional,
  executionMode,
  className = '',
  size = 'md',
}) => {
  const isProvisional = provisional || !executionMode || executionMode === 'unknown';
  if (!isProvisional) return null;

  const sizeClasses = {
    sm: 'text-[9px] px-1.5 py-0.5 gap-1',
    md: 'text-[11px] px-2 py-0.5 gap-1.5',
    lg: 'text-xs px-2.5 py-1 gap-2',
  }[size];

  return (
    <span
      className={`inline-flex items-center rounded-md font-mono font-medium border bg-amber-500/10 border-amber-500/30 text-amber-300 shadow-sm ${sizeClasses} ${className}`}
      title="Provisional Run: Execution mode was undeclared or unverified. Stamped non-authoritative for regulatory compliance."
      data-testid="provisional-badge"
    >
      <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse shrink-0" />
      <span>PROVISIONAL</span>
      <span className="opacity-70 text-[10px]">({executionMode || 'SIMULATED'})</span>
    </span>
  );
};
