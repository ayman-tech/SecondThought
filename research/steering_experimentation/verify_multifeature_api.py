"""Verify v2 plan/worker integration against a running local website API.

This checks routing, metadata and hook isolation, not generation quality.
Run: python research/steering_experimentation/verify_multifeature_api.py
"""
import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import uuid4


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8001')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    def post(path,body):
        with urlopen(Request(args.url+path,data=json.dumps(body).encode(),
                    headers={'Content-Type':'application/json'}),timeout=110) as response:
            return response.read().decode()
    with urlopen(args.url+'/api/v2/lab/catalog',timeout=10) as response:
        catalog=json.load(response)
    model='qwen2.5-0.5b-instruct'
    def vector(feature,layer,pooling='mean'):
        matches=[v for v in catalog['vectors'] if v['model_id']==model and
            v['feature_id']==feature and v['layer_index']==layer and v['pooling']==pooling and
            v['behavioral_status']=='experimental' and v['available']]
        if len(matches)!=1: raise ValueError('Expected one new-extraction vector; choose an explicit release')
        return matches[0]['id']
    session=str(uuid4());results=[]
    cases=[('baseline',[]),('shared_layer',[
        dict(vector_id=vector('formality',7),strength=.25),
        dict(vector_id=vector('detoxification',7),strength=.25)]),
        ('independent_layers',[
        dict(vector_id=vector('formality',7),strength=.25),
        dict(vector_id=vector('detoxification',11,'final_token'),strength=.25)]),
        ('fluency_mean', [dict(vector_id=vector('fluency',7),strength=.5)]),
        ('fluency_final_token', [dict(vector_id=vector('fluency',11,'final_token'),strength=.5)]),
        ('three_features_shared', [dict(vector_id=vector(feature,7),strength=.25)
                                  for feature in ('formality','detoxification','fluency')]),
        ('three_features_independent', [dict(vector_id=vector(feature,layer,pooling),strength=.25)
            for feature,layer,pooling in [('formality',7,'mean'),('detoxification',11,'final_token'),('fluency',15,'mean')]]),
        ('baseline_after',[])]
    features=[entry['id'] for entry in catalog['features']]
    extra=[]
    for feature in features:
        if feature in ('formality','detoxification','fluency'):continue
        for pooling in ('mean','final_token'):
            extra.append((f'{feature}_{pooling}',[dict(vector_id=vector(feature,7,pooling),strength=.25)]))
    extra.extend([
        ('all_features_shared',[dict(vector_id=vector(feature,7),strength=.1) for feature in features]),
        ('all_features_independent',[dict(vector_id=vector(feature,2*index,'final_token' if index%2 else 'mean'),strength=.1)
                                     for index,feature in enumerate(features)]),
    ])
    cases[-1:-1]=extra
    for revision,(name,interventions) in enumerate(cases,1):
        body=dict(session_id=session,revision=revision,model_id=model,
            catalog_version=catalog['catalog_version'],input='Send me the damn report before noon.',
            task='rewrite',interventions=interventions,generation=dict(max_input_tokens=2048,max_new_tokens=64))
        expected=json.loads(post('/api/v2/lab/runs/resolve',body))['resolved']
        events=[json.loads(line) for line in post('/api/v2/lab/runs/stream',body).splitlines()]
        final=events[-1]
        assert final['event']=='completed',final
        assert final['applied']==expected
        assert all(e['plan_id']==expected['plan']['plan_id'] for e in events)
        assert final['text'].strip()
        results.append(dict(case=name,text=final['text'],finish_reason=final['finish_reason'],
            latency_ms=final['latency_ms'],applied=final['applied']))
    assert results[0]['text']==results[-1]['text'],'Baseline changed after combined steering'
    report=dict(catalog_version=catalog['catalog_version'],checks='passed',
        note='Real-model routing/metadata/isolation smoke test, not a quality evaluation.',runs=results)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(checks=report['checks'],cases=[r['case'] for r in results]),indent=2))


if __name__=='__main__':
    main()
