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


def payload_hash_matches(left, right):
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    left, right = left.removeprefix("sha3_256:"), right.removeprefix("sha3_256:")
    return bool(left) and left.isascii() and right.isascii() and secrets.compare_digest(left, right)


def consume_approval(request, binding):
    if request.status != "APPROVED" or request.metadata.get("revocation"):
        raise ApprovalValidationError("ApprovalNotGranted")
    validate_expiry(request)
    if request.run_id != binding["run_id"]:
        raise ApprovalValidationError("ApprovalRunMismatch")
    if not payload_hash_matches(request.outbound_payload_hash, binding["payload_hash"]):
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


def expire_approval(request, run_id):
    """Shorten a live authorization's expiry while preserving its existing bindings."""
    if request.run_id != run_id:
        raise ApprovalValidationError("ApprovalRunMismatch")
    if (
        request.status not in {"PENDING", "APPROVED"}
        or request.metadata.get("revocation")
        or request.metadata.get("consumption")
    ):
        raise ApprovalValidationError("ApprovalNotExpirable")
    previous = request.metadata.get("expires_at")
    if previous is not None and (type(previous) not in (int, float) or not math.isfinite(previous)):
        raise ApprovalValidationError("ApprovalExpiryInvalid")
    now = time.time()
    expires = min(previous, now) if previous is not None else now
    request.metadata = {
        **request.metadata,
        "expires_at": expires,
        "expiry_change": {
            "previous_expires_at": previous,
            "expires_at": expires,
            "changed_at": now,
        },
    }
    return request
