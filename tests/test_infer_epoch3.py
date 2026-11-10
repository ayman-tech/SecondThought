import csv
import json
import zipfile
from types import SimpleNamespace

import pytest

from secondthought.data import write_csv
from secondthought.inference_from_jsonl import (
    COLUMNS, encode_input, evaluated_row, prepare_model, read_inputs,
)


@pytest.mark.parametrize('contents, message', [
    ('not json', 'invalid JSON'),
    ('[]', 'nonempty strings'),
    ('{"id":"x","original_text":" "}', 'nonempty strings'),
    ('{"original_text":"hello"}', 'nonempty strings'),
    ('', 'empty'),
    ('{"id":"x","original_text":"a"}\n{"id":"x","original_text":"b"}', 'duplicate'),
])
def test_invalid_inputs(tmp_path, contents, message):
    path = tmp_path / 'input.jsonl'
    path.write_text(contents)
    with pytest.raises(ValueError, match=message):
        read_inputs(path)


def test_csv_matches_existing_schema(tmp_path):
    record = {'id': 'test_001', 'original_text': 'Send 12 boxes, idiot.'}
    row = evaluated_row(record, 'Send 12 boxes.', 12.345, 9, 6, '/model')
    output = tmp_path / 'result.csv'
    write_csv(output, [row])
    with output.open(newline='') as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(COLUMNS)
        result = next(reader)
    assert result['number_recall'] == '1.0'
    assert result['response_id'] == ''
    assert result['latency_ms'] == '12.35'
    assert result['input_tokens'] == '9'
    assert result['output_tokens'] == '6'
    assert result['timestamp_utc'].endswith('+00:00')


def test_long_input_is_not_truncated():
    def tokenizer(text, **kwargs):
        assert text.startswith('detoxify: ')
        assert kwargs['truncation'] is False
        return {'input_ids': SimpleNamespace(shape=(1, 129))}
    with pytest.raises(ValueError, match="'long'.*129.*128"):
        encode_input(tokenizer, {'id': 'long', 'original_text': 'text'})


def test_missing_model(tmp_path):
    with pytest.raises(FileNotFoundError, match='missing'):
        prepare_model(tmp_path / 'absent')


def test_archive_paths_and_existing_model(tmp_path):
    archive = tmp_path / 'model.zip'
    target = tmp_path / 'model'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('../outside.txt', 'bad')
    with pytest.raises(ValueError, match='Unexpected ZIP'):
        prepare_model(target, archive)
    assert not target.exists()
    assert not (tmp_path / 'outside.txt').exists()
    with zipfile.ZipFile(archive, 'w') as z:
        for name in ('config.json', 'model.safetensors', 'tokenizer_config.json', 'tokenizer.json'):
            z.writestr(f'model/{name}', '{}')
    assert prepare_model(target, archive) == target
    (target / 'config.json').write_text('preserved')
    prepare_model(target, archive)
    assert (target / 'config.json').read_text() == 'preserved'


def test_new_dataset():
    from secondthought.inference_from_jsonl import PROJECT_ROOT
    records = read_inputs(PROJECT_ROOT / 'data/workplace_eval/input.jsonl')
    sample = read_inputs(PROJECT_ROOT / 'data/workplace_eval/sample.jsonl')
    assert len(records) == 35
    assert len({row['original_text'] for row in records}) == 35
    assert not ({row['original_text'] for row in records} & {row['original_text'] for row in sample})
