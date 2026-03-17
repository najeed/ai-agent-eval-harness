# Scenario: The Case of the Missing Refund

Customer Jane Doe is frustrated because she returned her item two weeks ago but hasn't seen a refund for Order #OM-5566.

## Objectives
- Locate the order and verify it was returned.
- Check the payment history to confirm no refund was issued.
- Process the full refund of $129.99.
- Send a personalized email apology to the customer.

## Tasks

### 1. Verification
- **Description**: Locate order #OM-5566 and check its status.
- **Tools**: `get_order_details`
- **Expected Outcome**: Order is found, status is "Returned", total is $129.99.

### 2. Financial Audit
- **Description**: Check the refund history for order #OM-5566.
- **Tools**: `get_refund_status`
- **Expected Outcome**: Confirm no refund has been processed yet.

### 3. Execution
- **Description**: Issue a full refund of $129.99.
- **Tools**: `issue_refund`
- **Expected Outcome**: Refund is successfully processed.

### 4. Communication
- **Description**: Notify Jane Doe (jane.doe@example.com) that her refund has been issued and apologize for the delay.
- **Tools**: `send_email_notification`
- **Expected Outcome**: Email is sent with the transaction details.
