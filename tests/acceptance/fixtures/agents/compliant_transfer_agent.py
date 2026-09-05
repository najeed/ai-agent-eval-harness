#!/usr/bin/env python3
"""
Acceptance Test Agent: Compliant Transfer Agent.
Executes an authorized transfer within policy limits (200.0 USD <= 500.0 USD limit)
and marks the task complete.
"""

import json
import sys


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
