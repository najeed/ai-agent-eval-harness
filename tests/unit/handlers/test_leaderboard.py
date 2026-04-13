"""
test_leaderboard.py

Unit tests for the LeaderboardGenerator class.
Verifies pass-rate calculation, threshold filtering, and Markdown formatting.
"""

import json

from eval_runner.leaderboard_generator import LeaderboardGenerator


def create_trace(runs_dir, run_id, agent_name, evaluations):
    """Helper to create a dummy trace in a vault."""
    vault = runs_dir / run_id
    vault.mkdir(parents=True, exist_ok=True)
    path = vault / "run.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        # Run Start event
        f.write(json.dumps({"event": "run_start", "metadata": {"agent_name": agent_name}}) + "\n")
        # Evaluation events
        for tid, success in evaluations.items():
            f.write(json.dumps({"event": "evaluation", "task_id": tid, "success": success}) + "\n")


def test_leaderboard_logic(tmp_path):
    """Verifies aggregate pass rate and threshold filtering."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()

    # 1. High-performing agent (100%)
    create_trace(runs_dir, "run_a", "Elite Agent", {"t1": True, "t2": True})

    # 2. Average agent (50%) - Should pass threshold
    create_trace(runs_dir, "run_b", "Average Agent", {"t1": True, "t2": False})

    # 3. Failing agent (25%) - Should NOT appear in leaderboard
    create_trace(
        runs_dir,
        "run_c",
        "Budget Agent",
        {"t1": True, "t2": False, "t3": False, "t4": False},
    )

    # 4. Corrupt trace - Should be skipped gracefully
    vault_corrupt = runs_dir / "vault_corrupt"
    vault_corrupt.mkdir()
    (vault_corrupt / "run.jsonl").write_text("not json\n", encoding="utf-8")

    md = LeaderboardGenerator.generate_markdown(str(runs_dir))

    # Verify contents
    assert "Elite Agent" in md
    assert "Average Agent" in md
    assert "100.0%" in md
    assert "50.0%" in md
    assert "Budget Agent" not in md  # Below 50% threshold
    assert "| 🥇 |" in md
    assert "| 🥈 |" in md


def test_leaderboard_no_agents(tmp_path):
    """Verifies warning message when no agents meet the threshold."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    md = LeaderboardGenerator.generate_markdown(str(empty_dir))
    assert "No agents have achieved the minimum quality threshold" in md


def test_leaderboard_filename_fallback(tmp_path):
    """Verifies name extraction from vault directory name if metadata is missing."""
    runs_dir = tmp_path / "runs_no_meta"
    runs_dir.mkdir()

    # Trace without agent_name in metadata, inside a vault
    vault = runs_dir / "fast-agent-99"
    vault.mkdir()
    path = vault / "run.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"event": "evaluation", "task_id": "t1", "success": True}) + "\n")

    md = LeaderboardGenerator.generate_markdown(str(runs_dir))
    assert "fast-agent-99" in md  # Derived from vault directory name
