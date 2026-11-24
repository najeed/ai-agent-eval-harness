"""The emitted certificate reference agrees with the certificate-view consumer."""

from copy import deepcopy
from dataclasses import replace

import pytest

from agentv_runtime.manifest import ExecutionManifest
from agentv_runtime.package import VerificationPackage
from eval_runner.certification_truth import _digest
from eval_runner.identity import IdentityService
from eval_runner.verifier import TraceVerifier, VerificationAuthority
from tests.unit.core.test_signing_finalization_contract import (
    finalization_source as finalization_source,
)


@pytest.mark.parametrize("view_mode", ["live", "hybrid"])
def test_certificate_hash_projection_preserves_execution_mode(finalization_source, view_mode):
    provider, scenario = finalization_source
    manifest = provider.get_manifest("run-a")["execution_manifest"]
    raw = provider.get_trace_bytes("run-a")
    finalization = provider.get_events("run-a", offset=0, limit=100)[-1]["data"]
    certificate = TraceVerifier.sign_trace_bytes(
        raw,
        run_id="run-a",
        run_store=provider,
        scenario_data=scenario,
        execution_manifest=manifest,
        metadata={"required_oracle_ids": ["oracle-1"]},
        execution_mode="live",
        evidence_root_hash=finalization["evidence_root_hash"],
    )
    package = certificate["verification_package"]
    authoritative = VerificationAuthority.verify_certification_artifact(
        package, raw_trace_bytes=raw, canonical_manifest=manifest, scenario_data=scenario
    )
    assert authoritative["certified"], authoritative["failures"]
    # This explicit legacy diagnostic projection resolves the certificate
    # reference only. The complete signed package was checked above; an
    # omitted physical manifest binding must never imply certification here.
    projection = {
        key: value
        for key, value in manifest.items()
        if key not in {"agent_config", "runtime_config", "environment"}
    }
    view = {**certificate, **projection, "execution_mode": view_mode}
    diagnostic_package = deepcopy(package)
    diagnostic_package["manifest_hash"] = ""
    diagnostic_package = (
        VerificationPackage.from_dict(diagnostic_package)
        .sign(IdentityService.get_private_key("system_id", auto_provision=False))
        .to_dict()
    )
    diagnostic = VerificationAuthority.verify_package_artifacts(
        diagnostic_package,
        raw_trace_bytes=raw,
        canonical_manifest=view,
        scenario_data=scenario,
        require_signature=False,
    )
    assert diagnostic["verified"] is (view_mode == "live"), diagnostic["failures"]
    assert diagnostic["authoritative"] is False
    assert diagnostic["certified"] is False
    if view_mode != "live":
        assert any("CertificateHashMismatch" in failure for failure in diagnostic["failures"])


@pytest.mark.parametrize("typed_manifest", [False, True])
@pytest.mark.parametrize(
    ("defect", "failure"),
    [
        ("missing_projection", "CertificateArtifactMissing"),
        ("missing_field", "CertificateArtifactMissing"),
        ("missing_hash", "CertificateHashMissing"),
        ("changed_hash", "CertificateHashMismatch"),
        ("changed_projection", "CertificateHashMismatch"),
        ("rebound_run", "CertificateProjectionMismatch:run_id"),
        ("rebound_compliance", "CertificateProjectionMismatch:compliance"),
    ],
)
def test_authoritative_certificate_projection_is_mandatory_and_recomputed(
    finalization_source, typed_manifest, defect, failure
):
    provider, scenario = finalization_source
    raw = provider.get_trace_bytes("run-a")
    certificate = TraceVerifier.sign_trace_bytes(
        raw, run_id="run-a", run_store=provider, execution_mode="live"
    )
    package = VerificationPackage.from_dict(deepcopy(certificate["verification_package"]))
    projection = package.metadata["certificate_projection"]
    if defect == "missing_projection":
        package.metadata.pop("certificate_projection")
    elif defect == "missing_field":
        projection.pop("timestamp")
    elif defect == "missing_hash":
        package = replace(package, certificate_hash="")
    elif defect == "changed_hash":
        package = replace(package, certificate_hash="sha3_256:tampered")
    elif defect == "changed_projection":
        projection["compliance"]["score"] = 0.125
    elif defect == "rebound_run":
        projection["run_id"] = "another-run"
        package = replace(package, certificate_hash=_digest(projection))
    elif defect == "rebound_compliance":
        projection["compliance"]["score"] = 0.125
        package = replace(package, certificate_hash=_digest(projection))
    # A valid package signature must not hide a broken certificate commitment.
    signed = package.sign(IdentityService.get_private_key("system_id", auto_provision=False))
    assert signed.verify_signature()
    manifest = certificate["execution_manifest"]
    result = VerificationAuthority.verify_certification_artifact(
        signed,
        raw_trace_bytes=raw,
        canonical_manifest=ExecutionManifest.from_dict(manifest) if typed_manifest else manifest,
        scenario_data=scenario,
    )
    assert result["certified"] is False
    assert any(failure in item for item in result["failures"]), result


def test_message_certification_verifies_with_public_trust_without_issuer_secrets(
    finalization_source, monkeypatch
):
    provider, scenario = finalization_source
    raw = provider.get_trace_bytes("run-a")
    certificate = TraceVerifier.sign_trace_bytes(
        raw, run_id="run-a", run_store=provider, execution_mode="live"
    )

    def private_material_forbidden(*args, **kwargs):
        raise AssertionError("Detached verification must not read issuer secrets")

    monkeypatch.setattr(IdentityService, "get_private_key", private_material_forbidden)
    monkeypatch.setattr(
        "eval_runner.state_authority.get_state_authority_trust_key", private_material_forbidden
    )
    result = VerificationAuthority.verify_certification_artifact(
        certificate["verification_package"],
        raw_trace_bytes=raw,
        canonical_manifest=ExecutionManifest.from_dict(certificate["execution_manifest"]),
        scenario_data=scenario,
    )
    assert result["certified"], result["failures"]


