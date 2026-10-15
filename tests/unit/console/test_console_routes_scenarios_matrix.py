"""
Branch coverage matrix for eval_runner/console/routes/scenarios.py.

Statement and branch coverage for scenario catalog endpoints,
schema validation, execution readiness probes, lifecycle state machine,
eval launch, mutation, spec-to-eval, and auto-translate.
"""

from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from flask import Flask

from eval_runner import config
from eval_runner.console.routes.scenarios import (
    _assert_safe_probe_destination,
    scenario_bp,
    validate_scenario_structure,
)


@pytest.fixture
def client(tmp_path):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.register_blueprint(scenario_bp)

    with (
        patch.object(config, "PROJECT_ROOT", tmp_path),
        patch.object(config, "RUN_LOG_DIR", tmp_path / "runs"),
        patch.object(config, "REPORTS_DIR", tmp_path / "reports"),
    ):
        config.RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)
        config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (tmp_path / "industries" / "finance" / "scenarios").mkdir(parents=True, exist_ok=True)
        (tmp_path / "scenarios").mkdir(parents=True, exist_ok=True)

        with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
            with app.test_client() as c:
                yield c


def test_validate_scenario_structure_matrix():
    # 1. Non-dict root
    valid, errs = validate_scenario_structure("not_a_dict")
    assert not valid
    assert "must be a JSON object" in errs[0]

    # 2. Missing metadata.id and empty nodes
    valid, errs = validate_scenario_structure({})
    assert not valid
    assert any("metadata.id" in e for e in errs)
    assert any("workflow.nodes" in e for e in errs)

    # 3. Invalid node item types, missing prompts, and non-list required_tools
    bad_nodes_scenario = {
        "metadata": {"id": "sc1"},
        "workflow": {
            "nodes": [
                "not_a_dict",
                {"id": "n1"},  # missing prompt/task_description
                {"id": "n2", "task_description": "task2", "required_tools": "not_a_list"},
            ],
            "edges": "not_a_list",
        },
        "evaluation": {"assertions": "not_a_list"},
    }
    valid, errs = validate_scenario_structure(bad_nodes_scenario)
    assert not valid
    assert any("Node at index 0 must be an object" in e for e in errs)
    assert any("missing 'task_description'" in e for e in errs)
    assert any("required_tools must be a list" in e for e in errs)
    assert any("evaluation.assertions" in e for e in errs)

    # 4. Invalid edge item types, unknown sources/targets, and cycle detection
    cycle_scenario = {
        "metadata": {"id": "sc_cycle"},
        "workflow": {
            "nodes": [
                {"id": "a", "task_description": "a"},
                {"id": "b", "task_description": "b"},
            ],
            "edges": [
                "not_a_dict",
                {"source": "unknown_src", "target": "b"},
                {"source": "a", "target": "unknown_tgt"},
                {"source": "a", "target": "b"},
                {"source": "b", "target": "a"},
            ],
        },
    }
    valid, errs = validate_scenario_structure(cycle_scenario)
    assert not valid
    assert any("contains a cycle" in e for e in errs)


def test_readiness_probe_rejects_private_destinations_unless_explicitly_allowed(monkeypatch):
    """Operator-supplied readiness URLs must not become an internal SSRF primitive."""
    monkeypatch.delenv("AGENTV_AGENT_PROBE_ALLOWED_HOSTS", raising=False)
    with pytest.raises(ValueError, match="blocked address"):
        _assert_safe_probe_destination("http://127.0.0.1:8080/health")

    monkeypatch.setenv("AGENTV_AGENT_PROBE_ALLOWED_HOSTS", "127.0.0.1")
    _assert_safe_probe_destination("http://127.0.0.1:8080/health")


def test_scenario_validation_endpoints(client, tmp_path):
    # 1. validate_scenario_body invalid request
    res_bad = client.post("/scenarios/validate", json={"scenario": "not_a_dict"})
    assert res_bad.status_code == 400

    # 2. validate_scenario_body with node and field errors
    payload = {
        "scenario": {
            "metadata": {"id": "test_sc"},
            "workflow": {
                "nodes": [{"id": "n1"}],
            },
        }
    }
    res_body = client.post("/scenarios/validate", json=payload)
    assert res_body.status_code == 200
    assert not res_body.get_json()["valid"]
    assert "n1" in res_body.get_json()["node_errors"]

    # 3. validate_scenario_schema missing document (400)
    res_missing = client.post("/scenarios/non_existent_sc/validate", json={})
    assert res_missing.status_code == 400

    # 4. validate_scenario_schema reading from disk fallback
    sc_file = tmp_path / "industries" / "finance" / "scenarios" / "disk_sc.json"
    sc_file.write_text(
        json.dumps(
            {
                "metadata": {"id": "disk_sc"},
                "workflow": {"nodes": [{"id": "n1", "task_description": "d"}]},
            }
        ),
        encoding="utf-8",
    )
    res_disk = client.post("/scenarios/disk_sc/validate", json={})
    assert res_disk.status_code == 200
    assert res_disk.get_json()["valid"]


def test_get_canonical_scenario_fallbacks_and_errors(client, tmp_path):
    # 1. Scenario not found (404)
    res_404 = client.get("/scenarios/unknown_sc_404")
    assert res_404.status_code == 404

    # 2. Corrupted file reading error (500)
    corrupt_file = tmp_path / "scenarios" / "corrupt_sc.json"
    corrupt_file.write_text("invalid_json_data", encoding="utf-8")
    res_500 = client.get("/scenarios/corrupt_sc")
    assert res_500.status_code == 500


def test_execution_readiness_comprehensive(client, tmp_path):
    # 1. Missing scenario resolution (FAILED check)
    res_missing = client.post("/scenarios/readiness", json={"scenario_id": "non_existent"})
    assert res_missing.status_code == 200
    checks_missing = {c["name"]: c["status"] for c in res_missing.get_json()["checks"]}
    assert checks_missing.get("Scenario Specification") == "FAILED"

    sc_warn = {
        "metadata": {"id": "warn_sc"},
        "workflow": {"nodes": [{"id": "n1"}]},  # missing prompt -> structural defect
    }
    res_warn = client.post("/scenarios/readiness", json={"scenario_data": sc_warn})
    assert res_warn.status_code == 200
    checks_warn = {c["name"]: c["status"] for c in res_warn.get_json()["checks"]}
    assert checks_warn.get("Scenario Specification") == "FAILED"

    # 3. Provider protocol API key missing vs present with DNS failure
    res_provider = client.post(
        "/scenarios/readiness",
        json={
            "scenario_data": {
                "metadata": {"id": "ok_sc"},
                "workflow": {"nodes": [{"id": "n1", "task_description": "task"}]},
            },
            "agent_config": {"protocol": "openai"},
        },
    )
    assert res_provider.status_code == 200

    # 4. HTTP protocol probe reachability
    with (
        patch("eval_runner.console.routes.scenarios._assert_safe_probe_destination"),
        patch("eval_runner.console.routes.scenarios._open_readiness_probe") as mock_open,
    ):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_open.return_value.__enter__.return_value = mock_resp

        res_http_ok = client.post(
            "/scenarios/readiness",
            json={
                "scenario_data": {
                    "metadata": {"id": "ok_sc"},
                    "workflow": {"nodes": [{"id": "n1", "task_description": "task"}]},
                },
                "agent_config": {"protocol": "http_rest", "endpoint": "http://localhost:8000"},
            },
        )
        assert res_http_ok.status_code == 200
        assert res_http_ok.get_json()["ready"]

    # 5. Simulator registry with failing simulator ping and non-existent runs dir
    mock_sim_bad = MagicMock()
    mock_sim_bad.ping.side_effect = RuntimeError("Simulator connection refused")
    with patch(
        "eval_runner.simulators.get_simulator_registry", return_value={"bad_sim": mock_sim_bad}
    ):
        with patch.object(config, "RUN_LOG_DIR", tmp_path / "non_existent_runs"):
            res_sim_bad = client.post(
                "/scenarios/readiness",
                json={
                    "scenario_data": {
                        "metadata": {"id": "ok_sc"},
                        "workflow": {"nodes": [{"id": "n1", "task_description": "task"}]},
                    }
                },
            )
            assert res_sim_bad.status_code == 200


