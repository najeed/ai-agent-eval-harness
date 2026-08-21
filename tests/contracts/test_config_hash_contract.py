"""
tests/contracts/test_config_hash_contract.py
Contract Test: ResolvedRuntimeConfig Hash Stability & Lossless Mesh Preservation

Verifies that:
1. Deterministic SHA3-256 config_hash covers all namespaces
(core, adapters, plugins, policies, custom_settings).
2. ConfigResolver preserves arbitrary drop-in config keys without loss.
3. Overrides, mandates, and namespaces are deterministically hashed.
"""

from __future__ import annotations

import hashlib
import json

from eval_runner.config_resolver import ConfigResolver, ResolvedRuntimeConfig


class TestConfigHashContract:
    """
    Config Hash Stability & Lossless Config-Mesh Contract Tests.
    """

    def test_identical_configs_produce_identical_hash(self):
        """
        Contract: Two ResolvedRuntimeConfig instances
        with the same values produce identical hash.
        """
        cfg1 = ResolvedRuntimeConfig(
            run_log_dir="/runs",
            audit_level=2,
            execution_backend="in_process",
            checkpoint_store="sqlite",
            artifact_store="local_file",
            signing_key_path=None,
            fail_closed_signing=True,
            timeout_seconds=120,
            enable_hitl=True,
            adapters={"bedrock": {"region": "us-east-1"}},
            plugins={"recorder": {"enabled": True}},
            policies={"max_spend": 1000},
            custom_settings={"enterprise_key": "val_123"},
        )
        cfg2 = ResolvedRuntimeConfig(
            run_log_dir="/runs",
            audit_level=2,
            execution_backend="in_process",
            checkpoint_store="sqlite",
            artifact_store="local_file",
            signing_key_path=None,
            fail_closed_signing=True,
            timeout_seconds=120,
            enable_hitl=True,
            adapters={"bedrock": {"region": "us-east-1"}},
            plugins={"recorder": {"enabled": True}},
            policies={"max_spend": 1000},
            custom_settings={"enterprise_key": "val_123"},
        )
        assert cfg1.config_hash == cfg2.config_hash

    def test_different_configs_produce_different_hash(self):
        """
        Contract: Changing any field or namespace in ResolvedRuntimeConfig
        must change config_hash.
        """
        base = ResolvedRuntimeConfig(
            run_log_dir="/runs",
            audit_level=2,
            execution_backend="in_process",
            timeout_seconds=120,
        )
        mutated = ResolvedRuntimeConfig(
            run_log_dir="/runs",
            audit_level=2,
            execution_backend="in_process",
            timeout_seconds=300,
        )
        assert base.config_hash != mutated.config_hash

    def test_config_hash_uses_sha3_256(self):
        """Contract: The hash algorithm must be SHA3-256 over all typed namespaces."""
        cfg = ResolvedRuntimeConfig(
            run_log_dir="/runs",
            audit_level=2,
            execution_backend="in_process",
            checkpoint_store="sqlite",
            artifact_store="local_file",
            signing_key_path=None,
            fail_closed_signing=True,
            timeout_seconds=120,
            enable_hitl=True,
            adapters={},
            plugins={},
            policies={},
            custom_settings={},
        )
        data_dict = {
            "core": {
                "run_log_dir": "/runs",
                "audit_level": 2,
                "execution_backend": "in_process",
                "checkpoint_store": "sqlite",
                "artifact_store": "local_file",
                "signing_key_path": None,
                "fail_closed_signing": True,
                "timeout_seconds": 120,
                "enable_hitl": True,
            },
            "adapters": {},
            "plugins": {},
            "policies": {},
            "custom_settings": {},
        }
        expected = hashlib.sha3_256(
            json.dumps(data_dict, sort_keys=True).encode("utf-8")
        ).hexdigest()
        assert cfg.config_hash == expected

    def test_config_hash_is_64_hex_chars(self):
        """Contract: SHA3-256 hashes must always be 64 lowercase hexadecimal characters."""
        cfg = ResolvedRuntimeConfig()
        assert len(cfg.config_hash) == 64
        assert all(c in "0123456789abcdef" for c in cfg.config_hash)

    def test_config_resolver_resolve_returns_resolved_runtime_config(self):
        """Contract: ConfigResolver.resolve() always returns a ResolvedRuntimeConfig instance."""
        result = ConfigResolver.resolve()
        assert isinstance(result, ResolvedRuntimeConfig)

    def test_config_resolver_lossless_arbitrary_key_preservation(self, tmp_path):
        """
        Contract: Arbitrary drop-in configuration keys loaded from .d/ drop-ins or overrides
        are strictly preserved in typed namespaces or custom_settings rather than discarded.
        """
        config_dir = tmp_path / "config"
        drop_in_dir = config_dir / "plugins.d"
        drop_in_dir.mkdir(parents=True)
        drop_file = drop_in_dir / "enterprise_mesh.json"
        drop_file.write_text(
            json.dumps(
                {
                    "enterprise_auth": {"provider": "okta", "tenant": "corp"},
                    "adapters": {"custom_llm": {"api_base": "https://llm.corp"}},
                    "policies": {"spend_cap": 5000},
                    "arbitrary_top_level_key": "must_not_be_lost",
                }
            ),
            encoding="utf-8",
        )

        resolved = ConfigResolver.resolve(config_dir=config_dir)

        # 1. Assert adapters preserved
        assert "custom_llm" in resolved.adapters
        assert resolved.adapters["custom_llm"]["api_base"] == "https://llm.corp"

        # 2. Assert policies preserved
        assert resolved.policies.get("spend_cap") == 5000

        # 3. Assert arbitrary keys preserved in custom_settings
        assert "enterprise_auth" in resolved.custom_settings
        assert resolved.custom_settings["enterprise_auth"]["tenant"] == "corp"
        assert resolved.custom_settings["arbitrary_top_level_key"] == "must_not_be_lost"

        # 4. Assert config_hash includes the preserved keys
        assert resolved.config_hash != ConfigResolver.resolve().config_hash

    def test_execution_manifest_hash_and_serialization(self):
        """
        Contract: ExecutionManifest from_dict and compute_manifest_hash produce
        deterministic SHA3-256 digests over multi-tenant context.
        """
        from agentv_runtime.manifest import ExecutionManifest, ManifestBuilder

        scen_data = {
            "metadata": {"id": "test-scen", "version": "2.1.0"},
            "workflow": {"nodes": [{"id": "node1"}]},
        }
        manifest = ManifestBuilder.build(
            scenario_data=scen_data,
            agent_config={"model": "gpt-4o", "endpoint": "http://localhost:8000"},
            runtime_config={"max_turns": 5},
            tenant_id="tenant-alpha",
            workspace_id="ws-beta",
            created_by="alice",
            metadata={"tag": "qa"},
        )
        manifest_dict = manifest.to_dict()
        rehydrated = ExecutionManifest.from_dict(manifest_dict)

        assert rehydrated.manifest_id == manifest.manifest_id
        assert rehydrated.tenant_id == "tenant-alpha"
        assert rehydrated.workspace_id == "ws-beta"
        assert rehydrated.agent_config["model"] == "gpt-4o"

        manifest_hash = rehydrated.compute_manifest_hash()
        assert manifest_hash.startswith("sha3_256:")
        assert len(manifest_hash.split(":")[1]) == 64
