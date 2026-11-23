"""Read-only artifact, split and optional numerical reproduction audit.

Never modifies vectors/catalogs. Raw sentences are not included in reports.
Missing restricted corpora are reported, not replaced or downloaded.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re

import torch

from secondthought.lab.catalog import get_catalog
from secondthought.lab.evidence import vector_evidence
from research.steering_experimentation.extract_lab_vectors import (
    ROOT, MODEL, REVISION, load_formality, load_detox, load_fluency,
    load_prepared_pairs, representations, normalized, split_digest,
)


def split_review(extraction, heldout):
    left={normalized(t) for pair in extraction for t in (pair.source,pair.target)}
    right={normalized(t) for pair in heldout for t in (pair.source,pair.target)}
    overlap=left & right
    shared_groups={p.group for p in extraction}&{p.group for p in heldout}
    rows=[*extraction,*heldout]
    ratios=[len(p.target.split())/max(1,len(p.source.split())) for p in rows]
    return dict(extraction_pairs=len(extraction),heldout_pairs=len(heldout),
        shared_texts_any_side=len(overlap),
        affected_heldout_pairs=sum(normalized(p.source) in overlap or normalized(p.target) in overlap for p in heldout),
        shared_group_labels=len(shared_groups),
        group_note='Some legacy groups denote domains/datasets, not document IDs.',
        target_word_count_ratio_mean=sum(ratios)/len(ratios),
        formatting_marker_pairs=sum(bool(re.search(r'-[LR]RB-|�|â',p.source+p.target)) for p in rows))


def audit(gyafc=None,recompute=False,device='mps'):
    catalog=get_catalog()
    if catalog.issues:raise ValueError(catalog.issues)
    report=dict(catalog_version=catalog.version,model_revision=REVISION,
        note='Ordering separation and hook correctness do not establish behavioral steering quality.',
        features={},unavailable_source_features=[])
    loaded={}
    for feature in catalog.features:
        artifacts=[a for a in catalog.spec.artifacts if a.feature_id==feature and a.format=='all_layers_v1']
        if len(artifacts)!=1:raise ValueError('Audit requires one explicit all-layer release per feature')
        artifact=artifacts[0];data=catalog._loaded[artifact.id];p=data['provenance']
        vectors=[v for v in catalog.spec.vectors if v.artifact_id==artifact.id]
        if {(v.layer_index,v.pooling) for v in vectors}!={(i,pool) for i in range(24) for pool in ('mean','final_token')}:
            raise ValueError('Incomplete layer/pooling coverage')
        rows=[]
        for vector in vectors:
            evidence=vector_evidence(catalog,vector.id)
            if not evidence['measured']:raise ValueError(f'Missing evidence: {vector.id}')
            candidate=data['candidates'][vector.candidate]
            if abs(evidence['value']-candidate['heldout_ordering_accuracy'])>1e-7:
                raise ValueError('Evidence points at another measurement')
            raw=data['raw_directions'][vector.candidate].float()
            expected=raw/raw.norm() if vector.scale=='unit_l2' else raw
            if not torch.equal(expected,catalog.vector(vector.id)):raise ValueError('Runtime scale mismatch')
            rows.append(dict(vector_id=vector.id,layer=vector.layer_index,pooling=vector.pooling,
                raw_norm=float(raw.norm()),runtime_norm=float(expected.norm()),ordering=evidence['value'],
                heldout_pairs=evidence['pairs'],interval_low=evidence['interval_low'],interval_high=evidence['interval_high']))
        entry=dict(artifact_id=artifact.id,artifact_sha256=artifact.sha256,
            dataset=p.get('dataset'),pair_construction=p.get('pair_construction','paired revisions'),
            scale=sorted({v.scale for v in vectors}),token_scope='all_tokens',vectors=rows,
            truncation=dict(extraction=p.get('extraction_truncation'),heldout=p.get('heldout_truncation')),
            extraction_batch_size_recorded=p.get('extraction_batch_size'),
            source_audit='not_available',numerical_reproduction='source_unavailable' if recompute else 'not_requested')
        report['features'][feature]=entry
        if feature=='formality':
            if gyafc is None:
                report['unavailable_source_features'].append(feature)
                continue
            splits=load_formality(gyafc,p['seed'])
        elif feature=='detoxification':
            path=ROOT/'research/steering_experimentation/artifacts/paradetox_direction_pairs.csv'
            if not path.exists():
                report['unavailable_source_features'].append(feature);continue
            splits=load_detox(path)
        else:
            path=ROOT/('data/iterater/fluency_pairs.jsonl' if feature=='fluency' else f'data/lab_features/{feature}_pairs.jsonl')
            if not path.exists():
                report['unavailable_source_features'].append(feature);continue
            splits=load_fluency(path) if feature=='fluency' else load_prepared_pairs(path,feature)
        extraction,heldout,_=splits
        if (split_digest(extraction)!=p['extraction_split_sha256'] or
                split_digest(heldout)!=p['heldout_split_sha256']):
            raise ValueError(f'Source split fingerprint mismatch: {feature}')
        entry['source_audit']=split_review(extraction,heldout)
        loaded[feature]=(extraction,heldout)
    if not recompute:return report
    from huggingface_hub import snapshot_download
    from transformers import AutoModelForCausalLM,AutoTokenizer
    snapshot=snapshot_download(MODEL,revision=REVISION,local_files_only=True)
    tokenizer=AutoTokenizer.from_pretrained(snapshot);tokenizer.padding_side='right'
    model=AutoModelForCausalLM.from_pretrained(snapshot,dtype=torch.float32).to(device).eval()
    model.requires_grad_(False)
    for feature,(extraction,heldout) in loaded.items():
        entry=report['features'][feature];data=catalog._loaded[entry['artifact_id']]
        p=data['provenance'];batch=p.get('extraction_batch_size',16 if feature in ('formality','detoxification') else 8)
        raw=torch.stack([torch.stack([data['raw_directions'][f'layer{i}_{pool}'] for i in range(24)])
                         for pool in ('mean','final_token')])
        sums=torch.zeros_like(raw,dtype=torch.float64);truncated=Counter()
        for start in range(0,len(extraction),batch):
            delta=representations(model,tokenizer,extraction[start:start+batch],device,p['max_length'],truncated)
            sums+=delta.sum(1).cpu().double()
        reproduced=(sums/len(extraction)).float()
        max_error=float((reproduced-raw).abs().max())
        if not torch.allclose(reproduced,raw,rtol=1e-4,atol=1e-5):
            raise ValueError(f'Extracted means differ from artifact: {feature}, max error {max_error}')
        units=(raw/raw.norm(dim=-1,keepdim=True)).to(device)
        hits=torch.zeros(2,24,dtype=torch.int64)
        for start in range(0,len(heldout),batch):
            delta=representations(model,tokenizer,heldout[start:start+batch],device,p['max_length'],Counter())
            hits+=((delta*units.unsqueeze(1)).sum(-1)>0).sum(1).cpu()
        for pi,pool in enumerate(('mean','final_token')):
            for layer in range(24):
                accuracy=float(data['candidates'][f'layer{layer}_{pool}']['heldout_ordering_accuracy'])
                if round(accuracy*len(heldout))!=int(hits[pi,layer]):
                    raise ValueError(f'Held-out ordering mismatch: {feature}/{pool}/{layer}')
        entry['numerical_reproduction']=dict(device=device,batch_size=batch,
            batch_size_source='artifact' if p.get('extraction_batch_size') else 'documented release recipe',
            raw_direction_max_abs_error=max_error,all_48_ordering_counts_match=True)
        print(f'{feature}: all 48 means and held-out ordering counts reproduced; max error {max_error:.3g}',flush=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gyafc',type=Path)
    parser.add_argument('--recompute',action='store_true')
    parser.add_argument('--device',default='mps',choices=['mps','cpu','cuda'])
    parser.add_argument('--output',type=Path,default=Path('/tmp/secondthought-feature-audit.json'))
    args=parser.parse_args()
    report=audit(args.gyafc,args.recompute,args.device)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(f'Checked {sum(len(f["vectors"]) for f in report["features"].values())} UI vectors. Source unavailable: {report["unavailable_source_features"]}. Report: {args.output}')


if __name__=='__main__':main()
