# STORY: The Twin Cities (Simulator Configuration)

Welcome back, Intermediate Lead. In this mission, you'll be controlling the **Digital Twin** environments that the agent lives in.

## 📖 The Narrative
The evaluation is split into two phases.
1.  **Phase I (CRM Alpha)**: The agent has full access to the CRM for customer records, but the Database is offline for maintenance.
2.  **Phase II (Database Beta)**: The CRM is taken offline for syncing, and the agent must use the direct Database records instead.

## 🏆 Your Task
Open `scenario_with_shims.json` and toggle the `enabled_shims` to match the mission phases.

- **Phase I**: Set `enabled_shims` to `["crm"]`.
- **Phase II**: Set `enabled_shims` to `["db"]`.

## 🏗️ Technical Backdrop
The harness's **Environment Driver** uses these shims to isolate the agent's world-state. By only enabling specific shims, you're performing a **Stress Test** on the agent's ability to adapt when its favorite tools are missing.

---
*Ready to master the digital world? Run the [verify_shims.py](./verify_shims.py) next!*
