"""
Unit tests for the automated dependency compliance synchronization tool.
"""

from tools.ci.sync_compliance import (
    check_or_sync_requirements,
    normalize_license,
    scan_npm_packages,
    scan_python_optional_packages,
    scan_python_packages,
    sync_compliance,
)


def test_normalize_license_known_types():
    assert normalize_license("MIT")[0] == "MIT"
    assert normalize_license("Apache 2.0")[0] == "Apache 2.0"
    assert normalize_license("BSD-3-Clause")[0] == "BSD-3-Clause"
    assert normalize_license("ISC")[0] == "ISC"


def test_scan_python_packages_pyproject(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text(
        """
[project]
dependencies = [
    "click==8.3.2",
    "pydantic>=2.13.0",
]
""",
        encoding="utf-8",
    )
    pkgs = scan_python_packages(p)
    assert len(pkgs) == 2
    names = [x["name"] for x in pkgs]
    assert "click" in names
    assert "pydantic" in names


def test_scan_python_optional_packages(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text(
        """
[project.optional-dependencies]
provider-gemini = [
    "google-genai==2.22.0",
]
framework-langchain = [
    "langchain==1.4.0",
]
all = [
    "google-genai==2.22.0",
    "langchain==1.4.0",
]
""",
        encoding="utf-8",
    )
    pkgs = scan_python_optional_packages(p)
    # Composite meta-extra 'all' must be filtered out, leaving unique items
    names = {x["name"] for x in pkgs}
    assert "google-genai" in names
    assert "langchain" in names
    assert len(pkgs) == 2


def test_check_or_sync_requirements_drift_and_mirror(tmp_path):
    p = tmp_path / "pyproject.toml"
    p.write_text(
        """
[project]
dependencies = [
    "aiohttp==3.14.3",
    "requests==2.34.2",
]
""",
        encoding="utf-8",
    )
    req = tmp_path / "requirements.txt"
    req.write_text("aiohttp==3.14.3\n", encoding="utf-8")

    # In check mode, drift is detected without modifying requirements.txt
    drift = check_or_sync_requirements(p, req, check_mode=True)
    assert drift is True
    assert req.read_text(encoding="utf-8").strip() == "aiohttp==3.14.3"

    # In write mode (check_mode=False), requirements.txt is regenerated and mirrored
    drift2 = check_or_sync_requirements(p, req, check_mode=False)
    assert drift2 is True
    updated_lines = req.read_text(encoding="utf-8")
    assert "aiohttp==3.14.3" in updated_lines
    assert "requests==2.34.2" in updated_lines

    # Subsequent check shows zero drift
    assert check_or_sync_requirements(p, req, check_mode=True) is False


def test_scan_npm_packages_json(tmp_path):
    p = tmp_path / "package.json"
    p.write_text(
        """
{
    "dependencies": {
        "react": "^19.2.8",
        "flatted": "^3.4.4"
    }
}
""",
        encoding="utf-8",
    )
    pkgs = scan_npm_packages(p)
    assert len(pkgs) == 2
    names = [x["name"] for x in pkgs]
    assert "react" in names
    assert "flatted" in names


def test_sync_compliance_check_mode():
    res = sync_compliance(check_mode=True)
    assert res == 0