@pytest.mark.parametrize("missing_evaluator", [False, True])
def test_explicit_trust_root_controls_evaluator_lookup(
    finalization_source, monkeypatch, tmp_path, missing_evaluator
):
    import shutil

    from eval_runner import config

    provider, scenario = finalization_source
    raw = provider.get_trace_bytes("run-a")
    certificate = TraceVerifier.sign_trace_bytes(
        raw, run_id="run-a", run_store=provider, execution_mode="live"
    )
    public = tmp_path / "independent-public-trust"
    shutil.copytree(config.TRUST_ROOT, public, ignore=shutil.ignore_patterns("private_key.pem"))
    if missing_evaluator:
        (public / "system_id" / "public_key.pem").unlink()
        # The default location still has a valid key: explicit trust must not fall back.
    else:
        monkeypatch.setattr(config, "TRUST_ROOT", tmp_path / "empty-default-trust")
    result = VerificationAuthority.verify_certification_artifact(
        certificate["verification_package"],
        raw_trace_bytes=raw,
        canonical_manifest=ExecutionManifest.from_dict(certificate["execution_manifest"]),
        scenario_data=scenario,
        trust_root=public,
    )
    assert result["verified"] is (not missing_evaluator), result["failures"]


def test_trusted_requester_is_signed_and_idempotent(finalization_source):
    from eval_runner.services.certification import execute_industrial_certification

    provider, scenario = finalization_source
    requester = {"principal_id": "operator", "account_id": "account-1"}
    result = execute_industrial_certification(
        "run-a", run_store=provider, scenario_data=scenario, requester=requester
    )
    package = result["manifest"]["verification_package"]
    assert package["metadata"]["certification_requester"] == requester
    repeated = execute_industrial_certification(
        "run-a", run_store=provider, requester={"account_id": "another-account"}
    )
    assert repeated["manifest"] == result["manifest"]
    tampered = deepcopy(package)
    tampered["metadata"]["certification_requester"]["account_id"] = "forged"
    checked = VerificationAuthority.verify_certification_artifact(
        tampered,
        raw_trace_bytes=provider.get_trace_bytes("run-a"),
        canonical_manifest=ExecutionManifest.from_dict(result["manifest"]["execution_manifest"]),
        scenario_data=scenario,
    )
    assert checked["verified"] is False


def test_capture_receipt_failures_exhaustive():
    import hashlib

    from eval_runner.certification_truth import capture_receipt_failures

    raw_trace = b'{"_seq": 1, "event": "run_start"}\n{"_seq": 2, "event": "run_end"}\n'
    events = [
        {"_seq": 1, "event": "run_start"},
        {"_seq": 2, "event": "run_end"},
    ]
    trace_hash = "sha3_256:" + hashlib.sha3_256(raw_trace).hexdigest()
    valid_receipt = {
        "complete": True,
        "event_count": 2,
        "terminal_seq": 2,
        "trace_hash": trace_hash,
    }

    # 1. Valid receipt
    assert capture_receipt_failures(valid_receipt, raw_trace, events) == []

    # 2. Receipt not a mapping
    assert capture_receipt_failures(None, raw_trace, events) == ["EvidenceCaptureReceiptMissing"]

    # 3. Incomplete receipt
    assert capture_receipt_failures(
        dict(valid_receipt, complete=False), raw_trace, events, require_complete=True
    ) == ["EvidenceCaptureIncomplete"]
    assert (
        capture_receipt_failures(
            dict(valid_receipt, complete=False), raw_trace, events, require_complete=False
        )
        == []
    )

    # 4. Missing raw bytes or empty events
    assert capture_receipt_failures(valid_receipt, None, events) == ["EvidenceCaptureBytesMissing"]
    assert capture_receipt_failures(valid_receipt, raw_trace, []) == ["EvidenceCaptureBytesMissing"]

    # 5. Count mismatch
    assert capture_receipt_failures(dict(valid_receipt, event_count=3), raw_trace, events) == [
        "EvidenceCaptureCountMismatch"
    ]
    assert capture_receipt_failures(dict(valid_receipt, terminal_seq=1), raw_trace, events) == [
        "EvidenceCaptureCountMismatch"
    ]

    # 6. Sequence mismatch
    corrupt_seq = [{"_seq": 1, "event": "run_start"}, {"_seq": 99, "event": "run_end"}]
    assert capture_receipt_failures(valid_receipt, raw_trace, corrupt_seq) == [
        "EvidenceCaptureSequenceMismatch"
    ]

    # 7. Digest mismatch
    assert capture_receipt_failures(
        dict(valid_receipt, trace_hash="sha3_256:wrong"), raw_trace, events
    ) == ["EvidenceCaptureDigestMismatch"]

    # 8. Terminal event missing
    non_terminal_events = [
        {"_seq": 1, "event": "run_start"},
        {"_seq": 2, "event": "intermediate_step"},
    ]
    assert capture_receipt_failures(
        valid_receipt, raw_trace, non_terminal_events, require_complete=True
    ) == ["EvidenceCaptureTerminalMissing"]


def test_extract_scenario_nodes_branches():
    from eval_runner.certification_truth import _extract_scenario_nodes

    # Not a mapping
    assert _extract_scenario_nodes(None) == []

    # Workflow is a list of nodes
    wf_list = [{"id": "n1"}, {"id": "n2"}, "not_a_mapping"]
    assert _extract_scenario_nodes({"workflow": wf_list}) == [{"id": "n1"}, {"id": "n2"}]

    # Workflow is a mapping with nodes list
    wf_dict = {"nodes": [{"id": "n3"}, 42]}
    assert _extract_scenario_nodes({"workflow": wf_dict}) == [{"id": "n3"}]

    # Workflow mapping with nodes not a list
    assert _extract_scenario_nodes({"workflow": {"nodes": "invalid"}}) == []


def test_unsupported_mutation_failures_exhaustive():
    from eval_runner.certification_truth import unsupported_mutation_failures

    # Clean scenario
    assert unsupported_mutation_failures({}) == []

    # Concurrency conflict in metadata
    assert len(unsupported_mutation_failures({"metadata": {"concurrency_conflict": True}})) == 1

    # Applied mutations containing unsupported type
    assert (
        len(
            unsupported_mutation_failures(
                {"metadata": {"applied_mutations": [{"type": "duplicate_commit"}]}}
            )
        )
        == 1
    )

    # Node with concurrent_writers
    scen_node = {"workflow": [{"id": "n1", "concurrent_writers": True}]}
    assert len(unsupported_mutation_failures(scen_node)) == 1


