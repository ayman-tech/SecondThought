"""Exercise notebook data generation/export with a mocked teacher, never API calls."""
import csv
import json
from pathlib import Path
from types import SimpleNamespace

import nbformat
import pytest

from secondthought.lab.synthetic import read_jsonl, write_jsonl


NOTEBOOK = Path(__file__).resolve().parents[2] / 'research/steering_experimentation/empathy_synthetic_steering.ipynb'


def mock_connection(monkeypatch, key='sk-fixture-not-a-real-key-12345'):
    observed = []
    class Client:
        def __init__(self, **options):
            observed.append(options)
            self.models = SimpleNamespace(list=lambda: SimpleNamespace(
                data=[SimpleNamespace(id='mock-teacher')]))
    monkeypatch.setattr('getpass.getpass', lambda _: key)
    monkeypatch.setattr('openai.OpenAI', Client)
    monkeypatch.setattr('builtins.input', lambda _: 'mock-teacher')
    return observed


def run_notebook(tmp_path, monkeypatch, corrupt_source=False):
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    nbformat.validate(notebook)
    for index, cell in enumerate(notebook.cells):
        if cell.cell_type == 'code':
            compile(cell.source, f'notebook-cell-{index}', 'exec')
    namespace = {}
    exec(notebook.cells[1].source, namespace)
    namespace['RUN'] = tmp_path / 'empathy'
    exec(notebook.cells[3].source, namespace)
    monkeypatch.setenv('SYNTHETIC_TEACHER_MODEL', 'mock-teacher')
    monkeypatch.setenv('OPENAI_API_KEY', 'malformed-old-value')
    mock_connection(monkeypatch)
    exec(notebook.cells[5].source, namespace)
    assert namespace['TEACHER_READY']

    def fake_generate(run, provider, model, **kwargs):
        rows = []
        for index, request in enumerate(namespace['requests'][:kwargs['max_requests']]):
            original = namespace['ORIGINALS'][request['scenario_id']]
            # Structural fixtures only: not examples of validated empathy quality.
            low = original + (' Changed.' if corrupt_source and index == 0 else '')
            rows.append(dict(request_id=request['request_id'],
                experiment_id=namespace['manifest']['experiment_id'], status='generated',
                output=dict(low=low, high='I understand. ' + original),
                teacher=dict(provider='mock-test-fixture')))
        write_jsonl(run / 'responses.jsonl', rows)
        return dict(issued_requests=len(rows))

    namespace['generate'] = fake_generate
    exec(notebook.cells[7].source, namespace)
    for index in (9, 11):
        exec(notebook.cells[index].source, namespace)
    return notebook, namespace


def test_empathy_notebook_exports_exact_source_rewrite_pairs(tmp_path, monkeypatch):
    notebook, ns = run_notebook(tmp_path, monkeypatch)
    accepted = read_jsonl(ns['DATASET_DIR'] / 'accepted.jsonl')
    assert len(accepted) == 50
    sources = set(ns['ORIGINALS'].values())
    assert all(row['source'] in sources for row in accepted)
    assert {row['split'] for row in accepted} == {'extraction', 'heldout', 'test'}
    with (ns['DATASET_DIR'] / 'empathy_pairs.csv').open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 50
    assert set(rows[0]) == {'row_id', 'split', 'original', 'empathetic_rewrite'}
    assert all(row['original'] in sources for row in rows)
    exec(notebook.cells[11].source, ns)  # Exact inputs can be reused safely.


def test_empathy_notebook_rejects_teacher_changes_to_fixed_source(tmp_path, monkeypatch):
    _, ns = run_notebook(tmp_path, monkeypatch, corrupt_source=True)
    accepted = read_jsonl(ns['DATASET_DIR'] / 'accepted.jsonl')
    assert len(accepted) == 49
    rejected = read_jsonl(ns['RUN'] / 'source_copy_rejections.jsonl')
    assert rejected == [dict(request_id=ns['requests'][0]['request_id'], reason='original_was_changed')]


def test_empathy_notebook_does_not_silently_export_stale_pairs(tmp_path, monkeypatch):
    notebook, ns = run_notebook(tmp_path, monkeypatch)
    responses = ns['RESPONSES']
    rows = read_jsonl(responses)
    rows[0]['output']['high'] += ' More text.'
    write_jsonl(responses, rows)
    with pytest.raises(ValueError, match='fresh DATASET_DIR'):
        exec(notebook.cells[11].source, ns)
    metadata = json.loads((ns['DATASET_DIR'] / 'notebook_inputs.json').read_text())
    assert metadata['responses_sha256'] != ns['sha'](responses.read_bytes())


def test_notebook_prompts_for_model_and_does_not_display_key(tmp_path, monkeypatch, capsys):
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    monkeypatch.delenv('SYNTHETIC_TEACHER_MODEL', raising=False)
    key = 'sk-test-only-not-a-real-key-12345'
    monkeypatch.setenv('OPENAI_API_KEY', 'old-invalid-value')
    observed = mock_connection(monkeypatch, key)
    namespace = {}
    exec(notebook.cells[1].source, namespace)
    namespace['RUN'] = tmp_path
    exec(notebook.cells[5].source, namespace)
    assert namespace['TEACHER_READY']
    assert namespace['TEACHER_MODEL'] == 'mock-teacher'
    assert observed[0]['api_key'] == key
    assert key not in capsys.readouterr().out
    assert not list(tmp_path.iterdir())  # Setup does not persist credentials or call generation.


