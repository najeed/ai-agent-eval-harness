import json
import os


def render_chart():
    """
    Renders an industrial attribution chart for Phase 3.
    """
    import sys

    filename = "attribution_sample.json"
    if len(sys.argv) > 1:
        filename = sys.argv[1]

    sample_path = os.path.join(os.path.dirname(__file__), filename)

    if not os.path.exists(sample_path):
        print(f"      [Error] Sample file not found: {sample_path}")
        return

    with open(sample_path) as f:
        data = json.load(f)

    attribution = data.get("attribution", {})

    print("\n      ⚔️  PHASE 3: INDUSTRIAL ATTRIBUTION ANALYSIS")
    print("-" * 60)
    print(f"      [Run ID]: {data.get('run_id')}")
    print(f"      [Timestamp]: {data.get('timestamp')}")
    print("-" * 60)

    for key, val in attribution.items():
        bar_len = int(val * 20)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        print(f"      {key.replace('_', ' ').title():<18}: |{bar}| {val:.1f}")

    print("-" * 60)

    m_score = attribution.get("model_reasoning", 0)
    a_score = attribution.get("agent_logic", 0)

    if m_score < 0.5 and a_score > 0.5:
        print("      [RCA Outcome]: 🧠 MODEL FAILURE. (Logic is sound; model is misinterpreting).")
    elif a_score < 0.5 and m_score > 0.5:
        print(
            "      [RCA Outcome]: 🔧 AGENT FAILURE. (Model is reasoning correctly; logic is broken)."  # noqa: E501
        )
    else:
        print("      [RCA Outcome]: ⚠️ MIXED FAILURE. Both brain and body require attention.")

    print("-" * 60)
    print("      [NIST-100] Alignment: Root Cause Attributed.")


if __name__ == "__main__":
    render_chart()
