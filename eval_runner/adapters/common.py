# eval_runner/adapters/common.py
import hashlib
import json
from typing import Any, Dict, Optional
from ..events import EventEmitter, CoreEvents

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

    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs: Any):
        # Redacted Summary + State Hash (Audit-ready security)
        try:
            state_str = json.dumps(inputs, sort_keys=True)
            state_hash = hashlib.sha256(state_str.encode()).hexdigest()
            inputs_summary = {k: type(v).__name__ for k, v in inputs.items()}
        except Exception:
            state_hash = "error_hashing"
            inputs_summary = {"error": "serialization_failed"}
        
        EventEmitter.emit(CoreEvents.CHAIN_START, {
            "adapter": self.adapter_name,
            "id": self.identifier,
            "state_hash": state_hash,
            "inputs_summary": inputs_summary
        })

    def on_chain_end(self, outputs: Dict[str, Any], **kwargs: Any):
        EventEmitter.emit(CoreEvents.CHAIN_END, {
            "adapter": self.adapter_name,
            "id": self.identifier
        })

    def on_node_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs: Any):
        EventEmitter.emit(CoreEvents.NODE_START, {
            "adapter": self.adapter_name,
            "node_id": serialized.get("id", ["unknown"])[-1] if isinstance(serialized, dict) else "unknown"
        })

    def on_node_end(self, outputs: Dict[str, Any], **kwargs: Any):
        EventEmitter.emit(CoreEvents.NODE_END, {
            "adapter": self.adapter_name
        })
