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


# --- Ecommerce Simulated Tools ---


def get_order_details(order_id):
    """Simulates looking up an order."""
    print(f"TOOL: Called get_order_details for ID: {order_id}")
    return {
        "status": "success",
        "order_id": order_id,
        "amount": 129.99,
        "status_label": "Returned",
    }


def get_refund_status(order_id):
    """Simulates checking refund status."""
    print(f"TOOL: Called get_refund_status for ID: {order_id}")
    return {"status": "success", "order_id": order_id, "refund_issued": False}


def issue_refund(order_id, amount):
    """Simulates processing a refund."""
    print(f"TOOL: Called issue_refund for ID: {order_id}, Amount: {amount}")
    return {
        "status": "success",
        "order_id": order_id,
        "refund_amount": amount,
        "transaction_id": "TXN_778899",
    }


def send_email_notification(email, message):
    """Simulates sending an email."""
    print(f"TOOL: Called send_email_notification to: {email}")
    return {"status": "success", "recipient": email}


# --- Healthcare/Insurance Simulated Tools ---


def get_provider_record(auth_code):
    """Simulates fetching a healthcare provider record."""
    print(f"TOOL: Called get_provider_record for: {auth_code}")
    return {
        "status": "success",
        "auth_code": auth_code,
        "auth_status": "Pending",
        "provider": "General Hospital",
    }


def check_insurance_authorization(auth_code):
    """Simulates checking insurance payer status."""
    print(f"TOOL: Called check_insurance_authorization for: {auth_code}")
    return {
        "status": "success",
        "auth_code": auth_code,
        "auth_status": "Denied",
        "reason": "Incomplete Documentation",
    }


def submit_claim_correction(auth_code, updates):
    """Simulates submitting a correction to insurance."""
    print(f"TOOL: Called submit_claim_correction for: {auth_code}")
    return {"status": "success", "auth_code": auth_code, "new_status": "Under Review"}


def send_patient_update(email, message):
    """Simulates notifying the patient."""
    print(f"TOOL: Called send_patient_update to: {email}")
    return {"status": "success", "recipient": email}


