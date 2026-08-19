"""
eval_runner.utils.safe_path
Centralized Safe Run Path Resolver and Filesystem Security Boundary Enforcement.
"""

from pathlib import Path

from eval_runner.utils.base import is_path_safe


class SafeRunPathResolver:
    """
    Centralized path-boundary abstraction for all store and file-based subsystems.
    Enforces strict isolation invariants to prevent directory traversal and filesystem escapes.
    """

    @staticmethod
    def validate_identifier(name: str, allow_nested: bool = False) -> str:
        """
        Validates that an identifier does not contain directory traversal
        patterns or invalid characters.
        """
        if not name or not isinstance(name, str):
            raise ValueError("Identifier must be a non-empty string")

        if "\x00" in name:
            raise PermissionError("Null byte injection detected in path identifier")

        clean = name.replace("\\", "/")
        if ".." in clean.split("/"):
            raise PermissionError(f"Directory traversal sequence detected in identifier: {name}")

        if not allow_nested and ("/" in clean or "\\" in name):
            raise PermissionError(
                f"Nested path separators not permitted in single-level identifier: {name}"
            )

        if clean.startswith("/") or (len(name) >= 2 and name[1] == ":"):
            raise PermissionError(f"Absolute path not allowed as relative identifier: {name}")

        return name

    @classmethod
    def resolve_run_dir(cls, base_dir: str | Path, run_id: str, create: bool = False) -> Path:
        """
        Resolves a run directory strictly under base_dir.
        """
        cls.validate_identifier(run_id, allow_nested=False)
        base_path = Path(base_dir).resolve()
        target = (base_path / run_id).resolve()

        if not target.is_relative_to(base_path) or not is_path_safe(target, base_path):
            raise PermissionError(f"Run ID '{run_id}' resolves outside base directory '{base_dir}'")

        if create:
            target.mkdir(parents=True, exist_ok=True)
        return target

    @classmethod
    def resolve_artifact_path(
        cls, run_dir: str | Path, artifact_name: str, allow_subdirs: bool = True
    ) -> Path:
        """
        Resolves an artifact path strictly within a run directory.
        """
        cls.validate_identifier(artifact_name, allow_nested=allow_subdirs)
        run_path = Path(run_dir).resolve()
        target = (run_path / artifact_name).resolve()

        if not target.is_relative_to(run_path) or not is_path_safe(target, run_path):
            raise PermissionError(
                f"Artifact '{artifact_name}' resolves outside run directory '{run_dir}'"
            )

        return target

    @classmethod
    def resolve_scenario_path(cls, base_dir: str | Path, scenario_path: str | Path) -> Path:
        """
        Resolves a scenario file path strictly within base_dir.
        """
        base_path = Path(base_dir).resolve()
        target = Path(scenario_path)
        if not target.is_absolute():
            target = base_path / target
        resolved = target.resolve()

        if not resolved.is_relative_to(base_path) or not is_path_safe(resolved, base_path):
            raise PermissionError(
                f"Scenario path '{scenario_path}' resolves outside allowed base directory "
                f"'{base_dir}'"
            )

        return resolved
