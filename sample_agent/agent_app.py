# agent_app.py
# A simple, rule-based AI agent simulator using the Flask web framework.
# This agent is designed to handle the "Home Internet Troubleshooting - Slow Speed" scenario.

from flask import Flask, request, jsonify

# --- 1. Agent Setup ---
# Initialize the Flask application
app = Flask(__name__)

# --- 2. Simulated Tools ---
# In a real agent, these functions would make API calls to actual backend systems.
# Here, we simulate them to return predictable results for our test scenario.


def get_customer_details(customer_id):
    """Simulates looking up a customer and their service plan."""
    print(f"TOOL: Called get_customer_details for ID: {customer_id}")
    return {"status": "success", "customer_name": "Jane Doe", "plan": "100 Mbps Fiber"}


def run_line_test(customer_id):
    """Simulates running a remote line test."""
    print(f"TOOL: Called run_line_test for ID: {customer_id}")
    return {"status": "success", "line_quality": "Excellent", "connection": "Stable"}


def run_remote_speed_test(customer_id):
    """Simulates running a speed test to the customer's modem."""
    print(f"TOOL: Called run_remote_speed_test for ID: {customer_id}")
    return {
        "status": "success",
        "download_speed_mbps": 102.5,
        "upload_speed_mbps": 21.3,
    }


def provide_wifi_optimization_guide(customer_id):
    """Simulates providing a link to a help article."""
    print(f"TOOL: Called provide_wifi_optimization_guide for ID: {customer_id}")
    return {"status": "success", "guide_url": "http://example.com/wifi-help"}


# --- 3. Core Agent Logic ---
# This is the "brain" of our agent. It decides which tool to use based on keywords
# in the task description it receives from the evaluation harness.


@app.route("/execute_task", methods=["POST"])
def execute_task():
    """
    This is the main API endpoint for the agent.
    It receives a task description and returns the action it decides to take.
    """
    try:
        data = request.get_json()
        if not data or "task_description" not in data:
            return jsonify({"error": "Missing 'task_description' in request body"}), 400

        task_desc = data["task_description"].lower()
        customer_id = data.get("customer_id", "cust_123")  # Use a default customer ID

        print(f"\nAGENT: Received task: '{task_desc}'")

        # Rule-based decision logic
        if "identify the customer" in task_desc and "speed tier" in task_desc:
            print("AGENT: Decided to use 'get_customer_details'")
            tool_result = get_customer_details(customer_id)
            agent_response = {
                "action": "call_tool",
                "tool_name": "get_customer_details",
                "tool_params": {"customer_id": customer_id},
                "tool_output": tool_result,
                "summary": f"Identified customer {tool_result['customer_name']} on plan {tool_result['plan']}.",
            }

        elif "run a remote line test" in task_desc and "speed test" in task_desc:
            print("AGENT: Decided to use 'run_line_test' and 'run_remote_speed_test'")
            line_result = run_line_test(customer_id)
            speed_result = run_remote_speed_test(customer_id)
            agent_response = {
                "action": "call_multiple_tools",
                "tool_names": ["run_line_test", "run_remote_speed_test"],
                "tool_outputs": [line_result, speed_result],
                "summary": f"Remote diagnostics complete. Modem is receiving full speed ({speed_result['download_speed_mbps']} Mbps).",
            }

        elif "guide them to run a speed test" in task_desc and "ethernet" in task_desc:
            print("AGENT: Decided to provide instructions.")
            agent_response = {
                "action": "provide_instructions",
                "instructions": "Please connect your computer directly to the router with an Ethernet cable and run a speed test at example-speedtest.com.",
            }

        elif "recommend wi-fi optimization steps" in task_desc:
            print("AGENT: Decided to use 'provide_wifi_optimization_guide'")
            tool_result = provide_wifi_optimization_guide(customer_id)
            agent_response = {
                "action": "call_tool",
                "tool_name": "provide_wifi_optimization_guide",
                "tool_params": {"customer_id": customer_id},
                "tool_output": tool_result,
                "summary": f"The issue is likely with local Wi-Fi. I have provided a guide for optimization steps: {tool_result['guide_url']}",
            }

        else:
            print("AGENT: No matching rule found for this task.")
            agent_response = {
                "action": "error",
                "summary": "I'm sorry, I don't know how to handle that task.",
            }

        return jsonify(agent_response), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- 4. Run the Application ---
# This allows you to run the agent locally for testing before deploying.
# To run locally: python agent_app.py
if __name__ == "__main__":
    # Note: host='0.0.0.0' makes it accessible on your local network
    app.run(host="0.0.0.0", port=5001, debug=True)
