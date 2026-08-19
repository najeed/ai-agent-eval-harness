"""
eval_runner.session_components.turn_state
Decomposed Session Component: TurnStateManager
"""

from typing import Any


class TurnStateManager:
    """
    Manages turn execution state, step sequences, and message history for an evaluation session.
    """

    def __init__(self, max_turns: int = 30):
        self.max_turns = max_turns
        self.current_turn: int = 0
        self.turn_events: list[dict[str, Any]] = []
        self.message_history: list[dict[str, Any]] = []
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0

    def start_turn(self, turn_number: int | None = None) -> int:
        """Increments and starts a new turn."""
        if turn_number is not None:
            self.current_turn = turn_number
        else:
            self.current_turn += 1
        return self.current_turn

    def is_exhausted(self) -> bool:
        """Returns True if the maximum turn limit has been reached."""
        return self.current_turn >= self.max_turns

    def record_message(self, role: str, content: Any, metadata: dict[str, Any] | None = None):
        """Records a conversational message turn."""
        self.message_history.append(
            {
                "role": role,
                "content": content,
                "turn": self.current_turn,
                "metadata": metadata or {},
            }
        )

    def record_token_usage(self, input_tokens: int, output_tokens: int):
        """Accumulates token consumption metrics."""
        self.total_input_tokens += max(0, input_tokens)
        self.total_output_tokens += max(0, output_tokens)

    def snapshot(self) -> dict[str, Any]:
        """Serializes current turn state for checkpointing."""
        return {
            "current_turn": self.current_turn,
            "max_turns": self.max_turns,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "message_count": len(self.message_history),
        }

    def restore(self, state: dict[str, Any]):
        """Restores turn state from a checkpoint."""
        self.current_turn = state.get(
            "current_turn", state.get("turn", state.get("turn_number", 0))
        )
        self.max_turns = state.get("max_turns", self.max_turns)
        self.total_input_tokens = state.get("total_input_tokens", 0)
        self.total_output_tokens = state.get("total_output_tokens", 0)
        if "history" in state and isinstance(state["history"], list):
            self.message_history = list(state["history"])
