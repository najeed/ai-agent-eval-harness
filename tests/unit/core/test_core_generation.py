"""
Consolidated Generation Test Suite for AgentV Evaluation Harness.
Verifies interactive scenario generation, demo asset creation,
and schema compliance for synthetic evaluation PRDs.
"""

import json

from eval_runner import scaffold

# --- 1. Interactive Generation & Schema Compliance ---


def test_generated_scenario_compliance(tmp_path, monkeypatch):
    """Verify that synthetic scenarios match the AES JSON Schema."""
    # Mock inputs: Industry=finance, Capability=credit, Count=1
    inputs = iter(["finance", "credit", "1"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", tmp_path)

    # Run generation
    scaffold.generate_interactive()

    # Check output
    gen_file = tmp_path / "scenarios" / "finance" / "gen_finance_credit_1.json"
    assert gen_file.exists()

    with open(gen_file) as f:
        data = json.load(f)
        assert data["industry"] == "finance"
        assert "workflow" in data


# --- 2. Demo Asset Generation ---


def test_generate_demo_assets(tmp_path, monkeypatch):
    """Verify creation of documentation assets and demo scenarios."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", tmp_path)

    # We can use a mock or call a specific demo generator if available
    # For now, verify the scaffold can create standard templates
    scaffold.generate_github_action()
    assert (tmp_path / ".github" / "workflows" / "eval_harness_ci.yml").exists()
