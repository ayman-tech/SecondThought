"""Pytest configuration shared by every test."""

# test_infer_epoch3.py predates the current secondthought.inference_from_jsonl. It imports COLUMNS
# and evaluated_row, which no longer exist, so it cannot even be collected. Set aside here until it
# is rewritten against the current script; delete this line once it is.
collect_ignore = ["test_infer_epoch3.py"]
