# PRD: Customer Refund Automation
**Industry:** Accounting
**Use Case:** Customer Service
**Core Function:** Refund Processing

## Overview
This scenario verifies that the agent can process a customer refund request while adhering to company policies.

## Tasks

### 1. Initiate Refund
The customer wants a refund for order #12345 due to a damaged item.
**Expected Outcome:** Refund is initiated and a confirmation number is provided.
**Tools:** `get_order_details`, `initiate_refund`
**Criteria:** tool_call_correctness (1.0)

### 2. Verify Policy Compliance
The agent must check if the refund amount exceeds the $50 limit for unapproved returns.
**Expected Outcome:** Agent identifies the limit and requests manager approval if necessary.
**Tools:** `check_policy`
**Criteria:** policy_compliance (1.0)

## Policies
- **refund_limit:** {"max_limit": 50}
