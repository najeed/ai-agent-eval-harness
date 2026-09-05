"""
tests.acceptance.support.trace_reader
Authoritative reader and event parser for AgentV run.jsonl execution traces.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class TraceReader:
    """Parses and extracts structured facts from AgentV execution traces (run.jsonl)."""

    def __init__(self, trace_path: str | Path):
        self.trace_path = Path(trace_path).resolve()
        self.events: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not self.trace_path.exists():
            return
        with open(self.trace_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    self.events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    @property
    def run_end_event(self) -> dict[str, Any] | None:
        """Return the terminal run_end event if present."""
        for ev in reversed(self.events):
            if ev.get("event") == "run_end":
                return ev
        return None

    @property
    def execution_status(self) -> str:
        """Resolve overall execution status from run_end event."""
        ev = self.run_end_event
        if ev:
            return str(ev.get("status", "unknown"))
        return "incomplete"

    @property
    def policy_decisions(self) -> list[dict[str, Any]]:
        """
        Extract all policy decision events and tool-call policy evaluations from the trace.
        """
        decisions: list[dict[str, Any]] = []
        for ev in self.events:
            ev_type = ev.get("event", "")
            # Direct policy_violation event
            if ev_type == "policy_violation":
                decisions.append(
                    {
                        "decision": "BLOCK",
                        "policy_id": ev.get("policy_id"),
                        "reason": ev.get("reason", ev.get("violation")),
                        "event": ev,
                    }
                )
            # HITL intervention event
            elif ev_type == "hitl_pause":
                decisions.append(
                    {
                        "decision": "REQUIRE_HITL",
                        "policy_id": "human_intervention_required",
                        "reason": ev.get("prompt", "Human intervention required."),
                        "event": ev,
                    }
                )
            # Tool result with policy_violation status or unregistered tool rejection
            elif ev_type in ("tool_result", "tool_call_result"):
                res = ev.get("result", {})
                if isinstance(res, dict):
                    err_code = str(res.get("error_code", "")).upper()
                    st = str(res.get("status", "")).lower()
                    if st in ("policy_violation", "blocked", "forbidden") or err_code in (
                        "UNREGISTERED_TOOL",
                        "UNAUTHORIZED_TOOL",
                        "POLICY_VIOLATION",
                        "TOOL_NOT_FOUND",
                    ):
                        decisions.append(
                            {
                                "decision": "BLOCK",
                                "policy_id": res.get("policy_id") or err_code,
                                "reason": res.get(
                                    "violation", res.get("reason", res.get("message"))
                                ),
                                "event": ev,
                            }
                        )
            # Tool call events
            elif ev_type == "tool_call":
                if ev.get("policy_decision"):
                    dec = ev.get("policy_decision").upper()
                    decisions.append(
                        {
                            "decision": dec,
                            "policy_id": ev.get("policy_id"),
                            "reason": ev.get("reason"),
                            "event": ev,
                        }
                    )
        return decisions

    @property
    def state_snapshots(self) -> list[dict[str, Any]]:
        """Extract recorded state snapshots."""
        snapshots = []
        for ev in self.events:
            if ev.get("event") in ("state_snapshot", "state_change", "parity_check"):
                snapshots.append(ev)
        return snapshots

    @property
    def certificate_issued(self) -> bool:
        """Check whether verification_certificate_issued event is present."""
        return any(ev.get("event") == "verification_certificate_issued" for ev in self.events)


__all__ = ["TraceReader"]
