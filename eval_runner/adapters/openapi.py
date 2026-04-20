import asyncio
import json
import logging
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp

from ..events import CoreEvents, emit

logger = logging.getLogger(__name__)


class DualNormalizationHub:
    """
    Standardized Mapping Engine for Industrial Agent Responses.
    Maps heterogeneous agent states to Harness Core actions (hitl_pause, final_answer, error).
    """

    # Lexical Heuristics (Agnostic Wait-State Markers)
    POLLING_KEYWORDS = ["pending", "processing", "gear", "queued", "progress"]
    HITL_KEYWORDS = [
        "hitl",
        "review",
        "manual",
        "human",
        "intervention",
        "pause",
        "clearance",
        "waiting",
    ]

    TERMINAL_KEYWORDS = ["approved", "rejected", "completed", "final", "success"]
    ERROR_KEYWORDS = ["error", "failed", "failure", "exception", "crash"]

    VALID_ACTIONS = {"hitl_pause", "final_answer", "error", "completed", "processing"}

    @classmethod
    def normalize(
        cls, response: dict[str, Any], status_code: int, overrides: dict[str, str] | None = None
    ) -> str:
        """
        Normalizes any JSON response to a Harness Action.
        Precedence: Overrides > Status Codes > Schema Metadata > Heuristics.
        """

        # 1. Break-Glass Overrides (P0)
        if overrides:
            for condition, action in overrides.items():
                # [Hardening] Explicit Validation of the target action
                if action not in cls.VALID_ACTIONS:
                    logger.warning(
                        f"   [Normalization Hub] Invalid override action '{action}' "
                        f"for condition '{condition}'. Ignoring."
                    )
                    continue

                # Supports simple equality or pattern matching on status-like fields
                # Current implementation: case-insensitive key/value mapping
                # Example: {"status": "processing"} matches "PROCESSING", "Processing", etc.
                for key, val in response.items():
                    if str(key).lower() in ["status", "state", "result"]:
                        if str(val).lower() == condition.lower():
                            emit(
                                CoreEvents.ADAPTER_DEBUG,
                                {"message": (f"Applied Semantic Match: {condition} -> {action}")},
                            )
                            return action

        # 2. Standard HTTP Status Codes (P1)
        if status_code >= 400:
            return "error"

        # 3. Lexical Heuristics (P2 - Agnostic Mapping)
        # Search primary status indicators
        status_val = ""
        for key in ["status", "state", "phase", "outcome", "decision", "result"]:
            if key in response:
                status_val = str(response[key]).lower()
                break

        if not status_val:
            # Fallback: scan whole first level of keys for common status names
            for k, v in response.items():
                if any(x in k.lower() for x in ["status", "state", "result"]):
                    status_val = str(v).lower()
                    break

        if any(kw in status_val for kw in cls.HITL_KEYWORDS):
            emit(
                CoreEvents.ADAPTER_DEBUG,
                {"message": f"Agnostic Mapping: hitl_pause (Status: '{status_val}')"},
            )
            return "hitl_pause"

        if any(kw in status_val for kw in cls.POLLING_KEYWORDS):
            emit(
                CoreEvents.ADAPTER_DEBUG,
                {"message": f"Agnostic Mapping: processing (Status: '{status_val}')"},
            )
            return "processing"

        if any(kw in status_val for kw in cls.ERROR_KEYWORDS):
            return "error"

        if any(kw in status_val for kw in cls.TERMINAL_KEYWORDS):
            return "final_answer"

        # Default fallback for untagged successful responses
        return "final_answer"


