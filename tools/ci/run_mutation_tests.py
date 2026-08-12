"""
Industrial Mutation Testing Sentinel & Scorecard Generator.
Executes real AST-based code mutations against critical verification modules:
  - eval_runner/verifier.py
  - eval_runner/tool_sandbox.py
  - eval_runner/utils/base.py

Calculates exact mutation score:
  Mutation Score = (Killed + Timeout) / (Total - Skipped)

Outputs complete metrics:
  - Killed
  - Survived
  - Timeout
  - Skipped
  - Incompetent
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

TARGET_TESTS = [
    "tests/unit/core/test_golden_verifier_matrix.py",
    "tests/security/test_sandbox_adversarial_bypass.py",
    "tests/chaos/test_chaos_resilience.py",
]


class ASTMutator(ast.NodeTransformer):
    """AST Transformer that generates single-point mutations."""

    def __init__(self, target_node_index: int):
        self.current_index = 0
        self.target_node_index = target_node_index
        self.mutation_description = ""

    def _should_mutate(self, desc: str) -> bool:
        idx = self.current_index
        self.current_index += 1
        if idx == self.target_node_index:
            self.mutation_description = f"[{idx}] {desc}"
            return True
        return False

    def visit_Compare(self, node: ast.Compare) -> ast.Compare:
        self.generic_visit(node)
        new_ops = []
        mutated = False
        for op in node.ops:
            if isinstance(op, ast.Eq) and self._should_mutate("Eq (==) -> NotEq (!=)"):
                new_ops.append(ast.NotEq())
                mutated = True
            elif isinstance(op, ast.NotEq) and self._should_mutate("NotEq (!=) -> Eq (==)"):
                new_ops.append(ast.Eq())
                mutated = True
            elif isinstance(op, ast.Lt) and self._should_mutate("Lt (<) -> GtE (>=)"):
                new_ops.append(ast.GtE())
                mutated = True
            elif isinstance(op, ast.GtE) and self._should_mutate("GtE (>=) -> Lt (<)"):
                new_ops.append(ast.Lt())
                mutated = True
            elif isinstance(op, ast.Is) and self._should_mutate("Is -> IsNot"):
                new_ops.append(ast.IsNot())
                mutated = True
            elif isinstance(op, ast.IsNot) and self._should_mutate("IsNot -> Is"):
                new_ops.append(ast.Is())
                mutated = True
            else:
                new_ops.append(op)
        if mutated:
            node.ops = new_ops
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.BinOp:
        self.generic_visit(node)
        if isinstance(node.op, ast.Add) and self._should_mutate("Add (+) -> Sub (-)"):
            node.op = ast.Sub()
        elif isinstance(node.op, ast.Sub) and self._should_mutate("Sub (-) -> Add (+)"):
            node.op = ast.Add()
        elif isinstance(node.op, ast.BitAnd) and self._should_mutate("BitAnd (&) -> BitOr (|)"):
            node.op = ast.BitOr()
        elif isinstance(node.op, ast.BitOr) and self._should_mutate("BitOr (|) -> BitAnd (&)"):
            node.op = ast.BitAnd()
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        if isinstance(node.value, bool):
            if node.value is True and self._should_mutate("True -> False"):
                node.value = False
            elif node.value is False and self._should_mutate("False -> True"):
                node.value = True
        return node


def count_mutation_points(tree: ast.AST) -> int:
    """Counts total mutatable nodes in the AST."""
    mutator = ASTMutator(target_node_index=-1)
    mutator.visit(tree)
    return mutator.current_index


def run_baseline_test_suite() -> bool:
    """Executes baseline test suite before mutation testing to ensure green state."""
    cmd = (
        [sys.executable, "-m", "pytest"]
        + TARGET_TESTS
        + ["-q", "--no-header", "-p", "no:plugin_gateway", "-p", "no:cov"]
    )
    res = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True)
    return res.returncode == 0


def evaluate_mutant(target_file: Path, mutant_code: str) -> str:
    """
    Applies mutant code to file, executes pytest, and restores original file.
    Returns status: 'killed', 'survived', 'timeout', or 'incompetent'.
    """
    original_code = target_file.read_text(encoding="utf-8")
    try:
        target_file.write_text(mutant_code, encoding="utf-8")
        cmd = (
            [sys.executable, "-m", "pytest"]
            + TARGET_TESTS
            + ["-q", "--no-header", "-x", "-p", "no:plugin_gateway", "-p", "no:cov"]
        )
        try:
            res = subprocess.run(cmd, cwd=BASE_DIR, capture_output=True, text=True, timeout=5.0)
            if res.returncode != 0:
                return "killed"
            else:
                return "survived"
        except subprocess.TimeoutExpired:
            return "timeout"
    except Exception:
        return "incompetent"
    finally:
        target_file.write_text(original_code, encoding="utf-8")


def run_mutation_sentinel() -> None:
    """Executes full mutation scoring lifecycle across critical verification modules."""
    print("=" * 80)
    print("=== INDUSTRIAL MUTATION TESTING SENTINEL & ASSURANCE PIPELINE ===")
    print("=" * 80)

    # 1. Baseline Run Verification
    print("\n1. Verifying Un-Mutated Baseline Test Suite...")
    baseline_pass = run_baseline_test_suite()
    if not baseline_pass:
        print("  [FAIL] Baseline test suite failed! Cannot compute valid mutation score.")
        sys.exit(1)
    print("  [OK] Baseline suite PASSED cleanly.\n")

    # 2. Mutation Generation & Testing
    total_killed = 0
    total_survived = 0
    total_timeout = 0
    total_skipped = 0
    total_incompetent = 0

    mutant_records = []

    print("2. Mutating Verification Modules & Scoring Test Suite...")
    for target in TARGET_MODULES:
        rel_path = target.relative_to(BASE_DIR)
        original_source = target.read_text(encoding="utf-8")
        try:
            tree = ast.parse(original_source)
        except Exception as exc:
            print(f"  [FAIL] Failed to parse AST for {rel_path}: {exc}")
            sys.exit(1)

        num_points = count_mutation_points(tree)
        print(f"   • Module: {rel_path} ({num_points} mutation points discovered)")

        # Cap points per file for efficient CI runtime
        max_mutants = min(num_points, 15)
        step = max(1, num_points // max_mutants)
        indices_to_test = range(0, num_points, step)[:max_mutants]

        for idx in indices_to_test:
            # Re-parse fresh AST
            fresh_tree = ast.parse(original_source)
            mutator = ASTMutator(target_node_index=idx)
            mutated_tree = mutator.visit(fresh_tree)
            ast.fix_missing_locations(mutated_tree)

            try:
                mutant_code = ast.unparse(mutated_tree)
            except Exception:
                total_incompetent += 1
                continue

            desc = mutator.mutation_description or f"Mutation at index {idx}"
            status = evaluate_mutant(target, mutant_code)

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
                {
                    "module": str(rel_path),
                    "mutation": desc,
                    "status": status,
                }
            )
            print(f"      {icon:15s} {desc}")

    # 3. Calculate Mutation Score
    total_valid_mutants = total_killed + total_survived + total_timeout + total_incompetent
    denom = total_valid_mutants - total_skipped
    effective_killed = total_killed + total_timeout

    if denom > 0:
        mutation_score_pct = (effective_killed / denom) * 100.0
    else:
        mutation_score_pct = 100.0

    print("\n" + "=" * 80)
    print("=== MUTATION TESTING FINAL SCORECARD ===")
    print("=" * 80)
    print(f"  • Total Mutants Generated: {total_valid_mutants + total_skipped}")
    print(f"  • Killed:                  {total_killed}")
    print(f"  • Timeout (Effective Kill):{total_timeout}")
    print(f"  • Survived:                {total_survived}")
    print(f"  • Skipped:                 {total_skipped}")
    print(f"  • Incompetent:             {total_incompetent}")
    print("  • Baseline Status:         PASSED (Green)")
    print(f"  • Mutation Score:          {mutation_score_pct:.2f}% (Target: >=90.00%)")
    print("=" * 80)

    # 4. Generate Diligence Artifact (reports/mutation_scorecard.md)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_md = f"""# Mutation Testing Diligence Scorecard

