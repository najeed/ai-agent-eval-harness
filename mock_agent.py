import sys
import json

def main():
    # Read from stdin
    try:
        line = sys.stdin.read().strip()
        if not line:
            return
        payload = json.loads(line)
    except Exception as e:
        print(json.dumps({"error": f"Invalid input: {str(e)}"}))
        return

    # Mock response: echo the task but say it's done
    task = payload.get("task_description", "No task provided")
    response = {
        "content": f"I have processed your request: '{task}'",
        "action": "final_answer",
        "summary": "Task completed successfully via local adapter."
    }

    # Write to stdout
    print(json.dumps(response))

if __name__ == "__main__":
    main()
