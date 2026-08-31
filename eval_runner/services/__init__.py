"""
eval_runner.services

Package containing core runtime domain services decoupled from console routes
and CLI presentation layers.
"""

from .certification import CertificationService, execute_industrial_certification

__all__ = ["CertificationService", "execute_industrial_certification"]
