"""Regression coverage for provider-only run verification."""

import hashlib
from unittest.mock import MagicMock, patch

import pytest

from eval_runner.verifier import TraceVerifier


def test_verify_run_reads_only_the_supplied_provider():
    provider = MagicMock()
    provider.get_run.return_value = {"run_id": "provider-run"}
    provider.get_manifest.return_value = {
        "trace_hash": "digest",
        "signature": "signature",
        "execution_mode": "live",
        "compliance_status": "pass",
    }
    provider.get_trace_bytes.return_value = b'{"event":"run_end"}\n'

    with patch.object(TraceVerifier, "verify_trace_bytes", return_value=True) as verify:
        result = TraceVerifier.verify_run(
            "provider-run", run_store=provider, context={"org_id": "a"}
        )

    assert result["verification_status"] == "VERIFIED"
    verify.assert_called_once_with(
        b'{"event":"run_end"}\n',
        provider.get_manifest.return_value,
        run_store=provider,
        context={"org_id": "a"},
        trace_only=False,
    )
    provider.get_run.assert_called_once_with("provider-run", context={"org_id": "a"})
    provider.get_manifest.assert_called_once_with("provider-run", context={"org_id": "a"})
    provider.get_trace_bytes.assert_called_once_with("provider-run", context={"org_id": "a"})


def test_verify_run_does_not_recover_missing_provider_artifacts_from_disk():
    provider = MagicMock()
    provider.get_run.return_value = {"run_id": "missing-trace"}
    provider.get_manifest.return_value = {"trace_hash": "digest"}
    provider.get_trace_bytes.return_value = None

    result = TraceVerifier.verify_run("missing-trace", run_store=provider)

    assert result["verification_status"] == "FAILED_VERIFICATION"
    assert result["failure_reason"] == "Trace bytes not returned by storage provider."


def test_byte_signer_rejects_bytes_not_owned_by_the_scoped_provider():
    provider = MagicMock()
    provider.get_trace_bytes.return_value = b'{"event":"run_start"}\n'

    with pytest.raises(Exception, match="ProviderTraceOwnershipMismatch"):
        TraceVerifier.sign_trace_bytes(
            b'{"event":"different"}\n',
            run_id="run-a",
            run_store=provider,
            context={"tenant_id": "a"},
        )

    provider.get_trace_bytes.assert_called_once_with("run-a", context={"tenant_id": "a"})


def test_byte_signer_hashes_the_exact_provider_bytes():
    trace = b'{"event":"run_start"}\n'
    provider = MagicMock()
    provider.get_trace_bytes.return_value = trace
    signer = MagicMock()
    signer.sign_payload.return_value = "ab" * 64

    manifest = TraceVerifier.sign_trace_bytes(
        trace,
        run_id="run-a",
        run_store=provider,
        context={"tenant_id": "a"},
        signing_backend=signer,
    )

    assert manifest["trace_hash"] == hashlib.sha3_256(trace).hexdigest()
    assert manifest["hash_algorithm"] == "sha3_256"
