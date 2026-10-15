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
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
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


def is_production() -> bool:
    """Determine if running under production environment markers."""
    environment_markers = ("AGENTV_ENV", "ENVIRONMENT", "ENV")
    return any(
        os.getenv(marker, "").strip().lower() in {"production", "prod"}
        for marker in environment_markers
    )


SECRET_KEYWORDS = {
    "key",
    "token",
    "secret",
    "password",
    "access_key",
    "private_key",
    "bearer",
    "credential",
}


def classify_sensitivity(key: str) -> tuple[str, bool]:
    """Classify setting sensitivity and determine if value is a secret.

    Returns:
        (sensitivity, is_secret) where sensitivity is one of
        'secret', 'sensitive', 'internal', 'public'.
    """
    key_lower = key.lower()
    if any(kw in key_lower for kw in SECRET_KEYWORDS):
        return ("secret", True)
    if any(kw in key_lower for kw in ("signing", "auth", "cert", "hash")):
        return ("sensitive", False)
    if any(kw in key_lower for kw in ("url", "endpoint", "dir", "path", "backend", "store")):
        return ("internal", False)
    return ("public", False)


def redact_sensitive_value(key: str, value: Any) -> Any:
    """Recursively mask secrets and preserve non-secret values."""
    _, is_sec = classify_sensitivity(key)
    if is_sec:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: redact_sensitive_value(f"{key}.{k}" if key else k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_sensitive_value(key, item) for item in value]
    return value


@dataclass
class ConfigSourceContributor:
    """Represents a contributor in the configuration resolution chain."""

    source_type: str
    source_name: str
    value: Any
    applied: bool = False


@dataclass
class ConfigDiagnosticError:
    """Structured error surfacing malformed inputs, invalid overrides, or mandate conflicts."""

    source: str
    error_type: str
    message: str
    raw_value: str | None = None
    canonical_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "error_type": self.error_type,
            "message": self.message,
            "raw_value": self.raw_value,
            "canonical_key": self.canonical_key,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConfigDiagnosticError:
        return cls(
            source=str(data.get("source") or ""),
            error_type=str(data.get("error_type") or ""),
            message=str(data.get("message") or ""),
            raw_value=data.get("raw_value"),
            canonical_key=data.get("canonical_key"),
        )


@dataclass
class ConfigKeyDiagnostic:
    """Detailed diagnostic entry for a single configuration key."""

    canonical_key: str
    effective_value: Any
    contributors: list[ConfigSourceContributor] = field(default_factory=list)
    validation_diagnostics: list[str] = field(default_factory=list)
    sensitivity: str = "internal"
    is_secret: bool = False


@dataclass
class DetailedResolutionResult:
    """Read-only detailed resolution result for a named Runtime configuration resolver/provider."""

    provider_name: str
    precedence_order: list[str]
    snapshot_fingerprint: str
    entries: dict[str, ConfigKeyDiagnostic] = field(default_factory=dict)
    errors: list[ConfigDiagnosticError] = field(default_factory=list)
    effective_snapshot: ResolvedRuntimeConfig | dict[str, Any] | None = None
    is_valid: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "precedence_order": list(self.precedence_order),
            "snapshot_fingerprint": self.snapshot_fingerprint,
            "is_valid": self.is_valid,
            "entries": {
                k: {
                    "canonical_key": v.canonical_key,
                    "effective_value": v.effective_value,
                    "contributors": [asdict(c) for c in v.contributors],
                    "validation_diagnostics": list(v.validation_diagnostics),
                    "sensitivity": v.sensitivity,
                    "is_secret": v.is_secret,
                }
                for k, v in self.entries.items()
            },
            "errors": [asdict(e) for e in self.errors],
            "effective_snapshot": (
                self.effective_snapshot.to_dict()
                if hasattr(self.effective_snapshot, "to_dict")
                else self.effective_snapshot
            ),
        }


class ConfigResolutionError(Exception):
    """
    Raised when configuration resolution fails closed due to
    malformed files, invalid env, or mandate conflicts.
    """

    def __init__(self, message: str, errors: list[ConfigDiagnosticError] | None = None):
        super().__init__(message)
        self.errors = errors or []


