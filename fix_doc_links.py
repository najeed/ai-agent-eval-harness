import os
import re

# Define the root directory for documentation
docs_root = r"c:\Users\najee\OneDrive\Documents\Projects\ai-agent-eval-harness\docs\src\content\docs"

# Mapping of old underscored names to new hyphenated names
replacements = {
    "user_manual": "user-manual",
    "aes_spec": "aes-spec",
    "developer_guide": "developer-guide",
    "core_functions": "core-functions",
    "api_reference": "api-reference",
    "testing_guide": "testing-guide",
    "triage_engine": "triage-engine",
    "trust_protocol": "trust-protocol",
    "publishing": "advanced-publication-suite",
    "triage_vfs": "triage-vfs"
}

def fix_links(directory):
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith((".md", ".mdx")):
                file_path = os.path.join(root, file)
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                original_content = content
                for old, new in replacements.items():
                    # Handle both markdown links [text](path/to/user_manual)
                    # and potentially raw paths or strings
                    # We look for the exact underscored string
                    content = content.replace(old, new)
                
                if content != original_content:
                    print(f"Updating links in: {file_path}")
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(content)

if __name__ == "__main__":
    fix_links(docs_root)
