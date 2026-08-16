# GitHub Security & Branch Protection Baseline (SOC 2 CC6.1 / CC8.1)

## 1. Overview
This document defines the formal repository security controls and branch protection rulesets enforced for `najeed/ai-agent-eval-harness` to satisfy SOC 2 Trust Services Criteria for Access Control (**CC6.1**) and Change Management (**CC8.1**).

---

## 2. Default Branch Protection Ruleset (`main`)

### 2.1 Branch Ruleset Configuration
- **Target Branch**: `main` (Default)
- **Enforcement Status**: Active / Mandatory

### 2.2 Pull Request Controls (CC8.1)
- [x] **Require a pull request before merging**: Enforced
- [x] **Required approvals**: Minimum 1 peer review approval from designated code owners (`.github/CODEOWNERS`)
- [x] **Dismiss stale pull request approvals when new commits are pushed**: Enabled
- [x] **Require review from Code Owners**: Enabled
- [x] **Require conversation resolution before merging**: Enabled

### 2.3 Status Check Gates (CC8.1)
- [x] **Require status checks to pass before merging**: Enforced
- [x] **Require branches to be up to date before merging**: Enabled
- **Mandatory Status Check Jobs**:
  - `CI / Lint & Type Check (flake8, black, isort, mypy)`
  - `CI / Unit & Integration Tests (pytest)`
  - `CI / Mutation Testing Sentinel (run_mutation_tests.py)`
  - `CI / Security & Vulnerability Scan (Bandit, Safety)`

### 2.4 Administrative Overrides & History Protection
- [x] **Do not allow bypassing the above settings**: Enabled (Enforced for repository administrators)
- [x] **Block force pushes**: Enabled (`--force` and `--force-with-lease` rejected)
- [x] **Block branch deletion**: Enabled
- [x] **Require signed commits**: Enabled (GPG / SSH / S/MIME commit signing)

---

## 3. Organization-Wide Access & Authentication Controls (CC6.1)

### 3.1 Multi-Factor Authentication (MFA)
- **Organization Policy**: Mandatory two-factor authentication (2FA/MFA) enforced for all organization members, contributors, and service accounts.
- **Audit Cadence**: Continuous via GitHub Audit Log API.

### 3.2 Audit Log Retention & Ingestion
- **Audit Log Status**: Enabled org-wide with automated streaming to compliance SIEM.
- **Monitored Events**:
  - `repo.create`, `repo.destroy`, `repo.access`
  - `protected_branch.policy_override`
  - `org.add_member`, `org.remove_member`, `org.2fa_disabled`
  - `secret_scanning_alert.created`, `dependabot_alert.created`

### 3.3 Automated Dependency & Secret Scanning
- **Dependabot Alerts & Security Updates**: Active
- **Secret Scanning with Push Protection**: Active
