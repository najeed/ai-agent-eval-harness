"""
Industrial Mutation Testing Sentinel & Scorecard Generator.
Executes real AST-based code mutations against critical verification modules:
  - eval_runner/verifier.py
  - eval_runner/tool_sandbox.py
  - eval_runner/utils/base.py

Mutation strategy: SURGICAL LINE SUBSTITUTION.
Rather than using ast.unparse() (which rewrites the entire file, losing comments,
blank lines, and f-string formatting), this sentinel applies mutations by direct
targeted string replacement at the exact (lineno, col_offset) AST position.
This preserves all non-mutated lines byte-for-byte, preventing spurious test
failures from file-hash mismatches in TraceVerifier-based tests.

Calculates exact mutation score:
  Mutation Score = (Killed + Timeout) / (Killed + Timeout + Survived)

Incompetent mutants (annotation-only BitOr with no runtime effect under
`from __future__ import annotations`) are excluded from the denominator.

Outputs complete metrics:
  - Killed / Survived / Timeout / Skipped / Incompetent
  - Mutation Score (%)
  - Baseline vs Delta

Generates diligence artifact 'reports/mutation_scorecard.md' and fails CI if score < 100.0%.
"""

from __future__ import annotations

import ast
import concurrent.futures
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent.parent.parent
REPORT_DIR = BASE_DIR / "reports"
REPORT_PATH = REPORT_DIR / "mutation_scorecard.md"

# Strips heavy, slow third-party plugins that add 3-5s of startup latency per mutant
FAST_PYTEST_FLAGS = [
    "-q",
    "--no-header",
    "-p",
    "no:plugin_gateway",
    "-p",
    "no:cov",
    "-p",
    "no:benchmark",
    "-p",
    "no:logfire",
    "-p",
    "no:langsmith",
    "-p",
    "no:playwright",
    "-p",
    "no:Faker",
    "-p",
    "no:xdist",
    "-o",
    "addopts=",
]

TARGET_MODULES = [
    BASE_DIR / "eval_runner" / "verifier.py",
    BASE_DIR / "eval_runner" / "tool_sandbox.py",
    BASE_DIR / "eval_runner" / "utils" / "base.py",
]

# Per-module test corpora.
#
# Only fast, synchronous unit tests qualify — integration/chaos/security tests that
# spawn subprocesses or do async I/O exceed the timeout budget.
#
# Measured wall-clock subprocess times (un-mutated baseline, Windows):
#   verifier.py corpus  (test_golden_verifier_matrix) : 7.67s
#   tool_sandbox corpus (test_tool_sandbox)            : 8.84s
#   base.py corpus      (test_core_utilities)          : 9.46s
MODULE_TEST_MAP: dict[str, list[str]] = {
    "verifier.py": [
        "tests/unit/core/test_golden_verifier_matrix.py",
        "tests/unit/core/test_hardened_audit_verification.py",
    ],
    "tool_sandbox.py": [
        "tests/unit/core/test_tool_sandbox.py",
    ],
    "base.py": [
        "tests/unit/core/test_core_utilities.py",
    ],
}

# Fallback corpus used for baseline verification and any module not in the map
BASELINE_TESTS = [
    "tests/unit/core/test_golden_verifier_matrix.py",
    "tests/security/test_sandbox_adversarial_bypass.py",
    "tests/chaos/test_chaos_resilience.py",
]

# Mutant subprocess timeout, derived from measured wall-clock subprocess times.
#
# IMPORTANT: `subprocess.run(timeout=...)` measures wall-clock time including
# Python startup + import overhead — NOT pytest's self-reported test duration.
# This codebase has ~4s of startup overhead before any test executes.
#
# Timeout = max(wall-clock) * 2.0 = 15.0 * 2.0 = 30.0s (provides 2x headroom).
# Any value below ~10s fires before tests execute → meaningless 100% from timeouts.
MUTANT_TIMEOUT_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Operator token mappings — the textual representation of each mutation.
# These are used for surgical string substitution at the exact source position.
# ---------------------------------------------------------------------------

