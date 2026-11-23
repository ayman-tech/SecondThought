from __future__ import annotations

import asyncio
import json
import re
from threading import Event
from time import sleep
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from secondthought.steering_rewriter import GenerationCancelled, GenerationResult
from website.api.generation import AdmissionError, GenerationManager
from website.api.schemas import RewriteRequest
from website.api.server import create_app


class FakeService:
    model_id = "test/qwen"

    def __init__(self):
        self.calls = []

    def stream_rewrite(self, message, alpha, beta, *, on_text, cancelled, **kwargs):
        self.calls.append((message, alpha, beta))
        if cancelled.is_set():
            raise GenerationCancelled()
        on_text("A considered ")
        on_text("rewrite.")
        return GenerationResult("A considered rewrite.", 5, "stop")


def payload(**overrides):
    return dict(session_id=str(uuid4()), revision=1, message="hello", alpha=0.5) | overrides


def wait_ready(client):
    for _ in range(100):
        if client.get("/health/ready").status_code == 200:
            return
        sleep(0.01)
    raise AssertionError("Test service did not become ready")


def test_static_page_configuration_and_stream_contract():
    service = FakeService()
    with TestClient(create_app(service)) as client:
        wait_ready(client)
        assert client.get("/").status_code == 200
        assert client.get("/assets/steering.js").status_code == 200
        config = client.get("/api/v1/steering/config").json()
        assert config["layer"] == 11 and config["beta"] == 0
        assert config["alpha"]["min"] == -2 and config["alpha"]["max"] == 2
        body = payload()
        response = client.post("/api/v1/steering/stream", json=body)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        events = [json.loads(line) for line in response.text.splitlines()]
        assert [e["event"] for e in events] == ["queued", "started", "delta", "delta", "completed"]
        assert all(e["revision"] == 1 and e["alpha"] == 0.5 for e in events)
        assert events[-1]["rewritten_text"] == "A considered rewrite."
        assert service.calls == [("hello", 0.5, 0)]
        assert client.post("/api/v1/steering/rewrite", json=body).status_code == 409


def test_lab_assets_and_relative_imports_share_a_versioned_prefix():
    with TestClient(create_app(FakeService())) as client:
        html = client.get('/explore').text
        source = re.search(r'<script type="module" src="([^"]+/steering.js)"',html)[1]
        assert re.fullmatch(r'/assets/build-[0-9a-f]{16}/steering.js',source)
        prefix = source.rsplit('/',1)[0]
        assert f'href="{prefix}/experiment.css"' in html
        assert f'href="{prefix}/styles.css"' in html
        for filename in ('steering.js','layers.js','layer-evidence.js','lifecycle.js','styles.css'):
            response = client.get(f'{prefix}/{filename}')
            assert response.status_code == 200
            assert response.headers['cache-control'] == 'no-cache'
        assert client.get('/assets/layers.js').headers['cache-control'] == 'no-cache'


@pytest.mark.parametrize("path", ["/explore", "/community", "/evaluation"])
def test_pages_have_separate_content_and_navigation(path):
    with TestClient(create_app(FakeService())) as client:
        response = client.get(path)
        assert response.status_code == 200
        html = response.text
        assert f'href="{path}" class="nav-active" aria-current="page"' in html
        assert ('/steering.js"' in html) == (path == "/explore")
        for target in ("/explore", "/community", "/evaluation"):
            assert f'href="{target}"' in html
        assert "{%" not in html and "{{" not in html
        if path == "/evaluation":
            assert '<section class="evaluation-page" aria-label="Evaluation">' in html
            assert 'src="/assets/evaluation.js"' in html and "data-eval-chart" in html
            data = client.get("/assets/eval-results.json").json()
            assert [len(s["messages"]) for s in data["systems"]] == [35]
            assert all("edit_ratio" in m for m in data["systems"][0]["messages"])
            assert "data-eval-units" in html and "data-eval-strip" in html