def test_certification_claim_scope_exhaustive():
    from eval_runner.certification_truth import certification_claim_scope

    # Non-mapping
    assert certification_claim_scope(None) == "unverified"

    # Execution evidence (no expected outcome)
    assert certification_claim_scope({"workflow": [{"id": "n1"}]}) == "execution_evidence"

    # Message only
    scen_msg = {
        "workflow": [{"id": "n1", "expected_outcome": [{"target": "message", "property": "text"}]}]
    }
    assert certification_claim_scope(scen_msg) == "message_only"

    # External business state via expected_state_changes
    scen_state = {
        "workflow": [
            {
                "id": "n1",
                "expected_state_changes": [{"path": "balance", "value": 100}],
            }
        ]
    }
    assert certification_claim_scope(scen_state) == "external_business_state"

    # External business state via non-message assertion target
    scen_target = {"workflow": [{"id": "n1", "expected_outcome": [{"target": "authority:orders"}]}]}
    assert certification_claim_scope(scen_target) == "external_business_state"


def test_certificate_projection_failures_exhaustive():
    from types import SimpleNamespace

    from eval_runner.certification_truth import _digest, certificate_projection_failures

    valid_projection = {
        "compliance": {"status": "certified", "score": 1.0},
        "evidence_root_hash": "sha3_root",
        "execution_mode": "live",
        "run_id": "r1",
        "timestamp": "2026-11-17T12:00:00Z",
        "trace_hash": "sha3_trace",
        "vc_version": "1.0",
    }
    cert_hash = _digest(valid_projection)

    pkg = SimpleNamespace(
        certificate_hash=cert_hash,
        metadata={"certificate_projection": valid_projection},
        execution_identity={"run_id": "r1", "execution_mode": "live"},
        evidence_root_hash="sha3_root",
        trace_hash="sha3_trace",
        trace_seal={"sealed_at": "2026-11-17T12:00:00Z"},
        decision={"status": "certified", "score": 1.0},
    )

    # 1. Valid package
    assert certificate_projection_failures(pkg) == []

    # 2. Missing certificate_hash
    assert certificate_projection_failures(SimpleNamespace(certificate_hash=None, metadata={})) == [
        "CertificateHashMissing: authoritative verification requires a certificate hash"
    ]

    # 3. Missing or incomplete projection
    assert certificate_projection_failures(
        SimpleNamespace(certificate_hash="abc", metadata={"certificate_projection": {}})
    ) == ["CertificateArtifactMissing: complete signed certificate projection is required"]

    # 4. Projection with unencodable type
    unencodable_proj = dict(valid_projection, run_id=object())
    assert certificate_projection_failures(
        SimpleNamespace(
            certificate_hash="abc", metadata={"certificate_projection": unencodable_proj}
        )
    ) == ["CertificateHashError: certificate projection is not canonical JSON"]

    # 5. Certificate hash mismatch
    assert (
        "CertificateHashMismatch"
        in certificate_projection_failures(
            replace_field(pkg, certificate_hash="sha3_256:mismatch")
        )[0]
    )

    # 6. Mismatches in execution identity / bindings
    pkg_mismatch = replace_field(
        pkg, execution_identity={"run_id": "r2", "execution_mode": "hybrid"}
    )
    fails = certificate_projection_failures(pkg_mismatch)
    assert any("CertificateProjectionMismatch:run_id" in f for f in fails)
    assert any("CertificateProjectionMismatch:execution_mode" in f for f in fails)

    # 7. Compliance mismatch
    pkg_comp = replace_field(pkg, decision={"status": "rejected", "score": 0.0})
    fails_comp = certificate_projection_failures(pkg_comp)
    assert any("CertificateProjectionMismatch:compliance" in f for f in fails_comp)


def replace_field(obj, **kwargs):
    from types import SimpleNamespace

    d = dict(obj.__dict__)
    d.update(kwargs)
    return SimpleNamespace(**d)


