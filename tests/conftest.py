"""
conftest.py

Shared fixtures and configuration for the AgentV test suite.
"""

import asyncio
import gc
import json
import logging
import os
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

_MEMORY_FORENSICS_ENV = "AGENTV_TEST_MEMORY_FORENSICS"
_MEMORY_FORENSICS_DIR_ENV = "AGENTV_TEST_MEMORY_FORENSICS_DIR"
_MEMORY_FORENSICS_THRESHOLD_ENV = "AGENTV_TEST_MEMORY_THRESHOLD_MB"
_MEMORY_FORENSICS_TRACEMALLOC_ENV = "AGENTV_TEST_MEMORY_TRACEMALLOC"


@dataclass
class _MemoryForensicsRecorder:
    """Opt-in per-worker RSS and Python-allocation forensic recorder."""

    path: Path
    threshold_bytes: int
    process: Any
    previous_rss: int
    previous_snapshot: tracemalloc.Snapshot | None
    trace_allocations: bool
    sequence: int = 0

    @classmethod
    def create(cls) -> "_MemoryForensicsRecorder":
        import psutil

        worker_id = os.getenv("PYTEST_XDIST_WORKER", "master")
        output_dir = Path(os.getenv(_MEMORY_FORENSICS_DIR_ENV, ".tmp/memory-forensics"))
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            threshold_mb = max(1, int(os.getenv(_MEMORY_FORENSICS_THRESHOLD_ENV, "256")))
        except ValueError:
            threshold_mb = 256

        trace_allocations = os.getenv(_MEMORY_FORENSICS_TRACEMALLOC_ENV, "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if trace_allocations and not tracemalloc.is_tracing():
            tracemalloc.start(25)

        process = psutil.Process(os.getpid())
        return cls(
            path=output_dir / f"{worker_id}-pid{process.pid}.jsonl",
            threshold_bytes=threshold_mb * 1024 * 1024,
            process=process,
            previous_rss=process.memory_info().rss,
            previous_snapshot=tracemalloc.take_snapshot() if trace_allocations else None,
            trace_allocations=trace_allocations,
        )

    def record(self, nodeid: str) -> None:
        gc.collect()
        current_rss = self.process.memory_info().rss
        rss_delta = current_rss - self.previous_rss

        self.sequence += 1
        event: dict[str, Any] = {
            "sequence": self.sequence,
            "nodeid": nodeid,
            "pid": self.process.pid,
            "rss_bytes": current_rss,
            "rss_delta_bytes": rss_delta,
        }

        if rss_delta >= self.threshold_bytes and self.trace_allocations:
            current_snapshot = tracemalloc.take_snapshot()
            if self.previous_snapshot is None:
                self.previous_snapshot = current_snapshot
            allocations = current_snapshot.compare_to(self.previous_snapshot, "lineno")
            traced_delta = sum(stat.size_diff for stat in allocations)
            event["traced_delta_bytes"] = traced_delta
            event["top_allocations"] = [
                {
                    "size_delta_bytes": stat.size_diff,
                    "count_delta": stat.count_diff,
                    "traceback": stat.traceback.format(),
                }
                for stat in allocations[:20]
                if stat.size_diff > 0
            ]
            self.previous_snapshot = current_snapshot
        elif rss_delta >= self.threshold_bytes:
            event["tracemalloc"] = "disabled"

        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")

        self.previous_rss = current_rss


try:
    from opentelemetry import trace

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False


@pytest.fixture(autouse=True)
def shutdown_tracer():
    """Explicitly shuts down the OpenTelemetry tracer provider at the end of each test."""
    yield
    if OTEL_AVAILABLE:
        try:
            provider = trace.get_tracer_provider()
            if hasattr(provider, "force_flush"):
                provider.force_flush()
            if hasattr(provider, "shutdown"):
                provider.shutdown()
        except (RuntimeError, AttributeError, ValueError) as flush_err:
            import logging

            logging.getLogger(__name__).debug(f"Tracer shutdown notice: {flush_err}")


@pytest_asyncio.fixture(autouse=True)
async def reset_sessions():
    """
    Industrial-grade connection teardown.
    Closes pooled sessions and allows a grace period for underlying transport cleanup.
    """
    yield
    from eval_runner.adapters.common import SessionManager

    try:
        await SessionManager.close_all()
        # Await only tasks that actually remain after explicit session close.
        loop = asyncio.get_running_loop()
        pending = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task(loop)]
        if pending:
            _, still_pending = await asyncio.wait(pending, timeout=0.25)
            for task in still_pending:
                task.cancel()
            if still_pending:
                await asyncio.gather(*still_pending, return_exceptions=True)
    except (TimeoutError, asyncio.CancelledError, RuntimeError, OSError) as session_err:
        import logging

        logging.getLogger(__name__).debug(f"Session teardown notice: {session_err}")


