import hashlib
import json

import pytest
import torch

from research.steering_experimentation import prepare_feature_pairs as preparation
from research.steering_experimentation.extract_lab_vectors import load_prepared_pairs, validate_split
from secondthought.lab.catalog import get_catalog
from secondthought.lab.interventions import Intervention, compile_interventions


def test_connected_text_variants_and_contexts_cannot_cross_preparation_splits(tmp_path,monkeypatch):
    source=tmp_path/'source';source.write_bytes(b'fixture')
    monkeypatch.setitem(preparation.SOURCES['empathy'],'sha256',hashlib.sha256(b'fixture').hexdigest())
    rows=[]
    for name in ('alpha','bravo','charlie','delta','echo','foxtrot','golf','hotel','india','juliet'):
        before=f'I can help with the report for {name} today.'
        after='Sorry you are struggling. '+before
        rows.append((before,after,name,name))
    # Two different contexts share text on opposite sides: split by components.
    rows.append((rows[0][1],'I understand. '+rows[0][1],'other','other'))
    monkeypatch.setattr(preparation,'records',lambda *args:iter(rows))
    output=tmp_path/'empathy_pairs.jsonl'
    _,report=preparation.prepare('empathy',source,output,max_extraction=100,max_heldout=100)
    extraction,heldout,_=load_prepared_pairs(output,'empathy')
    validate_split(extraction,heldout)
    left={preparation.normalized(t) for p in extraction for t in (p.source,p.target)}
    right={preparation.normalized(t) for p in heldout for t in (p.source,p.target)}
    assert left.isdisjoint(right)
    assert {p.group for p in extraction}.isdisjoint({p.group for p in heldout})
    assert report['pair_construction'].startswith('derived:')
    with pytest.raises(ValueError,match='different feature'):load_prepared_pairs(output,'politeness')
    output.write_text(output.read_text()+'\n')
    with pytest.raises(ValueError,match='checksum'):load_prepared_pairs(output,'empathy')


def test_each_new_feature_has_both_poolings_at_every_layer_and_composes_with_existing():
    catalog=get_catalog()
    features=('formality','detoxification','fluency','simplification','conciseness','empathy','politeness')
    assert set(catalog.features)==set(features)
    assert len(catalog.spec.vectors)==341
    for feature in features:
        vectors=[v for v in catalog.spec.vectors if v.feature_id==feature and v.behavioral_status=='experimental']
        assert {(v.layer_index,v.pooling) for v in vectors}=={(i,p) for i in range(24) for p in ('mean','final_token')}
    interventions=[Intervention(vector_id=f'qwen-{f}-l7-mean-v1',strength=.1) for f in features]
    compiled=compile_interventions(catalog,'qwen2.5-0.5b-instruct',interventions)
    expected=torch.stack([catalog.vector(i.vector_id)*i.strength for i in interventions]).sum(0)
    assert torch.allclose(compiled[7],expected)
    for feature in ('empathy','politeness'):
        artifact=catalog._loaded[f'qwen-{feature}-all-layers-v1']
        assert artifact['provenance']['pair_construction'].startswith('derived:')


def test_audit_detects_target_overlap_even_when_sources_are_unique():
    from research.steering_experimentation.audit_lab_features import split_review
    from research.steering_experimentation.extract_lab_vectors import Pair
    extraction=[Pair('Training original','Shared neutral target','dataset','train')]
    heldout=[Pair('Different original','shared neutral target','dataset','heldout')]
    result=split_review(extraction,heldout)
    assert result['shared_texts_any_side']==1
    assert result['affected_heldout_pairs']==1


def test_audit_reports_missing_sources_without_claiming_numerical_reproduction(tmp_path,monkeypatch):
    from research.steering_experimentation import audit_lab_features
    monkeypatch.setattr(audit_lab_features,'ROOT',tmp_path)
    report=audit_lab_features.audit()
    assert set(report['unavailable_source_features'])==set(get_catalog().features)
    assert sum(len(f['vectors']) for f in report['features'].values())==336
    assert all(f['numerical_reproduction']=='not_requested' for f in report['features'].values())
