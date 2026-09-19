from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval_runner.doctor import (
    check_agent_reachable,
    check_security_health,
    check_signing_audit_posture,
    run_doctor,
    show_registry_report,
)


@pytest.mark.asyncio
async def test_check_agent_reachable_success():
    """Verify check_agent_reachable returns True on HTTP 200/400."""
    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_instance = MagicMock()
        mock_session_cls.return_value = mock_instance
        mock_instance.__aenter__.return_value = mock_instance
        mock_instance.__aexit__ = AsyncMock()

        mock_post_context = MagicMock()
        mock_instance.post.return_value = mock_post_context

        mock_response = MagicMock()
        mock_response.status = 200
        mock_post_context.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_context.__aexit__ = AsyncMock()

        result = await check_agent_reachable("http://localhost:5001")
        assert result is True


@pytest.mark.asyncio
async def test_check_agent_reachable_failure():
    """Verify check_agent_reachable returns False on Exception."""
    with patch("aiohttp.ClientSession") as mock_session_cls:
        mock_session_cls.side_effect = Exception("Unreachable")
        result = await check_agent_reachable("http://localhost:5001")
        assert result is False


@pytest.mark.asyncio
async def test_run_doctor_smoke():
    with patch("builtins.print") as mock_print:
        with patch(
            "eval_runner.doctor.check_agent_reachable", new_callable=AsyncMock
        ) as mock_reach:
            mock_reach.return_value = True
            await run_doctor()
            assert mock_print.called


@pytest.mark.asyncio
async def test_run_doctor_old_python():
    from collections import namedtuple

    VersionInfo = namedtuple("VersionInfo", ["major", "minor", "micro"])
    with patch("sys.version_info", VersionInfo(3, 8, 0)):
        with patch("builtins.print") as mock_print:
            with patch(
                "eval_runner.doctor.check_agent_reachable", new_callable=AsyncMock
            ) as mock_reach:
                mock_reach.return_value = False
                with patch("pathlib.Path.exists", return_value=False):
                    await run_doctor(show_registry=True)
                calls = [c[0][0] for c in mock_print.call_args_list if c[0]]
                assert any("too old" in str(c).lower() for c in calls)


@pytest.mark.asyncio
async def test_run_doctor_missing_deps(monkeypatch):
    with patch("builtins.__import__", side_effect=ImportError("Missing")):
        with patch("builtins.print") as mock_print:
            with patch(
                "eval_runner.doctor.check_agent_reachable", new_callable=AsyncMock
            ) as mock_reach:
                mock_reach.return_value = True
                await run_doctor()
                calls = [c[0][0] for c in mock_print.call_args_list if c[0]]
                assert any("missing" in str(c).lower() for c in calls)


def test_check_security_health_all_branches(monkeypatch):
    # 1. No DASHBOARD_API_KEY and No SERVICE_API_KEY
    monkeypatch.delenv("DASHBOARD_API_KEY", raising=False)
    monkeypatch.delenv("SERVICE_API_KEY", raising=False)
    with patch("builtins.print") as mock_print:
        check_security_health()
        calls = [c[0][0] for c in mock_print.call_args_list if c[0]]
        assert any("DASHBOARD_API_KEY is not set" in str(c) for c in calls)
        assert any("SERVICE_API_KEY is not set" in str(c) for c in calls)

    # 2. Weak DASHBOARD_API_KEY and defaulting SERVICE_API_KEY
    monkeypatch.setenv("DASHBOARD_API_KEY", "short_key")
    monkeypatch.delenv("SERVICE_API_KEY", raising=False)
    with patch("builtins.print") as mock_print:
        check_security_health()
        calls = [c[0][0] for c in mock_print.call_args_list if c[0]]
        assert any("weak" in str(c).lower() for c in calls)
        assert any("defaulting to DASHBOARD_API_KEY" in str(c) for c in calls)

    # 3. Strong DASHBOARD_API_KEY and SERVICE_API_KEY
    monkeypatch.setenv("DASHBOARD_API_KEY", "a" * 32)
    monkeypatch.setenv("SERVICE_API_KEY", "b" * 32)
    with patch("builtins.print") as mock_print:
        check_security_health()
        calls = [c[0][0] for c in mock_print.call_args_list if c[0]]
        assert any("DASHBOARD_API_KEY is configured" in str(c) for c in calls)
        assert any("SERVICE_API_KEY is configured" in str(c) for c in calls)

    # 4. Auth provider exception branch
    auth_patch = "eval_runner.console.auth_manager.get_auth_provider"
    with patch(auth_patch, side_effect=RuntimeError("Auth load err")):
        with patch("builtins.print") as mock_print:
            check_security_health()
            calls = [c[0][0] for c in mock_print.call_args_list if c[0]]
            assert any("Auth Provider Error" in str(c) for c in calls)


