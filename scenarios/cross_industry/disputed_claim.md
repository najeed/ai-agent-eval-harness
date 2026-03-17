# Scenario: The Disputed Claim (Healthcare & Insurance)

A patient (John Smith) has a high-value surgery scheduled, but the Healthcare Provider and the Insurance Payer have conflicting records regarding the "Prior Authorization" code (AUTH-99).

## Objectives
- Fetch the authorization record from the Healthcare system.
- Cross-reference with the Insurance policy database.
- Negotiate a resolution or identify the specific data mismatch.
- Document the resolution in both systems.

## Tasks

### 1. Data Retrieval (Healthcare)
- **Description**: Fetch authorization AUTH-99 from the Healthcare Provider's API.
- **Tools**: `get_provider_record`
- **Expected Outcome**: Record found with code AUTH-99, status "Pending".

### 2. Discrepancy Analysis (Insurance)
- **Description**: Query the Insurance Payer's database for AUTH-99.
- **Tools**: `check_insurance_authorization`
- **Expected Outcome**: Record shows AUTH-99 is marked as "Denied" due to "Incomplete Documentation".

### 3. Conflict Resolution
- **Description**: Reconcile the records and propose a "Correction Request" to the Insurance system.
- **Tools**: `submit_claim_correction`
- **Expected Outcome**: Correction submitted, status updated to "Under Review".

### 4. Patient Transparency
- **Description**: Notify John Smith (john.smith@example.com) about the current status and the expected resolution timeline.
- **Tools**: `send_patient_update`
- **Expected Outcome**: Email sent to patient explaining the administrative correction.
