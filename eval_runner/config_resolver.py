"""
eval_runner.config_resolver
Resolved Runtime Config and ConfigResolver Boundary.
"""

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

import eval_runner.config as config

logger = logging.getLogger(__name__)

VALID_EXECUTION_BACKENDS = {"in_process", "temporal", "remote", "mock", "custom"}
VALID_CHECKPOINT_STORES = {"sqlite", "postgres", "memory", "custom"}
VALID_ARTIFACT_STORES = {"local_file", "s3", "gcs", "memory", "custom"}


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
    Schema-validated runtime configuration model.
    Represents the sealed, fully resolved configuration document for an evaluation execution.
    """

    run_log_dir: str = field(default_factory=lambda: str(config.RUN_LOG_DIR))
    audit_level: int = 2
    execution_backend: str = "in_process"
    checkpoint_store: str = "sqlite"
    artifact_store: str = "local_file"
    signing_key_path: str | None = None
    fail_closed_signing: bool = True
    timeout_seconds: int = 120
    enable_hitl: bool = True
    mandates: dict[str, Any] = field(default_factory=dict)
    custom_settings: dict[str, Any] = field(default_factory=dict)
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
        """Computes deterministic SHA3-256 hash digest of the configuration values."""
        data_dict = {
            "run_log_dir": self.run_log_dir,
            "audit_level": self.audit_level,
            "execution_backend": self.execution_backend,
            "checkpoint_store": self.checkpoint_store,
            "artifact_store": self.artifact_store,
            "signing_key_path": self.signing_key_path,
            "fail_closed_signing": self.fail_closed_signing,
            "timeout_seconds": self.timeout_seconds,
            "enable_hitl": self.enable_hitl,
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
    Config-Mesh Resolver.
    Merges configuration sources in hierarchical precedence:
      1. OSS Baseline Defaults
      2. Config files (.aes/config/*.json, *.yaml, and *.d/ directories)
      3. Environment Variable Overrides
      4. Explicit Runtime Overrides
      5. Immutable Enterprise/System Mandates (Non-overridable)
    """

    @classmethod
    def resolve(
        cls,
        overrides: dict[str, Any] | None = None,
        config_dir: str | Path | None = None,
        mandates: dict[str, Any] | None = None,
    ) -> ResolvedRuntimeConfig:
        """Resolves configuration into a validated ResolvedRuntimeConfig instance."""
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

        cfg: dict[str, Any] = {
            "run_log_dir": str(config.RUN_LOG_DIR),
            "audit_level": default_audit,
            "execution_backend": "in_process",
            "checkpoint_store": "sqlite",
            "artifact_store": "local_file",
            "signing_key_path": os.getenv("EVAL_SIGNING_KEY"),
            "fail_closed_signing": os.getenv("EVAL_SIGNING_FAIL_CLOSED", "true").lower() == "true",
            "timeout_seconds": default_timeout,
            "enable_hitl": os.getenv("ENABLE_HITL", "true").lower() == "true",
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
                                    _deep_merge(cfg, file_data)
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
                                            _deep_merge(cfg, file_data)
                                except Exception as e:
                                    logger.debug(
                                        "Failed to load drop-in config %s: %s", drop_file, e
                                    )

        # 3. Environment overrides
        if "RUN_LOG_DIR" in os.environ:
            cfg["run_log_dir"] = os.environ["RUN_LOG_DIR"]
        if "AUDIT_LEVEL" in os.environ:
            try:
                cfg["audit_level"] = int(os.environ["AUDIT_LEVEL"])
            except ValueError:
                pass
        if "EXECUTION_BACKEND" in os.environ:
            cfg["execution_backend"] = os.environ["EXECUTION_BACKEND"]
        if "CHECKPOINT_STORE" in os.environ:
            cfg["checkpoint_store"] = os.environ["CHECKPOINT_STORE"]
        if "ARTIFACT_STORE" in os.environ:
            cfg["artifact_store"] = os.environ["ARTIFACT_STORE"]
        if "EVAL_SIGNING_KEY" in os.environ:
            cfg["signing_key_path"] = os.environ["EVAL_SIGNING_KEY"]
        if "RUN_TIMEOUT_SECONDS" in os.environ:
            try:
                cfg["timeout_seconds"] = int(os.environ["RUN_TIMEOUT_SECONDS"])
            except ValueError:
                pass

        # 4. Explicit parameter overrides (Deep merged)
        if overrides:
            for k, v in overrides.items():
                if k in cfg:
                    if isinstance(cfg[k], dict) and isinstance(v, dict):
                        _deep_merge(cfg[k], v)
                    else:
                        cfg[k] = v
                else:
                    cfg["custom_settings"][k] = v

        # 5. Non-overridable Mandates Layer (Strict Enforcement)
        effective_mandates = dict(mandates or {})
        for mk, mv in effective_mandates.items():
            if mk in cfg:
                cfg[mk] = mv
            else:
                cfg["custom_settings"][mk] = mv

        return ResolvedRuntimeConfig(
            run_log_dir=cfg["run_log_dir"],
            audit_level=cfg["audit_level"],
            execution_backend=cfg["execution_backend"],
            checkpoint_store=cfg["checkpoint_store"],
            artifact_store=cfg["artifact_store"],
            signing_key_path=cfg["signing_key_path"],
            fail_closed_signing=cfg["fail_closed_signing"],
            timeout_seconds=cfg["timeout_seconds"],
            enable_hitl=cfg["enable_hitl"],
            mandates=effective_mandates,
            custom_settings=cfg["custom_settings"],
        )