def test_check_signing_audit_posture_configured_key(monkeypatch):
    monkeypatch.delenv("FLIGHT_RECORDER_KEY_PATH", raising=False)
    monkeypatch.setenv("CORE_ARTIFACT_SIGNING_PEM", "test_pem_key_content")
    monkeypatch.setenv("AUDIT_LEVEL", "2")
    with patch("builtins.print") as mock_print:
        check_signing_audit_posture()
        calls = [c[0][0] for c in mock_print.call_args_list if c[0]]
        assert any("Signing Key configured" in str(c) for c in calls)
        assert any("STRICT / FAIL-CLOSED" in str(c) for c in calls)


def test_check_signing_audit_posture_path_and_pqc(monkeypatch):
    monkeypatch.delenv("CORE_ARTIFACT_SIGNING_PEM", raising=False)
    monkeypatch.setenv("FLIGHT_RECORDER_KEY_PATH", "/path/to/key.pem")
    monkeypatch.setattr("eval_runner.config.PQC_ENABLED", True)
    monkeypatch.setattr("eval_runner.config.PQC_STRICT_MODE", True)
    with patch("builtins.print") as mock_print:
        check_signing_audit_posture()
        calls = [c[0][0] for c in mock_print.call_args_list if c[0]]
        assert any("Path: /path/to/key.pem" in str(c) for c in calls)
        assert any("ML-DSA-65" in str(c) and "STRICT MODE" in str(c) for c in calls)


def test_check_signing_audit_posture_missing_fail_closed(monkeypatch):
    monkeypatch.delenv("FLIGHT_RECORDER_KEY_PATH", raising=False)
    monkeypatch.delenv("CORE_ARTIFACT_SIGNING_PEM", raising=False)
    monkeypatch.setenv("EVAL_REQUIRE_SIGNING", "true")
    monkeypatch.setattr("eval_runner.config.PQC_ENABLED", False)
    with patch("builtins.print") as mock_print:
        check_signing_audit_posture()
        calls = [c[0][0] for c in mock_print.call_args_list if c[0]]
        assert any("Fail-Closed Mandate Active" in str(c) for c in calls)


def test_check_signing_audit_posture_unsigned_warning(monkeypatch):
    monkeypatch.delenv("FLIGHT_RECORDER_KEY_PATH", raising=False)
    monkeypatch.delenv("CORE_ARTIFACT_SIGNING_PEM", raising=False)
    monkeypatch.delenv("EVAL_REQUIRE_SIGNING", raising=False)
    monkeypatch.setenv("AUDIT_LEVEL", "0")
    monkeypatch.setattr("eval_runner.config.PQC_ENABLED", False)
    with patch("builtins.print") as mock_print:
        check_signing_audit_posture()
        calls = [c[0][0] for c in mock_print.call_args_list if c[0]]
        assert any("traces are unsigned" in str(c) for c in calls)


def test_show_registry_report_all_branches(tmp_path, monkeypatch):
    # Empty registry
    reg_patch = "eval_runner.config.RegistryManager.get_resolved_registry"
    with patch(reg_patch, return_value={"shims": {}}):
        with patch("builtins.print") as mock_print:
            show_registry_report()
            calls = [c[0][0] for c in mock_print.call_args_list if c[0]]
            assert any("Registry is empty" in str(c) for c in calls)

    # Populated registry with resources.d inside project root
    with patch(
        "eval_runner.config.RegistryManager.get_resolved_registry",
        return_value={"shims": {"demo": {"resources": {"api": "url"}}}},
    ):
        monkeypatch.setattr("eval_runner.config.SHIM_RESOURCES_D_DIR", tmp_path)
        monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", tmp_path)
        with patch("builtins.print") as mock_print:
            show_registry_report()
            calls = [c[0][0] for c in mock_print.call_args_list if c[0]]
            assert any("Shim 'demo'" in str(c) for c in calls)

    # Populated registry with resources.d outside project root (triggers ValueError on relative_to)
    with patch(
        "eval_runner.config.RegistryManager.get_resolved_registry",
        return_value={"shims": {"demo": {"resources": {}}}},
    ):
        monkeypatch.setattr("eval_runner.config.SHIM_RESOURCES_D_DIR", tmp_path / "ext_d")
        (tmp_path / "ext_d").mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr("eval_runner.config.PROJECT_ROOT", tmp_path / "other_root")
        with patch("builtins.print") as mock_print:
            show_registry_report()
            calls = [c[0][0] for c in mock_print.call_args_list if c[0]]
            assert any("Shim 'demo'" in str(c) for c in calls)

    # Error branch
    with patch(reg_patch, side_effect=Exception("Reg crash")):
        with patch("builtins.print") as mock_print:
            show_registry_report()
            calls = [c[0][0] for c in mock_print.call_args_list if c[0]]
            assert any("Registry Diagnostic Error" in str(c) for c in calls)


def test_check_security_health_pbac_misconfigured():
    with patch("eval_runner.console.auth_manager.Permission.SCENARIOS_READ", "wrong:val"):
        with patch("builtins.print") as mock_print:
            check_security_health()
            calls = [c[0][0] for c in mock_print.call_args_list if c[0]]
            assert any("PBAC Permission Nodes are misconfigured" in str(c) for c in calls)


