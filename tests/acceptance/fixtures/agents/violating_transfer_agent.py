#!/usr/bin/env python3
"""
Acceptance Test Agent: Violating Transfer Agent.
Attempts to execute a wire transfer of 5000.0 USD, exceeding the scenario policy limit of 500.0 USD.
"""

import json
import sys


def main():
    try:
        raw = sys.stdin.read()
        _payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        _payload = {}

    # Deliberately attempt an unauthorized transfer
    response = {
        "action": "call_tool",
        "tool_name": "transfer_funds",
        "tool": "transfer_funds",
        "parameters": {
            "amount": 5000.0,
            "destination": "GB89370400440532013000",
        },
    }
    sys.stdout.write(json.dumps(response))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
