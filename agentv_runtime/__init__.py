"""
agentv_runtime
AgentV OS Runtime Public Architecture & Authoritative Contracts Package (v2.0.0).

Neutral contract layer for AgentV OS Runtime and Control Plane seams.
"""

from __future__ import annotations

from agentv_runtime import config, interfaces, manifest, results
from agentv_runtime.config import ConfigResolver, ResolvedRuntimeConfig
from agentv_runtime.manifest import ExecutionManifest, ManifestBuilder, compute_scenario_hash
from agentv_runtime.results import (
    Attestation,
    EvaluationResult,
    ExecutionResult,
    VerificationCertificate,
    VerificationResult,
)

__version__ = "2.0.0"
__runtime_api_version__ = "2.0"
__plugin_api_version__ = "1.0"
__config_schema_version__ = "1.0"
__aes_schema_version__ = "1.4"
__certificate_schema_version__ = "3.0.0"
__event_schema_version__ = "1.0"

__all__ = [
    "interfaces",
    "results",
    "config",
    "manifest",
    "ConfigResolver",
    "ResolvedRuntimeConfig",
    "ExecutionManifest",
    "ManifestBuilder",
    "compute_scenario_hash",
    "ExecutionResult",
    "EvaluationResult",
    "VerificationResult",
    "Attestation",
    "VerificationCertificate",
    "__version__",
    "__runtime_api_version__",
    "__plugin_api_version__",
    "__config_schema_version__",
    "__aes_schema_version__",
    "__certificate_schema_version__",
    "__event_schema_version__",
]
