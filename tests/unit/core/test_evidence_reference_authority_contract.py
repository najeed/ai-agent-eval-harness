"""References must resolve independently of signatures and graph commitments."""

import copy
import hashlib
import json

import pytest

from agentv_runtime.evidence_graph import (
    compute_evidence_reference_digest,
    verify_trace_evidence_references,
)
from agentv_runtime.package import VerificationPackage
from eval_runner.identity import IdentityService
from eval_runner.services.certification import execute_industrial_certification
from eval_runner.verifier import VerificationAuthority, verify_trace_certificate
from tests.unit.core.test_signing_finalization_contract import (
    finalization_source as finalization_source,
)


def reference(content=None, **updates):
    sample = {"id": "record-1", "quantity": 10} if content is None else content
    return {
        "source_id": "erp://inventory",
        "scope": "warehouse-a",
        "result_hash": compute_evidence_reference_digest(sample),
        "sampled_result": sample,
        "result_count": 1,
        **updates,
    }


@pytest.mark.parametrize(
    "location", ["top", "nested", "finalization", "empty_alias", "scope", "digest"]
)
def test_every_reference_is_resolved_against_content_in_the_exact_scope(location):
    anchor = reference()
    event = {"event": "oracle_result", "_seq": 1, "evidence_reference": anchor}
    target = copy.deepcopy(anchor)
    if location == "scope":
        target["scope"] = "warehouse-b"
    if location == "digest":
        target["result_hash"] = "a" * 64
    if location == "empty_alias":
        target = {}
    carrier = {"event": "run_end", "_seq": 2}
    if location == "top":
        carrier["assertions"] = [{"reference": reference(source_id="erp://fiction")}]
    elif location == "nested":
        carrier["data"] = {
            "metrics": [{"data": {"reference": reference(source_id="erp://fiction")}}]
        }
    elif location == "finalization":
        carrier = {
            "event": "evaluator_finalization",
            "data": {"metadata": {"reference": reference(source_id="erp://fiction")}},
        }
    elif location == "empty_alias":
        carrier.update(evidence_reference=target, reference=anchor)
    else:
        carrier["evidence_reference"] = target
    failures = verify_trace_evidence_references([event, carrier])
    assert failures and all(
        "EvidenceReferenceVerificationFailed" in failure for failure in failures
    )


def test_hash_only_references_resolve_to_independently_recomputed_observations():
    first, second = reference(), reference({"id": "record-2", "quantity": 20})
    events = [
        {"event": "observation", "data": {"reference": first}},
        {"event": "observation", "reference": second},
    ]
    for ref in (first, second):
        events.append(
            {
                "event": "run_end",
                "reference": {key: value for key, value in ref.items() if key != "sampled_result"},
            }
        )
    assert verify_trace_evidence_references(events) == []


def test_certification_cannot_ignore_fabricated_reference_on_excluded_finalization_carrier(
    finalization_source, tmp_path
):
    from eval_runner.reference.local_run_store import LocalFileRunStore

    original, scenario = finalization_source
    events = original.get_events("run-a", offset=0, limit=100)
    # This carrier is excluded from the evidence root to avoid a self-reference.
    events[-1]["additional_evidence"] = {"evidence_reference": reference()}
    provider = LocalFileRunStore(tmp_path / "fabricated-provider")
    provider.create_run("run-a", scenario["id"])
    provider.append_events("run-a", events)
    provider.save_run_manifest("run-a", original.get_manifest("run-a"))
    with pytest.raises(ValueError, match="EvidenceReferenceVerificationFailed"):
        execute_industrial_certification("run-a", run_store=provider, scenario_data=scenario)
    assert provider.get_run("run-a")["lifecycle"] != "SEALED"


@pytest.mark.parametrize("with_sample", [False, True])
def test_independent_authority_rejects_fabricated_reference_even_in_a_resigned_package(
    finalization_source, with_sample
):
    provider, scenario = finalization_source
    execute_industrial_certification("run-a", run_store=provider, scenario_data=scenario)
    certificate = provider.get_manifest("run-a")
    package = copy.deepcopy(certificate["verification_package"])
    raw = provider.get_trace_bytes("run-a")
    manifest = certificate["execution_manifest"]
    baseline = VerificationAuthority.verify_certification_artifact(
        package, raw_trace_bytes=raw, canonical_manifest=manifest, scenario_data=scenario
    )
    assert baseline["verified"], baseline["failures"]
    events = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    forged = reference()
    if not with_sample:
        del forged["sampled_result"]
    events[-1]["additional_evidence"] = {"evidence_reference": forged}
    raw = ("\n".join(json.dumps(event) for event in events) + "\n").encode()
    digest = "sha3_256:" + hashlib.sha3_256(raw).hexdigest()
    package["trace_hash"] = digest
    package["trace_seal"]["trace_digest"] = digest
    package = (
        VerificationPackage.from_dict(package)
        .sign(IdentityService.get_private_key("system_id", auto_provision=False))
        .to_dict()
    )
    assert VerificationPackage.from_dict(package).verify_signature()
    result = VerificationAuthority.verify_certification_artifact(
        package, raw_trace_bytes=raw, canonical_manifest=manifest, scenario_data=scenario
    )
    assert not result["verified"]
    assert any("EvidenceReferenceVerificationFailed" in failure for failure in result["failures"])
    integrity = verify_trace_certificate(
        "run-a", raw, cert_data=certificate, scenario_data=scenario
    )
    assert not integrity["verified"]
    assert any("EvidenceReferenceVerificationFailed" in error for error in integrity["errors"])


def test_source_scope_delimiters_cannot_alias_another_recorded_source():
    actual = reference(source_id="erp://inventory#warehouse-a", scope="part")
    forged = reference(source_id="erp://inventory", scope="warehouse-a#part")
    failures = verify_trace_evidence_references(
        [
            {"event": "observation", "reference": actual},
            {"event": "run_end", "reference": forged},
        ]
    )
    assert len(failures) == 1
    assert "EvidenceReferenceVerificationFailed" in failures[0]
