from copy import copy

import pytest

from secondthought.lab.catalog import get_catalog
from secondthought.lab.evidence import ordering_interval, vector_evidence, layer_evidence_profiles


def test_ordering_intervals_use_actual_binary_counts_and_reject_invalid_metrics():
    result=ordering_interval(0.9595000147819519,2000)
    assert result['value']==0.9595
    assert result['interval_low']<result['value']<result['interval_high']
    narrow=ordering_interval(0.9,8000)
    wide=ordering_interval(0.9,2000)
    assert narrow['interval_high']-narrow['interval_low'] < wide['interval_high']-wide['interval_low']
    for accuracy, count in [(None,2000),(float('nan'),2000),(1.1,2000),(-.1,2000),
                            (.9,0),(.9,True),(.9,None),(.3333,2000)]:
        assert ordering_interval(accuracy,count) is None
    assert ordering_interval(0,2000)['interval_low']==pytest.approx(0)
    assert ordering_interval(1,2000)['interval_high']==pytest.approx(1)


def test_missing_legacy_score_is_not_borrowed_from_new_vector_at_same_layer():
    catalog=get_catalog()
    profiles=layer_evidence_profiles(catalog,'qwen2.5-0.5b-instruct')
    defaults=profiles[0]
    assert [row['layer_index'] for row in defaults['layers'] if not row['measured']]==[4,11,21]
    assert defaults['comparison_scope']=='mixed'
    new=next(profile for profile in profiles if profile['id']=='qwen-formality-all-layers-v1/mean')
    old_row=defaults['layers'][11]
    new_row=new['layers'][11]
    assert not old_row['measured']
    assert new_row['measured'] and not new_row['matches_default']
    assert old_row['vector_id'] != new_row['vector_id']
    assert defaults['layers'][0]['value']==0.9965
    assert defaults['layers'][0]['pairs']==2000


def test_each_new_colour_profile_is_one_comparable_measured_cohort():
    catalog=get_catalog()
    profiles=layer_evidence_profiles(catalog,'qwen2.5-0.5b-instruct')
    assert len(profiles)==7
    for profile in profiles[1:]:
        rows=profile['layers']
        assert profile['comparison_scope']=='single_cohort'
        assert len(rows)==24 and all(row['measured'] for row in rows)
        assert len({row['cohort_id'] for row in rows})==1
        assert len({(row['feature_id'],row['pooling']) for row in rows})==1
        expected_pairs = 84 if rows[0]['feature_id'] == 'fluency' else 2000
        assert all(row['pairs']==expected_pairs for row in rows)


def test_unavailable_vector_cannot_get_a_colour_from_its_saved_measurement():
    original=get_catalog()
    catalog=copy(original)
    catalog._tensors=dict(original._tensors)
    vector_id='qwen-formality-l3-mean-v1'
    catalog._tensors.pop(vector_id)
    assert not vector_evidence(catalog,vector_id)['measured']
    assert vector_evidence(original,vector_id)['measured']


def test_all_colour_scores_belong_to_the_exact_candidate_and_tensor():
    catalog = get_catalog()
    seen = set()
    for profile in layer_evidence_profiles(catalog,'qwen2.5-0.5b-instruct')[1:]:
        for row in profile['layers']:
            vector = catalog.vectors[row['vector_id']]
            data = catalog._loaded[vector.artifact_id]
            candidate = data['candidates'][vector.candidate]
            assert row['layer_index'] == vector.layer_index == candidate['layer_index']
            assert row['pooling'] == vector.pooling == candidate['pooling']
            assert row['feature_id'] == vector.feature_id
            assert row['value'] == pytest.approx(candidate['heldout_ordering_accuracy'],abs=1e-7)
            assert row['pairs'] == data['provenance']['heldout_pairs']
            expected = data['raw_directions'][vector.candidate].float()
            if vector.scale == 'unit_l2':
                expected = expected / expected.norm()
            assert catalog.vector(vector.id).equal(expected)
            seen.add((vector.feature_id,vector.pooling,vector.layer_index))
    assert seen == {(f,p,i) for f in ('formality','detoxification','fluency')
                    for p in ('mean','final_token') for i in range(24)}
