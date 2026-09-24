"""
tests/unit/ci/test_acceptance_attestation.py
Unit tests for tools/ci/create_acceptance_attestation.py
and tools/ci/verify_acceptance_attestation.py.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from tools.ci.create_acceptance_attestation import (
    compute_case_result_root,
    compute_sha256,
    create_attestation,
    main as create_main,
    resolve_commit_sha,
)
from tools.ci.verify_acceptance_attestation import (
    main as verify_main,
    verify_attestation,
)


def test_compute_sha256_and_case_root(tmp_path):
    # 1. Byte and file hash
    data = b"test payload bytes"
    h_bytes = compute_sha256(data)
    test_file = tmp_path / "test.bin"
    test_file.write_bytes(data)
    h_file = compute_sha256(test_file)
    assert h_bytes == h_file

    # 2. Case result root computation
    results = [
        {"case_id": "AT-02", "accepted": True, "_internal": "ignored"},
        {"case_id": "AT-01", "accepted": True},
    ]
    root1 = compute_case_result_root(results)
    # Order independence in input list
    root2 = compute_case_result_root(list(reversed(results)))
    assert root1 == root2


def test_resolve_commit_sha(monkeypatch):
    # Explicit commit takes precedence
    assert resolve_commit_sha("explicit123") == "explicit123"

    # GITHUB_SHA environment variable
    monkeypatch.setenv("GITHUB_SHA", "env_sha_456")
    assert resolve_commit_sha() == "env_sha_456"

    # Git fallback or zero fallback
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    sha = resolve_commit_sha()
    assert len(sha) == 40


def test_create_and_verify_attestation_full_lifecycle(tmp_path, monkeypatch):
    summary_file = tmp_path / "acceptance-summary.json"
    manifest_file = tmp_path / "release.yaml"
    wheel_file = tmp_path / "agentv-2.0.0-py3-none-any.whl"
    attestation_file = tmp_path / "acceptance-attestation.json"

    wheel_file.write_bytes(b"PK\x03\x04fake_wheel_content")
    manifest_content = (
        "manifest_version: '1.0'\nname: test-suite\nthresholds:\n  allow_false_negatives: 0\n"
        "  allow_false_positives: 0\n  allow_security_failures: 0\n  allow_evidence_failures: 0\n"
        "  allow_execution_errors: 0\ncases:\n  - tests/acceptance/corpus/AT-01.yaml\n"
    )
    manifest_file.write_text(manifest_content, encoding="utf-8")

    summary_data = {
        "timestamp": "2026-09-24T10:00:00Z",
        "total_cases": 1,
        "passed_cases": 1,
        "failed_cases": 0,
        "false_negatives": 0,
        "false_positives": 0,
        "security_failures": 0,
        "evidence_failures": 0,
        "execution_errors": 0,
        "results": [{"case_id": "AT-01", "accepted": True}],
    }
    summary_file.write_text(json.dumps(summary_data), encoding="utf-8")

    # 1. Create attestation
    att = create_attestation(
        summary_path=summary_file,
        manifest_path=manifest_file,
        wheel_path=wheel_file,
        source_commit="commit_abc123",
        oracle_repo="org/agentv-tester",
        oracle_sha="oracle_def456",
        workflow_run_id="run_999",
    )
    assert att["gate_status"] == "PASSED"
    assert att["source_commit"] == "commit_abc123"
    attestation_file.write_text(json.dumps(att), encoding="utf-8")

    # 2. Verify attestation passes cleanly
    ok, reasons = verify_attestation(
        attestation_path=attestation_file,
        manifest_path=manifest_file,
        wheel_path=wheel_file,
        expected_commit="commit_abc123",
        expected_oracle_repo="org/agentv-tester",
        expected_oracle_sha="oracle_def456",
    )
    assert ok is True
    assert reasons == []

    # 3. Verify mismatch detections
    # Wheel tampered
    wheel_file.write_bytes(b"tampered bytes")
    ok_tamper, reasons_tamper = verify_attestation(
        attestation_path=attestation_file,
        manifest_path=manifest_file,
        wheel_path=wheel_file,
    )
    assert ok_tamper is False
    assert any("Wheel digest mismatch" in r for r in reasons_tamper)

    # Commit mismatch
    ok_commit, reasons_commit = verify_attestation(
        attestation_path=attestation_file,
        expected_commit="wrong_commit",
    )
    assert ok_commit is False
    assert any("Source commit mismatch" in r for r in reasons_commit)

    # Oracle repo & sha mismatch
    ok_oracle, reasons_oracle = verify_attestation(
        attestation_path=attestation_file,
        expected_oracle_repo="wrong/repo",
        expected_oracle_sha="wrong_sha",
    )
    assert ok_oracle is False
    assert any("Oracle repo mismatch" in r for r in reasons_oracle)
    assert any("Oracle SHA mismatch" in r for r in reasons_oracle)

    # Gate status FAILED check
    failed_att = dict(att)
    failed_att["gate_status"] = "FAILED"
    failed_att_file = tmp_path / "failed_att.json"
    failed_att_file.write_text(json.dumps(failed_att), encoding="utf-8")
    ok_failed, reasons_failed = verify_attestation(failed_att_file)
    assert ok_failed is False
    assert any("Gate status in attestation is 'FAILED'" in r for r in reasons_failed)

    # Missing file
    missing_file = tmp_path / "does_not_exist.json"
    ok_missing, reasons_missing = verify_attestation(missing_file)
    assert ok_missing is False
    assert any("Attestation file not found" in r for r in reasons_missing)

    # Corrupt JSON
    corrupt_file = tmp_path / "corrupt.json"
    corrupt_file.write_text("invalid json {", encoding="utf-8")
    ok_corrupt, reasons_corrupt = verify_attestation(corrupt_file)
    assert ok_corrupt is False
    assert any("Failed to parse attestation JSON" in r for r in reasons_corrupt)


def test_cli_entrypoints(tmp_path):
    summary_file = tmp_path / "acceptance-summary.json"
    manifest_file = tmp_path / "release.yaml"
    attestation_file = tmp_path / "acceptance-attestation.json"

    manifest_file.write_text(
        "manifest_version: '1.0'\nname: test\nthresholds:\n  allow_false_negatives: 0\n"
        "  allow_false_positives: 0\n  allow_security_failures: 0\n  allow_evidence_failures: 0\n"
        "  allow_execution_errors: 0\ncases:\n  - tests/acceptance/corpus/AT-01.yaml\n",
        encoding="utf-8",
    )
    summary_file.write_text(
        json.dumps(
            {
                "timestamp": "2026-09-24T10:00:00Z",
                "total_cases": 1,
                "passed_cases": 1,
                "failed_cases": 0,
                "false_negatives": 0,
                "false_positives": 0,
                "security_failures": 0,
                "evidence_failures": 0,
                "execution_errors": 0,
                "results": [{"case_id": "AT-01", "accepted": True}],
            }
        ),
        encoding="utf-8",
    )

    # 1. create_main
    with patch(
        "sys.argv",
        [
            "create_acceptance_attestation.py",
            "--summary",
            str(summary_file),
            "--manifest",
            str(manifest_file),
            "--output",
            str(attestation_file),
            "--source-commit",
            "1234567890123456789012345678901234567890",
        ],
    ):
        code_create = create_main()
        assert code_create == 0
        assert attestation_file.exists()

    # 2. verify_main pass
    with patch(
        "sys.argv",
        [
            "verify_acceptance_attestation.py",
            "--attestation",
            str(attestation_file),
            "--manifest",
            str(manifest_file),
            "--expected-commit",
            "1234567890123456789012345678901234567890",
        ],
    ):
        code_verify = verify_main()
        assert code_verify == 0

    # 3. verify_main fail
    with patch(
        "sys.argv",
        [
            "verify_acceptance_attestation.py",
            "--attestation",
            str(attestation_file),
            "--manifest",
            str(manifest_file),
            "--expected-commit",
            "different_commit",
        ],
    ):
        code_fail = verify_main()
        assert code_fail == 1
