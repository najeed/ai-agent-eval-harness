import os
import json
from pathlib import Path
from jsonschema import validate, ValidationError

BASE_DIR = Path(".").resolve()
SCHEMA_PATH = BASE_DIR / "schemas" / "scenario.schema.json"
SCENARIOS_ROOT = BASE_DIR / "industries"

def load_all_scenario_files():
    for root, _, files in os.walk(SCENARIOS_ROOT):
        for file in files:
            if file.endswith(".json"):
                yield os.path.join(root, file)

with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
    schema = json.loads(f.read())

errors = []
for path_str in load_all_scenario_files():
    path = Path(path_str)
    try:
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            continue
        try:
            scenario = json.loads(content)
        except json.JSONDecodeError:
            continue
        if not isinstance(scenario, dict) or scenario.get("aes_version") != 1.2:
            continue
        validate(instance=scenario, schema=schema)
    except ValidationError as e:
        errors.append((path_str, str(e)))
    except Exception as e:
        errors.append((path_str, f"Unexpected error: {str(e)}"))

if errors:
    print(f"Found {len(errors)} validation failure(s):")
    for p, err in errors:
        print(f"File: {p}")
        print(f"Error: {err}\n")
else:
    print("No validation failures found.")
