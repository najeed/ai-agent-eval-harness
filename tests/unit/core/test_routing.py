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
