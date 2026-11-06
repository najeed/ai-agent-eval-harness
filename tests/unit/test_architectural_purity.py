import ast
from pathlib import Path

import pytest


def _logs_failure(statement):
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
        return False
    function = statement.value.func
    if not isinstance(function, ast.Attribute) or function.attr not in {
        "debug",
        "info",
        "warning",
        "error",
        "exception",
        "critical",
    }:
        return False
    receiver = function.value
    return (isinstance(receiver, ast.Name) and receiver.id in {"logger", "logging"}) or (
        isinstance(receiver, ast.Call)
        and isinstance(receiver.func, ast.Attribute)
        and isinstance(receiver.func.value, ast.Name)
        and receiver.func.value.id == "logging"
        and receiver.func.attr == "getLogger"
    )


def _failure_is_observable(statements):
    """Require a diagnostic or propagation on every syntactic exit path.

    A log in a nested function or just one conditional branch is insufficient.
    Re-raising or wrapping the failure propagates it to the caller's boundary.
    """
    for index, statement in enumerate(statements):
        if isinstance(statement, ast.Raise) or _logs_failure(statement):
            return True
        if isinstance(statement, (ast.Return, ast.Break, ast.Continue)):
            return False
        if isinstance(statement, ast.If):
            remainder = statements[index + 1 :]
            return _failure_is_observable(statement.body + remainder) and _failure_is_observable(
                statement.orelse + remainder
            )
    return False


def _unlogged_broad_handlers(source):
    tree = ast.parse(source)
    return [
        handler.lineno
        for handler in ast.walk(tree)
        if isinstance(handler, ast.ExceptHandler)
        and (
            handler.type is None
            or any(
                isinstance(node, ast.Name)
                and node.id in {"Exception", "BaseException"}
                or isinstance(node, ast.Attribute)
                and node.attr in {"Exception", "BaseException"}
                for node in ast.walk(handler.type)
            )
        )
        and not _failure_is_observable(handler.body)
    ]


def test_no_silent_exception_blocks():
    """
    Forensic Integrity Guard: Prohibit silent 'except Exception:' blocks without logging.
    All failures must be auditable in the Forensic Trust Protocol v3.0.0.
    """
    project_root = Path(__file__).resolve().parents[2]
    violations = []
    for package in ("agentv_runtime", "eval_runner", "dataproc_engine", "sample_agent"):
        package_root = project_root / package
        assert package_root.is_dir(), f"Missing architectural scan root: {package}"
        for py_file in sorted(package_root.rglob("*.py")):
            if "tests" in py_file.relative_to(package_root).parts:
                continue
            violations.extend(
                f"{py_file.relative_to(project_root)}:{line}"
                for line in _unlogged_broad_handlers(py_file.read_text(encoding="utf-8-sig"))
            )

    msg = f"CRITICAL: Silent 'except Exception:' blocks detected in: {violations}."
    assert not violations, msg


@pytest.mark.parametrize(
    "body",
    [
        "pass",
        "return None",
        "print('failed')",
        "client.error('failed')",
        "logger.log('error', 'in-memory trace only')",
        "def later():\n    logger.error('failed')",
        "if debug:\n    logger.error('failed')\nreturn None",
        "return None\nlogger.error('unreachable')",
        "if skip:\n    return None\nlogger.error('too late')",
        "try:\n    pass\nexcept ValueError:\n    logger.error('inner only')",
    ],
)
@pytest.mark.parametrize(
    "catch",
    [
        "Exception",
        "Exception as exc",
        "(ValueError, Exception)",
        "BaseException",
        "builtins.Exception",
        "",
    ],
)
def test_purity_detector_rejects_unlogged_broad_failures(body, catch):
    import textwrap

    source = (
        "def run():\n    try:\n        work()\n    except"
        + (f" {catch}" if catch else "")
        + ":\n"
        + textwrap.indent(body, "        ")
    )
    assert _unlogged_broad_handlers(source)


@pytest.mark.parametrize(
    "body",
    [
        "raise",
        "raise RuntimeError('failed') from exc",
        "logger.debug('failed', exc_info=True)\nreturn None",
        "logging.exception('failed')",
        "logging.getLogger(__name__).warning('failed', exc_info=True)",
        "if fatal:\n    raise\nelse:\n    logger.error('failed')",
    ],
)
def test_purity_detector_accepts_auditable_failure_boundaries(body):
    import textwrap

    source = "try:\n    work()\nexcept Exception as exc:\n" + textwrap.indent(body, "    ")
    assert not _unlogged_broad_handlers(source)


