import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner import config, doctor, identity, mutator
from eval_runner.handlers import analysis, environment, evaluation, scenarios


@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path / "runs")
    monkeypatch.setattr(config, "TRUST_ROOT", tmp_path / "identities")
    (tmp_path / "runs").mkdir()
    (tmp_path / "identities").mkdir()
    return tmp_path


# --- doctor.py Coverage ---


@pytest.mark.asyncio
async def test_doctor_agent_reachable_fail():
    # Trigger exception in aiohttp
    with patch("aiohttp.ClientSession.post", side_effect=Exception("Network Error")):
        assert await doctor.check_agent_reachable("http://invalid") is False


def test_doctor_security_health_matrix(monkeypatch, capsys):
    # 1. No keys
    monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)
    monkeypatch.delenv("SERVICE_API_KEY", raising=False)
    doctor.check_security_health()
    out = capsys.readouterr().out
    assert "DASHBOARD_API_KEY is not set" in out
    assert "SERVICE_API_KEY is not set" in out

    # 2. Weak key + Defaulting service key
    monkeypatch.setenv("DASHBOARD_API_KEY", "weak")
    doctor.check_security_health()
    out = capsys.readouterr().out
    assert "DASHBOARD_API_KEY is weak" in out
    assert "SERVICE_API_KEY is defaulting to DASHBOARD_API_KEY" in out

    # 3. Strong key + Specific service key + Auth error
    monkeypatch.setenv("DASHBOARD_API_KEY", "very_strong_key_32_chars_long_long")
    monkeypatch.setenv("SERVICE_API_KEY", "service_key")
    with patch(
        "eval_runner.console.auth_manager.get_auth_provider", side_effect=Exception("Auth Fail")
    ):
        doctor.check_security_health()
    out = capsys.readouterr().out
    assert "DASHBOARD_API_KEY is configured" in out
    assert "SERVICE_API_KEY is configured" in out
    assert "Auth Provider Error: Auth Fail" in out


def test_doctor_registry_report_edge_cases(monkeypatch, capsys, mock_config):
    # 1. Empty shims
    with patch(
        "eval_runner.config.RegistryManager.get_resolved_registry", return_value={"shims": {}}
    ):
        doctor.show_registry_report()
    assert "Registry is empty" in capsys.readouterr().out

    # 2. Extension dir resolution error
    with (
        patch(
            "eval_runner.config.RegistryManager.get_resolved_registry",
            return_value={"shims": {"test": {"resources": {"r1": {}}}}},
        ),
        patch("eval_runner.config.SHIM_RESOURCES_D_DIR") as mock_d,
    ):
        mock_d.exists.return_value = True
        mock_d.relative_to.side_effect = ValueError("Out of root")
        mock_d.name = "ext_dir"
        doctor.show_registry_report()
    out = capsys.readouterr().out
    assert "Shim 'test': [r1]" in out
    assert "[Extensions] ext_dir/" in out

    # 3. Top level error
    with patch(
        "eval_runner.config.RegistryManager.get_resolved_registry",
        side_effect=Exception("Registry Crash"),
    ):
        doctor.show_registry_report()
    assert "Registry Diagnostic Error: Registry Crash" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_run_doctor_comprehensive(monkeypatch, capsys, mock_config):
    # Mocking dependencies
    original_import = __builtins__["__import__"]

    def mock_import(name, *args, **kwargs):
        if name == "flask":
            raise ImportError("Missing Flask")
        return original_import(name, *args, **kwargs)

    # sys.version_info must have major, minor, micro
    from collections import namedtuple

    VersionInfo = namedtuple("VersionInfo", ["major", "minor", "micro"])
    mock_ver = VersionInfo(3, 10, 0)

    with (
        patch("builtins.__import__", side_effect=mock_import),
        patch("sys.version_info", mock_ver),
        patch("eval_runner.doctor.check_agent_reachable", return_value=False),
    ):
        await doctor.run_doctor(show_registry=True)

    out = capsys.readouterr().out
    assert "Python version 3.10.0 is too old" in out
    assert "Dependency 'flask' missing" in out
    assert "Agent endpoint unreachable" in out


