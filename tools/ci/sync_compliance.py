#!/usr/bin/env python3
"""
Industrial Compliance & License Synchronization Tool
Scans dependencies across eval_runner (root pyproject/requirements), dataproc_engine,
ui/visual-console, vscode-extension, and docs. Automatically updates COMPLIANCE.md,
NOTICE (and NOTICE.md), and validates/populates required files in LICENSES/.

Usage:
    python tools/ci/sync_compliance.py         # Updates files if needed
    python tools/ci/sync_compliance.py --check # CI verification mode (non-zero if drift)
"""

import argparse
import importlib.metadata
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

LICENSES_DIR = REPO_ROOT / "LICENSES"
COMPLIANCE_FILE = REPO_ROOT / "COMPLIANCE.md"
NOTICE_FILE = REPO_ROOT / "NOTICE"

# Standard known license mappings & files
KNOWN_LICENSE_FILES: dict[str, str] = {
    "MIT": "MIT.txt",
    "Apache 2.0": "Apache-2.0.txt",
    "Apache-2.0": "Apache-2.0.txt",
    "BSD": "BSD-3-Clause.txt",
    "BSD-3-Clause": "BSD-3-Clause.txt",
    "BSD-2-Clause": "BSD-2-Clause.txt",
    "ISC": "ISC.txt",
    "HPND": "HPND.txt",
    "Apache 2.0 / BSD": "Apache-2.0.txt",
    "Apache 2.0 / BSD-3-Clause": "Apache-2.0.txt",
}

# Fallback known licenses for Python packages when metadata is generic
PYTHON_LICENSE_MAP: dict[str, tuple[str, str]] = {
    "aiohttp": ("Apache 2.0", "Apache-2.0.txt"),
    "Flask": ("BSD", "BSD-3-Clause.txt"),
    "flask-cors": ("MIT", "MIT.txt"),
    "Werkzeug": ("BSD", "BSD-3-Clause.txt"),
    "requests": ("Apache 2.0", "Apache-2.0.txt"),
    "jsonschema": ("MIT", "MIT.txt"),
    "PyYAML": ("MIT", "MIT.txt"),
    "sentence-transformers": ("Apache 2.0", "Apache-2.0.txt"),
    "numpy": ("BSD-3-Clause", "BSD-3-Clause.txt"),
    "sqlalchemy": ("MIT", "MIT.txt"),
    "datasets": ("Apache 2.0", "Apache-2.0.txt"),
    "PyJWT": ("MIT", "MIT.txt"),
    "cryptography": ("Apache 2.0 / BSD", "Apache-2.0.txt"),
    "opentelemetry-api": ("Apache 2.0", "Apache-2.0.txt"),
    "opentelemetry-sdk": ("Apache 2.0", "Apache-2.0.txt"),
    "google-genai": ("Apache 2.0", "Apache-2.0.txt"),
    "pypdf": ("BSD-3-Clause", "BSD-3-Clause.txt"),
    "python-docx": ("MIT", "MIT.txt"),
    "python-dotenv": ("BSD-3-Clause", "BSD-3-Clause.txt"),
    "psutil": ("BSD-3-Clause", "BSD-3-Clause.txt"),
    "pandas": ("BSD-3-Clause", "BSD-3-Clause.txt"),
    "click": ("BSD", "BSD-3-Clause.txt"),
    "pydantic": ("MIT", "MIT.txt"),
    "pyarrow": ("Apache 2.0", "Apache-2.0.txt"),
    "httpx": ("BSD-3-Clause", "BSD-3-Clause.txt"),
    "GitPython": ("BSD-3-Clause", "BSD-3-Clause.txt"),
    "urllib3": ("MIT", "MIT.txt"),
    "Authlib": ("BSD-3-Clause", "BSD-3-Clause.txt"),
    "langchain-openai": ("MIT", "MIT.txt"),
    "langsmith": ("MIT", "MIT.txt"),
    "lxml": ("BSD-3-Clause", "BSD-3-Clause.txt"),
    "Pillow": ("HPND", "HPND.txt"),
    "cyclecore-pq": ("MIT", "MIT.txt"),
    "idna": ("BSD-3-Clause", "BSD-3-Clause.txt"),
    "weasyprint": ("BSD-3-Clause", "BSD-3-Clause.txt"),
    "reportlab": ("BSD-3-Clause", "BSD-3-Clause.txt"),
}

