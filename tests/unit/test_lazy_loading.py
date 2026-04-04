import sys
import pytest
from unittest.mock import patch

def test_handler_package_lazy_loading():
    """Verify that importing eval_runner.handlers does not eagerly import all sub-modules."""
    # 1. Ensure handlers is not already in sys.modules
    if "eval_runner.handlers.analysis" in sys.modules:
        del sys.modules["eval_runner.handlers.analysis"]
    if "eval_runner.handlers.evaluation" in sys.modules:
        del sys.modules["eval_runner.handlers.evaluation"]
    
    # 2. Import the handlers package
    import eval_runner.handlers
    
    # 3. Verify sub-modules are NOT yet loaded (Authoritative PEP 562 check)
    assert "eval_runner.handlers.analysis" not in sys.modules
    assert "eval_runner.handlers.evaluation" not in sys.modules
    
    # 4. Access a handler via __getattr__
    analysis_mod = eval_runner.handlers.analysis
    
    # 5. Now it should be loaded and be a valid module
    assert analysis_mod.__name__.endswith(".analysis")
    assert hasattr(analysis_mod, "handle_report")
    
    # 6. Verify attribute access on the parent is now cached
    assert eval_runner.handlers.analysis is analysis_mod
