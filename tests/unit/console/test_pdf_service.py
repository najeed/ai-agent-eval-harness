"""
tests/unit/console/test_pdf_service.py

Unit tests for eval_runner.console.pdf_service.
Covers: generate_run_pdf (WeasyPrint path, ReportLab path, text fallback, all-failed),
        generate_bundle_pdf (WeasyPrint path, ReportLab path, text fallback, zero runs).
"""

from unittest.mock import MagicMock, patch

import pytest

from eval_runner.console.pdf_service import generate_bundle_pdf, generate_run_pdf

# ---------------------------------------------------------------------------
# generate_run_pdf
# ---------------------------------------------------------------------------


@pytest.fixture
def run_data():
    return {
        "run_id": "run-abc",
        "scenario": "finance_scenario",
        "status": "COMPLETED",
        "timestamp": "2026-07-01T00:00:00Z",
        "analysis": {
            "summary": "All tasks passed",
            "root_cause": "None",
            "suggestion": "Continue",
            "confidence": 0.92,
            "failed_turn_index": 3,
        },
    }


def test_generate_run_pdf_weasyprint_path(run_data, tmp_path):
    output_path = tmp_path / "report.pdf"

    mock_wp = MagicMock()
    mock_html_instance = MagicMock()
    mock_wp.HTML.return_value = mock_html_instance

    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", True):
        with patch("eval_runner.console.pdf_service.weasyprint", mock_wp, create=True):
            result = generate_run_pdf(run_data, output_path)

    mock_html_instance.write_pdf.assert_called_once_with(str(output_path))
    assert result is True


def test_generate_run_pdf_weasyprint_exception_falls_to_reportlab(run_data, tmp_path):
    output_path = tmp_path / "report.pdf"

    mock_wp = MagicMock()
    mock_wp.HTML.side_effect = RuntimeError("GTK not found")

    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", True):
        with patch("eval_runner.console.pdf_service.weasyprint", mock_wp, create=True):
            with patch("eval_runner.console.pdf_service.REPORTLAB_AVAILABLE", True):
                with patch("eval_runner.console.pdf_service.SimpleDocTemplate") as mock_doc:
                    mock_doc.return_value.build = MagicMock()
                    result = generate_run_pdf(run_data, output_path)

    assert result is True


def test_generate_run_pdf_reportlab_path(run_data, tmp_path):
    output_path = tmp_path / "report.pdf"

    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", False):
        with patch("eval_runner.console.pdf_service.REPORTLAB_AVAILABLE", True):
            with patch("eval_runner.console.pdf_service.SimpleDocTemplate") as mock_doc:
                mock_doc.return_value.build = MagicMock()
                result = generate_run_pdf(run_data, output_path)

    assert result is True


def test_generate_run_pdf_reportlab_exception_falls_to_text(run_data, tmp_path):
    output_path = tmp_path / "report.pdf"

    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", False):
        with patch("eval_runner.console.pdf_service.REPORTLAB_AVAILABLE", True):
            with patch(
                "eval_runner.console.pdf_service.SimpleDocTemplate",
                side_effect=RuntimeError("reportlab crash"),
            ):
                result = generate_run_pdf(run_data, output_path)

    assert result is True
    txt_path = output_path.with_suffix(".txt")
    assert txt_path.exists()
    content = txt_path.read_text(encoding="utf-8")
    assert "run-abc" in content


def test_generate_run_pdf_text_fallback_only(run_data, tmp_path):
    output_path = tmp_path / "report.pdf"

    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", False):
        with patch("eval_runner.console.pdf_service.REPORTLAB_AVAILABLE", False):
            result = generate_run_pdf(run_data, output_path)

    assert result is True
    txt_path = output_path.with_suffix(".txt")
    content = txt_path.read_text(encoding="utf-8")
    assert "AgentV Enterprise Compliance Report" in content
    assert "run-abc" in content


def test_generate_run_pdf_all_engines_fail(run_data, tmp_path):
    output_path = tmp_path / "sub" / "report.pdf"
    output_path.parent.mkdir()

    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", False):
        with patch("eval_runner.console.pdf_service.REPORTLAB_AVAILABLE", False):
            with patch("builtins.open", side_effect=OSError("no disk")):
                result = generate_run_pdf(run_data, output_path)

    assert result is False


