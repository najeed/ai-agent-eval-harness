import json
import logging

import pytest

from eval_runner import config


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Isolated .aes/config tree for discovery testing."""
    config_root = tmp_path / "aes_config"
    config_root.mkdir()

    # Patch the config directory
    monkeypatch.setattr(config, "AES_CONFIG_DIR", config_root)
    # Clear cache
    config.RegistryManager.reload()

    return config_root


def test_forensics_auto_nesting(isolated_config):
    """Verify flat policy.json in forensics/ is auto-nested."""
    f_dir = isolated_config / "forensics"
    f_dir.mkdir()

    policy = {"extensions": [".log", ".txt"], "max_artifact_size": 100}
    (f_dir / "policy.json").write_text(json.dumps(policy))

    config.RegistryManager.reload()
    registry = config.RegistryManager.get_resolved_registry()

    assert "forensics" in registry
    assert registry["forensics"]["extensions"] == [".log", ".txt"]
    assert registry["forensics"]["max_artifact_size"] == 100


def test_routing_auto_nesting_and_mappings(isolated_config):
    """Verify flat manifest.json in routing/ is nested into routing.mappings."""
    r_dir = isolated_config / "routing"
    r_dir.mkdir()

    mappings = {"agent_a": {"protocol": "http", "endpoint": "url_a"}}
    # Structure: flat mappings at root (as in user's manifest.json)
    (r_dir / "manifest.json").write_text(json.dumps({"mappings": mappings}))

    config.RegistryManager.reload()
    registry = config.RegistryManager.get_resolved_registry()

    assert "routing" in registry
    assert "mappings" in registry["routing"]
    assert registry["routing"]["mappings"]["agent_a"]["endpoint"] == "url_a"


def test_routing_d_merging(isolated_config):
    """Verify that routing.d fragments are merged into the same bucket."""
    # 1. Base manifest
    r_dir = isolated_config / "routing"
    r_dir.mkdir()
    (r_dir / "manifest.json").write_text(
        json.dumps({"mappings": {"base": {"protocol": "http", "endpoint": "base_url"}}})
    )

    # 2. Extension in routing.d
    rd_dir = isolated_config / "routing.d"
    rd_dir.mkdir()
    (rd_dir / "99_overrides.json").write_text(
        json.dumps({"mappings": {"extra": {"protocol": "local", "endpoint": "extra_cmd"}}})
    )

    config.RegistryManager.reload()
    registry = config.RegistryManager.get_resolved_registry()

    mapping_root = registry["routing"]["mappings"]
    assert "base" in mapping_root
    assert "extra" in mapping_root
    assert mapping_root["extra"]["protocol"] == "local"


def test_alphabetical_priority_across_dirs(isolated_config):
    """Verify that subdirectories are processed in a deterministic order within buckets."""
    # routing (lower alphabetical) vs routing.d (higher alphabetical)
    # Both map to the 'routing' bucket.

    r_dir = isolated_config / "routing"
    r_dir.mkdir()
    (r_dir / "01_core.json").write_text(json.dumps({"mappings": {"shared": "from_routing"}}))

    rd_dir = isolated_config / "routing.d"
    rd_dir.mkdir()
    (rd_dir / "01_core.json").write_text(json.dumps({"mappings": {"shared": "from_routing_d"}}))

    config.RegistryManager.reload()
    registry = config.RegistryManager.get_resolved_registry()

    # 'routing.d' follows 'routing' alphabetically, so it should win.
    assert registry["routing"]["mappings"]["shared"] == "from_routing_d"


def test_discovery_error_logging(isolated_config, caplog):
    """Verify that failed loads are logged correctly."""
    r_dir = isolated_config / "routing"
    r_dir.mkdir()
    (r_dir / "manifest.json").write_text("{corrupt: json}")

    with caplog.at_level(logging.ERROR):
        config.RegistryManager.reload()

    assert "Failed to load routing manifest" in caplog.text


def test_junk_extension_exclusion_logic():
    """Verify that .log is no longer in the junk list."""
    from eval_runner.config import SYSTEM_JUNK_EXTENSIONS

    assert ".log" not in SYSTEM_JUNK_EXTENSIONS
    assert ".tmp" in SYSTEM_JUNK_EXTENSIONS