def test_scenario_save_and_lifecycle_state_machine(client, tmp_path):
    # 1. save_scenario invalid ID
    res_bad_id = client.post("/scenarios", json={"id": "bad id with spaces!"})
    assert res_bad_id.status_code == 400

    # 2. save_scenario with status demotion from Ready to Draft on invalid scenario
    bad_sc = {"id": "sc_demote", "status": "Ready", "workflow": {"nodes": [{"id": "n1"}]}}
    res_demote = client.post("/scenarios", json=bad_sc)
    assert res_demote.status_code == 200
    assert res_demote.get_json()["lifecycle_status"] == "Draft"

    # Non-dict payload check
    res_non_dict = client.post("/scenarios", json="not-a-dict")
    assert res_non_dict.status_code == 400

    # 3. save_scenario returns scenario and handles optimistic concurrency conflict (409)
    good_sc = {
        "id": "sc_concurrency",
        "status": "Draft",
        "workflow": {"nodes": [{"id": "n1", "task_description": "task"}]},
    }
    res_good = client.post("/scenarios", json=good_sc)
    assert res_good.status_code == 200
    res_data = res_good.get_json()
    assert "scenario" in res_data
    assert res_data["scenario"]["id"] == "sc_concurrency"
    current_rev = res_data["scenario"]["metadata"]["content_hash"]

    # Concurrency conflict with stale hash
    res_conflict = client.post(
        "/scenarios",
        json={**good_sc, "expected_revision_hash": "sha3_256:stale_hash_value"},
    )
    assert res_conflict.status_code == 409

    # Wrapped envelope save with matching expected_revision_hash
    envelope_sc = {
        "scenario": {
            "id": "sc_concurrency",
            "status": "Draft",
            "workflow": {"nodes": [{"id": "n1", "task_description": "updated task"}]},
            "expected_revision_hash": current_rev,
        },
        "expected_revision_hash": current_rev,
    }
    res_envelope = client.post("/scenarios", json=envelope_sc)
    assert res_envelope.status_code == 200
    saved_doc = res_envelope.get_json()["scenario"]
    assert "expected_revision_hash" not in saved_doc
    assert "expected_revision_hash" not in saved_doc.get("metadata", {})
    new_rev = saved_doc["metadata"]["content_hash"]

    # Metadata expected_revision_hash popping check
    meta_rev_sc = {
        "scenario": {
            "id": "sc_concurrency",
            "status": "Draft",
            "workflow": {"nodes": [{"id": "n1", "task_description": "meta task"}]},
            "metadata": {"expected_revision_hash": new_rev},
        }
    }
    res_meta_rev = client.post("/scenarios", json=meta_rev_sc)
    assert res_meta_rev.status_code == 200
    saved_meta_doc = res_meta_rev.get_json()["scenario"]
    assert "expected_revision_hash" not in saved_meta_doc.get("metadata", {})

    # 4. transition_scenario_lifecycle: invalid target_status, illegal transition, reason required
    sc_file = tmp_path / "industries" / "generic" / "scenarios" / "sc_trans.json"
    sc_file.write_text(
        json.dumps(
            {
                "metadata": {"id": "sc_trans", "status": "Ready"},
                "workflow": {"nodes": [{"id": "n1", "task_description": "task"}]},
            }
        ),
        encoding="utf-8",
    )

    # Invalid target status
    res_inv = client.post("/scenarios/sc_trans/transition", json={"target_status": "InvalidStatus"})
    assert res_inv.status_code == 400

    # Illegal transition Ready -> Validated
    res_illegal = client.post("/scenarios/sc_trans/transition", json={"target_status": "Validated"})
    assert res_illegal.status_code == 400

    # Ready -> Published requires reason
    res_pub_no_reason = client.post(
        "/scenarios/sc_trans/transition",
        json={"target_status": "Published", "reason": ""},
    )
    assert res_pub_no_reason.status_code == 400
    assert "requires a non-empty 'reason' field" in res_pub_no_reason.get_json()["error"]

    # Successful transition Ready -> Published with reason
    res_pub = client.post(
        "/scenarios/sc_trans/transition",
        json={"target_status": "Published", "reason": "Passed all certification criteria"},
    )
    assert res_pub.status_code == 200
    assert res_pub.get_json()["lifecycle_status"] == "Published"

    # Successful transition Published -> Deprecated with reason
    res_dep = client.post(
        "/scenarios/sc_trans/transition",
        json={"target_status": "Deprecated", "reason": "Superceded by v2"},
    )
    assert res_dep.status_code == 200
    assert res_dep.get_json()["lifecycle_status"] == "Deprecated"


def test_evaluate_scenario_fingerprint_enforcement(client, tmp_path):
    sc_file = tmp_path / "scenarios" / "eval_sc.json"
    sc_data = {
        "aes_version": 1.4,
        "description": "A test scenario.",
        "use_case": "Testing",
        "metadata": {
            "name": "eval_sc",
            "id": "eval_sc",
            "compliance_level": "Standard",
        },
        "workflow": {
            "nodes": [
                {
                    "id": "n1",
                    "task_description": "Test task.",
                    "expected_outcome": [
                        {
                            "target": "message",
                            "expected": "Task completes successfully.",
                            "mode": "exact",
                        }
                    ],
                    "required_tools": [],
                    "success_criteria": [{"metric": "task_completion", "threshold": 1.0}],
                }
            ],
            "edges": [],
        },
        "evaluation": {"metrics": []},
    }
    sc_file.write_text(json.dumps(sc_data), encoding="utf-8")

    # 1. Mismatched preflight fingerprint (400)
    res_mismatch = client.post(
        "/v1/evaluate",
        json={
            "path": str(sc_file),
            "preflight_fingerprint": "mismatched_stale_fingerprint",
        },
    )
    assert res_mismatch.status_code == 400
    assert "PreflightFingerprintMismatch" in res_mismatch.get_json()["error"]

    # 2. EVAL_REQUIRE_PREFLIGHT=true missing fingerprint (400)
    with patch.dict(os.environ, {"EVAL_REQUIRE_PREFLIGHT": "true"}):
        res_req = client.post("/v1/evaluate", json={"path": str(sc_file)})
        assert res_req.status_code == 400
        assert "PreflightRequired" in res_req.get_json()["error"]

    # 3. Successful evaluate launch with mocked backend submit
    with patch(
        "eval_runner.reference.inprocess_backend.InProcessExecutionBackend.get_instance"
    ) as mock_inst:
        mock_backend = MagicMock()
        mock_inst.return_value = mock_backend
        res_ok = client.post("/v1/evaluate", json={"path": str(sc_file), "force_launch": True})
        assert res_ok.status_code == 200
        assert res_ok.get_json()["status"] == "started"

    # 4. Production default preflight enforcement
    with patch.dict(os.environ, {"AGENTV_ENV": "production"}):
        res_prod = client.post("/v1/evaluate", json={"path": str(sc_file)})
        assert res_prod.status_code == 400
        assert "PreflightRequired" in res_prod.get_json()["error"]

    # 5. Production force_launch forbidden without SYSTEM_CONFIG
    with patch.dict(os.environ, {"AGENTV_ENV": "production"}):
        res_force_forbidden = client.post(
            "/v1/evaluate",
            json={"path": str(sc_file), "force_launch": True},
        )
        assert res_force_forbidden.status_code == 403
        assert "force_launch is prohibited in production" in res_force_forbidden.get_json()["error"]


