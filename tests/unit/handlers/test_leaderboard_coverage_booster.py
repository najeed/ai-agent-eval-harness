from unittest.mock import mock_open, patch

from eval_runner.leaderboard_generator import LeaderboardGenerator, run_leaderboard


class FakeRunStore:
    """Provider fixture preserving leaderboard edge-case coverage."""

    def __init__(self, runs, events, manifests=None):
        self.runs = runs
        self.events = events
        self.manifests = manifests or {}

    def list_runs(self, *, limit):
        return self.runs

    def get_events(self, run_id, *, offset, limit):
        return self.events[run_id]

    def get_manifest(self, run_id):
        return self.manifests.get(run_id)


def _events(agent, *, evaluation=True):
    events = [{"event": "run_start", "metadata": {"agent_name": agent}}]
    if evaluation:
        events.append({"event": "evaluation", "task_id": "1", "success": True})
    return events


def test_run_leaderboard():
    """The CLI helper writes markdown derived from the supplied provider."""
    store = FakeRunStore([{"run_id": "run-1"}], {"run-1": _events("test-agent")})
    output = mock_open()
    with patch("builtins.open", output), patch("builtins.print") as mock_print:
        run_leaderboard(store, "LEADERBOARD.md")
    output.assert_called_once_with("LEADERBOARD.md", "w", encoding="utf-8")
    assert "test-agent" in output().write.call_args.args[0]
    mock_print.assert_any_call("[OK] Leaderboard generated: LEADERBOARD.md")


def test_leaderboard_missing_manifest_uses_run_start_metadata():
    """Missing/unavailable manifests do not discard otherwise valid run events."""
    store = FakeRunStore([{"run_id": "run-1"}], {"run-1": _events("agent-1")})
    content = LeaderboardGenerator.generate_markdown(store)
    assert "agent-1" in content


def test_leaderboard_certified_badge():
    """Provider manifests control the certified display badge."""
    store = FakeRunStore(
        [{"run_id": "run-certified"}],
        {"run-certified": _events("pro-agent")},
        {"run-certified": {"metadata": {"agent_name": "pro-agent"}, "certification": {"id": "c"}}},
    )
    content = LeaderboardGenerator.generate_markdown(store)
    assert "🏅 pro-agent" in content


def test_leaderboard_no_evals():
    """Runs without evaluation events remain excluded from leaderboard rows."""
    store = FakeRunStore(
        [{"run_id": "run-empty"}], {"run-empty": _events("lazy-agent", evaluation=False)}
    )
    content = LeaderboardGenerator.generate_markdown(store)
    assert "No qualifying provider-owned runs found" in content
