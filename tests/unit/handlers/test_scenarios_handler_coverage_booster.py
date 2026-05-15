from unittest.mock import MagicMock, patch

import pytest

from eval_runner.handlers import scenarios


def test_classify_scenario_explicit():
    """Exercises explicit industry mapping (lines 28-35)."""
    scenario = {"metadata": {"industry": "Finance"}}
    res = scenarios.classify_scenario(scenario)
    assert res["industry"] == "fintech"
    assert res["confidence"] == 1.0


def test_classify_scenario_ml_fallback():
    """Exercises ML classification (lines 44-57) and fallback."""
    scenario = {"title": "Loan Application", "description": "Processing a bank loan"}

    # Mocking SentenceTransformer to trigger ML path or fallback
    with patch("sentence_transformers.SentenceTransformer") as mock_st:
        # Successful ML path
        mock_model = MagicMock()
        mock_model.encode.side_effect = [
            MagicMock(),
            MagicMock(),
        ]  # industry_embeddings, text_embedding
        mock_st.return_value = mock_model
        with patch("sentence_transformers.util.cos_sim", return_value=[MagicMock()]):
            res = scenarios.classify_scenario(scenario)
            assert "industry" in res

    # Exception fallback (line 61)
    with patch("sentence_transformers.SentenceTransformer", side_effect=Exception("No ML")):
        res = scenarios.classify_scenario(scenario)
        assert res["industry"] == "generic"


@pytest.mark.asyncio
async def test_handle_aes_validate_export(tmp_path):
    """Exercises export logic and loop failure (lines 118-124)."""
    export_file = tmp_path / "exported.yaml"
    args = MagicMock(path=str(tmp_path), export=str(export_file))

    # Create two dummy scenario files
    s1 = tmp_path / "s1.aes.yaml"
    s1.write_text("aes_version: 1.4\n")
    s2 = tmp_path / "s2.json"
    s2.write_text("{}")

    with patch("eval_runner.handlers.scenarios.validator_for") as mock_v_for:
        mock_val = MagicMock()
        # First succeeds, second fails
        mock_val.validate.side_effect = [None, Exception("Invalid Scenario")]
        mock_v_for.return_value = MagicMock(return_value=mock_val)

        await scenarios.handle_aes_validate(args)
        assert export_file.exists()


@pytest.mark.asyncio
async def test_handle_aes_validate_exception():
    """Exercises exception in handle_aes_validate (lines 127-129)."""
    with patch("pathlib.Path.parent", side_effect=Exception("Fail")):
        assert await scenarios.handle_aes_validate(MagicMock()) == 1


@pytest.mark.asyncio
async def test_handle_scenario_generate_coverage():
    """Exercises handle_scenario_generate (lines 245, 247-248)."""
    # 1. Success case
    with patch("eval_runner.scaffold.generate_interactive", return_value=None):
        assert await scenarios.handle_scenario_generate(MagicMock()) == 0

    # 2. Failure case
    with patch("eval_runner.scaffold.generate_interactive", side_effect=Exception("Fail")):
        assert await scenarios.handle_scenario_generate(MagicMock()) == 1


@pytest.mark.asyncio
async def test_handler_exceptions_remaining():
    """Exercises exceptions in remaining handlers."""
    # handle_inspect
    with patch("eval_runner.loader.load_scenario", side_effect=Exception("Fail")):
        assert await scenarios.handle_inspect(MagicMock()) == 1

    # handle_lint
    with patch("eval_runner.linter.run_lint", side_effect=Exception("Fail")):
        assert await scenarios.handle_lint(MagicMock()) == 1

    # handle_list
    with patch("eval_runner.catalog.ScenarioCatalog.load_index", side_effect=Exception("Fail")):
        assert await scenarios.handle_list(MagicMock(refresh=False)) == 1

    # handle_catalog_search
    with patch("eval_runner.catalog.ScenarioCatalog", side_effect=Exception("Fail")):
        assert await scenarios.handle_catalog_search(MagicMock()) == 1

    # handle_mutate
    with patch("os.path.exists", side_effect=Exception("Fail")):
        assert await scenarios.handle_mutate(MagicMock()) == 1

    # handle_spec_to_eval
    with patch("os.path.exists", side_effect=Exception("Fail")):
        assert await scenarios.handle_spec_to_eval(MagicMock()) == 1

    # handle_catalog_refresh
    with patch("eval_runner.catalog.ScenarioCatalog", side_effect=Exception("Fail")):
        assert await scenarios.handle_catalog_refresh(MagicMock()) == 1
