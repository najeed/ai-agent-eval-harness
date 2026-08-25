"""Reusable Agent Target registry ([G3]).

A persisted, server-authoritative entity store for agent connection
profiles: connect once, test reachability, then reuse the same target
across any number of scenarios.

Fail-closed doctrine applies here too:
- Secrets are never accepted or persisted (rejected outright).
- Reachability is only ever reported from an actual probe result;
  an untested target is CONFIGURED at best, never REACHABLE.
"""

import json
import logging
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

from eval_runner import config

from ..auth_manager import Permission, require_permission

logger = logging.getLogger(__name__)

AGENT_TARGETS_SCHEMA_VERSION = "1.0.0"

agent_targets_bp = Blueprint("agent_targets", __name__, url_prefix="/api")

_ALLOWED_PROTOCOLS = {
    "http_rest",
    "http",
    "sse",
    "ollama",
    "openai",
    "anthropic",
    "claude",
    "gemini",
    "custom_http",
    "grpc",
    "in_process",
    "local",
}

_PROVIDER_ENV_VARS = {
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GOOGLE_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "claude": ("ANTHROPIC_API_KEY",),
}

_HTTP_PROBED = {"http_rest", "http", "sse", "ollama", "custom_http", "grpc"}

_SECRET_FIELD_PATTERN = re.compile(
    r"(api[_-]?key|authorization|token|secret|password|credential)", re.IGNORECASE
)

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class AgentTargetValidationError(ValueError):
    """Raised when a target payload fails contract validation."""


def _reject_secrets(payload: dict[str, Any]) -> None:
    for key in payload:
        if _SECRET_FIELD_PATTERN.search(str(key)):
            raise AgentTargetValidationError(
                f"Field '{key}' looks like a secret; credentials are never stored in "
                "Agent Targets. Reference environment-based auth instead."
            )


def _validate_target_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AgentTargetValidationError("Request body must be a JSON object.")
    _reject_secrets(payload)

    name = str(payload.get("name") or "").strip()
    if not name:
        raise AgentTargetValidationError("'name' is required.")

    protocol = str(payload.get("protocol") or "").strip().lower()
    if protocol not in _ALLOWED_PROTOCOLS:
        raise AgentTargetValidationError(
            f"'protocol' must be one of: {', '.join(sorted(_ALLOWED_PROTOCOLS))}."
        )

    endpoint = str(payload.get("endpoint") or "").strip()
    if not endpoint:
        raise AgentTargetValidationError(
            "'endpoint' is required (no implicit default target is ever assumed)."
        )

    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme not in ("http", "https"):
        raise AgentTargetValidationError("Only http:// and https:// endpoints are supported.")
    if not parsed.hostname:
        raise AgentTargetValidationError("Endpoint URL has no resolvable hostname.")

    max_turns = payload.get("max_turns", 10)
    try:
        max_turns = int(max_turns)
    except (TypeError, ValueError):
        raise AgentTargetValidationError("'max_turns' must be an integer.") from None
    if not 1 <= max_turns <= 100:
        raise AgentTargetValidationError("'max_turns' must be between 1 and 100.")

    timeout_seconds = payload.get("timeout_seconds", 60)
    try:
        timeout_seconds = int(timeout_seconds)
    except (TypeError, ValueError):
        raise AgentTargetValidationError("'timeout_seconds' must be an integer.") from None
    if not 5 <= timeout_seconds <= 600:
        raise AgentTargetValidationError("'timeout_seconds' must be between 5 and 600.")

    model = str(payload.get("model") or "").strip()

    return {
        "name": name,
        "protocol": protocol,
        "endpoint": endpoint,
        "model": model,
        "max_turns": max_turns,
        "timeout_seconds": timeout_seconds,
    }


