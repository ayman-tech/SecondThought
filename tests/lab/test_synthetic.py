import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from secondthought.lab.synthetic import (
    FeatureDefinition,Scenario,Contrast,make_plan,load_plan,prepare,generate,validate_contrast,write_jsonl,
)
from secondthought.lab.experiments import publish_experiment
from secondthought.lab.catalog import Catalog


def definition():
    return dict(id='formality',version='synthetic-test',label='Formality',
        low='Informal conversational wording',high='Formal professional wording',scale='raw')


def scenarios():
    names=('Alex','Blair','Casey','Drew','Emery','Frankie','Gray','Harper','Indigo','Jules','Kai','Lee')
    return [dict(id=name,family='scenario-'+name,task='Write the request.',
        context=f'Ask {name} to send the report by 3 PM.',required_terms=[name,'3 PM']) for name in names]


def fixture_run(tmp_path):
    run=tmp_path/'run';make_plan(definition(),scenarios(),run)
    manifest,requests=load_plan(run)
    rows=[]
    for request in requests:
        name=request['scenario_id']
        rows.append(dict(request_id=request['request_id'],experiment_id=manifest['experiment_id'],
            status='generated',teacher={'provider':'handwritten_test_fixture'},
            output=dict(low=f'Hey {name}, send me the report by 3 PM.',
                        high=f'Please send me the report by 3 PM, {name}.')))
    write_jsonl(run/'responses.jsonl',rows)
    return run,manifest,requests,rows


def test_plan_splits_families_before_variants_and_detects_mutation(tmp_path):
    run=tmp_path/'run';make_plan(definition(),scenarios(),run,variants=3)
    _,jobs=load_plan(run)
    assert len(jobs)==36
    for family in {r['family'] for r in jobs}:
        assert len({r['split'] for r in jobs if r['family']==family})==1
    assert {r['split'] for r in jobs}=={'extraction','heldout','test'}
    (run/'requests.jsonl').write_text((run/'requests.jsonl').read_text()+'\n')
    with pytest.raises(ValueError,match='changed'):load_plan(run)


def test_plan_rejects_duplicate_context_crossing_families(tmp_path):
    rows=scenarios();rows[1]['context']=rows[0]['context'];rows[1]['required_terms']=[]
    with pytest.raises(ValueError,match='crosses'):make_plan(definition(),rows,tmp_path/'run')
    assert not (tmp_path/'run').exists()


def test_preparation_excludes_reserved_test_and_keeps_dataset_immutable(tmp_path):
    run,_,jobs,_=fixture_run(tmp_path)
    result=prepare(run)
    assert result['ready_for_extraction']
    pairs=[json.loads(line) for line in (run/'dataset/pairs.jsonl').read_text().splitlines()]
    evaluation=[json.loads(line) for line in (run/'dataset/evaluation.jsonl').read_text().splitlines()]
    assert len(evaluation)==2
    assert {r['split'] for r in pairs}=={'extraction','heldout'}
    assert {r['group'] for r in pairs}.isdisjoint({r['group'] for r in evaluation})
    metadata=json.loads((run/'dataset/pairs.metadata.json').read_text())
    assert metadata['summary']['review']=='heuristics_only_unreviewed'
    from research.steering_experimentation.extract_lab_vectors import load_prepared_pairs,validate_split
    extraction,heldout,_=load_prepared_pairs(run/'dataset/pairs.jsonl','formality')
    validate_split(extraction,heldout)
    with pytest.raises(ValueError,match='already exists'):prepare(run)


def test_validation_rejects_wrong_numbers_missing_terms_and_length_confound():
    feature=FeatureDefinition.model_validate(definition())
    scenario=Scenario.model_validate(scenarios()[0])
    pair=Contrast(low='Hey Alex, please send the report by 3 PM.',high='Alex, send the report by 4 PM please.')
    assert validate_contrast(pair,feature,scenario)=='numbers_differ'
    pair.high='Please send the report by 3 PM today.'
    assert validate_contrast(pair,feature,scenario)=='required_term_missing'
    pair.high=' '.join(['a']*80)
    assert validate_contrast(pair,feature,scenario)=='length_confound'


def test_unbound_duplicate_and_unapproved_imports_do_not_enter_extraction(tmp_path):
    run,_,_,rows=fixture_run(tmp_path)
    rows[0]['experiment_id']='wrong';write_jsonl(run/'responses.jsonl',rows)
    with pytest.raises(ValueError,match='not bound'):prepare(run)
    rows[0]['experiment_id']=rows[1]['experiment_id']
    write_jsonl(run/'responses.jsonl',rows+[rows[0]])
    with pytest.raises(ValueError,match='Duplicate'):prepare(run)
    write_jsonl(run/'responses.jsonl',rows)
    approvals=tmp_path/'approvals.json';approvals.write_text('[]')
    result=prepare(run,approvals=approvals)
    assert not result['ready_for_extraction']
    assert not (run/'dataset/pairs.jsonl').exists()


