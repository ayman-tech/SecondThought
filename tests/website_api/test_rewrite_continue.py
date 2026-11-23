from threading import Event

import pytest

from secondthought.lab.catalog import get_catalog
from secondthought.lab.interventions import Intervention
from secondthought.lab.plans import resolve_plan
from secondthought.steering_rewriter import GenerationResult, GenerationCancelled
from website.api.layers import ExploreRewriter, DEFAULT_MODEL
from website.api.prompts import TASKS, prompt_format


@pytest.mark.parametrize('finish,cancel', [('stop',False),('length',False),('stop',True)])
def test_both_stages_share_plan_budget_and_cancellation(finish,cancel):
    service=ExploreRewriter.__new__(ExploreRewriter)
    service.catalog=get_catalog()
    plan=resolve_plan(service.catalog,DEFAULT_MODEL,[Intervention(vector_id='qwen-fluency-l11-mean-v1',strength=.5)])
    calls=[];chunks=[];cancelled=Event()
    def run(message,alpha,beta,**options):
        calls.append((message,options))
        assert options['interventions']==plan.interventions
        if len(calls)==1:
            options['on_text']('Rewritten passage.')
            if cancel:cancelled.set()
            return GenerationResult('Rewritten passage.',8,finish)
        options['on_text']('New continuation.')
        return GenerationResult('New continuation.',6,'stop')
    service.stream_rewrite=run
    options=dict(on_text=chunks.append,cancelled=cancelled,max_new_tokens=64,max_input_tokens=2048,
        system_prompt=TASKS['rewrite_continue']['system_prompt'],timeout_seconds=30,
        continuation=prompt_format('rewrite_continue'))
    if cancel:
        with pytest.raises(GenerationCancelled):service.stream_run(plan,'Original',**options)
        assert len(calls)==1
        return
    result=service.stream_run(plan,'Original',**options)
    if finish=='length':
        assert len(calls)==1 and result.text=='Rewritten passage.'
        return
    assert calls[0][1]['max_new_tokens']==32
    assert calls[1][0]=='Rewritten passage.\n\n'
    assert calls[1][1]['max_new_tokens']==56
    assert calls[1][1]['user_instruction']==prompt_format('rewrite_continue')['user_instruction']
    assert calls[1][1]['system_prompt']==prompt_format('rewrite_continue')['continuation_system_prompt']
    assert 0<calls[1][1]['timeout_seconds']<=30
    assert result.text=='Rewritten passage.\n\nNew continuation.'
    assert ''.join(chunks)==result.text
    assert result.generated_tokens==14
