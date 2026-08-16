"""
tests/golden/test_golden_fail_closed_crypto.py
Golden Verification Corpus: Fail-Closed Cryptography Validation
"""

import pytest

from eval_runner.events import CoreEvents, Event
from eval_runner.flight_recorder import FlightRecorderPlugin


def test_golden_fail_closed_signing_on_invalid_key(tmp_path, monkeypatch):
    # Provision invalid key path
    invalid_key_path = tmp_path / "non_existent_key.pem"

    monkeypatch.setenv("AUDIT_LEVEL", "2")
    monkeypatch.setenv("EVAL_SIGNING_KEY", str(invalid_key_path))
    monkeypatch.setenv("EVAL_SIGNING_FAIL_CLOSED", "true")
    monkeypatch.setenv("RUN_LOG_DIR", str(tmp_path / "runs"))

    plugin = FlightRecorderPlugin()
    plugin._audit_level = 2
    plugin._private_key_path = str(invalid_key_path)

    test_event = Event(
        name=CoreEvents.STEP_START,
        data={"run_id": "test_run_fail_closed", "step": 1},
    )

    # Under AUDIT_LEVEL >= 2 and fail-closed policy, signing error MUST raise RuntimeError
    with pytest.raises(RuntimeError) as exc_info:
        plugin.handle_event(test_event)

    assert "CryptographicSigningError" in str(exc_info.value)
