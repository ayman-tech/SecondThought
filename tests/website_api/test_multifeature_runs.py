import json
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from secondthought.lab.catalog import get_catalog
from secondthought.lab.plans import resolve_plan
from secondthought.steering_rewriter import GenerationResult
from website.api.server import create_app
from website.api.layers import DEFAULT_MODEL


class Runtime:
    model_id='Qwen/Qwen2.5-0.5B-Instruct'
    catalog_model_id=DEFAULT_MODEL
    catalog=get_catalog()
    catalog_version=catalog.version
    def __init__(self): self.calls=[]
    def stream_run(self,plan,message,*,on_text,cancelled,**options):
        assert plan == resolve_plan(self.catalog,plan.model_id,plan.interventions)
        self.calls.append((plan,message,options))
        on_text('A response.')
        return GenerationResult('A response.',3,'stop')


def request(**changes):
    return dict(session_id=str(uuid4()),revision=1,model_id=DEFAULT_MODEL,
        input='Explain this clearly.',task='answer',interventions=[
            dict(vector_id='qwen-formality-l7-mean-v1',strength=.4),
            dict(vector_id='qwen-detoxification-l7-mean-v1',strength=.7),
            dict(vector_id='qwen-detoxification-l11-final_token-v1',strength=-.3)]) | changes


def ready(client):
    import time
    for _ in range(100):
        if client.get('/health/ready').status_code==200: return
        time.sleep(.01)
    raise AssertionError('Runtime not ready')


def test_inspection_and_execution_share_exact_resolved_configuration():
    runtime=Runtime()
    with TestClient(create_app(runtime)) as client:
        ready(client)
        body=request()
        resolved=client.post('/api/v2/lab/runs/resolve',json=body)
        assert resolved.status_code==200 and resolved.json()['runtime_ready']
        assert not runtime.calls
        response=client.post('/api/v2/lab/runs/stream',json=body)
        events=[json.loads(line) for line in response.text.splitlines()]
        assert [e['event'] for e in events]==['queued','started','delta','completed']
        completed=events[-1]
        assert completed['text']=='A response.'
        assert completed['applied']==resolved.json()['resolved']
        assert all(e['plan_id']==completed['plan_id'] for e in events)
        assert 'applied' not in events[2]  # Token events stay small.
        plan=runtime.calls[0][0]
        assert len(plan.interventions)==3
        assert {(i.feature_id,i.layer_index) for i in plan.interventions}=={
            ('formality',7),('detoxification',7),('detoxification',11)}
        assert plan.token_scope=='all_tokens' and plan.composition=='weighted_sum'
        assert client.post('/api/v2/lab/runs',json=body).status_code==409


@pytest.mark.parametrize('changes',[
    dict(model_id='missing-model'),dict(interventions=[dict(vector_id='missing',strength=.5)]),
    dict(interventions=[dict(vector_id='qwen-formality-l7-mean-v1',strength=3)]),
    dict(interventions=[dict(vector_id='qwen-formality-l7-mean-v1',strength=float('inf'))]),
    dict(interventions=[dict(vector_id='qwen-formality-l7-mean-v1',strength=True)]),
    dict(interventions=[dict(vector_id='qwen-formality-l7-mean-v1',strength=.5)]*2),
    dict(interventions=[dict(vector_id='qwen-formality-l7-mean-v1',strength=0)]*257),
    dict(interventions=[dict(vector_id='qwen-formality-l7-mean-v1',strength=.5,layer_index=11)]),
    dict(alpha=.5),dict(input=' '),dict(generation=dict(max_new_tokens=513)),
])
def test_invalid_combinations_never_reach_worker(changes):
    runtime=Runtime()
    with TestClient(create_app(runtime)) as client:
        ready(client)
        # JSON permits no infinity; send raw JSON to exercise server validation.
        response=client.post('/api/v2/lab/runs/stream',content=json.dumps(request(**changes)),headers={'Content-Type':'application/json'})
        assert response.status_code==422
        assert not runtime.calls


def test_empty_baseline_version_conflict_and_v1_compatibility():
    runtime=Runtime()
    with TestClient(create_app(runtime)) as client:
        ready(client)
        assert client.post('/api/v2/lab/runs',json=request(catalog_version='0'*64)).status_code==409
        baseline=client.post('/api/v2/lab/runs',json=request(interventions=[])).json()
        assert baseline['applied']['plan']['interventions']==[]
        old=dict(session_id=str(uuid4()),revision=1,message='Source',alpha=.5,
                 layer_strengths={'7':.4},layer_vector_ids={'7':'qwen-formality-l7-mean-v1'})
        v1=client.post('/api/v1/steering/rewrite',json=old).json()
        v2=client.post('/api/v2/lab/runs',json=request(input='Source',task='rewrite',
            interventions=[dict(vector_id='qwen-formality-l7-mean-v1',strength=.4)])).json()
        assert v1['rewritten_text']==v2['text']
        assert v1['applied']==v2['applied']
        assert len(runtime.calls)==3


def test_catalog_model_is_not_automatically_a_loaded_model():
    runtime=Runtime();runtime.catalog_model_id='other-worker'
    with TestClient(create_app(runtime)) as client:
        ready(client)
        result=client.post('/api/v2/lab/runs/resolve',json=request())
        assert result.status_code==200 and not result.json()['runtime_ready']
        assert client.post('/api/v2/lab/runs',json=request()).status_code==503
        assert not runtime.calls