def test_generation_budget_resume_and_no_hidden_retries(tmp_path,monkeypatch):
    run=tmp_path/'run';make_plan(definition(),scenarios(),run)
    observed=[]
    class Client:
        def __init__(self,**kwargs):
            assert kwargs['max_retries']==0
            self.responses=self
        def create(self,**kwargs):
            observed.append(kwargs)
            assert kwargs['store'] is False
            return SimpleNamespace(output_text='{"low":"Example low text.","high":"Example high text."}',
                id='response',model='teacher-snapshot',usage=None)
    monkeypatch.setattr('openai.OpenAI',Client)
    assert generate(run,'responses','teacher',2)['issued_requests']==2
    assert generate(run,'responses','teacher',1)['issued_requests']==1
    assert len(observed)==3
    with pytest.raises(ValueError,match='settings changed'):generate(run,'responses','another-teacher',1)


def make_artifact(run,manifest,base):
    feature=manifest['configuration']['feature'];candidates={};vectors={}
    for i in range(24):
        for pool in ('mean','final_token'):
            name=f'layer{i}_{pool}'
            candidates[name]=dict(layer_index=i,pooling=pool,heldout_pairs=2,heldout_ordering_accuracy=1.)
            vectors[name]=torch.ones(896)*(i+1)
    data=dict(format_version=1,model_id=base.models['qwen2.5-0.5b-instruct'].repository,
        model_revision=base.models['qwen2.5-0.5b-instruct'].revision,
        tokenizer_revision=base.models['qwen2.5-0.5b-instruct'].revision,
        feature=feature['id'],site='decoder_block_output',layer_count=24,hidden_size=896,
        candidates=candidates,raw_directions=vectors,
        provenance=dict(experiment_id=manifest['experiment_id'],definition=FeatureDefinition.model_validate(feature).model_dump()))
    artifact=run/'fixture.pt';torch.save(data,artifact);return artifact


def test_experiment_catalog_is_isolated_complete_and_preserves_legacy_defaults(tmp_path,monkeypatch):
    run,manifest,_,_=fixture_run(tmp_path)
    base=Catalog.load();original=base.spec.model_dump()
    artifact=make_artifact(run,manifest,base)
    destination=tmp_path/'serving'
    result=publish_experiment(run,artifact,destination,base)
    catalog=Catalog.load(result['catalog'],result['artifact_root'])
    assert not catalog.issues
    assert len(catalog.spec.vectors)==len(base.spec.vectors)
    assert list(catalog.features)==list(base.features)
    formality=[v for v in catalog.spec.vectors if v.feature_id=='formality' and v.behavioral_status=='experimental']
    assert len(formality)==48 and all('synthetic-test' in v.id for v in formality)
    for index in (0,4,11,21,22):
        assert catalog.defaults['qwen2.5-0.5b-instruct',index]==base.defaults['qwen2.5-0.5b-instruct',index]
    assert 'synthetic-test' in catalog.defaults['qwen2.5-0.5b-instruct',3]
    assert base.spec.model_dump()==original
    with pytest.raises(ValueError,match='isolated'):publish_experiment(run,artifact,base.root,base)
    monkeypatch.setenv('SECONDTHOUGHT_LAB_CATALOG',result['catalog'])
    monkeypatch.setenv('SECONDTHOUGHT_LAB_ARTIFACT_ROOT',result['artifact_root'])
    assert Catalog.load().version==catalog.version


def test_new_feature_publishes_without_hardcoded_backend_routing(tmp_path):
    feature=definition() | dict(id='warmth',label='Warmth',scale='unit_l2')
    run=tmp_path/'run';manifest=make_plan(feature,scenarios(),run)
    base=Catalog.load();artifact=make_artifact(run,manifest,base)
    result=publish_experiment(run,artifact,tmp_path/'serving',base)
    catalog=Catalog.load(result['catalog'],result['artifact_root'])
    assert not catalog.issues
    assert len(catalog.spec.vectors)==len(base.spec.vectors)+48
    from secondthought.lab.plans import resolve_plan
    from secondthought.lab.interventions import Intervention
    vector=next(v for v in catalog.spec.vectors if v.feature_id=='warmth')
    plan=resolve_plan(catalog,vector.model_id,[Intervention(vector_id=vector.id,strength=.5)])
    assert plan.interventions[0].feature_id=='warmth'
    assert vector.scale=='unit_l2'


def test_malformed_import_has_explicit_validation_error(tmp_path):
    run,_,_,_=fixture_run(tmp_path)
    write_jsonl(run/'responses.jsonl',[{'output':{}}])
    with pytest.raises(ValueError,match='request_id'):prepare(run)
