import { useEffect, useState } from 'react';

export interface ReportProfileOption {
  id: string;
  label: string;
  description?: string;
  href: string;
}

export interface RunReportAction {
  href: string;
  label: string;
  mode: 'basic' | 'governed';
  profiles: ReportProfileOption[];
}

const basic = (runId?: string): RunReportAction => {
  const href = runId ? `/api/v1/runs/${encodeURIComponent(runId)}/report.pdf` : '#';
  return {
    href,
    label: 'Download Basic Run Report (PDF)',
    mode: 'basic',
    profiles: [
      {
        id: 'basic',
        label: 'Basic Compliance Report (PDF)',
        description: "Human-readable summary derived from this run's evidence.",
        href,
      },
    ],
  };
};

export function useRunReportAction(runId: string | undefined): RunReportAction {
  const [action, setAction] = useState<RunReportAction>(basic(runId));

  useEffect(() => {
    if (!runId) {
      setAction(basic(undefined));
      return;
    }
    const fallback = basic(runId);
    setAction(fallback);
    let cancelled = false;

    const applyPayload = (data: any): boolean => {
      if (data?.mode === 'governed' && typeof data.download_url === 'string') {
        const profiles: ReportProfileOption[] = Array.isArray(data.profiles) && data.profiles.length > 0
          ? data.profiles
          : [
              {
                id: 'executive',
                label: data.label || 'Executive Assurance Brief (PDF)',
                description: 'One-page outcome, scope, critical findings, and release eligibility.',
                href: data.download_url,
              },
            ];
        if (!cancelled) {
          setAction({
            href: data.download_url,
            label: data.label || 'Download Executive Assurance Brief (PDF)',
            mode: 'governed',
            profiles,
          });
        }
        return true;
      }
      return false;
    };

    fetch(`/api/v1/runs/${encodeURIComponent(runId)}/report-actions`)
      .then(async (res) => (res.ok ? res.json() : null))
      .then(async (data) => {
        if (applyPayload(data)) return;
        const entRes = await fetch(`/api/enterprise/reports/run-action?run_id=${encodeURIComponent(runId)}`);
        if (entRes.ok) {
          applyPayload(await entRes.json());
        }
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
    };
  }, [runId]);

  return action;
}
