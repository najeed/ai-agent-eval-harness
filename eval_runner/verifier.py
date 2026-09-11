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
            manifest_to_sign.pop("certification_diagnostics", None)
            if "certification" in manifest_to_sign and isinstance(
                manifest_to_sign["certification"], dict
            ):
                cert_copy = dict(manifest_to_sign["certification"])
                cert_copy.pop("stages", None)
                manifest_to_sign["certification"] = cert_copy
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

            manifest.setdefault("provenance_chain", []).append(
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
        scenario_data: Mapping[str, Any] | None = None,
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
        staging_dir = p.parent / ".staging"
        staged_manifest_path = staging_dir / "run_manifest.json"
        pre_append_size = p.stat().st_size
        bytes_appended = 0

        def _rollback() -> None:
            """Best-effort rollback of any partial mutation."""
            import shutil

            if staging_dir.exists():
                try:
                    shutil.rmtree(staging_dir, ignore_errors=True)
                except Exception as s_err:
                    logger.debug(f"      [Verifier] Failed to remove staging directory: {s_err}")

            for stray in (sidecar_path, backup_path):
                try:
                    stray.unlink(missing_ok=True)
                except OSError as unlink_err:
                    logger.debug(
                        f"      [Verifier] Failed to unlink rollback stray {stray}: {unlink_err}"
                    )
            try:
                if hasattr(store, "unseal"):
                    store.unseal(run_id)
            except OSError as unseal_err:
                logger.debug(
                    f"      [Verifier] Failed to unseal rollback target {run_id}: {unseal_err}"
                )
            try:
                if p.exists() and bytes_appended > 0:
                    current_size = p.stat().st_size
                    if current_size == pre_append_size + bytes_appended:
                        with open(p, "a+b") as f:
                            f.truncate(pre_append_size)
            except OSError as trunc_err:
                logger.debug(f"      [Verifier] Trace rollback truncate notice: {trunc_err}")

        store = artifact_store or LocalFileArtifactStore()

        # 1. FREEZE: hash evidence + seal-hash BEFORE any mutation
        manifest_sidecars = [
            p.name,
            "run_manifest.json",
            "run_manifest.json.meta.json",
            "certificate.json",
            "trace_seal.json",
            ".sealed",
        ]
        evidence_ledger = _stage("freeze")(
            lambda: cls._compute_evidence_ledger(
                p.parent, run_id=run_id, exclude_files=manifest_sidecars
            )
        )
        seal_hash = _stage("freeze_seal_hash")(lambda: cls.compute_signature(p))

        # Recompute deterministic evidence root hash from trace events
        computed_evidence_root: str | None = None
        ev_graph: dict[str, Any] | None = None
        events_list: list[dict[str, Any]] = []
        if p.exists():
            try:
                from agentv_runtime.evidence_graph import (
                    build_evidence_graph_from_events,
                    compute_evidence_graph_root,
                )

                with open(p, encoding="utf-8") as tf:
                    for line_idx, line in enumerate(tf, start=1):
                        stripped = line.strip()
                        if stripped:
                            try:
                                events_list.append(json.loads(stripped))
                            except Exception as ev_parse_err:
                                logger.error(
                                    f"Malformed trace record at line {line_idx}: {ev_parse_err}"
                                )
                                raise CertificationFailedError(
                                    f"Malformed trace record at line {line_idx}: {ev_parse_err}"
                                ) from ev_parse_err
                if events_list:
                    ev_graph = build_evidence_graph_from_events(events_list)
                    computed_evidence_root = compute_evidence_graph_root(ev_graph)
                    total_nodes = ev_graph.get("total_nodes", ev_graph.get("node_count", 0))
                    if total_nodes > 0 and not ev_graph.get("is_complete_provenance", True):
                        # Only enforce direct provenance when assertion nodes exist.
                        # A trace with zero oracle assertion nodes (decision-only runs) is
                        # architecturally valid: there is simply nothing to attest at the
                        # assertion level. Certification of outcome-only traces is allowed.
                        logger.error(
                            "Evidence graph contains unresolved or carrier fallback provenance "
                            "(%d/%d nodes lack direct provenance).",
                            ev_graph.get("unresolved_count", 0)
                            + (total_nodes - ev_graph.get("direct_provenance_nodes", 0)),
                            total_nodes,
                        )
                        raise CertificationFailedError(
                            "DirectProvenanceViolation: Evidence graph contains unresolved "
                            "or carrier fallback provenance"
                        )
                    if total_nodes == 0:
                        logger.debug(
                            "Evidence graph has zero assertion nodes; "
                            "run is decision-only (no oracle evidence to attest)."
                        )
            except CertificationFailedError:
                raise
            except Exception as ev_err:
                logger.error(f"Evidence graph derivation failed: {ev_err}")
                raise CertificationFailedError(
                    f"Evidence graph derivation failed: {ev_err}"
                ) from ev_err

        if (
            evidence_root_hash
            and computed_evidence_root
            and evidence_root_hash != computed_evidence_root
        ):
            raise ValueError(
                f"EvidenceRootMismatch: supplied evidence_root_hash ({evidence_root_hash}) "
                f"does not match authoritative computed root ({computed_evidence_root})"
            )

        # Scenario binding resolution from canonical scenario document
        if scenario_data is not None:
            from agentv_runtime.manifest import compute_scenario_hash

            computed_scen_hash = compute_scenario_hash(scenario_data)
            scen_meta = scenario_data.get("metadata", {}) if isinstance(scenario_data, dict) else {}
            metadata = metadata or {}
            metadata["scenario_id"] = scen_meta.get("id") or metadata.get("scenario_id") or ""
            metadata["scenario_version"] = str(
                scen_meta.get("version") or metadata.get("scenario_version") or "1.0.0"
            )
            metadata["scenario_hash"] = computed_scen_hash

        # Derive machine-verifiable compliance status and score from trace.
        # Fail-closed authoritative derivation: terminal trace evidence takes absolute authority.
        effective_compliance_status = compliance_status
        effective_compliance_score = compliance_score

        has_root_cause = any(
            ev.get("is_root_cause") is True
            or (
                isinstance(ev.get("data"), dict) and ev.get("data", {}).get("is_root_cause") is True
            )
            for ev in events_list
        )

        extracted_decisions: list[tuple[str, float]] = []
        for ev in events_list:
            ev_name = ev.get("event") or ev.get("name") or ""
            data = ev.get("data", {}) if isinstance(ev.get("data"), dict) else {}
            is_decision = (
                ev_name
                in (
                    "run_end",
                    "end",
                    "turn_end",
                    "session_decision",
                    "evaluation_result",
                    "evaluation_verdict",
                    "workflow_verdict",
                )
                or "verdict" in ev
                or "verdict" in data
                or "decision" in ev
                or "decision" in data
                or "outcome" in ev
                or "outcome" in data
            )
            if not is_decision:
                continue

            raw_st = (
                data.get("status")
                or ev.get("status")
                or data.get("outcome")
                or ev.get("outcome")
                or ""
            )
            score_val = data.get("score") if data.get("score") is not None else ev.get("score")
            dec = str(data.get("decision") or ev.get("decision") or "").upper()
            verd = str(data.get("verdict") or ev.get("verdict") or "").upper()

            passed_val = data.get("passed") if data.get("passed") is not None else ev.get("passed")
            if passed_val is False:
                raw_st = "fail"
            elif passed_val is True and not raw_st:
                raw_st = "pass"

            if not raw_st and data.get("pass_at_k") is not None:
                pak = float(data["pass_at_k"])
                raw_st = "pass" if pak > 0 else "fail"
                if score_val is None:
                    score_val = pak
            if not raw_st and data.get("all_pass") is not None:
                raw_st = "pass" if data["all_pass"] else "fail"

            st_lower = str(raw_st).strip().lower()

            if (
                st_lower in ("fail", "failed", "failure", "rejected")
                or dec in ("FAIL", "FAILED", "REJECTED", "UNVERIFIED")
                or verd in ("FAIL", "FAILED", "POLICY_BREACH", "NOT_VERIFIED")
            ):
                extracted_decisions.append(
                    ("fail", float(score_val if score_val is not None else 0.0))
                )
            elif (
                st_lower in ("pass", "passed", "success", "verified")
                or dec in ("PASS", "PASSED", "VERIFIED")
                or verd in ("PASS", "PASSED", "VERIFIED")
            ):
                extracted_decisions.append(
                    ("pass", float(score_val) if score_val is not None else None)
                )
            elif dec == "EVALUATION_INVALID" or st_lower == "evaluation_invalid":
                extracted_decisions.append(("fail", 0.0))

        if has_root_cause:
            logger.warning(
                "      [Verifier] Trace contains root cause failure; "
                "deriving compliance_status='fail', compliance_score=0.0"
            )
            effective_compliance_status = "fail"
            effective_compliance_score = 0.0
        elif extracted_decisions:
            distinct_statuses = {d[0] for d in extracted_decisions}
            if len(distinct_statuses) > 1:
                logger.warning(
                    "      [Verifier] Conflicting terminal decisions in trace: %s",
                    distinct_statuses,
                )
                effective_compliance_status = "fail"
                effective_compliance_score = 0.0
            else:
                effective_compliance_status, term_score = extracted_decisions[-1]
                effective_compliance_score = (
                    term_score
                    if term_score is not None
                    else (compliance_score if compliance_score is not None else 1.0)
                )

        # 2. CANONICALIZE: build Manifest v3.0.0
        manifest = {
            "vc_version": VC_V3_SCHEMA_VERSION,
            "harness_version": config.VERSION,
            "timestamp": timestamp,
            "run_id": run_id,
            "trace_file": p.name,
            "compliance": {
                "status": effective_compliance_status,
                "score": effective_compliance_score,
                "policy_ref": policy_ref or config.TRUSTED_POLICY_REF,
            },
            "evidence_ledger": evidence_ledger,
            "provenance_chain": [],
            "governance_ttl": (ttl_days or config.GOVERNANCE_TTL_DAYS),
            "metadata": metadata or {},
            "behavioral_fingerprint_id": behavioral_fingerprint_id or "default_v1",
        }
        manifest_evidence_root = evidence_root_hash or computed_evidence_root
        if manifest_evidence_root:
            manifest["evidence_root_hash"] = manifest_evidence_root

        # Causal contract binding
        if metadata:
            for k in (
                "scenario_id",
                "scenario_hash",
                "policy_id",
                "evaluator_config_hash",
                "agent_id",
                "agent_identity",
            ):
                if k in metadata and k not in manifest:
                    manifest[k] = metadata[k]

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
                nonlocal bytes_appended
                bytes_appended = written
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

        def _persist() -> None:
            """
            Prepare: Persist manifest artifact and sidecars to isolated staging and store.
            No irreversible seal operations occur in this stage.
            """
            import copy

            staging_dir.mkdir(parents=True, exist_ok=True)
            manifest_to_write = copy.deepcopy(manifest)
            manifest_to_write["certification"]["stages"] = stages

            with open(staged_manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest_to_write, f, indent=4)

            # Persist to local run directory sidecar
            with open(sidecar_path, "w", encoding="utf-8") as f:
                json.dump(manifest_to_write, f, indent=4)

            # Store artifact in configured ArtifactStore
            store.store_artifact(
                run_id=run_id,
                artifact_name="run_manifest.json",
                content=json.dumps(manifest_to_write, indent=4),
                content_type="application/json",
                metadata={
                    "status": effective_compliance_status,
                    "vc_version": manifest["vc_version"],
                },
            )

        def _verify() -> None:
            """
            Self-Verification: Verify trace and full evidence ledger
            against manifest before promotion.
            """
            target = sidecar_path if sidecar_path.exists() else staged_manifest_path
            ok = cls.verify_trace(str(p), str(target), verify_ledger=True)
            if not ok:
                raise ValueError("Post-signature self-verification rejected the certificate")

        def _publish() -> None:
            """
            Commit/Promote: Publish public verification certificate backup.
            """
            import copy

            cert_dir = config.REPORTS_DIR / "certificates"
            cert_dir.mkdir(parents=True, exist_ok=True)
            manifest_to_write = copy.deepcopy(manifest)
            manifest_to_write["certification"]["stages"] = stages
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(manifest_to_write, f, indent=4)

        def _seal() -> None:
            """
            Final Irreversible Operation:
            Seal vault only after all artifacts are verified and published.
            """
            import shutil

            store.seal(
                run_id=run_id,
                metadata={
                    "certificate_hash": manifest.get("trace_hash", ""),
                    "vc_version": manifest.get("vc_version", VC_V3_SCHEMA_VERSION),
                    "timestamp": timestamp,
                    "compliance_status": compliance_status,
                },
            )
            shutil.rmtree(staging_dir, ignore_errors=True)

        # --- TRANSACTION: hash -> sign -> persist(stage) -> verify -> publish(promote) -> seal ---
        # Any stage failure rolls back the trace mutation and partial artifacts,
        # then raises CertificationFailedError. No certificate is ever emitted
        # from an incomplete sealing operation (P0 #11).
        try:
            manifest["trace_hash"] = _stage("hash")(_append_and_hash)
            manifest["hash_algorithm"] = "sha3_256"

            # Semantically authoritative certification metadata is signed
            manifest["certification"] = {
                "pipeline_version": "1.0.0",
                "transactional": True,
                "outcome": "CERTIFIED",
            }

            _stage("sign")(_sign)

            _stage("persist")(_persist)

            _stage("verify")(_verify)

            _stage("publish")(_publish)

            _stage("seal")(_seal)
            logger.info(f"      [Verifier] Evidence vault sealed for run '{run_id}'")
        except CertificationFailedError:
            _rollback()
            raise

        manifest["certification"]["stages"] = stages
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

            # 2b. Deterministic Evidence Graph Root Check (when present)
            expected_evidence_root = manifest.get("evidence_root_hash")
            if expected_evidence_root and tp.exists():
                try:
                    from agentv_runtime.evidence_graph import (
                        build_evidence_graph_from_events,
                        compute_evidence_graph_root,
                    )

                    ev_list = []
                    with open(tp, encoding="utf-8") as tf:
                        for line_idx, line in enumerate(tf, start=1):
                            stripped = line.strip()
                            if stripped:
                                try:
                                    ev_list.append(json.loads(stripped))
                                except (
                                    json.JSONDecodeError,
                                    UnicodeDecodeError,
                                    ValueError,
                                ) as line_err:
                                    logger.warning(
                                        "Trace line parse failure at line %d: %s",
                                        line_idx,
                                        line_err,
                                    )
                                    return False

                    if ev_list:
                        graph = build_evidence_graph_from_events(ev_list)
                        computed_root = compute_evidence_graph_root(graph)
                        if computed_root != expected_evidence_root:
                            logger.warning(
                                f"Evidence root mismatch: expected {expected_evidence_root}, "
                                f"got {computed_root}"
                            )
                            return False
                        # Only fail if assertion nodes exist but have incomplete provenance.
                        # Decision-only traces (zero assertion nodes) are architecturally valid.
                        ev_total = graph.get("total_nodes", graph.get("node_count", 0))
                        if ev_total > 0 and not graph.get("is_complete_provenance", True):
                            logger.warning(
                                "Evidence graph contains unresolved or carrier fallback provenance"
                            )
                            return False
                except Exception as ev_v_err:
                    logger.warning(f"Failed to verify evidence graph root: {ev_v_err}")
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
            manifest_to_verify.pop("certification_diagnostics", None)
            # Transient stage execution logs are excluded from the signed payload,
            # while authoritative certification metadata (outcome, pipeline_version, transactional)
            # is signed and verified against tampering.
            if "certification" in manifest_to_verify and isinstance(
                manifest_to_verify["certification"], dict
            ):
                cert_copy = dict(manifest_to_verify["certification"])
                cert_copy.pop("stages", None)
                manifest_to_verify["certification"] = cert_copy
            from agentv_runtime.canonical import canonical_json_encode as _canonical_json_encode

            candidate_bytes = [
                json.dumps(manifest_to_verify, sort_keys=True).encode("utf-8"),
                _canonical_json_encode(manifest_to_verify),
            ]
            manifest_bytes = candidate_bytes[0]

            if "certification" in manifest:
                cert_meta = manifest["certification"]
                if isinstance(cert_meta, dict) and cert_meta.get("outcome") != "CERTIFIED":
                    logger.warning("Uncertified manifest: certification outcome is not CERTIFIED")
                    return False

            for node in chain:
                identity_id = node.get("identity")
                sig_hex = node.get("signature")
                algorithm = node.get("algorithm", "ED25519")

                if algorithm == "ED25519":
                    # Local Classical Verification
                    public_key = IdentityService.get_public_key(identity_id)
                    verified = False
                    for m_bytes in candidate_bytes:
                        try:
                            public_key.verify(bytes.fromhex(sig_hex), m_bytes)
                            manifest_bytes = m_bytes
                            verified = True
                            break
                        except Exception:
                            continue
                    if not verified:
                        public_key.verify(bytes.fromhex(sig_hex), candidate_bytes[0])
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
                    msg = (
                        f"Unknown or unsupported signature algorithm '{algorithm}' "
                        f"for {identity_id}"
                    )
                    logger.error(f"      [Verifier] {msg}")
                    raise ValueError(msg)

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

            # Surface truth-level fields from the manifest so every caller has a single
            # authoritative source — avoids parent-prop fragility on direct/deep navigation.
            cert_execution_mode = mdata.get("execution_mode")
            cert_provisional = bool(
                mdata.get("provisional")
                or cert_execution_mode in ("simulated", "unknown")
                or not cert_execution_mode
            )

            if is_valid:
                status = "VERIFIED_PROVISIONAL" if cert_provisional else "VERIFIED"
            else:
                status = "FAILED_VERIFICATION"

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
                "execution_mode": cert_execution_mode,
                "provisional": cert_provisional,
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
    # The certification pipeline signs the CANONICAL MANIFEST bytes (the
    # manifest minus provenance_chain/certification/signing_context), and the
    # manifest in turn binds the trace via trace_hash. Verification therefore
    # reconstructs that exact payload.
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

    candidate_manifest_bytes = [
        _json.dumps(signed_payload, sort_keys=True).encode("utf-8"),
        _cje(signed_payload),
    ]

    sig_verified = False
    for entry in provenance_chain:
        if not isinstance(entry, dict):
            result["errors"].append(
                f"Malformed provenance entry (expected object, got {type(entry).__name__})."
            )
            continue
        algorithm = entry.get("algorithm", "ED25519")
        signature_hex = entry.get("signature", "")
        identity_id = entry.get("identity") or entry.get("signer_identity") or "system_id"

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
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            from cryptography.hazmat.primitives.serialization import (
                Encoding,
                PublicFormat,
                load_pem_public_key,
            )

            from .identity import IdentityService

            # 1. Authoritative Anchor Key Lookup (Fail-closed: trust root must be anchored)
            anchor_pk = None
            try:
                anchor_pk = IdentityService.get_public_key(identity_id)
            except Exception as id_lookup_err:
                logger.debug(f"IdentityService lookup error for {identity_id}: {id_lookup_err}")
                result["errors"].append(
                    f"Signature check error for '{identity_id}': "
                    f"IdentityService error: {id_lookup_err}"
                )
                continue

            if anchor_pk is None:
                result["errors"].append(
                    f"No trusted anchor public key found in IdentityService for "
                    f"identity '{identity_id}' (No public key available in trust root; "
                    "unanchored embedded keys prohibited)."
                )
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
                            continue
                except Exception as pk_cmp_err:
                    logger.debug(f"Public key comparison error: {pk_cmp_err}")
                    result["errors"].append(
                        f"Signature check error for '{identity_id}': "
                        f"No public key available ({pk_cmp_err})"
                    )
                    continue

            public_key = anchor_pk

            if not isinstance(public_key, Ed25519PublicKey):
                result["errors"].append(
                    f"Unsupported key type for signer '{identity_id}': {type(public_key).__name__}"
                )
                continue

            sig_bytes = bytes.fromhex(signature_hex)
            verified = False
            last_err = None
            for cand_bytes in candidate_manifest_bytes:
                try:
                    public_key.verify(sig_bytes, cand_bytes)
                    verified = True
                    break
                except Exception as ex:
                    last_err = ex

            if verified:
                sig_verified = True
                result["signer_identity"] = identity_id
                result["algorithm"] = algorithm
            else:
                result["errors"].append(
                    f"Ed25519 signature verification failed for '{identity_id}': {last_err}"
                )
        except Exception as sig_err:
            logger.debug("Signature check error for %s/%s: %s", run_id, identity_id, sig_err)
            result["errors"].append(f"Signature check error for '{identity_id}': {sig_err}")

    # 4. Check evidence_root_hash if present in certificate
    evidence_root_valid = True
    if cert_data.get("evidence_root_hash"):
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
                    for line_idx, line in enumerate(trace_str.splitlines(), start=1):
                        stripped = line.strip()
                        if stripped:
                            try:
                                ev_list.append(_json.loads(stripped))
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

                    if not has_line_error and ev_list:
                        ev_graph = build_evidence_graph_from_events(ev_list)
                        computed_ev_root = compute_evidence_graph_root(ev_graph)
                        expected_ev_root = cert_data["evidence_root_hash"]
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

    # Enforce scenario hash binding requirement if scenario hash is present in certificate
    scenario_bound_valid = True
    scen_hash_binding = cert_data.get("scenario_hash") or (
        cert_data.get("metadata", {}).get("scenario_hash")
    )
    if scen_hash_binding:
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
        raw_trace_events: list[dict[str, Any]],
        canonical_manifest: Any,
        scenario_data: Any | None = None,
        public_key_pem: str | None = None,
        trust_root: Any | None = None,
        key_registry: Mapping[str, str] | None = None,
        require_signature: bool = True,
    ) -> dict[str, Any]:
        """
        Authoritative validation of the complete evidence chain against underlying artifacts:
        1. Trace byte parity (recomputed SHA3-256 vs pkg.trace_hash)
        2. Manifest canonical hash binding (recomputed SHA3-256 vs pkg.manifest_hash)
        3. Evidence graph deterministic root reconstruction & direct provenance
        4. Trace seal integrity (cryptographic digest verification vs pkg.trace_hash)
        5. Scenario hash binding (mandatory scenario artifact presence, ID, version, and hash)
        6. Decision verdict conformance
        7. Required oracle inventory completeness & authoritative PASS outcome
        8. Cryptographic signature verification against external trust root
        """
        import hashlib

        from agentv_runtime.package import VerificationPackage

        if isinstance(package, dict):
            pkg = VerificationPackage.from_dict(package)
        else:
            pkg = package

        failures: list[str] = []

        # 1. Trace byte parity check
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

        # 2. Manifest canonical hash binding
        if canonical_manifest is None:
            failures.append("ManifestMissing: artifact verification requires canonical manifest")
        else:
            try:
                if hasattr(canonical_manifest, "compute_manifest_hash"):
                    computed_m_hash = canonical_manifest.compute_manifest_hash()
                elif isinstance(canonical_manifest, dict):
                    from agentv_runtime.manifest import ExecutionManifest

                    computed_m_hash = ExecutionManifest.from_dict(
                        canonical_manifest
                    ).compute_manifest_hash()
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
                if not exp_m_hash or computed_m_hash != exp_m_hash:
                    failures.append(
                        f"ManifestHashMismatch: package={exp_m_hash} actual={computed_m_hash}"
                    )
            except Exception as m_err:
                failures.append(f"ManifestVerificationFailed: {m_err}")

        # 3. Evidence root binding & reconstruction from raw events
        if raw_trace_events is None:
            failures.append("TraceEventsMissing: artifact verification requires raw trace events")
        else:
            try:
                from agentv_runtime.evidence_graph import (
                    build_evidence_graph_from_events,
                    compute_evidence_graph_root,
                )

                ev_graph = build_evidence_graph_from_events(raw_trace_events)
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

            if raw_trace_events is not None and "event_count" in pkg.trace_seal:
                try:
                    exp_count = int(pkg.trace_seal["event_count"])
                    if len(raw_trace_events) != exp_count:
                        failures.append(
                            f"TraceSealEventCountMismatch: seal declared {exp_count} events "
                            f"but actual trace contains {len(raw_trace_events)} events"
                        )
                except (ValueError, TypeError):
                    pass

        # 5. Scenario artifact binding check
        if scenario_data is None:
            failures.append(
                "ScenarioArtifactMissing: package certification requires bound scenario artifact"
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

        # 6. Decision verdict check
        decision_val = pkg.decision.get("decision") or pkg.decision.get("verdict")
        if decision_val not in ("PASS", "VERIFIED"):
            failures.append(f"UnverifiedDecision: decision was '{decision_val}'")

        # 7. Required oracle inventory & outcome check
        seen_oracle_ids: set[str] = set()
        executed_oracles: dict[str, dict[str, Any]] = {}
        for o in pkg.executed_oracle_results:
            o_id = str(o.get("oracle_id") or o.get("metric") or o.get("assertion") or "")
            if not o_id:
                continue
            if o_id in seen_oracle_ids:
                failures.append(f"DuplicateOracleId: duplicate oracle evaluation for '{o_id}'")
            seen_oracle_ids.add(o_id)
            executed_oracles[o_id] = o

        for req in pkg.required_oracle_ids:
            if not req:
                continue
            if req not in executed_oracles:
                failures.append(f"MissingRequiredOracles: required oracle '{req}' was not executed")
                continue

            o_res = executed_oracles[req]
            outcome = str(
                o_res.get("outcome") or ("PASS" if o_res.get("passed") is True else "FAIL")
            ).upper()
            if outcome != "PASS":
                failures.append(
                    f"RequiredOracleFailed: required oracle '{req}' outcome is '{outcome}'"
                )

            resolver = o_res.get("resolver") or o_res.get("evaluator") or o_res.get("metric_type")
            if not resolver or not isinstance(resolver, str):
                failures.append(
                    f"InvalidOracleResolver: required oracle '{req}' missing resolver specification"
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

        is_valid = len(failures) == 0
        return {
            "verified": is_valid,
            "status": "CERTIFIED" if is_valid else "UNVERIFIED",
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
        import hashlib

        from agentv_runtime.package import VerificationPackage

        if isinstance(package, dict):
            pkg = VerificationPackage.from_dict(package)
        else:
            pkg = package

        failures: list[str] = []

        # 1. Byte parity check if raw trace bytes supplied
        if raw_trace_bytes is not None:
            actual_trace_hash = hashlib.sha3_256(raw_trace_bytes).hexdigest()
            expected_hash = (
                pkg.trace_hash.split(":", 1)[1] if ":" in pkg.trace_hash else pkg.trace_hash
            )
            if actual_trace_hash.lower() != expected_hash.lower():
                failures.append(
                    f"TraceHashMismatch: package={pkg.trace_hash} actual={actual_trace_hash}"
                )

        # 2. Manifest binding
        if canonical_manifest is not None:
            try:
                if hasattr(canonical_manifest, "compute_manifest_hash"):
                    computed_m_hash = canonical_manifest.compute_manifest_hash()
                elif isinstance(canonical_manifest, dict):
                    from agentv_runtime.manifest import ExecutionManifest

                    computed_m_hash = ExecutionManifest.from_dict(
                        canonical_manifest
                    ).compute_manifest_hash()
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
                if not exp_m_hash or computed_m_hash != exp_m_hash:
                    failures.append(
                        f"ManifestHashMismatch: package={exp_m_hash} actual={computed_m_hash}"
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

                ev_graph = build_evidence_graph_from_events(raw_trace_events)
                computed_root = compute_evidence_graph_root(ev_graph)
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

            if raw_trace_events is not None and "event_count" in pkg.trace_seal:
                try:
                    exp_count = int(pkg.trace_seal["event_count"])
                    if len(raw_trace_events) != exp_count:
                        failures.append(
                            f"TraceSealEventCountMismatch: seal declared {exp_count} events "
                            f"but actual trace contains {len(raw_trace_events)} events"
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

        # 6. Decision verdict check
        decision_val = pkg.decision.get("decision") or pkg.decision.get("verdict")
        if decision_val not in ("PASS", "VERIFIED"):
            failures.append(f"UnverifiedDecision: decision was '{decision_val}'")

        # 7. Required oracle inventory & outcome check
        seen_oracle_ids: set[str] = set()
        executed_oracles: dict[str, dict[str, Any]] = {}
        for o in pkg.executed_oracle_results:
            o_id = str(o.get("oracle_id") or o.get("metric") or o.get("assertion") or "")
            if not o_id:
                continue
            if o_id in seen_oracle_ids:
                failures.append(f"DuplicateOracleId: duplicate oracle evaluation for '{o_id}'")
            seen_oracle_ids.add(o_id)
            executed_oracles[o_id] = o

        for req in pkg.required_oracle_ids:
            if not req:
                continue
            if req not in executed_oracles:
                failures.append(f"MissingRequiredOracles: required oracle '{req}' was not executed")
                continue

            o_res = executed_oracles[req]
            outcome = str(
                o_res.get("outcome") or ("PASS" if o_res.get("passed") is True else "FAIL")
            ).upper()
            if outcome != "PASS":
                failures.append(
                    f"RequiredOracleFailed: required oracle '{req}' outcome is '{outcome}'"
                )

            resolver = o_res.get("resolver") or o_res.get("evaluator") or o_res.get("metric_type")
            if not resolver or not isinstance(resolver, str):
                failures.append(
                    f"InvalidOracleResolver: required oracle '{req}' missing resolver specification"
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

        is_valid = len(failures) == 0
        return {
            "verified": is_valid,
            "status": "CERTIFIED" if is_valid else "UNVERIFIED",
            "failures": failures,
            "package_id": pkg.package_id,
            "scenario_id": pkg.scenario_id,
            "package_hash": pkg.compute_package_hash(),
        }


def locate_certificate_file(run_id: str) -> Path | None:
    """
    Authoritative canonical certificate locator across the AgentV ecosystem.
    Searches:
      1. Published reports vault: reports/certificates/<run_id>_vc.json
      2. Per-run storage vault: runs/<run_id>/run_manifest.json
      3. Legacy vault certificates: runs/<run_id>/<run_id>_certificate.json
         or runs/<run_id>/<run_id>_vc.json
    Returns the resolved Path if it exists, or None.
    """
    if not run_id or not isinstance(run_id, str) or ".." in run_id:
        return None

    reports_dir = Path(config.REPORTS_DIR)
    runs_dir = Path(config.RUN_LOG_DIR)

    candidates = [
        reports_dir / "certificates" / f"{run_id}_vc.json",
        runs_dir / run_id / "run_manifest.json",
        runs_dir / run_id / f"{run_id}_certificate.json",
        runs_dir / run_id / f"{run_id}_vc.json",
        reports_dir / "certificates" / f"{run_id}_certificate.json",
    ]
    for c in candidates:
        if c.is_file():
            return c.resolve()
    return None
