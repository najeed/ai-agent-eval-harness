import json
from unittest.mock import patch

from eval_runner.leaderboard_generator import LeaderboardGenerator, run_leaderboard


def test_run_leaderboard(tmp_path):
    """Exercises the run_leaderboard CLI helper."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    output_file = tmp_path / "LEADERBOARD.md"

    # Create a dummy trace
    run_dir = runs_dir / "run_1"
    run_dir.mkdir()
    trace_file = run_dir / "run.jsonl"
    trace_file.write_text(
        json.dumps({"event": "run_start", "metadata": {"agent": "test-agent"}})
        + "\n"
        + json.dumps({"event": "evaluation", "task_id": "1", "success": True})
        + "\n"
    )

    with patch("builtins.print") as mock_print:
        run_leaderboard(str(runs_dir), str(output_file))
        assert output_file.exists()
        mock_print.assert_any_call(f"[OK] Leaderboard generated: {output_file}")


def test_leaderboard_corrupted_manifest(tmp_path):
    """Exercises manifest read failure (lines 32-39)."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    run_dir = runs_dir / "run_corrupt"
    run_dir.mkdir()
    trace_file = run_dir / "run.jsonl"
    trace_file.write_text(
        json.dumps({"event": "run_start", "metadata": {"agent": "agent-1"}})
        + "\n"
        + json.dumps({"event": "evaluation", "task_id": "1", "success": True})
        + "\n"
    )

    manifest_file = run_dir / "run_manifest.json"
    manifest_file.write_text("{corrupted-json")

    # Should log error and continue
    with patch("logging.error") as mock_log:
        LeaderboardGenerator.generate_markdown(str(runs_dir))
        mock_log.assert_called()


def test_leaderboard_certified_badge(tmp_path):
    """Exercises certified badge logic (line 53)."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    run_dir = runs_dir / "run_certified"
    run_dir.mkdir()
    trace_file = run_dir / "run.jsonl"
    trace_file.write_text(
        json.dumps({"event": "run_start", "metadata": {"agent": "pro-agent"}})
        + "\n"
        + json.dumps({"event": "evaluation", "task_id": "1", "success": True})
        + "\n"
    )

    manifest_file = run_dir / "run_manifest.json"
    manifest_file.write_text(json.dumps({"metadata": {"agent_name": "pro-agent"}}))

    content = LeaderboardGenerator.generate_markdown(str(runs_dir))
    assert "🏅 pro-agent" in content


def test_leaderboard_no_evals(tmp_path):
    """Exercises continue when no evals found (line 58)."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    run_dir = runs_dir / "run_empty"
    run_dir.mkdir()
    trace_file = run_dir / "run.jsonl"
    trace_file.write_text(
        json.dumps({"event": "run_start", "metadata": {"agent": "lazy-agent"}}) + "\n"
    )

    content = LeaderboardGenerator.generate_markdown(str(runs_dir))
    assert "No agents have achieved the minimum quality threshold" in content