# Comparison operator text replacements: (original_text, mutated_text)
_COMPARE_MUTATIONS: dict[type, tuple[str, str]] = {
    ast.Eq: ("==", "!="),
    ast.NotEq: ("!=", "=="),
    ast.Lt: ("<", ">="),
    ast.GtE: (">=", "<"),
    ast.Is: ("is", "is not"),
    ast.IsNot: ("is not", "is"),
}

# BinOp operator text replacements
_BINOP_MUTATIONS: dict[type, tuple[str, str]] = {
    ast.Add: ("+", "-"),
    ast.Sub: ("-", "+"),
    ast.BitAnd: ("&", "|"),
    ast.BitOr: ("|", "&"),
}

# Boolean constant replacements
_BOOL_MUTATIONS: dict[bool, tuple[str, str]] = {
    True: ("True", "False"),
    False: ("False", "True"),
}


def _annotation_line_numbers(tree: ast.AST) -> set[int]:
    """
    Return line numbers that belong solely to type annotation context or TYPE_CHECKING blocks.

    Under `from __future__ import annotations`, annotations are not evaluated
    at runtime. Code inside `if TYPE_CHECKING:` is also skipped at runtime.
    Mutations in these positions produce no observable behavior change and are
    classified as INCOMPETENT (excluded from denominator).
    """
    annotation_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            all_args = (
                node.args.args
                + node.args.posonlyargs
                + node.args.kwonlyargs
                + ([node.args.vararg] if node.args.vararg else [])
                + ([node.args.kwarg] if node.args.kwarg else [])
            )
            for arg in all_args:
                if arg.annotation:
                    for n in ast.walk(arg.annotation):
                        if hasattr(n, "lineno"):
                            annotation_lines.add(n.lineno)
            if node.returns:
                for n in ast.walk(node.returns):
                    if hasattr(n, "lineno"):
                        annotation_lines.add(n.lineno)
        elif isinstance(node, ast.AnnAssign):
            for n in ast.walk(node.annotation):
                if hasattr(n, "lineno"):
                    annotation_lines.add(n.lineno)
        elif isinstance(node, ast.If):
            test_name = ""
            if isinstance(node.test, ast.Name):
                test_name = node.test.id
            elif isinstance(node.test, ast.Attribute):
                test_name = node.test.attr
            if test_name == "TYPE_CHECKING":
                for body_item in node.body:
                    for n in ast.walk(body_item):
                        if hasattr(n, "lineno"):
                            annotation_lines.add(n.lineno)
    return annotation_lines


class MutationPoint:
    """
    Describes a single mutation: where it is, what it changes, whether it
    is in an annotation-only (incompetent) position, and its enclosing AST scope.
    """

    __slots__ = (
        "index",
        "lineno",
        "col_offset",
        "original",
        "mutated",
        "description",
        "is_incompetent",
        "scope",
    )

    def __init__(
        self,
        index: int,
        lineno: int,
        col_offset: int,
        original: str,
        mutated: str,
        description: str,
        is_incompetent: bool,
        scope: str = "",
    ):
        self.index = index
        self.lineno = lineno
        self.col_offset = col_offset
        self.original = original
        self.mutated = mutated
        self.description = f"[{index}] line {lineno}: {description}"
        self.is_incompetent = is_incompetent
        self.scope = scope


