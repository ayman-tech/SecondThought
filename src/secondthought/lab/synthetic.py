"""Synthetic contrast experiments: immutable prompts, bounded generation, clean splits.

This module prepares data, not a claim that its contrast is causally steerable.
The existing mean-difference extractor consumes the prepared pairs unchanged.
"""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import random
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Spec(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)


class FeatureDefinition(Spec):
    id: str=Field(pattern=r'^[a-z][a-z0-9_]{1,63}$')
    version: str=Field(pattern=r'^[a-z0-9][a-z0-9_-]{0,63}$')
    label: str=Field(min_length=1,max_length=100)
    low: str=Field(min_length=5,max_length=2000)
    high: str=Field(min_length=5,max_length=2000)
    preserve: list[str]=Field(default_factory=lambda:['facts','speaker','stance','names','numbers','requested actions'])
    nuisance_controls: list[str]=Field(default_factory=lambda:['similar length','same topic','same point of view'])
    min_words: int=Field(default=4,ge=1,le=100)
    max_words: int=Field(default=100,ge=4,le=1000)
    max_word_ratio: float=Field(default=1.35,ge=1,le=10)
    scale: Literal['raw','unit_l2']='unit_l2'

    @model_validator(mode='after')
    def bounds(self):
        if self.min_words>self.max_words:raise ValueError('Word bounds are reversed')
        if self.low.strip().casefold()==self.high.strip().casefold():raise ValueError('Contrast endpoints must differ')
        return self


class Scenario(Spec):
    id: str=Field(min_length=1,max_length=100)
    family: str=Field(min_length=1,max_length=200)
    task: str=Field(min_length=1,max_length=1000)
    context: str=Field(min_length=5,max_length=8000)
    required_terms: list[str]=Field(default_factory=list)


class Contrast(Spec):
    low: str=Field(min_length=1,max_length=20000)
    high: str=Field(min_length=1,max_length=20000)


def sha(value):
    if not isinstance(value,bytes):value=json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
    return hashlib.sha256(value).hexdigest()


def normalize(text):return ' '.join(text.split()).casefold()


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_json(path,value):
    Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')


def write_jsonl(path,rows):
    Path(path).write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows))


