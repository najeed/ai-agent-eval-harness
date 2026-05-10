import os
from unittest.mock import patch

import pytest

from eval_runner.publication_suite.publication_suite import main


@pytest.fixture
def mock_filesystem(tmp_path):
    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    (scenarios / "test.json").write_text("{}")

    results = tmp_path / "results"
    results.mkdir()
    batch = results / "batch_1"
    batch.mkdir()
    (batch / "manifest.json").write_text('{"fingerprint": "f"}')
    (batch / "aggregated_results.json").write_text("{}")

    inventory = tmp_path / "inventory.yaml"
    inventory.write_text("agents:\n  - name: 'A'\n    protocol: 'http'\n    agent: 'url'")

    # Change CWD to tmp_path to make relative paths work in the script
    os.chdir(tmp_path)
    return tmp_path


def test_publication_suite_standard_mode(mock_filesystem):
    # Mock sys.argv
    test_args = ["publication_suite.py", "--path", "scenarios"]

    with patch("sys.argv", test_args), patch("subprocess.run") as mock_run:
        # Simulate batch discovery in results/
        # We need to mock Path("results").iterdir()
        mock_batch = mock_filesystem / "results" / "batch_1"

        with (
            patch("pathlib.Path.iterdir", return_value=[mock_batch]),
            patch("pathlib.Path.is_dir", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
        ):
            mock_stat.return_value.st_mtime = 12345

            main()

            # Phases: 1 (Conduct) + 1 (Aggregate) + 1 (Visualize) + 1 (Bundle)
            assert mock_run.call_count == 4


def test_publication_suite_pilot_mode(mock_filesystem):
    test_args = ["publication_suite.py", "--mode", "pilot"]

    with patch("sys.argv", test_args), patch("subprocess.run") as mock_run:
        mock_batch = mock_filesystem / "results" / "batch_1"

        with (
            patch("pathlib.Path.iterdir", return_value=[mock_batch]),
            patch("pathlib.Path.is_dir", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
        ):
            mock_stat.return_value.st_mtime = 12345

            main()

            # Check if --pilot was passed to conduct and html_builder
            conduct_cmd = mock_run.call_args_list[0][0][0]
            assert "--pilot" in conduct_cmd

            html_cmd = mock_run.call_args_list[2][0][0]
            assert "--pilot" in html_cmd


def test_publication_suite_compare_mode(mock_filesystem):
    inventory_path = mock_filesystem / "inventory.yaml"
    test_args = ["publication_suite.py", "--compare", str(inventory_path)]

    with patch("sys.argv", test_args), patch("subprocess.run") as mock_run:
        mock_batch = mock_filesystem / "results" / "batch_1"

        with (
            patch("pathlib.Path.iterdir", return_value=[mock_batch]),
            patch("pathlib.Path.is_dir", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
        ):
            mock_stat.return_value.st_mtime = 12345

            main()
            assert mock_run.called


def test_publication_suite_missing_inventory(mock_filesystem):
    test_args = ["publication_suite.py", "--compare", "missing.yaml"]
    with patch("sys.argv", test_args), patch("builtins.print") as mock_print:
        main()
        # The script prints the full path it tried
        assert any(
            "Error: Inventory file" in str(args[0]) and "not found" in str(args[0])
            for args in mock_print.call_args_list
        )


def test_publication_suite_no_batches(mock_filesystem):
    test_args = ["publication_suite.py"]
    with (
        patch("sys.argv", test_args),
        patch("subprocess.run"),
        patch("pathlib.Path.iterdir", return_value=[]),
        patch("builtins.print") as mock_print,
    ):
        main()
        assert any("Error: No results found" in str(args[0]) for args in mock_print.call_args_list)


def test_publication_suite_multi_agent_output(mock_filesystem):
    inventory_path = mock_filesystem / "inventory.yaml"
    # Create TWO agents in inventory to trigger multi-agent path
    inventory_content = (
        "agents:\n"
        "  - name: 'A'\n"
        "    protocol: 'http'\n"
        "    agent: 'url'\n"
        "  - name: 'B'\n"
        "    protocol: 'http'\n"
        "    agent: 'url'"
    )
    inventory_path.write_text(inventory_content)

    test_args = ["publication_suite.py", "--compare", str(inventory_path)]

    with patch("sys.argv", test_args), patch("subprocess.run"):
        mock_batch = mock_filesystem / "results" / "batch_1"

        with (
            patch("pathlib.Path.iterdir", return_value=[mock_batch]),
            patch("pathlib.Path.is_dir", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
        ):
            mock_stat.return_value.st_mtime = 12345

            with patch("builtins.print") as mock_print:
                main()
                assert any(
                    "Comparative Leaderboard" in str(args[0]) for args in mock_print.call_args_list
                )