def test_state_claim_failures_exhaustive(monkeypatch):
    import hashlib

    from eval_runner.certification_truth import _digest, state_claim_failures
    from eval_runner.state_authority import create_authenticated_connector_receipt

    auth_secret = b"bWFzdGVyX3NlY3JldF9mb3Jfc3RhdGVfYXV0aF8="
    monkeypatch.setenv("AGENTV_STATE_AUTHORITY_KEY", auth_secret.decode("utf-8"))

    # 1. Non-mapping scenario
    assert state_claim_failures(None, []) == ["StateClaimScenarioMissing"]

    # 2. Invalid state assertion (non-mapping)
    scen_invalid_assert = {
        "metadata": {"state_authorities": {"orders": {"url": "https://orders.example.com"}}},
        "workflow": [{"id": "n1", "expected_outcome": ["not_a_dict"]}],
    }
    assert state_claim_failures(scen_invalid_assert, []) == ["InvalidStateAssertion:n1"]

    # 3. Non-authoritative sandbox state (target == state or shim:*)
    scen_sandbox = {
        "workflow": [
            {
                "id": "n1",
                "expected_outcome": [
                    {"target": "state"},
                    {"target": "shim:mock"},
                ],
            }
        ]
    }
    fails_sb = state_claim_failures(scen_sandbox, [])
    assert "NonAuthoritativeSandboxState:n1:state" in fails_sb
    assert "NonAuthoritativeSandboxState:n1:shim:mock" in fails_sb

    # 4. Policy target with non-authority evidence_target
    scen_policy_no_auth = {
        "metadata": {"policies": {"p1": {"evidence_target": "internal:db"}}},
        "workflow": [{"id": "n1", "expected_outcome": [{"target": "policy:p1"}]}],
    }
    assert "IndependentPolicyEvidenceRequired:n1:policy:p1" in state_claim_failures(
        scen_policy_no_auth, []
    )

    # 5. Expected state changes without matching external assertions
    scen_unmatched_change = {
        "workflow": [
            {
                "id": "n1",
                "expected_state_changes": [{"path": "balance", "value": 100}],
            }
        ]
    }
    assert "IndependentStateAuthorityRequired:n1:balance" in state_claim_failures(
        scen_unmatched_change, []
    )

    # 6. Authoritative run identity missing
    scen_no_run_id = {
        "metadata": {
            "state_authorities": {"orders": {"url": "https://orders.example.com"}},
            "agent": {"endpoint": "https://agent.example.com"},
        },
        "workflow": [
            {
                "id": "n1",
                "expected_outcome": [
                    {"target": "authority:orders", "property": "status", "expected": "PAID"}
                ],
            }
        ],
    }
    assert state_claim_failures(scen_no_run_id, [], run_id=None) == [
        "AuthoritativeRunIdentityRequired:n1"
    ]

    # Baseline valid setup for execution verification
    auth_url = "https://orders.example.com"
    source_id = "sha3_256:" + hashlib.sha3_256(auth_url.rstrip("/").encode()).hexdigest()
    pre_obs = {"status": "PENDING"}
    post_obs = {"status": "PAID"}
    pre_snap = _digest(pre_obs)
    post_snap = _digest(post_obs)

    pre_receipt = create_authenticated_connector_receipt(
        connector_id="conn_orders",
        source_id=source_id,
        phase="pre",
        run_id="run_100",
        execution_id="exec_100",
        timestamp="2026-11-17T10:00:00+00:00",
        response_digest=pre_snap,
        key=auth_secret,
    )
    post_receipt = create_authenticated_connector_receipt(
        connector_id="conn_orders",
        source_id=source_id,
        phase="post",
        run_id="run_100",
        execution_id="exec_100",
        timestamp="2026-11-17T10:00:05+00:00",
        response_digest=post_snap,
        key=auth_secret,
    )

    valid_assertion = {"target": "authority:orders", "property": "status", "expected": "PAID"}
    valid_row = {
        "assertion": valid_assertion,
        "pre_observation": pre_obs,
        "pre_snapshot_hash": pre_snap,
        "pre_observation_identity": {
            "authenticated": True,
            "source_id": source_id,
            "connector_id": "conn_orders",
            "connector_receipt": pre_receipt,
        },
        "post_observation": post_obs,
        "post_snapshot_hash": post_snap,
        "post_observation_identity": {
            "authenticated": True,
            "source_id": source_id,
            "connector_id": "conn_orders",
            "connector_receipt": post_receipt,
        },
        "actual_before": "PENDING",
        "actual_after": "PAID",
        "passed": True,
    }
    valid_events = [
        {
            "event": "execution_graph_node",
            "data": {
                "scenario_node_id": "n1",
                "status": "completed",
                "execution_instance_id": "exec_100",
                "transition_evidence": [valid_row, "not_a_mapping"],
            },
        },
        {"event": "other_event"},
        {"event": "execution_graph_node", "data": {"scenario_node_id": "other_node"}},
        {"event": "execution_graph_node", "data": {"scenario_node_id": "n1", "status": "pending"}},
    ]

    scen_valid = {
        "metadata": {
            "state_authorities": {"orders": {"url": auth_url}},
            "agent": {"endpoint": "https://agent.example.com"},
        },
        "workflow": [{"id": "n1", "expected_outcome": [valid_assertion]}],
    }

    # Verify baseline valid passes with 0 failures
    assert state_claim_failures(scen_valid, valid_events, run_id="run_100") == []

    # 7. A configured HTTP URL still requires receipts bound to that URL
    scen_http_auth = {
        "metadata": {
            "state_authorities": {"orders": {"url": "http://insecure.example.com"}},
            "agent": {"endpoint": "https://agent.example.com"},
        },
        "workflow": [{"id": "n1", "expected_outcome": [valid_assertion]}],
    }
    assert any(
        "InvalidIndependentStateEvidence" in failure
        for failure in state_claim_failures(scen_http_auth, valid_events, run_id="run_100")
    )

    # 8. Same-origin deployment still requires the configured state source binding
    scen_self_auth = {
        "metadata": {
            "state_authorities": {"orders": {"url": "https://agent.example.com"}},
            "agent": {"endpoint": "https://agent.example.com"},
        },
        "workflow": [{"id": "n1", "expected_outcome": [valid_assertion]}],
    }
    assert any(
        "InvalidIndependentStateEvidence" in failure
        for failure in state_claim_failures(scen_self_auth, valid_events, run_id="run_100")
    )

    # 9. No carriers found for node
    assert "IndependentStateObservationMissing:n1:authority:orders" in state_claim_failures(
        scen_valid, [], run_id="run_100"
    )

    # 10. Execution ID missing in event data
    bad_exec_events = [
        {
            "event": "execution_graph_node",
            "data": {
                "scenario_node_id": "n1",
                "status": "completed",
                "execution_instance_id": None,
            },
        }
    ]
    assert "StateObservationExecutionIdentityMissing:n1" in state_claim_failures(
        scen_valid, bad_exec_events, run_id="run_100"
    )

    # 11. Observation matching none of the transitions
    unmatched_trans_events = [
        {
            "event": "execution_graph_node",
            "data": {
                "scenario_node_id": "n1",
                "status": "completed",
                "execution_instance_id": "exec_100",
                "transition_evidence": [
                    dict(valid_row, assertion={"target": "authority:orders", "property": "other"})
                ],
            },
        }
    ]
    assert "IndependentStateObservationMissing:exec_100:authority:orders" in state_claim_failures(
        scen_valid, unmatched_trans_events, run_id="run_100"
    )

    # 12. Pre timestamp > Post timestamp causes evidence failure (line 442)
    pre_receipt_late = create_authenticated_connector_receipt(
        connector_id="conn_orders",
        source_id=source_id,
        phase="pre",
        run_id="run_100",
        execution_id="exec_100",
        timestamp="2026-11-17T10:00:10+00:00",
        response_digest=pre_snap,
        key=auth_secret,
    )
    bad_time_row = dict(
        valid_row,
        pre_observation_identity=dict(
            valid_row["pre_observation_identity"],
            connector_receipt=pre_receipt_late,
        ),
    )
    bad_time_events = [
        {
            "event": "execution_graph_node",
            "data": {
                "scenario_node_id": "n1",
                "status": "completed",
                "execution_instance_id": "exec_100",
                "transition_evidence": [bad_time_row],
            },
        }
    ]
    assert "InvalidIndependentStateEvidence:exec_100:authority:orders" in state_claim_failures(
        scen_valid, bad_time_events, run_id="run_100"
    )

    # 13. Temporal bounds enforcement
    exec_manifest = {
        "started_at": "2026-11-17T09:00:00+00:00",
        "completed_at": "2026-11-17T09:30:00+00:00",
    }
    # Receipt timestamp is 10:00:00, which postdates completed_at 09:30:00 + skew
    assert "InvalidIndependentStateEvidence:exec_100:authority:orders" in state_claim_failures(
        scen_valid, valid_events, execution_manifest=exec_manifest, run_id="run_100"
    )

    # 14. Single dict "url" in authorities (line 140)
    scen_single_dict = {
        "metadata": {
            "state_authority": {"url": auth_url},
            "agent": {"endpoint": "https://agent.example.com"},
        },
        "workflow": [
            {
                "id": "n1",
                "expected_outcome": [
                    {"target": "authority:default", "property": "status", "expected": "PAID"}
                ],
            }
        ],
    }
    valid_default_row = dict(
        valid_row,
        assertion={"target": "authority:default", "property": "status", "expected": "PAID"},
    )
    valid_default_events = [
        {
            "event": "execution_graph_node",
            "data": {
                "scenario_node_id": "n1",
                "status": "completed",
                "execution_instance_id": "exec_100",
                "transition_evidence": [valid_default_row],
            },
        }
    ]
    assert state_claim_failures(scen_single_dict, valid_default_events, run_id="run_100") == []

    # 15. Subpath property via dot in source (e.g. authority:orders.items)
    scen_dot = {
        "metadata": {
            "state_authorities": {"orders": {"url": auth_url}},
            "agent": {"endpoint": "https://agent.example.com"},
        },
        "workflow": [
            {
                "id": "n1",
                "expected_outcome": [
                    {"target": "authority:orders.items", "property": "count", "expected": 2}
                ],
            }
        ],
    }
    pre_dot_obs = {"items": {"count": 1}}
    post_dot_obs = {"items": {"count": 2}}
    pre_dot_snap = _digest(pre_dot_obs)
    post_dot_snap = _digest(post_dot_obs)
    pre_dot_receipt = create_authenticated_connector_receipt(
        connector_id="conn_orders",
        source_id=source_id,
        phase="pre",
        run_id="run_100",
        execution_id="exec_100",
        timestamp="2026-11-17T10:00:00+00:00",
        response_digest=pre_dot_snap,
        key=auth_secret,
    )
    post_dot_receipt = create_authenticated_connector_receipt(
        connector_id="conn_orders",
        source_id=source_id,
        phase="post",
        run_id="run_100",
        execution_id="exec_100",
        timestamp="2026-11-17T10:00:05+00:00",
        response_digest=post_dot_snap,
        key=auth_secret,
    )
    dot_row = {
        "assertion": {
            "target": "authority:orders.items",
            "property": "count",
            "expected": 2,
        },
        "pre_observation": pre_dot_obs,
        "pre_snapshot_hash": pre_dot_snap,
        "pre_observation_identity": {
            "authenticated": True,
            "source_id": source_id,
            "connector_id": "conn_orders",
            "connector_receipt": pre_dot_receipt,
        },
        "post_observation": post_dot_obs,
        "post_snapshot_hash": post_dot_snap,
        "post_observation_identity": {
            "authenticated": True,
            "source_id": source_id,
            "connector_id": "conn_orders",
            "connector_receipt": post_dot_receipt,
        },
        "actual_before": 1,
        "actual_after": 2,
        "passed": True,
    }
    dot_events = [
        {
            "event": "execution_graph_node",
            "data": {
                "scenario_node_id": "n1",
                "status": "completed",
                "execution_instance_id": "exec_100",
                "transition_evidence": [dot_row],
            },
        }
    ]
    assert state_claim_failures(scen_dot, dot_events, run_id="run_100") == []

    # 16. Post observation value is None
    null_post_row = dict(
        dot_row,
        post_observation={"items": {"count": None}},
        post_snapshot_hash=_digest({"items": {"count": None}}),
        post_observation_identity=dict(
            dot_row["post_observation_identity"],
            connector_receipt=create_authenticated_connector_receipt(
                connector_id="conn_orders",
                source_id=source_id,
                phase="post",
                run_id="run_100",
                execution_id="exec_100",
                timestamp="2026-11-17T10:00:05+00:00",
                response_digest=_digest({"items": {"count": None}}),
                key=auth_secret,
            ),
        ),
    )
    null_dot_events = [
        {
            "event": "execution_graph_node",
            "data": {
                "scenario_node_id": "n1",
                "status": "completed",
                "execution_instance_id": "exec_100",
                "transition_evidence": [null_post_row],
            },
        }
    ]
    assert (
        "InvalidIndependentStateEvidence:exec_100:authority:orders.items"
        in state_claim_failures(scen_dot, null_dot_events, run_id="run_100")
    )

    # 17. Policy assertion evidence
    scen_policy = {
        "metadata": {
            "state_authorities": {"orders": {"url": auth_url}},
            "agent": {"endpoint": "https://agent.example.com"},
            "policies": {
                "p_orders": {
                    "evidence_target": "authority:orders",
                    "conditions": {"==": [{"var": "status"}, "PAID"]},
                }
            },
        },
        "workflow": [
            {
                "id": "n1",
                "expected_outcome": [
                    {"target": "policy:p_orders", "property": "allowed", "expected": True}
                ],
            }
        ],
    }
    policy_row = dict(
        valid_row,
        assertion={"target": "policy:p_orders", "property": "allowed", "expected": True},
        actual_before=False,
        actual_after=True,
    )
    policy_events = [
        {
            "event": "execution_graph_node",
            "data": {
                "scenario_node_id": "n1",
                "status": "completed",
                "execution_instance_id": "exec_100",
                "transition_evidence": [policy_row],
            },
        }
    ]
    assert state_claim_failures(scen_policy, policy_events, run_id="run_100") == []

    # 18. Policy post_observation not a mapping (line 477)
    non_map_obs = [1, 2, 3]
    non_map_snap = _digest(non_map_obs)
    non_map_receipt = create_authenticated_connector_receipt(
        connector_id="conn_orders",
        source_id=source_id,
        phase="post",
        run_id="run_100",
        execution_id="exec_100",
        timestamp="2026-11-17T10:00:05+00:00",
        response_digest=non_map_snap,
        key=auth_secret,
    )
    policy_row_bad_map = dict(
        policy_row,
        post_observation=non_map_obs,
        post_snapshot_hash=non_map_snap,
        post_observation_identity=dict(
            policy_row["post_observation_identity"],
            connector_receipt=non_map_receipt,
        ),
    )
    assert "InvalidIndependentStateEvidence:exec_100:authority:orders" in state_claim_failures(
        scen_policy,
        [
            {
                "event": "execution_graph_node",
                "data": {
                    "scenario_node_id": "n1",
                    "status": "completed",
                    "execution_instance_id": "exec_100",
                    "transition_evidence": [policy_row_bad_map],
                },
            }
        ],
        run_id="run_100",
    )

    # 19. Policy recomputed hash mismatch
    policy_row_bad_hash = dict(policy_row, post_snapshot_hash="sha3_256:corrupt")
    assert "InvalidIndependentStateEvidence:exec_100:authority:orders" in state_claim_failures(
        scen_policy,
        [
            {
                "event": "execution_graph_node",
                "data": {
                    "scenario_node_id": "n1",
                    "status": "completed",
                    "execution_instance_id": "exec_100",
                    "transition_evidence": [policy_row_bad_hash],
                },
            }
        ],
        run_id="run_100",
    )

    # 20. Policy evaluated outcome does not match actual_after
    policy_row_bad_actual = dict(policy_row, actual_after=False)
    assert "InvalidIndependentStateEvidence:exec_100:authority:orders" in state_claim_failures(
        scen_policy,
        [
            {
                "event": "execution_graph_node",
                "data": {
                    "scenario_node_id": "n1",
                    "status": "completed",
                    "execution_instance_id": "exec_100",
                    "transition_evidence": [policy_row_bad_actual],
                },
            }
        ],
        run_id="run_100",
    )

    # 21. Expected state changes matched by external assertion (branch 182->181)
    scen_matched_change = {
        "metadata": {
            "state_authorities": {"orders": {"url": auth_url}},
            "agent": {"endpoint": "https://agent.example.com"},
        },
        "workflow": [
            {
                "id": "n1",
                "expected_outcome": [valid_assertion],
                "expected_state_changes": [{"path": "status", "value": "PAID"}],
            }
        ],
    }
    assert state_claim_failures(scen_matched_change, valid_events, run_id="run_100") == []