@pytest.fixture(autouse=True)
def reset_plugins():
    """Resets all registries before each test."""
    from eval_runner.catalog import ScenarioCatalog
    from eval_runner.engine import AgentAdapterRegistry
    from eval_runner.events import reset
    from eval_runner.loader import reset_universal_registry
    from eval_runner.metrics import MetricRegistry
    from eval_runner.plugins import manager

    manager.reset()
    AgentAdapterRegistry.reset()
    reset()
    MetricRegistry.reset()
    reset_universal_registry()
    ScenarioCatalog.clear_instance()
    from eval_runner.config import RegistryManager

    RegistryManager.reload()
    try:
        from eval_runner.otel_bridge import OTelTelemetryBridge

        OTelTelemetryBridge._subscribed = False
    except ImportError:
        pass
    yield
    try:
        manager.reset()
        AgentAdapterRegistry.reset()
        reset()
        MetricRegistry.reset()
        reset_universal_registry()
        ScenarioCatalog.clear_instance()
    except (AttributeError, KeyError, RuntimeError) as reset_err:
        import logging

        logging.getLogger(__name__).debug(f"Registry reset notice: {reset_err}")


@pytest_asyncio.fixture(autouse=True)
async def reset_environ():
    """Resets os.environ and triggers GC after each test for industrial isolation."""
    import gc
    import os

    orig = dict(os.environ)
    from eval_runner import config

    orig_svc_key = getattr(config, "SERVICE_API_KEY", None)
    orig_dash_key = getattr(config, "DASHBOARD_API_KEY", None)
    orig_jwt_secret = getattr(config, "JWT_SECRET", None)
    yield
    os.environ.clear()
    os.environ.update(orig)
    config.SERVICE_API_KEY = orig_svc_key
    config.DASHBOARD_API_KEY = orig_dash_key
    config.JWT_SECRET = orig_jwt_secret
    # Physically purge stale references and close pending file handles (Windows Hardening)

    from eval_runner.simulators import BaseSimulator

    if hasattr(BaseSimulator, "_instances"):
        # Create a copy to iterate while modifying
        for sim in list(BaseSimulator._instances):
            try:
                if hasattr(sim, "cleanup"):
                    # Properly await the async cleanup in our async fixture
                    await sim.cleanup()
            except (RuntimeError, OSError, AttributeError) as sim_err:
                import logging

                logging.getLogger(__name__).debug(f"Simulator cleanup notice: {sim_err}")
        BaseSimulator._instances.clear()
    gc.collect()


@pytest.fixture(autouse=True)
def reset_cli_parser():
    """Reset CLI parser cache after each test to ensure clean state."""
    yield
    from eval_runner import cli

    cli._invalidate_parser_cache()


@pytest_asyncio.fixture
async def adapter_stub(aiohttp_server):
    """Restore the correct aiohttp_server contract (returning the server object with .host and .port)."""  # noqa: E501
    from aiohttp import web

    async def handle_chat(request):
        return web.json_response({"summary": "This is a joke", "action": "final_answer"})

    app = web.Application()
    app.router.add_post("/api/chat", handle_chat)
    app.router.add_post("/execute_task", handle_chat)

    return await aiohttp_server(app)


pytest_plugins = []


