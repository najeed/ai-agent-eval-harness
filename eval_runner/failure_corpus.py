import os
import json
import re
from pathlib import Path

def search(query: str):
    """
    Searches the master run log for terms matching the triage tags or error messages.
    Supports Regular Expressions and Multi-term (AND) search.
    """
    print(f"🔍 Searching local Failure Corpus for: '{query}'...")
    
    master_log = Path("runs/run.jsonl")
    if not master_log.exists():
        print("ℹ️  No master log found at runs/run.jsonl. Try running an evaluation first.")
        return

    matches = []
    
    # Pre-compile regex if possible
    regex_pattern = None
    try:
        # Check if it looks like a regex to avoid accidental regex matching for simple strings
        if any(c in query for c in '.+*?^$()[]{}|\\'):
            regex_pattern = re.compile(query, re.IGNORECASE)
    except re.error:
        regex_pattern = None

    try:
        with open(master_log, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                try:
                    data = json.loads(line)
                    # Search across key fields
                    search_space = f"{data.get('event', '')} {data.get('status', '')} {data.get('triage_tag', '')} {data.get('metric', '')} {str(data.get('content', ''))}"
                    
                    found = False
                    if regex_pattern:
                        if regex_pattern.search(search_space):
                            found = True
                    else:
                        # Fallback to Multi-term AND search
                        terms = query.lower().split()
                        if all(term in search_space.lower() for term in terms):
                            found = True
                    
                    if found:
                        matches.append(data)
                except json.JSONDecodeError:
                    continue
        
        if not matches:
            print(f"❌ No matching failures found for '{query}'.")
        else:
            print(f"✅ Found {len(matches)} matching failure events:")
            for m in matches[:10]: # Cap display
                ts = m.get('timestamp', 'N/A')
                ev = m.get('event', 'unknown')
                tag = m.get('triage_tag', 'NONE')
                run_id = m.get('run_id', 'unknown')
                print(f"  [{ts}] Run: {run_id} | Event: {ev} | Triage: {tag}")
            
            if len(matches) > 10:
                print(f"  ... and {len(matches)-10} more.")
    except Exception as e:
        print(f"❌ Error searching corpus: {e}")
