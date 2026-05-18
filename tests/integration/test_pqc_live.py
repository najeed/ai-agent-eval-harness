import pytest


@pytest.mark.live
def test_live_cyclecore_zes_sign(pqc_client):
    """
    Live integration test for CycleCore signing and verification.
    This test runs only if CYCLECORE_API_KEY environment variable is set.
    """
    mock_digest = b"a" * 32
    signature = pqc_client.sign_digest(digest=mock_digest, identity_id="agentv_test_identity")
    assert signature is not None

    is_valid = pqc_client.verify_digest(
        signature=signature, digest=mock_digest, identity_id="agentv_test_identity"
    )
    assert is_valid is True
