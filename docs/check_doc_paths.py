#!/usr/bin/env python3
"""
CI Sentinel Script: Documentation Path & Link Validity Checker.
Scans markdown documentation (e.g., TESTING.md, README.md, docs/) for:
1. Referenced repository paths (such as `tests/...` or `eval_runner/...`).
2. Markdown links ([text](target)) pointing to local files or Starlight routes.
Fails if any referenced path or link target does not exist on disk.
"""

import re
import sys
from pathlib import Path
from urllib.parse import unquote

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

# Regex pattern matching markdown links
LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def check_doc_paths() -> int:
    missing_paths = []
    missing_links = []
    total_paths = 0
    total_links = 0

    for doc_path in DOC_FILES:
        if not doc_path.exists():
            continue

        content = doc_path.read_text(encoding="utf-8", errors="ignore")

        # 1. Check backtick paths
        matches = PATH_PATTERN.findall(content)
        for match in set(matches):
            total_paths += 1
            clean_path = match.split("::")[0].split("#")[0].rstrip(".")
            full_path = PROJECT_ROOT / clean_path

            if not full_path.exists():
                missing_paths.append((doc_path.name, match, str(clean_path)))

        # 2. Check markdown link targets (ignoring code blocks)
        content_no_code = re.sub(r"```[\s\S]*?```", "", content)
        for text, target in LINK_PATTERN.findall(content_no_code):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            clean = target.split("#")[0].strip()
            if not clean:
                continue

            total_links += 1
            clean_unquoted = unquote(clean)

            if clean.startswith("/"):
                # Starlight documentation route or static public asset
                route = clean.strip("/")
                candidates = [
                    PROJECT_ROOT / "docs" / "src" / "content" / "docs" / (route + ".md"),
                    PROJECT_ROOT / "docs" / "src" / "content" / "docs" / (route + ".mdx"),
                    PROJECT_ROOT / "docs" / "src" / "content" / "docs" / route / "index.md",
                    PROJECT_ROOT / "docs" / "src" / "content" / "docs" / route / "index.mdx",
                    PROJECT_ROOT / "docs" / "public" / route,
                    PROJECT_ROOT / "spec" / route,
                ]
                if not any(c.exists() for c in candidates):
                    missing_links.append((doc_path.name, text, target))
            elif clean.startswith("file:///"):
                subpath = clean.replace("file:///", "")
                if not Path(subpath).exists() and not (PROJECT_ROOT / subpath).exists():
                    missing_links.append((doc_path.name, text, target))
            else:
                rel = (doc_path.parent / clean_unquoted).resolve()
                root_rel = (PROJECT_ROOT / clean_unquoted).resolve()
                if not rel.exists() and not root_rel.exists():
                    missing_links.append((doc_path.name, text, target))

    print(
        f"[CI Doc Sentinel] Checked {total_paths} code path references "
        f"and {total_links} markdown links across docs."
    )

    has_errors = False
    if missing_paths:
        has_errors = True
        print(f"\n[ERROR] Found {len(missing_paths)} broken documentation path reference(s):")
        for doc_name, orig_ref, clean_p in missing_paths:
            print(f"  - Document: {doc_name}")
            print(f"    Referenced Path: '{orig_ref}' -> Disk Path Not Found: '{clean_p}'\n")

    if missing_links:
        has_errors = True
        print(f"\n[ERROR] Found {len(missing_links)} broken markdown link target(s):")
        for doc_name, text, target in missing_links:
            print(f"  - Document: {doc_name}")
            print(f"    Link: [{text}]({target}) -> Target Not Found\n")

    if has_errors:
        return 1

    print("[CI Doc Sentinel] All documentation path references and links exist on disk!")
    return 0


if __name__ == "__main__":
    sys.exit(check_doc_paths())
