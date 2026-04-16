import json
import sys
from pathlib import Path

from eval_runner.calibrator import run_calibration


def test_calibrator_file_not_found(capsys):
    """Test calibrator handling missing trace file."""
    run_calibration("missing_file.json")
    assert "Trace file not found" in capsys.readouterr().out


def test_calibrator_single_file(tmp_path, capsys):
    """Test typical single file calibration flow."""
    trace_file = tmp_path / "trace.json"

    events = [
        {"event": "evaluation", "task_id": "t1", "value": 0.8, "metadata": {"human": False}},
        {"event": "evaluation", "task_id": "t1", "value": 1.0, "metadata": {"human": True}},
        # Malformed lines
        "not json",
        # run_start metadata
        {"event": "run_start", "task_id": "t2", "metadata": {"human_label": 0.5}},
        {"event": "evaluation", "task_id": "t2", "value": 0.4, "metadata": {"human": False}},
    ]
    with trace_file.open("w") as f:
        for ev in events:
            if isinstance(ev, str):
                f.write(ev + "\n")
            else:
                f.write(json.dumps(ev) + "\n")

    run_calibration(str(trace_file))
    stdout = capsys.readouterr().out
    assert "JUDGE CALIBRATION REPORT" in stdout
    assert "Total Samples:         2" in stdout


def test_calibrator_directory_and_golden(tmp_path, capsys):
    """Test directory aggregated loading and golden manifest."""
    d = tmp_path / "runs"
    d.mkdir()
    f1 = d / "a.jsonl"
    f2 = d / "b.jsonl"

    f1.write_text(
        json.dumps({"event": "evaluation", "task_id": "t3", "value": 0.9}) + "\nnot json\n"
    )
    f2.write_text(json.dumps({"event": "evaluation", "task_id": "t4", "value": 0.1}) + "\n")

    golden = tmp_path / "golden.json"
    golden.write_text(json.dumps({"t3": 1.0, "t4": 0.0}))

    run_calibration(str(d), golden_path=str(golden))
    stdout = capsys.readouterr().out

    assert "Loaded 2 golden labels" in stdout
    assert "Total Samples:         2" in stdout


def test_calibrator_no_aligned_pairs(tmp_path, capsys):
    """Test abortion when no aligned pairs are found."""
    f = tmp_path / "unaligned.json"
    f.write_text(json.dumps({"event": "evaluation", "task_id": "t1", "value": 0.9}) + "\n")

    run_calibration(str(f))
    stdout = capsys.readouterr().out
    assert "No aligned Judge-Human pairs found" in stdout


def test_calibrator_correlation_div_zero(tmp_path, capsys):
    """Test correlation calculation edge case (den=0)."""
    # 2 points that are exactly the same will make variance zero and denominator 0
    trace_file = tmp_path / "trace_zero.json"
    events = [
        {"event": "evaluation", "task_id": "t1", "value": 0.5, "metadata": {"human": False}},
        {"event": "evaluation", "task_id": "t1", "value": 0.5, "metadata": {"human": True}},
        {"event": "evaluation", "task_id": "t2", "value": 0.5, "metadata": {"human": False}},
        {"event": "evaluation", "task_id": "t2", "value": 0.5, "metadata": {"human": True}},
    ]
    trace_file.write_text("\n".join(json.dumps(e) for e in events))

    run_calibration(str(trace_file))
    stdout = capsys.readouterr().out
    assert "Calibration Analysis (Rho=0.000)" in stdout or "Correlation (Rho):     0.0000" in stdout


