import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.append(os.getcwd())

from eval_runner.catalog import get_catalog, ScenarioCatalog

def test_singleton():
    c1 = get_catalog()
    c2 = get_catalog()
    assert c1 is c2, "Catalog should be a singleton"
    print("✅ Singleton verification passed.")

def test_pagination():
    catalog = get_catalog()
    catalog.load_index()
    total = len(catalog.scenarios)
    print(f"Total scenarios in index: {total}")
    
    limit = 5
    results = catalog.search(limit=limit, offset=0)
    assert len(results) <= limit, f"Should return at most {limit} items"
    print(f"✅ Pagination (limit={limit}) verification passed.")
    
    # Check offset
    if total > 5:
        results_page2 = catalog.search(limit=limit, offset=5)
        assert results[0]["id"] != results_page2[0]["id"], "Page 2 should be different"
        print("✅ Pagination (offset=5) verification passed.")

def test_sync_metadata():
    catalog = get_catalog()
    catalog.build_index()
    assert catalog._disk_count > 0, "Disk count should be tracked"
    assert not catalog.check_for_updates(), "Should be in sync after build"
    print("✅ Sync logic verification passed.")

if __name__ == "__main__":
    try:
        test_singleton()
        test_pagination()
        test_sync_metadata()
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        sys.exit(1)