def pytest_configure(config):
    """Register custom markers and configure pytest-asyncio for Python 3.14+."""
    config.addinivalue_line("markers", "asyncio: mark test as an asyncio test")
    config.addinivalue_line(
        "markers", "live: environment-gated integration tests running against CycleCore"
    )
    config.addinivalue_line(
        "markers",
        "adapter_certification: opt-in real provider and framework interoperability tests",
    )
    config.addinivalue_line(
        "markers",
        "release_packaging: build & install the distributable artifact in an isolated environment",
    )

    if os.getenv(_MEMORY_FORENSICS_ENV, "").strip().lower() in {"1", "true", "yes", "on"}:
        try:
            config._agentv_memory_forensics = _MemoryForensicsRecorder.create()
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            logging.getLogger(__name__).warning("Memory forensics recorder disabled: %s", error)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    """Record worker memory after fixture teardown when explicitly enabled."""
    yield
    recorder = getattr(item.config, "_agentv_memory_forensics", None)
    if recorder is None:
        return

    try:
        recorder.record(item.nodeid)
    except (OSError, RuntimeError, ValueError, TypeError) as error:
        logging.getLogger(__name__).warning("Memory forensics sample failed: %s", error)


@pytest.fixture(autouse=True)
def isolate_plugin_registry(tmp_path, monkeypatch):
    """
    Global Safety Net: Automatically isolates the plugin registry for ALL tests.
    Redirects PERSISTENT_PLUGINS_PATH to a temporary file.
    Enables STRICT_PLUGINS mode to catch registration errors during tests.
    """
    import json

    # Create an empty registry in a nested directory to avoid polluting the root tmp_path
    # which some tests (like linter tests) scan for scenarios.
    registry_dir = tmp_path / ".isolated_config"
    registry_file = registry_dir / "registry.isolated"
    registry_dir.mkdir(parents=True, exist_ok=True)
    with open(registry_file, "w", encoding="utf-8") as f:
        json.dump({"plugins": []}, f)

    # Monkeypatch the paths in plugins.py
    from eval_runner import plugins

    monkeypatch.setattr(plugins, "PERSISTENT_PLUGINS_PATH", registry_file)
    monkeypatch.setattr(plugins, "STRICT_PLUGINS", True)

    # Also patch the environment variable for any child processes or lookups
    monkeypatch.setenv("STRICT_PLUGINS", "true")

    return registry_file


@pytest.fixture
def pqc_client():
    """
    Conditional, environment-gated provider for the real CycleCoreClient.
    Protects against sys.modules mock pollution from other unit/integration tests
    by temporarily clearing the mocked cyclecore modules, performing the import,
    and restoring the mocks for subsequent tests.
    """
    import os
    import sys

    if not os.getenv("CYCLECORE_API_KEY"):
        pytest.skip("CYCLECORE_API_KEY not set; skipping live CycleCore test.")

    # Save existing sys.modules to isolate from mock pollution in other test suites
    saved_modules = {}
    for mod_name in ["cyclecore_pq", "cyclecore_pq.client"]:
        if mod_name in sys.modules:
            saved_modules[mod_name] = sys.modules.pop(mod_name)

    try:
        try:
            from cyclecore_pq.client import CycleCoreClient
        except ImportError as e:
            pytest.skip(f"cyclecore-pq package is not installed: {e}")
        client = CycleCoreClient(api_key=os.getenv("CYCLECORE_API_KEY"))

        # Dynamically inject sign_digest and verify_digest to match ZES interface
        import base64

        def sign_digest(digest: bytes, identity_id: str = None) -> str:
            result = client.sign(digest)
            return result.signature

        def verify_digest(signature: str | bytes, digest: bytes, identity_id: str = None) -> bool:
            import binascii

            if isinstance(signature, str):
                try:
                    sig_bytes = base64.b64decode(signature)
                    if len(sig_bytes) < 100:
                        raise ValueError("Signature payload too short for base64")
                except (ValueError, binascii.Error):
                    try:
                        sig_bytes = bytes.fromhex(signature)
                    except ValueError:
                        sig_bytes = signature.encode()
            else:
                sig_bytes = signature

            try:
                result = client.verify(digest, sig_bytes)
                return result.valid
            except (ValueError, TypeError, RuntimeError) as verify_err:
                import logging

                logging.getLogger(__name__).debug(f"Signature verify notice: {verify_err}")
                return False

        client.sign_digest = sign_digest
        client.verify_digest = verify_digest
        return client
    finally:
        # Restore mock objects in sys.modules to prevent breaking other tests
        for mod_name, mod_obj in saved_modules.items():
            sys.modules[mod_name] = mod_obj