def test_purity_detector_preserves_targeted_catches_and_abstract_contracts():
    source = """
class Provider:
    @abstractmethod
    def execute(self):
        raise NotImplementedError

def optional_file():
    try:
        read()
    except FileNotFoundError:
        return None
"""
    assert not _unlogged_broad_handlers(source)


def test_scenario_authoring_uses_template_terminology():
    root = Path(__file__).resolve().parents[2]
    for name in ("contributor.py", "spec_parser.py"):
        tree = ast.parse((root / "eval_runner" / name).read_text(encoding="utf-8"))
        assert not any(
            isinstance(node, ast.Name) and node.id in {"stub", "save_scenario_stub"}
            for node in ast.walk(tree)
        ), f"Obsolete scenario authoring terminology in {name}"


def test_all_schemas_indexed():
    """Verify that the Universal Registry indexes all 5 forensic schemas."""
    from eval_runner.loader import get_universal_registry

    registry = get_universal_registry()

    # 5 schemas + their various definitions should result in a significant registry size.
    assert len(list(registry)) > 5, "Universal Registry failed to index the forensic tree."


def test_runtime_and_console_broad_exception_boundaries_keep_tracebacks():
    """Agent/plugin error barriers must record failures before suppressing them."""
    paths = [
        Path("eval_runner") / name
        for name in (
            "runner.py",
            "session.py",
            "workflow_interpreter.py",
            "flight_recorder.py",
            "state_authority.py",
            "tool_sandbox.py",
            "live_bridge_plugin.py",
            "services/config_revision.py",
        )
    ] + list(Path("eval_runner/console").rglob("*.py"))
    violations = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for handler in (node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)):
            if handler.type is not None and not any(
                isinstance(node, ast.Name) and node.id in ("Exception", "BaseException")
                for node in ast.walk(handler.type)
            ):
                continue
            if any(isinstance(stmt, ast.Raise) for stmt in handler.body):
                continue
            direct_calls = [
                stmt.value
                for stmt in handler.body
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
            ]
            if not any(
                isinstance(call.func, ast.Attribute)
                and call.func.attr in ("debug", "info", "warning", "error", "exception", "critical")
                and any(
                    kw.arg == "exc_info"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                    for kw in call.keywords
                )
                for call in direct_calls
            ):
                violations.append(f"{path}:{handler.lineno}")
    assert not violations, f"Unlogged runtime/plugin failure barriers: {violations}"


def test_phase_one_verification_failures_are_auditable():
    """A suppressed trust/persistence exception must retain its traceback in diagnostics."""
    paths = (
        "agentv_runtime/finalization.py",
        "agentv_runtime/package.py",
        "agentv_runtime/signatures.py",
        "eval_runner/services/certification.py",
        "eval_runner/verifier.py",
        "eval_runner/reference/local_run_store.py",
        "eval_runner/reference/signing.py",
        "eval_runner/identity.py",
        "eval_runner/certification_lock.py",
    )
    violations = []
    for name in paths:
        tree = ast.parse(Path(name).read_text(encoding="utf-8"))
        parents = {
            child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)
        }
        for handler in (node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)):
            parent = parents[handler]
            while not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                parent = parents[parent]
            if (
                name
                in (
                    "agentv_runtime/finalization.py",
                    "agentv_runtime/package.py",
                    "agentv_runtime/signatures.py",
                    "eval_runner/verifier.py",
                )
                and isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef))
                and parent.name not in ("sign", "call_next")
                and (
                    handler.type is None
                    or any(
                        isinstance(node, ast.Name) and node.id in ("Exception", "BaseException")
                        for node in ast.walk(handler.type)
                    )
                )
            ):
                violations.append(f"{name}:{handler.lineno}: overly broad verification catch")
            # Re-raising keeps the failure visible at the caller's boundary.
            if any(isinstance(stmt, ast.Raise) for stmt in handler.body):
                continue
            calls = [
                node
                for stmt in handler.body
                for node in ast.walk(stmt)
                if isinstance(node, ast.Call)
            ]
            if not any(
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "logger"
                and any(
                    kw.arg == "exc_info"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                    for kw in call.keywords
                )
                for call in calls
            ):
                violations.append(f"{name}:{handler.lineno}")
    assert not violations, f"Suppressed failures without traceback logging: {violations}"
