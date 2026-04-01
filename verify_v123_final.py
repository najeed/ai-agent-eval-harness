import os
import sys
from dotenv import load_dotenv

# Absolute Top: Environment Portability (R6)
load_dotenv()

from eval_runner import config
from eval_runner.catalog import ScenarioCatalog
from eval_runner.plugins import manager
from eval_runner.simulators import get_simulator_registry
from eval_runner.console.app import create_app

def final_verification():
    print("--- [v1.2.3-FINAL] Authoritative Corrective Audit ---")
    
    # 1. Audit: Scenario Catalog (RLock + Relative Path Logic)
    print("1. Auditing Scenario Catalog...")
    catalog = ScenarioCatalog.get_instance()
    # Explicitly reload to catch the new relative-path logic
    catalog.load_index()
    count = len(catalog.scenarios)
    print(f"   [Result] Scenario Count: {count}")
    
    # 2. Audit: Plugin Manager (Hydration)
    print("2. Auditing Plugin Manager...")
    manager.load_plugins()
    agent_count = len(manager.plugins)
    print(f"   [Result] Agents Registered: {agent_count}")

    # 3. Audit: Simulator Registry
    print("3. Auditing Simulator Registry...")
    shims = get_simulator_registry()
    shim_count = len(shims)
    print(f"   [Result] World Shims: {shim_count}")

    # 4. End-to-End API Mock
    print("4. Auditing API Boundary...")
    app = create_app()
    with app.test_client() as client:
        response = client.get('/api/info')
        data = response.get_json()
        print(f"   [Result] /api/info Response: {data}")
        
        # FINAL ASSERTIONS (Industrial Integrity)
        assert count == 5028, f"Scenario mismatch: expected 5028, got {count}"
        assert agent_count >= 14, f"Agent mismatch: expected >=14, got {agent_count}"
        assert shim_count >= 20, f"Shim mismatch: expected 20, got {shim_count}"

    print("\n--- AUDIT STATUS: [PASS] ALL CORE HYDRATION GATES CLEARED ---")

if __name__ == "__main__":
    try:
        final_verification()
    except Exception as e:
        print(f"\n--- AUDIT STATUS: [FAIL] REASON: {e} ---")
        sys.exit(1)
