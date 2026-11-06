"""Shared dataset transport and strict benchmark-to-AES projection."""

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from agentv_runtime.canonical import canonical_json_encode
from eval_runner import config
from eval_runner.utils import crypto


def _read_rows(uri: str) -> list[Any]:
    if uri.startswith("hf://"):
        from eval_runner.exceptions import AirgappedConfigurationError

        if config.is_airgapped():
            raise AirgappedConfigurationError("Remote benchmark loading is disabled in airgap mode")
        parsed = urlsplit(uri)
        dataset = f"{parsed.netloc}{parsed.path}".strip("/")
        query = parse_qs(parsed.query, keep_blank_values=True)
        if not dataset or set(query) - {"split", "config", "revision"}:
            raise ValueError("Expected hf://dataset?split=...&config=...&revision=...")
        if any(len(values) != 1 or not values[0] for values in query.values()):
            raise ValueError("Dataset options must have exactly one nonempty value")
        try:
            from datasets import load_dataset
        except ImportError as exc:
            raise ValueError("HuggingFace sources require the optional datasets package") from exc
        options = {key: values[0] for key, values in query.items()}
        name = options.pop("config", None)
        revision = options.pop("revision", "main")
        options.setdefault("split", "validation")
        return list(load_dataset(dataset, name=name, revision=revision, **options))

    path = Path(uri).expanduser()
    if not uri.strip() or not path.is_file():
        raise FileNotFoundError(f"Benchmark dataset not found: {uri!r}")
    suffix = path.suffix.lower()
    try:
        if suffix == ".json":
            rows = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(rows, dict):
                rows = rows.get("data", rows.get("rows"))
        elif suffix == ".jsonl":
            rows = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8-sig").splitlines()
                if line.strip()
            ]
        elif suffix == ".parquet":
            try:
                import pandas as pd

                rows = pd.read_parquet(path).to_dict(orient="records")
            except ImportError as exc:
                raise ValueError("Parquet sources require pandas and a Parquet engine") from exc
        else:
            raise ValueError(f"Unsupported benchmark dataset format: {suffix}")
    except (UnicodeError, TypeError) as exc:
        raise ValueError(f"Invalid benchmark dataset: {path.name}") from exc
    if not isinstance(rows, list):
        raise ValueError("Benchmark dataset must contain a list of records")
    return rows


def load_benchmark(
    uri: str, benchmark: str, questions: tuple[str, ...], answers: tuple[str, ...]
) -> list[dict[str, Any]]:
    """Require real questions and answers; publish no partial dataset on a bad row."""
    uri = str(uri)
    if uri.startswith(f"{benchmark}://"):
        uri = uri.split("://", 1)[1]
    if not uri.startswith("hf://"):
        uri = Path(unquote(uri)).expanduser().resolve().as_posix() if uri.strip() else ""
    rows = _read_rows(uri)
    if not rows:
        raise ValueError("Benchmark dataset is empty")
    scenarios = []
    identities = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"Benchmark row {index} must be an object")
        question = next((row[key] for key in questions if key in row), None)
        answer = next((row[key] for key in answers if key in row), None)
        if not isinstance(question, str) or not question.strip() or answer is None or answer == "":
            raise ValueError(f"Benchmark row {index} requires a nonempty question and answer")
        digest = crypto.checksum(canonical_json_encode(row))
        source_id = row.get("task_id", row.get("id", digest))
        if not isinstance(source_id, (str, int)) or isinstance(source_id, bool):
            raise ValueError(f"Benchmark row {index} has an invalid identity")
        if isinstance(source_id, str) and not source_id.strip():
            raise ValueError(f"Benchmark row {index} has an empty identity")
        identity = f"{benchmark}-{crypto.checksum(str(source_id))[:24]}"
        if identity in identities:
            raise ValueError(f"Duplicate benchmark identity at row {index}")
        identities.add(identity)
        scenarios.append(
            {
                "aes_version": config.AES_VERSION,
                "metadata": {
                    "id": identity,
                    "name": f"{benchmark}: {source_id}",
                    "compliance_level": "Standard",
                    "benchmark": {
                        "name": benchmark,
                        "source": uri,
                        "source_id": source_id,
                        "row_digest": f"sha3_256:{digest}",
                    },
                },
                "workflow": {
                    "nodes": [
                        {
                            "id": "answer",
                            "task_description": question,
                            "expected_outcome": [
                                {"target": "message", "expected": answer, "mode": "exact"}
                            ],
                        }
                    ],
                    "edges": [],
                },
                "initial_state": {
                    "benchmark_context": {
                        key: row[key]
                        for key in ("file_name", "file_path", "Level", "level")
                        if key in row
                    }
                },
                "evaluation": {},
            }
        )
    return scenarios
