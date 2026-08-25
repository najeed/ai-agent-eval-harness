/**
 * TypeScript mirror of eval_runner.console.routes.agent_targets ([G3]
 * reusable Agent Target entity, schema version 1.0.0 — additive-only
 * within 1.x).
 *
 * A target is a connect-once connection profile: the server persists it,
 * probes reachability on demand, and every scenario launch can reference
 * the same entity. Credentials are NEVER part of this contract — secret
 * fields are rejected by the server.
 */

export const AGENT_TARGETS_SCHEMA_VERSION = '1.0.0';

export const AGENT_TARGET_PROTOCOLS = [
  'http_rest',
  'http',
  'sse',
  'ollama',
  'openai',
  'anthropic',
  'claude',
  'gemini',
  'custom_http',
  'grpc',
  'in_process',
  'local',
] as const;

export type AgentTargetProtocol = (typeof AGENT_TARGET_PROTOCOLS)[number];

/** Server-persisted reusable agent target entity. */
export interface AgentTarget {
  id: string;
  name: string;
  protocol: AgentTargetProtocol | string;
  endpoint: string;
  model: string;
  max_turns: number;
  timeout_seconds: number;
  created_at: string;
  updated_at: string;
}

/** Payload for POST /api/v1/agent-targets (create or update). */
export interface AgentTargetInput {
  id?: string;
  name: string;
  protocol: AgentTargetProtocol | string;
  endpoint: string;
  model?: string;
  max_turns?: number;
  timeout_seconds?: number;
}

/**
 * Reachability test result. Truthful tiers only:
 *   - REACHABLE: a real probe succeeded.
 *   - CONFIGURED: structurally valid but not proven reachable
 *     (e.g. missing credential, in-process target).
 *   - UNREACHABLE: the probe actively failed.
 */
export type ReachabilityTier = 'REACHABLE' | 'CONFIGURED' | 'UNREACHABLE';

export interface AgentTargetTestResult {
  id?: string;
  reachable: boolean;
  tier: ReachabilityTier;
  latency_ms: number;
  message: string;
}

export function isAgentTarget(value: unknown): value is AgentTarget {
  if (!value || typeof value !== 'object') return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.id === 'string' &&
    typeof v.name === 'string' &&
    typeof v.protocol === 'string' &&
    typeof v.endpoint === 'string' &&
    typeof v.created_at === 'string' &&
    typeof v.updated_at === 'string'
  );
}
