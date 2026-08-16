"""
tests/unit/test_resolved_runtime_config.py
Validation for ResolvedRuntimeConfig and ConfigResolver.
"""

import json

from eval_runner.config_resolver import ConfigResolver, ResolvedRuntimeConfig


def test_resolved_runtime_config_defaults_and_hash():
    cfg = ResolvedRuntimeConfig(
        run_log_dir="runs",
        audit_level=2,
        execution_backend="in_process",
        checkpoint_store="sqlite",
    )
    assert cfg.audit_level == 2
    assert cfg.execution_backend == "in_process"
    assert len(cfg.config_hash) == 64  # Valid SHA-256

    # Determinism
    cfg2 = ResolvedRuntimeConfig(
        run_log_dir="runs",
        audit_level=2,
        execution_backend="in_process",
        checkpoint_store="sqlite",
    )
    assert cfg.config_hash == cfg2.config_hash


def test_config_resolver_hierarchy(tmp_path, monkeypatch):
    # 1. File config
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    with open(cfg_dir / "01_base.json", "w") as f:
        json.dump({"audit_level": 3, "timeout_seconds": 300}, f)

    # 2. Env override
    monkeypatch.setenv("AUDIT_LEVEL", "4")

    # 3. Explicit override
    resolved = ConfigResolver.resolve(
        overrides={"timeout_seconds": 600, "custom_tag": "fintech_v1"},
        config_dir=cfg_dir,
    )

    assert resolved.audit_level == 4  # Env overrides file
    assert resolved.timeout_seconds == 600  # Explicit overrides file
    assert resolved.custom_settings["custom_tag"] == "fintech_v1"
    assert resolved.config_hash != ""
