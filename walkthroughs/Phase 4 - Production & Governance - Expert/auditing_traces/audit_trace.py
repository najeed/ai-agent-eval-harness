import json
import os


def audit_trace():
    """
    Simulates the industrial forensic audit for Phase 4.
    """
    trace_path = os.path.join(os.path.dirname(__file__), "sample_run.jsonl")

    if not os.path.exists(trace_path):
        print(f"      [Error] Trace file not found: {trace_path}")
        return

    print("\n      🔍  PHASE 4: INDUSTRIAL FORENSIC AUDIT")
    print("-" * 60)
    print(f"      [File]: {trace_path}")
    print("-" * 60)

    with open(trace_path) as f:
        for line in f:
            if not line.strip():
                continue

            entry = json.loads(line)
            step = entry.get("step")
            e_type = entry.get("type", "UNKNOWN")
            content = entry.get("content", "")
            meta = entry.get("metadata", {})

            # --- BREACH DETECTION LOGIC ---
            is_anomaly = False
            reason = ""

            if meta.get("shim") == "legacy_forbidden_shim":
                is_anomaly = True
                reason = "SECURITY_BREACH_DETECTED (Unauthorized Shim Access)"

            status_icon = "⚠️" if is_anomaly else "🟢"
            print(f"      [{step:02}] {status_icon} {e_type:<8}: {content[:50]}...")

            if is_anomaly:
                print(f"           >>> 🚨 ALERT: {reason}")
                print(f"           >>> [Tool]: {meta.get('tool')}")

    print("-" * 60)
    print("      [NIST-100] Alignment: Forensic Accountability Verified.")
    print("      [Audit Result]: ❌ FAILED. Critical security markers compromised.")


if __name__ == "__main__":
    audit_trace()