def test_multilayer_contract_and_legacy_redirects():
    class Capture(FakeService):
        def stream_rewrite(self, *args, **kwargs):
            self.strengths = kwargs.get("layer_strengths")
            return super().stream_rewrite(*args, **kwargs)
    service = Capture()
    with TestClient(create_app(service)) as client:
        wait_ready(client)
        for path, target in [("/", "/explore"), ("/steering", "/explore"), ("/extension", "/community"), ("/about", "/community")]:
            assert client.get(path, follow_redirects=False).headers["location"] == target
        manifest = client.get("/api/v1/steering/config").json()["layers"]
        assert len(manifest) == 24
        assert [x["index"] for x in manifest if x["available"]] == list(range(24))
        response = client.post("/api/v1/steering/rewrite", json=payload(layer_strengths={"4": 0.3,"11": 0.5}))
        assert response.status_code == 200
        assert service.strengths == {4: 0.3,11: 0.5}
        assert response.json()["layer_strengths"] == {"4":0.3,"11":0.5}


def test_json_endpoint_and_cancel_are_revision_scoped():
    with TestClient(create_app(FakeService())) as client:
        wait_ready(client)
        body = payload()
        response = client.post("/api/v1/steering/rewrite", json=body)
        assert response.status_code == 200
        assert response.json()["finish_reason"] == "stop"
        assert client.post("/api/v1/steering/cancel", json={
            "session_id": body["session_id"], "revision": 1,
        }).status_code == 200


def test_catalog_is_read_only_and_exposes_full_feature_layer_pooling_coverage():
    with TestClient(create_app(FakeService())) as client:
        wait_ready(client)
        data=client.get('/api/v2/lab/catalog').json()
        assert data['schema_version']==1 and data['runtime_status']=='ready'
        assert len(data['catalog_version'])==64
        assert all(vector['available'] for vector in data['vectors'])
        for feature in ('formality','detoxification'):
            entries=[v for v in data['vectors'] if v['feature_id']==feature and v['behavioral_status']=='experimental']
            assert {(v['layer_index'],v['pooling']) for v in entries} == {(i,p) for i in range(24) for p in ('mean','final_token')}
        assert client.post('/api/v2/lab/catalog',json={}).status_code==405
        assert 'raw_directions' not in data


def test_catalog_digest_versions_both_config_and_completed_events():
    from secondthought.lab.catalog import get_catalog
    service=FakeService()
    service.catalog_version=get_catalog().version
    with TestClient(create_app(service)) as client:
        wait_ready(client)
        config=client.get('/api/v1/steering/config').json()
        result=client.post('/api/v1/steering/rewrite',json=payload()).json()
        assert result['steering_version']==config['steering_version']
        assert result['steering_version'].endswith(config['catalog_version'])


@pytest.mark.parametrize("changes", [
    {"message": " "}, {"message": "x" * 20001}, {"alpha": 3},
    {"alpha": "NaN"}, {"alpha": "Infinity"}, {"beta": 1},
    {"revision": -1}, {"revision": 1.5}, {"session_id": "not-a-uuid"},
    {"unexpected": "setting"}, {"layer_strengths": {"24": 0.5}},
    {"layer_strengths": {"11": 3}}, {"layer_strengths": {"0": "NaN"}},
    {"layer_vector_ids": {"11": "qwen-detoxification-l11-mean-v1"}},
    {"layer_strengths": {"11": .5}, "layer_vector_ids": {"11": "unknown"}},
    {"layer_strengths": {"11": .5}, "layer_vector_ids": {"11": "qwen-detoxification-l3-mean-v1"}},
    {"layer_strengths": {}, "layer_vector_ids": {"11": "qwen-detoxification-l11-mean-v1"}},
    {"task":"unknown"}, {"task":"none","system_prompt":"hidden instruction"},
    {"task":"custom","system_prompt":" "}, {"system_prompt":"not the rewrite preset"},
    {"task":"custom","system_prompt":"x"*4001},
    {"max_input_tokens":4097}, {"max_input_tokens":127}, {"max_input_tokens":True},
    {"max_new_tokens":513}, {"max_new_tokens":31}, {"max_new_tokens":64.5},
])
def test_invalid_input_never_reaches_the_model(changes):
    service = FakeService()
    with TestClient(create_app(service)) as client:
        wait_ready(client)
        body = payload(); body.update(changes)
        assert client.post("/api/v1/steering/stream", json=body).status_code == 422
        assert not service.calls


