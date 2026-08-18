"""
tests/contracts/test_config_hash_contract.py
Contract Test: ResolvedRuntimeConfig Hash Stability

Verifies that the deterministic SHA3-256 config_hash is stable across runs
with identical inputs, and that any change to a config field produces a
different hash. These properties are architectural guarantees under CC8.1.
"""

from __future__ import annotations

import hashlib
import json

from eval_runner.config_resolver import ConfigResolver, ResolvedRuntimeConfig


class TestConfigHashContract:
    """
    Config Hash Stability Contract Tests.
    """

    def test_identical_configs_produce_identical_hash(self):
        """
        Contract: Two ResolvedRuntimeConfig instances with the same values
        must produce the exact same config_hash.
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
            custom_settings={},
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
            custom_settings={},
        )
        assert cfg1.config_hash == cfg2.config_hash, (
            "Identical configs produced different hashes — hash is non-deterministic."
        )

    def test_different_configs_produce_different_hash(self):
        """
        Contract: Changing any field in ResolvedRuntimeConfig must change the config_hash.
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
            timeout_seconds=300,  # changed
        )
        assert base.config_hash != mutated.config_hash, (
            "Mutated config produced the same hash — hash is not collision-resistant."
        )

    def test_config_hash_uses_sha3_256(self):
        """
        Contract: The hash algorithm must be SHA3-256 (not SHA-256 or MD5).
        """
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
            custom_settings={},
        )
        # Manually reproduce using sha3_256
        data_dict = {
            "run_log_dir": "/runs",
            "audit_level": 2,
            "execution_backend": "in_process",
            "checkpoint_store": "sqlite",
            "artifact_store": "local_file",
            "signing_key_path": None,
            "fail_closed_signing": True,
            "timeout_seconds": 120,
            "enable_hitl": True,
            "custom_settings": {},
        }
        expected = hashlib.sha3_256(
            json.dumps(data_dict, sort_keys=True).encode("utf-8")
        ).hexdigest()
        assert cfg.config_hash == expected, (
            "config_hash algorithm is not SHA3-256. A change to this algorithm is a "
            "MAJOR contract violation."
        )

    def test_config_hash_is_64_hex_chars(self):
        """
        Contract: SHA3-256 hashes must always be 64 lowercase hexadecimal characters.
        """
        cfg = ResolvedRuntimeConfig()
        assert len(cfg.config_hash) == 64
        assert all(c in "0123456789abcdef" for c in cfg.config_hash)

    def test_config_resolver_resolve_returns_resolved_runtime_config(self):
        """
        Contract: ConfigResolver.resolve() always returns a ResolvedRuntimeConfig instance.
        """
        result = ConfigResolver.resolve()
        assert isinstance(result, ResolvedRuntimeConfig), (
            f"ConfigResolver.resolve() returned {type(result)}, expected ResolvedRuntimeConfig."
        )

    def test_config_resolver_override_is_reflected(self):
        """
        Contract: Explicit overrides passed to ConfigResolver.resolve() are reflected
        in the returned ResolvedRuntimeConfig.
        """
        result = ConfigResolver.resolve(overrides={"timeout_seconds": 999, "audit_level": 3})
        assert result.timeout_seconds == 999
        assert result.audit_level == 3

    def test_config_resolver_override_changes_hash(self):
        """
        Contract: Changing an override must change the config_hash, proving
        hash reflects the actual resolved values.
        """
        base = ConfigResolver.resolve(overrides={"timeout_seconds": 60})
        modified = ConfigResolver.resolve(overrides={"timeout_seconds": 180})
        assert base.config_hash != modified.config_hash