# --- identity.py Coverage ---


def test_identity_security_cage_violation(mock_config):
    # Path traversal attempt
    with pytest.raises(PermissionError, match="outside trust root"):
        identity.IdentityService.get_private_key("../secret")


def test_identity_load_failure(mock_config):
    # Corrupt PEM
    id_dir = mock_config / "identities" / "corrupt"
    id_dir.mkdir()
    (id_dir / "private_key.pem").write_text("NOT_A_PEM")
    with pytest.raises(ValueError):  # Specific error for garbage PEM
        identity.IdentityService.get_private_key("corrupt")


def test_identity_auto_provision_compliance(mock_config, monkeypatch):
    # Block system_id provisioning
    monkeypatch.setattr(config, "ALLOW_SYSTEM_IDENTITY_PROVISIONING", False)
    with pytest.raises(PermissionError, match="Auto-provisioning for 'system_id' is disabled"):
        identity.IdentityService.get_private_key("system_id")

    # auto_provision=False
    assert identity.IdentityService.get_private_key("missing", auto_provision=False) is None


def test_identity_public_key_fallbacks(mock_config):
    # 1. Derivation failure
    id_dir = mock_config / "identities" / "no_priv"
    id_dir.mkdir()
    # (id_dir / "private_key.pem") is missing
    assert identity.IdentityService.get_public_key("no_priv", auto_provision=False) is None

    # 2. Corrupt public PEM
    id_dir = mock_config / "identities" / "bad_pub"
    id_dir.mkdir()
    (id_dir / "public_key.pem").write_text("BAD_PUB")
    with pytest.raises(ValueError):  # Specific error for garbage PEM
        identity.IdentityService.get_public_key("bad_pub", auto_provision=False)


# --- mutator.py Coverage ---


def test_mutator_typos_edge_cases():
    assert mutator.mutate_text_with_typos("") == ""

    # Force 'delete' branch
    with patch("random.random", return_value=0.01), patch("random.choice", return_value="delete"):
        # Since it deletes everything, it might return empty or hit the 'not mutated' branch
        res = mutator.mutate_text_with_typos("abc", probability=1.0)
        # delete abc -> mutated=True, result=[] -> returns ""
        assert res == ""

    # Test small string guaranteed mutation (1 char)
    # mutated=False branch
    with patch("random.random", return_value=0.5):  # no mutation in loop
        # char 'a' -> mutated=False -> idx=0 -> len(chars)=1 -> return ""
        assert mutator.mutate_text_with_typos("a", probability=0.1) == ""

    # Test swap logic for 2 chars
    with patch("random.random", return_value=0.5):
        # 'ab' -> mutated=False -> idx=0 -> len(chars)=2 -> swap(idx, idx+1) -> 'ba'
        # Force idx=0 for swap logic
        with patch("random.randint", return_value=0):
            assert mutator.mutate_text_with_typos("ab", probability=0.1) == "ba"


def test_mutator_scenario_id_metadata(mock_config):
    scenario = {
        "id": "s1",
        "metadata": {"id": "m1"},
        "workflow": {"nodes": [{"task_description": "test"}]},
    }
    mutated = mutator.mutate_scenario(scenario, "typos")
    assert mutated["id"].endswith("_mutated_typos")
    assert mutated["metadata"]["id"].endswith("_mutated_typos")


# --- Handlers Coverage ---


