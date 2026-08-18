"""
tests/contracts/test_plugin_discovery_contract.py
Contract Test: Plugin Entry-Point Discovery & Plugin API

Validates that the plugin discovery mechanism (both entry-point-based and
hook-based) and base plugin contract remain stable. Breakage requires a MAJOR semver bump.
"""

from __future__ import annotations

from eval_runner.plugins import BaseEvalPlugin, PluginManager


class TestPluginDiscoveryContract:
    """
    Plugin Discovery Contract Tests.
    These tests verify the public plugin lifecycle: discovery, registration,
    hook definitions, and extension families stability.
    """

    def test_plugin_manager_is_importable(self):
        """Contract: eval_runner.plugins.PluginManager is importable from the public API."""
        assert PluginManager is not None

    def test_base_eval_plugin_hooks_contract(self):
        """
        Contract: BaseEvalPlugin defines the 7 standard lifecycle hook methods.
        Removing or renaming any hook is a MAJOR contract violation.
        """
        expected_hooks = [
            "before_evaluation",
            "after_evaluation",
            "on_register_commands",
            "on_discover_adapters",
            "on_register_simulators",
            "on_discover_metrics",
            "on_diagnose_failure",
        ]
        for hook_name in expected_hooks:
            assert hasattr(BaseEvalPlugin, hook_name), (
                f"BaseEvalPlugin is missing expected lifecycle hook: '{hook_name}'. "
                "This is a MAJOR plugin contract violation."
            )

    def test_plugin_registration_and_persistence(self, tmp_path, monkeypatch):
        """
        Contract: PluginManager registers persistent plugins and reflects them in the registry.
        """
        registry_file = tmp_path / "registry.json"
        from eval_runner import plugins

        monkeypatch.setattr(plugins, "PERSISTENT_PLUGINS_PATH", registry_file)

        plugin_file = tmp_path / "custom_test_plugin.py"
        plugin_file.write_text(
            "from eval_runner.plugins import BaseEvalPlugin\n"
            "class CustomTestPlugin(BaseEvalPlugin):\n"
            "    pass\n",
            encoding="utf-8",
        )

        pm = PluginManager()
        pm.register_persistent(str(plugin_file))
        assert registry_file.exists()

    def test_agentv_runtime_namespace_stability(self):
        """
        Contract: agentv_runtime exposes the canonical extension families namespace.
        These imports must not break across minor or patch releases.
        """
        from agentv_runtime.interfaces import (
            ArtifactStore,
            AuthorizationBackend,
            AuthPrincipal,
            CheckpointStore,
            ExecutionBackend,
            PolicyEvaluationResult,
            PolicyEvaluator,
            SigningBackend,
        )

        for symbol in (
            ExecutionBackend,
            CheckpointStore,
            SigningBackend,
            ArtifactStore,
            PolicyEvaluator,
            PolicyEvaluationResult,
            AuthorizationBackend,
            AuthPrincipal,
        ):
            assert symbol is not None, f"agentv_runtime.interfaces export missing: {symbol}"

    def test_agentv_runtime_reference_stability(self):
        """
        Contract: agentv_runtime.reference exposes canonical OSS implementations.
        These imports must not break across minor or patch releases.
        """
        from agentv_runtime.reference import (
            BasicFieldPolicyEvaluator,
            InProcessExecutionBackend,
            LocalFileArtifactStore,
            SQLiteCheckpointStore,
        )

        for symbol in (
            InProcessExecutionBackend,
            SQLiteCheckpointStore,
            LocalFileArtifactStore,
            BasicFieldPolicyEvaluator,
        ):
            assert symbol is not None, f"agentv_runtime.reference export missing: {symbol}"
