"""Smoke tests for the extension's local API, using a stand-in rewriter so no model is loaded."""

import os
from pathlib import Path
from types import SimpleNamespace

# Importing the server module builds the real rewriter (`app = create_app()` at module level).
# Point that at a config that does not exist, so the import stays fast and model-free; every test
# below builds its own app around a fake rewriter instead.
os.environ["SECONDTHOUGHT_CONFIG"] = str(Path(__file__).with_name("no-such-config.toml"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from extension.api.server import MAX_MESSAGE_CHARS, create_app  # noqa: E402

EXTENSION_ORIGIN = "chrome-extension://" + "abcdefghijklmnop" * 2


class FakeRewriter:
    model = "fake: drop the word stupid"

    def rewrite(self, message):
        if not message.strip():
            raise ValueError("The message is empty.")
        if "explode" in message:
            raise RuntimeError("the model failed")
        return SimpleNamespace(
            original_text=message,
            rewritten_text=message.replace("stupid ", ""),
            model_info=self.model,
            latency_ms=1.5,
        )


@pytest.fixture
def client():
    return TestClient(create_app(rewriter=FakeRewriter()))


def test_health_reports_the_loaded_model(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "model": "fake: drop the word stupid"}


def test_rewrite_returns_the_contract_the_extension_expects(client):
    response = client.post("/rewrite", json={"message": "This stupid loop hits the API 20 times."})

    assert response.status_code == 200
    body = response.json()
    assert body["original_text"] == "This stupid loop hits the API 20 times."
    assert body["rewritten_text"] == "This loop hits the API 20 times."
    assert body["model_info"] == "fake: drop the word stupid"
    assert body["latency_ms"] == 1.5
    assert isinstance(body["kept_values"], list)
    assert any("20" in value for value in body["kept_values"])


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"message": ""}, 422),                          # fails request validation
        ({"message": "x" * (MAX_MESSAGE_CHARS + 1)}, 422),
        ({"wrong": "field"}, 422),
        ({"message": "   "}, 400),                       # rewriter rejects a blank message
        ({"message": "please explode"}, 502),            # the model itself failed
    ],
)
def test_rewrite_errors_use_the_documented_status_codes(client, payload, status):
    response = client.post("/rewrite", json=payload)

    assert response.status_code == status
    assert "detail" in response.json()


def test_server_without_a_working_config_reports_it_instead_of_crashing(tmp_path):
    broken = TestClient(create_app(config_path=tmp_path / "missing.toml"))

    health = broken.get("/health").json()
    assert health["status"] == "error"
    assert "missing.toml" in health["detail"]
    assert broken.post("/rewrite", json={"message": "hello"}).status_code == 503


def test_cors_allows_only_chrome_extension_origins(client):
    allowed = client.get("/health", headers={"Origin": EXTENSION_ORIGIN})
    refused = client.get("/health", headers={"Origin": "https://evil.example"})

    assert allowed.headers.get("access-control-allow-origin") == EXTENSION_ORIGIN
    assert "access-control-allow-origin" not in refused.headers
