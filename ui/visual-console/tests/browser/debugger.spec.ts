import { expect, test } from '@playwright/test';

test('debugger renders canonical workflow nodes and edges', async ({ page }) => {
  const scenario = {
    workflow: {
      nodes: [{ id: 'intake' }, { id: 'review' }, { id: 'notify' }],
      edges: [{ from: 'intake', to: 'review' }, { from: 'review', to: 'notify' }],
    },
  };
  await page.route('**/api/status', route => route.fulfill({ json: { status: 'ok' } }));
  await page.route('**/api/nav', route => route.fulfill({ json: { items: [] } }));
  await page.route('**/api/auth/me', route => route.fulfill({ json: { user: { id: 'test', roles: ['admin'] } } }));
  await page.route('**/api/runs', route => route.fulfill({ json: { runs: [{ run_id: 'test-run' }] } }));
  await page.route('**/api/v1/runs/test-run', route => route.fulfill({ json: { status: 'COMPLETED', scenario } }));
  await page.route('**/api/v1/runs/test-run/stream**', route => route.fulfill({
    contentType: 'text/event-stream',
    body: [
      `id: 1\ndata: ${JSON.stringify({ event: 'run_start', _seq: 1, scenario_data: scenario })}\n\n`,
      'id: 2\ndata: {"event":"execution_graph_node","_seq":2,"scenario_node_id":"intake","status":"completed"}\n\n',
      'id: 3\ndata: {"event":"execution_graph_node","_seq":3,"scenario_node_id":"review","status":"completed"}\n\n',
      'id: 4\ndata: {"event":"execution_graph_node","_seq":4,"scenario_node_id":"notify","status":"completed"}\n\n',
    ].join(''),
  }));
  await page.goto('/debugger?run_id=test-run');
  await expect(page.getByText('Topology: CANONICAL')).toBeVisible();
  await page.getByRole('button', { name: 'planned' }).click();
  await expect(page.locator('.react-flow__node').first()).toBeVisible();
  // ReactFlow edges are SVG <g> containers, for which Playwright's layout
  // visibility heuristic is unreliable.  Assert the canonical edges mounted.
  await expect(page.locator('.react-flow__edge')).toHaveCount(2);
});
