
import os
import subprocess
import shutil

def test_run_log_dir_creation():
    log_dir = "test_run_logs_dir"
    if os.path.exists(log_dir):
        shutil.rmtree(log_dir)
    
    # We need a dummy scenario to run
    scenario_path = "scenarios/test_scenario.json"
    os.makedirs("scenarios", exist_ok=True)
    with open(scenario_path, "w") as f:
        f.write('{"scenario_id": "test_log_dir", "title": "Test Log Dir Creation", "tasks": []}')

    cmd = ["python", "-m", "eval_runner.cli", "run", "--scenario", scenario_path, "--run-log-dir", log_dir]
    print(f"Running command: {' '.join(cmd)}")
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
    
    if os.path.exists(log_dir):
        print(f"SUCCESS: Directory '{log_dir}' was created.")
        if os.path.exists(os.path.join(log_dir, "run.jsonl")):
            print(f"SUCCESS: 'run.jsonl' exists in '{log_dir}'.")
        else:
            print(f"FAILURE: 'run.jsonl' does NOT exist in '{log_dir}'.")
    else:
        print(f"FAILURE: Directory '{log_dir}' was NOT created.")

if __name__ == "__main__":
    test_run_log_dir_creation()
