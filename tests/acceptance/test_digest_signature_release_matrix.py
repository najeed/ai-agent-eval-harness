"""Real HTTP execution through signed digest envelopes and independent evidence review."""

import copy

import pytest

from agentv_runtime.signatures import (
    DigestEnvelopeSigningBackend,
    SignaturePolicy,
    fingerprint,
)
from eval_runner.console.routes.evidence import build_verification_package
from eval_runner.identity import IdentityService
from eval_runner.runner import DefaultRunner
from eval_runner.services.certification import execute_industrial_certification
from eval_runner.verifier import TraceVerifier, VerificationAuthority, verify_trace_certificate
from tests.acceptance.test_release_evidence_chain_matrix import (
    _independent_review,
    real_chain as real_chain,
)


class RemoteBoundary:
    """Test remote boundary; independent public verification never calls this object."""

    requires_private_key_material = False

    def __init__(self, key):
        self.key = key
        self.calls = []

    def can_sign(self):
        return True

    def sign_payload(self, payload, identity=None, **kwargs):
        assert 1 <= len(payload) <= 4096
        self.calls.append(payload)
        return self.key.sign(payload).hex()


CASES = ["complete_chain", "altered_payload", "unsigned", "unknown_profile", "missing_profile"] + [
    "altered_" + field
    for field in (
        "payload_projection",
        "envelope_canonicalization",
        "purpose",
        "payload_canonicalization",
        "payload_digest",
        "payload_digest_algorithm",
        "payload_digest_encoding",
        "signing_algorithm",
        "signing_semantics",
        "key_id",
        "signer_identity",
        "public_key_fingerprint",
        "fingerprint_algorithm",
        "public_key_encoding",
        "signature_encoding",
        "signature_length",
        "version",
    )
]


@pytest.mark.acceptance
@pytest.mark.acceptance_release
@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES)
async def test_digest_signature_release_matrix(real_chain, case, record_property):
    scenario, store, state = real_chain
    # Ensure both artifact projections exceed the remote RAW limit.
    scenario["metadata"]["large_payload_release_probe"] = "x" * 12000
    run_id = "digest-release-" + case
    await DefaultRunner(run_store=store).run(
        scenario, run_id=run_id, metadata={"execution_mode": "live"}, max_turns=1
    )
    assert state["balance"] == 75 and state["reads"][0] == 100
    key = IdentityService.get_private_key("system_id", auto_provision=False)
    raw_backend = RemoteBoundary(key)
    backend = DigestEnvelopeSigningBackend(
        raw_backend,
        SignaturePolicy("system_id", "sha256:" + fingerprint(key.public_key()), key.public_key()),
    )
    issued = execute_industrial_certification(
        run_id, run_store=store, scenario_data=scenario, signing_backend=backend
    )
    assert issued["certified"]
    assert len(raw_backend.calls) == 2
    certificate = copy.deepcopy(issued["manifest"])
    exported = build_verification_package(run_id, run_store=store)
    raw_trace = store.get_trace_bytes(run_id)
    anchors = {
        identity: IdentityService.get_public_key(identity, auto_provision=False)
        for identity in ("system_id", "eval_kernel")
    }
    assert TraceVerifier.verify_run(run_id, run_store=store)["verified"]
    assert _independent_review(
        certificate, raw_trace, exported["evidence_graph"], scenario, True, anchors, strict=True
    )
    package = certificate["verification_package"]
    if case == "altered_payload":
        package["metadata"]["tampered"] = True
        certificate["metadata"]["tampered"] = True
    elif case != "complete_chain":
        responses = [package["signature"], certificate["provenance_chain"][0]["signature"]]
        for response in responses:
            if case == "unsigned":
                response["signature"] = ""
            elif case == "unknown_profile":
                response["profile"] = "unknown"
            elif case == "missing_profile":
                response.pop("profile")
            else:
                field = case.removeprefix("altered_")
                response["envelope"][field] = (
                    2 if isinstance(response["envelope"][field], int) else "altered"
                )
    expected = case == "complete_chain"
    package_verdict = VerificationAuthority.verify_certification_artifact(
        package,
        raw_trace_bytes=raw_trace,
        canonical_manifest=certificate["execution_manifest"],
        scenario_data=scenario,
    )
    certificate_verdict = verify_trace_certificate(
        run_id, raw_trace, cert_data=certificate, scenario_data=scenario, trace_only=False
    )
    independent = _independent_review(
        certificate, raw_trace, exported["evidence_graph"], scenario, True, anchors
    )
    assert package_verdict["verified"] is expected, package_verdict["failures"]
    assert certificate_verdict["verified"] is expected, certificate_verdict["errors"]
    assert independent is expected
    record_property("expected_verified", expected)
    record_property("independently_verified", independent)