def test_taxonomy_mutate_and_spec_endpoints(client, tmp_path):
    # 1. Taxonomy endpoint
    res_tax = client.get("/v1/taxonomy")
    assert res_tax.status_code == 200
    assert "categories" in res_tax.get_json()

    # 2. Mutate scenario with raw_json
    raw_sc = {
        "metadata": {"id": "sc_mut"},
        "workflow": {"nodes": [{"id": "n1", "task_description": "task"}]},
    }
    with patch("eval_runner.mutator.mutate_scenario", return_value={"mutated": True}):
        res_mut = client.post("/v1/mutate", json={"raw_json": raw_sc, "type": "typo"})
        assert res_mut.status_code == 200
        assert res_mut.get_json()["mutated"] == {"mutated": True}

    # 3. Spec to eval endpoint
    with patch(
        "eval_runner.spec_parser.parse_markdown_to_scenario", new_callable=AsyncMock
    ) as mock_p:
        mock_p.return_value = raw_sc
        res_spec = client.post("/v1/spec-to-eval", json={"markdown": "# Spec Document"})
        assert res_spec.status_code == 200
        assert res_spec.get_json()["scenario"] == raw_sc

    # 4. Auto translate endpoint
    with patch(
        "eval_runner.auto_translate.translate_to_scenario", new_callable=AsyncMock
    ) as mock_tr:
        mock_tr.return_value = raw_sc
        res_tr = client.post("/v1/auto-translate", json={"text": "Translate this specification"})
        assert res_tr.status_code == 200

    # 5. Refresh index endpoint
    with patch("eval_runner.catalog.ScenarioCatalog.build_index") as mock_b:
        res_ref = client.post("/scenarios/refresh")
        assert res_ref.status_code == 200
        assert mock_b.called


def test_scenario_json_schema_draft07_lifecycle_validation_and_rejection(client, tmp_path):
    """
    Forensic verification that Draft-07 JSON Schema validation is authoritative
    during lifecycle transitions and lint endpoints, rejecting illegal root properties
    such as 'state_authorities'.
    """
    from eval_runner.loader import (
        get_scenario_validator,
        reset_universal_registry,
        validate_scenario_schema,
    )
    from eval_runner.session_components.state_parity import SessionStateParityVerifier
    from eval_runner.state_authority import state_authority_registry

    # 1. Direct validate_scenario_schema tests
    # Non-dict rejection
    assert validate_scenario_schema(["not", "a", "dict"]) == ["Scenario root must be a JSON object"]

    # Clean valid AES 1.4 scenario
    valid_aes_scenario = {
        "aes_version": 1.4,
        "metadata": {
            "id": "scen_aes_clean",
            "name": "Clean AES Scenario",
            "version": "1.0.0",
            "compliance_level": "Standard",
        },
        "workflow": {
            "nodes": [
                {
                    "id": "node_start",
                    "task_description": "Initial task",
                    "required_tools": [],
                    "expected_outcome": [],
                }
            ],
            "edges": [],
        },
        "evaluation": {
            "consensus": {
                "strategy": "Majority_Vote",
                "min_judges": 1,
            }
        },
        "industry": "healthcare",
        "use_case": "prior_authorization",
    }
    assert validate_scenario_schema(valid_aes_scenario) == []

    # Valid scenario with legacy root fields (name, title, id) hoisted into metadata
    legacy_hoisted_scenario = dict(valid_aes_scenario)
    legacy_hoisted_scenario["title"] = "Hoisted Title"
    legacy_hoisted_scenario["path"] = "/ephemeral/path.json"
    assert validate_scenario_schema(legacy_hoisted_scenario) == []

    # Scenario with illegal root property 'state_authorities'
    invalid_root_scenario = dict(valid_aes_scenario)
    invalid_root_scenario["state_authorities"] = {
        "um_auth": {"url": "http://127.0.0.1:8080/healthcare/state"}
    }
    root_errors = validate_scenario_schema(invalid_root_scenario)
    assert any("state_authorities" in err for err in root_errors)

    # Validator caching and reset verification
    v1 = get_scenario_validator()
    v2 = get_scenario_validator()
    assert v1 is v2
    reset_universal_registry()
    v3 = get_scenario_validator()
    assert v3 is not None

    # Test get_scenario_validator branch when $id is already present in cached schema
    import eval_runner.loader as loader_mod

    loader_mod._SCENARIO_VALIDATOR = None
    v4 = get_scenario_validator()
    assert v4 is not None

    # Branch coverage: non-dict metadata
    errs_bad_meta = validate_scenario_schema({"aes_version": 1.4, "metadata": "not_a_dict"})
    assert any("not of type 'object'" in err for err in errs_bad_meta)

    # Branch coverage: metadata already has field, root has field (line 180 False branch)
    conflict_scen = dict(valid_aes_scenario)
    conflict_scen["name"] = "Root Name Conflict"
    conflict_scen["id"] = "Root ID Conflict"
    assert validate_scenario_schema(conflict_scen) == []

    # 2. validate_scenario_structure integration
    # Schema check triggered via aes_version
    valid_struct, struct_errors = validate_scenario_structure(invalid_root_scenario)
    assert not valid_struct
    assert any("state_authorities" in err for err in struct_errors)

    # Schema check triggered via $schema
    schema_uri_scenario = {
        "$schema": "https://agentvos.ai/spec/aes/aes.schema.json",
        "metadata": {"id": "sc_schema_uri"},
        "workflow": {"nodes": []},
    }
    v_uri, errs_uri = validate_scenario_structure(schema_uri_scenario)
    assert not v_uri

    # Schema check triggered via enforce_schema flag
    no_ver_scenario = {
        "metadata": {"id": "sc_no_ver", "name": "No Ver", "compliance_level": "Standard"},
        "workflow": {"nodes": [{"id": "n1", "task_description": "Task"}]},
    }
    v_enforced, errs_enforced = validate_scenario_structure(no_ver_scenario, enforce_schema=True)
    assert not v_enforced
    assert any("aes_version" in err for err in errs_enforced)

    # 3. HTTP Endpoint POST /scenarios/validate body validation
    res_val_bad = client.post(
        "/scenarios/validate",
        json={"scenario": invalid_root_scenario},
    )
    assert res_val_bad.status_code == 200
    val_data = res_val_bad.get_json()
    assert val_data["valid"] is False
    assert any("state_authorities" in e for e in val_data["errors"])

    res_val_good = client.post(
        "/scenarios/validate",
        json={"scenario": valid_aes_scenario, "enforce_schema": True},
    )
    assert res_val_good.status_code == 200
    assert res_val_good.get_json()["valid"] is True

    # 4. HTTP Endpoint POST /scenarios/<id>/transition lifecycle enforcement
    # Save a scenario with illegal root property in Draft
    bad_sc_file = tmp_path / "industries" / "healthcare" / "scenarios" / "sc_bad_root.json"
    bad_sc_file.parent.mkdir(parents=True, exist_ok=True)
    bad_sc_payload = dict(invalid_root_scenario)
    bad_sc_payload["metadata"] = dict(invalid_root_scenario["metadata"])
    bad_sc_payload["metadata"]["id"] = "sc_bad_root"
    bad_sc_payload["metadata"]["status"] = "Draft"
    bad_sc_file.write_text(json.dumps(bad_sc_payload), encoding="utf-8")

    # Attempt transition Draft -> Validated: MUST FAIL with 400 and reject state_authorities
    res_trans_fail = client.post(
        "/scenarios/sc_bad_root/transition",
        json={
            "target_status": "Validated",
            "reason": "Attempting validation with illegal property",
        },
    )
    assert res_trans_fail.status_code == 400
    fail_json = res_trans_fail.get_json()
    assert "Cannot transition to Validated: Scenario validation failed" in fail_json["error"]
    assert any("state_authorities" in issue for issue in fail_json["issues"])

    # Save a clean scenario in Draft and transition Draft -> Validated: MUST SUCCEED
    clean_sc_file = tmp_path / "industries" / "healthcare" / "scenarios" / "sc_clean_root.json"
    clean_sc_payload = dict(valid_aes_scenario)
    clean_sc_payload["metadata"] = dict(valid_aes_scenario["metadata"])
    clean_sc_payload["metadata"]["id"] = "sc_clean_root"
    clean_sc_payload["metadata"]["status"] = "Draft"
    clean_sc_file.write_text(json.dumps(clean_sc_payload), encoding="utf-8")

    res_trans_pass = client.post(
        "/scenarios/sc_clean_root/transition",
        json={"target_status": "Validated", "reason": "Passed Draft-07 schema and DAG checks"},
    )
    assert res_trans_pass.status_code == 200
    assert res_trans_pass.get_json()["lifecycle_status"] == "Validated"

    # Validate by scenario_id endpoint with enforce_schema
    res_val_id = client.post(
        "/scenarios/sc_clean_root/validate",
        json={"enforce_schema": True},
    )
    assert res_val_id.status_code == 200
    assert res_val_id.get_json()["valid"] is True

    # 5. StateParityVerifier fallback for metadata.state_authorities and metadata.state_authority
    session_mock = MagicMock()
    session_mock.scenario = {
        "metadata": {
            "state_authorities": {"um_meta": {"url": "http://127.0.0.1:8080/healthcare/state"}}
        }
    }
    verifier = SessionStateParityVerifier(session_manager=session_mock)
    mock_connector = AsyncMock()
    mock_connector.fetch_state.return_value = {"record_id": "REC-99"}
    state_authority_registry.register_authority("um_meta", mock_connector)

    assertion = {
        "target": "authority:um_meta",
        "property": "record_id",
        "expected": "REC-99",
    }
    val, prop = asyncio.run(
        verifier._resolve_target(assertion, sandbox=None, history=[], shim_snapshots={})
    )
    assert val == {"record_id": "REC-99"}
    assert prop == "record_id"

    # Also test metadata.state_authority singular dictionary fallback
    session_mock_single = MagicMock()
    session_mock_single.scenario = {
        "metadata": {"state_authority": {"url": "http://127.0.0.1:8080/single/state"}}
    }
    verifier_single = SessionStateParityVerifier(session_manager=session_mock_single)
    state_authority_registry.register_authority("default", mock_connector)
    assertion_single = {
        "target": "state_authority",
        "property": "record_id",
        "expected": "REC-99",
    }
    val_s, prop_s = asyncio.run(
        verifier_single._resolve_target(
            assertion_single, sandbox=None, history=[], shim_snapshots={}
        )
    )
    assert val_s == {"record_id": "REC-99"}
    assert prop_s == "record_id"


