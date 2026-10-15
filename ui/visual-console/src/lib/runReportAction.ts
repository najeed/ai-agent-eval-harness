import { useEffect, useState } from 'react';

export interface RunReportAction {
  href: string;
  label: string;
  mode: 'basic' | 'governed';
}

const basic = (runId?: string): RunReportAction => ({
  href: runId ? `/api/v1/runs/${encodeURIComponent(runId)}/report.pdf` : '#',
  label: 'Download Basic Run Report (PDF)',
  mode: 'basic',
});

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
    fetch(`/api/enterprise/reports/run-action?run_id=${encodeURIComponent(runId)}`)
      .then(async (response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (!cancelled && data?.mode === 'governed' && typeof data.download_url === 'string') {
          setAction({
            href: data.download_url,
            label: data.label || 'Download Compliance Report (PDF)',
            mode: 'governed',
          });
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [runId]);

  return action;
}