def test_model_failure_keeps_frontend_available():
    def broken_factory():
        raise FileNotFoundError("private/local/path")
    with TestClient(create_app(service_factory=broken_factory)) as client:
        for _ in range(100):
            if client.get("/api/v1/steering/config").json()["status"] == "unavailable":
                break
            sleep(0.01)
        assert client.get("/").status_code == 200
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        response = client.post("/api/v1/steering/rewrite", json=payload())
        assert response.status_code == 503
        assert "private/local/path" not in response.text


@pytest.mark.parametrize("exception,code", [
    (ValueError("Please shorten the draft."), "invalid_input"),
    (TimeoutError("Generation timed out."), "timeout"),
    (RuntimeError("internal model path"), "generation_failed"),
])
def test_generation_failures_are_terminal_events(exception, code):
    class Broken(FakeService):
        def stream_rewrite(self, *args, **kwargs):
            raise exception
    with TestClient(create_app(Broken())) as client:
        wait_ready(client)
        response = client.post("/api/v1/steering/stream", json=payload())
        events = [json.loads(line) for line in response.text.splitlines()]
        assert events[-1]["event"] == "error" and events[-1]["code"] == code
        assert "internal model path" not in response.text


async def terminal(job):
    while True:
        item = await asyncio.wait_for(job.events.get(), 3)
        if item["event"] in {"completed", "cancelled", "error"}:
            return item


def test_latest_pending_request_replaces_earlier_ones_and_queue_is_bounded():
    async def scenario():
        service = FakeService()
        manager = GenerationManager(service, max_pending=2)
        sid = str(uuid4())
        first = manager.submit(RewriteRequest(**(payload() | {"session_id": sid})))
        latest = manager.submit(RewriteRequest(**(payload() | {"session_id": sid, "revision": 2, "alpha": 1})))
        assert first.cancelled.is_set() and len(manager.pending) == 1
        assert (await terminal(first))["event"] == "cancelled"
        second_tab = manager.submit(RewriteRequest(**payload()))
        with pytest.raises(AdmissionError) as exc:
            manager.submit(RewriteRequest(**payload()))
        assert exc.value.status_code == 429
        with pytest.raises(AdmissionError) as exc:
            manager.submit(RewriteRequest(**(payload() | {"session_id": sid, "revision": 1})))
        assert exc.value.status_code == 409
        # An old disconnect/cancel cannot cancel its replacement.
        manager.cancel(first)
        assert manager.pending[sid] is latest and not latest.cancelled.is_set()
        manager.start()
        assert (await terminal(latest))["event"] == "completed"
        assert (await terminal(second_tab))["event"] == "completed"
        await manager.close()
        assert len(service.calls) == 2
    asyncio.run(scenario())


def test_active_generation_cancels_before_replacement_starts():
    class Slow(FakeService):
        entered = Event()
        cleaned = Event()
        def stream_rewrite(self, message, alpha, beta, *, on_text, cancelled, **kwargs):
            self.calls.append((message, alpha, beta))
            if alpha == 0:
                self.entered.set()
                assert cancelled.wait(timeout=3)
                self.cleaned.set()  # Represents exiting the model's hook context.
                raise GenerationCancelled()
            assert self.cleaned.is_set()
            return GenerationResult("newest", 1, "stop")
    async def scenario():
        service = Slow(); manager = GenerationManager(service); manager.start()
        body = payload() | {"alpha": 0}
        first = manager.submit(RewriteRequest(**body))
        assert await asyncio.to_thread(service.entered.wait, 2)
        latest = manager.submit(RewriteRequest(**(body | {"revision": 2, "alpha": 1})))
        assert (await terminal(first))["event"] == "cancelled"
        assert (await terminal(latest))["rewritten_text"] == "newest"
        await manager.close()
    asyncio.run(scenario())


