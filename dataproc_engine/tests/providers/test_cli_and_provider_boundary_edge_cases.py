import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from dataproc_engine.cli.main import cli, run_rotational_backup
from dataproc_engine.core.base_provider import RawArtifact
from dataproc_engine.providers.agriculture import AgricultureProvider
from dataproc_engine.providers.finance import FinanceProvider
from dataproc_engine.providers.healthcare import HealthcareProvider
from dataproc_engine.providers.telecom import TelecomProvider


def mock_run_factory(return_value):
    def mock_run(coro):
        if asyncio.iscoroutine(coro):
            coro.close()
        return return_value

    return mock_run


@pytest.mark.asyncio
async def test_finance_provider_error_handling():
    """Boost coverage for finance.py error paths."""
    config = {"finance_mode": "worldbank", "allow_simulation": False}
    provider = FinanceProvider(config)

    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get.return_value = mock_ctx

        # Hit lines 47, 61
        artifacts = await provider.extract()
        assert len(artifacts) == 0


@pytest.mark.asyncio
async def test_finance_provider_credit_risk_success(tmp_path):
    """Boost coverage for finance.py credit risk success."""
    csv_file = tmp_path / "credit.csv"
    csv_file.write_text("ID,LIMIT_BAL,EDUCATION,AGE,default.payment.next.month\n1,5000,1,30,0")
    config = {"finance_mode": "credit_risk", "input_uri": str(csv_file), "allow_simulation": False}
    provider = FinanceProvider(config)

    # Hit lines 108-111
    artifacts = await provider.extract()
    assert len(artifacts) == 1
    assert artifacts[0].id == "UCI-CREDIT-USER"


@pytest.mark.asyncio
async def test_finance_provider_sec_mock_default():
    """Boost coverage for finance.py SEC mock default logic."""
    config = {"finance_mode": "sec_edgar", "ciks": ["001"], "allow_simulation": True}
    provider = FinanceProvider(config)

    with patch("os.path.exists", return_value=False):
        # Hit lines 207-230
        artifacts = await provider.extract()
        assert len(artifacts) == 1
        assert "SIM Company" in artifacts[0].metadata["company"]


@pytest.mark.asyncio
async def test_agriculture_provider_boost():
    """Boost coverage for agriculture.py."""
    # FAOStat Empty Path (line 58)
    provider_faostat = AgricultureProvider(
        {"agriculture_mode": "faostat", "allow_simulation": False}
    )
    assert await provider_faostat.extract() == []

    # Transform with climate anomaly (line 219)
    mock_llm = MagicMock()
    mock_llm.strategy = "mock"
    # Ensure verify_schema returns a dict to avoid JSON serialization error
    mock_llm._verify_schema.return_value = {
        "value": 90.0,
        "location": "Loc",
        "item": "Crop",
        "year": 2020,
        "unit": "T",
    }

    provider_agri = AgricultureProvider(
        {"agriculture_mode": "faostat", "climate_anomaly": 2.0}, llm_manager=mock_llm
    )
    from datetime import datetime

    raw = RawArtifact(
        id="test",
        source_url="url",
        content=[{"Area": "Loc", "Item": "Crop", "Year": 2020, "Value": 100, "Unit": "T"}],
        metadata={},
        timestamp=datetime.now().isoformat(),
    )
    results = await provider_agri.transform([raw])
    assert results[0].data["value"] == 90.0


@pytest.mark.asyncio
async def test_telecom_provider_boost():
    """Boost coverage for telecom.py."""
    # ITU Empty Path (line 55)
    p_itu = TelecomProvider({"telecom_mode": "itu", "allow_simulation": False})
    assert await p_itu.extract() == []

    # Ookla Empty Path (line 121)
    p_ookla = TelecomProvider({"telecom_mode": "ookla", "allow_simulation": False})
    assert await p_ookla.extract() == []

    # FCC Error Path (lines 190)
    p_fcc = TelecomProvider({"allow_simulation": False})
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(side_effect=Exception("FCC Fail"))
        mock_get.return_value = mock_ctx
        assert await p_fcc.extract() == []


