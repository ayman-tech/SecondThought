"""Validate all-layer extraction outputs, then publish an immutable runtime catalog.

No datasets or source sentences are copied. The legacy direction files remain
byte-for-byte unchanged; their five existing defaults stay in the compatibility map.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import torch

from secondthought.lab.catalog import Catalog, CatalogSpec, checksum

ROOT = Path(__file__).resolve().parents[2]
MODEL_ID = 'qwen2.5-0.5b-instruct'
REVISION = '7ae557604adf67be50417f59c2c2f167def9a775'


def build_catalog(staging: Path, destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    spec = dict(schema_version=1, id='secondthought-qwen-lab-v1',
        models=[dict(id=MODEL_ID, repository='Qwen/Qwen2.5-0.5B-Instruct', revision=REVISION,
                     layer_count=24, hidden_size=896, adapter='qwen2_decoder_output_v1')],
        features=[dict(id='formality', label='Formality', positive_direction='formal minus informal'),
                  dict(id='detoxification', label='Detoxification', positive_direction='neutral minus toxic')],
        artifacts=[], vectors=[], layer_defaults=[])
    for feature in ('formality','detoxification'):
        name = f'qwen2_5_0_5b_{feature}_all_layers_v1.pt'
        source = staging / name
        data = torch.load(source, map_location='cpu', weights_only=True)
        expected = {f'layer{i}_{pool}' for i in range(24) for pool in ('mean','final_token')}
        if set(data['candidates']) != expected or set(data['raw_directions']) != expected:
            raise ValueError('Every decoder index must have both extraction pooling methods')
        provenance = data['provenance']
        if (provenance.get('extraction_pairs'), provenance.get('heldout_pairs')) != (8000, 2000):
            raise ValueError('Unexpected extraction or held-out sample count')
        target = destination / name
        if target.exists() and checksum(target) != checksum(source):
            raise ValueError('Refusing to overwrite an artifact version; use a new version instead')
        if not target.exists():
            temporary = target.with_suffix('.pt.tmp')
            shutil.copyfile(source, temporary)
            temporary.replace(target)
        artifact_id = f'qwen-{feature}-all-layers-v1'
        spec['artifacts'].append(dict(id=artifact_id, path=name, sha256=checksum(target),
            model_id=MODEL_ID, feature_id=feature, model_revision=REVISION, format='all_layers_v1'))
        for candidate, settings in sorted(data['candidates'].items()):
            index, pooling = settings['layer_index'], settings['pooling']
            spec['vectors'].append(dict(id=f'qwen-{feature}-l{index}-{pooling}-v1', model_id=MODEL_ID,
                feature_id=feature, artifact_id=artifact_id, candidate=candidate,
                layer_index=index, pooling=pooling, site='decoder_block_output',
                scale='raw' if feature == 'formality' else 'unit_l2',
                raw_norm=float(data['raw_directions'][candidate].float().norm())))
    legacy = [
        ('formality', 'qwen2_5_0_5b_gyafc_formality_directions.pt',
         [(4, 'alternative_layer4_final'), (11, 'negative_layer11_mean'), (21, 'primary_layer21_mean')]),
        ('detoxification', 'qwen2_5_0_5b_paradetox_directions.pt', [(0, 'best_mean'), (22, 'best_final')]),
    ]
    defaults = {index: f'qwen-formality-l{index}-mean-v1' for index in range(24)}
    for feature, name, candidates in legacy:
        data = torch.load(destination / name, map_location='cpu', weights_only=True)
        artifact_id = f'qwen-{feature}-legacy'
        spec['artifacts'].append(dict(id=artifact_id, path=name, sha256=checksum(destination/name),
            model_id=MODEL_ID, feature_id=feature, model_revision=None, format='legacy'))
        for index, candidate in candidates:
            vector_id = f'qwen-{feature}-legacy-{candidate}'
            spec['vectors'].append(dict(id=vector_id, model_id=MODEL_ID, feature_id=feature,
                artifact_id=artifact_id, candidate=candidate, layer_index=index,
                pooling=data['candidates'][candidate]['pooling'], site='decoder_block_output',
                scale='raw' if feature == 'formality' else 'unit_l2',
                raw_norm=float(data['raw_directions'][candidate].float().norm()),
                behavioral_status='legacy_reference', strength_range_status='legacy_range'))
            defaults[index] = vector_id
    spec['layer_defaults'] = [dict(model_id=MODEL_ID, layer_index=i, vector_id=v) for i,v in defaults.items()]
    catalog = Catalog(CatalogSpec.model_validate(spec), destination)
    if catalog.issues:
        raise ValueError(f'Catalog validation failed: {catalog.issues}')
    for feature in ('formality','detoxification'):
        combinations = {(v.layer_index, v.pooling) for v in catalog.spec.vectors
                        if v.feature_id == feature and catalog.artifacts[v.artifact_id].format == 'all_layers_v1'}
        if len(combinations) != 48:
            raise ValueError('Incomplete model/feature/layer/pooling coverage')
    path = destination / 'catalog/qwen2_5_0_5b.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(catalog.spec.model_dump(mode='json'), indent=2) + '\n')
    temporary.replace(path)
    print(f'Published {len(catalog.spec.vectors)} checked vectors, catalog {catalog.version}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staging', type=Path, default=ROOT/'research/steering_experimentation/artifacts/lab_v1')
    parser.add_argument('--destination', type=Path, default=ROOT/'artifacts')
    args = parser.parse_args()
    build_catalog(args.staging, args.destination)


if __name__ == '__main__':
    main()
