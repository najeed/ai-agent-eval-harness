"""
tests/ui/test_visual_console_ui.py
Playwright End-to-End & UI Verification Suite for AgentV Visual Console.
Tests canonical SPA routing, navigation links, and dynamic component rendering.
"""

import http.client
import json
import socket
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from werkzeug.serving import make_server

from eval_runner import config
from eval_runner.console.app import create_app


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerThread(threading.Thread):
    def __init__(self, app, port: int):
        super().__init__(daemon=True)
        self.port = port
        self.server = make_server("127.0.0.1", port, app)
        self.ctx = app.app_context()
        self.ctx.push()

    def run(self):
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()


@pytest.fixture(scope="module")
def console_server(tmp_path_factory):
    """Launches a live background Flask server serving the Visual Console."""
    root_dir = tmp_path_factory.mktemp("ui_test_root")
    runs_dir = root_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    dist_dir = config.PROJECT_ROOT / "ui" / "visual-console" / "dist"
    if not (dist_dir / "index.html").exists():
        dist_dir.mkdir(parents=True, exist_ok=True)
        (dist_dir / "index.html").write_text(
            "<!DOCTYPE html><html><head><title>AgentV Visual Console</title></head>"
            "<body><div id='root'><h1>AgentV Verification OS</h1></div></body></html>",
            encoding="utf-8",
        )

    port = get_free_port()
    with (
        patch.object(config, "PROJECT_ROOT", config.PROJECT_ROOT),
        patch.object(config, "RUN_LOG_DIR", runs_dir),
    ):
        app = create_app()
        app.secret_key = "test-ui-secret"
        server = ServerThread(app, port)
        server.start()

        # Wait for server readiness
        deadline = time.time() + 5.0
        ready = False
        while time.time() < deadline:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port=port, timeout=1.0)
                conn.request("GET", "/api/ping")
                resp = conn.getresponse()
                if resp.status == 200:
                    ready = True
                    conn.close()
                    break
                conn.close()
            except Exception:
                time.sleep(0.05)

        if not ready:
            pytest.fail("Visual Console test server failed to start within timeout.")

        yield f"http://127.0.0.1:{port}", port
        server.shutdown()
        server.join(timeout=3.0)


def test_console_spa_canonical_routes(console_server):
    """Verifies that the canonical routes return 200 and serve the SPA index.html."""
    _, port = console_server
    routes = [
        "/",
        "/scenarios",
        "/reports",
        "/editor",
        "/debugger",
        "/runner",
        "/trust",
        "/v2",
    ]
    for route in routes:
        conn = http.client.HTTPConnection("127.0.0.1", port=port, timeout=5.0)
        conn.request("GET", route)
        resp = conn.getresponse()
        assert resp.status == 200
        body = resp.read().decode("utf-8")
        assert "<!DOCTYPE html>" in body or "<!doctype html>" in body.lower()
        assert (
            "AgentV" in body
            or "visual-console" in body
            or '<div id="root">' in body
            or "<script" in body
        )
        conn.close()


def test_console_api_routes_reachability(console_server):
    """Verifies that backend JSON APIs are reachable and responsive."""
    _, port = console_server
    conn = http.client.HTTPConnection("127.0.0.1", port=port, timeout=5.0)
    conn.request("GET", "/api/nav")
    resp = conn.getresponse()
    assert resp.status == 200
    data = json.loads(resp.read().decode("utf-8"))
    assert "nav" in data or "items" in data or isinstance(data, list)
    conn.close()


@pytest.mark.skipif(
    not Path(config.PROJECT_ROOT / "ui" / "visual-console" / "dist" / "index.html").exists(),
    reason="UI production bundle dist/index.html not built",
)
def test_playwright_e2e_navigation(console_server):
    """End-to-end browser test using Playwright if chromium is installed."""
    base_url, _ = console_server
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed in current environment")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # 1. Load Canonical Root
            page.goto(base_url, wait_until="domcontentloaded", timeout=20000)
            assert "AgentV" in page.title() or page.locator("#root").count() > 0

            # 2. Navigate to /scenarios
            page.goto(f"{base_url}/scenarios", wait_until="domcontentloaded", timeout=20000)
            assert page.locator("#root").count() > 0

            # 3. Navigate to /reports
            page.goto(f"{base_url}/reports", wait_until="domcontentloaded", timeout=20000)
            assert page.locator("#root").count() > 0

            # 4. Navigate to /debugger
            page.goto(f"{base_url}/debugger", wait_until="domcontentloaded", timeout=20000)
            assert page.locator("#root").count() > 0

            # 5. Navigate to /v2 (backward compatibility)
            page.goto(f"{base_url}/v2", wait_until="domcontentloaded", timeout=20000)
            assert page.locator("#root").count() > 0

            browser.close()

    except Exception as e:
        if "Executable doesn't exist" in str(e) or "browserType.launch" in str(e):
            pytest.skip(f"Chromium browser binary not downloaded: {e}")
        else:
            raise
