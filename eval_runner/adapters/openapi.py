from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import json
import logging
import os
import re
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import (
    parse_qsl,
    quote,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
)

import aiohttp

from .. import config
from ..plugins import BaseEvalPlugin
from .common import BaseAdapter, DualNormalizationHub

logger = logging.getLogger(__name__)

_HTTP_METHODS = {
    "get",
    "put",
    "post",
    "delete",
    "options",
    "head",
    "patch",
    "trace",
}

_SAFE_RETRY_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}

_PROCESSING_VALUES = {
    "accepted",
    "queued",
    "pending",
    "processing",
    "running",
    "in_progress",
    "in-progress",
    "submitted",
    "started",
    "scheduled",
    "waiting",
    "wait",
}

_CONTROL_KEYS = {
    "url",
    "endpoint",
    "spec_url",
    "openapi_spec",
    "openapi_spec_url",
    "operation_id",
    "operationId",
    "operation_ref",
    "operationRef",
    "path",
    "method",
    "content_type",
    "parameters",
    "path_params",
    "query_params",
    "header_params",
    "cookie_params",
    "server_variables",
    "server_index",
    "server_url",
    "headers",
    "cookies",
    "auth",
    "metadata",
    "input_payload",
    "body",
    "request_body",
    "poll_interval",
    "max_poll_attempts",
    "max_poll_duration",
    "overrides",
    "retry_safe",
    "retry_unsafe_methods",
}

_MAX_RESPONSE_BYTES = int(os.getenv("OPENAPI_MAX_RESPONSE_BYTES", str(10 * 1024 * 1024)))
_MAX_SPEC_BYTES = int(os.getenv("OPENAPI_MAX_SPEC_BYTES", str(5 * 1024 * 1024)))
_MAX_ERROR_BODY = int(os.getenv("OPENAPI_MAX_ERROR_BODY", "4000"))
_MAX_CONTENT_PREVIEW = int(os.getenv("OPENAPI_MAX_CONTENT_PREVIEW", "5000"))
_DEFAULT_MAX_POLL_ATTEMPTS = int(os.getenv("OPENAPI_MAX_POLL_ATTEMPTS", "150"))
_DEFAULT_POLL_INTERVAL = float(os.getenv("OPENAPI_POLL_INTERVAL", "2.0"))
_DEFAULT_MAX_POLL_DURATION = float(os.getenv("OPENAPI_MAX_POLL_DURATION", str(10 * 60)))


class OpenAPIResolutionError(ValueError):
    """Raised when an OpenAPI description cannot be resolved to an executable operation."""


class OpenAPIAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Specification-driven OpenAPI 3.0/3.1 adapter.

    The implementation intentionally keeps protocol mechanics here while
    delegating shared retry/session infrastructure to eval_runner.adapters.common.

    Supported:
      - OpenAPI 3.0 and 3.1
      - JSON/YAML specifications
      - local and external $ref resolution
      - operationId and operationRef resolution
      - server variables and explicit server selection
      - path/query/header/cookie parameter serialization
      - OpenAPI parameter styles: simple, form, spaceDelimited,
        pipeDelimited, deepObject, label, matrix
      - JSON, form-urlencoded, multipart, text and binary request bodies
      - apiKey, HTTP basic/bearer and OAuth2 security
      - explicit access tokens and OAuth2 client credentials/password flows
      - OpenID Connect discovery for token endpoint discovery
      - bounded response reads
      - lifecycle-scoped sessions through BaseAdapter/common.py
      - retry-safe request semantics
      - structured response normalization
      - HTTP 202 / Location / HATEOAS / OpenAPI response-link polling
      - Retry-After handling
      - legacy adapter() compatibility
    """

    def __init__(self, session_pool: Any | None = None):
        BaseAdapter.__init__(
            self,
            name="openapi",
            session_pool=session_pool,
        )

        self.max_poll_attempts = max(
            1,
            _DEFAULT_MAX_POLL_ATTEMPTS,
        )
        self.poll_interval = max(
            0.0,
            _DEFAULT_POLL_INTERVAL,
        )
        self.max_poll_duration = max(
            1.0,
            _DEFAULT_MAX_POLL_DURATION,
        )

        self._document_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._oauth_cache: dict[
            tuple[str, str, str, str, str],
            tuple[float, str],
        ] = {}

        self._cache_ttl = max(
            0.0,
            float(os.getenv("OPENAPI_SPEC_CACHE_TTL", "300")),
        )

    def on_discover_adapters(self, registry: Any) -> None:
        registry.register(
            "openapi",
            self.execute_openapi_query,
        )

    # -------------------------------------------------------------------------
    # Generic helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _normalized_content_type(value: str | None) -> str:
        return str(value or "").lower().split(";", 1)[0].strip()

    @classmethod
    def _is_json_media_type(cls, value: str | None) -> bool:
        normalized = cls._normalized_content_type(value)
        return (
            normalized == "application/json"
            or normalized.endswith("+json")
            or normalized == "application/*+json"
        )

    @staticmethod
    def _serialize_scalar(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"

        if value is None:
            return ""

        if isinstance(value, (dict, list, tuple)):
            return json.dumps(
                value,
                separators=(",", ":"),
                ensure_ascii=False,
            )

        return str(value)

    @staticmethod
    def _json_pointer_get(document: Any, pointer: str) -> Any:
        if pointer in {"", "#", "/"}:
            return document

        normalized = pointer
        if normalized.startswith("#"):
            normalized = normalized[1:]

        if normalized.startswith("/"):
            normalized = normalized[1:]

        if not normalized:
            return document

        current = document

        for token in normalized.split("/"):
            token = token.replace("~1", "/").replace("~0", "~")

            if isinstance(current, dict):
                if token not in current:
                    raise KeyError(token)
                current = current[token]
            elif isinstance(current, list):
                try:
                    index = int(token)
                except ValueError as exc:
                    raise KeyError(token) from exc

                if index < 0 or index >= len(current):
                    raise IndexError(index)

                current = current[index]
            else:
                raise KeyError(token)

        return current

    @staticmethod
    def _coerce_int(value: Any, default: int) -> int:
        try:
            return max(
                0,
                int(value),
            )
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _coerce_float(value: Any, default: float) -> float:
        try:
            return max(
                0.0,
                float(value),
            )
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _header_get(
        headers: dict[str, Any] | aiohttp.typedefs.LooseHeaders,
        name: str,
    ) -> str | None:
        for key, value in headers.items():
            if str(key).lower() == name.lower():
                return str(value)
        return None

    @staticmethod
    def _same_origin(left: str, right: str) -> bool:
        a = urlparse(left)
        b = urlparse(right)

        if not a.scheme or not b.scheme or not a.netloc or not b.netloc:
            return False

        return (
            a.scheme.lower(),
            a.hostname.lower() if a.hostname else "",
            a.port or (443 if a.scheme.lower() == "https" else 80),
        ) == (
            b.scheme.lower(),
            b.hostname.lower() if b.hostname else "",
            b.port or (443 if b.scheme.lower() == "https" else 80),
        )

    @staticmethod
    def _safe_url(
        value: str,
        *,
        allow_relative: bool = False,
    ) -> str:
        parsed = urlparse(value)

        if parsed.scheme.lower() not in {"http", "https", ""}:
            raise OpenAPIResolutionError(f"Unsupported URL scheme {parsed.scheme!r}")

        if not allow_relative and not parsed.netloc:
            raise OpenAPIResolutionError(f"Absolute HTTP(S) URL required: {value!r}")

        if parsed.username or parsed.password:
            raise OpenAPIResolutionError("URLs containing embedded credentials are not permitted")

        return value

    @staticmethod
    def _safe_local_path(source: str) -> Path:
        parsed = urlparse(source)

        if parsed.scheme not in {"", "file"}:
            raise OpenAPIResolutionError(
                f"Unsupported local specification URI scheme: {parsed.scheme}"
            )

        path = Path(parsed.path if parsed.scheme == "file" else source).expanduser().resolve()

        if not path.exists():
            raise FileNotFoundError(path)

        if not path.is_file():
            raise OpenAPIResolutionError(f"OpenAPI specification path is not a file: {path}")

        return path

    # -------------------------------------------------------------------------
    # Specification loading / validation
    # -------------------------------------------------------------------------

    async def _fetch_document(
        self,
        source: str,
        *,
        explicit: bool = False,
    ) -> dict[str, Any]:
        cached = self._document_cache.get(source)

        if cached is not None and time.monotonic() - cached[0] < self._cache_ttl:
            return copy.deepcopy(cached[1])

        parsed = urlparse(source)

        if parsed.scheme in {"http", "https"}:
            self._safe_url(source)

            session = await self.get_session()

            try:
                async with session.get(
                    source,
                    headers={
                        "Accept": (
                            "application/json, application/yaml, text/yaml, text/x-yaml, */*"
                        )
                    },
                    timeout=aiohttp.ClientTimeout(total=config.DEFAULT_ADAPTER_TIMEOUT),
                    allow_redirects=False,
                ) as response:
                    if 300 <= response.status < 400:
                        location = response.headers.get("Location")

                        if not location:
                            raise OpenAPIResolutionError(
                                f"OpenAPI specification fetch returned "
                                f"HTTP {response.status} without Location"
                            )

                        redirect_url = urljoin(
                            source,
                            location,
                        )

                        if not self._same_origin(
                            source,
                            redirect_url,
                        ):
                            raise OpenAPIResolutionError(
                                "Cross-origin redirects are not permitted "
                                "while loading an OpenAPI specification"
                            )

                        return await self._fetch_document(
                            redirect_url,
                            explicit=explicit,
                        )

                    if response.status >= 400:
                        body = await self._read_response_limited(
                            response,
                            limit=_MAX_ERROR_BODY,
                        )

                        if explicit:
                            raise OpenAPIResolutionError(
                                "OpenAPI specification fetch failed: "
                                f"HTTP {response.status}: "
                                f"{body.decode('utf-8', errors='replace')[:_MAX_ERROR_BODY]}"
                            )

                        raise FileNotFoundError(source)

                    raw = await self._read_response_bytes(
                        response,
                        limit=_MAX_SPEC_BYTES,
                    )
                    content_type = response.headers.get(
                        "Content-Type",
                        "",
                    )

            except OpenAPIResolutionError:
                raise
            except FileNotFoundError:
                raise
            except Exception as exc:
                if explicit:
                    raise OpenAPIResolutionError(
                        f"OpenAPI specification fetch failed for {source}: {exc}"
                    ) from exc
                raise

            document = self._parse_document(
                raw,
                source,
                content_type,
            )

        elif parsed.scheme in {"", "file"}:
            path = self._safe_local_path(source)

            raw = path.read_bytes()

            if len(raw) > _MAX_SPEC_BYTES:
                raise OpenAPIResolutionError(
                    f"OpenAPI specification exceeds {_MAX_SPEC_BYTES} bytes: {path}"
                )

            document = self._parse_document(
                raw,
                str(path),
                "",
            )

        else:
            raise OpenAPIResolutionError(
                f"Unsupported OpenAPI specification URI scheme: {parsed.scheme}"
            )

        self._validate_document(
            document,
            source,
        )

        self._document_cache[source] = (
            time.monotonic(),
            copy.deepcopy(document),
        )

        return document

    @staticmethod
    def _parse_document(
        raw: bytes,
        source: str,
        content_type: str,
    ) -> dict[str, Any]:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise OpenAPIResolutionError(
                f"OpenAPI document at {source} is not valid UTF-8"
            ) from exc

        normalized_type = content_type.lower()

        looks_yaml = (
            "yaml" in normalized_type
            or source.lower().endswith((".yaml", ".yml"))
            or text.lstrip().startswith(
                (
                    "openapi:",
                    "swagger:",
                    "---",
                )
            )
        )

        try:
            if looks_yaml:
                import yaml

                document = yaml.safe_load(text)
            else:
                document = json.loads(text)
        except Exception as exc:
            raise OpenAPIResolutionError(f"Invalid OpenAPI document at {source}: {exc}") from exc

        if not isinstance(document, dict):
            raise OpenAPIResolutionError(f"OpenAPI document at {source} must be an object")

        return document

    @staticmethod
    def _validate_document(
        document: dict[str, Any],
        source: str,
    ) -> None:
        version = str(document.get("openapi", ""))

        if not (version.startswith("3.0.") or version.startswith("3.1.")):
            raise OpenAPIResolutionError(
                f"Unsupported OpenAPI version {version!r} in {source}; OpenAPI 3.0/3.1 is required"
            )

        paths = document.get("paths")

        if paths is not None and not isinstance(paths, dict):
            raise OpenAPIResolutionError(f"OpenAPI document {source} has an invalid paths object")

        if paths is None and not isinstance(
            document.get("webhooks"),
            dict,
        ):
            raise OpenAPIResolutionError(
                f"OpenAPI document {source} contains neither paths nor webhooks"
            )

    async def _load_spec(
        self,
        endpoint: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None]:
        inline_spec = payload.get("openapi_spec")

        if isinstance(inline_spec, dict):
            spec = copy.deepcopy(inline_spec)

            self._validate_document(
                spec,
                "payload.openapi_spec",
            )

            return spec, None

        metadata = payload.get("metadata") or {}

        explicit_spec = (
            payload.get("spec_url")
            or payload.get("openapi_spec_url")
            or metadata.get("spec_url")
            or metadata.get("openapi_spec_url")
            or os.getenv("OPENAPI_SPEC_URL")
        )

        if explicit_spec:
            spec_url = self._resolve_reference_url(
                str(explicit_spec),
                endpoint,
            )

            return (
                await self._fetch_document(
                    spec_url,
                    explicit=True,
                ),
                spec_url,
            )

        parsed = urlparse(endpoint)

        if parsed.scheme not in {"http", "https"}:
            return None, None

        endpoint_without_query = urlunparse(
            parsed._replace(
                query="",
                fragment="",
            )
        )

        origin = f"{parsed.scheme}://{parsed.netloc}"

        candidates: list[str] = [
            f"{origin}/openapi.json",
            f"{origin}/openapi.yaml",
            f"{origin}/openapi.yml",
            urljoin(
                endpoint_without_query,
                "openapi.json",
            ),
            urljoin(
                endpoint_without_query,
                "openapi.yaml",
            ),
            urljoin(
                endpoint_without_query,
                "openapi.yml",
            ),
        ]

        seen: set[str] = set()

        for candidate in candidates:
            if candidate in seen:
                continue

            seen.add(candidate)

            try:
                return (
                    await self._fetch_document(
                        candidate,
                        explicit=False,
                    ),
                    candidate,
                )
            except Exception:
                continue

        return None, None

    @staticmethod
    def _resolve_reference_url(
        ref: str,
        base_url: str | None,
    ) -> str:
        if base_url and not urlparse(ref).scheme:
            return urljoin(
                base_url,
                ref,
            )

        return ref

    async def _resolve_ref(
        self,
        value: Any,
        *,
        document: dict[str, Any],
        document_url: str | None,
        _stack: tuple[str, ...] = (),
    ) -> Any:
        if not isinstance(value, dict) or "$ref" not in value:
            return value

        ref = str(value["$ref"])

        if ref in _stack:
            raise OpenAPIResolutionError(
                "Cyclic OpenAPI $ref detected: " + " -> ".join((*_stack, ref))
            )

        next_stack = (*_stack, ref)

        if ref.startswith("#/"):
            try:
                target = self._json_pointer_get(
                    document,
                    ref[1:],
                )
            except Exception as exc:
                raise OpenAPIResolutionError(f"Unresolvable OpenAPI reference: {ref}") from exc

            return copy.deepcopy(target)

        if not document_url:
            raise OpenAPIResolutionError(
                f"External OpenAPI reference requires a document URL: {ref}"
            )

        target_url = urljoin(
            document_url,
            ref,
        )

        parsed = urlparse(target_url)

        if parsed.scheme not in {"http", "https", "file"}:
            raise OpenAPIResolutionError(
                f"Unsupported external OpenAPI reference scheme: {parsed.scheme}"
            )

        fragment = parsed.fragment

        document_source = urlunparse(
            parsed._replace(
                fragment="",
            )
        )

        external = await self._fetch_document(
            document_source,
            explicit=True,
        )

        if not fragment:
            return external

        if not fragment.startswith("/"):
            raise OpenAPIResolutionError(
                f"Unsupported external OpenAPI reference fragment: #{fragment}"
            )

        try:
            target = self._json_pointer_get(
                external,
                fragment,
            )
        except Exception as exc:
            raise OpenAPIResolutionError(f"Unresolvable external OpenAPI reference: {ref}") from exc

        if isinstance(target, dict) and "$ref" in target:
            return await self._resolve_ref(
                target,
                document=external,
                document_url=document_source,
                _stack=next_stack,
            )

        return copy.deepcopy(target)

    # -------------------------------------------------------------------------
    # Operation resolution
    # -------------------------------------------------------------------------

    async def _resolve_server(
        self,
        *,
        spec: dict[str, Any],
        path_item: dict[str, Any],
        operation: dict[str, Any],
        document_url: str | None,
        payload: dict[str, Any],
        endpoint: str,
    ) -> str:
        metadata = payload.get("metadata") or {}

        explicit_server_url = payload.get("server_url") or metadata.get("server_url")

        if explicit_server_url:
            explicit = str(explicit_server_url)

            if not urlparse(explicit).scheme and document_url:
                explicit = urljoin(
                    document_url,
                    explicit,
                )

            return self._safe_url(
                explicit,
            ).rstrip("/")

        raw_servers = (
            operation.get("servers") or path_item.get("servers") or spec.get("servers") or []
        )

        if not raw_servers:
            parsed = urlparse(endpoint)

            if parsed.scheme in {"http", "https"} and parsed.netloc:
                return (f"{parsed.scheme}://{parsed.netloc}").rstrip("/")

            return endpoint.rstrip("/")

        resolved_servers: list[dict[str, Any]] = []

        for raw_server in raw_servers:
            server = await self._resolve_ref(
                raw_server,
                document=spec,
                document_url=document_url,
            )

            if isinstance(server, dict):
                resolved_servers.append(server)

        if not resolved_servers:
            raise OpenAPIResolutionError("OpenAPI operation declares no usable servers")

        requested_index = payload.get(
            "server_index",
            metadata.get("server_index"),
        )

        if requested_index is not None:
            try:
                index = int(requested_index)
            except (TypeError, ValueError) as exc:
                raise OpenAPIResolutionError(
                    f"Invalid OpenAPI server_index: {requested_index!r}"
                ) from exc

            if index < 0 or index >= len(resolved_servers):
                raise OpenAPIResolutionError(f"OpenAPI server_index {index} is out of range")

            server = resolved_servers[index]
        else:
            server = resolved_servers[0]

        server_url = str(server.get("url", ""))

        if not server_url:
            raise OpenAPIResolutionError("OpenAPI server is missing url")

        variables = payload.get("server_variables") or metadata.get("server_variables") or {}

        for name, definition in (server.get("variables") or {}).items():
            if not isinstance(definition, dict):
                raise OpenAPIResolutionError(f"Invalid OpenAPI server variable definition: {name}")

            value = variables.get(
                name,
                definition.get("default"),
            )

            if value is None:
                raise OpenAPIResolutionError(f"Missing value for OpenAPI server variable {name!r}")

            enum = definition.get("enum")

            if enum and value not in enum:
                raise OpenAPIResolutionError(
                    f"Invalid value {value!r} for OpenAPI server variable "
                    f"{name!r}; expected one of {enum}"
                )

            server_url = server_url.replace(
                "{" + name + "}",
                quote(
                    str(value),
                    safe="",
                ),
            )

        if not urlparse(server_url).scheme:
            if document_url:
                server_url = urljoin(
                    document_url,
                    server_url,
                )
            else:
                endpoint_parsed = urlparse(endpoint)

                if endpoint_parsed.scheme in {"http", "https"}:
                    server_url = urljoin(
                        (f"{endpoint_parsed.scheme}://{endpoint_parsed.netloc}"),
                        server_url,
                    )

        return self._safe_url(
            server_url,
        ).rstrip("/")

    async def _find_operation(
        self,
        spec: dict[str, Any],
        document_url: str | None,
        endpoint: str,
        payload: dict[str, Any],
    ) -> (
        tuple[
            dict[str, Any],
            dict[str, Any],
            str,
            str,
        ]
        | None
    ):
        metadata = payload.get("metadata") or {}

        openapi_meta = (
            metadata.get("openapi")
            if isinstance(
                metadata.get("openapi"),
                dict,
            )
            else {}
        )

        operation_id = (
            payload.get("operation_id")
            or payload.get("operationId")
            or metadata.get("operation_id")
            or metadata.get("operationId")
            or openapi_meta.get("operation_id")
            or openapi_meta.get("operationId")
        )

        operation_ref = (
            payload.get("operation_ref")
            or payload.get("operationRef")
            or metadata.get("operation_ref")
            or metadata.get("operationRef")
            or openapi_meta.get("operation_ref")
            or openapi_meta.get("operationRef")
        )

        requested_method = str(
            payload.get("method") or metadata.get("method") or openapi_meta.get("method") or ""
        ).lower()

        requested_path = payload.get("path") or metadata.get("path") or openapi_meta.get("path")

        if operation_ref:
            (
                operation,
                path,
                method,
                path_item,
            ) = await self._resolve_operation_ref(
                spec,
                str(operation_ref),
                document_url=document_url,
            )

            return (
                operation,
                path_item,
                path,
                method,
            )

        operations: list[
            tuple[
                str,
                str,
                dict[str, Any],
                dict[str, Any],
            ]
        ] = []

        for path, raw_item in (spec.get("paths") or {}).items():
            if not isinstance(
                raw_item,
                dict,
            ):
                continue

            path_item = await self._resolve_ref(
                raw_item,
                document=spec,
                document_url=document_url,
            )

            if not isinstance(
                path_item,
                dict,
            ):
                continue

            for method, raw_operation in path_item.items():
                method_lower = str(method).lower()

                if method_lower not in _HTTP_METHODS:
                    continue

                operation = await self._resolve_ref(
                    raw_operation,
                    document=spec,
                    document_url=document_url,
                )

                if isinstance(
                    operation,
                    dict,
                ):
                    operations.append(
                        (
                            str(path),
                            method_lower,
                            operation,
                            path_item,
                        )
                    )

        if operation_id:
            matches = [row for row in operations if row[2].get("operationId") == operation_id]

            if len(matches) != 1:
                raise OpenAPIResolutionError(
                    f"OpenAPI operationId {operation_id!r} resolved to {len(matches)} operations"
                )

            path, method, operation, path_item = matches[0]

            return (
                operation,
                path_item,
                path,
                method,
            )

        endpoint_path = urlparse(endpoint).path or "/"

        path_matches: list[
            tuple[
                str,
                str,
                dict[str, Any],
                dict[str, Any],
            ]
        ]

        if requested_path:
            normalized_requested_path = "/" + str(requested_path).lstrip("/")

            path_matches = [row for row in operations if row[0] == normalized_requested_path]
        else:
            path_matches = [
                row
                for row in operations
                if self._path_matches_template(
                    row[0],
                    endpoint_path,
                )
            ]

            if not path_matches:
                path_matches = await self._match_against_server_relative_path(
                    spec=spec,
                    operations=operations,
                    endpoint_path=endpoint_path,
                    document_url=document_url,
                )

        if requested_method:
            path_matches = [row for row in path_matches if row[1] == requested_method]

        if len(path_matches) == 1:
            path, method, operation, path_item = path_matches[0]

            return (
                operation,
                path_item,
                path,
                method,
            )

        if not requested_path and not requested_method and len(path_matches) > 1:
            exact = [row for row in path_matches if row[0] == endpoint_path]

            if len(exact) == 1:
                path, method, operation, path_item = exact[0]

                return (
                    operation,
                    path_item,
                    path,
                    method,
                )

        if not requested_path and not requested_method and len(operations) == 1:
            path, method, operation, path_item = operations[0]

            return (
                operation,
                path_item,
                path,
                method,
            )

        if requested_path or requested_method:
            raise OpenAPIResolutionError(
                "OpenAPI operation could not be uniquely resolved from the supplied path/method"
            )

        return None

    async def _match_against_server_relative_path(
        self,
        *,
        spec: dict[str, Any],
        operations: list[
            tuple[
                str,
                str,
                dict[str, Any],
                dict[str, Any],
            ]
        ],
        endpoint_path: str,
        document_url: str | None,
    ) -> list[
        tuple[
            str,
            str,
            dict[str, Any],
            dict[str, Any],
        ]
    ]:
        server_prefixes: set[str] = {""}

        for raw_server in spec.get("servers") or []:
            try:
                server = await self._resolve_ref(
                    raw_server,
                    document=spec,
                    document_url=document_url,
                )
            except Exception:
                continue

            if not isinstance(
                server,
                dict,
            ):
                continue

            raw_url = str(server.get("url", ""))

            parsed = urlparse(raw_url)

            if parsed.path:
                server_prefixes.add(parsed.path.rstrip("/"))

        candidates: list[
            tuple[
                str,
                str,
                dict[str, Any],
                dict[str, Any],
            ]
        ] = []

        for prefix in server_prefixes:
            if not prefix:
                continue

            if endpoint_path == prefix:
                relative = "/"
            elif endpoint_path.startswith(prefix + "/"):
                relative = endpoint_path[len(prefix) :]
            else:
                continue

            for row in operations:
                if self._path_matches_template(
                    row[0],
                    relative,
                ):
                    candidates.append(row)

        return candidates

    async def _resolve_operation_ref(
        self,
        spec: dict[str, Any],
        ref: str,
        *,
        document_url: str | None,
    ) -> tuple[
        dict[str, Any],
        str,
        str,
        dict[str, Any],
    ]:
        target_spec = spec
        target_url = document_url

        if ref.startswith("#/"):
            fragment = ref[1:]

        else:
            resolved_url = self._resolve_reference_url(
                ref,
                document_url,
            )

            parsed = urlparse(resolved_url)

            if parsed.scheme not in {
                "http",
                "https",
                "file",
            }:
                raise OpenAPIResolutionError(f"Unsupported operationRef scheme: {parsed.scheme}")

            fragment = parsed.fragment

            source = urlunparse(
                parsed._replace(
                    fragment="",
                )
            )

            target_spec = await self._fetch_document(
                source,
                explicit=True,
            )
            target_url = source

        if not fragment.startswith("/"):
            raise OpenAPIResolutionError(f"operationRef must identify an OpenAPI operation: {ref}")

        tokens = [
            token.replace(
                "~1",
                "/",
            ).replace(
                "~0",
                "~",
            )
            for token in fragment[1:].split("/")
        ]

        if len(tokens) < 3 or tokens[0] != "paths":
            raise OpenAPIResolutionError(
                f"operationRef must identify an operation under paths: {ref}"
            )

        path = "/" + "/".join(tokens[1:-1])

        method = tokens[-1].lower()

        if method not in _HTTP_METHODS:
            raise OpenAPIResolutionError(
                f"operationRef resolved to unsupported HTTP method {method!r}"
            )

        try:
            raw_path_item = self._json_pointer_get(
                target_spec,
                "/paths/"
                + "/".join(
                    token.replace(
                        "~1",
                        "/",
                    ).replace(
                        "~0",
                        "~",
                    )
                    for token in []
                ),
            )
        except Exception:
            raw_path_item = target_spec.get("paths", {}).get(path)

        if raw_path_item is None:
            raise OpenAPIResolutionError(f"operationRef path not found: {path}")

        path_item = await self._resolve_ref(
            raw_path_item,
            document=target_spec,
            document_url=target_url,
        )

        if not isinstance(
            path_item,
            dict,
        ):
            raise OpenAPIResolutionError(f"operationRef path item is invalid: {path}")

        raw_operation = path_item.get(method)

        if raw_operation is None:
            raise OpenAPIResolutionError(f"operationRef method not found: {method}")

        operation = await self._resolve_ref(
            raw_operation,
            document=target_spec,
            document_url=target_url,
        )

        if not isinstance(
            operation,
            dict,
        ):
            raise OpenAPIResolutionError(
                f"operationRef did not resolve to an operation object: {ref}"
            )

        return (
            operation,
            path,
            method,
            path_item,
        )

    async def _find_operation_by_id(
        self,
        spec: dict[str, Any],
        operation_id: str,
        spec_url: str | None,
    ) -> (
        tuple[
            dict[str, Any],
            dict[str, Any],
            str,
            str,
        ]
        | None
    ):
        for path, raw_item in (spec.get("paths") or {}).items():
            path_item = await self._resolve_ref(
                raw_item,
                document=spec,
                document_url=spec_url,
            )

            if not isinstance(
                path_item,
                dict,
            ):
                continue

            for method, raw_operation in path_item.items():
                method_lower = str(method).lower()

                if method_lower not in _HTTP_METHODS:
                    continue

                operation = await self._resolve_ref(
                    raw_operation,
                    document=spec,
                    document_url=spec_url,
                )

                if isinstance(operation, dict) and operation.get("operationId") == operation_id:
                    return (
                        operation,
                        path_item,
                        path,
                        method_lower,
                    )

        return None

    @staticmethod
    def _path_matches_template(
        template: str,
        actual: str,
    ) -> bool:
        escaped = re.escape(template.rstrip("/") or "/")

        pattern = re.sub(
            r"\\\{[^\\}]+\\\}",
            r"[^/]+",
            escaped,
        )

        return (
            re.match(
                "^" + pattern + r"/?$",
                actual or "/",
            )
            is not None
        )

    # -------------------------------------------------------------------------
    # Parameters
    # -------------------------------------------------------------------------

    async def _collect_parameters(
        self,
        spec: dict[str, Any],
        document_url: str | None,
        path_item: dict[str, Any],
        operation: dict[str, Any],
    ) -> list[dict[str, Any]]:
        merged: dict[
            tuple[str, str],
            dict[str, Any],
        ] = {}

        for raw_parameter in path_item.get("parameters") or []:
            parameter = await self._resolve_ref(
                raw_parameter,
                document=spec,
                document_url=document_url,
            )

            if not isinstance(
                parameter,
                dict,
            ):
                continue

            name = str(parameter.get("name", ""))
            location = str(parameter.get("in", ""))

            if name and location:
                merged[
                    (
                        name,
                        location,
                    )
                ] = parameter

        for raw_parameter in operation.get("parameters") or []:
            parameter = await self._resolve_ref(
                raw_parameter,
                document=spec,
                document_url=document_url,
            )

            if not isinstance(
                parameter,
                dict,
            ):
                continue

            name = str(parameter.get("name", ""))
            location = str(parameter.get("in", ""))

            if name and location:
                merged[
                    (
                        name,
                        location,
                    )
                ] = parameter

        return list(merged.values())

    @staticmethod
    def _lookup_parameter(
        payload: dict[str, Any],
        parameter: dict[str, Any],
    ) -> tuple[bool, Any]:
        name = str(parameter.get("name", ""))
        location = str(parameter.get("in", ""))

        by_location = payload.get(f"{location}_params")

        if (
            isinstance(
                by_location,
                dict,
            )
            and name in by_location
        ):
            return True, by_location[name]

        params = payload.get("parameters")

        if isinstance(
            params,
            dict,
        ):
            for key in (
                f"{location}.{name}",
                name,
            ):
                if key in params:
                    return True, params[key]

        direct = payload.get(name)

        if direct is not None:
            return True, direct

        return False, None

    # -------------------------------------------------------------------------
    # Parameter serialization
    # -------------------------------------------------------------------------

    @classmethod
    def _serialize_parameter(
        cls,
        parameter: dict[str, Any],
        value: Any,
    ) -> list[tuple[str, str]]:
        location = str(parameter.get("in", ""))
        name = str(parameter.get("name", ""))

        style = str(
            parameter.get(
                "style",
                {
                    "path": "simple",
                    "query": "form",
                    "header": "simple",
                    "cookie": "form",
                }.get(
                    location,
                    "form",
                ),
            )
        )

        explode = parameter.get(
            "explode",
            style == "form",
        )

        allow_empty = bool(
            parameter.get(
                "allowEmptyValue",
                False,
            )
        )

        if value is None:
            if allow_empty:
                return [(name, "")]
            return []

        if location == "path":
            return cls._serialize_path_parameter(
                name,
                value,
                style,
                bool(explode),
            )

        if location == "query":
            return cls._serialize_query_parameter(
                name,
                value,
                style,
                bool(explode),
            )

        if location == "header":
            return cls._serialize_header_parameter(
                name,
                value,
                style,
                bool(explode),
            )

        if location == "cookie":
            return cls._serialize_cookie_parameter(
                name,
                value,
                style,
                bool(explode),
            )

        raise OpenAPIResolutionError(f"Unsupported OpenAPI parameter location: {location}")

    @classmethod
    def _serialize_path_parameter(
        cls,
        name: str,
        value: Any,
        style: str,
        explode: bool,
    ) -> list[tuple[str, str]]:
        if style == "simple":
            rendered = cls._render_simple(
                value,
                explode,
            )
            return [
                (
                    "__PATH__" + name,
                    rendered,
                )
            ]

        if style == "label":
            rendered = cls._render_label(
                value,
                explode,
            )
            return [
                (
                    "__PATH_LABEL__" + name,
                    rendered,
                )
            ]

        if style == "matrix":
            rendered = cls._render_matrix(
                name,
                value,
                explode,
            )
            return [
                (
                    "__PATH_MATRIX__" + name,
                    rendered,
                )
            ]

        raise OpenAPIResolutionError(f"Unsupported OpenAPI path parameter style {style!r}")

    @classmethod
    def _serialize_query_parameter(
        cls,
        name: str,
        value: Any,
        style: str,
        explode: bool,
    ) -> list[tuple[str, str]]:
        if style == "form":
            if isinstance(value, dict):
                if explode:
                    return [
                        (
                            str(key),
                            cls._serialize_scalar(item),
                        )
                        for key, item in value.items()
                    ]

                return [
                    (
                        name,
                        cls._render_exploded_object(
                            value,
                            delimiter=",",
                        ),
                    )
                ]

            if isinstance(
                value,
                (list, tuple),
            ):
                if explode:
                    return [
                        (
                            name,
                            cls._serialize_scalar(item),
                        )
                        for item in value
                    ]

                return [
                    (
                        name,
                        ",".join(cls._serialize_scalar(item) for item in value),
                    )
                ]

            return [
                (
                    name,
                    cls._serialize_scalar(value),
                )
            ]

        if style == "spaceDelimited":
            if not isinstance(
                value,
                (list, tuple),
            ):
                raise OpenAPIResolutionError(
                    f"spaceDelimited query parameter {name!r} must be an array"
                )

            return [
                (
                    name,
                    " ".join(cls._serialize_scalar(item) for item in value),
                )
            ]

        if style == "pipeDelimited":
            if not isinstance(
                value,
                (list, tuple),
            ):
                raise OpenAPIResolutionError(
                    f"pipeDelimited query parameter {name!r} must be an array"
                )

            return [
                (
                    name,
                    "|".join(cls._serialize_scalar(item) for item in value),
                )
            ]

        if style == "deepObject":
            if not isinstance(
                value,
                dict,
            ):
                raise OpenAPIResolutionError(
                    f"deepObject query parameter {name!r} must be an object"
                )

            return [
                (
                    f"{name}[{key}]",
                    cls._serialize_scalar(item),
                )
                for key, item in value.items()
            ]

        raise OpenAPIResolutionError(f"Unsupported OpenAPI query parameter style {style!r}")

    @classmethod
    def _serialize_header_parameter(
        cls,
        name: str,
        value: Any,
        style: str,
        explode: bool,
    ) -> list[tuple[str, str]]:
        if style != "simple":
            raise OpenAPIResolutionError(f"Unsupported OpenAPI header parameter style {style!r}")

        return [
            (
                name,
                cls._render_simple(
                    value,
                    explode,
                ),
            )
        ]

    @classmethod
    def _serialize_cookie_parameter(
        cls,
        name: str,
        value: Any,
        style: str,
        explode: bool,
    ) -> list[tuple[str, str]]:
        if style != "form":
            raise OpenAPIResolutionError(f"Unsupported OpenAPI cookie parameter style {style!r}")

        if isinstance(
            value,
            dict,
        ):
            if explode:
                return [
                    (
                        str(key),
                        cls._serialize_scalar(item),
                    )
                    for key, item in value.items()
                ]

            return [
                (
                    name,
                    cls._render_exploded_object(
                        value,
                        delimiter=",",
                    ),
                )
            ]

        if isinstance(
            value,
            (list, tuple),
        ):
            if explode:
                return [
                    (
                        name,
                        cls._serialize_scalar(item),
                    )
                    for item in value
                ]

            return [
                (
                    name,
                    ",".join(cls._serialize_scalar(item) for item in value),
                )
            ]

        return [
            (
                name,
                cls._serialize_scalar(value),
            )
        ]

    @classmethod
    def _render_simple(
        cls,
        value: Any,
        explode: bool,
    ) -> str:
        if isinstance(
            value,
            dict,
        ):
            if explode:
                return ",".join(
                    f"{key}={cls._serialize_scalar(item)}" for key, item in value.items()
                )

            return cls._render_exploded_object(
                value,
                delimiter=",",
            )

        if isinstance(
            value,
            (list, tuple),
        ):
            return ",".join(cls._serialize_scalar(item) for item in value)

        return cls._serialize_scalar(value)

    @classmethod
    def _render_label(
        cls,
        value: Any,
        explode: bool,
    ) -> str:
        if isinstance(
            value,
            dict,
        ):
            if explode:
                return ".".join(
                    f"{key}={cls._serialize_scalar(item)}" for key, item in value.items()
                )

            return ".".join(
                [
                    str(key),
                    cls._serialize_scalar(item),
                ]
                for key, item in value.items()
            )

        if isinstance(
            value,
            (list, tuple),
        ):
            return ".".join(cls._serialize_scalar(item) for item in value)

        return cls._serialize_scalar(value)

    @classmethod
    def _render_matrix(
        cls,
        name: str,
        value: Any,
        explode: bool,
    ) -> str:
        if isinstance(
            value,
            dict,
        ):
            if explode:
                return ";".join(
                    f"{key}={cls._serialize_scalar(item)}" for key, item in value.items()
                )

            parts: list[str] = []

            for key, item in value.items():
                parts.extend(
                    (
                        str(key),
                        cls._serialize_scalar(item),
                    )
                )

            return ";" + quote(
                ",".join(parts),
                safe=",=;-_./~",
            )

        if isinstance(
            value,
            (list, tuple),
        ):
            if explode:
                return "".join(";" + name + "=" + cls._serialize_scalar(item) for item in value)

            return ";" + name + "=" + ",".join(cls._serialize_scalar(item) for item in value)

        return f";{name}={cls._serialize_scalar(value)}"

    @staticmethod
    def _render_exploded_object(
        value: dict[str, Any],
        delimiter: str,
    ) -> str:
        return delimiter.join(
            (
                str(key),
                OpenAPIAdapterPlugin._serialize_scalar(item),
            )
            for key, item in value.items()
        )

    # -------------------------------------------------------------------------
    # Request construction
    # -------------------------------------------------------------------------

    async def _build_request(
        self,
        *,
        spec: dict[str, Any] | None,
        document_url: str | None,
        path_item: dict[str, Any] | None,
        operation: dict[str, Any] | None,
        path_template: str | None,
        method: str,
        endpoint: str,
        payload: dict[str, Any],
    ) -> tuple[
        str,
        str,
        dict[str, str],
        dict[str, str],
        Any,
        str | None,
    ]:
        if not spec or not path_item or not operation or not path_template:
            body = self._body_from_payload(payload)

            headers = self._coerce_string_mapping(payload.get("headers"))

            header_params = payload.get("header_params")

            if isinstance(
                header_params,
                dict,
            ):
                headers.update(self._coerce_string_mapping(header_params))

            cookies = self._coerce_string_mapping(payload.get("cookies"))

            cookie_params = payload.get("cookie_params")

            if isinstance(
                cookie_params,
                dict,
            ):
                cookies.update(self._coerce_string_mapping(cookie_params))

            content_type = payload.get("content_type")

            if body is not None and content_type:
                headers.setdefault(
                    "Content-Type",
                    str(content_type),
                )

            return (
                self._safe_url(endpoint),
                method.upper(),
                headers,
                cookies,
                body,
                str(content_type) if content_type else None,
            )

        server_url = await self._resolve_server(
            spec=spec,
            path_item=path_item,
            operation=operation,
            document_url=document_url,
            payload=payload,
            endpoint=endpoint,
        )

        target_url = urljoin(
            server_url.rstrip("/") + "/",
            path_template.lstrip("/"),
        )

        parameters = await self._collect_parameters(
            spec,
            document_url,
            path_item,
            operation,
        )

        query_pairs: list[tuple[str, str]] = []

        headers = self._coerce_string_mapping(payload.get("headers"))

        header_params = payload.get("header_params")

        if isinstance(
            header_params,
            dict,
        ):
            headers.update(self._coerce_string_mapping(header_params))

        cookies = self._coerce_string_mapping(payload.get("cookies"))

        cookie_params = payload.get("cookie_params")

        if isinstance(
            cookie_params,
            dict,
        ):
            cookies.update(self._coerce_string_mapping(cookie_params))

        path_substitutions: list[tuple[str, str, str]] = []

        for parameter in parameters:
            found, value = self._lookup_parameter(
                payload,
                parameter,
            )

            if not found:
                if parameter.get("required"):
                    raise OpenAPIResolutionError(
                        "Missing required OpenAPI parameter "
                        f"{parameter.get('in')}.{parameter.get('name')}"
                    )

                continue

            serialized = self._serialize_parameter(
                parameter,
                value,
            )

            for key, rendered in serialized:
                if key.startswith("__PATH__"):
                    path_substitutions.append(
                        (
                            parameter["name"],
                            "simple",
                            rendered,
                        )
                    )
                elif key.startswith("__PATH_LABEL__"):
                    path_substitutions.append(
                        (
                            parameter["name"],
                            "label",
                            rendered,
                        )
                    )
                elif key.startswith("__PATH_MATRIX__"):
                    path_substitutions.append(
                        (
                            parameter["name"],
                            "matrix",
                            rendered,
                        )
                    )
                elif parameter["in"] == "query":
                    query_pairs.append(
                        (
                            key,
                            rendered,
                        )
                    )
                elif parameter["in"] == "header":
                    headers[key] = rendered
                elif parameter["in"] == "cookie":
                    cookies[key] = rendered

        for name, style, rendered in path_substitutions:
            placeholder = "{" + name + "}"

            if placeholder not in target_url:
                continue

            encoded = rendered

            if style == "simple":
                encoded = quote(
                    encoded,
                    safe=",=:_-./~",
                )
            elif style == "label":
                encoded = "." + rendered
            elif style == "matrix":
                encoded = rendered

            target_url = target_url.replace(
                placeholder,
                encoded,
            )

        parsed = urlparse(target_url)

        existing_query = parse_qsl(
            parsed.query,
            keep_blank_values=True,
        )

        target_url = urlunparse(
            parsed._replace(
                query=urlencode(
                    existing_query + query_pairs,
                    doseq=True,
                )
            )
        )

        body = self._body_from_payload(payload)

        content_type = payload.get("content_type")

        request_body = None

        if operation.get("requestBody") is not None:
            request_body = await self._resolve_ref(
                operation["requestBody"],
                document=spec,
                document_url=document_url,
            )

        if request_body is not None:
            if not isinstance(
                request_body,
                dict,
            ):
                raise OpenAPIResolutionError("OpenAPI requestBody is not an object")

            content = request_body.get("content") or {}

            if not isinstance(
                content,
                dict,
            ):
                raise OpenAPIResolutionError("OpenAPI requestBody.content must be an object")

            if body is None and request_body.get(
                "required",
                False,
            ):
                raise OpenAPIResolutionError("OpenAPI operation requires a request body")

            if body is not None and content:
                media_type = self._select_media_type(
                    content,
                    str(content_type) if content_type else None,
                )

                content_type = media_type

                if media_type:
                    normalized_media = self._normalized_content_type(media_type)

                    if normalized_media != "multipart/form-data":
                        headers.setdefault(
                            "Content-Type",
                            media_type,
                        )

        elif body is not None and content_type:
            headers.setdefault(
                "Content-Type",
                str(content_type),
            )

        return (
            self._safe_url(target_url),
            method.upper(),
            headers,
            cookies,
            body,
            str(content_type) if content_type else None,
        )

    @staticmethod
    def _coerce_string_mapping(
        value: Any,
    ) -> dict[str, str]:
        if not isinstance(
            value,
            dict,
        ):
            return {}

        return {str(key): str(item) for key, item in value.items()}

    @staticmethod
    def _body_from_payload(
        payload: dict[str, Any],
    ) -> Any:
        if "input_payload" in payload:
            return payload["input_payload"]

        if "request_body" in payload:
            return payload["request_body"]

        if "body" in payload:
            return payload["body"]

        data = {key: value for key, value in payload.items() if key not in _CONTROL_KEYS}

        return data if data else None

    @classmethod
    def _select_media_type(
        cls,
        content: dict[str, Any],
        requested: str | None,
    ) -> str | None:
        if not content:
            return None

        if requested:
            normalized_requested = cls._normalized_content_type(requested)

            for media_type in content:
                if cls._normalized_content_type(media_type) == normalized_requested:
                    return media_type

            requested_main = normalized_requested.split(
                "/",
                1,
            )[0]

            for media_type in content:
                normalized = cls._normalized_content_type(media_type)

                if normalized == f"{requested_main}/*":
                    return media_type

                if normalized.endswith("+json") and normalized_requested == "application/json":
                    return media_type

            raise OpenAPIResolutionError(
                f"Requested content type {requested!r} is not supported; "
                f"expected one of {list(content)}"
            )

        for preferred in (
            "application/json",
            "application/*+json",
            "application/x-www-form-urlencoded",
            "multipart/form-data",
            "text/plain",
            "application/octet-stream",
        ):
            if preferred in content:
                return preferred

        return next(
            iter(content),
            None,
        )

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------

    async def _get_auth_context(
        self,
        payload: dict[str, Any],
        *,
        spec: dict[str, Any] | None = None,
        operation: dict[str, Any] | None = None,
        path_item: dict[str, Any] | None = None,
        document_url: str | None = None,
    ) -> tuple[
        dict[str, str],
        dict[str, str],
        dict[str, str],
    ]:
        if not spec or not operation:
            return await self._legacy_auth_context(payload)

        if "security" in operation:
            security = operation.get("security")
        else:
            security = spec.get("security")

        if security == []:
            return {}, {}, {}

        if security is None:
            return await self._legacy_auth_context(payload)

        schemes = spec.get("components", {}).get("securitySchemes", {})

        if not isinstance(
            schemes,
            dict,
        ):
            schemes = {}

        auth = self._get_auth_config(payload)

        last_error: Exception | None = None

        for requirement in security:
            if not isinstance(
                requirement,
                dict,
            ):
                continue

            try:
                headers: dict[str, str] = {}
                query: dict[str, str] = {}
                cookies: dict[str, str] = {}

                for scheme_name, scopes in requirement.items():
                    raw_scheme = schemes.get(scheme_name)

                    if raw_scheme is None:
                        custom_schemes = auth.get("schemes")

                        if isinstance(
                            custom_schemes,
                            dict,
                        ):
                            raw_scheme = custom_schemes.get(scheme_name)

                    scheme = (
                        await self._resolve_ref(
                            raw_scheme,
                            document=spec,
                            document_url=document_url,
                        )
                        if raw_scheme is not None
                        else None
                    )

                    if not isinstance(
                        scheme,
                        dict,
                    ):
                        raise OpenAPIResolutionError(
                            f"Security scheme {scheme_name!r} "
                            "is not defined in the OpenAPI document"
                        )

                    (
                        h,
                        q,
                        c,
                    ) = await self._apply_security_scheme(
                        scheme_name,
                        scheme,
                        list(scopes or []),
                        auth,
                        spec=spec,
                        document_url=document_url,
                    )

                    headers.update(h)
                    query.update(q)
                    cookies.update(c)

                return (
                    headers,
                    query,
                    cookies,
                )

            except Exception as exc:
                last_error = exc
                continue

        raise OpenAPIResolutionError(
            "No configured OpenAPI security requirement could be satisfied"
            + (f": {last_error}" if last_error else "")
        )

    @staticmethod
    def _get_auth_config(
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        auth = payload.get("auth")

        if isinstance(
            auth,
            dict,
        ):
            return auth

        metadata = payload.get("metadata")

        if isinstance(
            metadata,
            dict,
        ):
            auth = metadata.get("auth")

            if isinstance(
                auth,
                dict,
            ):
                return auth

        return {}

    async def _apply_security_scheme(
        self,
        name: str,
        scheme: dict[str, Any],
        scopes: list[str],
        auth: dict[str, Any],
        *,
        spec: dict[str, Any],
        document_url: str | None,
    ) -> tuple[
        dict[str, str],
        dict[str, str],
        dict[str, str],
    ]:
        scheme_type = str(scheme.get("type", ""))

        credentials = self._get_scheme_credentials(
            name,
            auth,
        )

        if scheme_type == "apiKey":
            value = credentials.get("value") or credentials.get("key") or credentials.get("token")

            if value is None:
                value = self._auth_env(
                    name,
                    suffixes=(
                        "KEY",
                        "TOKEN",
                    ),
                )

            if value is None:
                value = auth.get("api_key") or os.getenv("OPENAPI_API_KEY")

            if not value:
                raise OpenAPIResolutionError(
                    f"Missing credential for OpenAPI apiKey scheme {name!r}"
                )

            key_name = str(scheme.get("name", ""))
            location = str(scheme.get("in", ""))

            if not key_name:
                raise OpenAPIResolutionError(f"OpenAPI apiKey scheme {name!r} is missing name")

            if location == "header":
                return (
                    {key_name: str(value)},
                    {},
                    {},
                )

            if location == "query":
                return (
                    {},
                    {key_name: str(value)},
                    {},
                )

            if location == "cookie":
                return (
                    {},
                    {},
                    {key_name: str(value)},
                )

            raise OpenAPIResolutionError(f"Unsupported OpenAPI apiKey location {location!r}")

        if scheme_type == "http":
            http_scheme = str(scheme.get("scheme", "")).lower()

            if http_scheme == "bearer":
                token = (
                    credentials.get("token")
                    or credentials.get("access_token")
                    or auth.get("access_token")
                    or auth.get("token")
                    or self._auth_env(
                        name,
                        suffixes=(
                            "TOKEN",
                            "KEY",
                        ),
                    )
                    or os.getenv("OPENAPI_TOKEN")
                    or os.getenv("OPENAPI_API_KEY")
                )

                if not token:
                    raise OpenAPIResolutionError(
                        f"Missing bearer token for OpenAPI scheme {name!r}"
                    )

                return (
                    {"Authorization": f"Bearer {token}"},
                    {},
                    {},
                )

            if http_scheme == "basic":
                username = (
                    credentials.get("username")
                    or auth.get("username")
                    or self._auth_env(
                        name,
                        suffixes=("USERNAME",),
                    )
                    or os.getenv("OPENAPI_USERNAME")
                )

                password = (
                    credentials.get("password")
                    or auth.get("password")
                    or self._auth_env(
                        name,
                        suffixes=("PASSWORD",),
                    )
                    or os.getenv("OPENAPI_PASSWORD")
                )

                if username is None or password is None:
                    raise OpenAPIResolutionError(
                        f"Missing basic-auth credentials for OpenAPI scheme {name!r}"
                    )

                encoded = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")

                return (
                    {"Authorization": f"Basic {encoded}"},
                    {},
                    {},
                )

            token = credentials.get("token") or credentials.get("access_token")

            if token:
                return (
                    {"Authorization": (f"{http_scheme} {token}")},
                    {},
                    {},
                )

            raise OpenAPIResolutionError(
                f"Unsupported OpenAPI HTTP auth scheme {http_scheme!r} without an explicit token"
            )

        if scheme_type == "oauth2":
            return await self._apply_oauth2_scheme(
                name,
                scheme,
                scopes,
                auth,
                document_url=document_url,
            )

        if scheme_type == "openIdConnect":
            return await self._apply_openid_connect_scheme(
                name,
                scheme,
                scopes,
                auth,
                document_url=document_url,
            )

        if scheme_type == "mutualTLS":
            if credentials.get("configured"):
                return {}, {}, {}

            raise OpenAPIResolutionError(
                f"OpenAPI mutualTLS scheme {name!r} requires an "
                "externally configured TLS client certificate"
            )

        raise OpenAPIResolutionError(f"Unsupported OpenAPI security scheme type {scheme_type!r}")

    @staticmethod
    def _get_scheme_credentials(
        name: str,
        auth: dict[str, Any],
    ) -> dict[str, Any]:
        schemes = auth.get("schemes")

        credentials: Any = None

        if isinstance(
            schemes,
            dict,
        ):
            credentials = schemes.get(name)

        if credentials is None:
            credentials = auth.get(name)

        if isinstance(
            credentials,
            dict,
        ):
            return credentials

        if isinstance(
            credentials,
            str,
        ):
            return {"token": credentials}

        return {}

    @staticmethod
    def _auth_env(
        scheme_name: str,
        *,
        suffixes: Iterable[str],
    ) -> str | None:
        prefix = re.sub(
            r"[^A-Za-z0-9]",
            "_",
            scheme_name,
        ).upper()

        for suffix in suffixes:
            value = os.getenv(f"OPENAPI_{prefix}_{suffix}")

            if value:
                return value

        return None

    async def _apply_oauth2_scheme(
        self,
        name: str,
        scheme: dict[str, Any],
        scopes: list[str],
        auth: dict[str, Any],
        *,
        document_url: str | None,
    ) -> tuple[
        dict[str, str],
        dict[str, str],
        dict[str, str],
    ]:
        credentials = self._get_scheme_credentials(
            name,
            auth,
        )

        access_token = (
            credentials.get("access_token") or credentials.get("token") or auth.get("access_token")
        )

        if access_token:
            return (
                {"Authorization": f"Bearer {access_token}"},
                {},
                {},
            )

        flows = scheme.get("flows") or {}

        if not isinstance(
            flows,
            dict,
        ):
            raise OpenAPIResolutionError(f"Invalid OAuth2 flows for scheme {name!r}")

        grant_type = str(credentials.get("grant_type" or auth.get("grant_type") or "")).strip()

        flow_name: str | None = None
        flow: dict[str, Any] | None = None

        flow_candidates: list[tuple[str, str]] = []

        if grant_type:
            flow_candidates.append(
                (
                    grant_type,
                    grant_type,
                )
            )

        flow_candidates.extend(
            [
                (
                    "client_credentials",
                    "clientCredentials",
                ),
                (
                    "password",
                    "password",
                ),
                (
                    "authorization_code",
                    "authorizationCode",
                ),
                (
                    "implicit",
                    "implicit",
                ),
            ]
        )

        for _candidate_grant, candidate_flow_name in flow_candidates:
            candidate = flows.get(candidate_flow_name)

            if isinstance(
                candidate,
                dict,
            ):
                flow_name = candidate_flow_name
                flow = candidate
                grant_type = (
                    "client_credentials"
                    if candidate_flow_name == "clientCredentials"
                    else candidate_flow_name
                )
                break

        if flow is None:
            raise OpenAPIResolutionError(
                f"OAuth2 scheme {name!r} has no supported flow and no access token was supplied"
            )

        if flow_name == "clientCredentials":
            token = await self._fetch_oauth_token(
                token_url=self._resolve_token_url(
                    flow.get("tokenUrl"),
                    document_url,
                ),
                client_id=(
                    credentials.get("client_id")
                    or auth.get("client_id")
                    or os.getenv("OPENAPI_CLIENT_ID")
                ),
                client_secret=(
                    credentials.get("client_secret")
                    or auth.get("client_secret")
                    or os.getenv("OPENAPI_CLIENT_SECRET")
                ),
                scopes=scopes,
                declared_scopes=flow.get("scopes") or {},
                grant_type="client_credentials",
                username=None,
                password=None,
                use_basic=(credentials.get("token_endpoint_auth_method") == "client_secret_basic"),
            )

            return (
                {"Authorization": f"Bearer {token}"},
                {},
                {},
            )

        if flow_name == "password":
            token_url = self._resolve_token_url(
                flow.get("tokenUrl"),
                document_url,
            )

            username = (
                credentials.get("username") or auth.get("username") or os.getenv("OPENAPI_USERNAME")
            )

            password = (
                credentials.get("password") or auth.get("password") or os.getenv("OPENAPI_PASSWORD")
            )

            client_id = (
                credentials.get("client_id")
                or auth.get("client_id")
                or os.getenv("OPENAPI_CLIENT_ID")
            )

            client_secret = (
                credentials.get("client_secret")
                or auth.get("client_secret")
                or os.getenv("OPENAPI_CLIENT_SECRET")
            )

            if not username or not password:
                raise OpenAPIResolutionError(
                    f"OAuth2 password flow for scheme {name!r} requires username and password"
                )

            token = await self._fetch_oauth_token(
                token_url=token_url,
                client_id=client_id,
                client_secret=client_secret,
                scopes=scopes,
                declared_scopes=flow.get("scopes") or {},
                grant_type="password",
                username=username,
                password=password,
                use_basic=(credentials.get("token_endpoint_auth_method") == "client_secret_basic"),
            )

            return (
                {"Authorization": f"Bearer {token}"},
                {},
                {},
            )

        if flow_name == "authorizationCode":
            refresh_token = credentials.get("refresh_token") or auth.get("refresh_token")

            if refresh_token:
                token_url = self._resolve_token_url(
                    flow.get("tokenUrl"),
                    document_url,
                )

                token = await self._fetch_oauth_token(
                    token_url=token_url,
                    client_id=(
                        credentials.get("client_id")
                        or auth.get("client_id")
                        or os.getenv("OPENAPI_CLIENT_ID")
                    ),
                    client_secret=(
                        credentials.get("client_secret")
                        or auth.get("client_secret")
                        or os.getenv("OPENAPI_CLIENT_SECRET")
                    ),
                    scopes=scopes,
                    declared_scopes=flow.get("scopes") or {},
                    grant_type="refresh_token",
                    username=None,
                    password=None,
                    refresh_token=refresh_token,
                    use_basic=(
                        credentials.get("token_endpoint_auth_method") == "client_secret_basic"
                    ),
                )

                return (
                    {"Authorization": f"Bearer {token}"},
                    {},
                    {},
                )

            raise OpenAPIResolutionError(
                f"OAuth2 authorizationCode flow for scheme {name!r} "
                "requires an access token or externally obtained refresh token"
            )

        if flow_name == "implicit":
            raise OpenAPIResolutionError(
                f"OAuth2 implicit flow for scheme {name!r} requires "
                "an externally obtained access token"
            )

        raise OpenAPIResolutionError(f"Unsupported OAuth2 flow for scheme {name!r}: {flow_name}")

    @staticmethod
    def _resolve_token_url(
        token_url: Any,
        document_url: str | None,
    ) -> str:
        if not token_url:
            raise OpenAPIResolutionError("OAuth2 token endpoint is missing")

        resolved = str(token_url)

        if document_url and not urlparse(resolved).scheme:
            resolved = urljoin(
                document_url,
                resolved,
            )

        return OpenAPIAdapterPlugin._safe_url(resolved)

    async def _apply_openid_connect_scheme(
        self,
        name: str,
        scheme: dict[str, Any],
        scopes: list[str],
        auth: dict[str, Any],
        *,
        document_url: str | None,
    ) -> tuple[
        dict[str, str],
        dict[str, str],
        dict[str, str],
    ]:
        credentials = self._get_scheme_credentials(
            name,
            auth,
        )

        token = (
            credentials.get("access_token")
            or credentials.get("token")
            or auth.get("access_token")
            or auth.get("token")
        )

        if token:
            return (
                {"Authorization": f"Bearer {token}"},
                {},
                {},
            )

        discovery_url = scheme.get("openIdConnectUrl")

        if not discovery_url:
            raise OpenAPIResolutionError(
                f"OpenID Connect scheme {name!r} is missing openIdConnectUrl"
            )

        if document_url and not urlparse(str(discovery_url)).scheme:
            discovery_url = urljoin(
                document_url,
                str(discovery_url),
            )

        discovery_url = self._safe_url(str(discovery_url))

        discovery = await self._fetch_document(
            discovery_url,
            explicit=True,
        )

        token_url = discovery.get("token_endpoint")

        if not token_url:
            raise OpenAPIResolutionError(
                f"OpenID Connect discovery for {name!r} did not provide token_endpoint"
            )

        grant_type = str(
            credentials.get("grant_type" or auth.get("grant_type") or "client_credentials")
        )

        token = await self._fetch_oauth_token(
            token_url=self._resolve_token_url(
                token_url,
                discovery_url,
            ),
            client_id=(
                credentials.get("client_id")
                or auth.get("client_id")
                or os.getenv("OPENAPI_CLIENT_ID")
            ),
            client_secret=(
                credentials.get("client_secret")
                or auth.get("client_secret")
                or os.getenv("OPENAPI_CLIENT_SECRET")
            ),
            scopes=scopes,
            declared_scopes={},
            grant_type=grant_type,
            username=(credentials.get("username") or auth.get("username")),
            password=(credentials.get("password") or auth.get("password")),
            refresh_token=(credentials.get("refresh_token") or auth.get("refresh_token")),
            use_basic=(credentials.get("token_endpoint_auth_method") == "client_secret_basic"),
        )

        return (
            {"Authorization": f"Bearer {token}"},
            {},
            {},
        )

    async def _fetch_oauth_token(
        self,
        *,
        token_url: str,
        client_id: str | None,
        client_secret: str | None,
        scopes: list[str],
        declared_scopes: dict[str, Any],
        grant_type: str,
        username: str | None,
        password: str | None,
        refresh_token: str | None = None,
        use_basic: bool = False,
    ) -> str:
        if grant_type != "refresh_token" and not client_id:
            raise OpenAPIResolutionError("OAuth2 client_id is required")

        if (
            grant_type
            in {
                "client_credentials",
                "password",
                "refresh_token",
            }
            and not use_basic
            and grant_type != "password"
            and client_id
            and not client_secret
        ):
            raise OpenAPIResolutionError(
                f"OAuth2 client_secret is required for {grant_type} "
                "unless the token endpoint uses another authentication method"
            )

        scope_values = [
            scope for scope in scopes if not declared_scopes or scope in declared_scopes
        ]

        secret_fingerprint = hashlib.sha256((client_secret or "").encode("utf-8")).hexdigest()[:16]

        cache_key = (
            token_url,
            client_id or "",
            secret_fingerprint,
            " ".join(sorted(scope_values)),
            grant_type,
        )

        cached = self._oauth_cache.get(cache_key)

        now = time.monotonic()

        if cached is not None and cached[0] > now + 15:
            return cached[1]

        session = await self.get_session()

        async def _call():
            form: dict[str, str] = {
                "grant_type": grant_type,
            }

            if scope_values:
                form["scope"] = " ".join(scope_values)

            if grant_type == "password":
                if username is None or password is None:
                    raise OpenAPIResolutionError(
                        "OAuth2 password flow requires username and password"
                    )

                form["username"] = username
                form["password"] = password

            elif grant_type == "refresh_token":
                if not refresh_token:
                    raise OpenAPIResolutionError("OAuth2 refresh_token flow requires refresh_token")

                form["refresh_token"] = refresh_token

            if use_basic:
                if not client_id or not client_secret:
                    raise OpenAPIResolutionError(
                        "OAuth2 client_secret_basic requires client_id and client_secret"
                    )

                basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")

                request_headers = {
                    "Authorization": f"Basic {basic}",
                    "Content-Type": ("application/x-www-form-urlencoded"),
                    "Accept": "application/json",
                }

            else:
                request_headers = {
                    "Content-Type": ("application/x-www-form-urlencoded"),
                    "Accept": "application/json",
                }

                if client_id:
                    form["client_id"] = client_id

                if client_secret:
                    form["client_secret"] = client_secret

            async with session.post(
                token_url,
                headers=request_headers,
                data=form,
                timeout=aiohttp.ClientTimeout(total=config.DEFAULT_ADAPTER_TIMEOUT),
                allow_redirects=False,
            ) as response:
                raw = await self._read_response_bytes(
                    response,
                    limit=_MAX_RESPONSE_BYTES,
                )

                if response.status in _RETRYABLE_STATUS_CODES:
                    raise self._response_error(
                        response.status,
                        raw.decode(
                            "utf-8",
                            errors="replace",
                        ),
                        token_url,
                        response.headers,
                    )

                if response.status >= 400:
                    raise OpenAPIResolutionError(
                        "OAuth2 token request failed: "
                        f"HTTP {response.status}: "
                        f"{raw.decode('utf-8', errors='replace')[:_MAX_ERROR_BODY]}"
                    )

                data = self._decode_response(
                    raw,
                    response.headers.get(
                        "Content-Type",
                        "",
                    ),
                    response.status,
                )

                if not isinstance(
                    data,
                    dict,
                ):
                    raise OpenAPIResolutionError(
                        "OAuth2 token endpoint did not return a JSON object"
                    )

                token = data.get("access_token")

                if not token:
                    raise OpenAPIResolutionError(
                        "OAuth2 token endpoint response omitted access_token"
                    )

                try:
                    expires_in = int(
                        data.get(
                            "expires_in",
                            300,
                        )
                    )
                except (TypeError, ValueError):
                    expires_in = 300

                return (
                    str(token),
                    max(
                        30,
                        expires_in,
                    ),
                )

        token, expires_in = await self.call_with_retry(
            _call,
            retry_codes=_RETRYABLE_STATUS_CODES,
        )

        self._oauth_cache[cache_key] = (
            time.monotonic() + expires_in,
            token,
        )

        return token

    async def _legacy_auth_context(
        self,
        payload: dict[str, Any],
    ) -> tuple[
        dict[str, str],
        dict[str, str],
        dict[str, str],
    ]:
        auth = self._get_auth_config(payload)

        token = (
            auth.get("token")
            or auth.get("api_key")
            or auth.get("access_token")
            or os.getenv("OPENAPI_TOKEN")
            or os.getenv("OPENAPI_API_KEY")
        )

        if token:
            return (
                {"Authorization": f"Bearer {token}"},
                {},
                {},
            )

        client_id = auth.get("client_id") or os.getenv("OPENAPI_CLIENT_ID")

        client_secret = auth.get("client_secret") or os.getenv("OPENAPI_CLIENT_SECRET")

        token_url = auth.get("token_url") or os.getenv("OPENAPI_TOKEN_URL")

        if client_id and client_secret and token_url:
            token = await self._fetch_oauth_token(
                token_url=self._resolve_token_url(
                    token_url,
                    None,
                ),
                client_id=client_id,
                client_secret=client_secret,
                scopes=[],
                declared_scopes={},
                grant_type="client_credentials",
                username=None,
                password=None,
            )

            return (
                {"Authorization": f"Bearer {token}"},
                {},
                {},
            )

        username = auth.get("username") or os.getenv("OPENAPI_USERNAME")

        password = auth.get("password") or os.getenv("OPENAPI_PASSWORD")

        if username is not None and password is not None:
            encoded = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")

            return (
                {"Authorization": f"Basic {encoded}"},
                {},
                {},
            )

        return {}, {}, {}

    async def _get_auth_header(
        self,
        payload: dict[str, Any],
    ) -> dict[str, str]:
        headers, _, _ = await self._legacy_auth_context(payload)

        return headers

    # -------------------------------------------------------------------------
    # Request execution
    # -------------------------------------------------------------------------

    async def execute_openapi_query(
        self,
        payload: dict[str, Any],
        endpoint: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        endpoint = endpoint or payload.get("url") or payload.get("endpoint")

        if not endpoint:
            return {
                "status": "error",
                "action": "error",
                "message": "Missing endpoint URL for OpenAPI adapter.",
            }

        endpoint = self._safe_url(str(endpoint))

        metadata = payload.get("metadata") or {}

        overrides = (
            kwargs.get("overrides")
            or payload.get("overrides")
            or (
                metadata.get("overrides")
                if isinstance(
                    metadata,
                    dict,
                )
                else None
            )
        )

        if not isinstance(
            overrides,
            dict,
        ):
            overrides = None

        try:
            spec, spec_url = await self._load_spec(
                endpoint,
                payload,
            )

            resolved = None

            if spec:
                resolved = await self._find_operation(
                    spec,
                    spec_url,
                    endpoint,
                    payload,
                )

            if resolved:
                (
                    operation,
                    path_item,
                    path_template,
                    method,
                ) = resolved

                (
                    target_url,
                    method,
                    request_headers,
                    request_cookies,
                    body,
                    content_type,
                ) = await self._build_request(
                    spec=spec,
                    document_url=spec_url,
                    path_item=path_item,
                    operation=operation,
                    path_template=path_template,
                    method=method,
                    endpoint=endpoint,
                    payload=payload,
                )

            else:
                operation = None
                path_item = None
                path_template = None

                method = str(
                    payload.get(
                        "method",
                        "POST",
                    )
                ).upper()

                if method.lower() not in _HTTP_METHODS:
                    raise OpenAPIResolutionError(f"Unsupported HTTP method {method!r}")

                (
                    target_url,
                    method,
                    request_headers,
                    request_cookies,
                    body,
                    content_type,
                ) = await self._build_request(
                    spec=None,
                    document_url=None,
                    path_item=None,
                    operation=None,
                    path_template=None,
                    method=method,
                    endpoint=endpoint,
                    payload=payload,
                )

            (
                auth_headers,
                auth_query,
                auth_cookies,
            ) = await self._get_auth_context(
                payload,
                spec=spec,
                operation=operation,
                path_item=path_item,
                document_url=spec_url,
            )

            request_headers.update(auth_headers)
            request_cookies.update(auth_cookies)

            if auth_query:
                parsed = urlparse(target_url)

                existing = parse_qsl(
                    parsed.query,
                    keep_blank_values=True,
                )

                target_url = urlunparse(
                    parsed._replace(
                        query=urlencode(
                            existing + list(auth_query.items()),
                            doseq=True,
                        )
                    )
                )

            if body is not None and content_type:
                normalized_content = self._normalized_content_type(content_type)

                if normalized_content != "multipart/form-data":
                    request_headers.setdefault(
                        "Content-Type",
                        str(content_type),
                    )

            request_headers.setdefault(
                "Accept",
                "application/json, text/plain, */*",
            )

            retry_safe = self._is_retry_safe(
                method,
                payload,
                request_headers,
            )

            (
                response_json,
                status_code,
                response_headers,
                response_text,
            ) = await self._request(
                method=method,
                url=target_url,
                headers=request_headers,
                cookies=request_cookies,
                body=body,
                content_type=content_type,
                retry_safe=retry_safe,
            )

            result = await self._build_result(
                response_json=response_json,
                response_text=response_text,
                status_code=status_code,
                response_headers=response_headers,
                overrides=overrides,
                operation=operation,
                spec=spec,
                spec_url=spec_url,
                request_url=target_url,
                request_method=method,
            )

            if result.get("action") == "processing":
                poll_target = await self._resolve_poll_target(
                    response_json=response_json,
                    response_headers=response_headers,
                    operation=operation,
                    spec=spec,
                    spec_url=spec_url,
                    request_url=target_url,
                    request_method=method,
                )

                if poll_target:
                    return await self._poll_for_result(
                        poll_target["url"],
                        overrides,
                        poll_target.get("headers") or request_headers,
                        method=poll_target.get(
                            "method",
                            "GET",
                        ),
                        operation=poll_target.get("operation"),
                        spec=poll_target.get("spec") or spec,
                        spec_url=poll_target.get("spec_url") or spec_url,
                        initial_body=poll_target.get("body"),
                        cookies=poll_target.get("cookies") or request_cookies,
                        initial_delay=poll_target.get(
                            "initial_delay",
                            0.0,
                        ),
                    )

            return result

        except aiohttp.ClientResponseError as exc:
            return {
                "status": "error",
                "action": "error",
                "message": (f"HTTP {exc.status}: {exc.message or 'request failed'}"),
            }

        except Exception as exc:
            logger.debug(
                "OpenAPI adapter execution failed",
                exc_info=True,
            )

            return {
                "status": "error",
                "action": "error",
                "message": str(exc),
            }

    @staticmethod
    def _is_retry_safe(
        method: str,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> bool:
        if bool(
            payload.get(
                "retry_safe",
                False,
            )
        ):
            return True

        if method.upper() in _SAFE_RETRY_METHODS:
            return True

        if OpenAPIAdapterPlugin._header_get(
            headers,
            "Idempotency-Key",
        ) or OpenAPIAdapterPlugin._header_get(
            headers,
            "X-Idempotency-Key",
        ):
            return True

        unsafe = payload.get("retry_unsafe_methods")

        if isinstance(
            unsafe,
            (list, tuple, set),
        ):
            return method.upper() not in {str(item).upper() for item in unsafe}

        return False

    async def _request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        cookies: dict[str, str],
        body: Any,
        content_type: str | None,
        retry_safe: bool,
    ) -> tuple[
        Any,
        int,
        dict[str, str],
        str,
    ]:
        method = method.upper()

        self._safe_url(url)

        async def _call():
            return await self._request_once(
                method=method,
                url=url,
                headers=headers,
                cookies=cookies,
                body=body,
                content_type=content_type,
            )

        if retry_safe:
            return await self.call_with_retry(
                _call,
                retry_codes=_RETRYABLE_STATUS_CODES,
            )

        return await _call()

    async def _request_once(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        cookies: dict[str, str],
        body: Any,
        content_type: str | None,
    ) -> tuple[
        Any,
        int,
        dict[str, str],
        str,
    ]:
        session = await self.get_session()

        request_headers = dict(headers)

        normalized_content_type = self._normalized_content_type(content_type)

        request_kwargs: dict[str, Any] = {
            "headers": request_headers,
            "cookies": cookies or None,
            "timeout": aiohttp.ClientTimeout(total=config.DEFAULT_ADAPTER_TIMEOUT),
            "allow_redirects": False,
        }

        if body is not None:
            if self._is_json_media_type(content_type):
                request_kwargs["json"] = body

            elif normalized_content_type == ("application/x-www-form-urlencoded"):
                request_kwargs["data"] = self._to_urlencoded_data(body)

            elif normalized_content_type == ("multipart/form-data"):
                request_headers.pop(
                    "Content-Type",
                    None,
                )

                request_kwargs["data"] = self._to_multipart_data(body)

            elif normalized_content_type.startswith("text/"):
                request_kwargs["data"] = (
                    body
                    if isinstance(
                        body,
                        str,
                    )
                    else json.dumps(
                        body,
                        ensure_ascii=False,
                        default=str,
                    )
                )

            elif isinstance(
                body,
                (bytes, bytearray, memoryview),
            ):
                request_kwargs["data"] = bytes(body)

            elif isinstance(
                body,
                str,
            ):
                request_kwargs["data"] = body

            else:
                request_kwargs["data"] = json.dumps(
                    body,
                    ensure_ascii=False,
                    default=str,
                )

        async with session.request(
            method,
            url,
            **request_kwargs,
        ) as response:
            response_headers = {str(key): str(value) for key, value in response.headers.items()}

            if 300 <= response.status < 400:
                location = response.headers.get("Location")

                if not location:
                    raise OpenAPIResolutionError(
                        f"HTTP redirect {response.status} without Location header"
                    )

                redirect_url = urljoin(
                    url,
                    location,
                )

                if not self._same_origin(
                    url,
                    redirect_url,
                ):
                    raise OpenAPIResolutionError(
                        "Cross-origin HTTP redirects are not permitted for OpenAPI requests"
                    )

                raise _OpenAPIRedirectError(
                    redirect_url,
                    status=response.status,
                )

            raw = await self._read_response_bytes(
                response,
                limit=_MAX_RESPONSE_BYTES,
            )

            response_text = raw.decode(
                "utf-8",
                errors="replace",
            )

            if response.status in _RETRYABLE_STATUS_CODES:
                raise self._response_error(
                    response.status,
                    response_text,
                    url,
                    response.headers,
                )

            parsed = self._decode_response(
                raw,
                response.headers.get(
                    "Content-Type",
                    "",
                ),
                response.status,
            )

            return (
                parsed,
                response.status,
                response_headers,
                response_text,
            )

    async def _request_with_same_origin_redirects(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        cookies: dict[str, str],
        body: Any,
        content_type: str | None,
        retry_safe: bool,
        max_redirects: int = 3,
    ) -> tuple[
        Any,
        int,
        dict[str, str],
        str,
    ]:
        current_url = url
        current_method = method
        current_headers = dict(headers)
        current_cookies = dict(cookies)
        current_body = body

        for _ in range(max_redirects + 1):
            try:
                return await self._request(
                    method=current_method,
                    url=current_url,
                    headers=current_headers,
                    cookies=current_cookies,
                    body=current_body,
                    content_type=content_type,
                    retry_safe=retry_safe,
                )
            except _OpenAPIRedirectError as redirect:
                next_url = redirect.url

                if not self._same_origin(
                    current_url,
                    next_url,
                ):
                    raise OpenAPIResolutionError("Cross-origin redirect rejected") from redirect

                if redirect.status in {
                    301,
                    302,
                    303,
                }:
                    current_method = "GET"
                    current_body = None

                    current_headers = {
                        key: value
                        for key, value in current_headers.items()
                        if key.lower()
                        not in {
                            "content-length",
                            "content-type",
                        }
                    }

                elif redirect.status in {
                    307,
                    308,
                }:
                    pass

                current_url = next_url

        raise OpenAPIResolutionError(f"HTTP redirect limit exceeded for {url}")

    @staticmethod
    async def _read_response_bytes(
        response: aiohttp.ClientResponse,
        *,
        limit: int,
    ) -> bytes:
        content_length = response.headers.get("Content-Length")

        if content_length:
            try:
                if int(content_length) > limit:
                    raise OpenAPIResolutionError(
                        f"HTTP response exceeds configured maximum size of {limit} bytes"
                    )
            except ValueError:
                pass

        return await OpenAPIAdapterPlugin._read_response_limited(
            response,
            limit=limit,
        )

    @staticmethod
    async def _read_response_limited(
        response: aiohttp.ClientResponse,
        *,
        limit: int,
    ) -> bytes:
        chunks: list[bytes] = []
        total = 0

        async for chunk in response.content.iter_chunked(64 * 1024):
            total += len(chunk)

            if total > limit:
                raise OpenAPIResolutionError(
                    f"HTTP response exceeds configured maximum size of {limit} bytes"
                )

            chunks.append(chunk)

        return b"".join(chunks)

    @staticmethod
    def _response_error(
        status: int,
        body: str,
        url: str,
        headers: Any = None,
    ) -> aiohttp.ClientResponseError:
        message = body[:_MAX_ERROR_BODY] if body else f"HTTP {status}"

        retry_after = None

        if headers:
            retry_after = headers.get("Retry-After")

        if retry_after:
            message = f"{message} (Retry-After: {retry_after})"

        request_info = None

        return aiohttp.ClientResponseError(
            request_info=request_info,
            history=(),
            status=status,
            message=message,
            headers=headers,
        )

    @staticmethod
    def _decode_response(
        raw: bytes,
        content_type: str,
        status: int,
    ) -> Any:
        if status == 204 or not raw:
            return {}

        text = raw.decode(
            "utf-8",
            errors="replace",
        )

        normalized = content_type.lower().split(";", 1)[0].strip()

        if "json" in normalized or normalized.endswith("+json"):
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise OpenAPIResolutionError(
                    "OpenAPI endpoint returned invalid JSON "
                    f"for content type {content_type!r}: {exc}"
                ) from exc

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    @staticmethod
    def _to_urlencoded_data(
        body: Any,
    ) -> Any:
        if isinstance(
            body,
            dict,
        ):
            return [
                (
                    str(key),
                    OpenAPIAdapterPlugin._serialize_scalar(value),
                )
                for key, value in body.items()
            ]

        if isinstance(
            body,
            (list, tuple),
        ):
            return [
                (
                    str(item[0]),
                    OpenAPIAdapterPlugin._serialize_scalar(item[1]),
                )
                for item in body
                if isinstance(
                    item,
                    (list, tuple),
                )
                and len(item) == 2
            ]

        if isinstance(
            body,
            str,
        ):
            return body

        return json.dumps(
            body,
            ensure_ascii=False,
            default=str,
        )

    @staticmethod
    def _to_multipart_data(
        body: Any,
    ) -> Any:
        from aiohttp import FormData

        form = FormData()

        if isinstance(
            body,
            dict,
        ):
            items = body.items()

        elif isinstance(
            body,
            list,
        ):
            items = (
                (
                    item.get("name"),
                    item,
                )
                for item in body
                if isinstance(
                    item,
                    dict,
                )
            )

        else:
            raise OpenAPIResolutionError("multipart/form-data body must be an object or list")

        for name, value in items:
            if name is None:
                continue

            if isinstance(
                value,
                dict,
            ):
                if "content" in value:
                    part = value.get("content")

                    filename = value.get("filename")

                    content_type = value.get("content_type") or value.get("media_type")

                    form.add_field(
                        str(name),
                        part,
                        filename=filename,
                        content_type=content_type,
                    )
                elif "value" in value:
                    form.add_field(
                        str(name),
                        value["value"],
                    )
                else:
                    form.add_field(
                        str(name),
                        json.dumps(
                            value,
                            ensure_ascii=False,
                        ),
                        content_type="application/json",
                    )
            else:
                form.add_field(
                    str(name),
                    value,
                )

        return form

    # -------------------------------------------------------------------------
    # Response normalization
    # -------------------------------------------------------------------------

    async def _build_result(
        self,
        *,
        response_json: Any,
        response_text: str,
        status_code: int,
        response_headers: dict[str, str],
        overrides: dict[str, str] | None,
        operation: dict[str, Any] | None,
        spec: dict[str, Any] | None,
        spec_url: str | None,
        request_url: str,
        request_method: str,
    ) -> dict[str, Any]:
        if isinstance(
            response_json,
            dict,
        ):
            action = self._classify_mapping(
                response_json,
                status_code,
                overrides,
            )

            content = self._extract_content(response_json)

        else:
            if status_code >= 400:
                action = "error"
            else:
                action = DualNormalizationHub.normalize_text(str(response_json or response_text))

            content = str(
                response_json
                if response_json
                not in (
                    {},
                    None,
                )
                else response_text
            )[:_MAX_CONTENT_PREVIEW]

        response_meta: dict[str, Any] = {
            "framework": "openapi",
            "status_code": status_code,
            "url": request_url,
            "method": request_method,
            "content_type": response_headers.get("Content-Type"),
            "response_headers": response_headers,
            "raw_response": response_json,
        }

        if spec_url:
            response_meta["spec_url"] = spec_url

        if operation:
            operation_id = operation.get("operationId")

            if operation_id:
                response_meta["operation_id"] = operation_id

            if operation.get("summary"):
                response_meta["operation_summary"] = operation.get("summary")

            if operation.get("description"):
                response_meta["operation_description"] = operation.get("description")

        return {
            "status": ("error" if status_code >= 400 or action == "error" else "success"),
            "action": action,
            "content": content,
            "metadata": response_meta,
        }

    @staticmethod
    def _extract_content(
        response: dict[str, Any],
    ) -> str:
        for key in (
            "content",
            "output",
            "message",
            "decision_reason",
            "result",
            "detail",
            "error",
        ):
            if key not in response:
                continue

            value = response[key]

            if isinstance(
                value,
                str,
            ):
                return value[:_MAX_CONTENT_PREVIEW]

            return json.dumps(
                value,
                ensure_ascii=False,
                default=str,
            )[:_MAX_CONTENT_PREVIEW]

        return json.dumps(
            response,
            ensure_ascii=False,
            default=str,
        )[:_MAX_CONTENT_PREVIEW]

    @staticmethod
    def _classify_mapping(
        response: dict[str, Any],
        status_code: int,
        overrides: dict[str, str] | None,
    ) -> str:
        if status_code >= 400:
            return "error"

        if status_code == 202:
            return "processing"

        for key in (
            "status",
            "state",
            "phase",
            "outcome",
            "decision",
            "result",
        ):
            value = response.get(key)

            if (
                value is not None
                and not isinstance(value, (dict, list, set, tuple))
                and str(value).strip().lower() in _PROCESSING_VALUES
            ):
                return "processing"

        return DualNormalizationHub.normalize(
            response,
            status_code,
            overrides,
        )

    # -------------------------------------------------------------------------
    # Asynchronous operation / polling
    # -------------------------------------------------------------------------

    async def _resolve_poll_target(
        self,
        *,
        response_json: Any,
        response_headers: dict[str, str],
        operation: dict[str, Any] | None,
        spec: dict[str, Any] | None,
        spec_url: str | None,
        request_url: str,
        request_method: str,
    ) -> dict[str, Any] | None:
        location = self._header_get(
            response_headers,
            "Location",
        )

        if location:
            return {
                "url": urljoin(
                    request_url,
                    location,
                ),
                "method": "GET",
                "initial_delay": self._parse_retry_after(
                    self._header_get(
                        response_headers,
                        "Retry-After",
                    ),
                    fallback=0.0,
                ),
            }

        if isinstance(
            response_json,
            dict,
        ):
            href_info = self._find_hateoas_link(response_json)

            if href_info:
                href, link_method = href_info

                return {
                    "url": urljoin(
                        request_url,
                        href,
                    ),
                    "method": (link_method or "GET"),
                    "initial_delay": self._parse_retry_after(
                        self._header_get(
                            response_headers,
                            "Retry-After",
                        ),
                        fallback=0.0,
                    ),
                }

        if spec and operation:
            response_links = await self._get_response_links(
                operation,
                spec,
                spec_url,
                status_code=202,
            )

            for link in response_links:
                try:
                    target = await self._resolve_link_target(
                        link,
                        spec=spec,
                        spec_url=spec_url,
                        request_url=request_url,
                        request_method=request_method,
                        response_json=response_json,
                        response_headers=response_headers,
                    )

                    if target:
                        return target

                except Exception as exc:
                    logger.debug(
                        "OpenAPI response link resolution failed: %s",
                        exc,
                    )

        if isinstance(
            response_json,
            dict,
        ):
            for key in (
                "status_url",
                "poll_url",
                "result_url",
                "monitor_url",
                "operation_url",
            ):
                value = response_json.get(key)

                if (
                    isinstance(
                        value,
                        str,
                    )
                    and value
                ):
                    return {
                        "url": urljoin(
                            request_url,
                            value,
                        ),
                        "method": "GET",
                        "initial_delay": self._parse_retry_after(
                            self._header_get(
                                response_headers,
                                "Retry-After",
                            ),
                            fallback=0.0,
                        ),
                    }

        return None

    @staticmethod
    def _find_hateoas_link(
        response: dict[str, Any],
    ) -> (
        tuple[
            str,
            str | None,
        ]
        | None
    ):
        links = response.get("_links") or response.get("links")

        if not isinstance(
            links,
            dict,
        ):
            return None

        for key in (
            "status",
            "poll",
            "operation",
            "result",
            "self",
        ):
            item = links.get(key)

            if isinstance(
                item,
                str,
            ):
                return (
                    item,
                    None,
                )

            if isinstance(
                item,
                dict,
            ):
                href = item.get("href")

                if isinstance(
                    href,
                    str,
                ):
                    method = item.get("method")

                    return (
                        href,
                        str(method).upper() if method else None,
                    )

        return None

    async def _get_response_links(
        self,
        operation: dict[str, Any],
        spec: dict[str, Any],
        spec_url: str | None,
        *,
        status_code: int,
    ) -> list[dict[str, Any]]:
        responses = operation.get("responses") or {}

        if not isinstance(
            responses,
            dict,
        ):
            return []

        status = str(status_code)

        candidates = [
            status,
            "default",
            "202",
            "200",
            "201",
        ]

        raw_response = None

        for candidate in candidates:
            if candidate in responses:
                raw_response = responses[candidate]
                break

        if raw_response is None:
            return []

        raw_response = await self._resolve_ref(
            raw_response,
            document=spec,
            document_url=spec_url,
        )

        if not isinstance(
            raw_response,
            dict,
        ):
            return []

        links = raw_response.get("links")

        if not isinstance(
            links,
            dict,
        ):
            return []

        result: list[dict[str, Any]] = []

        for value in links.values():
            resolved = await self._resolve_ref(
                value,
                document=spec,
                document_url=spec_url,
            )

            if isinstance(
                resolved,
                dict,
            ):
                result.append(resolved)

        return result

    async def _resolve_link_target(
        self,
        link: dict[str, Any],
        *,
        spec: dict[str, Any],
        spec_url: str | None,
        request_url: str,
        request_method: str,
        response_json: Any,
        response_headers: dict[str, str],
    ) -> dict[str, Any] | None:
        found = None

        if link.get("operationId"):
            found = await self._find_operation_by_id(
                spec,
                str(link["operationId"]),
                spec_url,
            )

            if not found:
                raise OpenAPIResolutionError(
                    f"Linked operationId {link['operationId']!r} not found"
                )

            (
                operation,
                path_item,
                path_template,
                method,
            ) = found

        elif link.get("operationRef"):
            (
                operation,
                path_template,
                method,
                path_item,
            ) = await self._resolve_operation_ref(
                spec,
                str(link["operationRef"]),
                document_url=spec_url,
            )

        else:
            return None

        server_url = await self._resolve_server(
            spec=spec,
            path_item=path_item,
            operation=operation,
            document_url=spec_url,
            payload={},
            endpoint=request_url,
        )

        linked_payload: dict[str, Any] = {
            "path_params": {},
            "query_params": {},
            "header_params": {},
            "cookie_params": {},
        }

        for key, expression in (link.get("parameters") or {}).items():
            value = self._evaluate_runtime_expression(
                expression,
                response_body=response_json,
                request_url=request_url,
                request_method=request_method,
                response_headers=response_headers,
            )

            if value is None:
                continue

            key_text = str(key)

            if "." in key_text:
                location, name = key_text.split(
                    ".",
                    1,
                )
            else:
                location, name = (
                    "query",
                    key_text,
                )

            destination = {
                "path": linked_payload["path_params"],
                "query": linked_payload["query_params"],
                "header": linked_payload["header_params"],
                "cookie": linked_payload["cookie_params"],
            }.get(location)

            if destination is None:
                raise OpenAPIResolutionError(
                    f"Unsupported OpenAPI response-link parameter location: {location}"
                )

            destination[name] = value

        if "requestBody" in link:
            linked_payload["input_payload"] = self._evaluate_runtime_expression(
                link["requestBody"],
                response_body=response_json,
                request_url=request_url,
                request_method=request_method,
                response_headers=response_headers,
            )

        endpoint_for_link = urljoin(
            server_url.rstrip("/") + "/",
            path_template.lstrip("/"),
        )

        (
            target_url,
            target_method,
            headers,
            cookies,
            body,
            content_type,
        ) = await self._build_request(
            spec=spec,
            document_url=spec_url,
            path_item=path_item,
            operation=operation,
            path_template=path_template,
            method=method,
            endpoint=endpoint_for_link,
            payload=linked_payload,
        )

        link_headers, link_query, link_cookies = await self._get_auth_context(
            linked_payload,
            spec=spec,
            operation=operation,
            path_item=path_item,
            document_url=spec_url,
        )

        headers.update(link_headers)

        cookies.update(link_cookies)

        if link_query:
            parsed = urlparse(target_url)

            existing = parse_qsl(
                parsed.query,
                keep_blank_values=True,
            )

            target_url = urlunparse(
                parsed._replace(
                    query=urlencode(
                        existing + list(link_query.items()),
                        doseq=True,
                    )
                )
            )

        return {
            "url": target_url,
            "method": target_method,
            "operation": operation,
            "spec": spec,
            "spec_url": spec_url,
            "headers": headers,
            "cookies": cookies,
            "body": body,
            "content_type": content_type,
            "initial_delay": 0.0,
        }

    @staticmethod
    def _evaluate_runtime_expression(
        expression: Any,
        *,
        response_body: Any,
        request_url: str,
        request_method: str,
        response_headers: dict[str, str],
    ) -> Any:
        if not isinstance(
            expression,
            str,
        ):
            return expression

        if not expression.startswith("$"):
            return expression

        lowered = expression.lower()

        if lowered == "$url":
            return request_url

        if lowered == "$method":
            return request_method

        if expression.startswith("$response.header."):
            header_name = expression[len("$response.header.") :]

            for key, value in response_headers.items():
                if key.lower() == header_name.lower():
                    return value

            return None

        if expression.startswith("$response.body#/"):
            pointer = expression[len("$response.body") :]

            try:
                return OpenAPIAdapterPlugin._json_pointer_get(
                    response_body,
                    pointer,
                )
            except Exception:
                return None

        if expression == "$response.body":
            return response_body

        return None

    async def _poll_for_result(
        self,
        poll_url: str,
        overrides: dict[str, str] | None,
        headers: dict[str, str] | None = None,
        *,
        method: str = "GET",
        operation: dict[str, Any] | None = None,
        spec: dict[str, Any] | None = None,
        spec_url: str | None = None,
        initial_body: Any = None,
        cookies: dict[str, str] | None = None,
        initial_delay: float = 0.0,
    ) -> dict[str, Any]:
        current_url = self._safe_url(poll_url)
        current_method = method.upper()
        request_headers = dict(headers or {})
        request_cookies = dict(cookies or {})
        body = initial_body

        interval = max(
            0.0,
            initial_delay,
        )

        started = time.monotonic()
        attempts = 0

        while (
            attempts < self.max_poll_attempts
            and time.monotonic() - started < self.max_poll_duration
        ):
            if interval > 0:
                await asyncio.sleep(interval)

            attempts += 1

            try:
                polling_content_type = (
                    request_headers.get("Content-Type") if body is not None else None
                )

                (
                    response_json,
                    status_code,
                    response_headers,
                    response_text,
                ) = await self._request(
                    method=current_method,
                    url=current_url,
                    headers=request_headers,
                    cookies=request_cookies,
                    body=body,
                    content_type=polling_content_type,
                    retry_safe=current_method in _SAFE_RETRY_METHODS,
                )

                if isinstance(
                    response_json,
                    dict,
                ):
                    action = self._classify_mapping(
                        response_json,
                        status_code,
                        overrides,
                    )

                    content = self._extract_content(response_json)
                else:
                    action = (
                        "error"
                        if status_code >= 400
                        else DualNormalizationHub.normalize_text(
                            str(response_json or response_text)
                        )
                    )

                    content = str(
                        response_json
                        if response_json
                        not in (
                            {},
                            None,
                        )
                        else response_text
                    )[:_MAX_CONTENT_PREVIEW]

                next_interval = self._parse_retry_after(
                    self._header_get(
                        response_headers,
                        "Retry-After",
                    ),
                    fallback=self.poll_interval,
                )

                if (
                    action
                    in {
                        "hitl_pause",
                        "final_answer",
                        "error",
                    }
                    or status_code >= 400
                ):
                    return {
                        "status": (
                            "success" if action != "error" and status_code < 400 else "error"
                        ),
                        "action": action,
                        "content": content,
                        "metadata": {
                            "framework": "openapi",
                            "attempts": attempts,
                            "status_code": status_code,
                            "raw_response": response_json,
                            "response_headers": response_headers,
                            "poll_url": current_url,
                        },
                    }

                if response_headers.get("Location"):
                    next_url = urljoin(
                        current_url,
                        response_headers["Location"],
                    )

                    if not self._same_origin(
                        current_url,
                        next_url,
                    ):
                        raise OpenAPIResolutionError("Cross-origin polling redirect rejected")

                    current_url = next_url
                    current_method = "GET"
                    body = None

                elif isinstance(
                    response_json,
                    dict,
                ):
                    href_info = self._find_hateoas_link(response_json)

                    if href_info:
                        href, href_method = href_info

                        next_url = urljoin(
                            current_url,
                            href,
                        )

                        if not self._same_origin(
                            current_url,
                            next_url,
                        ):
                            raise OpenAPIResolutionError(
                                "Cross-origin HATEOAS polling target rejected"
                            )

                        current_url = next_url
                        current_method = href_method or "GET"
                        body = None

                if action != "processing":
                    return {
                        "status": "success",
                        "action": action,
                        "content": content,
                        "metadata": {
                            "framework": "openapi",
                            "attempts": attempts,
                            "status_code": status_code,
                            "raw_response": response_json,
                            "response_headers": response_headers,
                            "poll_url": current_url,
                        },
                    }

                interval = max(
                    0.0,
                    next_interval,
                )

            except _OpenAPIRedirectError as redirect:
                if not self._same_origin(
                    current_url,
                    redirect.url,
                ):
                    return {
                        "status": "error",
                        "action": "error",
                        "content": ("Cross-origin polling redirect rejected"),
                        "metadata": {
                            "framework": "openapi",
                            "attempts": attempts,
                            "poll_url": current_url,
                        },
                    }

                current_url = redirect.url
                current_method = (
                    "GET"
                    if redirect.status
                    in {
                        301,
                        302,
                        303,
                    }
                    else current_method
                )

                if current_method == "GET":
                    body = None

            except Exception as exc:
                logger.debug(
                    "OpenAPI polling attempt %d failed: %s",
                    attempts,
                    exc,
                )

                if attempts >= self.max_poll_attempts:
                    return {
                        "status": "error",
                        "action": "error",
                        "content": (f"Polling failed after {attempts} attempts: {exc}"),
                        "metadata": {
                            "framework": "openapi",
                            "attempts": attempts,
                            "poll_url": current_url,
                        },
                    }

                interval = self.poll_interval

        return {
            "status": "error",
            "action": "error",
            "content": "Polling timeout exceeded.",
            "metadata": {
                "framework": "openapi",
                "attempts": attempts,
                "poll_url": current_url,
                "max_poll_attempts": self.max_poll_attempts,
                "max_poll_duration": self.max_poll_duration,
            },
        }

    @staticmethod
    def _parse_retry_after(
        value: str | None,
        *,
        fallback: float,
    ) -> float:
        if not value:
            return max(
                0.0,
                fallback,
            )

        try:
            return max(
                0.0,
                float(value),
            )
        except (TypeError, ValueError):
            pass

        try:
            parsed = parsedate_to_datetime(value)

            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)

            delay = (parsed.astimezone(UTC) - datetime.now(UTC)).total_seconds()

            return max(
                0.0,
                delay,
            )

        except (TypeError, ValueError, OverflowError):
            return max(
                0.0,
                fallback,
            )


class _OpenAPIRedirectError(RuntimeError):
    def __init__(
        self,
        url: str,
        *,
        status: int,
    ):
        super().__init__(f"HTTP redirect {status}: {url}")
        self.url = url
        self.status = status


async def adapter(
    payload: dict[str, Any],
    endpoint: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Compatibility wrapper for the legacy adapter discovery contract."""
    plugin = OpenAPIAdapterPlugin()

    return await plugin.execute_openapi_query(
        payload,
        endpoint,
        **kwargs,
    )
