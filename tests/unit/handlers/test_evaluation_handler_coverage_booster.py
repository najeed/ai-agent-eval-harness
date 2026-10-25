import os
from unittest.mock import AsyncMock, MagicMock, patch

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
        "eval_runner.trace_recorder.record_interaction",
        new_callable=AsyncMock,
        return_value=None,
    ):
        assert await evaluation.handle_record(args) == 0
    with patch(
        "eval_runner.playground.run_playground",
        new_callable=AsyncMock,
        return_value=None,
    ):
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

    # Manifest not found or UNVERIFIED
    with patch(
        "eval_runner.verifier.TraceVerifier.verify_run",
        return_value={"is_valid": False, "verification_status": "NOT_FOUND"},
    ):
        assert await evaluation.handle_gate(MagicMock(run_id="r", hash=None)) == 1

    # Verification failed (is_valid = False)
    with (
        patch(
            "eval_runner.verifier.TraceVerifier.verify_run",
            return_value={"is_valid": False, "verification_status": "FAILED"},
        ),
        patch(
            "eval_runner.reference.local_run_store.LocalFileRunStore.get_manifest",
            return_value={"metadata": {}},
        ),
    ):
        assert await evaluation.handle_gate(MagicMock(run_id="r", hash=None)) == 1

    # Verification success (no hash required)
    with (
        patch(
            "eval_runner.verifier.TraceVerifier.verify_run",
            return_value={"is_valid": True, "verification_status": "VERIFIED"},
        ),
        patch(
            "eval_runner.reference.local_run_store.LocalFileRunStore.get_manifest",
            return_value={"metadata": {"git_hash": "abc"}},
        ),
    ):
        assert await evaluation.handle_gate(MagicMock(run_id="r", hash=None)) == 0

    # Commit hash mismatch
    with (
        patch(
            "eval_runner.verifier.TraceVerifier.verify_run",
            return_value={"is_valid": True, "verification_status": "VERIFIED"},
        ),
        patch(
            "eval_runner.reference.local_run_store.LocalFileRunStore.get_manifest",
            return_value={"metadata": {"git_hash": "abc"}},
        ),
    ):
        assert await evaluation.handle_gate(MagicMock(run_id="r", hash="def")) == 1

    # Commit hash match
    with (
        patch(
            "eval_runner.verifier.TraceVerifier.verify_run",
            return_value={"is_valid": True, "verification_status": "VERIFIED"},
        ),
        patch(
            "eval_runner.reference.local_run_store.LocalFileRunStore.get_manifest",
            return_value={"metadata": {"git_hash": "abc"}},
        ),
    ):
        assert await evaluation.handle_gate(MagicMock(run_id="r", hash="abc")) == 0

    # Unexpected Exception
    with patch(
        "eval_runner.verifier.TraceVerifier.verify_run",
        side_effect=Exception("Catch me"),
    ):
        assert await evaluation.handle_gate(MagicMock(run_id="r", hash=None)) == 1


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
        patch("eval_runner.services.certification.execute_industrial_certification") as mock_cert,
    ):
        mock_cert.return_value = {"status": "certified", "manifest": {"trace_hash": "h"}}
        assert await evaluation.handle_certify(args) == 0

    # Exception
    # Triggered by execute_industrial_certification
    with (
        patch("eval_runner.handlers.evaluation._ensure_path_safe", return_value=True),
        patch("pathlib.Path.exists", return_value=True),
        patch(
            "eval_runner.services.certification.execute_industrial_certification",
            side_effect=Exception("Fail"),
        ),
    ):
        assert await evaluation.handle_certify(MagicMock(run_id="r")) == 1
