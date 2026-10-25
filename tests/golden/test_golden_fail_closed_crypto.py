"""
tests/golden/test_golden_fail_closed_crypto.py
Golden Verification Corpus: Fail-Closed Cryptography Validation
"""

import pytest

from eval_runner.events import CoreEvents, Event
from eval_runner.flight_recorder import FlightRecorderPlugin
from eval_runner.reference.local_run_store import LocalFileRunStore


def test_golden_fail_closed_signing_on_invalid_key(tmp_path, monkeypatch):
    # Provision invalid key path
    invalid_key_path = tmp_path / "non_existent_key.pem"

    monkeypatch.setenv("AUDIT_LEVEL", "2")
    monkeypatch.setenv("FLIGHT_RECORDER_KEY_PATH", str(invalid_key_path))
    monkeypatch.setenv("EVAL_SIGNING_FAIL_CLOSED", "true")
    monkeypatch.setenv("RUN_LOG_DIR", str(tmp_path / "runs"))

    store = LocalFileRunStore(tmp_path / "runs")
    plugin = FlightRecorderPlugin(run_store=store)
    plugin._audit_level = 2
    plugin._private_key_path = str(invalid_key_path)

    test_event = Event(
        name=CoreEvents.STEP_START,
        data={"run_id": "test_run_fail_closed", "step": 1},
    )
    store.create_run("test_run_fail_closed", "golden-fail-closed")
    plugin.bind_run_provider("test_run_fail_closed", store)

    # Under AUDIT_LEVEL >= 2 and fail-closed policy, signing error MUST raise RuntimeError
    with pytest.raises(RuntimeError) as exc_info:
        plugin.handle_event(test_event)

    assert "CryptographicSigningError" in str(exc_info.value)
