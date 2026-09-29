"""
eval_runner.state_authority
External State Observation Connectors (P0-05) and Bounded State Capture (P0-06).
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import ipaddress
import json
import logging
import os
import socket
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp

from agentv_runtime.canonical import canonical_json_encode
from agentv_runtime.contracts import EvidenceBoundednessLimits
from eval_runner.utils.path_resolver import PathResolver

logger = logging.getLogger(__name__)


class StateAuthorityPolicyError(ValueError):
    """Raised when an external-state request violates the egress contract."""


def _configured_authority_origins() -> set[str]:
    """Return the explicit egress allow-list for scenario-owned authorities.

    An authority is evidence input, not an arbitrary HTTP client.  Keeping the
    policy in one environment variable makes both CI fixtures and deployments
    declare exactly which authority origins they trust.
    """
    entries = os.getenv("AGENTV_EXTERNAL_STATE_AUTHORITY_ALLOWLIST", "").split(",")
    origins: set[str] = set()
    for entry in entries:
        parsed = urlparse(entry.strip())
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            origins.add(f"{parsed.scheme}://{parsed.netloc}".lower())
    return origins


def _validate_external_authority_url(url: str) -> str:
    """Validate a connector URL before opening a network connection.

    The URL must target an explicitly configured origin.  Private, loopback,
    link-local, metadata, and otherwise non-global addresses are prohibited
    unless that exact origin is explicitly allow-listed (the latter supports a
    deliberately declared local CI oracle without making localhost generally
    reachable from scenario input).
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise StateAuthorityPolicyError("External state authority requires an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise StateAuthorityPolicyError("External state authority URL must not contain credentials")

    origin = f"{parsed.scheme}://{parsed.netloc}".lower()
    allowed_origins = _configured_authority_origins()
    if origin not in allowed_origins:
        raise StateAuthorityPolicyError(
            f"External state authority origin is not allow-listed: {origin}"
        )

    try:
        addresses = {
            record[4][0]
            for record in socket.getaddrinfo(
                parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
            )
        }
    except OSError as exc:
        raise StateAuthorityPolicyError(
            f"External state authority host could not be resolved: {parsed.hostname}"
        ) from exc

    if not addresses:
        raise StateAuthorityPolicyError("External state authority host resolved to no addresses")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global and origin not in allowed_origins:
            # Kept as a defense-in-depth guard if the allow-list implementation
            # is changed: private destinations must *never* be implicit.
            raise StateAuthorityPolicyError(
                f"External state authority resolves to a non-global address: {address}"
            )
    return url


def _safe_default(obj: Any) -> str:
    if inspect.iscoroutine(obj):
        try:
            obj.close()
        except (RuntimeError, TypeError, AttributeError) as exc:
            logger.debug("Failed closing unawaited coroutine: %s", exc)
    return str(obj)


class StateLimitExceededError(ValueError):
    """Raised when state snapshot violates strict boundedness limits."""


def bound_state_snapshot(
    state: Any,
    projection: list[str] | None = None,
    max_bytes: int = EvidenceBoundednessLimits.MAX_SNAPSHOT_BYTES,
    max_items: int = EvidenceBoundednessLimits.MAX_INLINE_ITEMS,
) -> tuple[Any, str]:
    """
    Bounded State Capture Contract (P0-06).

    1. If projection selectors are provided (e.g. ['authorizations.*', 'status']),
       extracts only the projected paths from the state.
    2. Computes the authoritative SHA3-256 content hash of the full/projected data.
    3. If serialized bytes exceed max_bytes or list collections exceed max_items,
       returns a bounded truncated structure carrying the exact digest commitment.

    Returns:
        (bounded_state, sha3_256_digest)
    """
    if state is None:
        return None, "sha3_256:" + hashlib.sha3_256(b"null").hexdigest()

    # Step 1: Apply projection if specified
    projected_state = state
    if projection and isinstance(state, dict):
        projected_state = {}
        for path in projection:
            val = PathResolver.resolve(state, path)
            if val is not None:
                parts = path.split(".")
                curr = projected_state
                for part in parts[:-1]:
                    if part not in curr or not isinstance(curr[part], dict):
                        curr[part] = {}
                    curr = curr[part]
                curr[parts[-1]] = copy.deepcopy(val)

    # Step 2: Compute full canonical SHA3-256 digest
    try:
        c_bytes = canonical_json_encode(projected_state)
    except Exception:
        c_bytes = json.dumps(projected_state, sort_keys=True, default=_safe_default).encode("utf-8")
    full_digest = f"sha3_256:{hashlib.sha3_256(c_bytes).hexdigest()}"

    # Step 3: Check byte size boundary
    if len(c_bytes) <= max_bytes:
        # Check nested item counts
        def _bound_collections(val: Any) -> Any:
            if isinstance(val, list):
                if len(val) > max_items:
                    bounded_items = [_bound_collections(x) for x in val[:max_items]]
                    return {
                        "__BOUNDED_COLLECTION__": {
                            "total_items": len(val),
                            "retained_items": max_items,
                            "items": bounded_items,
                            "truncated": True,
                        }
                    }
                return [_bound_collections(x) for x in val]
            if isinstance(val, dict):
                return {k: _bound_collections(v) for k, v in val.items()}
            return val

        return _bound_collections(projected_state), full_digest

    # Step 4: Oversized state - produce bounded commitment structure
    sample: Any
    if isinstance(projected_state, dict):
        sample = {k: projected_state[k] for k in list(projected_state.keys())[:5]}
    elif isinstance(projected_state, list):
        sample = projected_state[:5]
    else:
        sample = str(projected_state)[:256]

    bounded_repr = {
        "__BOUNDED_STATE__": {
            "status": "BOUNDED_STATE_LIMIT_EXCEEDED",
            "original_byte_size": len(c_bytes),
            "max_allowed_bytes": max_bytes,
            "full_state_sha3_256": full_digest,
            "sample": sample,
            "truncated": True,
        }
    }
    return bounded_repr, full_digest


class StateAuthorityConnector(ABC):
    """Abstract interface for observing external system state authorities."""

    @abstractmethod
    async def fetch_state(
        self,
        endpoint_or_query: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Fetch raw state snapshot from external state authority."""


class HttpStateAuthorityConnector(StateAuthorityConnector):
    """
    HTTP / REST External State Authority Connector (P0-05).
    Observes external services via standard HTTP GET with timeout.
    """

    def __init__(self, base_url: str, default_headers: dict[str, str] | None = None):
        self.base_url = _validate_external_authority_url(base_url.rstrip("/"))
        self.default_headers = default_headers or {}

    async def fetch_state(
        self,
        endpoint_or_query: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        url = self.base_url
        if endpoint_or_query:
            endpoint = urlparse(endpoint_or_query)
            if endpoint.scheme or endpoint.netloc:
                raise StateAuthorityPolicyError(
                    "State authority endpoint must be relative to its declared origin"
                )
            url = urljoin(f"{self.base_url}/", endpoint_or_query.lstrip("/"))

        _validate_external_authority_url(url)

        req_headers = {**self.default_headers, **(headers or {})}
        client_timeout = aiohttp.ClientTimeout(total=timeout)

        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            try:
                async with session.get(url, headers=req_headers, allow_redirects=False) as resp:
                    status_code = resp.status
                    if status_code >= 400:
                        err_text = await resp.text()
                        logger.warning(
                            f"[StateAuthority] External authority {url} "
                            f"returned HTTP {status_code}: {err_text[:200]}"
                        )
                        raise ValueError(
                            f"External state authority {url} "
                            f"returned HTTP {status_code}: {err_text[:200]}"
                        )

                    content_length = resp.content_length
                    max_response_bytes = EvidenceBoundednessLimits.MAX_SNAPSHOT_BYTES
                    if content_length is not None and content_length > max_response_bytes:
                        raise StateLimitExceededError(
                            "External state response exceeds bounded snapshot limit"
                        )
                    raw_payload = await resp.content.read(max_response_bytes + 1)
                    if len(raw_payload) > max_response_bytes:
                        raise StateLimitExceededError(
                            "External state response exceeds bounded snapshot limit"
                        )
                    try:
                        payload = json.loads(raw_payload)
                    except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise ValueError("External state authority returned invalid JSON") from exc
                    if not isinstance(payload, dict):
                        payload = {"data": payload}

                    return payload
            except (aiohttp.ClientError, TimeoutError, OSError) as exc:
                logger.error(f"[StateAuthority] Network error querying {url}: {exc}")
                raise ConnectionError(
                    f"Failed to query external state authority {url}: {exc}"
                ) from exc


class ExternalStateAuthorityRegistry:
    """Registry of state authorities declared across scenarios and nodes."""

    def __init__(self):
        self._connectors: dict[str, StateAuthorityConnector] = {}

    def register_authority(self, name: str, connector: StateAuthorityConnector):
        self._connectors[name] = connector

    def get_connector(
        self,
        target_name_or_url: str,
        scenario_authorities: dict[str, Any] | None = None,
    ) -> StateAuthorityConnector:
        # 1. Direct registry hit
        if target_name_or_url in self._connectors:
            return self._connectors[target_name_or_url]

        # 2. Check scenario-declared authorities
        if scenario_authorities and target_name_or_url in scenario_authorities:
            auth_conf = scenario_authorities[target_name_or_url]
            if isinstance(auth_conf, dict):
                url = auth_conf.get("url") or auth_conf.get("endpoint")
                headers = auth_conf.get("headers")
                if url:
                    connector = HttpStateAuthorityConnector(base_url=url, default_headers=headers)
                    self._connectors[target_name_or_url] = connector
                    return connector

        # 3. Dynamic HTTP URL target
        if target_name_or_url.startswith("http://") or target_name_or_url.startswith("https://"):
            connector = HttpStateAuthorityConnector(base_url=target_name_or_url)
            self._connectors[target_name_or_url] = connector
            return connector

        raise KeyError(
            f"No external state authority registered for '{target_name_or_url}' "
            "and target is not a valid URL."
        )

    def clear(self):
        self._connectors.clear()


# Authoritative Global Registry Instance
state_authority_registry = ExternalStateAuthorityRegistry()