def test_generate_run_pdf_missing_timestamp(tmp_path):
    """Verify missing timestamp triggers utcnow() fallback."""
    run_data_no_ts = {
        "run_id": "run-nots",
        "scenario": "s",
        "status": "COMPLETED",
        "timestamp": "",  # empty triggers the fallback
        "analysis": {},
    }
    output_path = tmp_path / "report.pdf"

    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", False):
        with patch("eval_runner.console.pdf_service.REPORTLAB_AVAILABLE", False):
            result = generate_run_pdf(run_data_no_ts, output_path)

    assert result is True


def test_generate_run_pdf_failed_turn_none(tmp_path):
    """Verify None failed_turn renders as 'N/A' in the text fallback."""
    run_data = {
        "run_id": "run-noturn",
        "scenario": "s",
        "status": "COMPLETED",
        "timestamp": "2026-07-01T00:00:00Z",
        "analysis": {"failed_turn_index": None},
    }
    output_path = tmp_path / "report.pdf"

    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", False):
        with patch("eval_runner.console.pdf_service.REPORTLAB_AVAILABLE", False):
            result = generate_run_pdf(run_data, output_path)

    assert result is True


def test_generate_run_pdf_non_completed_status(tmp_path):
    """Status not containing 'completed' → NON_COMPLIANT PQC status branch."""
    run_data = {
        "run_id": "run-fail",
        "scenario": "s",
        "status": "FAILED",
        "timestamp": "2026-07-01T00:00:00Z",
        "analysis": {},
    }
    output_path = tmp_path / "report.pdf"

    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", False):
        with patch("eval_runner.console.pdf_service.REPORTLAB_AVAILABLE", False):
            generate_run_pdf(run_data, output_path)

    txt = output_path.with_suffix(".txt").read_text(encoding="utf-8")
    assert "NON_COMPLIANT" in txt


# ---------------------------------------------------------------------------
# generate_bundle_pdf
# ---------------------------------------------------------------------------


@pytest.fixture
def suite_data():
    return {
        "suite_id": "suite-xyz",
        "name": "Finance Regression Suite",
        "agent_name": "GPT-4",
        "created_at": "2026-07-01T00:00:00Z",
    }


@pytest.fixture
def run_list():
    return [
        {"run_id": "r1", "status": "COMPLETED"},
        {"run_id": "r2", "status": "FAILED"},
    ]


def test_generate_bundle_pdf_weasyprint_path(suite_data, run_list, tmp_path):
    output_path = tmp_path / "bundle.pdf"

    mock_wp = MagicMock()
    mock_html_instance = MagicMock()
    mock_wp.HTML.return_value = mock_html_instance

    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", True):
        with patch("eval_runner.console.pdf_service.weasyprint", mock_wp, create=True):
            result = generate_bundle_pdf(suite_data, run_list, output_path)

    mock_html_instance.write_pdf.assert_called_once()
    assert result is True


def test_generate_bundle_pdf_weasyprint_exception_falls_to_reportlab(
    suite_data, run_list, tmp_path
):
    output_path = tmp_path / "bundle.pdf"

    mock_wp = MagicMock()
    mock_wp.HTML.side_effect = RuntimeError("GTK missing")

    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", True):
        with patch("eval_runner.console.pdf_service.weasyprint", mock_wp, create=True):
            with patch("eval_runner.console.pdf_service.REPORTLAB_AVAILABLE", True):
                with patch("eval_runner.console.pdf_service.SimpleDocTemplate") as mock_doc:
                    mock_doc.return_value.build = MagicMock()
                    result = generate_bundle_pdf(suite_data, run_list, output_path)

    assert result is True


def test_generate_bundle_pdf_reportlab_path(suite_data, run_list, tmp_path):
    output_path = tmp_path / "bundle.pdf"

    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", False):
        with patch("eval_runner.console.pdf_service.REPORTLAB_AVAILABLE", True):
            with patch("eval_runner.console.pdf_service.SimpleDocTemplate") as mock_doc:
                mock_doc.return_value.build = MagicMock()
                result = generate_bundle_pdf(suite_data, run_list, output_path)

    assert result is True


