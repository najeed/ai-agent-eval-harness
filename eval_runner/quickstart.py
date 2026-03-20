import os
import sys
import subprocess
import time
import asyncio
import signal
from pathlib import Path
from . import engine
from . import reporter

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
        text=True
    )
    # Wait for the server to start (simple sleep for demo)
    time.sleep(2)
    return process

async def run_quickstart():
    """Executes the quickstart flow."""
    print("\n" + "="*50)
    print("🏃 AI Agent Eval Harness - Quickstart Demo")
    print("="*50 + "\n")
    
    agent_process = start_sample_agent()
    if not agent_process:
        return
    
    try:
        scenario_path = Path("industries/telecom/scenarios/technical_support/13814_home_internet_slow_speed.json")
        if not scenario_path.exists():
            print(f"❌ Error: Quickstart scenario not found at {scenario_path}")
            return
        
        print(f"📊 Running demo scenario: {scenario_path.name}")
        
        import json
        with open(scenario_path, "r", encoding="utf-8") as f:
            scenario = json.load(f)
            
        results = await engine.run_evaluation(scenario)
        
        print("\n✅ Quickstart evaluation complete!")
        reporter.generate_report(scenario, results, export_trajectory=True)
        
        # Also try to generate an HTML report if implemented
        if hasattr(reporter, 'generate_html_report'):
            html_path = reporter.generate_html_report(scenario, results)
            print(f"🎨 Visual Report: {html_path}")
            
    finally:
        print("\n🛑 Shutting down sample agent...")
        if agent_process:
            agent_process.terminate()
            agent_process.wait()
            print("✔ Agent server stopped.")
    
    print("\n" + "="*50)
    print("Instant Gratification Achieved! 🏆")
    print("="*50 + "\n")
