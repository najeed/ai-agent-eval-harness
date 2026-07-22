# eval_runner/adapters/common.py
import asyncio
import hashlib
import json
import logging
from typing import Any

import aiohttp

from .. import config
from ..events import CoreEvents, emit

logger = logging.getLogger(__name__)

try:
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:

    class BaseCallbackHandler:  # type: ignore[no-redef]
        pass


class SessionManager:
    """
    Singleton Connection Pool Manager (v1.6.0).
    Ensures shared resources are reused across all adapters to prevent leaks.
    """

    _session: aiohttp.ClientSession | None = None
    _lock = asyncio.Lock()

    @classmethod
    async def get_session(cls) -> aiohttp.ClientSession:
        """Returns the global aiohttp session instance."""
        if cls._session is None or cls._session.closed:
            async with cls._lock:
                if cls._session is None or cls._session.closed:
                    # Industrial Setting: High-concurrency connection pooling
                    connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
                    cls._session = aiohttp.ClientSession(
                        connector=connector,
                        connector_owner=True,
                        timeout=aiohttp.ClientTimeout(total=config.DEFAULT_ADAPTER_TIMEOUT),
                    )
        return cls._session

    @classmethod
    async def close_all(cls):
        """Cleanly closes all pooled connections and resets state."""
        if cls._session and not cls._session.closed:
            connector = cls._session.connector
            await cls._session.close()
            if connector:
                try:
                    res = connector.close()
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as _e:
                    logger.debug("Connector close skipped: %s", _e, exc_info=True)
        cls._session = None
        cls._lock = asyncio.Lock()


class BaseAdapter:
    """
    Foundational Adapter Layer for AgentV release-quality resilience.
    Provides connection pooling and exponential backoff retry logic.
    """

    def __init__(self, name: str):
        self.name = name
        self.max_retries = config.ADAPTER_MAX_RETRIES
        self.retry_delay = config.ADAPTER_RETRY_DELAY

    async def call_with_retry(
        self,
        func,
        *args,
        max_attempts: int | None = None,
        base_delay: float | None = None,
        retry_codes: set[int] | None = None,
        **kwargs,
    ) -> Any:
        """
        Executes a function with exponential backoff retry logic.
        """
        max_attempts = max_attempts or self.max_retries
        base_delay = base_delay or self.retry_delay
        retry_codes = retry_codes or {429, 502, 503, 504}
        attempt = 0

        while attempt < max_attempts:
            try:
                return await func(*args, **kwargs)
            except aiohttp.ClientResponseError as e:
                if e.status in retry_codes and attempt < max_attempts - 1:
                    attempt += 1
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"      [Adapter:{self.name}] Transient error {e.status}. "
                        f"Retry {attempt}/{max_attempts} in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
            except (TimeoutError, aiohttp.ClientConnectorError) as e:
                if attempt < max_attempts - 1:
                    attempt += 1
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"      [Adapter:{self.name}] Connection error: {e}. "
                        f"Retry {attempt}/{max_attempts} in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
            except Exception:
                raise


class AESCallbackHandler(BaseCallbackHandler):
    """
    Industrial Telemetry: Translates LangChain/LangGraph signals to AES event bus.
    Provides standardized 'CHAIN' and 'NODE' lifecycle events.
    """

    def __init__(self, adapter_name: str, identifier: str):
        self.adapter_name = adapter_name
        self.identifier = identifier

    def on_chain_start(self, serialized: dict[str, Any], inputs: dict[str, Any], **kwargs: Any):
        # Redacted Summary + State Hash (Audit-ready security)
        try:
            state_str = json.dumps(inputs, sort_keys=True)
            state_hash = hashlib.sha256(state_str.encode()).hexdigest()
            inputs_summary = {k: type(v).__name__ for k, v in inputs.items()}
        except Exception as _e:
            logger.debug("State hashing skipped: %s", _e, exc_info=True)
            state_hash = "error_hashing"
            inputs_summary = {"error": "serialization_failed"}

        emit(
            CoreEvents.CHAIN_START,
            {
                "adapter": self.adapter_name,
                "id": self.identifier,
                "state_hash": state_hash,
                "inputs_summary": inputs_summary,
            },
        )

    def on_chain_end(self, outputs: dict[str, Any], **kwargs: Any):
        emit(CoreEvents.CHAIN_END, {"adapter": self.adapter_name, "id": self.identifier})

    def on_node_start(self, serialized: dict[str, Any], inputs: dict[str, Any], **kwargs: Any):
        emit(
            CoreEvents.NODE_START,
            {
                "adapter": self.adapter_name,
                "node_id": serialized.get("id", ["unknown"])[-1]
                if isinstance(serialized, dict)
                else "unknown",
            },
        )

    def on_node_end(self, outputs: dict[str, Any], **kwargs: Any):
        emit(CoreEvents.NODE_END, {"adapter": self.adapter_name})

    def on_llm_start(self, serialized: dict[str, Any], prompts: list[str], **kwargs: Any):
        emit(
            CoreEvents.ADAPTER_DEBUG,
            {"adapter": self.adapter_name, "message": f"LLM Start: {len(prompts)} prompts"},
        )

    def on_llm_end(self, response: Any, **kwargs: Any):
        # Extract token usage if available (standard in LangChain LLMResult)
        usage = getattr(response, "llm_output", {}).get("token_usage", {})
        if usage:
            emit(
                "metric_update",
                {
                    "adapter": self.adapter_name,
                    "tokens": usage.get("total_tokens"),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                },
            )


