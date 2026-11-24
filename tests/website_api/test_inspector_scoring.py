"""Response inspector scoring: the /api/v2/lab/score endpoint and ResponseScorer's output shape."""

from __future__ import annotations

import threading
from time import sleep

from fastapi.testclient import TestClient

from secondthought.steering_rewriter import GenerationResult
from website.api.scoring import ResponseScorer
from website.api.server import create_app


class FakeService:
    model_id = "test/qwen"

    def stream_rewrite(self, message, alpha, beta, *, on_text, cancelled, **kwargs):
        on_text("A considered rewrite.")
        return GenerationResult("A considered rewrite.", 5, "stop")


class FakeScorer:
    def __init__(self):
        self.calls = []

    def score(self, source, response, task):
        self.calls.append((source, response, task))
        if not response.strip():
            raise ValueError("Both the input and the response need text to score")
        return {"formality": {"input": 0.4, "response": 0.9, "lowest": 0.9, "lowest_sentence": response},
                "toxicity": {"input": 0.8, "response": 0.01}, "similarity": 0.95, "values": None, "models": {}}


def wait_for_scoring(client, status):
    for _ in range(200):
        if client.get("/api/v1/steering/config").json()["scoring"] == status:
            return
        sleep(0.01)
    raise AssertionError(f"scoring never became {status}")


def test_completed_responses_are_scored():
    scorer = FakeScorer()
    with TestClient(create_app(FakeService(), scorer_factory=lambda: scorer)) as client:
        wait_for_scoring(client, "ready")
        body = {"input": "You idiot, fix it by 5 PM.", "response": "Please fix it by 5 PM.", "task": "rewrite"}
        response = client.post("/api/v2/lab/score", json=body)
        assert response.status_code == 200
        assert response.json()["status"] == "scored" and response.json()["toxicity"]["response"] == 0.01
        assert scorer.calls == [(body["input"], body["response"], "rewrite")]
        assert client.post("/api/v2/lab/score", json=body | {"response": "  "}).status_code == 422
        assert client.post("/api/v2/lab/score", json=body | {"extra": 1}).status_code == 422
        assert client.post("/api/v2/lab/score", json=body | {"task": "poem"}).status_code == 422


def test_scoring_reports_disabled_and_broken_without_breaking_the_page():
    with TestClient(create_app(FakeService())) as client:
        wait_for_scoring(client, "disabled")
        assert client.post("/api/v2/lab/score", json={"input": "a", "response": "b"}).json() == {
            "detail": "Scoring is disabled"}

    def broken():
        raise RuntimeError("detoxify is not installed")

    with TestClient(create_app(FakeService(), scorer_factory=broken)) as client:
        wait_for_scoring(client, "unavailable")
        assert client.post("/api/v2/lab/score", json={"input": "a", "response": "b"}).status_code == 503
        assert client.get("/explore").status_code == 200


class _Fixed:
    """Stands in for the three models inside ResponseScorer."""
    model_name = "fixed"

    def score(self, texts):
        return [0.7 if "idiot" in text else 0.1 for text in texts]

    def score_pairs(self, pairs):
        return [0.93 for _ in pairs]


def test_response_scorer_shape_for_rewrite_and_other_tasks():
    scorer = ResponseScorer.__new__(ResponseScorer)  # skip loading the real models
    scorer._toxicity = scorer._formality = scorer._similarity = _Fixed()
    scorer.models = {}
    scorer._lock = threading.Lock()

    rewrite = scorer.score("You idiot, ship 3 boxes by 5 PM.", "Please ship 2 boxes by 5 PM today.", "rewrite")
    assert rewrite["toxicity"] == {"input": 0.7, "response": 0.1}
    assert rewrite["similarity"] == 0.93
    assert rewrite["values"]["count"] == 2 and rewrite["values"]["kept"] == 1
    assert rewrite["values"]["missing"] == ["3"] and rewrite["values"]["added"] == ["2", "today"]

    other = scorer.score("You idiot.", "Here is a reply.", "continue")
    assert other["similarity"] is None and other["values"] is None