async def adapter(payload: dict[str, Any], endpoint: str, **kwargs) -> dict[str, Any]:
    """
    Generic OpenAPI REST Adapter.
    Handles standard OAS patterns: POST execution, 202 Polling, and Agnostic Normalization.
    """
    overrides = kwargs.get("overrides")  # Passed from session.py via Registry

    # 1. Spec Discovery (OAS Handshake)
    # [Fix A] Always derive the spec URL from the base origin (scheme+host+port).
    # If the caller pre-configures the endpoint as e.g. http://localhost:8000/apply
    # we must not append /openapi.json to the path — we fetch from the root origin.
    parsed = urlparse(endpoint)
    base_origin = f"{parsed.scheme}://{parsed.netloc}"  # e.g. http://localhost:8000
    spec_url = base_origin + "/openapi.json"

    async with aiohttp.ClientSession() as session:
        # Note: In production, we would cache the spec. Here we fetch for freshness.
        try:
            async with session.get(spec_url, timeout=10) as resp:
                if resp.status == 200:
                    spec = await resp.json()
                    emit(
                        CoreEvents.ADAPTER_DEBUG,
                        {"message": f"Discovered OAS: {spec.get('info', {}).get('title')}"},
                    )
                else:
                    spec = {}
        except Exception:
            spec = {}

        # 2. Protocol Execution (Industrial REST Phase)
        # Spec-Aware Resolution: Resolve target_url from discovered spec or fallback to endpoint
        target_url = endpoint
        if spec.get("paths"):
            # Heuristic: Find canonical execution point (e.g. POST /apply or POST /run)
            potential_paths = ["/apply", "/run", "/execute", "/applications", "/v1/apply"]
            for path in potential_paths:
                if path in spec["paths"] and "post" in spec["paths"][path]:
                    target_url = urljoin(endpoint, path)
                    emit(
                        CoreEvents.ADAPTER_DEBUG,
                        {"message": f"Spec Discovery: Resolved execution path -> {target_url}"},
                    )
                    break

        # Determine method (OAS check would be here, defaulting to POST for task execution)
        method = "POST"

        # Prepare Payload
        data = payload.get("input_payload", payload)

        # [Industrial Debug]: Verify payload compliance before transmission
        print(f"      [OpenAPI Adapter] Transmitting Payload: {json.dumps(data)}")
        emit(CoreEvents.ADAPTER_DEBUG, {"message": f"Transmitting Payload: {json.dumps(data)}"})

        async with session.request(method, target_url, json=data) as resp:
            status_code = resp.status
            response_json = await resp.json()

            # 3. Asynchronous Polling (202 Accepted Pattern)
            if status_code == 202 or "Location" in resp.headers:
                poll_url = resp.headers.get("Location")
                if not poll_url:
                    # Fallback: look for status link in body
                    poll_url = response_json.get("status_url") or response_json.get(
                        "links", {}
                    ).get("status")

                if poll_url:
                    if not poll_url.startswith("http"):
                        # Build relative URL
                        poll_url = urljoin(target_url, poll_url)

                    return await _poll_for_result(session, poll_url, overrides)

            # 4. Immediate Normalization (Sync Pattern)
            action = DualNormalizationHub.normalize(response_json, status_code, overrides)

            # [RFC-003]: Agnostic Polling Trigger
            # If the normalization indicates 'processing', we initiate native polling
            if action == "processing":
                # [Industrial Identity Resolution]
                # Look for common ID fields to construct a resource-specific poll URL
                res_id = (
                    response_json.get("application_id")
                    or response_json.get("id")
                    or response_json.get("uuid")
                    or response_json.get("job_id")
                )

                poll_url = target_url  # Default fallback

                if spec.get("paths") and res_id:
                    # Heuristic: Find canonical status point (e.g. /status/{id}) in Spec
                    # Look for paths containing parameters with GET methods
                    found_template = False
                    for path_template in spec["paths"]:
                        if "{" in path_template and "get" in spec["paths"][path_template]:
                            # Verify if the path takes an ID parameter
                            params = spec["paths"][path_template]["get"].get("parameters", [])
                            if any(
                                p.get("name") in ["id", "application_id", "job_id"] for p in params
                            ):
                                resolved_path = path_template.replace("{id}", str(res_id)).replace(
                                    "{application_id}", str(res_id)
                                )
                                # [Fix A] Use base_origin as the join base, not target_url.
                                # target_url may be /apply which would produce /apply/status/164.
                                poll_url = urljoin(base_origin + "/", resolved_path.lstrip("/"))
                                found_template = True
                                break

                    if found_template:
                        emit(
                            CoreEvents.ADAPTER_DEBUG,
                            {"message": f"Spec Discovery: Resolved polling path -> {poll_url}"},
                        )

                elif res_id:
                    # REST Fallback: no spec available, construct a best-guess status URL.
                    # [Fix A] Use base_origin + /status/{id} rather than appending to target_url
                    # (which may be /apply, producing the nonsensical /apply/{id}).
                    poll_url = f"{base_origin}/status/{res_id}"

                emit(
                    CoreEvents.ADAPTER_DEBUG,
                    {
                        "message": f"Wait-state detected (Status: {response_json.get('status')}). "
                        f"Initiating native poll on resolved resource: {poll_url}"
                    },
                )
                return await _poll_for_result(session, poll_url, overrides)

            return {
                "action": action,
                "content": response_json.get("decision_reason")
                or response_json.get("message")
                or response_json.get("status")
                or str(response_json)[:500],
                "metadata": {
                    "raw_response": response_json,
                    "status_code": status_code,
                    "protocol": "openapi_v1.5",
                },
            }


MAX_POLL_ATTEMPTS = 150


async def _poll_for_result(session, poll_url: str, overrides: dict | None) -> dict[str, Any]:
    """Internal polling loop following standard industrial async patterns."""
    interval = 2

    for i in range(MAX_POLL_ATTEMPTS):
        await asyncio.sleep(interval)
        async with session.get(poll_url) as resp:
            status_code = resp.status
            try:
                data = await resp.json()
            except Exception:
                continue

            # [Fix B] Transient HTTP errors (4xx/5xx) during polling indicate the
            # resource is not yet ready — continue polling rather than exiting.
            # Only exit on a verified non-processing state from a successful response.
            if status_code >= 400:
                logger.debug(f"   [Poll] Transient HTTP {status_code} from {poll_url} — retrying.")
                continue

            action = DualNormalizationHub.normalize(data, status_code, overrides)

            # Terminal State Found
            if action in ["hitl_pause", "final_answer"]:
                return {
                    "action": action,
                    "content": data.get("decision_reason") or data.get("message") or str(data),
                    "metadata": {"raw_response": data, "attempts": i + 1},
                }
            # Continue polling for 'processing' or unrecognized states
            # (error is treated as transient during active polling)

    return {"action": "error", "content": "Polling timeout exceeded (Industrial Safety Cutoff)"}