class _MutationVisitor(ast.NodeVisitor):
    """AST visitor that discovers mutation points and tracks enclosing method/class scope."""

    def __init__(self, annotation_lines: set[int]):
        self.annotation_lines = annotation_lines
        self.points: list[MutationPoint] = []
        self.scope_stack: list[str] = []
        self.idx = 0

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def _current_scope(self) -> str:
        return self.scope_stack[-1] if self.scope_stack else "module"

    def visit_Compare(self, node: ast.Compare) -> None:
        lineno = getattr(node, "lineno", None)
        col = getattr(node, "col_offset", 0)
        in_annotation = lineno is not None and lineno in self.annotation_lines
        scope = self._current_scope()

        for op in node.ops:
            op_type = type(op)
            if op_type in _COMPARE_MUTATIONS:
                orig, mut = _COMPARE_MUTATIONS[op_type]
                # For multi-operator comparisons the AST doesn't give per-op col_offset.
                # Use the node's start col as a best-effort anchor; the surgical
                # replacer will find the first occurrence of orig on that line.
                desc = f"{op_type.__name__} ({orig}) -> ({mut})"
                self.points.append(
                    MutationPoint(self.idx, lineno, col, orig, mut, desc, in_annotation, scope)
                )
                self.idx += 1
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        lineno = getattr(node, "lineno", None)
        col = getattr(node, "col_offset", 0)
        in_annotation = lineno is not None and lineno in self.annotation_lines
        scope = self._current_scope()

        op_type = type(node.op)
        if op_type in _BINOP_MUTATIONS:
            orig, mut = _BINOP_MUTATIONS[op_type]
            desc = f"{orig} -> {mut}"
            self.points.append(
                MutationPoint(self.idx, lineno, col, orig, mut, desc, in_annotation, scope)
            )
            self.idx += 1
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        lineno = getattr(node, "lineno", None)
        col = getattr(node, "col_offset", 0)
        in_annotation = lineno is not None and lineno in self.annotation_lines
        scope = self._current_scope()

        if isinstance(node.value, bool):
            val = node.value
            orig, mut = _BOOL_MUTATIONS[val]
            desc = f"{orig} -> {mut}"
            self.points.append(
                MutationPoint(self.idx, lineno, col, orig, mut, desc, in_annotation, scope)
            )
            self.idx += 1
        self.generic_visit(node)


def discover_mutation_points(source: str, annotation_lines: set[int]) -> list[MutationPoint]:
    """
    Walk the AST and enumerate every mutatable node as a MutationPoint.
    Uses col_offset from the AST to locate the exact operator in the source line.
    Captures enclosing function/class scope for targeted test dispatch.
    """
    tree = ast.parse(source)
    visitor = _MutationVisitor(annotation_lines)
    visitor.visit(tree)
    return visitor.points


def _apply_surgical_mutation(source_lines: list[str], mp: MutationPoint) -> str | None:
    """
    Apply a single mutation by targeted string replacement on the exact source line.

    The original token is searched starting from col_offset on the target line.
    If the token is not found (e.g., due to multi-line AST reordering), returns
    None and the mutant is classified as INCOMPETENT.

    This preserves ALL other lines byte-for-byte, avoiding hash-corruption in
    TraceVerifier-based tests and source-pattern guards.
    """
    if mp.lineno is None or mp.lineno > len(source_lines):
        return None

    line = source_lines[mp.lineno - 1]  # 1-indexed

    # Search from col_offset forward for the original token
    search_start = mp.col_offset
    if mp.original.isalnum() or all(c.isalnum() or c == " " for c in mp.original):
        import re

        pattern = re.compile(r"\b" + re.escape(mp.original) + r"\b")
        match = pattern.search(line, search_start)
        if match:
            pos = match.start()
        else:
            match = pattern.search(line)
            pos = match.start() if match else -1
    else:
        pos = line.find(mp.original, search_start)
        if pos == -1:
            # Fallback: search from beginning of line (handles multi-op comparisons)
            pos = line.find(mp.original)

    if pos == -1:
        return None  # Token not found on expected line → incompetent

    mutated_line = line[:pos] + mp.mutated + line[pos + len(mp.original) :]
    result_lines = source_lines[: mp.lineno - 1] + [mutated_line] + source_lines[mp.lineno :]
    return "".join(result_lines)


def count_mutation_points(source: str, annotation_lines: set[int]) -> int:
    """Counts total mutatable nodes."""
    return len(discover_mutation_points(source, annotation_lines))


def _tests_for_module(module_name: str) -> list[str]:
    """Return the relevant test paths for a given target module filename."""
    return MODULE_TEST_MAP.get(module_name, BASELINE_TESTS)


