from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_chat_sse_streams_tokens_then_done() -> None:
    with client.stream("POST", "/chat", json={"query": "What is CHT?"}) as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        body = "".join(response.iter_text())
    assert "data:" in body
    assert "[DONE]" in body
    assert "CHT?" in body


def test_chat_rejects_empty_query() -> None:
    response = client.post("/chat", json={"query": ""})
    assert response.status_code == 422
