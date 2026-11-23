"""Canonical run configuration, v1 adaptation and reproducible run identity."""
import hashlib
import json

from secondthought.lab.catalog import get_catalog
from secondthought.lab.interventions import Intervention
from secondthought.lab.plans import resolve_plan
from .schemas import RunRequest, RewriteRequest
from .prompts import prompt_format

DEFAULT_MODEL = 'qwen2.5-0.5b-instruct'


def canonical_request(request: RunRequest | RewriteRequest, catalog=None) -> RunRequest:
    if isinstance(request, RunRequest):
        return request
    catalog = catalog or get_catalog()
    strengths = request.layer_strengths if request.layer_strengths is not None else {11:request.alpha}
    overrides = request.layer_vector_ids or {}
    return RunRequest(session_id=request.session_id, revision=request.revision,
        model_id=DEFAULT_MODEL, catalog_version=catalog.version, input=request.message,
        task=request.task, system_prompt=request.system_prompt,
        generation=dict(max_input_tokens=request.max_input_tokens,max_new_tokens=request.max_new_tokens),
        interventions=tuple(Intervention(vector_id=overrides.get(index,
            catalog.defaults[(DEFAULT_MODEL,index)]),strength=strength)
            for index,strength in sorted(strengths.items())))


def resolve_run(request: RunRequest, catalog=None):
    catalog = catalog or get_catalog()
    if request.catalog_version is not None and request.catalog_version != catalog.version:
        raise ValueError('Catalog version changed; reload the catalog before retrying')
    plan = resolve_plan(catalog,request.model_id,request.interventions)
    configuration = dict(plan=plan.public(),task=request.task,system_prompt=request.system_prompt,
        prompt_format=prompt_format(request.task),
        generation=request.generation.model_dump(),
        input_sha256=hashlib.sha256(request.input.encode()).hexdigest(),
        decoding='greedy')
    experiment_id = hashlib.sha256(json.dumps(configuration,sort_keys=True,
        separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return plan,dict(experiment_id=experiment_id,**configuration)