@pytest.mark.asyncio
async def test_handler_analysis_errors(mock_config):
    args = MagicMock(run_id=None)
    # Missing run_id
    assert await analysis.handle_report(args) == 1
    assert await analysis.handle_explain(args) == 1
    assert await analysis.handle_calibrate(args) == 1

    # Exceptions
    with patch(
        "eval_runner.handlers.evaluation._resolve_replay_trace", side_effect=Exception("Crash")
    ):
        assert await analysis.handle_report(MagicMock(run_id="r1")) == 1
        assert await analysis.handle_explain(MagicMock(run_id="r1")) == 1
        assert await analysis.handle_calibrate(MagicMock(run_id="r1")) == 1

    with patch("eval_runner.leaderboard_generator.run_leaderboard", side_effect=Exception("Crash")):
        assert await analysis.handle_leaderboard(args) == 1

    # To trigger exception in handle_taxonomy, patch something inside the try block
    class CrashOnIter:
        def __iter__(self):
            raise Exception("Iter Crash")

    with patch("eval_runner.taxonomy.CATEGORIES", CrashOnIter()):
        assert await analysis.handle_taxonomy(args) == 1

    with patch("eval_runner.metrics.MetricRegistry.list_metrics", side_effect=Exception("Crash")):
        assert await analysis.handle_list_metrics(args) == 1


@pytest.mark.asyncio
async def test_handler_environment_expansion(mock_config, monkeypatch):
    monkeypatch.chdir(mock_config)  # Crucial for detect_framework()

    # list_industries exception
    with patch("eval_runner.registry_sync.load_registry", side_effect=Exception("Crash")):
        industries = environment.list_industries()
        assert "finance" in industries  # mapping fallback

    # detect_framework signals
    (mock_config / "crew.py").write_text("")
    assert environment.detect_framework() == "CrewAI"
    (mock_config / "crew.py").unlink()

    (mock_config / "conversable_agent.py").write_text("")
    assert environment.detect_framework() == "AutoGen"
    (mock_config / "conversable_agent.py").unlink()

    # requirements.txt
    req = mock_config / "requirements.txt"
    req.write_text("langgraph")
    assert environment.detect_framework() == "LangGraph"
    req.write_text("crewai")
    assert environment.detect_framework() == "CrewAI"
    req.write_text("pyautogen")
    assert environment.detect_framework() == "AutoGen"
    req.write_text("langchain")
    assert environment.detect_framework() == "LangChain"

    # parse error
    with patch("pathlib.Path.read_text", side_effect=Exception("Read Error")):
        # Should debug log and continue to path signals
        assert environment.detect_framework() == "Custom"

    # path signals
    (mock_config / "libs" / "langchain").mkdir(parents=True)
    assert environment.detect_framework() == "LangChain"


@pytest.mark.asyncio
async def test_handler_evaluation_expansion(mock_config, monkeypatch):
    # _ensure_path_safe
    assert evaluation._ensure_path_safe(mock_config / "safe") is True
    assert evaluation._ensure_path_safe("/unsafe") is False

    # _resolve_replay_trace
    assert evaluation._resolve_replay_trace("") is None
    assert evaluation._resolve_replay_trace("../unsafe") is None
    assert evaluation._resolve_replay_trace("ghost") is None

    # prepare_agent_env
    args = MagicMock(protocol="local", agent_cmd="python")
    evaluation.prepare_agent_env(args)
    assert os.environ["AGENT_LOCAL_CMD"] == "python"

    args = MagicMock(protocol="socket", agent_socket="localhost:8080")
    evaluation.prepare_agent_env(args)
    assert os.environ["AGENT_SOCKET_ADDR"] == "localhost:8080"

    # load_plugins_from_args
    monkeypatch.setenv("AES_PLUGINS", "p1, p2")
    with patch("eval_runner.plugins.manager.load", side_effect=Exception("Load fail")):
        evaluation.load_plugins_from_args(MagicMock(plugin=["p3"]))
        # Should print warning and continue

    # handle_evaluate errors
    args = MagicMock(path="http://invalid", format="jsonl")
    with patch("eval_runner.loader.load_dataset", side_effect=Exception("Load fail")):
        assert await evaluation.handle_evaluate(args) == 1

    args.path = str(mock_config / "scenarios")
    (mock_config / "scenarios").mkdir()
    with patch("eval_runner.loader.load_dataset", return_value=[]):
        assert await evaluation.handle_evaluate(args) == 1

    # handle_replay content reconstruction
    events = [
        {"event": "run_start", "run_id": "r1", "scenario": "s1"},
        {"event": "prompt", "role": "user", "content": "hi"},
        {"event": "agent_response", "content": "hello"},
        {"event": "run_end", "status": "pass"},
    ]
    with (
        patch(
            "eval_runner.handlers.evaluation._resolve_replay_trace",
            return_value=mock_config / "run.jsonl",
        ),
        patch("eval_runner.trace_utils.load_events", return_value=events),
    ):
        assert await evaluation.handle_replay(MagicMock(run_id="r1")) == 0


