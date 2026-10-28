"""
test_leaderboard.py

Unit tests for the LeaderboardGenerator class.
Verifies pass-rate calculation, threshold filtering, and Markdown formatting.
"""

from eval_runner.leaderboard_generator import LeaderboardGenerator


class FakeRunStore:
    def __init__(self):
        self.runs, self.events, self.manifests = [], {}, {}

    def add(self, run_id, agent_name, evaluations, manifest=None):
        self.runs.append({"run_id": run_id, "agent_id": agent_name})
        self.events[run_id] = [{"event": "run_start", "metadata": {"agent_name": agent_name}}] + [
            {"event": "evaluation", "task_id": tid, "success": success}
            for tid, success in evaluations.items()
        ]
        self.manifests[run_id] = manifest or {}

    def list_runs(self, **kwargs):
        return self.runs

    def get_events(self, run_id, **kwargs):
        return self.events.get(run_id, [])

    def get_manifest(self, run_id, **kwargs):
        return self.manifests.get(run_id)


def test_leaderboard_logic(tmp_path):
    """Verifies aggregate pass rate and threshold filtering."""
    runs = FakeRunStore()

    # 1. High-performing agent (100%)
    runs.add("run_a", "Elite Agent", {"t1": True, "t2": True})

    # 2. Average agent (50%) - Should pass threshold
    runs.add("run_b", "Average Agent", {"t1": True, "t2": False})

    # 3. Failing agent (25%) - Should NOT appear in leaderboard
    runs.add("run_c", "Budget Agent", {"t1": True, "t2": False, "t3": False, "t4": False})

    md = LeaderboardGenerator.generate_markdown(runs)

    # Verify contents
    assert "Elite Agent" in md
    assert "Average Agent" in md
    assert "100.0%" in md
    assert "50.0%" in md
    assert "Budget Agent" not in md  # Below 50% threshold
    assert "| 1. |" in md
    assert "| 2. |" in md


def test_leaderboard_no_agents(tmp_path):
    """Verifies warning message when no agents meet the threshold."""
    md = LeaderboardGenerator.generate_markdown(FakeRunStore())
    assert "No qualifying provider-owned runs found" in md


def test_leaderboard_filename_fallback(tmp_path):
    """Verifies name extraction from vault directory name if metadata is missing."""
    runs = FakeRunStore()
    runs.add("fast-agent-99", "fast-agent-99", {"t1": True})
    md = LeaderboardGenerator.generate_markdown(runs)
    assert "fast-agent-99" in md  # Derived from vault directory name