def test_calibrator_plot_success(tmp_path, monkeypatch, capsys):
    """Test the plotting logic."""
    trace_file = tmp_path / "trace_plot.json"
    events = [
        {"event": "evaluation", "task_id": "t1", "value": 0.5, "metadata": {"human": False}},
        {"event": "evaluation", "task_id": "t1", "value": 0.5, "metadata": {"human": True}},
    ]
    trace_file.write_text("\n".join(json.dumps(e) for e in events))

    import builtins
    from unittest.mock import MagicMock

    mock_plt = MagicMock()

    # Needs to bypass the ImportError inside calibrator.py
    # and satisfy the attribute accesses.
    mock_plt.figure = MagicMock()
    mock_plt.scatter = MagicMock()
    mock_plt.plot = MagicMock()
    mock_plt.axhline = MagicMock()
    mock_plt.xlabel = MagicMock()
    mock_plt.ylabel = MagicMock()
    mock_plt.title = MagicMock()
    mock_plt.legend = MagicMock()
    mock_plt.grid = MagicMock()

    def savefig(path):
        Path(path).write_text("fake image")

    mock_plt.savefig = savefig
    mock_plt.close = MagicMock()

    old_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "matplotlib.pyplot":
            return mock_plt
        elif name == "numpy":
            return MagicMock()
        return old_import(name, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(builtins, "__import__", mock_import)
        run_calibration(str(trace_file), plot=True)
        assert "plot saved" in capsys.readouterr().out


def test_calibrator_plot_import_error(tmp_path, monkeypatch, capsys):
    """Test the plotting import error handling."""
    trace_file = tmp_path / "trace_import.json"
    events = [
        {"event": "evaluation", "task_id": "t1", "value": 0.5, "metadata": {"human": False}},
        {"event": "evaluation", "task_id": "t1", "value": 0.5, "metadata": {"human": True}},
    ]
    trace_file.write_text("\n".join(json.dumps(e) for e in events))

    # Hide matplotlib
    import builtins

    old_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "matplotlib.pyplot":
            raise ImportError("Mocked missing")
        return old_import(name, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(builtins, "__import__", mock_import)
        run_calibration(str(trace_file), plot=True)

    assert "plotting skipped" in capsys.readouterr().out.lower()


def test_calibrator_plot_exception(tmp_path, capsys, monkeypatch):
    """Test generic plot exception."""
    trace_file = tmp_path / "trace_exc.json"
    events = [
        {"event": "evaluation", "task_id": "t1", "value": 0.5, "metadata": {"human": False}},
        {"event": "evaluation", "task_id": "t1", "value": 0.5, "metadata": {"human": True}},
    ]
    trace_file.write_text("\n".join(json.dumps(e) for e in events))

    from unittest.mock import MagicMock, patch

    mock_plt = MagicMock()

    def raise_err(*args, **kwargs):
        raise ValueError("Simulated Save Error")

    mock_plt.savefig.side_effect = raise_err

    # Use patch.dict on sys.modules for clean, reliable industrial mocking

    # Use patch.dict on sys.modules with importlib.reload for absolute industrial isolation
    from importlib import reload

    import eval_runner.calibrator as cal

    mock_matplotlib = MagicMock()
    mock_plt = mock_matplotlib.pyplot
    mock_plt.savefig.side_effect = Exception("Simulated Save Error")

    with patch.dict(
        sys.modules,
        {"matplotlib": mock_matplotlib, "matplotlib.pyplot": mock_plt, "numpy": MagicMock()},
    ):
        reload(cal)
        cal.run_calibration(str(trace_file), plot=True)

    stdout = capsys.readouterr().out
    assert "Failed to generate plot" in stdout or "Simulated Save Error" in stdout


def test_calibrator_main_block(monkeypatch):
    """Test __main__ block executing run_calibration."""
    import runpy

    monkeypatch.setattr("eval_runner.calibrator.run_calibration", lambda *a, **kw: None)

    from unittest.mock import patch

    with patch("sys.argv", ["calibrator.py", "dummy.json", "--plot"]):
        # Test __main__
        # Because we can't easily mock __name__ easily without runpy:
        # Instead, just execute the module
        runpy.run_module("eval_runner.calibrator", run_name="__main__")
