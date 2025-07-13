# eval-runner/loader.py

import json
from pathlib import Path

def load_scenario(file_path: Path) -> dict:
    """
    Loads a scenario JSON file from the given path.

    Args:
        file_path: The Path object pointing to the .json scenario file.

    Returns:
        A dictionary containing the scenario data.
    
    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    print(f"   [Loader] Attempting to load from: {file_path}")
    if not file_path.exists():
        raise FileNotFoundError(f"Scenario file not found at {file_path}")
    
    with open(file_path, 'r') as f:
        try:
            scenario_data = json.load(f)
            return scenario_data
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(f"Error decoding JSON from {file_path}: {e.msg}", e.doc, e.pos)

def load_dataset(file_path: Path):
    """
    Loads a dataset file (e.g., .jsonl, .csv).
    This is a placeholder and should be expanded to handle different file types.

    Args:
        file_path: The Path object pointing to the dataset file.
    """
    # TODO: Implement dataset loading logic based on file extension.
    print(f"   [Loader] Placeholder for loading dataset from: {file_path}")
    pass
