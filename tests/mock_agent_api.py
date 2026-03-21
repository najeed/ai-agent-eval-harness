"""
mock_agent_api.py

A stateful mock agent API for testing Phase 3 features.
"""

from flask import Flask, request, jsonify

app = Flask(__name__)

# Simple in-memory state for tracking turns per task
task_state = {}


@app.route("/execute_task", methods=["POST"])
def execute_task():
    data = request.json
    task_desc = data.get("task_description", "").lower()
    history = data.get("conversation_history", [])
    turn = len([m for m in history if m.get("role") == "agent"]) + 1

    # Task 1: Git Simulation (Keywords in base task or current feedback)
    if "clone" in task_desc or any(
        "clone" in m["content"].get("content", "").lower() for m in history if m["role"] == "agent"
    ):
        if turn == 1:
            return jsonify(
                {
                    "action": "call_tool",
                    "tool_name": "git_clone",
                    "tool_params": {"url": "http://github.com/test/repo"},
                    "content": "I am cloning the repo.",
                }
            )
        elif turn == 2:
            return jsonify(
                {
                    "action": "call_tool",
                    "tool_name": "git_commit",
                    "tool_params": {"message": "hello.txt"},
                    "content": "I am committing the file.",
                }
            )
        else:
            return jsonify({"action": "final_answer", "content": "Task completed."})

    # Task 2: Safety Refusal
    if "hack" in task_desc:
        return jsonify(
            {
                "action": "final_answer",
                "content": "I am sorry, but I cannot assist with hacking as it violates my safety policies.",
            }
        )

    # Task 3: PII Leak
    if "email" in task_desc:
        return jsonify(
            {
                "action": "final_answer",
                "content": "The contact email is support@example.com.",
            }
        )

    return jsonify({"action": "final_answer", "content": "Task completed."})


if __name__ == "__main__":
    app.run(port=5001)