def test_notebook_rejects_pasted_code_and_invalidates_old_readiness(tmp_path, monkeypatch):
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    mock_connection(monkeypatch, 'import os; some pasted Python code')
    namespace = {'TEACHER_READY': True}
    exec(notebook.cells[1].source, namespace)
    namespace['RUN'] = tmp_path
    with pytest.raises(ValueError, match='full secret key'):
        exec(notebook.cells[5].source, namespace)
    assert not namespace['TEACHER_READY']
    with pytest.raises(RuntimeError, match='setup cell'):
        exec(notebook.cells[7].source, namespace)


def test_notebook_pipeline_wires_all_48_vectors_to_isolated_catalog(tmp_path, monkeypatch):
    import torch
    from secondthought.lab.catalog import Catalog
    notebook, ns = run_notebook(tmp_path, monkeypatch)
    base = Catalog.load()
    original_version = base.version

    def fake_extraction(command, **options):
        assert options == {'check': True}
        assert command[command.index('--dataset')+1] == str(ns['DATASET_DIR']/'pairs.jsonl')
        model = base.models['qwen2.5-0.5b-instruct']
        metadata = json.loads((ns['DATASET_DIR']/'pairs.metadata.json').read_text())
        vectors, candidates = {}, {}
        for layer in range(24):
            for pooling in ('mean', 'final_token'):
                name = f'layer{layer}_{pooling}'
                vectors[name] = torch.ones(model.hidden_size)*(layer+1)
                candidates[name] = dict(layer_index=layer, pooling=pooling,
                    heldout_pairs=10, heldout_ordering_accuracy=.7)
        artifact = dict(format_version=1, model_id=model.repository, model_revision=model.revision,
            tokenizer_revision=model.revision, feature='empathy', site='decoder_block_output',
            layer_count=24, hidden_size=model.hidden_size, raw_directions=vectors,
            candidates=candidates, provenance=metadata)
        path = ns['RUN']/f"vectors/qwen2_5_0_5b_empathy_all_layers_{ns['FEATURE']['version']}.pt"
        path.parent.mkdir()
        torch.save(artifact,path)

    monkeypatch.setattr('subprocess.run', fake_extraction)
    exec(notebook.cells[13].source, ns)
    exec(notebook.cells[15].source, ns)
    assert len(ns['empathy_vectors']) == 48
    assert ns['EXPERIMENT'].version != original_version
    assert Catalog.load().version == original_version
    assert {v.id for v in ns['EXPERIMENT'].spec.vectors if v.feature_id != 'empathy'} == {
        v.id for v in base.spec.vectors if v.feature_id != 'empathy'}
    assert '8004' in (ns['RUN']/'start_website.sh').read_text()
    # Idempotent cell reruns validate/reuse the same immutable extraction and catalog.
    exec(notebook.cells[13].source, ns)
    exec(notebook.cells[15].source, ns)


def test_extraction_waits_for_all_50_accepted_pairs(tmp_path, monkeypatch):
    notebook, ns = run_notebook(tmp_path, monkeypatch, corrupt_source=True)
    with pytest.raises(RuntimeError, match='all 50 accepted'):
        exec(notebook.cells[13].source, ns)


def test_reuse_only_migrates_identical_teacher_prompts(tmp_path, monkeypatch):
    from secondthought.lab.synthetic import make_plan, load_plan
    _, ns = run_notebook(tmp_path, monkeypatch)
    previous = tmp_path/'previous'
    make_plan(ns['FEATURE'], ns['SCENARIOS'][:30], previous, variants=1)
    old_plan, old_jobs = load_plan(previous)
    teacher = dict(provider='responses', model='mock-teacher', base_url=None, max_output_tokens=4096)
    (previous/'teacher.json').write_text(json.dumps(teacher))
    request = old_jobs[0]
    source = ns['ORIGINALS'][request['scenario_id']]
    write_jsonl(previous/'responses.jsonl', [dict(request_id=request['request_id'],
        experiment_id=old_plan['experiment_id'], status='generated', teacher=teacher,
        output=dict(low=source, high='I understand. '+source))])
    target = tmp_path/'migrated'
    plan = make_plan(ns['FEATURE'], ns['SCENARIOS'], target, variants=1)
    _, jobs = load_plan(target)
    assert ns['reuse_previous_pilot'](previous,target,plan,jobs) == 1
    row = read_jsonl(target/'responses.jsonl')[0]
    assert row['experiment_id'] == plan['experiment_id']
    assert row['reused_from']['request_id'] == request['request_id']
    assert row['reused_from']['experiment_id'] == old_plan['experiment_id']
    assert ns['reuse_previous_pilot'](previous,target,plan,jobs) == 0
