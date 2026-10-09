import subprocess
import sys
import time
from pathlib import Path

from . import engine, reporter


def start_sample_agent():
    """Starts the sample agent in a background process."""
    agent_path = Path("sample_agent") / "agent_app.py"
    if not agent_path.exists():
        print(f"❌ Error: Sample agent not found at {agent_path}")
        return None

    print("[Quickstart] Starting sample agent server...")
    # Use sys.executable to ensure we use the same python interpreter
    process = subprocess.Popen(
        [sys.executable, str(agent_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # Wait for the server to start (simple sleep for demo)
    time.sleep(2)
    return process


async def run_quickstart():
    """Executes the quickstart flow."""
    print("\n" + "=" * 50)
    print("🏃 AgentV - Quickstart Demo")
    print("=" * 50 + "\n")

    agent_process = start_sample_agent()
    if not agent_process:
        return

    try:
        scenario_path = Path(
            "industries/telecom/scenarios/technical_support/13814_home_internet_slow_speed.json"
        )
        if not scenario_path.exists():
            print(f"❌ Error: Quickstart scenario not found at {scenario_path}")
            return

        from . import loader
        from .runner import new_run_id

        print(f"📊 Running demo scenario: {scenario_path.name}")

        scenario = loader.load_scenario(scenario_path)
        scenario_id = str(
            scenario.get("id") or scenario.get("metadata", {}).get("id") or "quickstart"
        )
        run_id = new_run_id(scenario_id)

        # The bundled demo is self-contained.  Do not import optional external
        # entry-point plugins (which can start distributed runtimes) while it runs.
        from .plugins import disable_external_plugin_discovery

        with disable_external_plugin_discovery():
            results = await engine.run_evaluation(scenario, run_id=run_id)

        print("\n✅ Quickstart evaluation complete!")
        report_metadata = {
            "run_id": run_id,
            "protocol": "http",
            "agent": scenario.get("metadata", {}).get("agent", {}).get("endpoint"),
        }
        reporter.generate_report(
            scenario, results, metadata=report_metadata, export_trajectory=True
        )

        # Also try to generate an HTML report if implemented
        if hasattr(reporter, "generate_html_report"):
            html_path = reporter.generate_html_report(scenario, results, metadata=report_metadata)
            print(f"🎨 Visual Report: {html_path}")

    finally:
        try:
            # HTTP adapters use the backwards-compatible shared pool when a
            # run has not injected a pool of its own. Quickstart owns this
            # short-lived evaluation lifecycle, so it must release that pool.
            from .adapters import close_adapter_sessions

            await close_adapter_sessions()
        finally:
            print("\n🛑 Shutting down sample agent...")
            if agent_process:
                agent_process.terminate()
                agent_process.wait()
                print("✔ Agent server stopped.")

    print("\n" + "=" * 50)
    print("Instant Gratification Achieved! 🏆")
    print("=" * 50 + "\n")
