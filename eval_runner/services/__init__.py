"""
eval_runner.services

Package containing core runtime domain services decoupled from console routes
and CLI presentation layers.
"""

from .certification import (
    CertificationService,
    execute_industrial_certification,
    issue_certification,
)
from .config_revision import (
    ConfigurationRevisionService,
    RuntimeDeploymentProviderAdapter,
    ScopeAccessDeniedError,
    StaleRevisionError,
    bind_revision_to_evidence,
    derive_verified_scope,
)
from .run_summary import RunSummaryService

__all__ = [
    "CertificationService",
    "RunSummaryService",
    "execute_industrial_certification",
    "issue_certification",
    "ConfigurationRevisionService",
    "RuntimeDeploymentProviderAdapter",
    "ScopeAccessDeniedError",
    "StaleRevisionError",
    "derive_verified_scope",
    "bind_revision_to_evidence",
]
