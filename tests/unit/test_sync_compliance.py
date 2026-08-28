"""
Unit tests for the automated dependency compliance synchronization tool.
"""

from tools.ci.sync_compliance import (
    normalize_license,
    scan_npm_packages,
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