def make_plan(definition,scenarios,run,seed=42,variants=1):
    definition=FeatureDefinition.model_validate(definition)
    scenarios=[Scenario.model_validate(row) for row in scenarios]
    if not 1<=variants<=20:raise ValueError('Use 1–20 variants per scenario')
    if len({s.id for s in scenarios})!=len(scenarios):raise ValueError('Duplicate scenario ID')
    contexts={}
    for scenario in scenarios:
        text=normalize(scenario.context)
        if text in contexts and contexts[text]!=scenario.family:raise ValueError('Same context crosses scenario families')
        contexts[text]=scenario.family
        if any(not term.strip() or term.casefold() not in scenario.context.casefold() for term in scenario.required_terms):
            raise ValueError('Required terms must occur in the context')
    families=sorted({s.family for s in scenarios})
    if len(families)<10:raise ValueError('Use at least 10 independent scenario families')
    random.Random(seed).shuffle(families)
    n=max(2,len(families)//5)
    assignment={family:('test' if i<n else 'heldout' if i<2*n else 'extraction') for i,family in enumerate(families)}
    configuration=dict(feature=definition.model_dump(),scenarios=[s.model_dump() for s in scenarios],seed=seed,variants=variants)
    experiment_id=sha(configuration)
    system=('Generate exactly one controlled contrast pair as JSON with only keys "low" and "high". '
        'Both must fulfill the SAME task in the SAME scenario and preserve its facts. '
        'Change only the specified feature. Do not put feature labels, explanations, ratings or headings in either text. '
        'Return the JSON object only. Do not claim the pair has been independently validated.')
    requests=[]
    for scenario in scenarios:
        for variant in range(variants):
            payload=dict(feature=definition.model_dump(),task=scenario.task,context=scenario.context,
                required_terms=scenario.required_terms,variation=variant,
                instruction='low realizes the low endpoint; high realizes the high endpoint. Both must include all required_terms.')
            request_id=sha(dict(experiment_id=experiment_id,scenario=scenario.id,variant=variant))
            requests.append(dict(request_id=request_id,scenario_id=scenario.id,family=scenario.family,
                split=assignment[scenario.family],variant=variant,system=system,input=json.dumps(payload,ensure_ascii=False)))
    run=Path(run);run.mkdir(parents=True,exist_ok=False)
    write_json(run/'feature.json',definition.model_dump())
    write_jsonl(run/'scenarios.jsonl',[s.model_dump() for s in scenarios])
    write_jsonl(run/'requests.jsonl',requests)
    manifest=dict(format_version=1,experiment_id=experiment_id,configuration=configuration,
        requests_sha256=sha((run/'requests.jsonl').read_bytes()),
        feature_sha256=sha((run/'feature.json').read_bytes()),scenarios_sha256=sha((run/'scenarios.jsonl').read_bytes()),
        splits=dict(Counter(r['split'] for r in requests)),
        created_at=datetime.now(UTC).isoformat(),preparation_code_sha256=sha(Path(__file__).read_bytes()))
    write_json(run/'plan.json',manifest)
    return manifest


def load_plan(run):
    run=Path(run);manifest=json.loads((run/'plan.json').read_text())
    for filename,key in [('requests.jsonl','requests_sha256'),('feature.json','feature_sha256'),('scenarios.jsonl','scenarios_sha256')]:
        if sha((run/filename).read_bytes())!=manifest[key]:raise ValueError('Immutable plan file changed: '+filename)
    if sha(manifest['configuration'])!=manifest['experiment_id']:raise ValueError('Experiment fingerprint mismatch')
    return manifest,read_jsonl(run/'requests.jsonl')


def generate(run,provider,model,max_requests,max_output_tokens=512,base_url=None):
    """Explicit bounded calls; no automatic provider retries or hidden judging."""
    from openai import OpenAI
    if provider not in ('responses','chat'):raise ValueError('Choose responses or chat backend')
    if max_requests<1 or not 64<=max_output_tokens<=4096:raise ValueError('Invalid request/token budget')
    if not model.strip():raise ValueError('Specify a teacher model')
    if base_url:
        from urllib.parse import urlsplit
        parsed=urlsplit(base_url)
        if parsed.scheme not in ('http','https') or parsed.username or parsed.password or parsed.query:
            raise ValueError('Use an HTTP(S) endpoint without credentials/query parameters')
    run=Path(run);manifest,requests=load_plan(run)
    teacher=dict(provider=provider,model=model,base_url=base_url,max_output_tokens=max_output_tokens)
    teacher_path=run/'teacher.json'
    if teacher_path.exists() and json.loads(teacher_path.read_text())!=teacher:raise ValueError('Teacher settings changed; use a new run')
    if not teacher_path.exists():write_json(teacher_path,teacher)
    raw=run/'responses.jsonl'
    previous=read_jsonl(raw) if raw.exists() else []
    seen={row['request_id'] for row in previous}
    client=OpenAI(max_retries=0,timeout=90,**({'base_url':base_url,'api_key':os.getenv('OPENAI_API_KEY','local')} if base_url else {}))
    issued=0
    for request in requests:
        if request['request_id'] in seen:continue
        if issued>=max_requests:break
        issued+=1
        record=dict(request_id=request['request_id'],experiment_id=manifest['experiment_id'],teacher=teacher,
            created_at=datetime.now(UTC).isoformat())
        try:
            if provider=='responses':
                response=client.responses.create(model=model,instructions=request['system'],input=request['input'],
                    max_output_tokens=max_output_tokens,store=False)
                text=response.output_text
            else:
                response=client.chat.completions.create(model=model,
                    messages=[dict(role='system',content=request['system']),dict(role='user',content=request['input'])],
                    max_tokens=max_output_tokens)
                text=response.choices[0].message.content or ''
            record.update(status='generated',output=text,response_id=response.id,actual_model=response.model,
                usage=response.usage.model_dump() if response.usage else None)
        except Exception as exc:
            record.update(status='error',error_type=type(exc).__name__,http_status=getattr(exc,'status_code',None))
        with raw.open('a') as stream:
            stream.write(json.dumps(record,ensure_ascii=False)+'\n');stream.flush();os.fsync(stream.fileno())
        print(f'{issued}: {request["request_id"][:10]} {record["status"]}',flush=True)
    return dict(issued_requests=issued,already_recorded=len(seen),pending=max(0,len(requests)-len(seen)-issued))


def parse_contrast(value):
    if isinstance(value,str):
        text=value.strip()
        if text.startswith('```') and text.endswith('```'):
            text=re.sub(r'^```(?:json)?\s*','',text)[:-3].strip()
        value=json.loads(text)
    return Contrast.model_validate(value)


def validate_contrast(pair,definition,scenario):
    low,high=pair.low.strip(),pair.high.strip()
    if normalize(low)==normalize(high):return 'identical_endpoints'
    counts=[len(t.split()) for t in (low,high)]
    if min(counts)<definition.min_words or max(counts)>definition.max_words:return 'word_bounds'
    if max(counts)/min(counts)>definition.max_word_ratio:return 'length_confound'
    numbers=lambda text:Counter(re.findall(r'\d+(?:[.,:]\d+)*',text))
    if numbers(low)!=numbers(high):return 'numbers_differ'
    if numbers(low)-numbers(scenario.context):return 'invented_number'
    for term in scenario.required_terms:
        if any(not re.search(r'(?<!\w)'+re.escape(term)+r'(?!\w)',text,re.I) for text in (low,high)):
            return 'required_term_missing'
    if any(re.match(r'^(?:low|high)(?:\s+\w+){0,3}\s*:',t,re.I) for t in (low,high)):return 'endpoint_label_in_text'
    return None


def prepare(run,responses=None,output=None,approvals=None):
    run=Path(run);manifest,requests=load_plan(run)
    definition=FeatureDefinition.model_validate(manifest['configuration']['feature'])
    scenarios={s['id']:Scenario.model_validate(s) for s in manifest['configuration']['scenarios']}
    requests={r['request_id']:r for r in requests}
    responses=Path(responses or run/'responses.jsonl');rows=read_jsonl(responses)
    if any(not isinstance(row,dict) or not isinstance(row.get('request_id'),str) for row in rows):
        raise ValueError('Each response must have a string request_id')
    if len({row['request_id'] for row in rows})!=len(rows):raise ValueError('Duplicate response IDs; provide one response per request')
    if any(row['request_id'] not in requests or row.get('experiment_id')!=manifest['experiment_id'] for row in rows):
        raise ValueError('Response is not bound to this experiment plan')
    approved_rows=json.loads(Path(approvals).read_text()) if approvals else None
    if approved_rows is not None and (not isinstance(approved_rows,list) or any(not isinstance(v,str) for v in approved_rows)):
        raise ValueError('Approvals must be a JSON list of request IDs')
    approved=set(approved_rows) if approved_rows is not None else None
    if approved is not None and not approved<=set(requests):raise ValueError('Unknown approval request IDs')
    accepted=[];rejected=[];seen=set()
    for row in rows:
        request=requests[row['request_id']];reason=None;pair=None
        if row.get('status') not in (None,'generated'):reason='generation_error'
        elif approved is not None and row['request_id'] not in approved:reason='not_approved'
        else:
            try:pair=parse_contrast(row.get('output'))
            except (ValueError,TypeError):reason='invalid_json_or_schema'
        if pair:
            reason=validate_contrast(pair,definition,scenarios[request['scenario_id']])
            keys={normalize(pair.low),normalize(pair.high)}
            if reason is None and keys&seen:reason='duplicate_text'
            if reason is None:
                seen.update(keys)
                accepted.append(dict(source=pair.low.strip(),target=pair.high.strip(),
                    group=sha(request['family']),row_id=row['request_id'],split=request['split']))
        if reason:rejected.append(dict(request_id=row['request_id'],reason=reason))
    output=Path(output or run/'dataset')
    if (output/'pairs.jsonl').exists():raise ValueError('Prepared dataset already exists; use a new output/version')
    output.mkdir(parents=True,exist_ok=True)
    counts=dict(Counter(row['split'] for row in accepted))
    ready=counts.get('extraction',0)>=2 and counts.get('heldout',0)>=2
    summary=dict(experiment_id=manifest['experiment_id'],accepted=len(accepted),rejected=len(rejected),
        pending=len(requests)-len(rows),split_counts=counts,rejection_reasons=dict(Counter(r['reason'] for r in rejected)),
        ready_for_extraction=ready,review='approved_only' if approved is not None else 'heuristics_only_unreviewed')
    write_jsonl(output/'accepted.jsonl',accepted);write_jsonl(output/'rejected.jsonl',rejected)
    write_json(output/'summary.json',summary)
    write_jsonl(output/'evaluation.jsonl',[row for row in accepted if row['split']=='test'])
    if ready:
        write_jsonl(output/'pairs.jsonl',[row for row in accepted if row['split']!='test'])
        metadata=dict(feature=definition.id,dataset='Synthetic contrast experiment '+definition.version,
            pairs_sha256=sha((output/'pairs.jsonl').read_bytes()),experiment_id=manifest['experiment_id'],
            definition=definition.model_dump(),pair_construction='synthetic low/high responses to identical scenario and task',
            split_policy='scenario families assigned before generation; reserved test excluded from extraction/held-out pairs',
            input_sha256=sha(responses.read_bytes()),plan_sha256=sha((run/'plan.json').read_bytes()),
            response_teachers=[json.loads(value) for value in sorted({json.dumps(
                {key:value for key,value in r.get('teacher',{}).items() if key in ('provider','model','base_url','max_output_tokens')},sort_keys=True) for r in rows})],
            summary=summary,limitations='Synthetic contrast; heuristic checks do not establish semantic equivalence or causal steering. '+summary['review'])
        write_json(output/'pairs.metadata.json',metadata)
    return summary