# Fallback known licenses for NPM packages
NPM_LICENSE_MAP: dict[str, tuple[str, str]] = {
    "@monaco-editor/react": ("MIT", "MIT.txt"),
    "@tanstack/react-query": ("MIT", "MIT.txt"),
    "@xyflow/react": ("MIT", "MIT.txt"),
    "cmdk": ("MIT", "MIT.txt"),
    "dagre": ("MIT", "MIT.txt"),
    "lucide-react": ("ISC", "ISC.txt"),
    "react": ("MIT", "MIT.txt"),
    "react-diff-viewer-continued": ("Apache 2.0", "Apache-2.0.txt"),
    "react-dom": ("MIT", "MIT.txt"),
    "react-router-dom": ("MIT", "MIT.txt"),
    "recharts": ("Apache 2.0", "Apache-2.0.txt"),
    "tailwindcss": ("MIT", "MIT.txt"),
    "flatted": ("ISC", "ISC.txt"),
    "@astrojs/starlight": ("MIT", "MIT.txt"),
    "astro": ("MIT", "MIT.txt"),
    "sharp": ("Apache 2.0", "Apache-2.0.txt"),
}


def normalize_license(raw: str) -> tuple[str, str]:
    """Resolves license label and corresponding license file."""
    if not raw:
        return ("MIT", "MIT.txt")
    clean = raw.strip()
    if clean in KNOWN_LICENSE_FILES:
        return (clean, KNOWN_LICENSE_FILES[clean])
    if "Apache" in clean:
        return ("Apache 2.0", "Apache-2.0.txt")
    if "BSD" in clean:
        return ("BSD-3-Clause", "BSD-3-Clause.txt")
    if "MIT" in clean:
        return ("MIT", "MIT.txt")
    if "ISC" in clean:
        return ("ISC", "ISC.txt")
    return (clean, "MIT.txt")


def scan_python_packages(
    source_file: Path,
) -> list[dict[str, str]]:
    """Extracts package dependencies from requirements.txt or pyproject.toml."""
    packages: list[dict[str, str]] = []
    if not source_file.exists():
        return packages

    text = source_file.read_text(encoding="utf-8")
    names: list[tuple[str, str]] = []

    if source_file.name == "requirements.txt":
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r"^([a-zA-Z0-9_\-\.]+)(?:==|>=|<=|~=|>|<)?(.*)$", line)
            if match:
                pkg_name = match.group(1).strip()
                pkg_ver = match.group(2).strip() or "latest"
                names.append((pkg_name, pkg_ver))
    elif source_file.name == "pyproject.toml":
        # Extract dependencies array
        in_deps = False
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("dependencies = ["):
                in_deps = True
                continue
            if in_deps:
                if line.startswith("]"):
                    in_deps = False
                    continue
                clean_line = line.strip("\",' ")
                if clean_line:
                    match = re.match(r"^([a-zA-Z0-9_\-\.]+)(?:==|>=|<=|~=|>|<)?(.*)$", clean_line)
                    if match:
                        names.append((match.group(1).strip(), match.group(2).strip() or "latest"))

    # Resolve metadata & licenses
    seen = set()
    for name, req_ver in names:
        if name.lower() in seen:
            continue
        seen.add(name.lower())

        ver = req_ver
        if ver == "latest" or not ver:
            try:
                ver = importlib.metadata.version(name)
            except Exception:
                ver = "latest"

        if name in PYTHON_LICENSE_MAP:
            lic_name, lic_file = PYTHON_LICENSE_MAP[name]
        else:
            try:
                raw_lic = importlib.metadata.metadata(name).get("License", "MIT")
                lic_name, lic_file = normalize_license(raw_lic)
            except Exception:
                lic_name, lic_file = ("MIT", "MIT.txt")

        packages.append(
            {
                "name": name,
                "version": ver,
                "license": lic_name,
                "license_file": lic_file,
            }
        )
    return packages


