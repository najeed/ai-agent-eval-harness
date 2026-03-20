import json
import glob
import os
import collections
import datetime

# Paths
root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "industries")

# 1) Tool catalog
counts = collections.Counter()
examples = {}
for path in glob.glob(os.path.join(root, "**", "scenarios", "*.json"), recursive=True):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    sid = data.get("scenario_id")
    for t in data.get("tasks", []):
        tid = t.get("task_id")
        for tool in t.get("required_tools", []) or []:
            counts[tool] += 1
            if tool not in examples:
                examples[tool] = {"scenario_id": sid, "task_id": tid, "path": path}

catalog = {
    "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
    "tool_count": len(counts),
    "tools": [],
}
for tool, cnt in counts.most_common():
    catalog["tools"].append(
        {
            "name": tool,
            "count": cnt,
            "example": examples.get(tool),
        }
    )

out_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schemas")
os.makedirs(out_dir, exist_ok=True)
json_path = os.path.join(out_dir, "tool_catalog.json")
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(catalog, f, indent=2)

# 2) Questionable thresholds report
report = []
for path in glob.glob(os.path.join(root, "**", "scenarios", "*.json"), recursive=True):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    sid = data.get("scenario_id")
    for t in data.get("tasks", []):
        tid = t.get("task_id")
        for sc in t.get("success_criteria", []):
            thr = sc.get("threshold")
            if thr in (0.5, 1.0):
                report.append(
                    {
                        "scenario_id": sid,
                        "path": path,
                        "task_id": tid,
                        "metric": sc.get("metric"),
                        "threshold": thr,
                    }
                )

reports_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
os.makedirs(reports_dir, exist_ok=True)
json_report_path = os.path.join(reports_dir, "questionable_thresholds.json")
with open(json_report_path, "w", encoding="utf-8") as f:
    json.dump(
        {
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "entries": report,
        },
        f,
        indent=2,
    )

md_report_path = os.path.join(reports_dir, "questionable_thresholds.md")
with open(md_report_path, "w", encoding="utf-8") as f:
    f.write("# Questionable Success Thresholds\n\n")
    f.write("Thresholds of 0.5 or 1.0 are flagged for review.\n\n")
    f.write(f"Total entries: {len(report)}\n\n")
    f.write("| Scenario ID | Task ID | Metric | Threshold | File Path |\n")
    f.write("|---|---|---|---|---|\n")
    for e in report[:200]:
        f.write(
            f"| {e['scenario_id']} | {e['task_id']} | {e.get('metric','')} | {e['threshold']} | {e['path']} |\n"
        )

print(f"Wrote tool catalog: {json_path}")
print(
    f"Wrote questionable threshold reports: {json_report_path} and {md_report_path} (entries: {len(report)})"
)
