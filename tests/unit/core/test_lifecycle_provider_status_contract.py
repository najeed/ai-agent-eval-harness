"""Provider execution status must not be confused with certification lifecycle."""

from types import SimpleNamespace

import pytest

from eval_runner.run_lifecycle import (
    RunLifecycleState,
    can_write_trace,
    get_run_lifecycle_state,
)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("PENDING", RunLifecycleState.OPEN),
        ("QUEUED", RunLifecycleState.OPEN),
        ("RUNNING", RunLifecycleState.OPEN),
        ("COMPLETED", RunLifecycleState.FINALIZING),
        ("FAILED", RunLifecycleState.FINALIZING),
        ("APPROVED", RunLifecycleState.INVALID),
        ("SEALED", RunLifecycleState.SEALED),
    ],
)
def test_provider_execution_status_has_explicit_lifecycle_meaning(status, expected):
    provider = SimpleNamespace(get_run=lambda run_id, **kwargs: {"status": status})
    assert get_run_lifecycle_state("owned-run", run_store=provider) == expected


@pytest.mark.parametrize("record", [None, [], "untrusted", 42])
def test_missing_or_non_mapping_provider_record_has_no_lifecycle_marker(record):
    provider = SimpleNamespace(get_run=lambda run_id, **kwargs: record)
    assert get_run_lifecycle_state("owned-run", run_store=provider) == RunLifecycleState.OPEN


@pytest.mark.parametrize("run_id", ["", "unknown"])
def test_unassigned_run_write_probe_does_not_access_a_provider(run_id):
    assert can_write_trace(run_id, run_store=None) == (True, "")
