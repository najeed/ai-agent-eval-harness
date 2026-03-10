"""
dashboard/app.py

Streamlit application for visualizing AI Agent Evaluation trajectories and metrics.
"""

import streamlit as st
import json
import os
from pathlib import Path

# Set page configuration for a premium look
st.set_page_config(
    page_title="AI Agent Eval Lab",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for dark mode aesthetics
st.markdown("""
<style>
    .main {
        background-color: #0e1117;
    }
    .stMetric {
        background-color: #1e2130;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #3d4455;
    }
    .reportview-container {
        color: #fafafa;
    }
</style>
""", unsafe_allow_html=True)

st.title("🤖 AI Agent Evaluation Lab: Trajectory Dashboard")

# Trajectory discovery
TRAJECTORY_DIR = Path("reports/trajectories")
if not TRAJECTORY_DIR.exists():
    TRAJECTORY_DIR.mkdir(parents=True, exist_ok=True)

files = sorted(TRAJECTORY_DIR.glob("*.json"), key=os.path.getmtime, reverse=True)

if not files:
    st.info("No evaluation trajectories found. Run an evaluation with `--export` to see results here.")
    st.stop()

# Sidebar selection
selected_file = st.sidebar.selectbox("Select Evaluation Run", files, format_func=lambda x: x.name)

# Load data
with open(selected_file, "r") as f:
    data = json.loads(f.read())

metadata = data.get("metadata", {})
results = data.get("results", [])

# Header Metrics
st.header(f"Run: {metadata.get('title', 'Unknown Scenario')}")
st.subheader(f"Industry: {metadata.get('industry', 'N/A')} | Timestamp: {metadata.get('timestamp')}")

col1, col2, col3, col4 = st.columns(4)

total_tasks = len(results)
success_count = sum(1 for r in results if all(m["success"] for m in r["metrics"]))
avg_parsimony = 0.0
parsimony_scores = []

for r in results:
    for m in r["metrics"]:
        if m["metric"] == "path_parsimony":
            parsimony_scores.append(m["score"])

if parsimony_scores:
    avg_parsimony = sum(parsimony_scores) / len(parsimony_scores)

with col1:
    st.metric("Total Tasks", total_tasks)
with col2:
    st.metric("Success Rate", f"{(success_count/total_tasks)*100:.1f}%" if total_tasks else "0%")
with col3:
    st.metric("Avg Parsimony", f"{avg_parsimony:.2f}")
with col4:
    st.metric("Scenario ID", metadata.get("scenario_id", "N/A"))

# Task Details
st.divider()

selected_task_id = st.selectbox("Detailed Task View", [r["task_id"] for r in results])
task_result = next(r for r in results if r["task_id"] == selected_task_id)

t_col1, t_col2 = st.columns([1, 2])

with t_col1:
    st.subheader("Metrics")
    for m in task_result["metrics"]:
        status_color = "green" if m["success"] else "red"
        st.markdown(f"**{m['metric']}**: :{status_color}[{m['score']:.2f}] (Threshold: {m['threshold']:.2f})")

    st.subheader("Conversation History")
    for msg in task_result.get("conversation_history", []):
        with st.expander(f"{msg['role'].capitalize()}: {str(msg.get('content'))[:50]}..."):
            st.json(msg)

with t_col2:
    st.subheader("Decision Trajectory Map")

    # Generate Mermaid from data
    history = task_result.get("conversation_history", [])
    mermaid_code = ["graph TD"]
    mermaid_code.append("  Start((Start))")
    
    prev_node = "Start"
    turn_idx = 1
    
    for entry in history:
        role = entry.get("role")
        content = entry.get("content", {})
        node_id = f"Turn_{turn_idx}_{role}"
        
        if role == "agent":
            action = content.get("action", "unknown")
            label = f"{turn_idx}: {action}"
            mermaid_code.append(f'  {node_id}["{label}"]')
            mermaid_code.append(f"  {prev_node} --> {node_id}")
            prev_node = node_id
        elif role == "environment":
            status = content.get("status", "success")
            label = f"Env: {status}"
            if status == "policy_violation":
                mermaid_code.append(f"  {node_id}{{Violation}}")
            else:
                mermaid_code.append(f'  {node_id}["{label}"]')
            mermaid_code.append(f"  {prev_node} --> {node_id}")
            prev_node = node_id
            turn_idx += 1
            
    mermaid_code.append(f"  {prev_node} --> End((End))")
    
    # Render using the built-in mermaid support if available or fallback to text
    st.code("\n".join(mermaid_code), language="mermaid")
    st.info("💡 Paste the code above into [Mermaid Live Editor](https://mermaid.live) for a full visual render.")

st.sidebar.markdown("---")
st.sidebar.caption("Digital Twin Lab v1.0")
