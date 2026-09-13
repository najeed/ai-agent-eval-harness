"""
agentv_runtime.scenario
Authoritative Scenario Definition and Canonical Scenario IR Contracts (v2.0.0).

Defines the first two stages of the 6-stage lifecycle:
    compose (ScenarioDefinition) -> Canonical Scenario IR (CanonicalScenarioIR)
        -> execute (ExecutionManifest, RunTrace)
        -> evaluate (EvaluationResult)
        -> verify (VerificationResult)
        -> certify (VerificationCertificate)
        -> package (VerificationPackage)

Guarantees stable node/edge identity and deterministic hashing across platforms.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from agentv_runtime.canonical import canonical_json_encode
from agentv_runtime.manifest import compute_scenario_hash


def _canonical_json_bytes(data: Any) -> bytes:
    """Serializes data to canonical RFC 8785 JSON bytes (deterministic key ordering, UTF-8)."""
    return canonical_json_encode(data)


@dataclass(frozen=True)
class ScenarioDefinition:
    """
    Authoritative contract representing a composed scenario definition prior to IR compilation.
    Produced by the Scenario Composer, scenario loaders, or authoring tools.
    """

    scenario_id: str
    scenario_version: str = "1.0.0"
    definition: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "2.0.0"
    producer_identity: str = "agentv.scenario_composer"
    producer_version: str = "2.0.0"
    content_hash: str = ""
    parent_artifact_refs: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.content_hash:
            computed = self.compute_content_hash()
            object.__setattr__(self, "content_hash", computed)

    def compute_content_hash(self) -> str:
        """Computes deterministic SHA3-256 hash using the canonical scenario hashing algorithm."""
        if self.definition:
            return compute_scenario_hash(self.definition)
        payload = {
            "scenario_id": self.scenario_id,
            "scenario_version": self.scenario_version,
            "metadata": self.metadata,
        }
        return f"sha3_256:{hashlib.sha3_256(_canonical_json_bytes(payload)).hexdigest()}"

    def compile(self) -> CanonicalScenarioIR:
        """Compiles the ScenarioDefinition into canonical Scenario IR."""
        return CanonicalScenarioIR.from_scenario(self.definition)

    def to_dict(self) -> dict[str, Any]:
        """Serializes ScenarioDefinition to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ScenarioDefinition:
        """Constructs ScenarioDefinition from dictionary."""
        return cls(
            scenario_id=str(data.get("scenario_id", "")),
            scenario_version=str(data.get("scenario_version", "1.0.0")),
            definition=dict(data.get("definition") or {}),
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(data.get("schema_version", "2.0.0")),
            producer_identity=str(data.get("producer_identity", "agentv.scenario_composer")),
            producer_version=str(data.get("producer_version", "2.0.0")),
            content_hash=str(data.get("content_hash", "")),
            parent_artifact_refs=list(data.get("parent_artifact_refs") or []),
        )