def test_extension_download_is_a_loadable_zip():
    import io
    import zipfile

    with TestClient(create_app(FakeService())) as client:
        response = client.get("/downloads/secondthought-extension.zip")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        names = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
        assert "SecondThought/manifest.json" in names
        assert "SecondThought/content.js" in names
        assert "SecondThought/HOW TO INSTALL.txt" in names


def test_detox_vector_choice_reaches_worker_and_stream_events():
    from secondthought.lab.catalog import get_catalog
    vector = next(v for v in get_catalog().spec.vectors if
                  v.feature_id == 'detoxification' and v.layer_index == 11 and
                  v.pooling == 'mean' and v.behavioral_status == 'experimental')
    class Capture(FakeService):
        def stream_rewrite(self, *args, **kwargs):
            self.vector_ids = kwargs.get('layer_vector_ids')
            return super().stream_rewrite(*args, **kwargs)
    service = Capture()
    with TestClient(create_app(service)) as client:
        wait_ready(client)
        response = client.post('/api/v1/steering/stream', json=payload(
            layer_strengths={'11': .7}, layer_vector_ids={'11': vector.id}))
        assert response.status_code == 200
        events = [json.loads(line) for line in response.text.splitlines()]
        assert events[-1]['event'] == 'completed'
        assert all(e['layer_vector_ids'] == {'11': vector.id} for e in events)
        assert service.vector_ids == {11: vector.id}


@pytest.mark.parametrize('task,prompt', [('summarize',None),('continue',None),('rewrite_continue',None),('custom','Respond in two short sentences.'),('none',None)])
def test_task_prompt_and_larger_budgets_reach_worker_and_completed_metadata(task,prompt):
    from website.api.prompts import TASKS
    class Capture(FakeService):
        def stream_rewrite(self,*args,**kwargs):
            self.applied = kwargs
            return super().stream_rewrite(*args,**kwargs)
    service = Capture()
    with TestClient(create_app(service)) as client:
        wait_ready(client)
        body = payload(task=task,message='Longer source. '*200,max_input_tokens=4096,max_new_tokens=512)
        if task == 'custom': body['system_prompt'] = prompt
        response = client.post('/api/v1/steering/rewrite',json=body)
        assert response.status_code == 200
        expected = prompt if task == 'custom' else TASKS[task]['system_prompt']
        assert service.applied['system_prompt'] == expected
        assert service.applied['max_input_tokens'] == 4096
        assert service.applied['max_new_tokens'] == 512
        if task == 'continue':
            assert service.applied['user_instruction'] == TASKS['continue']['user_instruction']
        else:
            assert 'user_instruction' not in service.applied
        result = response.json()
        assert result['task'] == task and result['system_prompt'] == expected
        assert result['max_new_tokens'] == 512


def test_download_buttons_always_point_at_the_zip():
    import re

    from jinja2 import Environment, FileSystemLoader

    from website.api.server import FRONTEND

    with TestClient(create_app(FakeService())) as client:
        served = client.get("/community").text
    # A server started before a pull renders the page without the download address;
    # the buttons must still link to the zip, never to an empty href (which saves the page).
    stale = Environment(loader=FileSystemLoader(str(FRONTEND))).get_template("community.html").render(
        page="community", title="Community", description="", navigation=[]
    )
    for html in (served, stale):
        links = re.findall(r'class="(?:download|install)-button" href="([^"]*)"', html)
        assert links == ["/downloads/secondthought-extension.zip"] * 2
