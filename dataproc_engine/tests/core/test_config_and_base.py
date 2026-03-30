"""
test_config_and_base.py
Coverage for core/config.py and core/base_provider.py gaps:
  - ConfigLoader.load_secrets() warning paths
  - ConfigLoader.get_config() with overrides
  - StandardSchema.create() factory
  - BaseProvider.load_raw_data() edge cases
  - BaseProvider.heuristic_transform() default behavior
"""
import os
import pytest
import pandas as pd
from unittest.mock import patch
from dataproc_engine.core.config import ConfigLoader
from dataproc_engine.core.base_provider import BaseProvider, StandardSchema, RawArtifact
from dataproc_engine.core.llm_manager import LLMManager


# ─── ConfigLoader ─────────────────────────────────────────────────────────────

def test_config_load_secrets_finance_no_env_vars():
    """ConfigLoader.load_secrets warns but returns dict when env vars are missing."""
    with patch.dict(os.environ, {}, clear=True):
        # Remove keys if present
        env = {k: v for k, v in os.environ.items()
               if k not in ("SEC_USER_AGENT", "FRED_API_KEY")}
        with patch.dict(os.environ, env, clear=True):
            secrets = ConfigLoader.load_secrets("finance")
    assert isinstance(secrets, dict)
    assert "sec_user_agent" in secrets
    assert "fred_api_key" in secrets
    # Values should be None when env vars are absent
    assert secrets["sec_user_agent"] is None
    assert secrets["fred_api_key"] is None


def test_config_load_secrets_finance_with_env_vars():
    """ConfigLoader.load_secrets returns values when env vars are set."""
    with patch.dict(os.environ, {"SEC_USER_AGENT": "TestAgent/1.0", "FRED_API_KEY": "test_key_123"}):
        secrets = ConfigLoader.load_secrets("finance")
    assert secrets["sec_user_agent"] == "TestAgent/1.0"
    assert secrets["fred_api_key"] == "test_key_123"


def test_config_load_secrets_unknown_industry():
    """ConfigLoader.load_secrets returns empty dict for unknown industry."""
    secrets = ConfigLoader.load_secrets("unknown_industry")
    assert secrets == {}


def test_config_get_config_defaults():
    """ConfigLoader.get_config returns base config with env-var defaults."""
    with patch.dict(os.environ, {}, clear=True):
        config = ConfigLoader.get_config()
    assert "rate_limit" in config
    assert "limit" in config
    assert isinstance(config["rate_limit"], float)
    assert isinstance(config["limit"], int)


def test_config_get_config_with_overrides():
    """ConfigLoader.get_config merges overrides correctly."""
    overrides = {"limit": 42, "custom_field": "test_value"}
    config = ConfigLoader.get_config(overrides=overrides)

    assert config["limit"] == 42
    assert config["custom_field"] == "test_value"
    # Base keys still present
    assert "rate_limit" in config


def test_config_get_config_env_overrides():
    """ConfigLoader.get_config reads DATAPROC_RATE_LIMIT and DATAPROC_LIMIT from env."""
    with patch.dict(os.environ, {"DATAPROC_RATE_LIMIT": "2.5", "DATAPROC_LIMIT": "25"}):
        config = ConfigLoader.get_config()
    assert config["rate_limit"] == pytest.approx(2.5)
    assert config["limit"] == 25


# ─── StandardSchema.create() factory ─────────────────────────────────────────

def test_standard_schema_create_auto_generates_id_and_checksum():
    """StandardSchema.create() auto-generates id and checksum if not provided."""
    schema = StandardSchema.create(
        industry="finance",
        data={"revenue": 1000.0, "profit": 100.0},
        provenance={"source": "test://source"}
    )
    assert schema.id is not None
    assert len(schema.id) == 16  # md5 truncated
    assert schema.checksum is not None
    assert len(schema.checksum) == 64  # sha256 hex
    assert schema.industry == "finance"


def test_standard_schema_create_with_explicit_id():
    """StandardSchema.create() respects explicit record_id."""
    schema = StandardSchema.create(
        industry="healthcare",
        data={"glucose": 110.0},
        provenance={},
        record_id="custom-id-001"
    )
    assert schema.id == "custom-id-001"


def test_standard_schema_create_checksum_deterministic():
    """StandardSchema.create() produces the same checksum for the same data."""
    data = {"x": 1.0, "y": 2.0}
    s1 = StandardSchema.create(industry="test", data=data, provenance={})
    s2 = StandardSchema.create(industry="test", data=data, provenance={})
    assert s1.checksum == s2.checksum
    assert s1.id == s2.id


def test_standard_schema_to_dict_flattens_data():
    """StandardSchema.to_dict() flattens data fields into root dict."""
    schema = StandardSchema.create(
        industry="energy",
        data={"series_id": "WTI", "latest_value": 75.4},
        provenance={"source": "eia.gov"}
    )
    flat = schema.to_dict()
    assert "series_id" in flat
    assert "latest_value" in flat
    assert flat["industry"] == "energy"
    assert flat["series_id"] == "WTI"


