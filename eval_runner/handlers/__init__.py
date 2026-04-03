"""
eval_runner.handlers

Subpackage for CLI command handlers.
Refactored to use lazy module loading (PEP 562) to resolve circular 
dependencies between the CLI entry point and specific handlers.
"""

def __getattr__(name):
    """
    Lazy-load handler modules only when requested as package attributes.
    Supports high-fidelity verification in unit tests (test_cli_extra).
    """
    import importlib
    
    _handlers = {
        "scenarios": ".scenarios",
        "evaluation": ".evaluation",
        "analysis": ".analysis",
        "environment": ".environment",
        "console": ".console.app"
    }
    
    if name in _handlers:
        return importlib.import_module(_handlers[name], __package__)
    
    raise AttributeError(f"module {__name__} has no attribute {name}")
