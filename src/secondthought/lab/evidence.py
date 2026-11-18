"""Describe measured feature separation without inventing generation-quality scores."""
from __future__ import annotations

import math

METRIC = "heldout_ordering_accuracy"
LABEL = "Held-out pair ordering"


def ordering_interval(accuracy, pairs):
    """Wilson interval for the observed count of positive held-out projections."""
    if (isinstance(accuracy, bool) or not isinstance(accuracy, (int, float)) or
            not math.isfinite(accuracy) or not 0 <= accuracy <= 1 or
            isinstance(pairs, bool) or not isinstance(pairs, int) or pairs <= 0):
        return None
    count = round(accuracy * pairs)
    # Stored float32 means have rounding noise, but a different aggregation
    # cannot be interpreted as a count of binary pair-ordering outcomes.
    if abs(count - accuracy * pairs) > 0.001:
        return None
    point = count / pairs
    z = 1.959963984540054
    denominator = 1 + z*z/pairs
    center = (point + z*z/(2*pairs)) / denominator
    radius = z * math.sqrt(point*(1-point)/pairs + z*z/(4*pairs*pairs)) / denominator
    return dict(value=point, pairs=pairs, interval_low=max(0., center-radius),
                interval_high=min(1., center+radius), interval_method="Wilson 95%")


def vector_evidence(catalog, vector_id):
    vector = catalog.vectors[vector_id]
    base = dict(vector_id=vector.id, layer_index=vector.layer_index,
                feature_id=vector.feature_id, feature=catalog.features[vector.feature_id].label,
                pooling=vector.pooling, artifact_id=vector.artifact_id,
                cohort_id=f'{vector.artifact_id}/{vector.pooling}', metric=METRIC,
                measured=False, reason='vector_unavailable')
    if vector.id not in catalog._tensors:
        return base
    artifact = catalog._loaded.get(vector.artifact_id, {})
    candidate = artifact.get('candidates', {}).get(vector.candidate, {})
    accuracy = candidate.get(METRIC)
    if accuracy is None:
        return dict(base, reason='No held-out ordering score saved for this exact vector.')
    pairs = candidate.get('heldout_pairs', artifact.get('provenance', {}).get(
        'heldout_pairs', artifact.get('heldout_pairs')))
    interval = ordering_interval(accuracy, pairs)
    if interval is None:
        return dict(base, reason='Held-out score or sample count is missing or invalid.')
    return dict(base, **interval, measured=True, reason=None)


def layer_evidence_profiles(catalog, model_id):
    """Default-vector evidence plus separate, comparable extraction cohorts.

    A new extraction's score is never borrowed for a legacy default, even when
    its feature, layer, and pooling happen to have the same names.
    """
    model = catalog.models[model_id]
    defaults = []
    for index in range(model.layer_count):
        vector_id = catalog.defaults.get((model_id,index))
        evidence = (vector_evidence(catalog,vector_id) if vector_id is not None else
                    dict(layer_index=index,measured=False,reason='No default vector.'))
        defaults.append(dict(evidence,matches_default=True))
    profiles = [dict(id='defaults',label='Applied steering vectors',metric_label=LABEL,
        comparison_scope='mixed',
        note='Exact applied vectors. Compare scores only within the same feature, pooling and extraction cohort.',
        layers=defaults)]
    for artifact in catalog.spec.artifacts:
        if artifact.model_id != model_id or artifact.format != 'all_layers_v1':
            continue
        for pooling in ('mean','final_token'):
            vectors = {v.layer_index:v for v in catalog.spec.vectors
                       if v.artifact_id == artifact.id and v.pooling == pooling}
            if not vectors:
                continue
            rows = []
            for index in range(model.layer_count):
                vector = vectors.get(index)
                evidence = (vector_evidence(catalog,vector.id) if vector else
                            dict(layer_index=index,measured=False,reason='No vector in this cohort.'))
                rows.append(dict(evidence,matches_default=(vector is not None and
                    catalog.defaults.get((model_id,index)) == vector.id)))
            feature = catalog.features[artifact.feature_id].label
            pool_label = 'mean' if pooling == 'mean' else 'last token'
            profiles.append(dict(id=f'{artifact.id}/{pooling}',
                label=f'{feature} · {pool_label} · new extraction',metric_label=LABEL,
                comparison_scope='single_cohort',
                note=f'{feature}, {pool_label}, one held-out extraction cohort. Colour view does not change applied steering vectors.',
                layers=rows))
    return profiles
