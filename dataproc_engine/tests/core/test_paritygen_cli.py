"""
test_paritygen_cli.py
Coverage for dataproc_engine/core/paritygen/cli.py via in-process sys.argv patching.
"""
import json
import os
import sys
import pytest
import pandas as pd
from unittest.mock import patch
from dataproc_engine.core.paritygen.cli import main


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_csv(tmp_path, rows=10) -> str:
    """Create a small CSV file for testing."""
    df = pd.DataFrame({
        "revenue": [float(i * 100) for i in range(1, rows + 1)],
        "profit":  [float(i * 10)  for i in range(1, rows + 1)],
        "sector":  ["tech" if i % 2 == 0 else "health" for i in range(rows)]
    })
    path = str(tmp_path / "input.csv")
    df.to_csv(path, index=False)
    return path


# ─── Error paths ──────────────────────────────────────────────────────────────

def test_cli_nonexistent_input_file(tmp_path, capsys):
    """CLI exits with code 1 and prints error when --input file doesn't exist."""
    output = str(tmp_path / "output.csv")
    test_args = ["cli.py", "--input", "non_existent_file.csv", "--output", output]

    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "not found" in captured.out


def test_cli_missing_required_args():
    """CLI exits non-zero when --input or --output is not provided."""
    with patch.object(sys, "argv", ["cli.py"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code != 0


# ─── Happy paths ──────────────────────────────────────────────────────────────

def test_cli_happy_path_generates_output(tmp_path, capsys):
    """CLI generates synthetic CSV and provenance JSON for a valid input."""
    input_path = make_csv(tmp_path, rows=20)
    output_path = str(tmp_path / "synthetic.csv")
    test_args = ["cli.py", "--input", input_path, "--output", output_path, "--n-samples", "15"]

    with patch.object(sys, "argv", test_args):
        main()

    assert os.path.exists(output_path), "Output CSV was not created"
    meta_path = output_path + ".metadata.json"
    assert os.path.exists(meta_path), "Provenance metadata JSON was not created"


def test_cli_output_csv_has_correct_row_count(tmp_path):
    """CLI output CSV has exactly --n-samples rows."""
    input_path = make_csv(tmp_path)
    output_path = str(tmp_path / "out.csv")
    test_args = ["cli.py", "--input", input_path, "--output", output_path, "--n-samples", "25"]

    with patch.object(sys, "argv", test_args):
        main()

    df = pd.read_csv(output_path)
    assert len(df) == 25


def test_cli_provenance_json_structure(tmp_path):
    """Provenance JSON from CLI contains required compliance fields."""
    input_path = make_csv(tmp_path)
    output_path = str(tmp_path / "out.csv")
    test_args = ["cli.py", "--input", input_path, "--output", output_path,
                 "--license", "CC-BY 4.0", "--n-samples", "5"]

    with patch.object(sys, "argv", test_args):
        main()

    meta_path = output_path + ".metadata.json"
    with open(meta_path) as f:
        meta = json.load(f)

    assert meta["license_info"] == "CC-BY 4.0"
    assert "generation_method" in meta
    assert "compliance_disclaimer" in meta
    assert "generated_at" in meta


def test_cli_validation_report_in_stdout(tmp_path, capsys):
    """CLI prints validation report and completion message to stdout."""
    input_path = make_csv(tmp_path)
    output_path = str(tmp_path / "out.csv")
    test_args = ["cli.py", "--input", input_path, "--output", output_path, "--n-samples", "10"]

    with patch.object(sys, "argv", test_args):
        main()

    captured = capsys.readouterr()
    assert "Parity Synthesis Complete" in captured.out
    assert "Validation Report" in captured.out


def test_cli_default_license_is_restricted(tmp_path):
    """CLI uses 'Restricted' as default license when --license is not specified."""
    input_path = make_csv(tmp_path)
    output_path = str(tmp_path / "out.csv")
    test_args = ["cli.py", "--input", input_path, "--output", output_path, "--n-samples", "5"]

    with patch.object(sys, "argv", test_args):
        main()

    meta_path = output_path + ".metadata.json"
    with open(meta_path) as f:
        meta = json.load(f)
    assert meta["license_info"] == "Restricted"


def test_cli_preserves_column_names(tmp_path):
    """Synthetic output contains same numeric columns as input."""
    input_path = make_csv(tmp_path)
    output_path = str(tmp_path / "out.csv")
    test_args = ["cli.py", "--input", input_path, "--output", output_path, "--n-samples", "10"]

    with patch.object(sys, "argv", test_args):
        main()

    output_df = pd.read_csv(output_path)
    assert "revenue" in output_df.columns
    assert "profit" in output_df.columns
