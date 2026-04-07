import pytest
import sys
from unittest.mock import MagicMock, patch
from eval_runner.handlers import evaluation

@pytest.mark.asyncio
async def test_handle_run_exit_on_exception():
    """Verify BUG-01: handle_run must exit with code 1 on exception."""
    args = MagicMock()
    args.scenario = "non_existent.json"
    
    with patch("eval_runner.handlers.evaluation.sys.exit") as mock_exit:
        with patch("eval_runner.handlers.evaluation.traceback.print_exc") as mock_trace:
            # This should trigger the exception block in handle_run
            await evaluation.handle_run(args)
            mock_exit.assert_called_once_with(1)
            mock_trace.assert_called_once()

@pytest.mark.asyncio
async def test_handle_evaluate_exit_on_exception():
    """Verify BUG-01: handle_evaluate must exit with code 1 on exception."""
    args = MagicMock()
    args.path = "non_existent/"
    
    with patch("eval_runner.handlers.evaluation.sys.exit") as mock_exit:
        with patch("eval_runner.handlers.evaluation.traceback.print_exc") as mock_trace:
            await evaluation.handle_evaluate(args)
            mock_exit.assert_called_once_with(1)
            mock_trace.assert_called_once()

@pytest.mark.asyncio
async def test_handle_certify_exit_on_exception():
    """Verify BUG-01: handle_certify must exit with code 1 on exception."""
    args = MagicMock()
    args.path = "non_existent.jsonl"
    
    with patch("eval_runner.handlers.evaluation.sys.exit") as mock_exit:
        with patch("eval_runner.handlers.evaluation.traceback.print_exc") as mock_trace:
            await evaluation.handle_certify(args)
            mock_exit.assert_called_once_with(1)
            mock_trace.assert_called_once()
