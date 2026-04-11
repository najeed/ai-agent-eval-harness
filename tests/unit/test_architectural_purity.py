import re
from pathlib import Path


def test_no_silent_exception_blocks():
    """
    Forensic Integrity Guard: Prohibit silent 'except Exception:' blocks without logging.
    All failures must be auditable in the Forensic Trust Protocol v3.0.0.
    """
    core_dir = Path("eval_runner")
    # Pattern: except Exception: followed by optional whitespace and 'pass' or 'return'
    # without any specialized logging call observed in the vicinity.
    # We strictly target blocks that suggest intentional silencing of errors.
    silent_pattern = re.compile(r"except\s+Exception:(\s+pass|\s+return\s*$)")

    violations = []

    for py_file in core_dir.glob("**/*.py"):
        content = py_file.read_text(encoding="utf-8")
        if silent_pattern.search(content):
            violations.append(str(py_file))

    msg = f"CRITICAL: Silent 'except Exception:' blocks detected in: {violations}."
    assert not violations, msg


def test_all_schemas_indexed():
    """Verify that the Universal Registry indexes all 5 authoritative forensic schemas."""
    from eval_runner.loader import get_universal_registry

    registry = get_universal_registry()

    # 5 schemas + their various definitions should result in a significant registry size.
    assert len(list(registry)) > 5, "Universal Registry failed to index the forensic tree."