@pytest.mark.asyncio
async def test_handler_scenarios_expansion(mock_config, monkeypatch):
    # classify_scenario fallback
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    res = scenarios.classify_scenario({})
    assert res["industry"] == "generic"

    res_fin = scenarios.classify_scenario({"metadata": {"industry": "finance"}})
    assert res_fin["industry"] == "fintech"

    res_med = scenarios.classify_scenario({"metadata": {"industry": "healthcare"}})
    assert res_med["industry"] == "medical"

    # handle_aes_validate errors
    args = MagicMock(path=str(mock_config / "empty"))
    (mock_config / "empty").mkdir()
    assert await scenarios.handle_aes_validate(args) == 1

    # export logic
    scen = mock_config / "test.aes.yaml"
    scen_content = (
        "aes_version: 1.4\nworkflow: {nodes: [], edges: []}\n"
        "metadata: {id: id1, name: n1, compliance_level: Standard}\n"
        "evaluation: {metrics: []}"
    )
    scen.write_text(scen_content)
    args = MagicMock(path=str(scen), export=str(mock_config / "exported.yaml"))
    with patch("jsonschema.validators.Draft7Validator.validate"):  # skip real validation
        assert await scenarios.handle_aes_validate(args) == 0
        assert (mock_config / "exported.yaml").exists()

    # inspect missing file
    args = MagicMock(path="ghost.json")
    assert await scenarios.handle_inspect(args) == 1

    # mutation input missing
    args = MagicMock(input="ghost.json", type="typos", output=None)
    assert await scenarios.handle_mutate(args) == 1

    # spec_to_eval failure
    args = MagicMock(input="ghost.md")
    assert await scenarios.handle_spec_to_eval(args) == 1


@pytest.mark.asyncio
async def test_identity_coverage_gap_fill(mock_config, monkeypatch):
    # Line 40-43: Env key load fail
    monkeypatch.setenv("AES_PRIVATE_KEY_SYSTEM_ID", "INVALID_PEM")
    # Should catch and log warning, then continue to file fallback
    # Since it is system_id and files don't exist, it will raise PermissionError
    # if provisioning blocked
    monkeypatch.setattr(config, "ALLOW_SYSTEM_IDENTITY_PROVISIONING", False)
    with pytest.raises(PermissionError):
        identity.IdentityService.get_private_key("system_id", auto_provision=False)

    # Line 92-96: Unsafe path in get_public_key
    with pytest.raises(PermissionError):
        identity.IdentityService.get_public_key("../secret")

    # Line 105-107: Fallback derivation success
    id_dir = mock_config / "identities" / "derive"
    id_dir.mkdir()
    identity.IdentityService._provision_local_identity("derive")
    (id_dir / "public_key.pem").unlink()
    assert identity.IdentityService.get_public_key("derive", auto_provision=False) is not None


