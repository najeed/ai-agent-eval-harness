# eval_runner/adapters/common.py
import hashlib
import json
from typing import Any

from .. import config
from ..events import CoreEvents, emit

try:
    from langchain_core.callbacks import BaseCallbackHandler
except ImportError:
    # Minimal fallback for environments without langchain-core
    class BaseCallbackHandler:
        pass


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
        except Exception:
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
        cls, response: dict[str, Any], status_code: int, overrides: dict[str, str] | None = None
    ) -> str:
        """
        Normalizes any JSON response to a Harness Action.
        Precedence: Overrides > Status Codes > Schema Metadata > Heuristics.
        """

        # 1. Break-Glass Overrides (P0)
        if overrides:
            import logging

            logger = logging.getLogger(__name__)
            for condition, action in overrides.items():
                if action not in cls.VALID_ACTIONS:
                    logger.warning(
                        f"Invalid override action '{action}' for condition '{condition}'."
                    )
                    continue

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
