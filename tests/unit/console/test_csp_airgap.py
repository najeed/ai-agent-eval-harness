"""
Unit tests for configurable Console CSP and offline local Mermaid bundling (SOC 2 CC6.6 / DF-05).
"""

from __future__ import annotations

import os
from unittest.mock import patch

from eval_runner import config
from eval_runner.config import get_mermaid_asset_url


class TestConsoleCSPAirgap:
    """Verifies Console Content-Security-Policy behavior in online vs air-gapped modes."""

    def test_default_online_csp_includes_jsdelivr(self) -> None:
        from eval_runner.console.app import create_app

        with patch.object(config, "is_airgapped", return_value=False):
            with patch.dict(
                os.environ, {"CONSOLE_CSP_SCRIPT_SRC": "", "CONSOLE_CSP_CONNECT_SRC": ""}
            ):
                app = create_app()

                @app.route("/test-html")
                def test_html():
                    return "<html><body>OK</body></html>", 200, {"Content-Type": "text/html"}

                with app.test_client() as client:
                    resp = client.get("/test-html")
                    csp = resp.headers.get("Content-Security-Policy", "")
                    assert "https://cdn.jsdelivr.net" in csp
                    assert "script-src 'self' https://cdn.jsdelivr.net blob:" in csp
                    assert "connect-src 'self' https://cdn.jsdelivr.net" in csp

    def test_airgapped_csp_strips_jsdelivr(self) -> None:
        from eval_runner.console.app import create_app

        with patch.object(config, "is_airgapped", return_value=True):
            with patch.dict(
                os.environ,
                {
                    "AIRGAPPED_MODE": "true",
                    "CONSOLE_CSP_SCRIPT_SRC": "",
                    "CONSOLE_CSP_CONNECT_SRC": "",
                },
            ):
                app = create_app()

                @app.route("/test-airgap-html")
                def test_airgap_html():
                    return "<html><body>Airgap</body></html>", 200, {"Content-Type": "text/html"}

                with app.test_client() as client:
                    resp = client.get("/test-airgap-html")
                    csp = resp.headers.get("Content-Security-Policy", "")
                    assert "https://cdn.jsdelivr.net" not in csp
                    assert "script-src 'self' blob:" in csp
                    assert "connect-src 'self'" in csp

    def test_custom_csp_directives_injected(self) -> None:
        from eval_runner.console.app import create_app

        with patch.object(config, "is_airgapped", return_value=True):
            with patch.dict(
                os.environ,
                {
                    "CONSOLE_CSP_SCRIPT_SRC": "https://offline-assets.corp.internal",
                    "CONSOLE_CSP_CONNECT_SRC": "https://eval-telemetry.corp.internal",
                },
            ):
                app = create_app()

                @app.route("/test-custom-csp")
                def test_custom():
                    return "<html><body>Custom</body></html>", 200, {"Content-Type": "text/html"}

                with app.test_client() as client:
                    resp = client.get("/test-custom-csp")
                    csp = resp.headers.get("Content-Security-Policy", "")
                    assert "https://offline-assets.corp.internal" in csp
                    assert "https://eval-telemetry.corp.internal" in csp
                    assert "https://cdn.jsdelivr.net" not in csp


class TestMermaidAssetResolution:
    """Verifies Mermaid asset URL resolution for online and offline environments."""

    def test_online_resolves_to_jsdelivr(self) -> None:
        with patch.object(config, "is_airgapped", return_value=False):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("MERMAID_CDN", None)
                url = get_mermaid_asset_url()
                assert url == "https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"

    def test_airgapped_resolves_to_local_vendor(self) -> None:
        with patch.object(config, "is_airgapped", return_value=True):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("MERMAID_CDN", None)
                url = get_mermaid_asset_url()
                assert url == "/static/vendor/mermaid.min.js"

    def test_explicit_override_takes_precedence(self) -> None:
        with patch.dict(os.environ, {"MERMAID_CDN": "https://my-internal-bundle.net/mermaid.js"}):
            url = get_mermaid_asset_url()
            assert url == "https://my-internal-bundle.net/mermaid.js"
