"""
agentv_runtime
AgentV OS Runtime Public Architecture & Contracts Package (v2.0.0).
"""

import eval_runner
from eval_runner import interfaces, reference, session_components
from eval_runner.config_resolver import ConfigResolver, ResolvedRuntimeConfig

__version__ = "2.0.0"
__runtime_api_version__ = eval_runner.__runtime_api_version__
__plugin_api_version__ = eval_runner.__plugin_api_version__
__config_schema_version__ = eval_runner.__config_schema_version__
__aes_schema_version__ = eval_runner.__aes_schema_version__

__all__ = [
    "interfaces",
    "reference",
    "session_components",
    "ConfigResolver",
    "ResolvedRuntimeConfig",
    "__version__",
    "__runtime_api_version__",
    "__plugin_api_version__",
    "__config_schema_version__",
    "__aes_schema_version__",
]
