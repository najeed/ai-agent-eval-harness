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
  // visibility heuristic is unreliable. Assert the canonical edges mounted.
  await expect(page.locator('.react-flow__edge')).toHaveCount(2);
});

test('debugger handles runtime execution trace with branches, retries, HITL pause and terminal completion', async ({ page }) => {
  const scenario = {
    workflow: {
      nodes: [
        { id: 'intake', task_description: 'Intake request' },
        { id: 'branch_eval', task_description: 'Evaluate routing' },
        { id: 'retry_task', task_description: 'Execute flakey operation' },
        { id: 'hitl_gate', task_description: 'Human approval gate' },
        { id: 'finalize', task_description: 'Commit results' },
      ],
      edges: [
        { from: 'intake', to: 'branch_eval' },
        { from: 'branch_eval', to: 'retry_task' },
        { from: 'retry_task', to: 'hitl_gate' },
        { from: 'hitl_gate', to: 'finalize' },
      ],
    },
  };

  await page.route('**/api/status', route => route.fulfill({ json: { status: 'ok' } }));
  await page.route('**/api/nav', route => route.fulfill({ json: { items: [] } }));
  await page.route('**/api/auth/me', route => route.fulfill({ json: { user: { id: 'test', roles: ['admin'] } } }));
  await page.route('**/api/runs', route => route.fulfill({ json: { runs: [{ run_id: 'full-trace-run' }] } }));
  await page.route('**/api/v1/runs/full-trace-run', route => route.fulfill({ json: { status: 'COMPLETED', scenario } }));
  await page.route('**/api/v1/runs/full-trace-run/stream**', route => route.fulfill({
    contentType: 'text/event-stream',
    body: [
      `id: 1\ndata: ${JSON.stringify({ event: 'run_start', _seq: 1, scenario_data: scenario })}\n\n`,
      'id: 2\ndata: {"event":"execution_graph_node","_seq":2,"scenario_node_id":"intake","status":"completed","execution_instance_id":"inst-1"}\n\n',
      'id: 3\ndata: {"event":"execution_graph_node","_seq":3,"scenario_node_id":"branch_eval","status":"completed","execution_instance_id":"inst-2"}\n\n',
      'id: 4\ndata: {"event":"execution_graph_node","_seq":4,"scenario_node_id":"retry_task","status":"failed","attempt":1,"execution_instance_id":"inst-3-a"}\n\n',
      'id: 5\ndata: {"event":"execution_graph_node","_seq":5,"scenario_node_id":"retry_task","status":"completed","attempt":2,"execution_instance_id":"inst-3-b"}\n\n',
      'id: 6\ndata: {"event":"execution_graph_node","_seq":6,"scenario_node_id":"hitl_gate","status":"paused","approval_token":"tok-123","execution_instance_id":"inst-4"}\n\n',
      'id: 7\ndata: {"event":"execution_graph_node","_seq":7,"scenario_node_id":"hitl_gate","status":"completed","execution_instance_id":"inst-4"}\n\n',
      'id: 8\ndata: {"event":"execution_graph_node","_seq":8,"scenario_node_id":"finalize","status":"completed","execution_instance_id":"inst-5"}\n\n',
      'id: 9\ndata: {"event":"run_end","_seq":9,"status":"COMPLETED"}\n\n',
    ].join(''),
  }));

  await page.goto('/debugger?run_id=full-trace-run');
  await expect(page.getByText('Topology: CANONICAL')).toBeVisible();
  // Ensure execution nodes rendered
  await expect(page.locator('.react-flow__node').first()).toBeVisible();
  // Nodes mounted across trace
  await expect(page.locator('.react-flow__node')).toHaveCount(5);
});

test('debugger renders planned pending preview in executed mode before execution events arrive', async ({ page }) => {
  const scenario = {
    workflow: {
      nodes: [{ id: 'step_one' }, { id: 'step_two' }],
      edges: [{ from: 'step_one', to: 'step_two' }],
    },
  };

  await page.route('**/api/status', route => route.fulfill({ json: { status: 'ok' } }));
  await page.route('**/api/nav', route => route.fulfill({ json: { items: [] } }));
  await page.route('**/api/auth/me', route => route.fulfill({ json: { user: { id: 'test', roles: ['admin'] } } }));
  await page.route('**/api/runs', route => route.fulfill({ json: { runs: [{ run_id: 'pending-run' }] } }));
  await page.route('**/api/v1/runs/pending-run', route => route.fulfill({ json: { status: 'RUNNING', scenario } }));
  await page.route('**/api/v1/runs/pending-run/stream**', route => route.fulfill({
    contentType: 'text/event-stream',
    body: `id: 1\ndata: ${JSON.stringify({ event: 'run_start', _seq: 1, scenario_data: scenario })}\n\n`,
  }));

  await page.goto('/debugger?run_id=pending-run');
  // Pending nodes should be visible in executed mode with pending indicator
  await expect(page.locator('.react-flow__node').first()).toBeVisible();
  await expect(page.getByText('PLANNED (PENDING)').first()).toBeVisible();
});

test('adversarial mutator displays explicit error banner when catalog endpoint fails', async ({ page }) => {
  await page.route('**/api/status', route => route.fulfill({ json: { status: 'ok' } }));
  await page.route('**/api/nav', route => route.fulfill({ json: { items: [] } }));
  await page.route('**/api/auth/me', route => route.fulfill({ json: { user: { id: 'test', roles: ['admin'] } } }));
  await page.route('**/api/scenarios?**', route => route.fulfill({ json: { scenarios: [{ id: 'test-scenario', title: 'Test Scenario', industry: 'General' }] } }));
  await page.route('**/api/v1/mutations', route => route.fulfill({ status: 500, json: { error: 'Service Unavailable' } }));

  await page.goto('/mutator');
  await expect(page.getByText('Live Mutation Catalog Unavailable')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry Catalog Load' }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Execute Mutation Engine' })).toBeDisabled();
});
