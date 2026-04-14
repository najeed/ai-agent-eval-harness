from argparse import Namespace

import pytest

from eval_runner.handlers.evaluation import handle_certify, handle_evaluate, handle_run


@pytest.mark.asyncio
async def test_handle_run_exit_on_exception(tmp_path):
    """Verify BUG-01: handle_run must return code 1 on exception."""
    # Scenario doesn't exist - should trigger return 1
    args = Namespace(scenario="non_existent.json", engine="open_core", run_id="test-run")

    # handle_run prints an error message then returns 1
    result = await handle_run(args)
    assert result == 1


@pytest.mark.asyncio
async def test_handle_evaluate_exit_on_exception(tmp_path):
    """Verify BUG-01: handle_evaluate must return code 1 on exception."""
    # Passing a directory instead of a file should trigger failure
    bad_path = tmp_path / "not_a_file"
    bad_path.mkdir()
    args = Namespace(path=str(bad_path), engine="open_core", run_id="test-run")

    result = await handle_evaluate(args)
    assert result == 1


@pytest.mark.asyncio
async def test_handle_certify_exit_on_exception(tmp_path):
    """Verify BUG-01: handle_certify must return code 1 on exception."""
    # Passing a non-existent file path
    args = Namespace(
        path="non_existent.jsonl", run_id="test_certify_fail", metadata=None, private_key=None
    )

    result = await handle_certify(args)
    assert result == 1
