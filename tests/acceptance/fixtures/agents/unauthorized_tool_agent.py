#!/usr/bin/env python3
"""
Acceptance Test Agent: Unauthorized Tool Agent.
Attempts to execute a tool not declared in the scenario definition.
"""

import json
import sys


def main():
    try:
        raw = sys.stdin.read()
        _payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        _payload = {}

    response = {
        "action": "call_tool",
        "tool_name": "system_exec_privileged",
        "tool": "system_exec_privileged",
        "parameters": {
            "command": "rm -rf /",
        },
    }
    sys.stdout.write(json.dumps(response))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
