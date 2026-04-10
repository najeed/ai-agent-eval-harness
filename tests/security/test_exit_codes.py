from argparse import Namespace
from unittest.mock import patch

import pytest

from eval_runner.handlers.evaluation import handle_certify, handle_evaluate, handle_run


@pytest.mark.asyncio
async def test_handle_run_exit_on_exception(tmp_path):
    """Verify BUG-01: handle_run must exit with code 1 on exception."""
    # Scenario doesn't exist - should trigger explicit sys.exit(1)
    args = Namespace(scenario="non_existent.json", engine="open_core", run_id="test-run")

    with patch("eval_runner.handlers.evaluation.sys.exit") as mock_exit:
        # handle_run prints an error message then exits
        await handle_run(args)
        mock_exit.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_handle_evaluate_exit_on_exception(tmp_path):
    """Verify BUG-01: handle_evaluate must exit with code 1 on exception."""
    # Passing a directory instead of a file should trigger failure
    bad_path = tmp_path / "not_a_file"
    bad_path.mkdir()
    args = Namespace(path=str(bad_path), engine="open_core", run_id="test-run")

    with patch("eval_runner.handlers.evaluation.sys.exit") as mock_exit:
        await handle_evaluate(args)
        mock_exit.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_handle_certify_exit_on_exception(tmp_path):
    """Verify BUG-01: handle_certify must exit with code 1 on exception."""
    # Passing a non-existent file path
    args = Namespace(path="non_existent.jsonl", run_id="test_certify_fail", metadata=None, private_key=None)

    with patch("eval_runner.handlers.evaluation.sys.exit") as mock_exit:
        await handle_certify(args)
        mock_exit.assert_called_once_with(1)
