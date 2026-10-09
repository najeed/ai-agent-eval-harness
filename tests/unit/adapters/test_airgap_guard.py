"""
Unit tests for strict fail-closed air-gapped network boundary guards (SOC 2 CC6.6 / DF-06).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from eval_runner import config
from eval_runner.adapters.common import (
    AdapterSessionPool,
    assert_airgap_safe_endpoint,
    is_airgap_safe_host,
    validate_http_endpoint,
)
from eval_runner.exceptions import AirgappedConfigurationError
from eval_runner.llm_providers import (
    AnthropicProvider,
    GeminiProvider,
    GrokProvider,
    OllamaProvider,
    OpenAIProvider,
)


class TestAirgapSafeHost:
    """Verifies host and CIDR classification for airgap safety."""

    def test_localhost_and_loopback_allowed(self) -> None:
        assert is_airgap_safe_host("localhost") is True
        assert is_airgap_safe_host("127.0.0.1") is True
        assert is_airgap_safe_host("127.0.1.1") is True
        assert is_airgap_safe_host("::1") is True
        assert is_airgap_safe_host("0.0.0.0") is True  # nosec B104

    def test_rfc1918_private_ipv4_allowed(self) -> None:
        assert is_airgap_safe_host("10.0.0.1") is True
        assert is_airgap_safe_host("10.254.254.254") is True
        assert is_airgap_safe_host("172.16.0.1") is True
        assert is_airgap_safe_host("172.31.255.255") is True
        assert is_airgap_safe_host("192.168.1.1") is True
        assert is_airgap_safe_host("192.168.100.50") is True

    def test_link_local_allowed(self) -> None:
        assert is_airgap_safe_host("169.254.169.254") is True

    def test_internal_tlds_allowed(self) -> None:
        assert is_airgap_safe_host("agent-runner.local") is True
        assert is_airgap_safe_host("model-service.internal") is True
        assert is_airgap_safe_host("deepseek.lan") is True
        assert is_airgap_safe_host("eval-cluster.corp") is True
        assert is_airgap_safe_host("mock-target.test") is True
        assert is_airgap_safe_host("gateway.home.arpa") is True

    def test_public_ips_and_domains_rejected(self) -> None:
        assert is_airgap_safe_host("api.openai.com") is False
        assert is_airgap_safe_host("api.anthropic.com") is False
        assert is_airgap_safe_host("generativelanguage.googleapis.com") is False
        assert is_airgap_safe_host("api.x.ai") is False
        assert is_airgap_safe_host("8.8.8.8") is False
        assert is_airgap_safe_host("1.1.1.1") is False
        assert is_airgap_safe_host("93.184.216.34") is False

    def test_explicit_allowed_hosts_and_cidrs(self) -> None:
        allowed = ["", "  ", "proxy.enterprise.net", "198.51.100.0/24", "invalid-cidr/999"]
        assert is_airgap_safe_host("proxy.enterprise.net", allowed_hosts=allowed) is True
        assert is_airgap_safe_host("sub.proxy.enterprise.net", allowed_hosts=allowed) is True
        assert is_airgap_safe_host("198.51.100.42", allowed_hosts=allowed) is True
        assert is_airgap_safe_host("198.51.101.1", allowed_hosts=allowed) is False
        assert is_airgap_safe_host("other.domain.com", allowed_hosts=allowed) is False

    def test_bracketed_and_port_formats(self) -> None:
        assert is_airgap_safe_host("[::1]:8080") is True
        assert is_airgap_safe_host("[::1]") is True
        assert is_airgap_safe_host("[127.0.0.1]") is True
        assert is_airgap_safe_host("localhost:8000") is True
        assert is_airgap_safe_host("10.0.0.1:5000") is True
        assert is_airgap_safe_host("[unclosed-bracket") is False

    def test_invalid_and_empty_host_handling(self) -> None:
        assert is_airgap_safe_host(None) is False
        assert is_airgap_safe_host("") is False
        assert is_airgap_safe_host("   ") is False


class TestAssertAirgapSafeEndpoint:
    """Verifies fail-closed endpoint assertion."""

    def test_noop_when_not_airgapped(self) -> None:
        with patch.object(config, "is_airgapped", return_value=False):
            # Should not raise for public WAN endpoints
            assert_airgap_safe_endpoint("https://api.openai.com/v1")
            assert_airgap_safe_endpoint("https://api.anthropic.com/v1/messages")

    def test_allowed_endpoints_when_airgapped(self) -> None:
        with patch.object(config, "is_airgapped", return_value=True):
            assert_airgap_safe_endpoint("http://localhost:8000/v1")
            assert_airgap_safe_endpoint("http://127.0.0.1:11434")
            assert_airgap_safe_endpoint("http://10.0.1.20:5000/execute_task")
            assert_airgap_safe_endpoint("https://ollama.cluster.local:443")

    def test_raises_when_airgapped_and_endpoint_is_public(self) -> None:
        with patch.object(config, "is_airgapped", return_value=True):
            with pytest.raises(AirgappedConfigurationError) as exc_info:
                assert_airgap_safe_endpoint("https://api.openai.com/v1")
            assert "Fail-closed airgap violation" in str(exc_info.value)
            assert "api.openai.com" in str(exc_info.value)

            with pytest.raises(AirgappedConfigurationError):
                assert_airgap_safe_endpoint("https://api.anthropic.com/v1/messages")

            with pytest.raises(AirgappedConfigurationError):
                assert_airgap_safe_endpoint("http://93.184.216.34:8080/api")

    def test_raises_on_empty_or_invalid_endpoint(self) -> None:
        with patch.object(config, "is_airgapped", return_value=True):
            with pytest.raises(AirgappedConfigurationError):
                assert_airgap_safe_endpoint("")
            with pytest.raises(AirgappedConfigurationError):
                assert_airgap_safe_endpoint(None)
            with pytest.raises(AirgappedConfigurationError) as exc_info:
                assert_airgap_safe_endpoint("http://[invalid-ipv6")
            assert "invalid endpoint URL" in str(exc_info.value)


class TestValidateHttpEndpointWithAirgap:
    """Verifies validate_http_endpoint integration with airgap checks."""

    def test_validates_private_url_in_airgap_mode(self) -> None:
        with patch.object(config, "is_airgapped", return_value=True):
            result = validate_http_endpoint("http://localhost:8000/v1/agent")
            assert result == "http://localhost:8000/v1/agent"

    def test_rejects_public_url_in_airgap_mode(self) -> None:
        with patch.object(config, "is_airgapped", return_value=True):
            with pytest.raises(AirgappedConfigurationError):
                validate_http_endpoint("https://api.external-agent.com/execute")


class TestLLMProvidersAirgapGuard:
    """Verifies all LLM providers fail closed upon airgap boundary violation."""

    def test_ollama_local_allowed_in_airgap(self) -> None:
        with patch.object(config, "is_airgapped", return_value=True):
            provider = OllamaProvider(host="http://localhost:11434")
            assert provider.host == "http://localhost:11434"

    def test_ollama_remote_public_rejected_in_airgap(self) -> None:
        with patch.object(config, "is_airgapped", return_value=True):
            with pytest.raises(AirgappedConfigurationError):
                OllamaProvider(host="https://remote-public-ollama.io:11434")

    def test_openai_default_public_rejected_in_airgap(self) -> None:
        with patch.object(config, "is_airgapped", return_value=True):
            with pytest.raises(AirgappedConfigurationError) as exc_info:
                OpenAIProvider(api_key="test-key")
            assert "Fail-closed airgap violation" in str(exc_info.value)

    def test_openai_internal_proxy_allowed_in_airgap(self) -> None:
        with patch.object(config, "is_airgapped", return_value=True):
            provider = OpenAIProvider(api_key="test-key", base_url="http://10.0.5.10:8000/v1")
            assert provider.base_url == "http://10.0.5.10:8000/v1"

    def test_anthropic_default_public_rejected_in_airgap(self) -> None:
        with patch.object(config, "is_airgapped", return_value=True):
            with pytest.raises(AirgappedConfigurationError):
                AnthropicProvider(api_key="test-key")

    def test_anthropic_internal_proxy_allowed_in_airgap(self) -> None:
        with patch.object(config, "is_airgapped", return_value=True):
            provider = AnthropicProvider(
                api_key="test-key", base_url="http://127.0.0.1:8080/v1/messages"
            )
            assert provider.base_url == "http://127.0.0.1:8080/v1/messages"

    def test_gemini_rejected_in_airgap(self) -> None:
        with patch.object(config, "is_airgapped", return_value=True):
            with pytest.raises(AirgappedConfigurationError) as exc_info:
                GeminiProvider(api_key="test-key")
            assert "GeminiProvider relies on public Google GenAI cloud API" in str(exc_info.value)

    def test_grok_rejected_in_airgap(self) -> None:
        with patch.object(config, "is_airgapped", return_value=True):
            with pytest.raises(AirgappedConfigurationError):
                GrokProvider(api_key="test-key")


class TestDnsRebindingAndRedirectGuards:
    """Verifies DNS rebinding and redirect revalidation defense-in-depth."""

    def test_internal_suffix_resolving_to_public_ip_rejected(self) -> None:
        # Mock DNS resolution where a .internal domain resolves to a public WAN IP
        fake_addrinfo = [
            (2, 1, 6, "", ("93.184.216.34", 80)),
        ]
        with patch("socket.getaddrinfo", return_value=fake_addrinfo):
            assert is_airgap_safe_host("malicious-rebinding.internal", resolve_dns=True) is False

    def test_rebinding_dual_homed_host_with_mixed_ips_rejected(self) -> None:
        # Host resolves to both 127.0.0.1 and a public IP (split-horizon / rebinding attack)
        fake_addrinfo = [
            (2, 1, 6, "", ("127.0.0.1", 80)),
            (2, 1, 6, "", ("8.8.8.8", 80)),
        ]
        with patch("socket.getaddrinfo", return_value=fake_addrinfo):
            assert is_airgap_safe_host("dual-homed.local", resolve_dns=True) is False

    def test_assert_airgap_safe_endpoint_rejects_rebinding_domain(self) -> None:
        fake_addrinfo = [
            (2, 1, 6, "", ("142.250.190.46", 443)),
        ]
        with patch.object(config, "is_airgapped", return_value=True):
            with patch("socket.getaddrinfo", return_value=fake_addrinfo):
                with pytest.raises(AirgappedConfigurationError) as exc_info:
                    assert_airgap_safe_endpoint("https://spoofed.internal/v1")
                assert "targets a public WAN or non-private destination" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_session_pool_redirect_trace_config_rejects_public_redirect(self) -> None:
        with patch.object(config, "is_airgapped", return_value=True):
            pool = AdapterSessionPool()
            session = pool._build_session()
            try:
                assert len(session.trace_configs) == 1
                trace_cfg = session.trace_configs[0]
                assert len(trace_cfg.on_request_redirect) == 1

                class DummyParams:
                    url = "https://public-wan-site.com/steal"

                with pytest.raises(AirgappedConfigurationError):
                    await trace_cfg.on_request_redirect[0](session, None, DummyParams())
            finally:
                await session.close()

    @pytest.mark.asyncio
    async def test_adapter_request_context_revalidates_response_history(self) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from eval_runner.adapters.common import _AdapterRequestContext

        pool = MagicMock()
        mock_session = AsyncMock()
        pool.get_session = AsyncMock(return_value=mock_session)

        mock_context = AsyncMock()
        mock_session.request = MagicMock(return_value=mock_context)

        # Create mock response with a public redirect history
        mock_response = MagicMock()
        mock_response.url = "http://127.0.0.1:8000/done"

        redirect_record = MagicMock()
        redirect_record.url = "https://external-leak.com/intermediate"
        mock_response.history = [redirect_record]

        mock_context.__aenter__.return_value = mock_response

        with patch.object(config, "is_airgapped", return_value=True):
            ctx = _AdapterRequestContext(
                pool=pool,
                method="GET",
                url="http://127.0.0.1:8000/start",
                kwargs={},
            )
            with pytest.raises(AirgappedConfigurationError) as exc_info:
                await ctx.__aenter__()
            assert "external-leak.com" in str(exc_info.value)
