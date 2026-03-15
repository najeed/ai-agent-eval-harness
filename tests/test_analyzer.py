import pytest
import json
from pathlib import Path
from eval_runner.analyzer import analyze_repo

@pytest.mark.asyncio
async def test_analyze_repo_telecom(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scenarios = await analyze_repo("https://github.com/user/telecom-agent")
    
    assert len(scenarios) == 2
    assert "billing" in scenarios[0]["metadata"]["source_file"]
    assert Path("scenarios/auto").exists()
    
    # Verify persisted file
    sc_file = tmp_path / "scenarios" / "auto" / f"{scenarios[0]['scenario_id']}.json"
    assert sc_file.exists()

@pytest.mark.asyncio
async def test_analyze_repo_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    scenarios = await analyze_repo("https://github.com/user/simple-agent")
    
    assert len(scenarios) == 1
    assert scenarios[0]["metadata"]["pattern"] == "AgentExecutor(...)"
