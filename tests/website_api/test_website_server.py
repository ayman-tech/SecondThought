from __future__ import annotations

import asyncio
import json
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
    return dict(session_id=str(uuid4()), revision=1, message="hello", alpha=0.5, **overrides)


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


@pytest.mark.parametrize("changes", [
    {"message": " "}, {"message": "x" * 2001}, {"alpha": 3},
    {"alpha": "NaN"}, {"alpha": "Infinity"}, {"beta": 1},
    {"revision": -1}, {"revision": 1.5}, {"session_id": "not-a-uuid"},
    {"unexpected": "setting"},
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
