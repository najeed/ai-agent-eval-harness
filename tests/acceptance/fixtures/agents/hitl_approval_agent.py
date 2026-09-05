#!/usr/bin/env python3
"""
Acceptance Test Agent: HITL Approval Agent.
Pauses for human approval on actions requiring authorization.
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
        "action": "hitl_pause",
        "reason": "Approval required for international wire transfer",
    }
    sys.stdout.write(json.dumps(response))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