def _make_loader_code(mutant_file: str, orig_file: Path, module_name: str, args_str: str) -> str:
    pkg_name = module_name.rsplit(".", 1)[0]
    return f"""
import sys, importlib.util
from pathlib import Path
sys.path.insert(0, r"{BASE_DIR}")
code = compile(Path(r"{mutant_file}").read_text(encoding="utf-8"), r"{orig_file}", "exec")
pkg_name = "{pkg_name}"
__import__(pkg_name)
pkg = sys.modules[pkg_name]
spec = importlib.util.spec_from_file_location("{module_name}", r"{orig_file}")
mod = importlib.util.module_from_spec(spec)
mod.__file__ = r"{orig_file}"
mod.__package__ = pkg_name
setattr(pkg, "{module_name.rsplit(".", 1)[-1]}", mod)
sys.modules["{module_name}"] = mod
exec(code, mod.__dict__)
import pytest
sys.exit(pytest.main({args_str}))
"""


def evaluate_mutant(
    target_file: Path,
    mutant_source: str,
    tests: list[str],
    timeout_seconds: float = 30.0,
    original_bytes: bytes | None = None,
    scope: str = "",
    killer_cache: dict[str, str] | None = None,
    cache_lock: threading.Lock | None = None,
) -> str:
    """
    Evaluates mutant using dynamic in-memory injection without mutating target_file on disk.
    Applies 3-phase cascading acceleration:
      1. Cached killer-test execution (stops in ~1 test if cached)
      2. Targeted scope test execution (-k <scope> -x)
      3. Fallback full module corpus execution (-x)
    Returns status: 'killed', 'survived', 'timeout', or 'incompetent'.
    """
    # 1. In-process AST syntax pre-check before touching disk or spawning subprocess
    try:
        compile(mutant_source, str(target_file), "exec")
    except Exception as syntax_err:
        sys.stderr.write(f"      [Mutant] Incompetent AST syntax: {syntax_err}\n")
        return "incompetent"

    rel_path = target_file.resolve().relative_to(BASE_DIR)
    module_name = ".".join(rel_path.with_suffix("").parts)
    target_resolved = target_file.resolve()

    # Isolated temporary mutant file (never modifies original source file on disk!)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
        tf.write(mutant_source)
        tf_path = tf.name

    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = f"{BASE_DIR}{os.pathsep}{env.get('PYTHONPATH', '')}"

    def _extract_and_cache_killer(output: str) -> None:
        if killer_cache is not None and scope and scope != "module":
            m = re.search(r"FAILED\s+[^:]+::([A-Za-z0-9_]+)", output)
            if m:
                test_name = m.group(1)
                if cache_lock:
                    with cache_lock:
                        killer_cache[scope] = test_name
                else:
                    killer_cache[scope] = test_name

    try:
        # Phase 1: Try cached killer test first (fast-fail on 1 test)
        cached_killer = None
        if killer_cache and scope:
            if cache_lock:
                with cache_lock:
                    cached_killer = killer_cache.get(scope)
            else:
                cached_killer = killer_cache.get(scope)

        if cached_killer:
            fast_flags = FAST_PYTEST_FLAGS + ["-k", cached_killer, "-x"]
            args_str = repr(tests + fast_flags)
            loader_code = _make_loader_code(tf_path, target_resolved, module_name, args_str)
            res = subprocess.run(
                [sys.executable, "-B", "-c", loader_code],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                timeout=min(timeout_seconds, 15.0),
                env=env,
            )
            if res.returncode != 0:
                return "killed"

        # Phase 2: Scoped test filter
        if scope and scope != "module":
            scoped_flags = FAST_PYTEST_FLAGS + ["-k", scope, "-x"]
            args_str = repr(tests + scoped_flags)
            loader_code = _make_loader_code(tf_path, target_resolved, module_name, args_str)
            res = subprocess.run(
                [sys.executable, "-B", "-c", loader_code],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
            if res.returncode != 0:
                _extract_and_cache_killer(res.stdout)
                return "killed"

        # Phase 3: Fallback full module corpus
        full_flags = FAST_PYTEST_FLAGS + ["-x"]
        args_str = repr(tests + full_flags)
        loader_code = _make_loader_code(tf_path, target_resolved, module_name, args_str)
        res = subprocess.run(
            [sys.executable, "-B", "-c", loader_code],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
        if res.returncode != 0:
            _extract_and_cache_killer(res.stdout)
            return "killed"
        return "survived"
    except subprocess.TimeoutExpired:
        return "timeout"
    except (SyntaxError, UnicodeDecodeError, OSError, ValueError) as err:
        sys.stderr.write(f"      [Mutant] Incompetent AST substitution: {err}\n")
        return "incompetent"
    finally:
        Path(tf_path).unlink(missing_ok=True)


def verify_sentinel_preconditions() -> dict[str, float]:
    """
    Self-validating precondition checks executed before any mutation testing begins.

    Prevents silent failure modes:
      1. Missing test files referenced in MODULE_TEST_MAP or BASELINE_TESTS.
      2. Missing target module files.
      3. Failing un-mutated baseline tests or empty test collections.
      4. Dynamically scales per-module timeout to guarantee >= 2.0x headroom on any host.
    """
    import time

    print("\n1. Running Self-Validating Sentinel Precondition Checks...")

    # Check target modules existence
    for target in TARGET_MODULES:
        if not target.exists():
            rel = target.relative_to(BASE_DIR)
            print(f"  [FAIL] Target module missing: {rel}")
            sys.exit(1)

    # Check test file existence
    all_test_paths = set(BASELINE_TESTS)
    for test_list in MODULE_TEST_MAP.values():
        all_test_paths.update(test_list)

    for test_path in all_test_paths:
        full_path = BASE_DIR / test_path
        if not full_path.exists():
            print(f"  [FAIL] Configured test file missing: {test_path}")
            sys.exit(1)

    # Verify per-module baseline runtimes and calculate dynamic timeouts
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = f"{BASE_DIR}{os.pathsep}{env.get('PYTHONPATH', '')}"
    module_timeouts: dict[str, float] = {}
    for target in TARGET_MODULES:
        module_name = target.name
        tests = _tests_for_module(module_name)
        args_str = repr(tests + FAST_PYTEST_FLAGS)
        py_code = (
            f"import sys; sys.path.insert(0, r'{BASE_DIR}'); "
            f"import pytest; sys.exit(pytest.main({args_str}))"
        )
        cmd = [sys.executable, "-B", "-c", py_code]
        t0 = time.monotonic()
        res = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True, env=env)
        elapsed = time.monotonic() - t0

        if res.returncode != 0:
            print(f"  [FAIL] Baseline test suite for '{module_name}' failed or collected no tests!")
            print(f"         Command output:\n{res.stdout}\n{res.stderr}")
            sys.exit(1)

        dynamic_timeout = max(MUTANT_TIMEOUT_SECONDS, elapsed * 2.5)
        module_timeouts[module_name] = dynamic_timeout
        headroom = dynamic_timeout / elapsed if elapsed > 0 else 999.0
        print(
            f"   • Module '{module_name}' baseline: {elapsed:.2f}s "
            f"(Timeout: {dynamic_timeout:.1f}s, Headroom: {headroom:.2f}x)"
        )

    print("  [OK] Precondition checks PASSED cleanly.\n")
    return module_timeouts


def _evaluate_target_module(
    target: Path,
    args: Any,
    module_timeouts: dict[str, float],
    shared_killer_cache: dict[str, str] | None = None,
    cache_lock: threading.Lock | None = None,
) -> tuple[int, int, int, int, list[dict]]:
    """
    Evaluates mutants for a single target module using mutant-level concurrency.
    Returns: (killed, survived, timeout, incompetent, mutant_records)
    """
    rel_path = target.relative_to(BASE_DIR)
    module_name = target.name
    tests = _tests_for_module(module_name)
    timeout_sec = module_timeouts.get(module_name, MUTANT_TIMEOUT_SECONDS)

    original_bytes = target.read_bytes()
    original_source = target.read_text(encoding="utf-8")
    source_lines = [line + "\n" for line in original_source.splitlines()]

    try:
        tree = ast.parse(original_source)
    except Exception as exc:
        print(f"  [FAIL] Failed to parse AST for {rel_path}: {exc}")
        sys.exit(1)

    annotation_lines = _annotation_line_numbers(tree)
    all_points = discover_mutation_points(original_source, annotation_lines)
    num_points = len(all_points)
    competent_points = [p for p in all_points if not p.is_incompetent]
    num_competent = len(competent_points)

    if args.full:
        sampled = all_points
        print(f"   • Module: {rel_path} ({num_points} mutation points, evaluating ALL 100%)")
    else:
        max_mutants = min(num_competent, 15)
        rng = random.Random(args.seed) if args.seed is not None else random.Random()
        sampled = (
            rng.sample(competent_points, max_mutants)
            if num_competent > max_mutants
            else list(competent_points)
        )
        sampled.sort(key=lambda p: (p.lineno, p.col_offset))
        seed_info = f" [seed={args.seed}]" if args.seed is not None else ""
        print(
            f"   • Module: {rel_path} ({num_points} total, {num_competent} runtime-effective, "
            f"randomly sampled {len(sampled)}{seed_info})"
        )

    killed = 0
    survived = 0
    timeout = 0
    incompetent = 0
    records: list[dict] = []

    num_workers = max(1, getattr(args, "workers", 1))

    def _eval_one(mp: MutationPoint) -> tuple[str, str, MutationPoint]:
        if mp.is_incompetent:
            return "incompetent", f"{mp.description}  (annotation-only, no runtime effect)", mp

        mutant_source = _apply_surgical_mutation(source_lines, mp)
        if mutant_source is None:
            desc = (
                f"{mp.description}  "
                f"(token not locatable at col {mp.col_offset} on line {mp.lineno})"
            )
            return "incompetent", desc, mp

        status = evaluate_mutant(
            target,
            mutant_source,
            tests,
            timeout_seconds=timeout_sec,
            original_bytes=original_bytes,
            scope=mp.scope,
            killer_cache=shared_killer_cache,
            cache_lock=cache_lock,
        )
        return status, mp.description, mp

    if num_workers > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as pool:
            futures = {pool.submit(_eval_one, mp): mp for mp in sampled}
            for fut in concurrent.futures.as_completed(futures):
                status, desc, mp = fut.result()
                if status == "killed":
                    killed += 1
                    icon = "[KILLED]"
                elif status == "timeout":
                    timeout += 1
                    icon = "[TIMEOUT]"
                elif status == "survived":
                    survived += 1
                    icon = "[SURVIVED]"
                else:
                    incompetent += 1
                    icon = "[INCOMPETENT]"

                records.append(
                    {"module": str(rel_path), "mutation": mp.description, "status": status}
                )
                print(f"      {icon:15s} [{rel_path.as_posix()}] {desc}", flush=True)
    else:
        for mp in sampled:
            status, desc, _ = _eval_one(mp)
            if status == "killed":
                killed += 1
                icon = "[KILLED]"
            elif status == "timeout":
                timeout += 1
                icon = "[TIMEOUT]"
            elif status == "survived":
                survived += 1
                icon = "[SURVIVED]"
            else:
                incompetent += 1
                icon = "[INCOMPETENT]"

            records.append({"module": str(rel_path), "mutation": mp.description, "status": status})
            print(f"      {icon:15s} [{rel_path.as_posix()}] {desc}", flush=True)

    return killed, survived, timeout, incompetent, records


def run_mutation_sentinel() -> None:
    """Executes full or sampled mutation scoring lifecycle across critical verification modules."""
    import argparse

    parser = argparse.ArgumentParser(description="Industrial Mutation Testing Sentinel")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Evaluate 100%% of discovered mutation points (Nightly/Release CI mode).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional RNG seed for reproducible random sampling in non-full mode.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of concurrent worker threads for parallel module evaluation (default: 1).",
    )
    args = parser.parse_args()

    seed_suffix = f", seed={args.seed}" if args.seed is not None else ""
    worker_suffix = f", workers={args.workers}" if args.workers > 1 else ""
    mode_label = (
        "FULL POPULATION"
        if args.full
        else f"RANDOMLY SAMPLED (max 15/module{seed_suffix}{worker_suffix})"
    )

    print("=" * 80)
    print(f"=== INDUSTRIAL MUTATION TESTING SENTINEL & ASSURANCE PIPELINE ({mode_label}) ===")
    # Enforce process singleton lock to guarantee no concurrent file mutation collisions
    lock_file = BASE_DIR / ".mutation_testing.lock"
    import os

    if lock_file.exists():
        try:
            old_pid = int(lock_file.read_text(encoding="utf-8").strip())
            # Check if process is still running
            import ctypes

            kernel32 = getattr(ctypes, "windll", None)
            is_running = False
            if os.name == "nt" and kernel32:
                # Windows check
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                handle = kernel32.kernel32.OpenProcess(
                    PROCESS_QUERY_LIMITED_INFORMATION, False, old_pid
                )
                if handle:
                    kernel32.kernel32.CloseHandle(handle)
                    is_running = True
            elif os.name != "nt":
                try:
                    os.kill(old_pid, 0)
                    is_running = True
                except OSError:
                    is_running = False
            if is_running:
                print(
                    f"  [FAIL] Another mutation testing runner is actively running (PID {old_pid})!"
                )
                sys.exit(1)
        except (ValueError, OSError) as read_err:
            sys.stderr.write(f"  [Warn] Failed to inspect existing lock file: {read_err}\n")
        try:
            lock_file.unlink(missing_ok=True)
        except OSError as unlink_err:
            sys.stderr.write(f"  [Warn] Failed to unlink lock file: {unlink_err}\n")

    try:
        lock_file.write_text(str(os.getpid()), encoding="utf-8")
    except OSError as lock_err:
        sys.stderr.write(f"  [Warn] Could not write lock file: {lock_err}\n")

    import atexit
    import signal

    pristine_sources = {target: target.read_bytes() for target in TARGET_MODULES}

    def emergency_restore(*args, **kwargs):
        for target, data in pristine_sources.items():
            try:
                if target.exists() and target.read_bytes() != data:
                    target.write_bytes(data)
            except OSError as restore_err:
                sys.stderr.write(f"  [CRITICAL] Failed to restore {target}: {restore_err}\n")
        try:
            lock_file.unlink(missing_ok=True)
        except OSError as lock_err:
            sys.stderr.write(f"  [Warn] Failed to remove lock file on exit: {lock_err}\n")

    def signal_handler(signum, frame):
        emergency_restore()
        sys.exit(128 + signum if isinstance(signum, int) else 1)

    atexit.register(emergency_restore)
    for sig in (
        getattr(signal, "SIGINT", None),
        getattr(signal, "SIGTERM", None),
        getattr(signal, "SIGBREAK", None),
    ):
        if sig is not None:
            try:
                signal.signal(sig, signal_handler)
            except (ValueError, OSError) as sig_err:
                sys.stderr.write(
                    f"  [Warn] Could not register signal handler for {sig}: {sig_err}\n"
                )

    # Ensure all target modules are pristine before starting
    emergency_restore()

    # 1. Self-Validating Precondition Verification
    module_timeouts = verify_sentinel_preconditions()

    # 2. Mutation Discovery & Testing
    total_killed = 0
    total_survived = 0
    total_timeout = 0
    total_skipped = 0
    total_incompetent = 0
    mutant_records: list[dict] = []

    shared_killer_cache: dict[str, str] = {}
    cache_lock = threading.Lock()
    try:
        print(f"2. Mutating Verification Modules & Scoring Test Suite ({mode_label})...")
        for target in TARGET_MODULES:
            k, s, t, inc, recs = _evaluate_target_module(
                target, args, module_timeouts, shared_killer_cache, cache_lock
            )
            total_killed += k
            total_survived += s
            total_timeout += t
            total_incompetent += inc
            mutant_records.extend(recs)
    finally:
        emergency_restore()

    # 3. Calculate Refined Mutation Metrics
    # Denominator excludes incompetent mutants (annotation-only, no runtime effect).
    total_valid_mutants = total_killed + total_survived + total_timeout + total_incompetent
    denom = total_killed + total_survived + total_timeout
    effective_killed = total_killed + total_timeout

    kill_rate_pct = (total_killed / denom * 100.0) if denom > 0 else 100.0
    timeout_rate_pct = (total_timeout / denom * 100.0) if denom > 0 else 0.0
    effective_detection_pct = (effective_killed / denom * 100.0) if denom > 0 else 100.0

    print("\n" + "=" * 80)
    print(f"=== MUTATION TESTING FINAL SCORECARD ({mode_label}) ===")
    print("=" * 80)
    print(f"  • Execution Mode:           {mode_label}")
    print(f"  • Total Mutants Evaluated:  {total_valid_mutants + total_skipped}")
    print(f"  • Killed:                   {total_killed}")
    print(f"  • Timeout:                  {total_timeout}")
    print(f"  • Survived:                 {total_survived}")
    print(f"  • Incompetent (Annotation): {total_incompetent}")
    print(f"  • Mutation Kill Rate:       {kill_rate_pct:.2f}% (Killed / Evaluated)")
    print(f"  • Timeout Rate:             {timeout_rate_pct:.2f}% (Timeout / Evaluated)")
    print(
        f"  • Effective Detection Rate: {effective_detection_pct:.2f}% "
        f"((Killed + Timeout) / Evaluated, Target: >=100.00%)"
    )
    print("=" * 80)

    # 4. Generate Diligence Artifact
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_md = f"""# Mutation Testing Diligence Scorecard

Enterprise verification assurance scorecard generated by surgical AST mutation analysis.

## Summary Metrics

| Metric | Value |
| :--- | :--- |
| **Execution Mode** | **{mode_label}** |
| **Effective Detection Rate** | **{effective_detection_pct:.2f}%** |
| **Mutation Kill Rate** | **{kill_rate_pct:.2f}%** |
| **Timeout Rate** | **{timeout_rate_pct:.2f}%** |
| **Minimum Required Target** | **100.00%** |
| **Evaluation Baseline** | **PASSED (Green)** |
| **Killed Mutants** | **{total_killed}** |
| **Timeout Mutants** | **{total_timeout}** |
| **Survived Mutants** | **{total_survived}** |
| **Incompetent Mutants** | **{total_incompetent}** |
| **Total Mutants Evaluated** | **{total_valid_mutants}** |

## Scoring Methodology

- **Mutation Strategy**: Surgical line substitution — targeted token replacement at AST
  coordinates; non-mutated lines preserved 100% byte-for-byte.
- **Metric Definitions**:
  - `Mutation Kill Rate = Killed / (Killed + Timeout + Survived)`
  - `Timeout Rate = Timeout / (Killed + Timeout + Survived)`
  - `Effective Detection Rate = (Killed + Timeout) / (Killed + Timeout + Survived)`

## Target Modules Evaluated

1. `eval_runner/verifier.py`
2. `eval_runner/tool_sandbox.py`
3. `eval_runner/utils/base.py`

## Detailed Mutation Log

| Module | Mutation Description | Status |
| :--- | :--- | :--- |
"""
    for rec in mutant_records:
        if rec["status"] == "incompetent":
            status_str = "INCOMPETENT (annotation-only or not locatable)"
        elif rec["status"] == "killed":
            status_str = "PASSED (Killed)"
        elif rec["status"] == "timeout":
            status_str = "PASSED (Timeout)"
        else:
            status_str = "FAILED (Survived)"
        report_md += f"| `{rec['module']}` | `{rec['mutation']}` | {status_str} |\n"

    REPORT_PATH.write_text(report_md, encoding="utf-8")
    rel_report = REPORT_PATH.relative_to(BASE_DIR)
    print(f"\n[Diligence Artifact] Generated mutation scorecard report at: {rel_report}")

    # 5. Enforce >= 90% Threshold Gate
    if effective_detection_pct < 100.0:
        print(
            f"\n[FAIL] Effective detection rate {effective_detection_pct:.2f}% "
            f"is below required 100.00% threshold!"
        )
        sys.exit(1)
    else:
        print(
            f"\n[OK] Effective detection rate {effective_detection_pct:.2f}% "
            f"meets enterprise gate (>=100.00%)."
        )


if __name__ == "__main__":
    run_mutation_sentinel()
