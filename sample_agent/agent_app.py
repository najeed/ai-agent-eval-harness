from __future__ import annotations

import threading
from typing import Any

from flask import Flask, jsonify, request

app = Flask(__name__)

AGENT_NAME = "Luna-Sample-Agent"


class AgentState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.consistency_attempts = 0

    def reset(self) -> None:
        with self.lock:
            self.consistency_attempts = 0

    def consistency_attempt(self) -> int:
        with self.lock:
            self.consistency_attempts += 1
            return self.consistency_attempts


STATE = AgentState()


def final(summary: str) -> dict[str, Any]:
    return {
        "action": "final_answer",
        "summary": summary,
        "name": AGENT_NAME,
    }


def call_tool(
    tool_name: str,
    params: dict[str, Any] | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    return {
        "action": "call_tool",
        "tool_name": tool_name,
        "tool_params": params or {},
        "summary": summary or f"Calling {tool_name}.",
        "name": AGENT_NAME,
    }


def fail(summary: str) -> dict[str, Any]:
    return {
        "action": "error",
        "summary": summary,
        "name": AGENT_NAME,
    }


def task_text(data: dict[str, Any]) -> str:
    return str(data.get("task_description", "")).strip().lower()


def history_text(data: dict[str, Any]) -> str:
    return str(data.get("conversation_history", [])).lower()


def quickstart(task: str, history: str, customer_id: str) -> dict[str, Any] | None:
    if "identify the customer" in task and "speed tier" in task:
        if "get_customer_details" in history:
            return final("I have identified the customer as Jane Doe on a 100 Mbps Fiber plan.")
        return call_tool(
            "get_customer_details",
            {"customer_id": customer_id},
            "Identifying customer and plan details.",
        )

    if "run a remote line test" in task and "speed test" in task:
        if "run_remote_speed_test" in history:
            return final(
                "Remote diagnostics confirm the modem is receiving the full 100 Mbps speed."
            )
        return call_tool(
            "run_remote_speed_test",
            {"customer_id": customer_id},
            "Executing remote diagnostics.",
        )

    if "guide them to run a speed test" in task and "ethernet" in task:
        return final(
            "I have guided the customer to perform a local speed test via Ethernet "
            "to isolate the Wi-Fi issue. 100 Mbps detected at modem."
        )

    if "recommend wi-fi optimization steps" in task:
        return final(
            "The issue is local Wi-Fi. I have provided the optimization guide at "
            "http://example.com/wifi-help."
        )

    return None


def golden(task: str, history: str) -> dict[str, Any] | None:

    if "initialize the workflow" in task:
        STATE.reset()
        return final("INITIALIZED")

    if "perform the customer risk assessment" in task:
        if "risk_assess" in history:
            return final("APPROVE")
        return call_tool(
            "risk_assess",
            {"customer_id": "CUST-10042", "score": 0.18},
            "Running risk assessment.",
        )

    if "fan out into independent identity and balance" in task:
        return final("PARALLEL_FANOUT")

    if "validate the customer identity" in task:
        if "customer_read" in history:
            return final("IDENTITY_VALID")
        return call_tool(
            "customer_read",
            {"customer_id": "CUST-10042"},
            "Validating customer identity.",
        )

    if "validate that the account balance" in task:
        if "ledger_read" in history:
            return final("BALANCE_VALID")
        return call_tool(
            "ledger_read",
            {"account_id": "ACCT-90017"},
            "Validating account balance.",
        )

    if "converge the identity and balance" in task:
        return final("VALIDATIONS_JOINED")

    if "route the approved risk decision" in task:
        return final("RISK_ROUTE_APPROVED")

    if "reserve 5000 usd" in task:
        if "ledger_write" in history:
            return final("RESERVED_5000")
        return call_tool(
            "ledger_write",
            {
                "operation": "reserve",
                "account_id": "ACCT-90017",
                "amount": 5000.0,
            },
            "Reserving 5000 USD.",
        )

    if "verify authorization" in task:
        if "authorization_check" in history:
            return final("AUTHORIZED")
        return call_tool(
            "authorization_check",
            {
                "resource": "ACCT-90017",
                "operation": "read",
            },
            "Verifying authorization.",
        )

    if "perform consistency validation" in task:
        attempt = STATE.consistency_attempt()

        if attempt == 1:
            return call_tool(
                "consistency_check",
                {"attempt": attempt},
                "Performing consistency validation.",
            )

        return final("CONSISTENT")

    if "attempt the final ledger commit" in task:
        return call_tool(
            "ledger_commit",
            {
                "account_id": "ACCT-90017",
                "amount": 5000.0,
            },
            "Attempting final ledger commit.",
        )

    if "handle the ledger commit failure" in task:
        return call_tool(
            "state_write",
            {
                "shared_write": {
                    "path": "workflow:recovery_required",
                    "value": True,
                }
            },
            "Recording recovery requirement.",
        )

    if "compensate the reserved funds" in task:
        return call_tool(
            "rollback_reservation",
            {
                "account_id": "ACCT-90017",
                "amount": 5000.0,
            },
            "Compensating the reservation.",
        )

    if "execute a deliberately slow validation" in task:
        return call_tool(
            "latency_probe",
            {"delay_seconds": 1.0},
            "Executing deliberately slow validation.",
        )

    if "handle the timeout" in task:
        return call_tool(
            "state_write",
            {
                "shared_write": {
                    "path": "workflow:timeout_handled",
                    "value": True,
                }
            },
            "Recording timeout recovery.",
        )

    if "evaluate the final governance gate" in task:
        return final("GOVERNANCE_PASS")

    if "confirm the recovered workflow" in task:
        return final("GOLDEN_SCENARIO_PASS")

    return None


@app.get("/health")
def health() -> Any:
    return jsonify(
        {
            "status": "ok",
            "agent": AGENT_NAME,
        }
    )


@app.post("/reset")
def reset() -> Any:
    STATE.reset()
    return jsonify({"status": "reset"})


@app.post("/execute_task")
def execute_task() -> Any:
    try:
        data = request.get_json(silent=True) or {}

        if not isinstance(data.get("task_description"), str):
            return (
                jsonify({"error": "Missing required field: task_description"}),
                400,
            )

        task = task_text(data)
        history = history_text(data)
        customer_id = data.get("customer_id", "CUST-101")

        result = quickstart(task, history, customer_id)

        if result is None:
            result = golden(task, history)

        if result is None:
            result = fail(f"Unsupported task: {data['task_description']}")

        return jsonify(result), 200

    except Exception as exc:
        return jsonify(
            {
                "action": "error",
                "summary": str(exc),
                "name": AGENT_NAME,
            }
        ), 500


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5001,
        debug=False,
        threaded=True,
    )
