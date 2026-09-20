from __future__ import annotations

import asyncio
import base64
import copy
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlparse, urlunparse

import aiohttp

from .. import config
from ..plugins import BaseEvalPlugin
from .common import BaseAdapter, DualNormalizationHub, SessionManager

logger = logging.getLogger(__name__)

_HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}

_CONTROL_KEYS = {
    "url",
    "endpoint",
    "spec_url",
    "openapi_spec",
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
    "headers",
    "cookies",
    "auth",
    "metadata",
    "input_payload",
    "body",
    "request_body",
    "poll_interval",
    "max_poll_attempts",
    "overrides",
}

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


class OpenAPIResolutionError(ValueError):
    """Raised when an OpenAPI description cannot be resolved to an executable operation."""


class OpenAPIAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Specification-driven OpenAPI 3.0/3.1 adapter.

    Capabilities:
      - OpenAPI JSON/YAML discovery and explicit spec URLs.
      - OpenAPI 3.0/3.1 path/operation resolution.
      - operationId / operationRef resolution.
      - server URL and server-variable resolution.
      - path/query/header/cookie parameter serialization.
      - JSON, form, multipart, text and binary request bodies.
      - apiKey, HTTP bearer/basic and OAuth2 client-credentials security.
      - OAuth2 token caching.
      - structured response parsing.
      - standards-based response links and HATEOAS polling.
      - Location/202 asynchronous polling.
      - connection pooling and transient retry handling.
      - backwards-compatible adapter() entry point.
    """

    def __init__(self):
        BaseAdapter.__init__(self, name="openapi")
        self.max_poll_attempts = int(os.getenv("OPENAPI_MAX_POLL_ATTEMPTS", "150"))
        self.poll_interval = float(os.getenv("OPENAPI_POLL_INTERVAL", "2.0"))
        self._spec_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._document_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._oauth_cache: dict[tuple[str, str, str, str], tuple[float, str]] = {}
        self._cache_ttl = float(os.getenv("OPENAPI_SPEC_CACHE_TTL", "300"))

    def on_discover_adapters(self, registry: Any):
        registry.register("openapi", self.execute_openapi_query)

    # -------------------------------------------------------------------------
    # OpenAPI document loading / validation
    # -------------------------------------------------------------------------

    async def _fetch_document(self, source: str, *, explicit: bool = False) -> dict[str, Any]:
        """Load an OpenAPI JSON/YAML document from HTTP(S) or a local file."""
        cached = self._document_cache.get(source)
        if cached and time.monotonic() - cached[0] < self._cache_ttl:
            return copy.deepcopy(cached[1])

        parsed = urlparse(source)

        if parsed.scheme in {"http", "https"}:
            session = await SessionManager.get_session()
            try:
                async with session.get(
                    source,
                    headers={
                        "Accept": (
                            "application/json, application/yaml, text/yaml, text/x-yaml, */*"
                        )
                    },
                    timeout=aiohttp.ClientTimeout(total=config.DEFAULT_ADAPTER_TIMEOUT),
                ) as response:
                    if response.status >= 400:
                        if explicit:
                            body = await response.text()
                            raise OpenAPIResolutionError(
                                f"OpenAPI specification fetch failed: "
                                f"HTTP {response.status}: {body[:500]}"
                            )
                        raise FileNotFoundError(source)

                    raw = await response.read()
                    content_type = response.headers.get("Content-Type", "").lower()

            except OpenAPIResolutionError:
                raise
            except Exception as exc:
                if explicit:
                    raise OpenAPIResolutionError(
                        f"OpenAPI specification fetch failed for {source}: {exc}"
                    ) from exc
                raise

            document = self._parse_document(raw, source, content_type)

        elif parsed.scheme in {"", "file"}:
            path = Path(parsed.path if parsed.scheme == "file" else source).expanduser().resolve()

            if not path.exists():
                raise FileNotFoundError(path)

            raw = path.read_bytes()
            document = self._parse_document(raw, str(path), "")

        else:
            raise OpenAPIResolutionError(
                f"Unsupported OpenAPI specification URI scheme: {parsed.scheme}"
            )

        self._validate_document(document, source)
        self._document_cache[source] = (time.monotonic(), copy.deepcopy(document))
        return document

    @staticmethod
    def _parse_document(raw: bytes, source: str, content_type: str) -> dict[str, Any]:
        text = raw.decode("utf-8-sig")

        looks_yaml = (
            "yaml" in content_type
            or source.lower().endswith((".yaml", ".yml"))
            or text.lstrip().startswith(("openapi:", "swagger:"))
        )

        try:
            if not looks_yaml:
                document = json.loads(text)
            else:
                import yaml

                document = yaml.safe_load(text)
        except Exception as exc:
            raise OpenAPIResolutionError(f"Invalid OpenAPI document at {source}: {exc}") from exc

        if not isinstance(document, dict):
            raise OpenAPIResolutionError(f"OpenAPI document at {source} must be an object")

        return document

    @staticmethod
    def _validate_document(document: dict[str, Any], source: str) -> None:
        version = str(document.get("openapi", ""))

        if not version.startswith("3."):
            raise OpenAPIResolutionError(
                f"Unsupported OpenAPI version {version!r} in {source}; OpenAPI 3.0/3.1 is required"
            )

        if not isinstance(document.get("paths"), dict):
            raise OpenAPIResolutionError(f"OpenAPI document {source} has no usable paths object")

    async def _load_spec(
        self,
        endpoint: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str | None]:
        """
        Resolve the OpenAPI description.

        Resolution order:
          1. Inline payload.openapi_spec.
          2. Explicit spec_url/openapi_spec_url.
          3. OPENAPI_SPEC_URL.
          4. Standard service-origin discovery:
             /openapi.json
             /openapi.yaml
             /openapi.yml
        """
        inline_spec = payload.get("openapi_spec")
        if isinstance(inline_spec, dict):
            spec = copy.deepcopy(inline_spec)
            self._validate_document(spec, "payload.openapi_spec")
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
            spec_url = self._resolve_reference_url(str(explicit_spec), endpoint)
            try:
                return await self._fetch_document(spec_url, explicit=True), spec_url
            except Exception as exc:
                raise OpenAPIResolutionError(str(exc)) from exc

        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"}:
            return None, None

        origin = f"{parsed.scheme}://{parsed.netloc}"
        candidates = [
            f"{origin}/openapi.json",
            f"{origin}/openapi.yaml",
            f"{origin}/openapi.yml",
        ]

        for candidate in candidates:
            try:
                return await self._fetch_document(candidate), candidate
            except Exception:
                continue

        return None, None

    @staticmethod
    def _resolve_reference_url(ref: str, base_url: str | None) -> str:
        if base_url and not urlparse(ref).scheme:
            return urljoin(base_url, ref)
        return ref

    async def _resolve_ref(
        self,
        value: Any,
        *,
        document: dict[str, Any],
        document_url: str | None,
    ) -> Any:
        """Resolve local or external OpenAPI $ref objects."""
        if not isinstance(value, dict) or "$ref" not in value:
            return value

        ref = str(value["$ref"])

        if ref.startswith("#/"):
            target: Any = document

            for token in ref[2:].split("/"):
                token = token.replace("~1", "/").replace("~0", "~")

                if not isinstance(target, dict) or token not in target:
                    raise OpenAPIResolutionError(f"Unresolvable OpenAPI reference: {ref}")

                target = target[token]

            return copy.deepcopy(target)

        if not document_url:
            raise OpenAPIResolutionError(
                f"External OpenAPI reference requires a document URL: {ref}"
            )

        target_url = urljoin(document_url, ref)
        parsed = urlparse(target_url)
        fragment = parsed.fragment
        document_source = urlunparse(parsed._replace(fragment=""))

        external = await self._fetch_document(document_source, explicit=True)

        if not fragment:
            return external

        if not fragment.startswith("/"):
            raise OpenAPIResolutionError(
                f"Unsupported external OpenAPI reference fragment: #{fragment}"
            )

        target: Any = external

        for token in fragment[1:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")

            if not isinstance(target, dict) or token not in target:
                raise OpenAPIResolutionError(f"Unresolvable OpenAPI reference: {ref}")

            target = target[token]

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
        servers = operation.get("servers") or path_item.get("servers") or spec.get("servers") or []

        if not servers:
            parsed = urlparse(endpoint)

            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"

            return endpoint.rstrip("/")

        server = servers[0]
        server = await self._resolve_ref(
            server,
            document=spec,
            document_url=document_url,
        )

        server_url = str(server.get("url", ""))

        metadata = payload.get("metadata") or {}
        variables = payload.get("server_variables") or metadata.get("server_variables") or {}

        for name, definition in (server.get("variables") or {}).items():
            value = variables.get(name, definition.get("default"))

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
                quote(str(value), safe=""),
            )

        if document_url and not urlparse(server_url).scheme:
            server_url = urljoin(document_url, server_url)

        return server_url.rstrip("/")

    async def _find_operation(
        self,
        spec: dict[str, Any],
        document_url: str | None,
        endpoint: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], str, str] | None:
        metadata = payload.get("metadata") or {}
        openapi_meta = metadata.get("openapi") if isinstance(metadata.get("openapi"), dict) else {}

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
            operation, path, method, path_item = await self._resolve_operation_ref(
                spec,
                str(operation_ref),
                document_url=document_url,
            )
            return operation, path_item, path, method

        operations: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []

        for path, raw_item in spec.get("paths", {}).items():
            if not isinstance(raw_item, dict):
                continue

            path_item = await self._resolve_ref(
                raw_item,
                document=spec,
                document_url=document_url,
            )

            if not isinstance(path_item, dict):
                continue

            for method, raw_operation in path_item.items():
                if method.lower() not in _HTTP_METHODS:
                    continue

                operation = await self._resolve_ref(
                    raw_operation,
                    document=spec,
                    document_url=document_url,
                )

                if not isinstance(operation, dict):
                    continue

                operations.append((path, method.lower(), operation, path_item))

        if operation_id:
            matches = [row for row in operations if row[2].get("operationId") == operation_id]

            if len(matches) != 1:
                raise OpenAPIResolutionError(
                    f"OpenAPI operationId {operation_id!r} resolved to {len(matches)} operations"
                )

            path, method, operation, path_item = matches[0]
            return operation, path_item, path, method

        endpoint_path = urlparse(endpoint).path or "/"

        if requested_path:
            requested_path = "/" + str(requested_path).lstrip("/")
            path_matches = [row for row in operations if row[0] == requested_path]
        else:
            path_matches = [
                row for row in operations if self._path_matches_template(row[0], endpoint_path)
            ]

            if not path_matches:
                path_matches = self._match_against_server_relative_path(
                    spec=spec,
                    operations=operations,
                    endpoint_path=endpoint_path,
                )

        if requested_method:
            path_matches = [row for row in path_matches if row[1] == requested_method]

        if len(path_matches) == 1:
            path, method, operation, path_item = path_matches[0]
            return operation, path_item, path, method

        if not requested_path and not requested_method and len(path_matches) > 1:
            exact = [row for row in path_matches if row[0] == endpoint_path]

            if len(exact) == 1:
                path, method, operation, path_item = exact[0]
                return operation, path_item, path, method

        if not requested_path and not requested_method and len(operations) == 1:
            path, method, operation, path_item = operations[0]
            return operation, path_item, path, method

        if requested_path or requested_method:
            raise OpenAPIResolutionError(
                "OpenAPI operation could not be uniquely resolved from the supplied path/method"
            )

        return None

    async def _match_against_server_relative_path(
        self,
        *,
        spec: dict[str, Any],
        operations: list[tuple[str, str, dict[str, Any], dict[str, Any]]],
        endpoint_path: str,
    ) -> list[tuple[str, str, dict[str, Any], dict[str, Any]]]:
        """
        Match /server-prefix/resource against the path portion described in OAS.

        This is only path-base normalization. It does not invent operations.
        """
        server_prefixes: set[str] = {""}

        for raw_server in spec.get("servers") or []:
            try:
                server = await self._resolve_ref(
                    raw_server,
                    document=spec,
                    document_url=None,
                )
            except Exception:
                continue

            if not isinstance(server, dict):
                continue

            raw_url = str(server.get("url", ""))
            parsed = urlparse(raw_url)

            if parsed.path:
                server_prefixes.add(parsed.path.rstrip("/"))

        candidates = []

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
                if self._path_matches_template(row[0], relative):
                    candidates.append(row)

        return candidates

    async def _resolve_operation_ref(
        self,
        spec: dict[str, Any],
        ref: str,
        *,
        document_url: str | None,
    ) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
        if ref.startswith("#/"):
            target: Any = spec
            tokens = ref[2:].split("/")

            for token in tokens:
                token = token.replace("~1", "/").replace("~0", "~")

                if not isinstance(target, dict) or token not in target:
                    raise OpenAPIResolutionError(f"Unresolvable operationRef: {ref}")

                target = target[token]

            if len(tokens) < 3 or tokens[0] != "paths":
                raise OpenAPIResolutionError(f"operationRef must identify an operation: {ref}")

            path = "/" + "/".join(tokens[1:-1]).replace("~1", "/").replace("~0", "~")

            method = tokens[-1].lower()
            path_item = spec["paths"][path]

            path_item = await self._resolve_ref(
                path_item,
                document=spec,
                document_url=document_url,
            )

            return target, path, method, path_item

        target_url = self._resolve_reference_url(ref, document_url)
        parsed = urlparse(target_url)
        fragment = parsed.fragment
        source = urlunparse(parsed._replace(fragment=""))

        external = await self._fetch_document(
            source,
            explicit=True,
        )

        if not fragment:
            raise OpenAPIResolutionError(f"operationRef must identify an operation object: {ref}")

        target: Any = external
        tokens = fragment.lstrip("/").split("/")

        for token in tokens:
            token = token.replace("~1", "/").replace("~0", "~")

            if not isinstance(target, dict) or token not in target:
                raise OpenAPIResolutionError(f"Unresolvable operationRef: {ref}")

            target = target[token]

        if len(tokens) < 3 or tokens[0] != "paths":
            raise OpenAPIResolutionError(f"operationRef must identify an operation: {ref}")

        path = "/" + "/".join(tokens[1:-1])
        method = tokens[-1].lower()

        path_item = await self._resolve_ref(
            external["paths"][path],
            document=external,
            document_url=source,
        )

        return target, path, method, path_item

    async def _find_operation_by_id(
        self,
        spec: dict[str, Any],
        operation_id: str,
        spec_url: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any], str, str] | None:
        for path, raw_item in spec.get("paths", {}).items():
            path_item = await self._resolve_ref(
                raw_item,
                document=spec,
                document_url=spec_url,
            )

            if not isinstance(path_item, dict):
                continue

            for method, raw_operation in path_item.items():
                if method.lower() not in _HTTP_METHODS:
                    continue

                operation = await self._resolve_ref(
                    raw_operation,
                    document=spec,
                    document_url=spec_url,
                )

                if isinstance(operation, dict) and operation.get("operationId") == operation_id:
                    return operation, path_item, path, method.lower()

        return None

    @staticmethod
    def _path_matches_template(template: str, actual: str) -> bool:
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
    # Parameters / request construction
    # -------------------------------------------------------------------------

    async def _collect_parameters(
        self,
        spec: dict[str, Any],
        document_url: str | None,
        path_item: dict[str, Any],
        operation: dict[str, Any],
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        merged: dict[tuple[str, str], dict[str, Any]] = {}

        for raw in (path_item.get("parameters") or []) + (operation.get("parameters") or []):
            parameter = await self._resolve_ref(
                raw,
                document=spec,
                document_url=document_url,
            )

            if not isinstance(parameter, dict):
                continue

            name = str(parameter.get("name", ""))
            location = str(parameter.get("in", ""))

            if name and location:
                merged[(name, location)] = parameter

        return list(merged.values())

    @staticmethod
    def _lookup_parameter(
        payload: dict[str, Any],
        parameter: dict[str, Any],
    ) -> tuple[bool, Any]:
        name = str(parameter["name"])
        location = str(parameter["in"])

        by_location = payload.get(f"{location}_params")
        if isinstance(by_location, dict) and name in by_location:
            return True, by_location[name]

        params = payload.get("parameters")

        if isinstance(params, dict):
            for key in (f"{location}.{name}", name):
                if key in params:
                    return True, params[key]

        direct = payload.get(name)

        if direct is not None:
            return True, direct

        return False, None

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
        if not operation or not spec or not path_item or not path_template:
            body = self._body_from_payload(payload)

            headers = dict(payload.get("headers") or payload.get("header_params") or {})

            cookies = dict(payload.get("cookies") or payload.get("cookie_params") or {})

            headers = {str(key): str(value) for key, value in headers.items()}

            cookies = {str(key): str(value) for key, value in cookies.items()}

            return (
                endpoint,
                method.upper(),
                headers,
                cookies,
                body,
                payload.get("content_type"),
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
            payload,
        )

        query: list[tuple[str, str]] = []

        headers = {str(key): str(value) for key, value in (payload.get("headers") or {}).items()}

        header_params = payload.get("header_params") or {}
        if isinstance(header_params, dict):
            headers.update({str(key): str(value) for key, value in header_params.items()})

        cookies = {str(key): str(value) for key, value in (payload.get("cookies") or {}).items()}

        cookie_params = payload.get("cookie_params") or {}
        if isinstance(cookie_params, dict):
            cookies.update({str(key): str(value) for key, value in cookie_params.items()})

        for parameter in parameters:
            found, value = self._lookup_parameter(
                payload,
                parameter,
            )

            if not found:
                if parameter.get("required"):
                    raise OpenAPIResolutionError(
                        f"Missing required OpenAPI parameter {parameter['in']}.{parameter['name']}"
                    )
                continue

            location = parameter["in"]
            name = parameter["name"]

            if location == "path":
                target_url = target_url.replace(
                    "{" + name + "}",
                    quote(str(value), safe=""),
                )

            elif location == "query":
                query.extend(
                    self._serialize_query_parameter(
                        parameter,
                        value,
                    )
                )

            elif location == "header":
                headers[name] = self._serialize_scalar(value)

            elif location == "cookie":
                cookies[name] = self._serialize_scalar(value)

            else:
                raise OpenAPIResolutionError(f"Unsupported OpenAPI parameter location: {location}")

        parsed = urlparse(target_url)
        existing_query = parse_qsl(
            parsed.query,
            keep_blank_values=True,
        )

        target_url = urlunparse(
            parsed._replace(
                query=urlencode(
                    existing_query + query,
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

        if request_body:
            content = request_body.get("content") or {}

            if not content:
                if request_body.get("required") and body is None:
                    raise OpenAPIResolutionError("OpenAPI operation requires a request body")
            else:
                media_type = self._select_media_type(
                    content,
                    content_type,
                )

                if media_type:
                    content_type = media_type

                    if body is None and request_body.get("required"):
                        raise OpenAPIResolutionError("OpenAPI operation requires a request body")

                    if media_type != "multipart/form-data":
                        headers.setdefault(
                            "Content-Type",
                            media_type,
                        )

        elif body is not None and content_type:
            headers.setdefault(
                "Content-Type",
                content_type,
            )

        return (
            target_url,
            method.upper(),
            headers,
            cookies,
            body,
            content_type,
        )

    @staticmethod
    def _body_from_payload(payload: dict[str, Any]) -> Any:
        if "input_payload" in payload:
            return payload["input_payload"]

        if "request_body" in payload:
            return payload["request_body"]

        if "body" in payload:
            return payload["body"]

        data = {key: value for key, value in payload.items() if key not in _CONTROL_KEYS}

        return data if data else None

    @staticmethod
    def _select_media_type(
        content: dict[str, Any],
        requested: str | None,
    ) -> str | None:
        if requested:
            if requested in content:
                return requested

            req_main = requested.split("/", 1)[0]

            for media_type in content:
                if media_type == f"{req_main}/*":
                    return media_type

                if media_type.endswith("+json") and requested == "application/json":
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
        ):
            if preferred in content:
                return preferred

        return next(iter(content), None)

    @staticmethod
    def _serialize_scalar(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"

        if isinstance(value, (dict, list)):
            return json.dumps(
                value,
                separators=(",", ":"),
                ensure_ascii=False,
            )

        return str(value)

    @classmethod
    def _serialize_query_parameter(
        cls,
        parameter: dict[str, Any],
        value: Any,
    ) -> list[tuple[str, str]]:
        name = str(parameter["name"])
        schema = parameter.get("schema") or {}

        style = parameter.get("style", "form")
        explode = parameter.get(
            "explode",
            True if style == "form" else False,
        )

        if isinstance(value, dict):
            if style == "deepObject":
                return [
                    (
                        f"{name}[{key}]",
                        cls._serialize_scalar(item),
                    )
                    for key, item in value.items()
                ]

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
                    ",".join(f"{key},{cls._serialize_scalar(item)}" for key, item in value.items()),
                )
            ]

        if isinstance(value, (list, tuple)):
            if style == "pipeDelimited":
                return [
                    (
                        name,
                        "|".join(cls._serialize_scalar(item) for item in value),
                    )
                ]

            if style == "spaceDelimited":
                return [
                    (
                        name,
                        " ".join(cls._serialize_scalar(item) for item in value),
                    )
                ]

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

        schema_type = schema.get("type")

        if schema_type == "boolean":
            value = cls._serialize_scalar(value)

        return [
            (
                name,
                cls._serialize_scalar(value),
            )
        ]

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
        """
        Resolve OpenAPI security requirements.

        Security alternatives are attempted in declaration order.
        Within one security requirement, every scheme is applied.
        """
        if not spec or not operation:
            return await self._legacy_auth_context(payload)

        security = operation.get("security") if "security" in operation else spec.get("security")

        if security == []:
            return {}, {}, {}

        if security is None:
            return await self._legacy_auth_context(payload)

        schemes = spec.get("components", {}).get("securitySchemes", {})

        auth = payload.get("auth") or (payload.get("metadata") or {}).get("auth") or {}

        last_error: Exception | None = None

        for requirement in security:
            try:
                headers: dict[str, str] = {}
                query: dict[str, str] = {}
                cookies: dict[str, str] = {}

                if not requirement:
                    return headers, query, cookies

                for scheme_name, scopes in requirement.items():
                    raw_scheme = schemes.get(scheme_name)

                    if raw_scheme is None:
                        auth_schemes = (
                            auth.get("schemes") if isinstance(auth.get("schemes"), dict) else {}
                        )
                        raw_scheme = auth_schemes.get(scheme_name)

                    scheme = (
                        await self._resolve_ref(
                            raw_scheme,
                            document=spec,
                            document_url=document_url,
                        )
                        if raw_scheme
                        else None
                    )

                    if not isinstance(scheme, dict):
                        raise OpenAPIResolutionError(
                            f"Security scheme {scheme_name!r} "
                            "is not defined in the OpenAPI document"
                        )

                    h, q, c = await self._apply_security_scheme(
                        scheme_name,
                        scheme,
                        scopes or [],
                        auth,
                        spec=spec,
                        document_url=document_url,
                    )

                    headers.update(h)
                    query.update(q)
                    cookies.update(c)

                return headers, query, cookies

            except Exception as exc:
                last_error = exc
                continue

        raise OpenAPIResolutionError(
            f"No configured OpenAPI security requirement could be satisfied: {last_error}"
        )

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
        kind = scheme.get("type")

        auth_schemes = auth.get("schemes") if isinstance(auth.get("schemes"), dict) else {}

        credentials = auth_schemes.get(name)
        if credentials is None:
            credentials = auth.get(name)

        if not isinstance(credentials, dict):
            credentials = {"token": credentials} if isinstance(credentials, str) else {}

        if kind == "apiKey":
            value = credentials.get("value") or credentials.get("key") or credentials.get("token")

            if value is None and scheme.get("name") == auth.get("api_key_name"):
                value = auth.get("api_key")

            env_name = (
                "OPENAPI_"
                + re.sub(
                    r"[^A-Za-z0-9]",
                    "_",
                    name,
                ).upper()
                + "_KEY"
            )

            value = (
                value
                or os.getenv(env_name)
                or os.getenv("OPENAPI_API_KEY")
                or os.getenv("OPENAPI_TOKEN")
            )

            if not value:
                raise OpenAPIResolutionError(
                    f"Missing credential for OpenAPI apiKey scheme {name!r}"
                )

            where = scheme.get("in")
            key_name = str(scheme.get("name"))

            if where == "header":
                return {key_name: str(value)}, {}, {}

            if where == "query":
                return {}, {key_name: str(value)}, {}

            if where == "cookie":
                return {}, {}, {key_name: str(value)}

            raise OpenAPIResolutionError(f"Unsupported apiKey location {where!r}")

        if kind == "http":
            http_scheme = str(scheme.get("scheme", "")).lower()

            if http_scheme == "bearer":
                token = (
                    credentials.get("token")
                    or credentials.get("access_token")
                    or auth.get("token")
                    or os.getenv("OPENAPI_API_KEY")
                    or os.getenv("OPENAPI_TOKEN")
                )

                if not token:
                    raise OpenAPIResolutionError(
                        f"Missing bearer token for OpenAPI scheme {name!r}"
                    )

                return {"Authorization": f"Bearer {token}"}, {}, {}

            if http_scheme == "basic":
                username = (
                    credentials.get("username")
                    or auth.get("username")
                    or os.getenv("OPENAPI_USERNAME")
                )

                password = (
                    credentials.get("password")
                    or auth.get("password")
                    or os.getenv("OPENAPI_PASSWORD")
                )

                if username is None or password is None:
                    raise OpenAPIResolutionError(
                        f"Missing basic-auth credentials for OpenAPI scheme {name!r}"
                    )

                encoded = base64.b64encode(f"{username}:{password}".encode()).decode()

                return {"Authorization": f"Basic {encoded}"}, {}, {}

            raise OpenAPIResolutionError(f"Unsupported OpenAPI HTTP auth scheme {http_scheme!r}")

        if kind == "oauth2":
            token = (
                credentials.get("access_token")
                or credentials.get("token")
                or auth.get("access_token")
            )

            if token:
                return {"Authorization": f"Bearer {token}"}, {}, {}

            flows = scheme.get("flows") or {}

            flow = flows.get("clientCredentials") or flows.get("client_credentials")

            if not flow:
                raise OpenAPIResolutionError(
                    f"OpenAPI oauth2 scheme {name!r} has no "
                    "clientCredentials flow and no access token was supplied"
                )

            token_url = (
                flow.get("tokenUrl") or auth.get("token_url") or os.getenv("OPENAPI_TOKEN_URL")
            )

            if not token_url:
                raise OpenAPIResolutionError(f"Missing OAuth2 token URL for scheme {name!r}")

            if document_url:
                token_url = urljoin(
                    document_url,
                    token_url,
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

            if not client_id or not client_secret:
                raise OpenAPIResolutionError(
                    f"Missing OAuth2 client credentials for scheme {name!r}"
                )

            token = await self._fetch_oauth_token(
                token_url,
                client_id,
                client_secret,
                scopes,
                flow.get("scopes", {}),
            )

            return {"Authorization": f"Bearer {token}"}, {}, {}

        if kind in {"openIdConnect", "mutualTLS"}:
            token = credentials.get("access_token") or credentials.get("token") or auth.get("token")

            if token:
                return {"Authorization": f"Bearer {token}"}, {}, {}

            raise OpenAPIResolutionError(
                f"OpenAPI security scheme {name!r} ({kind}) "
                "requires an explicit access token or external credential integration"
            )

        raise OpenAPIResolutionError(f"Unsupported OpenAPI security scheme type {kind!r}")

    async def _fetch_oauth_token(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        scopes: list[str],
        declared_scopes: dict[str, Any],
    ) -> str:
        scope_values = [
            scope for scope in scopes if scope in declared_scopes or not declared_scopes
        ]

        cache_key = (
            token_url,
            client_id,
            client_secret,
            " ".join(sorted(scope_values)),
        )

        cached = self._oauth_cache.get(cache_key)

        if cached and cached[0] > time.monotonic() + 15:
            return cached[1]

        async def _call():
            session = await SessionManager.get_session()

            form = {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            }

            if scope_values:
                form["scope"] = " ".join(scope_values)

            async with session.post(
                token_url,
                data=form,
                timeout=aiohttp.ClientTimeout(total=config.DEFAULT_ADAPTER_TIMEOUT),
            ) as response:
                if response.status >= 500 or response.status in {408, 425, 429}:
                    body = await response.text()

                    raise self._response_error(
                        response.status,
                        body,
                        token_url,
                        response.headers,
                    )

                data = await response.json()

                if response.status >= 400:
                    raise OpenAPIResolutionError(
                        f"OAuth2 token request failed: HTTP {response.status}: {data}"
                    )

                token = data.get("access_token")

                if not token:
                    raise OpenAPIResolutionError(
                        "OAuth2 token endpoint response omitted access_token"
                    )

                return str(token), int(data.get("expires_in", 300))

        token, expires_in = await self.call_with_retry(
            _call,
            retry_codes={408, 425, 429, 500, 502, 503, 504},
        )

        self._oauth_cache[cache_key] = (
            time.monotonic() + max(30, expires_in),
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
        auth = payload.get("auth") or (payload.get("metadata") or {}).get("auth") or {}

        token = (
            auth.get("token")
            or auth.get("api_key")
            or os.getenv("OPENAPI_API_KEY")
            or os.getenv("OPENAPI_TOKEN")
        )

        if token:
            return {"Authorization": f"Bearer {token}"}, {}, {}

        client_id = auth.get("client_id") or os.getenv("OPENAPI_CLIENT_ID")

        client_secret = auth.get("client_secret") or os.getenv("OPENAPI_CLIENT_SECRET")

        token_url = auth.get("token_url") or os.getenv("OPENAPI_TOKEN_URL")

        if client_id and client_secret and token_url:
            token = await self._fetch_oauth_token(
                token_url,
                client_id,
                client_secret,
                [],
                {},
            )

            return {"Authorization": f"Bearer {token}"}, {}, {}

        username = auth.get("username") or os.getenv("OPENAPI_USERNAME")

        password = auth.get("password") or os.getenv("OPENAPI_PASSWORD")

        if username is not None and password is not None:
            encoded = base64.b64encode(f"{username}:{password}".encode()).decode()

            return {"Authorization": f"Basic {encoded}"}, {}, {}

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
                "message": ("Missing endpoint URL for OpenAPI adapter."),
            }

        metadata = payload.get("metadata") or {}

        overrides = kwargs.get("overrides") or payload.get("overrides") or metadata.get("overrides")

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

                method = str(payload.get("method") or "POST").upper()

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
                    parsed._replace(query=urlencode(existing + list(auth_query.items())))
                )

            if body is not None and content_type and content_type != "multipart/form-data":
                request_headers.setdefault(
                    "Content-Type",
                    content_type,
                )

            request_headers.setdefault(
                "Accept",
                "application/json, text/plain, */*",
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
                )

                if poll_target:
                    return await self._poll_for_result(
                        poll_target["url"],
                        overrides,
                        request_headers,
                        method=poll_target.get(
                            "method",
                            "GET",
                        ),
                        operation=poll_target.get("operation"),
                        spec=poll_target.get("spec") or spec,
                        spec_url=poll_target.get("spec_url") or spec_url,
                        initial_body=poll_target.get("body"),
                        cookies=request_cookies,
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

    async def _request(
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
        async def _call():
            session = await SessionManager.get_session()

            request_headers = dict(headers)

            if content_type == "multipart/form-data":
                request_headers.pop("Content-Type", None)

            request_kwargs: dict[str, Any] = {
                "headers": request_headers,
                "cookies": cookies or None,
                "timeout": aiohttp.ClientTimeout(total=config.DEFAULT_ADAPTER_TIMEOUT),
            }

            if body is not None:
                if self._is_json_media_type(content_type):
                    request_kwargs["json"] = body

                elif content_type == "application/x-www-form-urlencoded":
                    request_kwargs["data"] = body

                elif content_type == "multipart/form-data":
                    request_kwargs["data"] = self._to_form_data(body)

                elif content_type and content_type.startswith("text/"):
                    request_kwargs["data"] = body if isinstance(body, str) else json.dumps(body)

                elif isinstance(
                    body,
                    (bytes, bytearray),
                ):
                    request_kwargs["data"] = body

                elif isinstance(body, str):
                    request_kwargs["data"] = body

                else:
                    request_kwargs["data"] = json.dumps(
                        body,
                        ensure_ascii=False,
                    )

            async with session.request(
                method,
                url,
                **request_kwargs,
            ) as response:
                if hasattr(response, "read"):
                    raw = await response.read()
                else:
                    text_value = await response.text()
                    raw = text_value.encode("utf-8")

                text_body = raw.decode(
                    "utf-8",
                    errors="replace",
                )

                if response.status in {
                    408,
                    425,
                    429,
                    500,
                    502,
                    503,
                    504,
                }:
                    raise self._response_error(
                        response.status,
                        text_body,
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
                    dict(response.headers),
                    text_body,
                )

        return await self.call_with_retry(
            _call,
            retry_codes={
                408,
                425,
                429,
                500,
                502,
                503,
                504,
            },
        )

    @staticmethod
    def _response_error(
        status: int,
        body: str,
        url: str,
        headers: Any = None,
    ) -> aiohttp.ClientResponseError:
        message = body[:1000] if body else f"HTTP {status}"

        if headers and headers.get("Retry-After"):
            message = f"{message} (Retry-After: {headers['Retry-After']})"

        return aiohttp.ClientResponseError(
            request_info=None,
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

        normalized = (
            content_type.lower()
            .split(
                ";",
                1,
            )[0]
            .strip()
        )

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
    def _is_json_media_type(
        content_type: str | None,
    ) -> bool:
        if not content_type:
            return False

        normalized = (
            content_type.lower()
            .split(
                ";",
                1,
            )[0]
            .strip()
        )

        return normalized == "application/json" or normalized.endswith("+json")

    @staticmethod
    def _to_form_data(body: Any) -> Any:
        from aiohttp import FormData

        form = FormData()

        if isinstance(body, dict):
            items = body.items()

        elif isinstance(body, list):
            items = (
                (
                    item.get("name"),
                    item.get("value"),
                )
                for item in body
                if isinstance(item, dict)
            )

        else:
            raise OpenAPIResolutionError(
                "multipart/form-data body must be an object or list of fields"
            )

        for name, value in items:
            if name is None:
                continue

            if isinstance(value, dict) and "content" in value:
                form.add_field(
                    str(name),
                    value["content"],
                    filename=value.get("filename"),
                    content_type=value.get("content_type"),
                )
            else:
                form.add_field(
                    str(name),
                    value,
                )

        return form

    # -------------------------------------------------------------------------
    # Response handling / normalization
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
        if isinstance(response_json, dict):
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

            content = str(response_json if response_json not in ({}, None) else response_text)[
                :5000
            ]

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
            response_meta["operation_id"] = operation.get("operationId")
            response_meta["operation_summary"] = operation.get("summary")

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

            if isinstance(value, str):
                return value

            return json.dumps(
                value,
                ensure_ascii=False,
                default=str,
            )[:5000]

        return json.dumps(
            response,
            ensure_ascii=False,
            default=str,
        )[:5000]

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

            if value is not None and str(value).strip().lower() in _PROCESSING_VALUES:
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
    ) -> dict[str, Any] | None:
        """
        Resolve the asynchronous follow-up operation.

        Resolution order:
          1. HTTP Location header.
          2. HATEOAS response links.
          3. OpenAPI response Links.
          4. Conventional runtime response URL fields.
        """
        location = response_headers.get("Location")

        if location:
            return {
                "url": urljoin(
                    request_url,
                    location,
                ),
                "method": "GET",
            }

        if isinstance(response_json, dict):
            href = self._find_hateoas_href(response_json)

            if href:
                return {
                    "url": urljoin(
                        request_url,
                        href,
                    ),
                    "method": "GET",
                }

        if spec and operation:
            response_links = await self._get_response_links(
                operation,
                spec,
                spec_url,
                response_headers,
                response_json,
                status_code=202,
            )

            for link in response_links:
                try:
                    target = await self._resolve_link_target(
                        link,
                        spec=spec,
                        spec_url=spec_url,
                        request_url=request_url,
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

        if isinstance(response_json, dict):
            for key in (
                "status_url",
                "poll_url",
                "result_url",
                "monitor_url",
                "operation_url",
            ):
                value = response_json.get(key)

                if isinstance(value, str) and value:
                    return {
                        "url": urljoin(
                            request_url,
                            value,
                        ),
                        "method": "GET",
                    }

        return None

    @staticmethod
    def _find_hateoas_href(
        response: dict[str, Any],
    ) -> str | None:
        links = response.get("_links") or response.get("links")

        if not isinstance(links, dict):
            return None

        for key in (
            "status",
            "self",
            "result",
            "poll",
            "operation",
        ):
            item = links.get(key)

            if isinstance(item, str):
                return item

            if isinstance(item, dict) and isinstance(item.get("href"), str):
                return item["href"]

        return None

    async def _get_response_links(
        self,
        operation: dict[str, Any],
        spec: dict[str, Any],
        spec_url: str | None,
        response_headers: dict[str, str],
        response_json: Any,
        *,
        status_code: int = 202,
    ) -> list[dict[str, Any]]:
        responses = operation.get("responses") or {}

        status = str(status_code) if str(status_code) in responses else None

        if not status:
            for candidate in (
                "202",
                "default",
                "200",
                "201",
            ):
                if candidate in responses:
                    status = candidate
                    break

        if not status:
            return []

        raw_response = responses.get(status) or responses.get("default")

        if not raw_response:
            return []

        raw_response = await self._resolve_ref(
            raw_response,
            document=spec,
            document_url=spec_url,
        )

        if not isinstance(raw_response, dict):
            return []

        links = raw_response.get("links")

        if not isinstance(links, dict):
            return []

        result: list[dict[str, Any]] = []

        for value in links.values():
            resolved = await self._resolve_ref(
                value,
                document=spec,
                document_url=spec_url,
            )

            if isinstance(resolved, dict):
                result.append(resolved)

        return result

    async def _resolve_link_target(
        self,
        link: dict[str, Any],
        *,
        spec: dict[str, Any],
        spec_url: str | None,
        request_url: str,
        response_json: Any,
        response_headers: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
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

            server_url = await self._resolve_server(
                spec=spec,
                path_item=path_item,
                operation=operation,
                document_url=spec_url,
                payload={},
                endpoint=request_url,
            )

            path_params: dict[str, Any] = {}
            query_params: dict[str, Any] = {}
            header_params: dict[str, Any] = {}

            for key, expression in (link.get("parameters") or {}).items():
                value = self._evaluate_runtime_expression(
                    expression,
                    response_json,
                    request_url,
                    response_headers or {},
                )

                if value is None:
                    continue

                if "." in str(key):
                    location, name = str(key).split(
                        ".",
                        1,
                    )
                else:
                    location, name = (
                        "query",
                        str(key),
                    )

                target_map = {
                    "path": path_params,
                    "query": query_params,
                    "header": header_params,
                }.get(
                    location,
                    query_params,
                )

                target_map[name] = value

            temp_payload = {
                "path_params": path_params,
                "query_params": query_params,
                "header_params": header_params,
            }

            if "requestBody" in link:
                temp_payload["input_payload"] = link.get("requestBody")

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
                _,
            ) = await self._build_request(
                spec=spec,
                document_url=spec_url,
                path_item=path_item,
                operation=operation,
                path_template=path_template,
                method=method,
                endpoint=endpoint_for_link,
                payload=temp_payload,
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
            }

        if link.get("operationRef"):
            (
                operation,
                path,
                method,
                path_item,
            ) = await self._resolve_operation_ref(
                spec,
                str(link["operationRef"]),
                document_url=spec_url,
            )

            server_url = await self._resolve_server(
                spec=spec,
                path_item=path_item,
                operation=operation,
                document_url=spec_url,
                payload={},
                endpoint=request_url,
            )

            path_params: dict[str, Any] = {}
            query_params: dict[str, Any] = {}
            header_params: dict[str, Any] = {}

            for key, expression in (link.get("parameters") or {}).items():
                value = self._evaluate_runtime_expression(
                    expression,
                    response_json,
                    request_url,
                    response_headers or {},
                )

                if value is None:
                    continue

                if "." in str(key):
                    location, name = str(key).split(
                        ".",
                        1,
                    )
                else:
                    location, name = (
                        "query",
                        str(key),
                    )

                target_map = {
                    "path": path_params,
                    "query": query_params,
                    "header": header_params,
                }.get(
                    location,
                    query_params,
                )

                target_map[name] = value

            temp_payload = {
                "path_params": path_params,
                "query_params": query_params,
                "header_params": header_params,
            }

            if "requestBody" in link:
                temp_payload["input_payload"] = link.get("requestBody")

            endpoint_for_link = urljoin(
                server_url.rstrip("/") + "/",
                path.lstrip("/"),
            )

            (
                target_url,
                target_method,
                headers,
                cookies,
                body,
                _,
            ) = await self._build_request(
                spec=spec,
                document_url=spec_url,
                path_item=path_item,
                operation=operation,
                path_template=path,
                method=method,
                endpoint=endpoint_for_link,
                payload=temp_payload,
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
            }

        return None

    @staticmethod
    def _evaluate_runtime_expression(
        expression: Any,
        response_body: Any,
        request_url: str,
        response_headers: dict[str, str],
    ) -> Any:
        if not isinstance(expression, str):
            return expression

        if not expression.startswith("$"):
            return expression

        if expression.lower() == "$url":
            return request_url

        if expression.startswith("$response.header."):
            header_name = expression[len("$response.header.") :]

            for key, value in response_headers.items():
                if key.lower() == header_name.lower():
                    return value

            return None

        if expression.startswith("$response.body#/"):
            current = response_body

            for token in expression[len("$response.body#/") :].split("/"):
                token = token.replace(
                    "~1",
                    "/",
                ).replace(
                    "~0",
                    "~",
                )

                if not isinstance(current, dict) or token not in current:
                    return None

                current = current[token]

            return current

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
    ) -> dict[str, Any]:
        current_url = poll_url
        current_method = method.upper()
        request_headers = dict(headers or {})
        request_cookies = dict(cookies or {})
        body = initial_body
        interval = self.poll_interval

        for attempt in range(
            1,
            self.max_poll_attempts + 1,
        ):
            await asyncio.sleep(max(0.0, interval))

            try:
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
                    content_type=request_headers.get("Content-Type"),
                )

                if isinstance(response_json, dict):
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
                        response_json if response_json not in ({}, None) else response_text
                    )[:5000]

                if response_headers.get("Retry-After"):
                    interval = self._parse_retry_after(
                        response_headers["Retry-After"],
                        fallback=interval,
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
                            "attempts": attempt,
                            "status_code": status_code,
                            "raw_response": response_json,
                            "response_headers": response_headers,
                            "poll_url": current_url,
                        },
                    }

                if response_headers.get("Location"):
                    current_url = urljoin(
                        current_url,
                        response_headers["Location"],
                    )
                    current_method = "GET"
                    body = None

                elif isinstance(response_json, dict):
                    href = self._find_hateoas_href(response_json)

                    if href:
                        current_url = urljoin(
                            current_url,
                            href,
                        )
                        current_method = "GET"
                        body = None

                if action != "processing" and status_code < 400:
                    return {
                        "status": "success",
                        "action": action,
                        "content": content,
                        "metadata": {
                            "framework": "openapi",
                            "attempts": attempt,
                            "status_code": status_code,
                            "raw_response": response_json,
                            "response_headers": response_headers,
                            "poll_url": current_url,
                        },
                    }

            except Exception as exc:
                logger.debug(
                    "OpenAPI polling attempt %d failed: %s",
                    attempt,
                    exc,
                )

                if attempt == self.max_poll_attempts:
                    return {
                        "status": "error",
                        "action": "error",
                        "content": (f"Polling failed after {attempt} attempts: {exc}"),
                    }

        return {
            "status": "error",
            "action": "error",
            "content": "Polling timeout exceeded.",
            "metadata": {
                "attempts": self.max_poll_attempts,
                "poll_url": current_url,
            },
        }

    @staticmethod
    def _parse_retry_after(
        value: str,
        fallback: float,
    ) -> float:
        try:
            return max(
                0.0,
                float(value),
            )
        except (TypeError, ValueError):
            return fallback


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
