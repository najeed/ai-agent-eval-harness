"""
handlers/environment.py

Environment, utilities, and setup handlers.
"""

from pathlib import Path

from .. import (
    analyzer,
    auto_translate,
    catalog,
    cleaner,
    doctor,
    exporter,
    failure_corpus,
    registry_sync,
    scaffold,
)


async def handle_analyze(args):
    """Handler for 'analyze' command."""
    await analyzer.analyze_repo(args.url)


async def handle_auto_translate(args):
    """Handler for 'auto-translate' command."""
    text = auto_translate.extract_text(args.input)
    scenario = await auto_translate.translate_to_scenario(
        text, industry=args.industry, model=args.model
    )
    auto_translate.save_scenario(scenario, Path(args.output or "translated_scenario.json"))


async def handle_init(args):
    """Handler for 'init' command."""
    if getattr(args, "standard", None):
        scaffold.init_standard(args.standard)
    else:
        scaffold.scaffold_benchmark(args.dir, industry=args.industry, protocol=args.protocol)


async def handle_install(args):
    """Handler for 'install' command."""
    catalog.install_pack(args.pack)


async def handle_registry_sync(args):
    """Handler for 'registry sync' command."""
    registry_sync.ensure_schema_sync(force=True)


async def handle_registry_add(args):
    """Handler for 'registry add' command."""
    registry_sync.add_standard_to_registry(
        args.id,
        getattr(args, "name", "New Standard"),
        args.industry,
        getattr(args, "description", "No description provided"),
    )


async def handle_registry_search(args):
    """Handler for 'registry search' command."""
    from .scenarios import handle_catalog_search

    await handle_catalog_search(args)


async def handle_plugin_list(args):
    """Handler for 'plugin list' command."""
    from .. import plugins

    plugins.manager.load_plugins()
    print("\nLoaded Plugins:")
    for p in plugins.manager.plugins:
        print(f" - {p.__class__.__name__}")


async def handle_plugin_register(args):
    """Handler for 'plugin register' command."""
    from ..plugins import manager

    try:
        # Standardize registration using the Authoritative PluginManager
        # This ensures schema compliance (module/class split)
        manager.register_persistent(args.path)
        print(f"✅ Registered plugin: {args.path}")
    except Exception as e:
        print(f"❌ Error during registration: {e}")


async def handle_plugin_unregister(args):
    """Handler for 'plugin unregister' command."""
    from ..plugins import manager

    try:
        manager.unregister_persistent(args.name)
        print(f"✅ Unregistered plugin: {args.name}")
    except Exception as e:
        print(f"❌ Error during unregistration: {e}")


async def handle_doctor(args):
    """Handler for 'doctor' command. Safely handles existing loops."""
    await doctor.run_doctor(show_registry=getattr(args, "registry", False))


async def handle_ci_generate(args):
    """Handler for 'ci generate' command."""
    scaffold.generate_github_action()


async def handle_cleanup_runs(args):
    """Handler for 'cleanup-runs' command."""
    cleaner.cleanup_traces(days=args.days, force=getattr(args, "force", False))


async def handle_export(args):
    """Handler for 'export' command."""
    exporter.HFExporter.export(args.input, args.output)


async def handle_failures_search(args):
    """Handler for 'failures search' command."""
    failure_corpus.search(args.query)


def detect_framework():
    """Heuristic to detect the agent framework from the CWD."""
    cwd = Path.cwd()
    if (cwd / "langgraph.json").exists() or (cwd / "nodes.py").exists():
        return "LangGraph"
    if (cwd / "crew.py").exists() or (cwd / "agents.yaml").exists():
        return "CrewAI"
    if (cwd / "requirements.txt").exists():
        reqs = (cwd / "requirements.txt").read_text()
        if "langgraph" in reqs.lower():
            return "LangGraph"
        if "crewai" in reqs.lower():
            return "CrewAI"
    return "Custom"


def list_industries():
    """Returns the list of available industry categories."""
    return [
        "accounting",
        "finance",
        "healthcare",
        "telecom",
        "retail",
        "manufacturing",
        "supply_chain",
        "logistics",
    ]
