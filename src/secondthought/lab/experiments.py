"""Publish a synthetic release to an isolated catalog; never mutate serving assets."""
import json
from pathlib import Path
import shutil
import tempfile

import torch

from .catalog import Catalog,CatalogSpec,checksum
from .synthetic import FeatureDefinition,load_plan


def publish_experiment(run,artifact,destination,base=None):
    manifest,_=load_plan(run)
    definition=FeatureDefinition.model_validate(manifest['configuration']['feature'])
    base=base or Catalog.load()
    if base.issues:raise ValueError('Base catalog has unavailable artifacts/vectors')
    artifact=Path(artifact);destination=Path(destination).resolve()
    if destination.exists() or destination==base.root or destination.is_relative_to(base.root):
        raise ValueError('Choose a new isolated catalog directory outside the serving artifact root')
    data=torch.load(artifact,map_location='cpu',weights_only=True)
    provenance=data.get('provenance',{})
    if data.get('feature')!=definition.id or provenance.get('experiment_id')!=manifest['experiment_id']:
        raise ValueError('Artifact is not from this synthetic experiment')
    if provenance.get('definition')!=definition.model_dump():raise ValueError('Definition changed since extraction')
    model_id=next((m.id for m in base.spec.models if m.repository==data.get('model_id') and m.revision==data.get('model_revision')),None)
    if model_id is None:raise ValueError('Artifact model does not match the base catalog')
    model=base.models[model_id]
    expected={f'layer{i}_{pool}' for i in range(model.layer_count) for pool in ('mean','final_token')}
    if set(data.get('candidates',{}))!=expected or set(data.get('raw_directions',{}))!=expected:
        raise ValueError('Incomplete all-layer/pooling synthetic artifact')
    spec=base.spec.model_dump(mode='json')
    old_artifacts={a.id for a in base.spec.artifacts if a.feature_id==definition.id and a.model_id==model_id and a.format=='all_layers_v1'}
    replaced={v.id:v for v in base.spec.vectors if v.artifact_id in old_artifacts}
    spec['artifacts']=[a for a in spec['artifacts'] if a['id'] not in old_artifacts]
    spec['vectors']=[v for v in spec['vectors'] if v['id'] not in replaced]
    feature_spec=dict(id=definition.id,label=definition.label,
        positive_direction=definition.high+' minus '+definition.low)
    if any(f['id']==definition.id for f in spec['features']):
        spec['features']=[feature_spec if f['id']==definition.id else f for f in spec['features']]
    else:spec['features'].append(feature_spec)
    artifact_id=f'qwen-{definition.id}-synthetic-{definition.version}'
    name=f'qwen2_5_0_5b_{definition.id}_synthetic_{definition.version}.pt'
    spec['artifacts'].append(dict(id=artifact_id,path=name,sha256=checksum(artifact),model_id=model_id,
        feature_id=definition.id,model_revision=model.revision,format='all_layers_v1'))
    ids={}
    for candidate,settings in sorted(data['candidates'].items()):
        layer,pool=settings['layer_index'],settings['pooling']
        vector_id=f'qwen-{definition.id}-l{layer}-{pool}-synthetic-{definition.version}'
        ids[layer,pool]=vector_id
        spec['vectors'].append(dict(id=vector_id,model_id=model_id,feature_id=definition.id,artifact_id=artifact_id,
            candidate=candidate,layer_index=layer,pooling=pool,site='decoder_block_output',scale=definition.scale,
            raw_norm=float(data['raw_directions'][candidate].float().norm())))
    for default in spec['layer_defaults']:
        if default['vector_id'] in replaced:
            old=replaced[default['vector_id']]
            default['vector_id']=ids[old.layer_index,old.pooling]
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='synthetic-publish-',dir=destination.parent) as temporary:
        staging=Path(temporary)
        for entry in spec['artifacts']:
            target=(staging/entry['path']).resolve()
            if not target.is_relative_to(staging):raise ValueError('Invalid artifact path')
            target.parent.mkdir(parents=True,exist_ok=True)
            source=artifact if entry['id']==artifact_id else base.root/entry['path']
            shutil.copyfile(source,target)
        catalog=Catalog(CatalogSpec.model_validate(spec),staging)
        if catalog.issues:raise ValueError(f'Experimental catalog failed validation: {catalog.issues}')
        (staging/'catalog').mkdir(exist_ok=True)
        (staging/'catalog/qwen2_5_0_5b.json').write_text(json.dumps(catalog.spec.model_dump(mode='json'),indent=2)+'\n')
        # Publish only a completely validated snapshot, to a new directory.
        staging.rename(destination)
    return dict(catalog_version=catalog.version,feature=definition.id,artifact_id=artifact_id,
        vectors=model.layer_count*2,artifact_root=str(destination),
        catalog=str(destination/'catalog/qwen2_5_0_5b.json'))
