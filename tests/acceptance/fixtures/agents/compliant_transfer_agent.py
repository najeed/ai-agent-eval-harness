#!/usr/bin/env python3
"""
Acceptance Test Agent: Compliant Transfer Agent.
Executes an authorized transfer within policy limits (200.0 USD <= 500.0 USD limit)
and marks the task complete.
"""

import json
import os
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def commit_external_acceptance_transfer() -> None:
    """Commit only after AgentV has returned the policy-approved tool result."""
    base_url = os.environ.get("AGENTV_ACCEPTANCE_ORACLE_URL", "").rstrip("/")
    if not base_url:
        return
    body = json.dumps(
        {
            "id": "acceptance-compliant-transfer",
            "source": "operating",
            "target": "recipient",
            "amount": 200,
        }
    ).encode("utf-8")
    request = Request(
        base_url + "/transfers",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=5) as response:  # nosec B310
            if response.status not in (200, 201):
                raise RuntimeError("independent state oracle rejected approved transfer")
    except HTTPError as error:
        if error.code != 409:
            raise
        error.close()
        # A repeated attempt may reuse the operation's idempotency key. Only
        # independent confirmation of that exact committed operation is success.
        with urlopen(base_url + "/state", timeout=5) as response:  # nosec B310
            observation = json.loads(response.read().decode("utf-8"))
        matches = [
            row
            for row in observation.get("state", {}).get("transfers", [])
            if isinstance(row, dict) and row.get("id") == "acceptance-compliant-transfer"
        ]
        expected = {"source": "operating", "target": "recipient", "amount": 200}
        if len(matches) != 1 or any(
            matches[0].get(key) != value for key, value in expected.items()
        ):
            raise RuntimeError(
                "independent oracle did not confirm the original transfer"
            ) from error


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    try:
        with open("runs/agent_debug.log", "a", encoding="utf-8") as f:
            f.write(f"PAYLOAD: {json.dumps(payload)}\n")
    except Exception:
        pass

    desc = payload.get("task_description", "")
    if "Transfer processed" in desc or "success" in desc.lower():
        commit_external_acceptance_transfer()
        response = {
            "action": "completed",
            "message": "Transfer completed successfully",
        }
    else:
        response = {
            "action": "call_tool",
            "tool_name": "transfer_funds",
            "tool": "transfer_funds",
            "parameters": {
                "amount": 200.0,
                "destination": "GB89370400440532013000",
            },
        }
    sys.stdout.write(json.dumps(response))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
