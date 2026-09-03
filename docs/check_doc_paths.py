#!/usr/bin/env python3
"""
CI Sentinel Script: Documentation Path Validity Checker.
Scans markdown documentation (e.g., TESTING.md, README.md) for referenced repository paths
(such as tests/... or eval_runner/...) and fails if any path does not exist on disk.
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DOC_FILES = [
    PROJECT_ROOT / "TESTING.md",
    PROJECT_ROOT / "README.md",
    PROJECT_ROOT / "COMPLIANCE.md",
    PROJECT_ROOT / "docs" / "AUTHENTICATION.md",
    *list((PROJECT_ROOT / "docs" / "src" / "content" / "docs").rglob("*.md")),
    *list((PROJECT_ROOT / "docs" / "src" / "content" / "docs").rglob("*.mdx")),
    *list((PROJECT_ROOT / "docs-v1-deprecated-reference").rglob("*.md")),
]

# Regex pattern matching code blocks referencing project root directories
PATH_PATTERN = re.compile(
    r"`((?:tests|eval_runner|dataproc_engine|industries|agentv_runtime|spec|tools)/[a-zA-Z0-9_\-\./]+)`"
)


def check_doc_paths() -> int:
    missing_paths = []
    total_checked = 0

    for doc_path in DOC_FILES:
        if not doc_path.exists():
            continue

        content = doc_path.read_text(encoding="utf-8")
        matches = PATH_PATTERN.findall(content)

        for match in set(matches):
            total_checked += 1
            # Clean up function/line references (e.g. ::test_foo or #L123)
            clean_path = match.split("::")[0].split("#")[0].rstrip(".")
            full_path = PROJECT_ROOT / clean_path

            if not full_path.exists():
                missing_paths.append((doc_path.name, match, str(clean_path)))

    msg = f"[CI Doc Sentinel] Checked {total_checked} documentation path references across docs."
    print(msg)

    if missing_paths:
        print(f"\n[ERROR] Found {len(missing_paths)} broken documentation path reference(s):")
        for doc_name, orig_ref, clean_p in missing_paths:
            print(f"  - Document: {doc_name}")
            print(f"    Referenced Path: '{orig_ref}' -> Disk Path Not Found: '{clean_p}'\n")
        return 1

    print("[CI Doc Sentinel] All documentation path references exist on disk!")
    return 0


if __name__ == "__main__":
    sys.exit(check_doc_paths())
