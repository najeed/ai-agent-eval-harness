"""
Industrial Mutation Testing Sentinel & Scorecard Generator.
Executes real AST-based code mutations against explicit critical Runtime
surfaces: verification, execution isolation, lifecycle, HITL durability,
trace persistence, outbound payloads, checkpoints, and canonical evidence.

Mutation strategy: SURGICAL LINE SUBSTITUTION.
Rather than using ast.unparse() (which rewrites the entire file, losing comments,
blank lines, and f-string formatting), this sentinel applies mutations by direct
targeted string replacement at the exact (lineno, col_offset) AST position.
This preserves all non-mutated lines byte-for-byte, preventing spurious test
failures from file-hash mismatches in TraceVerifier-based tests.

Calculates exact mutation score:
Mutation Score = Killed / (Killed + Survived)

Incompetent mutants (annotation-only BitOr with no runtime effect under
`from __future__ import annotations`) are excluded from the denominator.

Outputs complete metrics:
  - Killed / Survived / Timeout / Indeterminate / Skipped / Incompetent
  - Mutation Score (%)
  - Baseline vs Delta

Generates diligence artifact 'reports/mutation_scorecard.md' and fails CI unless every
competent mutant is deterministically killed.
"""

from __future__ import annotations

import ast
import base64
import bisect
import concurrent.futures
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent.parent.parent
REPORT_DIR = BASE_DIR / "reports"
REPORT_PATH = REPORT_DIR / "mutation_scorecard.md"
BASELINE_CACHE_PATH = REPORT_DIR / "mutation_baseline_cache.json"
BASELINE_CACHE_VERSION = 2

# Strips heavy, slow third-party plugins that add 3-5s of startup latency per mutant
FAST_PYTEST_FLAGS = [
    "-q",
    "--no-header",
    "-p",
    "no:plugin_gateway",
    "-p",
    "no:cov",
    "-p",
    "no:benchmark",
    "-p",
    "no:logfire",
    "-p",
    "no:langsmith",
    "-p",
    "no:playwright",
    "-p",
    "no:Faker",
    "-p",
    "no:xdist",
    "-o",
    "addopts=",
]


# Per-module test corpora.
#
# Unit contracts provide focused failures; the credential-free positive acceptance
# chain independently checks cryptographic wire formats across producer/consumer seams.
EVIDENCE_CHAIN_POSITIVE = (
    "tests/acceptance/test_release_evidence_chain_matrix.py"
    "::test_release_evidence_chain_matrix[complete_chain]"
)
EVIDENCE_CHAIN_UNSEALED = (
    "tests/acceptance/test_release_evidence_chain_matrix.py"
    "::test_release_evidence_chain_matrix[unsealed_run]"
)


@dataclass(frozen=True)
class CriticalMutationTarget:
    """An explicit Runtime trust boundary and its authoritative fast corpus."""

    path: Path
    tests: tuple[str, ...]
    scopes: frozenset[str]
    required_operator_families: frozenset[str] = frozenset()
    eligible_operator_families: frozenset[str] = frozenset()
    excluded_mutations: frozenset[tuple[str, int, str, str]] = frozenset()
    scope_test_names: Mapping[str, tuple[str, ...]] | None = None
    exclusion_reasons: Mapping[tuple[str, int, str, str], str] | None = None


@dataclass
class ModuleTiming:
    """Measured per-module cost and acceleration evidence for one sentinel run."""

    baseline_seconds: float
    mutant_seconds: float = 0.0
    full_corpus_fallbacks: int = 0
    cache_hits: int = 0
    timeout_retries: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_cache_hit(self) -> None:
        with self._lock:
            self.cache_hits += 1

    def record_full_corpus_fallback(self) -> None:
        with self._lock:
            self.full_corpus_fallbacks += 1

    def record_timeout_retry(self) -> None:
        with self._lock:
            self.timeout_retries += 1


