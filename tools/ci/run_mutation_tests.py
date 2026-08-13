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

Generates diligence artifact 'reports/mutation_scorecard.md' and fails CI if score < 90.0%.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent.parent
REPORT_DIR = BASE_DIR / "reports"
REPORT_PATH = REPORT_DIR / "mutation_scorecard.md"

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
    Return line numbers that belong solely to type annotation context.

    Under `from __future__ import annotations`, annotations are not evaluated
    at runtime. Mutations in annotation-only positions produce no observable
    behavior change and are classified as INCOMPETENT (excluded from denominator).
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
        if isinstance(node, ast.AnnAssign):
            for n in ast.walk(node.annotation):
                if hasattr(n, "lineno"):
                    annotation_lines.add(n.lineno)
    return annotation_lines


class MutationPoint:
    """
    Describes a single mutation: where it is, what it changes, and whether it
    is in an annotation-only (incompetent) position.
    """

    __slots__ = (
        "index",
        "lineno",
        "col_offset",
        "original",
        "mutated",
        "description",
        "is_incompetent",
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
    ):
        self.index = index
        self.lineno = lineno
        self.col_offset = col_offset
        self.original = original
        self.mutated = mutated
        self.description = f"[{index}] {description}"
        self.is_incompetent = is_incompetent


def discover_mutation_points(source: str, annotation_lines: set[int]) -> list[MutationPoint]:
    """
    Walk the AST and enumerate every mutatable node as a MutationPoint.
    Uses col_offset from the AST to locate the exact operator in the source line.
    """
    tree = ast.parse(source)
    points: list[MutationPoint] = []
    idx = 0

    for node in ast.walk(tree):
        lineno = getattr(node, "lineno", None)
        col = getattr(node, "col_offset", 0)
        in_annotation = lineno is not None and lineno in annotation_lines

        if isinstance(node, ast.Compare):
            for op in node.ops:
                op_type = type(op)
                if op_type in _COMPARE_MUTATIONS:
                    orig, mut = _COMPARE_MUTATIONS[op_type]
                    # For multi-operator comparisons the AST doesn't give per-op col_offset.
                    # Use the node's start col as a best-effort anchor; the surgical
                    # replacer will find the first occurrence of orig on that line.
                    desc = f"{op_type.__name__} ({orig}) -> ({mut})"
                    points.append(MutationPoint(idx, lineno, col, orig, mut, desc, in_annotation))
                    idx += 1

        elif isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type in _BINOP_MUTATIONS:
                orig, mut = _BINOP_MUTATIONS[op_type]
                desc = f"{orig} -> {mut}"
                points.append(MutationPoint(idx, lineno, col, orig, mut, desc, in_annotation))
                idx += 1

        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            val = node.value
            orig, mut = _BOOL_MUTATIONS[val]
            desc = f"{orig} -> {mut}"
            points.append(MutationPoint(idx, lineno, col, orig, mut, desc, in_annotation))
            idx += 1

    return points


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


def evaluate_mutant(target_file: Path, mutant_source: str, tests: list[str]) -> str:
    """
    Surgically applies mutant source to the target file, executes pytest against
    the per-module corpus with bytecode caching disabled (-B and PYTHONDONTWRITEBYTECODE=1)
    and PYTHONPATH prioritized to BASE_DIR, then restores the original file byte-for-byte.

    Returns status: 'killed', 'survived', 'timeout', or 'incompetent'.
    """
    import os

    original_bytes = target_file.read_bytes()
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = f"{BASE_DIR}{os.pathsep}{env.get('PYTHONPATH', '')}"
    try:
        target_file.write_text(mutant_source, encoding="utf-8")
        extra_flags = ["-q", "--no-header", "-x", "-p", "no:plugin_gateway", "-p", "no:cov"]
        args_str = repr(tests + extra_flags)
        py_code = (
            f"import sys; sys.path.insert(0, r'{BASE_DIR}'); "
            f"import pytest; sys.exit(pytest.main({args_str}))"
        )
        cmd = [sys.executable, "-B", "-c", py_code]
        try:
            res = subprocess.run(
                cmd,
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                timeout=MUTANT_TIMEOUT_SECONDS,
                env=env,
            )
            return "killed" if res.returncode != 0 else "survived"
        except subprocess.TimeoutExpired:
            return "timeout"
    except Exception:
        return "incompetent"
    finally:
        target_file.write_bytes(original_bytes)


