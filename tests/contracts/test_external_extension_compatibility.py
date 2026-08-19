"""
tests/contracts/test_external_extension_compatibility.py
Zero-Touch Compatibility Fixture: Simulates an external enterprise / third-party package
implementing all 6 Extension Families and 3 Storage Interfaces via agentv_runtime.interfaces
without accessing internal private implementation details.
"""

from typing import Any

from agentv_runtime.interfaces import (
    ArtifactStore,
    AuthorizationBackend,
    AuthPrincipal,
    CatalogStore,
    CheckpointStore,
    ExecutionBackend,
    LeaderboardStore,
    PolicyEvaluationResult,
    PolicyEvaluator,
    RunStore,
    SigningBackend,
)


class MockExternalExecutionBackend(ExecutionBackend):
    def __init__(self):
        self.submitted = []

    def submit(
        self, run_id: str, scenario_data: dict[str, Any], background: bool = False, **kwargs: Any
    ) -> Any:
        self.submitted.append(run_id)
        return {"status": "submitted", "run_id": run_id}

    def status(self, run_id: str) -> dict[str, Any]:
        return {"status": "RUNNING" if run_id in self.submitted else "NOT_FOUND"}

    def cancel(self, run_id: str, reason: str | None = None) -> bool:
        return run_id in self.submitted

    def resume(self, run_id: str, resumption_token: str | None = None, **kwargs: Any) -> Any:
        return {"status": "RESUMED", "run_id": run_id}