def _probe_endpoint(protocol: str, endpoint: str, timeout: float = 5.0) -> dict[str, Any]:
    """Truthful connectivity probe: REACHABLE only on a real successful check."""
    started = time.perf_counter()
    parsed = urllib.parse.urlparse(endpoint)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    env_keys = _PROVIDER_ENV_VARS.get(protocol, ())
    missing_keys = [k for k in env_keys if not os.environ.get(k)]

    # Credential presence is checked before any network dependency so that
    # provider targets report deterministically in offline environments.
    if env_keys and missing_keys:
        return {
            "reachable": False,
            "tier": "CONFIGURED",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "message": (
                f"Endpoint saved but required credential(s) not set: {', '.join(missing_keys)}."
            ),
        }

    if protocol in ("local", "in_process"):
        return {
            "reachable": False,
            "tier": "CONFIGURED",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "message": "Local/in-process targets execute inside the harness; no remote probe.",
        }

    if parsed.scheme not in ("http", "https"):
        # Defense in depth: routes validate this too, but the probe itself
        # must never be reachable with arbitrary schemes.
        return {
            "reachable": False,
            "tier": "UNREACHABLE",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "message": f"Scheme '{parsed.scheme}' is not probeable; use http/https.",
        }

    try:
        socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError as e:
        return {
            "reachable": False,
            "tier": "UNREACHABLE",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "message": f"DNS resolution failed for '{host}': {e}",
        }

    req = urllib.request.Request(
        endpoint,
        method="GET",
        headers={"User-Agent": "agentv-reachability/1.0", "Connection": "close"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 - scheme restricted to http/https above
            resp.read(4096)
            latency_ms = int((time.perf_counter() - started) * 1000)
            if 200 <= resp.status < 500:
                return {
                    "reachable": True,
                    "tier": "REACHABLE",
                    "latency_ms": latency_ms,
                    "message": f"HTTP {resp.status} from {host}:{port}.",
                }
            return {
                "reachable": False,
                "tier": "UNREACHABLE",
                "latency_ms": latency_ms,
                "message": f"Unexpected HTTP status {resp.status} from {host}:{port}.",
            }
    except urllib.error.HTTPError as e:
        # A well-formed HTTP error still proves the socket path is alive.
        return {
            "reachable": True,
            "tier": "REACHABLE",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "message": f"Endpoint responded HTTP {e.code} (server-side status, transport OK).",
        }
    except Exception as e:
        logger.debug("Agent target probe failed for %s: %s", endpoint, e)
        return {
            "reachable": False,
            "tier": "UNREACHABLE",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "message": f"Connection failed: {e}",
        }


class AgentTargetStore:
    """Thread-safe JSON-file-backed registry of reusable agent targets."""

    def __init__(self, path: Path | None = None):
        # When no explicit path is given the registry location resolves from
        # config at operation time, honoring runtime overrides (tests, env).
        self._explicit_path = Path(path) if path else None
        self._lock = threading.Lock()

    @property
    def _path(self) -> Path:
        return self._explicit_path or Path(config.AGENT_TARGETS_PATH)
        self._lock = threading.Lock()

    def _load_unlocked(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            targets = data.get("targets") if isinstance(data, dict) else None
            return targets if isinstance(targets, dict) else {}
        except Exception as e:
            logger.warning("Agent target registry unreadable at %s: %s", self._path, e)
            return {}

    def _save_unlocked(self, targets: dict[str, dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(
                {"schema_version": AGENT_TARGETS_SCHEMA_VERSION, "targets": targets},
                f,
                indent=2,
                sort_keys=True,
            )
        tmp_path.replace(self._path)

    def list_targets(self) -> list[dict[str, Any]]:
        with self._lock:
            targets = self._load_unlocked()
        return sorted(targets.values(), key=lambda t: t.get("name", ""))

    def get(self, target_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._load_unlocked().get(target_id)

    def upsert(self, fields: dict[str, Any], target_id: str | None = None) -> dict[str, Any]:
        now = datetime.now().isoformat()
        with self._lock:
            targets = self._load_unlocked()
            tid = target_id or ""
            if tid and tid in targets:
                record = dict(targets[tid])
                record.update(fields)
                record["updated_at"] = now
            else:
                if target_id:
                    if not _ID_PATTERN.match(target_id):
                        raise AgentTargetValidationError("Invalid 'id' format.")
                    tid = target_id
                else:
                    slug = re.sub(r"[^a-z0-9]+", "-", fields["name"].lower()).strip("-")[:32]
                    tid = slug or "target"
                    while tid in targets:
                        tid = f"{tid[:48]}-{os.urandom(2).hex()}"
                record = {
                    **fields,
                    "id": tid,
                    "created_at": now,
                    "updated_at": now,
                }
            targets[tid] = record
            self._save_unlocked(targets)
        return record

    def delete(self, target_id: str) -> bool:
        with self._lock:
            targets = self._load_unlocked()
            if target_id not in targets:
                return False
            del targets[target_id]
            self._save_unlocked(targets)
        return True


_store = AgentTargetStore()


@agent_targets_bp.route("/v1/agent-targets", methods=["GET"])
@require_permission(Permission.SCENARIOS_READ)
def list_agent_targets():
    """List all reusable agent targets."""
    return jsonify(
        {"schema_version": AGENT_TARGETS_SCHEMA_VERSION, "targets": _store.list_targets()}
    )


@agent_targets_bp.route("/v1/agent-targets/<target_id>", methods=["GET"])
@require_permission(Permission.SCENARIOS_READ)
def get_agent_target(target_id: str):
    target = _store.get(target_id)
    if not target:
        return jsonify({"error": f"Agent target '{target_id}' not found"}), 404
    return jsonify(target)


@agent_targets_bp.route("/v1/agent-targets", methods=["POST"])
@require_permission(Permission.SCENARIOS_WRITE)
def save_agent_target():
    """Create or update a reusable agent target (connect-once wizard)."""
    data = request.json or {}
    try:
        fields = _validate_target_payload(data)
        target = _store.upsert(fields, target_id=data.get("id"))
    except AgentTargetValidationError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logger.error("Failed to persist agent target: %s", e)
        return jsonify({"error": "Failed to persist agent target."}), 500
    return jsonify(target), 201


@agent_targets_bp.route("/v1/agent-targets/<target_id>", methods=["DELETE"])
@require_permission(Permission.SCENARIOS_WRITE)
def delete_agent_target(target_id: str):
    if not _store.delete(target_id):
        return jsonify({"error": f"Agent target '{target_id}' not found"}), 404
    return jsonify({"status": "deleted", "id": target_id})


@agent_targets_bp.route("/v1/agent-targets/test", methods=["POST"])
@require_permission(Permission.SCENARIOS_READ)
def test_unsaved_agent_target():
    """Reachability probe for an unsaved payload (wizard pre-save check)."""
    data = request.json or {}
    try:
        fields = _validate_target_payload(data)
    except AgentTargetValidationError as e:
        return jsonify({"error": str(e)}), 400
    result = _probe_endpoint(fields["protocol"], fields["endpoint"])
    return jsonify(result)


@agent_targets_bp.route("/v1/agent-targets/<target_id>/test", methods=["POST"])
@require_permission(Permission.SCENARIOS_READ)
def test_agent_target(target_id: str):
    """Server-authoritative reachability test for a saved target."""
    target = _store.get(target_id)
    if not target:
        return jsonify({"error": f"Agent target '{target_id}' not found"}), 404
    result = _probe_endpoint(target["protocol"], target["endpoint"])
    return jsonify({"id": target_id, **result})
