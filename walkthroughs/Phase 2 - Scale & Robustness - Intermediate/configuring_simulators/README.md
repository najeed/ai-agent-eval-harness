# README: Configuring Simulators (The Digital Twin)

Learn how to control the agent's world-state by toggling environmental shims and digital twins.

## 🎯 Objectives
- Understand the role of **Environmental Shims** in industrial evaluation.
- Learn how to use the `enabled_shims` config in a scenario.
- Toggle between **CRM (Customer Relationship Management)** and **DB (Database)** mock environments.

## 🚀 Steps

### Step 1: The Toggle Switch
Open `scenario_with_shims.json`. You'll notice a special configuration block:
```json
"config": {
  "enabled_shims": ["crm", "cloud_metadata"]
}
```
This tells the harness to only activate the CRM and Cloud simulators for this specific run, leaving the Database simulator neutralized.

### Step 2: Verify the Environment
Run the verification script to see how the shim configuration changes the agent's available tools:
```bash
python walkthroughs/Phase 2 - Scale & Robustness - Intermediate/configuring_simulators/verify_shims.py
```

### Step 3: Switch Worlds
Modify `scenario_with_shims.json` to change the `enabled_shims` to `["db"]`. Run the verification script again and notice how the CRM tools are now missing, replaced by Database operations.

## 📊 Key Concepts
- **Digital Twins**: Mock environments that simulate real-world systems for safe, reliable testing.
- **Shim Isolation**: Ensuring that agents only interact with the systems defined in their specific industrial test case.
- **NIST AI-100-1 Resilience**: By restricting shims, you test the agent's **Resilience** when its world-state is reduced or modified.

---
*Ready to play god with the agent's universe? Check out the [STORY.md](./STORY.md) next!*