@pytest.mark.asyncio
async def test_all_environment_handlers_exceptions():

    import eval_runner.handlers.environment as env

    # We patch the underlying modules to raise exceptions
    handlers = [
        (env.handle_analyze, "eval_runner.analyzer.analyze_repo", MagicMock(url="u")),
        (
            env.handle_auto_translate,
            "eval_runner.auto_translate.extract_text",
            MagicMock(input="i"),
        ),
        (
            env.handle_init,
            "eval_runner.scaffold.scaffold_benchmark",
            MagicMock(dir="d", industry="i", protocol="p", standard=None),
        ),
        (env.handle_install, "eval_runner.catalog.install_pack", MagicMock(pack="p")),
        (env.handle_registry_sync, "eval_runner.registry_sync.ensure_schema_sync", MagicMock()),
        (
            env.handle_registry_add,
            "eval_runner.registry_sync.add_standard_to_registry",
            MagicMock(id="i", industry="in"),
        ),
        (env.handle_plugin_list, "eval_runner.plugins.manager.load_plugins", MagicMock()),
        (env.handle_ci_generate, "eval_runner.scaffold.generate_github_action", MagicMock()),
        (env.handle_cleanup_runs, "eval_runner.cleaner.cleanup_traces", MagicMock(days=1)),
        (
            env.handle_export,
            "eval_runner.exporter.HFExporter.export",
            MagicMock(input="i", output="o"),
        ),
        (env.handle_failures_search, "eval_runner.failure_corpus.search", MagicMock(query="q")),
    ]

    for handler, patch_path, args in handlers:
        with patch(patch_path, side_effect=Exception("Crash")):
            assert await handler(args) == 1


@pytest.mark.asyncio
async def test_all_evaluation_handlers_exceptions(mock_config):
    import eval_runner.handlers.evaluation as eval_h

    handlers = [
        (
            eval_h.handle_record,
            "eval_runner.trace_recorder.record_interaction",
            MagicMock(agent="a"),
        ),
        (eval_h.handle_playground, "eval_runner.playground.run_playground", MagicMock(agent="a")),
        (
            eval_h.handle_verify,
            "eval_runner.verifier.TraceVerifier.verify_trace_async",
            MagicMock(run_id="r1"),
        ),
        (
            eval_h.handle_certify,
            "eval_runner.verifier.TraceVerifier.sign_trace",
            MagicMock(run_id="r1"),
        ),
        (eval_h.handle_gate, "json.load", MagicMock(run_id="r1", hash="h")),
    ]

    for handler, patch_path, args in handlers:
        if patch_path == "eval_runner.verifier.TraceVerifier.verify_trace_async":
            # Need to patch with AsyncMock for coroutines
            m = AsyncMock(side_effect=Exception("Crash"))
        else:
            m = MagicMock(side_effect=Exception("Crash"))

        # For handle_verify/handle_certify, we need to ensure the files exist to reach the call
        (mock_config / "runs" / "r1").mkdir(parents=True, exist_ok=True)
        (mock_config / "runs" / "r1" / "run.jsonl").write_text("[]")
        (mock_config / "runs" / "r1" / "run_manifest.json").write_text("{}")

        is_async_verify = patch_path == "eval_runner.verifier.TraceVerifier.verify_trace_async"
        with (
            patch(patch_path, side_effect=Exception("Crash"))
            if not is_async_verify
            else patch(patch_path, new=m)
        ):
            assert await handler(args) == 1


@pytest.mark.asyncio
async def test_handle_gate_specific_paths(mock_config):
    # Test commit hash mismatch
    vc_path = mock_config / "runs" / "r1" / "run_manifest.json"
    vc_path.parent.mkdir(parents=True, exist_ok=True)
    vc_path.write_text(json.dumps({"metadata": {"git_hash": "wrong"}}))
    (vc_path.parent / "run.jsonl").write_text("[]")

    args = MagicMock(run_id="r1", hash="correct", verify_ledger=False)
    with patch("eval_runner.verifier.TraceVerifier.verify_trace_async", return_value=True):
        assert await evaluation.handle_gate(args) == 1
