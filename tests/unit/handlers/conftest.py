import pytest

from eval_runner.catalog import ScenarioCatalog


@pytest.fixture
def mock_catalog_dir(tmp_path, monkeypatch):
    """Setup a controlled project root for catalog tests."""
    root = tmp_path / "project"
    root.mkdir()
    scenarios_dir = root / "scenarios"
    scenarios_dir.mkdir()

    # Needs to be a string or Path depending on config expectations
    monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", root)

    # Reset singleton
    if hasattr(ScenarioCatalog, "_instance"):
        ScenarioCatalog._instance = None

    return root
