import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from eval_runner.console.app import create_app

app = create_app()

print("\n--- Route Map Diagnostic ---")
for rule in app.url_map.iter_rules():
    methods = ", ".join(sorted(rule.methods))
    print(f"{rule.rule} [{methods}] -> {rule.endpoint}")
print("--- End Diagnostic ---\n")