@dataclass(frozen=True)
class CanonicalScenarioIR:
    """
    Authoritative compiled Scenario IR with stable node/edge identity,
    failure policy, and evaluation plan. Acts as the canonical source of truth for execution.
    """

    scenario_id: str
    scenario_version: str = "1.0.0"
    ir_version: str = "2.0.0"
    nodes: dict[str, Any] = field(default_factory=dict)
    edges: list[dict[str, Any]] = field(default_factory=list)
    entry_node_ids: list[str] = field(default_factory=list)
    failure_policy: str = "fail_fast"
    evaluation_plan: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "2.0.0"
    producer_identity: str = "agentv.execution_ir"
    producer_version: str = "2.0.0"
    content_hash: str = ""
    parent_artifact_refs: list[str] = field(default_factory=list)
    is_authoritative: bool = True

    def __post_init__(self):
        if not self.content_hash:
            computed = self.compute_content_hash()
            object.__setattr__(self, "content_hash", computed)

    def compute_content_hash(self) -> str:
        """
        Computes deterministic SHA3-256 hash over canonical IR payload
        with stable node/edge ordering.
        """
        payload = {
            "entry_node_ids": sorted(self.entry_node_ids),
            "evaluation_plan": self.evaluation_plan,
            "failure_policy": self.failure_policy,
            "ir_version": self.ir_version,
            "nodes": {k: self.nodes[k] for k in sorted(self.nodes.keys())},
            "edges": sorted(
                self.edges,
                key=lambda e: (
                    e.get("priority", 100),
                    e.get("from_node", e.get("from", "")),
                    e.get("to_node", e.get("to", "")),
                    e.get("edge_id", ""),
                ),
            ),
            "scenario_id": self.scenario_id,
            "scenario_version": self.scenario_version,
        }
        return f"sha3_256:{hashlib.sha3_256(_canonical_json_bytes(payload)).hexdigest()}"

    def to_dict(self) -> dict[str, Any]:
        """Serializes CanonicalScenarioIR to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CanonicalScenarioIR:
        """Constructs CanonicalScenarioIR from dictionary."""
        return cls(
            scenario_id=str(data.get("scenario_id", "")),
            scenario_version=str(data.get("scenario_version", "1.0.0")),
            ir_version=str(data.get("ir_version", "2.0.0")),
            nodes=dict(data.get("nodes") or {}),
            edges=list(data.get("edges") or []),
            entry_node_ids=list(data.get("entry_node_ids") or []),
            failure_policy=str(data.get("failure_policy", "fail_fast")),
            evaluation_plan=dict(data.get("evaluation_plan") or {}),
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(data.get("schema_version", "2.0.0")),
            producer_identity=str(data.get("producer_identity", "agentv.execution_ir")),
            producer_version=str(data.get("producer_version", "2.0.0")),
            content_hash=str(data.get("content_hash", "")),
            parent_artifact_refs=list(data.get("parent_artifact_refs") or []),
            is_authoritative=bool(data.get("is_authoritative", True)),
        )

    @classmethod
    def from_scenario(cls, scenario_data: Mapping[str, Any]) -> CanonicalScenarioIR:
        """
        Compiles scenario data into canonical IR representation with stable node/edge identity.
        """
        meta = dict(scenario_data.get("metadata") or {})
        scen_id = meta.get("id") or str(scenario_data.get("id", "unnamed_scenario"))
        scen_version = str(meta.get("version") or scenario_data.get("version", "1.0.0"))
        scen_hash = compute_scenario_hash(scenario_data)

        # Import compiler if available
        nodes: dict[str, Any] = {}
        edges: list[dict[str, Any]] = []
        entry_node_ids: list[str] = []
        failure_policy = "fail_fast"
        eval_plan_dict: dict[str, Any] = {}
        ir_version = "2.0.0"
        is_authoritative = True

        try:
            from eval_runner.execution_ir import compile_workflow

            plan = compile_workflow(dict(scenario_data))
            for n_id, n_ir in plan.nodes.items():
                nodes[n_id] = {
                    "node_id": n_ir.node_id,
                    "is_entry": n_ir.is_entry,
                    "definition": n_ir.definition,
                }
            for e_ir in plan.edges:
                edges.append(
                    {
                        "edge_id": e_ir.edge_id,
                        "from_node": e_ir.from_node,
                        "to_node": e_ir.to_node,
                        "type": str(e_ir.type),
                        "priority": e_ir.priority,
                        "declaration_index": e_ir.declaration_index,
                        "predicate": e_ir.predicate.to_evidence() if e_ir.predicate else None,
                    }
                )
            entry_node_ids = list(plan.entry_node_ids)
            failure_policy = str(plan.failure_policy)
            if plan.evaluation_plan:
                eval_plan_dict = plan.evaluation_plan.to_dict()
        except (ImportError, ModuleNotFoundError):
            # Fallback direct normalization: ONLY when compiler is unavailable.
            # Semantic and validation failures must NEVER be caught or downgraded.
            ir_version = "0.1.0-nonauthoritative-fallback"
            is_authoritative = False
            wf = scenario_data.get("workflow", {})
            if isinstance(wf, dict):
                raw_nodes = wf.get("nodes", [])
                for idx, n in enumerate(raw_nodes):
                    if isinstance(n, dict) and "id" in n:
                        nodes[n["id"]] = {"node_id": n["id"], "is_entry": idx == 0, "definition": n}
                        if idx == 0:
                            entry_node_ids.append(n["id"])
                for idx, e in enumerate(wf.get("edges", [])):
                    if isinstance(e, dict):
                        edges.append(
                            {
                                "edge_id": e.get("id", f"e_{idx}"),
                                "from_node": e.get("from", ""),
                                "to_node": e.get("to", ""),
                                "type": e.get("type", "sequential"),
                                "priority": e.get("priority", 100),
                                "declaration_index": idx,
                            }
                        )
            elif isinstance(wf, list):
                for idx, n in enumerate(wf):
                    if isinstance(n, dict) and "id" in n:
                        nodes[n["id"]] = {"node_id": n["id"], "is_entry": idx == 0, "definition": n}
                        if idx == 0:
                            entry_node_ids.append(n["id"])
                node_keys = list(nodes.keys())
                for idx, (a, b) in enumerate(zip(node_keys, node_keys[1:], strict=False)):
                    edges.append(
                        {
                            "edge_id": f"seq_{idx}",
                            "from_node": a,
                            "to_node": b,
                            "type": "sequential",
                            "priority": 100,
                            "declaration_index": idx,
                        }
                    )

        return cls(
            scenario_id=scen_id,
            scenario_version=scen_version,
            ir_version=ir_version,
            nodes=nodes,
            edges=edges,
            entry_node_ids=entry_node_ids,
            failure_policy=failure_policy,
            evaluation_plan=eval_plan_dict,
            metadata=meta,
            schema_version="2.0.0",
            producer_identity="agentv.execution_ir",
            producer_version="2.0.0",
            parent_artifact_refs=[scen_hash] if scen_hash else [],
            is_authoritative=is_authoritative,
        )


# Canonical alias for Scenario IR
ScenarioVersion = CanonicalScenarioIR

__all__ = [
    "ScenarioDefinition",
    "CanonicalScenarioIR",
    "ScenarioVersion",
]
