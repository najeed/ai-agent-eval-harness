"""Additional SIG-01..14 acceptance requirements, without claiming live AWS evidence."""

import copy
import hashlib
import json
import re
import runpy
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from agentv_runtime.canonical import canonical_json_encode
from agentv_runtime.signatures import (
    CERTIFICATE,
    PACKAGE,
    PROFILE,
    canonical_payload_from_json,
    verify_artifact_signature,
)
from eval_runner.identity import IdentityService
from eval_runner.services.certification import execute_industrial_certification
from eval_runner.verifier import CertificationFailedError
from tests.unit.core.test_digest_signature_contract import (
    _provision_remote_policy,
    remote as remote,
)
from tests.unit.core.test_signing_finalization_contract import (
    finalization_source as finalization_source,
)

REVIEWER = (
    Path(__file__).resolve().parents[2] / "acceptance" / "support" / "offline_digest_reviewer.py"
)


@pytest.mark.parametrize(
    "purpose", [CERTIFICATE, PACKAGE], ids=["SIG-02-certificate", "SIG-02-package"]
)
@pytest.mark.parametrize("corrupt_payload", [False, True], ids=["positive", "SIG-05-corrupt"])
def test_offline_process_reconstructs_frozen_projection(
    finalization_source, tmp_path, purpose, corrupt_payload
):
    provider, scenario = finalization_source
    backend = _provision_remote_policy()
    issued = execute_industrial_certification(
        "run-a", run_store=provider, scenario_data=scenario, signing_backend=backend
    )["manifest"]
    artifact = copy.deepcopy(issued if purpose == CERTIFICATE else issued["verification_package"])
    response = (
        artifact["provenance_chain"][0]["signature"]
        if purpose == CERTIFICATE
        else artifact["signature"]
    )
    if corrupt_payload:
        artifact["metadata"]["corrupted"] = True
    input_path = tmp_path / "offline-artifact.json"
    input_path.write_text(
        json.dumps(
            {
                "purpose": purpose,
                "artifact": artifact,
                "result": response,
                "trusted_anchor": {
                    "identity": backend.policy.identity,
                    "key_id": backend.policy.key_id,
                    "public_key_pem": backend.public_key_pem,
                    "revoked": False,
                    "permitted_profiles": [PROFILE],
                    "permitted_purposes": [purpose],
                },
            }
        )
    )
    completed = subprocess.run(
        [sys.executable, "-P", str(REVIEWER), str(input_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert (completed.returncode == 0) is not corrupt_payload, completed.stderr


@pytest.mark.parametrize(
    "value",
    [
        {"z": "e\u0301", "a": "é", "\U0001f600": "astral", "\ufffd": "bmp"},
        {"numbers": [-0.0, 1e-7, 1e-6, 1e20, 1e21, 333333333.3333333]},
        {"numbers": [9007199254740991, -9007199254740991, 5e-324, 1.7976931348623157e308]},
        {"nested": [{"b": 1, "a": 2}], "controls": '\n\t\\"\u0000'},
    ],
    ids=["SIG-03-unicode", "SIG-03-number-boundaries", "SIG-03-binary64", "SIG-03-order"],
)
def test_cross_implementation_canonicalization_vectors(value):
    independent = runpy.run_path(str(REVIEWER))["canonical"](value)
    native = canonical_json_encode(value)
    assert native == independent
    assert canonical_payload_from_json(native) == independent
    assert hashlib.sha256(native).digest() == hashlib.sha256(independent).digest()


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"nested":{"x":1,"x":2}}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":1e400}',
        b'{"x":9007199254740993}',
        b'{"x":"\\ud800"}',
        b'{"x":}',
        b'{"x":"\xff"}',
        b"[]",
        b"true",
    ],
    ids=["SIG-03-invalid-" + str(index) for index in range(11)],
)
def test_strict_transport_json_rejects_ambiguous_or_unsupported_inputs(raw):
    with pytest.raises((ValueError, OverflowError, UnicodeError)):
        canonical_payload_from_json(raw)


