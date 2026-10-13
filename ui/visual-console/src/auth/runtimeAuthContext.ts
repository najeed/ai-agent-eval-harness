/** Core Runtime authentication read-model and context-switch client.
 *
 * This module deliberately never accepts org or tenant identifiers from a
 * caller.  Runtime remains the authority for resolving those values.
 */
export interface AuthorizedContext {
  org_id: string;
  tenant_id: string;
  workspace_id: string;
  environments: string[];
}

export interface RuntimeAuthContext {
  context_version: string;
  context: {
    org_id: string;
    tenant_id: string;
    workspace_id: string;
    active_environment: string;
  } | null;
  authorized_contexts: AuthorizedContext[];
}

interface RuntimeAuthResponse extends RuntimeAuthContext {
  authenticated?: boolean;
  user?: Record<string, unknown> | null;
}

let handoffCredentials: string | null = null;

export function clearRuntimeAuthCaches(): void {
  handoffCredentials = null;
}

async function readJson(response: Response): Promise<RuntimeAuthResponse> {
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) clearRuntimeAuthCaches();
    throw new Error(`Runtime authentication request failed (${response.status})`);
  }
  return response.json() as Promise<RuntimeAuthResponse>;
}

export async function getRuntimeAuthContext(): Promise<RuntimeAuthContext> {
  const payload = await readJson(await fetch('/api/auth/me'));
  if (!payload.authenticated) {
    clearRuntimeAuthCaches();
    throw new Error('Runtime authentication required');
  }
  return {
    context_version: payload.context_version,
    context: payload.context,
    authorized_contexts: payload.authorized_contexts || [],
  };
}

export async function switchRuntimeContext(
  workspaceId: string,
  activeEnvironment: string,
): Promise<RuntimeAuthContext> {
  const response = await fetch('/api/auth/context', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace_id: workspaceId, active_environment: activeEnvironment }),
  });
  await readJson(response);
  // A successful switch invalidates context-bound extension credentials.
  clearRuntimeAuthCaches();
  return getRuntimeAuthContext();
}

export async function logoutRuntimeAuth(): Promise<void> {
  try {
    await fetch('/api/auth/logout', { method: 'POST' });
  } finally {
    clearRuntimeAuthCaches();
  }
}

/** Generic extension helper; no extension route or tenant data is involved. */
export async function getRuntimeHandoff(pluginId: string): Promise<string> {
  const payload = await readJson(await fetch('/api/auth/handoff', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ plugin_id: pluginId }),
  })) as RuntimeAuthResponse & { token?: string };
  if (!payload.token) throw new Error('Runtime did not issue a handoff token');
  handoffCredentials = payload.token;
  return handoffCredentials;
}
