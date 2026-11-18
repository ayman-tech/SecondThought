import json
from pathlib import Path

import pytest
import torch

from secondthought.lab.catalog import Catalog, CatalogSpec, checksum


@pytest.fixture
def catalog_files(tmp_path):
    artifact = dict(format_version=1, model_id='test/model', model_revision='a'*40,
        tokenizer_revision='a'*40, feature='formality', site='decoder_block_output',
        layer_count=2, hidden_size=2,
        candidates={'first': {'layer_index': 0, 'pooling': 'mean', 'site': 'decoder_block_output'},
                    'last': {'layer_index': 1, 'pooling': 'final_token', 'site': 'decoder_block_output'}},
        raw_directions={'first': torch.tensor([3.,4.]), 'last': torch.tensor([0.,2.])})
    path = tmp_path/'directions.pt'
    torch.save(artifact, path)
    manifest = dict(schema_version=1, id='test-catalog',
        models=[dict(id='test',repository='test/model',revision='a'*40,layer_count=2,
                     hidden_size=2,adapter='qwen2_decoder_output_v1')],
        features=[dict(id='formality',label='Formality',positive_direction='target minus source')],
        artifacts=[dict(id='directions',path='directions.pt',sha256=checksum(path),
                        model_id='test',feature_id='formality',model_revision='a'*40,format='all_layers_v1')],
        vectors=[dict(id='raw',model_id='test',feature_id='formality',artifact_id='directions',
                      candidate='first',layer_index=0,pooling='mean',scale='raw',raw_norm=5),
                 dict(id='unit',model_id='test',feature_id='formality',artifact_id='directions',
                      candidate='last',layer_index=1,pooling='final_token',scale='unit_l2',raw_norm=2)],
        layer_defaults=[dict(model_id='test',layer_index=0,vector_id='raw'),
                        dict(model_id='test',layer_index=1,vector_id='unit')])
    return manifest, artifact, path


def load(files):
    manifest, _, path = files
    return Catalog(CatalogSpec.model_validate(manifest), path.parent)


def test_raw_and_unit_vectors_are_checked_and_cannot_be_mutated_by_callers(catalog_files):
    catalog = load(catalog_files)
    assert not catalog.issues
    assert torch.equal(catalog.vector('raw'), torch.tensor([3.,4.]))
    assert torch.equal(catalog.vector('unit'), torch.tensor([0.,1.]))
    catalog.vector('raw').zero_()
    assert catalog.vector('raw').norm() == 5
    assert [x['available'] for x in catalog.layer_manifest('test')] == [True,True]
    public = catalog.public()
    assert all('path' not in artifact for artifact in public['artifacts'])
    assert 'experimental' in public['note']


def test_checksum_failure_disables_vectors_and_changes_no_manifest(catalog_files):
    manifest, _, path = catalog_files
    path.write_bytes(b'not the promoted artifact')
    catalog = load(catalog_files)
    assert catalog.issues['directions'] == 'checksum_mismatch'
    assert not any(x['available'] for x in catalog.layer_manifest('test'))
    with pytest.raises(ValueError,match='unavailable'):
        catalog.vector('raw')


@pytest.mark.parametrize('kind',['zero','nan','shape','pooling','revision','feature','site'])
def test_invalid_artifact_or_candidate_fails_closed(catalog_files, kind):
    manifest, artifact, path = catalog_files
    if kind == 'zero': artifact['raw_directions']['first'] = torch.zeros(2)
    if kind == 'nan': artifact['raw_directions']['first'] = torch.tensor([float('nan'),1.])
    if kind == 'shape': artifact['raw_directions']['first'] = torch.ones(3)
    if kind == 'pooling': artifact['candidates']['first']['pooling'] = 'final_token'
    if kind == 'revision': artifact['model_revision'] = 'b'*40
    if kind == 'feature': artifact['feature'] = 'detoxification'
    if kind == 'site': artifact['site'] = 'final_normalized_output'
    torch.save(artifact,path)
    manifest['artifacts'][0]['sha256'] = checksum(path)
    catalog = load(catalog_files)
    assert 'raw' in catalog.issues
    assert not catalog.layer_manifest('test')[0]['available']
    if kind in {'zero','nan','shape','pooling'}:
        assert catalog.layer_manifest('test')[1]['available']  # Unrelated vector stays available.


def test_duplicate_ids_and_incompatible_defaults_are_rejected(catalog_files):
    manifest, _, _ = catalog_files
    manifest['vectors'].append(dict(manifest['vectors'][0]))
    with pytest.raises(ValueError,match='Duplicate'):
        load(catalog_files)
    manifest['vectors'].pop()
    manifest['layer_defaults'][0]['vector_id'] = 'unit'
    with pytest.raises(ValueError,match='default'):
        load(catalog_files)