@pytest.mark.asyncio
async def test_healthcare_provider_boost(tmp_path):
    """Boost coverage for healthcare.py."""
    # WHO Error Path (line 57)
    p_who = HealthcareProvider({"healthcare_mode": "who", "allow_simulation": False})
    with patch("aiohttp.ClientSession.get") as mock_get:
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(side_effect=Exception("WHO Fail"))
        mock_get.return_value = mock_ctx
        assert await p_who.extract() == []

    # CMS Empty Actual Paths (line 240)
    p_cms = HealthcareProvider({"input_uris": ["broken.csv"], "allow_simulation": False})
    assert await p_cms.extract() == []

    # CMS Simulation Trigger (line 228)
    p_sim = HealthcareProvider({"input_uris": [], "allow_simulation": True})
    with patch("os.path.exists", return_value=False):
        artifacts = await p_sim.extract()
        assert len(artifacts) == 1
        assert "sim_cms.csv" in artifacts[0].source_url


def test_cli_rotational_backup_edge_cases(tmp_path):
    """Cover OSError and empty list in run_rotational_backup (lines 29, 42)."""
    # 1. Empty list (line 29)
    run_rotational_backup("nonexistent.txt", 5)

    # 2. OSError (line 42)
    f = tmp_path / "test.txt"
    f.write_text("content")
    bak = tmp_path / "test.txt.20230101_000000_000.bak"
    bak.write_text("old")
    with patch("os.remove", side_effect=OSError("Locked")):
        run_rotational_backup(str(f), 0)


def test_cli_industry_provider_branches():
    """Cover all industry provider registration branches in extract command (lines 165-221)."""
    runner = CliRunner()
    industries = [
        "energy",
        "ecommerce",
        "healthcare",
        "telecom",
        "agriculture",
        "transportation",
        "demographics",
        "labor",
        "environment",
        "housing",
        "manufacturing",
        "media_and_entertainment",
        "decision_support",
        "education",
    ]

    for ind in industries:
        with patch("asyncio.run", side_effect=mock_run_factory([])):
            with patch(
                "dataproc_engine.core.engine.DatasetEngine.run_industry_pipeline", MagicMock()
            ):
                result = runner.invoke(cli, ["extract", "--industry", ind, "--source", "api"])
                assert f"Initializing dataproc pipeline for industry: {ind}" in result.output


def test_cli_save_and_success_flow(tmp_path):
    """Cover successful pipeline execution and saving (lines 239, 255, 288)."""
    runner = CliRunner()
    # Use 'output' to hit line 239 relocation logic
    target_dir = "output"

    mock_item = MagicMock()
    mock_item.to_dict.return_value = {"id": "test"}
    mock_res = [mock_item]

    with patch("asyncio.run", side_effect=mock_run_factory(mock_res)):
        with patch("dataproc_engine.core.engine.DatasetEngine.run_industry_pipeline", MagicMock()):
            with patch("os.makedirs"):
                with patch("pandas.DataFrame.to_json"):
                    # Use overwrite=True to skip confirmation (line 288)
                    result = runner.invoke(
                        cli,
                        [
                            "extract",
                            "--industry",
                            "finance",
                            "--target-dir",
                            target_dir,
                            "--overwrite",
                        ],
                    )
                    assert "Pipeline completed successfully" in result.output


def test_cli_empty_results(tmp_path):
    """Cover line 293 (no data generated)."""
    runner = CliRunner()
    with patch("asyncio.run", side_effect=mock_run_factory([])):
        with patch("dataproc_engine.core.engine.DatasetEngine.run_industry_pipeline", MagicMock()):
            result = runner.invoke(cli, ["extract", "--industry", "finance"])
            assert "Pipeline completed but produced no results." in result.output


def test_cli_file_source_unstructured(tmp_path):
    """Cover lines 226-231 (unstructured provider for file source)."""
    runner = CliRunner()
    dummy_file = tmp_path / "dummy.txt"
    dummy_file.write_text("data")
    with patch("asyncio.run", side_effect=mock_run_factory([])):
        with patch("dataproc_engine.core.engine.DatasetEngine.run_industry_pipeline", MagicMock()):
            result = runner.invoke(
                cli,
                [
                    "extract",
                    "--industry",
                    "finance",
                    "--source",
                    "file",
                    "--input-uri",
                    str(dummy_file),
                ],
            )
            assert (
                "Initializing dataproc pipeline for industry: finance (Source: file)"
                in result.output
            )
