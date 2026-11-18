import { expect, test } from '@playwright/test';

for (const mode of ['signature_failure', 'certified', 'invalid', 'absent'] as const) {
  test(`policy audit distinguishes ${mode} from absent evidence`, async ({ page }) => {
    const policy = { oracle_id: 'policy:human_review_before_adverse_commit',
      scenario_node_id: 'physician_review', requiredness: 'REQUIRED',
      outcome: mode === 'invalid' ? 'INVALID' : 'PASS' };
    const frames = [
      ...(mode === 'absent' ? [] : [{ event: 'execution_graph_node', scenario_node_id: 'physician_review', oracle_results: [policy] }]),
      { event: 'execution_graph_node', data: { scenario_node_id: 'notify_provider', oracle_results: [{ oracle_id: 'notification:sent', outcome: 'PASS' }] } },
      { event: 'run_end' },
    ];
    const verified = mode === 'certified' || mode === 'absent';
    await page.route('**/api/**', route => {
      const path = new URL(route.request().url()).pathname;
      const payload = path === '/api/auth/me'
        ? { authenticated: true, user: { id: 'test', permissions: ['*'] } }
        : path === '/api/runs'
          ? { runs: [{ run_id: 'policy-audit', status: 'COMPLETED', execution_mode: 'live' }] }
          : path.endsWith('/verify')
            ? { is_valid: verified, certificate_authoritative: verified, has_certificate: true, verification_status: verified ? 'VERIFIED' : 'FAILED_VERIFICATION',
              failures: verified ? [] : ["EnvelopeSignatureVerificationFailed: 'system_id'"] }
            : path.includes('/evidence/packages/')
              ? { evidence_chain_valid: verified, cryptographic_verification: {
                verified, authority_valid: verified, has_certificate: true,
                errors: verified ? [] : ["EnvelopeSignatureVerificationFailed: 'system_id'"],
              }, verdict: { assertions: verified && mode !== 'absent' ? [policy] : [] } }
              : { status: 'ok', nav: [], profiles: [] };
      return route.fulfill({ json: payload });
    });
    await page.addInitScript(frames => {
      class FixtureEventSource {
        onmessage: ((event: { data: string }) => void) | null = null;
        onerror = null;
        constructor() {
          setTimeout(() => { for (const frame of frames) this.onmessage?.({ data: JSON.stringify(frame) }); }, 50);
        }
        close() {}
      }
      (window as any).EventSource = FixtureEventSource;
    }, frames);
    await page.goto('/runs?run_id=policy-audit');
    await page.getByRole('button', { name: 'Policy & Guardrails' }).click();
    if (mode === 'signature_failure' || mode === 'invalid') {
      await expect(page.getByTestId('policy-state-verification_failed')).toBeVisible();
      await expect(page.getByTestId('policy-observation')).toHaveCount(1);
      await expect(page.getByTestId('policy-observation')).toContainText(mode === 'invalid' ? 'OBSERVED INVALID' : 'OBSERVED PASS');
      await expect(page.getByRole('alert').filter({ hasText: 'EnvelopeSignatureVerificationFailed' })).toBeVisible();
      await expect(page.getByText('PASS — Authoritative Policy Evidence Verified', { exact: true })).toHaveCount(0);
      await expect(page.getByText(/POLICY BREACH DETECTED/)).toHaveCount(0);
    } else if (mode === 'certified') {
      await expect(page.getByText('PASS — Authoritative Policy Evidence Verified', { exact: true })).toBeVisible();
      await expect(page.getByTestId('policy-observation')).toHaveCount(1);
    } else {
      await expect(page.getByTestId('policy-state-absent')).toContainText('NOT VERIFIED / NO POLICY CHECKS RECORDED');
    }
  });
}
