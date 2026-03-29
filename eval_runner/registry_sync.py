import json
import os
import sys
from pathlib import Path

# Paths relative to project root
REGISTRY_PATH = Path("spec/aes/standards.json")
METADATA_SCHEMA_PATH = Path("spec/aes/definitions/metadata.json")

def get_registry_ids():
    """Extracts all standard IDs from the categorized registry."""
    if not REGISTRY_PATH.exists():
        return []
    
    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        registry = json.load(f)
    
    ids = []
    # registry["categories"] is a dict in standards.json
    categories = registry.get("categories", {})
    for cat_name, cat_data in categories.items():
        # Some categories might have subcategories (list) or just standards (list)
        # For our current standard.json, it's just 'standards'
        for standard in cat_data.get("standards", []):
            ids.append(standard["id"])
            
        # Support recursive subcategories if we ever add them
        for subcat in cat_data.get("subcategories", []):
            for standard in subcat.get("standards", []):
                ids.append(standard["id"])
                
    return sorted(list(set(ids)))

def ensure_schema_sync(force=False):
    """
    Syncs the standards registry enum in metadata.json if standards.json has changed.
    Called once per CLI invocation.
    """
    if not REGISTRY_PATH.exists() or not METADATA_SCHEMA_PATH.exists():
        return

    reg_mtime = os.path.getmtime(REGISTRY_PATH)
    meta_mtime = os.path.getmtime(METADATA_SCHEMA_PATH)

    # Only sync if registry is newer than schema, or forced
    if not force and reg_mtime <= meta_mtime:
        return

    ids = get_registry_ids()
    if not ids:
        return

    with open(METADATA_SCHEMA_PATH, "r", encoding="utf-8") as f:
        metadata_schema = json.load(f)

    # Update the enum in the correct path: properties -> standards_registry -> items -> enum
    try:
        metadata_schema["properties"]["standards_registry"]["items"]["enum"] = ids
        
        with open(METADATA_SCHEMA_PATH, "w", encoding="utf-8") as f:
            json.dump(metadata_schema, f, indent=2)
        
        # Touch metadata file to ensure mtime is strictly greater than registry
        os.utime(METADATA_SCHEMA_PATH, (reg_mtime + 1, reg_mtime + 1))
        print(f"✅ Synced {len(ids)} standards to {METADATA_SCHEMA_PATH.name}")
    except KeyError as e:
        print(f"❌ Failed to sync: Schema structure mismatch at {e}")

def add_standard_to_registry(standard_id, name, industry, description, category=None):
    """Adds a new standard to the registry, categorizing it, and triggers a sync."""
    if not REGISTRY_PATH.exists():
        print("❌ Registry not found.")
        return False
    
    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        registry = json.load(f)
    
    # Check if exists
    ids = get_registry_ids()
    if standard_id in ids:
        print(f"⚠ Standard '{standard_id}' already exists.")
        return False

    # Minimal placement logic
    categories = registry.get("categories", {})
    
    # Use industry as the top-level category if category is not provided
    target_category_name = category or industry or "Global Standards"
    
    if target_category_name not in categories:
        categories[target_category_name] = {
            "description": f"Standards related to {target_category_name}.",
            "standards": []
        }
    
    # Add new standard to the chosen category
    categories[target_category_name]["standards"].append({
        "id": standard_id,
        "name": name,
        "description": description
    })
    
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)
    
    print(f"✅ Added {standard_id} to {target_category_name}")
    
    # Immediate sync to update metadata.json enum
    ensure_schema_sync(force=True)
    return True

if __name__ == "__main__":
    ensure_schema_sync(force=True)
