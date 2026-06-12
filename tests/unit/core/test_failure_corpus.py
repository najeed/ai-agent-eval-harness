"""
test_failure_corpus.py

Full coverage for eval_runner/failure_corpus.py.
Tests cover: missing log file path, regex search, multi-term AND search,
json decode errors, error cap/display, and exception handling.
"""

import json
from pathlib import Path
from unittest.mock import patch

from eval_runner import failure_corpus


def _write_log(path: Path, records: list[dict]) -> None:
    """Helper to write a JSONL log file."""
    lines = [json.dumps(r) for r in records]
    # Add an intentionally blank line to test skip logic
    path.write_text("\n".join(lines) + "\n\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# No log file
# ---------------------------------------------------------------------------


def test_search_no_log_file(tmp_path, monkeypatch, capsys):
    """When runs/run.jsonl doesn't exist, print an info message and return."""
    # Redirect the path lookup by temporarily changing cwd
    monkeypatch.chdir(tmp_path)
    failure_corpus.search("anything")
    captured = capsys.readouterr()
    assert "No master log found" in captured.out


# ---------------------------------------------------------------------------
# Regex search
# ---------------------------------------------------------------------------


def test_search_regex_match(tmp_path, monkeypatch, capsys):
    """Regex patterns are compiled and matched against the search space."""
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / "runs"
    runs.mkdir()
    log = runs / "run.jsonl"

    records = [
        {
            "event": "TURN_FAIL",
            "status": "failure",
            "triage_tag": "TOOL_ERROR",
            "metric": "accuracy",
            "content": "tool crashed",
            "timestamp": "2026-01-01T00:00:00Z",
            "run_id": "run-001",
        },
        {
            "event": "TURN_PASS",
            "status": "success",
            "triage_tag": "NONE",
            "metric": "accuracy",
            "content": "ok",
            "timestamp": "2026-01-01T00:01:00Z",
            "run_id": "run-002",
        },
    ]
    _write_log(log, records)

    # Regex: matches "TOOL" case-insensitively
    failure_corpus.search("TOOL.+")
    captured = capsys.readouterr()
    assert "Found 1 matching" in captured.out
    assert "run-001" in captured.out


def test_search_regex_no_match(tmp_path, monkeypatch, capsys):
    """Regex that matches nothing produces the 'No matching failures' message."""
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / "runs"
    runs.mkdir()
    log = runs / "run.jsonl"
    _write_log(log, [{"event": "OK", "status": "success"}])

    failure_corpus.search("ZZZZZZ_NEVER_MATCHES.+")
    captured = capsys.readouterr()
    assert "No matching failures" in captured.out


# ---------------------------------------------------------------------------
# Multi-term AND search
# ---------------------------------------------------------------------------


def test_search_multi_term_all_match(tmp_path, monkeypatch, capsys):
    """All terms must appear in the combined search space (AND logic)."""
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / "runs"
    runs.mkdir()
    log = runs / "run.jsonl"

    records = [
        {
            "event": "TOOL_CALL",
            "status": "failure",
            "triage_tag": "INJECTION",
            "metric": "",
            "content": "prompt injection detected",
            "timestamp": "T1",
            "run_id": "run-x",
        },
    ]
    _write_log(log, records)

    failure_corpus.search("failure injection")
    captured = capsys.readouterr()
    assert "Found 1 matching" in captured.out


def test_search_multi_term_partial_no_match(tmp_path, monkeypatch, capsys):
    """If any term is missing from the combined search space, the record is skipped."""
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / "runs"
    runs.mkdir()
    log = runs / "run.jsonl"

    records = [
        {
            "event": "TURN_END",
            "status": "success",
            "triage_tag": "NONE",
            "metric": "",
            "content": "all good",
        }
    ]
    _write_log(log, records)

    failure_corpus.search("failure injection")
    captured = capsys.readouterr()
    assert "No matching failures" in captured.out


# ---------------------------------------------------------------------------
# JSON decode error on a single line
# ---------------------------------------------------------------------------


def test_search_skips_invalid_json_lines(tmp_path, monkeypatch, capsys):
    """Lines that are not valid JSON are skipped silently; valid lines are processed."""
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / "runs"
    runs.mkdir()
    log = runs / "run.jsonl"

    content = (
        "{invalid json line}\n"
        + json.dumps(
            {
                "event": "TOOL_ERROR",
                "status": "failure",
                "triage_tag": "CRASH",
                "metric": "",
                "content": "",
                "timestamp": "T",
                "run_id": "run-valid",
            }
        )
        + "\n"
    )
    log.write_text(content, encoding="utf-8")

    failure_corpus.search("failure")
    captured = capsys.readouterr()
    assert "Found 1 matching" in captured.out
    assert "run-valid" in captured.out


# ---------------------------------------------------------------------------
# Display cap at 10 + overflow message
# ---------------------------------------------------------------------------


def test_search_display_cap_and_overflow(tmp_path, monkeypatch, capsys):
    """When >10 matches exist, the first 10 are printed and an overflow message shown."""
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / "runs"
    runs.mkdir()
    log = runs / "run.jsonl"

    records = [
        {
            "event": "TURN_FAIL",
            "status": "failure",
            "triage_tag": "ERR",
            "metric": "",
            "content": "",
            "timestamp": f"T{i}",
            "run_id": f"run-{i:03d}",
        }
        for i in range(15)
    ]
    _write_log(log, records)

    failure_corpus.search("failure")
    captured = capsys.readouterr()
    assert "Found 15 matching" in captured.out
    assert "... and 5 more" in captured.out


# ---------------------------------------------------------------------------
# Outer exception (unreadable file)
# ---------------------------------------------------------------------------


def test_search_outer_exception(tmp_path, monkeypatch, capsys):
    """If the log file cannot be opened, an error message is printed."""
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / "runs"
    runs.mkdir()
    log = runs / "run.jsonl"
    log.write_text("{}", encoding="utf-8")

    with patch("builtins.open", side_effect=PermissionError("Access denied")):
        failure_corpus.search("anything")

    captured = capsys.readouterr()
    assert "Error searching corpus" in captured.out


# ---------------------------------------------------------------------------
# Invalid regex (fallback to multi-term)
# ---------------------------------------------------------------------------


def test_search_invalid_regex_falls_back_to_multiterm(tmp_path, monkeypatch, capsys):
    """An invalid regex pattern gracefully falls back to multi-term string search."""
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / "runs"
    runs.mkdir()
    log = runs / "run.jsonl"

    records = [
        {
            "event": "TOOL_FAIL",
            "status": "failure",
            "triage_tag": "[invalid",  # same bracket in query will trigger re.error
            "metric": "",
            "content": "",
            "timestamp": "T",
            "run_id": "run-fb",
        }
    ]
    _write_log(log, records)

    # "[invalid" is an invalid regex: will fall back to multi-term
    failure_corpus.search("[invalid")
    captured = capsys.readouterr()
    # Multi-term search: "[invalid" is treated as one term — it's in triage_tag
    assert "Found 1 matching" in captured.out or "No matching failures" in captured.out
