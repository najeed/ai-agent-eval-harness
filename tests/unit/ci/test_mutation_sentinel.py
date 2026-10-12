"""Regression tests for mutation-sentinel verdict integrity."""

import ast
import io
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def _load_sentinel_module():
    path = Path("tools/ci/run_mutation_tests.py")
    spec = spec_from_file_location("mutation_sentinel_test_module", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def test_mutation_sentinel_falls_through_after_no_tests_collected():
    """A stale cached selector or unmatched scope cannot count as a kill."""
    sentinel = _load_sentinel_module()
    target = Path("eval_runner/utils/base.py").resolve()
    source = target.read_text(encoding="utf-8")
    tests = ["tests/unit/core/test_core_utilities.py"]
    cache_key = sentinel._mutation_cache_key("eval_runner.utils.base", tests, "missing_scope")
    cache = {cache_key: "stale_test"}
    completed = [
        SimpleNamespace(returncode=sentinel.PYTEST_NO_TESTS_COLLECTED, stdout=""),
        SimpleNamespace(returncode=0, stdout=""),
    ]

    with patch.object(sentinel.subprocess, "run", side_effect=completed) as run:
        status = sentinel.evaluate_mutant(
            target,
            source,
            tests,
            scope="missing_scope",
            killer_cache=cache,
        )

    assert status == "survived"
    assert cache == {}
    assert run.call_count == 2


def test_mutation_sentinel_marks_full_no_test_corpus_indeterminate():
    """A full corpus that collects nothing is a failed sentinel condition."""
    sentinel = _load_sentinel_module()
    target = Path("eval_runner/utils/base.py").resolve()
    source = target.read_text(encoding="utf-8")

    with patch.object(
        sentinel.subprocess,
        "run",
        return_value=SimpleNamespace(
            returncode=sentinel.PYTEST_NO_TESTS_COLLECTED,
            stdout="",
        ),
    ):
        status = sentinel.evaluate_mutant(
            target,
            source,
            ["tests/unit/core/test_core_utilities.py"],
            scope="module",
        )

    assert status == "indeterminate"


def test_mutation_sentinel_killer_cache_is_scoped_to_module_and_corpus():
    """Identically named scopes in different test corpora cannot share killers."""
    sentinel = _load_sentinel_module()

    assert sentinel._mutation_cache_key("a.module", ["a_test.py"], "validate") != (
        sentinel._mutation_cache_key("b.module", ["b_test.py"], "validate")
    )


def test_mutation_sentinel_manifest_covers_runtime_trust_boundaries():
    """The mutation suite must cover lifecycle and evidence gates, not utilities alone."""
    sentinel = _load_sentinel_module()
    paths = {
        target.path.relative_to(sentinel.BASE_DIR).as_posix()
        for target in sentinel.CRITICAL_MUTATION_TARGETS
    }

    assert {
        "eval_runner/verifier.py",
        "eval_runner/tool_sandbox.py",
        "eval_runner/flight_recorder.py",
        "eval_runner/run_lifecycle.py",
        "eval_runner/session.py",
        "eval_runner/engine.py",
        "eval_runner/reference/sqlite_checkpoint.py",
        "agentv_runtime/package.py",
        "agentv_runtime/canonical.py",
        "agentv_runtime/manifest.py",
        "agentv_runtime/evidence_graph.py",
        "agentv_runtime/finalization.py",
        "eval_runner/reference/approval_store.py",
    } <= paths
    assert all(target.tests and target.scopes for target in sentinel.CRITICAL_MUTATION_TARGETS)


def test_mutation_sentinel_selects_only_declared_critical_scopes():
    """A target's full-file operators cannot silently expand the mutation surface."""
    sentinel = _load_sentinel_module()
    target = next(
        item for item in sentinel.CRITICAL_MUTATION_TARGETS if item.path.name == "engine.py"
    )
    source = target.path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    points = sentinel.discover_mutation_points(source, sentinel._annotation_line_numbers(tree))
    selected = [point for point in points if point.scope in target.scopes]

    assert target.scopes <= sentinel.discover_defined_scopes(tree)
    assert selected
    assert len(selected) < len(points)
    assert {point.scope for point in selected} <= target.scopes


def test_mutation_sentinel_requires_semantic_operator_families_per_boundary():
    """Critical evidence and approval targets cannot silently lose their key mutants."""
    sentinel = _load_sentinel_module()
    expected = {
        "sqlite_checkpoint.py": {"serialization"},
        "manifest.py": {"commitment"},
        "evidence_graph.py": {"commitment"},
        "finalization.py": {"commitment"},
        "approval_store.py": {"approval_gate"},
    }

    for target in sentinel.CRITICAL_MUTATION_TARGETS:
        if target.path.name not in expected:
            continue
        source = target.path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        families = {
            sentinel.mutation_operator_family(point)
            for point in sentinel.discover_mutation_points(
                source, sentinel._annotation_line_numbers(tree)
            )
            if point.scope in target.scopes
        }
        assert target.required_operator_families == expected[target.path.name]
        assert target.required_operator_families <= families


def test_mutation_sentinel_limits_declared_boundaries_to_their_required_families():
    """Evidence boundary mutations retain guards and verdict semantics."""
    sentinel = _load_sentinel_module()
    target = next(
        item for item in sentinel.CRITICAL_MUTATION_TARGETS if item.path.name == "evidence_graph.py"
    )
    source = target.path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    selected_families = {
        sentinel.mutation_operator_family(point)
        for point in sentinel.discover_mutation_points(
            source, sentinel._annotation_line_numbers(tree)
        )
        if point.scope in target.scopes
        and sentinel.mutation_operator_family(point) in target.eligible_operator_families
    }

    assert selected_families == {"boolean", "commitment", "comparison", "guard"}


def test_mutation_sentinel_tracks_only_the_proven_equivalent_approval_exclusion():
    """Authorization mutants stay executable unless their equivalence is explicit."""
    sentinel = _load_sentinel_module()
    target = next(
        item for item in sentinel.CRITICAL_MUTATION_TARGETS if item.path.name == "approval_store.py"
    )

    assert target.eligible_operator_families == {
        "approval_gate",
        "boolean",
        "comparison",
        "guard",
    }
    assert target.excluded_mutations == {("get_request", 90, "or", "and")}


def test_mutation_sentinel_documents_only_proven_equivalent_evidence_exclusions():
    """Dead expressions and unreachable defaults are not counted as runtime mutants."""
    sentinel = _load_sentinel_module()
    target = next(
        item for item in sentinel.CRITICAL_MUTATION_TARGETS if item.path.name == "evidence_graph.py"
    )

    assert target.excluded_mutations == {
        ("build_evidence_graph", 271, "False", "True"),
        ("build_evidence_graph_from_events", 379, "is not", "is"),
        ("build_evidence_graph_from_events", 382, "is not", "is"),
        ("build_evidence_graph_from_events", 383, "False", "True"),
    }


def test_mutation_sentinel_vets_scope_selectors_without_empty_pytest_probes():
    """Unmatched production scopes skip -k rather than collecting zero tests."""
    sentinel = _load_sentinel_module()
    approval_target = next(
        item for item in sentinel.CRITICAL_MUTATION_TARGETS if item.path.name == "approval_store.py"
    )
    names = sentinel._declared_test_names(list(approval_target.tests))

    assert sentinel._scope_selector_available("lifecycle", names) is True
    assert sentinel._scope_selector_available("create_request", names) is False
    assert sentinel._scope_test_selector(approval_target.path, "create_request", names) == (
        "test_lifecycle"
    )


def test_mutation_sentinel_partitions_one_cache_primer_per_source_scope():
    """A deterministic first mutant seeds each scope before parallel siblings run."""
    sentinel = _load_sentinel_module()
    source = """\
def first(value):
    return value and True

def second(value):
    return value or False
"""
    points = sentinel.discover_mutation_points(source, set())

    primers, remainder = sentinel._partition_scope_primers(points)

    assert {point.scope for point in primers} == {"first", "second"}
    assert all(point.scope in {"first", "second"} for point in remainder)
    assert len(primers) + len(remainder) == len(points)


def test_mutation_sentinel_critical_scope_maps_reference_real_tests():
    """Explicit mappings are validated names, not opaque string guesses."""
    sentinel = _load_sentinel_module()

    for target in sentinel.CRITICAL_MUTATION_TARGETS:
        declared = sentinel._declared_test_names(list(target.tests))
        for scope in sentinel.MODULE_SCOPE_TEST_MAP[target.path]:
            selector = sentinel._scope_test_selector(target.path, scope, declared)
            assert selector is not None


def test_mutation_sentinel_exercises_security_and_hitl_gate_operators():
    """High-impact semantic operators must remain available to critical scopes."""
    sentinel = _load_sentinel_module()
    source = """
def enforce(candidate, allowed, receipts):
    if not (candidate in allowed and all(receipts)):
        return {"signature": candidate, "evidence_root_hash": candidate}
    return RunLifecycleState.PAUSED_FOR_APPROVAL
"""

    points = sentinel.discover_mutation_points(source, set())
    operators = {(point.original, point.mutated) for point in points}

    assert {
        ("not", ""),
        ("in", "not in"),
        ("and", "or"),
        ("all", "any"),
        ("PAUSED_FOR_APPROVAL", "RUNNING"),
        ("signature", sentinel._MUTATED_COMMITMENT_FIELD),
        ("evidence_root_hash", sentinel._MUTATED_COMMITMENT_FIELD),
    } <= operators


def test_mutation_sentinel_not_guard_mutation_preserves_valid_python():
    """Removing a guard token must produce a runnable mutant, not invalid syntax."""
    sentinel = _load_sentinel_module()
    source = """\
def enforce(candidate, allowed):
    if not (candidate in allowed):
        return False
    return True
"""
    point = next(
        item
        for item in sentinel.discover_mutation_points(source, set())
        if (item.original, item.mutated) == ("not", "")
    )

    mutated = sentinel._apply_surgical_mutation(source.splitlines(keepends=True), point)

    assert mutated is not None
    compile(mutated, "<guard-mutant>", "exec")


def test_mutation_sentinel_mutates_each_repeated_operator_at_its_ast_location():
    """Repeated same-line operators must not collapse onto the first token."""
    sentinel = _load_sentinel_module()
    source = """\
def ordered(first, second, third):
    return first < second < third
"""
    points = [
        point
        for point in sentinel.discover_mutation_points(source, set())
        if (point.original, point.mutated) == ("<", ">=")
    ]

    assert len(points) == 2
    mutated = sentinel._apply_surgical_mutation(source.splitlines(keepends=True), points[1])

    assert mutated is not None
    assert "first < second >= third" in mutated


def test_mutation_sentinel_uses_unicode_safe_ast_offsets():
    """UTF-8 byte offsets must resolve to the correct text location for surgery."""
    sentinel = _load_sentinel_module()
    source = """\
def labeled(value):
    return "évidence" == value
"""
    point = next(
        item
        for item in sentinel.discover_mutation_points(source, set())
        if (item.original, item.mutated) == ("==", "!=")
    )

    mutated = sentinel._apply_surgical_mutation(source.splitlines(keepends=True), point)

    assert mutated is not None
    assert '"évidence" != value' in mutated


def test_mutation_sentinel_injects_mutants_through_subprocess_stdin():
    """Mutants must never be materialized as temporary Python files on disk."""
    sentinel = _load_sentinel_module()
    target = Path("eval_runner/utils/base.py").resolve()
    source = target.read_text(encoding="utf-8")

    with patch.object(
        sentinel.subprocess,
        "run",
        return_value=SimpleNamespace(returncode=0, stdout=""),
    ) as run:
        status = sentinel.evaluate_mutant(
            target,
            source,
            ["tests/unit/core/test_core_utilities.py"],
            scope="module",
        )

    assert status == "survived"
    command = run.call_args.args[0]
    loader_code = run.call_args.kwargs["input"]
    assert command[-1] == "-"
    assert "-c" not in command
    assert "base64.b64decode" in loader_code
    assert source not in loader_code


def test_mutation_sentinel_progress_reports_completed_mutants_without_ansi_noise():
    """Console progress remains useful in non-interactive CI logs."""
    sentinel = _load_sentinel_module()
    stream = io.StringIO()
    progress = sentinel._MutationProgress(total=3, workers=2, stream=stream)

    progress.start()
    progress.heartbeat(active_workers=2)
    for status in ("killed", "survived", "timeout"):
        progress.report(status)
    progress.close()

    output = stream.getvalue()
    assert "0/3 queued (workers=2)" in output
    assert ".FT 3/3" in output
    assert "[RUNNING] 0/3 complete; 2 mutant worker(s) active" in output
    assert "\033[" not in output


def test_mutation_sentinel_formats_duration_like_pytest():
    """Scorecards retain precise seconds and a readable elapsed wall clock."""
    sentinel = _load_sentinel_module()

    assert sentinel.format_sentinel_duration(1100.28) == "1100.28s (0:18:20)"
    assert sentinel.format_sentinel_duration(59.99) == "59.99s (0:00:59)"


def test_mutation_sentinel_records_module_timing_and_acceleration_evidence():
    """The scorecard counters distinguish cache savings from expensive fallbacks."""
    sentinel = _load_sentinel_module()
    timing = sentinel.ModuleTiming(baseline_seconds=12.5)

    timing.record_cache_hit()
    timing.record_full_corpus_fallback()
    timing.record_timeout_retry()

    assert timing.baseline_seconds == 12.5
    assert timing.cache_hits == 1
    assert timing.full_corpus_fallbacks == 1
    assert timing.timeout_retries == 1


def test_mutation_sentinel_baseline_cache_key_binds_the_corpus_and_targets():
    """Changing either executable baseline input invalidates a cached baseline."""
    sentinel = _load_sentinel_module()
    sqlite_target = next(
        item
        for item in sentinel.CRITICAL_MUTATION_TARGETS
        if item.path.name == "sqlite_checkpoint.py"
    )
    lifecycle_target = next(
        item for item in sentinel.CRITICAL_MUTATION_TARGETS if item.path.name == "run_lifecycle.py"
    )
    tests = tuple(sqlite_target.tests)

    key = sentinel._baseline_cache_key(tests, (lifecycle_target.path, sqlite_target.path))

    assert key == sentinel._baseline_cache_key(tests, (lifecycle_target.path, sqlite_target.path))
    assert key != sentinel._baseline_cache_key(tests, (sqlite_target.path,))