def test_state_claim_receipt_and_temporal_validation_branches(monkeypatch):
    import hashlib
    from copy import deepcopy

    from eval_runner.certification_truth import _digest, state_claim_failures
    from eval_runner.state_authority import create_authenticated_connector_receipt

    auth_secret = b"bWFzdGVyX3NlY3JldF9mb3Jfc3RhdGVfYXV0aF8="
    monkeypatch.setenv("AGENTV_STATE_AUTHORITY_KEY", auth_secret.decode("utf-8"))

    auth_url = "https://orders.example.com"
    source_id = "sha3_256:" + hashlib.sha3_256(auth_url.rstrip("/").encode()).hexdigest()
    pre_obs = {"status": "PENDING"}
    post_obs = {"status": "PAID"}
    pre_snap = _digest(pre_obs)
    post_snap = _digest(post_obs)

    pre_receipt = create_authenticated_connector_receipt(
        connector_id="conn_orders",
        source_id=source_id,
        phase="pre",
        run_id="run_100",
        execution_id="exec_100",
        timestamp="2026-11-17T10:00:00+00:00",
        response_digest=pre_snap,
        key=auth_secret,
    )
    post_receipt = create_authenticated_connector_receipt(
        connector_id="conn_orders",
        source_id=source_id,
        phase="post",
        run_id="run_100",
        execution_id="exec_100",
        timestamp="2026-11-17T10:00:05+00:00",
        response_digest=post_snap,
        key=auth_secret,
    )

    valid_assertion = {"target": "authority:orders", "property": "status", "expected": "PAID"}
    valid_row = {
        "assertion": valid_assertion,
        "pre_observation": pre_obs,
        "pre_snapshot_hash": pre_snap,
        "pre_observation_identity": {
            "authenticated": True,
            "source_id": source_id,
            "connector_id": "conn_orders",
            "connector_receipt": pre_receipt,
        },
        "post_observation": post_obs,
        "post_snapshot_hash": post_snap,
        "post_observation_identity": {
            "authenticated": True,
            "source_id": source_id,
            "connector_id": "conn_orders",
            "connector_receipt": post_receipt,
        },
        "actual_before": "PENDING",
        "actual_after": "PAID",
        "passed": True,
    }
    scen_valid = {
        "metadata": {
            "state_authorities": {"orders": {"url": auth_url}},
            "agent": {"endpoint": "https://agent.example.com"},
        },
        "workflow": [
            {
                "id": "n1",
                "expected_outcome": [
                    valid_assertion,
                    {"target": "unknown_unmatched_target"},  # branch 176->160
                ],
            }
        ],
    }

    def check_failure(tamper_fn):
        row_copy = deepcopy(valid_row)
        tamper_fn(row_copy)
        evs = [
            {
                "event": "execution_graph_node",
                "data": {
                    "scenario_node_id": "n1",
                    "status": "completed",
                    "execution_instance_id": "exec_100",
                    "transition_evidence": [row_copy],
                },
            }
        ]
        fails = state_claim_failures(scen_valid, evs, run_id="run_100")
        assert len(fails) > 0

    # 1. Identity authenticated is False (line 240)
    check_failure(lambda r: r["pre_observation_identity"].update(authenticated=False))

    # 2. Connector id missing (line 246)
    check_failure(lambda r: r["pre_observation_identity"].update(connector_id=None))

    # 3. Receipt missing / not mapping (line 248)
    check_failure(lambda r: r["pre_observation_identity"].update(connector_receipt="not_a_map"))

    # 4. Receipt source_id mismatch (line 255)
    check_failure(
        lambda r: r["pre_observation_identity"]["connector_receipt"].update(
            source_id="sha3_256:other"
        )
    )

    # 5. Receipt authenticated False (line 257)
    check_failure(
        lambda r: r["pre_observation_identity"]["connector_receipt"].update(authenticated=False)
    )

    # 6. Profile not v2 (line 266)
    check_failure(lambda r: r["pre_observation_identity"]["connector_receipt"].update(profile="v1"))

    # 7. Encoding_version not v2 (line 275)
    check_failure(
        lambda r: r["pre_observation_identity"]["connector_receipt"].update(encoding_version="v1")
    )

    # 8. Version not v2 (line 280)
    check_failure(lambda r: r["pre_observation_identity"]["connector_receipt"].update(version="v1"))

    # 9. Execution ID mismatch in receipt (line 288)
    check_failure(
        lambda r: r["pre_observation_identity"]["connector_receipt"].update(
            execution_id="wrong_exec"
        )
    )

    # 10. Phase missing / invalid (line 293)
    check_failure(
        lambda r: r["pre_observation_identity"]["connector_receipt"].update(phase="wrong")
    )

    # 11. Phase mismatch: expected pre, got post (line 298)
    check_failure(lambda r: r["pre_observation_identity"]["connector_receipt"].update(phase="post"))

    # 12. Run ID missing (line 307)
    check_failure(lambda r: r["pre_observation_identity"]["connector_receipt"].update(run_id=""))

    # 13. Run ID mismatch (line 309)
    check_failure(
        lambda r: r["pre_observation_identity"]["connector_receipt"].update(run_id="run_wrong")
    )

    # 14. Timestamp missing (line 318)
    check_failure(lambda r: r["pre_observation_identity"]["connector_receipt"].update(timestamp=""))

    # 15. Timestamp invalid format (lines 321-322)
    check_failure(
        lambda r: r["pre_observation_identity"]["connector_receipt"].update(timestamp="not-a-date")
    )

    # 16. Timestamp naive (no tz) (line 326)
    check_failure(
        lambda r: r["pre_observation_identity"]["connector_receipt"].update(
            timestamp="2026-11-17T10:00:00"
        )
    )

    # 17. Snapshot hash mismatch (line 425)
    check_failure(lambda r: r.update(pre_snapshot_hash="sha3_256:corrupt"))

    # 18. Response digest missing in receipt (line 428)
    check_failure(
        lambda r: r["pre_observation_identity"]["connector_receipt"].update(response_digest="")
    )

    # 19. Response digest mismatch in receipt (line 430)
    check_failure(
        lambda r: r["pre_observation_identity"]["connector_receipt"].update(
            response_digest="sha3_256:corrupt"
        )
    )

    # 20. Pre-observation timestamp missing tz in pre/post check (line 451)
    check_failure(
        lambda r: r["pre_observation_identity"]["connector_receipt"].update(
            timestamp="2026-11-17T10:00:00"
        )
    )

    # 21. Post-observation timestamp missing tz in pre/post check (line 455)
    check_failure(
        lambda r: r["post_observation_identity"]["connector_receipt"].update(
            timestamp="2026-11-17T10:00:05"
        )
    )

    # 22. Authority changed between pre and post (line 469)
    receipt_c2 = create_authenticated_connector_receipt(
        connector_id="conn_orders_2",
        source_id=source_id,
        phase="post",
        run_id="run_100",
        execution_id="exec_100",
        timestamp="2026-11-17T10:00:05+00:00",
        response_digest=post_snap,
        key=auth_secret,
    )
    row_auth_changed = deepcopy(valid_row)
    row_auth_changed["post_observation_identity"]["connector_id"] = "conn_orders_2"
    row_auth_changed["post_observation_identity"]["connector_receipt"] = receipt_c2
    assert (
        len(
            state_claim_failures(
                scen_valid,
                [
                    {
                        "event": "execution_graph_node",
                        "data": {
                            "scenario_node_id": "n1",
                            "status": "completed",
                            "execution_instance_id": "exec_100",
                            "transition_evidence": [row_auth_changed],
                        },
                    }
                ],
                run_id="run_100",
            )
        )
        > 0
    )

    # 23. Actual after does not match observed (line 517)
    check_failure(lambda r: r.update(actual_after="NOT_PAID"))

    # 24. Missing response digest and response digest mismatch with bypassed verify (lines 428, 430)
    from eval_runner.state_authority import (
        bound_state_snapshot as real_bound,
        verify_connector_receipt_authenticity as real_verify,
    )

    monkeypatch.setattr(
        "eval_runner.state_authority.verify_connector_receipt_authenticity", lambda r: True
    )
    check_failure(
        lambda r: r["pre_observation_identity"]["connector_receipt"].update(response_digest="")
    )
    check_failure(
        lambda r: r["pre_observation_identity"]["connector_receipt"].update(
            response_digest="sha3_256:wrong_digest"
        )
    )
    monkeypatch.setattr(
        "eval_runner.state_authority.verify_connector_receipt_authenticity", real_verify
    )

    # Temporal bounds branches in execution manifest (lines 351-396):
    evs_valid = [
        {
            "event": "execution_graph_node",
            "data": {
                "scenario_node_id": "n1",
                "status": "completed",
                "execution_instance_id": "exec_100",
                "transition_evidence": [valid_row],
            },
        }
    ]

    # 25. Valid temporal window passes both lower and upper bounds (branch 408->414)
    manifest_in_window = {
        "started_at": "2026-11-17T09:00:00+00:00",
        "completed_at": "2026-11-17T11:00:00+00:00",
    }
    assert (
        state_claim_failures(
            scen_valid, evs_valid, execution_manifest=manifest_in_window, run_id="run_100"
        )
        == []
    )

    # 26. require_temporal_bounds=True without execution manifest (branch 351->357)
    assert (
        len(
            state_claim_failures(
                scen_valid,
                evs_valid,
                execution_manifest=None,
                run_id="run_100",
                require_temporal_bounds=True,
            )
        )
        > 0
    )

    # Manifest without temporal bounds when bounds are not required (branch 353->359)
    assert (
        state_claim_failures(
            scen_valid,
            evs_valid,
            execution_manifest={"unrelated": True},
            run_id="run_100",
            require_temporal_bounds=False,
        )
        == []
    )

    # 27. Policy raw observation hash mismatch against bound_state_snapshot (line 485)
    scen_policy_test = {
        "metadata": {
            "state_authorities": {"orders": {"url": auth_url}},
            "agent": {"endpoint": "https://agent.example.com"},
            "policies": {
                "p_orders": {
                    "evidence_target": "authority:orders",
                    "conditions": {"==": [{"var": "status"}, "PAID"]},
                }
            },
        },
        "workflow": [
            {
                "id": "n1",
                "expected_outcome": [
                    {"target": "policy:p_orders", "property": "allowed", "expected": True}
                ],
            }
        ],
    }
    policy_row_test = dict(
        valid_row,
        assertion={"target": "policy:p_orders", "property": "allowed", "expected": True},
        actual_before=False,
        actual_after=True,
    )
    policy_events_test = [
        {
            "event": "execution_graph_node",
            "data": {
                "scenario_node_id": "n1",
                "status": "completed",
                "execution_instance_id": "exec_100",
                "transition_evidence": [policy_row_test],
            },
        }
    ]
    monkeypatch.setattr(
        "eval_runner.state_authority.bound_state_snapshot",
        lambda obs: (obs, "sha3_256:different_hash"),
    )
    assert "InvalidIndependentStateEvidence:exec_100:authority:orders" in state_claim_failures(
        scen_policy_test,
        policy_events_test,
        run_id="run_100",
    )
    monkeypatch.setattr("eval_runner.state_authority.bound_state_snapshot", real_bound)

    # started_at fallback to created_at when require_temporal_bounds=True (lines 351-355, 364)
    manifest_created_only = {"created_at": "2026-11-17T09:00:00+00:00"}
    fails_created = state_claim_failures(
        scen_valid,
        evs_valid,
        execution_manifest=manifest_created_only,
        run_id="run_100",
        require_temporal_bounds=True,
    )
    assert len(fails_created) > 0

    # started_at missing (line 359)
    assert (
        len(
            state_claim_failures(
                scen_valid,
                evs_valid,
                execution_manifest={"completed_at": "2026-11-17T10:30:00+00:00"},
                run_id="run_100",
            )
        )
        > 0
    )

    # started_at invalid (lines 371-372)
    assert (
        len(
            state_claim_failures(
                scen_valid,
                evs_valid,
                execution_manifest={
                    "started_at": "invalid",
                    "completed_at": "2026-11-17T10:30:00+00:00",
                },
                run_id="run_100",
            )
        )
        > 0
    )

    # started_at naive tz (line 376)
    assert (
        len(
            state_claim_failures(
                scen_valid,
                evs_valid,
                execution_manifest={
                    "started_at": "2026-11-17T09:00:00",
                    "completed_at": "2026-11-17T10:30:00+00:00",
                },
                run_id="run_100",
            )
        )
        > 0
    )

    # completed_at invalid (lines 383-384)
    assert (
        len(
            state_claim_failures(
                scen_valid,
                evs_valid,
                execution_manifest={
                    "started_at": "2026-11-17T09:00:00+00:00",
                    "completed_at": "invalid",
                },
                run_id="run_100",
            )
        )
        > 0
    )

    # completed_at naive tz (line 388)
    assert (
        len(
            state_claim_failures(
                scen_valid,
                evs_valid,
                execution_manifest={
                    "started_at": "2026-11-17T09:00:00+00:00",
                    "completed_at": "2026-11-17T10:30:00",
                },
                run_id="run_100",
            )
        )
        > 0
    )

    # started_at postdates completed_at (line 396)
    assert (
        len(
            state_claim_failures(
                scen_valid,
                evs_valid,
                execution_manifest={
                    "started_at": "2026-11-17T11:00:00+00:00",
                    "completed_at": "2026-11-17T09:00:00+00:00",
                },
                run_id="run_100",
            )
        )
        > 0
    )

    # Receipt timestamp predates window (line 404)
    assert (
        len(
            state_claim_failures(
                scen_valid,
                evs_valid,
                execution_manifest={
                    "started_at": "2026-11-17T10:10:00+00:00",
                    "completed_at": "2026-11-17T10:30:00+00:00",
                },
                run_id="run_100",
            )
        )
        > 0
    )


