"""Shared validation for real approval decisions and one-time action authorization."""

import math
import secrets
import time


class ApprovalValidationError(PermissionError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def validate_expiry(request):
    expires = request.metadata.get("expires_at")
    if expires is None:
        return
    if type(expires) not in (int, float) or not math.isfinite(expires):
        raise ApprovalValidationError("ApprovalExpiryInvalid")
    if time.time() >= expires:
        raise ApprovalValidationError("ApprovalExpired")


def consume_approval(request, binding):
    if request.status != "APPROVED" or request.metadata.get("revocation"):
        raise ApprovalValidationError("ApprovalNotGranted")
    validate_expiry(request)
    if request.run_id != binding["run_id"]:
        raise ApprovalValidationError("ApprovalRunMismatch")
    actual = str(request.outbound_payload_hash).removeprefix("sha3_256:")
    expected = str(binding["payload_hash"]).removeprefix("sha3_256:")
    if not actual or not secrets.compare_digest(actual, expected):
        raise ApprovalValidationError("ApprovalPayloadMismatch")
    if request.metadata.get("consumption"):
        raise ApprovalValidationError("ApprovalReplayBlocked")
    request.metadata = {
        **request.metadata,
        "consumption": {
            "run_id": request.run_id,
            "payload_hash": binding["payload_hash"],
            "consumed_at": time.time(),
            "authorization_id": secrets.token_hex(16),
        },
    }
    return request
