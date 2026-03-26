import pytest
import json
from pathlib import Path
from eval_runner.analyzer import analyze_repo


@pytest.mark.asyncio
async def test_analyze_repo_telecom(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    results = await analyze_repo("http://github.com/telecom-agent")
    assert len(results) > 0
    assert results[0]["metadata"]["source_file"] == "app/billing.py"

    auto_dir = tmp_path / "scenarios" / "auto"
    assert auto_dir.exists()
    assert (auto_dir / f"{results[0]['scenario_id']}.json").exists()


@pytest.mark.asyncio
async def test_analyze_repo_finance(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    results = await analyze_repo("http://github.com/finance-agent")
    assert len(results) > 0
    assert "market.py" in results[1]["metadata"]["source_file"]
    
    auto_dir = tmp_path / "scenarios" / "auto"
    assert len(list(auto_dir.glob("*.json"))) >= 2
