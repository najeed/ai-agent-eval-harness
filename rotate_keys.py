import os
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

def rotate_keys():
    """Generates a fresh Ed25519 key pair and overwrites the compromised files in .tmp/proof_keys."""
    key_dir = Path(".tmp/proof_keys")
    private_key_path = key_dir / "private_key.pem"
    public_key_path = key_dir / "public_key.pem"

    print(f"🔐 [Forensic Remediation] Starting key rotation in {key_dir}...")

    # 1. Generate new private key
    private_key = ed25519.Ed25519PrivateKey.generate()
    
    # 2. Extract public key
    public_key = private_key.public_key()

    # 3. Serialize private key
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )

    # 4. Serialize public key
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

    # 5. Overwrite the compromised files
    key_dir.mkdir(parents=True, exist_ok=True)
    with open(private_key_path, "wb") as f:
        f.write(private_pem)
    with open(public_key_path, "wb") as f:
        f.write(public_pem)

    print(f"✅ [Forensic Remediation] Success: Fresh private/public key pair generated.")

if __name__ == "__main__":
    rotate_keys()
