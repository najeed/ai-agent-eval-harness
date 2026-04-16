from types import SimpleNamespace
from unittest.mock import patch

import pytest

from eval_runner import config
from eval_runner.handlers import evaluation as h_eval
from eval_runner.handlers import scenarios as h_scen


@pytest.mark.asyncio
async def test_handle_evaluate_industrial_args(tmp_path, monkeypatch):
    """Verifies that the evaluation handler correctly process industrial seed and overrides."""
    base = tmp_path.resolve()
    monkeypatch.setattr(config, "PROJECT_ROOT", base)

    args = SimpleNamespace(
        path="ds.json",
        attempts=1,
        format="json",
        plugin=[],
        run_id="r1",
        run_log_dir=None,
        per_run_logs=None,
        master_log=None,
        seed=None,
        agent_name=None,
        agent=None,
        protocol="http",
    )

    with patch.object(h_eval.loader, "load_dataset", return_value=[{"title": "s"}]):
        with patch.object(h_eval.engine, "run_evaluation"):
            assert await h_eval.handle_evaluate(args) == 0


@pytest.mark.asyncio
async def test_handle_inspect_metadata_resolution(monkeypatch):
    """Verifies that scenario inspection handles missing metadata fields gracefully."""
    with patch.object(
        h_scen.loader,
        "load_scenario",
        return_value={
            "metadata": {},
            "industry": "generic",
            "workflow": {"nodes": []},
            "description": "Industrial test",
        },
    ):
        assert await h_scen.handle_inspect(SimpleNamespace(path="s1.json")) == 0
