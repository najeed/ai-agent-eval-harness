import json

import pytest

from eval_runner import config
from eval_runner.routing import RoutingRegistry


@pytest.fixture
def temp_routing_root(tmp_path):
    """Fixture to provide a isolated routing environment."""
    original_config_dir = config.AES_CONFIG_DIR
    original_routing_path = config.ROUTING_CONFIG_PATH
    original_routing_d = config.ROUTING_D_DIR

    config_dir = tmp_path / "config"
    routing_dir = config_dir / "routing"
    routing_d = config_dir / "routing.d"

    routing_dir.mkdir(parents=True)
    routing_d.mkdir(parents=True)

    config.AES_CONFIG_DIR = config_dir
    config.ROUTING_CONFIG_PATH = routing_dir / "manifest.json"
    config.ROUTING_D_DIR = routing_d

    RoutingRegistry.reload()

    yield {"manifest": config.ROUTING_CONFIG_PATH, "d_dir": config.ROUTING_D_DIR}

    # Restore
    config.AES_CONFIG_DIR = original_config_dir
    config.ROUTING_CONFIG_PATH = original_routing_path
    config.ROUTING_D_DIR = original_routing_d
    RoutingRegistry.reload()


def test_routing_resolve_default(temp_routing_root):
    """Verify default fallback when no match is found."""
    manifest = {"mappings": {"default": {"protocol": "http", "endpoint": "http://default-agent"}}}
    with open(temp_routing_root["manifest"], "w") as f:
        json.dump(manifest, f)

    RoutingRegistry.reload()
    resolved = RoutingRegistry.resolve(["non_existent"])

    assert resolved["endpoint"] == "http://default-agent"
    assert resolved["protocol"] == "http"


def test_routing_resolve_exact_match(temp_routing_root):
    """Verify exact capability match."""
    manifest = {
        "mappings": {
            "fintech_agent": {"protocol": "http", "endpoint": "http://fintech-agent"},
            "default": {"protocol": "http", "endpoint": "http://default-agent"},
        }
    }
    with open(temp_routing_root["manifest"], "w") as f:
        json.dump(manifest, f)

    RoutingRegistry.reload()
    resolved = RoutingRegistry.resolve(["fintech_agent"])

    assert resolved["endpoint"] == "http://fintech-agent"


def test_routing_resolve_extension(temp_routing_root):
    """Verify resolution from .d extension files."""
    manifest = {"mappings": {"default": {"protocol": "http", "endpoint": "http://default-agent"}}}
    with open(temp_routing_root["manifest"], "w") as f:
        json.dump(manifest, f)

    # Add an extension
    ext_path = temp_routing_root["d_dir"] / "99_custom.json"
    with open(ext_path, "w") as f:
        json.dump(
            {
                "mappings": {
                    "custom_capability": {"protocol": "local", "endpoint": "python agent.py"}
                }
            },
            f,
        )

    RoutingRegistry.reload()
    resolved = RoutingRegistry.resolve(["custom_capability"])

    assert resolved["protocol"] == "local"
    assert resolved["endpoint"] == "python agent.py"


def test_routing_resolve_empty(temp_routing_root):
    """Verify empty dict returned when nothing matches and no default exists."""
    RoutingRegistry.reload()
    resolved = RoutingRegistry.resolve(["something"])
    assert resolved == {}


def test_routing_cache_hit(temp_routing_root):
    """Verify that the cache is utilized on multiple calls."""
    manifest = {"mappings": {"cached": {"protocol": "test", "endpoint": "test"}}}
    with open(temp_routing_root["manifest"], "w") as f:
        json.dump(manifest, f)

    RoutingRegistry.reload()

    # First call loads into cache
    first_res = RoutingRegistry.get_resolved_registry()
    assert "cached" in first_res

    # Modify file on disk - if cache works, we should still get the old value
    with open(temp_routing_root["manifest"], "w") as f:
        json.dump({"mappings": {"new": {"protocol": "new", "endpoint": "new"}}}, f)

    second_res = RoutingRegistry.get_resolved_registry()
    assert "cached" in second_res
    assert "new" not in second_res


def test_routing_yaml_extension(temp_routing_root):
    """Verify loading from YAML extensions."""
    ext_path = temp_routing_root["d_dir"] / "overrides.yaml"
    with open(ext_path, "w") as f:
        f.write("mappings:\n  yaml_cap: {protocol: yaml, endpoint: yaml_url}")

    RoutingRegistry.reload()
    resolved = RoutingRegistry.resolve(["yaml_cap"])
    assert resolved["protocol"] == "yaml"


def test_routing_load_error_handling(temp_routing_root, caplog):
    """Verify that corrupt files don't crash the registry."""
    with open(temp_routing_root["manifest"], "w") as f:
        f.write("{corrupt: json")

    # Should log error and return empty instead of crashing
    RoutingRegistry.reload()
    res = RoutingRegistry.get_resolved_registry()
    assert res == {}
    assert "Failed to load routing manifest" in caplog.text


def test_routing_extension_load_error(temp_routing_root, caplog):
    """Verify that a single corrupt extension doesn't kill others."""
    # Good manifest
    manifest = {"mappings": {"base": {"protocol": "base", "endpoint": "base"}}}
    with open(temp_routing_root["manifest"], "w") as f:
        json.dump(manifest, f)

    # Corrupt extension
    bad_ext = temp_routing_root["d_dir"] / "bad.json"
    bad_ext.write_text("{corrupt}")

    RoutingRegistry.reload()
    res = RoutingRegistry.get_resolved_registry()
    assert "base" in res
    assert "Failed to load routing extension" in caplog.text