# Superseded host-separation policy; retained at user request.
# Current signed HTTP certification tests cover same-host and undeclared-agent deployments.
# def test_authority_is_independent_exhaustive():
#     from eval_runner.certification_truth import authority_is_independent
#
#     # No agent declared -> fails closed (returns False)
#     assert authority_is_independent("https://auth.example.com", {}) is False
#
#     # Agent matches authority URL -> False
#     scen_matching = {
#         "metadata": {"agent": {"endpoint": "https://same-host.example.com"}},
#     }
#     assert authority_is_independent("https://same-host.example.com/state", scen_matching) is False
#
#     # Agent differs from authority URL -> True
#     assert (
#         authority_is_independent(
#             "https://different-host.example.com/state", scen_matching
#         ) is True
#     )
#
#     # Agent declared as direct string URL
#     scen_str = {"agent": "https://agent-str.example.com"}
#     assert authority_is_independent("https://agent-str.example.com/api", scen_str) is False
#     assert authority_is_independent("https://other-str.example.com/api", scen_str) is True
#
#     # Execution manifest with to_dict and runtime_config
#     class MockManifestObj:
#         def to_dict(self):
#             return {"runtime_config": {"agent": {"url": "https://manifest-agent.example.com"}}}
#
#     assert (
#         authority_is_independent(
#             "https://manifest-agent.example.com", {}, execution_manifest=MockManifestObj()
#         )
#         is False
#     )
#     assert (
#         authority_is_independent(
#             "https://other.example.com", {}, execution_manifest=MockManifestObj()
#         )
#         is True
#     )


# Superseded host-separation policy; retained at user request.
# Current signed HTTP certification tests cover same-host and undeclared-agent deployments.
# def test_authority_is_independent_missing_branch_coverage():
#     from eval_runner.certification_truth import authority_is_independent
#
#     auth_url = "https://orders.example.com"
#     # execution_manifest is not Mapping (branch 84->91)
#     assert (
#         authority_is_independent(
#             auth_url,
#             {"agent": "https://agent.example.com"},
#             execution_manifest="not_a_map",
#         )
#         is True
#     )
#
#     # scenario metadata is not Mapping (branch 92->94)
#     assert (
#         authority_is_independent(
#             auth_url, {"metadata": "not_a_map", "agent": "https://agent.example.com"}
#         )
#         is True
#     )
#
#     # agent dict has empty/whitespace endpoint (branch 100->97)
#     assert authority_is_independent(auth_url, {"agent": {"endpoint": "   "}}) is False