class DualNormalizationHub:
    """
    Standardized Mapping Engine for Industrial Agent Responses.
    Maps heterogeneous agent states to Harness Core actions (hitl_pause, final_answer, error).
    """

    # Lexical Heuristics (Agnostic Wait-State Markers)
    POLLING_KEYWORDS = config.POLLING_KEYWORDS
    HITL_KEYWORDS = config.HITL_KEYWORDS
    TERMINAL_KEYWORDS = config.TERMINAL_KEYWORDS
    ERROR_KEYWORDS = config.ERROR_KEYWORDS

    VALID_ACTIONS = {"hitl_pause", "final_answer", "error", "completed", "processing"}

    @classmethod
    def normalize_text(cls, text: str) -> str:
        """
        Infers an action from free-text using heuristics.
        Useful for raw LLM outputs.
        """
        text_lower = text.lower()

        if any(kw in text_lower for kw in cls.HITL_KEYWORDS):
            return "hitl_pause"

        if any(kw in text_lower for kw in cls.POLLING_KEYWORDS):
            return "processing"

        if any(kw in text_lower for kw in cls.ERROR_KEYWORDS):
            return "error"

        if any(kw in text_lower for kw in cls.TERMINAL_KEYWORDS):
            return "final_answer"

        return "final_answer"

    @classmethod
    def normalize(
        cls,
        response: dict[str, Any],
        status_code: int,
        overrides: dict[str, str] | None = None,
        schema: dict[str, str] | None = None,
    ) -> str:
        """
        Normalizes any JSON response to a Harness Action.
        Precedence: Overrides > Schema Mapping > Status Codes > Heuristics.
        """

        # 1. Break-Glass Overrides (P0)
        if overrides:
            for condition, action in overrides.items():
                if action not in cls.VALID_ACTIONS:
                    logger.warning(  # noqa: E501
                        f"Invalid override action '{action}' for condition '{condition}'"
                    )
                    continue

                for key, val in response.items():
                    if str(key).lower() in ["status", "state", "result"]:
                        if str(val).lower() == condition.lower():
                            return action

        # 2. Schema-Based Mapping (P1 - Release Quality)
        if schema:
            # Schema format: {"status_field": "status", "mapping": {"success": "completed"}}
            field = schema.get("status_field", "status")
            mapping = schema.get("mapping", {})
            val = response.get(field)
            if val is not None:
                action = mapping.get(str(val).lower())
                if action in cls.VALID_ACTIONS:
                    emit(
                        CoreEvents.ADAPTER_DEBUG,
                        {"message": f"Schema Match: {field}='{val}' -> {action}"},
                    )
                    return action

        # 3. Standard HTTP Status Codes (P2)
        if status_code >= 400:
            return "error"

        # 4. Lexical Heuristics (P3 - Agnostic Mapping)
        status_val = ""
        for key in ["status", "state", "phase", "outcome", "decision", "result"]:
            if key in response:
                status_val = str(response[key])
                break

        if not status_val:
            for k, v in response.items():
                if any(x in k.lower() for x in ["status", "state", "result"]):
                    status_val = str(v)
                    break

        # Use centralized text normalization logic
        if status_val:
            action = cls.normalize_text(status_val)
            if action != "final_answer":
                emit(
                    CoreEvents.ADAPTER_DEBUG,
                    {"message": f"Agnostic Mapping: {action} (Value: '{status_val}')"},
                )
            return action

        return "final_answer"