class MockExternalCheckpointStore(CheckpointStore):
    def __init__(self):
        self.checkpoints = {}

    def save(
        self,
        run_id: str,
        checkpoint_id: str,
        state: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self.checkpoints[f"{run_id}:{checkpoint_id}"] = state
        return f"mock://{run_id}/{checkpoint_id}"

    def load(self, run_id: str, checkpoint_id: str | None = None) -> dict[str, Any] | None:
        key = f"{run_id}:{checkpoint_id}" if checkpoint_id else f"{run_id}:latest"
        return self.checkpoints.get(key)

    def delete(self, run_id: str, checkpoint_id: str | None = None) -> bool:
        key = f"{run_id}:{checkpoint_id}"
        return self.checkpoints.pop(key, None) is not None

    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        return [
            {"checkpoint_id": k.split(":")[1]}
            for k in self.checkpoints
            if k.startswith(f"{run_id}:")
        ]


class MockExternalArtifactStore(ArtifactStore):
    def __init__(self):
        self.artifacts = {}

    def store_artifact(
        self,
        run_id: str,
        artifact_name: str,
        content: bytes | str,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self.artifacts[f"{run_id}/{artifact_name}"] = content
        return f"s3://mock-bucket/{run_id}/{artifact_name}"

    def get_artifact(self, run_id: str, artifact_name: str) -> bytes | None:
        val = self.artifacts.get(f"{run_id}/{artifact_name}")
        return val.encode() if isinstance(val, str) else val

    def exists(self, run_id: str, artifact_name: str) -> bool:
        return f"{run_id}/{artifact_name}" in self.artifacts

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        return [{"name": k.split("/")[1]} for k in self.artifacts if k.startswith(f"{run_id}/")]


class MockExternalPolicyEvaluator(PolicyEvaluator):
    def evaluate_policy(
        self, action: str, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> PolicyEvaluationResult:
        if params.get("prohibited"):
            return PolicyEvaluationResult(
                allowed=False,
                policy_id="mock_pol_01",
                reason="Prohibited parameter detected",
            )
        return PolicyEvaluationResult(allowed=True, policy_id="mock_pol_01")

    def validate_policy(self, policy_definition: dict[str, Any]) -> bool:
        return isinstance(policy_definition, dict)


class MockExternalSigningBackend(SigningBackend):
    def sign_payload(self, payload: bytes) -> dict[str, Any]:
        return {"algorithm": "MOCK-DSA", "signature": "mock_sig_hex"}

    def verify_signature(self, payload: bytes, signature_metadata: dict[str, Any]) -> bool:
        return signature_metadata.get("algorithm") == "MOCK-DSA"


class MockExternalAuthorizationBackend(AuthorizationBackend):
    def validate_token(self, token: str) -> AuthPrincipal | None:
        if token == "mock-token":
            return AuthPrincipal(principal_id="enterprise-user", roles=["admin"], permissions=["*"])
        return None

    def check_permission(self, principal: AuthPrincipal, resource: str, action: str = "") -> bool:
        return "admin" in principal.roles


class MockExternalCatalogStore(CatalogStore):
    def __init__(self):
        self.scenarios = {}

    def list_scenarios(self, category: str | None = None) -> list[dict[str, Any]]:
        return list(self.scenarios.values())

    def get_scenario(self, scenario_id: str) -> dict[str, Any] | None:
        return self.scenarios.get(scenario_id)

    def save_scenario(self, scenario_id: str, scenario_data: dict[str, Any]) -> str:
        self.scenarios[scenario_id] = scenario_data
        return f"mock-catalog://{scenario_id}"

    def delete_scenario(self, scenario_id: str) -> bool:
        return self.scenarios.pop(scenario_id, None) is not None


class MockExternalRunStore(RunStore):
    def __init__(self):
        self.runs = {}

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.runs.get(run_id)

    def list_runs(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return list(self.runs.values())[offset : offset + limit]

    def save_run_manifest(self, run_id: str, manifest: dict[str, Any]) -> str:
        self.runs[run_id] = {"run_id": run_id, "manifest": manifest}
        return f"mock-run://{run_id}"

    def delete_run(self, run_id: str) -> bool:
        return self.runs.pop(run_id, None) is not None


class MockExternalLeaderboardStore(LeaderboardStore):
    def __init__(self):
        self.board = []

    def get_leaderboard(self, scenario_id: str | None = None) -> list[dict[str, Any]]:
        return self.board

    def record_run_summary(self, summary: dict[str, Any]) -> None:
        self.board.append(summary)


def test_external_extension_compatibility_contract():
    # 1. ExecutionBackend Contract
    exec_backend = MockExternalExecutionBackend()
    res = exec_backend.submit("run_compat_01", {"id": "scen_1"})
    assert res["status"] == "submitted"
    assert exec_backend.status("run_compat_01")["status"] == "RUNNING"
    assert exec_backend.cancel("run_compat_01") is True
    assert exec_backend.resume("run_compat_01")["status"] == "RESUMED"

    # 2. CheckpointStore Contract
    chk_store = MockExternalCheckpointStore()
    chk_uri = chk_store.save("run_compat_01", "chk_1", {"turn": 1})
    assert "mock://" in chk_uri
    assert len(chk_store.list_checkpoints("run_compat_01")) == 1

    # 3. ArtifactStore Contract
    art_store = MockExternalArtifactStore()
    art_uri = art_store.store_artifact("run_compat_01", "report.json", '{"key": 1}')
    assert "s3://" in art_uri
    assert art_store.exists("run_compat_01", "report.json") is True
    assert art_store.get_artifact("run_compat_01", "report.json") == b'{"key": 1}'

    # 4. PolicyEvaluator Contract
    policy = MockExternalPolicyEvaluator()
    assert policy.validate_policy({"rules": []}) is True
    assert policy.evaluate_policy("exec", {"prohibited": True}).allowed is False
    assert policy.evaluate_policy("exec", {"prohibited": False}).allowed is True

    # 5. SigningBackend Contract
    signing = MockExternalSigningBackend()
    sig_meta = signing.sign_payload(b"data")
    assert signing.verify_signature(b"data", sig_meta) is True

    # 6. AuthorizationBackend Contract
    auth = MockExternalAuthorizationBackend()
    principal = auth.validate_token("mock-token")
    assert principal is not None
    assert auth.check_permission(principal, "runs", "delete") is True

    # 7. CatalogStore Contract
    cat = MockExternalCatalogStore()
    cat.save_scenario("scen_ext", {"id": "scen_ext", "name": "External Scenario"})
    assert cat.get_scenario("scen_ext")["name"] == "External Scenario"
    assert len(cat.list_scenarios()) == 1
    assert cat.delete_scenario("scen_ext") is True

    # 8. RunStore Contract
    r_store = MockExternalRunStore()
    r_store.save_run_manifest("run_ext", {"status": "SUCCESS"})
    assert r_store.get_run("run_ext")["manifest"]["status"] == "SUCCESS"
    assert len(r_store.list_runs()) == 1
    assert r_store.delete_run("run_ext") is True

    # 9. LeaderboardStore Contract
    lb_store = MockExternalLeaderboardStore()
    lb_store.record_run_summary({"run_id": "run_ext", "score": 98.5})
    assert len(lb_store.get_leaderboard()) == 1
