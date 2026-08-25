import re

from eval_runner.runner import new_run_id


def test_new_run_id_shape_and_uniqueness():
    ids = {new_run_id("loan_flow") for _ in range(1000)}
    assert len(ids) == 1000
    pattern = re.compile(r"^run-loan_flow-[0-9a-f]{32}$")
    assert all(pattern.match(i) for i in ids)
