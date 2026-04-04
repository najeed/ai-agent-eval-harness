"""
Gatekeeper Reference Implementation (v1.2.3)
This script demonstrates how an custom extensions CI/CD gate or auditor can verify the 
integrity of an Open Core evaluation run using the public Certificates API.

Workflow:
1. Fetch the authoritative Verification Certificate (VC) from the public API.
2. Verify the VC's asymmetric signature (ED25519) using the harness Public Key.
3. Verify the local Trace file's content integrity (SHA-256) against the VC.
"""

import os
import json
import requests
import hashlib
from eval_runner.verifier import TraceVerifier, LocalFileKeyLoader

# --- Configuration ---
# HARNESS_API_URL: The base URL of the Open Core console
HARNESS_API_URL = os.getenv("HARNESS_API_URL", "http://localhost:5000")
# PUBLIC_KEY_PATH: Path to the harness's public key (The Trust Anchor)
PUBLIC_KEY_PATH = os.getenv("PUBLIC_KEY_PATH", ".aes/keys/public_key.pem")
# RUN_ID: The specific evaluation run to verify
RUN_ID = os.getenv("RUN_ID", "sample_telecom_run")
# TRACE_PATH: Path to the local trace file to be validated
TRACE_PATH = os.getenv("TRACE_PATH", f"reports/{RUN_ID}.jsonl")

def verify_run(run_id, trace_path, public_key_path):
    print(f"[*] Starting verification for Run: {run_id}")
    
    # 1. Fetch Authoritative Certificate from Public API
    cert_url = f"{HARNESS_API_URL}/api/v1/certificates/{run_id}"
    print(f"[*] Fetching certificate from: {cert_url}")
    
    try:
        response = requests.get(cert_url)
        if response.status_code != 200:
            print(f"[!] Error: Failed to fetch certificate (HTTP {response.status_code})")
            return False
            
        vc = response.get_json()
    except Exception as e:
        print(f"[!] Network Error: {e}")
        return False
        
    print(f"[+] Certificate retrieved (ID: {vc.get('certificate_id')})")
    
    # 2. Verify Asymmetric Authority (ED25519)
    # We use the Open Core's TraceVerifier logic directly
    print(f"[*] Verifying authority using Public Key: {public_key_path}")
    
    # Extract the payload to verify (manifest without the signature)
    manifest_to_verify = vc.copy()
    sig_hex = manifest_to_verify.pop("signature_ed25519", None)
    manifest_to_verify.pop("signing_algorithm", None)
    
    if not sig_hex:
        print("[!] Error: Certificate is not signed.")
        return False
        
    manifest_bytes = json.dumps(manifest_to_verify, sort_keys=True).encode("utf-8")
    
    if not TraceVerifier.verify_asymmetric(manifest_bytes, sig_hex, public_key_path):
        print("[!] CRYPTOGRAPHIC FAILURE: Signature is invalid or key mismatch!")
        return False
        
    print("[+] Cryptographic Authority Verified.")
    
    # 3. Verify Content Integrity (SHA-256)
    print(f"[*] Verifying content integrity for: {trace_path}")
    
    if not os.path.exists(trace_path):
        print(f"[!] Error: Local trace file not found at {trace_path}")
        return False
        
    expected_hash = vc.get("sha256")
    
    # Compute local hash
    sha256 = hashlib.sha256()
    with open(trace_path, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    actual_hash = sha256.hexdigest()
    
    if expected_hash != actual_hash:
        print(f"[!] INTEGRITY FAILURE: Trace content has been tampered with!")
        print(f"    Expected: {expected_hash}")
        print(f"    Actual:   {actual_hash}")
        return False
        
    print("[+] Content Integrity Verified.")
    print("\n[SUCCESS] The run is safe and authentic. Proceed with deployment.")
    return True

if __name__ == "__main__":
    success = verify_run(RUN_ID, TRACE_PATH, PUBLIC_KEY_PATH)
    exit(0 if success else 1)
