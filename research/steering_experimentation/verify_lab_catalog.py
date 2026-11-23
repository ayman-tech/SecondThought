"""Execute every catalog vector on its declared Qwen layer and verify hook deltas.

This is a causal hook/integration smoke check, not a rewrite-quality benchmark.
Reports include short generated samples so failure modes remain reviewable.
Run from the repository root with python -m research.steering_experimentation.verify_lab_catalog.
"""
import argparse
import json
from pathlib import Path

import torch

from secondthought.lab.catalog import get_catalog
from secondthought.lab.interventions import Intervention, compile_interventions, steering_context
from website.api.layers import ExploreRewriter, DEFAULT_MODEL


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device',default='mps')
    parser.add_argument('--output',type=Path,default=Path('research/steering_experimentation/artifacts/lab_v1/generation_smoke.json'))
    args = parser.parse_args()
    catalog = get_catalog()
    if catalog.issues:
        raise ValueError(catalog.issues)
    service = ExploreRewriter(device=args.device)
    source = 'its really hard when u want to know what happened'
    inputs = service._encode_prompt(source)
    results = []
    composition_results = []
    service.max_new_tokens = 8
    with torch.inference_mode():
        for position, spec in enumerate(catalog.spec.vectors):
            compiled = compile_interventions(catalog,DEFAULT_MODEL,[Intervention(vector_id=spec.id,strength=0.5)])
            observations = {'calls':0,'correct':True}
            original = {}
            def before(_module,_inputs,output):
                original['tensor'] = output[0] if isinstance(output,tuple) else output
            def after(_module,_inputs,output):
                residual = output[0] if isinstance(output,tuple) else output
                shift = compiled[spec.layer_index].to(residual.device,residual.dtype).view(1,1,-1)
                observations['calls'] += 1
                observations['correct'] &= torch.equal(residual,original['tensor']+shift)
            layer = service.decoder_layers[spec.layer_index]
            capture = layer.register_forward_hook(before)
            try:
                with steering_context(service.decoder_layers,compiled):
                    observer = layer.register_forward_hook(after)
                    try:
                        generated = service.model.generate(**inputs,max_new_tokens=8,do_sample=False,
                            temperature=None,top_p=None,top_k=None,pad_token_id=service.tokenizer.pad_token_id,
                            eos_token_id=service.tokenizer.eos_token_id)
                    finally:
                        observer.remove()
            finally:
                capture.remove()
            assert observations['calls'] and observations['correct'],spec.id
            assert all(not layer._forward_hooks for layer in service.decoder_layers),spec.id
            text = service.tokenizer.decode(generated[0,inputs['input_ids'].shape[1]:],skip_special_tokens=True)
            results.append(dict(vector_id=spec.id,feature=spec.feature_id,layer=spec.layer_index,
                pooling=spec.pooling,hook_calls=observations['calls'],exact_hook_delta=True,sample=text))
            if position%12==0:
                print(f'Checked {position+1}/{len(catalog.spec.vectors)} vectors',flush=True)
        # Exercise signed composition through the same layer hooks. The UI
        # audit separately proves which IDs/strengths actual controls submit.
        features=list(catalog.features)
        for independent in (False,True):
            for sign in (-1,1):
                entries=[Intervention(vector_id=f'qwen-{feature}-l{2*i if independent else 7}-mean-v1',strength=sign*.1)
                         for i,feature in enumerate(features)]
                compiled=compile_interventions(catalog,DEFAULT_MODEL,entries)
                original={};observed={index:0 for index in compiled};handles=[]
                def before(index):
                    def capture(_module,_inputs,output):
                        original[index]=output[0] if isinstance(output,tuple) else output
                    return capture
                def after(index):
                    def check(_module,_inputs,output):
                        residual=output[0] if isinstance(output,tuple) else output
                        shift=compiled[index].to(residual.device,residual.dtype).view(1,1,-1)
                        assert torch.equal(residual,original[index]+shift)
                        observed[index]+=1
                    return check
                try:
                    for index in compiled:handles.append(service.decoder_layers[index].register_forward_hook(before(index)))
                    with steering_context(service.decoder_layers,compiled):
                        for index in compiled:handles.append(service.decoder_layers[index].register_forward_hook(after(index)))
                        service.model.generate(**inputs,max_new_tokens=8,do_sample=False,
                            temperature=None,top_p=None,top_k=None,pad_token_id=service.tokenizer.pad_token_id,
                            eos_token_id=service.tokenizer.eos_token_id)
                finally:
                    for handle in handles:handle.remove()
                assert all(observed.values())
                assert all(not layer._forward_hooks for layer in service.decoder_layers)
                composition_results.append(dict(independent_layers=independent,strength=sign*.1,
                    features=features,exact_hook_delta=True,hook_calls=observed))
    # Both compatibility and mixed contexts must preserve the original default.
    service.max_new_tokens = 64
    old = service._generate(inputs,0.5,0)
    new = service._generate_result(inputs,0.5,0,layer_strengths={11:0.5}).text
    assert old == new, (old,new)
    for index, vector in service.layer_vectors.items():
        assert vector.shape == (service.model.config.hidden_size,)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(dict(catalog_version=catalog.version,device=str(service.device),
        precision=str(service.model.dtype),model_revision=service.model_revision,
        verification='Exact added hook delta and cleanup during real generation; not a quality guarantee.',
        default_reference_unchanged=True,reference_output=new,results=results,composition=composition_results),indent=2)+'\n')
    print(f'All {len(results)} catalog vectors executed correctly; default unchanged. Report: {args.output}',flush=True)


if __name__ == '__main__':
    main()