def test_standard_schema_from_pandas_series():
    """StandardSchema.from_pandas() processes a single pandas Series row."""
    row = pd.Series({"id": "r001", "val": 42.0, "label": "test"})
    schema = StandardSchema.from_pandas(row, industry="manufacturing")

    assert schema.industry == "manufacturing"
    assert schema.id == "r001"
    assert "val" in schema.data


def test_standard_schema_from_pandas_with_provenance_fields():
    """StandardSchema.from_pandas() extracts provenance fields from row."""
    row = pd.Series({
        "id": "r002",
        "val": 99.0,
        "source": "test://source",
        "retrieved_at": "2023-01-01"
    })
    schema = StandardSchema.from_pandas(row, industry="finance")

    # source and retrieved_at should be in provenance, not data
    assert "source" in schema.provenance
    assert "source" not in schema.data
    assert "retrieved_at" in schema.provenance


# ─── BaseProvider edge cases ──────────────────────────────────────────────────

class ConcreteProvider(BaseProvider):
    """Minimal concrete implementation of BaseProvider for testing."""
    async def extract(self):
        return []

    async def transform(self, raw_artifacts):
        return []

    def validate(self, normalized_data):
        return True


def test_base_provider_load_raw_data_nonexistent_file():
    """load_raw_data returns None for non-existent file path."""
    provider = ConcreteProvider({}, llm_manager=LLMManager({"llm_strategy": "mock"}))
    result = provider.load_raw_data("non_existent_file_xyz.csv")
    assert result is None


def test_base_provider_load_raw_data_empty_path():
    """load_raw_data returns None when path is empty/None."""
    provider = ConcreteProvider({}, llm_manager=LLMManager({"llm_strategy": "mock"}))
    assert provider.load_raw_data("") is None
    assert provider.load_raw_data(None) is None


def test_base_provider_load_raw_data_valid_csv(tmp_path):
    """load_raw_data successfully loads a valid CSV file."""
    csv_file = tmp_path / "test_data.csv"
    csv_file.write_text("col1,col2\n1,2\n3,4")

    provider = ConcreteProvider({}, llm_manager=LLMManager({"llm_strategy": "mock"}))
    df = provider.load_raw_data(str(csv_file))

    assert df is not None
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert list(df.columns) == ["col1", "col2"]


def test_base_provider_heuristic_transform_returns_none():
    """heuristic_transform base implementation returns None by default."""
    provider = ConcreteProvider({}, llm_manager=LLMManager({"llm_strategy": "mock"}))
    result = provider.heuristic_transform("some content", {"field": "string"})
    assert result is None


def test_base_provider_scrub_pii_email():
    """scrub_pii redacts email addresses."""
    provider = ConcreteProvider({}, llm_manager=LLMManager({"llm_strategy": "mock"}))
    result = provider.scrub_pii("Contact us at user@example.com for support.")
    assert "user@example.com" not in result
    assert "[EMAIL]" in result


def test_base_provider_scrub_pii_phone():
    """scrub_pii redacts phone numbers."""
    provider = ConcreteProvider({}, llm_manager=LLMManager({"llm_strategy": "mock"}))
    result = provider.scrub_pii("Call us at 555-867-5309 for assistance.")
    assert "555-867-5309" not in result
    assert "[PHONE]" in result


def test_base_provider_scrub_pii_non_string():
    """scrub_pii coerces non-string input to string."""
    provider = ConcreteProvider({}, llm_manager=LLMManager({"llm_strategy": "mock"}))
    result = provider.scrub_pii(12345)
    assert isinstance(result, str)


def test_base_provider_circuit_breaker_initial_state():
    """Circuit breaker starts closed (not open) and failure count is zero."""
    provider = ConcreteProvider({}, llm_manager=LLMManager({"llm_strategy": "mock"}))
    assert provider._circuit_open is False
    assert provider._failure_count == 0


def test_base_provider_simulation_enabled_by_default():
    """allow_simulation defaults to True from BaseProvider."""
    provider = ConcreteProvider({})
    assert provider.allow_simulation is True


def test_base_provider_simulation_disabled_via_config():
    """allow_simulation can be disabled via config."""
    provider = ConcreteProvider({"allow_simulation": False})
    assert provider.allow_simulation is False


def test_base_provider_create_simulated_artifact():
    """create_simulated_artifact always tags artifact with simulation=True and sim- prefix."""
    provider = ConcreteProvider({})
    artifact = provider.create_simulated_artifact(
        id="test-123",
        content={"key": "value"},
        source_url="test://url",
        metadata={"extra": "data"}
    )
    assert isinstance(artifact, RawArtifact)
    assert artifact.id.startswith("sim-")
    assert artifact.metadata.get("simulation") is True
    assert artifact.metadata.get("extra") == "data"
    assert artifact.source_url == "test://url"
