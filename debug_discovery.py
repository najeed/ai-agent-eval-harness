
import asyncio
from eval_runner.engine import AgentAdapterRegistry
from eval_runner.plugins import BaseEvalPlugin, manager

class MockDiscoveryPlugin(BaseEvalPlugin):
    def on_discover_adapters(self, registry):
        registry.register("mock_proto", self.mock_adapter)
    
    async def mock_adapter(self, payload, endpoint=None):
        return {"action": "final_answer", "content": "Mock discovery works!"}

async def test_debug():
    plugin = MockDiscoveryPlugin()
    manager.plugins.append(plugin)
    
    try:
        AgentAdapterRegistry._discovered = False
        AgentAdapterRegistry._adapters = {}
        
        print(f"Adapters before: {list(AgentAdapterRegistry._adapters.keys())}")
        response = await AgentAdapterRegistry.call_agent({}, protocol="mock_proto")
        print(f"SUCCESS: {response}")
    except Exception as e:
        import traceback
        print("FAILURE:")
        traceback.print_exc()
    finally:
        manager.plugins.remove(plugin)

if __name__ == "__main__":
    asyncio.run(test_debug())
