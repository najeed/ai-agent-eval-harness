import os
import pytest
from eval_runner import utils, config
from pathlib import Path
from unittest.mock import MagicMock, patch

def test_strict_jail_enforcement():
    """Verify that AEH_STRICT_JAIL=1 blocks access to system temp files."""
    import tempfile
    # System temp is definitively outside the project root
    temp_dir = Path(tempfile.gettempdir()).resolve()
    temp_file = temp_dir / "ah_security_test.txt"
    temp_file.write_text("shhh")
    
    try:
        # Condition A: Temp allowed by default
        if "AEH_STRICT_JAIL" in os.environ: del os.environ["AEH_STRICT_JAIL"]
        assert utils.is_path_safe(temp_file, config.PROJECT_ROOT) is True
        
        # Condition B: Temp blocked in strict mode
        os.environ["AEH_STRICT_JAIL"] = "1"
        assert utils.is_path_safe(temp_file, config.PROJECT_ROOT) is False
    finally:
        if temp_file.exists(): temp_file.unlink()
        if "AEH_STRICT_JAIL" in os.environ: del os.environ["AEH_STRICT_JAIL"]

@pytest.mark.asyncio
async def test_handle_run_exit_code_on_error():
    """Verify BUG-01: handle_run must exit with code 1 on exception."""
    from eval_runner.handlers import evaluation
    
    args = MagicMock()
    args.scenario = "non_existent.json"
    
    # Correct patching of module-local sys/traceback
    with patch("eval_runner.handlers.evaluation.sys.exit") as mock_exit:
        with patch("eval_runner.handlers.evaluation.traceback.print_exc") as mock_trace:
            await evaluation.handle_run(args)
            mock_exit.assert_called_once_with(1)
            mock_trace.assert_called_once()
