"""Contract and behavioral tests for agentv_runtime.discovery."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from agentv_runtime.discovery import (
    ENTRY_POINT_NAMESPACE,
    reset_extensions,
    resolve_extension,
    set_extension,
)


@pytest.fixture(autouse=True)
def clean_registry():
    reset_extensions()
    yield
    reset_extensions()


class MockExtension:
    def __init__(self, name: str = "mock"):
        self.name = name


def test_resolve_extension_explicit_returns_immediately():
    explicit = MockExtension("explicit")
    resolved = resolve_extension("run_stores", explicit=explicit, default_factory=MockExtension)
    assert resolved is explicit


def test_resolve_extension_cached_registry():
    pre_set = MockExtension("preset")
    set_extension("run_stores", pre_set)
    resolved = resolve_extension("run_stores", default_factory=MockExtension)
    assert resolved is pre_set


def test_resolve_extension_env_var_selected(monkeypatch):
    monkeypatch.setenv("AGENTV_RUN_STORES", "custom")
    custom_inst = MockExtension("custom")
    ep = SimpleNamespace(name="custom", load=lambda: lambda: custom_inst)

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group=None: [ep] if group == f"{ENTRY_POINT_NAMESPACE}.run_stores" else [],
    )

    resolved = resolve_extension("run_stores", default_factory=MockExtension)
    assert resolved is custom_inst


def test_resolve_extension_env_var_load_failure(monkeypatch, caplog):
    monkeypatch.setenv("AGENTV_RUN_STORES", "failing")

    def broken_loader():
        raise RuntimeError("Load failed")

    ep = SimpleNamespace(name="failing", load=broken_loader)

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group=None: [ep] if group == f"{ENTRY_POINT_NAMESPACE}.run_stores" else [],
    )

    with caplog.at_level(logging.WARNING):
        resolved = resolve_extension(
            "run_stores", default_factory=lambda: MockExtension("fallback")
        )
    assert resolved.name == "fallback"
    assert "Failed to load configured run_stores provider 'failing'" in caplog.text


def test_resolve_extension_default_entry_point(monkeypatch):
    default_inst = MockExtension("default")
    other_inst = MockExtension("other")
    ep_default = SimpleNamespace(name="default", load=lambda: lambda: default_inst)
    ep_other = SimpleNamespace(name="other", load=lambda: lambda: other_inst)

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group=None: (
            [ep_default, ep_other] if group == f"{ENTRY_POINT_NAMESPACE}.artifact_stores" else []
        ),
    )

    resolved = resolve_extension("artifact_stores", default_factory=MockExtension)
    assert resolved is default_inst


def test_resolve_extension_default_entry_point_load_failure(monkeypatch, caplog):
    def broken_loader():
        raise RuntimeError("Default load failed")

    ep_default = SimpleNamespace(name="default", load=broken_loader)
    other_inst = MockExtension("other")
    ep_other = SimpleNamespace(name="other", load=lambda: lambda: other_inst)

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group=None: (
            [ep_default, ep_other] if group == f"{ENTRY_POINT_NAMESPACE}.artifact_stores" else []
        ),
    )

    with caplog.at_level(logging.WARNING):
        resolved = resolve_extension(
            "artifact_stores", default_factory=lambda: MockExtension("fallback")
        )
    assert resolved.name == "fallback"
    assert "Failed to load default registered artifact_stores provider" in caplog.text


def test_resolve_extension_single_entry_point_auto_bind(monkeypatch):
    unique_inst = MockExtension("unique")
    ep_unique = SimpleNamespace(name="isolated", load=lambda: lambda: unique_inst)

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group=None: (
            [ep_unique] if group == f"{ENTRY_POINT_NAMESPACE}.checkpoint_stores" else []
        ),
    )

    resolved = resolve_extension("checkpoint_stores", default_factory=MockExtension)
    assert resolved is unique_inst


def test_resolve_extension_single_entry_point_auto_bind_failure(monkeypatch, caplog):
    def broken_loader():
        raise RuntimeError("Single load failed")

    ep_unique = SimpleNamespace(name="isolated", load=broken_loader)

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group=None: (
            [ep_unique] if group == f"{ENTRY_POINT_NAMESPACE}.checkpoint_stores" else []
        ),
    )

    with caplog.at_level(logging.WARNING):
        resolved = resolve_extension(
            "checkpoint_stores", default_factory=lambda: MockExtension("fallback")
        )
    assert resolved.name == "fallback"
    assert "Failed to load single registered checkpoint_stores provider 'isolated'" in caplog.text


def test_resolve_extension_enumeration_failure(monkeypatch, caplog):
    def failing_entry_points(group=None):
        raise OSError("Package metadata corrupted")

    monkeypatch.setattr("importlib.metadata.entry_points", failing_entry_points)

    with caplog.at_level(logging.WARNING):
        resolved = resolve_extension(
            "signing_backends", default_factory=lambda: MockExtension("fallback")
        )
    assert resolved.name == "fallback"
    assert "Failed to enumerate entry points for 'agentv_runtime.signing_backends'" in caplog.text


def test_resolve_extension_fallback_factory_called():
    fallback = MockExtension("factory_fallback")
    resolved = resolve_extension(
        "policy_evaluators",
        default_factory=lambda: fallback,
    )
    assert resolved is fallback


def test_set_extension_none_removes_entry():
    set_extension("test_family", MockExtension("active"))
    assert resolve_extension("test_family", default_factory=MockExtension).name == "active"
    set_extension("test_family", None)
    assert (
        resolve_extension("test_family", default_factory=lambda: MockExtension("reset")).name
        == "reset"
    )