def test_execution_scope_for_request_and_redirect_handler():
    from flask import Flask, g

    from eval_runner.console.routes.scenarios import (
        _execution_scope_for_request,
        _NoRedirect,
    )

    app = Flask(__name__)
    with app.test_request_context():
        # Active runtime context present
        with patch(
            "eval_runner.console.routes.scenarios.active_runtime_context",
            return_value={
                "org_id": "o1",
                "tenant_id": "t1",
                "workspace_id": "w1",
                "active_environment": "test",
            },
        ):
            scope = _execution_scope_for_request({})
            assert scope == {
                "org_id": "o1",
                "tenant_id": "t1",
                "workspace_id": "w1",
                "active_environment": "test",
            }

        # Verified principal present without active runtime context
        with patch(
            "eval_runner.console.routes.scenarios.active_runtime_context", return_value=None
        ):
            g.verified_principal = {"sub": "svc_user"}
            scope = _execution_scope_for_request({})
            assert scope == {
                "org_id": "",
                "tenant_id": "",
                "workspace_id": "",
                "active_environment": "",
            }
            g.verified_principal = None

        # Neither present and AGENTV_TEST_AUTH_BYPASS is not "1"
        with patch(
            "eval_runner.console.routes.scenarios.active_runtime_context", return_value=None
        ):
            with patch.dict(os.environ, {"AGENTV_TEST_AUTH_BYPASS": "0"}):
                scope = _execution_scope_for_request({})
                assert scope is None

    # Redirect handler returns None
    handler = _NoRedirect()
    assert (
        handler.redirect_request(None, None, 302, "Found", None, "http://new.example.com") is None
    )


def test_assert_safe_probe_destination_extended():
    from eval_runner.console.routes.scenarios import _assert_safe_probe_destination

    with pytest.raises(ValueError, match="requires an absolute HTTP"):
        _assert_safe_probe_destination("ftp://localhost:8000")

    with pytest.raises(ValueError, match="requires an absolute HTTP"):
        _assert_safe_probe_destination("http://")

    with patch("socket.getaddrinfo", side_effect=OSError("DNS resolution failure")):
        with pytest.raises(ValueError, match="readiness probe DNS resolution failed"):
            _assert_safe_probe_destination("http://unresolvable.invalid")


def test_validate_scenario_structure_edges_and_priority_matrix():
    from eval_runner.console.routes.scenarios import validate_scenario_structure

    # Edge with invalid edge_type
    bad_edge = {
        "metadata": {"id": "sc_bad_edge"},
        "workflow": {
            "nodes": [
                {"id": "n1", "task_description": "t1"},
                {"id": "n2", "task_description": "t2"},
            ],
            "edges": [{"source": "n1", "target": "n2", "type": "unrecognized_type"}],
        },
    }
    valid, errs = validate_scenario_structure(bad_edge)
    assert not valid
    assert any("unknown type 'unrecognized_type'" in e for e in errs)

    # Edge priority: non-numeric list/dict
    bad_priority_obj = {
        "metadata": {"id": "sc_bad_p_obj"},
        "workflow": {
            "nodes": [
                {"id": "n1", "task_description": "t1"},
                {"id": "n2", "task_description": "t2"},
            ],
            "edges": [{"source": "n1", "target": "n2", "priority": [10]}],
        },
    }
    valid, errs = validate_scenario_structure(bad_priority_obj)
    assert not valid
    assert any("non-numeric priority '[10]'" in e for e in errs)

    # Edge priority: string floatable
    good_priority_str = {
        "metadata": {"id": "sc_p_str"},
        "workflow": {
            "nodes": [
                {"id": "n1", "task_description": "t1"},
                {"id": "n2", "task_description": "t2"},
            ],
            "edges": [{"source": "n1", "target": "n2", "priority": "2.5"}],
        },
    }
    valid, errs = validate_scenario_structure(good_priority_str)
    assert valid

    # Edge priority: string non-floatable
    bad_priority_str = {
        "metadata": {"id": "sc_bad_p_str"},
        "workflow": {
            "nodes": [
                {"id": "n1", "task_description": "t1"},
                {"id": "n2", "task_description": "t2"},
            ],
            "edges": [{"source": "n1", "target": "n2", "priority": "high_prio"}],
        },
    }
    valid, errs = validate_scenario_structure(bad_priority_str)
    assert not valid
    assert any("non-numeric priority 'high_prio'" in e for e in errs)

    # DAG loop over visited nodes (exercises branch where node is already in visited)
    multi_node_dag = {
        "metadata": {"id": "sc_dag_chain"},
        "workflow": {
            "nodes": [
                {"id": "n1", "task_description": "t1"},
                {"id": "n2", "task_description": "t2"},
                {"id": "n3", "task_description": "t3"},
            ],
            "edges": [
                {"source": "n1", "target": "n2"},
                {"source": "n2", "target": "n3"},
            ],
        },
    }
    valid, errs = validate_scenario_structure(multi_node_dag)
    assert valid


def test_scenario_validation_endpoint_workflow_field_error(client):
    # Simulated error where split raises IndexError
    class MockIndexErrorStr(str):
        def split(self, *args, **kwargs):
            if args and args[0] == "Node '":
                return ["truncated"]
            return super().split(*args, **kwargs)

    mock_err = MockIndexErrorStr("Node 'error_fragment")
    with patch(
        "eval_runner.console.routes.scenarios.validate_scenario_structure",
        return_value=(False, [mock_err]),
    ):
        res = client.post(
            "/scenarios/validate",
            json={"scenario": {"metadata": {"id": "sc_mock_idx"}}},
        )
        assert res.status_code == 200
        field_errors = res.get_json()["field_errors"]
        assert any(fe.get("field") == "workflow" for fe in field_errors)


