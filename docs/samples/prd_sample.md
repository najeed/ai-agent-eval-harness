# PRD: Billing Dispute Resolution Agent

## Metadata
- **scenario_id**: billing_dispute_01
- **version**: 1.2
- **industry**: telecom
- **compliance_level**: Standard
- **agent_topology**:
    - **billing_agent**: writes to `billing:*`, reads from `customer:*`
    - **support_agent**: reads from `billing:balance`

---

## Scenario Overview
Evaluate an agent's ability to handle a complex billing dispute involving data overages and multi-agent coordination.

## Workflow

### 1. Identify Overcharge (`task-1`)
The agent should look up the customer's recent data usage and identify the $40 overage charge.
- **Expected Outcome:** Agent confirms the $40 overage in the conversation.
- **Tools**: `get_billing_history`, `get_usage_data`
- **Criteria**: `tool_call_correctness` (threshold: 1.0)

### 2. Verify Eligibility (`task-2`)
Check the customer's loyalty status and determine if they are eligible for a one-time waiver.
- **Expected Outcome:** Agent informs the customer they are eligible for a waiver.
- **Tools**: `get_customer_profile`
- **Criteria**: `policy_compliance` (threshold: 1.0)

### 3. Apply Waiver (`task-3`)
Apply the $40 credit to the customer's account.
- **Expected Outcome:** The account balance is reduced by $40.
- **Tools**: `apply_credit`
- **Criteria**: `state_verification` (path: `billing:balance`, value: 0)

## Edges
- from: "task-1" to: "task-2"
- from: "task-2" to: "task-3"

---

## Tools (Global)
- **get_billing_history**: {"max_limit": 10}
- **apply_credit**: {"max_limit": 500}

## Policies
- **Eligibility**: Customer must be active for > 12 months for waiver.
