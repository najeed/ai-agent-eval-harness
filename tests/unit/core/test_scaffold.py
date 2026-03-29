import pytest
import json
from pathlib import Path
from unittest.mock import patch
from eval_runner.scaffold import generate_interactive


def test_scaffold_generation(tmp_path, monkeypatch):
    # Mock input
    inputs = iter(["telecom", "reboot", "1"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    # Run in tmp_path
    monkeypatch.chdir(tmp_path)

    with patch("builtins.print"):
        generate_interactive()

    expected_file = tmp_path / "scenarios" / "telecom" / "gen_telecom_reboot_1.json"
    assert expected_file.exists()

def test_scaffold_default_inputs(tmp_path, monkeypatch):
    # Empty inputs should fall back to defaults
    inputs = iter(["", "", ""])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.chdir(tmp_path)

    with patch("builtins.print"):
        generate_interactive()

    # Default industry is "general", default capability is "default"
    expected_file = tmp_path / "scenarios" / "general" / "gen_general_default_1.json"
    assert expected_file.exists()


def test_scaffold_invalid_count(tmp_path, monkeypatch):
    # Invalid count "abc" should fall back to 1
    inputs = iter(["general", "test", "abc"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.chdir(tmp_path)

    with patch("builtins.print"):
        generate_interactive()

    expected_file = tmp_path / "scenarios" / "general" / "gen_general_test_1.json"
    assert expected_file.exists()
