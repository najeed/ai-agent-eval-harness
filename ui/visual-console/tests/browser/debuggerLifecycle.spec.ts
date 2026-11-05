import { expect, test, type Page } from '@playwright/test';

const scenario = { workflow: { nodes: [{ id: 'review' }] } };

async function setup(page: Page, providerStatus = 'RUNNING') {
  const provider = { status: providerStatus, offline: false, reads: 0 };
  await page.route('**/api/status', route => route.fulfill({ json: { status: 'ok' } }));
  await page.route('**/api/nav', route => route.fulfill({ json: { items: [] } }));
  await page.route('**/api/auth/me', route => route.fulfill({ json: { user: { id: 'test', permissions: ['debugger:read'] } } }));
  await page.route('**/api/runs', route => route.fulfill({ json: { runs: [{ run_id: 'lifecycle' }] } }));
  await page.route('**/api/v1/runs/lifecycle', route => {
    provider.reads++;
    return route.fulfill({ status: provider.offline ? 503 : 200, json: { status: provider.status, scenario } });
  });
  await page.addInitScript(() => {
    (window as any).streams = [];
    class ControlledEventSource {
      onmessage: any; onerror: any; onopen: any;
      constructor(public url: string) {
        (window as any).streams.push(this);
        setTimeout(() => this.onopen?.(), 0);
      }
      close() {}
    }
    (window as any).EventSource = ControlledEventSource;
  });
  await page.goto('/debugger?run_id=lifecycle');
  await expect.poll(() => page.evaluate(() => (window as any).streams.length)).toBeGreaterThan(0);
  await expect(page.getByText('Topology: CANONICAL')).toBeVisible();
  return provider;
}

async function emit(page: Page, frames: Record<string, unknown>[]) {
  await page.evaluate(frames => {
    const stream = (window as any).streams.at(-1);
    for (const frame of frames) stream.onmessage({ data: JSON.stringify(frame), lastEventId: String(frame.cursor ?? frame._seq) });
  }, frames);
}
async function close(page: Page) {
  await page.evaluate(() => (window as any).streams.at(-1).onerror());
}

for (const reopened of [false, true]) {
  test(`historical pause is superseded on ${reopened ? 'reopened completed' : 'live'} run`, async ({ page }) => {
    const provider = await setup(page, reopened ? 'COMPLETED' : 'RUNNING');
    await emit(page, [{ event: 'run_start', _seq: 1 }, { event: 'hitl_pause', _seq: 39 }]);
    if (!reopened) await expect(page.getByText('PAUSED_FOR_APPROVAL', { exact: true })).toBeVisible();
    await emit(page, [{ event: 'run_start', _seq: 40 }]);
    if (!reopened) await expect(page.getByText('RUNNING', { exact: true })).toBeVisible();
    await emit(page, [{ event: 'run_end', _seq: 74, status: 'success' }]);
    provider.status = 'COMPLETED';
    const reads = provider.reads;
    await close(page);
    await expect(page.getByText('COMPLETED', { exact: true })).toBeVisible();
    await expect(page.getByText('FINISHED', { exact: true })).toBeVisible();
    await expect.poll(() => provider.reads).toBeGreaterThan(reads);
    // Delivery gaps remain visible despite a successful lifecycle.
    await expect(page.getByText(/Trace: .*PARTIAL/)).toBeVisible();
    await expect(page.getByText(/Trace: .*NO_END/)).toHaveCount(0);
  });
}

test('genuine pending approval survives closure and historical duplicates do not regress resume', async ({ page }) => {
  const provider = await setup(page);
  await emit(page, [{ event: 'run_start', _seq: 1 }, { event: 'hitl_pause', _seq: 2 }, { event: 'run_start', _seq: 3 }]);
  await emit(page, [{ event: 'hitl_pause', _seq: 2 }, { event: 'hitl_pause', _seq: 2, cursor: 4 }]);
  await expect(page.getByText('RUNNING', { exact: true })).toBeVisible();
  await emit(page, [{ event: 'hitl_pause', _seq: 4, cursor: 5 }]);
  provider.status = 'PAUSED_FOR_APPROVAL';
  await close(page);
  await expect(page.getByText('PAUSED_FOR_APPROVAL', { exact: true })).toBeVisible();
  await expect(page.getByText('FINISHED', { exact: true })).toBeVisible();
});

