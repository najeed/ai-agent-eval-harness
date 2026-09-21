from eval_runner.engine import AgentAdapterRegistry


def test_adapter_discovery():
    # Force reset discovery
    AgentAdapterRegistry.reset()

    # Use a permissive mock to allow core protocol registration for verification
    from unittest.mock import patch

    from eval_runner import config

    try:
        with patch(
            "eval_runner.config.RegistryManager.get_resolved_registry",
            return_value={"adapters": {"active_protocols": ["http", "local", "socket"]}},
        ):
            AgentAdapterRegistry._discover()
            assert "http" in AgentAdapterRegistry._adapters
            assert "local" in AgentAdapterRegistry._adapters
            assert "socket" in AgentAdapterRegistry._adapters
    finally:
        config.RegistryManager.reload()
        AgentAdapterRegistry.reset()
