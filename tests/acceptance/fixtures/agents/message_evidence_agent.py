"""Execute a message-only acceptance task through the real local agent protocol."""

import json
import sys


def main():
    request = json.load(sys.stdin)
    if "Confirm evidence acceptance" not in request.get("task_description", ""):
        raise ValueError("Unexpected evidence acceptance task")
    json.dump({"action": "completed", "message": "Evidence acceptance completed"}, sys.stdout)


if __name__ == "__main__":
    main()
