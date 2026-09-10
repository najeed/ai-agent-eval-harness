"""Adversarial and regression unit tests for the 6 P0/P1 audit defensibility remediations.

Remediations tested:
1. Trace persistence intrinsically fail-closed in certification mode.
2. Trace seal trust envelope covers signer_identity and key_id before signing.
3. Manifest trust failure: no auto-generation; verify_integrity requires external trust root.
4. ZIP bundle verification hashes internal archive bytes; rejects path traversal.
5. RFC 8785 canonicalization compliance and unification.
6. Reporter truthfulness: manifest existence on disk never implies verification.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from agentv_runtime.canonical import canonical_json_dumps, canonical_json_encode
from agentv_runtime.package import VerificationPackage
from eval_runner import config, reporter
from eval_runner.artifact_plugin import ArtifactPlugin
from eval_runner.events import Event
from eval_runner.flight_recorder import FlightRecorderPlugin
from eval_runner.verifier import VerificationAuthority


def _generate_ed25519_pem_pair() -> tuple[ed25519.Ed25519PrivateKey, str, str]:
    priv = ed25519.Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = (
        priv.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return priv, priv_pem, pub_pem


class MockSigningBackend:
    """Test signing backend adhering to the flight recorder signing protocol."""

    def __init__(
        self,
        private_key: ed25519.Ed25519PrivateKey,
        key_id: str = "cert-key-001",
        identity: str = "agentv-attestor-v1",
    ):
        self._private_key = private_key
        self.key_id = key_id
        self.identity = identity

    def sign(self, payload: bytes) -> bytes:
        return self._private_key.sign(payload)

    def sign_payload(self, payload: bytes, key_id: str | None = None) -> str:
        return self._private_key.sign(payload).hex()


# ---------------------------------------------------------------------------
# Rem 1: Trace Persistence Intrinsically Fail-Closed in Certification Mode
# ---------------------------------------------------------------------------
def test_rem1_flight_recorder_fail_closed_in_certification_mode(tmp_path: Path):
    """Persistence failure in certification mode must transition run to CERTIFICATION_FAILED

    and forbid seal/certificate generation.
    """
    recorder = FlightRecorderPlugin(log_dir=tmp_path, certification_mode=True)
    run_id = "cert-run-001"

    # Force write to raise an OSError
    with patch("builtins.open", side_effect=OSError("Disk full / write failure")):
        event = Event("model_call", {"run_id": run_id, "prompt": "test"})
        with pytest.raises(RuntimeError, match="TracePersistenceError"):
            recorder.handle_event(event)

    assert recorder.get_run_state(run_id) == "CERTIFICATION_FAILED"
    assert run_id in recorder._failed_runs

    # Finalize must refuse to generate seal or certificate
    with pytest.raises(RuntimeError, match="TracePersistenceError"):
        recorder.finalize_run(run_id)

    seal_file = tmp_path / run_id / "trace_seal.json"
    assert not seal_file.exists(), "trace_seal.json must not be created for failed runs"


def test_rem1_flight_recorder_env_certification_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """EVAL_CERTIFICATION_MODE=true or EVAL_ATTESTATION_MODE=true activates fail-closed."""
    monkeypatch.setenv("EVAL_CERTIFICATION_MODE", "true")
    recorder = FlightRecorderPlugin(log_dir=tmp_path)
    assert recorder.is_certification_mode() is True

    run_id = "cert-env-run"
    with patch("builtins.open", side_effect=OSError("Storage failure")):
        event = Event("step_start", {"run_id": run_id})
        with pytest.raises(RuntimeError, match="TracePersistenceError"):
            recorder.handle_event(event)

    assert recorder.get_run_state(run_id) == "CERTIFICATION_FAILED"


# ---------------------------------------------------------------------------
# Rem 2: Trace Seal Trust Binding (Envelope covers identity before signing)
# ---------------------------------------------------------------------------
def test_rem2_trace_seal_trust_envelope_tamper_detected(tmp_path: Path):
    """Tampering with signer_identity or key_id in trace_seal.json breaks verification."""
    priv_key, priv_pem, pub_pem = _generate_ed25519_pem_pair()
    backend = MockSigningBackend(priv_key, key_id="cert-key-001", identity="agentv-attestor-v1")

    recorder = FlightRecorderPlugin(log_dir=tmp_path, signing_backend=backend)
    run_id = "run-seal-001"

    event = Event("step_start", {"run_id": run_id, "step": 1})
    recorder.handle_event(event)
    recorder.finalize_run(run_id)

    seal_path = tmp_path / run_id / "trace_seal.json"
    assert seal_path.exists()
    seal_data = json.loads(seal_path.read_text(encoding="utf-8"))

    assert seal_data["signer_identity"] == "agentv-attestor-v1"
    assert seal_data["key_id"] == "cert-key-001"
    assert "signature" in seal_data

    # 1. Untampered verification succeeds with external trust root
    trace_path = tmp_path / run_id / "run.jsonl"
    raw_trace = trace_path.read_bytes() if trace_path.exists() else b""

    valid_pkg = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="s_hash",
        manifest_id="m1",
        manifest_hash="m_hash",
        execution_identity={"run_id": run_id},
        trace_hash=seal_data.get("trace_digest", ""),
        trace_seal=seal_data,
        evidence_root_hash="ev_root",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
    )
    valid_res = VerificationAuthority.verify_package(
        valid_pkg,
        raw_trace_bytes=raw_trace,
        trust_root={"cert-key-001": pub_pem},
        require_signature=False,
        require_scenario_binding=False,
    )
    assert valid_res["verified"] is True

    # 2. Tamper with signer_identity -> verification fails
    tampered_seal = dict(seal_data)
    tampered_seal["signer_identity"] = "impostor-identity"

    tampered_pkg = VerificationPackage(
        scenario_id="s1",
        scenario_version="1.0.0",
        scenario_hash="s_hash",
        manifest_id="m1",
        manifest_hash="m_hash",
        execution_identity={"run_id": run_id},
        trace_hash=seal_data.get("trace_digest", ""),
        trace_seal=tampered_seal,
        evidence_root_hash="ev_root",
        required_oracle_ids=[],
        executed_oracle_results=[],
        decision={"decision": "PASS", "verdict": "VERIFIED"},
    )
    tampered_res = VerificationAuthority.verify_package(
        tampered_pkg,
        raw_trace_bytes=raw_trace,
        trust_root={"cert-key-001": pub_pem},
        require_signature=False,
        require_scenario_binding=False,
    )
    assert tampered_res["verified"] is False
    assert any(
        "TraceSealUntrustedSigner" in r or "TraceSealSignatureInvalid" in r
        for r in tampered_res["failures"]
    )


# ---------------------------------------------------------------------------
# Rem 3: Audit-Manifest Trust Failure (No auto-gen, external trust anchor required)
# ---------------------------------------------------------------------------
def test_rem3_artifact_plugin_no_auto_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """ArtifactPlugin._get_signing_key() raises RuntimeError when no key configured."""
    monkeypatch.delenv("AES_PRIVATE_KEY", raising=False)
    plugin = ArtifactPlugin()

    with patch("eval_runner.identity.IdentityService.get_private_key", return_value=None):
        with patch.object(Path, "exists", return_value=False):
            with pytest.raises(RuntimeError, match="No signing key configured"):
                plugin._get_signing_key()


def test_rem3_verify_integrity_requires_external_trust_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """verify_integrity() returns UNVERIFIED when no external trust root is provided."""
    priv_key, priv_pem, pub_pem = _generate_ed25519_pem_pair()
    monkeypatch.setenv("AES_PRIVATE_KEY", priv_pem)

    plugin = ArtifactPlugin()
    data_file = tmp_path / "result.txt"
    data_file.write_text("secure data", encoding="utf-8")

    bundle_res = plugin.bundle_artifacts(str(tmp_path), ["result.txt"])
    manifest_path = bundle_res["manifest_path"]

    # Now clear external trust anchors
    empty_trust = tmp_path / "empty_trust"
    empty_trust.mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path / "empty_root")
    monkeypatch.setattr(config, "TRUST_ROOT", empty_trust)
    monkeypatch.delenv("AES_PUBLIC_KEY_SYSTEM_ID", raising=False)
    monkeypatch.delenv("AES_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("AES_PRIVATE_KEY", raising=False)

    # Verify with NO external trust anchor
    result = plugin.verify_integrity(manifest_path)
    assert result["status"] == "UNVERIFIED"
    assert result["is_valid"] is False
    assert "No external trust anchor found" in result["message"]


# ---------------------------------------------------------------------------
# Rem 4: Bundle Verification Hashes Actual Internal Archive Bytes
# ---------------------------------------------------------------------------
def test_rem4_zip_bundle_internal_bytes_and_unsafe_path_rejection(tmp_path: Path):
    """ZIP verification reads internal archive bytes and rejects path traversal."""
    plugin = ArtifactPlugin()
    f1 = tmp_path / "item.txt"
    f1.write_text("safe content", encoding="utf-8")

    bundle_res = plugin.bundle_artifacts(str(tmp_path), ["item.txt"])
    zip_path = Path(bundle_res["bundle_path"])

    # Tamper inside ZIP: replace item.txt content directly in the archive bytes
    buf = io.BytesIO()
    with zipfile.ZipFile(zip_path, "r") as zf_in:
        with zipfile.ZipFile(buf, "w") as zf_out:
            for item in zf_in.infolist():
                if item.filename == "item.txt":
                    zf_out.writestr(item, "corrupted content")
                else:
                    zf_out.writestr(item, zf_in.read(item.filename))

    tampered_zip = tmp_path / "tampered.zip"
    tampered_zip.write_bytes(buf.getvalue())

    # Verifying tampered zip directly detects hash mismatch from internal bytes
    res_tampered = plugin.verify_integrity(str(tampered_zip))
    assert res_tampered["is_valid"] is False
    assert res_tampered["status"] == "INVALID"
    assert any(d["status"] == "mismatch" for d in res_tampered["details"])

    # Reject path traversal
    unsafe_manifest = tmp_path / "unsafe_manifest.json"
    manifest_dict = {
        "version": "1.0",
        "batch_id": "unsafe",
        "files": [{"name": "../etc/passwd", "file_hash": "badhash"}],
    }
    unsafe_manifest.write_text(json.dumps(manifest_dict), encoding="utf-8")
    res_unsafe = plugin.verify_integrity(str(unsafe_manifest))
    assert res_unsafe["is_valid"] is False
    assert res_unsafe["status"] == "INVALID"
    assert res_unsafe["details"][0]["status"] == "unsafe_path"


# ---------------------------------------------------------------------------
# Rem 5: RFC 8785 Canonicalization Compliance
# ---------------------------------------------------------------------------
def test_rem5_canonical_json_rfc8785():
    """canonical_json_encode produces correct UTF-16 code-unit ordering & formatting."""
    data = {
        "b": 1,
        "a": [True, False, None, 1.5, 100.0],
        "\u00e9": "accent",
        "z": "end",
    }
    encoded = canonical_json_encode(data)
    decoded_str = canonical_json_dumps(data)

    assert encoded == decoded_str.encode("utf-8")
    assert "100.0" not in decoded_str  # ECMAScript float format serializes 100.0 as 100
    assert decoded_str.startswith('{"a":[true,false,null,1.5,100],"b":1')


# ---------------------------------------------------------------------------
# Rem 6: Reporter Truthfulness (File existence never implies verified)
# ---------------------------------------------------------------------------
def test_rem6_reporter_truthfulness_no_file_existence_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """HTML report does NOT display VERIFIED RUN merely because a manifest exists on disk."""
    monkeypatch.setattr(config, "HTML_REPORTS_DIR", tmp_path / "reports")
    scenario = {"id": "s1", "title": "Test Scenario"}
    results = [
        {
            "task_id": "t1",
            "metrics": [{"metric": "m1", "score": 1, "threshold": 0.5, "success": True}],
        }
    ]

    # Place a dummy manifest beside the trace in runs directory
    run_dir = tmp_path / "runs" / "run-unverified"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "audit_manifest.json").write_text("{}", encoding="utf-8")
    (run_dir / "trace.jsonl").write_text("{}", encoding="utf-8")

    # Generate report with NO authoritative verification metadata
    out_file = reporter.generate_html_report(
        scenario, results, metadata={"run_id": "run-unverified"}
    )
    html = Path(out_file).read_text(encoding="utf-8")

    assert "VERIFIED RUN" not in html

    # Generate report WITH authoritative verification result
    out_file_verified = reporter.generate_html_report(
        scenario,
        results,
        metadata={
            "run_id": "run-verified",
            "verification_result": {"is_valid": True, "status": "CERTIFIED"},
        },
    )
    html_verified = Path(out_file_verified).read_text(encoding="utf-8")
    assert "VERIFIED RUN" in html_verified
