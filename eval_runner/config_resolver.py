"""
eval_runner.config_resolver
Resolved Runtime Config and ConfigResolver Boundary.
Re-exported from authoritative agentv_runtime.config.
"""

from agentv_runtime.config import (
    CORE_FIELDS,
    KNOWN_NAMESPACES,
    ConfigResolver,
    ResolvedRuntimeConfig,
    _deep_merge,
)

VALID_EXECUTION_BACKENDS = {"in_process", "temporal", "remote", "mock", "custom"}
VALID_CHECKPOINT_STORES = {"sqlite", "postgres", "memory", "custom"}
VALID_ARTIFACT_STORES = {"local_file", "s3", "gcs", "memory", "custom"}

__all__ = [
    "ResolvedRuntimeConfig",
    "ConfigResolver",
    "VALID_EXECUTION_BACKENDS",
    "VALID_CHECKPOINT_STORES",
    "VALID_ARTIFACT_STORES",
    "_deep_merge",
    "CORE_FIELDS",
    "KNOWN_NAMESPACES",
]
