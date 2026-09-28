from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.server import create_app
from secondthought.rewriter import OpenAIRewriter


class FakeResponses:
    def __init__(self, output_text="Please fix the timeout before merging.", error=None):
        self.output_text = output_text
        self.error = error
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return SimpleNamespace(id="response-1", output_text=self.output_text, usage=None)


def make_client(tmp_path, responses):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Rewrite professionally.", encoding="utf-8")
    rewriter = OpenAIRewriter(
        model="test-model",
        prompt_path=prompt,
        client=SimpleNamespace(responses=responses),
    )
    return TestClient(create_app(rewriter=rewriter))


def test_rewrite_returns_existing_rewriter_output(tmp_path):
    responses = FakeResponses()
    client = make_client(tmp_path, responses)

    response = client.post("/rewrite", json={"message": "Fix this stupid timeout."})

    assert response.status_code == 200
    body = response.json()
    assert body["rewritten_text"] == "Please fix the timeout before merging."
    assert body["original_text"] == "Fix this stupid timeout."
    assert body["model_info"] == "test-model"
    assert responses.kwargs["instructions"] == "Rewrite professionally."


def test_rewrite_rejects_blank_message(tmp_path):
    client = make_client(tmp_path, FakeResponses())

    assert client.post("/rewrite", json={"message": "   "}).status_code == 400
    assert client.post("/rewrite", json={"message": ""}).status_code == 422


def test_rewrite_reports_provider_auth_error(tmp_path):
    error = Exception("bad key")
    error.status_code = 401
    client = make_client(tmp_path, FakeResponses(error=error))

    response = client.post("/rewrite", json={"message": "Fix it."})

    assert response.status_code == 502
    assert "API key" in response.json()["detail"]


def test_rewrite_reports_empty_model_output(tmp_path):
    client = make_client(tmp_path, FakeResponses(output_text="  "))

    response = client.post("/rewrite", json={"message": "Fix it."})

    assert response.status_code == 502
    assert "empty rewrite" in response.json()["detail"]


def test_health_and_cors_for_extension_origin(tmp_path):
    client = make_client(tmp_path, FakeResponses())
    origin = "chrome-extension://" + "a" * 32

    health = client.get("/health", headers={"Origin": origin})

    assert health.json() == {"status": "ok", "model": "test-model"}
    assert health.headers["access-control-allow-origin"] == origin
    other = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_unconfigured_server_returns_503(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("api.server.load_dotenv", lambda path: None)
    client = TestClient(create_app())

    response = client.post("/rewrite", json={"message": "Fix it."})

    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]
    assert client.get("/health").json()["status"] == "error"
