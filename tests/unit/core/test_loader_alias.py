"""
Unit tests for Scenario ID alias resolution in the loader.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from eval_runner import loader
from eval_runner.catalog import ScenarioCatalog


@pytest.fixture
def mock_catalog():
    """Fixture to reset and provide a mocked ScenarioCatalog."""
    ScenarioCatalog.clear_instance()
    with patch("eval_runner.catalog.ScenarioCatalog.get_instance") as mock_get:
        instance = MagicMock(spec=ScenarioCatalog)
        mock_get.return_value = instance
        yield instance


def get_minimal_scenario(scenario_id: str) -> dict:
    return {
        "aes_version": 1.4,
        "metadata": {"id": scenario_id, "name": "test", "compliance_level": "Standard"},
        "workflow": {"nodes": [], "edges": []},
        "evaluation": {"metrics": []},
    }


def test_load_scenario_by_id_alias(tmp_path, mock_catalog):
    """Verify that load_scenario prioritizes Scenario ID resolution."""
    scenario_path = tmp_path / "actual_scenario.json"
    scenario_data = get_minimal_scenario("my-id")
    scenario_path.write_text(json.dumps(scenario_data))

    # Mock catalog to resolve 'my-alias' to the tmp file
    mock_catalog.get_absolute_path.return_value = scenario_path

    # Act
    loaded = loader.load_scenario("my-alias")

    # Assert
    assert loaded["metadata"]["id"] == "my-id"
    mock_catalog.get_absolute_path.assert_called_once_with("my-alias")


def test_load_scenario_by_relative_path_fallback(tmp_path, mock_catalog):
    """Verify that load_scenario falls back to relative path if ID resolution fails."""
    scenario_path = tmp_path / "rel_scenario.json"
    scenario_data = get_minimal_scenario("rel-id")
    scenario_path.write_text(json.dumps(scenario_data))

    # Mock catalog to NOT find the alias
    mock_catalog.get_absolute_path.return_value = None

    # Act
    # We use str(scenario_path) to simulate a project-relative path that exists
    loaded = loader.load_scenario(str(scenario_path))

    # Assert
    assert loaded["metadata"]["id"] == "rel-id"
    mock_catalog.get_absolute_path.assert_called_once()


def test_load_scenario_not_found_error_message(mock_catalog):
    """Verify that the error message contains the catalog hint when resolution fails."""
    mock_catalog.get_absolute_path.return_value = None

    with pytest.raises(FileNotFoundError) as excinfo:
        loader.load_scenario("non-existent-thing")

    assert "If this is a Scenario ID, ensure the catalog is indexed" in str(excinfo.value)
    assert "verify the project-relative path" in str(excinfo.value)


def test_load_dataset_by_id_alias(tmp_path, mock_catalog):
    """Verify that load_dataset supports Scenario ID aliases."""
    scenario_path = tmp_path / "dataset_scenario.json"
    scenario_data = get_minimal_scenario("ds-id")
    scenario_path.write_text(json.dumps(scenario_data))

    mock_catalog.get_absolute_path.return_value = scenario_path

    # Act
    results = loader.load_dataset("ds-alias")

    # Assert
    assert len(results) == 1
    assert results[0]["metadata"]["id"] == "ds-id"
    mock_catalog.get_absolute_path.assert_any_call("ds-alias")


@patch("eval_runner.catalog.ScenarioCatalog.load_index")
def test_catalog_get_absolute_path_auto_loads_index(mock_load_index):
    """Verify that get_absolute_path calls load_index if scenarios are empty."""
    ScenarioCatalog.clear_instance()
    catalog = ScenarioCatalog.get_instance()

    # Force scenarios to be empty (default)
    catalog.scenarios = []

    # Act
    catalog.get_absolute_path("any-id")

    # Assert
    mock_load_index.assert_called_once()
