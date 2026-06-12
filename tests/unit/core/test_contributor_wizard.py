"""
test_contributor_wizard.py

Full coverage for eval_runner/contributor.py (ContributeWizard).
Tests cover the quality-tier tip/warning display branch and the
mutator-variant generation branch.
"""

import json
from unittest.mock import patch

from eval_runner.contributor import ContributeWizard


def _run_wizard(inputs: list[str]) -> None:
    """Helper that injects stdin responses and runs the wizard."""
    with patch("builtins.input", side_effect=inputs):
        ContributeWizard.run()


# ---------------------------------------------------------------------------
# Happy path — GOLD tier, no mutation
# ---------------------------------------------------------------------------


def test_wizard_creates_file_gold_tier_no_mutation(tmp_path, capsys, monkeypatch):
    """Wizard with all valid inputs reaches GOLD tier and skips mutation."""
    monkeypatch.chdir(tmp_path)

    inputs = [
        "Return Policy Inquiries",  # title
        "retail",  # industry
        "n",  # do not generate adversarial variants
    ]

    # Linter will return a GOLD report (score == 100) because the stub
    # does not include the mandatory 'aes_version' / 'workflow' fields,
    # meaning the linter will actually fail — but we patch it so this test
    # focuses only on the wizard flow path.
    mock_report = {
        "score": 100,
        "tier": "GOLD",
        "warnings": [],
        "errors": [],
    }

    with patch("eval_runner.contributor.ScenarioLinter.lint", return_value=mock_report):
        _run_wizard(inputs)

    captured = capsys.readouterr()
    assert "CONTRIBUTION WIZARD" in captured.out
    assert "NEXT STEPS" in captured.out

    # File should have been created
    expected_path = (
        tmp_path / "industries" / "retail" / "scenarios" / "return-policy-inquiries.json"
    )
    assert expected_path.exists()
    data = json.loads(expected_path.read_text())
    assert data["id"] == "return-policy-inquiries"
    assert data["industry"] == "retail"


# ---------------------------------------------------------------------------
# Non-GOLD tier branch — prints TIP + warnings
# ---------------------------------------------------------------------------


def test_wizard_non_gold_tier_prints_tip_and_warnings(tmp_path, capsys, monkeypatch):
    """When tier != GOLD the wizard prints the TIP and iterates over warnings."""
    monkeypatch.chdir(tmp_path)

    inputs = [
        "Silver Scenario",  # title
        "finance",  # industry
        "n",  # no mutation
    ]

    mock_report = {
        "score": 72,
        "tier": "SILVER",
        "warnings": ["Missing complexity_level", "No attribution"],
        "errors": [],
    }

    with patch("eval_runner.contributor.ScenarioLinter.lint", return_value=mock_report):
        _run_wizard(inputs)

    captured = capsys.readouterr()
    assert "TIP" in captured.out
    assert "Missing complexity_level" in captured.out
    assert "No attribution" in captured.out


# ---------------------------------------------------------------------------
# Mutation variant branch
# ---------------------------------------------------------------------------


def test_wizard_generates_mutation_variant(tmp_path, capsys, monkeypatch):
    """When user selects 'y', a typo-mutated variant is saved."""
    monkeypatch.chdir(tmp_path)

    inputs = [
        "Mutation Test",  # title
        "telecom",  # industry
        "y",  # generate adversarial variants
    ]

    mock_report = {
        "score": 100,
        "tier": "GOLD",
        "warnings": [],
        "errors": [],
    }

    mock_mutated = {"id": "mutation-test-typo"}

    with patch("eval_runner.contributor.ScenarioLinter.lint", return_value=mock_report):
        with patch(
            "eval_runner.contributor.mutator.mutate_scenario", return_value=mock_mutated
        ) as mock_mutate:
            with patch("eval_runner.contributor.mutator.save_mutated_scenario") as mock_save:
                _run_wizard(inputs)

    captured = capsys.readouterr()
    assert "Mutator" in captured.out
    mock_mutate.assert_called_once()
    mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# Default industry fallback
# ---------------------------------------------------------------------------


def test_wizard_empty_industry_defaults_to_generic(tmp_path, capsys, monkeypatch):
    """Pressing Enter on industry uses 'generic' as the default."""
    monkeypatch.chdir(tmp_path)

    inputs = [
        "Generic Scenario",  # title
        "",  # empty industry → defaults to 'generic'
        "n",
    ]

    mock_report = {"score": 100, "tier": "GOLD", "warnings": [], "errors": []}

    with patch("eval_runner.contributor.ScenarioLinter.lint", return_value=mock_report):
        _run_wizard(inputs)

    expected_path = tmp_path / "industries" / "generic" / "scenarios" / "generic-scenario.json"
    assert expected_path.exists()
    data = json.loads(expected_path.read_text())
    assert data["industry"] == "generic"