# Mutation testing is deliberately risk-driven. This is not a general code
# coverage list: each entry is an execution, evidence, or lifecycle boundary.
CRITICAL_MUTATION_TARGETS: tuple[CriticalMutationTarget, ...] = (
    CriticalMutationTarget(
        BASE_DIR / "eval_runner" / "verifier.py",
        (
            EVIDENCE_CHAIN_POSITIVE,
            EVIDENCE_CHAIN_UNSEALED,
            "tests/unit/core/test_provisional_authority_verdict_contract.py",
            "tests/unit/core/test_provisional_package_verdict_contract.py",
            "tests/unit/core/test_execution_mode_binding_contract.py",
            "tests/unit/core/test_legacy_certificate_profile_contract.py",
            "tests/unit/core/test_provider_native_verifier.py",
            "tests/unit/core/test_verification_boundary_contracts.py",
            "tests/unit/core/test_signing_finalization_contract.py",
            "tests/unit/core/test_digest_signature_contract.py",
            "tests/unit/core/test_oracle_carrier_reference_contract.py",
            "tests/unit/core/test_signing_carrier_hash_contract.py",
            "tests/unit/core/test_certificate_projection_contract.py",
            "tests/unit/core/test_actual_artifact_hash_contract.py",
            "tests/unit/core/test_signing_retention_contract.py",
            "tests/unit/core/test_signing_outcome_contract.py",
            "tests/unit/core/test_signing_snapshot_contract.py",
            "tests/unit/core/test_signing_terminal_binding_contract.py",
            "tests/unit/core/test_diagnostic_manifest_binding_contract.py",
            "tests/unit/core/test_multi_attempt_evidence_contract.py",
            "tests/unit/core/test_terminal_finalization_summary_contract.py",
            "tests/unit/core/test_certification_service_and_trust_boundary.py",
            "tests/unit/core/test_hardened_audit_verification.py",
            "tests/unit/core/test_golden_verifier_matrix.py",
        ),
        frozenset(
            {
                "sign_trace_bytes",
                "verify_trace",
                "verify_trace_async",
                "verify_run",
                "verify_trace_bytes",
                "verify_certification_artifact",
                "verify_trace_certificate",
                "verify_package",
                "verify_package_artifacts",
                "verify_package_signature_only",
            }
        ),
        scope_test_names={
            "sign_trace_bytes": (
                "test_signing_requires_explicit_run_and_provider",
                "test_signing_recovers_finalization_from_trace_without_metadata_hint",
                "test_byte_signer_rejects_bytes_not_owned_by_the_scoped_provider",
                "test_byte_signer_hashes_the_exact_provider_bytes",
                "test_signing_retention_provider_capability",
                "test_signing_outcome_tracks_execution_and_oracles",
                "test_signing_preserves_explicit_snapshot_or_resolves_provider_fallback",
                "test_invalid_provider_snapshot_fallback_cannot_authorize",
                "test_detached_package_cannot_drop_issuer_provisional_restriction",
                "test_signing_rejects_root_that_omits_terminal_evidence",
            ),
            "verify_trace_bytes": (
                "test_byte_verification_requires_explicit_run_and_provider",
                "test_release_evidence_chain_matrix",
            ),
            "verify_trace": (
                "test_trace_verification_rejects_malformed_inputs_before_provider_access",
            ),
            "verify_run": (
                "test_live_signed_certificate_honors_explicit_provisional_designation",
                "test_verify_run_reads_only_the_supplied_provider",
                "test_verify_run_does_not_recover_missing_provider_artifacts_from_disk",
                "test_partial_provider_artifacts_are_not_reported_as_absent_or_verified",
            ),
            "verify_trace_certificate": (
                "test_certificate_integrity_accepts_declared_scenario_hash_locations",
                "test_terminal_summary_preserves_pre_finalization_evidence",
            ),
            "verify_package_artifacts": (
                "test_legacy_manifest_projection_does_not_override_declared_binding",
                "test_verify_package_artifacts_manifest_types_and_errors",
                "test_verify_package_and_artifacts_cross_binding_matrix",
                "test_verifier_remaining_branches_matrix",
            ),
            "verify_package": (
                "test_legacy_signed_package_profile_is_explicitly_non_authoritative",
                "test_legacy_manifest_projection_does_not_override_declared_binding",
                "test_terminal_summary_preserves_pre_finalization_evidence",
                "test_verify_package_manifest_and_scenario_branches",
                "test_verify_package_and_artifacts_cross_binding_matrix",
            ),
            "verify_certification_artifact": (
                "test_legacy_signed_package_profile_is_explicitly_non_authoritative",
                "test_signed_execution_mode_claim_must_match_actual_manifest",
                "test_detached_package_cannot_drop_issuer_provisional_restriction",
                "test_certification_finalization_carrier_contract",
                "test_authoritative_package_verification_uses_bytes_without_caller_events",
            ),
        },
        excluded_mutations=frozenset(
            {
                ("sign_trace_bytes", 523, "or", "and"),
                ("sign_trace_bytes", 585, "and", "or"),
                ("sign_trace_bytes", 616, "and", "or"),
                ("sign_trace_bytes", 616, "evidence_root_hash", "__mutation_missing_commitment__"),
                ("sign_trace_bytes", 645, "evidence_root_hash", "__mutation_missing_commitment__"),
                ("verify_trace_certificate", 1619, "and", "or"),
                ("verify_trace_certificate", 1627, "and", "or"),
                ("verify_package_artifacts", 2127, "and", "or"),
            }
        ),
        exclusion_reasons={
            ("sign_trace_bytes", 616, "evidence_root_hash", "__mutation_missing_commitment__"): (
                "Equivalent extra-filter trigger: a missing lookup only runs the pure "
                "fallback when the declared root already matches. The fallback adopts "
                "only that same declared root, leaving the actual root comparison intact."
            ),
            ("sign_trace_bytes", 645, "evidence_root_hash", "__mutation_missing_commitment__"): (
                "Non-binding diagnostic lookup used only to format an already-raised "
                "EvidenceRootMismatchError. The root comparison, signed commitments, "
                "and successful verification paths are unchanged."
            ),
            ("sign_trace_bytes", 585, "and", "or"): (
                "Equivalent for supported provider manifest projections: a valid scenario "
                "is selected either way; an absent key adds only a caught lookup error. "
                "Empty/malformed scenario projections remain non-authoritative, covered "
                "by positive and deliberately invalid snapshot-fallback contracts."
            ),
            ("sign_trace_bytes", 523, "or", "and"): (
                "Equivalent for provider capability strings or None: the trailing != WORM "
                "check subsumes both the logical-seal equality and missing-capability guards."
            ),
            ("sign_trace_bytes", 616, "and", "or"): (
                "Equivalent for supported JSON evidence: extra graph filtering changes the "
                "stored root only when the filtered root equals the declared root; an "
                "already-matching root is unchanged, and an absent hint cannot match a hash."
            ),
            ("verify_trace_certificate", 1627, "and", "or"): (
                "Equivalent for supported JSON evidence: filtering is an extra fallback; "
                "its result is adopted only if it matches the expected root already verified."
            ),
            ("verify_trace_certificate", 1619, "and", "or"): (
                "Equivalent for supported JSON evidence: the extra fallback only replaces "
                "the graph when its root equals the expected, already-matched root."
            ),
            ("verify_package_artifacts", 2127, "and", "or"): (
                "Equivalent for graph-builder outputs (dict or None): both branches yield "
                "the same nodes; an empty dict has no nodes and defaults to []."
            ),
        },
    ),
    CriticalMutationTarget(
        BASE_DIR / "eval_runner" / "tool_sandbox.py",
        (
            "tests/unit/core/test_sandbox_policy_commit_contract.py",
            "tests/unit/core/test_tool_sandbox.py",
            "tests/unit/core/test_core_sandbox.py",
            "tests/unit/core/test_tool_sandbox_coverage_extra.py",
            "tests/unit/core/test_tool_sandbox_pipeline.py",
        ),
        frozenset({"execute", "_execute_core", "get_bounded_state", "_sanitize_path", "fork"}),
        scope_test_names={
            "_execute_core": (
                "test_policy_denial_without_detailed_violations_still_blocks_the_write",
                "test_policy_input_commitment_supports_yaml_date_values",
                "test_commit_interceptor_decision_controls_the_observed_state",
                "test_malformed_intercepted_diff_is_rejected_before_any_state_write",
                "test_write_veto_does_not_prevent_a_read_only_tool",
                "test_sandbox_known_tool",
                "test_sandbox_unknown_tool",
                "test_sandbox_state_mutation",
                "test_sandbox_execute_missing_branches",
                "test_sandbox_state_changes_and_shared_state_edge_cases",
                "test_tool_sandbox_execution_quiesce_and_policy_branches",
            ),
            "get_bounded_state": ("test_sandbox_get_bounded_state_projection",),
        },
    ),
    CriticalMutationTarget(
        BASE_DIR / "eval_runner" / "flight_recorder.py",
        (
            "tests/unit/core/test_recorder_provider_binding_contract.py",
            "tests/unit/core/test_flight_recorder_matrix.py",
            "tests/unit/core/test_flight_recorder_extra.py",
            "tests/unit/core/test_flight_recorder_engine.py",
            "tests/unit/test_flight_recorder_refresh.py",
        ),
        frozenset(
            {
                "bind_run_provider",
                "_provider_for_run",
                "is_certification_mode",
                "handle_event",
                "finalize_run",
                "freeze_run",
                "close_execution_writes",
            }
        ),
        scope_test_names={
            "finalize_run": (
                "test_finalize_transitions_bound_provider",
                "test_finalizing_unknown_identity_never_publishes_a_trace_seal",
                "test_unsigned_diagnostic_trace_closure_is_persisted_without_claiming_a_signature",
                "test_optional_key_identifier_is_emitted_only_when_nonempty",
            ),
            "_provider_for_run": (
                "test_recorder_requires_explicit_run_binding_despite_an_ambient_provider",
            ),
            "freeze_run": (
                "test_freezing_an_unassigned_identity_preserves_its_public_recorder_state",
                "test_freeze_run_and_utility_hooks",
            ),
        },
    ),
    CriticalMutationTarget(
        BASE_DIR / "eval_runner" / "run_lifecycle.py",
        (
            "tests/unit/core/test_placeholder_run_probe_contract.py",
            "tests/unit/core/test_hitl_durable_suspension_and_resume.py",
            "tests/unit/core/test_trace_integrity_and_lifecycle_gates.py",
            "tests/unit/core/test_hitl_suspension_to_certification_lifecycle.py",
            "tests/unit/core/test_lifecycle_provider_status_contract.py",
        ),
        frozenset(
            {
                "get_run_lifecycle_state",
                "transition_run_lifecycle",
                "can_write_trace",
                "assert_can_write_trace",
                "rollback_run_lifecycle_to_open",
            }
        ),
    ),
    CriticalMutationTarget(
        BASE_DIR / "eval_runner" / "session.py",
        (
            "tests/unit/core/test_hitl_checkpoint_handle_contract.py",
            "tests/unit/core/test_hitl_durable_suspension_and_resume.py",
            "tests/unit/core/test_core_session.py",
            "tests/unit/core/test_session_plugin_state_tools.py",
            "tests/unit/core/test_hitl_resumption_timing_contract.py",
        ),
        frozenset(
            {
                "save_checkpoint",
                "restore_from_checkpoint",
                "_verify_state_parity",
                "_raise_if_pending_durable_approval",
                "_handle_hitl",
            }
        ),
        scope_test_names={
            "_handle_hitl": (
                "test_durable_approval_suspends_with_optional_checkpoint_handle",
                "test_hitl_resumption_wait_uses_decision_time_only_when_available_and_ordered",
                "test_session_hitl_non_interactive_approval_and_rejection",
                "test_p0_session_hitl_resumption_and_gate_branches",
            ),
            "restore_from_checkpoint": (
                "test_session_turn_number_and_checkpoint_branches",
                "test_session_restore_checkpoint_completed_nodes_and_tokens",
            ),
            "_raise_if_pending_durable_approval": (
                "test_pending_durable_approval_suspends_before_state_parity",
                "test_session_pending_durable_approval_and_lifecycle",
            ),
        },
    ),
    CriticalMutationTarget(
        BASE_DIR / "eval_runner" / "engine.py",
        (
            "tests/unit/core/test_agent_wire_payload_contract.py",
            "tests/unit/core/test_core_engine.py",
            "tests/unit/adapters/test_engine_adapters.py",
        ),
        frozenset({"render_outbound_payload", "call_agent"}),
    ),
    CriticalMutationTarget(
        BASE_DIR / "eval_runner" / "reference" / "sqlite_checkpoint.py",
        ("tests/unit/core/test_hitl_durable_suspension_and_resume.py",),
        frozenset({"save", "load"}),
        frozenset({"serialization"}),
        frozenset({"serialization", "guard", "comparison", "boolean"}),
        scope_test_names={
            "save": (
                "test_sqlite_checkpoint_store_preserves_opaque_state_and_metadata",
                "test_sqlite_checkpoint_store_serializes_non_json_runtime_state",
            ),
            "load": (
                "test_sqlite_checkpoint_store_load_normalizes_durable_uri",
                "test_sqlite_checkpoint_store_load_normalizes_numeric_checkpoint_identifier",
            ),
        },
    ),
    CriticalMutationTarget(
        BASE_DIR / "agentv_runtime" / "package.py",
        (EVIDENCE_CHAIN_POSITIVE, "tests/unit/core/test_verification_envelope.py"),
        frozenset(
            {
                "compute_content_hash",
                "canonical_payload_dict",
                "compute_package_hash",
                "sign",
                "verify_signature",
            }
        ),
    ),
    CriticalMutationTarget(
        BASE_DIR / "agentv_runtime" / "canonical.py",
        (EVIDENCE_CHAIN_POSITIVE, "tests/unit/core/test_rfc8785_canonicalization.py"),
        frozenset(
            {
                "_serialize_number",
                "canonical_json_dumps",
                "canonical_json_encode",
                "compute_reference_hash",
            }
        ),
    ),
    CriticalMutationTarget(
        BASE_DIR / "agentv_runtime" / "manifest.py",
        (
            EVIDENCE_CHAIN_POSITIVE,
            "tests/unit/test_execution_manifest.py",
            "tests/unit/core/test_resumption_manifest_integrity.py",
        ),
        frozenset(
            {
                "_to_json_compatible",
                "_canonical_json_bytes",
                "compute_scenario_hash",
                "compute_preflight_fingerprint",
                "compute_content_hash",
                "compute_manifest_hash",
                "from_dict",
                "build",
            }
        ),
        frozenset({"commitment"}),
    ),
    CriticalMutationTarget(
        BASE_DIR / "agentv_runtime" / "evidence_graph.py",
        ("tests/unit/core/test_evidence_graph.py",),
        frozenset(
            {
                "_strict_result_value",
                "index_events_by_seq",
                "link_assertion",
                "build_evidence_graph",
                "build_evidence_graph_from_events",
                "compute_evidence_graph_root",
            }
        ),
        frozenset({"commitment"}),
        frozenset({"commitment", "guard", "comparison", "boolean"}),
        scope_test_names={
            "_strict_result_value": ("test_strict_result_value_rejects_invalid_types",),
            "index_events_by_seq": ("test_index_events_by_seq_duplicate_raises",),
            "link_assertion": (
                "test_graph_links_assertion_via_carrier_seq",
                "test_unresolved_assertions_never_invent_provenance",
                "test_incomplete_evidence_references_and_artifacts_remain_unresolved",
                "test_link_assertion_preserves_direct_and_fallback_provenance_semantics",
                "test_artifact_reference_wins_when_declared",
                "test_link_assertion_all_outcome_states",
            ),
            "build_evidence_graph": (
                "test_build_evidence_graph_sequential_executions_and_missing_required",
                "test_evidence_completeness_ignores_informational_and_rejects_invalid_results",
                "test_empty_evidence_graph_has_complete_vacuous_provenance",
                "test_required_direct_trace_result_is_complete",
                "test_artifact_evidence_counts_as_complete_provenance",
            ),
            "build_evidence_graph_from_events": (
                "test_build_evidence_graph_from_events_with_tuples_and_carrier_upgrade",
                "test_build_evidence_graph_from_events_dict_stream_and_execution_graph_node_metrics",
                "test_build_evidence_graph_ignores_unknown_events_and_keeps_first_unsequenced_assertion",
            ),
            "compute_evidence_graph_root": (
                "test_evidence_root_commitment_semantics",
                "test_compute_evidence_graph_root_mapping_and_dicts",
            ),
        },
    ),
    CriticalMutationTarget(
        BASE_DIR / "agentv_runtime" / "finalization.py",
        (
            "tests/unit/core/test_signed_finalization_object_contract.py",
            EVIDENCE_CHAIN_POSITIVE,
            "tests/unit/core/test_finalization_record.py",
            "tests/unit/core/test_finalization_alias_contract.py",
        ),
        frozenset(
            {
                "parse_untrusted",
                "verify_authoritative",
                "from_dict",
                "canonical_payload_bytes",
                "compute_finalization_hash",
                "sign",
                "verify_signature",
            }
        ),
        frozenset({"commitment"}),
    ),
    CriticalMutationTarget(
        BASE_DIR / "eval_runner" / "reference" / "approval_store.py",
        (
            "tests/unit/core/test_approval_store.py",
            "tests/unit/core/test_scope_bound_approval_persistence.py",
            "tests/unit/core/test_approval_events_and_hooks.py",
        ),
        frozenset(
            {
                "create_request",
                "get_request",
                "get_request_by_run_id",
                "resolve_request",
                "list_pending",
                "delete_request",
            }
        ),
        frozenset({"approval_gate"}),
        frozenset({"approval_gate", "boolean", "comparison", "guard"}),
        scope_test_names={
            "create_request": ("test_lifecycle",),
            "get_request": (
                "test_lifecycle",
                "test_fallback_scan_when_token_file_missing_and_corruptions",
            ),
            "get_request_by_run_id": ("test_lifecycle",),
            "resolve_request": (
                "test_resolve_errors",
                "test_rejected_request_uses_rejected_default_audit_reason",
                "test_approved_request_uses_approved_default_audit_reason",
                "test_hitl_resume_already_resolved",
            ),
            "list_pending": ("test_lifecycle",),
            "delete_request": (
                "test_delete_request_reports_and_removes_both_durable_records",
                "test_delete_request_reports_token_deletion_when_run_record_is_missing",
                "test_delete_request_unlink_exceptions",
            ),
        },
    ),
)

