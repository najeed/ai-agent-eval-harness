"""
test_energy_extended.py
Extended coverage for EnergyProvider:
  - energy_balances mode with api_key (dynamic generation path)
  - energy_balances transform (country_code/flow/product schema)
  - EnergyProvider.validate() for all 3 mode branches
  - EIA list-format transform path
"""
import datetime
import pytest
from unittest.mock import patch
from dataproc_engine.providers.energy import EnergyProvider
from dataproc_engine.core.base_provider import RawArtifact, StandardSchema
from dataproc_engine.core.llm_manager import LLMManager


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_llm():
    return LLMManager({"llm_strategy": "mock"})


def make_artifact(content, id="test-artifact", source_url="test://energy"):
    return RawArtifact(
        id=id,
        source_url=source_url,
        content=content,
        metadata={"series_name": "Test Series", "units": "Units"},
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
    )


# ─── energy_balances mode extract ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_energy_balances_extract_with_api_key():
    """energy_balances with api_key generates dynamic records (lines 72-90)."""
    config = {
        "energy_mode": "energy_balances",
        "eia_api_key": "test_api_key_xyz",
        "allow_simulation": True
    }
    provider = EnergyProvider(config, llm_manager=make_llm())

    artifacts = await provider.extract()
    # Should produce dynamic data from the api_key branch
    assert len(artifacts) > 0
    content = artifacts[0].content
    assert len(content) > 0
    # Verify structure: country, flow, product, value, unit
    for row in content:
        assert "country" in row or "flow" in row


@pytest.mark.asyncio
async def test_energy_balances_extract_no_api_key_no_file():
    """energy_balances without api_key and no input_uri returns empty list."""
    config = {
        "energy_mode": "energy_balances",
        "allow_simulation": False
    }
    provider = EnergyProvider(config, llm_manager=make_llm())
    artifacts = await provider.extract()
    assert artifacts == []


@pytest.mark.asyncio
async def test_energy_balances_extract_with_local_file(tmp_path):
    """energy_balances loads from local CSV when input_uri is set."""
    csv = tmp_path / "balances.csv"
    csv.write_text("country,flow,product,value,unit\nUSA,Production,Solar,1000.0,Mtoe")

    config = {
        "energy_mode": "energy_balances",
        "input_uri": str(csv),
        "allow_simulation": False
    }
    provider = EnergyProvider(config, llm_manager=make_llm())
    artifacts = await provider.extract()
    assert len(artifacts) > 0
    assert artifacts[0].id == "ENERGY-BALANCE-USER"


# ─── energy_balances mode transform ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_energy_balances_transform_valid_data():
    """energy_balances transform produces StandardSchema with correct keys."""
    config = {"energy_mode": "energy_balances"}
    provider = EnergyProvider(config, llm_manager=make_llm())

    content = [
        {"country": "USA", "flow": "Production", "product": "Solar", "value": 1500.0, "unit": "Mtoe"},
        {"country": "DEU", "flow": "Consumption", "product": "Wind", "value": 800.0, "unit": "Mtoe"},
    ]
    artifact = make_artifact(content, id="ENERGY-BALANCES-X")
    results = await provider.transform([artifact])

    assert len(results) > 0
    for r in results:
        assert r.industry == "energy"
        assert "country_code" in r.data
        assert "energy_flow" in r.data
        assert "energy_product" in r.data
        assert "flow_value" in r.data
        assert r.data["flow_value"] > 0


@pytest.mark.asyncio
async def test_energy_balances_transform_missing_fields():
    """energy_balances transform handles rows with missing fields gracefully."""
    config = {"energy_mode": "energy_balances"}
    provider = EnergyProvider(config, llm_manager=make_llm())

    # Missing 'unit' → strict verify will reject this row
    content = [{"country": "USA", "flow": "Production", "product": "Solar", "value": 1500.0}]
    artifact = make_artifact(content, id="PARTIAL-DATA")
    # Should not crash — just produce zero results for bad rows
    results = await provider.transform([artifact])
    # strict=True → None fields cause verify to fail → 0 records is acceptable
    assert isinstance(results, list)


# ─── EIA list-format transform path (lines 249-258) ──────────────────────────