for (const [outcome, canonical] of [['failed', 'FAILED'], ['canceled', 'CANCELLED']]) {
  test(`${outcome} terminal cannot be replaced by old pauses or a stale running provider`, async ({ page }) => {
    await setup(page);
    await emit(page, [{ event: 'run_start', _seq: 1 }, { event: 'run_end', _seq: 3, status: outcome }, { event: 'hitl_pause', _seq: 2 }]);
    await close(page);
    await expect(page.getByText(canonical, { exact: true })).toBeVisible();
    await expect(page.getByText('FINISHED', { exact: true })).toBeVisible();
  });
}

test('provider completion and truncated trace remain distinct', async ({ page }) => {
  await setup(page, 'COMPLETED');
  await emit(page, [{ event: 'run_start', _seq: 1 }]);
  await expect(page.getByText(/Trace: AWAITING_END/)).toBeVisible();
  await close(page);
  await expect(page.getByText('COMPLETED', { exact: true })).toBeVisible();
  await expect(page.getByText('Trace: NO_END', { exact: true })).toBeVisible();
});

test('provider outage preserves terminal evidence and reports unavailability', async ({ page }) => {
  const provider = await setup(page);
  await emit(page, [{ event: 'run_start', _seq: 1 }, { event: 'run_end', _seq: 2, status: 'success' }]);
  provider.offline = true;
  await close(page);
  await expect(page.getByText('COMPLETED', { exact: true })).toBeVisible();
  await expect(page.getByText('Provider unavailable', { exact: true })).toBeVisible();
  await expect(page.getByText('Trace: COMPLETE', { exact: true })).toBeVisible();
});

test('provider outage during execution reconnects and ignores stale connection frames', async ({ page }) => {
  const provider = await setup(page);
  await emit(page, [{ event: 'run_start', _seq: 1 }]);
  provider.offline = true;
  await close(page);
  await expect(page.getByText('Provider unavailable', { exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => (window as any).streams.length)).toBeGreaterThan(1);
  await emit(page, [{ event: 'run_start', _seq: 2 }]);
  await page.evaluate(() => (window as any).streams[0].onmessage({ data: JSON.stringify({ event: 'hitl_pause', _seq: 99 }), lastEventId: '99' }));
  await expect(page.getByText('RUNNING', { exact: true })).toBeVisible();
});


test('native EventSource EOF reconciles a pause-resume-success trace', async ({ page }) => {
  await page.route('**/api/status', route => route.fulfill({ json: { status: 'ok' } }));
  await page.route('**/api/nav', route => route.fulfill({ json: { items: [] } }));
  await page.route('**/api/auth/me', route => route.fulfill({ json: { authenticated: true, user: { id: 'test', permissions: ['debugger:read'] } } }));
  await page.route('**/api/runs', route => route.fulfill({ json: { runs: [{ run_id: 'native' }] } }));
  let status = 'RUNNING';
  let reads = 0;
  await page.route('**/api/v1/runs/native', route => {
    reads++;
    return route.fulfill({ json: { status, scenario } });
  });
  await page.route('**/api/v1/runs/native/stream**', route => {
    status = 'COMPLETED';
    return route.fulfill({ contentType: 'text/event-stream', body: [
      { event: 'run_start', _seq: 1 }, { event: 'hitl_pause', _seq: 2 },
      { event: 'run_start', _seq: 3 }, { event: 'run_end', _seq: 4, status: 'success' },
    ].map(frame => `id: ${frame._seq}\ndata: ${JSON.stringify(frame)}\n\n`).join('') });
  });
  await page.goto('/debugger?run_id=native');
  await expect(page.getByText('COMPLETED', { exact: true })).toBeVisible();
  await expect(page.getByText('FINISHED', { exact: true })).toBeVisible();
  await expect(page.getByText('Trace: COMPLETE', { exact: true })).toBeVisible();
  expect(reads).toBeGreaterThanOrEqual(3);
});
