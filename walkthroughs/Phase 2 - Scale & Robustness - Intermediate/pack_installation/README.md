# README: Pack Installation

Learn how to safely deploy curated industrial benchmarks using the `install-pack` system.

## 🎯 Objectives
- Install a benchmark "Flavor" (e.g., `telecom`).
- Understand how versioning (`@1.2.3`) is handled.
- Witness the automated **Archiving** of legacy packs.

## 🚀 Steps

### Step 1: Deploy the First Pack
We'll start by installing the base `telecom` industrial suite.
```bash
python walkthroughs/Phase 2 - Scale & Robustness - Intermediate/pack_installation/Step_1_Install_Benchmarks.py
```

### Step 2: The Version Upgrade
Now, we'll "upgrade" to a specific version. This will trigger the harness's safety logic.
```bash
python walkthroughs/Phase 2 - Scale & Robustness - Intermediate/pack_installation/Step_2_Upgrade_and_Archive.py
```

### Step 3: Inspect the Vault
After the upgrade, look for the hidden `.archived/` directory in your project root. You'll see your previous benchmarks safely tucked away with a timestamp.

## 📊 Key Concepts
- **Atomic Indexing**: When a pack is installed, the `ScenarioCatalog` automatically re-indexes everything so the new benchmarks are immediately available to the `list` command.
- **Flavors**: Industrial standards often have variations (e.g., `FINRA-Basic` vs `FINRA-Full`). The `install-pack` command supports these as independent flavors.

---
*Ready to deploy the cargo? Run the [Step_1_Install_Benchmarks.py](./Step_1_Install_Benchmarks.py) script next!*








