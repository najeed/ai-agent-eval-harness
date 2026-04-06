import os
import json
from pathlib import Path

def migrate_scenarios(root_dir: str):
    root = Path(root_dir)
    count = 0
    updated = 0
    
    # Target all relevant source, scenario, and documentation directories
    targets = [
        root / "industries", 
        root / "walkthroughs", 
        root / "tests", 
        root / "scenarios", 
        root / "eval_runner", 
        root / "sample_agent",
        root / "docs"
    ]
    
    for target in targets:
        if not target.exists():
            continue
            
        for path in target.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in [".json", ".py", ".md"]:
                continue
                
            count += 1
            try:
                content = path.read_text(encoding="utf-8")
                changed = False
                
                # Handle JSON style
                if '"aes_version": 1.2' in content:
                    content = content.replace('"aes_version": 1.2', '"aes_version": 1.3')
                    changed = True
                
                # Handle Python dict style
                if "'aes_version': 1.2" in content:
                    content = content.replace("'aes_version': 1.2", "'aes_version': 1.3")
                    changed = True
                
                # Handle edge case found in walkthroughs
                if '"aes_version": "1.2.3"' in content:
                    content = content.replace('"aes_version": "1.2.3"', '"aes_version": 1.3')
                    changed = True

                if changed:
                    path.write_text(content, encoding="utf-8")
                    updated += 1
            except Exception as e:
                print(f"Error processing {path}: {e}")

    print(f"Done! Scanned {count} files, updated {updated} to AES v1.3.")

if __name__ == "__main__":
    migrate_scenarios(".")