# --- 3. Core Agent Logic ---
# This is the "brain" of our agent. It decides which tool to use based on keywords
# in the task description it receives from the MultiAgentEval.


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
        if (
            "tools returned" in task_desc
            or "modem is receiving full speed" in task_desc
        ):
            print("AGENT: Decided that task is complete.")
            agent_response = {
                "action": "final_answer",
                "summary": "The diagnostic tests are complete. I have identified the customer and verified the connection status.",
                "name": "Luna-Sample-Agent",
            }

        elif "identify the customer" in task_desc and "speed tier" in task_desc:
            print("AGENT: Decided to use 'get_customer_details'")
            tool_result = get_customer_details(customer_id)
            agent_response = {
                "action": "call_tool",
                "tool_name": "get_customer_details",
                "tool_params": {"customer_id": customer_id},
                "tool_output": tool_result,
                "summary": f"Identified customer {tool_result['customer_name']} on plan {tool_result['plan']}.",
                "name": "Luna-Sample-Agent",
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
                "name": "Luna-Sample-Agent",
            }

        elif "guide them to run a speed test" in task_desc and "ethernet" in task_desc:
            print("AGENT: Decided to provide instructions.")
            agent_response = {
                "action": "provide_instructions",
                "instructions": "Please connect your computer directly to the router with an Ethernet cable and run a speed test at example-speedtest.com.",
                "name": "Luna-Sample-Agent",
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
                "name": "Luna-Sample-Agent",
            }

        # --- Ecommerce Logic ---

        elif "locate order" in task_desc and "check its status" in task_desc:
            print("AGENT: Decided to use 'get_order_details'")
            tool_result = get_order_details("OM-5566")
            agent_response = {
                "action": "call_tool",
                "tool_name": "get_order_details",
                "tool_params": {"order_id": "OM-5566"},
                "tool_output": tool_result,
                "summary": f"Order #OM-5566 found with status '{tool_result['status_label']}' and amount ${tool_result['amount']}.",
                "name": "Luna-Sample-Agent",
            }

        elif "check the refund history" in task_desc:
            print("AGENT: Decided to use 'get_refund_status'")
            tool_result = get_refund_status("OM-5566")
            agent_response = {
                "action": "call_tool",
                "tool_name": "get_refund_status",
                "tool_params": {"order_id": "OM-5566"},
                "tool_output": tool_result,
                "summary": "Confirmed that no refund has been processed for order #OM-5566.",
                "name": "Luna-Sample-Agent",
            }

        elif "issue a full refund" in task_desc:
            print("AGENT: Decided to use 'issue_refund'")
            tool_result = issue_refund("OM-5566", 129.99)
            agent_response = {
                "action": "call_tool",
                "tool_name": "issue_refund",
                "tool_params": {"order_id": "OM-5566", "amount": 129.99},
                "tool_output": tool_result,
                "summary": "Successfully issued a full refund of $129.99 for order #OM-5566.",
                "name": "Luna-Sample-Agent",
            }

        elif "notify jane doe" in task_desc:
            print("AGENT: Decided to use 'send_email_notification'")
            tool_result = send_email_notification(
                "jane.doe@example.com",
                "Your refund for order #OM-5566 has been processed.",
            )
            agent_response = {
                "action": "call_tool",
                "tool_name": "send_email_notification",
                "tool_params": {
                    "email": "jane.doe@example.com",
                    "message": "Your refund for order #OM-5566 has been processed.",
                },
                "tool_output": tool_result,
                "summary": "Notified the customer jane.doe@example.com about the refund and apologized for the delay.",
                "name": "Luna-Sample-Agent",
            }

        # --- Healthcare/Insurance Logic ---

        elif "fetch authorization auth-99" in task_desc:
            print("AGENT: Decided to use 'get_provider_record'")
            tool_result = get_provider_record("AUTH-99")
            # Handle angry persona sub-context if present
            summary = f"Retrieved AUTH-99 from general hospital. Status is {tool_result['auth_status']}."
            if "yelling" in task_desc:
                summary = "I have professionally de-escalated the yelling patient and retrieved the AUTH-99 record from General Hospital as requested."

            agent_response = {
                "action": "call_tool",
                "tool_name": "get_provider_record",
                "tool_params": {"auth_code": "AUTH-99"},
                "tool_output": tool_result,
                "summary": summary,
                "name": "Luna-Sample-Agent",
            }

        elif "query the insurance payer's database" in task_desc:
            print("AGENT: Decided to use 'check_insurance_authorization'")
            tool_result = check_insurance_authorization("AUTH-99")
            agent_response = {
                "action": "call_tool",
                "tool_name": "check_insurance_authorization",
                "tool_params": {"auth_code": "AUTH-99"},
                "tool_output": tool_result,
                "summary": f"Insurance audit complete. AUTH-99 is {tool_result['auth_status']} due to {tool_result['reason']}.",
                "name": "Luna-Sample-Agent",
            }

        elif "propose a 'correction request'" in task_desc:
            print("AGENT: Decided to use 'submit_claim_correction'")
            tool_result = submit_claim_correction(
                "AUTH-99", {"reason": "Data Reconciled"}
            )
            agent_response = {
                "action": "call_tool",
                "tool_name": "submit_claim_correction",
                "tool_params": {
                    "auth_code": "AUTH-99",
                    "updates": {"reason": "Data Reconciled"},
                },
                "tool_output": tool_result,
                "summary": "Successfully submitted a claim correction for AUTH-99. Status is now 'Under Review'.",
                "name": "Luna-Sample-Agent",
            }

        elif (
            "notify john smith" in task_desc or "notify the angry patient" in task_desc
        ):
            print("AGENT: Decided to use 'send_patient_update'")
            tool_result = send_patient_update(
                "john.smith@example.com", "Your claim correction has been submitted."
            )
            summary = "Notified John Smith about the claim correction."
            if "threatened to post a negative viral review" in task_desc:
                summary = "Provided an extremely apologetic and professional update to the patient, preventing the negative review and confirming the correction status."

            agent_response = {
                "action": "call_tool",
                "tool_name": "send_patient_update",
                "tool_params": {
                    "email": "john.smith@example.com",
                    "message": "Your claim correction has been submitted.",
                },
                "tool_output": tool_result,
                "summary": summary,
                "name": "Luna-Sample-Agent",
            }

        else:
            print("AGENT: No matching rule found for this task.")
            agent_response = {
                "action": "error",
                "summary": "I'm sorry, I don't know how to handle that task.",
                "name": "Luna-Sample-Agent",
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
