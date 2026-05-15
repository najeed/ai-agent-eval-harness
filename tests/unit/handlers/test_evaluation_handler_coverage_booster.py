import os
from unittest.mock import MagicMock, patch

import pytest

from eval_runner.handlers import evaluation


@pytest.mark.asyncio
async def test_resolve_replay_trace_security(tmp_path):
    """Exercises security failure in _resolve_replay_trace (line 54)."""
    # First check passes (line 51), second fails (line 53)
    with patch("eval_runner.utils.is_path_safe", side_effect=[True, False]):
        res = evaluation._resolve_replay_trace("some-run")
        assert res is None


@pytest.mark.asyncio
async def test_handle_evaluate_metadata_error():
    """Exercises TypeError in vars(args) (lines 161-162)."""
    args = MagicMock()
    args.path = "some-path"
    args.format = "json"

    # To trigger TypeError: vars() argument must have __dict__ attribute
    # But MagicMock has __dict__. We need something that doesn't.
    class NoDict:
        __slots__ = ["path", "format", "plugin", "agent", "agent_name", "run_id"]

        def __init__(self):
            self.path = "p"
            self.format = "f"
            self.plugin = []
            self.agent = "a"
            self.agent_name = "n"
            self.run_id = "r"

    args_no_dict = NoDict()

    with (
        patch("eval_runner.loader.load_dataset", return_value=[{"id": "1"}]),
        patch("eval_runner.engine.run_evaluation") as mock_run,
    ):
        await evaluation.handle_evaluate(args_no_dict)
        mock_run.assert_called()
        # Verify metadata['args'] is {}
        call_args = mock_run.call_args[1]
        assert call_args["metadata"]["args"] == {}


@pytest.mark.asyncio
async def test_handle_evaluate_loop_exception():
    """Exercises exception in evaluation loop (lines 176-179)."""
    args = MagicMock(path="p", format="f", plugin=[], attempts=1)
    with (
        patch("eval_runner.loader.load_dataset", return_value=[{"id": "1"}]),
        patch("eval_runner.engine.run_evaluation", side_effect=Exception("Loop Error")),
    ):
        res = await evaluation.handle_evaluate(args)
        assert res == 1


@pytest.mark.asyncio
async def test_handle_run_overrides(tmp_path):
    """Exercises environment overrides and seed logic (lines 187, 199-202, 220-221)."""

    class NoDict:
        __slots__ = [
            "scenario",
            "run_log_dir",
            "per_run_logs",
            "master_log",
            "seed",
            "plugin",
            "attempts",
            "agent",
            "agent_name",
            "run_id",
        ]

        def __init__(self):
            self.scenario = "s"
            self.run_log_dir = "custom_logs"
            self.per_run_logs = True
            self.master_log = True
            self.seed = 42
            self.plugin = []
            self.attempts = "not-int"
            self.agent = "a"
            self.agent_name = "n"
            self.run_id = "r"

    args = NoDict()

    with (
        patch("eval_runner.loader.load_scenario", return_value={"id": "1"}),
        patch("eval_runner.engine.run_evaluation"),
    ):
        await evaluation.handle_run(args)
        assert os.environ["RUN_LOG_DIR"] == "custom_logs"
        assert os.environ["RUN_LOG_PER_RUN"] == "true"
        assert os.environ["RUN_LOG_MASTER"] == "true"


@pytest.mark.asyncio
async def test_handle_record_playground_success():
    """Exercises successful calls (lines 253, 264)."""
    args = MagicMock(agent="a", protocol="http")
    with patch(
        "eval_runner.handlers.evaluation.trace_recorder.record_interaction", return_value=None
    ):
        assert await evaluation.handle_record(args) == 0
    with patch("eval_runner.handlers.evaluation.playground.run_playground", return_value=None):
        assert await evaluation.handle_playground(args) == 0


@pytest.mark.asyncio
async def test_handle_record_playground_failure():
    """Exercises failures (lines 254-256, 265-267)."""
    args = MagicMock(agent="a", protocol="http")
    with patch(
        "eval_runner.handlers.evaluation.trace_recorder.record_interaction",
        side_effect=Exception("Fail"),
    ):
        assert await evaluation.handle_record(args) == 1
    with patch(
        "eval_runner.handlers.evaluation.playground.run_playground", side_effect=Exception("Fail")
    ):
        assert await evaluation.handle_playground(args) == 1


@pytest.mark.asyncio
async def test_handle_replay_logic(tmp_path):
    """Exercises replay missing run_id and failure (lines 279-280, 318-320)."""
    # Missing run_id
    assert await evaluation.handle_replay(MagicMock(run_id=None)) == 1

    # Exception
    with patch(
        "eval_runner.handlers.evaluation._resolve_replay_trace", side_effect=Exception("Fail")
    ):
        assert await evaluation.handle_replay(MagicMock(run_id="r")) == 1


