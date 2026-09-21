import pytest

from eval_runner.adapters import ag2
from eval_runner.adapters.ag2 import AG2AdapterPlugin


def test_ag2_observer_stream_uses_installed_memory_stream():
    """Use the pinned AG2 stream class rather than a synthetic SDK substitute."""
    pytest.importorskip("ag2")
    from ag2 import stream as ag2_stream

    adapter = AG2AdapterPlugin()
    installed_ag2 = adapter._import_ag2()

    assert isinstance(adapter._build_observer_stream(installed_ag2), ag2_stream.MemoryStream)


def test_ag2_observer_stream_uses_root_compatibility_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve compatibility with AG2 releases exporting MemoryStream at the root."""

    class RootMemoryStream:
        pass

    def unavailable_stream_module(name: str):
        assert name == "ag2.stream"
        raise ImportError("stream module unavailable")

    monkeypatch.setattr(ag2.importlib, "import_module", unavailable_stream_module)
    root_ag2 = type("RootAG2", (), {"MemoryStream": RootMemoryStream})()

    assert isinstance(AG2AdapterPlugin._build_observer_stream(root_ag2), RootMemoryStream)


def test_ag2_observer_stream_logs_constructor_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unusable observer stream is observable without breaking agent execution."""

    class BrokenMemoryStream:
        def __init__(self) -> None:
            raise TypeError("unsupported constructor")

    stream_module = type("StreamModule", (), {"MemoryStream": BrokenMemoryStream})()
    monkeypatch.setattr(ag2.importlib, "import_module", lambda name: stream_module)

    assert AG2AdapterPlugin._build_observer_stream(object()) is None
    assert "AG2 MemoryStream construction failed" in caplog.text
