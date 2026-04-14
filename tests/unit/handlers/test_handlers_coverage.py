import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from eval_runner import config, loader, verifier
from eval_runner.handlers import analysis, environment, evaluation, scenarios


@pytest.fixture
def mock_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUN_LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
    (tmp_path / "reports").mkdir(exist_ok=True)
    return tmp_path


class MockArgs:
    def __init__(self, tmp_path=None, **kwargs):
        # Industrial Hardening: All paths must be relative to tmp_path
        # to prevent workspace pollution
        self.tmp = tmp_path
        self.path = str(tmp_path / "s.json") if tmp_path else "s.json"
        self.format = "json"
        self.limit = None
        self.attempts = 1
        self.run_id = "r1"
        self.per_run_logs = False
        self.master_log = False
        self.seed = None
        self.run_log_dir = None
        self.protocol = "http"
        self.agent = "a"
        self.plugin = []
        self.hash = None
        self.verify_ledger = False
        self.identity = None
        self.status = "pass"
        self.score = 1.0
        self.ttl = 30
        self.output = str(tmp_path / "o") if tmp_path else "o"
        self.dir = str(tmp_path / "d") if tmp_path else "d"
        self.aes_command = "validate"
        self.scenario_path = None
        self.target = "t"
        self.search = None
        self.refresh = False
        self.query = "q"
        self.input = tmp_path / "i" if tmp_path else Path("i")
        self.type = "typo"
        self.industry = "finance"
        self.model = "m"
        self.url = "u"
        self.pack = "p"
        self.id = "id"
        self.name = "n"
        self.description = "d"
        self.days = 7
        self.force = False
        self.registry = False
        self.scenario_command = "inspect"
        self.agent_cmd = "ls"
        self.scenario = "s"
        self.__dict__.update(kwargs)


@pytest.mark.asyncio
async def test_evaluation_coverage_pure(mock_config):
    tmp_path = mock_config
    scen = tmp_path / "s.json"
    scen.write_text("{}")

    # 1. handle_evaluate (Success, Empty, Failure)
    args = MockArgs(tmp_path, path=str(scen), limit=1)
    with (
        patch("eval_runner.loader.load_dataset", return_value=[{"id": "s1"}]),
        patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock),
        patch("eval_runner.handlers.evaluation.prepare_agent_env"),
    ):
        assert await evaluation.handle_evaluate(args) == 0

    # ❌ [Silent Failure Hardening] Empty dataset must return 1
    with patch("eval_runner.loader.load_dataset", return_value=[]):
        assert await evaluation.handle_evaluate(args) == 1

    with patch("eval_runner.loader.load_dataset", side_effect=Exception):
        assert await evaluation.handle_evaluate(args) == 1

    # 2. handle_run (local/socket)
    args = MockArgs(tmp_path, scenario=str(scen), protocol="local", agent_cmd="ls")
    with (
        patch("eval_runner.loader.load_scenario", return_value={}),
        patch("eval_runner.engine.run_evaluation", new_callable=AsyncMock),
        patch("eval_runner.handlers.evaluation.prepare_agent_env"),
    ):
        assert await evaluation.handle_run(args) == 0
        args.protocol = "socket"
        args.agent_socket = "0"
        assert await evaluation.handle_run(args) == 0

    # 3. handle_replay (Vault vs Master)
    run_id = "r_rep"
    vault = tmp_path / run_id
    vault.mkdir()
    (vault / "run.jsonl").write_text(json.dumps({"event": "run_start", "run_id": run_id}) + "\n")
    assert await evaluation.handle_replay(MockArgs(tmp_path, run_id=run_id)) == 0
    (tmp_path / "run.jsonl").write_text(json.dumps({"event": "run_start", "run_id": "m1"}) + "\n")
    assert await evaluation.handle_replay(MockArgs(tmp_path, run_id="m1")) == 0
    assert await evaluation.handle_replay(MockArgs(tmp_path, run_id="MISSING")) == 1


@pytest.mark.asyncio
async def test_trust_protocols_pure(mock_config):
    tmp_path = mock_config
    run_id = "v1"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "run.jsonl").write_text("[]")
    manifest = {"run_id": run_id, "sha256": "h", "vc_version": "3.0.0"}
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest))

    # 1. Verify
    with patch("eval_runner.verifier.TraceVerifier.verify_trace_async", return_value=True):
        assert await evaluation.handle_verify(MockArgs(tmp_path, run_id=run_id)) == 0

    # 2. Gate (Success, Integrity Fail)
    cert_dir = tmp_path / "reports" / "certificates"
    cert_dir.mkdir(parents=True)
    vc_path = cert_dir / f"{run_id}_vc.json"
    vc_path.write_text(json.dumps(manifest))
    with patch("eval_runner.verifier.TraceVerifier.verify_trace_async", return_value=True):
        assert await evaluation.handle_gate(MockArgs(tmp_path, run_id=run_id)) == 0
        with patch("eval_runner.verifier.TraceVerifier.verify_trace_async", return_value=False):
            assert await evaluation.handle_gate(MockArgs(tmp_path, run_id=run_id)) == 1

    # 3. Certify
    with patch("eval_runner.verifier.TraceVerifier.sign_trace", return_value={"run_id": run_id}):
        assert await evaluation.handle_certify(MockArgs(tmp_path, run_id=run_id)) == 0