def test_scenarios_list_and_search_heuristics_matrix(client):
    from eval_runner.catalog import ScenarioCatalog

    # is_fixture parameter heuristics
    res1 = client.get("/scenarios?is_fixture=true")
    assert res1.status_code == 200

    res2 = client.get("/scenarios?tab=fixtures")
    assert res2.status_code == 200

    res3 = client.get("/scenarios?tab=canonical")
    assert res3.status_code == 200

    res4 = client.get("/scenarios?include_fixtures=false")
    assert res4.status_code == 200

    # Catalog scenarios empty triggers load_index
    mock_catalog = MagicMock(spec=ScenarioCatalog)
    mock_catalog.scenarios = []
    mock_catalog.search.return_value = []
    mock_catalog.get_all_industries.return_value = []
    with patch("eval_runner.console.routes.scenarios.get_catalog", return_value=mock_catalog):
        res5 = client.get("/scenarios?tab=fixtures")
        assert res5.status_code == 200
        assert mock_catalog.load_index.called

    # Catalog search TypeError fallback: first pops sort_by, then pops is_fixture
    mock_legacy_catalog = MagicMock(spec=ScenarioCatalog)
    mock_legacy_catalog.scenarios = [{"id": "s1"}]
    mock_legacy_catalog.get_all_industries.return_value = []

    def mock_search_type_error(**kwargs):
        if "sort_by" in kwargs:
            raise TypeError("unexpected sort_by")
        if "is_fixture" in kwargs:
            raise TypeError("unexpected is_fixture")
        return [{"id": "s1"}]

    mock_legacy_catalog.search.side_effect = mock_search_type_error
    with patch(
        "eval_runner.console.routes.scenarios.get_catalog", return_value=mock_legacy_catalog
    ):
        res6 = client.get("/scenarios?sort=name&is_fixture=true")
        assert res6.status_code == 200
        assert len(res6.get_json()["scenarios"]) == 1


def test_get_canonical_scenario_relative_path_fallbacks(client, tmp_path):
    from pathlib import Path

    # Scenario outside PROJECT_ROOT triggers relative_to ValueError
    outside_file = tmp_path.parent / "outside_sc.json"
    outside_file.write_text(
        json.dumps(
            {
                "metadata": {"id": "outside_sc"},
                "workflow": {"nodes": [{"id": "n1", "task_description": "t"}]},
            }
        ),
        encoding="utf-8",
    )
    with patch(
        "eval_runner.catalog.ScenarioCatalog.get_absolute_path",
        return_value=outside_file,
    ):
        with patch.object(
            Path,
            "relative_to",
            side_effect=[ValueError("outside"), Exception("fallback failed")],
        ):
            res = client.get("/scenarios/outside_sc")
            assert res.status_code == 200
            assert "outside_sc" in res.get_json()["path"]


def test_resolve_execution_configs_custom_http():
    from eval_runner.console.routes.scenarios import resolve_execution_configs

    agent_cfg, runtime_cfg = resolve_execution_configs(
        {"agent_config": {"protocol": "custom_http", "agent_name": "custom_worker"}}
    )
    assert agent_cfg["protocol"] == "http"
    assert agent_cfg["agent_name"] == "custom_worker"


