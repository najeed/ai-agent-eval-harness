from flask import Flask, jsonify, request

# --- 1. Agent Setup ---
app = Flask(__name__)

# --- 2. Simulated Tools ---


def get_customer_details(customer_id):
    print(f"TOOL: Called get_customer_details for ID: {customer_id}")
    return {"status": "success", "customer_name": "Jane Doe", "plan": "100 Mbps Fiber"}


def run_remote_speed_test(customer_id):
    print(f"TOOL: Called run_remote_speed_test for ID: {customer_id}")
    return {
        "status": "success",
        "download_speed_mbps": 102.5,
        "upload_speed_mbps": 21.3,
    }


def provide_wifi_optimization_guide(customer_id):
    print(f"TOOL: Called provide_wifi_optimization_guide for ID: {customer_id}")
    return {"status": "success", "guide_url": "http://example.com/wifi-help"}


# --- 3. Main Action-Based Protocol Loop ---


@app.route("/execute_task", methods=["POST"])
def execute_task():
    """
    Industrialized Task Execution Loop.
    Supports AES v1.4.1 action-based protocol with state awareness.
    """
    try:
        data = request.json or {}
        task_desc = data.get("task_description")
        if task_desc is None:
            return jsonify({"error": "Missing required field: task_description"}), 400

        task_desc = task_desc.lower().strip()
        history = data.get("conversation_history", [])
        customer_id = data.get("customer_id", "CUST-101")

        print(f"AGENT: Received task request: {task_desc}")

        # Helper: Check if a tool has already been called and returned data in this session
        def is_tool_result_available(tool_name_substring):
            for msg in history:
                if msg.get("role") == "agent" and "action" in msg.get("content", ""):
                    # In a real agent, we'd parse the JSON content, but for the simulator
                    # we look for the tool name in the history trace.
                    content = str(msg.get("content"))
                    if tool_name_substring in content:
                        return True
            return False

        # --- Telecom Logic (Industrial Quickstart) ---

        if "identify the customer" in task_desc and "speed tier" in task_desc:
            if is_tool_result_available("get_customer_details"):
                agent_response = {
                    "action": "final_answer",
                    "summary": (
                        "I have identified the customer as Jane Doe on a 100 Mbps Fiber plan."
                    ),
                    "name": "Luna-Sample-Agent",
                }
            else:
                agent_response = {
                    "action": "call_tool",
                    "tool_name": "get_customer_details",
                    "tool_params": {"customer_id": customer_id},
                    "summary": "Identifying customer and plan details.",
                    "name": "Luna-Sample-Agent",
                }

        elif "run a remote line test" in task_desc and "speed test" in task_desc:
            if is_tool_result_available("run_remote_speed_test"):
                agent_response = {
                    "action": "final_answer",
                    "summary": (
                        "Remote diagnostics confirm the modem is receiving the full 100 Mbps speed."
                    ),
                    "name": "Luna-Sample-Agent",
                }
            else:
                agent_response = {
                    "action": "call_tool",
                    "tool_name": "run_remote_speed_test",
                    "tool_params": {"customer_id": customer_id},
                    "summary": "Executing remote diagnostics.",
                    "name": "Luna-Sample-Agent",
                }

        elif "guide them to run a speed test" in task_desc and "ethernet" in task_desc:
            # This is an instruction-only task, so we can return final_answer immediately
            agent_response = {
                "action": "final_answer",
                "summary": (
                    "I have guided the customer to perform a local speed test via Ethernet "
                    "to isolate the Wi-Fi issue. 100 Mbps detected at modem."
                ),
                "name": "Luna-Sample-Agent",
            }

        elif "recommend wi-fi optimization steps" in task_desc:
            # This is the final step
            agent_response = {
                "action": "final_answer",
                "summary": "The issue is local Wi-Fi. I have provided the optimization guide at http://example.com/wifi-help.",
                "name": "Luna-Sample-Agent",
            }

        # --- Fallback ---

        else:
            print("AGENT: No matching rule found. Defaulting to final_answer.")
            agent_response = {
                "action": "final_answer",
                "summary": "Task processed via industrial fallback logic.",
                "name": "Luna-Sample-Agent",
            }

        return jsonify(agent_response), 200

    except Exception as e:
        print(f"AGENT ERROR: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