# The new signing protocol is an independent trust boundary, exercised without KMS.
CRITICAL_MUTATION_TARGETS += (
    CriticalMutationTarget(
        BASE_DIR / "agentv_runtime" / "signatures.py",
        (
            "tests/unit/core/test_digest_signature_contract.py",
            "tests/unit/core/test_signing_acceptance_matrix.py",
            "tests/unit/core/test_signing_input_policy_contract.py",
        ),
        frozenset(
            {
                "certificate_payload_bytes",
                "unsigned_envelope",
                "verify_artifact_signature",
                "resolve_policy",
                "validate_signing_response",
                "authorize",
                "sign_payload",
            }
        ),
        excluded_mutations=frozenset({("verify_artifact_signature", 258, "or", "and")}),
        exclusion_reasons={
            ("verify_artifact_signature", 258, "or", "and"): (
                "Equivalent for JSON envelope values: the subsequent exact field-type and "
                "canonical-byte equality checks still reject missing/extra fields. Non-object "
                "JSON values fail those checks or the fail-closed exception boundary; no "
                "additional envelope can verify. JSON shape regressions cover these cases."
            ),
        },
    ),
)

TARGET_MODULES = [target.path for target in CRITICAL_MUTATION_TARGETS]
MODULE_TEST_MAP: dict[Path, tuple[str, ...]] = {
    target.path: target.tests for target in CRITICAL_MUTATION_TARGETS
}
MODULE_SCOPE_MAP: dict[Path, frozenset[str]] = {
    target.path: target.scopes for target in CRITICAL_MUTATION_TARGETS
}
MODULE_REQUIRED_OPERATOR_FAMILIES: dict[Path, frozenset[str]] = {
    target.path: target.required_operator_families for target in CRITICAL_MUTATION_TARGETS
}
MODULE_ELIGIBLE_OPERATOR_FAMILIES: dict[Path, frozenset[str]] = {
    target.path: target.eligible_operator_families for target in CRITICAL_MUTATION_TARGETS
}
MODULE_EXCLUDED_MUTATIONS: dict[Path, frozenset[tuple[str, int, str, str]]] = {
    target.path: target.excluded_mutations for target in CRITICAL_MUTATION_TARGETS
}
MODULE_SCOPE_TEST_MAP: dict[Path, Mapping[str, tuple[str, ...]]] = {
    target.path: target.scope_test_names or {} for target in CRITICAL_MUTATION_TARGETS
}

# Fallback corpus used for baseline verification and any module not in the map
BASELINE_TESTS = [
    "tests/unit/core/test_golden_verifier_matrix.py",
    "tests/security/test_sandbox_adversarial_bypass.py",
    "tests/chaos/test_chaos_resilience.py",
]

# Mutant subprocess timeout, derived from measured wall-clock subprocess times.
#
# IMPORTANT: `subprocess.run(timeout=...)` measures wall-clock time including
# Python startup + import overhead — NOT pytest's self-reported test duration.
# This codebase has ~4s of startup overhead before any test executes.
#
# Timeout = max(wall-clock) * 2.0 = 15.0 * 2.0 = 30.0s (provides 2x headroom).
# Any value below ~10s fires before tests execute → meaningless 100% from timeouts.
MUTANT_TIMEOUT_SECONDS = 30.0
PYTEST_NO_TESTS_COLLECTED = 5


# ---------------------------------------------------------------------------
# Operator token mappings — the textual representation of each mutation.
# These are used for surgical string substitution at the exact source position.
# ---------------------------------------------------------------------------

# Comparison operator text replacements: (original_text, mutated_text)
_COMPARE_MUTATIONS: dict[type, tuple[str, str]] = {
    ast.Eq: ("==", "!="),
    ast.NotEq: ("!=", "=="),
    ast.Lt: ("<", ">="),
    ast.GtE: (">=", "<"),
    ast.Is: ("is", "is not"),
    ast.IsNot: ("is not", "is"),
    ast.In: ("in", "not in"),
    ast.NotIn: ("not in", "in"),
}

# Guard mutations exercise fail-open mistakes that simple equality mutations
# miss: bypassing a negated precondition, weakening conjunctions, and changing
# universal evidence requirements into existential ones.
_BOOLOP_MUTATIONS: dict[type, tuple[str, str]] = {
    ast.And: ("and", "or"),
    ast.Or: ("or", "and"),
}

_QUANTIFIER_MUTATIONS = {"all": "any", "any": "all"}

# Lifecycle values are Runtime authorization boundaries.  Replacing either
# side models the class of defect that permits trace writes while approval is
# pending, or falsely suspends an active run.
_LIFECYCLE_STATE_MUTATIONS = {
    "PAUSED_FOR_APPROVAL": "RUNNING",
    "RUNNING": "PAUSED_FOR_APPROVAL",
}

_APPROVAL_STATE_MUTATIONS = {
    "PENDING": "APPROVED",
    "APPROVED": "PENDING",
    "REJECTED": "APPROVED",
}

# Replacing a commitment key simulates omitting the binding from emitted
# evidence without generating syntactically invalid dictionary literals.
_COMMITMENT_FIELD_MUTATIONS = {
    "profile",
    "payload_digest",
    "payload_projection",
    "signing_algorithm",
    "signing_semantics",
    "public_key_fingerprint",
    "signature_encoding",
    "key_id",
    "certificate_profile",
    "execution_mode",
    "provisional",
    "signature",
    "trace_digest",
    "manifest_hash",
    "scenario_digest",
    "scenario_hash",
    "execution_manifest_hash",
    "evidence_root_hash",
    "finalization_hash",
    "evaluator_signature",
}
_MUTATED_COMMITMENT_FIELD = "__mutation_missing_commitment__"

HIGH_IMPACT_OPERATOR_FAMILIES = frozenset(
    {"approval_gate", "commitment", "guard", "lifecycle", "quantifier", "serialization"}
)

# BinOp operator text replacements
_BINOP_MUTATIONS: dict[type, tuple[str, str]] = {
    ast.Add: ("+", "-"),
    ast.Sub: ("-", "+"),
    ast.BitAnd: ("&", "|"),
    ast.BitOr: ("|", "&"),
}

# Boolean constant replacements
_BOOL_MUTATIONS: dict[bool, tuple[str, str]] = {
    True: ("True", "False"),
    False: ("False", "True"),
}


def _annotation_line_numbers(tree: ast.AST) -> set[int]:
    """
    Return line numbers that belong solely to type annotation context or TYPE_CHECKING blocks.

    Under `from __future__ import annotations`, annotations are not evaluated
    at runtime. Code inside `if TYPE_CHECKING:` is also skipped at runtime.
    Mutations in these positions produce no observable behavior change and are
    classified as INCOMPETENT (excluded from denominator).
    """
    annotation_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            all_args = (
                node.args.args
                + node.args.posonlyargs
                + node.args.kwonlyargs
                + ([node.args.vararg] if node.args.vararg else [])
                + ([node.args.kwarg] if node.args.kwarg else [])
            )
            for arg in all_args:
                if arg.annotation:
                    for n in ast.walk(arg.annotation):
                        if hasattr(n, "lineno"):
                            annotation_lines.add(n.lineno)
            if node.returns:
                for n in ast.walk(node.returns):
                    if hasattr(n, "lineno"):
                        annotation_lines.add(n.lineno)
        elif isinstance(node, ast.AnnAssign):
            for n in ast.walk(node.annotation):
                if hasattr(n, "lineno"):
                    annotation_lines.add(n.lineno)
        elif isinstance(node, ast.If):
            test_name = ""
            if isinstance(node.test, ast.Name):
                test_name = node.test.id
            elif isinstance(node.test, ast.Attribute):
                test_name = node.test.attr
            if test_name == "TYPE_CHECKING":
                for body_item in node.body:
                    for n in ast.walk(body_item):
                        if hasattr(n, "lineno"):
                            annotation_lines.add(n.lineno)
    return annotation_lines


class MutationPoint:
    """
    Describes a single mutation: where it is, what it changes, whether it
    is in an annotation-only (incompetent) position, and its enclosing AST scope.
    """

    __slots__ = (
        "index",
        "lineno",
        "col_offset",
        "original",
        "mutated",
        "description",
        "is_incompetent",
        "scope",
    )

    def __init__(
        self,
        index: int,
        lineno: int,
        col_offset: int,
        original: str,
        mutated: str,
        description: str,
        is_incompetent: bool,
        scope: str = "",
    ):
        self.index = index
        self.lineno = lineno
        self.col_offset = col_offset
        self.original = original
        self.mutated = mutated
        self.description = f"[{index}] line {lineno}: {description}"
        self.is_incompetent = is_incompetent
        self.scope = scope