@pytest.mark.parametrize("purpose", [CERTIFICATE, PACKAGE])
@pytest.mark.parametrize("injected", [False, True], ids=["resolved", "explicit"])
@pytest.mark.parametrize(
    "failure",
    [
        ConnectionError("DependencyTimeoutException"),
        PermissionError("AccessDeniedException"),
        RuntimeError("DisabledException"),
        RuntimeError("KMSInvalidStateException"),
        TimeoutError("timeout"),
        OSError("retry budget exhausted"),
        TypeError("malformed remote response"),
    ],
    ids=[
        "SIG-12-outage",
        "SIG-12-denied",
        "SIG-12-disabled",
        "SIG-12-unavailable",
        "SIG-12-timeout",
        "SIG-12-retries",
        "SIG-12-malformed",
    ],
)
def test_hardware_failure_never_consults_available_local_key(
    finalization_source, monkeypatch, purpose, injected, failure
):
    from eval_runner import runtime_services

    provider, scenario = finalization_source
    backend = _provision_remote_policy()
    original = backend.sign_payload

    def fail_at_boundary(*args, **kwargs):
        if kwargs["purpose"] == purpose:
            raise failure
        return original(*args, **kwargs)

    monkeypatch.setattr(backend, "sign_payload", fail_at_boundary)
    monkeypatch.setattr(runtime_services, "resolve_signing_backend", lambda: backend)
    # Real local key files exist. After selecting hardware, even consulting them is a failure.
    local_lookup = Mock(side_effect=AssertionError("SIG-14 local private key consulted"))
    monkeypatch.setattr(IdentityService, "get_private_key", local_lookup)
    commit = Mock(wraps=provider.commit_certification)
    monkeypatch.setattr(provider, "commit_certification", commit)
    with pytest.raises((CertificationFailedError, type(failure)), match=re.escape(str(failure))):
        execute_industrial_certification(
            "run-a",
            run_store=provider,
            scenario_data=scenario,
            signing_backend=backend if injected else None,
        )
    local_lookup.assert_not_called()
    commit.assert_not_called()
    assert provider.get_run("run-a")["lifecycle"] != "SEALED"
    assert not provider.get_manifest("run-a").get("verification_package")


@pytest.mark.parametrize(
    "field,value",
    [
        ("signing_algorithm", "Ed25519ph"),
        ("signing_algorithm", "ED25519_PH_SHA_512"),
        ("signing_semantics", "raw-ed25519-over-original-payload"),
        ("signing_semantics", "DIGEST"),
        ("version", 1.0),
        ("signature_length", 64.0),
    ],
    ids=[
        "SIG-09-ph",
        "SIG-09-kms-ph",
        "SIG-09-original",
        "SIG-09-digest",
        "SIG-08-float-version",
        "SIG-08-float-length",
    ],
)
def test_signature_semantics_and_exact_field_types_are_not_inferred(remote, field, value):
    import base64

    backend, raw, policy = remote
    response = backend.sign_payload(b"{}", purpose=PACKAGE)
    response["envelope"][field] = value
    response["signature"] = base64.b64encode(
        raw.key.sign(canonical_json_encode(response["envelope"]))
    ).decode()
    assert not verify_artifact_signature(b"{}", response, policy, PACKAGE)


def test_mutable_kms_alias_is_not_an_immutable_key_binding(remote):
    from dataclasses import replace

    from agentv_runtime.signatures import DigestEnvelopeSigningBackend, SignatureContractError

    _, raw, policy = remote
    backend = DigestEnvelopeSigningBackend(raw, replace(policy, key_id="alias/production"))
    with pytest.raises(SignatureContractError, match="immutable KMS key ARN"):
        backend.sign_payload(b"{}", purpose=PACKAGE)
    assert not raw.calls
