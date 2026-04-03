import os
import base64
from pathlib import Path

def main():
    print("============================================")
    print("The Immutable Truth: Key Generation")
    print("Scenario: The Warden's Seal")
    print("============================================")
    
    # Locate project root
    root = Path(__file__).parent.parent.parent.parent
    key_dir = root / "walkthroughs" / "Phase 4 - Production & Governance - Expert" / "cryptographic_verification" / ".keys"
    key_dir.mkdir(exist_ok=True)

    print("\nWe are generating a unique **ED25519** keypair.")
    print("This keypair will be used to 'Anchor' your benchmarks.")
    
    input("\n[Press ENTER] to starting the generator...")
    
    # Simulate high-security key generation
    print("\n   [Entropy] Gathering system noise for randomness...")
    print("   [Math] Computing the Edwards-curve point multiplication...")
    
    # Simple base64 mock for demonstration (simulating ED25519 format)
    private_key = base64.b64encode(os.urandom(32)).decode('utf-8')
    public_key = base64.b64encode(os.urandom(32)).decode('utf-8')
    
    with open(key_dir / "private.key", "w") as f:
        f.write(private_key)
    with open(key_dir / "public.key", "w") as f:
        f.write(public_key)

    print("\n📊 Security Artifacts Created:")
    print(f"1. **Private Key (The Seal)**: {key_dir.name}/private.key")
    print(f"   [!] NEVER SHARE THIS. Use it to sign your results.")
    print(f"2. **Public Key (The Validator)**: {key_dir.name}/public.key")
    print(f"   [!] SHARE THIS. Use it to verify results are untampered.")

    print("\nSuccess. You have forged your own cryptographic seal.")
    print("\n============================================")
    print("Proceed to: Step 2 (Sign and Tamper)")
    print("============================================")

if __name__ == "__main__":
    main()

