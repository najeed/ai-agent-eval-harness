---
title: CrewAI Integration Guide
description: Evaluate multi-agent hierarchical crews, task delegation, and role coordination with AgentV.
---

AgentV provides first-class support for **CrewAI**, enabling rigorous evaluation of multi-agent collaboration, delegation loops, tool assignments, and role-based execution.

---

## 🏗️ 1. Building the CrewAI Adapter Service

Wrap your CrewAI multi-agent crew in a FastAPI service conforming to the AgentV REST contract:

```python
from fastapi import FastAPI, Request
from crewai import Agent, Crew, Task, Process
from crewai.tools import tool

app = FastAPI(title="CrewAI Multi-Agent Evaluation Adapter")


# Define mock tools that bridge to the AgentV world shim
@tool("Fetch KYC Data")
def fetch_kyc_data(applicant_id: str) -> str:
    """Fetches applicant tax and credit records."""
    # In a real run, this can call back into the harness or mock local DB
    return f"KYC Verified for {applicant_id}: Income $140,000, Debt $32,000"


# Define specialized role agents
researcher = Agent(
    role="Senior Credit Analyst",
    goal="Verify financial background and compute financial ratios",
    backstory="You are an expert underwriter specializing in risk evaluation.",
    tools=[fetch_kyc_data],
    verbose=True,
)

compliance_officer = Agent(
    role="Chief Compliance Officer",
    goal="Ensure all credit decisions strictly conform to lending policy FIN-POL-402",
    backstory="You ensure zero regulatory drift and enforce strict audit rules.",
    verbose=True,
)


@app.post("/execute_task")
async def execute_task(request: Request):
    payload = await request.json()
    task_desc = payload["task_description"]

    # Define tasks for crew
    analysis_task = Task(
        description=f"Analyze loan request: {task_desc}",
        expected_output="Detailed credit report with recommended decision.",
        agent=researcher,
    )

    compliance_task = Task(
        description="Verify the analyst recommendation against FIN-POL-402 policy rules.",
        expected_output="Final approved or declined certification string.",
        agent=compliance_officer,
    )

    # Instantiate and run the crew
    crew = Crew(
        agents=[researcher, compliance_officer],
        tasks=[analysis_task, compliance_task],
        process=Process.sequential,
        verbose=True,
    )

    result = crew.kickoff()

    return {
        "action": "final_answer",
        "summary": str(result),
        "metadata": {
            "agents_involved": ["Senior Credit Analyst", "Chief Compliance Officer"],
            "raw_output": str(result),
        },
    }
```

---

## 🚀 2. Running the Evaluation

Launch the CrewAI service:
```bash
uvicorn crew_agent:app --host 127.0.0.1 --port 8000
```

Execute the evaluation run:
```bash
agentv evaluate \
  --path industries/finance/scenarios/loan_approval_risk_check.json \
  --protocol crewai \
  --agent http://127.0.0.1:8000/execute_task \
  --agent-name "CrewAI-Underwriting-Team" \
  --attempts 1
```

---

## 🛡️ 3. Auditing Multi-Agent Delegation Loops

One of the most critical failure modes in multi-agent crews is **infinite delegation** or ping-ponging between roles. AgentV includes a built-in metric:
- `delegation_loop_risk`: Analyzes inter-agent communication chains to flag circular replanning and excessive token burn.
