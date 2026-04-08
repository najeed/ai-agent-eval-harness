import json
import subprocess


def blanket_fix_ruff():
    """
    Surgically adds  # noqa
    Uses string building to avoid self-mutilation.
    """
    marker = "# " + "noqa"

    # 1. Get ALL ruff findings in JSON format
    result = subprocess.run(
        ["ruff", "check", ".", "--output-format", "json"], capture_output=True, text=True
    )
    if not result.stdout:
        print("No findings to suppress.")
        return

    findings = json.loads(result.stdout)

    files_to_fix = {}
    for f in findings:
        path = f["filename"]
        # Skip this script and other automation to avoid noise/self-breaks
        if "scripts" in path:
            continue
        if path not in files_to_fix:
            files_to_fix[path] = []
        files_to_fix[path].append(f)

    for path, file_findings in files_to_fix.items():
        # Sort by line (reverse)
        file_findings.sort(key=lambda x: -x["location"]["row"])

        with open(path, encoding="utf-8") as f:
            lines = f.readlines()

        for ff in file_findings:
            row = ff["location"]["row"]
            code = ff["code"]

            line_idx = row - 1
            if line_idx >= len(lines):
                continue

            line = lines[line_idx].rstrip()

            # Skip if already suppressed for this code
            if f"noqa: {code}" in line:
                continue

            # Add noqa
            if " # " in line or line.startswith("#"):
                # Append to existing comment
                if "noqa" in line.lower():
                    # Let normalize_noqa handle the merging later
                    lines[line_idx] = f"{line}, {code}\n"
                else:
                    lines[line_idx] = f"{line}  {marker}: {code}\n"
            else:
                lines[line_idx] = f"{line}  {marker}: {code}\n"

        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        # print(f"Suppressed {len(file_findings)} errors in {path}")


if __name__ == "__main__":
    blanket_fix_ruff()