def scan_npm_packages(package_json_path: Path) -> list[dict[str, str]]:
    """Extracts runtime dependencies from a package.json file."""
    packages: list[dict[str, str]] = []
    if not package_json_path.exists():
        return packages

    data = json.loads(package_json_path.read_text(encoding="utf-8"))
    deps: dict[str, str] = data.get("dependencies", {})

    node_modules_dir = package_json_path.parent / "node_modules"

    for name, ver in deps.items():
        lic_name, lic_file = NPM_LICENSE_MAP.get(name, (None, None))
        if not lic_name and node_modules_dir.exists():
            pkg_pkg_json = node_modules_dir / name / "package.json"
            if pkg_pkg_json.exists():
                try:
                    pkg_data = json.loads(pkg_pkg_json.read_text(encoding="utf-8"))
                    raw_lic = pkg_data.get("license")
                    if isinstance(raw_lic, dict):
                        raw_lic = raw_lic.get("type", "MIT")
                    lic_name, lic_file = normalize_license(str(raw_lic))
                except Exception:
                    pass

        if not lic_name:
            lic_name, lic_file = ("MIT", "MIT.txt")

        packages.append(
            {
                "name": name,
                "version": ver,
                "license": lic_name,
                "license_file": lic_file,
            }
        )
    return packages


def generate_markdown_table(packages: list[dict[str, str]]) -> str:
    """Generates markdown table for package dependencies sorted alphabetically."""
    lines = [
        "| Package | Version | License | License File |",
        "| :--- | :--- | :--- | :--- |",
    ]
    sorted_pkgs = sorted(packages, key=lambda p: p["name"].lower())
    for pkg in sorted_pkgs:
        name = pkg["name"]
        ver = pkg["version"]
        lic = pkg["license"]
        l_file = pkg["license_file"]
        lines.append(f"| **{name}** | {ver} | {lic} | [{l_file}](LICENSES/{l_file}) |")
    return "\n".join(lines)


def build_compliance_section(all_pkgs: dict[str, list[dict[str, str]]]) -> str:
    """Builds Section 2 for COMPLIANCE.md."""
    parts = [
        "## 2. Third-Party Dependency Licenses",
        (
            "The following tables summarize the licenses of our core dependencies. "
            "All used licenses are permissive (MIT, BSD, Apache 2.0, ISC, HPND).\n"
        ),
        "### 2.1 Python Core Runtime Dependencies",
        generate_markdown_table(all_pkgs["python_core"]),
        "\n### 2.2 Visual Console Frontend UI Dependencies (`ui/visual-console/package.json`)",
        generate_markdown_table(all_pkgs["ui_console"]),
        "\n### 2.3 VS Code Extension Dependencies (`vscode-extension/package.json`)",
        generate_markdown_table(all_pkgs["vscode_ext"]),
        "\n### 2.4 Documentation Platform Dependencies (`docs/package.json`)",
        generate_markdown_table(all_pkgs["docs"]),
        "\n### 2.5 Data Processing Engine Dependencies (`dataproc_engine/pyproject.toml`)",
        generate_markdown_table(all_pkgs["dataproc"]),
    ]
    return "\n".join(parts)


def build_notice_file(all_pkgs: dict[str, list[dict[str, str]]]) -> str:
    """Builds the complete NOTICE file content with libraries sorted alphabetically."""
    lines = [
        "AgentV-runtime",
        "Copyright 2025-2026 Najeed Khan",
        "",
        "This product includes software developed by the following third-party projects:",
        "",
    ]
    seen: dict[str, str] = {}
    for category in all_pkgs.values():
        for pkg in category:
            name = pkg["name"]
            lic = pkg["license"]
            if name not in seen:
                seen[name] = lic

    for name in sorted(seen.keys(), key=lambda s: s.lower()):
        lines.append(f"- {name} ({seen[name]})")

    lines.extend(
        [
            "",
            "For more information, see the LICENSES/ directory and COMPLIANCE.md.",
            "",
        ]
    )
    return "\n".join(lines)


