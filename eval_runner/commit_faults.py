"""Atomic sandbox commits and fault observations at the actual write boundary."""

import copy
import threading

from eval_runner.mutation_evidence import evidence_hash
from eval_runner.utils.path_resolver import PathResolver


class RevisionConflict(RuntimeError):
    pass


class SandboxCommitBoundary:
    def __init__(self, sandbox):
        self.sandbox = sandbox
        self.revision = 0
        self._lock = threading.RLock()

    def commit(self, diff, params, agent, *, expected_revision=None):
        with self._lock:
            if expected_revision is not None and expected_revision != self.revision:
                raise RevisionConflict(
                    f"Revision conflict: expected {expected_revision}, actual {self.revision}"
                )
            sandbox = self.sandbox
            before = copy.deepcopy(sandbox.state)
            shared_before = copy.deepcopy(sandbox.shared_state.registry)
            revision = self.revision
            try:
                for path, value in diff.items():
                    sandbox._set_state_path(str(path), copy.deepcopy(value))
                if "shared_write" in params:
                    path = params["shared_write"].get("path")
                    if path and not sandbox.shared_state.write(
                        agent, path, params["shared_write"].get("value")
                    ):
                        raise PermissionError(f"Agent '{agent}' denied write access to '{path}'")
                if "shared_read" in params:
                    path = params["shared_read"].get("path")
                    if path and not sandbox.shared_state.can_read(agent, path):
                        raise PermissionError(f"Agent '{agent}' denied read access to '{path}'")
                    if path:
                        sandbox.shared_state.read(agent, path)
            except BaseException:
                sandbox.state.clear()
                sandbox.state.update(before)
                sandbox.shared_state.registry.clear()
                sandbox.shared_state.registry.update(shared_before)
                raise
            if diff or params.get("shared_write", {}).get("path"):
                self.revision += 1
            return {
                "before_hash": evidence_hash(before),
                "after_hash": evidence_hash(sandbox.state),
                "revision_before": revision,
                "revision_after": self.revision,
            }

    def prepare_partial(self, diff, node, execution):
        controller = self.sandbox.fault_controller
        identity = controller._identity("partial_commit", node, execution)
        before = {
            path: copy.deepcopy(PathResolver.resolve(self.sandbox.state, path)) for path in diff
        }
        changed = [path for path, value in diff.items() if before[path] != value]
        applicable = len(changed) >= 2
        selected = {changed[0]: diff[changed[0]]} if applicable else dict(diff)
        ref = controller._observe(
            "commit_proposed",
            identity,
            {
                "before": before,
                "proposed": copy.deepcopy(diff),
                "selected_paths": list(selected),
                "applicable": applicable,
            },
        )
        return selected, {
            "identity": identity,
            "refs": [ref],
            "before": before,
            "proposed": copy.deepcopy(diff),
            "selected": selected,
            "applicable": applicable,
        }

    def complete_partial(self, ticket):
        after = {
            path: copy.deepcopy(PathResolver.resolve(self.sandbox.state, path))
            for path in ticket["proposed"]
        }
        applied = [
            path
            for path in ticket["selected"]
            if after[path] == ticket["proposed"][path] and after[path] != ticket["before"][path]
        ]
        omitted = [
            path
            for path in ticket["proposed"]
            if path not in ticket["selected"]
            and after[path] == ticket["before"][path] != ticket["proposed"][path]
        ]
        delivered = ticket["applicable"] and bool(applied) and bool(omitted)
        observation = {
            "before": ticket["before"],
            "after": after,
            "proposed": ticket["proposed"],
            "applied_paths": applied,
            "omitted_paths": omitted,
        }
        controller = self.sandbox.fault_controller
        ref = controller._observe("partial_commit_observed", ticket["identity"], observation)
        return controller._receipt(
            ticket["identity"],
            [*ticket["refs"], ref],
            observation,
            delivery="DELIVERED" if delivered else "NOT_DELIVERED",
        )

    def stale_commit(self, diff, node, execution):
        controller = self.sandbox.fault_controller
        identity = controller._identity("stale_commit", node, execution)
        with self._lock:
            expected = self.revision
            ref = controller._observe(
                "revision_read", identity, {"revision": expected, "diff_hash": evidence_hash(diff)}
            )
            # A competing transaction really commits before the stale writer retries.
            competitor = self.commit(
                {next(iter(diff)): next(iter(diff.values()))}, {}, self.sandbox.current_agent
            )
            competing = controller._observe("competing_commit", identity, competitor)
            try:
                self.commit(diff, {}, self.sandbox.current_agent, expected_revision=expected)
            except RevisionConflict:
                observed = {
                    "expected_revision": expected,
                    "actual_revision": self.revision,
                    "blocked": True,
                }
                rejected = controller._observe("revision_guard_rejected", identity, observed)
                controller._receipt(identity, [ref, competing, rejected], observed)
                return observed
            raise RuntimeError("Stale transaction unexpectedly committed")