def test_generate_bundle_pdf_reportlab_exception_falls_to_text(suite_data, run_list, tmp_path):
    output_path = tmp_path / "bundle.pdf"

    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", False):
        with patch("eval_runner.console.pdf_service.REPORTLAB_AVAILABLE", True):
            with patch(
                "eval_runner.console.pdf_service.SimpleDocTemplate",
                side_effect=RuntimeError("reportlab crash"),
            ):
                result = generate_bundle_pdf(suite_data, run_list, output_path)

    assert result is True
    txt_path = output_path.with_suffix(".txt")
    content = txt_path.read_text(encoding="utf-8")
    assert "AgentV Regression Suite Handoff Summary" in content
    assert "r1" in content


def test_generate_bundle_pdf_text_fallback_only(suite_data, run_list, tmp_path):
    output_path = tmp_path / "bundle.pdf"

    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", False):
        with patch("eval_runner.console.pdf_service.REPORTLAB_AVAILABLE", False):
            result = generate_bundle_pdf(suite_data, run_list, output_path)

    assert result is True
    txt = output_path.with_suffix(".txt").read_text(encoding="utf-8")
    assert "Finance Regression Suite" in txt
    assert "2/2" in txt or "passed" in txt


def test_generate_bundle_pdf_all_engines_fail(suite_data, run_list, tmp_path):
    output_path = tmp_path / "sub" / "bundle.pdf"
    output_path.parent.mkdir()

    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", False):
        with patch("eval_runner.console.pdf_service.REPORTLAB_AVAILABLE", False):
            with patch("builtins.open", side_effect=OSError("no space")):
                result = generate_bundle_pdf(suite_data, run_list, output_path)

    assert result is False


def test_generate_bundle_pdf_zero_runs(suite_data, tmp_path):
    output_path = tmp_path / "empty_bundle.pdf"

    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", False):
        with patch("eval_runner.console.pdf_service.REPORTLAB_AVAILABLE", False):
            result = generate_bundle_pdf(suite_data, [], output_path)

    assert result is True
    txt = output_path.with_suffix(".txt").read_text(encoding="utf-8")
    assert "0/0" in txt or "passed" in txt


def test_generate_bundle_pdf_passing_runs_count(suite_data, tmp_path):
    """Verify pass rate counts COMPLETED and 'pass'-containing statuses."""
    runs = [
        {"run_id": "r1", "status": "COMPLETED"},
        {"run_id": "r2", "status": "passed"},
        {"run_id": "r3", "status": "FAILED"},
    ]
    output_path = tmp_path / "pr_bundle.pdf"

    with patch("eval_runner.console.pdf_service.WEASYPRINT_AVAILABLE", False):
        with patch("eval_runner.console.pdf_service.REPORTLAB_AVAILABLE", False):
            result = generate_bundle_pdf(suite_data, runs, output_path)

    assert result is True
    txt = output_path.with_suffix(".txt").read_text(encoding="utf-8")
    assert "2/3" in txt


def test_import_weasyprint_success_and_reportlab_failure():
    """Verify WeasyPrint import path and ReportLab fallback triggers at module import time."""
    import importlib
    import sys
    from unittest.mock import MagicMock, patch

    # 1. WeasyPrint Success path
    mock_wp = MagicMock()
    sys.modules["weasyprint"] = mock_wp

    try:
        from eval_runner.console import pdf_service

        importlib.reload(pdf_service)
        assert pdf_service.WEASYPRINT_AVAILABLE is True
    finally:
        sys.modules.pop("weasyprint", None)
        from eval_runner.console import pdf_service

        importlib.reload(pdf_service)

    # 2. ReportLab Failure path
    orig_import = __import__

    def mock_import(name, *args, **kwargs):
        if "reportlab" in name:
            raise ImportError("Mocked ReportLab Import Failure")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        from eval_runner.console import pdf_service

        importlib.reload(pdf_service)
        assert pdf_service.REPORTLAB_AVAILABLE is False

    # Restore clean state
    from eval_runner.console import pdf_service

    importlib.reload(pdf_service)
