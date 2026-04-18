from eval_runner.metrics.accuracy import calculate_output_matches


def test_calculate_output_matches_empty_target():
    """Verify that no targets returns 1.0 (baseline)."""
    assert calculate_output_matches({}, "some summary") == 1.0
    assert calculate_output_matches({"expected": []}, "some summary") == 1.0


def test_calculate_output_matches_single_string():
    """Verify exact and partial string matching."""
    criterion = {"expected": "Success"}
    assert calculate_output_matches(criterion, "Operation Success") == 1.0
    assert calculate_output_matches(criterion, "Failure") == 0.0


def test_calculate_output_matches_list():
    """Verify multiple target matching (all or nothing score)."""
    criterion = {"expected": ["Success", "Done"]}
    # Full match
    assert calculate_output_matches(criterion, "Success - Task is Done") == 1.0
    # Partial match (1/2)
    assert calculate_output_matches(criterion, "Success - Not finished") == 0.5
    # No match
    assert calculate_output_matches(criterion, "Pending") == 0.0


def test_calculate_output_matches_regex():
    """Verify regex pattern support."""
    criterion = {"expected": ["regex:ID-\\d+"]}
    assert calculate_output_matches(criterion, "Case ID-123") == 1.0
    assert calculate_output_matches(criterion, "Case ID-ABC") == 0.0


def test_calculate_output_matches_mixed():
    """Verify mixed string and regex targets."""
    criterion = {"expected": ["Completed", "regex:TRX-[a-z]+"]}
    # TRX part is case-insensitive in search
    assert calculate_output_matches(criterion, "Completed TRX-abc") == 1.0
    assert calculate_output_matches(criterion, "Completed No TRX") == 0.5


def test_calculate_output_matches_non_string_summary():
    """Verify resilience with non-string summaries."""
    criterion = {"expected": "123"}
    assert calculate_output_matches(criterion, 123) == 1.0
    assert calculate_output_matches(criterion, None) == 0.0


def test_calculate_output_matches_non_standard_target():
    """Verify resilience with non-standard target types (ints)."""
    criterion = {"expected": 123}
    assert calculate_output_matches(criterion, "The key is 123") == 1.0