class _MutationProgress:
    """Compact, xdist-style progress output owned by the coordinating thread."""

    _TOKENS = {
        "killed": (".", "\033[32m"),
        "survived": ("F", "\033[31m"),
        "timeout": ("T", "\033[33m"),
        "indeterminate": ("?", "\033[35m"),
        "incompetent": ("i", "\033[36m"),
    }
    _RESET = "\033[0m"

    def __init__(self, total: int, workers: int, stream: Any | None = None):
        self.total = total
        self.workers = workers
        self.completed = 0
        self.stream = stream if stream is not None else sys.stdout
        self.color = bool(getattr(self.stream, "isatty", lambda: False)()) and not os.getenv(
            "NO_COLOR"
        )

    def start(self) -> None:
        print(
            f"      Progress: 0/{self.total} queued (workers={self.workers}) ",
            end="",
            file=self.stream,
            flush=True,
        )

    def report(self, status: str, description: str | None = None) -> None:
        token, color = self._TOKENS.get(status, ("!", "\033[31m"))
        self.completed += 1
        rendered = f"{color}{token}{self._RESET}" if self.color else token
        print(rendered, end="", file=self.stream, flush=True)
        if description and status in {"survived", "timeout", "indeterminate"}:
            print(
                f"\n      [{status.upper()}] {description}\n      Progress: ",
                end="",
                file=self.stream,
                flush=True,
            )
        if self.completed % 40 == 0 and self.completed < self.total:
            print(
                f" {self.completed}/{self.total}\n      Progress: ",
                end="",
                file=self.stream,
                flush=True,
            )

    def close(self) -> None:
        print(f" {self.completed}/{self.total}", file=self.stream, flush=True)

    def heartbeat(self, active_workers: int) -> None:
        """Make long-running mutant subprocesses visibly alive between completions."""
        print(
            f" {self.completed}/{self.total}\n"
            f"      [RUNNING] {self.completed}/{self.total} complete; "
            f"{active_workers} mutant worker(s) active\n"
            "      Progress: ",
            end="",
            file=self.stream,
            flush=True,
        )


class _MutationVisitor(ast.NodeVisitor):
    """AST visitor that discovers mutation points and tracks enclosing method/class scope."""

    def __init__(self, annotation_lines: set[int], source: str):
        self.annotation_lines = annotation_lines
        self.source = source
        self.source_lines = source.splitlines(keepends=True)
        self.line_offsets: list[int] = []
        offset = 0
        for line in self.source_lines:
            self.line_offsets.append(offset)
            offset += len(line)
        self.points: list[MutationPoint] = []
        self.scope_stack: list[str] = []
        self.guard_depth = 0
        self.display_label_positions: set[tuple[int, int]] = set()
        self.idx = 0

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def _current_scope(self) -> str:
        return self.scope_stack[-1] if self.scope_stack else "module"

    def _absolute_position(self, lineno: int, col_offset: int) -> int:
        # CPython AST columns are UTF-8 byte offsets, while string slices use
        # Unicode code points. Convert before using the source-text index.
        line = self.source_lines[lineno - 1]
        char_offset = len(line.encode("utf-8")[:col_offset].decode("utf-8"))
        return self.line_offsets[lineno - 1] + char_offset

    def _line_col(self, offset: int) -> tuple[int, int]:
        line_index = bisect.bisect_right(self.line_offsets, offset) - 1
        return line_index + 1, offset - self.line_offsets[line_index]

    def _between(self, left: ast.AST, right: ast.AST, token: str) -> tuple[int, int] | None:
        """Locate an operator only in the AST gap between its two operands."""
        if not all(
            hasattr(node, "end_lineno") and hasattr(node, "lineno") for node in (left, right)
        ):
            return None
        start = self._absolute_position(left.end_lineno, left.end_col_offset)
        end = self._absolute_position(right.lineno, right.col_offset)
        gap = self.source[start:end]
        if token.isalnum() or " " in token:
            match = re.search(r"\b" + re.escape(token) + r"\b", gap)
            position = match.start() if match else -1
        else:
            position = gap.find(token)
        return self._line_col(start + position) if position >= 0 else None

    def _before(self, node: ast.AST, following: ast.AST, token: str) -> tuple[int, int] | None:
        """Locate a prefix operator between an AST node start and its operand."""
        start = self._absolute_position(node.lineno, node.col_offset)
        end = self._absolute_position(following.lineno, following.col_offset)
        position = self.source[start:end].find(token)
        return self._line_col(start + position) if position >= 0 else None

    def _visit_guard(self, node: ast.AST) -> None:
        """Visit an authorization/control-flow predicate as a guard context."""
        self.guard_depth += 1
        self.visit(node)
        self.guard_depth -= 1

    def visit_If(self, node: ast.If) -> None:
        self._visit_guard(node.test)
        for statement in node.body:
            self.visit(statement)
        for statement in node.orelse:
            self.visit(statement)

    def visit_While(self, node: ast.While) -> None:
        self._visit_guard(node.test)
        for statement in node.body:
            self.visit(statement)
        for statement in node.orelse:
            self.visit(statement)

    def visit_Assert(self, node: ast.Assert) -> None:
        self._visit_guard(node.test)
        if node.msg:
            self.visit(node.msg)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self._visit_guard(node.test)
        self.visit(node.body)
        self.visit(node.orelse)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self.visit(node.target)
        self.visit(node.iter)
        for condition in node.ifs:
            self._visit_guard(condition)

    def visit_Compare(self, node: ast.Compare) -> None:
        lineno = getattr(node, "lineno", None)
        in_annotation = lineno is not None and lineno in self.annotation_lines
        scope = self._current_scope()

        for op_index, op in enumerate(node.ops):
            op_type = type(op)
            if op_type in {ast.In, ast.NotIn} and not self.guard_depth:
                continue
            if op_type in _COMPARE_MUTATIONS:
                orig, mut = _COMPARE_MUTATIONS[op_type]
                left = node.left if op_index == 0 else node.comparators[op_index - 1]
                location = self._between(left, node.comparators[op_index], orig)
                if location is None:
                    continue
                op_lineno, op_col = location
                desc = f"{op_type.__name__} ({orig}) -> ({mut})"
                self.points.append(
                    MutationPoint(
                        self.idx, op_lineno, op_col, orig, mut, desc, in_annotation, scope
                    )
                )
                self.idx += 1
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        lineno = getattr(node, "lineno", None)
        in_annotation = lineno is not None and lineno in self.annotation_lines
        scope = self._current_scope()

        op_type = type(node.op)
        if op_type in _BINOP_MUTATIONS:
            orig, mut = _BINOP_MUTATIONS[op_type]
            location = self._between(node.left, node.right, orig)
            if location is None:
                self.generic_visit(node)
                return
            op_lineno, op_col = location
            desc = f"{orig} -> {mut}"
            self.points.append(
                MutationPoint(self.idx, op_lineno, op_col, orig, mut, desc, in_annotation, scope)
            )
            self.idx += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        if not self.guard_depth:
            self.generic_visit(node)
            return

        lineno = getattr(node, "lineno", None)
        in_annotation = lineno is not None and lineno in self.annotation_lines
        scope = self._current_scope()
        op_type = type(node.op)

        if op_type in _BOOLOP_MUTATIONS:
            orig, mut = _BOOLOP_MUTATIONS[op_type]
            for value_index in range(len(node.values) - 1):
                location = self._between(
                    node.values[value_index], node.values[value_index + 1], orig
                )
                if location is None:
                    continue
                op_lineno, op_col = location
                self.points.append(
                    MutationPoint(
                        self.idx,
                        op_lineno,
                        op_col,
                        orig,
                        mut,
                        f"guard {orig} -> {mut}",
                        in_annotation,
                        scope,
                    )
                )
                self.idx += 1
        self.generic_visit(node)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:
        if not self.guard_depth or not isinstance(node.op, ast.Not):
            self.generic_visit(node)
            return

        lineno = getattr(node, "lineno", None)
        in_annotation = lineno is not None and lineno in self.annotation_lines
        location = self._before(node, node.operand, "not")
        if location is None:
            self.generic_visit(node)
            return
        op_lineno, op_col = location
        self.points.append(
            MutationPoint(
                self.idx,
                op_lineno,
                op_col,
                "not",
                "",
                "guard not -> removed",
                in_annotation,
                self._current_scope(),
            )
        )
        self.idx += 1
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if (
            self.guard_depth
            and isinstance(node.func, ast.Name)
            and node.func.id in _QUANTIFIER_MUTATIONS
        ):
            lineno, col = self._line_col(
                self._absolute_position(node.func.lineno, node.func.col_offset)
            )
            in_annotation = lineno is not None and lineno in self.annotation_lines
            original = node.func.id
            self.points.append(
                MutationPoint(
                    self.idx,
                    lineno,
                    col,
                    original,
                    _QUANTIFIER_MUTATIONS[original],
                    f"quantifier {original} -> {_QUANTIFIER_MUTATIONS[original]}",
                    in_annotation,
                    self._current_scope(),
                )
            )
            self.idx += 1
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "json"
            and node.func.attr == "dumps"
        ):
            for keyword in node.keywords:
                if (
                    keyword.arg == "default"
                    and isinstance(keyword.value, ast.Name)
                    and keyword.value.id == "str"
                ):
                    lineno, col = self._line_col(
                        self._absolute_position(keyword.value.lineno, keyword.value.col_offset)
                    )
                    self.points.append(
                        MutationPoint(
                            self.idx,
                            lineno,
                            col,
                            "str",
                            "None",
                            "serialization default str -> None",
                            lineno in self.annotation_lines,
                            self._current_scope(),
                        )
                    )
                    self.idx += 1
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in _LIFECYCLE_STATE_MUTATIONS:
            attr_end = self._absolute_position(node.end_lineno, node.end_col_offset)
            lineno, col = self._line_col(attr_end - len(node.attr))
            in_annotation = lineno is not None and lineno in self.annotation_lines
            self.points.append(
                MutationPoint(
                    self.idx,
                    lineno,
                    col,
                    node.attr,
                    _LIFECYCLE_STATE_MUTATIONS[node.attr],
                    f"lifecycle {node.attr} -> {_LIFECYCLE_STATE_MUTATIONS[node.attr]}",
                    in_annotation,
                    self._current_scope(),
                )
            )
            self.idx += 1
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if (node.lineno, node.col_offset) in self.display_label_positions:
            return
        lineno, col = self._line_col(self._absolute_position(node.lineno, node.col_offset))
        in_annotation = lineno is not None and lineno in self.annotation_lines
        scope = self._current_scope()

        if isinstance(node.value, bool):
            val = node.value
            orig, mut = _BOOL_MUTATIONS[val]
            desc = f"{orig} -> {mut}"
            self.points.append(
                MutationPoint(self.idx, lineno, col, orig, mut, desc, in_annotation, scope)
            )
            self.idx += 1
        elif isinstance(node.value, str) and node.value in _APPROVAL_STATE_MUTATIONS:
            self.points.append(
                MutationPoint(
                    self.idx,
                    lineno,
                    col,
                    node.value,
                    _APPROVAL_STATE_MUTATIONS[node.value],
                    f"approval state {node.value} -> {_APPROVAL_STATE_MUTATIONS[node.value]}",
                    in_annotation,
                    scope,
                )
            )
            self.idx += 1
        elif isinstance(node.value, str) and node.value in _COMMITMENT_FIELD_MUTATIONS:
            self.points.append(
                MutationPoint(
                    self.idx,
                    lineno,
                    col,
                    node.value,
                    _MUTATED_COMMITMENT_FIELD,
                    f"commitment field {node.value} -> omitted",
                    in_annotation,
                    scope,
                )
            )
            self.idx += 1
        self.generic_visit(node)


