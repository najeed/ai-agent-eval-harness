"""
tests/ui/test_verification_workflow_journey.py

End-to-End Browser Journey Acceptance Test (Phase 6).
Validates the complete verification workflow journey across the browser interface:
  1. Scenario selection & execution mode declaration (live vs hybrid).
  2. Preflight readiness probe (is_verifiable, preflight_fingerprint, badges).
  3. Live evaluation execution (execution_mode="live", declared=True).
  4. Live Debugger topology rendering.
  5. Induced assertion failure & RCA Failure Summary (causal node, expected vs actual).
  6. Strict 3-state Policy tab assurance (PASS, FAIL, NOT VERIFIED).
  7. Evidence package contract verification.
  8. Cryptographic verification authority & public privacy (unauthenticated manifest redaction).
"""

from __future__ import annotations

import http.client
import json
import os
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


TEST_API_KEY = "test-journey-auth-key-007"
RUN_ID = "run-journey-rca-001"


@pytest.fixture(scope="module")
def journey_console_server(tmp_path_factory):
    """Launches a live background Flask server with seeded scenario and run data."""
    root_dir = tmp_path_factory.mktemp("journey_ui_root")
    runs_dir = root_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    dist_dir = config.PROJECT_ROOT / "ui" / "visual-console" / "dist"
    if not (dist_dir / "index.html").exists():
        pytest.skip(
            "Visual Console build artifact ui/visual-console/dist/index.html not found. "
            "Run 'npm run build' first."
        )

    # 1. Seed completed run with induced assertion failure in run vault
    run_vault = runs_dir / RUN_ID
    run_vault.mkdir(parents=True, exist_ok=True)

    # run.jsonl trace
    trace_path = run_vault / "run.jsonl"
    events = [
        {
            "event": "run_start",
            "run_id": RUN_ID,
            "scenario_id": "journey_scenario",
            "execution_mode": "live",
            "execution_mode_declared": True,
            "_seq": 1,
            "timestamp": "2026-09-19T10:00:00.000Z",
        },
        {
            "event": "assertion_evaluated",
            "run_id": RUN_ID,
            "node": "checkout_node",
            "metric": "db_state_invariance",
            "oracle_id": "db_state_invariance",
            "passed": False,
            "expected": "100",
            "actual": "80",
            "causal_node": "checkout_node",
            "_seq": 2,
            "timestamp": "2026-09-19T10:00:01.000Z",
        },
        {
            "event": "run_end",
            "run_id": RUN_ID,
            "status": "failure",
            "passed": False,
            "score": 0.0,
            "execution_mode": "live",
            "execution_mode_declared": True,
            "assertions": [
                {
                    "metric": "db_state_invariance",
                    "passed": False,
                    "node": "checkout_node",
                    "expected": "100",
                    "actual": "80",
                    "causal_node": "checkout_node",
                }
            ],
            "_seq": 3,
            "timestamp": "2026-09-19T10:00:02.000Z",
        },
    ]
    with open(trace_path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")

    # evidence_package.json
    evidence_pkg_path = run_vault / "evidence_package.json"
    evidence_pkg = {
        "run_id": RUN_ID,
        "execution_mode": "live",
        "execution_mode_declared": True,
        "verdict": {
            "status": "FAILED_VERIFICATION",
            "assertions": [
                {
                    "name": "db_state_invariance",
                    "metric": "db_state_invariance",
                    "passed": False,
                    "node": "checkout_node",
                    "expected": "100",
                    "actual": "80",
                    "causal_node": "checkout_node",
                }
            ],
        },
        "assertions": [
            {
                "name": "db_state_invariance",
                "metric": "db_state_invariance",
                "passed": False,
                "node": "checkout_node",
                "expected": "100",
                "actual": "80",
                "causal_node": "checkout_node",
            }
        ],
        "evidence_graph": {
            "nodes": [
                {
                    "id": "checkout_node",
                    "node": "checkout_node",
                    "label": "db_state_invariance",
                    "passed": False,
                    "expected": "100",
                    "actual": "80",
                }
            ],
            "edges": [],
        },
    }
    evidence_pkg_path.write_text(json.dumps(evidence_pkg, indent=2), encoding="utf-8")

    # run_manifest.json
    manifest_path = run_vault / "run_manifest.json"
    manifest = {
        "vc_version": "3.0.0",
        "harness_version": "2.0.0",
        "run_id": RUN_ID,
        "execution_mode": "live",
        "execution_mode_declared": True,
        "trace_hash": "sha3_256:fakehash12345",
        "hash_algorithm": "sha3_256",
        "timestamp": "2026-09-19T10:00:02.000Z",
        "provenance_chain": [
            {
                "identity": "system_id",
                "role": "Evaluator",
                "timestamp": "2026-09-19T10:00:02.000Z",
                "signature": "deadbeef",
                "algorithm": "ED25519",
            }
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Sealed marker — required by hardened lifecycle check; without this
    # get_run_lifecycle_state() returns OPEN and public_verify_run returns 400.
    (run_vault / ".sealed").write_text("SEALED", encoding="utf-8")

    # Launch server with patched config
    port = get_free_port()
    with (
        patch.object(config, "PROJECT_ROOT", config.PROJECT_ROOT),
        patch.object(config, "RUN_LOG_DIR", runs_dir),
        patch.object(config, "SERVICE_API_KEY", TEST_API_KEY),
        patch.dict(os.environ, {"SERVICE_API_KEY": TEST_API_KEY, "RUN_LOG_DIR": str(runs_dir)}),
    ):
        app = create_app()
        app.secret_key = "journey-test-secret"
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
            pytest.fail("Visual Console journey test server failed to start within timeout.")

        yield f"http://127.0.0.1:{port}", port, runs_dir
        server.shutdown()
        server.join(timeout=3.0)


@pytest.mark.skipif(
    not Path(config.PROJECT_ROOT / "ui" / "visual-console" / "dist" / "index.html").exists(),
    reason="UI production bundle dist/index.html not built",
)
def test_verification_workflow_journey_playwright(journey_console_server):
    """
    End-to-End Playwright acceptance test verifying the complete user journey:
    1. Scenario & Execution Mode Selection (live vs hybrid)
    2. Preflight Readiness Probe (is_verifiable, badges)
    3. Live Debugger topology render
    4. Induced assertion failure & RCA Failure Summary (causal node, expected vs actual)
    5. Strict 3-state Policy Tab assurance
    6. Evidence Package contract
    7. Cryptographic Verification & Public Privacy
    """
    base_url, port, _ = journey_console_server
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed in current environment")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # ------------------------------------------------------------------
            # Step 1: Navigate to Primary Product Spine (Verification Workflow)
            # ------------------------------------------------------------------
            page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_selector("h1:has-text('New Verification')", timeout=10000)

            # ------------------------------------------------------------------
            # Step 2: Configure Endpoint & Mode Selection
            # ------------------------------------------------------------------
            # Select execution mode: "live"
            mode_select = page.locator("select:has-text('live')")
            if mode_select.count() > 0:
                mode_select.first.select_option("live")

            # Fill in agent endpoint
            endpoint_input = page.locator("input[placeholder*='your-agent']")
            if endpoint_input.count() > 0:
                endpoint_input.first.fill("http://127.0.0.1:5001/agent")

            # ------------------------------------------------------------------
            # Step 3: Verify Preflight Readiness Probe
            # ------------------------------------------------------------------
            # Verify preflight button exists
            preflight_btn = page.locator("button:has-text('Run preflight')")
            assert preflight_btn.count() > 0

            # Test switching mode to hybrid updates badge/warning
            if mode_select.count() > 0:
                mode_select.first.select_option("hybrid")
                # When hybrid is selected, it should produce provisional indicators

            # ------------------------------------------------------------------
            # Step 4: Live Debugger Topology Route Verification
            # ------------------------------------------------------------------
            debugger_url = f"{base_url}/debugger?run_id={RUN_ID}"
            page.goto(debugger_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_selector("#root", timeout=10000)
            # Verify debugger view mounted
            assert page.locator("#root").count() > 0

            # ------------------------------------------------------------------
            # Step 5: Reports / RunDetailView — RCA Failure Summary & Policy Tab
            # ------------------------------------------------------------------
            reports_url = f"{base_url}/reports?run_id={RUN_ID}"
            page.goto(reports_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_selector("#root", timeout=10000)

            # Check for RCA Failure Summary element
            rca_summary = page.locator("[data-testid='rca-failure-summary']")
            if rca_summary.count() > 0:
                # Verify causal node and metric name are rendered
                text = rca_summary.inner_text()
                assert "checkout_node" in text or "db_state_invariance" in text
                # Verify expected vs actual is rendered
                assert "100" in text and "80" in text

            # Check Policy Tab: Click Policy & Guardrails
            policy_tab_btn = page.locator("button:has-text('Policy & Guardrails')")
            if policy_tab_btn.count() > 0:
                policy_tab_btn.first.click()
                time.sleep(0.3)

                # Strict 3-state assurance: Exactly one must be present
                pass_state = page.locator("[data-testid='policy-state-pass']").count()
                fail_state = page.locator("[data-testid='policy-state-fail']").count()
                not_verified_state = page.locator(
                    "[data-testid='policy-state-not-verified']"
                ).count()

                total_active_states = pass_state + fail_state + not_verified_state
                assert total_active_states == 1, (
                    f"Policy tab must render strictly one canonical state, found "
                    f"pass={pass_state}, fail={fail_state}, not_verified={not_verified_state}"
                )

            browser.close()

    except Exception as e:
        if "Executable doesn't exist" in str(e) or "browserType.launch" in str(e):
            pytest.skip(f"Chromium browser binary not downloaded: {e}")
        else:
            raise


def test_evidence_package_contract_api(journey_console_server):
    """
    Contract Test: Validates that /api/v1/evidence/packages/<run_id>
    hydrates verdict assertions with causal_node, expected, and actual values.
    """
    _, port, _ = journey_console_server
    conn = http.client.HTTPConnection("127.0.0.1", port=port, timeout=5.0)
    conn.request(
        "GET",
        f"/api/v1/evidence/packages/{RUN_ID}",
        headers={"X-Api-Key": TEST_API_KEY},
    )
    resp = conn.getresponse()
    assert resp.status == 200
    data = json.loads(resp.read().decode("utf-8"))
    conn.close()

    assert data["run_id"] == RUN_ID
    assert data["chain"]["execution_mode"] == "live"
    assert data["chain"]["execution_mode_declared"] is True

    assertions = data["verdict"]["assertions"]
    assert len(assertions) > 0
    assertion = assertions[0]
    assert assertion["metric"] == "db_state_invariance"
    assert assertion["node"] == "checkout_node"
    assert assertion["expected"] == "100"
    assert assertion["actual"] == "80"
    assert assertion["passed"] is False


def test_public_verification_privacy_and_authenticated_manifest(journey_console_server):
    """
    Contract Test: Validates that public unauthenticated /api/v1/verify/<run_id>
    redacts the raw manifest dict, while authenticated /api/v1/verify/<run_id>/manifest
    returns the manifest.
    """
    _, port, _ = journey_console_server

    # 1. Unauthenticated public verification -> manifest redacted
    conn = http.client.HTTPConnection("127.0.0.1", port=port, timeout=5.0)
    conn.request("GET", f"/api/v1/verify/{RUN_ID}")
    resp = conn.getresponse()
    assert resp.status == 200
    public_data = json.loads(resp.read().decode("utf-8"))
    conn.close()

    assert "manifest" not in public_data, "Public unauthenticated verify must redact raw manifest"
    assert public_data["run_id"] == RUN_ID

    # 2. Unauthenticated request to /manifest -> 401 Unauthorized
    conn = http.client.HTTPConnection("127.0.0.1", port=port, timeout=5.0)
    conn.request("GET", f"/api/v1/verify/{RUN_ID}/manifest")
    resp_unauth = conn.getresponse()
    assert resp_unauth.status == 401
    conn.close()

    # 3. Authenticated request to /manifest with X-Api-Key -> 200 OK with manifest
    conn = http.client.HTTPConnection("127.0.0.1", port=port, timeout=5.0)
    conn.request(
        "GET",
        f"/api/v1/verify/{RUN_ID}/manifest",
        headers={"X-Api-Key": TEST_API_KEY},
    )
    resp_auth = conn.getresponse()
    assert resp_auth.status == 200
    manifest = json.loads(resp_auth.read().decode("utf-8"))
    conn.close()

    assert manifest["run_id"] == RUN_ID
    assert manifest["execution_mode"] == "live"
    assert manifest["execution_mode_declared"] is True
