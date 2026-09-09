import time

from api.ulid import new_ulid


def test_ulid_format() -> None:
    value = new_ulid()
    assert len(value) == 26
    assert value.isupper() or value.isdigit() or all(c.isalnum() for c in value)


def test_ulid_is_time_sortable() -> None:
    first = new_ulid()
    time.sleep(0.002)
    second = new_ulid()
    assert first < second


def test_ulid_used_as_request_id_when_header_absent(monkeypatch) -> None:
    monkeypatch.delenv("COMPANION_INTERNAL_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from fastapi.testclient import TestClient

    from main import app

    with TestClient(app) as client:
        with client.stream("POST", "/chat", json={"query": "hi"}) as response:
            request_id = response.headers.get("X-Request-Id")
    assert request_id is not None
    assert len(request_id) == 26
