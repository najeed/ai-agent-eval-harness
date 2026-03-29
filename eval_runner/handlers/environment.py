"""
handlers/environment.py

Environment, utilities, and setup handlers.
"""

import json
import os
import datetime
from pathlib import Path
from .. import doctor, registry_sync, configuration, analyzer, auto_translate, scaffold, catalog, cleaner, exporter, failure_corpus

async def handle_analyze(args):
    """Handler for 'analyze' command."""
    await analyzer.analyze_repo(args.url)

async def handle_auto_translate(args):
    """Handler for 'auto-translate' command."""
    text = auto_translate.extract_text(args.input)
    scenario = await auto_translate.translate_to_scenario(text, industry=args.industry, model=args.model)
    auto_translate.save_scenario(scenario, Path(args.output or "translated_scenario.json"))

def handle_init(args):
    """Handler for 'init' command."""
    if getattr(args, "standard", None):
        scaffold.init_standard(args.standard)
    else:
        scaffold.scaffold_benchmark(args.dir, industry=args.industry, protocol=args.protocol)

def handle_install(args):
    """Handler for 'install' command."""
    catalog.install_pack(args.pack)

def handle_registry_sync(args):
    """Handler for 'registry sync' command."""
    registry_sync.ensure_schema_sync(force=True)

def handle_registry_add(args):
    """Handler for 'registry add' command."""
    registry_sync.add_standard_to_registry(args.id, getattr(args, "name", "New Standard"), args.industry, getattr(args, "description", "No description provided"))

def handle_registry_search(args):
    """Handler for 'registry search' command."""
    from .scenarios import handle_catalog_search
    handle_catalog_search(args)

def handle_plugin_list(args):
    """Handler for 'plugin list' command."""
    from .. import plugins
    plugins.manager.load_plugins()
    print("\nLoaded Plugins:")
    for p in plugins.manager.plugins:
        print(f" - {p.__class__.__name__}")

def handle_plugin_register(args):
    """Handler for 'plugin register' command."""
    from .. import plugins
    plugin_path = Path(args.path).resolve()
    if not plugin_path.exists():
        print(f"❌ Error: Plugin path '{plugin_path}' does not exist.")
        return

    # In Zero-Touch core, we manage a local manifest in .aes/plugins.json
    manifest_dir = Path(".aes")
    manifest_dir.mkdir(exist_ok=True)
    manifest_path = manifest_dir / "plugins.json"

    try:
        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        else:
            manifest = {"plugins": []}

        if str(plugin_path) not in manifest["plugins"]:
            manifest["plugins"].append(str(plugin_path))
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=4)
            print(f"✅ Registered plugin: {plugin_path}")
        else:
            print(f"ℹ️  Plugin already registered: {plugin_path}")
    except Exception as e:
        print(f"❌ Error during registration: {e}")

def handle_plugin_unregister(args):
    """Handler for 'plugin unregister' command."""
    manifest_path = Path(".aes/plugins.json")
    if not manifest_path.exists():
        print("ℹ️  No plugin manifest found (.aes/plugins.json).")
        return

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        
        target = str(Path(args.path).resolve())
        if target in manifest.get("plugins", []):
            manifest["plugins"].remove(target)
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=4)
            print(f"✅ Unregistered plugin: {target}")
        else:
            print(f"❌ Error: Plugin '{target}' not found in manifest.")
    except Exception as e:
        print(f"❌ Error during unregistration: {e}")

def handle_doctor(args):
    """Handler for 'doctor' command. Safely handles existing loops to avoid deadlocks."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Schedule the task on the existing loop (e.g., in a test)
        loop.create_task(doctor.run_doctor())
    else:
        asyncio.run(doctor.run_doctor())

def handle_ci_generate(args):
    scaffold.generate_github_action()

def handle_cleanup_runs(args):
    cleaner.cleanup_traces(days=args.days, force=getattr(args, "force", False))

def handle_export(args):
    exporter.HFExporter.export(args.input, args.output)

def handle_failures_search(args):
    failure_corpus.search(args.query)

def detect_framework():
    """Heuristic to detect the agent framework from the CWD."""
    cwd = Path.cwd()
    if (cwd / "langgraph.json").exists() or (cwd / "nodes.py").exists(): return "LangGraph"
    if (cwd / "crew.py").exists() or (cwd / "agents.yaml").exists(): return "CrewAI"
    if (cwd / "requirements.txt").exists():
        reqs = (cwd / "requirements.txt").read_text()
        if "langgraph" in reqs.lower(): return "LangGraph"
        if "crewai" in reqs.lower(): return "CrewAI"
    return "Custom"

def list_industries():
    """Returns the list of available industry categories."""
    return ["accounting", "finance", "healthcare", "telecom", "retail", "manufacturing", "supply_chain", "logistics"]
