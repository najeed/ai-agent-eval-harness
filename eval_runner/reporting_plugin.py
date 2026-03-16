"""
reporting_plugin.py

Handles evaluation reports, reproduction scripts, and notifications.
Moved out of the core to allow Enterprise hot-swapping.
"""

from .plugins import BaseEvalPlugin
from .context import EvaluationContext
from . import reporter
from . import triage
from . import metrics
from pathlib import Path
from datetime import datetime

class ReportingPlugin(BaseEvalPlugin):
    """Orchestrates report generation and notifications after evaluation."""

    def on_metrics_calculated(self, context: EvaluationContext, all_attempt_results: list):
        """Calculates consistency score across multiple attempts."""
        if len(all_attempt_results) < 2:
            return

        print(f"   [ReportingPlugin] Calculating cross-attempt consistency...")
        
        # Calculate consistency per task
        num_tasks = len(all_attempt_results[0])
        for t_idx in range(num_tasks):
            summaries = []
            for attempt_res in all_attempt_results:
                task_res = attempt_res[t_idx]
                history = task_res.get("conversation_history", [])
                summary = self._extract_summary_from_history(history)
                summaries.append(summary)
            
            consistency_score = metrics.calculate_consistency_score(summaries)
            
            # Inject consistency metric into the last attempt's results for backward compat with tests
            last_task_res = all_attempt_results[-1][t_idx]
            last_task_res["metrics"].append({
                "metric": "consistency_score",
                "score": consistency_score,
                "threshold": 0.0,
                "success": True
            })

    def _extract_summary_from_history(self, history):
        agent_msgs = [m for m in history if m["role"] == "agent"]
        if not agent_msgs: return ""
        last_content = agent_msgs[-1].get("content", "")
        if isinstance(last_content, dict):
            return last_content.get("summary") or last_content.get("content") or ""
        return str(last_content)

    def on_register_commands(self, registry):
        """Plugins now use a secure namespace registry instead of extend_cli"""
        pass

    def after_evaluation(self, context: EvaluationContext, results: list):
        """Automatically called when evaluation finishes."""
        scenario = context.scenario_data
        
        # Note: In k-attempt runs, results is a list of lists.
        # Use the first attempt for the summary report (backwards compat)
        display_results = results[0] if isinstance(results[0], list) else results

        # 0. Apply Triage
        print("   [ReportingPlugin] Applying triage logic...")
        triage.TriageEngine.apply_triage(display_results)

        # 1. Standard Summary Report
        print("\n   [ReportingPlugin] Generating summary report...")
        reporter.generate_report(scenario, display_results, export_trajectory=True, metadata=context.metadata)
        
        # 2. Reproduction Script (Mock implementation)
        self.generate_repro_script(context)
        
        # 3. Notifications (Mock implementation)
        # We can check CLI args if we store them in a shared location, 
        # but for now we'll check context metadata.
        if context.metadata.get("args") and getattr(context.metadata["args"], "notify", False):
            import asyncio
            # We are in a sync hook, but need to call async dispatcher
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already in a loop, create task
                loop.create_task(self.dispatch_notifications(context, display_results))
            else:
                loop.run_until_complete(self.dispatch_notifications(context, display_results))

    def generate_repro_script(self, context: EvaluationContext):
        """Creates a standalone script to reproduce the evaluation."""
        scenario_id = context.scenario_id
        repro_dir = Path("reports") / "repro"
        repro_dir.mkdir(parents=True, exist_ok=True)
        
        # Security Guardrails: RCE Prevention
        # Generate as inert .txt to prevent auto-execution
        repro_path = repro_dir / f"repro_{scenario_id}.txt"
        
        # Strip potential arbitrary execution
        content = f"""# Reproduction script for {scenario_id}
# Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# 
# Usage:
# 1. Ensure you have the eval-harness installed: pip install .
# 2. Set your environment variables (AGENT_API_URL, etc.)
# 3. RUN: eval-harness run --path scenarios/{scenario_id}.json
#
# SECURITY NOTE: ONLY execute this manually after reviewing the scenario file.

eval-harness run --path scenarios/{scenario_id}.json
"""
        # Additional safety for scenarios that might contain shell commands
        content = content.replace("os.system", "[REDACTED]").replace("subprocess", "[REDACTED]")
        
        with open(repro_path, "w") as f:
            f.write(content)
        print(f"   [ReportingPlugin] Inert repro instructions generated: {repro_path}")

    async def dispatch_notifications(self, context: EvaluationContext, results: list):
        """Dispatches results to external webhooks (Slack/Discord/Custom)."""
        webhook_url = context.metadata.get("webhook_url")
        if not webhook_url:
            print("   [ReportingPlugin] Skip: No 'webhook_url' provided in metadata.")
            return

        print(f"   [ReportingPlugin] Dispatching notification to: {webhook_url[:20]}...")
        
        # Simple summary
        total = len(results)
        successes = 0
        for attempt_res in results:
            # Check if all tasks in this attempt succeeded
            if all(all(m.get("success", False) for m in tr.get("metrics", [])) for tr in attempt_res):
                successes += 1
        
        payload = {
            "text": f"🚀 *Evaluation Complete*\n*Scenario*: {context.scenario_id}\n*Success Rate*: {successes}/{total} tasks passed.",
            "attachments": [
                {
                    "title": "View Report",
                    "text": f"Reproduction script generated: reports/repro/repro_{context.scenario_id}.txt"
                }
            ]
        }

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_url, json=payload, timeout=5) as response:
                    if response.status < 300:
                        print("   [ReportingPlugin] Notification sent successfully.")
                    else:
                        print(f"   [ReportingPlugin] Webhook failed: {response.status}")
        except Exception as e:
            print(f"   [ReportingPlugin] Error dispatching notification: {e}")
