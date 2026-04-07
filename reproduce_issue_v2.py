
import os
import subprocess
import shutil
from pathlib import Path

def test_run_log_dir_creation():
    log_dir = "test_run_logs_dir_v2"
    if os.path.exists(log_dir):
        shutil.rmtree(log_dir)
    
    # Also check default 'runs' dir
    if os.path.exists("runs"):
        # We don't want to delete user's runs, but we want to see if something new appeared
        old_runs = set(os.listdir("runs"))
    else:
        old_runs = set()

    # We need a dummy scenario to run
    scenario_path = "scenarios/test_scenario_v2.json"
    os.makedirs("scenarios", exist_ok=True)
    with open(scenario_path, "w") as f:
        f.write('{"scenario_id": "test_log_dir_v2", "title": "Test Log Dir Creation V2", "tasks": []}')

    cmd = ["python", "-m", "eval_runner.cli", "run", "--scenario", scenario_path, "--run-log-dir", log_dir]
    print(f"Running command: {' '.join(cmd)}")
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
    
    if os.path.exists(log_dir):
        print(f"SUCCESS: Directory '{log_dir}' was created.")
    else:
        print(f"FAILURE: Directory '{log_dir}' was NOT created.")
        
    if os.path.exists("runs"):
        new_runs = set(os.listdir("runs")) - old_runs
        if new_runs:
            print(f"OBSERVATION: New files/dirs in 'runs/': {new_runs}")
            print("This confirms the plugin is using the default directory instead of the overridden one.")

if __name__ == "__main__":
    test_run_log_dir_creation()
