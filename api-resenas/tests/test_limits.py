import asyncio
import json
from uuid import uuid4

import mongomock
import pytest
from fastapi.testclient import TestClient
from starlette.responses import Response

from app import limits
from app.config import load_settings
from app.limits import MAX_BODY_BYTES, RequestGuardMiddleware
from app.main import create_app


@pytest.mark.parametrize("cidr", ["0.0.0.0/0", "::/0"])
def test_create_app_rejects_universal_trusted_proxy_networks_before_serving(monkeypatch, cidr):
    monkeypatch.setenv("TRUSTED_PROXIES", cidr)
    with pytest.raises(ValueError, match="TRUSTED_PROXIES.*rangos /0"):
        create_app(mongo_client=mongomock.MongoClient())


def test_settings_read_shared_trusted_proxies_name_only(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.0/8")
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "0.0.0.0/0")  # nombre antiguo: no debe leerse
    assert load_settings().trusted_proxy_cidrs == "10.0.0.0/8"


def test_create_app_accepts_restricted_trusted_proxy_network(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.0/8")
    app = create_app(mongo_client=mongomock.MongoClient())
    assert app is not None


@pytest.mark.parametrize(
    ("headers", "size", "status"),
    [
        ([(b"content-length", b"262145")], 1, 413),
        ([(b"content-length", b"1")], MAX_BODY_BYTES + 1, 413),
        ([(b"transfer-encoding", b"chunked")], MAX_BODY_BYTES + 1, 413),
        ([(b"transfer-encoding", b"chunked")], MAX_BODY_BYTES, 200),
    ],
)
def test_body_limit_applies_before_route_even_when_it_does_not_read(headers, size, status):
    async def exercise():
        messages = []
        chunks = iter([
            {"type": "http.request", "body": b"x", "more_body": True},
            {"type": "http.request", "body": b"y" * (size - 1), "more_body": False},
        ])

        async def receive():
            return next(chunks)

        async def send(message):
            messages.append(message)

        async def route(scope, receive, send):
            await Response(status_code=200)(scope, receive, send)

        guard = RequestGuardMiddleware(route)
        await guard(
            {
                "type": "http", "method": "GET", "path": "/anything",
                "headers": headers, "client": ("192.0.2.10", 12345),
            },
            receive,
            send,
        )
        return messages

    messages = asyncio.run(exercise())
    assert messages[0]["status"] == status
    if status == 413:
        assert (b"content-type", b"application/json") in messages[0]["headers"]
        assert json.loads(messages[1]["body"]) == {
            "success": False, "message": "El cuerpo excede el límite de 256 KiB.", "errors": {},
        }


def test_query_quota_ignores_spoofed_ip_from_untrusted_peer(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", "")
    app = create_app(mongo_client=mongomock.MongoClient())

    with TestClient(app, client=("192.0.2.1", 12345)) as client:
        path = f"/api/resenas/producto/{uuid4()}"
        for attempt in range(120):
            response = client.get(path, headers={"X-Forwarded-For": f"203.0.113.{attempt}"})
            assert response.status_code == 200

        blocked = client.get(path, headers={"X-Forwarded-For": "203.0.113.200"})
        assert blocked.status_code == 429
        assert blocked.json()["success"] is False
        assert 1 <= int(blocked.headers["Retry-After"]) <= 60
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 200


def test_trusted_proxy_uses_rightmost_untrusted_hop(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.0/24")
    app = create_app(mongo_client=mongomock.MongoClient())

    with TestClient(app, client=("10.0.0.1", 12345)) as client:
        for attempt in range(30):
            response = client.post("/api/resenas", headers={
                "X-Forwarded-For": f"203.0.113.{attempt}, 192.0.2.1, 10.0.0.2",
            }, json={})
            assert response.status_code == 401

        blocked = client.post("/api/resenas", headers=[
            ("X-Forwarded-For", "203.0.113.99"),
            ("X-Forwarded-For", "192.0.2.1, 10.0.0.2"),
        ], json={})
        assert blocked.status_code == 429
        assert client.post("/api/resenas", headers={
            "X-Forwarded-For": "192.0.2.2, 10.0.0.2",
        }, json={}).status_code == 401


def test_internal_quota_and_retry_after_rounding():
    now = 0.0
    guard = RequestGuardMiddleware(Response(), clock=lambda: now)
    client = TestClient(guard)
    for _ in range(300):
        assert client.get("/internal/example").status_code == 200

    now = 58.1
    blocked = client.post("/internal/example")
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "2"
    assert client.get("/api/resenas").status_code == 200

    now = 60.0
    assert client.post("/internal/example").status_code == 200


def test_counter_capacity_preserves_active_counters_and_purges_expired_ones(monkeypatch):
    monkeypatch.setattr(limits, "MAX_COUNTERS", 2)
    now = 0.0
    guard = RequestGuardMiddleware(Response(), clock=lambda: now)
    client = TestClient(guard)
    assert client.get("/api/resenas").status_code == 200
    assert client.post("/api/resenas").status_code == 200
    assert client.get("/internal/example").status_code == 429
    assert len(guard.counters) == 2
    assert client.get("/api/resenas").status_code == 200

    now = 60.0
    assert client.get("/internal/example").status_code == 200
    assert len(guard.counters) == 1
