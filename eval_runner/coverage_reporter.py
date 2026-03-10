"""
coverage_reporter.py

Generates HTML heatmaps from grounding coverage data.
"""

import json
from pathlib import Path
from typing import Dict, Any, List
from .context import EvaluationContext

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Grounding Coverage Heatmap</title>
    <style>
        body {{ font-family: sans-serif; margin: 20px; background: #f4f4f9; }}
        h1, h2 {{ color: #333; }}
        .card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }}
        .item {{ padding: 15px; border-radius: 4px; text-align: center; font-weight: bold; border: 1px solid #ddd; }}
        .hit {{ background: #d4edda; color: #155724; border-color: #c3e6cb; }}
        .miss {{ background: #f8d7da; color: #721c24; border-color: #f5c6cb; }}
        .count {{ font-size: 0.8em; display: block; margin-top: 5px; opacity: 0.7; }}
        .legend {{ margin-bottom: 10px; font-size: 0.9em; }}
        .dot {{ height: 10px; width: 10px; border-radius: 50%; display: inline-block; margin-right: 5px; }}
    </style>
</head>
<body>
    <h1>Grounding Coverage Heatmap: {scenario_id}</h1>
    
    <div class="card">
        <h2>Policy Enforcement Coverage</h2>
        <div class="legend">
            <span class="dot" style="background: #d4edda;"></span> Covered
            <span class="dot" style="background: #f8d7da; margin-left: 10px;"></span> Not Exercised
        </div>
        <div class="grid">
            {policy_items}
        </div>
    </div>

    <div class="card">
        <h2>Tool / Knowledge Base Coverage</h2>
        <div class="grid">
            {tool_items}
        </div>
    </div>
</body>
</html>
"""

def generate_coverage_report(context: EvaluationContext, output_path: Path):
    """Generates an HTML report showing metrics coverage."""
    hits = context.grounding_hits
    scenario = context.scenario_data
    
    all_policies = scenario.get("policies", {}).keys()
    all_tools = scenario.get("tools_required", []) or scenario.get("tools", {}).keys()
    
    policy_html = ""
    for p in all_policies:
        count = hits["policies"].get(p, 0)
        cls = "hit" if count > 0 else "miss"
        policy_html += f'<div class="item {cls}">{p}<span class="count">{count} hits</span></div>'
        
    tool_html = ""
    for t in all_tools:
        count = hits["tools"].get(t, 0)
        cls = "hit" if count > 0 else "miss"
        tool_html += f'<div class="item {cls}">{t}<span class="count">{count} hits</span></div>'

    html = HTML_TEMPLATE.format(
        scenario_id=context.scenario_id,
        policy_items=policy_html if policy_html else "No policies defined",
        tool_items=tool_html if tool_html else "No tools defined"
    )
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"   [Coverage] Heatmap report generated: {output_path}")
