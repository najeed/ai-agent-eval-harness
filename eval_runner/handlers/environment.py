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
    utils,
)


def list_industries() -> list[str]:
    """Returns a list of supported industries based on registry and mapping."""
    # Anchored to AES v1.4 registry discovery
    try:
        registry = registry_sync.load_registry()
        reg_industries = list(registry.get("industries", {}).keys())
    except Exception:
        reg_industries = []

    # Merge with mapping
    mapped = list(utils.INDUSTRY_MAPPING.values())
    return sorted(
        list(
            set(
                reg_industries
                + mapped
                + [
                    "generic",
                    "finance",
                    "healthcare",
                    "telecom",
                    "manufacturing",
                    "retail",
                    "logistics",
                    "legal",
                    "education",
                    "energy",
                ]
            )
        )
    )


def detect_framework() -> str:
    """
    Heuristic framework discovery for onboarding standard.
    Detects LangGraph, CrewAI, AutoGen, and LangChain based on file signals and requirements.
    """
    cwd = Path.cwd()

    # 1. Framework-Specific File Signals
    if (cwd / "langgraph.json").exists() or (cwd / "nodes.py").exists():
        return "LangGraph"
    if (cwd / "crew.py").exists() or (cwd / "agents.yaml").exists():
        return "CrewAI"
    if (cwd / "conversable_agent.py").exists():
        return "AutoGen"

    # 2. Requirements.txt Scanning
    req_file = cwd / "requirements.txt"
    if req_file.exists():
        try:
            content = req_file.read_text().lower()
            if "langgraph" in content:
                return "LangGraph"
            if "crewai" in content:
                return "CrewAI"
            if "autogen" in content or "pyautogen" in content:
                return "AutoGen"
            if "langchain" in content:
                return "LangChain"
        except Exception as e:
            # Mitigation for non-critical requirement scan failures (v1.2.3 Forensic)
            import logging

            logging.getLogger(__name__).debug(f"Framework discovery check skipped: {e}")

    # 3. Path-based Signals (Common LangChain/AutoGen patterns)
    if (cwd / "libs" / "langchain").exists():
        return "LangChain"

    return "Custom"


async def handle_analyze(args):
    """Handler for 'analyze' command."""
    try:
        await analyzer.analyze_repo(args.url)
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Repository analysis FAILED: {e}")
        return 1


async def handle_auto_translate(args):
    """Handler for 'auto-translate' command."""
    try:
        text = auto_translate.extract_text(args.input)
        scenario = await auto_translate.translate_to_scenario(
            text, industry=args.industry, model=args.model
        )
        auto_translate.save_scenario(scenario, Path(args.output or "translated_scenario.json"))
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Auto-translation FAILED: {e}")
        return 1


async def handle_init(args):
    """Handler for 'init' command."""
    try:
        if getattr(args, "standard", None):
            scaffold.init_standard(args.standard)
        else:
            scaffold.scaffold_benchmark(args.dir, industry=args.industry, protocol=args.protocol)
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Environment initialization FAILED: {e}")
        return 1


async def handle_install(args):
    """Handler for 'install' command."""
    try:
        catalog.install_pack(args.pack)
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Installation FAILED: {e}")
        return 1


async def handle_registry_sync(args):
    """Handler for 'registry sync' command."""
    try:
        registry_sync.ensure_schema_sync(force=True)
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Registry synchronization FAILED: {e}")
        return 1


async def handle_registry_add(args):
    """Handler for 'registry add' command."""
    try:
        registry_sync.add_standard_to_registry(
            args.id,
            getattr(args, "name", "New Standard"),
            args.industry,
            getattr(args, "description", "No description provided"),
        )
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Registry registration FAILED: {e}")
        return 1


async def handle_registry_search(args):
    """Handler for 'registry search' command."""
    try:
        from .scenarios import handle_catalog_search

        return await handle_catalog_search(args)
    except Exception as e:
        print(f"❌ [ERROR] Registry search FAILED: {e}")
        return 1


async def handle_plugin_list(args):
    """Handler for 'plugin list' command."""
    try:
        from .. import plugins

        plugins.manager.load_plugins()
        print("\nLoaded Plugins:")
        for p in plugins.manager.plugins:
            print(f" - {p.__class__.__name__}")
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Failed to list plugins: {e}")
        return 1


async def handle_plugin_register(args):
    """Handler for 'plugin register' command."""
    from ..plugins import manager

    try:
        manager.register_persistent(args.path)
        print(f"✅ Registered plugin: {args.path}")
        return 0
    except Exception as e:
        print(f"❌ Error during registration: {e}")
        return 1


async def handle_plugin_unregister(args):
    """Handler for 'plugin unregister' command."""
    from ..plugins import manager

    try:
        manager.unregister_persistent(args.name)
        print(f"✅ Unregistered plugin: {args.name}")
        return 0
    except Exception as e:
        print(f"❌ Error during unregistration: {e}")
        return 1


async def handle_doctor(args):
    """Handler for 'doctor' command. Safely handles existing loops."""
    try:
        await doctor.run_doctor(show_registry=getattr(args, "registry", False))
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Doctor audit FAILED: {e}")
        return 1


async def handle_ci_generate(args):
    """Handler for 'ci generate' command."""
    try:
        scaffold.generate_github_action()
        return 0
    except Exception as e:
        print(f"❌ [ERROR] CI generation FAILED: {e}")
        return 1


async def handle_cleanup_runs(args):
    """Handler for 'cleanup-runs' command."""
    try:
        cleaner.cleanup_traces(days=args.days, force=getattr(args, "force", False))
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Cleanup FAILED: {e}")
        return 1


async def handle_export(args):
    """Handler for 'export' command."""
    try:
        exporter.HFExporter.export(args.input, args.output)
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Export FAILED: {e}")
        return 1


async def handle_failures_search(args):
    """Handler for 'failures search' command."""
    try:
        failure_corpus.search(args.query)
        return 0
    except Exception as e:
        print(f"❌ [ERROR] Failures search FAILED: {e}")
        return 1
