from unittest.mock import MagicMock, patch

import pytest

from eval_runner.context import EvaluationContext
from eval_runner.reporting_plugin import ReportingPlugin


@pytest.fixture
def mock_context():
    ctx = EvaluationContext("test_scenario", "test_run", {})
    object.__setattr__(ctx, "metadata", {"args": {}})
    object.__setattr__(ctx, "scenario_data", {"name": "test"})
    return ctx


def test_reporting_plugin_on_metrics_calculated():
    plugin = ReportingPlugin()
    ctx = EvaluationContext("test", "run", {})

    # Test early return
    plugin.on_metrics_calculated(ctx, [{}])

    # Test full consistency score calculation
    history1 = [{"role": "user", "content": "hello"}, {"role": "agent", "content": "hi"}]
    history2 = [{"role": "agent", "content": {"summary": "hi"}}]
    history3 = [{"role": "agent", "content": {"content": "hello"}}]

    results = [
        [{"conversation_history": history1, "metrics": []}],
        [{"conversation_history": history2, "metrics": []}],
        [{"conversation_history": history3, "metrics": []}],
    ]

    plugin.on_metrics_calculated(ctx, results)

    # Check if inconsistency score injected
    assert len(results[-1][0]["metrics"]) == 1
    assert results[-1][0]["metrics"][0]["metric"] == "consistency_score"


def test_reporting_plugin_on_register_commands():
    plugin = ReportingPlugin()
    plugin.on_register_commands(None)
    # Just checking it doesn't crash
    assert True


def test_reporting_plugin_after_evaluation(mock_context, monkeypatch):
    plugin = ReportingPlugin()

    with (
        patch("eval_runner.triage.TriageEngine.apply_triage") as mock_triage,
        patch("eval_runner.reporter.generate_report") as mock_report,
    ):
        # Base case
        results = [{"metrics": [{"success": True}]}]
        plugin.after_evaluation(mock_context, results)
        assert mock_triage.called
        assert mock_report.called

        # K-attempt case
        results_k = [[{"metrics": [{"success": True}]}]]
        plugin.after_evaluation(mock_context, results_k)
        assert mock_triage.call_count == 2


def test_reporting_plugin_after_eval_notify_running_loop(mock_context, monkeypatch):
    mock_context.metadata["args"]["notify"] = True

    with (
        patch("eval_runner.triage.TriageEngine.apply_triage", new_callable=MagicMock),
        patch("eval_runner.reporter.generate_report", new_callable=MagicMock),
        patch.object(
            ReportingPlugin, "dispatch_notifications", new_callable=MagicMock, return_value=None
        ),
        patch("asyncio.get_event_loop", new_callable=MagicMock) as mock_get_loop,
    ):
        plugin = ReportingPlugin()
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True
        mock_get_loop.return_value = mock_loop

        plugin.after_evaluation(mock_context, [{"metrics": []}])
        assert mock_loop.create_task.called


def test_reporting_plugin_after_eval_notify_not_running(mock_context, monkeypatch):
    mock_context.metadata["args"]["notify"] = True

    with (
        patch("eval_runner.triage.TriageEngine.apply_triage", new_callable=MagicMock),
        patch("eval_runner.reporter.generate_report", new_callable=MagicMock),
        patch.object(
            ReportingPlugin, "dispatch_notifications", new_callable=MagicMock, return_value=None
        ),
        patch("asyncio.get_event_loop", new_callable=MagicMock) as mock_get_loop,
    ):
        plugin = ReportingPlugin()
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = False
        mock_get_loop.return_value = mock_loop

        plugin.after_evaluation(mock_context, [{"metrics": []}])
        assert mock_loop.run_until_complete.called


def test_reporting_plugin_generate_repro_script_paths(mock_context, tmp_path, monkeypatch):
    plugin = ReportingPlugin()

    # Needs to be able to test different conditions (109, 115)
    # Cond 1: path has ://
    mock_context.metadata["args"]["path"] = "http://test.json"

    # We patch Path("reports") to write inside tmp_path
    def mock_path(p):
        return tmp_path / p

    with patch("eval_runner.reporting_plugin.Path") as mock_p:
        mock_p.side_effect = lambda x: mock_path(x)
        plugin.generate_repro_script(mock_context)
        file_path = tmp_path / "reports" / "repro" / f"repro_{mock_context.identifier}.txt"
        assert file_path.exists()
        assert "http://test.json" in file_path.read_text()

    # Cond 3: scenario_data contains path
    mock_context.metadata["args"] = {}
    mock_context.scenario_data["path"] = "data_path.json"

    with patch("eval_runner.reporting_plugin.Path") as mock_p:
        mock_p.side_effect = lambda x: mock_path(x)
        plugin.generate_repro_script(mock_context)
        assert "data_path.json" in file_path.read_text()


@pytest.mark.asyncio
async def test_reporting_plugin_dispatch_notifications_no_url(mock_context, capsys):
    plugin = ReportingPlugin()
    await plugin.dispatch_notifications(mock_context, [])
    assert "No 'webhook_url'" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_reporting_plugin_dispatch_notifications_error(mock_context, capsys, monkeypatch):
    plugin = ReportingPlugin()
    mock_context.metadata["webhook_url"] = "http://bad_url"

    # Test error branch by forcing aiohttp ClientSession to raise
    with patch("aiohttp.ClientSession") as mock_session:
        mock_session.side_effect = Exception("Simulated Webhook Failure")
        await plugin.dispatch_notifications(mock_context, [])
        assert "Error dispatching" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_reporting_plugin_dispatch_notifications_bad_status(mock_context, capsys):
    plugin = ReportingPlugin()
    mock_context.metadata["webhook_url"] = "http://webhook"

    class MockResp:
        status = 400

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class MockPost:
        async def __aenter__(self):
            return MockResp()

        async def __aexit__(self, *args):
            pass

    class MockSession:
        def post(self, *args, **kwargs):
            return MockPost()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    with patch("aiohttp.ClientSession", return_value=MockSession()):
        await plugin.dispatch_notifications(mock_context, [[{"metrics": [{"success": True}]}]])
        assert "Webhook failed: 400" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_reporting_plugin_dispatch_notifications_success(mock_context, capsys):
    plugin = ReportingPlugin()
    object.__setattr__(mock_context, "metadata", {})
    mock_context.metadata["webhook_url"] = "http://webhook"

    class MockResp:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class MockPost:
        async def __aenter__(self):
            return MockResp()

        async def __aexit__(self, *args):
            pass

    class MockSession:
        def post(self, *args, **kwargs):
            return MockPost()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    with patch("aiohttp.ClientSession", return_value=MockSession()):
        await plugin.dispatch_notifications(mock_context, [[{"metrics": [{"success": True}]}]])
    assert "Notification sent successfully" in capsys.readouterr().out


def test_reporting_plugin_on_metrics_no_agent_msgs():
    plugin = ReportingPlugin()
    ctx = EvaluationContext("test", "run", {})
    results = [
        [{"conversation_history": [{"role": "user", "content": "hello"}], "metrics": []}],
        [{"conversation_history": [{"role": "user", "content": "hello"}], "metrics": []}],
    ]
    plugin.on_metrics_calculated(ctx, results)
    assert results[-1][0]["metrics"][0]["metric"] == "consistency_score"
