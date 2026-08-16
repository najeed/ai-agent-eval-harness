"""
eval_runner.interfaces.signing
Public Extension Family: SigningBackend Contract
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class SigningBackend(ABC):
    """
    Abstraction for cryptographic signing and signature verification of evaluation traces.
    OSS Reference: LocalEd25519SigningBackend
    Control Plane / Enterprise: KMSSigningBackend / VaultSigningBackend
    """

    @abstractmethod
    def sign_payload(self, payload: bytes, key_identifier: str | Path, **kwargs: Any) -> str:
        """
        Signs a raw bytes payload and returns a base64/hex-encoded cryptographic signature string.
        """
        raise NotImplementedError

    @abstractmethod
    def verify_signature(
        self, payload: bytes, signature: str, public_key_identifier: str | Path, **kwargs: Any
    ) -> bool:
        """Verifies that the signature matches the payload under the public key."""
        raise NotImplementedError
