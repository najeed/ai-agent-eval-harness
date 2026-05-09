import asyncio
import logging
import os
from typing import Any
from urllib.parse import urljoin, urlparse

from ..plugins import BaseEvalPlugin
from .common import BaseAdapter, DualNormalizationHub, SessionManager

logger = logging.getLogger(__name__)


class OpenAPIAdapterPlugin(BaseEvalPlugin, BaseAdapter):
    """
    Industrial Adapter: Generic OpenAPI REST Adapter with OAuth2 and pooling.
    Registers the 'openapi' protocol.
    """

    def __init__(self):
        BaseAdapter.__init__(self, name="openapi")
        self.max_poll_attempts = 150

    def on_discover_adapters(self, registry: Any):
        """Register the openapi protocol."""
        print("      [Plugin] Registering OpenAPI adapter via on_discover_adapters hook.")
        registry.register("openapi", self.execute_openapi_query)

    async def _get_auth_header(self, payload: dict[str, Any]) -> dict[str, str]:
        """Resolves authentication headers (Bearer, OAuth2, Basic)."""
        auth = payload.get("metadata", {}).get("auth", {})
        headers = {}

        # 1. Direct Bearer Token
        token = auth.get("token") or os.getenv("OPENAPI_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
            return headers

        # 2. OAuth2 Client Credentials
        client_id = auth.get("client_id") or os.getenv("OPENAPI_CLIENT_ID")
        client_secret = auth.get("client_secret") or os.getenv("OPENAPI_CLIENT_SECRET")
        token_url = auth.get("token_url") or os.getenv("OPENAPI_TOKEN_URL")

        if client_id and client_secret and token_url:

            async def _fetch_token():
                session = await SessionManager.get_session()
                data = {
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                }
                async with session.post(token_url, data=data) as resp:
                    resp.raise_for_status()
                    return await resp.json(), resp.status

            try:
                res, _ = await self.call_with_retry(_fetch_token)
                headers["Authorization"] = f"Bearer {res['access_token']}"
                return headers
            except Exception as e:
                logger.warning(f"OAuth2 Token Fetch Failed: {e}")

        # 3. Basic Auth
        username = auth.get("username")
        password = auth.get("password")
        if username and password:
            import base64

            creds = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {creds}"

        return headers

    async def execute_openapi_query(
        self, payload: dict[str, Any], endpoint: str = None, **kwargs
    ) -> dict[str, Any]:
        """
        Executes an OpenAPI query with standardized pooling and resilience.
        """
        overrides = kwargs.get("overrides")
        endpoint = endpoint or payload.get("url")

        if not endpoint:
            return {"status": "error", "message": "Missing endpoint URL for OpenAPI adapter."}

        parsed = urlparse(endpoint)
        base_origin = f"{parsed.scheme}://{parsed.netloc}"
        spec_url = base_origin + "/openapi.json"

        session = await SessionManager.get_session()
        spec = {}
        try:
            async with session.get(spec_url, timeout=5) as resp:
                if resp.status == 200:
                    spec = await resp.json()
        except Exception as e:
            logger.debug(f"OpenAPI Spec fetch failed (non-critical): {e}")

        target_url = endpoint
        if spec.get("paths"):
            potential_paths = ["/apply", "/run", "/execute", "/applications", "/v1/apply"]
            for path in potential_paths:
                if path in spec["paths"] and "post" in spec["paths"][path]:
                    target_url = urljoin(endpoint, path)
                    break

        headers = await self._get_auth_header(payload)
        headers["Content-Type"] = "application/json"

        method = "POST"
        data = payload.get("input_payload", payload)

        async def _call():
            async with session.request(method, target_url, json=data, headers=headers) as resp:
                if resp.status >= 500:
                    resp.raise_for_status()
                return await resp.json(), resp.status, resp.headers

        try:
            response_json, status_code, resp_headers = await self.call_with_retry(_call)

            if status_code == 202 or "Location" in resp_headers:
                poll_url = resp_headers.get("Location")
                if not poll_url:
                    poll_url = response_json.get("status_url") or response_json.get(
                        "links", {}
                    ).get("status")
                if poll_url:
                    if not poll_url.startswith("http"):
                        poll_url = urljoin(target_url, poll_url)
                    return await self._poll_for_result(poll_url, overrides, headers)

            action = DualNormalizationHub.normalize(response_json, status_code, overrides)

            if action == "processing":
                res_id = (
                    response_json.get("application_id")
                    or response_json.get("id")
                    or response_json.get("uuid")
                    or response_json.get("job_id")
                )
                if res_id:
                    poll_url = f"{base_origin}/status/{res_id}"
                    return await self._poll_for_result(poll_url, overrides, headers)

            return {
                "action": action,
                "content": response_json.get("decision_reason")
                or response_json.get("message")
                or str(response_json)[:500],
                "metadata": {
                    "raw_response": response_json,
                    "status_code": status_code,
                    "framework": "openapi",
                },
            }

        except Exception as e:
            return {"status": "error", "action": "error", "message": str(e)}

    async def _poll_for_result(
        self, poll_url: str, overrides: dict | None, headers: dict
    ) -> dict[str, Any]:
        session = await SessionManager.get_session()
        interval = 2

        for i in range(self.max_poll_attempts):
            await asyncio.sleep(interval)
            try:
                async with session.get(poll_url, headers=headers) as resp:
                    status_code = resp.status
                    data = await resp.json()

                    if status_code >= 400:
                        continue

                    action = DualNormalizationHub.normalize(data, status_code, overrides)
                    if action in ["hitl_pause", "final_answer", "error"]:
                        return {
                            "action": action,
                            "content": (
                                data.get("decision_reason") or data.get("message") or str(data)
                            ),
                            "metadata": {"raw_response": data, "attempts": i + 1},
                        }
            except Exception as e:
                logger.debug(f"OpenAPI Polling iteration failed: {e}")
                continue

        return {"action": "error", "content": "Polling timeout exceeded."}


async def adapter(payload: dict[str, Any], endpoint: str, **kwargs) -> dict[str, Any]:
    """Compatibility wrapper."""
    plugin = OpenAPIAdapterPlugin()
    return await plugin.execute_openapi_query(payload, endpoint, **kwargs)
