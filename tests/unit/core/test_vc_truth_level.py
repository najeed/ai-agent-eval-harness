"""
[VC-Trust B] Truth-level contract: execution_mode is REQUIRED in every
certificate; undeclared/legacy runs stamp "unknown" + provisional=true.
No version bump — 2026-08 maintainer waiver.
"""

import json

import pytest
from jsonschema import validate

from eval_runner import config
from eval_runner.verifier import TraceVerifier


def _sign_tmp_trace(tmp_path, monkeypatch, **kwargs) -> dict:
    vault = tmp_path / "runs" / "vc-truth-run"
    vault.mkdir(parents=True)
    trace = vault / "run.jsonl"
    trace.write_text('{"event": "run_start"}\n', encoding="utf-8")
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")

    return TraceVerifier.sign_trace(
        str(trace),
        run_id="vc-truth-run",
        identity_id="test-identity",
        **kwargs,
    )


def _schema():
    schema_path = config.PROJECT_ROOT / "spec" / "vc" / "vc.schema.json"
    with open(schema_path, encoding="utf-8") as f:
        return json.load(f)


def test_execution_mode_is_required_and_stamped_unknown_for_legacy(tmp_path, monkeypatch):
    manifest = _sign_tmp_trace(tmp_path, monkeypatch)

    assert manifest["execution_mode"] == "unknown"
    assert manifest["provisional"] is True
    validate(instance=manifest, schema=_schema())


def test_declared_live_mode_is_stamped_not_provisional(tmp_path, monkeypatch):
    manifest = _sign_tmp_trace(tmp_path, monkeypatch, execution_mode="live")

    assert manifest["execution_mode"] == "live"
    assert "provisional" not in manifest or manifest["provisional"] is False
    validate(instance=manifest, schema=_schema())


@pytest.mark.parametrize("junk", ["SIMULATED", "live ", "holographic", "  ", ""])
def test_verifier_never_emits_junk_modes(tmp_path, monkeypatch, junk):
    """[Defense in depth] Even if junk reaches the verifier (upstream session
    parsing should have rejected it), the certificate may only carry canonical
    enum values: unrecognized input stamps unknown + provisional."""
    from jsonschema import validate as _validate

    manifest = _sign_tmp_trace(tmp_path, monkeypatch, execution_mode=junk)
    assert manifest["execution_mode"] == "unknown"
    assert manifest["provisional"] is True
    _validate(instance=manifest, schema=_schema())
