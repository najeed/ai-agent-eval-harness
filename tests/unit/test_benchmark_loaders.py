"""Real benchmark loading, schema conformance, and fail-closed dataset boundaries."""

import json
import sys
from types import SimpleNamespace

import pytest

from eval_runner.benchmarks import BENCHMARK_REGISTRY
from eval_runner.benchmarks.assistantbench import AssistantBenchmark
from eval_runner.benchmarks.gaia import GAIABenchmark
from eval_runner.loader import get_universal_registry, load_scenario


@pytest.mark.parametrize(
    "benchmark_name,loader,row",
    [
        (
            "gaia",
            GAIABenchmark,
            {"task_id": "task-a", "Question": "What is 2 + 2?", "Final answer": "4"},
        ),
        (
            "assistantbench",
            AssistantBenchmark,
            {"id": "task-a", "task": "What is 2 + 2?", "answer": "4"},
        ),
    ],
)
@pytest.mark.parametrize("extension", ["json", "jsonl", "parquet"])
def test_benchmark_real_rows_preserve_answers_and_validate_schema(
    tmp_path, benchmark_name, loader, row, extension
):
    path = tmp_path / f"rows.{extension}"
    if extension == "parquet":
        pd = pytest.importorskip("pandas")
        pytest.importorskip("pyarrow")
        pd.DataFrame([row]).to_parquet(path)
    else:
        path.write_text(json.dumps([row] if extension == "json" else row), encoding="utf-8")
    scenarios = load_scenario(f"{benchmark_name}://{path.as_posix()}")
    assert BENCHMARK_REGISTRY[benchmark_name] is loader
    assert loader.load(str(path)) == scenarios
    assert scenarios[0]["workflow"]["nodes"][0]["expected_outcome"][0]["expected"] == "4"
    assert scenarios[0]["metadata"]["benchmark"]["source_id"] == "task-a"
    from pathlib import Path

    import jsonschema

    schema = json.loads(Path("spec/aes/aes.schema.json").read_text(encoding="utf-8"))
    schema["$id"] = "https://agentvos.ai/spec/aes/aes.schema.json"
    jsonschema.Draft7Validator(schema, registry=get_universal_registry()).validate(scenarios[0])


@pytest.mark.parametrize("loader", [GAIABenchmark, AssistantBenchmark])
@pytest.mark.parametrize("source", ["", "validation", "missing.json"])
def test_benchmark_missing_source_never_fabricates(loader, source):
    with pytest.raises(FileNotFoundError):
        loader.load(source)


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        "[]",
        "{}",
        "[null]",
        '[{"question":"q"}]',
        '[{"question":"", "answer":"a"}]',
        '[{"question":"q", "answer":null}]',
    ],
)
def test_benchmark_malformed_dataset_rejected(tmp_path, content):
    path = tmp_path / "bad.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        GAIABenchmark.load(str(path))


def test_benchmark_duplicate_identity_rejected(tmp_path):
    row = {"task_id": "duplicate", "Question": "Q", "Final answer": "A"}
    path = tmp_path / "duplicates.json"
    path.write_text(json.dumps([row, row]), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        GAIABenchmark.load(str(path))


def test_benchmark_huggingface_configuration_is_explicit(monkeypatch):
    calls = []

    def load_dataset(path, **options):
        calls.append((path, options))
        return [{"task_id": "remote-a", "Question": "Q", "Final answer": "A"}]

    monkeypatch.setitem(sys.modules, "datasets", SimpleNamespace(load_dataset=load_dataset))
    monkeypatch.setattr("eval_runner.config.is_airgapped", lambda: False)
    assert GAIABenchmark.load("hf://owner/dataset?config=all&split=train&revision=fixed")
    assert calls == [("owner/dataset", {"name": "all", "split": "train", "revision": "fixed"})]


def test_benchmark_huggingface_airgap_never_downloads(monkeypatch):
    from eval_runner.exceptions import AirgappedConfigurationError

    monkeypatch.setattr("eval_runner.config.is_airgapped", lambda: True)
    with pytest.raises(AirgappedConfigurationError):
        GAIABenchmark.load("hf://owner/dataset")


def test_optional_dataset_dependency_failure_is_explicit(monkeypatch):
    import builtins

    original_import = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name == "datasets":
            raise ModuleNotFoundError("datasets unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("eval_runner.config.is_airgapped", lambda: False)
    monkeypatch.setattr(builtins, "__import__", unavailable)
    with pytest.raises(ValueError, match="optional datasets package"):
        GAIABenchmark.load("hf://owner/dataset")


@pytest.mark.parametrize(
    "uri",
    [
        "hf://",
        "hf://owner/data?split=",
        "hf://owner/data?split=a&split=b",
        "hf://owner/data?untrusted=code",
    ],
)
def test_remote_dataset_options_cannot_be_ambiguous(monkeypatch, uri):
    monkeypatch.setattr("eval_runner.config.is_airgapped", lambda: False)
    with pytest.raises(ValueError):
        GAIABenchmark.load(uri)


@pytest.mark.parametrize("identity", [None, "", " ", [], True])
def test_benchmark_rejects_malformed_explicit_identity(tmp_path, identity):
    path = tmp_path / "invalid-identity.json"
    path.write_text(
        json.dumps([{"task_id": identity, "Question": "Q", "Final answer": "A"}]), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="identity"):
        GAIABenchmark.load(str(path))


def test_benchmark_wrapped_json_preserves_unicode_and_file_context(tmp_path):
    row = {"Question": "How many résumé files?", "Final answer": "1", "file_name": "résumé.pdf"}
    path = tmp_path / "dataset with spaces.json"
    path.write_text(json.dumps({"data": [row]}), encoding="utf-8")
    result = GAIABenchmark.load(str(path))[0]
    assert result["initial_state"]["benchmark_context"]["file_name"] == "résumé.pdf"
    assert result["workflow"]["nodes"][0]["task_description"] == row["Question"]


def test_benchmark_does_not_return_partial_jsonl_or_accept_nonfinite_values(tmp_path):
    path = tmp_path / "rows.jsonl"
    row = {"Question": "Q", "Final answer": "A"}
    path.write_text(json.dumps(row) + "\n{incomplete", encoding="utf-8")
    with pytest.raises(ValueError):
        GAIABenchmark.load(str(path))
    path.write_text(json.dumps({**row, "metadata": float("nan")}), encoding="utf-8")
    with pytest.raises(ValueError):
        GAIABenchmark.load(str(path))


def test_benchmark_unsupported_format_is_explicit(tmp_path):
    path = tmp_path / "rows.csv"
    path.write_text("Question,answer\nQ,A", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported"):
        GAIABenchmark.load(str(path))


def test_benchmark_parquet_engine_is_optional_without_data_substitution(tmp_path, monkeypatch):
    pd = pytest.importorskip("pandas")
    path = tmp_path / "rows.parquet"
    path.touch()

    def unavailable(*args, **kwargs):
        raise ImportError("Parquet engine missing")

    monkeypatch.setattr(pd, "read_parquet", unavailable)
    with pytest.raises(ValueError, match="Parquet engine"):
        GAIABenchmark.load(str(path))
