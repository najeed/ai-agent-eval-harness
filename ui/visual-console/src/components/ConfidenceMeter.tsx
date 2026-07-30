import React from 'react';

interface ConfidenceMeterProps {
  confidence: number | string;
  className?: string;
}

export const ConfidenceMeter: React.FC<ConfidenceMeterProps> = ({ confidence, className = '' }) => {
  // Translate confidence value to descriptive label and score
  let score = 0.0;
  let label = 'Inconclusive';
  let color = 'bg-slate-500';

  if (typeof confidence === 'string') {
    const val = confidence.toUpperCase();
    if (val === 'CERTAIN' || val === '1.0' || val === '1') {
      score = 1.0;
      label = 'Certain';
    } else if (val === 'HIGH' || val === '0.95') {
      score = 0.95;
      label = 'High';
    } else if (val === 'MEDIUM_HIGH' || val === '0.85') {
      score = 0.85;
      label = 'Med-High';
    } else if (val === 'MEDIUM' || val === '0.7') {
      score = 0.7;
      label = 'Medium';
    } else if (val === 'LOW' || val === '0.5') {
      score = 0.5;
      label = 'Low';
    } else if (val === 'WEAK' || val === '0.3') {
      score = 0.3;
      label = 'Weak';
    } else {
      score = 0.1;
      label = 'Inconclusive';
    }
  } else {
    score = confidence;
    if (score >= 1.0) label = 'Certain';
    else if (score >= 0.9) label = 'High';
    else if (score >= 0.8) label = 'Med-High';
    else if (score >= 0.6) label = 'Medium';
    else if (score >= 0.4) label = 'Low';
    else if (score >= 0.2) label = 'Weak';
    else label = 'Inconclusive';
  }

  // Set colors based on label
  if (label === 'Certain' || label === 'High') {
    color = 'bg-indigo-500 shadow-[0_0_10px_rgba(99,102,241,0.5)]';
  } else if (label === 'Med-High' || label === 'Medium') {
    color = 'bg-cyan-500 shadow-[0_0_10px_rgba(6,182,212,0.5)]';
  } else if (label === 'Low' || label === 'Weak') {
    color = 'bg-amber-500';
  } else {
    color = 'bg-slate-600';
  }

  // Render a segmented bar meter (6 segments)
  const segments = ['Inconclusive', 'Weak', 'Low', 'Medium', 'Med-High', 'Certain'];
  const activeIndex = segments.findIndex((seg) => {
    if (label === 'High' && seg === 'Certain') return true; // Group High with certain for index matching or keep separate
    if (label === 'Med-High' && seg === 'Med-High') return true;
    return seg === label;
  });

  return (
    <div className={`flex flex-col gap-1 min-w-[120px] ${className}`}>
      <div className="flex justify-between items-center text-[10px] font-mono text-slate-400">
        <span>Confidence</span>
        <span className="font-bold text-slate-200 uppercase tracking-wider">{label} ({score.toFixed(2)})</span>
      </div>
      <div className="flex gap-1 h-1.5 w-full bg-slate-950 p-0.5 rounded border border-slate-900">
        {segments.map((seg, i) => {
          const isActive = i <= (activeIndex === -1 ? 0 : activeIndex);
          return (
            <div
              key={seg}
              className={`flex-1 rounded-sm transition-all duration-300 ${
                isActive ? color : 'bg-slate-800'
              }`}
              title={seg}
            />
          );
        })}
      </div>
    </div>
  );
};
