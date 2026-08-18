"""
tests/unit/core/test_reference_implementations.py

Comprehensive test suite verifying 100% branch and statement coverage across all
reference implementations under `eval_runner/reference/`:
- `LocalEd25519SigningBackend`, `NullSigningBackend`, `PQCSigningBackend`
- `SimpleAPIKeyAuthBackend`
- `BasicFieldPolicyEvaluator`
- `InProcessExecutionBackend`
- `LocalFileCatalogStore`
- `LocalFileRunStore`
- `LocalLeaderboardStore`
- `SQLiteCheckpointStore`
- `LocalFileArtifactStore`
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa

from eval_runner import config
from eval_runner.identity import IdentityService
from eval_runner.reference.auth import SimpleAPIKeyAuthBackend
from eval_runner.reference.field_policy import BasicFieldPolicyEvaluator
from eval_runner.reference.inprocess_backend import InProcessExecutionBackend
from eval_runner.reference.local_artifact import LocalFileArtifactStore
from eval_runner.reference.local_catalog import LocalFileCatalogStore
from eval_runner.reference.local_leaderboard import LocalLeaderboardStore
from eval_runner.reference.local_run_store import LocalFileRunStore
from eval_runner.reference.signing import (
    LocalEd25519SigningBackend,
    NullSigningBackend,
    PQCSigningBackend,
)
from eval_runner.reference.sqlite_checkpoint import SQLiteCheckpointStore

# ==============================================================================
# 1. SigningBackend Reference Implementations (Classical & PQC)
# ==============================================================================


class TestSigningReferenceImplementations:
    """Tests for LocalEd25519SigningBackend, NullSigningBackend, and PQCSigningBackend."""

    def test_null_signing_backend(self):
        backend = NullSigningBackend()
        assert backend.sign_payload(b"data", "key_id") == ""
        assert backend.verify_signature(b"data", "sig", "key_id") is False

    def test_ed25519_signing_and_verification_full_lifecycle(self, tmp_path):
        priv_key = ed25519.Ed25519PrivateKey.generate()
        priv_pem = priv_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub_key = priv_key.public_key()
        pub_pem = pub_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        key_file = tmp_path / "priv.pem"
        key_file.write_bytes(priv_pem)
        pub_file = tmp_path / "pub.pem"
        pub_file.write_bytes(pub_pem)

        backend = LocalEd25519SigningBackend()
        payload = b'{"eval":"success","score":1.0}'

        # 1. Sign using Path, str path, raw str, and raw bytes
        sig1 = backend.sign_payload(payload, key_file)
        sig2 = backend.sign_payload(payload, str(key_file))
        sig3 = backend.sign_payload(payload, priv_pem.decode("utf-8"))
        sig4 = backend.sign_payload(payload, priv_pem)

        assert sig1 == sig2 == sig3 == sig4
        assert len(sig1) == 128

        # 2. Verify using Path file, str path, raw str, raw bytes
        assert backend.verify_signature(payload, sig1, pub_file) is True
        assert backend.verify_signature(payload, sig1, str(pub_file)) is True
        assert backend.verify_signature(payload, sig1, pub_pem.decode("utf-8")) is True
        assert backend.verify_signature(payload, sig1, pub_pem) is True

        # 3. Tampered payload
        assert backend.verify_signature(b'{"eval":"tampered"}', sig1, pub_file) is False

        # 4. Invalid hex signature
        assert backend.verify_signature(payload, "invalid_hex_string", pub_file) is False

    def test_ed25519_invalid_key_types_and_errors(self, tmp_path):
        backend = LocalEd25519SigningBackend()

        # Non-existent file
        with pytest.raises(FileNotFoundError):
            backend.sign_payload(b"test", tmp_path / "missing_key.pem")

        # Invalid type for key_identifier
        with pytest.raises(TypeError, match="Expected file path"):
            backend.sign_payload(b"test", 12345)

        # RSA key instead of Ed25519
        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        rsa_pem = rsa_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        rsa_file = tmp_path / "rsa.pem"
        rsa_file.write_bytes(rsa_pem)

        with pytest.raises(TypeError, match="Expected Ed25519PrivateKey"):
            backend.sign_payload(b"test", rsa_file)

        # Invalid public key during verification
        rsa_pub_pem = rsa_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        assert backend.verify_signature(b"test", "ab" * 64, rsa_pub_pem) is False
        assert backend.verify_signature(b"test", "ab" * 64, b"invalid_pem_bytes") is False

    def test_pqc_signing_backend(self, monkeypatch):
        backend = PQCSigningBackend()
        payload = b'{"quantum":"safe"}'

        # 1. PQC disabled -> RuntimeError
        monkeypatch.setattr(config, "PQC_ENABLED", False)
        IdentityService._pqc_client = None
        with pytest.raises(RuntimeError, match="PQC client is not available"):
            backend.sign_payload(payload)

        # Verify returns False when PQC disabled (or raises if STRICT)
        monkeypatch.setattr(config, "PQC_STRICT_MODE", False)
        assert backend.verify_signature(payload, "sig_hex") is False

        monkeypatch.setattr(config, "PQC_STRICT_MODE", True)
        with pytest.raises(ValueError, match="PQC_STRICT_MODE"):
            backend.verify_signature(payload, "sig_hex")

        # 2. PQC enabled with mock client
        monkeypatch.setattr(config, "PQC_ENABLED", True)
        mock_client = MagicMock()
        mock_client.sign_digest.return_value = "pqc_signature_hex_999"
        mock_client.verify_digest.return_value = True
        monkeypatch.setattr(IdentityService, "_pqc_client", mock_client)

        sig = backend.sign_payload(payload, key_identifier="sys_pqc")
        assert sig == "pqc_signature_hex_999"
        assert mock_client.sign_digest.called

        assert backend.verify_signature(payload, sig, public_key_identifier="sys_pqc") is True
        assert mock_client.verify_digest.called


# ==============================================================================
# 2. AuthorizationBackend Reference Implementation
# ==============================================================================


class TestAuthReferenceImplementation:
    """Tests for SimpleAPIKeyAuthBackend."""

    def test_auth_backend_full_lifecycle(self, monkeypatch):
        monkeypatch.setenv("EVAL_MASTER_KEY", "env-master-key-999")
        backend = SimpleAPIKeyAuthBackend()

        # 1. Master key authentication
        master_principal = backend.validate_token("env-master-key-999")
        assert master_principal is not None
        assert master_principal.principal_id == "root-admin"
        assert backend.check_permission(master_principal, "scenarios", "write") is True
        assert backend.check_permission(master_principal, "scenarios:write") is True
        assert backend.check_permission(master_principal, "any:other:node") is True

        # 2. Register custom key
        backend.register_key(
            key="auditor-key-001",
            principal_id="auditor-jane",
            roles=["auditor"],
            permissions=["scenarios:read", "runs:*"],
            metadata={"department": "compliance"},
        )

        principal = backend.validate_token("auditor-key-001")
        assert principal is not None
        assert principal.principal_id == "auditor-jane"

        # Check permissions including wildcard matching
        assert backend.check_permission(principal, "scenarios", "read") is True
        assert backend.check_permission(principal, "scenarios:read") is True
        assert backend.check_permission(principal, "runs", "read") is True
        assert backend.check_permission(principal, "runs", "delete") is True
        assert backend.check_permission(principal, "scenarios", "write") is False

        # 3. None / invalid token
        assert backend.validate_token("") is None
        assert backend.validate_token(None) is None
        assert backend.validate_token("non-existent-token") is None
        assert backend.check_permission(None, "scenarios", "read") is False

        # 4. List keys & Revoke key
        keys = backend.list_keys()
        assert "auditor-key-001" in keys
        assert backend.revoke_key("auditor-key-001") is True
        assert backend.revoke_key("non-existent-token") is False
        assert backend.validate_token("auditor-key-001") is None


# ==============================================================================
# 3. PolicyEvaluator Reference Implementation
# ==============================================================================


class TestPolicyEvaluatorReferenceImplementation:
    """Tests for BasicFieldPolicyEvaluator."""

    def test_field_policy_evaluator_limits_and_constraints(self):
        evaluator = BasicFieldPolicyEvaluator()

        # 1. Constrained params (list)
        spec = {"max_limit": 500, "constrained_params": ["transfer_amt", "fee"]}
        res1 = evaluator.evaluate_policy(spec, {"transfer_amt": 400, "fee": 50})
        assert res1.allowed is True

        res2 = evaluator.evaluate_policy(spec, {"transfer_amt": 600, "fee": 50})
        assert res2.allowed is False
        assert len(res2.violations) == 1
        assert res2.violations[0]["field"] == "transfer_amt"

        # 2. Constrained params (single string)
        spec_str = {"max_limit": 100, "constrained_params": "single_param"}
        res3 = evaluator.evaluate_policy(spec_str, {"single_param": 150})
        assert res3.allowed is False

        # 3. Param key in spec
        spec_param = {"max_limit": 100, "param_key": "amount"}
        res_p = evaluator.evaluate_policy(spec_param, {"amount": 150})
        assert res_p.allowed is False
        assert res_p.violations[0]["field"] == "amount"

        # 4. Target field
        spec_target = {"max_limit": 200, "target_field": "withdrawal"}
        res4 = evaluator.evaluate_policy(spec_target, {"withdrawal": 250})
        assert res4.allowed is False
        assert res4.violations[0]["field"] == "withdrawal"

        # 5. Fallback all fields
        spec_all = {"max_limit": 50}
        res5 = evaluator.evaluate_policy(spec_all, {"a": 10, "b": 60, "text": "not-a-number"})
        assert res5.allowed is False
        assert res5.violations[0]["field"] == "b"

    def test_field_policy_required_fields_and_allowed_values(self):
        evaluator = BasicFieldPolicyEvaluator()

        # Required fields
        spec_req = {"required_fields": ["user_id", "email"]}
        res_ok = evaluator.evaluate_policy(spec_req, {"user_id": "u1", "email": "a@b.com"})
        assert res_ok.allowed is True

        res_miss = evaluator.evaluate_policy(spec_req, {"user_id": "u1"})
        assert res_miss.allowed is False
        assert len(res_miss.violations) == 1
        assert res_miss.violations[0]["field"] == "email"

    def test_field_policy_validation(self):
        evaluator = BasicFieldPolicyEvaluator()

        assert evaluator.validate_policy({"max_limit": 100}) is True
        assert evaluator.validate_policy({"required_fields": ["id"]}) is True
        assert evaluator.validate_policy("not_a_dict") is False
        assert evaluator.validate_policy({"max_limit": "not_a_number"}) is False
        assert evaluator.validate_policy({"required_fields": "not_a_list"}) is False


# ==============================================================================
# 4. ExecutionBackend Reference Implementation
# ==============================================================================


class TestInProcessExecutionBackend:
    """Tests for InProcessExecutionBackend."""

    def test_inprocess_execution_lifecycle_and_error_handling(self):
        backend = InProcessExecutionBackend()
        run_id = "test-inprocess-exec-run"

        scenario = {
            "id": "mock_exec_scenario",
            "workflow": {
                "nodes": [
                    {
                        "id": "task_1",
                        "type": "task",
                        "tool": "mock_tool",
                        "params": {"q": "ping"},
                    }
                ]
            },
            "tools": {"mock_tool": {"output": {"status": "success", "msg": "pong"}}},
        }

        # Submit synchronously
        res = backend.submit(run_id=run_id, scenario_data=scenario, background=False)
        assert res is not None

        st = backend.status(run_id)
        assert st["status"] == "COMPLETED"

        # Unknown status
        assert backend.status("non_existent_run_id")["status"] == "UNKNOWN"

        # Cancel
        assert backend.cancel(run_id, reason="User requested abort") is True
        assert backend.status(run_id)["status"] == "ABORTED"
        assert backend.cancel("non_existent_run_id") is False

        # Resume
        resumed = backend.resume(run_id, resumption_token="tok_abc_123")
        assert resumed is not None
        assert resumed["status"] == "RUNNING"
        assert backend.resume("non_existent_run_id") is None

    def test_inprocess_execution_exception_propagation(self, monkeypatch):
        backend = InProcessExecutionBackend()
        run_id = "test-fail-run"
        scenario = {"id": "test_scenario"}

        import eval_runner.runner as runner

        def mock_failing_runner(*args, **kwargs):
            raise RuntimeError("Injected runner execution crash")

        monkeypatch.setattr(runner, "run_scenario", mock_failing_runner)

        with pytest.raises(RuntimeError, match="Injected runner execution crash"):
            backend.submit(run_id=run_id, scenario_data=scenario, background=False)

        st = backend.status(run_id)
        assert st["status"] == "FAILED"
        assert "Injected runner execution crash" in st["error"]


# ==============================================================================
# 5. CatalogStore Reference Implementation
# ==============================================================================


class TestCatalogStoreReferenceImplementation:
    """Tests for LocalFileCatalogStore."""

    def test_catalog_store_crud_and_discovery(self, tmp_path, monkeypatch):
        catalog = LocalFileCatalogStore(base_dir=tmp_path)

        # 1. Save scenarios (JSON & YAML)
        catalog.save_scenario(
            "wire_transfer",
            {"id": "wire_transfer", "title": "Wire Transfer"},
        )
        yaml_path = tmp_path / "scenarios" / "jailbreak.yaml"
        yaml_path.write_text("id: jailbreak\ntitle: Jailbreak Test\n", encoding="utf-8")

        # 2. Get scenario
        scen = catalog.get_scenario("wire_transfer")
        assert scen is not None
        assert scen["id"] == "wire_transfer"

        scen_yaml = catalog.get_scenario("jailbreak")
        assert scen_yaml is not None
        assert scen_yaml["id"] == "jailbreak"

        assert catalog.get_scenario("non_existent") is None

        # 3. List scenarios with and without category filtering
        all_scenarios = catalog.list_scenarios()
        assert len(all_scenarios) == 2

        filtered = catalog.list_scenarios(category="wire")
        assert len(filtered) == 1
        assert filtered[0]["id"] == "wire_transfer"

        # 4. Path traversal safety violation
        monkeypatch.setenv("AEH_STRICT_JAIL", "1")
        with pytest.raises(PermissionError, match="outside allowed boundary"):
            catalog.save_scenario("../../outside", {"id": "outside"})

        # 5. Corrupted scenario file
        bad_path = tmp_path / "scenarios" / "bad.json"
        bad_path.write_text("{corrupted_json", encoding="utf-8")
        assert catalog.get_scenario("bad") is None

        # 6. Delete scenario
        assert catalog.delete_scenario("wire_transfer") is True
        assert catalog.delete_scenario("wire_transfer") is False
        assert catalog.get_scenario("wire_transfer") is None


# ==============================================================================
# 6. RunStore Reference Implementation
# ==============================================================================


class TestRunStoreReferenceImplementation:
    """Tests for LocalFileRunStore."""

    def test_run_store_crud_and_status(self, tmp_path):
        run_store = LocalFileRunStore(log_dir=tmp_path)

        # 1. Save manifest
        manifest = {
            "run_id": "run-001",
            "scenario": "test_scenario",
            "status": "PASSED",
            "score": 0.95,
        }
        saved_path = run_store.save_run_manifest("run-001", manifest)
        assert Path(saved_path).exists()

        # 2. Get run with valid and corrupted manifest
        run_data = run_store.get_run("run-001")
        assert run_data is not None
        assert run_data["manifest"]["status"] == "PASSED"
        assert run_store.get_run("non_existent_run") is None

        corrupted_vault = tmp_path / "run-corrupted"
        corrupted_vault.mkdir()
        (corrupted_vault / "run_manifest.json").write_text("{bad_json")
        corrupted_run = run_store.get_run("run-corrupted")
        assert corrupted_run is not None
        assert corrupted_run["manifest"] == {}

        # 3. List runs
        runs = run_store.list_runs()
        assert len(runs) == 2

        # 4. Empty / non-existent log_dir
        empty_store = LocalFileRunStore(log_dir=tmp_path / "non_existent_sub")
        assert empty_store.list_runs() == []

        # 5. Delete run
        assert run_store.delete_run("run-001") is True
        assert run_store.delete_run("run-001") is False
        assert run_store.get_run("run-001") is None


# ==============================================================================
# 7. LeaderboardStore Reference Implementation
# ==============================================================================


class TestLeaderboardStoreReferenceImplementation:
    """Tests for LocalLeaderboardStore."""

    def test_leaderboard_store_aggregation(self, tmp_path):
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        # Setup 2 runs with valid run.jsonl traces and manifests
        run1_dir = runs_dir / "run-101"
        run1_dir.mkdir()
        (run1_dir / "run.jsonl").write_text(
            '{"event":"run_start","metadata":{"agent_name":"Agent-Alpha"}}\n'
            '{"event":"evaluation","task_id":"t1","success":true}\n'
        )
        (run1_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "run_id": "run-101",
                    "metadata": {"agent_name": "Agent-Alpha"},
                }
            )
        )

        run2_dir = runs_dir / "run-102"
        run2_dir.mkdir()
        (run2_dir / "run.jsonl").write_text(
            '{"event":"run_start","metadata":{"agent_name":"Agent-Beta"}}\n'
            '{"event":"evaluation","task_id":"t1","success":true}\n'
        )
        (run2_dir / "run_manifest.json").write_text(
            json.dumps(
                {
                    "run_id": "run-102",
                    "metadata": {"agent_name": "Agent-Beta"},
                }
            )
        )

        lb_store = LocalLeaderboardStore(runs_dir=runs_dir)
        leaderboard = lb_store.get_leaderboard()

        assert len(leaderboard) == 2
        agent_names = [row["agent"] for row in leaderboard]
        assert "Agent-Alpha" in agent_names
        assert "Agent-Beta" in agent_names

        # Filter by agent
        filtered = lb_store.get_leaderboard(filters={"agent": "Alpha"})
        assert len(filtered) == 1
        assert filtered[0]["agent"] == "Agent-Alpha"

        # Record run summary
        lb_store.record_run_summary("run-103", {"agent": "Agent-Gamma"})


# ==============================================================================
# 8. SQLiteCheckpointStore Reference Implementation
# ==============================================================================


class TestSQLiteCheckpointStore:
    """Tests for SQLiteCheckpointStore."""

    def test_sqlite_checkpoint_store_full_lifecycle(self, tmp_path):
        db_path = str(tmp_path / "checkpoints.db")
        store = SQLiteCheckpointStore(db_path=db_path)

        state_1 = {"turn": 1, "messages": ["hello"]}
        state_2 = {"turn": 2, "messages": ["hello", "how can I help?"]}

        # 1. Save checkpoints
        chk1_id = store.save("run-chk-001", "chk_001", state_1, metadata={"step": "greeting"})
        chk2_id = store.save("run-chk-001", "chk_002", state_2, metadata={"step": "response"})

        assert chk1_id.endswith("chk_001")
        assert chk2_id.endswith("chk_002")

        # 2. Load latest checkpoint
        latest = store.load("run-chk-001")
        assert latest is not None
        assert latest["turn"] == 2

        # 3. Load specific checkpoint by ID
        first = store.load("run-chk-001", checkpoint_id="chk_001")
        assert first is not None
        assert first["turn"] == 1

        # 4. List checkpoints
        chk_list = store.list_checkpoints("run-chk-001")
        assert len(chk_list) == 2

        # 5. Delete specific checkpoint
        assert store.delete("run-chk-001", checkpoint_id="chk_001") is True
        assert len(store.list_checkpoints("run-chk-001")) == 1

        # 6. Delete all checkpoints for run
        assert store.delete("run-chk-001") is True
        assert len(store.list_checkpoints("run-chk-001")) == 0
        assert store.load("run-chk-001") is None

    def test_sqlite_checkpoint_store_default_constructor(self):
        store = SQLiteCheckpointStore()
        assert store.db_path is not None


# ==============================================================================
# 9. LocalFileArtifactStore Reference Implementation
# ==============================================================================


class TestLocalFileArtifactStore:
    """Tests for LocalFileArtifactStore."""

    def test_artifact_store_crud_and_existence(self, tmp_path):
        store = LocalFileArtifactStore(base_dir=str(tmp_path))
        run_id = "run-art-001"

        # 1. Store text and bytes artifacts
        p_txt = store.store_artifact(
            run_id, "notes.txt", "Plain text notes", metadata={"author": "alice"}
        )
        p_bin = store.store_artifact(run_id, "data.bin", b"\x00\x01\x02\x03")

        assert Path(p_txt).exists()
        assert Path(p_bin).exists()

        # 2. Check existence
        assert store.exists(run_id, "notes.txt") is True
        assert store.exists(run_id, "non_existent.txt") is False

        # 3. Retrieve artifacts
        assert store.get_artifact(run_id, "notes.txt") == b"Plain text notes"
        assert store.get_artifact(run_id, "data.bin") == b"\x00\x01\x02\x03"
        assert store.get_artifact(run_id, "non_existent.txt") is None

        # 4. List artifacts (including non-existent directory)
        artifacts = store.list_artifacts(run_id)
        assert len(artifacts) == 2
        art_names = [a["name"] for a in artifacts]
        assert "notes.txt" in art_names
        assert "data.bin" in art_names

        assert store.list_artifacts("non_existent_run_dir") == []
