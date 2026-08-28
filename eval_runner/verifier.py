import json
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from agentv_runtime.versions import VC_SCHEMA_VERSION as VC_V3_SCHEMA_VERSION

from . import config, forensics, utils
from .interfaces.artifact import ArtifactStore
from .interfaces.signing import SigningBackend
from .reference.local_artifact import LocalFileArtifactStore
from .reference.signing import LocalEd25519SigningBackend
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
    def verify(self, trace_path: Path, **kwargs) -> VerificationResult:
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

            from eval_runner.reference.signing import LocalEd25519SigningBackend

            private_key = IdentityService.get_private_key(identity_id)
            # Standard: Sign the manifest content (excluding transient fields like provenance_chain)
            manifest_to_sign = manifest.copy()
            manifest_to_sign.pop("provenance_chain", None)
            manifest_to_sign.pop("signing_context", None)
            manifest_bytes = json.dumps(manifest_to_sign, sort_keys=True).encode("utf-8")

            if hasattr(private_key, "private_bytes") and callable(private_key.private_bytes):
                try:
                    priv_pem = private_key.private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.PKCS8,
                        encryption_algorithm=serialization.NoEncryption(),
                    )
                    backend = LocalEd25519SigningBackend()
                    signature = backend.sign_payload(manifest_bytes, priv_pem)
                except Exception:
                    sig_raw = private_key.sign(manifest_bytes)
                    signature = sig_raw.hex() if isinstance(sig_raw, bytes) else str(sig_raw)
            elif hasattr(private_key, "sign"):
                sig_raw = private_key.sign(manifest_bytes)
                signature = sig_raw.hex() if isinstance(sig_raw, bytes) else str(sig_raw)
            else:
                raise CertificationFailedError(
                    f"Identity '{identity_id}' exposes no usable signing capability "
                    "(fail-closed: degenerate placeholder signatures are prohibited)"
                )

            manifest["provenance_chain"].append(
                {
                    "identity": identity_id,
                    "role": "Evaluator",
                    "timestamp": timestamp,
                    "signature": signature,
                    "algorithm": "ED25519",
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
            logger.warning(f"Could not cryptographically sign trace as '{identity_id}': {e}")
            if config.PQC_STRICT_MODE and "PQC_STRICT_MODE Violation" in str(e):
                raise

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
        backend = signing_backend or LocalEd25519SigningBackend()
        return backend.sign_payload(payload, private_key_path)

    @classmethod
    def sign_trace(
        cls,
        trace_path: str,
        identity_id: str = "system_id",
        compliance_status: str = "pass",
        compliance_score: float = 1.0,
        policy_ref: str | None = None,
        ttl_days: int | None = None,
        metadata: dict[str, Any] | None = None,
        behavioral_fingerprint_id: str | None = None,
        run_id: str | None = None,
        artifact_store: ArtifactStore | None = None,
        evidence_root_hash: str | None = None,
        execution_mode: str | None = None,
        provisional: bool = False,
        rubrics: dict[str, Any] | None = None,
        consensus: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Signs a trace file and issues a standardized Verification Certificate (VC) v3
        via the transactional certification pipeline (AgentV v2.0.0):

            freeze -> canonicalize -> hash -> sign -> persist -> verify -> seal -> publish

        Any stage failure rolls back partial mutations and raises
        CertificationFailedError (outcome CERTIFICATION_FAILED). No certificate is
        ever returned from an incomplete sealing operation.

        ``execution_mode`` is stamped into every certificate so an
        auditor can distinguish simulated from live/replay-verified evidence.
        ``provisional=True`` marks certificates produced without an explicit
        operator-declared mode (silent SIMULATED default) — such certificates
        are non-authoritative for compliance purposes.
        """
        stages: list[dict[str, Any]] = []

        def _stage(name: str):
            def _wrap(fn: Callable[[], Any]) -> Any:
                entry = {"stage": name, "status": "running", "ts": datetime.now().isoformat()}
                stages.append(entry)
                try:
                    result = fn()
                    entry["status"] = "ok"
                    return result
                except CertificationFailedError:
                    entry["status"] = "failed"
                    raise
                except Exception as exc:
                    entry["status"] = "failed"
                    entry["error"] = f"{type(exc).__name__}: {exc}"
                    logger.error(f"      [Verifier] Stage '{name}' FAILED: {exc}")
                    raise CertificationFailedError(
                        f"CERTIFICATION_FAILED at stage '{name}': {exc}", stages
                    ) from exc

            return _wrap

        # --- Precondition validation (pre-transaction; no mutation possible) ---
        p = Path(trace_path)
        if not utils.is_path_safe(p, config.PROJECT_ROOT):
            raise PermissionError(
                f"Security violation: Trace file outside project jail: {trace_path}"
            )
        if not p.exists():
            raise FileNotFoundError(f"Trace file not found: {trace_path}")

        cls.compute_signature(p)

        if not run_id:
            logger.error(
                "   [Verifier] FAIL: Missing explicit Run ID. Inference "
                "is prohibited for forensic stability."
            )
            raise ValueError(
                "Identity Basis Failure: Explicit 'run_id' is required for certification."
            )

        vault_path = (config.RUN_LOG_DIR / run_id / "run.jsonl").resolve()
        master_path = (config.RUN_LOG_DIR / "run.jsonl").resolve()
        resolved_p = p.resolve()

        is_vault = resolved_p == vault_path
        is_master = resolved_p == master_path
        if not (is_vault or is_master):
            logger.error("   [Verifier] FAIL: Forensic Pollution - Path mismatch.")
            logger.error(f"      Provided: {resolved_p}")
            logger.error(f"      Expected (Vault): {vault_path}")
            logger.error(f"      Expected (Master): {master_path}")
            raise ValueError(
                f"Forensic Pollution: Trace at '{p}' resides in a non-compliant location. "
                "Traces must be standard vaults (runs/<id>/run.jsonl) or the master log."
            )

        logger.info(
            f"      [Identity] Identity Basis Confirmed: {run_id} "
            f"(Type: {'Vault' if is_vault else 'Master'})"
        )

        now = datetime.now().astimezone()
        ts_base = now.strftime("%Y-%m-%dT%H:%M:%S")
        ms = f".{now.microsecond // 1000:03d}"
        timestamp = ts_base + ms + now.strftime("%z")

        sidecar_path = p.parent / "run_manifest.json"
        backup_path = config.REPORTS_DIR / "certificates" / f"{run_id}_vc.json"
        pre_append_size = p.stat().st_size

        def _rollback() -> None:
            """Best-effort rollback of any partial mutation."""
            try:
                if p.exists() and p.stat().st_size != pre_append_size:
                    with open(p, "r+b") as f:
                        f.truncate(pre_append_size)
            except Exception as rb_exc:  # noqa: BLE001
                logger.critical(f"      [Verifier] Rollback of trace failed: {rb_exc}")
            for stray in (sidecar_path, backup_path):
                try:
                    if stray.exists():
                        stray.unlink(missing_ok=True)
                except OSError as unlink_err:
                    logger.debug(
                        f"      [Verifier] Failed to unlink rollback stray {stray}: {unlink_err}"
                    )

        store = artifact_store or LocalFileArtifactStore()

        # 1. FREEZE: hash evidence + seal-hash BEFORE any mutation
        evidence_ledger = _stage("freeze")(
            lambda: cls._compute_evidence_ledger(p.parent, run_id=run_id, exclude_files=[p.name])
        )
        seal_hash = _stage("freeze_seal_hash")(lambda: cls.compute_signature(p))

        # 2. CANONICALIZE: build Manifest v3.0.0
        manifest = {
            "vc_version": VC_V3_SCHEMA_VERSION,
            "harness_version": config.VERSION,
            "timestamp": timestamp,
            "run_id": run_id,
            "trace_file": p.name,
            "compliance": {
                "status": compliance_status,
                "score": compliance_score,
                "policy_ref": policy_ref or config.TRUSTED_POLICY_REF,
            },
            "evidence_ledger": evidence_ledger,
            "provenance_chain": [],
            "governance_ttl": (ttl_days or config.GOVERNANCE_TTL_DAYS),
            "metadata": metadata or {},
            "behavioral_fingerprint_id": behavioral_fingerprint_id or "default_v1",
        }
        if evidence_root_hash:
            # [E2] Additive field within VC v3.0.0: the certificate commits to
            # the decision's evidence root hash over its assertion set.
            manifest["evidence_root_hash"] = evidence_root_hash

        # Extract real consensus / rubrics from trace if present and not explicitly passed
        extracted_consensus = consensus or (metadata.get("consensus") if metadata else None)
        extracted_rubrics = rubrics or (metadata.get("rubrics") if metadata else None)
        if (extracted_consensus is None or extracted_rubrics is None) and p.exists():
            try:
                with open(p, encoding="utf-8") as tf:
                    for line in tf:
                        if not line.strip():
                            continue
                        try:
                            record = json.loads(line)
                            if extracted_consensus is None and record.get("consensus"):
                                extracted_consensus = record.get("consensus")
                            if extracted_rubrics is None and record.get("rubrics"):
                                extracted_rubrics = record.get("rubrics")
                        except (
                            json.JSONDecodeError,
                            UnicodeDecodeError,
                            AttributeError,
                        ) as line_err:
                            logger.debug(
                                f"      [Verifier] Non-JSON line in trace scan: {line_err}"
                            )

            except OSError as read_err:
                logger.warning(
                    f"      [Verifier] Could not read trace for consensus extraction: {read_err}"
                )

        if extracted_consensus:
            manifest["consensus"] = extracted_consensus
        if extracted_rubrics:
            manifest["rubrics"] = extracted_rubrics

        # [VC-Trust B] REQUIRED truth-level stamping (2026-08 waiver, no
        # version bump): every certificate states the run's execution mode.
        # Whitelist enforcement here too (defense in depth): SessionManager
        # rejects junk upstream, but the verifier must never emit a value
        # outside the schema enum. Unrecognized input is recorded truthfully
        # as "unknown" + provisional — never fabricated, never passed through.
        from .execution_ir import ExecutionMode

        _valid_modes = {m.value for m in ExecutionMode}
        # Exact-match only: mirrors SessionManager's strict fail-closed
        # parsing ("SIMULATED" / "live " are rejected upstream). Case- or
        # space-variants never silently become declarations.
        _mode_in = str(execution_mode) if execution_mode else ""
        if _mode_in in _valid_modes:
            manifest["execution_mode"] = _mode_in
            if provisional:
                manifest["provisional"] = True
        else:
            manifest["execution_mode"] = "unknown"
            manifest["provisional"] = True
        _stage("canonicalize")(lambda: manifest)

        # 3. EMIT LIFECYCLE EVENT + HASH (mutation point; rolled back on failure)
        def _append_and_hash() -> str:
            event = {
                "event": "verification_certificate_issued",
                "timestamp": timestamp,
                "identity": identity_id,
                "vc_version": manifest["vc_version"],
                "seal_hash": seal_hash,
            }
            # [Append Safety] Guarantee JSONL line integrity: if the existing
            # trace does not end with a newline, start a fresh line before
            # appending so the final pre-certification event is never merged
            # (and destroyed) by the concatenation.
            needs_newline = False
            if pre_append_size > 0:
                with open(p, "rb") as f:
                    f.seek(-1, 2)  # os.SEEK_END
                    needs_newline = f.read(1) != b"\n"
            with open(p, "ab") as f:
                event_line = (json.dumps(event) + "\n").encode("utf-8")
                if needs_newline:
                    written = f.write(b"\n") + f.write(event_line)
                else:
                    written = f.write(event_line)
                f.flush()
                import os as _os

                _os.fsync(f.fileno())
                if written != len(event_line) + (1 if needs_newline else 0):
                    raise OSError("Short write while appending certification lifecycle event")
            actual_hash = cls.compute_signature(p)
            if not actual_hash or actual_hash == seal_hash:
                raise OSError("Post-event trace hash could not be established")
            return actual_hash

        # 3b. STAGE DEFINITIONS (executed transactionally below)
        def _sign() -> None:
            manifest["signing_context"] = {
                "identity_id": identity_id,
                "timestamp": timestamp,
            }
            format_str = "hybrid" if config.PQC_ENABLED else "ED25519"
            try:
                # NOTE: VerificationService.sign mutates and returns the SAME
                # manifest object; rebinding/clearing here would destroy it.
                verification_service.sign(manifest, format=format_str)
                if not manifest.get("provenance_chain"):
                    raise ValueError(
                        "Signing pipeline produced no provenance chain "
                        "(fail-closed: unsigned manifests can never be certified)"
                    )
            finally:
                manifest.pop("signing_context", None)

        persisted_local_path: Path | None = None

        def _persist() -> None:
            nonlocal persisted_local_path
            try:
                store.store_artifact(
                    run_id=run_id,
                    artifact_name="run_manifest.json",
                    content=json.dumps(manifest, indent=4),
                    content_type="application/json",
                    metadata={
                        "status": compliance_status,
                        "vc_version": manifest["vc_version"],
                    },
                )
                candidate = p.parent / "run_manifest.json"
                if candidate.exists():
                    persisted_local_path = candidate
            except Exception:
                with open(sidecar_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=4)
                persisted_local_path = sidecar_path

        def _verify() -> None:
            target = persisted_local_path or sidecar_path
            if target.exists():
                ok = cls.verify_trace(str(p), str(target), verify_ledger=True)
                if not ok:
                    raise ValueError("Post-signature self-verification rejected the certificate")

        def _seal() -> None:
            store.seal(
                run_id=run_id,
                metadata={
                    "certificate_hash": manifest.get("trace_hash", ""),
                    "vc_version": manifest.get("vc_version", VC_V3_SCHEMA_VERSION),
                    "timestamp": timestamp,
                    "compliance_status": compliance_status,
                },
            )

        def _publish() -> None:
            cert_dir = config.REPORTS_DIR / "certificates"
            cert_dir.mkdir(parents=True, exist_ok=True)
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=4)

        # --- TRANSACTION: hash -> sign -> persist -> verify -> seal -> publish ---
        # Any stage failure rolls back the trace mutation and partial artifacts,
        # then raises CertificationFailedError. No certificate is ever emitted
        # from an incomplete sealing operation (P0 #11).
        try:
            manifest["trace_hash"] = _stage("hash")(_append_and_hash)
            manifest["hash_algorithm"] = "sha3_256"

            _stage("sign")(_sign)

            _stage("persist")(_persist)

            _stage("verify")(_verify)

            _stage("seal")(_seal)
            logger.info(f"      [Verifier] Evidence vault sealed for run '{run_id}'")

            _stage("publish")(_publish)
        except CertificationFailedError:
            _rollback()
            raise

        manifest["certification"] = {
            "pipeline_version": "1.0.0",
            "transactional": True,
            "stages": stages,
            "outcome": "CERTIFIED",
        }
        return manifest

    @staticmethod
    def _compute_evidence_ledger(
        directory: Path, run_id: str | None = None, exclude_files: list[str] | None = None
    ) -> dict[str, str]:
        """
        Computes a filtered forensic ledger for a directory.
        Delegates to the ForensicRelevanceEngine with Namespace Affinity Enforcement.
        """
        exclude_files = exclude_files or []
        engine = forensics.ForensicRelevanceEngine()
        return engine.compute_filtered_ledger(directory, exclude_files=exclude_files, run_id=run_id)

    @classmethod
    def get_certificate(
        cls, trace_path: str, run_id: str, identity_id: str = "system_id"
    ) -> dict[str, Any]:
        """
        Signs a trace and returns the certificate DICT directly (API Helper).
        """
        return cls.sign_trace(trace_path, run_id=run_id, identity_id=identity_id)

    @classmethod
    async def verify_trace_async(
        cls, trace_path: str, manifest_path: str, verify_ledger: bool = True
    ) -> bool:
        """
        Asynchronous version of verify_trace. Standard for v1.2+ Async-First architecture.
        Defaults to full evidence-chain verification.
        """
        return cls.verify_trace(trace_path, manifest_path, verify_ledger=verify_ledger)

    @classmethod
    def verify_trace(
        cls,
        trace_path: str,
        manifest_path: str,
        verify_ledger: bool = True,
        *,
        trace_only: bool = False,
    ) -> bool:
        """
        Verifies a trace file against its manifest (VC). Strictly enforces VC v3.0.0+.

        AgentV v2.0.0: verification of a VC defaults to FULL evidence-chain
        validation (trace hash + signature + every referenced evidence artifact).
        Partial verification must be explicitly requested via trace_only=True
        (or the legacy verify_ledger=False argument).
        """
        from .identity import IdentityService

        effective_ledger_check = False if trace_only else verify_ledger

        tp = Path(trace_path)
        mp = Path(manifest_path)

        if not utils.is_path_safe(tp, config.PROJECT_ROOT) or not utils.is_path_safe(
            mp, config.PROJECT_ROOT
        ):
            logger.error("Security violation: Verification paths outside project jail.")
            return False

        if not tp.exists() or not mp.exists():
            logger.error(
                f"❌ [Verifier] Artifact missing for {mp.stem}: "
                f"{'Trace' if not tp.exists() else ''} "
                f"{'Manifest' if not mp.exists() else ''}"
            )
            return False

        try:
            with open(mp, encoding="utf-8") as f:
                manifest = json.load(f)

            vc_version = manifest.get("vc_version", "1.0.0")
            if vc_version < "3.0.0":
                logger.error(
                    f"Legacy VC Version {vc_version} is no longer supported. (Standard: 3.0.0+)"
                )
                return False

            # 1. Base Integrity Check
            expected_hash = manifest.get("trace_hash")
            actual_hash = cls.compute_signature(tp)
            if expected_hash != actual_hash:
                logger.warning(f"Trace hash mismatch: expected {expected_hash}, got {actual_hash}")
                return False

            # 2. Forensic Evidence Ledger Check (v3+; FULL chain by default)
            if effective_ledger_check:
                ledger = manifest.get("evidence_ledger", {})
                for rel_path, expected_file_hash in ledger.items():
                    file_path = tp.parent / rel_path
                    if not file_path.exists():
                        logger.warning(f"Forensic artifact missing: {rel_path}")
                        return False
                    if cls.compute_signature(file_path) != expected_file_hash:
                        logger.warning(f"Forensic artifact tampered: {rel_path}")
                        return False

            # 3. Governance TTL Check (v3+)
            ts_str = manifest.get("timestamp")
            ttl_days = manifest.get("governance_ttl", config.GOVERNANCE_TTL_DAYS)
            try:
                created_at = datetime.fromisoformat(ts_str)
                age = datetime.now().astimezone() - created_at
                if age.days > ttl_days:
                    logger.warning(
                        f"Verification Certificate expired ({age.days} > {ttl_days} days)"
                    )
                    return False
            except Exception as e:
                logger.warning(f"Failed to verify governance TTL: {e}")
                return False

            # 4. Cryptographic Proof (Hybrid/Chain Support)
            chain = manifest.get("provenance_chain", [])
            if not chain:
                logger.warning("No provenance chain found in v3 manifest.")
                return False

            manifest_to_verify = manifest.copy()
            manifest_to_verify.pop("provenance_chain", None)
            # Transient pipeline metadata is excluded from the signed payload
            # (it is appended after signing by the certification transaction).
            manifest_to_verify.pop("certification", None)
            manifest_bytes = json.dumps(manifest_to_verify, sort_keys=True).encode("utf-8")

            for node in chain:
                identity_id = node.get("identity")
                sig_hex = node.get("signature")
                algorithm = node.get("algorithm", "ED25519")

                if algorithm == "ED25519":
                    # Local Classical Verification
                    public_key = IdentityService.get_public_key(identity_id)
                    public_key.verify(bytes.fromhex(sig_hex), manifest_bytes)
                    logger.debug(f"      [Verifier] ED25519 Signature Verified: {identity_id}")
                elif algorithm == "ML-DSA-65":
                    # PQC Verification (via CycleCore or local validator)
                    pqc_client = IdentityService.get_pqc_client()
                    if pqc_client:
                        # ZES Verification: Hash locally and verify signature
                        shake_digest = forensics.compute_shake256_digest(manifest_bytes)
                        is_valid = pqc_client.verify_digest(
                            signature=sig_hex,
                            digest=shake_digest,
                            identity_id=config.PQC_IDENTITY_ID,
                        )
                        if not is_valid:
                            raise ValueError(f"PQC Signature Mismatch for {identity_id}")
                        logger.debug(
                            f"      [Verifier] ML-DSA-65 Signature Verified: {identity_id}"
                        )
                    else:
                        msg = (
                            f"Skipping PQC verification for {identity_id} "
                            "(PQC client not available)."
                        )
                        logger.warning(f"      [Verifier] {msg}")
                        if config.PQC_STRICT_MODE:
                            raise ValueError(f"PQC_STRICT_MODE Violation: {msg}")
                else:
                    logger.warning(
                        f"      [Verifier] Unknown algorithm '{algorithm}' for {identity_id}"
                    )

            return True
        except Exception:
            import traceback

            logger.error(f"Verification Failure:\n{traceback.format_exc()}")
            return False

    @classmethod
    def verify_run_directory(cls, run_dir: Path | str) -> dict[str, Any]:
        """
        Authoritative Server-Side Verification for an entire run directory.
        Checks trace integrity, certificate validity, signatures, and summary.
        """
        p = Path(run_dir)
        tp = p / "run.jsonl"
        mp = p / "run_manifest.json"
        cp = p / "certificate.json"
        if not cp.exists():
            cp = config.REPORTS_DIR / "certificates" / f"{p.name}_vc.json"

        if not p.exists():
            return {
                "run_id": p.name,
                "verification_status": "NOT_FOUND",
                "is_valid": False,
                "has_certificate": False,
                "has_signature": False,
                "failure_reason": "Run directory does not exist",
            }

        target_manifest = mp if mp.exists() else cp if cp.exists() else None
        if not target_manifest or not target_manifest.exists():
            return {
                "run_id": p.name,
                "verification_status": "UNVERIFIED",
                "is_valid": False,
                "has_certificate": False,
                "has_signature": False,
                "failure_reason": (
                    "No persistent cryptographic manifest or certificate found for this run."
                ),
            }

        if not tp.exists():
            return {
                "run_id": p.name,
                "verification_status": "FAILED_VERIFICATION",
                "is_valid": False,
                "has_certificate": True,
                "has_signature": False,
                "failure_reason": "Execution trace (run.jsonl) is missing from run directory.",
            }

        try:
            with open(target_manifest, encoding="utf-8") as f:
                mdata = json.load(f)

            # Full evidence-chain verification is the server-side default (P0 #12).
            is_valid = cls.verify_trace(str(tp), str(target_manifest), verify_ledger=True)
            has_sig = bool(mdata.get("signature") or mdata.get("signatures"))
            algorithm = mdata.get("algorithm") or mdata.get("crypto_suite", "Ed25519")
            pqc = bool("ml-dsa" in str(algorithm).lower() or "pqc" in str(algorithm).lower())

            status = "VERIFIED" if is_valid else "FAILED_VERIFICATION"
            return {
                "run_id": p.name,
                "verification_status": status,
                "is_valid": is_valid,
                "has_certificate": True,
                "has_signature": has_sig,
                "algorithm": algorithm,
                "is_pqc": pqc,
                "trace_hash": mdata.get("trace_hash"),
                "timestamp": mdata.get("timestamp"),
                "failure_reason": None
                if is_valid
                else "Trace content hash mismatch or signature verification failed.",
            }
        except Exception as e:
            return {
                "run_id": p.name,
                "verification_status": "FAILED_VERIFICATION",
                "is_valid": False,
                "has_certificate": True,
                "has_signature": False,
                "failure_reason": f"Verification error: {str(e)}",
            }


def verify_trace_certificate(
    run_id: str,
    trace_bytes: bytes,
    cert_data: dict[str, Any],
    scenario_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Authoritative top-level certificate verifier invoked by the evidence package builder.

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

    result: dict[str, Any] = {
        "verified": False,
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
            result["manifest_hash_match"] = False
        else:
            result["errors"].append(
                f"Trace hash mismatch: expected={expected_trace_hash!r}, "
                f"computed=sha3_256:{computed_hex!r}"
            )
    else:
        # No reference hash in cert \u2014 cannot verify
        result["errors"].append("Certificate does not contain a trace_hash for verification.")

    # 2. Scenario hash match
    if scenario_data is not None:
        try:
            from agentv_runtime.manifest import compute_scenario_hash

            expected_scen_hash = cert_data.get("scenario_hash")
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
    # The certification pipeline signs the CANONICAL MANIFEST bytes (the
    # manifest minus provenance_chain/certification/signing_context), and the
    # manifest in turn binds the trace via trace_hash. Verification therefore
    # reconstructs that exact payload.
    provenance_chain = cert_data.get("provenance_chain") or cert_data.get("signatures") or []
    if not provenance_chain:
        result["errors"].append("Certificate has no provenance_chain entries to verify.")

    signed_payload = {
        k: v
        for k, v in cert_data.items()
        if k not in ("provenance_chain", "certification", "signing_context")
    }
    manifest_bytes = _json.dumps(signed_payload, sort_keys=True).encode("utf-8")

    sig_verified = False
    for entry in provenance_chain:
        if not isinstance(entry, dict):
            result["errors"].append(
                f"Malformed provenance entry (expected object, got {type(entry).__name__})."
            )
            continue
        algorithm = entry.get("algorithm", "ED25519")
        signature_hex = entry.get("signature", "")
        identity_id = entry.get("identity", "system_id")

        if not signature_hex or len(signature_hex) < 32:
            result["errors"].append(
                f"Signature entry for identity '{identity_id}' is empty or malformed."
            )
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
            continue

        try:
            from .identity import IdentityService

            private_key = IdentityService.get_private_key(identity_id)
            if private_key is None:
                result["errors"].append(
                    f"No private key available for signer identity '{identity_id}'."
                )
                continue

            # Derive public key for verification
            if hasattr(private_key, "public_key"):
                public_key = private_key.public_key()
                sig_bytes = bytes.fromhex(signature_hex)

                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

                if isinstance(public_key, Ed25519PublicKey):
                    try:
                        public_key.verify(sig_bytes, manifest_bytes)
                        sig_verified = True
                        result["signer_identity"] = identity_id
                        result["algorithm"] = algorithm
                    except Exception as verify_err:
                        result["errors"].append(
                            f"Ed25519 signature verification failed for "
                            f"'{identity_id}': {verify_err}"
                        )
                else:
                    result["errors"].append(
                        f"Unsupported key type for signer '{identity_id}': "
                        f"{type(public_key).__name__}"
                    )
            else:
                result["errors"].append(f"Cannot derive public key from signer '{identity_id}'.")
        except Exception as sig_err:
            logger.debug("Signature check error for %s/%s: %s", run_id, identity_id, sig_err)
            result["errors"].append(f"Signature check error for '{identity_id}': {sig_err}")

    if sig_verified and result["manifest_hash_match"]:
        result["verified"] = True

    return result