def discover_mutation_points(source: str, annotation_lines: set[int]) -> list[MutationPoint]:
    """
    Walk the AST and enumerate every mutatable node as a MutationPoint.
    Uses col_offset from the AST to locate the exact operator in the source line.
    Captures enclosing function/class scope for targeted test dispatch.
    """
    tree = ast.parse(source)
    visitor = _MutationVisitor(annotation_lines, source)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}

    def error_only_label(use: ast.Name) -> bool:
        current = parents.get(use)
        while isinstance(current, (ast.FormattedValue, ast.JoinedStr)):
            current = parents.get(current)
        return bool(
            isinstance(current, ast.Call)
            and isinstance(current.func, ast.Name)
            and current.func.id in {"ValueError", "TypeError"}
            and isinstance(parents.get(current), ast.Raise)
        )

    def owner(node: ast.AST) -> ast.AST:
        while node in parents:
            node = parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                return node
        return tree

    error_label_scopes: set[ast.AST] = set()
    for loop in ast.walk(tree):
        if (
            isinstance(loop, ast.For)
            and isinstance(loop.iter, ast.Name)
            and loop.iter.id == "mandatory_str_fields"
            and isinstance(loop.target, ast.Tuple)
            and len(loop.target.elts) == 2
            and isinstance(loop.target.elts[1], ast.Name)
        ):
            name = loop.target.elts[1].id
            uses = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id == name
                and owner(node) is owner(loop)
            ]
            if uses and all(error_only_label(use) for use in uses):
                error_label_scopes.add(owner(loop))
    # The second item in this validation specification is an error label,
    # not a data key or a cryptographic commitment.
    for assignment in ast.walk(tree):
        if (
            isinstance(assignment, ast.Assign)
            and owner(assignment) in error_label_scopes
            and any(
                isinstance(target, ast.Name) and target.id == "mandatory_str_fields"
                for target in assignment.targets
            )
            and isinstance(assignment.value, (ast.List, ast.Tuple))
        ):
            for entry in assignment.value.elts:
                if isinstance(entry, ast.Tuple) and len(entry.elts) == 2:
                    label = entry.elts[1]
                    if isinstance(label, ast.Constant) and isinstance(label.value, str):
                        visitor.display_label_positions.add((label.lineno, label.col_offset))
    visitor.visit(tree)
    return visitor.points


def mutation_operator_family(point: MutationPoint) -> str:
    """Classify a mutant for manifest-level assurance requirements."""
    if point.original in _LIFECYCLE_STATE_MUTATIONS:
        return "lifecycle"
    if point.original in _APPROVAL_STATE_MUTATIONS:
        return "approval_gate"
    if point.original in _COMMITMENT_FIELD_MUTATIONS:
        return "commitment"
    if point.description.endswith("serialization default str -> None"):
        return "serialization"
    if point.original in {"not", "and", "or", "in", "not in"}:
        return "guard"
    if point.original in _QUANTIFIER_MUTATIONS:
        return "quantifier"
    if point.original in {"True", "False"}:
        return "boolean"
    if point.original in {"+", "-", "&", "|"}:
        return "arithmetic"
    return "comparison"


def discover_defined_scopes(tree: ast.AST) -> set[str]:
    """Return declared function scopes, including scopes with no mutable operator."""
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _apply_surgical_mutation(source_lines: list[str], mp: MutationPoint) -> str | None:
    """
    Apply a single mutation by targeted string replacement on the exact source line.

    The original token is searched starting from col_offset on the target line.
    If the token is not found (e.g., due to multi-line AST reordering), returns
    None and the mutant is classified as INCOMPETENT.

    This preserves ALL other lines byte-for-byte, avoiding hash-corruption in
    TraceVerifier-based tests and source-pattern guards.
    """
    if mp.lineno is None or mp.lineno > len(source_lines):
        return None

    line = source_lines[mp.lineno - 1]  # 1-indexed

    # Search from col_offset forward for the original token
    search_start = mp.col_offset
    if mp.original.isalnum() or all(c.isalnum() or c == " " for c in mp.original):
        import re

        pattern = re.compile(r"\b" + re.escape(mp.original) + r"\b")
        match = pattern.search(line, search_start)
        pos = match.start() if match else -1
    else:
        pos = line.find(mp.original, search_start)

    if pos == -1:
        return None  # Token not found on expected line → incompetent

    mutated_line = line[:pos] + mp.mutated + line[pos + len(mp.original) :]
    result_lines = source_lines[: mp.lineno - 1] + [mutated_line] + source_lines[mp.lineno :]
    return "".join(result_lines)


def count_mutation_points(source: str, annotation_lines: set[int]) -> int:
    """Counts total mutatable nodes."""
    return len(discover_mutation_points(source, annotation_lines))


def _tests_for_module(target: Path) -> list[str]:
    """Return the relevant test paths for a given target module filename."""
    return list(MODULE_TEST_MAP.get(target, tuple(BASELINE_TESTS)))


def _mutation_cache_key(
    module_name: str, tests: list[str], scope: str
) -> tuple[str, tuple[str, ...], str]:
    """Return a cache key that cannot leak killers between target corpora."""
    return module_name, tuple(tests), scope


def _collected_no_tests(returncode: int) -> bool:
    """Identify pytest's explicit no-tests-collected outcome."""
    return returncode == PYTEST_NO_TESTS_COLLECTED


def _test_source_path(selector: str) -> Path:
    return BASE_DIR / selector.split("::", 1)[0]


def _declared_test_names(tests: list[str]) -> set[str]:
    """Return test function names without starting pytest just to probe ``-k``.

    A source scope such as ``resolve_request`` is usually not part of a test
    name.  Starting a Python process merely to discover that fact is expensive
    and guarantees an unnecessary full-corpus fallback for every mutant.
    """
    names: set[str] = set()
    for test_path in tests:
        try:
            tree = ast.parse(_test_source_path(test_path).read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError) as err:
            raise RuntimeError(
                f"Cannot inspect configured mutation test {test_path}: {err}"
            ) from err
        names.update(
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name.startswith("test_")
        )
    return names


def _scope_selector_available(scope: str, declared_test_names: set[str]) -> bool:
    """Whether a conventional ``-k <source scope>`` selector can collect a test."""
    normalized_scope = scope.casefold()
    return any(normalized_scope in test_name.casefold() for test_name in declared_test_names)


def _scope_test_selector(target: Path, scope: str, declared_test_names: set[str]) -> str | None:
    """Return a vetted explicit selector, or a viable conventional scope selector."""
    explicit_names = MODULE_SCOPE_TEST_MAP.get(target, {}).get(scope, ())
    if explicit_names:
        missing_names = set(explicit_names) - declared_test_names
        if missing_names:
            raise RuntimeError(
                f"Configured mutation selector for {target.name}:{scope} references missing tests: "
                f"{sorted(missing_names)}"
            )
        return " or ".join(explicit_names)
    if _scope_selector_available(scope, declared_test_names):
        return scope
    return None


def _partition_scope_primers(
    points: list[MutationPoint],
) -> tuple[list[MutationPoint], list[MutationPoint]]:
    """Reserve the first deterministic mutant from each source scope as a cache primer."""
    primers: list[MutationPoint] = []
    remainder: list[MutationPoint] = []
    primed_scopes: set[str] = set()
    for point in points:
        if point.scope not in primed_scopes:
            primers.append(point)
            primed_scopes.add(point.scope)
        else:
            remainder.append(point)
    return primers, remainder


def _sha3_file(path: Path) -> str:
    """Return the SHA3-256 content digest used to invalidate baseline cache entries."""
    return hashlib.sha3_256(path.read_bytes()).hexdigest()