def test_signing_readiness_result_to_dict():
    from eval_runner.signing_readiness import SigningReadinessResult

    res = SigningReadinessResult(
        is_ready=True,
        is_verifiable=True,
        signer_type="SIGNED",
        key_identifier="test_key",
        error_message=None,
    )
    d = res.to_dict()
    assert d == {
        "is_ready": True,
        "is_verifiable": True,
        "signer_type": "SIGNED",
        "key_identifier": "test_key",
        "error_message": None,
    }


def test_check_signing_readiness_corrupt_file_path(tmp_path, monkeypatch):
    from eval_runner.signing_readiness import check_signing_readiness

    corrupt_key = tmp_path / "corrupt.pem"
    corrupt_key.write_text("NOT A REAL PEM KEY", encoding="utf-8")
    monkeypatch.setenv("FLIGHT_RECORDER_KEY_PATH", str(corrupt_key))

    res = check_signing_readiness()
    assert res.is_ready is False
    assert res.is_verifiable is False
    assert res.signer_type == "FAILED"
    assert "Failed to parse private key" in str(res.error_message)


def test_check_signing_readiness_inline_pem_success_and_failure(monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    from eval_runner.signing_readiness import check_signing_readiness

    monkeypatch.delenv("FLIGHT_RECORDER_KEY_PATH", raising=False)

    # Valid inline PEM via CORE_ARTIFACT_SIGNING_PEM
    key = ed25519.Ed25519PrivateKey.generate()
    pem_str = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    monkeypatch.setenv("CORE_ARTIFACT_SIGNING_PEM", pem_str)

    res = check_signing_readiness()
    assert res.is_ready is True
    assert res.is_verifiable is True
    assert res.signer_type == "SIGNED"
    assert "inline:CORE_ARTIFACT_SIGNING_PEM" in str(res.key_identifier)

    # Corrupt inline PEM via CORE_ARTIFACT_SIGNING_PEM_SYSTEM_ID
    monkeypatch.delenv("CORE_ARTIFACT_SIGNING_PEM", raising=False)
    monkeypatch.setenv("CORE_ARTIFACT_SIGNING_PEM_SYSTEM_ID", "CORRUPTED_INLINE_PEM")

    res_fail = check_signing_readiness()
    assert res_fail.is_ready is False
    assert res_fail.is_verifiable is False
    assert res_fail.signer_type == "FAILED"
    assert "Failed to parse private key from CORE_ARTIFACT_SIGNING_PEM" in str(
        res_fail.error_message
    )


def test_check_signing_readiness_probe_exception(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    from eval_runner.signing_readiness import check_signing_readiness

    key = ed25519.Ed25519PrivateKey.generate()
    key_file = tmp_path / "probe_fail.key"
    key_file.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    monkeypatch.setenv("FLIGHT_RECORDER_KEY_PATH", str(key_file))

    mock_key = MagicMock()
    mock_key.sign.side_effect = RuntimeError("Cryptographic probe failed")
    with patch(
        "cryptography.hazmat.primitives.serialization.load_pem_private_key",
        return_value=mock_key,
    ):
        res = check_signing_readiness()
        assert res.is_ready is False
        assert res.is_verifiable is False
        assert res.signer_type == "FAILED"
        assert "Cryptographic health probe failed on active key" in str(res.error_message)


def test_check_signing_readiness_file_not_found(tmp_path, monkeypatch):
    from eval_runner.signing_readiness import check_signing_readiness

    monkeypatch.setenv("FLIGHT_RECORDER_KEY_PATH", str(tmp_path / "absent.pem"))
    res = check_signing_readiness()
    assert res.is_ready is False
    assert res.is_verifiable is False
    assert res.signer_type == "FAILED"
    assert "Configured FLIGHT_RECORDER_KEY_PATH file not found" in str(res.error_message)


def test_check_signing_readiness_identity_service_fallback_and_null(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import ed25519

    from eval_runner.signing_readiness import check_signing_readiness

    monkeypatch.delenv("FLIGHT_RECORDER_KEY_PATH", raising=False)
    monkeypatch.delenv("CORE_ARTIFACT_SIGNING_PEM", raising=False)
    monkeypatch.delenv("CORE_ARTIFACT_SIGNING_PEM_SYSTEM_ID", raising=False)

    # 1. IdentityService success fallback
    key = ed25519.Ed25519PrivateKey.generate()
    with patch("eval_runner.identity.IdentityService.get_private_key", return_value=key):
        res_id = check_signing_readiness()
        assert res_id.is_ready is True
        assert res_id.is_verifiable is True
        assert res_id.signer_type == "SIGNED"
        assert "identity_service:system_id" in str(res_id.key_identifier)

    # 2. IdentityService exception fallback -> NULL signer
    with patch(
        "eval_runner.identity.IdentityService.get_private_key",
        side_effect=Exception("Vault locked"),
    ):
        res_null = check_signing_readiness()
        assert res_null.is_ready is True
        assert res_null.is_verifiable is False
        assert res_null.signer_type == "NULL"
        assert "No persistent signing key configured" in str(res_null.error_message)
