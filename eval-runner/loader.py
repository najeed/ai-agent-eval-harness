"""
loader.py

This module provides utilities for loading scenario and dataset files for the AI Agent Evaluation Harness.
It supports loading scenario JSON files with schema validation, and dataset loading for CSV/JSONL.

Typical usage example:
    from eval_runner import loader
    scenario = loader.load_scenario(Path('path/to/scenario.json'))
"""
# eval-runner/loader.py

import csv
import json
from pathlib import Path
from jsonschema import validate, ValidationError

# Load the schema once at module level
_SCHEMA_PATH = Path(__file__).parent.parent / "schemas" / "scenario.schema.json"
_SCENARIO_SCHEMA = None


def _get_schema() -> dict:
    """Lazy-loads and caches the scenario JSON schema."""
    global _SCENARIO_SCHEMA
    if _SCENARIO_SCHEMA is None:
        with open(_SCHEMA_PATH, "r") as f:
            _SCENARIO_SCHEMA = json.load(f)
    return _SCENARIO_SCHEMA


def load_scenario(file_path: Path) -> dict:
    """
    Loads and validates a scenario JSON file from the given path.

    Args:
        file_path (Path): The Path object pointing to the .json scenario file.

    Returns:
        dict: A dictionary containing the validated scenario data.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
        ValueError: If the scenario fails schema validation.
    """
    print(f"   [Loader] Attempting to load from: {file_path}")
    if not file_path.exists():
        raise FileNotFoundError(f"Scenario file not found at {file_path}")

    with open(file_path, "r") as f:
        try:
            scenario_data = json.load(f)
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(
                f"Error decoding JSON from {file_path}: {e.msg}", e.doc, e.pos
            )

    # Validate against schema
    try:
        validate(instance=scenario_data, schema=_get_schema())
    except ValidationError as e:
        raise ValueError(
            f"Schema validation failed for {file_path}: {e.message}"
        )

    return scenario_data



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
