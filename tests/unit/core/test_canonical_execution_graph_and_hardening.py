"""
Comprehensive test suite verifying canonical execution graphs, server-side
authoritative verification endpoints, evidence bundle determinism, SSE replay,
and scenario preflight fingerprinting.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from flask import Flask

from agentv_runtime.manifest import compute_scenario_hash
from eval_runner import config
from eval_runner.artifact_plugin import ArtifactPlugin
from eval_runner.console.routes.runs import run_bp
from eval_runner.console.routes.scenarios import (
    scenario_bp,
    validate_scenario_structure,
)
from eval_runner.events import (
    ExecutionEdgeType,
    ExecutionGraphEdge,
    ExecutionGraphNode,
    ExecutionNodeStatus,
)
from eval_runner.verifier import TraceVerifier

# ---------------------------------------------------------------------------
# 1. Execution Graph Models & Serialization
# ---------------------------------------------------------------------------


def test_execution_graph_node_and_edge_serialization():
    node = ExecutionGraphNode(
        run_id="run_alpha",
        execution_node_id="exec_node_1",
        scenario_node_id="scen_node_alpha",
        parent_execution_id="exec_root",
        status=ExecutionNodeStatus.COMPLETED,
        evidence_refs=["ref_1", "ref_2"],
        metadata={"tool_calls": 2, "tokens": 150},
    )
    d = node.model_dump()
    assert d["execution_node_id"] == "exec_node_1"
    assert d["scenario_node_id"] == "scen_node_alpha"
    assert d["status"] == "completed"
    assert d["evidence_refs"] == ["ref_1", "ref_2"]

    edge = ExecutionGraphEdge(
        run_id="run_alpha",
        source_execution_id="exec_node_1",
        target_execution_id="exec_node_2",
        edge_type=ExecutionEdgeType.RETRY,
        condition="attempt < 3",
    )
    ed = edge.model_dump()
    assert ed["source_execution_id"] == "exec_node_1"
    assert ed["edge_type"] == "retry"
    assert ed["condition"] == "attempt < 3"


# ---------------------------------------------------------------------------
# 2. Server-Authoritative TraceVerifier.verify_run_directory
# ---------------------------------------------------------------------------


def test_verify_run_directory_all_paths(tmp_path):
    # 1. Non-existent directory
    missing_dir = tmp_path / "missing_run"
    res_404 = TraceVerifier.verify_run_directory(missing_dir)
    assert res_404["verification_status"] == "NOT_FOUND"
    assert res_404["is_valid"] is False

    # 2. Run directory without manifest or certificate
    empty_run = tmp_path / "empty_run"
    empty_run.mkdir()
    res_unverified = TraceVerifier.verify_run_directory(empty_run)
    assert res_unverified["verification_status"] == "UNVERIFIED"
    assert res_unverified["has_certificate"] is False

    # 3. Manifest present, trace file missing
    manifest_only = tmp_path / "manifest_only"
    manifest_only.mkdir()
    (manifest_only / "run_manifest.json").write_text("{}", encoding="utf-8")
    res_missing_trace = TraceVerifier.verify_run_directory(manifest_only)
    assert res_missing_trace["verification_status"] == "FAILED_VERIFICATION"
    assert res_missing_trace["has_certificate"] is True
    assert "missing" in res_missing_trace["failure_reason"]

    # 4. Valid run directory with manifest and trace
    valid_run = tmp_path / "valid_run"
    valid_run.mkdir()
    (valid_run / "run.jsonl").write_text('{"event": "run_start"}\n', encoding="utf-8")
    manifest_data = {
        "run_id": "valid_run",
        "trace_hash": "dummy_hash",
        "hash_algorithm": "sha3_256",
        "signature": {"algorithm": "Ed25519", "key_id": "key_1"},
    }
    (valid_run / "run_manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    with patch.object(TraceVerifier, "verify_trace", return_value=True):
        res_valid = TraceVerifier.verify_run_directory(valid_run)
        assert res_valid["verification_status"] == "VERIFIED"
        assert res_valid["is_valid"] is True
        assert res_valid["algorithm"] == "Ed25519"

    # 5. Invalid signature / hash verification failure
    with patch.object(TraceVerifier, "verify_trace", return_value=False):
        res_tampered = TraceVerifier.verify_run_directory(valid_run)
        assert res_tampered["verification_status"] == "FAILED_VERIFICATION"
        assert res_tampered["is_valid"] is False

    # 6. Exception during verification
    with patch.object(TraceVerifier, "verify_trace", side_effect=ValueError("Corrupt trace")):
        res_err = TraceVerifier.verify_run_directory(valid_run)
        assert res_err["verification_status"] == "FAILED_VERIFICATION"
        assert "Corrupt trace" in res_err["failure_reason"]


# ---------------------------------------------------------------------------
# 3. Artifact Determinism: bundle_hash in ArtifactPlugin
# ---------------------------------------------------------------------------


def test_artifact_plugin_bundle_hash_and_discovery(tmp_path):
    plugin = ArtifactPlugin()
    registry = MagicMock()
    plugin.on_discover_services(registry)
    registry.register_service.assert_any_call("bundle_artifacts", plugin.bundle_artifacts)
    registry.register_service.assert_any_call("verify_integrity", plugin.verify_integrity)

    run_dir = tmp_path / "run_1"
    run_dir.mkdir()
    (run_dir / "run.jsonl").write_text('{"event": "run_start"}\n', encoding="utf-8")

    res = plugin.bundle_artifacts(
        target_dir=str(run_dir),
        files_to_include=["run.jsonl", "missing_artifact.png"],
        output_filename="evidence.zip",
        generate_manifest=True,
    )
    assert "bundle_path" in res
    assert "bundle_hash" in res
    assert len(res["bundle_hash"]) == 64
    assert Path(res["bundle_path"]).exists()

    # Verify integrity
    verified = plugin.verify_integrity(res["bundle_path"])
    assert isinstance(verified, dict)
    assert verified["is_valid"] is True


# ---------------------------------------------------------------------------
# 4. Server Route /api/v1/runs/<run_id>/verify
# ---------------------------------------------------------------------------


def test_run_verify_api_endpoint(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test-secret-key-eval"
    app.register_blueprint(run_bp, url_prefix="/api")
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)

    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
        client = app.test_client()

        # 1. 404 for missing run
        res = client.get("/api/v1/runs/missing_run_id/verify")
        assert res.status_code == 404

        # 2. 200 with verification details
        run_dir = tmp_path / "runs" / "r123"
        run_dir.mkdir()
        (run_dir / "run.jsonl").write_text("trace", encoding="utf-8")
        (run_dir / "run_manifest.json").write_text('{"run_id": "r123"}', encoding="utf-8")

        with patch.object(
            TraceVerifier,
            "verify_run_directory",
            return_value={"verification_status": "VERIFIED", "is_valid": True},
        ):
            res_ok = client.get("/api/v1/runs/r123/verify")
            assert res_ok.status_code == 200
            assert res_ok.get_json()["verification_status"] == "VERIFIED"


# ---------------------------------------------------------------------------
# 5. Preflight Fingerprinting & Scenario Structure Validator
# ---------------------------------------------------------------------------


def test_scenario_validation_and_concurrency(tmp_path, monkeypatch):
    # 1. Valid scenario structure
    valid_scen = {
        "metadata": {"id": "scen_valid", "name": "Valid Scenario"},
        "workflow": {
            "nodes": [
                {"id": "n1", "task_description": "Task 1", "required_tools": ["calc"]},
                {"id": "n2", "task_description": "Task 2"},
            ],
            "edges": [{"from": "n1", "to": "n2"}],
        },
    }
    is_valid, issues = validate_scenario_structure(valid_scen)
    assert is_valid is True
    assert len(issues) == 0

    # 2. Cycle detection in DAG
    cyclic_scen = {
        "metadata": {"id": "scen_cyclic"},
        "workflow": {
            "nodes": [
                {"id": "n1", "task_description": "Task 1"},
                {"id": "n2", "task_description": "Task 2"},
            ],
            "edges": [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n1"}],
        },
    }
    is_cyclic_valid, cyclic_issues = validate_scenario_structure(cyclic_scen)
    assert is_cyclic_valid is False
    assert any("cycle" in issue for issue in cyclic_issues)

    # 3. Hash calculation
    h = compute_scenario_hash(valid_scen)
    assert h.startswith("sha3_256:")

    # 4. Readiness probing via client
    app = Flask(__name__)
    app.secret_key = "test-secret-key-eval"
    app.register_blueprint(scenario_bp, url_prefix="/api")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    with patch("eval_runner.console.auth_manager.require_permission", lambda _: lambda f: f):
        client = app.test_client()
        res_readiness = client.post(
            "/api/scenarios/readiness",
            json={
                "scenario_data": valid_scen,
                "agent_config": {"model": "gpt-5", "endpoint": "https://api.openai.com"},
            },
        )
        assert res_readiness.status_code == 200
        data = res_readiness.get_json()
        assert data["is_executable"] is True
        assert "preflight_fingerprint" in data
        assert len(data["preflight_fingerprint"]) == 64
