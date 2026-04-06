import re
import subprocess


def prefix_unused_vars():
    # 1. Get ruff findings for F841 in tests
    result = subprocess.run(
        ["ruff", "check", "tests", "--select=F841", "--output-format", "json"],
        capture_output=True,
        text=True,
    )
    if not result.stdout:
        print("No F841 findings in tests.")
        return

    import json

    findings = json.loads(result.stdout)

    # 2. Sort by file and line (reverse) to avoid offset issues
    findings.sort(key=lambda x: (x["filename"], -x["location"]["row"], -x["location"]["column"]))

    for f in findings:
        path = f["filename"]
        row = f["location"]["row"]
        col = f["location"]["column"]
        # Extract variable name from message: "Local variable `captured` is assigned to but never used", E501, E501
        match = re.search(r"Local variable `([^`]+)` is assigned", f["message"])
        if not match:
            continue
        var_name = match.group(1)

        with open(path, encoding="utf-8") as file:
            lines = file.readlines()

        line_idx = row - 1
        line = lines[line_idx]

        # Check if it's already prefixed
        if f"_{var_name}" in line:
            continue

        # Surgical replacement of the exact variable assignment
        # Look for the variable name at the column position (1-indexed)
        # Note: col is generally the start of the variable name
        new_line = line[: col - 1] + f"_{var_name}" + line[col - 1 + len(var_name) :]
        lines[line_idx] = new_line

        with open(path, "w", encoding="utf-8") as file:
            file.writelines(lines)
        print(f"Prefixed {var_name} in {path}:{row}")


if __name__ == "__main__":
    prefix_unused_vars()
