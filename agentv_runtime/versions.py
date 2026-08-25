"""
agentv_runtime.versions — [F1] Single truth-version namespace.

Every wire-format contract version lives here and ONLY here. Producers must
import (never redeclare) so a bump cannot drift across surfaces:

    versions.py value                 consumed by
    --------------------------------- ------------------------------------
    EXECUTION_IR_VERSION              eval_runner.execution_ir
                                      (WorkflowPlan.ir_version; stamped on
                                      every execution_graph_node/edge event)

    EXTENSION_CONTRACT_VERSION        agentv_runtime.extension_contract +
                                      ui/visual-console types mirror
                                      (manifest api_version compatibility)

    VC_SCHEMA_VERSION                 eval_runner.verifier (run manifests,
                                      certificates; evidence_root_hash is an
                                      additive optional field within 3.0.0)

    VERIFICATION_PACKAGE_VERSION      console evidence packager
                                      (.agentv-package.json envelope)

ADAPTER ALIGNMENT NOTE
----------------------
Adapters speak THREE aligned contracts, each versioned here:
  1. IR          (execution): scenario -> WorkflowPlan -> graph events;
                 every event/result row carries ExecutionIdentity fields
                 bound by EXECUTION_IR_VERSION semantics.
  2. CONTRACTS   (trust):     RuntimeExtension manifests and VC certificates;
                 canonical bytes/hash algorithms never change within a major.
  3. RESULTS     (evidence):  task-result rows -> assertions -> Evidence Graph;
                 verification decisions commit to evidence_root_hash.
An adapter is compliant iff it preserves these three round-trips unchanged
within the major versions declared below.
"""

from __future__ import annotations

EXECUTION_IR_VERSION = "2.0.0"

EXTENSION_CONTRACT_VERSION = "1.0.0"

VC_SCHEMA_VERSION = "3.0.0"

VERIFICATION_PACKAGE_VERSION = "2.1.0"

__all__ = [
    "EXECUTION_IR_VERSION",
    "EXTENSION_CONTRACT_VERSION",
    "VC_SCHEMA_VERSION",
    "VERIFICATION_PACKAGE_VERSION",
]
