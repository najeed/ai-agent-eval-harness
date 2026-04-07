import os
import subprocess
import shutil
from pathlib import Path

def test_evaluate_run_log_dir_creation():
    log_dir = "test_evaluate_logs_dir"
    scenario_dir = "scenarios"
    
    # Ensure logs dir does not exist
    if os.path.exists(log_dir):
        shutil.rmtree(log_dir)
    
    # Create a dummy scenario file if not exists
    if not os.path.exists(scenario_dir):
        os.makedirs(scenario_dir)
    
    scenario_path = os.path.join(scenario_dir, "test_scenario_eval.json")
    with open(scenario_path, "w") as f:
        f.write('{"scenario_id": "test_eval_v1", "title": "Test Eval V1", "tasks": [{"task_id": "task1", "prompt": "Hello", "expected_outcome": "World"}]}')
    
    # Run the evaluate command
    print(f"Running command: python -m eval_runner.cli evaluate --path {scenario_dir} --run-log-dir {log_dir} --limit 1")
    
    result = subprocess.run(
        ["python", "-m", "eval_runner.cli", "evaluate", "--path", scenario_dir, "--run-log-dir", log_dir, "--limit", "1"],
        capture_output=True,
        text=True
    )
    
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
    
    if os.path.exists(log_dir):
        print(f"SUCCESS: Directory '{log_dir}' was created.")
    else:
        print(f"FAILURE: Directory '{log_dir}' was NOT created.")

if __name__ == "__main__":
    test_evaluate_run_log_dir_creation()
