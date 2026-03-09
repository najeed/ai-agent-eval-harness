# PRD: Billing Dispute Resolution Agent

**Industry:** telecom
**Use Case:** customer_service
**Core Function:** billing

## Scenario Overview
Evaluate an agent's ability to handle a complex billing dispute involving data overages and multi-agent coordination.

## Tasks

### 1. Identify Overcharge
The agent should look up the customer's recent data usage and identify the $40 overage charge.
- **Expected Outcome:** Agent confirms the $40 overage in the conversation.
- **Tools:** `get_billing_history`, `get_usage_data`

### 2. Verify Eligibility
Check the customer's loyalty status and determine if they are eligible for a one-time waiver.
- **Expected Outcome:** Agent informs the customer they are eligible for a waiver.
- **Tools:** `get_customer_profile`
- **Criteria:** `policy_compliance` (threshold: 1.0)

### 3. Apply Waiver
Apply the $40 credit to the customer's account.
- **Expected Outcome:** The account balance is reduced by $40.
- **Tools:** `apply_credit`
- **Criteria:** `state_verification` (path: `billing:balance`, value: 0)

## Agent Topology
- **billing_agent:** writes to `billing:*`, reads from `customer:*`
- **support_agent:** reads from `billing:balance`

## Policies
- **apply_credit:** {"max_limit": 500}
- **get_billing_history:** {"max_limit": 10}
