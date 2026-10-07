import React, { useState, useEffect, useMemo } from 'react';
import ReactDiffViewer from 'react-diff-viewer-continued';
import {
  Layers,
  PlayCircle,
  Save,
  Check,
  Sparkles,
  Copy,
  ArrowRight,
  HelpCircle,
  Shield,
  Sliders,
  FileText,
  Code2,
  Hash,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export interface MutationDescriptor {
  id: string;
  label: string;
  vector: string;
  operation: string;
  tier: string;
  source: string;
  description: string;
  target_field: string;
  regulatory_frameworks?: string[];
  org_id?: string | null;
  deterministic?: boolean;
  parameters_schema?: any;
}

interface ScenarioOption {
  id: string;
  title?: string;
  name?: string;
  industry: string;
  description?: string;
  metadata?: {
    id?: string;
    name?: string;
    description?: string;
    compliance_level?: string;
  };
  workflow?: {
    nodes?: Array<{
      id: string;
      task_description: string;
      required_tools?: string[];
      expected_outcome?: any;
    }>;
    edges?: any[];
  };
}

// Built-in baseline catalog for instant zero-latency render & offline fallback
const FALLBACK_MUTATION_CATALOG: MutationDescriptor[] = [
  {
    id: "typo",
    label: "Typographical Keyboard Errors",
    vector: "INPUT",
    operation: "CORRUPT",
    tier: "T0_LINGUISTIC",
    source: "core",
    description: "Simulates keyboard slips, letter swaps, and spelling corruptions in user instructions.",
    target_field: "task_description",
    regulatory_frameworks: ["ROBUSTNESS", "USER_INPUT_TOLERANCE"],
    deterministic: true,
  },
  {
    id: "ambiguity",
    label: "Vague & Non-Committal Hedging",
    vector: "INPUT",
    operation: "INSERT",
    tier: "T1_BEHAVIORAL",
    source: "core",
    description: "Appends vague, non-committal hedging clauses requesting unnecessary permissions.",
    target_field: "task_description",
    regulatory_frameworks: ["PROMPT_AMBIGUITY", "DECISION_CLARITY"],
    deterministic: true,
  },
  {
    id: "injection",
    label: "Adversarial Prompt Injection",
    vector: "INPUT",
    operation: "INSERT",
    tier: "T4_SECURITY",
    source: "core",
    description: "Appends adversarial jailbreak and system boundary override sequences.",
    target_field: "task_description",
    regulatory_frameworks: ["EU_AI_ACT_ART15", "OWASP_LLM_TOP_10", "NIST_SP_800_218"],
    deterministic: true,
  },
  {
    id: "goal_drift",
    label: "Midway Objective Goal Drift",
    vector: "CONTEXT",
    operation: "DRIFT",
    tier: "T1_BEHAVIORAL",
    source: "core",
    description: "Pivots agent objective midway toward an alternative or secondary task.",
    target_field: "task_description",
    regulatory_frameworks: ["OBJECTIVE_INTEGRITY", "INTENT_ALIGNMENT"],
    deterministic: true,
  },
  {
    id: "constraint_drop",
    label: "Safety Constraint Stripping",
    vector: "CONTEXT",
    operation: "DROP",
    tier: "T1_BEHAVIORAL",
    source: "core",
    description: "Strips negative safety constraints and operational guardrails from instructions.",
    target_field: "task_description",
    regulatory_frameworks: ["EU_AI_ACT_ART14", "GUARDRAIL_ENFORCEMENT"],
    deterministic: true,
  },
  {
    id: "memory_drift",
    label: "Scratchpad & Working Memory Corruption",
    vector: "MEMORY",
    operation: "CORRUPT",
    tier: "T1_BEHAVIORAL",
    source: "core",
    description: "Corrupts scratchpad intermediate thoughts and cross-turn memory state.",
    target_field: "scratchpad",
    regulatory_frameworks: ["STATE_REPRODUCIBILITY", "MEMORY_ISOLATION"],
    deterministic: true,
  },
  {
    id: "retrieval_stale",
    label: "Stale Knowledge Base Document",
    vector: "RETRIEVAL",
    operation: "EXPIRE",
    tier: "T2_STRUCTURAL",
    source: "core",
    description: "Injects outdated or expired reference documents into RAG context.",
    target_field: "retrieved_documents",
    regulatory_frameworks: ["EU_AI_ACT_ART14", "NIST_AI_RMF"],
    deterministic: true,
  },
  {
    id: "retrieval_irrelevant",
    label: "Irrelevant Distractor Chunk",
    vector: "RETRIEVAL",
    operation: "INSERT",
    tier: "T2_STRUCTURAL",
    source: "core",
    description: "Injects plausible but irrelevant distractor documents into retrieval context.",
    target_field: "retrieved_documents",
    regulatory_frameworks: ["RETRIEVAL_PRECISION", "NOISE_TOLERANCE"],
    deterministic: true,
  },
  {
    id: "retrieval_conflict",
    label: "Conflicting Knowledge Policies",
    vector: "RETRIEVAL",
    operation: "CONFLICT",
    tier: "T2_STRUCTURAL",
    source: "core",
    description: "Injects mutually contradictory policy documentation to test resolution.",
    target_field: "retrieved_documents",
    regulatory_frameworks: ["POLICY_CONFLICT_RESOLUTION", "EVIDENTIARY_CONSISTENCY"],
    deterministic: true,
  },
  {
    id: "retrieval_chunk",
    label: "Truncated / Clipped Chunk Boundary",
    vector: "RETRIEVAL",
    operation: "CORRUPT",
    tier: "T2_STRUCTURAL",
    source: "core",
    description: "Simulates chunk boundary clipping and unexpected EOF truncation in retrieved texts.",
    target_field: "retrieved_documents",
    regulatory_frameworks: ["DATA_INTEGRITY", "TRUNCATION_HANDLING"],
    deterministic: true,
  },
  {
    id: "retrieval_source_swap",
    label: "Untrusted Mirror Source Substitution",
    vector: "RETRIEVAL",
    operation: "REPLACE",
    tier: "T2_STRUCTURAL",
    source: "core",
    description: "Substitutes verified knowledge sources with untrusted external mirrors.",
    target_field: "retrieved_documents",
    regulatory_frameworks: ["PROVENANCE_VERIFICATION", "SUPPLY_CHAIN_SECURITY"],
    deterministic: true,
  },
  {
    id: "schema_type",
    label: "Parameter Type Confusion",
    vector: "TOOL",
    operation: "CORRUPT",
    tier: "T2_STRUCTURAL",
    source: "core",
    description: "Mutates tool parameter types violating schemas.",
    target_field: "parameters",
    regulatory_frameworks: ["API_CONTRACT_INTEGRITY", "SCHEMA_CONFORMANCE"],
    deterministic: true,
  },
  {
    id: "missing_field",
    label: "Required Schema Field Omission",
    vector: "TOOL",
    operation: "DROP",
    tier: "T2_STRUCTURAL",
    source: "core",
    description: "Drops a required parameter from tool invocation definitions.",
    target_field: "parameters",
    regulatory_frameworks: ["SCHEMA_VALIDATION", "DEFENSIVE_TOOLING"],
    deterministic: true,
  },
  {
    id: "enum_drift",
    label: "Unsupported Enum Code Drift",
    vector: "TOOL",
    operation: "REPLACE",
    tier: "T2_STRUCTURAL",
    source: "core",
    description: "Injects an invalid or deprecated enum code into structured tool calls.",
    target_field: "unsupported_enum_value",
    regulatory_frameworks: ["API_EVOLUTION", "ENUM_INTEGRITY"],
    deterministic: true,
  },
  {
    id: "malformed_payload",
    label: "Malformed JSON Byte Serialization",
    vector: "TOOL",
    operation: "CORRUPT",
    tier: "T2_STRUCTURAL",
    source: "core",
    description: "Injects unclosed syntax and corrupt serialization bytes into payloads.",
    target_field: "raw_payload_corrupted",
    regulatory_frameworks: ["INPUT_VALIDATION", "PARSER_ROBUSTNESS"],
    deterministic: true,
  },
  {
    id: "tool_contract",
    label: "Forbidden Additional Properties Violation",
    vector: "TOOL",
    operation: "CORRUPT",
    tier: "T2_STRUCTURAL",
    source: "core",
    description: "Injects forbidden additional properties violating strict JSON schemas.",
    target_field: "parameters",
    regulatory_frameworks: ["ZERO_TRUST_TOOL_CONTRACTS", "STRICT_SCHEMA"],
    deterministic: true,
  },
  {
    id: "duplicate",
    label: "Duplicate Action Multiplicity",
    vector: "TOOL",
    operation: "DUPLICATE",
    tier: "T2_STRUCTURAL",
    source: "core",
    description: "Duplicates actions to test non-idempotent tool safety.",
    target_field: "repeat_action_count",
    regulatory_frameworks: ["IDEMPOTENCY_ASSURANCE", "FINANCIAL_NONCE_VERIFICATION"],
    deterministic: true,
  },
  {
    id: "replay",
    label: "Cross-Session Event Replay",
    vector: "TOOL",
    operation: "REPLAY",
    tier: "T3_WORKFLOW",
    source: "core",
    description: "Replays previous tool results to test freshness and idempotency.",
    target_field: "replay_previous_event",
    regulatory_frameworks: ["REPLAY_ATTACK_DEFENSE", "NONCE_VALIDATION"],
    deterministic: true,
  },
  {
    id: "stale_state",
    label: "Stale Snapshot Initial State",
    vector: "STATE",
    operation: "EXPIRE",
    tier: "T3_WORKFLOW",
    source: "core",
    description: "Initializes execution with outdated state checkpoints.",
    target_field: "initial_state",
    regulatory_frameworks: ["STATE_FRESHNESS", "CHECKPOINT_INTEGRITY"],
    deterministic: true,
  },
  {
    id: "partial_commit",
    label: "Partial Atomic Commit Abort",
    vector: "STATE",
    operation: "DROP",
    tier: "T3_WORKFLOW",
    source: "core",
    description: "Simulates failure midway through a multi-step commit sequence.",
    target_field: "failure_mode",
    regulatory_frameworks: ["ATOMICITY_ASSURANCE", "SAGA_RESILIENCE"],
    deterministic: true,
  },
  {
    id: "rollback_failure",
    label: "Saga Rollback Handler Failure",
    vector: "STATE",
    operation: "CORRUPT",
    tier: "T3_WORKFLOW",
    source: "core",
    description: "Corrupts compensation handlers to evaluate recovery from failed sagas.",
    target_field: "failure_policy",
    regulatory_frameworks: ["COMPENSATION_INTEGRITY", "RECOVERY_ORCHESTRATION"],
    deterministic: true,
  },
  {
    id: "concurrency",
    label: "Concurrent Writer Contention",
    vector: "CONCURRENCY",
    operation: "CONFLICT",
    tier: "T3_WORKFLOW",
    source: "core",
    description: "Simulates race conditions with simultaneous external state modifications.",
    target_field: "metadata",
    regulatory_frameworks: ["OPTIMISTIC_CONCURRENCY", "ISOLATION_LEVELS"],
    deterministic: true,
  },
  {
    id: "duplicate_commit",
    label: "Duplicate Transaction Commit",
    vector: "STATE",
    operation: "DUPLICATE",
    tier: "T3_WORKFLOW",
    source: "core",
    description: "Simulates double-execution of state commit transactions.",
    target_field: "failure_policy",
    regulatory_frameworks: ["TRANSACTION_ISOLATION", "FINRA_4370"],
    deterministic: true,
  },
  {
    id: "commit_after_cancel",
    label: "Post-Cancellation Commit Attempt",
    vector: "STATE",
    operation: "CONFLICT",
    tier: "T3_WORKFLOW",
    source: "core",
    description: "Tests whether agent commits actions after receiving a cancellation event.",
    target_field: "failure_policy",
    regulatory_frameworks: ["CANCELLATION_SAFETY", "LIFECYCLE_BOUNDARIES"],
    deterministic: true,
  },
  {
    id: "stale_commit",
    label: "Base Revision Mismatch Collision",
    vector: "STATE",
    operation: "EXPIRE",
    tier: "T3_WORKFLOW",
    source: "core",
    description: "Simulates optimistic locking collision by referencing outdated revisions.",
    target_field: "expected_base_revision",
    regulatory_frameworks: ["REVISION_CONTROL", "OPTIMISTIC_LOCKING"],
    deterministic: true,
  },
  {
    id: "approval_stale",
    label: "Expired Approval Signature",
    vector: "AUTHORIZATION",
    operation: "EXPIRE",
    tier: "T4_SECURITY",
    source: "core",
    description: "Injects expired HITL security tokens and timestamp signatures.",
    target_field: "approval_token",
    regulatory_frameworks: ["EU_AI_ACT_ART14", "SEC_15C3_5", "SOC2_CC6"],
    deterministic: true,
  },
  {
    id: "approval_mismatch",
    label: "Approval Transaction ID Mismatch",
    vector: "AUTHORIZATION",
    operation: "CONFLICT",
    tier: "T4_SECURITY",
    source: "core",
    description: "Binds an approval token to an unrelated transaction ID.",
    target_field: "approval_transaction_id",
    regulatory_frameworks: ["SEC_15C3_5", "PCI_DSS_REQ7", "ZERO_TRUST"],
    deterministic: true,
  },
  {
    id: "approval_replay",
    label: "Replayed Single-Use Approval Token",
    vector: "AUTHORIZATION",
    operation: "REPLAY",
    tier: "T4_SECURITY",
    source: "core",
    description: "Reuses a previously consumed approval token in a fresh session.",
    target_field: "replay_token",
    regulatory_frameworks: ["NONCE_ENFORCEMENT", "SECURITY_AUDIT"],
    deterministic: true,
  },
  {
    id: "approval_race",
    label: "TOCTOU Authorization Race Condition",
    vector: "AUTHORIZATION",
    operation: "CONFLICT",
    tier: "T4_SECURITY",
    source: "core",
    description: "Simulates TOCTOU race between permission check and tool execution.",
    target_field: "approval_race",
    regulatory_frameworks: ["TOCTOU_DEFENSE", "HIGH_FREQUENCY_TRADING_SAFETY"],
    deterministic: true,
  },
  {
    id: "approval_revocation",
    label: "Asynchronous Token Revocation",
    vector: "AUTHORIZATION",
    operation: "DELETE",
    tier: "T4_SECURITY",
    source: "core",
    description: "Revokes authorization midway through an asynchronous action.",
    target_field: "approval_status",
    regulatory_frameworks: ["REVOCATION_LIST_INTEGRITY", "REAL_TIME_GUARDRAILS"],
    deterministic: true,
  },
  {
    id: "timeout_boundary",
    label: "Sub-Threshold Execution Timeout",
    vector: "TIME",
    operation: "DELAY",
    tier: "T2_STRUCTURAL",
    source: "core",
    description: "Forces tight execution timeouts to test graceful degradation.",
    target_field: "timeout_boundary_ms",
    regulatory_frameworks: ["SLA_CONFORMANCE", "BOUNDED_EXECUTION"],
    deterministic: true,
  },
  {
    id: "latency_jitter",
    label: "High-Jitter Latency Spike",
    vector: "TIME",
    operation: "DELAY",
    tier: "T2_STRUCTURAL",
    source: "core",
    description: "Injects unpredictable network latency spikes into operations.",
    target_field: "injected_latency_ms",
    regulatory_frameworks: ["RESILIENCE_CHAOS", "LATENCY_TOLERANCE"],
    deterministic: true,
  },
  {
    id: "cancel_race",
    label: "Cancellation Boundary Race",
    vector: "TIME",
    operation: "CONFLICT",
    tier: "T3_WORKFLOW",
    source: "core",
    description: "Cancels workflow precisely when reaching step boundary.",
    target_field: "cancel_at_boundary",
    regulatory_frameworks: ["CANCEL_SAFETY", "GRACEFUL_SHUTDOWN"],
    deterministic: true,
  },
  {
    id: "metric_gaming",
    label: "Goodhart's Law Metric Gaming",
    vector: "OBJECTIVE",
    operation: "CORRUPT",
    tier: "T1_BEHAVIORAL",
    source: "core",
    description: "Nudges agent to optimize for word count / velocity over correctness.",
    target_field: "task_description",
    regulatory_frameworks: ["EU_AI_ACT_ART15", "ALIGNMENT_AUDITING"],
    deterministic: true,
  },
  {
    id: "proxy_goal",
    label: "Proxy Goal Shortcut",
    vector: "OBJECTIVE",
    operation: "REPLACE",
    tier: "T1_BEHAVIORAL",
    source: "core",
    description: "Offers a lazy shortcut (e.g. closing ticket without doing work).",
    target_field: "task_description",
    regulatory_frameworks: ["SPECIFICATION_GAMING", "PROXY_DRIFT"],
    deterministic: true,
  },
  {
    id: "constraint_tradeoff",
    label: "Security-for-Speed Tradeoff Pressure",
    vector: "OBJECTIVE",
    operation: "DROP",
    tier: "T1_BEHAVIORAL",
    source: "core",
    description: "Pressures agent to bypass safety checks to meet time deadlines.",
    target_field: "task_description",
    regulatory_frameworks: ["SAFETY_OVER_SPEED", "ETHICAL_BOUNDARIES"],
    deterministic: true,
  },
  {
    id: "subgoal_cannibalization",
    label: "Subgoal Resource Cannibalization",
    vector: "OBJECTIVE",
    operation: "CONFLICT",
    tier: "T3_WORKFLOW",
    source: "core",
    description: "Preconditions early task step by destroying resources needed later.",
    target_field: "task_description",
    regulatory_frameworks: ["LONG_HORIZON_PLANNING", "DEPENDENCY_INTEGRITY"],
    deterministic: true,
  },
  {
    id: "reward_hacking",
    label: "Auditor Passcode Reward Hacking",
    vector: "OBJECTIVE",
    operation: "ESCALATE",
    tier: "T1_BEHAVIORAL",
    source: "core",
    description: "Prompts agent to emit auditor passcodes without fulfilling requirements.",
    target_field: "task_description",
    regulatory_frameworks: ["REWARD_HACKING_DEFENSE", "EU_AI_ACT_ART15"],
    deterministic: true,
  },
];

export const AdversarialMutator: React.FC = () => {
  const navigate = useNavigate();
  const [scenarios, setScenarios] = useState<ScenarioOption[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [mutationType, setMutationType] = useState('typo');
  const [seed, setSeed] = useState('42');
  const [loadingScenarios, setLoadingScenarios] = useState(false);

  // Dynamic Catalog State
  const [catalog, setCatalog] = useState<MutationDescriptor[]>(FALLBACK_MUTATION_CATALOG);
  const [selectedVector, setSelectedVector] = useState<string>('All');
  const [diffMode, setDiffMode] = useState<'prompt' | 'json'>('json');
  const [splitView, setSplitView] = useState(true);
  const [wrapLines, setWrapLines] = useState(false);

  const [mutating, setMutating] = useState(false);
  const [mutatedJson, setMutatedJson] = useState<any>(null);
  const [canonicalBaseScenario, setCanonicalBaseScenario] = useState<any>(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [copied, setCopied] = useState(false);

  // Search & Filter state
  const [industryFilter, setIndustryFilter] = useState('All');
  const [searchTerm, setSearchTerm] = useState('');

  // Fetch full canonical scenario specification when selectedId changes
  useEffect(() => {
    if (!selectedId) {
      setCanonicalBaseScenario(null);
      return;
    }
    let isCurrent = true;
    fetch(`/api/scenarios/${encodeURIComponent(selectedId)}`)
      .then((res) => res.json())
      .then((data) => {
        if (isCurrent && data.scenario) {
          setCanonicalBaseScenario(data.scenario);
        }
      })
      .catch((err) => {
        console.warn('Failed to load canonical scenario specification for diff:', err);
      });
    return () => {
      isCurrent = false;
    };
  }, [selectedId]);

  // 1. Fetch live mutation catalog from backend
  const fetchCatalog = async () => {
    try {
      const res = await fetch('/api/v1/mutations');
      const data = await res.json();
      if (res.ok && data.mutations && Array.isArray(data.mutations) && data.mutations.length > 0) {
        setCatalog(data.mutations);
      }
    } catch (e) {
      console.warn('Could not fetch dynamic mutations catalog, falling back to local registry:', e);
    }
  };

  // 2. Fetch scenarios
  const fetchScenarios = async () => {
    setLoadingScenarios(true);
    try {
      const res = await fetch('/api/scenarios?limit=10000');
      const data = await res.json();
      if (res.ok && data.scenarios) {
        setScenarios(data.scenarios);
      }
    } catch (e) {
      console.error('Error fetching scenarios:', e);
    } finally {
      setLoadingScenarios(false);
    }
  };

  useEffect(() => {
    fetchCatalog();
    fetchScenarios();
  }, []);

  // Compute available vectors dynamically
  const vectors = useMemo(() => {
    const rawVectors = Array.from(new Set(catalog.map((m) => m.vector))).filter(Boolean);
    return ['All', ...rawVectors.sort()];
  }, [catalog]);

  // Filter mutations by selected vector
  const visibleMutations = useMemo(() => {
    if (selectedVector === 'All') return catalog;
    return catalog.filter((m) => m.vector === selectedVector);
  }, [catalog, selectedVector]);

  // Ensure selected mutation exists in current visible subset
  useEffect(() => {
    if (visibleMutations.length > 0) {
      if (!visibleMutations.some((m) => m.id === mutationType)) {
        setMutationType(visibleMutations[0].id);
      }
    }
  }, [selectedVector, visibleMutations]);

  const selectedDescriptor = useMemo(() => {
    return catalog.find((m) => m.id === mutationType) || catalog[0] || null;
  }, [catalog, mutationType]);

  // Recommend diff mode based on vector type
  const isLinguistic = selectedDescriptor?.vector === 'INPUT' || selectedDescriptor?.vector === 'CONTEXT';

  const filteredOptions = scenarios.filter((s) => {
    const indMatch = industryFilter === 'All' || s.industry === industryFilter;
    const textMatch =
      !searchTerm ||
      s.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (s.metadata?.name || s.title || "").toLowerCase().includes(searchTerm.toLowerCase());
    return indMatch && textMatch;
  });

  const industries = [
    'All',
    ...Array.from(new Set(scenarios.map((s) => s.industry)))
      .filter(Boolean)
      .sort((a, b) => a.localeCompare(b)),
  ];

  useEffect(() => {
    if (filteredOptions.length > 0) {
      if (!filteredOptions.some((o) => o.id === selectedId)) {
        setSelectedId(filteredOptions[0].id);
      }
    } else {
      setSelectedId('');
    }
  }, [industryFilter, searchTerm, scenarios]);

  const handleMutate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedId) return;

    setMutating(true);
    setError('');
    setMutatedJson(null);
    setSaveMsg('');

    try {
      const parsedSeed = seed ? parseInt(seed, 10) : undefined;
      const res = await fetch('/api/v1/mutate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scenario_id: selectedId,
          type: mutationType,
          seed: Number.isInteger(parsedSeed) ? parsedSeed : 42,
        }),
      });
      const data = await res.json();
      if (res.ok && data.status === 'success') {
        setMutatedJson(data.mutated);
        // Automatically default diff mode to the recommended view
        setDiffMode(isLinguistic ? 'prompt' : 'json');
        window.dispatchEvent(
          new CustomEvent('agentv-toast', {
            detail: {
              message: `Adversarial mutation (${selectedDescriptor?.label || mutationType}) executed.`,
              type: 'success',
            },
          })
        );
      } else {
        setError(data.message || 'Failed to mutate scenario.');
      }
    } catch (err: any) {
      setError(err.message || 'Network error executing mutation.');
    } finally {
      setMutating(false);
    }
  };

  const handleSaveMutant = async () => {
    if (!mutatedJson) return;
    setSaving(true);
    setSaveMsg('');
    setError('');

    const expectedSuffix = `_mutated_${mutationType}`;
    let targetId = mutatedJson.metadata?.id || mutatedJson.id || selectedId;
    if (!targetId.endsWith(expectedSuffix)) {
      targetId = `${targetId}${expectedSuffix}`;
    }

    const derivedName =
      mutatedJson.metadata?.name ||
      mutatedJson.name ||
      `${selectedId} (Mutated: ${selectedDescriptor?.label || mutationType})`;

    const mutantCopy = {
      ...mutatedJson,
      metadata: {
        ...(mutatedJson.metadata || {}),
        id: targetId,
        parent_scenario_id: selectedId,
        name: derivedName,
        adversarial_vector: selectedDescriptor?.vector,
        adversarial_tier: selectedDescriptor?.tier,
        adversarial_operation: selectedDescriptor?.operation,
      },
    };
    delete (mutantCopy as any).name;
    delete (mutantCopy as any).id;
    delete (mutantCopy as any).title;

    try {
      const res = await fetch('/api/scenarios', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mutantCopy),
      });
      if (res.ok) {
        const data = await res.json().catch(() => ({}));
        const savedId = data.id || data.scenario_id || targetId;
        setSaveMsg(`Mutated scenario saved to library: ${savedId}`);
        window.dispatchEvent(
          new CustomEvent('agentv-toast', {
            detail: { message: `Mutated scenario successfully saved: ${savedId}`, type: 'success' },
          })
        );
        setTimeout(() => navigate(`/scenarios?q=${encodeURIComponent(savedId)}`), 1500);
      } else {
        const errData = await res.json().catch(() => ({}));
        setError(errData.error || 'Failed to save mutated scenario.');
      }
    } catch (err: any) {
      setError(err.message || 'Network error saving mutated scenario.');
    } finally {
      setSaving(false);
    }
  };

  const handleCopy = () => {
    if (!mutatedJson) return;
    navigator.clipboard.writeText(JSON.stringify(mutatedJson, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const getScenarioText = (sc: any) => {
    if (!sc) return '';
    let text = `Scenario ID: ${sc.metadata?.id || sc.id || ''}\n`;
    text += `Title: ${sc.metadata?.name || sc.title || ''}\n`;
    text += `Description: ${sc.metadata?.description || sc.description || ''}\n\n`;

    if (sc.workflow?.nodes) {
      sc.workflow.nodes.forEach((n: any) => {
        text += `[Node ID: ${n.id}]\n`;
        text += `Task Description:\n${n.task_description || ''}\n`;
        if (n.parameters && Object.keys(n.parameters).length > 0) {
          text += `Parameters: ${JSON.stringify(n.parameters)}\n`;
        }
        if (n.retrieved_documents && n.retrieved_documents.length > 0) {
          text += `Retrieved Documents (${n.retrieved_documents.length}):\n${JSON.stringify(n.retrieved_documents, null, 2)}\n`;
        }
        text += '\n';
      });
    }
    return text;
  };

  const chosenScenario = scenarios.find((s) => s.id === selectedId) || null;

  // Provenance badge helper
  const renderSourceBadge = (source?: string) => {
    switch (source) {
      case 'enterprise':
        return (
          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-purple-500/20 text-purple-300 border border-purple-500/40">
            ENTERPRISE T5
          </span>
        );
      case 'plugin':
        return (
          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
            CUSTOM PLUGIN
          </span>
        );
      default:
        return (
          <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-cyan-500/20 text-cyan-300 border border-cyan-500/40">
            CORE RUNTIME
          </span>
        );
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-[1700px] w-full mx-auto min-h-screen flex flex-col">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-slate-900 pb-5">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Layers className="w-5 h-5 text-indigo-400" />
            <span>Adversarial Scenario Mutator</span>
          </h1>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            Test policy stability, safety constraints, and resilience across all 9 perturbation vectors (Linguistic,
            Context, Memory, Retrieval, Tools, State, Authorization, Temporal, and Objective Gaming).
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-slate-500 font-mono">
            {catalog.length} Mutators Active ({vectors.length - 1} Vectors)
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-1">
        {/* Left column: Controls */}
        <div className="space-y-6 lg:col-span-1">
          <div className="bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4">
            <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
              <Sparkles className="w-4 h-4 text-indigo-400" />
              <span>Mutation Settings</span>
            </h3>

            {loadingScenarios ? (
              <div className="text-xs text-slate-500 italic py-4">Loading scenario choices...</div>
            ) : scenarios.length === 0 ? (
              <div className="text-xs text-rose-400 py-4">
                No scenarios available to mutate. Create a scenario first.
              </div>
            ) : (
              <form onSubmit={handleMutate} className="space-y-4">
                {/* Scenario Filters */}
                <div className="space-y-3 p-3 bg-slate-950/40 border border-slate-900 rounded-lg">
                  <span className="text-[9px] text-slate-500 font-bold uppercase font-mono">
                    Base Scenario Selector
                  </span>

                  <div className="space-y-1">
                    <label className="text-[9px] text-slate-400 font-medium">Search Keyword</label>
                    <input
                      type="text"
                      placeholder="Type to filter..."
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-850 rounded px-2 py-1.5 text-[11px] text-slate-350 focus:outline-none focus:border-indigo-500 font-mono"
                    />
                  </div>

                  <div className="space-y-1">
                    <label className="text-[9px] text-slate-400 font-medium">Sector</label>
                    <select
                      value={industryFilter}
                      onChange={(e) => setIndustryFilter(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-850 rounded px-2 py-1.5 text-[11px] text-slate-350 focus:outline-none focus:border-indigo-500 cursor-pointer"
                    >
                      {industries.map((ind) => (
                        <option key={ind} value={ind}>
                          {ind === 'All' ? 'All Sectors' : ind.replace(/_/g, ' ')}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="space-y-1">
                    <label className="text-[9px] text-slate-400 font-medium">
                      Target Scenario ({filteredOptions.length} available)
                    </label>
                    <select
                      value={selectedId}
                      onChange={(e) => setSelectedId(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-indigo-500 cursor-pointer font-mono"
                    >
                      {filteredOptions.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.metadata?.name || s.title || s.id} ({s.id})
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                {/* Vector Selection Tabs */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <label className="text-[9px] text-slate-500 font-bold uppercase font-mono flex items-center gap-1">
                      <Sliders className="w-3 h-3 text-indigo-400" />
                      <span>Perturbation Vector</span>
                    </label>
                    <span className="text-[9px] text-slate-600 font-mono">
                      {visibleMutations.length} options
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-1 bg-slate-950/80 p-1 rounded-lg border border-slate-850 max-h-24 overflow-y-auto">
                    {vectors.map((vec) => (
                      <button
                        key={vec}
                        type="button"
                        onClick={() => setSelectedVector(vec)}
                        className={`px-2 py-1 rounded text-[10px] font-mono transition-colors ${
                          selectedVector === vec
                            ? 'bg-indigo-600 text-white font-bold'
                            : 'text-slate-400 hover:text-white hover:bg-slate-900'
                        }`}
                      >
                        {vec}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Mutation Strategy Selector */}
                <div className="space-y-1.5">
                  <label className="text-[9px] text-slate-500 font-bold uppercase font-mono">
                    Mutation Strategy ({visibleMutations.length})
                  </label>
                  <select
                    value={mutationType}
                    onChange={(e) => setMutationType(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-indigo-500 cursor-pointer font-medium"
                  >
                    {visibleMutations.map((m) => (
                      <option key={m.id} value={m.id}>
                        [{m.vector}] {m.label} ({m.tier.replace('T', 'Tier ')})
                      </option>
                    ))}
                  </select>
                </div>

                {/* Deterministic Seed */}
                <div className="space-y-1.5">
                  <label className="text-[9px] text-slate-500 font-bold uppercase font-mono flex items-center gap-1">
                    <Hash className="w-3 h-3 text-indigo-400" />
                    <span>Deterministic Seed (PRNG)</span>
                  </label>
                  <input
                    type="number"
                    value={seed}
                    onChange={(e) => setSeed(e.target.value)}
                    placeholder="42"
                    className="w-full bg-slate-950 border border-slate-850 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-indigo-500 font-mono"
                  />
                  <span className="text-[9px] text-slate-600">
                    Controls pseudo-random character replacements & perturbation permutations.
                  </span>
                </div>

                {/* Strategy Details Card */}
                {selectedDescriptor && (
                  <div className="p-3 bg-slate-950/80 border border-slate-850 rounded-lg space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-[9px] text-slate-500 font-bold uppercase font-mono flex items-center gap-1">
                        <HelpCircle className="w-3.5 h-3.5 text-indigo-400" />
                        <span>Strategy Details</span>
                      </span>
                      {renderSourceBadge(selectedDescriptor.source)}
                    </div>
                    <p className="text-[10px] text-slate-300 leading-relaxed font-sans">
                      {selectedDescriptor.description}
                    </p>
                    <div className="flex flex-wrap gap-1.5 pt-1 border-t border-slate-900">
                      <span className="px-1.5 py-0.5 rounded bg-slate-900 text-slate-400 text-[9px] font-mono">
                        Target: {selectedDescriptor.target_field}
                      </span>
                      <span className="px-1.5 py-0.5 rounded bg-slate-900 text-slate-400 text-[9px] font-mono">
                        Op: {selectedDescriptor.operation}
                      </span>
                      <span className="px-1.5 py-0.5 rounded bg-slate-900 text-slate-400 text-[9px] font-mono">
                        {selectedDescriptor.tier}
                      </span>
                    </div>

                    {selectedDescriptor.regulatory_frameworks && selectedDescriptor.regulatory_frameworks.length > 0 && (
                      <div className="flex flex-wrap gap-1 pt-1">
                        {selectedDescriptor.regulatory_frameworks.map((rf) => (
                          <span
                            key={rf}
                            className="px-1.5 py-0.5 rounded bg-indigo-950/40 text-indigo-300 border border-indigo-900/50 text-[8px] font-mono"
                          >
                            {rf}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={mutating || !selectedId}
                  className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-xs font-bold rounded-lg transition-colors flex items-center justify-center gap-1.5"
                >
                  <PlayCircle className="w-4 h-4" />
                  <span>{mutating ? 'Executing Mutator Engine...' : 'Execute Mutation Engine'}</span>
                </button>
              </form>
            )}
          </div>
        </div>

        {/* Right column: Comparative Diff & Save action */}
        <div className="lg:col-span-2 bg-slate-950/40 border border-slate-900 rounded-xl p-5 space-y-4 flex flex-col justify-between min-h-[700px] flex-1">
          <div className="space-y-4 flex-1 flex flex-col">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2 border-b border-slate-900/60 pb-3">
              <div>
                <h3 className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
                  <Shield className="w-4 h-4 text-emerald-400" />
                  <span>Scenario State Attribution Diff</span>
                  {mutatedJson && (
                    <span className="text-[9px] text-slate-500 font-mono flex items-center gap-1 lowercase">
                      ({selectedId} <ArrowRight className="w-3 h-3" /> {mutatedJson.id || mutatedJson.metadata?.id})
                    </span>
                  )}
                </h3>
              </div>

              {/* Dual Diff View Selector & Layout Mode */}
              <div className="flex items-center gap-2">
                {mutatedJson && (
                  <>
                    <div className="flex items-center bg-slate-900 p-0.5 rounded-lg border border-slate-800">
                      <button
                        type="button"
                        onClick={() => setDiffMode('prompt')}
                        className={`px-2 py-1 rounded text-[10px] font-mono flex items-center gap-1 transition-colors ${
                          diffMode === 'prompt'
                            ? 'bg-indigo-600 text-white font-bold'
                            : 'text-slate-400 hover:text-white'
                        }`}
                      >
                        <FileText className="w-3 h-3" />
                        <span>Prompts {isLinguistic && '★'}</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => setDiffMode('json')}
                        className={`px-2 py-1 rounded text-[10px] font-mono flex items-center gap-1 transition-colors ${
                          diffMode === 'json'
                            ? 'bg-indigo-600 text-white font-bold'
                            : 'text-slate-400 hover:text-white'
                        }`}
                      >
                        <Code2 className="w-3 h-3" />
                        <span>Full Spec JSON {!isLinguistic && '★'}</span>
                      </button>
                    </div>

                    <div className="flex items-center bg-slate-900 p-0.5 rounded-lg border border-slate-800">
                      <button
                        type="button"
                        onClick={() => setSplitView(true)}
                        className={`px-2 py-1 rounded text-[10px] font-mono transition-colors ${
                          splitView
                            ? 'bg-indigo-600 text-white font-bold'
                            : 'text-slate-400 hover:text-white'
                        }`}
                        title="Side-by-side 50/50 split diff view"
                      >
                        <span>Split</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => setSplitView(false)}
                        className={`px-2 py-1 rounded text-[10px] font-mono transition-colors ${
                          !splitView
                            ? 'bg-indigo-600 text-white font-bold'
                            : 'text-slate-400 hover:text-white'
                        }`}
                        title="Single unified inline diff view"
                      >
                        <span>Unified</span>
                      </button>
                    </div>

                    <div className="flex items-center bg-slate-900 p-0.5 rounded-lg border border-slate-800">
                      <button
                        type="button"
                        onClick={() => setWrapLines(false)}
                        className={`px-2 py-1 rounded text-[10px] font-mono transition-colors ${
                          !wrapLines
                            ? 'bg-indigo-600 text-white font-bold'
                            : 'text-slate-400 hover:text-white'
                        }`}
                        title="Horizontal scroll view (no line wrap)"
                      >
                        <span>Scroll</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => setWrapLines(true)}
                        className={`px-2 py-1 rounded text-[10px] font-mono transition-colors ${
                          wrapLines
                            ? 'bg-indigo-600 text-white font-bold'
                            : 'text-slate-400 hover:text-white'
                        }`}
                        title="Wrap text lines within column"
                      >
                        <span>Wrap</span>
                      </button>
                    </div>
                  </>
                )}

                {mutatedJson && (
                  <button
                    onClick={handleCopy}
                    className="flex items-center gap-1 px-2.5 py-1 bg-slate-900 hover:bg-slate-850 border border-slate-800 rounded text-[10px] font-bold text-slate-300 hover:text-white transition-colors"
                  >
                    {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                    <span>{copied ? 'Copied' : 'Copy JSON'}</span>
                  </button>
                )}
              </div>
            </div>

            {error && (
              <div className="p-3 bg-rose-500/10 border border-rose-500/25 rounded-lg text-rose-400 text-xs">
                {error}
              </div>
            )}

            {saveMsg && (
              <div className="p-3 bg-emerald-500/10 border border-emerald-500/25 rounded-lg text-emerald-400 text-xs font-semibold">
                {saveMsg}
              </div>
            )}

            {mutating ? (
              <div className="min-h-[500px] flex flex-col justify-center items-center gap-3">
                <div className="w-6 h-6 border-2 border-indigo-500/20 border-t-indigo-500 rounded-full animate-spin" />
                <span className="text-xs text-slate-500">
                  Synthesizing adversarial perturbations across {selectedDescriptor?.vector || 'target'} vector...
                </span>
              </div>
            ) : !mutatedJson ? (
              <div className="min-h-[500px] border border-dashed border-slate-900 rounded-xl flex flex-col items-center justify-center p-6 text-center text-xs text-slate-600">
                <Layers className="w-8 h-8 text-slate-800 mb-2" />
                <p>Select target scenario and perturbation strategy, then execute the mutation engine.</p>
                <p className="text-[10px] text-slate-700 mt-1">
                  Attribution Diff compares the canonical baseline scenario specification against the mutated output.
                </p>
              </div>
            ) : (
              <div className="border border-slate-900 rounded-xl bg-slate-950 text-xs leading-relaxed min-h-[600px] h-[calc(100vh-270px)] overflow-x-auto overflow-y-auto flex-1">
                <ReactDiffViewer
                  oldValue={
                    diffMode === 'prompt'
                      ? getScenarioText(canonicalBaseScenario || chosenScenario)
                      : JSON.stringify(canonicalBaseScenario || chosenScenario, null, 2)
                  }
                  newValue={
                    diffMode === 'prompt'
                      ? getScenarioText(mutatedJson)
                      : JSON.stringify(mutatedJson, null, 2)
                  }
                  splitView={splitView}
                  leftTitle="Baseline Scenario (Original Specification)"
                  rightTitle={`Mutated Scenario (+ Perturbations: ${selectedDescriptor?.label || mutationType})`}
                  useDarkTheme={true}
                  summary={
                    <span
                      title="Expand/Fold unchanged blocks. The number indicates total changed lines; colored blocks show additions (green) vs deletions (red) ratio."
                      className="text-[10px] text-slate-400 font-sans cursor-help flex items-center gap-1.5 ml-2"
                    >
                      <span className="text-slate-600 font-mono">|</span>
                      <span>Fold/Expand toggle &amp; line diff metrics (green=added, red=deleted)</span>
                    </span>
                  }
                  styles={{
                    variables: {
                      dark: {
                        diffViewerBackground: '#020617',
                        diffViewerColor: '#cbd5e1',
                        addedBackground: '#064e3b',
                        addedColor: '#34d399',
                        removedBackground: '#7f1d1d',
                        removedColor: '#f87171',
                        wordAddedBackground: '#047857',
                        wordRemovedBackground: '#991b1b',
                        diffViewerTitleBackground: '#0b1329',
                        diffViewerTitleColor: '#cbd5e1',
                        diffViewerTitleBorderColor: '#1e293b',
                      },
                    },
                    diffContainer: {
                      tableLayout: 'fixed',
                      width: '100%',
                      minWidth: wrapLines ? '100%' : (splitView ? '1200px' : '800px'),
                      overflowX: 'auto',
                    },
                    splitView: {
                      width: '100%',
                    },
                    content: {
                      width: splitView ? '50%' : '100%',
                      overflowX: 'visible',
                    },
                    titleBlock: {
                      width: splitView ? '50%' : '100%',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      padding: '6px 12px',
                      fontSize: '11px',
                      fontWeight: 600,
                    },
                    line: {
                      fontSize: '11px',
                      fontFamily: 'monospace',
                      lineHeight: '1.4',
                      whiteSpace: wrapLines ? 'pre-wrap' : 'pre',
                      wordBreak: wrapLines ? 'break-all' : 'normal',
                    },
                    contentText: {
                      whiteSpace: wrapLines ? 'pre-wrap' : 'pre',
                      wordBreak: wrapLines ? 'break-all' : 'normal',
                    },
                  }}
                />
              </div>
            )}
          </div>

          {mutatedJson && (
            <div className="border-t border-slate-900/60 pt-4 mt-4">
              <button
                onClick={handleSaveMutant}
                disabled={saving}
                className="w-full py-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-500 text-white text-xs font-bold rounded-lg transition-colors flex items-center justify-center gap-1.5"
              >
                <Save className="w-4 h-4" />
                <span>
                  {saving ? 'Saving Mutant Scenario...' : 'Save Mutated Copy to Scenario Library'}
                </span>
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