@pytest.mark.asyncio
async def test_handle_verify_failures(tmp_path):
    """Exercises verify failures (lines 334-335, 343, 353-356, 368-372)."""
    # Missing run_id
    assert await evaluation.handle_verify(MagicMock(run_id=None)) == 1

    # Security failure
    with patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=False):
        assert await evaluation.handle_verify(MagicMock(run_id="r")) == 1

    # Missing manifest
    with patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=True):
        with patch(
            "pathlib.Path.exists", side_effect=[True, False]
        ):  # trace exists, manifest doesn't
            assert await evaluation.handle_verify(MagicMock(run_id="r")) == 1

    # Verification failed (line 368)
    with (
        patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=True),
        patch("pathlib.Path.exists", return_value=True),
        patch("eval_runner.verifier.TraceVerifier.verify_trace_async", return_value=False),
    ):
        assert await evaluation.handle_verify(MagicMock(run_id="r")) == 1

    # Exception
    with patch("eval_runner.handlers.evaluation._ensure_path_safe", side_effect=Exception("Fail")):
        assert await evaluation.handle_verify(MagicMock(run_id="r")) == 1


@pytest.mark.asyncio
async def test_handle_gate_failures(tmp_path):
    """Exercises gate failures (lines 384-385, 391, 398, 404, 407-408, 421-422,
    441-442, 447-449)."""
    # Missing run_id
    assert await evaluation.handle_gate(MagicMock(run_id=None)) == 1

    # Security fail 1
    with patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=False):
        assert await evaluation.handle_gate(MagicMock(run_id="r")) == 1

    # Sidecar exists (line 398)
    with (
        patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=True),
        patch("pathlib.Path.exists", side_effect=[False, True, True, True]),
    ):  # vault NO, sidecar YES, safe YES, vc YES
        with patch("builtins.open", MagicMock()):
            with patch("json.load", return_value={"trace_file": "t.json"}):
                with patch(
                    "eval_runner.verifier.TraceVerifier.verify_trace_async", return_value=True
                ):
                    assert await evaluation.handle_gate(MagicMock(run_id="r", hash=None)) == 0

    # Security fail 2 (line 404)
    # We need vault_path.exists() to be True so vc_path is set.
    with (
        patch("eval_runner.handlers.evaluation._ensure_path_safe", side_effect=[True, False]),
        patch("pathlib.Path.exists", side_effect=[True, True]),
    ):  # vault exists
        assert await evaluation.handle_gate(MagicMock(run_id="r")) == 1

    # VC Path not exists (line 407)
    # We need vault_path.exists() to be True, then later vc_path.exists() to be False
    with (
        patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=True),
        patch("pathlib.Path.exists", side_effect=[True, False]),
    ):  # vault exists, vc NOT exists
        assert await evaluation.handle_gate(MagicMock(run_id="r")) == 1

    # Trace missing (line 421)
    with (
        patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=True),
        patch("pathlib.Path.exists", side_effect=[True, True, False]),
    ):  # vault YES, safe YES, trace NO
        with patch("builtins.open", MagicMock()):
            with patch("json.load", return_value={"trace_file": "t.json"}):
                assert await evaluation.handle_gate(MagicMock(run_id="r")) == 1

    # Hash mismatch (line 441)
    with (
        patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=True),
        patch("pathlib.Path.exists", return_value=True),
    ):
        with patch("builtins.open", MagicMock()):
            with patch("json.load", return_value={"metadata": {"git_hash": "abc"}}):
                with patch(
                    "eval_runner.verifier.TraceVerifier.verify_trace_async", return_value=True
                ):
                    assert await evaluation.handle_gate(MagicMock(run_id="r", hash="def")) == 1

    # Unexpected Exception (line 447)
    # Triggered by json.load or open
    with (
        patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=True),
        patch("pathlib.Path.exists", return_value=True),
    ):
        with patch("builtins.open", side_effect=Exception("Catch me")):
            assert await evaluation.handle_gate(MagicMock(run_id="r")) == 1


@pytest.mark.asyncio
async def test_handle_quickstart():
    """Exercises handle_quickstart (line 454)."""
    with patch("eval_runner.quickstart.run_quickstart") as mock_q:
        await evaluation.handle_quickstart(None)
        mock_q.assert_called_once()


@pytest.mark.asyncio
async def test_handle_certify_failures(tmp_path):
    """Exercises certify failures (lines 466-467, 474, 513, 523-526)."""
    # Missing run_id
    assert await evaluation.handle_certify(MagicMock(run_id=None)) == 1

    # Security failure
    with patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=False):
        assert await evaluation.handle_certify(MagicMock(run_id="r")) == 1

    # Provenance chain (line 513)
    args = MagicMock(
        run_id="r",
        identity="i",
        status="pass",
        score=1.0,
        ttl=30,
        fingerprint=None,
        policy_ref=None,
    )
    with (
        patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=True),
        patch("pathlib.Path.exists", return_value=True),
        patch("eval_runner.verifier.TraceVerifier.sign_trace") as mock_sign,
    ):
        mock_sign.return_value = {"provenance_chain": [{"identity": "signer-1"}], "run_id": "r"}
        assert await evaluation.handle_certify(args) == 0

    # Exception
    # Triggered by sign_trace
    with (
        patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=True),
        patch("pathlib.Path.exists", return_value=True),
        patch("eval_runner.verifier.TraceVerifier.sign_trace", side_effect=Exception("Fail")),
    ):
        assert await evaluation.handle_certify(MagicMock(run_id="r")) == 1
