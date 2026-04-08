import os
import re


def normalize_noqa():
    """
      Finds lines with  # noqa
    # noqa: CODE1, CODE2
      Uses string building to avoid self-mutilation by this script.
    """
    # Sentinel used to find the comment
    marker = "# " + "noqa"

    for root, _dirs, files in os.walk("."):
        if any(d in root for d in [".git", "venv", ".venv", "node_modules", "__pycache__"]):
            # Skipping scripts temporarily to avoid breaking itself until logic is solid
            continue
        for file in files:
            if not file.endswith(".py"):
                continue

            path = os.path.join(root, file)
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()

            modified = False
            for i, line in enumerate(lines):
                # Only act if marker is at the end or preceded by space
                if marker in line:
                    # Very simple check: is the last '#' on the line starting a comment?
                    # For industrial reliability, we look for '  # ' or '#' at start.
                    if " # " not in line and not line.startswith("#"):
                        continue

                    # Split at the last occurrence of # to find codes
                    parts = line.rsplit("#", 1)
                    if len(parts) < 2 or "noqa" not in parts[1].lower():
                        continue

                    prefix = parts[0].rstrip()
                    codes_part = parts[1]

                    # Extract codes
                    codes = re.findall(r"([A-Z]+[0-9]+)", codes_part)

                    if not codes:
                        new_noqa = "# " + "noqa"
                    else:
                        unique_codes = sorted(list(set(codes)))
                        new_noqa = "# " + f"noqa: {', '.join(unique_codes)}"

                    new_line = f"{prefix}  {new_noqa}\n"
                    if new_line != line:
                        lines[i] = new_line
                        modified = True

            if modified:
                with open(path, "w", encoding="utf-8") as f:
                    f.writelines(lines)


if __name__ == "__main__":
    normalize_noqa()