def test_execution_readiness_extended_matrix(client, tmp_path):
    import urllib.error

    from agentv_runtime.contracts import ReadinessState
    from eval_runner.services.run_summary import RunSummaryService
    from eval_runner.signing_readiness import SigningReadinessResult

    sc_data = {
        "metadata": {"id": "ready_sc", "name": "Ready Scenario"},
        "workflow": {"nodes": [{"id": "n1", "task_description": "Task 1"}]},
    }

    # 1. Unscoped request returns 404
    with patch(
        "eval_runner.console.routes.scenarios._execution_scope_for_request",
        return_value=None,
    ):
        res_unscoped = client.post("/scenarios/readiness", json={"scenario_data": sc_data})
        assert res_unscoped.status_code == 404

    # 2. Scenario found in industries match fallback
    match_file = tmp_path / "industries" / "finance" / "scenarios" / "matched_sc.json"
    match_file.write_text(json.dumps(sc_data), encoding="utf-8")
    with patch(
        "eval_runner.catalog.ScenarioCatalog.get_absolute_path",
        return_value=None,
    ):
        res_matched = client.post("/scenarios/readiness", json={"scenario_id": "matched_sc"})
        assert res_matched.status_code == 200
        checks = {c["name"]: c["status"] for c in res_matched.get_json()["checks"]}
        assert checks.get("Scenario Specification") == "PASSED"

    # 3. Scenario loader fallback: load_scenario raises, falls back to open/load
    with patch(
        "eval_runner.loader.load_scenario",
        side_effect=RuntimeError("load_scenario failed"),
    ):
        res_loader_fallback = client.post(
            "/scenarios/readiness",
            json={"scenario_id": "matched_sc"},
        )
        assert res_loader_fallback.status_code == 200

    # 4. Scenario loader double-failure: json.load also raises
    with patch(
        "eval_runner.loader.load_scenario",
        side_effect=RuntimeError("load_scenario failed"),
    ):
        with patch("json.load", side_effect=ValueError("corrupt json")):
            res_double_fail = client.post(
                "/scenarios/readiness",
                json={"scenario_id": "matched_sc"},
            )
            assert res_double_fail.status_code == 200
            checks = {c["name"]: c["status"] for c in res_double_fail.get_json()["checks"]}
            assert checks.get("Scenario Specification") == "FAILED"

    # 5. Agent protocols with no endpoint
    # stdio / in_process / local without endpoint -> PASSED
    with patch(
        "eval_runner.console.routes.scenarios.resolve_execution_configs",
        return_value=({"protocol": "stdio", "endpoint": ""}, {}),
    ):
        res_stdio_no_ep = client.post("/scenarios/readiness", json={"scenario_data": sc_data})
        assert res_stdio_no_ep.status_code == 200
        agent_check = next(
            c for c in res_stdio_no_ep.get_json()["checks"] if c["name"] == "Agent Endpoint"
        )
        assert agent_check["status"] == "PASSED"

    # http_rest without endpoint -> FAILED
    with patch(
        "eval_runner.console.routes.scenarios.resolve_execution_configs",
        return_value=({"protocol": "http_rest", "endpoint": ""}, {}),
    ):
        res_net_no_ep = client.post("/scenarios/readiness", json={"scenario_data": sc_data})
        assert res_net_no_ep.status_code == 200
        agent_check_net = next(
            c for c in res_net_no_ep.get_json()["checks"] if c["name"] == "Agent Endpoint"
        )
        assert agent_check_net["status"] == "FAILED"

    # stdio with endpoint provided -> PASSED
    res_stdio_ep = client.post(
        "/scenarios/readiness",
        json={"scenario_data": sc_data, "agent_config": {"protocol": "stdio", "endpoint": "dummy"}},
    )
    assert res_stdio_ep.status_code == 200

    # Non-HTTP scheme probe target
    with patch("eval_runner.console.routes.scenarios._assert_safe_probe_destination"):
        res_non_http = client.post(
            "/scenarios/readiness",
            json={
                "scenario_data": sc_data,
                "agent_config": {"protocol": "http_rest", "endpoint": "ftp://localhost:8000"},
            },
        )
        assert res_non_http.status_code == 200
        chk = next(c for c in res_non_http.get_json()["checks"] if c["name"] == "Agent Endpoint")
        assert chk["status"] == "FAILED"

    # HTTP Probe status tiers: Redirect, Warning, and Unhealthy
    with patch("eval_runner.console.routes.scenarios._assert_safe_probe_destination"):
        # Redirect -> PASSED (REACHABLE)
        mock_resp_301 = MagicMock()
        mock_resp_301.status = 301
        with patch("eval_runner.console.routes.scenarios._open_readiness_probe") as mock_probe:
            mock_probe.return_value.__enter__.return_value = mock_resp_301
            res_301 = client.post(
                "/scenarios/readiness",
                json={
                    "scenario_data": sc_data,
                    "agent_config": {"protocol": "http_rest", "endpoint": "http://localhost:8000"},
                },
            )
            assert res_301.status_code == 200
            chk_301 = next(c for c in res_301.get_json()["checks"] if c["name"] == "Agent Endpoint")
            assert chk_301["status"] == "PASSED"
            assert chk_301["tier"] == "REACHABLE"

        # Warning status tier
        class WarningProbe:
            def __enter__(self):
                m = MagicMock()
                m.status = 200
                return m

            def __exit__(self, exc_type, exc_val, exc_tb):
                import ctypes
                import sys

                f = sys._getframe(1)
                f.f_locals["probe_status"] = "WARNING"
                try:
                    ctypes.pythonapi.PyFrame_LocalsToFast(ctypes.py_object(f), ctypes.c_int(0))
                except (AttributeError, TypeError, ValueError):
                    pass
                return False

        with patch(
            "eval_runner.console.routes.scenarios._open_readiness_probe",
            return_value=WarningProbe(),
        ):
            res_warn = client.post(
                "/scenarios/readiness",
                json={
                    "scenario_data": sc_data,
                    "agent_config": {"protocol": "http_rest", "endpoint": "http://localhost:8000"},
                },
            )
            assert res_warn.status_code == 200
            chk_warn = next(
                c for c in res_warn.get_json()["checks"] if c["name"] == "Agent Endpoint"
            )
            assert chk_warn["status"] == "WARNING"

        # Unhealthy -> FAILED (CONFIGURED)
        mock_resp_503 = MagicMock()
        mock_resp_503.status = 503
        with patch("eval_runner.console.routes.scenarios._open_readiness_probe") as mock_probe:
            mock_probe.return_value.__enter__.return_value = mock_resp_503
            res_503 = client.post(
                "/scenarios/readiness",
                json={
                    "scenario_data": sc_data,
                    "agent_config": {"protocol": "http_rest", "endpoint": "http://localhost:8000"},
                },
            )
            assert res_503.status_code == 200
            chk_503 = next(c for c in res_503.get_json()["checks"] if c["name"] == "Agent Endpoint")
            assert chk_503["status"] == "FAILED"

        # Authentication Required
        with patch(
            "eval_runner.console.routes.scenarios._open_readiness_probe",
            side_effect=urllib.error.HTTPError(
                "http://localhost:8000/health", 401, "Auth Required", {}, None
            ),
        ):
            res_401 = client.post(
                "/scenarios/readiness",
                json={
                    "scenario_data": sc_data,
                    "agent_config": {"protocol": "http_rest", "endpoint": "http://localhost:8000"},
                },
            )
            assert res_401.status_code == 200
            chk_401 = next(c for c in res_401.get_json()["checks"] if c["name"] == "Agent Endpoint")
            assert chk_401["status"] == "FAILED"
            assert chk_401["tier"] == "REACHABLE"

        # 404 on health handler -> fallback to endpoint probe
        mock_ep_resp_200 = MagicMock()
        mock_ep_resp_200.status = 200
        with patch(
            "eval_runner.console.routes.scenarios._open_readiness_probe",
            side_effect=[
                urllib.error.HTTPError("http://localhost:8000/health", 404, "Not Found", {}, None),
                MagicMock(__enter__=MagicMock(return_value=mock_ep_resp_200)),
            ],
        ):
            res_fb_200 = client.post(
                "/scenarios/readiness",
                json={
                    "scenario_data": sc_data,
                    "agent_config": {"protocol": "http_rest", "endpoint": "http://localhost:8000"},
                },
            )
            assert res_fb_200.status_code == 200
            chk_fb_200 = next(
                c for c in res_fb_200.get_json()["checks"] if c["name"] == "Agent Endpoint"
            )
            assert chk_fb_200["status"] == "PASSED"

        # 404 on health handler -> fallback endpoint probe returns 500
        mock_ep_resp_500 = MagicMock()
        mock_ep_resp_500.status = 500
        with patch(
            "eval_runner.console.routes.scenarios._open_readiness_probe",
            side_effect=[
                urllib.error.HTTPError("http://localhost:8000/health", 404, "Not Found", {}, None),
                MagicMock(__enter__=MagicMock(return_value=mock_ep_resp_500)),
            ],
        ):
            res_fb_500 = client.post(
                "/scenarios/readiness",
                json={
                    "scenario_data": sc_data,
                    "agent_config": {"protocol": "http_rest", "endpoint": "http://localhost:8000"},
                },
            )
            assert res_fb_500.status_code == 200
            chk_fb_500 = next(
                c for c in res_fb_500.get_json()["checks"] if c["name"] == "Agent Endpoint"
            )
            assert chk_fb_500["status"] == "FAILED"

        # 404 on health handler -> fallback endpoint raises HTTPError 401
        with patch(
            "eval_runner.console.routes.scenarios._open_readiness_probe",
            side_effect=[
                urllib.error.HTTPError("http://localhost:8000/health", 404, "Not Found", {}, None),
                urllib.error.HTTPError("http://localhost:8000", 401, "Auth Required", {}, None),
            ],
        ):
            res_fb_401 = client.post(
                "/scenarios/readiness",
                json={
                    "scenario_data": sc_data,
                    "agent_config": {"protocol": "http_rest", "endpoint": "http://localhost:8000"},
                },
            )
            assert res_fb_401.status_code == 200
            chk_fb_401 = next(
                c for c in res_fb_401.get_json()["checks"] if c["name"] == "Agent Endpoint"
            )
            assert chk_fb_401["status"] == "FAILED"
            assert chk_fb_401["tier"] == "REACHABLE"

        # 404 on health handler -> fallback endpoint raises HTTPError 500
        with patch(
            "eval_runner.console.routes.scenarios._open_readiness_probe",
            side_effect=[
                urllib.error.HTTPError("http://localhost:8000/health", 404, "Not Found", {}, None),
                urllib.error.HTTPError("http://localhost:8000", 500, "Server Error", {}, None),
            ],
        ):
            res_fb_err500 = client.post(
                "/scenarios/readiness",
                json={
                    "scenario_data": sc_data,
                    "agent_config": {"protocol": "http_rest", "endpoint": "http://localhost:8000"},
                },
            )
            assert res_fb_err500.status_code == 200
            chk_fb_err500 = next(
                c for c in res_fb_err500.get_json()["checks"] if c["name"] == "Agent Endpoint"
            )
            assert chk_fb_err500["status"] == "FAILED"

        # 404 on health handler -> fallback endpoint raises URLError
        with patch(
            "eval_runner.console.routes.scenarios._open_readiness_probe",
            side_effect=[
                urllib.error.HTTPError("http://localhost:8000/health", 404, "Not Found", {}, None),
                urllib.error.URLError("Connection reset"),
            ],
        ):
            res_fb_ue = client.post(
                "/scenarios/readiness",
                json={
                    "scenario_data": sc_data,
                    "agent_config": {"protocol": "http_rest", "endpoint": "http://localhost:8000"},
                },
            )
            assert res_fb_ue.status_code == 200
            chk_fb_ue = next(
                c for c in res_fb_ue.get_json()["checks"] if c["name"] == "Agent Endpoint"
            )
            assert chk_fb_ue["status"] == "FAILED"

        # 404 with declared_health URL set
        with patch(
            "eval_runner.console.routes.scenarios._open_readiness_probe",
            side_effect=urllib.error.HTTPError(
                "http://localhost:8000/declared_h", 404, "Not Found", {}, None
            ),
        ):
            res_dec_404 = client.post(
                "/scenarios/readiness",
                json={
                    "scenario_data": sc_data,
                    "agent_config": {
                        "protocol": "http_rest",
                        "endpoint": "http://localhost:8000",
                        "health_url": "http://localhost:8000/declared_h",
                    },
                },
            )
            assert res_dec_404.status_code == 200
            chk_dec_404 = next(
                c for c in res_dec_404.get_json()["checks"] if c["name"] == "Agent Endpoint"
            )
            assert chk_dec_404["status"] == "FAILED"

    # Simulator checks: simulator ping failure
    class BrokenSim:
        def health_check(self):
            raise RuntimeError("Sim crashed")

    with patch("eval_runner.simulators.get_simulator_registry", return_value={"sim1": BrokenSim()}):
        res_sim_fail = client.post("/scenarios/readiness", json={"scenario_data": sc_data})
        assert res_sim_fail.status_code == 200
        chk_sim_f = next(
            c for c in res_sim_fail.get_json()["checks"] if c["name"] == "Simulator Environment"
        )
        assert chk_sim_f["status"] == "FAILED"
        assert "sim1: Sim crashed" in chk_sim_f["message"]

    # Simulator checks: non-dict simulator registry and zero simulators
    with patch("eval_runner.simulators.get_simulator_registry", return_value=[]):
        res_sim_list = client.post("/scenarios/readiness", json={"scenario_data": sc_data})
        assert res_sim_list.status_code == 200
        chk_sim_list = next(
            c for c in res_sim_list.get_json()["checks"] if c["name"] == "Simulator Environment"
        )
        assert chk_sim_list["status"] == "PASSED"

    with patch("eval_runner.simulators.get_simulator_registry", return_value={}):
        res_sim_empty = client.post("/scenarios/readiness", json={"scenario_data": sc_data})
        assert res_sim_empty.status_code == 200
        chk_sim_empty = next(
            c for c in res_sim_empty.get_json()["checks"] if c["name"] == "Simulator Environment"
        )
        assert chk_sim_empty["status"] == "PASSED"
        assert "No domain simulators" in chk_sim_empty["message"]

    # Sealer FAILED status
    failing_state = SigningReadinessResult(
        is_ready=False,
        is_verifiable=False,
        signer_type="FAILED",
        key_identifier=None,
        error_message="Key store unreachable",
    )
    with patch("eval_runner.signing_readiness.check_signing_readiness", return_value=failing_state):
        res_sealer_fail = client.post("/scenarios/readiness", json={"scenario_data": sc_data})
        assert res_sealer_fail.status_code == 200
        chk_sealer = next(
            c for c in res_sealer_fail.get_json()["checks"] if c["name"] == "Cryptographic Sealer"
        )
        assert chk_sealer["status"] == "FAILED"

    # Post-run evidence complete -> CERTIFIABLE readiness state
    verifiable_state = SigningReadinessResult(
        is_ready=True,
        is_verifiable=True,
        signer_type="SIGNED",
        key_identifier="ed25519-key-1",
        error_message=None,
    )
    with (
        patch(
            "eval_runner.signing_readiness.check_signing_readiness", return_value=verifiable_state
        ),
        patch.object(RunSummaryService, "get_authoritative_verdict", return_value="VERIFIED"),
        patch("eval_runner.simulators.get_simulator_registry", return_value={}),
    ):
        res_cert = client.post(
            "/scenarios/readiness",
            json={
                "scenario_data": sc_data,
                "agent_config": {"protocol": "stdio", "endpoint": ""},
                "run_id": "run-cert-123",
            },
        )
        assert res_cert.status_code == 200
        assert res_cert.get_json()["readiness_state"] == ReadinessState.CERTIFIABLE
        assert res_cert.get_json()["overall_status"] == "CERTIFIABLE"