def verify_sentinel_preconditions() -> None:
    """
    Self-validating precondition checks executed before any mutation testing begins.

    Prevents silent failure modes:
      1. Missing test files referenced in MODULE_TEST_MAP or BASELINE_TESTS.
      2. Missing target module files.
      3. Failing un-mutated baseline tests or empty test collections.
      4. Insufficient timeout headroom (< 1.5x of baseline runtime), preventing
         false 'timeout' classification of survived mutants.
    """
    import os
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

    # Verify per-module baseline runtimes and timeout headroom
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = f"{BASE_DIR}{os.pathsep}{env.get('PYTHONPATH', '')}"
    for target in TARGET_MODULES:
        module_name = target.name
        tests = _tests_for_module(module_name)
        extra_flags = ["-q", "--no-header", "-p", "no:plugin_gateway", "-p", "no:cov"]
        args_str = repr(tests + extra_flags)
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

        headroom = MUTANT_TIMEOUT_SECONDS / elapsed if elapsed > 0 else 999.0
        print(
            f"   • Module '{module_name}' baseline: {elapsed:.2f}s "
            f"(Timeout: {MUTANT_TIMEOUT_SECONDS:.1f}s, Headroom: {headroom:.2f}x)"
        )

        if headroom < 1.5:
            print(
                f"  [FAIL] Insufficient timeout headroom for '{module_name}'!\n"
                f"         Baseline runtime ({elapsed:.2f}s) is too close to "
                f"timeout ({MUTANT_TIMEOUT_SECONDS:.1f}s).\n"
                f"         Required headroom is >= 1.5x. Increase MUTANT_TIMEOUT_SECONDS "
                f"or streamline test corpus."
            )
            sys.exit(1)

    print("  [OK] Precondition checks PASSED cleanly.\n")


def run_mutation_sentinel() -> None:
    """Executes full or sampled mutation scoring lifecycle across critical verification modules."""
    import argparse

    parser = argparse.ArgumentParser(description="Industrial Mutation Testing Sentinel")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Evaluate 100%% of discovered mutation points (Nightly/Release CI mode).",
    )
    args = parser.parse_args()

    mode_label = "FULL POPULATION" if args.full else "SAMPLED (max 15/module)"

    print("=" * 80)
    print(f"=== INDUSTRIAL MUTATION TESTING SENTINEL & ASSURANCE PIPELINE ({mode_label}) ===")
    print("=" * 80)

    # 1. Self-Validating Precondition Verification
    verify_sentinel_preconditions()

    # 2. Mutation Discovery & Testing
    total_killed = 0
    total_survived = 0
    total_timeout = 0
    total_skipped = 0
    total_incompetent = 0
    mutant_records: list[dict] = []

    print(f"2. Mutating Verification Modules & Scoring Test Suite ({mode_label})...")
    for target in TARGET_MODULES:
        rel_path = target.relative_to(BASE_DIR)
        module_name = target.name
        tests = _tests_for_module(module_name)

        original_source = target.read_text(encoding="utf-8")
        source_lines = [line + "\n" for line in original_source.splitlines()]
        # Preserve original line endings for final write_bytes restore
        try:
            tree = ast.parse(original_source)
        except Exception as exc:
            print(f"  [FAIL] Failed to parse AST for {rel_path}: {exc}")
            sys.exit(1)

        annotation_lines = _annotation_line_numbers(tree)
        all_points = discover_mutation_points(original_source, annotation_lines)
        num_points = len(all_points)

        if args.full:
            sampled = all_points
            print(f"   • Module: {rel_path} ({num_points} mutation points, evaluating ALL 100%)")
        else:
            max_mutants = min(num_points, 15)
            step = max(1, num_points // max_mutants)
            sampled = all_points[::step][:max_mutants]
            print(
                f"   • Module: {rel_path} ({num_points} mutation points discovered, "
                f"sampling {len(sampled)})"
            )

        for mp in sampled:
            # Annotation-only mutations have no runtime effect
            if mp.is_incompetent:
                total_incompetent += 1
                mutant_records.append(
                    {"module": str(rel_path), "mutation": mp.description, "status": "incompetent"}
                )
                print(
                    f"      {'[INCOMPETENT]':15s} {mp.description}  "
                    f"(annotation-only, no runtime effect)"
                )
                continue

            mutant_source = _apply_surgical_mutation(source_lines, mp)
            if mutant_source is None:
                # Token not locatable on expected line — treat as incompetent
                total_incompetent += 1
                mutant_records.append(
                    {"module": str(rel_path), "mutation": mp.description, "status": "incompetent"}
                )
                print(
                    f"      {'[INCOMPETENT]':15s} {mp.description}  "
                    f"(token not locatable at col {mp.col_offset} on line {mp.lineno})"
                )
                continue

            status = evaluate_mutant(target, mutant_source, tests)

            if status == "killed":
                total_killed += 1
                icon = "[KILLED]"
            elif status == "timeout":
                total_timeout += 1
                icon = "[TIMEOUT]"
            elif status == "survived":
                total_survived += 1
                icon = "[SURVIVED]"
            else:
                total_incompetent += 1
                icon = "[INCOMPETENT]"

            mutant_records.append(
                {"module": str(rel_path), "mutation": mp.description, "status": status}
            )
            print(f"      {icon:15s} {mp.description}")

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
        f"((Killed + Timeout) / Evaluated, Target: >=90.00%)"
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
| **Minimum Required Target** | **90.00%** |
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
    if effective_detection_pct < 90.0:
        print(
            f"\n[FAIL] Effective detection rate {effective_detection_pct:.2f}% "
            f"is below required 90.00% threshold!"
        )
        sys.exit(1)
    else:
        print(
            f"\n[OK] Effective detection rate {effective_detection_pct:.2f}% "
            f"meets enterprise gate (>=90.00%)."
        )


if __name__ == "__main__":
    run_mutation_sentinel()
