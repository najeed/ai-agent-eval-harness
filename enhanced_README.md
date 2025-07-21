# 🤖 AI Agent Evaluation Harness

[![CI](https://github.com/najeed/ai-agent-eval-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/najeed/ai-agent-eval-harness/actions)
[![Tests](https://github.com/najeed/ai-agent-eval-harness/actions/workflows/test.yml/badge.svg)](https://github.com/najeed/ai-agent-eval-harness/actions)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Contributors](https://img.shields.io/github/contributors/najeed/ai-agent-eval-harness)](https://github.com/najeed/ai-agent-eval-harness/graphs/contributors)

An open-source, standardized framework for evaluating AI agent performance across industries and use cases. Built for developers, researchers, and businesses who need reliable, reproducible benchmarks for their AI agents.

## 🚀 Quick Start

### Prerequisites
- Python 3.8 or higher
- pip package manager
- Git

### Installation

```bash
# Clone the repository
git clone https://github.com/najeed/ai-agent-eval-harness.git
cd ai-agent-eval-harness

# Install the package
pip install -e .

# (Optional) Install development dependencies
pip install -r requirements-dev.txt
```

### Run Your First Evaluation

```bash
# Run a manufacturing scenario
python -m eval_runner --industry manufacturing --scenario maintenance_repair

# Run all scenarios in healthcare
python -m eval_runner --industry healthcare --scenario all

# Get help
python -m eval_runner --help
```

### Expected Output
```
=== AI Agent Evaluation Results ===
Industry: Manufacturing
Scenario: Maintenance & Repair
Agent: YourAgentName

Metrics:
✓ Task Completion: 85% (17/20 tasks completed)
✓ Accuracy: 92% (correct solutions)
✓ Average Response Time: 2.3s
✓ Cost Efficiency: $0.15 per task

Overall Score: 88/100
Recommendation: Production Ready ✅
```

## 📁 Project Structure

```
ai-agent-eval-harness/
├── industries/                 # Industry-specific evaluation assets
│   ├── manufacturing/
│   │   ├── scenarios/         # JSON scenario definitions
│   │   │   ├── maintenance_repair.json
│   │   │   └── quality_assurance_control.json
│   │   └── datasets/          # Supporting data files
│   │       ├── equipment_data.csv
│   │       └── failure_logs.jsonl
│   ├── healthcare/
│   ├── finance/
│   └── retail/
├── eval_runner/               # Core evaluation engine
│   ├── __init__.py
│   ├── runner.py             # Main evaluation logic
│   ├── metrics.py            # Scoring algorithms
│   ├── agents.py             # Agent interface definitions
│   └── utils.py              # Helper functions
├── tests/                    # Test suite
├── docs/                     # Documentation
├── examples/                 # Example implementations
└── README.md
```

## 🎯 Supported Industries & Scenarios

| Industry | Scenarios Available | Status |
|----------|-------------------|--------|
| 🏭 **Manufacturing** | Maintenance & Repair, Quality Control, Supply Chain | ✅ Stable |
| 🏥 **Healthcare** | Diagnosis Support, Treatment Planning | 🚧 In Progress |
| 💰 **Finance** | Risk Assessment, Fraud Detection | 📋 Planned |
| 🛒 **Retail** | Customer Service, Inventory Management | 📋 Planned |
| 🚗 **Automotive** | Autonomous Driving, Predictive Maintenance | 💡 Proposed |

[➕ Request a new industry](https://github.com/najeed/ai-agent-eval-harness/issues/new?template=industry_request.md)

## 🧠 Integrating Your AI Agent

### Step 1: Implement the Agent Interface

```python
from eval_runner.agents import BaseAgent

class MyCustomAgent(BaseAgent):
    def __init__(self, model_name="gpt-4"):
        self.model_name = model_name
        # Initialize your agent here
    
    def execute(self, task: dict) -> dict:
        """
        Execute a task and return results.
        
        Args:
            task: Dictionary containing task description and context
            
        Returns:
            Dictionary with agent's response and metadata
        """
        # Your agent logic here
        response = self.your_agent_logic(task["description"])
        
        return {
            "answer": response,
            "confidence": 0.95,
            "reasoning": "Step-by-step explanation...",
            "metadata": {
                "model": self.model_name,
                "tokens_used": 150,
                "cost": 0.003
            }
        }

# Register your agent
agent = MyCustomAgent()
```

### Step 2: Run Evaluation

```python
from eval_runner import EvaluationRunner

runner = EvaluationRunner()
results = runner.evaluate(
    agent=agent,
    industry="manufacturing",
    scenario="maintenance_repair"
)

print(f"Score: {results.overall_score}/100")
```

### Popular Framework Adapters

We provide ready-to-use adapters for popular frameworks:

```python
# LangChain
from eval_runner.adapters import LangChainAdapter
agent = LangChainAdapter(your_langchain_agent)

# OpenAI API
from eval_runner.adapters import OpenAIAdapter  
agent = OpenAIAdapter(api_key="your-key", model="gpt-4")

# AutoGPT
from eval_runner.adapters import AutoGPTAdapter
agent = AutoGPTAdapter(your_autogpt_config)
```

## 📊 Understanding Evaluation Metrics

### Core Metrics
- **Accuracy**: Correctness of agent responses (0-100%)
- **Completeness**: How fully tasks are completed (0-100%)
- **Efficiency**: Response time and resource usage
- **Cost**: API calls, tokens, computational resources
- **Safety**: Adherence to safety guidelines and constraints

### Industry-Specific Metrics
- **Healthcare**: Clinical accuracy, safety protocols, ethical considerations
- **Finance**: Regulatory compliance, risk assessment accuracy
- **Manufacturing**: Operational efficiency, safety compliance

### Custom Metrics
```python
# Define custom evaluation criteria
custom_metrics = {
    "domain_expertise": {
        "weight": 0.3,
        "evaluator": "expert_human_review"
    },
    "creativity": {
        "weight": 0.2, 
        "evaluator": "automated_novelty_score"
    }
}
```

## 🔧 Advanced Usage

### Batch Evaluation
```bash
# Evaluate multiple agents
python -m eval_runner --batch --agents agent1,agent2,agent3 --scenario all

# Compare performance
python -m eval_runner --compare --baseline gpt-3.5 --candidates gpt-4,claude-v1
```

### Custom Scenarios
```bash
# Create a new scenario
python -m eval_runner --create-scenario --industry healthcare --name "emergency_triage"

# Validate scenario format
python -m eval_runner --validate-scenario path/to/scenario.json
```

### Export Results
```bash
# Export to various formats
python -m eval_runner --export csv --output results.csv
python -m eval_runner --export json --output results.json
python -m eval_runner --export html --output report.html
```

## 🤝 Contributing

We welcome contributions! Here are ways to get involved:

### 🌟 Quick Contributions
- ⭐ Star this repository
- 🐛 [Report bugs](https://github.com/najeed/ai-agent-eval-harness/issues/new?template=bug_report.md)
- 💡 [Suggest features](https://github.com/najeed/ai-agent-eval-harness/issues/new?template=feature_request.md)
- 📖 Improve documentation

### 🔨 Code Contributions
- 🆕 [Good first issues](https://github.com/najeed/ai-agent-eval-harness/labels/good%20first%20issue)
- 🧪 Add test scenarios
- 🏭 [Contribute new industries](https://github.com/najeed/ai-agent-eval-harness/issues/new?template=industry_request.md)
- 🎯 [Create evaluation scenarios](https://github.com/najeed/ai-agent-eval-harness/issues/new?template=scenario_contribution.md)

### 📋 Development Setup
```bash
# Fork the repository, then:
git clone https://github.com/YOUR-USERNAME/ai-agent-eval-harness.git
cd ai-agent-eval-harness

# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linting
black . && flake8 .

# Submit a pull request!
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

## 📚 Documentation & Examples

- 📖 [Full Documentation](docs/)
- 🎯 [Scenario Creation Guide](docs/creating-scenarios.md)
- 🔌 [Agent Integration Guide](docs/agent-integration.md) 
- 📊 [Metrics Reference](docs/metrics.md)
- 🎨 [Example Implementations](examples/)

## 🏆 Community & Recognition

### Contributors
Thanks to all our contributors! 🙌

<a href="https://github.com/najeed/ai-agent-eval-harness/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=najeed/ai-agent-eval-harness" />
</a>

### Community
- 💬 [Discord Server](https://discord.gg/ai-agent-eval) - Chat with the community
- 🐦 [Twitter](https://twitter.com/agentevals) - Latest updates
- 📧 [Newsletter](https://newsletter.ai-agent-eval.com) - Monthly insights

## 📈 Roadmap

### Q1 2025
- [ ] 🎯 10 industries, 50+ scenarios
- [ ] 🔧 Advanced metrics framework
- [ ] 📊 Web-based dashboard
- [ ] 🤖 Popular framework integrations

### Q2 2025
- [ ] 🏢 Enterprise features
- [ ] 🔐 Safety evaluation suite
- [ ] 📱 Mobile agent support
- [ ] 🌍 Multi-language scenarios

[View full roadmap →](ROADMAP.md)

## ❓ FAQ

### How is this different from other evaluation frameworks?
- **Industry-focused**: Real-world scenarios, not just academic benchmarks
- **Standardized**: Consistent metrics across different agent types
- **Community-driven**: Open source with active contributor community
- **Production-ready**: Built for enterprise use, not just research

### What agent frameworks are supported?
Currently: LangChain, OpenAI API, custom implementations. Coming soon: AutoGPT, AgentGPT, Microsoft Semantic Kernel.

### Can I use this for commercial projects?
Yes! Apache 2.0 license allows commercial use. Enterprise support available.

### How do I add my industry?
Check out our [Industry Contribution Guide](docs/adding-industries.md) or [open an issue](https://github.com/najeed/ai-agent-eval-harness/issues/new?template=industry_request.md).

## 📜 License

This project is licensed under the Apache 2.0 License - see the [LICENSE](LICENSE) file for details.

## 🙋‍♀️ Support

- 📖 Check the [Documentation](docs/)
- 🐛 [Report Issues](https://github.com/najeed/ai-agent-eval-harness/issues)
- 💬 [Join our Discord](https://discord.gg/ai-agent-eval)
- 📧 Email: support@ai-agent-eval.com

---

<div align="center">

**⭐ Star this repo if you find it useful! ⭐**

[Get Started](https://github.com/najeed/ai-agent-eval-harness/blob/main/docs/quickstart.md) • 
[Documentation](docs/) • 
[Contributing](CONTRIBUTING.md) • 
[Roadmap](ROADMAP.md)

Made with ❤️ by the AI Agent Evaluation community

</div>
