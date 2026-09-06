"""
tests/ui/conftest.py

Shared fixtures for Playwright UI tests.

The ``worker_id`` fixture is declared as a local fallback so the conftest
works in plain ``pytest`` runs (no ``-n`` flag) where pytest-xdist does
not inject ``worker_id`` automatically.
"""

import pytest

# ---------------------------------------------------------------------------
# worker_id fallback (only registered when pytest-xdist is absent)
# ---------------------------------------------------------------------------

try:
    import xdist  # noqa: F401 — xdist is present; it provides worker_id itself
except ImportError:

    @pytest.fixture(scope="session")
    def worker_id() -> str:  # type: ignore[misc]
        """Fallback for non-xdist runs."""
        return "master"