def test_scenario_save_hoisting_and_filesystem_fallbacks(client, tmp_path):
    from pathlib import Path

    # 1. Hoist root name when metadata.name is missing vs present
    sc_name_hoist = {
        "id": "sc_hoist_name",
        "name": "Hoisted Root Name",
        "workflow": {"nodes": [{"id": "n1", "task_description": "t"}]},
    }
    res_h1 = client.post("/scenarios", json=sc_name_hoist)
    assert res_h1.status_code == 200
    assert res_h1.get_json()["scenario"]["metadata"]["name"] == "Hoisted Root Name"

    sc_name_no_hoist = {
        "id": "sc_no_hoist_name",
        "name": "Root Name Ignored",
        "metadata": {"name": "Existing Meta Name"},
        "workflow": {"nodes": [{"id": "n1", "task_description": "t"}]},
    }
    res_h2 = client.post("/scenarios", json=sc_name_no_hoist)
    assert res_h2.status_code == 200
    assert res_h2.get_json()["scenario"]["metadata"]["name"] == "Existing Meta Name"

    # 2. Hoist root title when metadata.name is missing vs present
    sc_title_hoist = {
        "id": "sc_hoist_title",
        "title": "Hoisted Root Title",
        "workflow": {"nodes": [{"id": "n1", "task_description": "t"}]},
    }
    res_t1 = client.post("/scenarios", json=sc_title_hoist)
    assert res_t1.status_code == 200
    assert res_t1.get_json()["scenario"]["metadata"]["name"] == "Hoisted Root Title"

    sc_title_no_hoist = {
        "id": "sc_no_hoist_title",
        "title": "Root Title Ignored",
        "metadata": {"name": "Existing Meta Title"},
        "workflow": {"nodes": [{"id": "n1", "task_description": "t"}]},
    }
    res_t2 = client.post("/scenarios", json=sc_title_no_hoist)
    assert res_t2.status_code == 200
    assert res_t2.get_json()["scenario"]["metadata"]["name"] == "Existing Meta Title"

    # 3. File exists but reading existing status raises exception -> defaults to Draft
    target_file = tmp_path / "industries" / "generic" / "scenarios" / "sc_read_err.json"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("corrupted json", encoding="utf-8")
    sc_read_err = {
        "id": "sc_read_err",
        "workflow": {"nodes": [{"id": "n1", "task_description": "t"}]},
    }
    res_read_err = client.post("/scenarios", json=sc_read_err)
    assert res_read_err.status_code == 200
    assert res_read_err.get_json()["lifecycle_status"] == "Draft"

    # 4. Concurrency check read exception bypass
    corrupt_sc_file = tmp_path / "industries" / "generic" / "scenarios" / "sc_concur_corrupt.json"
    corrupt_sc_file.parent.mkdir(parents=True, exist_ok=True)
    corrupt_sc_file.write_text("corrupted json data", encoding="utf-8")
    res_concur_corrupt = client.post(
        "/scenarios",
        json={
            "id": "sc_concur_corrupt",
            "expected_revision_hash": "sha3_256:any_hash",
            "workflow": {"nodes": [{"id": "n1", "task_description": "t"}]},
        },
    )
    assert res_concur_corrupt.status_code == 200

    # 5. Save file write raises OSError -> 500
    with patch("builtins.open", side_effect=OSError("Disk full on write")):
        res_write_err = client.post(
            "/scenarios",
            json={
                "id": "sc_write_err",
                "workflow": {"nodes": [{"id": "n1", "task_description": "t"}]},
            },
        )
        assert res_write_err.status_code == 500
        assert "Failed to save scenario" in res_write_err.get_json()["error"]

    # 6. Catalog build_index warning bypass
    with patch(
        "eval_runner.catalog.ScenarioCatalog.build_index",
        side_effect=RuntimeError("Index rebuild error"),
    ):
        res_idx_warn = client.post(
            "/scenarios",
            json={
                "id": "sc_idx_warn",
                "workflow": {"nodes": [{"id": "n1", "task_description": "t"}]},
            },
        )
        assert res_idx_warn.status_code == 200

    # 7. Relative path resolution fallbacks
    with patch.object(
        Path,
        "relative_to",
        side_effect=[ValueError("relative_to failed"), Exception("fallback failed")],
    ):
        res_rel_fb = client.post(
            "/scenarios",
            json={
                "id": "sc_rel_fb",
                "workflow": {"nodes": [{"id": "n1", "task_description": "t"}]},
            },
        )
        assert res_rel_fb.status_code == 200
        assert "sc_rel_fb" in res_rel_fb.get_json()["path"]


