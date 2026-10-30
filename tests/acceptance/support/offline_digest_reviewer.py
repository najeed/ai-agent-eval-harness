"""Independent acceptance reviewer: Python crypto and ECMAScript canonicalization.

Run as a separate process with an input JSON file. Imports no AgentV code and
requires no signing backend, private key, network, or KMS credentials.
"""

import base64
import hashlib
import json
import math
import subprocess
import sys

from cryptography.hazmat.primitives import serialization


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _supported(value):
    if isinstance(value, str):
        value.encode("utf-8", errors="strict")
    elif type(value) is int:
        if abs(value) > 9007199254740991:
            raise ValueError("Unsupported integer range")
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite JSON number")
    elif isinstance(value, dict):
        for key, item in value.items():
            _supported(key)
            _supported(item)
    elif isinstance(value, list):
        for item in value:
            _supported(item)
    elif value is not None and not isinstance(value, bool):
        raise ValueError("Unsupported JSON value")


def canonical(value):
    _supported(value)
    # ECMAScript number serialization and UTF-16 property ordering are independent
    # of the Runtime's Python JCS implementation.
    script = r"""
const fs=require('fs');
function jcs(v) {
  if (Array.isArray(v)) return '['+v.map(jcs).join(',')+']';
  if (v !== null && typeof v === 'object')
    return '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+jcs(v[k])).join(',')+'}';
  return JSON.stringify(v);
}
process.stdout.write(jcs(JSON.parse(fs.readFileSync(0,'utf8'))));
"""
    return subprocess.run(
        ["node", "-e", script],
        input=json.dumps(value, ensure_ascii=False).encode(),
        capture_output=True,
        check=True,
        timeout=15,
    ).stdout


def project(artifact, purpose):
    if purpose == "agentv.certificate":
        excluded = {
            "provenance_chain",
            "signing_context",
            "certification_diagnostics",
            "verification_package",
            "package_hash",
            "evaluation_hash",
            "verification_hash",
            "certificate_hash",
        }
        payload = {key: value for key, value in artifact.items() if key not in excluded}
        if isinstance(payload.get("certification"), dict):
            payload["certification"] = {
                key: value for key, value in payload["certification"].items() if key != "stages"
            }
    elif purpose == "agentv.verification-package":
        keys = {
            "algorithm",
            "certificate_hash",
            "decision",
            "evaluation_hash",
            "evidence_root_hash",
            "executed_oracle_results",
            "execution_identity",
            "finalization_hash",
            "key_id",
            "manifest_hash",
            "manifest_id",
            "metadata",
            "package_id",
            "package_version",
            "parent_artifact_refs",
            "producer_identity",
            "producer_version",
            "required_oracle_ids",
            "scenario_hash",
            "scenario_id",
            "scenario_version",
            "schema_version",
            "signer_identity",
            "trace_hash",
            "trace_seal",
            "verification_hash",
        }
        if (
            set(artifact)
            - keys
            - {"signature", "public_key_pem", "package_hash", "content_hash", "commitment_graph"}
        ):
            raise ValueError("Unknown package field")
        payload = {key: artifact[key] for key in keys}
        for key in (
            "key_id",
            "signer_identity",
            "certificate_hash",
            "evaluation_hash",
            "verification_hash",
        ):
            payload[key] = payload[key] or ""
        payload["finalization_hash"] = payload["finalization_hash"] or payload["evaluation_hash"]
        for key in ("parent_artifact_refs", "required_oracle_ids"):
            payload[key] = sorted(payload[key])
    elif purpose == "agentv.evaluator-finalization":
        keys = {
            "evaluator_config_hash",
            "evaluator_identity",
            "evidence_root_hash",
            "execution_manifest_hash",
            "finalization_id",
            "finalized_at",
            "metadata",
            "outcome",
            "required_oracle_ids",
            "run_id",
            "scenario_hash",
            "scenario_id",
            "scenario_version",
            "schema_version",
            "score",
            "terminal_seq",
        }
        payload = {key: artifact[key] for key in keys}
        payload["required_oracle_ids"] = sorted(payload["required_oracle_ids"])
    else:
        raise ValueError("Unsupported purpose")
    return canonical(payload)


def review(data):
    purpose = data["purpose"]
    trust = data["trusted_anchor"]
    # Trust is supplied separately by the reviewer, never derived from result/embedded keys.
    if trust.get("revoked") or purpose not in trust["permitted_purposes"]:
        raise ValueError("External trust policy rejects purpose or key")
    response = data["result"]
    if set(response) != {"profile", "envelope", "signature"}:
        raise ValueError("Malformed response")
    key = serialization.load_pem_public_key(trust["public_key_pem"].encode())
    der = key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    expected = {
        "profile": "agentv.signature.digest-envelope.v1",
        "version": 1,
        "envelope_canonicalization": "RFC8785",
        "purpose": purpose,
        "payload_projection": purpose + ".unsigned.v1",
        "payload_canonicalization": "RFC8785",
        "payload_digest": hashlib.sha256(project(data["artifact"], purpose)).hexdigest(),
        "payload_digest_algorithm": "sha256",
        "payload_digest_encoding": "hex-lowercase",
        "signing_algorithm": "Ed25519",
        "signing_semantics": "raw-ed25519-over-canonical-envelope-bytes",
        "signer_identity": trust["identity"],
        "key_id": trust["key_id"],
        "public_key_fingerprint": hashlib.sha256(der).hexdigest(),
        "fingerprint_algorithm": "sha256",
        "public_key_encoding": "spki-der",
        "signature_encoding": "base64-rfc4648-padded",
        "signature_length": 64,
    }
    if (
        response["profile"] not in trust["permitted_profiles"]
        or response["profile"] != expected["profile"]
    ):
        raise ValueError("External trust policy rejects profile")
    expected_bytes = canonical(expected)
    if (
        type(response["envelope"].get("version")) is not int
        or type(response["envelope"].get("signature_length")) is not int
    ):
        raise ValueError("Envelope integer fields have the wrong JSON type")
    if canonical(response["envelope"]) != expected_bytes or len(expected_bytes) > 4096:
        raise ValueError("Envelope binding mismatch")
    signature = base64.b64decode(response["signature"], validate=True)
    if len(signature) != 64 or base64.b64encode(signature).decode() != response["signature"]:
        raise ValueError("Malformed signature encoding")
    key.verify(signature, expected_bytes)


if __name__ == "__main__":
    try:
        with open(sys.argv[1], encoding="utf-8") as handle:
            review(json.load(handle, object_pairs_hook=_pairs))
    except Exception as exc:
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        sys.exit(1)
    print("VERIFIED_DIGEST_ENVELOPE")