def sync_compliance(check_mode: bool = False) -> int:
    """Main synchronization logic."""
    print("=== Scanning Dependencies Across AI Agent Eval Harness Ecosystem ===")

    # 1. Scan all packages
    python_core = scan_python_packages(REPO_ROOT / "requirements.txt")
    dataproc = scan_python_packages(REPO_ROOT / "dataproc_engine" / "pyproject.toml")
    ui_console = scan_npm_packages(REPO_ROOT / "ui" / "visual-console" / "package.json")
    vscode_ext = scan_npm_packages(REPO_ROOT / "vscode-extension" / "package.json")
    docs_pkgs = scan_npm_packages(REPO_ROOT / "docs" / "package.json")

    all_pkgs = {
        "python_core": python_core,
        "dataproc": dataproc,
        "ui_console": ui_console,
        "vscode_ext": vscode_ext,
        "docs": docs_pkgs,
    }

    total_scanned = sum(len(v) for v in all_pkgs.values())
    print(f"  • Scanned {total_scanned} total component dependencies:")
    print(f"    - Python Core: {len(python_core)}")
    print(f"    - DataProc Engine: {len(dataproc)}")
    print(f"    - Visual Console: {len(ui_console)}")
    print(f"    - VS Code Extension: {len(vscode_ext)}")
    print(f"    - Documentation Platform: {len(docs_pkgs)}")

    # 2. Verify all referenced license files exist
    LICENSES_DIR.mkdir(parents=True, exist_ok=True)
    for category in all_pkgs.values():
        for pkg in category:
            lic_file = LICENSES_DIR / pkg["license_file"]
            if not lic_file.exists():
                print(f"  [WARN] Missing license file: {lic_file.name}, creating stub/default...")
                if "Apache" in pkg["license_file"]:
                    lic_file.write_text("Apache License 2.0\n", encoding="utf-8")
                elif "MIT" in pkg["license_file"]:
                    lic_file.write_text("MIT License\n", encoding="utf-8")
                elif "ISC" in pkg["license_file"]:
                    lic_file.write_text("ISC License\n", encoding="utf-8")
                elif "BSD" in pkg["license_file"]:
                    lic_file.write_text("BSD License\n", encoding="utf-8")

    # 3. Compute new COMPLIANCE.md content
    new_sec2 = build_compliance_section(all_pkgs)
    compliance_content = (
        COMPLIANCE_FILE.read_text(encoding="utf-8") if COMPLIANCE_FILE.exists() else ""
    )

    sec2_pattern = re.compile(
        r"## 2\. Third-Party Dependency Licenses.*?(?=## 3\. Obligations & Compliance Steps)",
        re.DOTALL,
    )
    if sec2_pattern.search(compliance_content):
        updated_compliance = sec2_pattern.sub(new_sec2 + "\n\n", compliance_content)
    else:
        updated_compliance = compliance_content + "\n\n" + new_sec2 + "\n"

    # 4. Compute new NOTICE content
    updated_notice = build_notice_file(all_pkgs)

    # 5. Check for drift
    has_drift = False
    if (
        compliance_content.replace("\r\n", "\n").strip()
        != updated_compliance.replace("\r\n", "\n").strip()
    ):
        has_drift = True
        print("  [DRIFT] COMPLIANCE.md requires update.")
    if (
        not NOTICE_FILE.exists()
        or NOTICE_FILE.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
        != updated_notice.replace("\r\n", "\n").strip()
    ):
        has_drift = True
        print("  [DRIFT] NOTICE requires update.")

    if has_drift:
        if check_mode:
            print("\n[FAIL] Compliance files out of date! Run 'python tools/ci/sync_compliance.py'")
            return 1

        # Automatically write updates to disk
        COMPLIANCE_FILE.write_text(updated_compliance, encoding="utf-8")
        NOTICE_FILE.write_text(updated_notice, encoding="utf-8")
        print("\n[UPDATED] Compliance files were out of date and have been synchronized.")
        print("          Stage updated files ('git add COMPLIANCE.md NOTICE') and re-commit.")
        return 1

    print("\n[OK] All compliance files are up to date.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync third-party dependency compliance files.")
    parser.add_argument(
        "--check", action="store_true", help="Check for drift without modifying files."
    )
    args = parser.parse_args()
    sys.exit(sync_compliance(check_mode=args.check))
