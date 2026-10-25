"""Console dependency accessors.

The console receives its run provider at app composition. Routes must never
resolve a global provider for an individual run request.
"""

from __future__ import annotations

from flask import current_app

from agentv_runtime.interfaces import RunStorageProvider


def get_run_store() -> RunStorageProvider:
    try:
        store = current_app.extensions.get("agentv_run_store")
    except Exception:
        store = None
    if store is None:
        from eval_runner.runtime_services import resolve_run_store

        return resolve_run_store()
    return store
