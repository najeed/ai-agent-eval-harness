import json
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from agentv_runtime.versions import VC_SCHEMA_VERSION as VC_V3_SCHEMA_VERSION

from . import config, forensics
from .interfaces.signing import SigningBackend
from .utils import crypto

logger = logging.getLogger(__name__)


# Baseline schema versions for VC (Forensic Integrity) — see agentv_runtime.versions
class CertificationFailedError(RuntimeError):
    """
    Raised when the transactional certification pipeline fails at any stage.

    An evidence artifact is either successfully sealed or it is not certified:
    no partial certificate may ever be emitted (P0 #11).
    """

    def __init__(self, message: str, stage_log: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.stage_log = stage_log or []
        self.outcome = "CERTIFICATION_FAILED"


class EvidenceRootMismatchError(ValueError, CertificationFailedError):
    """Raised when declared evidence root hash does not match computed evidence graph root."""


class VerificationResult:
    """
    Structured result object for all verifiers aligned with NIST AI-100-1 principles.
    Supports consistent scoring schemas and behavioral metadata using the
    Weighted Severity Model (WSM) for aggregate scoring (Enterprise Standard v2).
    """

    # NIST 7-Dimension WSM Weights
    WSM_WEIGHTS = {
        "safety": 0.25,
        "security": 0.20,
        "reliability": 0.20,
        "fairness": 0.15,
        "explainability": 0.10,
        "privacy": 0.05,
        "resilience": 0.05,
    }

    def __init__(
        self,
        success: bool,
        message: str,
        metrics: dict[str, float] | None = None,
        metadata: dict[str, Any] | None = None,
        aggregate_score: float | None = None,
    ):
        self.success = success
        """Verify VerificationResult adheres to NIST AI-100-1 principles (7-dimension vector)."""
        self.message = message
        # NIST 7-Dimension Vector
        self.metrics = metrics or {
            "reliability": 0.0,
            "safety": 0.0,
            "security": 0.0,
            "fairness": 0.0,
            "explainability": 0.0,
            "privacy": 0.0,
            "resilience": 0.0,
        }
        self.metadata = metadata or {}

        # Calculate aggregate score using WSM if not explicitly provided
        if aggregate_score is not None:
            self.aggregate_score = aggregate_score
        else:
            self.aggregate_score = self._calculate_wsm_score()

    def _calculate_wsm_score(self) -> float:
        """
        Calculates the aggregate score using the Enterprise Weighted Severity Model.
        Implements the 'Safety Floor' logic: If Safety or Security < 0.5,
        the maximum possible aggregate score is 0.49.
        """
        score = 0.0
        for dim, weight in self.WSM_WEIGHTS.items():
            score += self.metrics.get(dim, 0.0) * weight

        # Apply Safety Floor (Critical Guardrail)
        if self.metrics.get("safety", 1.0) < 0.5 or self.metrics.get("security", 1.0) < 0.5:
            score = min(score, 0.49)

        return round(score, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregate_score": self.aggregate_score,
            "success": self.success,
            "message": self.message,
            "metrics": self.metrics,
            "metadata": self.metadata,
            "timestamp": datetime.now().astimezone().isoformat(),
        }


class BaseVerifier(ABC):
    """
    Abstract interface for standardized verification.
    All high-fidelity verifiers should implement this interface.
    """

    @abstractmethod
    def verify(self, trace_bytes: bytes, **kwargs) -> VerificationResult:
        """Executes the verification logic and returns a structured result."""
        pass


class TraceVerificationInterceptor(ABC):
    """
    [P2.8] Abstract Base Class for Trace Verification Interceptors in the signing pipeline.
    Differentiates mandatory trust providers (failure -> CERTIFICATION_FAILED)
    from optional enrichers (failure -> warning/bypass).
    """

    is_mandatory: bool = True

    @abstractmethod
    def can_sign(self, format: str) -> bool:
        """Determines if this interceptor supports the requested cryptographic signature format."""
        pass

    @abstractmethod
    def sign(self, manifest: dict, next_signer: Callable[[dict], dict]) -> dict:
        """Applies middleware processing (Preempt, Augment, or Post-process signing)."""
        pass


class CoreTraceSigner(TraceVerificationInterceptor):
    """Core standard verifier implementation of TraceVerificationInterceptor."""

    def can_sign(self, format: str) -> bool:
        # Core supports classic (ED25519) and hybrid (PQC / ML-DSA-65) signing
        return format in ["ED25519", "ML-DSA-65", "hybrid", "standard"]

    def sign(self, manifest: dict, next_signer: Callable[[dict], dict]) -> dict:
        from .identity import IdentityService

        context = manifest.get("signing_context", {})
        identity_id = context.get("identity_id", "system_id")
        timestamp = context.get("timestamp")

        try:
            from cryptography.hazmat.primitives import serialization

            from eval_runner.runtime_services import resolve_signing_backend

            signing_backend = context.get("signing_backend")
            if signing_backend is None:
                signing_backend = resolve_signing_backend()
            # Standard: Sign the manifest content (excluding transient fields like provenance_chain)
            from agentv_runtime.signatures import CERTIFICATE, certificate_payload_bytes

            manifest_bytes = certificate_payload_bytes(manifest)

            key_identifier: Any = identity_id
            if getattr(signing_backend, "requires_private_key_material", False):
                private_key = IdentityService.get_private_key(identity_id, auto_provision=False)
                if private_key is None or not hasattr(private_key, "private_bytes"):
                    raise CertificationFailedError(
                        "Pre-existing trusted private key not found for certification identity "
                        f"'{identity_id}' (required by the selected signing backend)."
                    )
                key_identifier = private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            signature = signing_backend.sign_payload(
                manifest_bytes, key_identifier, purpose=CERTIFICATE
            )
            if not signature:
                raise CertificationFailedError(
                    "Signing backend returned an empty manifest signature"
                )

            from agentv_runtime.signatures import validate_signing_response

            signature = validate_signing_response(
                manifest_bytes, signature, identity=identity_id, purpose=CERTIFICATE
            )
            manifest.setdefault("provenance_chain", []).append(
                {
                    "identity": identity_id,
                    "role": "Evaluator",
                    "timestamp": timestamp,
                    "signature": signature,
                    "algorithm": "ED25519",
                    **(
                        {"signature_profile": signature["profile"]}
                        if isinstance(signature, dict)
                        else {}
                    ),
                }
            )

            # --- [PQC Upgrade] ---
            if config.PQC_ENABLED:
                pqc_client = IdentityService.get_pqc_client()
                if pqc_client:
                    try:
                        # Zero-Exposure Signing (ZES) Pattern:
                        # We hash the manifest locally (SHAKE-256) and send only the digest.
                        shake_digest = forensics.compute_shake256_digest(manifest_bytes)
                        pqc_signature = pqc_client.sign_digest(
                            digest=shake_digest, identity_id=config.PQC_IDENTITY_ID
                        )

                        manifest["provenance_chain"].append(
                            {
                                "identity": f"{identity_id}@pqc",
                                "role": "PQC-Evaluator",
                                "timestamp": timestamp,
                                "signature": pqc_signature,
                                "algorithm": "ML-DSA-65",
                                "provider": config.PQC_PROVIDER,
                            }
                        )
                        logger.info("      [Identity] Hybrid PQC Signature attached (ML-DSA-65)")
                    except Exception as e:
                        logger.warning(f"      [Identity] PQC Signing failed (API Error): {e}")
                        if config.PQC_STRICT_MODE:
                            raise RuntimeError(
                                f"PQC_STRICT_MODE Violation: Failed to secure PQC signature: {e}"
                            ) from e
                else:
                    msg = "PQC enabled but client not available."
                    logger.warning(f"      [Identity] {msg}")
                    if config.PQC_STRICT_MODE:
                        raise RuntimeError(f"PQC_STRICT_MODE Violation: {msg}")

        except CertificationFailedError:
            # Fail-closed: an un-signable identity aborts certification; the
            # error barrier below must never swallow this into a warning.
            raise
        except Exception as e:
            logger.error(f"Could not cryptographically sign trace as '{identity_id}': {e}")
            raise CertificationFailedError(
                f"CoreTraceSigner failed to sign manifest for '{identity_id}': {e}"
            ) from e

        return next_signer(manifest)


class VerificationService:
    """Sync Pipeline orchestrator for TraceVerificationInterceptor chain."""

    def __init__(self):
        self._lock = threading.RLock()
        self._global_interceptors: list[TraceVerificationInterceptor] = []
        self._interceptor_threads: dict[TraceVerificationInterceptor, int] = {}
        self._core_signer = CoreTraceSigner()
        self._local = threading.local()

    @property
    def _interceptors(self) -> list[TraceVerificationInterceptor]:
        """Provides thread-local copy of registered interceptors to ensure thread isolation."""
        if not hasattr(self._local, "interceptors"):
            with self._lock:
                current_thread = threading.get_ident()
                main_thread = threading.main_thread().ident
                self._local.interceptors = [
                    i
                    for i in self._global_interceptors
                    if self._interceptor_threads.get(i) in (current_thread, main_thread)
                ]
        return self._local.interceptors

    def register_interceptor(self, interceptor: TraceVerificationInterceptor):
        """Registers an interceptor thread-safely at the head of the priority chain."""
        with self._lock:
            self._global_interceptors.insert(0, interceptor)
            self._interceptor_threads[interceptor] = threading.get_ident()
            if hasattr(self._local, "interceptors"):
                self._local.interceptors.insert(0, interceptor)

    def reset(self):
        """Thread-safely clears all custom interceptors."""
        with self._lock:
            self._global_interceptors.clear()
            self._interceptor_threads.clear()
            if hasattr(self._local, "interceptors"):
                self._local.interceptors.clear()

    @contextmanager
    def override_interceptor(self, interceptor: TraceVerificationInterceptor):
        """Context manager to safely register an interceptor temporarily and prevent leaks."""
        self.register_interceptor(interceptor)
        try:
            yield
        finally:
            with self._lock:
                self._interceptor_threads.pop(interceptor, None)
                if interceptor in self._global_interceptors:
                    self._global_interceptors.remove(interceptor)
                if hasattr(self._local, "interceptors") and interceptor in self._local.interceptors:
                    self._local.interceptors.remove(interceptor)

    def sign(self, manifest: dict, format: str) -> dict:
        """Executes the signing request through the chain with error barriers."""

        def make_next(index: int, depth: int) -> Callable[[dict], dict]:
            if depth > 50:
                raise RecursionError("Max verifier pipeline depth exceeded. Cycle detected.")

            interceptors_list = self._interceptors
            if index >= len(interceptors_list):
                return lambda m: self._core_signer.sign(m, lambda x: x)

            interceptor = interceptors_list[index]

            def call_next(m: dict) -> dict:
                if interceptor.can_sign(format):
                    try:
                        return interceptor.sign(m, make_next(index + 1, depth + 1))
                    except (
                        RecursionError,
                        KeyboardInterrupt,
                        SystemExit,
                        GeneratorExit,
                        CertificationFailedError,
                    ):
                        raise
                    except Exception as e:
                        is_mandatory = getattr(interceptor, "is_mandatory", False)
                        if is_mandatory:
                            logger.error(
                                f"[VerificationService] Mandatory interceptor "
                                f"'{interceptor.__class__.__name__}' failed: {e}. "
                                "Failing certification (fail-closed)."
                            )
                            raise CertificationFailedError(
                                f"Mandatory verification interceptor "
                                f"'{interceptor.__class__.__name__}' failed: {e}"
                            ) from e
                        logger.warning(
                            f"[VerificationService] Optional interceptor "
                            f"'{interceptor.__class__.__name__}' failed: {e}. "
                            "Gracefully bypassing to next handler."
                        )
                        return make_next(index + 1, depth + 1)(m)
                else:
                    return make_next(index + 1, depth + 1)(m)

            return call_next

        return make_next(0, 0)(manifest)


# Thread-safe global registry singleton
verification_service = VerificationService()


class TraceVerifier:
    """
    Electronic Verification and Certification Engine for evaluation traces.
    Implements the industrial Trust Protocol (SHA3-256 + ED25519).
    Updated for VC v3 (Forensic Integrity) and IdentityService.
    """

    @staticmethod
    def compute_signature(file_path: Path) -> str:
        """Computes the SHA3-256 hash of a file using the forensics utility."""
        return crypto.file_hash(file_path)

    @staticmethod
    def generate_key_pair(output_dir: str):
        """
        Industrial Key Generation Utility.
        Used primarily by test harnesses to provision isolated identities.
        """
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519

        p = Path(output_dir)
        if not p.is_absolute():
            p = config.PROJECT_ROOT / p

        p.mkdir(parents=True, exist_ok=True)

        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        with open(p / "private_key.pem", "wb") as f:
            f.write(
                private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )

        with open(p / "public_key.pem", "wb") as f:
            f.write(
                public_key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            )

    @staticmethod
    def sign_payload(
        payload: bytes,
        private_key_path: str | Path,
        signing_backend: SigningBackend | None = None,
    ) -> str:
        """
        Signs a raw payload using an Ed25519 private key via SigningBackend.
        Used for trace-level forensic integrity.
        """
        # Runtime implementation selection belongs to the composition
        # boundary.  Verification itself must never import a reference signer.
        from eval_runner.runtime_services import resolve_signing_backend

        backend = resolve_signing_backend(explicit=signing_backend)
        return backend.sign_payload(payload, private_key_path)

    @classmethod
    def sign_trace_bytes(
        cls,
        trace_bytes: bytes,
        *,
        run_id: str,
        run_store: Any,
        context: Mapping[str, Any] | None = None,
        identity_id: str = "system_id",
        compliance_status: str = "pass",
        compliance_score: float = 1.0,
        policy_ref: str | None = None,
        ttl_days: int | None = None,
        metadata: Mapping[str, Any] | None = None,
        behavioral_fingerprint_id: str | None = None,
        execution_mode: str | None = None,
        provisional: bool = False,
        scenario_data: Mapping[str, Any] | None = None,
        execution_manifest: Mapping[str, Any] | None = None,
        signing_backend: SigningBackend | None = None,
        evidence_root_hash: str | None = None,
        evidence_ledger: Mapping[str, Any] | None = None,
        consensus: Mapping[str, Any] | None = None,
        rubrics: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Sign exact provider-owned trace bytes.

        This is the production certification primitive.  It neither accepts nor
        discovers a run directory; the provider bytes supplied here must be the
        same bytes exposed by ``get_trace_bytes`` for this scoped run.
        """
        import hashlib

        if not run_id or run_store is None:
            raise ValueError("RunStorageProvider and explicit run_id are required for signing.")
        if signing_backend is None:
            from eval_runner.runtime_services import resolve_signing_backend

            signing_backend = resolve_signing_backend()
        raw_trace = bytes(trace_bytes)
        owned_trace = run_store.get_trace_bytes(run_id, context=context)
        if owned_trace is None or bytes(owned_trace) != raw_trace:
            raise CertificationFailedError(
                "ProviderTraceOwnershipMismatch: signing requires the provider's exact trace bytes."
            )

        from eval_runner.run_lifecycle import RunLifecycleState, get_run_lifecycle_state

        lifecycle = get_run_lifecycle_state(run_id, run_store=run_store, context=context)
        if lifecycle in (RunLifecycleState.INVALID, RunLifecycleState.UNKNOWN):
            raise CertificationFailedError(f"InvalidLifecycleState: {lifecycle.value}")

        try:
            decoded_lines = raw_trace.decode("utf-8").splitlines()
            events = []
            for idx, line in enumerate(decoded_lines, start=1):
                if line.strip():
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        raise CertificationFailedError(
                            f"Malformed trace record at line {idx}: {exc}"
                        ) from exc
        except UnicodeDecodeError as exc:
            raise CertificationFailedError(f"Malformed trace record at line 1: {exc}") from exc
        if not all(isinstance(event, dict) for event in events):
            raise CertificationFailedError("MalformedProviderTraceBytes")
        for event in events:
            event_data = event.get("data") if isinstance(event.get("data"), dict) else {}
            event_run_id = event.get("run_id") or event_data.get("run_id")
            if event_run_id and str(event_run_id) != run_id:
                raise CertificationFailedError("ProviderTraceScopeViolation")

        if ttl_days is not None and ttl_days < 0:
            raise CertificationFailedError(
                "CERTIFICATION_FAILED: Governance TTL expired or negative."
            )

        require_immutable = bool(
            getattr(config, "REQUIRE_IMMUTABLE_WORM", False)
            or (metadata or {}).get("require_immutable_worm")
        )
        if require_immutable:
            from eval_runner.runtime_services import resolve_artifact_store

            store = resolve_artifact_store()
            guarantee = getattr(store, "immutability_guarantee", None)
            if (
                guarantee == "TAMPER_EVIDENT_LOGICAL_SEAL"
                or not guarantee
                or guarantee != "HARDWARE_OR_CLOUD_ENFORCED_WORM"
            ):
                raise CertificationFailedError(
                    f"ImmutableRetentionRequired: Active artifact store "
                    f"'{store.__class__.__name__}' offers '{guarantee or 'UNSPECIFIED'}', "
                    "but deployment/scenario requires an externally enforced "
                    "immutable ArtifactStore (e.g., S3 Object Lock)."
                )

        mode = str(execution_mode or "unknown")
        from eval_runner.execution_ir import ExecutionMode

        valid_modes = {item.value for item in ExecutionMode}
        if mode not in valid_modes:
            mode, provisional = "unknown", True

        # Detached packages must preserve every issuer provisional restriction.
        provisional = bool(provisional or (metadata or {}).get("provisional") is True)
        trace_hex = hashlib.sha3_256(raw_trace).hexdigest()
        manifest: dict[str, Any] = {
            "vc_version": VC_V3_SCHEMA_VERSION,
            "harness_version": config.VERSION,
            "timestamp": datetime.now().astimezone().isoformat(),
            "run_id": run_id,
            # Schema-required opaque locator.  Core never resolves this as a
            # path; the bound provider remains the sole trace authority.
            "trace_file": "provider://trace",
            "trace_hash": trace_hex,
            "hash_algorithm": "sha3_256",
            "evidence_ledger": dict(evidence_ledger or {}),
            "compliance": {
                "status": compliance_status,
                "score": compliance_score,
                "policy_ref": policy_ref or config.TRUSTED_POLICY_REF,
            },
            "governance_ttl": ttl_days or config.GOVERNANCE_TTL_DAYS,
            "metadata": {
                **dict(metadata or {}),
                "certificate_profile": f"agentv.certification.v{VC_V3_SCHEMA_VERSION}",
                "provisional": bool(provisional),
            },
            "behavioral_fingerprint_id": behavioral_fingerprint_id or "default_v1",
            "provenance_chain": [],
            "execution_mode": mode,
            "provisional": bool(provisional),
            "certification": {
                "pipeline_version": "2.0.0",
                "transactional": True,
                "outcome": (
                    "CERTIFIED_PASS"
                    if compliance_status.lower() == "pass" and mode == "live" and not provisional
                    else "PROVISIONAL_PASS"
                    if compliance_status.lower() == "pass"
                    else "ATTESTED_FAIL"
                ),
            },
        }
        if scenario_data is None and run_store is not None and run_id:
            try:
                if hasattr(run_store, "get_manifest"):
                    raw_m = run_store.get_manifest(run_id, context=context)
                    if isinstance(raw_m, dict) and raw_m.get("scenario_data"):
                        scenario_data = raw_m["scenario_data"]
            except Exception as exc:
                logger.debug("Scenario data resolution fallback: %s", exc)
        if execution_manifest is None and run_store is not None and run_id:
            try:
                if hasattr(run_store, "get_manifest"):
                    raw_m = run_store.get_manifest(run_id, context=context)
                    if isinstance(raw_m, dict) and raw_m.get("execution_manifest"):
                        execution_manifest = raw_m["execution_manifest"]
            except Exception as exc:
                logger.debug("Execution manifest resolution fallback: %s", exc)
        if scenario_data is not None:
            manifest["scenario_data"] = dict(scenario_data)
        if execution_manifest is not None:
            manifest["execution_manifest"] = dict(execution_manifest)
        if consensus is not None:
            manifest["consensus"] = dict(consensus)
        if rubrics is not None:
            manifest["rubrics"] = dict(rubrics)
        if events:
            from agentv_runtime.evidence_graph import build_evidence_graph_from_events

            event_lines = list(
                zip(events, [line for line in decoded_lines if line.strip()], strict=False)
            )
            graph = build_evidence_graph_from_events(
                event_lines,
                required_oracle_ids=manifest["metadata"].get("required_oracle_ids"),
            )
            manifest["evidence_root_hash"] = graph.get("evidence_root_hash", "")
            if evidence_root_hash and manifest.get("evidence_root_hash") != evidence_root_hash:
                filtered_lines = [
                    (ev, line)
                    for ev, line in event_lines
                    if not (
                        ev.get("event") == "evaluator_finalization"
                        or (
                            ev.get("event")
                            in ("run_end", "verification_decision", "session_decision")
                            and isinstance(
                                ev.get("finalization")
                                or (ev.get("data") if isinstance(ev.get("data"), dict) else {}).get(
                                    "finalization"
                                ),
                                dict,
                            )
                        )
                    )
                ]
                graph_filtered = build_evidence_graph_from_events(
                    filtered_lines,
                    required_oracle_ids=manifest["metadata"].get("required_oracle_ids"),
                )
                if graph_filtered.get("evidence_root_hash") == evidence_root_hash:
                    manifest["evidence_root_hash"] = evidence_root_hash

        if evidence_root_hash and manifest.get("evidence_root_hash") != evidence_root_hash:
            raise EvidenceRootMismatchError(
                f"EvidenceRootMismatch: declared={evidence_root_hash} "
                f"computed={manifest.get('evidence_root_hash')}"
            )

        manifest["signing_context"] = {
            "identity_id": identity_id,
            "timestamp": manifest["timestamp"],
            "signing_backend": signing_backend,
        }
        try:
            verification_service.sign(
                manifest, format="hybrid" if config.PQC_ENABLED else "ED25519"
            )
        finally:
            manifest.pop("signing_context", None)
        if not manifest["provenance_chain"]:
            raise CertificationFailedError(
                "UnsignedProviderTrace: signing produced no provenance chain."
            )

        # Build and sign the VerificationPackage bound to the certificate
        from dataclasses import replace

        from agentv_runtime.canonical import canonical_json_encode
        from agentv_runtime.package import VerificationPackage

        scen_id_val = (
            (scenario_data or {}).get("id")
            or (scenario_data or {}).get("scenario_id")
            or manifest.get("metadata", {}).get("scenario_id")
            or ""
        )
        scen_ver_val = (
            (scenario_data or {}).get("version")
            or manifest.get("metadata", {}).get("scenario_version")
            or "1.0.0"
        )
        scen_h_val = manifest.get("metadata", {}).get("scenario_hash") or ""
        if not scen_h_val and scenario_data:
            from agentv_runtime.manifest import compute_scenario_hash

            scen_h_val = compute_scenario_hash(scenario_data)
        m_id_val = (
            (execution_manifest or {}).get("manifest_id")
            or manifest.get("metadata", {}).get("manifest_id")
            or f"man_{run_id}"
        )
        m_h_val = manifest.get("metadata", {}).get("execution_manifest_hash") or ""
        if not m_h_val and execution_manifest:
            try:
                from agentv_runtime.manifest import ExecutionManifest

                m_h_val = ExecutionManifest.from_dict(execution_manifest).compute_manifest_hash()
            except Exception:
                enc_bytes = canonical_json_encode(execution_manifest)
                m_h_val = f"sha3_256:{hashlib.sha3_256(enc_bytes).hexdigest()}"
        ev_root_val = manifest.get("evidence_root_hash") or ""
        required_inventory = (
            (execution_manifest.get("metadata") or {}).get("required_oracle_ids", [])
            if execution_manifest is not None
            else manifest.get("metadata", {}).get("required_oracle_ids") or []
        )
        pkg_req_oracles = list(required_inventory)
        executed_oracles: list[dict[str, Any]] = []
        if events:
            from agentv_runtime.evidence_graph import index_events_by_seq

            source_index = index_events_by_seq(event_lines)
            has_explicit_sequence = any(isinstance(event.get("_seq"), int) for event in events)
            for position, (ev, _line) in enumerate(event_lines, start=1):
                data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
                carrier_rows = []
                for key in ("oracle_results", "executed_oracle_results"):
                    results = data.get(key) or ev.get(key)
                    if isinstance(results, list):
                        carrier_rows.extend(results)
                if ev.get("event") in (
                    "oracle_result",
                    "executed_oracle_result",
                    "assertion_evaluated",
                    "metric_evaluated",
                ):
                    carrier_rows.append(data if data else ev)
                for oracle in carrier_rows:
                    if not isinstance(oracle, dict):
                        raise CertificationFailedError("MalformedOracleResult: expected object")
                    source_sequence = ev.get("_seq") if has_explicit_sequence else position
                    if ev.get("event") in (
                        "oracle_result",
                        "executed_oracle_result",
                        "assertion_evaluated",
                        "metric_evaluated",
                    ):
                        source_sequence = (
                            data.get("event_seq") or ev.get("event_seq") or source_sequence
                        )
                    if not isinstance(source_sequence, int) or source_sequence not in source_index:
                        raise CertificationFailedError("UnboundOracleTraceCarrier")
                    # These are compiler-owned coordinates, never claims copied
                    # from an oracle row or an agent response.
                    bound_oracle = dict(oracle)
                    bound_oracle["sequence"] = source_sequence
                    bound_oracle["source_hash"] = source_index[source_sequence]
                    executed_oracles.append(bound_oracle)

        eval_hash = manifest.get("metadata", {}).get("evaluator_finalization_hash") or ""
        if not eval_hash:
            for ev in reversed(events):
                if ev.get("event") == "evaluator_finalization":
                    eval_hash = str(
                        ev.get("finalization_hash")
                        or (ev.get("data", {}) or {}).get("finalization_hash")
                        or ""
                    )
                    if eval_hash:
                        break
                elif ev.get("event") in ("run_end", "verification_decision", "session_decision"):
                    fin_sub = ev.get("finalization") or (ev.get("data", {}) or {}).get(
                        "finalization"
                    )
                    if isinstance(fin_sub, Mapping) and fin_sub.get("finalization_hash"):
                        eval_hash = str(fin_sub["finalization_hash"])
                        break

        verif_payload = {
            "decision": {
                "decision": "PASS" if compliance_status.lower() == "pass" else "FAIL",
                "score": compliance_score,
                "status": compliance_status,
            },
            "evidence_root_hash": ev_root_val,
            "executed_oracle_results": executed_oracles,
            "required_oracle_ids": sorted(pkg_req_oracles),
        }
        verif_hash = (
            f"sha3_256:{hashlib.sha3_256(canonical_json_encode(verif_payload)).hexdigest()}"
        )

        cert_payload = {
            "compliance": manifest["compliance"],
            "evidence_root_hash": ev_root_val,
            "execution_mode": manifest.get("execution_mode", "unknown"),
            "run_id": run_id,
            "timestamp": manifest["timestamp"],
            "trace_hash": manifest.get("trace_hash", trace_hex),
            "vc_version": manifest["vc_version"],
        }
        cert_hash = f"sha3_256:{hashlib.sha3_256(canonical_json_encode(cert_payload)).hexdigest()}"

        non_finalization_events = [
            e
            for e in events
            if not (
                e.get("event") == "evaluator_finalization"
                or (
                    e.get("event") in ("run_end", "verification_decision", "session_decision")
                    and isinstance(
                        e.get("finalization")
                        or (
                            e.get("data", {}).get("finalization")
                            if isinstance(e.get("data"), dict)
                            else None
                        ),
                        dict,
                    )
                )
            )
        ]
        pkg = VerificationPackage(
            package_id=f"pkg_{run_id}",
            scenario_id=str(scen_id_val),
            scenario_version=str(scen_ver_val),
            scenario_hash=str(scen_h_val),
            manifest_id=str(m_id_val),
            manifest_hash=str(m_h_val),
            execution_identity={
                "run_id": run_id,
                "execution_mode": manifest.get("execution_mode", "live"),
                "agent_id": manifest.get("metadata", {}).get("agent_id") or "system_agent",
            },
            trace_hash=manifest.get("trace_hash", trace_hex),
            trace_seal={
                "trace_digest": manifest.get("trace_hash", trace_hex),
                "algorithm": "sha3_256",
                "event_count": len(non_finalization_events),
                "sealed_at": manifest["timestamp"],
            },
            evidence_root_hash=ev_root_val,
            required_oracle_ids=pkg_req_oracles,
            executed_oracle_results=executed_oracles,
            decision={
                "decision": "PASS" if compliance_status.lower() == "pass" else "FAIL",
                "status": compliance_status,
                "score": compliance_score,
            },
            finalization_hash=eval_hash,
            evaluation_hash=eval_hash,
            verification_hash=verif_hash,
            certificate_hash=cert_hash,
            package_version="1.0.0",
            signature=None,
            signer_identity=identity_id,
            algorithm="ed25519",
            metadata=manifest.get("metadata", {}),
        )

        from eval_runner.identity import IdentityService

        pub_pem = None
        # Provider signing backends own key references, while the local
        # reference backend deliberately requires actual private key
        # material.  The manifest-signing path above already makes this
        # distinction; package signing must use the identical key
        # resolution or a valid certificate fails after its first
        # signature with ``Signing key not found at system_id``.
        package_key_identifier: Any = identity_id
        if getattr(signing_backend, "requires_private_key_material", False):
            private_key = IdentityService.get_private_key(identity_id, auto_provision=False)
            if private_key is None or not hasattr(private_key, "private_bytes"):
                raise CertificationFailedError(
                    "Pre-existing trusted private key not found for certification identity "
                    f"'{identity_id}' (required by the selected signing backend)."
                )
            from cryptography.hazmat.primitives import serialization

            package_key_identifier = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        from agentv_runtime.signatures import PACKAGE, validate_signing_response

        pkg_sig = signing_backend.sign_payload(
            pkg.canonical_payload_bytes(), package_key_identifier, purpose=PACKAGE
        )
        pkg_sig = validate_signing_response(
            pkg.canonical_payload_bytes(), pkg_sig, identity=identity_id, purpose=PACKAGE
        )
        get_backend_public_key = getattr(signing_backend, "get_public_key", lambda _id: None)
        backend_public_key = get_backend_public_key(identity_id)
        if isinstance(backend_public_key, bytes):
            pub_pem = backend_public_key.decode("utf-8")
        elif isinstance(backend_public_key, str):
            pub_pem = backend_public_key
        elif hasattr(backend_public_key, "public_bytes"):
            from cryptography.hazmat.primitives import serialization

            pub_pem = backend_public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("utf-8")
        if not pkg_sig:
            raise CertificationFailedError(
                "IncompletePackageSignature: signing produced no signature"
            )
        pkg = replace(pkg, signature=pkg_sig, public_key_pem=pub_pem)
        manifest["verification_package"] = pkg.to_dict()
        manifest["package_hash"] = pkg.compute_package_hash()
        manifest["evaluation_hash"] = eval_hash
        manifest["verification_hash"] = verif_hash
        manifest["certificate_hash"] = cert_hash
        return manifest

    @classmethod
    def sign_trace(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Removed production filesystem signer; use :meth:`sign_trace_bytes`."""
        raise RuntimeError("ProviderOwnedEvidenceRequired: use sign_trace_bytes, not a trace path.")

    @classmethod
    def get_certificate(
        cls,
        *args: Any,
        run_id: str | None = None,
        identity_id: str = "system_id",
        run_store: Any = None,
        context: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Signs provider-owned trace bytes and returns the certificate directly.
        Routes strictly through CertificationService.execute_industrial_certification.
        Fails closed on any error (legacy fallback eliminated).
        """
        resolved_run_id = str(args[0]) if args else str(run_id or "")
        if not resolved_run_id or run_store is None:
            raise ValueError("RunStorageProvider and explicit run_id are required.")
        from eval_runner.services.certification import CertificationService

        res = CertificationService.execute_industrial_certification(
            run_id=resolved_run_id,
            identity_id=identity_id,
            run_store=run_store,
            context=context,
        )
        manifest = res.get("manifest")
        if manifest and isinstance(manifest, dict) and "trace_hash" in manifest:
            return manifest
        raise CertificationFailedError(
            f"CertificationService failed to produce a valid certificate manifest for {run_id}"
        )

    @classmethod
    async def verify_trace_async(
        cls,
        trace_bytes: bytes,
        manifest: Mapping[str, Any],
        *,
        run_store: Any,
        context: dict[str, Any] | None = None,
        trace_only: bool = False,
        **kwargs: Any,
    ) -> bool:
        """Async provider-native verification entry point."""
        return cls.verify_trace_bytes(
            trace_bytes,
            manifest,
            run_store=run_store,
            context=context,
            trace_only=trace_only,
            **kwargs,
        )

    @classmethod
    def verify_trace_bytes(
        cls,
        trace_bytes: bytes,
        manifest: Mapping[str, Any],
        *,
        run_store: Any,
        context: dict[str, Any] | None = None,
        verify_ledger: bool = False,
        trace_only: bool = False,
        scenario_data: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> bool:
        """Verify exact provider-owned bytes without a filesystem adapter."""
        import hashlib

        if kwargs.get("require_sealed") is not None:
            trace_only = not bool(kwargs["require_sealed"])

        run_id = manifest.get("run_id") or kwargs.get("run_id")
        if not run_id or run_store is None:
            return False
        owned_trace = run_store.get_trace_bytes(run_id, context=context)
        if owned_trace is None or bytes(owned_trace) != bytes(trace_bytes):
            return False
        expected_raw = str(manifest.get("trace_hash") or "")
        expected_hex = (
            expected_raw.split(":", 1)[1] if expected_raw.startswith("sha3_256:") else expected_raw
        )
        actual_hex = hashlib.sha3_256(trace_bytes).hexdigest()
        if expected_hex != actual_hex:
            return False
        if not trace_only:
            from eval_runner.run_lifecycle import RunLifecycleState, get_run_lifecycle_state

            if (
                get_run_lifecycle_state(run_id, run_store=run_store, context=context)
                != RunLifecycleState.SEALED
            ):
                return False
        if verify_ledger or kwargs.get("verify_ledger"):
            # A ledger cannot be validated by reaching into a local provider's
            # vault. Providers that expose artifact-ledger verification must
            # implement it as an explicit contract before this option can be
            # supported.
            return False
        scenario = (
            scenario_data
            or kwargs.get("scenario_data")
            or manifest.get("scenario_data")
            or manifest.get("scenario")
        )
        certificate = verify_trace_certificate(
            run_id,
            bytes(trace_bytes),
            cert_data=dict(manifest),
            scenario_data=scenario,
            trace_only=trace_only,
            **kwargs,
        )
        if not certificate.get("verified"):
            return False
        if trace_only:
            return True
        package = manifest.get("verification_package")
        execution_manifest = manifest.get("execution_manifest")
        if not package or not execution_manifest:
            return False
        result = VerificationAuthority.verify_certification_artifact(
            package,
            raw_trace_bytes=bytes(trace_bytes),
            canonical_manifest=execution_manifest,
            scenario_data=scenario,
        )
        return bool(result.get("verified"))

    @classmethod
    def verify_trace(
        cls,
        trace_bytes: bytes,
        manifest: Mapping[str, Any],
        *,
        run_store: Any = None,
        context: dict[str, Any] | None = None,
        trace_only: bool = False,
        **kwargs: Any,
    ) -> bool:
        """Verify provider-owned exact trace bytes and a provider manifest.

        Production callers must supply the execution owner's provider and its
        exact committed trace serialization.
        """
        if not isinstance(trace_bytes, bytes) or not isinstance(manifest, Mapping):
            return False
        if run_store is None:
            return False
        return cls.verify_trace_bytes(
            trace_bytes,
            manifest,
            run_store=run_store,
            context=context,
            trace_only=trace_only,
            **kwargs,
        )

    @classmethod
    def verify_run(
        cls,
        run_id: str,
        *,
        run_store: Any,
        context: dict[str, Any] | None = None,
        scenario_data: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            run = run_store.get_run(run_id, context=context)
            manifest = run_store.get_manifest(run_id, context=context)
            trace_bytes = run_store.get_trace_bytes(run_id, context=context)
        except Exception as e:
            return {
                "run_id": run_id,
                "verification_status": "FAILED_VERIFICATION",
                "is_valid": False,
                "has_certificate": False,
                "has_signature": False,
                "failure_reason": f"Corrupt or malformed run evidence: {e}",
            }
        if run is None and trace_bytes is None:
            return {
                "run_id": run_id,
                "verification_status": "NOT_FOUND",
                "is_valid": False,
                "has_certificate": False,
                "has_signature": False,
                "failure_reason": "Run not found by storage provider.",
            }
        if not manifest:
            return {
                "run_id": run_id,
                "verification_status": "UNVERIFIED",
                "is_valid": False,
                "has_certificate": False,
                "has_signature": False,
                "failure_reason": "Certification manifest not returned by storage provider.",
            }
        if (run and run.get("run_id") not in (None, run_id)) or manifest.get("run_id") not in (
            None,
            run_id,
        ):
            return {
                "run_id": run_id,
                "verification_status": "FAILED_VERIFICATION",
                "is_valid": False,
                "has_certificate": bool(manifest),
                "has_signature": False,
                "failure_reason": "Provider scope returned artifacts for a different run.",
            }
        if trace_bytes is None:
            return {
                "run_id": run_id,
                "verification_status": "FAILED_VERIFICATION",
                "is_valid": False,
                "has_certificate": True,
                "has_signature": bool(manifest.get("signature") or manifest.get("signatures")),
                "failure_reason": "Trace bytes not returned by storage provider.",
            }
        try:
            verify_kwargs = dict(kwargs)
            verify_kwargs.pop("trace_only", None)
            verify_kwargs.pop("require_sealed", None)
            if scenario_data is not None:
                verify_kwargs["scenario_data"] = scenario_data
            valid = cls.verify_trace_bytes(
                trace_bytes,
                manifest,
                run_store=run_store,
                context=context,
                trace_only=False,
                **verify_kwargs,
            )
        except Exception as exc:
            valid, failure_reason = False, f"Verification error: {exc}"
        else:
            failure_reason = (
                None if valid else "Trace content hash or signature verification failed."
            )
        algorithm = manifest.get("algorithm") or manifest.get("crypto_suite", "Ed25519")
        mode = manifest.get("execution_mode")
        provisional = bool(
            manifest.get("provisional") or mode in {"simulated", "unknown"} or not mode
        )
        if valid and (provisional or str(mode).lower() not in {"live", "hybrid"}):
            valid = False
            failure_reason = (
                "Authoritative verification requires a non-provisional live or hybrid run."
            )
        compliance = manifest.get("compliance") or {}
        certification = manifest.get("certification") or {}
        package_data = manifest.get("verification_package") or {}
        package_decision = (
            package_data.get("decision") if isinstance(package_data, Mapping) else None
        )
        if not isinstance(package_decision, Mapping):
            package_decision = {}
        outcome = str(
            package_decision.get("decision")
            or certification.get("outcome")
            or compliance.get("status")
            or manifest.get("compliance_status")
            or ""
        ).lower()
        passed = outcome in {"pass", "passed", "certified", "certified_pass"}
        terminal_verdict = (
            "CERTIFIED_PASS" if valid and passed else "ATTESTED_FAIL" if valid else "UNVERIFIED"
        )
        verification_status = (
            "VERIFIED"
            if terminal_verdict == "CERTIFIED_PASS"
            else "ATTESTED_FAIL"
            if valid
            else "FAILED_VERIFICATION"
        )
        return {
            "run_id": run_id,
            "verification_status": verification_status,
            "verdict": verification_status,
            "terminal_verdict": terminal_verdict,
            "verified": valid and passed,
            "is_valid": valid,
            "cryptographically_valid": valid,
            "certificate_valid": valid,
            "evaluation_passed": passed,
            "has_certificate": True,
            "has_signature": bool(
                manifest.get("signature")
                or manifest.get("signatures")
                or manifest.get("provenance_chain")
            ),
            "algorithm": algorithm,
            "is_pqc": "ml-dsa" in str(algorithm).lower() or "pqc" in str(algorithm).lower(),
            "trace_hash": manifest.get("trace_hash"),
            "timestamp": manifest.get("timestamp"),
            "execution_mode": mode,
            "provisional": provisional,
            "failure_reason": failure_reason,
        }

        # authoritative source — avoids parent-prop fragility on direct/deep navigation.


def verify_trace_certificate(
    run_id: str,
    trace_bytes: bytes,
    cert_data: dict[str, Any] | None = None,
    scenario_data: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
    trace_only: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Certificate integrity check used by the complete verification service.

    This check alone does not authorize certification. Use verify_run for
    provider-owned runs or verify_certification_artifact for exported artifacts.
    Explicit trace_only mode also permits non-authoritative legacy signatures.

    Performs:
    1. Recompute trace SHA3-256 hash and compare against cert manifest trace_hash.
    2. If scenario_data is provided, verify scenario_hash matches the cert entry.
    3. Validate the Ed25519 signature in the provenance_chain against the trace bytes.

    Returns a dict with keys:
        verified (bool), signer_identity (str|None), manifest_hash_match (bool),
        scenario_hash_match (bool), errors (list[str]), algorithm (str|None).
    """
    import hashlib
    import json as _json

    def _norm_sha3(value: Any) -> str | None:
        """Normalizes 'sha3_256:<hex>' or bare '<hex>' forms to bare hex."""
        if isinstance(value, str):
            return value.split(":", 1)[1] if value.startswith("sha3_256:") else value
        return None

    if cert_data is None:
        cert_data = manifest or {}

    result: dict[str, Any] = {
        "verified": False,
        "authoritative": False,
        "verification_mode": "DIAGNOSTIC" if trace_only else "CERTIFICATE_INTEGRITY",
        "signer_identity": None,
        "manifest_hash_match": False,
        "scenario_hash_match": False,
        "errors": [],
        "algorithm": None,
    }

    # 1. Trace hash match
    expected_trace_hash = _norm_sha3(cert_data.get("trace_hash"))
    if expected_trace_hash:
        computed_hex = hashlib.sha3_256(trace_bytes).hexdigest()
        if computed_hex == expected_trace_hash:
            result["manifest_hash_match"] = True
        else:
            result["errors"].append(
                f"Trace hash mismatch: expected={expected_trace_hash!r}, "
                f"computed=sha3_256:{computed_hex!r}"
            )
    else:
        # No reference hash in cert \u2014 cannot verify
        result["errors"].append("Certificate does not contain a trace_hash for verification.")

    # 2. Scenario hash match
    if scenario_data is None:
        scenario_data = cert_data.get("scenario_data") or cert_data.get("scenario")
    if scenario_data is not None:
        try:
            from agentv_runtime.manifest import compute_scenario_hash

            expected_scen_hash = cert_data.get("scenario_hash") or (
                cert_data.get("metadata", {}).get("scenario_hash")
                if isinstance(cert_data.get("metadata"), dict)
                else None
            )
            if expected_scen_hash:
                computed_scen = compute_scenario_hash(scenario_data)
                if computed_scen == expected_scen_hash:
                    result["scenario_hash_match"] = True
                else:
                    result["errors"].append(
                        f"Scenario hash mismatch: expected={expected_scen_hash!r}, "
                        f"computed={computed_scen!r}"
                    )
        except Exception as scen_err:
            result["errors"].append(f"Scenario hash check failed: {scen_err}")

    # 3. Signature verification \u2014 validate the Ed25519 provenance chain.
    # The certification pipeline signs canonical manifest bytes with the
    # provenance chain and transient signing context removed.  Certification
    # semantics remain signed; only its volatile stage log is excluded.  The
    # signed manifest in turn binds the trace via ``trace_hash``.
    provenance_chain = cert_data.get("provenance_chain") or cert_data.get("signatures") or []
    if not provenance_chain:
        result["errors"].append("Certificate has no provenance_chain entries to verify.")

    signed_payload = dict(cert_data)
    signed_payload.pop("provenance_chain", None)
    signed_payload.pop("signing_context", None)
    signed_payload.pop("certification_diagnostics", None)
    if "certification" in signed_payload and isinstance(signed_payload["certification"], dict):
        cert_copy = dict(signed_payload["certification"])
        cert_copy.pop("stages", None)
        signed_payload["certification"] = cert_copy
    from agentv_runtime.canonical import canonical_json_encode as _cje

    cand_base = dict(signed_payload)
    for k in (
        "verification_package",
        "package_hash",
        "evaluation_hash",
        "verification_hash",
        "certificate_hash",
    ):
        cand_base.pop(k, None)

    # Current certificates have one canonical envelope, including execution_manifest.
    from agentv_runtime.signatures import CERTIFICATE, certificate_payload_bytes

    candidate_manifest_bytes = [certificate_payload_bytes(cert_data)]
    if trace_only:
        # Legacy payloads are available only for explicitly diagnostic verification.
        legacy = dict(cand_base)
        legacy.pop("execution_manifest", None)
        candidate_manifest_bytes.extend(
            [
                _cje(legacy),
                _cje(signed_payload),
                json.dumps(cand_base, sort_keys=True).encode("utf-8"),
                json.dumps(legacy, sort_keys=True).encode("utf-8"),
                json.dumps(signed_payload, sort_keys=True).encode("utf-8"),
            ]
        )

    sig_verified = False
    all_signatures_valid = True
    sig_count = 0
    for entry in provenance_chain:
        if not isinstance(entry, dict):
            result["errors"].append(
                f"Malformed provenance entry (expected object, got {type(entry).__name__})."
            )
            all_signatures_valid = False
            continue
        algorithm = entry.get("algorithm", "ED25519")
        signature_hex = entry.get("signature", "")
        identity_id = entry.get("identity") or entry.get("signer_identity") or "system_id"

        if isinstance(signature_hex, dict):
            from agentv_runtime.signatures import resolve_policy, verify_artifact_signature

            try:
                if algorithm != "ED25519" or entry.get("signature_profile") != signature_hex.get(
                    "profile"
                ):
                    raise ValueError("Signature profile or algorithm declaration mismatch")
                policy = resolve_policy(identity_id)
                valid = verify_artifact_signature(
                    candidate_manifest_bytes[0], signature_hex, policy, CERTIFICATE
                )
            except Exception:
                valid = False
            if not valid:
                result["errors"].append(f"EnvelopeSignatureVerificationFailed: '{identity_id}'")
                all_signatures_valid = False
            else:
                sig_count += 1
                result["signer_identity"] = identity_id
                result["algorithm"] = algorithm
            continue

        if entry.get("signature_profile") is not None or algorithm not in {
            "ED25519",
            "ed25519",
            "Ed25519",
            "ML-DSA-65",
        }:
            result["errors"].append(f"UnsupportedSignatureProfile: '{identity_id}'")
            all_signatures_valid = False
            continue

        if not signature_hex or (algorithm != "ML-DSA-65" and len(signature_hex) < 8):
            result["errors"].append(
                f"Signature entry for identity '{identity_id}' is empty or malformed."
            )
            all_signatures_valid = False
            continue

        # Fail-closed: reject degenerate all-zero placeholder signatures.
        # These carry no cryptographic proof (and would bypass verification
        # entirely against mock/transparent key objects), so they must never
        # be allowed to certify evidence.
        normalized_sig = signature_hex.strip().lower()
        if not normalized_sig or set(normalized_sig) == {"0"}:
            result["errors"].append(
                f"Degenerate all-zero signature rejected for identity '{identity_id}' "
                "(fail-closed: placeholder signatures cannot certify evidence)."
            )
            all_signatures_valid = False
            continue

        if algorithm == "ML-DSA-65":
            try:
                from . import forensics
                from .identity import IdentityService

                pqc_client = IdentityService.get_pqc_client()
                if not pqc_client:
                    result["errors"].append(
                        "PQC client not available to verify ML-DSA-65 signature."
                    )
                    all_signatures_valid = False
                    continue
                shake_digest = forensics.compute_shake256_digest(candidate_manifest_bytes[0])
                if not pqc_client.verify_digest(
                    signature=signature_hex,
                    digest=shake_digest,
                    identity_id=identity_id,
                ):
                    result["errors"].append(
                        f"ML-DSA-65 signature verification failed for '{identity_id}'."
                    )
                    all_signatures_valid = False
                    continue
                sig_count += 1
                continue
            except Exception as pqc_err:
                result["errors"].append(f"ML-DSA-65 signature check error: {pqc_err}")
                all_signatures_valid = False
                continue

        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            from cryptography.hazmat.primitives.serialization import (
                Encoding,
                PublicFormat,
                load_pem_public_key,
            )

            from .identity import IdentityService

            # 1. Authoritative Anchor Key Lookup (Fail-closed: trust root must be anchored)
            anchor_pk = None
            trust_root = kwargs.get("trust_root")
            if trust_root:
                if hasattr(trust_root, "get_public_key"):
                    anchor_pk = trust_root.get_public_key(identity_id)
                elif isinstance(trust_root, (str, Path)):
                    cand = Path(trust_root) / identity_id / "public_key.pem"
                    if not cand.is_file():
                        cand = Path(trust_root) / f"{identity_id}.pem"
                    if cand.is_file():
                        try:
                            anchor_pk = load_pem_public_key(cand.read_bytes())
                        except Exception:
                            anchor_pk = None
            if anchor_pk is None:
                try:
                    anchor_pk = IdentityService.get_public_key(identity_id, auto_provision=False)
                except Exception as id_lookup_err:
                    logger.debug(f"IdentityService lookup error for {identity_id}: {id_lookup_err}")
                    result["errors"].append(
                        f"Signature check error for '{identity_id}': "
                        f"IdentityService error: {id_lookup_err}"
                    )
                    all_signatures_valid = False
                    continue

            if anchor_pk is None:
                result["errors"].append(
                    f"No trusted anchor public key found in IdentityService for "
                    f"identity '{identity_id}' (No public key available in trust root; "
                    "unanchored embedded keys prohibited)."
                )
                all_signatures_valid = False
                continue

            raw_pk = entry.get("public_key")
            if raw_pk:
                try:
                    embedded_pk = None
                    if isinstance(raw_pk, str):
                        if "BEGIN PUBLIC KEY" in raw_pk:
                            embedded_pk = load_pem_public_key(raw_pk.encode("utf-8"))
                        else:
                            embedded_pk = Ed25519PublicKey.from_public_bytes(bytes.fromhex(raw_pk))
                    elif isinstance(raw_pk, bytes):
                        embedded_pk = Ed25519PublicKey.from_public_bytes(raw_pk)
                    if embedded_pk is not None:
                        anchor_bytes = anchor_pk.public_bytes(Encoding.Raw, PublicFormat.Raw)
                        embedded_bytes = embedded_pk.public_bytes(Encoding.Raw, PublicFormat.Raw)
                        if anchor_bytes != embedded_bytes:
                            result["errors"].append(
                                f"Signer key mismatch: embedded key for '{identity_id}' "
                                "does not match trusted IdentityService anchor."
                            )
                            all_signatures_valid = False
                            continue
                except Exception as pk_cmp_err:
                    logger.debug(f"Public key comparison error: {pk_cmp_err}")
                    result["errors"].append(
                        f"Signature check error for '{identity_id}': "
                        f"No public key available ({pk_cmp_err})"
                    )
                    all_signatures_valid = False
                    continue

            public_key = anchor_pk

            if not isinstance(public_key, Ed25519PublicKey):
                result["errors"].append(
                    f"Unsupported key type for signer '{identity_id}': {type(public_key).__name__}"
                )
                all_signatures_valid = False
                continue

            from agentv_runtime.signatures import resolve_policy

            policy = resolve_policy(identity_id, public_key)
            policy.authorize(CERTIFICATE, "ed25519-raw")
            if not policy.allow_legacy_raw:
                raise ValueError("Legacy raw Ed25519 is disabled by external trust policy")

            sig_bytes = bytes.fromhex(signature_hex)
            verified = False
            last_err = None
            for m_cand in candidate_manifest_bytes:
                try:
                    public_key.verify(sig_bytes, m_cand)
                    verified = True
                    break
                except Exception as ex:
                    last_err = ex

            if verified:
                sig_count += 1
                result["signer_identity"] = identity_id
                result["algorithm"] = algorithm
            else:
                result["errors"].append(
                    f"Ed25519 signature verification failed for '{identity_id}': {last_err}"
                )
                all_signatures_valid = False
        except Exception as sig_err:
            logger.debug("Signature check error for %s/%s: %s", run_id, identity_id, sig_err)
            result["errors"].append(f"Signature check error for '{identity_id}': {sig_err}")
            all_signatures_valid = False

    sig_verified = bool(
        all_signatures_valid and sig_count > 0 and len(provenance_chain) == sig_count
    )

    # 4. Check evidence_root_hash if present in certificate
    evidence_root_valid = True
    if not trace_only and cert_data.get("evidence_root_hash"):
        evidence_root_valid = False
        if trace_bytes:
            try:
                from agentv_runtime.evidence_graph import (
                    build_evidence_graph_from_events,
                    compute_evidence_graph_root,
                )

                ev_list = []
                trace_str = ""
                try:
                    trace_str = trace_bytes.decode("utf-8")
                except UnicodeDecodeError as uerr:
                    result["errors"].append(f"Trace file is not valid UTF-8: {uerr}")

                if trace_str:
                    has_line_error = False
                    ev_list_with_lines: list[tuple[dict[str, Any], str]] = []
                    for line_idx, line in enumerate(trace_str.splitlines(), start=1):
                        stripped = line.strip()
                        if stripped:
                            try:
                                parsed_ev = _json.loads(stripped)
                                ev_list.append(parsed_ev)
                                ev_list_with_lines.append((parsed_ev, stripped))
                            except (
                                json.JSONDecodeError,
                                UnicodeDecodeError,
                                ValueError,
                            ) as line_err:
                                has_line_error = True
                                result["errors"].append(
                                    f"Malformed trace record at line {line_idx}: {line_err}"
                                )
                                break

                    if not has_line_error and ev_list_with_lines:
                        req_oracles = (
                            cert_data.get("required_oracles")
                            or cert_data.get("required_oracle_ids")
                            or (cert_data.get("metadata", {}) or {}).get("required_oracle_ids")
                        )
                        ev_graph = build_evidence_graph_from_events(
                            ev_list_with_lines, required_oracle_ids=req_oracles
                        )
                        computed_ev_root = compute_evidence_graph_root(ev_graph)
                        expected_ev_root = cert_data["evidence_root_hash"]
                        if computed_ev_root != expected_ev_root and ev_list:
                            ev_graph_canon = build_evidence_graph_from_events(
                                ev_list, required_oracle_ids=req_oracles
                            )
                            computed_ev_root_canon = compute_evidence_graph_root(ev_graph_canon)
                            if computed_ev_root_canon == expected_ev_root:
                                ev_graph = ev_graph_canon
                                computed_ev_root = computed_ev_root_canon
                        if computed_ev_root != expected_ev_root and ev_list_with_lines:
                            filtered_evs = [
                                (ev, line)
                                for ev, line in ev_list_with_lines
                                if not (
                                    ev.get("event") == "evaluator_finalization"
                                    or (
                                        ev.get("event")
                                        in ("run_end", "verification_decision", "session_decision")
                                        and isinstance(
                                            ev.get("finalization")
                                            or (
                                                ev.get("data")
                                                if isinstance(ev.get("data"), dict)
                                                else {}
                                            ).get("finalization"),
                                            dict,
                                        )
                                    )
                                )
                            ]
                            ev_graph_filtered = build_evidence_graph_from_events(
                                filtered_evs, required_oracle_ids=req_oracles
                            )
                            computed_ev_root_filtered = compute_evidence_graph_root(
                                ev_graph_filtered
                            )
                            if computed_ev_root_filtered == expected_ev_root:
                                ev_graph = ev_graph_filtered
                                computed_ev_root = computed_ev_root_filtered
                        if computed_ev_root == expected_ev_root:
                            if ev_graph.get("is_complete_provenance") is False:
                                result["errors"].append(
                                    "Evidence graph contains unresolved or carrier fallback "
                                    "provenance"
                                )
                                evidence_root_valid = False
                            else:
                                evidence_root_valid = True
                        else:
                            result["errors"].append(
                                f"Evidence root hash mismatch: expected={expected_ev_root!r}, "
                                f"computed={computed_ev_root!r}"
                            )
            except Exception as ev_check_err:
                logger.debug(
                    "Evidence root check failed in verify_trace_certificate: %s",
                    ev_check_err,
                )
                result["errors"].append(f"Evidence root check failed: {ev_check_err}")
                evidence_root_valid = False

    if cert_data.get("verification_package"):
        vp = cert_data["verification_package"]
        vp_dict = vp if isinstance(vp, dict) else (vp.to_dict() if hasattr(vp, "to_dict") else {})
        if not vp_dict.get("signature"):
            result["errors"].append("Manifest verification_package is unsigned")
        else:
            pkg_res = VerificationAuthority.verify_package_signature_only(vp)
            if not pkg_res.get("verified"):
                result["errors"].extend(
                    pkg_res.get("failures") or ["Manifest verification_package signature invalid"]
                )

    # Enforce scenario hash binding requirement if scenario hash is present in certificate
    scenario_bound_valid = True
    scen_hash_binding = cert_data.get("scenario_hash") or (
        cert_data.get("metadata", {}).get("scenario_hash")
    )
    if scen_hash_binding:
        if scenario_data is None:
            scenario_data = cert_data.get("scenario_data") or cert_data.get("scenario")
        if scenario_data is None:
            scenario_bound_valid = False
            result["errors"].append(
                "Scenario binding verification required but scenario_data not provided."
            )
        elif not result.get("scenario_hash_match"):
            scenario_bound_valid = False
            result["errors"].append("Scenario hash mismatch against certificate binding.")
        else:
            scenario_bound_valid = True

    if (
        sig_verified
        and not result["errors"]
        and result["manifest_hash_match"]
        and scenario_bound_valid
        and evidence_root_valid
    ):
        result["verified"] = True

    return result


class VerificationAuthority:
    """
    Authoritative verification authority for AgentV evaluation runs and verification packages.
    Enforces that certification claims are strictly derived from full package validation.
    """

    @staticmethod
    def verify_package_signature_only(
        package: Any,
        public_key_pem: str | None = None,
        trust_root: Any | None = None,
        key_registry: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        Validates the detached cryptographic signature over the canonical package payload.
        Fast-path signature validation without requiring underlying evidence artifacts.
        Requires an external trust anchor (public_key_pem, trust_root, or key_registry).
        """
        from agentv_runtime.package import VerificationPackage

        if isinstance(package, dict):
            pkg = VerificationPackage.from_dict(package)
        else:
            pkg = package

        if not pkg.signature:
            return {
                "verified": False,
                "status": "UNSIGNED",
                "failures": ["UnsignedPackage: package signature is missing"],
                "package_id": pkg.package_id,
                "package_hash": pkg.compute_package_hash(),
            }

        sig_valid = pkg.verify_signature(
            public_key_pem=public_key_pem,
            trust_root=trust_root,
            key_registry=key_registry,
        )
        return {
            "verified": sig_valid,
            "status": "SIGNATURE_VALID" if sig_valid else "SIGNATURE_INVALID",
            "failures": []
            if sig_valid
            else [
                f"SignatureVerificationFailed: Signature for identity "
                f"'{pkg.signer_identity}' failed verification"
            ],
            "package_id": pkg.package_id,
            "package_hash": pkg.compute_package_hash(),
        }

    @staticmethod
    def verify_package_artifacts(
        package: Any,
        raw_trace_bytes: bytes,
        raw_trace_events: list[dict[str, Any]] | None = None,
        canonical_manifest: Any = None,
        scenario_data: Any | None = None,
        public_key_pem: str | None = None,
        trust_root: Any | None = None,
        key_registry: Mapping[str, str] | None = None,
        require_signature: bool = True,
    ) -> dict[str, Any]:
        """
        Diagnostic artifact-binding checks; certification requires verify_certification_artifact:
        1. Trace byte parity (recomputed SHA3-256 vs pkg.trace_hash)
        2. Manifest canonical hash binding (recomputed SHA3-256 vs pkg.manifest_hash)
        3. Evidence graph deterministic root reconstruction & direct provenance
        4. Trace seal integrity (cryptographic digest verification vs pkg.trace_hash)
        5. Scenario hash binding (mandatory scenario artifact presence, ID, version, and hash)
        6. Decision verdict conformance
        7. Required oracle inventory completeness and outcome reconciliation
        8. Cryptographic signature verification against external trust root
        """
        import hashlib

        from agentv_runtime.package import VerificationPackage

        if isinstance(package, dict):
            pkg = VerificationPackage.from_dict(package)
        else:
            pkg = package

        failures: list[str] = []

        # 1. Trace byte parity check and internal line-by-line parsing
        parsed_events_with_lines: list[tuple[dict[str, Any], str]] = []
        parsed_events: list[dict[str, Any]] = []

        if raw_trace_bytes is None:
            failures.append("TraceBytesMissing: artifact verification requires raw trace bytes")
        else:
            actual_trace_hash = hashlib.sha3_256(raw_trace_bytes).hexdigest()
            expected_hash = (
                pkg.trace_hash.split(":", 1)[1] if ":" in pkg.trace_hash else pkg.trace_hash
            )
            if actual_trace_hash.lower() != expected_hash.lower():
                failures.append(
                    f"TraceHashMismatch: package={pkg.trace_hash} actual={actual_trace_hash}"
                )

            try:
                decoded = raw_trace_bytes.decode("utf-8")
                for line in decoded.splitlines():
                    trimmed = line.strip()
                    if not trimmed:
                        continue
                    evt = json.loads(trimmed)
                    if not isinstance(evt, dict):
                        raise ValueError("Trace record must be a JSON object")
                    parsed_events.append(evt)
                    # Preserve all JSON whitespace from the recorded line; the
                    # evidence graph commits to raw JSONL, not a reserialization.
                    parsed_events_with_lines.append((evt, line.rstrip("\r\n")))
            except Exception as parse_err:
                failures.append(f"TraceStreamParsingFailed: {parse_err}")

        # Derive authoritative event stream from parsed raw trace bytes
        def _is_finalization_carrier(event: dict[str, Any]) -> bool:
            return bool(
                event.get("event") == "evaluator_finalization"
                or (
                    event.get("event") in ("run_end", "verification_decision", "session_decision")
                    and isinstance(
                        event.get("finalization")
                        or (
                            event.get("data", {}).get("finalization")
                            if isinstance(event.get("data"), dict)
                            else None
                        ),
                        dict,
                    )
                )
            )

        # Parse every raw line, then exclude only the terminal self-referential
        # finalization carrier from evidence-root reconstruction.
        effective_events_with_lines = [
            item for item in parsed_events_with_lines if not _is_finalization_carrier(item[0])
        ]
        effective_events = [evt for evt in parsed_events if not _is_finalization_carrier(evt)]

        # Raw JSONL is the only authoritative event source.  Caller events are
        # useful only as an anti-split-chain assertion and must never replace it.
        if raw_trace_events is not None:
            if parsed_events and len(raw_trace_events) != len(parsed_events):
                failures.append(
                    "TraceStreamSplitChainViolation: Caller-supplied event count "
                    f"({len(raw_trace_events)}) does not match byte-stream parsed "
                    f"event count ({len(parsed_events)})"
                )
            elif parsed_events and list(raw_trace_events) != parsed_events:
                failures.append(
                    "TraceStreamSplitChainViolation: caller-supplied events do not "
                    "exactly match the raw JSONL event stream"
                )
            elif not parsed_events:
                failures.append(
                    "TraceStreamSplitChainViolation: empty raw trace cannot be "
                    "supplemented by caller-supplied events"
                )

        # 2. Manifest canonical hash binding
        if canonical_manifest is None:
            failures.append("ManifestMissing: artifact verification requires canonical manifest")
        else:
            try:
                physical = False
                generic_vc_envelope = False
                source = None
                if hasattr(canonical_manifest, "compute_manifest_hash"):
                    physical = True
                    computed_m_hash = canonical_manifest.compute_manifest_hash()
                elif isinstance(canonical_manifest, dict):
                    from agentv_runtime.manifest import ExecutionManifest

                    # A VC envelope is not a physical ExecutionManifest.  Only
                    # a physical manifest is subject to the closed-schema parser;
                    # preserve legacy VC package binding through its declared
                    # execution-manifest projection.
                    physical = {"agent_config", "runtime_config", "environment"}.issubset(
                        canonical_manifest
                    )
                    generic_vc_envelope = not physical and "vc_version" in canonical_manifest
                    source = (
                        canonical_manifest
                        if physical
                        else {
                            key: canonical_manifest[key]
                            for key in {
                                f.name for f in __import__("dataclasses").fields(ExecutionManifest)
                            }
                            if key in canonical_manifest
                        }
                    )
                    computed_m_hash = ExecutionManifest.from_dict(source).compute_manifest_hash()
                elif isinstance(canonical_manifest, (bytes, str)):
                    c_bytes = (
                        canonical_manifest
                        if isinstance(canonical_manifest, bytes)
                        else canonical_manifest.encode("utf-8")
                    )
                    computed_m_hash = f"sha3_256:{hashlib.sha3_256(c_bytes).hexdigest()}"
                else:
                    computed_m_hash = ""

                exp_m_hash = pkg.manifest_hash
                if not (generic_vc_envelope and not exp_m_hash) and (
                    not exp_m_hash or computed_m_hash != exp_m_hash
                ):
                    failures.append(
                        f"ManifestHashMismatch: package={exp_m_hash} actual={computed_m_hash}"
                    )

                # Semantic cross-binding check between manifest and package (P0-4 Fix)
                m_obj = None
                if isinstance(canonical_manifest, dict):
                    try:
                        from agentv_runtime.manifest import ExecutionManifest

                        m_obj = ExecutionManifest.from_dict(source or canonical_manifest)
                    except Exception as exc:
                        logger.debug(
                            "Failed to instantiate ExecutionManifest from dict: %s",
                            exc,
                        )
                elif hasattr(canonical_manifest, "scenario_id"):
                    m_obj = canonical_manifest

                if m_obj is not None:
                    if (
                        m_obj.scenario_id
                        and pkg.scenario_id
                        and m_obj.scenario_id != pkg.scenario_id
                    ):
                        failures.append(
                            f"ManifestScenarioIdMismatch: manifest={m_obj.scenario_id} "
                            f"package={pkg.scenario_id}"
                        )
                    if (
                        m_obj.scenario_version
                        and pkg.scenario_version
                        and m_obj.scenario_version != pkg.scenario_version
                    ):
                        failures.append(
                            f"ManifestScenarioVersionMismatch: manifest={m_obj.scenario_version} "
                            f"package={pkg.scenario_version}"
                        )
                    if (
                        m_obj.scenario_hash
                        and pkg.scenario_hash
                        and m_obj.scenario_hash != pkg.scenario_hash
                    ):
                        failures.append(
                            f"ManifestScenarioHashMismatch: manifest={m_obj.scenario_hash} "
                            f"package={pkg.scenario_hash}"
                        )
                    if (
                        m_obj.manifest_id
                        and pkg.manifest_id
                        and m_obj.manifest_id != pkg.manifest_id
                    ):
                        failures.append(
                            f"ManifestIdMismatch: manifest={m_obj.manifest_id} "
                            f"package={pkg.manifest_id}"
                        )
            except Exception as m_err:
                failures.append(f"ManifestVerificationFailed: {m_err}")

        # 3. Evidence root binding & reconstruction from stream events
        if not pkg.evidence_root_hash:
            failures.append("EvidenceRootMissing: package missing evidence graph root")
        ev_graph: dict[str, Any] | None = None
        if not effective_events_with_lines:
            failures.append("TraceEventsMissing: artifact verification requires raw trace events")
        else:
            try:
                from agentv_runtime.evidence_graph import (
                    build_evidence_graph_from_events,
                    compute_evidence_graph_root,
                )

                ev_graph = build_evidence_graph_from_events(effective_events_with_lines)
                computed_root = compute_evidence_graph_root(ev_graph)
                if computed_root != pkg.evidence_root_hash:
                    failures.append(
                        f"EvidenceRootMismatch: package={pkg.evidence_root_hash} "
                        f"actual={computed_root}"
                    )
                if not ev_graph.get("is_complete_provenance", True):
                    failures.append(
                        "DirectProvenanceViolation: Evidence graph contains unresolved "
                        "or carrier fallback provenance"
                    )
            except Exception as ev_err:
                failures.append(f"EvidenceReconstructionFailed: {ev_err}")

        # 4. Trace seal integrity check
        if not pkg.trace_seal:
            failures.append("TraceSealMissing: package missing trace seal")
        else:
            seal_digest = (
                pkg.trace_seal.get("trace_digest")
                or pkg.trace_seal.get("digest")
                or pkg.trace_seal.get("trace_hash")
                or pkg.trace_seal.get("certificate_hash")
            )
            if not seal_digest or not isinstance(seal_digest, str):
                failures.append("TraceSealCorrupt: trace seal missing cryptographic digest")
            else:
                norm_seal_digest = (
                    seal_digest.split(":", 1)[1] if ":" in seal_digest else seal_digest
                )
                norm_trace_hash = (
                    pkg.trace_hash.split(":", 1)[1] if ":" in pkg.trace_hash else pkg.trace_hash
                )
                if norm_seal_digest.lower() != norm_trace_hash.lower():
                    failures.append(
                        f"TraceSealMismatch: trace seal digest '{seal_digest}' does not match "
                        f"trace hash '{pkg.trace_hash}'"
                    )

            if "event_count" in pkg.trace_seal:
                try:
                    exp_count = int(pkg.trace_seal["event_count"])
                    if len(effective_events) != exp_count:
                        failures.append(
                            f"TraceSealEventCountMismatch: seal declared {exp_count} events "
                            f"but actual trace contains {len(effective_events)} evidence events"
                        )
                except (ValueError, TypeError):
                    pass

        # 5. Scenario artifact binding check
        if scenario_data is None:
            if pkg.scenario_hash:
                failures.append(
                    "ScenarioArtifactMissing: package certification requires "
                    "bound scenario artifact"
                )
        else:
            try:
                from agentv_runtime.manifest import compute_scenario_hash

                computed_scen_hash = compute_scenario_hash(scenario_data)
                if not pkg.scenario_hash or computed_scen_hash != pkg.scenario_hash:
                    failures.append(
                        f"ScenarioHashMismatch: package={pkg.scenario_hash} "
                        f"actual={computed_scen_hash}"
                    )

                if not pkg.scenario_id or not pkg.scenario_version:
                    failures.append(
                        "ScenarioBindingIncomplete: package missing scenario ID or version"
                    )

                scen_meta = (
                    scenario_data.get("metadata")
                    if isinstance(scenario_data.get("metadata"), dict)
                    else {}
                )
                scen_id_in_data = str(
                    scenario_data.get("id")
                    or scenario_data.get("scenario_id")
                    or scen_meta.get("id")
                    or scen_meta.get("scenario_id")
                    or ""
                )
                if scen_id_in_data and pkg.scenario_id and scen_id_in_data != pkg.scenario_id:
                    failures.append(
                        f"ScenarioIdMismatch: package={pkg.scenario_id} actual={scen_id_in_data}"
                    )

                scen_ver_in_data = str(
                    scenario_data.get("version")
                    or scenario_data.get("scenario_version")
                    or scen_meta.get("version")
                    or scen_meta.get("scenario_version")
                    or ""
                )
                if (
                    scen_ver_in_data
                    and pkg.scenario_version
                    and scen_ver_in_data != pkg.scenario_version
                ):
                    failures.append(
                        f"ScenarioVersionMismatch: package={pkg.scenario_version} "
                        f"actual={scen_ver_in_data}"
                    )
            except Exception as s_err:
                failures.append(f"ScenarioVerificationFailed: {s_err}")

        # 6. Behavioral outcome is distinct from cryptographic evidence validity.
        # A complete signed FAIL is an attestable negative evaluation, not a
        # malformed package. Only explicit PASS claims require all mandatory
        # oracle outcomes to be PASS.
        decision_raw = (pkg.decision or {}).get("decision") or (pkg.decision or {}).get("verdict")
        decision_val = str(decision_raw or "").upper()
        if decision_val not in ("PASS", "VERIFIED", "FAIL", "ATTESTED_FAIL"):
            failures.append(f"UnverifiedDecision: decision was '{decision_raw}'")
        requires_oracle_pass = decision_val in ("PASS", "VERIFIED")

        # 7. Semantic reconciliation of packaged oracles against raw trace evidence
        raw_evidence_nodes = (
            ev_graph.get("nodes", []) if (ev_graph and isinstance(ev_graph, dict)) else []
        )
        if ev_graph is not None:
            raw_node_by_identity: dict[tuple, dict[str, Any]] = {}
            raw_nodes_by_oid: dict[str, list[dict[str, Any]]] = {}
            for rn in raw_evidence_nodes:
                oid = rn.get("oracle_id")
                if not oid:
                    continue
                raw_nodes_by_oid.setdefault(oid, []).append(rn)
                key = (
                    oid,
                    str(rn.get("execution_instance_id") or rn.get("instance_id") or ""),
                    rn.get("sequence") or rn.get("_seq"),
                    str(rn.get("source_hash") or rn.get("content_hash") or ""),
                )
                raw_node_by_identity[key] = rn

            for o in pkg.executed_oracle_results:
                if not isinstance(o, dict):
                    failures.append("MalformedOracleResult: expected an oracle result object")
                    continue
                o_id = str(o.get("oracle_id") or o.get("metric") or o.get("assertion") or "")
                if not o_id:
                    continue
                matching_raw = None
                key = (
                    o_id,
                    str(o.get("execution_instance_id") or o.get("instance_id") or ""),
                    o.get("sequence") or o.get("_seq"),
                    str(o.get("source_hash") or o.get("content_hash") or ""),
                )
                if key in raw_node_by_identity:
                    matching_raw = raw_node_by_identity[key]
                elif o_id in raw_nodes_by_oid:
                    candidates = raw_nodes_by_oid[o_id]
                    for cand in candidates:
                        cand_inst = str(
                            cand.get("execution_instance_id") or cand.get("instance_id") or ""
                        )
                        o_inst = str(o.get("execution_instance_id") or o.get("instance_id") or "")
                        cand_hash = str(cand.get("source_hash") or cand.get("content_hash") or "")
                        o_hash = str(o.get("source_hash") or o.get("content_hash") or "")
                        if (cand_inst and cand_inst == o_inst) or (
                            cand_hash and cand_hash == o_hash
                        ):
                            matching_raw = cand
                            break
                    if not matching_raw and len(candidates) == 1 and not o_hash:
                        matching_raw = candidates[0]

                if matching_raw:
                    raw_outcome = str(
                        matching_raw.get("outcome")
                        or ("PASS" if matching_raw.get("passed") is True else "FAIL")
                    ).upper()
                    pkg_outcome = str(
                        o.get("outcome") or ("PASS" if o.get("passed") is True else "FAIL")
                    ).upper()
                    if pkg_outcome != raw_outcome:
                        failures.append(
                            "PackagedEvidenceDivergence: packaged oracle "
                            f"'{o_id}' outcome '{pkg_outcome}' contradicts "
                            f"raw trace evidence node outcome '{raw_outcome}'"
                        )
                    pkg_passed = o.get("passed")
                    if pkg_passed is None and pkg_outcome in ("PASS", "FAIL"):
                        pkg_passed = pkg_outcome == "PASS"
                    raw_passed = matching_raw.get("passed")
                    if raw_passed is None and raw_outcome in ("PASS", "FAIL"):
                        raw_passed = raw_outcome == "PASS"
                    if (
                        pkg_passed is not None
                        and raw_passed is not None
                        and bool(pkg_passed) != bool(raw_passed)
                    ):
                        failures.append(
                            f"PackagedEvidenceDivergence: packaged oracle '{o_id}' "
                            "passed={o.get('passed')} contradicts "
                            f"raw trace evidence passed={matching_raw.get('passed')}"
                        )
                else:
                    failures.append(
                        f"UngroundedPackagedOracle: packaged oracle '{o_id}' has no "
                        "corresponding raw trace evidence node in recomputed evidence graph"
                    )

        seen_oracle_keys: set[tuple | str] = set()
        executed_oracles_by_id: dict[str, list[dict[str, Any]]] = {}
        for o in pkg.executed_oracle_results:
            if not isinstance(o, dict):
                failures.append("MalformedOracleResult: expected an oracle result object")
                continue
            o_id = str(o.get("oracle_id") or o.get("metric") or o.get("assertion") or "")
            if not o_id:
                continue
            inst_key = (
                o_id,
                str(o.get("execution_instance_id") or o.get("instance_id") or ""),
                o.get("attempt") or o.get("attempt_id") or 0,
                o.get("sequence") or o.get("_seq"),
                str(o.get("source_hash") or o.get("content_hash") or ""),
            )
            dedup_key: tuple | str = inst_key if any(inst_key[1:]) else o_id
            if dedup_key in seen_oracle_keys:
                failures.append(f"DuplicateOracleId: duplicate oracle evaluation for '{o_id}'")
            seen_oracle_keys.add(dedup_key)
            executed_oracles_by_id.setdefault(o_id, []).append(o)

        for req in pkg.required_oracle_ids:
            if not req:
                continue
            if req not in executed_oracles_by_id:
                failures.append(f"MissingRequiredOracles: required oracle '{req}' was not executed")
                continue

            for o_res in executed_oracles_by_id[req]:
                outcome = str(
                    o_res.get("outcome") or ("PASS" if o_res.get("passed") is True else "FAIL")
                ).upper()
                if outcome not in ("PASS", "FAIL"):
                    failures.append(
                        "RequiredOracleNotExecuted: required oracle "
                        f"'{req}' outcome is '{outcome}' "
                        "(only genuinely executed PASS/FAIL oracles satisfy completeness)"
                    )
                elif requires_oracle_pass and outcome != "PASS":
                    failures.append(
                        f"RequiredOracleFailed: required oracle '{req}' outcome is '{outcome}'"
                    )

                resolver = (
                    o_res.get("resolver") or o_res.get("evaluator") or o_res.get("metric_type")
                )
                if not resolver or not isinstance(resolver, str):
                    failures.append(
                        f"InvalidOracleResolver: required oracle '{req}' "
                        "missing resolver specification"
                    )

                ev_refs = o_res.get("evidence_refs")
                if ev_refs is not None and not isinstance(ev_refs, list):
                    failures.append(
                        f"InvalidOracleEvidenceRefs: required oracle '{req}' "
                        "evidence_refs must be a list"
                    )

        # 8. Signature verification against external trust root
        if pkg.signature:
            try:
                sig_valid = pkg.verify_signature(
                    public_key_pem=public_key_pem,
                    trust_root=trust_root,
                    key_registry=key_registry,
                )
                if not sig_valid:
                    failures.append(
                        f"SignatureVerificationFailed: Signature for identity "
                        f"'{pkg.signer_identity}' failed verification"
                    )
            except Exception as sig_err:
                failures.append(f"SignatureVerificationFailed: {sig_err}")
        elif require_signature:
            failures.append("UnsignedPackage: package signature is required")

        # 9. Sub-hash bindings: evaluation_hash, verification_hash, certificate_hash
        if pkg.evaluation_hash and parsed_events:
            fin_ev = next(
                (e for e in reversed(parsed_events) if e.get("event") == "evaluator_finalization"),
                None,
            )
            if fin_ev:
                fin_h = str(
                    fin_ev.get("finalization_hash")
                    or (fin_ev.get("data", {}) or {}).get("finalization_hash")
                    or ""
                )
                if fin_h and fin_h != pkg.evaluation_hash:
                    failures.append(
                        f"EvaluationHashMismatch: package={pkg.evaluation_hash} actual={fin_h}"
                    )

        if pkg.verification_hash:
            try:
                from agentv_runtime.canonical import canonical_json_encode

                exp_verif_payload = {
                    "decision": pkg.decision,
                    "evidence_root_hash": pkg.evidence_root_hash,
                    "executed_oracle_results": pkg.executed_oracle_results,
                    "required_oracle_ids": sorted(pkg.required_oracle_ids),
                }
                verif_bytes = canonical_json_encode(exp_verif_payload)
                actual_verif_hash = f"sha3_256:{hashlib.sha3_256(verif_bytes).hexdigest()}"
                if actual_verif_hash != pkg.verification_hash:
                    failures.append(
                        f"VerificationHashMismatch: package={pkg.verification_hash} "
                        f"actual={actual_verif_hash}"
                    )
            except Exception as vh_err:
                failures.append(f"VerificationHashError: {vh_err}")

        if pkg.certificate_hash and canonical_manifest is not None:
            try:
                from agentv_runtime.canonical import canonical_json_encode

                m_dict = None
                if isinstance(canonical_manifest, dict) and "compliance" in canonical_manifest:
                    m_dict = canonical_manifest
                elif hasattr(canonical_manifest, "to_dict"):
                    candidate = canonical_manifest.to_dict()
                    if isinstance(candidate, dict) and "compliance" in candidate:
                        m_dict = candidate

                if m_dict:
                    exp_cert_payload = {
                        "compliance": m_dict.get("compliance", {}),
                        "evidence_root_hash": m_dict.get(
                            "evidence_root_hash", pkg.evidence_root_hash
                        ),
                        "execution_mode": m_dict.get("execution_mode", "unknown"),
                        "run_id": m_dict.get("run_id", ""),
                        "timestamp": m_dict.get("timestamp", ""),
                        "trace_hash": m_dict.get("trace_hash", pkg.trace_hash),
                        "vc_version": m_dict.get("vc_version", "3.0.0"),
                    }
                    cert_bytes = canonical_json_encode(exp_cert_payload)
                    actual_cert_hash = f"sha3_256:{hashlib.sha3_256(cert_bytes).hexdigest()}"
                    if actual_cert_hash != pkg.certificate_hash:
                        failures.append(
                            f"CertificateHashMismatch: package={pkg.certificate_hash} "
                            f"actual={actual_cert_hash}"
                        )
            except Exception as ch_err:
                failures.append(f"CertificateHashError: {ch_err}")

        is_valid = len(failures) == 0
        pkg_status = "DIAGNOSTIC_VALID" if is_valid else "UNVERIFIED"

        return {
            "verified": is_valid,
            "authoritative": False,
            "certified": False,
            "verification_mode": "DIAGNOSTIC",
            "status": pkg_status,
            "failures": failures,
            "package_id": pkg.package_id,
            "scenario_id": pkg.scenario_id,
            "package_hash": pkg.compute_package_hash(),
        }

    @staticmethod
    def verify_package(
        package: Any,
        raw_trace_bytes: bytes | None = None,
        raw_trace_events: list[dict[str, Any]] | None = None,
        canonical_manifest: Any | None = None,
        scenario_data: Any | None = None,
        public_key_pem: str | None = None,
        trust_root: Any | None = None,
        key_registry: Mapping[str, str] | None = None,
        require_signature: bool = True,
        require_scenario_binding: bool = True,
    ) -> dict[str, Any]:
        """
        Validates the evidence package against supplied artifacts:
        - Trace SHA3-256 byte parity vs trace_hash
        - Manifest hash binding (recomputes canonical hash if canonical_manifest is provided)
        - Evidence graph root binding & direct provenance
        - Trace seal integrity vs trace hash
        - Mandatory scenario hash binding (for certified results)
        - Decision verdict conformance
        - Required oracle inventory completeness and PASS outcome
        - Cryptographic signature validation against external trust root
        """
        if require_signature:
            return VerificationAuthority.verify_certification_artifact(
                package,
                raw_trace_bytes=raw_trace_bytes,
                raw_trace_events=raw_trace_events,
                canonical_manifest=canonical_manifest,
                scenario_data=scenario_data,
                public_key_pem=public_key_pem,
                trust_root=trust_root,
                key_registry=key_registry,
                require_signature=True,
            )

        import hashlib

        from agentv_runtime.package import VerificationPackage

        if isinstance(package, dict):
            pkg = VerificationPackage.from_dict(package)
        else:
            pkg = package

        failures: list[str] = []

        # 1. Byte parity check and trace stream parsing if raw trace bytes supplied
        parsed_events_with_lines: list[tuple[dict[str, Any], str]] = []
        parsed_events: list[dict[str, Any]] = []

        if raw_trace_bytes is not None:
            actual_trace_hash = hashlib.sha3_256(raw_trace_bytes).hexdigest()
            expected_hash = (
                pkg.trace_hash.split(":", 1)[1] if ":" in pkg.trace_hash else pkg.trace_hash
            )
            if actual_trace_hash.lower() != expected_hash.lower():
                failures.append(
                    f"TraceHashMismatch: package={pkg.trace_hash} actual={actual_trace_hash}"
                )

            try:
                decoded = raw_trace_bytes.decode("utf-8")
                for line in decoded.splitlines():
                    trimmed = line.strip()
                    if not trimmed:
                        continue
                    evt = json.loads(trimmed)
                    if not isinstance(evt, dict):
                        raise ValueError("Trace record must be a JSON object")
                    parsed_events.append(evt)
                    parsed_events_with_lines.append((evt, trimmed))
            except Exception as parse_err:
                failures.append(f"TraceStreamParsingFailed: {parse_err}")
        elif require_signature:
            failures.append("TraceBytesMissing: artifact verification requires raw trace bytes")

        from agentv_runtime.canonical import canonical_json_dumps

        effective_events_with_lines = (
            parsed_events_with_lines
            if raw_trace_bytes is not None
            else (
                [
                    (e, canonical_json_dumps(e) if isinstance(e, dict) else str(e))
                    for e in (raw_trace_events or [])
                ]
                if raw_trace_events is not None
                else None
            )
        )
        effective_events = parsed_events if raw_trace_bytes is not None else raw_trace_events
        # The trace seal counts evidence events before the self-referential
        # finalization carrier, consistently with artifact verification.
        if effective_events_with_lines is not None:
            effective_events_with_lines = [
                (event, line)
                for event, line in effective_events_with_lines
                if not isinstance(event, dict)
                or not (
                    event.get("event") == "evaluator_finalization"
                    or event.get("event")
                    in ("run_end", "verification_decision", "session_decision")
                    and isinstance(
                        event.get("finalization")
                        or (event.get("data") if isinstance(event.get("data"), dict) else {}).get(
                            "finalization"
                        ),
                        dict,
                    )
                )
            ]
            effective_events = [event for event, _ in effective_events_with_lines]

        if raw_trace_events is not None and parsed_events:
            if len(raw_trace_events) != len(parsed_events):
                failures.append(
                    "TraceStreamSplitChainViolation: Caller-supplied event count "
                    f"({len(raw_trace_events)}) does not match byte-stream parsed "
                    f"event count ({len(parsed_events)})"
                )

        # 2. Manifest binding
        if canonical_manifest is not None:
            try:
                physical = False
                generic_vc_envelope = False
                source = None
                if hasattr(canonical_manifest, "compute_manifest_hash"):
                    physical = True
                    computed_m_hash = canonical_manifest.compute_manifest_hash()
                elif isinstance(canonical_manifest, dict):
                    from agentv_runtime.manifest import ExecutionManifest

                    physical = {"agent_config", "runtime_config", "environment"}.issubset(
                        canonical_manifest
                    )
                    generic_vc_envelope = not physical and "vc_version" in canonical_manifest
                    source = (
                        canonical_manifest
                        if physical
                        else {
                            key: canonical_manifest[key]
                            for key in {
                                f.name for f in __import__("dataclasses").fields(ExecutionManifest)
                            }
                            if key in canonical_manifest
                        }
                    )
                    computed_m_hash = ExecutionManifest.from_dict(source).compute_manifest_hash()
                elif isinstance(canonical_manifest, (bytes, str)):
                    c_bytes = (
                        canonical_manifest
                        if isinstance(canonical_manifest, bytes)
                        else canonical_manifest.encode("utf-8")
                    )
                    computed_m_hash = f"sha3_256:{hashlib.sha3_256(c_bytes).hexdigest()}"
                else:
                    computed_m_hash = ""

                exp_m_hash = pkg.manifest_hash
                if not (generic_vc_envelope and not exp_m_hash) and (
                    not exp_m_hash or computed_m_hash != exp_m_hash
                ):
                    failures.append(
                        f"ManifestHashMismatch: package={exp_m_hash} actual={computed_m_hash}"
                    )

                # Semantic cross-binding check between manifest and package (P0-4 Fix)
                m_obj = None
                if isinstance(canonical_manifest, dict):
                    try:
                        from agentv_runtime.manifest import ExecutionManifest

                        m_obj = ExecutionManifest.from_dict(source or canonical_manifest)
                    except Exception as exc:
                        logger.debug(
                            "Failed to instantiate ExecutionManifest from dict: %s",
                            exc,
                        )
                elif hasattr(canonical_manifest, "scenario_id"):
                    m_obj = canonical_manifest

                if m_obj is not None:
                    if (
                        m_obj.scenario_id
                        and pkg.scenario_id
                        and m_obj.scenario_id != pkg.scenario_id
                    ):
                        failures.append(
                            f"ManifestScenarioIdMismatch: manifest={m_obj.scenario_id} "
                            f"package={pkg.scenario_id}"
                        )
                    if (
                        m_obj.scenario_version
                        and pkg.scenario_version
                        and m_obj.scenario_version != pkg.scenario_version
                    ):
                        failures.append(
                            f"ManifestScenarioVersionMismatch: manifest={m_obj.scenario_version} "
                            f"package={pkg.scenario_version}"
                        )
                    if (
                        m_obj.scenario_hash
                        and pkg.scenario_hash
                        and m_obj.scenario_hash != pkg.scenario_hash
                    ):
                        failures.append(
                            f"ManifestScenarioHashMismatch: manifest={m_obj.scenario_hash} "
                            f"package={pkg.scenario_hash}"
                        )
                    if (
                        m_obj.manifest_id
                        and pkg.manifest_id
                        and m_obj.manifest_id != pkg.manifest_id
                    ):
                        failures.append(
                            f"ManifestIdMismatch: manifest={m_obj.manifest_id} "
                            f"package={pkg.manifest_id}"
                        )
            except Exception as m_err:
                failures.append(f"ManifestVerificationFailed: {m_err}")
        elif not pkg.manifest_hash or not pkg.manifest_id:
            failures.append("ManifestMissing: package does not bind a valid manifest hash")

        # 3. Evidence root binding
        if not pkg.evidence_root_hash:
            failures.append("EvidenceRootMissing: package missing evidence graph root")

        # 4. Evidence graph recalculation from raw events if provided
        if raw_trace_events is not None:
            try:
                from agentv_runtime.evidence_graph import (
                    build_evidence_graph_from_events,
                    compute_evidence_graph_root,
                )

                ev_source = (
                    effective_events_with_lines
                    if effective_events_with_lines is not None
                    else raw_trace_events
                )
                ev_graph = build_evidence_graph_from_events(ev_source)
                computed_root = compute_evidence_graph_root(ev_graph)
                if computed_root != pkg.evidence_root_hash and raw_trace_events:
                    ev_graph_canon = build_evidence_graph_from_events(raw_trace_events)
                    computed_root_canon = compute_evidence_graph_root(ev_graph_canon)
                    if computed_root_canon == pkg.evidence_root_hash:
                        ev_graph = ev_graph_canon
                        computed_root = computed_root_canon
                if computed_root != pkg.evidence_root_hash:
                    failures.append(
                        f"EvidenceRootMismatch: package={pkg.evidence_root_hash} "
                        f"actual={computed_root}"
                    )
                if require_signature and not ev_graph.get("is_complete_provenance", True):
                    failures.append(
                        "DirectProvenanceViolation: Evidence graph contains unresolved "
                        "or carrier fallback provenance"
                    )
            except Exception as ev_err:
                logger.debug("Evidence graph calculation failed: %s", ev_err)
                failures.append(f"EvidenceReconstructionFailed: {ev_err}")

        # 4b. Trace seal verification
        if pkg.trace_seal:
            seal_digest = (
                pkg.trace_seal.get("trace_digest")
                or pkg.trace_seal.get("digest")
                or pkg.trace_seal.get("trace_hash")
                or pkg.trace_seal.get("certificate_hash")
            )
            if not seal_digest or not isinstance(seal_digest, str):
                failures.append("TraceSealCorrupt: trace seal missing cryptographic digest")
            else:
                norm_seal_digest = (
                    seal_digest.split(":", 1)[1] if ":" in seal_digest else seal_digest
                )
                norm_trace_hash = (
                    pkg.trace_hash.split(":", 1)[1] if ":" in pkg.trace_hash else pkg.trace_hash
                )
                if norm_seal_digest.lower() != norm_trace_hash.lower():
                    failures.append(
                        f"TraceSealMismatch: trace seal digest '{seal_digest}' does not match "
                        f"trace hash '{pkg.trace_hash}'"
                    )

            if effective_events is not None and "event_count" in pkg.trace_seal:
                try:
                    exp_count = int(pkg.trace_seal["event_count"])
                    if len(effective_events) != exp_count:
                        failures.append(
                            f"TraceSealEventCountMismatch: seal declared {exp_count} events "
                            f"but actual trace contains {len(effective_events)} events"
                        )
                except (ValueError, TypeError):
                    pass

            # Trace seal trust binding verification
            seal_sig = pkg.trace_seal.get("signature")
            if seal_sig and isinstance(seal_sig, str):
                seal_envelope_to_verify = {
                    k: v for k, v in pkg.trace_seal.items() if k != "signature"
                }
                seal_signer_id = seal_envelope_to_verify.get(
                    "signer_identity"
                ) or seal_envelope_to_verify.get("key_id")
                if not seal_signer_id:
                    failures.append(
                        "TraceSealMissingIdentity: trace seal signature present but missing "
                        "signer_identity and key_id"
                    )
                else:
                    seal_pub_pem: str | None = None
                    if public_key_pem:
                        seal_pub_pem = public_key_pem
                    elif key_registry is not None:
                        seal_pub_pem = key_registry.get(str(seal_signer_id)) or (
                            key_registry.get(str(seal_envelope_to_verify.get("key_id")))
                            if seal_envelope_to_verify.get("key_id")
                            else None
                        )
                    elif trust_root is not None:
                        if hasattr(trust_root, "get_public_key"):
                            try:
                                pk = trust_root.get_public_key(str(seal_signer_id))
                                if pk:
                                    from cryptography.hazmat.primitives import serialization

                                    seal_pub_pem = pk.public_bytes(
                                        encoding=serialization.Encoding.PEM,
                                        format=serialization.PublicFormat.SubjectPublicKeyInfo,
                                    ).decode("utf-8")
                            except Exception:
                                seal_pub_pem = None
                        elif isinstance(trust_root, Mapping):
                            seal_pub_pem = trust_root.get(str(seal_signer_id)) or (
                                trust_root.get(str(seal_envelope_to_verify.get("key_id")))
                                if seal_envelope_to_verify.get("key_id")
                                else None
                            )
                        elif isinstance(trust_root, (str, Path)):
                            root_path = Path(trust_root)
                            cand = root_path / str(seal_signer_id) / "public_key.pem"
                            if cand.is_file():
                                seal_pub_pem = cand.read_text(encoding="utf-8")
                    else:
                        try:
                            from eval_runner.identity import IdentityService

                            pk = IdentityService.get_public_key(
                                str(seal_signer_id), auto_provision=False
                            )
                            if pk:
                                from cryptography.hazmat.primitives import serialization

                                seal_pub_pem = pk.public_bytes(
                                    encoding=serialization.Encoding.PEM,
                                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                                ).decode("utf-8")
                        except Exception:
                            seal_pub_pem = None

                    if not seal_pub_pem:
                        failures.append(
                            f"TraceSealUntrustedSigner: no external trust anchor found for "
                            f"trace seal signer '{seal_signer_id}'"
                        )
                    else:
                        try:
                            from cryptography.hazmat.primitives import serialization
                            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                                Ed25519PublicKey,
                            )

                            from agentv_runtime.canonical import canonical_json_encode

                            pub_obj = serialization.load_pem_public_key(
                                seal_pub_pem.encode("utf-8")
                            )
                            if isinstance(pub_obj, Ed25519PublicKey):
                                sig_bytes = bytes.fromhex(seal_sig)
                                canon_seal_bytes = canonical_json_encode(seal_envelope_to_verify)
                                pub_obj.verify(sig_bytes, canon_seal_bytes)
                            else:
                                failures.append(
                                    "TraceSealUnsupportedKeyType: expected Ed25519 for "
                                    f"signer '{seal_signer_id}'"
                                )
                        except Exception as seal_v_err:
                            failures.append(
                                f"TraceSealSignatureInvalid: signature verification failed for "
                                f"trace seal: {seal_v_err}"
                            )

        # 5. Scenario hash binding check
        if scenario_data is not None:
            try:
                from agentv_runtime.manifest import compute_scenario_hash

                computed_scen_hash = compute_scenario_hash(scenario_data)
                if computed_scen_hash != pkg.scenario_hash:
                    failures.append(
                        f"ScenarioHashMismatch: package={pkg.scenario_hash} "
                        f"actual={computed_scen_hash}"
                    )
                if not pkg.scenario_id or not pkg.scenario_version:
                    failures.append(
                        "ScenarioBindingIncomplete: package missing scenario ID or version"
                    )

                scen_meta = (
                    scenario_data.get("metadata")
                    if isinstance(scenario_data.get("metadata"), dict)
                    else {}
                )
                scen_id_in_data = str(
                    scenario_data.get("id")
                    or scenario_data.get("scenario_id")
                    or scen_meta.get("id")
                    or scen_meta.get("scenario_id")
                    or ""
                )
                if scen_id_in_data and pkg.scenario_id and scen_id_in_data != pkg.scenario_id:
                    failures.append(
                        f"ScenarioIdMismatch: package={pkg.scenario_id} actual={scen_id_in_data}"
                    )

                scen_ver_in_data = str(
                    scenario_data.get("version")
                    or scenario_data.get("scenario_version")
                    or scen_meta.get("version")
                    or scen_meta.get("scenario_version")
                    or ""
                )
                if (
                    scen_ver_in_data
                    and pkg.scenario_version
                    and scen_ver_in_data != pkg.scenario_version
                ):
                    failures.append(
                        f"ScenarioVersionMismatch: package={pkg.scenario_version} "
                        f"actual={scen_ver_in_data}"
                    )
            except Exception as s_err:
                failures.append(f"ScenarioVerificationFailed: {s_err}")
        elif require_scenario_binding:
            failures.append(
                "ScenarioArtifactMissing: package certification requires bound scenario artifact"
            )

        # 6. A signed FAIL is a valid negative attestation.  Only a positive
        # certification claim requires PASS outcomes for mandatory oracles.
        decision_raw = (pkg.decision or {}).get("decision") or (pkg.decision or {}).get("verdict")
        decision_val = str(decision_raw or "").upper()
        if decision_val not in ("PASS", "VERIFIED", "FAIL", "ATTESTED_FAIL"):
            failures.append(f"UnverifiedDecision: decision was '{decision_raw}'")
        requires_oracle_pass = decision_val in ("PASS", "VERIFIED")

        # 7. Required oracle inventory & outcome check
        seen_oracle_keys: set[tuple | str] = set()
        executed_oracles_by_id: dict[str, list[dict[str, Any]]] = {}
        for o in pkg.executed_oracle_results:
            if not isinstance(o, dict):
                failures.append("MalformedOracleResult: expected an oracle result object")
                continue
            o_id = str(o.get("oracle_id") or o.get("metric") or o.get("assertion") or "")
            if not o_id:
                continue
            inst_key = (
                o_id,
                str(o.get("execution_instance_id") or o.get("instance_id") or ""),
                o.get("attempt") or o.get("attempt_id") or 0,
                o.get("sequence") or o.get("_seq"),
                str(o.get("source_hash") or o.get("content_hash") or ""),
            )
            dedup_key: tuple | str = inst_key if any(inst_key[1:]) else o_id
            if dedup_key in seen_oracle_keys:
                failures.append(f"DuplicateOracleId: duplicate oracle evaluation for '{o_id}'")
            seen_oracle_keys.add(dedup_key)
            executed_oracles_by_id.setdefault(o_id, []).append(o)

        for req in pkg.required_oracle_ids:
            if not req:
                continue
            if req not in executed_oracles_by_id:
                failures.append(f"MissingRequiredOracles: required oracle '{req}' was not executed")
                continue

            for o_res in executed_oracles_by_id[req]:
                outcome = str(
                    o_res.get("outcome") or ("PASS" if o_res.get("passed") is True else "FAIL")
                ).upper()
                if outcome not in ("PASS", "FAIL"):
                    failures.append(
                        "RequiredOracleNotExecuted: required oracle "
                        f"'{req}' outcome is '{outcome}' "
                        "(only genuinely executed PASS/FAIL oracles satisfy completeness)"
                    )
                elif requires_oracle_pass and outcome != "PASS":
                    failures.append(
                        f"RequiredOracleFailed: required oracle '{req}' outcome is '{outcome}'"
                    )

                resolver = (
                    o_res.get("resolver") or o_res.get("evaluator") or o_res.get("metric_type")
                )
                if not resolver or not isinstance(resolver, str):
                    failures.append(
                        f"InvalidOracleResolver: required oracle '{req}' "
                        "missing resolver specification"
                    )

                ev_refs = o_res.get("evidence_refs")
                if ev_refs is not None and not isinstance(ev_refs, list):
                    failures.append(
                        f"InvalidOracleEvidenceRefs: required oracle '{req}' "
                        "evidence_refs must be a list"
                    )

        # 8. Signature verification against external trust root
        if pkg.signature:
            try:
                sig_valid = pkg.verify_signature(
                    public_key_pem=public_key_pem,
                    trust_root=trust_root,
                    key_registry=key_registry,
                )
                if not sig_valid:
                    failures.append(
                        f"SignatureVerificationFailed: Signature for identity "
                        f"'{pkg.signer_identity}' failed verification"
                    )
            except Exception as sig_err:
                failures.append(f"SignatureVerificationFailed: {sig_err}")
        elif require_signature:
            failures.append("UnsignedPackage: package signature is required")

        # 9. Sub-hash bindings: evaluation_hash, verification_hash, certificate_hash
        finalization_events = parsed_events if raw_trace_bytes is not None else raw_trace_events
        if pkg.evaluation_hash and finalization_events is not None:
            fin_ev = next(
                (
                    e
                    for e in reversed(finalization_events)
                    if e.get("event") == "evaluator_finalization"
                ),
                None,
            )
            if fin_ev:
                fin_h = str(
                    fin_ev.get("finalization_hash")
                    or (fin_ev.get("data", {}) or {}).get("finalization_hash")
                    or ""
                )
                if fin_h and fin_h != pkg.evaluation_hash:
                    failures.append(
                        f"EvaluationHashMismatch: package={pkg.evaluation_hash} actual={fin_h}"
                    )

        if pkg.verification_hash:
            try:
                from agentv_runtime.canonical import canonical_json_encode

                exp_verif_payload = {
                    "decision": pkg.decision,
                    "evidence_root_hash": pkg.evidence_root_hash,
                    "executed_oracle_results": pkg.executed_oracle_results,
                    "required_oracle_ids": sorted(pkg.required_oracle_ids),
                }
                verif_bytes = canonical_json_encode(exp_verif_payload)
                actual_verif_hash = f"sha3_256:{hashlib.sha3_256(verif_bytes).hexdigest()}"
                if actual_verif_hash != pkg.verification_hash:
                    failures.append(
                        f"VerificationHashMismatch: package={pkg.verification_hash} "
                        f"actual={actual_verif_hash}"
                    )
            except Exception as vh_err:
                failures.append(f"VerificationHashError: {vh_err}")

        if pkg.certificate_hash and canonical_manifest is not None:
            try:
                from agentv_runtime.canonical import canonical_json_encode

                m_dict = (
                    canonical_manifest
                    if isinstance(canonical_manifest, dict)
                    else (
                        canonical_manifest.to_dict()
                        if hasattr(canonical_manifest, "to_dict")
                        else {}
                    )
                )
                if isinstance(m_dict, dict) and "compliance" in m_dict:
                    exp_cert_payload = {
                        "compliance": m_dict.get("compliance", {}),
                        "evidence_root_hash": m_dict.get(
                            "evidence_root_hash", pkg.evidence_root_hash
                        ),
                        "execution_mode": m_dict.get("execution_mode", "unknown"),
                        "run_id": m_dict.get("run_id", ""),
                        "timestamp": m_dict.get("timestamp", ""),
                        "trace_hash": m_dict.get("trace_hash", pkg.trace_hash),
                        "vc_version": m_dict.get("vc_version", "3.0.0"),
                    }
                    cert_bytes = canonical_json_encode(exp_cert_payload)
                    actual_cert_hash = f"sha3_256:{hashlib.sha3_256(cert_bytes).hexdigest()}"
                    if actual_cert_hash != pkg.certificate_hash:
                        failures.append(
                            f"CertificateHashMismatch: package={pkg.certificate_hash} "
                            f"actual={actual_cert_hash}"
                        )
            except Exception as ch_err:
                failures.append(f"CertificateHashError: {ch_err}")

        is_valid = len(failures) == 0
        pkg_status = "DIAGNOSTIC_VALID" if is_valid else "UNVERIFIED"

        return {
            "verified": is_valid,
            "authoritative": False,
            "certified": False,
            "verification_mode": "DIAGNOSTIC",
            "status": pkg_status,
            "failures": failures,
            "package_id": pkg.package_id,
            "scenario_id": pkg.scenario_id,
            "package_hash": pkg.compute_package_hash(),
        }

    @classmethod
    def verify_certification_artifact(
        cls,
        package: Any,
        raw_trace_bytes: bytes,
        raw_trace_events: list[dict[str, Any]] | None = None,
        canonical_manifest: Any = None,
        scenario_data: Any | None = None,
        public_key_pem: str | None = None,
        trust_root: Any | None = None,
        key_registry: Mapping[str, str] | None = None,
        require_signature: bool = True,
    ) -> dict[str, Any]:
        """
        Industrial-grade authoritative verification authority for AgentV evaluation
        runs and certification artifacts.
        Enforces the complete end-to-end verification contract:
        1. EvaluatorFinalizationRecord present in trace with valid cryptographic signature
        2. Execution mode is authoritative ('live' or 'hybrid') and not provisional/simulated
        3. Raw trace byte parity (SHA3-256 vs pkg.trace_hash)
        4. Canonical manifest hash binding & semantic cross-bindings
        5. Evidence graph deterministic root reconstruction & direct provenance
        6. Trace seal integrity & event count
        7. Scenario hash binding against canonical scenario definition
        8. Decision verdict conformance (PASS / VERIFIED)
        9. Required oracle inventory completeness and PASS outcomes
        10. Verification package cryptographic signature against trust root
        11. Sub-hash bindings (evaluation_hash, verification_hash, certificate_hash)
        """
        from agentv_runtime.package import VerificationPackage

        if isinstance(package, dict):
            pkg = VerificationPackage.from_dict(package)
        else:
            pkg = package

        failures: list[str] = []
        profile_supported = (pkg.metadata or {}).get("certificate_profile") == (
            f"agentv.certification.v{VC_V3_SCHEMA_VERSION}"
        )
        if require_signature and not profile_supported:
            failures.append(
                "UnsupportedCertificateProfile: legacy packages require diagnostic verification"
            )
        if require_signature and not isinstance((pkg.metadata or {}).get("provisional"), bool):
            failures.append("ProvisionalDesignationMissing: signed boolean designation is required")
        if not (
            hasattr(canonical_manifest, "compute_manifest_hash")
            or isinstance(canonical_manifest, dict)
            and {"agent_config", "runtime_config", "environment"}.issubset(canonical_manifest)
        ):
            failures.append("ExecutionManifestMissing: actual execution manifest is required")
        if not pkg.manifest_id or not pkg.manifest_hash:
            failures.append(
                "ExecutionManifestBindingMissing: manifest identity and hash are required"
            )
        if scenario_data is None:
            failures.append("ScenarioArtifactMissing: authoritative verification requires scenario")

        # Parse trace events from raw_trace_bytes
        parsed_events: list[dict[str, Any]] = []
        if raw_trace_bytes is None:
            failures.append(
                "TraceBytesMissing: certification verification requires raw trace bytes"
            )
        else:
            try:
                decoded = raw_trace_bytes.decode("utf-8")
                for line in decoded.splitlines():
                    trimmed = line.strip()
                    if trimmed:
                        event = json.loads(trimmed)
                        if not isinstance(event, dict):
                            raise ValueError("Trace record must be a JSON object")
                        parsed_events.append(event)
            except Exception as parse_err:
                failures.append(f"TraceStreamParsingFailed: {parse_err}")

        # Never substitute caller-supplied events for the recorded raw JSONL.
        if raw_trace_events is not None and not parsed_events:
            failures.append(
                "TraceStreamSplitChainViolation: empty raw trace cannot be "
                "supplemented by caller-supplied events"
            )
        effective_events = parsed_events

        finalization_carriers = [
            event
            for event in effective_events
            if event.get("event") == "evaluator_finalization"
            or event.get("event") in {"run_end", "end"}
            and isinstance(
                event.get("finalization")
                or (event.get("data") if isinstance(event.get("data"), dict) else {}).get(
                    "finalization"
                ),
                dict,
            )
        ]
        if len(finalization_carriers) > 1:
            failures.append(
                "DuplicateEvaluatorFinalization: exactly one authoritative finalization is required"
            )
        # 1. Authoritative EvaluatorFinalizationRecord validation
        fin_record: Any | None = None
        for ev in reversed(effective_events):
            if ev.get("event") == "evaluator_finalization":
                fin_data = ev.get("data") or ev
                try:
                    from agentv_runtime.finalization import EvaluatorFinalizationRecord

                    fin_record = EvaluatorFinalizationRecord.from_dict(
                        fin_data, require_authoritative=True
                    )
                    break
                except Exception as fin_err:
                    failures.append(f"AuthoritativeEvaluatorRecordInvalid: {fin_err}")
            elif ev.get("event") in ("run_end", "end"):
                ev_data = ev.get("data") if isinstance(ev.get("data"), dict) else ev
                candidate = None
                if isinstance(ev_data.get("finalization"), dict):
                    candidate = ev_data["finalization"]
                elif isinstance(ev.get("finalization"), dict):
                    candidate = ev.get("finalization")
                if candidate:
                    try:
                        from agentv_runtime.finalization import EvaluatorFinalizationRecord

                        fin_record = EvaluatorFinalizationRecord.from_dict(
                            candidate, require_authoritative=True
                        )
                        break
                    except Exception as fin_err:
                        failures.append(f"AuthoritativeEvaluatorRecordInvalid: {fin_err}")

        if fin_record is None:
            if not any("AuthoritativeEvaluatorRecordInvalid" in f for f in failures):
                failures.append(
                    "MissingEvaluatorFinalization: trace missing mandatory authoritative "
                    "EvaluatorFinalizationRecord"
                )
        else:
            # Cryptographic signature validation of EvaluatorFinalizationRecord
            eval_pub = None
            if public_key_pem:
                eval_pub = public_key_pem
            elif key_registry and fin_record.evaluator_identity in key_registry:
                eval_pub = key_registry[fin_record.evaluator_identity]
            else:
                from eval_runner.identity import IdentityService

                eval_pub = IdentityService.get_public_key(
                    fin_record.evaluator_identity, auto_provision=False
                )

            if eval_pub is None:
                failures.append(
                    f"EvaluatorKeyMissing: no public key found for evaluator identity "
                    f"'{fin_record.evaluator_identity}' (auto-provisioning disabled)"
                )
            else:
                try:
                    if not fin_record.verify_authoritative(
                        public_key=eval_pub, trust_root=trust_root
                    ):
                        failures.append(
                            f"EvaluatorSignatureVerificationFailed: signature for "
                            f"'{fin_record.evaluator_identity}' failed verification"
                        )
                except Exception as esig_err:
                    failures.append(f"EvaluatorSignatureVerificationFailed: {esig_err}")

            # Cross-field consistency with execution manifest and package
            man_run_id = (
                canonical_manifest.get("run_id") if isinstance(canonical_manifest, dict) else None
            )
            exp_run_id = (
                (pkg.execution_identity or {}).get("run_id")
                or man_run_id
                or (pkg.package_id[4:] if pkg.package_id.startswith("pkg_") else pkg.package_id)
            )
            if exp_run_id and fin_record.run_id != exp_run_id:
                failures.append(
                    f"RunIdMismatch: EvaluatorFinalizationRecord run_id "
                    f"'{fin_record.run_id}' != expected '{exp_run_id}'"
                )
            if pkg.evidence_root_hash and fin_record.evidence_root_hash != pkg.evidence_root_hash:
                failures.append(
                    f"EvidenceRootMismatch: EvaluatorFinalizationRecord evidence_root_hash "
                    f"'{fin_record.evidence_root_hash}' != package '{pkg.evidence_root_hash}'"
                )
            if pkg.scenario_hash and fin_record.scenario_hash != pkg.scenario_hash:
                failures.append(
                    f"ScenarioHashMismatch: EvaluatorFinalizationRecord scenario_hash "
                    f"'{fin_record.scenario_hash}' != package '{pkg.scenario_hash}'"
                )
            if pkg.manifest_hash and fin_record.execution_manifest_hash != pkg.manifest_hash:
                failures.append(
                    f"ManifestHashMismatch: EvaluatorFinalizationRecord execution_manifest_hash "
                    f"'{fin_record.execution_manifest_hash}' != package '{pkg.manifest_hash}'"
                )
            if pkg.finalization_hash != fin_record.finalization_hash:
                failures.append(
                    f"FinalizationHashMismatch: package={pkg.finalization_hash} "
                    f"evaluator={fin_record.finalization_hash}"
                )
            if pkg.evaluation_hash != fin_record.finalization_hash:
                failures.append(
                    f"EvaluationHashMismatch: package={pkg.evaluation_hash} "
                    f"evaluator={fin_record.finalization_hash}"
                )
            # Requiredness is part of the signed evaluation contract, not a
            # caller-selected subset of otherwise valid oracle results.
            execution_data = (
                canonical_manifest.to_dict()
                if hasattr(canonical_manifest, "to_dict")
                else canonical_manifest
                if isinstance(canonical_manifest, dict)
                else {}
            )
            manifest_reqs = set(
                (execution_data.get("metadata") or {}).get("required_oracle_ids") or []
            )
            fin_reqs = set(fin_record.required_oracle_ids)
            pkg_reqs = set(pkg.required_oracle_ids)
            if manifest_reqs != fin_reqs or pkg_reqs != fin_reqs:
                failures.append(
                    "RequiredOracleInventoryMismatch: manifest, finalization and package differ"
                )
            if isinstance(scenario_data, Mapping):
                scenario_metadata = scenario_data.get("metadata") or {}
                explicit_reqs = (
                    scenario_data.get("required_oracle_ids")
                    or scenario_data.get("required_oracles")
                    or scenario_metadata.get("required_oracle_ids")
                    or scenario_metadata.get("required_oracles")
                )
                if explicit_reqs is None:
                    from eval_runner.runner import compile_required_oracle_ids

                    explicit_reqs = compile_required_oracle_ids(scenario_data)
                if set(explicit_reqs) != fin_reqs:
                    failures.append(
                        "RequiredOracleInventoryMismatch: scenario and finalization differ"
                    )
            # The signed terminal sequence is the trace boundary immediately
            # before the event carrying finalization, never an attempt count.
            finalization_event_index = next(
                (
                    idx
                    for idx, event in enumerate(parsed_events)
                    if (
                        event.get("event") == "evaluator_finalization"
                        and (
                            (
                                isinstance(event.get("data"), dict)
                                and event["data"].get("finalization_hash")
                                == fin_record.finalization_hash
                            )
                            or event.get("finalization_hash") == fin_record.finalization_hash
                        )
                    )
                    or (
                        (
                            isinstance(event.get("finalization"), dict)
                            and event["finalization"].get("finalization_hash")
                            == fin_record.finalization_hash
                        )
                        or (
                            isinstance(event.get("data"), dict)
                            and isinstance(event["data"].get("finalization"), dict)
                            and event["data"]["finalization"].get("finalization_hash")
                            == fin_record.finalization_hash
                        )
                    )
                ),
                None,
            )
            if finalization_event_index is None:
                failures.append("FinalizationTraceCarrierMissing")
            else:
                prior_sequences = [
                    event.get("_seq")
                    for event in parsed_events[:finalization_event_index]
                    if isinstance(event.get("_seq"), int)
                ]
                if prior_sequences:
                    if fin_record.terminal_seq not in (prior_sequences[-1], 0):
                        failures.append(
                            "TerminalSequenceMismatch: finalization terminal_seq="
                            f"{fin_record.terminal_seq} trace={prior_sequences[-1]}"
                        )
                elif fin_record.terminal_seq not in (
                    0,
                    1,
                    len(parsed_events[:finalization_event_index]),
                ):
                    failures.append("TerminalTraceSequenceMissing")
            package_decision = str((pkg.decision or {}).get("decision") or "").lower()
            expected_decision = "pass" if fin_record.outcome == "pass" else "fail"
            if package_decision != expected_decision:
                failures.append(
                    f"DecisionMismatch: package={package_decision or 'missing'} "
                    f"evaluator={expected_decision}"
                )
            package_score = (pkg.decision or {}).get("score")
            if (
                not isinstance(package_score, (int, float))
                or isinstance(package_score, bool)
                or float(package_score) != float(fin_record.score)
            ):
                failures.append(
                    f"ScoreMismatch: package={package_score!r} evaluator={fin_record.score!r}"
                )

        # 2. Execution Mode Enforcement (Fail-closed on simulated/provisional)
        man_mode = (
            canonical_manifest.get("execution_mode")
            if isinstance(canonical_manifest, dict)
            else None
        )
        exec_mode = (
            ((pkg.execution_identity or {}).get("execution_mode") or man_mode or "").lower().strip()
        )

        runtime_config = (
            canonical_manifest.get("runtime_config", {})
            if isinstance(canonical_manifest, Mapping)
            else getattr(canonical_manifest, "runtime_config", {})
        )
        truth_contexts = [
            ("execution_manifest", canonical_manifest),
            ("runtime_config", runtime_config),
        ]
        for event in effective_events:
            if event.get("event") not in {"run_start", "start"}:
                continue
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            truth_contexts.extend(
                [
                    ("run_start", event),
                    ("run_start.data", data),
                    ("run_start.metadata", event.get("metadata")),
                    ("run_start.data.metadata", data.get("metadata")),
                ]
            )
        recorded_provisional = False
        trace_mode_present = False
        for origin, truth in truth_contexts:
            if not isinstance(truth, Mapping):
                continue
            recorded_mode = truth.get("execution_mode")
            if origin.startswith("run_start") and recorded_mode is not None:
                trace_mode_present = trace_mode_present or bool(str(recorded_mode).strip())
            if recorded_mode is not None and str(recorded_mode).lower().strip() != exec_mode:
                failures.append(
                    f"ExecutionModeMismatch: {origin}={recorded_mode!r} package={exec_mode!r}"
                )
            recorded_provisional = recorded_provisional or bool(truth.get("provisional"))
        if not trace_mode_present:
            failures.append(
                "ExecutionModeMissing: raw trace must declare execution mode in run_start"
            )

        if exec_mode not in ("live", "hybrid"):
            failures.append(
                f"UncertifiedExecutionMode: authoritative certification requires "
                f"'live' or 'hybrid' execution mode, got '{exec_mode or 'undeclared'}'"
            )

        man_provisional = (
            canonical_manifest.get("provisional") if isinstance(canonical_manifest, dict) else False
        )
        is_provisional = bool(
            recorded_provisional
            or man_provisional
            or (pkg.metadata or {}).get("provisional") is True
        )
        if is_provisional:
            failures.append(
                "ProvisionalExecutionCertificationProhibited: provisional runs cannot be certified"
            )

        # 3. Complete underlying artifact validation
        pkg_art_res = cls.verify_package_artifacts(
            package=pkg,
            raw_trace_bytes=raw_trace_bytes,
            raw_trace_events=raw_trace_events,
            canonical_manifest=canonical_manifest,
            scenario_data=scenario_data,
            public_key_pem=public_key_pem,
            trust_root=trust_root,
            key_registry=key_registry,
            require_signature=require_signature,
        )
        for f in pkg_art_res.get("failures", []):
            if f not in failures:
                failures.append(f)

        is_valid = len(failures) == 0
        passed = str((pkg.decision or {}).get("decision") or "").lower() == "pass"
        status = (
            "UNVERIFIED"
            if not is_valid
            else "DIAGNOSTIC_VALID"
            if not require_signature
            else "CERTIFIED"
            if passed
            else "ATTESTED_FAIL"
        )
        return {
            "verified": is_valid,
            "certified": bool(is_valid and require_signature and passed),
            "authoritative": bool(require_signature and profile_supported),
            "status": status,
            "failures": failures,
            "package_id": pkg.package_id,
            "scenario_id": pkg.scenario_id,
            "package_hash": pkg.compute_package_hash(),
        }


TraceVerifier.verify_package = VerificationAuthority.verify_package
TraceVerifier.verify_package_artifacts = VerificationAuthority.verify_package_artifacts
TraceVerifier.verify_package_signature_only = VerificationAuthority.verify_package_signature_only
TraceVerifier.verify_certification_artifact = VerificationAuthority.verify_certification_artifact