def _baseline_cache_key(tests: tuple[str, ...], targets: tuple[Path, ...]) -> str:
    """Bind a reusable baseline to its exact executable test context."""
    import pytest

    context_files = (
        BASE_DIR / "pyproject.toml",
        BASE_DIR / "tests" / "conftest.py",
        Path(__file__).resolve(),
    )
    environment = {
        name: value
        for name, value in os.environ.items()
        if name == "CI" or name.startswith(("AGENTV_", "PYTEST_", "COVERAGE_"))
    }
    payload = {
        "cache_version": BASELINE_CACHE_VERSION,
        "python_version": sys.version,
        "pytest_version": pytest.__version__,
        "pytest_flags": FAST_PYTEST_FLAGS,
        "tests": [(path, _sha3_file(_test_source_path(path))) for path in tests],
        "targets": [
            (path.relative_to(BASE_DIR).as_posix(), _sha3_file(path))
            for path in sorted(targets, key=lambda item: item.as_posix())
        ],
        "context_files": [
            (path.relative_to(BASE_DIR).as_posix(), _sha3_file(path))
            for path in context_files
            if path.exists()
        ],
        "environment": environment,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha3_256(encoded).hexdigest()


def _load_baseline_cache() -> dict[str, dict[str, Any]]:
    """Load only well-formed cache entries; malformed cache data is never trusted."""
    if not BASELINE_CACHE_PATH.exists():
        return {}
    try:
        payload = json.loads(BASELINE_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
        sys.stderr.write(f"  [Warn] Ignoring unreadable baseline cache: {err}\n")
        return {}
    if not isinstance(payload, dict) or payload.get("version") != BASELINE_CACHE_VERSION:
        return {}
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        return {}
    return {
        key: entry
        for key, entry in entries.items()
        if isinstance(key, str)
        and isinstance(entry, dict)
        and isinstance(entry.get("duration_seconds"), (int, float))
        and entry["duration_seconds"] > 0
    }


def _write_baseline_cache(entries: Mapping[str, Mapping[str, Any]]) -> None:
    """Persist successful baseline timings as an ignored reports artifact."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"version": BASELINE_CACHE_VERSION, "entries": entries}
    try:
        BASELINE_CACHE_PATH.write_text(
            json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8"
        )
    except OSError as err:
        sys.stderr.write(f"  [Warn] Could not write baseline cache: {err}\n")


def format_sentinel_duration(duration_seconds: float) -> str:
    """Render precise elapsed seconds alongside a pytest-style wall-clock duration."""
    whole_seconds = max(0, int(duration_seconds))
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{duration_seconds:.2f}s ({hours}:{minutes:02d}:{seconds:02d})"


def _make_loader_code(mutant_source: str, orig_file: Path, module_name: str, args_str: str) -> str:
    """Build a subprocess loader that receives the mutant only through stdin."""
    encoded_source = base64.b64encode(mutant_source.encode("utf-8")).decode("ascii")

    return f"""
import base64, sys, importlib, importlib.abc, importlib.util
sys.path.insert(0, r"{BASE_DIR}")
source = base64.b64decode({encoded_source!r}).decode("utf-8")
code = compile(source, r"{orig_file}", "exec")
class MutantModule(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "{module_name}":
            return importlib.util.spec_from_file_location(fullname, r"{orig_file}", loader=self)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        exec(code, module.__dict__)

# Install before importing the package. Its normal initialization and all
# transitive imports must see the same mutant, including re-exported symbols.
sys.meta_path.insert(0, MutantModule())
importlib.import_module("{module_name}")
import pytest
sys.exit(pytest.main({args_str}))
"""


def evaluate_mutant(
    target_file: Path,
    mutant_source: str,
    tests: list[str],
    timeout_seconds: float = 30.0,
    original_bytes: bytes | None = None,
    scope: str = "",
    scope_test_selector: str | None = None,
    killer_cache: dict[tuple[str, tuple[str, ...], str], str] | None = None,
    cache_lock: threading.Lock | None = None,
    module_timing: ModuleTiming | None = None,
) -> str:
    """
    Evaluates mutant using dynamic in-memory injection without mutating target_file on disk.
    Applies 3-phase cascading acceleration:
      1. Cached killer-test execution (stops in ~1 test if cached)
      2. Targeted source-scope test execution (-k selector -x), when viable
      3. Fallback full module corpus execution (-x)
    Returns status: 'killed', 'survived', 'timeout', 'indeterminate', or
    'incompetent'. A timeout is retried serially by the module coordinator.
    """
    # 1. In-process AST syntax pre-check before touching disk or spawning subprocess
    try:
        compile(mutant_source, str(target_file), "exec")
    except Exception as syntax_err:
        sys.stderr.write(f"      [Mutant] Incompetent AST syntax: {syntax_err}\n")
        return "incompetent"

    rel_path = target_file.resolve().relative_to(BASE_DIR)
    module_name = ".".join(rel_path.with_suffix("").parts)
    target_resolved = target_file.resolve()

    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = f"{BASE_DIR}{os.pathsep}{env.get('PYTHONPATH', '')}"

    cache_key = _mutation_cache_key(module_name, tests, scope)

    def _extract_and_cache_killer(output: str) -> None:
        if killer_cache is not None and scope and scope != "module":
            m = re.search(r"FAILED\s+[^:]+::([A-Za-z0-9_]+)", output)
            if m:
                test_name = m.group(1)
                if cache_lock:
                    with cache_lock:
                        killer_cache[cache_key] = test_name
                else:
                    killer_cache[cache_key] = test_name

    try:
        # Phase 1: Try cached killer test first (fast-fail on 1 test)
        cached_killer = None
        if killer_cache and scope:
            if cache_lock:
                with cache_lock:
                    cached_killer = killer_cache.get(cache_key)
            else:
                cached_killer = killer_cache.get(cache_key)

        if cached_killer:
            if module_timing is not None:
                module_timing.record_cache_hit()
            fast_flags = FAST_PYTEST_FLAGS + ["-k", cached_killer, "-x"]
            args_str = repr(tests + fast_flags)
            loader_code = _make_loader_code(mutant_source, target_resolved, module_name, args_str)
            res = subprocess.run(
                [sys.executable, "-B", "-"],
                cwd=BASE_DIR,
                capture_output=True,
                input=loader_code,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
            if _collected_no_tests(res.returncode):
                # Cached selectors can become stale as tests are renamed or
                # moved. They are an optimization, never kill evidence.
                if cache_lock:
                    with cache_lock:
                        killer_cache.pop(cache_key, None)
                else:
                    killer_cache.pop(cache_key, None)
            elif res.returncode == 1:
                return "killed"
            elif res.returncode != 0:
                return "indeterminate"

        # Phase 2: Scoped test filter.  The selector is vetted from the test
        # AST once per scope; never spawn an empty ``-k resolve_request`` probe.
        if scope_test_selector:
            scoped_flags = FAST_PYTEST_FLAGS + ["-k", scope_test_selector, "-x"]
            args_str = repr(tests + scoped_flags)
            loader_code = _make_loader_code(mutant_source, target_resolved, module_name, args_str)
            res = subprocess.run(
                [sys.executable, "-B", "-"],
                cwd=BASE_DIR,
                capture_output=True,
                input=loader_code,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
            if res.returncode == 1:
                _extract_and_cache_killer(res.stdout)
                return "killed"
            if res.returncode != 0 and not _collected_no_tests(res.returncode):
                return "indeterminate"

        # Phase 3: Fallback full module corpus
        if module_timing is not None:
            module_timing.record_full_corpus_fallback()
        full_flags = FAST_PYTEST_FLAGS + ["-x"]
        args_str = repr(tests + full_flags)
        loader_code = _make_loader_code(mutant_source, target_resolved, module_name, args_str)
        res = subprocess.run(
            [sys.executable, "-B", "-"],
            cwd=BASE_DIR,
            capture_output=True,
            input=loader_code,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
        if _collected_no_tests(res.returncode):
            sys.stderr.write(
                "      [Mutant] Full corpus collected no tests; mutation result is indeterminate.\n"
            )
            return "indeterminate"
        if res.returncode == 1:
            _extract_and_cache_killer(res.stdout)
            return "killed"
        if res.returncode != 0:
            return "indeterminate"
        return "survived"
    except subprocess.TimeoutExpired:
        return "timeout"
    except (SyntaxError, UnicodeDecodeError, OSError, ValueError) as err:
        sys.stderr.write(f"      [Mutant] Incompetent AST substitution: {err}\n")
        return "incompetent"


def verify_sentinel_preconditions(
    active_targets: list[Path] | None = None,
    *,
    workers: int = 1,
) -> tuple[dict[str, float], dict[Path, float]]:
    """
    Self-validating precondition checks executed before any mutation testing begins.

    Prevents silent failure modes:
      1. Missing test files referenced in MODULE_TEST_MAP or BASELINE_TESTS.
      2. Missing target module files.
      3. Failing un-mutated baseline tests or empty test collections.
      4. Dynamically scales per-module timeout to guarantee >= 2.0x headroom on any host.
    """
    import time

    targets_to_check = active_targets if active_targets is not None else list(TARGET_MODULES)
    print("\n1. Running Self-Validating Sentinel Precondition Checks...")

    # Check target modules existence
    for target in targets_to_check:
        if not target.exists():
            rel = target.relative_to(BASE_DIR)
            print(f"  [FAIL] Target module missing: {rel}")
            sys.exit(1)
        try:
            tree = ast.parse(target.read_text(encoding="utf-8"))
            available_scopes = discover_defined_scopes(tree)
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            print(f"  [FAIL] Cannot inspect critical mutation target {target}: {exc}")
            sys.exit(1)
        missing_scopes = MODULE_SCOPE_MAP[target] - available_scopes
        if missing_scopes:
            print(
                f"  [FAIL] Critical mutation scopes missing from {target.name}: "
                f"{sorted(missing_scopes)}"
            )
            sys.exit(1)
        selected_points = [
            point
            for point in discover_mutation_points(
                target.read_text(encoding="utf-8"), _annotation_line_numbers(tree)
            )
            if point.scope in MODULE_SCOPE_MAP[target]
        ]
        configuration = next(item for item in CRITICAL_MUTATION_TARGETS if item.path == target)
        excluded = MODULE_EXCLUDED_MUTATIONS[target]
        reasons = configuration.exclusion_reasons or {}
        available_points = {
            (point.scope, point.lineno, point.original, point.mutated) for point in selected_points
        }
        if set(reasons) != excluded or excluded - available_points or not all(reasons.values()):
            print(f"  [FAIL] Unreviewed or stale mutation exclusions for {target.name}")
            sys.exit(1)
        if excluded:
            print(f"   [Reviewed exclusions] {target.name}: {len(excluded)} explicit exclusions")
        selected_points = [
            point
            for point in selected_points
            if (point.scope, point.lineno, point.original, point.mutated) not in excluded
        ]
        present_families = {mutation_operator_family(point) for point in selected_points}
        missing_families = MODULE_REQUIRED_OPERATOR_FAMILIES[target] - present_families
        if missing_families:
            print(
                f"  [FAIL] Critical mutation families missing from {target.name}: "
                f"{sorted(missing_families)}"
            )
            sys.exit(1)

    # Check test file existence
    all_test_paths = set(BASELINE_TESTS) if active_targets is None else set()
    for target in targets_to_check:
        all_test_paths.update(MODULE_TEST_MAP.get(target, ()))

    for test_path in all_test_paths:
        full_path = _test_source_path(test_path)
        if not full_path.exists():
            print(f"  [FAIL] Configured test file missing: {test_path}")
            sys.exit(1)

    # Explicit source-scope mappings are executable configuration, not best
    # effort hints.  Fail before mutation fan-out if a renamed test would turn
    # a critical boundary back into an expensive and less precise fallback.
    for target in targets_to_check:
        scope_map = MODULE_SCOPE_TEST_MAP.get(target, {})
        declared_names = _declared_test_names(_tests_for_module(target))
        for scope, test_names in scope_map.items():
            unknown_names = set(test_names) - declared_names
            if unknown_names:
                print(
                    f"  [FAIL] Critical selector mapping for {target.name}:{scope} "
                    f"references missing tests: {sorted(unknown_names)}"
                )
                sys.exit(1)

    # Prove each unmodified target through the same loader used for mutants.
    # A native import baseline cannot detect loader-induced collection failures.
    # Deliberately serial: concurrent Python/pytest startup is slower and less
    # stable on Windows under import and disk contention.
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = f"{BASE_DIR}{os.pathsep}{env.get('PYTHONPATH', '')}"
    module_timeouts: dict[str, float] = {}
    baseline_durations: dict[Path, float] = {}
    baseline_cache = _load_baseline_cache()
    corpus_groups = [(tuple(_tests_for_module(target)), [target]) for target in targets_to_check]

    for tests, targets in corpus_groups:
        cache_key = _baseline_cache_key(tests, tuple(targets))
        # Historical timings are artifacts, never substitutes for a live control.
        args_str = repr(list(tests) + FAST_PYTEST_FLAGS)
        target = targets[0]
        module_name = ".".join(target.relative_to(BASE_DIR).with_suffix("").parts)
        py_code = _make_loader_code(
            target.read_text(encoding="utf-8"), target, module_name, args_str
        )
        cmd = [sys.executable, "-B", "-"]
        t0 = time.monotonic()
        res = subprocess.run(
            cmd, input=py_code, cwd=BASE_DIR, capture_output=True, text=True, env=env
        )
        elapsed = time.monotonic() - t0

        if res.returncode != 0:
            names = ", ".join(target.name for target in targets)
            print(f"  [FAIL] Baseline test suite for '{names}' failed or collected no tests!")
            print(f"         Command output:\n{res.stdout}\n{res.stderr}")
            sys.exit(1)

        baseline_cache[cache_key] = {
            "duration_seconds": elapsed,
            "tests": list(tests),
            "targets": [target.relative_to(BASE_DIR).as_posix() for target in targets],
        }
        status = "verified"

        print(
            f"   [Baseline {status}] corpus={', '.join(tests)} "
            f"targets={', '.join(target.name for target in targets)}"
        )
        for target in targets:
            module_name = target.name
            dynamic_timeout = max(MUTANT_TIMEOUT_SECONDS, elapsed * max(2.5, max(1, workers) * 1.5))
            module_timeouts[module_name] = dynamic_timeout
            baseline_durations[target] = elapsed
            headroom = dynamic_timeout / elapsed if elapsed > 0 else 999.0
            print(
                f"   • Module '{module_name}' baseline: {elapsed:.2f}s "
                f"(Timeout: {dynamic_timeout:.1f}s, Headroom: {headroom:.2f}x)"
            )

    _write_baseline_cache(baseline_cache)
    print("  [OK] Precondition checks PASSED cleanly.\n")
    return module_timeouts, baseline_durations


def _evaluate_target_module(
    target: Path,
    args: Any,
    module_timeouts: dict[str, float],
    baseline_seconds: float,
    shared_killer_cache: dict[tuple[str, tuple[str, ...], str], str] | None = None,
    cache_lock: threading.Lock | None = None,
) -> tuple[int, int, int, int, int, list[dict], ModuleTiming]:
    """
    Evaluates mutants for a single target module using mutant-level concurrency.
    Returns: (killed, survived, timeout, indeterminate, incompetent, mutant_records, timing)
    """
    rel_path = target.relative_to(BASE_DIR)
    module_name = target.name
    tests = _tests_for_module(target)
    declared_test_names = _declared_test_names(tests)
    timeout_sec = module_timeouts.get(module_name, MUTANT_TIMEOUT_SECONDS)

    original_bytes = target.read_bytes()
    original_source = target.read_text(encoding="utf-8")
    source_lines = [line + "\n" for line in original_source.splitlines()]

    try:
        tree = ast.parse(original_source)
    except Exception as exc:
        print(f"  [FAIL] Failed to parse AST for {rel_path}: {exc}")
        sys.exit(1)

    annotation_lines = _annotation_line_numbers(tree)
    all_points = discover_mutation_points(original_source, annotation_lines)
    selected_scopes = MODULE_SCOPE_MAP.get(target, frozenset())
    required_families = MODULE_REQUIRED_OPERATOR_FAMILIES.get(target, frozenset())
    eligible_families = (
        MODULE_ELIGIBLE_OPERATOR_FAMILIES[target]
        or required_families
        or HIGH_IMPACT_OPERATOR_FAMILIES
    )
    scoped_points = [
        point
        for point in all_points
        if point.scope in selected_scopes
        and mutation_operator_family(point) in eligible_families
        and (point.scope, point.lineno, point.original, point.mutated)
        not in MODULE_EXCLUDED_MUTATIONS[target]
    ]
    num_points = len(scoped_points)
    competent_points = [p for p in scoped_points if not p.is_incompetent]
    num_competent = len(competent_points)

    if args.full:
        sampled = scoped_points
        print(
            f"   • Module: {rel_path} ({num_points} critical-surface mutation points, "
            "evaluating ALL 100%)"
        )
    else:
        max_mutants = min(num_competent, 15)
        rng = random.Random(args.seed) if args.seed is not None else random.Random()
        sampled = (
            rng.sample(competent_points, max_mutants)
            if num_competent > max_mutants
            else list(competent_points)
        )
        sampled.sort(key=lambda p: (p.lineno, p.col_offset))
        seed_info = f" [seed={args.seed}]" if args.seed is not None else ""
        print(
            f"   • Module: {rel_path} ({num_points} total, {num_competent} runtime-effective, "
            f"randomly sampled {len(sampled)}{seed_info})"
        )

    killed = 0
    survived = 0
    timeout = 0
    indeterminate = 0
    incompetent = 0
    records: list[dict] = []
    timing = ModuleTiming(baseline_seconds=baseline_seconds)
    mutation_started_at = time.monotonic()

    num_workers = max(1, getattr(args, "workers", 1))
    progress = _MutationProgress(len(sampled), num_workers)

    def _eval_one(mp: MutationPoint) -> tuple[str, str, MutationPoint]:
        if mp.is_incompetent:
            return "incompetent", f"{mp.description}  (annotation-only, no runtime effect)", mp

        mutant_source = _apply_surgical_mutation(source_lines, mp)
        if mutant_source is None:
            desc = (
                f"{mp.description}  "
                f"(token not locatable at col {mp.col_offset} on line {mp.lineno})"
            )
            return "incompetent", desc, mp

        status = evaluate_mutant(
            target,
            mutant_source,
            tests,
            timeout_seconds=timeout_sec,
            original_bytes=original_bytes,
            scope=mp.scope,
            scope_test_selector=_scope_test_selector(target, mp.scope, declared_test_names),
            killer_cache=shared_killer_cache,
            cache_lock=cache_lock,
            module_timing=timing,
        )
        return status, mp.description, mp

    evaluations: list[tuple[str, str, MutationPoint]] = []
    progress.start()
    # Prime exactly one mutant per source scope before concurrent fan-out.
    # Once a primer identifies its killer, sibling mutants start with that one
    # test rather than racing to repeat an expensive full-corpus fallback.
    primers, remainder = _partition_scope_primers(sampled)
    for primer in primers:
        result = _eval_one(primer)
        evaluations.append(result)
        progress.report(result[0], f"{result[2].scope}: {result[1]}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as pool:
        pending = {pool.submit(_eval_one, mp) for mp in remainder}
        while pending:
            completed, pending = concurrent.futures.wait(
                pending,
                timeout=10.0,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            if not completed:
                progress.heartbeat(min(num_workers, len(pending)))
                continue
            for future in completed:
                result = future.result()
                evaluations.append(result)
                progress.report(result[0], f"{result[2].scope}: {result[1]}")
    progress.close()

    # Timeout retries run only after every parallel worker has completed so
    # the retry is serial and free of mutant-level resource contention.
    final_evaluations: list[tuple[str, str, MutationPoint]] = []
    for status, desc, mp in evaluations:
        if status == "timeout":
            print(f"      [RETRY SERIAL]   [{rel_path.as_posix()}] {desc}", flush=True)
            timing.record_timeout_retry()
            status, desc, mp = _eval_one(mp)
        final_evaluations.append((status, desc, mp))

    for status, desc, mp in final_evaluations:
        if status == "killed":
            killed += 1
            icon = "[KILLED]"
        elif status == "timeout":
            timeout += 1
            icon = "[TIMEOUT]"
        elif status == "survived":
            survived += 1
            icon = "[SURVIVED]"
        elif status == "indeterminate":
            indeterminate += 1
            icon = "[INDETERMINATE]"
        else:
            incompetent += 1
            icon = "[INCOMPETENT]"

        records.append({"module": str(rel_path), "mutation": mp.description, "status": status})
        print(f"      {icon:15s} [{rel_path.as_posix()}] {desc}", flush=True)

    timing.mutant_seconds = time.monotonic() - mutation_started_at
    return killed, survived, timeout, indeterminate, incompetent, records, timing


def assert_sources_unchanged(sources: Mapping[Path, bytes]) -> None:
    """Invalidate a run when its inputs change, preserving every workspace edit."""
    changed = []
    for path, expected in sources.items():
        try:
            if path.read_bytes() != expected:
                changed.append(str(path))
        except OSError:
            changed.append(str(path))
    if changed:
        raise RuntimeError(
            "MutationSourceChanged: validation inputs changed; workspace edits preserved: "
            + ", ".join(changed)
        )


def run_mutation_sentinel() -> None:
    """Executes full or sampled mutation scoring lifecycle across critical verification modules."""
    import argparse

    started_at = time.monotonic()

    parser = argparse.ArgumentParser(description="Industrial Mutation Testing Sentinel")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Evaluate 100%% of discovered mutation points (Nightly/Release CI mode).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional RNG seed for reproducible random sampling in non-full mode.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of concurrent mutant evaluations within each module (default: 1).",
    )
    parser.add_argument(
        "--target",
        type=str,
        default=None,
        help="Optional module name or path substring to filter targets (e.g. evidence_graph.py).",
    )
    args = parser.parse_args()

    seed_suffix = f", seed={args.seed}" if args.seed is not None else ""
    worker_suffix = f", workers={args.workers}" if args.workers > 1 else ""
    mode_label = (
        "FULL POPULATION"
        if args.full
        else f"RANDOMLY SAMPLED (max 15/module{seed_suffix}{worker_suffix})"
    )

    print("=" * 80)
    print(f"=== INDUSTRIAL MUTATION TESTING SENTINEL & ASSURANCE PIPELINE ({mode_label}) ===")
    # Keep validation and its shared reports isolated from concurrent runners.
    lock_file = BASE_DIR / ".mutation_testing.lock"
    import os

    if lock_file.exists():
        try:
            old_pid = int(lock_file.read_text(encoding="utf-8").strip())
            # Check if process is still running
            import ctypes

            kernel32 = getattr(ctypes, "windll", None)
            is_running = False
            if os.name == "nt" and kernel32:
                # Windows check
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                handle = kernel32.kernel32.OpenProcess(
                    PROCESS_QUERY_LIMITED_INFORMATION, False, old_pid
                )
                if handle:
                    kernel32.kernel32.CloseHandle(handle)
                    is_running = True
            elif os.name != "nt":
                try:
                    os.kill(old_pid, 0)
                    is_running = True
                except OSError:
                    is_running = False
            if is_running:
                print(
                    f"  [FAIL] Another mutation testing runner is actively running (PID {old_pid})!"
                )
                sys.exit(1)
        except (ValueError, OSError) as read_err:
            sys.stderr.write(f"  [Warn] Failed to inspect existing lock file: {read_err}\n")
        try:
            lock_file.unlink(missing_ok=True)
        except OSError as unlink_err:
            sys.stderr.write(f"  [Warn] Failed to unlink lock file: {unlink_err}\n")

    try:
        lock_file.write_text(str(os.getpid()), encoding="utf-8")
    except OSError as lock_err:
        sys.stderr.write(f"  [Warn] Could not write lock file: {lock_err}\n")

    import atexit
    import signal

    validation_inputs = set(TARGET_MODULES)
    validation_inputs.update(
        _test_source_path(selector)
        for target in TARGET_MODULES
        for selector in _tests_for_module(target)
    )
    validation_inputs.update(
        {Path(__file__).resolve(), BASE_DIR / "pyproject.toml", BASE_DIR / "tests" / "conftest.py"}
    )
    pristine_sources = {path: path.read_bytes() for path in validation_inputs if path.is_file()}

    def cleanup_runner_lock():
        try:
            if lock_file.exists() and lock_file.read_text(encoding="utf-8").strip() == str(
                os.getpid()
            ):
                lock_file.unlink()
        except OSError as lock_err:
            sys.stderr.write(f"  [Warn] Failed to remove lock file on exit: {lock_err}\n")

    def signal_handler(signum, frame):
        cleanup_runner_lock()
        sys.exit(128 + signum if isinstance(signum, int) else 1)

    atexit.register(cleanup_runner_lock)
    for sig in (
        getattr(signal, "SIGINT", None),
        getattr(signal, "SIGTERM", None),
        getattr(signal, "SIGBREAK", None),
    ):
        if sig is not None:
            try:
                signal.signal(sig, signal_handler)
            except (ValueError, OSError) as sig_err:
                sys.stderr.write(
                    f"  [Warn] Could not register signal handler for {sig}: {sig_err}\n"
                )

    if args.target:
        active_targets = [
            t
            for t in TARGET_MODULES
            if args.target.lower() in t.name.lower() or args.target.lower() in str(t).lower()
        ]
        if not active_targets:
            print(f"  [FAIL] No target modules matched filter: {args.target}")
            sys.exit(1)
    else:
        active_targets = list(TARGET_MODULES)

    # 1. Self-Validating Precondition Verification
    module_timeouts, baseline_durations = verify_sentinel_preconditions(
        active_targets, workers=args.workers
    )

    # 2. Mutation Discovery & Testing
    total_killed = 0
    total_survived = 0
    total_timeout = 0
    total_indeterminate = 0
    total_skipped = 0
    total_incompetent = 0
    mutant_records: list[dict] = []
    module_timings: list[tuple[Path, ModuleTiming]] = []

    shared_killer_cache: dict[tuple[str, tuple[str, ...], str], str] = {}
    cache_lock = threading.Lock()
    try:
        print(f"2. Mutating Verification Modules & Scoring Test Suite ({mode_label})...")
        for target in active_targets:
            k, s, t, ind, inc, recs, timing = _evaluate_target_module(
                target,
                args,
                module_timeouts,
                baseline_durations[target],
                shared_killer_cache,
                cache_lock,
            )
            total_killed += k
            total_survived += s
            total_timeout += t
            total_indeterminate += ind
            total_incompetent += inc
            mutant_records.extend(recs)
            module_timings.append((target, timing))
    finally:
        try:
            assert_sources_unchanged(pristine_sources)
        finally:
            cleanup_runner_lock()

    # 3. Calculate Refined Mutation Metrics
    # Denominator excludes incompetent mutants (annotation-only, no runtime effect).
    total_valid_mutants = total_killed + total_survived + total_timeout + total_indeterminate
    definitive_denom = total_killed + total_survived

    kill_rate_pct = (total_killed / definitive_denom * 100.0) if definitive_denom > 0 else 0.0
    timeout_rate_pct = (total_timeout / total_valid_mutants * 100.0) if total_valid_mutants else 0.0
    duration_seconds = time.monotonic() - started_at
    duration_display = format_sentinel_duration(duration_seconds)

    print("\n" + "=" * 80)
    print(f"=== MUTATION TESTING FINAL SCORECARD ({mode_label}) ===")
    print("=" * 80)
    print(f"  • Execution Mode:           {mode_label}")
    print(f"  • Sentinel Duration:        {duration_display}")
    print(f"  • Total Mutants Evaluated:  {total_valid_mutants + total_skipped}")
    print(f"  • Killed:                   {total_killed}")
    print(f"  • Timeout:                  {total_timeout}")
    print(f"  • Indeterminate:            {total_indeterminate}")
    print(f"  • Survived:                 {total_survived}")
    print(f"  • Incompetent (Annotation): {total_incompetent}")
    print(f"  • Mutation Kill Rate:       {kill_rate_pct:.2f}% (Killed / Evaluated)")
    print(f"  • Timeout Rate:             {timeout_rate_pct:.2f}% (Timeout / Evaluated)")
    print(f"  • Definitive Kill Rate:     {kill_rate_pct:.2f}% (Target: 100.00%)")
    print("=" * 80)

    print("  Per-module timing:")
    for target, timing in module_timings:
        print(
            f"    - {target.relative_to(BASE_DIR).as_posix()}: "
            f"baseline={format_sentinel_duration(timing.baseline_seconds)}, "
            f"mutants={format_sentinel_duration(timing.mutant_seconds)}, "
            f"full-fallbacks={timing.full_corpus_fallbacks}, "
            f"cache-hits={timing.cache_hits}, retries={timing.timeout_retries}"
        )

    # 4. Generate Diligence Artifact
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    target_modules_report = "\n".join(
        f"{idx}. `{target.relative_to(BASE_DIR).as_posix()}`"
        for idx, target in enumerate(TARGET_MODULES, 1)
    )
    report_md = f"""# Mutation Testing Diligence Scorecard

Enterprise verification assurance scorecard generated by surgical AST mutation analysis.

## Summary Metrics

| Metric | Value |
| :--- | :--- |
| **Execution Mode** | **{mode_label}** |
| **Sentinel Duration** | **{duration_display}** |
| **Definitive Kill Rate** | **{kill_rate_pct:.2f}%** |
| **Timeout Rate** | **{timeout_rate_pct:.2f}%** |
| **Minimum Required Target** | **100.00%** |
| **Evaluation Baseline** | **PASSED (Green)** |
| **Killed Mutants** | **{total_killed}** |
| **Timeout Mutants** | **{total_timeout}** |
| **Indeterminate Mutants** | **{total_indeterminate}** |
| **Survived Mutants** | **{total_survived}** |
| **Incompetent Mutants** | **{total_incompetent}** |
| **Total Mutants Evaluated** | **{total_valid_mutants}** |

## Scoring Methodology

- **Mutation Strategy**: Surgical line substitution — targeted token replacement at AST
  coordinates; non-mutated lines preserved 100% byte-for-byte.
- **Metric Definitions**:
  - `Definitive Kill Rate = Killed / (Killed + Survived)`
  - `Timeout Rate = Timeout / (Killed + Survived + Timeout + Indeterminate)`
  - A timeout is retried serially and remains non-passing if unresolved.
  - A no-tests-collected result is indeterminate; it is never kill evidence.
  - Collection and pytest infrastructure errors are indeterminate, not kills.
  - Each unmodified target must pass through the same injection loader first.

## Target Modules Evaluated

{target_modules_report}

## Per-Module Timing

| Module | Baseline | Mutant Evaluation | Full Fallbacks | Cache Hits | Retries |
| :--- | ---: | ---: | ---: | ---: | ---: |
"""
    for target, timing in module_timings:
        report_md += (
            f"| `{target.relative_to(BASE_DIR).as_posix()}` | "
            f"{format_sentinel_duration(timing.baseline_seconds)} | "
            f"{format_sentinel_duration(timing.mutant_seconds)} | "
            f"{timing.full_corpus_fallbacks} | {timing.cache_hits} | {timing.timeout_retries} |\n"
        )

    report_md += "\n## Reviewed equivalent and non-binding exclusions\n\n"
    report_md += "| Module | Excluded mutation | Reason |\n| :--- | :--- | :--- |\n"
    for configuration in CRITICAL_MUTATION_TARGETS:
        if configuration.path not in active_targets:
            continue
        for point, reason in (configuration.exclusion_reasons or {}).items():
            scope, line, original, replacement = point
            report_md += (
                f"| `{configuration.path.relative_to(BASE_DIR).as_posix()}` | "
                f"`{scope}:{line} {original} -> {replacement}` | {reason} |\n"
            )

    report_md += """

## Detailed Mutation Log

| Module | Mutation Description | Status |
| :--- | :--- | :--- |
"""
    for rec in mutant_records:
        if rec["status"] == "incompetent":
            status_str = "INCOMPETENT (annotation-only or not locatable)"
        elif rec["status"] == "killed":
            status_str = "PASSED (Killed)"
        elif rec["status"] == "timeout":
            status_str = "FAILED (Unresolved timeout)"
        elif rec["status"] == "indeterminate":
            status_str = "FAILED (Indeterminate)"
        else:
            status_str = "FAILED (Survived)"
        report_md += f"| `{rec['module']}` | `{rec['mutation']}` | {status_str} |\n"

    REPORT_PATH.write_text(report_md, encoding="utf-8")
    rel_report = REPORT_PATH.relative_to(BASE_DIR)
    print(f"\n[Diligence Artifact] Generated mutation scorecard report at: {rel_report}")

    # 5. Enforce a deterministic 100% mutation gate. A timeout or indeterminate
    # result is not evidence that a test detected the mutant.
    if total_survived or total_timeout or total_indeterminate or kill_rate_pct < 100.0:
        print(
            f"\n[FAIL] Mutation gate failed: kill_rate={kill_rate_pct:.2f}%, "
            f"survived={total_survived}, timeout={total_timeout}, "
            f"indeterminate={total_indeterminate}."
        )
        sys.exit(1)
    else:
        print(f"\n[OK] Definitive kill rate {kill_rate_pct:.2f}% meets the 100.00% gate.")


if __name__ == "__main__":
    run_mutation_sentinel()