def test_v1_and_v2_share_latest_revision_cancellation():
    import asyncio
    from secondthought.steering_rewriter import GenerationCancelled
    from website.api.generation import GenerationManager
    from website.api.schemas import RunRequest, RewriteRequest
    class Slow(Runtime):
        def __init__(self):
            super().__init__(); self.entered=Event(); self.cleaned=Event()
        def stream_run(self,plan,message,*,on_text,cancelled,**options):
            if message=='first':
                self.entered.set()
                assert cancelled.wait(2)
                self.cleaned.set()
                raise GenerationCancelled()
            assert self.cleaned.is_set()
            return super().stream_run(plan,message,on_text=on_text,cancelled=cancelled,**options)
    async def scenario():
        runtime=Slow();manager=GenerationManager(runtime);manager.start()
        sid=str(uuid4())
        first=manager.submit(RunRequest(**request(session_id=sid,input='first')))
        assert await asyncio.to_thread(runtime.entered.wait,2)
        latest=manager.submit(RewriteRequest(session_id=sid,revision=2,message='latest',alpha=.5))
        async def terminal(job):
            while True:
                event=await asyncio.wait_for(job.events.get(),3)
                if event['event'] in {'completed','cancelled','error'}: return event
        assert (await terminal(first))['event']=='cancelled'
        assert (await terminal(latest))['rewritten_text']=='A response.'
        await manager.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('outcome',['success','failure','cancelled'])
def test_real_execution_path_adds_shared_layer_vectors_once_and_removes_all_hooks(outcome):
    from threading import Lock
    from types import SimpleNamespace
    import torch
    from secondthought.lab.interventions import Intervention
    from secondthought.steering_rewriter import GenerationCancelled
    from website.api.layers import ExploreRewriter
    service=ExploreRewriter.__new__(ExploreRewriter)
    service.catalog=get_catalog();service._generation_lock=Lock();service.max_new_tokens=64
    service.decoder_layers=torch.nn.ModuleList([torch.nn.Identity() for _ in range(24)])
    service.tokenizer=SimpleNamespace(eos_token_id=3,pad_token_id=3,decode=lambda *args,**kwargs:'A response.')
    service._encode_prompt=lambda text,**kwargs:{'input_ids':torch.zeros((1,2),dtype=torch.long)}
    cancelled=Event();observed={}
    plan=resolve_plan(service.catalog,DEFAULT_MODEL,tuple(Intervention(**i) for i in request()['interventions']))
    class Model:
        def generate(self,input_ids,**kwargs):
            hidden=torch.zeros(1,2,896)
            for index,layer in enumerate(service.decoder_layers):
                observed[index]=(len(layer._forward_hooks),hidden.clone())
                hidden=layer(hidden)
            observed['result']=hidden
            if outcome=='failure': raise RuntimeError('forward failed')
            if outcome=='cancelled': cancelled.set()
            kwargs['streamer'].on_finalized_text('A response.',stream_end=True)
            return torch.cat([input_ids,torch.tensor([[2,3]])],dim=1)
    service.model=Model()
    try:
        if outcome=='failure':
            with pytest.raises(RuntimeError,match='forward failed'):
                service.stream_run(plan,'Input',on_text=lambda text:None,cancelled=cancelled)
        elif outcome=='cancelled':
            with pytest.raises(GenerationCancelled):
                service.stream_run(plan,'Input',on_text=lambda text:None,cancelled=cancelled)
        else:
            assert service.stream_run(plan,'Input',on_text=lambda text:None,cancelled=cancelled).text=='A response.'
        assert observed[7][0]==1 and observed[11][0]==1
        assert sum(observed[i][0] for i in range(24))==2
        expected=sum((service.catalog.vector(i.vector_id)*i.strength for i in plan.interventions),torch.zeros(896))
        assert torch.allclose(observed['result'][0,0],expected,atol=1e-6)
        assert torch.allclose(observed['result'][0,1],expected,atol=1e-6)
    finally:
        assert all(not layer._forward_hooks for layer in service.decoder_layers)
        assert not service._generation_lock.locked()


def test_unavailable_zero_vector_is_rejected_without_silent_fallback():
    from copy import copy
    runtime=Runtime();runtime.catalog=copy(runtime.catalog)
    runtime.catalog._tensors=dict(runtime.catalog._tensors)
    runtime.catalog._tensors.pop('qwen-formality-l7-mean-v1')
    with TestClient(create_app(runtime)) as client:
        ready(client)
        body=request(interventions=[dict(vector_id='qwen-formality-l7-mean-v1',strength=0)])
        assert client.post('/api/v2/lab/runs/resolve',json=body).status_code==422
        assert client.post('/api/v2/lab/runs',json=body).status_code==422
        assert not runtime.calls


def test_registered_unloaded_model_and_cross_model_vector_are_distinct_errors():
    from secondthought.lab.catalog import Catalog
    runtime=Runtime()
    catalog=runtime.catalog
    other=catalog.spec.models[0].model_copy(update=dict(id='other-model',repository='test/other',revision='b'*40))
    runtime.catalog=Catalog(catalog.spec.model_copy(update=dict(models=catalog.spec.models+(other,))),catalog.root)
    with TestClient(create_app(runtime)) as client:
        ready(client)
        blank=request(model_id='other-model',interventions=[])
        result=client.post('/api/v2/lab/runs/resolve',json=blank)
        assert result.status_code==200 and not result.json()['runtime_ready']
        assert client.post('/api/v2/lab/runs',json=blank).status_code==503
        assert client.post('/api/v2/lab/runs',json=request(model_id='other-model')).status_code==422
        assert not runtime.calls
