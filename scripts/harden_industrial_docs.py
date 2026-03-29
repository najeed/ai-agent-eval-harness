import os
import re
from pathlib import Path
import time

def remove_emojis(text):
    # Simple regex to remove common emoji ranges
    # This is a bit aggressive but ensures emoji-free docs
    emoji_pattern = re.compile("["
                               "\U0001f600-\U0001f64f"  # emoticons
                               "\U0001f300-\U0001f5ff"  # symbols & pictographs
                               "\U0001f680-\U0001f6ff"  # transport & map symbols
                               "\U0001f1e0-\U0001f1ff"  # flags (iOS)
                               "\U00002702-\U000027b0"
                               "\U000024c2-\U0001f251"
                               "]+", flags=re.UNICODE)
    return emoji_pattern.sub(r'', text)

def sanitize_content(content):
    # Replace smart quotes and other non-standard characters
    replacements = {
        '\u201c': '"', '\u201d': '"',  # Smart quotes
        '\u2018': "'", '\u2019': "'",  # Smart apostrophes
        '\u2013': "-", '\u2014': "--", # En/Em dashes
        '\u2026': "...",               # Ellipsis
    }
    for old, new in replacements.items():
        content = content.replace(old, new)
    
    # Remove emojis
    content = remove_emojis(content)
    
    return content

def harden_docs():
    industries_dir = Path("industries")
    state_file = Path(".harden_state")
    last_run = 0
    if state_file.exists():
        try:
            last_run = float(state_file.read_text())
        except ValueError:
            pass

    print(f"🔍 Scanning {industries_dir} for markdown files...")
    
    processed_count = 0
    for file_path in industries_dir.rglob("*.md"):
        if file_path.stat().st_mtime > last_run:
            print(f"🛠️ Hardening {file_path}...")
            try:
                content = file_path.read_text(encoding="utf-8")
                sanitized = sanitize_content(content)
                if content != sanitized:
                    file_path.write_text(sanitized, encoding="utf-8")
                    processed_count += 1
                else:
                    # Even if no change, we mark it as "checked" by updating mtime? 
                    # No, just knowing we checked it is enough once we update last_run.
                    pass
            except Exception as e:
                print(f"❌ Failed to process {file_path}: {e}")

    state_file.write_text(str(time.time()))
    print(f"✅ Hardening complete. Processed {processed_count} files.")

if __name__ == "__main__":
    harden_docs()
