import asyncio
import json
import logging
from typing import Any

import aiohttp

from ..events import CoreEvents, emit

logger = logging.getLogger(__name__)


class DualNormalizationHub:
    """
    Standardized Mapping Engine for Industrial Agent Responses.
    Maps heterogeneous agent states to Harness Core actions (hitl_pause, final_answer, error).
    """

    # Lexical Heuristics (Agnostic Wait-State Markers)
    WAIT_KEYWORDS = [
        "hitl",
        "review",
        "manual",
        "pending",
        "waiting",
        "human",
        "gear",
        "intervention",
        "pause",
        "clearance",
        "processing",
    ]

    TERMINAL_KEYWORDS = ["approved", "rejected", "completed", "final", "success"]
    ERROR_KEYWORDS = ["error", "failed", "failure", "exception", "crash"]

    VALID_ACTIONS = {"hitl_pause", "final_answer", "error", "completed"}

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
                # Current implementation: key == value mapping
                # Example: {"status": "HITL_REQUIRED"} -> "hitl_pause"
                for key, val in response.items():
                    if str(key).lower() in ["status", "state", "result"]:
                        if str(val) == condition:
                            emit(
                                CoreEvents.ADAPTER_DEBUG,
                                {
                                    "message": (
                                        f"Applied Break-Glass Override: {condition} -> {action}"
                                    )
                                },
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

        if any(kw in status_val for kw in cls.WAIT_KEYWORDS):
            emit(
                CoreEvents.ADAPTER_DEBUG,
                {"message": f"Agnostic Mapping: hitl_pause (Status: '{status_val}')"},
            )
            return "hitl_pause"

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
    spec_url = endpoint
    if not spec_url.endswith(".json") and not spec_url.endswith(".yaml"):
        # Attempt standard location
        spec_url = spec_url.rstrip("/") + "/openapi.json"

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
        # Determine the execution path (e.g., POST /apply)
        # For this agnostic impl, we assume the 'endpoint' provided in the call
        # is the target for the initial payload (Scenario -> Registry -> Here)
        target_url = endpoint  # Fallback to literal endpoint if discovery fails

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
                        from urllib.parse import urljoin

                        poll_url = urljoin(target_url, poll_url)

                    return await _poll_for_result(session, poll_url, overrides)

            # 4. Immediate Normalization (Sync Pattern)
            action = DualNormalizationHub.normalize(response_json, status_code, overrides)

            # [Industrial Resilience]: If the status is 'processing' but returned via 200 OK,
            # we map to 'hitl_pause' to allow the engine to wait or the user to intervene.
            if action == "hitl_pause" and status_code == 200:
                emit(
                    CoreEvents.ADAPTER_DEBUG,
                    {"message": "Wait-state detected in synchronous response. Pausing."},
                )
                return {
                    "action": "hitl_pause",
                    "content": response_json.get("message") or "Agent is processing the request.",
                    "metadata": {"raw_response": response_json, "status_code": 200},
                }

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


async def _poll_for_result(session, poll_url: str, overrides: dict | None) -> dict[str, Any]:
    """Internal polling loop following standard industrial async patterns."""
    max_attempts = 150
    interval = 2

    for i in range(max_attempts):
        await asyncio.sleep(interval)
        async with session.get(poll_url) as resp:
            status_code = resp.status
            try:
                data = await resp.json()
            except Exception:
                continue

            action = DualNormalizationHub.normalize(data, status_code, overrides)

            # Terminal State Found
            if action != "processing":  # Any mapping that isn't 'still busy'
                # Note: Default hub maps unknown/wait states to hitl_pause.
                # If we want to continue polling, we'd need a 'PENDING' mapping.
                # For this industrial impl, we treat non-terminal unrecognized as HITL for safety.
                if action in ["hitl_pause", "final_answer", "error"]:
                    return {
                        "action": action,
                        "content": data.get("decision_reason") or data.get("message") or str(data),
                        "metadata": {"raw_response": data, "attempts": i + 1},
                    }

    return {"action": "error", "content": "Polling timeout exceeded (Industrial Safety Cutoff)"}