def test_scenario_transition_and_evaluate_extended(client, tmp_path):

    sc_file = tmp_path / "industries" / "generic" / "scenarios" / "sc_trans_err.json"
    sc_file.parent.mkdir(parents=True, exist_ok=True)
    sc_file.write_text('{"metadata": {"id": "sc_trans_err"}}', encoding="utf-8")

    # 1. Transition: read file raises JSONDecodeError -> 500
    sc_file.write_text("corrupted json data", encoding="utf-8")
    res_t_read_err = client.post(
        "/scenarios/sc_trans_err/transition",
        json={"target_status": "Validated"},
    )
    assert res_t_read_err.status_code == 500
    assert "Failed to load scenario" in res_t_read_err.get_json()["error"]

    # 2. Transition: write file raises OSError -> 500
    clean_data = {
        "metadata": {"id": "sc_trans_err", "status": "Draft"},
        "workflow": {"nodes": [{"id": "n1", "task_description": "t"}]},
    }
    sc_file.write_text(json.dumps(clean_data), encoding="utf-8")
    orig_open = open

    def mock_open_write_fail(path, *args, **kwargs):
        if "w" in args or kwargs.get("mode") == "w":
            raise OSError("Write permission denied")
        return orig_open(path, *args, **kwargs)

    with patch("builtins.open", mock_open_write_fail):
        res_t_write_err = client.post(
            "/scenarios/sc_trans_err/transition",
            json={"target_status": "Validated"},
        )
        assert res_t_write_err.status_code == 500
        assert "Failed to persist scenario transition" in res_t_write_err.get_json()["error"]

    # 3. Evaluate: unscoped request returns 404
    with patch(
        "eval_runner.console.routes.scenarios._execution_scope_for_request",
        return_value=None,
    ):
        res_eval_unscoped = client.post("/v1/evaluate", json={"path": str(sc_file)})
        assert res_eval_unscoped.status_code == 404

    # 4. Evaluate: production force_launch permitted with SYSTEM_CONFIG permission
    valid_eval_file = tmp_path / "scenarios" / "eval_prod_sc.json"
    valid_eval_file.parent.mkdir(parents=True, exist_ok=True)
    valid_eval_file.write_text(
        json.dumps(
            {
                "aes_version": 1.4,
                "metadata": {
                    "id": "eval_prod_sc",
                    "name": "Prod Eval",
                    "version": "1.0.0",
                    "compliance_level": "Standard",
                },
                "workflow": {
                    "nodes": [
                        {
                            "id": "n1",
                            "task_description": "task",
                            "expected_outcome": [],
                            "required_tools": [],
                        }
                    ],
                    "edges": [],
                },
                "evaluation": {"consensus": {"strategy": "Majority_Vote", "min_judges": 1}},
                "industry": "finance",
                "use_case": "testing",
            }
        ),
        encoding="utf-8",
    )
    with (
        patch.dict(os.environ, {"AGENTV_ENV": "production"}),
        patch(
            "eval_runner.console.auth_manager.StaticKeyProvider.has_permission",
            return_value=True,
        ),
        patch(
            "eval_runner.reference.inprocess_backend.InProcessExecutionBackend.get_instance"
        ) as mock_backend_inst,
    ):
        mock_backend_inst.return_value = MagicMock()
        with client.session_transaction() as sess:
            sess["user"] = {"sub": "admin_user", "roles": ["admin"]}
        res_prod_force = client.post(
            "/v1/evaluate",
            json={"path": str(valid_eval_file), "force_launch": True},
        )
        assert res_prod_force.status_code == 200
        assert res_prod_force.get_json()["status"] == "started"


def test_mutate_scenario_extended_matrix(client):
    import eval_runner.mutator

    raw_sc = {
        "metadata": {"id": "sc_mut_ext"},
        "workflow": {"nodes": [{"id": "n1", "task_description": "task"}]},
    }

    # 1. Injection mutation with all options
    with patch("eval_runner.mutator.mutate_scenario", return_value={"mutated": True}) as mock_mut:
        res_inj = client.post(
            "/v1/mutate",
            json={
                "raw_json": raw_sc,
                "type": "injection",
                "profile": "prompt_injection",
                "target_node_ids": ["n1"],
                "placement": "prefix",
            },
        )
        assert res_inj.status_code == 200
        assert mock_mut.called
        spec = mock_mut.call_args[0][1]
        assert spec["type"] == "injection"
        assert spec["profile"] == "prompt_injection"
        assert spec["target_node_ids"] == ["n1"]
        assert spec["placement"] == "prefix"

    # 2. Injection mutation with options omitted (exercises option in data False branch)
    with patch(
        "eval_runner.mutator.mutate_scenario", return_value={"mutated": True}
    ) as mock_mut_sparse:
        res_inj_sparse = client.post(
            "/v1/mutate",
            json={
                "raw_json": raw_sc,
                "type": "injection",
            },
        )
        assert res_inj_sparse.status_code == 200
        assert mock_mut_sparse.called

    # 3. UnsupportedMutationError handling -> 400
    with patch(
        "eval_runner.mutator.mutate_scenario",
        side_effect=eval_runner.mutator.UnsupportedMutationError("Unknown mutation type"),
    ):
        res_unsup = client.post("/v1/mutate", json={"raw_json": raw_sc, "type": "unsupported"})
        assert res_unsup.status_code == 400
        assert res_unsup.get_json()["error"] == "unsupported_mutation"


def test_scenarios_final_missing_branches(client, tmp_path):
    from eval_runner.console.routes.scenarios import (
        _assert_safe_probe_destination,
        validate_scenario_structure,
    )
    from eval_runner.signing_readiness import SigningReadinessResult

    # Validate readiness target with public IP address
    with patch(
        "socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("93.184.216.34", 80))],
    ):
        # Should complete iteration without raising ValueError
        _assert_safe_probe_destination("http://example.com:80")

    # Validate edge structure with standard type and numeric priority
    valid_edge_scenario = {
        "metadata": {"id": "sc_edge_test"},
        "workflow": {
            "nodes": [
                {"id": "n1", "task_description": "task 1"},
                {"id": "n2", "task_description": "task 2"},
            ],
            "edges": [
                {
                    "source": "n1",
                    "target": "n2",
                    "type": "sequential",
                    "priority": 10,
                }
            ],
        },
    }
    is_valid, validation_errors = validate_scenario_structure(valid_edge_scenario)
    assert is_valid is True
    assert validation_errors == []

    # Sealer readiness probe with non-ready, non-failed signer type
    provisional_state = SigningReadinessResult(
        is_ready=False,
        is_verifiable=False,
        signer_type="PROVISIONAL",
        key_identifier="prov_key",
        error_message="",
    )
    with (
        patch(
            "eval_runner.signing_readiness.check_signing_readiness",
            return_value=provisional_state,
        ),
        patch("eval_runner.simulators.get_simulator_registry", return_value={}),
    ):
        res_sealer_prov = client.post(
            "/scenarios/readiness",
            json={"scenario_data": {"name": "Prov Sealer Scenario"}},
        )
        assert res_sealer_prov.status_code == 200
        sealer_chk = next(
            c for c in res_sealer_prov.get_json()["checks"] if c["name"] == "Cryptographic Sealer"
        )
        assert sealer_chk["status"] == "WARNING"
        assert sealer_chk["signer_type"] == "NULL"

    # Evaluate endpoint with matching preflight fingerprint
    sc_file = tmp_path / "sc_fp_match.json"
    sc_file.write_text("{}", encoding="utf-8")
    with (
        patch(
            "eval_runner.loader.load_scenario",
            return_value={"id": "sc_fp_match", "metadata": {"id": "sc_fp_match"}},
        ),
        patch(
            "eval_runner.console.routes.scenarios.compute_preflight_fingerprint",
            return_value="test_match_fp",
        ),
        patch(
            "eval_runner.reference.inprocess_backend.InProcessExecutionBackend.submit",
            return_value="run_fp_match_123",
        ),
        patch(
            "eval_runner.services.run_summary.RunSummaryService.get_authoritative_verdict",
            return_value="VERIFIED",
        ),
    ):
        res_fp_eval = client.post(
            "/v1/evaluate",
            json={
                "path": str(sc_file),
                "preflight_fingerprint": "test_match_fp",
            },
        )
        assert res_fp_eval.status_code == 200
        assert res_fp_eval.get_json()["status"] == "started"
