"""
loader.py

This module provides utilities for loading scenario and dataset files for the AI Agent Evaluation Harness.
It supports loading scenario JSON files and includes a placeholder for dataset loading.

Typical usage example:
    from eval_runner import loader
    scenario = loader.load_scenario(Path('path/to/scenario.json'))
"""
# eval-runner/loader.py

import csv
import json
from pathlib import Path


def load_scenario(file_path: Path) -> dict:
    """
    Loads a scenario JSON file from the given path.

    Args:
        file_path (Path): The Path object pointing to the .json scenario file.

    Returns:
        dict: A dictionary containing the scenario data.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file is not valid JSON.

    Example:
        >>> from pathlib import Path
        >>> scenario = load_scenario(Path('industries/accounting/scenarios/accounts_payable/001.json'))
        >>> print(scenario['scenario_id'])
    """
    print(f"   [Loader] Attempting to load from: {file_path}")
    if not file_path.exists():
        raise FileNotFoundError(f"Scenario file not found at {file_path}")

    with open(file_path, "r") as f:
        try:
            scenario_data = json.load(f)
            return scenario_data
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(
                f"Error decoding JSON from {file_path}: {e.msg}", e.doc, e.pos
            )



def load_dataset(file_path: Path):
    """
    Loads a dataset file (e.g., .jsonl, .csv).
    
    Args:
        file_path (Path): The Path object pointing to the dataset file.

    Returns:
        list: A list of dictionaries representing the dataset rows.

    Example:
        >>> from pathlib import Path
        >>> data = load_dataset(Path('industries/accounting/datasets/sample.csv'))
    """
    print(f"   [Loader] Loading dataset from: {file_path}")
    if not file_path.exists():
        raise FileNotFoundError(f"Dataset file not found at {file_path}")

    dataset = []
    
    # Handle CSV
    if file_path.suffix == '.csv':
        with open(file_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                dataset.append(row)
                
    # Handle JSONL
    elif file_path.suffix == '.jsonl':
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    dataset.append(json.loads(line))
                    
    else:
        print(f"   [Loader] Warning: Unsupported dataset format {file_path.suffix}")

    return dataset