def append_authoritative_finalization(
    trace_file: Path,
    run_id: str,
    run_dir: Path | None = None,
    outcome: str = "pass",
    score: float = 1.0,
    evaluator_identity: str = "authoritative_evaluator",
) -> None:
    """Helper for test suites to append an authoritative EvaluatorFinalizationRecord."""

    from agentv_runtime.evidence_graph import (
        build_evidence_graph_from_events,
        compute_evidence_graph_root,
    )
    from agentv_runtime.finalization import EvaluatorFinalizationRecord
    from agentv_runtime.manifest import ExecutionManifest, compute_scenario_hash

    target_dir = run_dir or trace_file.parent
    content = trace_file.read_text(encoding="utf-8") if trace_file.exists() else ""
    if content and not content.endswith("\n"):
        trace_file.write_text(content + "\n", encoding="utf-8")
        content += "\n"
    parsed = []
    events_with_lines = []
    for line in content.splitlines():
        trimmed = line.strip()
        if trimmed:
            try:
                ev = json.loads(trimmed)
                parsed.append(ev)
                events_with_lines.append((ev, trimmed))
            except (json.JSONDecodeError, ValueError):
                pass
    ev_graph = build_evidence_graph_from_events(events_with_lines)
    ev_root = ev_graph.get("evidence_root_hash") or compute_evidence_graph_root(ev_graph)

    scen_file = target_dir / "scenario.json"
    scen_res_file = target_dir / "scenario_resolved.json"
    if scen_res_file.exists():
        scen_data = json.loads(scen_res_file.read_text(encoding="utf-8"))
    elif scen_file.exists():
        scen_data = json.loads(scen_file.read_text(encoding="utf-8"))
        scen_res_file.write_text(json.dumps(scen_data), encoding="utf-8")
    else:
        scen_data = {"id": f"scen_{run_id}", "version": "1.0.0"}
        scen_file.write_text(json.dumps(scen_data), encoding="utf-8")
        scen_res_file.write_text(json.dumps(scen_data), encoding="utf-8")

    scen_h = compute_scenario_hash(scen_data)

    man_file = target_dir / "execution_manifest.json"
    if man_file.exists():
        man_data = json.loads(man_file.read_text(encoding="utf-8"))
        man_h = ExecutionManifest.from_dict(man_data).compute_manifest_hash()
    else:
        eman = ExecutionManifest(
            manifest_id=f"man_{run_id}",
            scenario_id=scen_data.get("id", f"scen_{run_id}"),
            scenario_version=scen_data.get("version", "1.0.0"),
            scenario_hash=scen_h,
        )
        man_file.write_text(json.dumps(eman.to_dict()), encoding="utf-8")
        man_h = eman.compute_manifest_hash()

    fin = EvaluatorFinalizationRecord(
        finalization_id=f"fin_{run_id}",
        run_id=run_id,
        execution_manifest_hash=man_h,
        scenario_id=scen_data.get("id", f"scen_{run_id}"),
        scenario_version=scen_data.get("version", "1.0.0"),
        scenario_hash=scen_h,
        evaluator_identity=evaluator_identity,
        evaluator_config_hash="sha3_256:abc",
        required_oracle_ids=[],
        evidence_root_hash=ev_root,
        outcome=outcome,
        score=score,
        terminal_seq=len(parsed) + 1,
    ).sign()

    fin_line = json.dumps({"event": "evaluator_finalization", "data": fin.to_dict()})
    with open(trace_file, "a", encoding="utf-8") as f:
        f.write(fin_line + "\n")