@pytest.mark.asyncio
async def test_analysis_coverage_pure(mock_config):
    tmp_path = mock_config
    run_id = "a1"
    vault = tmp_path / run_id
    vault.mkdir()
    (vault / "run.jsonl").write_text(json.dumps({"event": "run_start", "run_id": run_id}) + "\n")

    # 1. Report/Explain/Calibrate
    with (
        patch("eval_runner.reporter.generate_html_report"),
        patch("eval_runner.explainer.explain_trace"),
        patch("eval_runner.calibrator.run_calibration"),
    ):
        assert await analysis.handle_report(MockArgs(tmp_path, run_id=run_id)) == 0
        assert await analysis.handle_explain(MockArgs(tmp_path, run_id=run_id)) == 0
        assert await analysis.handle_calibrate(MockArgs(tmp_path, run_id=run_id)) == 0

    # 2. Leaderboard/Taxonomy/Metrics
    with patch("eval_runner.leaderboard_generator.run_leaderboard"):
        assert await analysis.handle_leaderboard(MockArgs(tmp_path)) == 0
        assert await analysis.handle_taxonomy(MockArgs(tmp_path)) == 0
        assert await analysis.handle_list_metrics(MockArgs(tmp_path)) == 0


@pytest.mark.asyncio
async def test_scenarios_coverage_pure(mock_config):
    tmp_path = mock_config
    scen = tmp_path / "s.json"
    scen.write_text('{"aes_version":"1.0"}')

    # 1. AES Validate
    with patch("eval_runner.handlers.scenarios.validate"):
        assert await scenarios.handle_aes_validate(MockArgs(tmp_path, path=str(scen))) == 0
        assert await scenarios.handle_aes_validate(MockArgs(tmp_path, path="MISSING")) == 1

    # 2. Inspect/Lint/List
    with patch("eval_runner.loader.load_scenario", return_value={}):
        assert await scenarios.handle_inspect(MockArgs(tmp_path, path=str(scen))) == 0
        assert await scenarios.handle_lint(MockArgs(tmp_path, target=str(scen))) == 0
        assert await scenarios.handle_list(MockArgs(tmp_path)) == 0

    # 3. Mutate/Spec-to-Eval/Drift
    input_file = tmp_path / "i.json"
    input_file.write_text("{}")
    with (
        patch("eval_runner.mutator.mutate_scenario", return_value={}),
        patch("eval_runner.spec_parser.parse_markdown_to_scenario", return_value={}),
        patch("eval_runner.drift_importer.import_trace_as_scenario"),
    ):
        assert await scenarios.handle_mutate(MockArgs(tmp_path, input=str(input_file))) == 0
        assert await scenarios.handle_spec_to_eval(MockArgs(tmp_path, input=str(input_file))) == 0
        assert await scenarios.handle_import_drift(MockArgs(tmp_path, input=str(input_file))) == 0


@pytest.mark.asyncio
async def test_environment_coverage_pure(mock_config):
    tmp_path = mock_config

    # 1. Analyze/Translate/Init
    input_p = tmp_path / "i.json"
    input_p.write_text("{}")
    with (
        patch("eval_runner.analyzer.analyze_repo"),
        patch("eval_runner.auto_translate.translate_to_scenario", return_value={}),
    ):
        assert await environment.handle_analyze(MockArgs(tmp_path, url="u")) == 0
        assert await environment.handle_auto_translate(MockArgs(tmp_path, input=input_p)) == 0
        assert await environment.handle_init(MockArgs(tmp_path)) == 0

    # 2. Plugins/Doctor/Cleanup
    with (
        patch("eval_runner.plugins.manager.load_plugins"),
        patch("eval_runner.doctor.run_doctor"),
        patch("eval_runner.cleaner.cleanup_traces"),
    ):
        assert await environment.handle_plugin_list(MockArgs(tmp_path)) == 0
        assert await environment.handle_doctor(MockArgs(tmp_path)) == 0
        assert await environment.handle_cleanup_runs(MockArgs(tmp_path)) == 0


def test_silent_failure_hardening_core(mock_config):
    # 1. Loader registry corruption detection
    bad_json = mock_config / "bad.json"
    bad_json.write_text("{invalid")
    with pytest.raises(RuntimeError, match="Registry Corruption"):
        # We need to ensure get_universal_registry crawls this file
        with patch("eval_runner.loader.get_internal_spec_root", return_value=mock_config):
            loader.get_universal_registry()

    # 2. Verifier missing artifacts logging
    with patch("eval_runner.verifier.logger.error") as mock_log:
        # verify_trace is now hardened to log errors if TP or MP are missing
        assert verifier.TraceVerifier.verify_trace("non", "existent") is False
        mock_log.assert_called()
