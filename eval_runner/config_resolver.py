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

import eval_runner.config as config

logger = logging.getLogger(__name__)


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
    custom_settings: dict[str, Any] = field(default_factory=dict)
    config_hash: str = ""

    def __post_init__(self):
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
        canonical_json = json.dumps(data_dict, sort_keys=True)
        return hashlib.sha3_256(canonical_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ConfigResolver:
    """
    Config-Mesh Resolver.
    Merges configuration sources in hierarchical precedence:
      1. OSS Baseline Defaults
      2. Config files (.aes/config/*.d, JSON, YAML)
      3. Environment Variable Overrides
      4. Explicit Runtime Overrides
    """

    @classmethod
    def resolve(
        cls,
        overrides: dict[str, Any] | None = None,
        config_dir: str | Path | None = None,
    ) -> ResolvedRuntimeConfig:
        """Resolves configuration into a validated ResolvedRuntimeConfig instance."""
        # 1. Base Defaults
        cfg: dict[str, Any] = {
            "run_log_dir": str(config.RUN_LOG_DIR),
            "audit_level": int(os.getenv("AUDIT_LEVEL", "2")),
            "execution_backend": "in_process",
            "checkpoint_store": "sqlite",
            "artifact_store": "local_file",
            "signing_key_path": os.getenv("EVAL_SIGNING_KEY"),
            "fail_closed_signing": os.getenv("EVAL_SIGNING_FAIL_CLOSED", "true").lower() == "true",
            "timeout_seconds": int(os.getenv("RUN_TIMEOUT_SECONDS", "120")),
            "enable_hitl": os.getenv("ENABLE_HITL", "true").lower() == "true",
            "custom_settings": {},
        }

        # 2. File-based configuration (e.g. .aes/config/)
        search_dirs: list[Path] = []
        if config_dir:
            search_dirs.append(Path(config_dir))
        search_dirs.append(Path(".aes") / "config")

        for sdir in search_dirs:
            if sdir.exists() and sdir.is_dir():
                for cfg_file in sorted(sdir.glob("*.json")):
                    try:
                        with open(cfg_file, encoding="utf-8") as f:
                            file_data = json.load(f)
                            if isinstance(file_data, dict):
                                cfg.update(file_data)
                    except Exception as e:
                        logger.debug(f"Failed to load config file {cfg_file}: {e}")

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

        # 4. Explicit parameter overrides
        if overrides:
            for k, v in overrides.items():
                if k in cfg:
                    cfg[k] = v
                else:
                    cfg["custom_settings"][k] = v

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
            custom_settings=cfg["custom_settings"],
        )