class ConfigurationRevisionState(StrEnum):
    """Authoritative lifecycle states for configuration revision consumption and observation."""

    PROVIDER_ACCEPTED = "PROVIDER_ACCEPTED"
    DEPLOYED = "DEPLOYED"
    OBSERVED = "OBSERVED"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    FAILED = "FAILED"


@dataclass
class InstanceObservation:
    """Per-instance Runtime observation of a consumed configuration revision."""

    instance_id: str
    consumed_fingerprint: str
    reload_status: str  # "reloaded", "restarted", "failed", "pending"
    observed_at: str
    failure_reason: str | None = None
    diagnostics: list[ConfigDiagnosticError] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "consumed_fingerprint": self.consumed_fingerprint,
            "reload_status": self.reload_status,
            "observed_at": self.observed_at,
            "failure_reason": self.failure_reason,
            "diagnostics": [
                d.to_dict() if hasattr(d, "to_dict") else asdict(d) for d in self.diagnostics
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InstanceObservation:
        return cls(
            instance_id=str(data.get("instance_id") or ""),
            consumed_fingerprint=str(data.get("consumed_fingerprint") or ""),
            reload_status=str(data.get("reload_status") or "pending"),
            observed_at=str(data.get("observed_at") or ""),
            failure_reason=data.get("failure_reason"),
            diagnostics=[
                ConfigDiagnosticError.from_dict(d) if isinstance(d, dict) else d
                for d in data.get("diagnostics") or []
            ],
        )


@dataclass
class ConfigurationRevisionRecord:
    """
    Authoritative server-side record for a configuration revision lifecycle.
    Binds desired fingerprint to verified server scope and tracks worker observations.
    """

    revision_id: str
    target_scope: dict[str, str]  # org_id, tenant_id, workspace_id, active_environment
    desired_fingerprint: str
    status: str = ConfigurationRevisionState.PROVIDER_ACCEPTED.value
    provider_acknowledged: bool = False
    expected_base_revision_id: str | None = None
    previous_revision_id: str | None = None
    target_instances: list[str] = field(default_factory=list)
    instances: dict[str, InstanceObservation] = field(default_factory=dict)
    diagnostics: list[ConfigDiagnosticError] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    is_rollback: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "target_scope": dict(self.target_scope),
            "desired_fingerprint": self.desired_fingerprint,
            "status": self.status,
            "provider_acknowledged": self.provider_acknowledged,
            "expected_base_revision_id": self.expected_base_revision_id,
            "previous_revision_id": self.previous_revision_id,
            "target_instances": list(self.target_instances),
            "instances": {k: v.to_dict() for k, v in self.instances.items()},
            "diagnostics": [
                d.to_dict() if hasattr(d, "to_dict") else asdict(d) for d in self.diagnostics
            ],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_rollback": self.is_rollback,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConfigurationRevisionRecord:
        raw_instances = data.get("instances") or {}
        instances = {
            k: (InstanceObservation.from_dict(v) if isinstance(v, dict) else v)
            for k, v in raw_instances.items()
        }
        return cls(
            revision_id=str(data.get("revision_id") or ""),
            target_scope=dict(data.get("target_scope") or {}),
            desired_fingerprint=str(data.get("desired_fingerprint") or ""),
            status=str(data.get("status") or ConfigurationRevisionState.PROVIDER_ACCEPTED.value),
            provider_acknowledged=bool(data.get("provider_acknowledged", False)),
            expected_base_revision_id=data.get("expected_base_revision_id"),
            previous_revision_id=data.get("previous_revision_id"),
            target_instances=list(data.get("target_instances") or []),
            instances=instances,
            diagnostics=[
                ConfigDiagnosticError.from_dict(d) if isinstance(d, dict) else d
                for d in data.get("diagnostics") or []
            ],
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            is_rollback=bool(data.get("is_rollback", False)),
            metadata=dict(data.get("metadata") or {}),
        )


class RuntimeWorkerConfigConsumer:
    """
    Concrete Runtime worker configuration consumer.
    Receives a desired configuration revision, reloads worker configuration,
    evaluates mandate compliance and configuration fingerprints, and produces
    an authoritative InstanceObservation for reporting back to the revision lifecycle.
    """

    def __init__(
        self,
        instance_id: str | None = None,
        resolver: ConfigResolver | None = None,
        config_dir: Path | str | None = None,
    ) -> None:
        self.instance_id = (
            instance_id
            or os.getenv("AGENTV_WORKER_INSTANCE_ID")
            or f"worker_{uuid.uuid4().hex[:8]}"
        )
        self.resolver = resolver or ConfigResolver()
        self.config_dir = Path(config_dir) if config_dir else None
        self.consumed_fingerprint: str | None = None
        self.active_revision_id: str | None = None

    def consume_and_reload(
        self,
        revision: ConfigurationRevisionRecord,
        config_dict: dict[str, Any] | None = None,
        mandates: dict[str, Any] | None = None,
        config_dir: Path | str | None = None,
    ) -> InstanceObservation:
        """
        Consumes the desired revision, reloads worker configuration through ConfigResolver,
        and produces an authoritative InstanceObservation.
        """
        now_iso = datetime.now(UTC).isoformat()
        target_dir = Path(config_dir) if config_dir else self.config_dir
        try:
            detailed_result = self.resolver.resolve_detailed(
                overrides=config_dict,
                config_dir=target_dir,
                mandates=mandates,
                fail_closed=False,
            )
            errors = list(detailed_result.errors)
            consumed_fp = detailed_result.snapshot_fingerprint or ""

            # Mandate conflict or resolution error
            if errors:
                error_msgs = [e.message for e in errors]
                return InstanceObservation(
                    instance_id=self.instance_id,
                    consumed_fingerprint=consumed_fp,
                    reload_status="failed",
                    observed_at=now_iso,
                    failure_reason="; ".join(error_msgs),
                    diagnostics=errors,
                )

            # Check fingerprint agreement
            if revision.desired_fingerprint and consumed_fp != revision.desired_fingerprint:
                return InstanceObservation(
                    instance_id=self.instance_id,
                    consumed_fingerprint=consumed_fp,
                    reload_status="failed",
                    observed_at=now_iso,
                    failure_reason=(
                        f"Consumed fingerprint '{consumed_fp}' does not match "
                        f"desired revision fingerprint '{revision.desired_fingerprint}'"
                    ),
                    diagnostics=[],
                )

            self.consumed_fingerprint = consumed_fp
            self.active_revision_id = revision.revision_id
            return InstanceObservation(
                instance_id=self.instance_id,
                consumed_fingerprint=consumed_fp,
                reload_status="reloaded",
                observed_at=now_iso,
                failure_reason=None,
                diagnostics=[],
            )
        except Exception as exc:
            return InstanceObservation(
                instance_id=self.instance_id,
                consumed_fingerprint="",
                reload_status="failed",
                observed_at=now_iso,
                failure_reason=f"Worker reload exception: {exc}",
                diagnostics=[
                    ConfigDiagnosticError(
                        source="worker_reload",
                        error_type="worker_reload_exception",
                        message=str(exc),
                        canonical_key="system.reload",
                    )
                ],
            )


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
    def resolve_detailed(
        cls,
        overrides: dict[str, Any] | None = None,
        config_dir: str | Path | None = None,
        mandates: dict[str, Any] | None = None,
        provider_name: str = "runtime_config_mesh",
        fail_closed: bool | None = None,
    ) -> DetailedResolutionResult:
        """Resolves config mesh with full per-key provenance, diagnostics, and structured errors."""
        entries: dict[str, ConfigKeyDiagnostic] = {}
        errors: list[ConfigDiagnosticError] = []

        def record_entry(canonical_key: str, source_type: str, source_name: str, raw_val: Any):
            sensitivity, is_sec = classify_sensitivity(canonical_key)
            redacted_val = redact_sensitive_value(canonical_key, raw_val)
            if canonical_key not in entries:
                entries[canonical_key] = ConfigKeyDiagnostic(
                    canonical_key=canonical_key,
                    effective_value=redacted_val,
                    sensitivity=sensitivity,
                    is_secret=is_sec,
                    contributors=[],
                )
            diag = entries[canonical_key]
            for c in diag.contributors:
                c.applied = False
            diag.contributors.append(
                ConfigSourceContributor(
                    source_type=source_type,
                    source_name=source_name,
                    value=redacted_val,
                    applied=True,
                )
            )
            diag.effective_value = redacted_val

        def record_dict_entries(prefix: str, d: dict[str, Any], source_type: str, source_name: str):
            for k, v in d.items():
                c_key = f"{prefix}.{k}" if prefix else str(k)
                if isinstance(v, dict):
                    record_dict_entries(c_key, v, source_type, source_name)
                else:
                    record_entry(c_key, source_type, source_name, v)

        file_mandates: list[tuple[dict[str, Any], str]] = []

        def apply_config_dict(d: dict[str, Any], source_type: str, source_name: str):
            for k, v in d.items():
                if k == "mandates" and isinstance(v, dict):
                    file_mandates.append((v, source_name))
                elif k == "core" and isinstance(v, dict):
                    for sub_k, sub_v in v.items():
                        if sub_k in CORE_FIELDS:
                            raw_merged[sub_k] = sub_v
                            record_entry(
                                f"core.{sub_k}",
                                source_type,
                                f"{source_name}:core.{sub_k}",
                                sub_v,
                            )
                        else:
                            raw_merged.setdefault("custom_settings", {})[sub_k] = sub_v
                            record_entry(
                                f"custom_settings.{sub_k}",
                                source_type,
                                f"{source_name}:{sub_k}",
                                sub_v,
                            )
                elif k in CORE_FIELDS:
                    raw_merged[k] = v
                    record_entry(f"core.{k}", source_type, f"{source_name}:{k}", v)
                elif k in KNOWN_NAMESPACES and isinstance(v, dict):
                    _deep_merge(raw_merged.setdefault(k, {}), v)
                    record_dict_entries(k, v, source_type, source_name)
                elif isinstance(v, dict):
                    raw_merged.setdefault("custom_settings", {})[k] = v
                    record_dict_entries(f"custom_settings.{k}", v, source_type, source_name)
                else:
                    raw_merged.setdefault("custom_settings", {})[k] = v
                    record_entry(f"custom_settings.{k}", source_type, f"{source_name}:{k}", v)

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
            "signing_key_path": os.getenv("FLIGHT_RECORDER_KEY_PATH"),
            "fail_closed_signing": os.getenv("EVAL_SIGNING_FAIL_CLOSED", "true").lower() == "true",
            "timeout_seconds": default_timeout,
            "enable_hitl": os.getenv("ENABLE_HITL", "true").lower() == "true",
            "adapters": {},
            "plugins": {},
            "policies": {},
            "custom_settings": {},
        }

        record_entry("core.run_log_dir", "default", "default", "runs")
        record_entry("core.audit_level", "default", "default", 2)
        record_entry("core.execution_backend", "default", "default", "in_process")
        record_entry("core.checkpoint_store", "default", "default", "sqlite")
        record_entry("core.artifact_store", "default", "default", "local_file")
        record_entry("core.signing_key_path", "default", "default", None)
        record_entry("core.fail_closed_signing", "default", "default", True)
        record_entry("core.timeout_seconds", "default", "default", 120)
        record_entry("core.enable_hitl", "default", "default", True)

        # 2. File-based configuration (e.g. .aes/config/, *.d directories)
        search_dirs: list[Path] = []
        eff_config_dir = config_dir or os.getenv("AGENTV_CONFIG_DIR")
        if eff_config_dir:
            search_dirs.append(Path(eff_config_dir))
        search_dirs.append(Path(".aes") / "config")

        for sdir in search_dirs:
            if sdir.exists() and sdir.is_dir():
                for cfg_file in sorted(sdir.glob("*.*")):
                    if cfg_file.suffix in (".json", ".yaml", ".yml"):
                        try:
                            content = cfg_file.read_text(encoding="utf-8")
                            file_data = (
                                yaml.safe_load(content)
                                if cfg_file.suffix in (".yaml", ".yml")
                                else json.loads(content)
                            )
                            if isinstance(file_data, dict):
                                apply_config_dict(file_data, "file", f"file:{cfg_file}")
                            elif file_data is not None:
                                errors.append(
                                    ConfigDiagnosticError(
                                        source=f"file:{cfg_file}",
                                        error_type="malformed_file",
                                        message=f"Root of config file {cfg_file.name} must be "
                                        "a dictionary, got {type(file_data).__name__}",
                                    )
                                )
                        except (OSError, json.JSONDecodeError, yaml.YAMLError, ValueError) as exc:
                            logger.debug("Failed to load config file %s: %s", cfg_file, exc)
                            errors.append(
                                ConfigDiagnosticError(
                                    source=f"file:{cfg_file}",
                                    error_type="malformed_file",
                                    message=f"Failed to parse config file {cfg_file.name}: {exc}",
                                )
                            )

                for d_dir in sorted(sdir.glob("*.d")):
                    if d_dir.is_dir():
                        for drop_file in sorted(d_dir.glob("*.*")):
                            if drop_file.suffix in (".json", ".yaml", ".yml"):
                                try:
                                    content = drop_file.read_text(encoding="utf-8")
                                    file_data = (
                                        yaml.safe_load(content)
                                        if drop_file.suffix in (".yaml", ".yml")
                                        else json.loads(content)
                                    )
                                    if isinstance(file_data, dict):
                                        apply_config_dict(file_data, "file", f"file:{drop_file}")
                                    elif file_data is not None:
                                        errors.append(
                                            ConfigDiagnosticError(
                                                source=f"file:{drop_file}",
                                                error_type="malformed_file",
                                                message=f"Root of drop-in config {drop_file.name} "
                                                "must be a dictionary, "
                                                "got {type(file_data).__name__}",
                                            )
                                        )
                                except (
                                    OSError,
                                    json.JSONDecodeError,
                                    yaml.YAMLError,
                                    ValueError,
                                ) as exc:
                                    logger.debug(
                                        "Failed to load drop-in config %s: %s", drop_file, exc
                                    )
                                    errors.append(
                                        ConfigDiagnosticError(
                                            source=f"file:{drop_file}",
                                            error_type="malformed_file",
                                            message="Failed to parse drop-in config "
                                            f"{drop_file.name}: {exc}",
                                        )
                                    )

        # 3. Environment variable overrides
        if "RUN_LOG_DIR" in os.environ:
            val = os.environ["RUN_LOG_DIR"]
            raw_merged["run_log_dir"] = val
            record_entry("core.run_log_dir", "env", "env:RUN_LOG_DIR", val)

        if "AUDIT_LEVEL" in os.environ:
            val = os.environ["AUDIT_LEVEL"]
            try:
                parsed_audit = int(val)
                if parsed_audit < 1:
                    raise ValueError(f"audit_level must be positive integer, got {parsed_audit}")
                raw_merged["audit_level"] = parsed_audit
                record_entry("core.audit_level", "env", "env:AUDIT_LEVEL", parsed_audit)
            except ValueError as exc:
                errors.append(
                    ConfigDiagnosticError(
                        source="env:AUDIT_LEVEL",
                        error_type="invalid_environment_override",
                        message=f"Invalid AUDIT_LEVEL '{val}': {exc}",
                        raw_value=val,
                        canonical_key="core.audit_level",
                    )
                )

        if "EXECUTION_BACKEND" in os.environ:
            val = os.environ["EXECUTION_BACKEND"]
            raw_merged["execution_backend"] = val
            record_entry("core.execution_backend", "env", "env:EXECUTION_BACKEND", val)

        if "CHECKPOINT_STORE" in os.environ:
            val = os.environ["CHECKPOINT_STORE"]
            raw_merged["checkpoint_store"] = val
            record_entry("core.checkpoint_store", "env", "env:CHECKPOINT_STORE", val)

        if "ARTIFACT_STORE" in os.environ:
            val = os.environ["ARTIFACT_STORE"]
            raw_merged["artifact_store"] = val
            record_entry("core.artifact_store", "env", "env:ARTIFACT_STORE", val)

        if "FLIGHT_RECORDER_KEY_PATH" in os.environ:
            val = os.environ["FLIGHT_RECORDER_KEY_PATH"]
            raw_merged["signing_key_path"] = val
            record_entry("core.signing_key_path", "env", "env:FLIGHT_RECORDER_KEY_PATH", val)

        if "EVAL_SIGNING_FAIL_CLOSED" in os.environ:
            val = os.environ["EVAL_SIGNING_FAIL_CLOSED"].lower() == "true"
            raw_merged["fail_closed_signing"] = val
            record_entry("core.fail_closed_signing", "env", "env:EVAL_SIGNING_FAIL_CLOSED", val)

        if "ENABLE_HITL" in os.environ:
            val = os.environ["ENABLE_HITL"].lower() == "true"
            raw_merged["enable_hitl"] = val
            record_entry("core.enable_hitl", "env", "env:ENABLE_HITL", val)

        if "RUN_TIMEOUT_SECONDS" in os.environ:
            val = os.environ["RUN_TIMEOUT_SECONDS"]
            try:
                parsed_timeout = int(val)
                if parsed_timeout <= 0:
                    raise ValueError(f"timeout_seconds must be > 0, got {parsed_timeout}")
                raw_merged["timeout_seconds"] = parsed_timeout
                record_entry(
                    "core.timeout_seconds", "env", "env:RUN_TIMEOUT_SECONDS", parsed_timeout
                )
            except ValueError as exc:
                errors.append(
                    ConfigDiagnosticError(
                        source="env:RUN_TIMEOUT_SECONDS",
                        error_type="invalid_environment_override",
                        message=f"Invalid RUN_TIMEOUT_SECONDS '{val}': {exc}",
                        raw_value=val,
                        canonical_key="core.timeout_seconds",
                    )
                )

        # 4. Explicit parameter overrides
        if overrides:
            apply_config_dict(overrides, "override", "override")

        # 5. Non-overridable Mandates Layer (Strict Enforcement)
        # Mandates enforce absolute governance and override files, environment, and user settings.
        # File-declared mandates participate in effective mandates with explicit provenance.
        # Explicit runtime mandates enforce highest authority and fail closed on conflicts.
        effective_mandates: dict[str, Any] = {}

        def _apply_mandate_entry(
            m_key: str,
            m_val: Any,
            prefix: str = "",
            source_type: str = "mandate",
            source_label_prefix: str = "mandate",
        ) -> None:
            full_key = f"{prefix}.{m_key}" if prefix else str(m_key)
            if isinstance(m_val, dict):
                for sub_k, sub_v in m_val.items():
                    _apply_mandate_entry(
                        sub_k,
                        sub_v,
                        prefix=full_key,
                        source_type=source_type,
                        source_label_prefix=source_label_prefix,
                    )
                return

            if m_key in CORE_FIELDS and not prefix:
                canonical = f"core.{m_key}"
            elif prefix == "core" and m_key in CORE_FIELDS:
                canonical = f"core.{m_key}"
            elif "." in full_key or prefix:
                canonical = full_key
            else:
                canonical = f"custom_settings.{full_key}"

            src_name = (
                f"{source_label_prefix}:{full_key}"
                if source_label_prefix == "mandate"
                else f"{source_label_prefix}.{full_key}"
            )

            if canonical in entries and entries[canonical].contributors:
                last_c = [c for c in entries[canonical].contributors if c.applied][-1]
                redacted_mv = redact_sensitive_value(canonical, m_val)
                if last_c.source_type != "default" and last_c.value != redacted_mv:
                    errors.append(
                        ConfigDiagnosticError(
                            source=src_name,
                            error_type="mandate_conflict",
                            message=f"Mandate conflict on '{full_key}': "
                            f"source '{last_c.source_name}' contributed {last_c.value!r} "
                            f"but mandate strictly enforces {redacted_mv!r}",
                            canonical_key=canonical,
                            raw_value=str(last_c.value),
                        )
                    )
            record_entry(canonical, source_type, src_name, m_val)
            if (m_key in CORE_FIELDS and not prefix) or (prefix == "core" and m_key in CORE_FIELDS):
                raw_merged[m_key] = m_val
            elif prefix:
                parts = full_key.split(".")
                d = raw_merged
                for p in parts[:-1]:
                    d = d.setdefault(p, {})
                d[parts[-1]] = m_val
            else:
                raw_merged.setdefault("custom_settings", {})[m_key] = m_val

        # Apply file-declared mandates first (if any)
        for f_dict, f_src in file_mandates:
            for f_k, f_v in f_dict.items():
                _apply_mandate_entry(
                    f_k,
                    f_v,
                    source_type="file_mandate",
                    source_label_prefix=f"{f_src}:mandates",
                )
                effective_mandates[f_k] = f_v

        # Apply explicit runtime/session mandates next (highest authority)
        if mandates:
            for mk, mv in mandates.items():
                _apply_mandate_entry(
                    mk,
                    mv,
                    source_type="mandate",
                    source_label_prefix="mandate",
                )
                effective_mandates[mk] = mv

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

        should_fail_closed = is_production() if fail_closed is None else bool(fail_closed)
        fatal_errors = [
            e
            for e in errors
            if e.error_type
            in ("malformed_file", "invalid_environment_override", "mandate_conflict")
        ]
        is_valid = len(fatal_errors) == 0

        snapshot: ResolvedRuntimeConfig | None = None
        fingerprint = ""

        if not (should_fail_closed and not is_valid):
            try:
                snapshot = ResolvedRuntimeConfig(
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
                fingerprint = snapshot.compute_hash()
            except (ValueError, TypeError) as exc:
                is_valid = False
                errors.append(
                    ConfigDiagnosticError(
                        source="validation",
                        error_type="validation_error",
                        message=f"ResolvedRuntimeConfig validation failed: {exc}",
                    )
                )

        if not fingerprint:
            fingerprint = hashlib.sha3_256(b"agentv-invalid-configuration-state").hexdigest()

        if should_fail_closed and not is_valid:
            err_msg = (
                fatal_errors[0].message
                if fatal_errors
                else "Configuration resolution failed closed"
            )
            raise ConfigResolutionError(
                f"Configuration resolution failed closed: {err_msg}",
                errors=errors,
            )

        return DetailedResolutionResult(
            provider_name=provider_name,
            precedence_order=["default", "file", "env", "override", "mandate"],
            snapshot_fingerprint=fingerprint,
            entries=entries,
            errors=errors,
            effective_snapshot=snapshot,
            is_valid=is_valid,
        )

    @classmethod
    def resolve(
        cls,
        overrides: dict[str, Any] | None = None,
        config_dir: str | Path | None = None,
        mandates: dict[str, Any] | None = None,
        fail_closed: bool | None = None,
    ) -> ResolvedRuntimeConfig:
        """Resolves config into a validated ResolvedRuntimeConfig preserving all keys."""
        detailed = cls.resolve_detailed(
            overrides=overrides,
            config_dir=config_dir,
            mandates=mandates,
            fail_closed=fail_closed,
        )
        should_fail_closed = is_production() if fail_closed is None else bool(fail_closed)
        if not detailed.is_valid and should_fail_closed:
            err_msg = (
                detailed.errors[0].message if detailed.errors else "Unknown configuration error"
            )
            raise ConfigResolutionError(
                f"Production configuration resolution failed closed: {err_msg}",
                errors=detailed.errors,
            )
        if isinstance(detailed.effective_snapshot, ResolvedRuntimeConfig):
            return detailed.effective_snapshot
        err_msg = detailed.errors[0].message if detailed.errors else "Invalid configuration"
        raise ConfigResolutionError(
            f"Configuration resolution failed: {err_msg}",
            errors=detailed.errors,
        )


__all__ = [
    "ResolvedRuntimeConfig",
    "ConfigResolver",
    "DetailedResolutionResult",
    "ConfigKeyDiagnostic",
    "ConfigSourceContributor",
    "ConfigDiagnosticError",
    "ConfigResolutionError",
    "ConfigurationRevisionState",
    "InstanceObservation",
    "ConfigurationRevisionRecord",
    "classify_sensitivity",
    "redact_sensitive_value",
    "is_production",
    "CORE_FIELDS",
    "KNOWN_NAMESPACES",
]
