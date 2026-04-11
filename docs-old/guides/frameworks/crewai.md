# Quickstart: CrewAI + AgentV

Bring multi-agent crew evaluation to the AgentV.

## 1. Setup Your Agent API
Wrap your crew in an API that processes task requests.

```python
from crewai import Crew, Agent, Task
from fastapi import FastAPI

app = FastAPI()

@app.post("/execute_task")
async def execute(request: dict):
    # Define your agents and tasks based on input
    # ...
    # crew = Crew(agents=[...], tasks=[...])
    # result = crew.kickoff()
    return {"content": result}
```

## 2. Register Your Crew
```bash
agentv evaluate --run-id <id> --agent http://localhost:8000/execute_task --agent-name "CrewAI-Financial-Analyst"
```

## 3. Generate Verified Report
```bash
agentv report --run-id <id> --share
```
