"""
plugins.py

Plugin management system for AgentV.
Handles dynamic discovery and loading of evaluation plugins.
Updated to respect Zero-Touch architecture and immutable core.
"""

from abc import ABC  # noqa: I001
import concurrent.futures
import importlib.metadata
import importlib.util
import inspect
import json
import os
import time  # noqa: F401
from pathlib import Path
from typing import Any

from . import config, discovery

PLUGIN_TIMEOUT = config.PLUGIN_TIMEOUT
PERSISTENT_PLUGINS_PATH = config.PLUGINS_CONFIG_PATH
STRICT_PLUGINS = os.getenv("STRICT_PLUGINS", "false").lower() == "true"


def _invoke_with_timeout(func, *args, **kwargs):
    """Executes a plugin hook with a security timeout using a thread pool."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args, **kwargs)
        try:
            return future.result(timeout=PLUGIN_TIMEOUT)
        except concurrent.futures.TimeoutError:
            print(f"   [PluginManager] Timeout (>{PLUGIN_TIMEOUT}s) in hook execution.")
            raise


class BaseEvalPlugin(ABC):  # noqa: B024
    """Base class for all evaluation plugins."""

    def before_evaluation(self, context: Any, span_context: dict[str, Any] | None = None):  # noqa: B027
        """Hook called before the evaluation scenario begins."""
        pass

    def after_evaluation(  # noqa: B027
        self, context: Any, results: list, span_context: dict[str, Any] | None = None
    ):
        """Hook called after the evaluation scenario completes."""
        pass

    def on_register_commands(self, registry: Any):  # noqa: B027
        """Hook to register custom CLI commands."""
        pass

    def on_discover_adapters(self, registry: Any):  # noqa: B027
        """Hook to register custom agent adapters."""
        pass

    def on_register_simulators(self, registry: dict):  # noqa: B027
        """Hook to register custom world simulators."""
        pass

    def on_diagnose_failure(self, taxonomy: Any):  # noqa: B027
        """Hook to register custom forensic failure analyzers with the taxonomy engine."""
        pass


class PluginManager:
    """
    Orchestrates plugin lifecycle.
    Updated to support instantiation for session-scoped isolation.
    """

    def __init__(self):
        self.plugins: list[BaseEvalPlugin] = []
        self._plugins = self.plugins  # Alias for diagnostic visibility
        self.provenance_map: list[dict[str, Any]] = []
        self._loaded = False
        self._last_load_time = 0

    def reset(self):
        """Resets the plugin manager state for tests."""
        self.plugins.clear()
        self._loaded = False

    def load(self, path: str) -> dict[str, Any]:
        """
        Ad-hoc logic to load a single plugin from a path.
        Returns provenance metadata (path, hash) for forensic tracking.
        """
        path_obj = Path(path).resolve()
        if not path_obj.exists():
            raise FileNotFoundError(f"Plugin file not found: {path}")

        # 1. Forensic Hash Calculation
        from .forensics import compute_file_hash

        file_hash = compute_file_hash(path_obj)

        # 2. Dynamic Import
        module_name = path_obj.stem
        spec = importlib.util.spec_from_file_location(module_name, path_obj)
        if not spec or not spec.loader:
            raise ImportError(f"Could not load spec for plugin: {path}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # 3. Discovery & Instantiation
        found = False
        loaded_class = None
        for name_attr, obj in inspect.getmembers(module, inspect.isclass):
            # Ensure it's inside the module and inherits
            # (directly or indirectly) from BaseEvalPlugin
            # Note: module.__name__ is the canonical module name used during import
            if obj.__module__ == module.__name__ and any(
                base.__name__ == "BaseEvalPlugin" for base in obj.__mro__
            ):
                if not any(isinstance(p, obj) for p in self.plugins):
                    instance = obj()
                    self.plugins.append(instance)
                    found = True
                    loaded_class = name_attr
                    break
                else:
                    # Already loaded, find the existing one for metadata mapping
                    found = True
                    loaded_class = name_attr
                    break

        if not found:
            raise ValueError(f"No valid BaseEvalPlugin found in {path}")

        metadata = {"path": str(path_obj), "hash": file_hash, "class": loaded_class}
        self.provenance_map.append(metadata)
        return metadata

    def load_plugins(self, force: bool = False):
        """Discovers and loads plugins with an industrial 60s TTL debounce."""
        import time  # noqa: F811

        now = time.time()

        # Performance: Skip scan if loaded within 60s (unless forced)
        if self._loaded and not force:
            if now - self._last_load_time < 60:
                return

        self._last_load_time = now

        # 1. Discover external plugins via entry points (standard install)
        for entry_point in importlib.metadata.entry_points(group="eval_runner.plugins"):
            try:
                plugin_cls = entry_point.load()
                if not any(isinstance(p, plugin_cls) for p in self.plugins):
                    self.plugins.append(plugin_cls())
            except Exception as e:
                # Forensic Transparency: Log all entry-point failures
                print(
                    f"   [PluginManager] Warning: Entry-point load failure "
                    f"({entry_point.name}): {e}"
                )

        # 2. Load manually registered persistent plugins (Industrial Dictionary Schema Only)
        if PERSISTENT_PLUGINS_PATH.exists():
            try:
                from jsonschema.validators import validator_for

                from .loader import get_universal_registry

                with open(PERSISTENT_PLUGINS_PATH, encoding="utf-8") as f:
                    registry_data = json.load(f)

                universal_registry = get_universal_registry()
                # AUTHORITATIVELY resolve the plugins schema using the Logical Anchor
                # (Guardrails v3.4 Section 1.6 compliance)
                schema_uri = "https://agentv.co/spec/plugins/plugins.schema.json"
                try:
                    schema_resource = universal_registry.resolver().lookup(schema_uri).contents
                    validator_cls = validator_for(schema_resource)
                    validator = validator_cls(schema_resource, registry=universal_registry)
                    validator.validate(instance=registry_data)
                except Exception as ve:
                    # Registry Drift detected: This is a critical forensic warning
                    msg = (
                        f"   [PluginManager] CRITICAL: Registry Drift in {PERSISTENT_PLUGINS_PATH}"
                    )
                    print(f"{msg}: {ve}")
                    # In purity mode, we proceed but the warning is logged to the forensic trail

                for plugin_def in registry_data.get("plugins", []):
                    if not plugin_def.get("enabled", True):
                        continue

                    module_name = plugin_def.get("module")
                    class_name = plugin_def.get("class")
                    if not module_name or not class_name:
                        print(
                            f"   [PluginManager] Skipping malformed plugin definition: {plugin_def}"
                        )
                        continue

                    try:
                        module = importlib.import_module(module_name)
                        plugin_cls = getattr(module, class_name)
                        if not any(isinstance(p, plugin_cls) for p in self.plugins):
                            self.plugins.append(plugin_cls())
                    except Exception as e:
                        msg = (
                            f"   [PluginManager] Failed to load plugin "
                            f"{module_name}.{class_name}: {e}"
                        )
                        if STRICT_PLUGINS:
                            raise ValueError(msg) from e
                        print(msg)
            except Exception as e:
                # Fail Fast: Registry corruption is a forensic blocker
                msg = f"CRITICAL: Failed to read forensic registry {PERSISTENT_PLUGINS_PATH}: {e}"
                raise ValueError(msg) from e

        # 3. Dynamic search in project-root 'plugins' directory
        root_plugins = discovery.discover_plugins_in_directory(
            config.PROJECT_ROOT / "plugins", BaseEvalPlugin, package_prefix="plugins"
        )
        for p in root_plugins:
            if not any(isinstance(existing, p.__class__) for existing in self.plugins):
                self.plugins.append(p)

        # 4. Fallback for Internal Essential Plugins & Ecosystem Adapters
        # Discovery: Ensures core capabilities are loaded if entry-points are shadowed.
        internal_manifest = []

        # -- Core Essentials --
        try:
            from .coverage_plugin import CoveragePlugin

            internal_manifest.append(CoveragePlugin)
        except ImportError:
            # Debug log only for internal skips (expected in some envs)
            pass

        try:
            from .flight_recorder import FlightRecorderPlugin

            internal_manifest.append(FlightRecorderPlugin)
        except ImportError:
            pass

        try:
            from .reporting_plugin import ReportingPlugin

            internal_manifest.append(ReportingPlugin)
        except ImportError:
            pass

        try:
            from .artifact_plugin import ArtifactPlugin

            internal_manifest.append(ArtifactPlugin)
        except ImportError:
            pass

        try:
            from .publication_plugin import PublicationPlugin

            internal_manifest.append(PublicationPlugin)
        except ImportError:
            pass

        try:
            from .live_bridge_plugin import RemoteBridgePlugin

            internal_manifest.append(RemoteBridgePlugin)
        except ImportError:
            pass

        try:
            from .triage_plugin import TroubleshootingPlugin

            internal_manifest.append(TroubleshootingPlugin)
        except ImportError:
            pass

        # -- Ecosystem Adapters --
        try:
            from eval_runner.adapters.autogen import AutoGenAdapterPlugin
            from eval_runner.adapters.claude import ClaudeAdapterPlugin
            from eval_runner.adapters.crewai import CrewAIAdapterPlugin
            from eval_runner.adapters.gemini import GeminiAdapterPlugin
            from eval_runner.adapters.grok import GrokAdapterPlugin
            from eval_runner.adapters.langchain import LangChainAdapterPlugin
            from eval_runner.adapters.langgraph import LangGraphAdapterPlugin
            from eval_runner.adapters.ollama import OllamaAdapterPlugin
            from eval_runner.adapters.openai import OpenAIAdapterPlugin

            internal_manifest.extend(
                [
                    OpenAIAdapterPlugin,
                    GeminiAdapterPlugin,
                    ClaudeAdapterPlugin,
                    OllamaAdapterPlugin,
                    GrokAdapterPlugin,
                    AutoGenAdapterPlugin,
                    CrewAIAdapterPlugin,
                    LangGraphAdapterPlugin,
                    LangChainAdapterPlugin,
                ]
            )
        except ImportError:
            pass

        # Robust Instantiation Loop (Zero-Touch Isolation)
        for PluginClass in internal_manifest:
            try:
                # Deduplication: Only load if an instance of this class doesn't exist
                if not any(isinstance(p, PluginClass) for p in self.plugins):
                    self.plugins.append(PluginClass())
            except Exception as e:
                # Log isolated failure without crashing the manager
                print(f"   [PluginManager] Isolated Failure loading {PluginClass.__name__}: {e}")

        self._loaded = True

    def trigger(self, hook_name: str, *args, **kwargs):
        """Triggers a plugin hook across all loaded plugins with timeout."""
        self.load_plugins()
        for plugin in self.plugins:
            if hasattr(plugin, hook_name):
                try:
                    hook = getattr(plugin, hook_name)
                    _invoke_with_timeout(hook, *args, **kwargs)
                except Exception as e:
                    print(
                        f"   [PluginManager] Error in {hook_name} for {plugin.__class__.__name__}: {e}"  # noqa: E501
                    )

    def finalize(self):
        """
        Explicitly triggers cleanup on all loaded plugins.
        Targeted at plugins that maintain file handles or state (e.g. FlightRecorder).
        """
        for plugin in self.plugins:
            # 1. Check for dedicated finalize_run (FlightRecorder pattern)
            if hasattr(plugin, "finalize_run"):
                try:
                    plugin.finalize_run()
                except Exception as e:
                    print(
                        f"   [PluginManager] Finalization Error ({plugin.__class__.__name__}): {e}"
                    )
            # 2. Check for general cleanup hook
            elif hasattr(plugin, "cleanup"):
                try:
                    plugin.cleanup()
                except Exception as e:
                    print(f"   [PluginManager] Cleanup Error ({plugin.__class__.__name__}): {e}")

    def trigger_interceptor(self, hook_name: str, *args, **kwargs) -> bool:
        """
        Triggers an interceptor hook and returns False if any plugin rejects the action.
        Defaults to True (allow).
        """
        self.load_plugins()
        for plugin in self.plugins:
            if hasattr(plugin, hook_name):
                try:
                    hook = getattr(plugin, hook_name)
                    result = hook(*args, **kwargs)
                    if result is False:
                        return False
                except Exception as e:
                    print(
                        f"   [PluginManager] Error in interceptor {hook_name} for {plugin.__class__.__name__}: {e}"  # noqa: E501
                    )
        return True

    def register_persistent(
        self,
        module_path: str,
        class_name: str | None = None,
        name: str | None = None,
        plugin_id: str | None = None,
    ):
        """Register a plugin persistently using the split module/class dictionary schema."""
        PERSISTENT_PLUGINS_PATH.parent.mkdir(parents=True, exist_ok=True)
        registry = {"plugins": []}
        if PERSISTENT_PLUGINS_PATH.exists():
            with open(PERSISTENT_PLUGINS_PATH, encoding="utf-8") as f:
                registry = json.load(f)

        # Forensic Normalization: Robust Discovery logic
        if not class_name:
            if module_path.endswith(".py") or os.path.isfile(module_path):
                # 1. It's a file. Normalize to stem and try to find the class.
                path_obj = Path(module_path)
                module_name = path_obj.stem

                # Heuristic 1: CamelCase candidate generation
                heuristic_base = "".join(x.capitalize() for x in module_name.split("_"))
                heuristic_candidates = {heuristic_base, f"{heuristic_base}Plugin"}

                # Heuristic 2: Introspection (Advanced Discovery)
                try:
                    spec = importlib.util.spec_from_file_location(module_name, module_path)
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)

                        # Find all classes inheriting from BaseEvalPlugin
                        # (Avoiding circular import by comparing class name/base)
                        candidates = []
                        for name_attr, obj in inspect.getmembers(module, inspect.isclass):
                            if obj.__module__ != module.__name__:
                                continue
                            if any(
                                base.__name__ == "BaseEvalPlugin" or base.__name__ == "ABC"
                                for base in obj.__mro__
                            ):
                                candidates.append(name_attr)

                        if len(candidates) == 1:
                            class_name = candidates[0]
                        elif len(candidates) > 1:
                            # Intersection of candidates and heuristics
                            matches = heuristic_candidates.intersection(set(candidates))
                            if len(matches) == 1:
                                class_name = list(matches)[0]
                            else:
                                raise ValueError(
                                    f"Ambiguous plugin file: {len(candidates)} candidates found. "
                                    f"Please specify --class explicitly."
                                )

                        if not class_name:
                            class_name = heuristic_base
                except Exception as e:
                    if "Ambiguous" in str(e):
                        raise
                    # Fallback to the first heuristic if introspection is inconclusive
                    class_name = heuristic_base

                # Use the stem as the module path for registration to keep it portable
                module_path = module_name
            elif "." in module_path:
                # Assume legacy format module.Class
                module_path, class_name = module_path.rsplit(".", 1)

        if not class_name:
            raise ValueError(f"CRITICAL: Failed to resolve class_name for {module_path}")

        # Schema Alignment: Determine authoritative name and ID
        pid = plugin_id or class_name.lower()
        pname = name or pid

        # Collision check
        existing = [
            p
            for p in registry["plugins"]
            if p.get("module") == module_path and p.get("class") == class_name
        ]

        if not existing:
            registry["plugins"].append(
                {
                    "id": pid,
                    "name": pname,
                    "module": module_path,
                    "class": class_name,
                    "enabled": True,
                    "config": {},
                }
            )
            with open(PERSISTENT_PLUGINS_PATH, "w", encoding="utf-8") as f:
                json.dump(registry, f, indent=4)
            print(
                f"   [Plugins] Persistent registration saved: {pname} ({module_path}.{class_name})"
            )
        else:
            print(f"   [Plugins] Plugin already exists in registry: {module_path}.{class_name}")

    def unregister_persistent(self, module_path: str, class_name: str | None = None):
        """Unregister a plugin persistently by removing it from the dictionary-based registry."""
        if not PERSISTENT_PLUGINS_PATH.exists():
            return

        with open(PERSISTENT_PLUGINS_PATH, encoding="utf-8") as f:
            registry = json.load(f)

        initial_count = len(registry["plugins"])

        # Forensic Normalization: Consistent discovery for unregistration
        if not class_name:
            if module_path.endswith(".py") or os.path.isfile(module_path):
                module_path = Path(module_path).stem
            elif "." in module_path:
                module_path, class_name = module_path.rsplit(".", 1)

        if class_name:
            registry["plugins"] = [
                p
                for p in registry["plugins"]
                if not (p.get("module") == module_path and p.get("class") == class_name)
            ]
        else:
            # Fallback for name/id based removal if only one arg provided and no dots
            registry["plugins"] = [
                p
                for p in registry["plugins"]
                if p.get("module") != module_path
                and p.get("id") != module_path
                and p.get("name") != module_path
            ]

        if len(registry["plugins"]) < initial_count:
            with open(PERSISTENT_PLUGINS_PATH, "w", encoding="utf-8") as f:
                json.dump(registry, f, indent=4)
            print(
                f"   [Plugins] Persistent registration removed for: "
                f"{module_path}.{class_name or ''}"
            )
        else:
            print(f"   [Plugins] No plugin found matching: {module_path}.{class_name or ''}")


manager = PluginManager()
