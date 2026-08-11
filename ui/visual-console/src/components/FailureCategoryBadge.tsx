import React from 'react';

interface FailureCategoryBadgeProps {
  category: string;
  className?: string;
}

export const FailureCategoryBadge: React.FC<FailureCategoryBadgeProps> = ({ category, className = '' }) => {
  const cat = category.toUpperCase().replace(/_/g, ' ');

  // Mapping taxonomy families to their corresponding visual representations
  let family = 'Unknown';
  let colorClasses = 'bg-slate-500/10 border-slate-500/25 text-slate-400';

  if (
    cat.includes('TIMEOUT') ||
    cat.includes('OOM') ||
    cat.includes('SANDBOX') ||
    cat.includes('RESOURCE') ||
    cat.includes('INFRA')
  ) {
    family = 'Infra';
    colorClasses = 'bg-indigo-500/10 border-indigo-500/20 text-indigo-300';
  } else if (
    cat.includes('STALL') ||
    cat.includes('PLANNING') ||
    cat.includes('STATE_MISMATCH') ||
    cat.includes('OBJECTIVE') ||
    cat.includes('ABANDONMENT') ||
    cat.includes('LOGIC')
  ) {
    family = 'Logic';
    colorClasses = 'bg-amber-500/10 border-amber-500/20 text-amber-300';
  } else if (
    cat.includes('VIOLATION') ||
    cat.includes('HALLUCINATION') ||
    cat.includes('STALENESS') ||
    cat.includes('POLICY')
  ) {
    family = 'Policy';
    colorClasses = 'bg-violet-500/10 border-violet-500/20 text-violet-300';
  } else if (
    cat.includes('PII') ||
    cat.includes('UNAUTHORIZED') ||
    cat.includes('ESCAPE') ||
    cat.includes('HITL_FAILURE') ||
    cat.includes('SECURITY') ||
    cat.includes('PARITY') ||
    cat.includes('PROTOCOL')
  ) {
    family = 'Security';
    colorClasses = 'bg-rose-500/10 border-rose-500/20 text-rose-300';
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-semibold border ${colorClasses} ${className}`}
      title={`Failure Family: ${family}`}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current opacity-75 shrink-0" />
      <span>{category}</span>
    </span>
  );
};
