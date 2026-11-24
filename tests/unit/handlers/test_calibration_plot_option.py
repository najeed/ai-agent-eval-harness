from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from eval_runner.handlers.analysis import handle_calibrate


@pytest.mark.asyncio
@pytest.mark.parametrize("plot", [True, False])
async def test_provider_calibration_forwards_plot_and_golden_labels(plot):
    events = [{"event": "evaluation", "task_id": "task-a", "value": 0.8}]
    store = MagicMock()
    store.get_events.return_value = events
    args = SimpleNamespace(
        run_id="run-a", path="unused-scenario.json", golden="labels.json", plot=plot
    )
    with (
        patch("eval_runner.runtime_services.resolve_run_store", return_value=store),
        patch("eval_runner.calibrator.run_calibration_events", return_value=None) as calibrate,
    ):
        assert await handle_calibrate(args) == 0
    calibrate.assert_called_once_with(events, golden_path="labels.json", plot=plot)
    store.get_events.assert_called_once_with("run-a", offset=0, limit=10_000_000, context=None)


@pytest.mark.asyncio
async def test_offline_calibration_forwards_plot():
    args = SimpleNamespace(path="trace.jsonl", golden="labels.json", plot=True)
    with patch("eval_runner.calibrator.run_calibration", return_value=0) as calibrate:
        assert await handle_calibrate(args) == 0
    calibrate.assert_called_once_with("trace.jsonl", golden_path="labels.json", plot=True)
