"""
agentv_runtime.config
Resolved Runtime Config and ConfigResolver Boundary with Formal Namespaces (v2.0.0).

Preserves all arbitrary and plugin-specific config-mesh keys across typed namespaces:
  - core: Core runtime execution parameters
  - adapters: Protocol and model adapters
  - plugins: Plugin lifecycle configurations
  - policies: Policy and constraint definitions
  - custom_settings: Arbitrary extension settings
  - mandates: Non-overridable enterprise governance rules
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

CORE_FIELDS = {
    "run_log_dir",
    "audit_level",
    "execution_backend",
    "checkpoint_store",
    "artifact_store",
    "signing_key_path",
    "fail_closed_signing",
    "timeout_seconds",
    "enable_hitl",
}

KNOWN_NAMESPACES = {
    "adapters",
    "plugins",
    "policies",
    "custom_settings",
    "custom",
    "mandates",
    "core",
}


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """Recursively merges source dictionary into target dictionary."""
    for key, val in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(val, dict):
            _deep_merge(target[key], val)
        else:
            target[key] = val
    return target


@dataclass
class ResolvedRuntimeConfig:
    """
    Schema-validated runtime configuration model with lossless typed namespaces.
    Represents the sealed, fully resolved configuration document for an evaluation execution.
    """

    run_log_dir: str = "runs"
    audit_level: int = 2
    execution_backend: str = "in_process"
    checkpoint_store: str = "sqlite"
    artifact_store: str = "local_file"
    signing_key_path: str | None = None
    fail_closed_signing: bool = True
    timeout_seconds: int = 120
    enable_hitl: bool = True
    adapters: dict[str, Any] = field(default_factory=dict)
    plugins: dict[str, Any] = field(default_factory=dict)
    policies: dict[str, Any] = field(default_factory=dict)
    custom_settings: dict[str, Any] = field(default_factory=dict)
    mandates: dict[str, Any] = field(default_factory=dict)
    config_hash: str = ""

    def __post_init__(self):
        # 1. Schema Constraints Validation
        if not isinstance(self.audit_level, int) or self.audit_level < 1:
            raise ValueError(f"Invalid audit_level: {self.audit_level}. Must be positive integer.")

        if not isinstance(self.timeout_seconds, int) or self.timeout_seconds <= 0:
            raise ValueError(f"Invalid timeout_seconds: {self.timeout_seconds}. Must be > 0.")

        if not self.execution_backend or not isinstance(self.execution_backend, str):
            raise ValueError("execution_backend must be a non-empty string identifier.")

        if not self.checkpoint_store or not isinstance(self.checkpoint_store, str):
            raise ValueError("checkpoint_store must be a non-empty string identifier.")

        if not self.artifact_store or not isinstance(self.artifact_store, str):
            raise ValueError("artifact_store must be a non-empty string identifier.")

        # 2. Deterministic Hash Seal
        if not self.config_hash:
            self.config_hash = self.compute_hash()

    def compute_hash(self) -> str:
        """Computes deterministic SHA3-256 hash digest of all configuration namespaces."""
        data_dict = {
            "core": {
                "run_log_dir": str(self.run_log_dir),
                "audit_level": self.audit_level,
                "execution_backend": self.execution_backend,
                "checkpoint_store": self.checkpoint_store,
                "artifact_store": self.artifact_store,
                "signing_key_path": self.signing_key_path,
                "fail_closed_signing": self.fail_closed_signing,
                "timeout_seconds": self.timeout_seconds,
                "enable_hitl": self.enable_hitl,
            },
            "adapters": self.adapters,
            "plugins": self.plugins,
            "policies": self.policies,
            "custom_settings": self.custom_settings,
        }
        if self.mandates:
            data_dict["mandates"] = self.mandates

        canonical_json = json.dumps(data_dict, sort_keys=True)
        return hashlib.sha3_256(canonical_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ConfigResolver:
    """
    Lossless Config-Mesh Resolver.
    Merges configuration sources in hierarchical precedence:
      1. Baseline Defaults
      2. Config files (.aes/config/*.json, *.yaml, and *.d/ drop-in directories)
      3. Environment Variable Overrides
      4. Explicit Runtime Overrides
      5. Immutable Enterprise Mandates (Strict Non-overridable)
    """

    @classmethod
    def resolve(
        cls,
        overrides: dict[str, Any] | None = None,
        config_dir: str | Path | None = None,
        mandates: dict[str, Any] | None = None,
    ) -> ResolvedRuntimeConfig:
        """Resolves config into a validated ResolvedRuntimeConfig preserving all keys."""
        # 1. Base Defaults
        default_audit = 2
        try:
            default_audit = int(os.getenv("AUDIT_LEVEL", "2"))
        except ValueError:
            pass

        default_timeout = 120
        try:
            default_timeout = int(os.getenv("RUN_TIMEOUT_SECONDS", "120"))
        except ValueError:
            pass

        raw_merged: dict[str, Any] = {
            "run_log_dir": "runs",
            "audit_level": default_audit,
            "execution_backend": "in_process",
            "checkpoint_store": "sqlite",
            "artifact_store": "local_file",
            "signing_key_path": os.getenv("EVAL_SIGNING_KEY"),
            "fail_closed_signing": os.getenv("EVAL_SIGNING_FAIL_CLOSED", "true").lower() == "true",
            "timeout_seconds": default_timeout,
            "enable_hitl": os.getenv("ENABLE_HITL", "true").lower() == "true",
            "adapters": {},
            "plugins": {},
            "policies": {},
            "custom_settings": {},
        }

        # 2. File-based configuration (e.g. .aes/config/, *.d directories)
        search_dirs: list[Path] = []
        if config_dir:
            search_dirs.append(Path(config_dir))
        search_dirs.append(Path(".aes") / "config")

        for sdir in search_dirs:
            if sdir.exists() and sdir.is_dir():
                # Read top-level config files
                for cfg_file in sorted(sdir.glob("*.*")):
                    if cfg_file.suffix in (".json", ".yaml", ".yml"):
                        try:
                            with open(cfg_file, encoding="utf-8") as f:
                                file_data = (
                                    yaml.safe_load(f)
                                    if cfg_file.suffix in (".yaml", ".yml")
                                    else json.load(f)
                                )
                                if isinstance(file_data, dict):
                                    _deep_merge(raw_merged, file_data)
                        except Exception as e:
                            logger.debug("Failed to load config file %s: %s", cfg_file, e)

                # Read *.d/ configuration drop-in directories
                for d_dir in sorted(sdir.glob("*.d")):
                    if d_dir.is_dir():
                        for drop_file in sorted(d_dir.glob("*.*")):
                            if drop_file.suffix in (".json", ".yaml", ".yml"):
                                try:
                                    with open(drop_file, encoding="utf-8") as f:
                                        file_data = (
                                            yaml.safe_load(f)
                                            if drop_file.suffix in (".yaml", ".yml")
                                            else json.load(f)
                                        )
                                        if isinstance(file_data, dict):
                                            _deep_merge(raw_merged, file_data)
                                except Exception as e:
                                    logger.debug(
                                        "Failed to load drop-in config %s: %s", drop_file, e
                                    )

        # 3. Environment variable overrides
        if "RUN_LOG_DIR" in os.environ:
            raw_merged["run_log_dir"] = os.environ["RUN_LOG_DIR"]
        if "AUDIT_LEVEL" in os.environ:
            try:
                raw_merged["audit_level"] = int(os.environ["AUDIT_LEVEL"])
            except ValueError:
                pass
        if "EXECUTION_BACKEND" in os.environ:
            raw_merged["execution_backend"] = os.environ["EXECUTION_BACKEND"]
        if "CHECKPOINT_STORE" in os.environ:
            raw_merged["checkpoint_store"] = os.environ["CHECKPOINT_STORE"]
        if "ARTIFACT_STORE" in os.environ:
            raw_merged["artifact_store"] = os.environ["ARTIFACT_STORE"]
        if "EVAL_SIGNING_KEY" in os.environ:
            raw_merged["signing_key_path"] = os.environ["EVAL_SIGNING_KEY"]
        if "RUN_TIMEOUT_SECONDS" in os.environ:
            try:
                raw_merged["timeout_seconds"] = int(os.environ["RUN_TIMEOUT_SECONDS"])
            except ValueError:
                pass

        # 4. Explicit parameter overrides
        if overrides:
            for k, v in overrides.items():
                if k in raw_merged:
                    if isinstance(raw_merged[k], dict) and isinstance(v, dict):
                        _deep_merge(raw_merged[k], v)
                    else:
                        raw_merged[k] = v
                else:
                    raw_merged["custom_settings"][k] = v

        # 5. Non-overridable Mandates Layer (Strict Enforcement)
        effective_mandates = dict(mandates or {})
        for mk, mv in effective_mandates.items():
            if mk in raw_merged:
                raw_merged[mk] = mv
            else:
                raw_merged["custom_settings"][mk] = mv

        # 6. Lossless Namespace Sorting: Extract known namespaces and collect arbitrary extra keys
        adapters_cfg = dict(raw_merged.get("adapters", {}))
        plugins_cfg = dict(raw_merged.get("plugins", {}))
        policies_cfg = dict(raw_merged.get("policies", {}))
        custom_cfg = dict(raw_merged.get("custom_settings", {}))
        if "custom" in raw_merged and isinstance(raw_merged["custom"], dict):
            _deep_merge(custom_cfg, raw_merged["custom"])

        for k, v in raw_merged.items():
            if k not in CORE_FIELDS and k not in KNOWN_NAMESPACES:
                custom_cfg[k] = v

        return ResolvedRuntimeConfig(
            run_log_dir=raw_merged["run_log_dir"],
            audit_level=raw_merged["audit_level"],
            execution_backend=raw_merged["execution_backend"],
            checkpoint_store=raw_merged["checkpoint_store"],
            artifact_store=raw_merged["artifact_store"],
            signing_key_path=raw_merged["signing_key_path"],
            fail_closed_signing=raw_merged["fail_closed_signing"],
            timeout_seconds=raw_merged["timeout_seconds"],
            enable_hitl=raw_merged["enable_hitl"],
            adapters=adapters_cfg,
            plugins=plugins_cfg,
            policies=policies_cfg,
            custom_settings=custom_cfg,
            mandates=effective_mandates,
        )


__all__ = [
    "ResolvedRuntimeConfig",
    "ConfigResolver",
]