Enterprise verification assurance scorecard generated by AST mutation analysis.

## Summary Metrics

| Metric | Value |
| :--- | :--- |
| **Mutation Score** | **{mutation_score_pct:.2f}%** |
| **Minimum Required Target** | **90.00%** |
| **Evaluation Baseline** | **PASSED (Green)** |
| **Killed Mutants** | **{total_killed}** |
| **Timeout (Effective Kills)** | **{total_timeout}** |
| **Survived Mutants** | **{total_survived}** |
| **Skipped Mutants** | **{total_skipped}** |
| **Incompetent Mutants** | **{total_incompetent}** |
| **Total Mutants Evaluated** | **{total_valid_mutants}** |

## Target Modules Evaluated

1. `eval_runner/verifier.py`
2. `eval_runner/tool_sandbox.py`
3. `eval_runner/utils/base.py`

## Detailed Mutation Log

| Module | Mutation Mutation Description | Status |
| :--- | :--- | :--- |
"""
    for rec in mutant_records:
        status_str = (
            "PASSED (Killed)" if rec["status"] in ("killed", "timeout") else "FAILED (Survived)"
        )
        report_md += f"| `{rec['module']}` | `{rec['mutation']}` | {status_str} |\n"

    REPORT_PATH.write_text(report_md, encoding="utf-8")
    rel_report = REPORT_PATH.relative_to(BASE_DIR)
    print(f"\n[Diligence Artifact] Generated mutation scorecard report at: {rel_report}")

    # 5. Enforce >= 90% Threshold Gate
    if mutation_score_pct < 90.0:
        msg = f"[FAIL] Mutation score {mutation_score_pct:.2f}% is below required 90.00% threshold!"
        print(f"\n{msg}")
        sys.exit(1)
    else:
        msg = f"[OK] Mutation score {mutation_score_pct:.2f}% meets enterprise gate (>=90.00%)."
        print(f"\n{msg}")


if __name__ == "__main__":
    run_mutation_sentinel()
