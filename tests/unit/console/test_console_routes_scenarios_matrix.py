"""
Branch coverage matrix for eval_runner/console/routes/scenarios.py.

Statement and branch coverage for scenario catalog endpoints,
schema validation, execution readiness probes, lifecycle state machine,
eval launch, mutation, spec-to-eval, and auto-translate.
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from flask import Flask

from eval_runner import config
from eval_runner.console.routes.scenarios import (
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
    with patch("urllib.request.urlopen") as mock_open:
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

    # 3. save_scenario optimistic concurrency conflict (409)
    good_sc = {
        "id": "sc_concurrency",
        "status": "Draft",
        "workflow": {"nodes": [{"id": "n1", "task_description": "task"}]},
    }
    client.post("/scenarios", json=good_sc)
    res_conflict = client.post(
        "/scenarios",
        json={**good_sc, "expected_revision_hash": "sha3_256:stale_hash_value"},
    )
    assert res_conflict.status_code == 409

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
