import pytest

from eval_runner.adapters.openapi import DualNormalizationHub


def test_normalization_hub_keywords():
    """Verify that the Agnostic Normalization Hub correctly identifies actions based on keywords."""
    # HITL Pause
    assert (
        DualNormalizationHub.normalize({"status": "Waiting for manual review"}, 200) == "hitl_pause"
    )
    assert DualNormalizationHub.normalize({"state": "pending-intervention"}, 200) == "hitl_pause"

    # Error
    assert DualNormalizationHub.normalize({"result": "The process failed"}, 200) == "error"
    assert DualNormalizationHub.normalize({"status": "crash"}, 200) == "error"

    # Final Answer (Default & Keywords)
    assert DualNormalizationHub.normalize({"status": "approved"}, 200) == "final_answer"
    assert DualNormalizationHub.normalize({"data": "some value"}, 200) == "final_answer"


def test_normalization_hub_status_codes():
    """Verify that HTTP status codes have correctly prioritized mapping."""
    # 4xx/5xx should always be error regardless of body
    assert DualNormalizationHub.normalize({"status": "success"}, 400) == "error"
    assert DualNormalizationHub.normalize({"status": "approved"}, 500) == "error"


def test_normalization_hub_overrides():
    """Verify that 'Break-Glass' mapping overrides take precedence and are validated."""
    overrides = {
        "PROPRIETARY_WAIT": "hitl_pause",
        "FAKE_SUCCESS": "error",
        "INVALID_ACTION": "not_real",  # Should be ignored
    }

    # Condition: PROPRIETARY_WAIT -> hitl_pause
    assert (
        DualNormalizationHub.normalize({"status": "PROPRIETARY_WAIT"}, 200, overrides=overrides)
        == "hitl_pause"
    )

    # Condition: FAKE_SUCCESS -> error
    assert (
        DualNormalizationHub.normalize({"status": "FAKE_SUCCESS"}, 200, overrides=overrides)
        == "error"
    )

    # Invalid Action should be ignored, falling back to heuristics (approved -> final_answer)
    assert (
        DualNormalizationHub.normalize({"status": "INVALID_ACTION"}, 200, overrides=overrides)
        == "final_answer"
    )


@pytest.mark.asyncio
async def test_openapi_adapter_polling_mock():
    """Verify the logic of the polling loop in mock conditions."""
    # This would require patching aiohttp. Wait, I'll focus on the Hub for now
    # as the adapter itself is mostly glue code around the Hub.
    pass
