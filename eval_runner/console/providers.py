"""Console dependency accessors.

The console receives its run provider at app composition. Routes must never
resolve a global provider for an individual run request.
"""

from __future__ import annotations

import logging

from flask import current_app

from agentv_runtime.interfaces import RunStorageProvider

logger = logging.getLogger(__name__)


def get_run_store() -> RunStorageProvider:
    try:
        store = current_app.extensions.get("agentv_run_store")
    except RuntimeError:
        logger.debug("get_run_store failed", extra={"operation": "get_run_store"}, exc_info=True)
        store = None
    if store is None:
        from eval_runner.runtime_services import resolve_run_store

        return resolve_run_store()
    return store