def test_artifacts_cannot_escape_root_even_through_symlinks(catalog_files,tmp_path):
    manifest, _, path = catalog_files
    outside = tmp_path.parent / f'{tmp_path.name}-outside.pt'
    outside.write_bytes(path.read_bytes())
    link = tmp_path/'escape.pt'
    link.symlink_to(outside)
    manifest['artifacts'][0]['path'] = 'escape.pt'
    with pytest.raises(ValueError,match='inside'):
        load(catalog_files)
    outside.unlink()


def test_version_is_stable_and_changes_with_intervention_scale(catalog_files):
    manifest, _, _ = catalog_files
    first = load(catalog_files).version
    assert load(catalog_files).version == first
    manifest['vectors'][0]['scale'] = 'unit_l2'
    assert load(catalog_files).version != first


def test_compilation_applies_all_tokens_and_always_cleans_up(catalog_files):
    from secondthought.lab.interventions import Intervention, compile_interventions, steering_context
    catalog = load(catalog_files)
    compiled = compile_interventions(catalog,'test',[Intervention(vector_id='raw',strength=0.5),
                                                    Intervention(vector_id='unit',strength=1)])
    layers = torch.nn.ModuleList([torch.nn.Identity(),torch.nn.Identity()])
    with pytest.raises(RuntimeError):
        with steering_context(layers,compiled):
            hidden = torch.zeros(2,3,2)
            for layer in layers:
                hidden = layer(hidden)
            assert torch.equal(hidden,torch.tensor([1.5,3.]).expand(2,3,2))
            raise RuntimeError('generation failure')
    assert all(not layer._forward_hooks for layer in layers)
    assert compile_interventions(catalog,'test',[Intervention(vector_id='raw',strength=0)]) == {}
    with pytest.raises(ValueError,match='model'):
        compile_interventions(catalog,'missing',[])
    for interventions in [[Intervention(vector_id='raw',strength=3)],
                          [Intervention(vector_id='raw',strength=1)]*2,
                          [Intervention(vector_id='missing',strength=0)]]:
        with pytest.raises(ValueError):
            compile_interventions(catalog,'test',interventions)


def test_multiple_directions_can_share_one_decoder_block(catalog_files):
    from secondthought.lab.interventions import Intervention, compile_interventions
    manifest, artifact, path = catalog_files
    artifact['candidates']['last']['layer_index'] = 0
    manifest['vectors'][1]['layer_index'] = 0
    manifest['layer_defaults'] = manifest['layer_defaults'][:1]
    torch.save(artifact,path)
    manifest['artifacts'][0]['sha256'] = checksum(path)
    catalog = load(catalog_files)
    compiled = compile_interventions(catalog,'test',[Intervention(vector_id='unit',strength=1),
                                                    Intervention(vector_id='raw',strength=0.5)])
    assert list(compiled) == [0]
    assert torch.equal(compiled[0],torch.tensor([1.5,3.]))


def test_promoted_catalog_has_full_coverage_and_preserves_reference_vectors():
    from secondthought.lab.catalog import get_catalog, ARTIFACT_ROOT
    catalog = get_catalog()
    assert not catalog.issues
    for feature in ('formality','detoxification'):
        entries = [v for v in catalog.spec.vectors if v.feature_id == feature and v.behavioral_status == 'experimental']
        assert {(v.layer_index,v.pooling) for v in entries} == {(i,p) for i in range(24) for p in ('mean','final_token')}
    for index in (0,4,11,21,22):
        vector = catalog.vectors[catalog.defaults[('qwen2.5-0.5b-instruct',index)]]
        artifact = catalog.artifacts[vector.artifact_id]
        assert artifact.format == 'legacy'
        data = torch.load(ARTIFACT_ROOT/artifact.path,map_location='cpu',weights_only=True)
        expected = data['raw_directions'][vector.candidate].float()
        if vector.scale == 'unit_l2':
            expected = expected/expected.norm().clamp_min(1e-12)
        assert torch.equal(catalog.vector(vector.id),expected)


def test_explicit_model_revision_reaches_snapshot_resolver(monkeypatch):
    from secondthought.steering_rewriter import resolve_model_source
    observed={}
    def download(**kwargs):
        observed.update(kwargs)
        return 'pinned-snapshot'
    monkeypatch.setattr('secondthought.steering_rewriter.snapshot_download',download)
    assert resolve_model_source('test/model',revision='a'*40) == 'pinned-snapshot'
    assert observed == dict(repo_id='test/model',revision='a'*40,local_files_only=True)
