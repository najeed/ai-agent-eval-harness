"""
Evaluation Runner Core Package.
"""

# Establish version first for package identity (SSOT)
from .config import VERSION as __version__  # noqa: F401

import os
import sys
import warnings

# --- INDUSTRIAL NEUTRALITY: VERSION-GATE SUPPRESSION ---
# Neutralize speculative compatibility warnings from external dependencies (LangChain/Pydantic)
# that mangle the console output on Python 3.14+ without impacting system stability.
# This ensures a clean, audit-grade experience for Enterprise Trust Workflows.
warnings.filterwarnings("ignore", message=".*compatible with Python 3.14 or greater.*")

# NOTE: circular import protection. Engineers should import Engine specifically 
# from eval_runner.engine to avoid initialization races.
