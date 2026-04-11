---
title: CrewAI
description: Bring multi-agent crew evaluation to the AgentV platform.
---

AgentV provides native support for CrewAI, allowing you to evaluate role-based agent orchestration and collaborative task execution.

## 1. Setup Your Agent API

Wrap your CrewAI agents in a standard HTTP endpoint.

```python
from crewai import Crew, Agent, Task
from fastapi import FastAPI

app = FastAPI()

@app.post("/execute_task")
async def execute(request: dict):
    # Map the task_description to a CrewAI Task
    # researcher = Agent(role='Researcher', ...)
    # task = Task(description=request["task_description"], agent=researcher)
    # crew = Crew(agents=[researcher], tasks=[task])
    # result = crew.kickoff()
    return {"action": "final_answer", "summary": str(result)}
```

## 2. Run Evaluation

Use the `crewai://` protocol to connect the harness to your agent service.

```bash
agentv evaluate \
  --run-id <id> \
  --protocol crewai \
  --agent crewai://localhost:8000/execute_task \
  --agent-name "CrewAI-Tech-Support"
```

## 3. High-Fidelity Auditing

The `crewai://` protocol utilizes the **Behavioral DNA** bus to track task hand-offs between individual agents in the crew, providing a clear audit trail of who did what and why.

```bash
# View the agent hand-offs in the Visual Debugger
agentv console
```
