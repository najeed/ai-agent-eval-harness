"""Pre-assignment lifecycle probes cannot adopt an ambient provider's lease."""

from types import SimpleNamespace

import pytest

from eval_runner.run_lifecycle import can_write_trace


@pytest.mark.parametrize("run_id", ["", "unknown"])
def test_unassigned_identity_ignores_ambient_provider_lease_state(run_id):
    provider = SimpleNamespace(is_certification_leased=lambda *args, **kwargs: True)

    assert can_write_trace(run_id, run_store=provider) == (True, "")
