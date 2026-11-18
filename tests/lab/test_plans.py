import json
from uuid import uuid4

import pytest
import torch
from pydantic import ValidationError

from secondthought.lab.catalog import Catalog, CatalogSpec, checksum, get_catalog
from secondthought.lab.interventions import Intervention, compile_interventions, steering_context
from secondthought.lab.plans import resolve_plan
from website.api.runs import resolve_run
from website.api.schemas import RunRequest

MODEL = 'qwen2.5-0.5b-instruct'


def entry(feature, layer, strength, pooling='mean'):
    vector = next(v for v in get_catalog().spec.vectors if v.feature_id == feature and
        v.layer_index == layer and v.pooling == pooling and v.behavioral_status == 'experimental')
    return Intervention(vector_id=vector.id,strength=strength)


@pytest.mark.parametrize('detox_layer,pooling',[(7,'mean'),(11,'final_token')])
def test_independent_feature_layers_and_same_layer_composition(detox_layer,pooling):
    catalog=get_catalog()
    interventions=(entry('formality',7,.4),entry('detoxification',detox_layer,-.7,pooling),entry('formality',21,0))
    plan=resolve_plan(catalog,MODEL,interventions)
    assert plan == resolve_plan(catalog,MODEL,tuple(reversed(interventions)))
    compiled=compile_interventions(catalog,MODEL,plan.interventions)
    assert set(compiled) == {7,detox_layer}
    expected={}
    for row in interventions:
        layer=catalog.vectors[row.vector_id].layer_index
        if row.strength:
            expected[layer]=expected.get(layer,torch.zeros(896))+catalog.vector(row.vector_id)*row.strength
    for layer,shift in expected.items():
        assert torch.allclose(compiled[layer],shift)
    layers=torch.nn.ModuleList([torch.nn.Identity() for _ in range(24)])
    with steering_context(layers,compiled):
        for index in compiled:
            output=layers[index](torch.zeros(1,3,896))
            assert torch.allclose(output[0,0],expected[index])
            assert torch.allclose(output[0,2],expected[index])
    assert all(not layer._forward_hooks for layer in layers)
    for row in plan.interventions:
        assert row.artifact_sha256 == catalog.artifacts[row.artifact_id].sha256
    with pytest.raises(ValidationError):
        plan.interventions[0].strength = 1


def test_fingerprints_include_input_prompt_generation_and_vectors_not_request_order():
    data=dict(session_id=uuid4(),revision=1,model_id=MODEL,input='Source',task='custom',
        system_prompt='Reply briefly.',interventions=[entry('formality',7,.4),entry('detoxification',7,.7)])
    plan,configuration=resolve_run(RunRequest(**data))
    reordered=RunRequest(**(data|dict(session_id=uuid4(),revision=2,interventions=list(reversed(data['interventions'])))))
    assert resolve_run(reordered)[1]['experiment_id'] == configuration['experiment_id']
    for change in [dict(input='Other source'),dict(system_prompt='Reply in French.'),
                   dict(generation=dict(max_new_tokens=256)),
                   dict(interventions=[entry('formality',7,.5),entry('detoxification',7,.7)])]:
        assert resolve_run(RunRequest(**(data|change)))[1]['experiment_id'] != configuration['experiment_id']
    with pytest.raises(ValueError,match='Catalog version'):
        resolve_run(RunRequest(**(data|dict(catalog_version='0'*64))))
    with pytest.raises(ValueError,match='Duplicate'):
        resolve_plan(get_catalog(),MODEL,[data['interventions'][0]]*2)
    with pytest.raises(ValueError,match='bounds'):
        resolve_plan(get_catalog(),MODEL,[entry('formality',7,100)])
    assert resolve_plan(get_catalog(),MODEL,[]).interventions == ()


def test_new_feature_is_catalog_data_not_a_special_case(tmp_path):
    # Synthetic empathy vectors, not a claim of an extracted empathy release.
    artifact=dict(format_version=1,model_id='test/model',model_revision='a'*40,
        tokenizer_revision='a'*40,feature='empathy',site='decoder_block_output',layer_count=2,hidden_size=2,
        candidates={'empathy':dict(layer_index=1,pooling='mean')},
        raw_directions={'empathy':torch.tensor([3.,4.])})
    path=tmp_path/'empathy.pt';torch.save(artifact,path)
    spec=CatalogSpec.model_validate(dict(schema_version=1,id='synthetic-test',
        models=[dict(id='test',repository='test/model',revision='a'*40,layer_count=2,hidden_size=2,adapter='qwen2_decoder_output_v1')],
        features=[dict(id='empathy',label='Empathy',positive_direction='empathetic minus neutral')],
        artifacts=[dict(id='empathy-release',path='empathy.pt',sha256=checksum(path),model_id='test',feature_id='empathy',model_revision='a'*40,format='all_layers_v1')],
        vectors=[dict(id='empathy-l1',model_id='test',feature_id='empathy',artifact_id='empathy-release',candidate='empathy',layer_index=1,pooling='mean',scale='unit_l2',raw_norm=5)],layer_defaults=[]))
    catalog=Catalog(spec,tmp_path)
    assert not catalog.issues
    plan=resolve_plan(catalog,'test',[Intervention(vector_id='empathy-l1',strength=.5)])
    assert plan.interventions[0].feature_id == 'empathy'
    assert torch.equal(compile_interventions(catalog,'test',plan.interventions)[1],torch.tensor([.3,.4]))
    with pytest.raises(ValueError,match='Unknown'):
        resolve_plan(catalog,MODEL,[])
