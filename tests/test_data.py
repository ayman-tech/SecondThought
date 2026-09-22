import json

import pytest

from secondthought.data import read_csv, read_jsonl, write_csv, write_jsonl


def test_jsonl_round_trip(tmp_path):
    records = [{"id": "one", "original_text": "Message"}]
    path = tmp_path / "records.jsonl"

    write_jsonl(path, records)

    assert read_jsonl(path) == records


def test_jsonl_requires_core_fields(tmp_path):
    path = tmp_path / "invalid.jsonl"
    path.write_text(json.dumps({"id": "one"}) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="id and original_text"):
        read_jsonl(path)


def test_csv_round_trip(tmp_path):
    records = [
        {
            "id": "one",
            "original_text": "Original",
            "rewritten_text": "Rewrite",
        }
    ]
    path = tmp_path / "records.csv"

    write_csv(path, records)

    assert read_csv(path) == records