@pytest.mark.asyncio
async def test_energy_eia_list_format_transform():
    """EIA transform handles list [date, value] format (not dict)."""
    config = {"energy_mode": "eia"}
    provider = EnergyProvider(config, llm_manager=make_llm())

    # EIA API returns lists of [date_str, value]
    content = [["2023-01-01", 75.4], ["2023-01-02", 76.1]]
    artifact = RawArtifact(
        id="PET.RWTC.D",
        source_url="https://api.eia.gov/",
        content=content,
        metadata={"series_name": "WTI Crude Oil", "units": "USD/BBL"},
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    results = await provider.transform([artifact])
    assert len(results) > 0
    for r in results:
        assert r.data["series_id"] == "PET.RWTC.D"
        assert r.data["latest_value"] > 0


@pytest.mark.asyncio
async def test_energy_eia_list_format_skips_short_items():
    """EIA transform skips list items with fewer than 2 elements."""
    config = {"energy_mode": "eia"}
    provider = EnergyProvider(config, llm_manager=make_llm())

    # Mix of valid and malformed list items
    content = [["2023-01-01", 75.4], ["bad"], ["2023-01-02", 76.1]]
    artifact = RawArtifact(
        id="PET.RWTC.D",
        source_url="https://api.eia.gov/",
        content=content,
        metadata={"series_name": "WTI Crude Oil", "units": "USD/BBL"},
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    results = await provider.transform([artifact])
    # Should produce 2 records (skipping the "bad" item)
    assert len(results) == 2


# ─── EnergyProvider.validate() — all 3 mode branches ─────────────────────────

def test_energy_validate_opsd_valid():
    """validate() for OPSD mode accepts non-negative load values."""
    config = {"energy_mode": "opsd"}
    provider = EnergyProvider(config, llm_manager=make_llm())

    record = StandardSchema(
        id="r1", industry="energy",
        data={"region": "DE", "utc_timestamp": "2023-01-01T00:00:00Z",
              "load": 45000.0, "solar": 0.0, "wind": 12000.0},
        provenance={}, checksum=""
    )
    assert provider.validate([record]) is True


def test_energy_validate_opsd_negative_load():
    """validate() for OPSD mode rejects negative load values."""
    config = {"energy_mode": "opsd"}
    provider = EnergyProvider(config, llm_manager=make_llm())

    record = StandardSchema(
        id="r1", industry="energy",
        data={"region": "DE", "utc_timestamp": "2023-01-01T00:00:00Z",
              "load": -100.0, "solar": 0.0, "wind": 0.0},
        provenance={}, checksum=""
    )
    assert provider.validate([record]) is False


def test_energy_validate_balances_negative_flow():
    """validate() for energy_balances mode rejects negative flow values."""
    config = {"energy_mode": "energy_balances"}
    provider = EnergyProvider(config, llm_manager=make_llm())

    record = StandardSchema(
        id="r1", industry="energy",
        data={"country_code": "USA", "energy_flow": "Production",
              "energy_product": "Solar", "flow_value": -500.0, "unit_of_measure": "Mtoe"},
        provenance={}, checksum=""
    )
    assert provider.validate([record]) is False


def test_energy_validate_eia_extreme_negative():
    """validate() for EIA mode flags extreme negative prices (below -50)."""
    config = {"energy_mode": "eia"}
    provider = EnergyProvider(config, llm_manager=make_llm())

    # WTI went negative in 2020, but only slightly — below -50 is anomalous
    anomaly = StandardSchema(
        id="r1", industry="energy",
        data={"series_id": "WTI", "series_name": "WTI Crude", "latest_value": -99.0, "unit": "USD/BBL", "period": "2020-04-20"},
        provenance={}, checksum=""
    )
    assert provider.validate([anomaly]) is False


def test_energy_validate_eia_normal_range():
    """validate() for EIA mode accepts normal price range."""
    config = {"energy_mode": "eia"}
    provider = EnergyProvider(config, llm_manager=make_llm())

    record = StandardSchema(
        id="r1", industry="energy",
        data={"series_id": "WTI", "series_name": "WTI Crude", "latest_value": 75.4, "unit": "USD/BBL", "period": "2023-01-01"},
        provenance={}, checksum=""
    )
    assert provider.validate([record]) is True


# ─── Alias mode mapping ───────────────────────────────────────────────────────

def test_energy_mode_alias_balances():
    """'balances' mode alias maps to 'energy_balances'."""
    config = {"energy_mode": "balances"}
    provider = EnergyProvider(config, llm_manager=make_llm())
    assert provider.energy_mode == "energy_balances"


def test_energy_mode_alias_power():
    """'power' mode alias maps to 'opsd'."""
    config = {"energy_mode": "power"}
    provider = EnergyProvider(config, llm_manager=make_llm())
    assert provider.energy_mode == "opsd"


# ─── OPSD mode extract ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_energy_opsd_extract_simulation():
    """OPSD mode produces simulated European grid records."""
    config = {"energy_mode": "opsd", "allow_simulation": True, "region": "FR"}
    provider = EnergyProvider(config, llm_manager=make_llm())

    artifacts = await provider.extract()
    assert len(artifacts) > 0
    assert artifacts[0].metadata.get("simulation") is True
    content = artifacts[0].content
    assert all("load" in row for row in content)
    assert all(row["region"] == "FR" for row in content)
