import os
from pathlib import Path
from unittest.mock import patch, MagicMock

def is_path_safe(target, base):
    try:
        print(f"DEBUG_START: target={target}, base={base}")
        target_path = Path(target).resolve()
        base_path = Path(base).resolve()
        
        target_str = str(target_path).lower().replace("\\", "/").rstrip("/")
        base_str = str(base_path).lower().replace("\\", "/").rstrip("/")
        
        print(f"DEBUG_SAFE: target_str={target_str}, base_str={base_str}")
        res = target_str == base_str or target_str.startswith(f"{base_str}/")
        return res
    except Exception as e:
        print(f"DEBUG_EXC: {e}")
        return False

# Simulate the test
with patch("pathlib.Path.resolve", side_effect=lambda self: self):
    target = Path("/tmp/root/docs/g1.md")
    base = Path("/tmp/root/docs")
    print(f"RESULT: {is_path_safe(target, base)}")

print("\n--- with autospec ---")
with patch("pathlib.Path.resolve", autospec=True, side_effect=lambda self: self):
    target = Path("/tmp/root/docs/g1.md")
    base = Path("/tmp/root/docs")
    print(f"RESULT: {is_path_safe(target, base)}")
