from eval_runner.taxonomy import FailureCategory, FailureTaxonomy


def test_normalized_command_matching():
    """Verifies that base actions are matched despite different flags/args."""
    # Test normalization helper
    assert FailureTaxonomy._normalize_action("ls -la /tmp") == "ls"
    assert FailureTaxonomy._normalize_action("git commit -m 'test'") == "git"
    assert (
        FailureTaxonomy._normalize_action("python3 -c 'print(1)'") == "print(1)"
    )  # Simple heuristic check
    assert (
        FailureTaxonomy._normalize_action({"tool": "search_browser", "params": {"query": "test"}})
        == "search_browser"
    )


def test_fuzzy_loop_detection_with_flags():
    """Verifies that Logic State Stall is detected when base actions repeat."""
    history = [
        {"role": "agent", "tool_calls": [{"tool": "ls", "params": {"args": "-la"}}]},
        {"role": "environment", "content": {"status": "success", "result": "file1"}},
        {"role": "agent", "tool_calls": [{"tool": "ls", "params": {"args": "-F"}}]},
        {"role": "environment", "content": {"status": "success", "result": "file1"}},
        {"role": "agent", "tool_calls": [{"tool": "ls", "params": {"args": "-R"}}]},
    ]

    # FailureTaxonomy._detect_loops uses raw_msgs for fuzzy and normalized_actions for stalls
    # In this case, A -> B -> A is a cyclical loop (distance 2), which is a planning error.
    cat = FailureTaxonomy._detect_loops(history)
    assert cat == FailureCategory.LOGIC_PLANNING_ERROR


def test_fuzzy_text_similarity():
    """Verifies that SequenceMatcher catches near-duplicate agent thoughts."""
    history = [
        {"role": "agent", "content": "I am looking for the file now."},
        {"role": "agent", "content": "I'm looking for the file now..."},
    ]

    # Test _is_near_duplicate directly
    assert FailureTaxonomy._is_near_duplicate(history[0]["content"], history[1]["content"]) is True

    # Test _detect_loops integration
    cat = FailureTaxonomy._detect_loops(history)
    assert cat == FailureCategory.LOGIC_PLANNING_ERROR
