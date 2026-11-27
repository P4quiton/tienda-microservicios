from datetime import datetime, timedelta, timezone
from uuid import uuid4

import mongomock
import pytest
import jwt
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import Settings
from app.main import create_app


class FakeProductVerifier:
    def __init__(self):
        self.result = "exists"

    def exists(self, _product_id: str) -> None:
        if self.result == "missing":
            from app.errors import ProductNotFound

            raise ProductNotFound
        if self.result == "unavailable":
            from app.errors import ProductServiceUnavailable

            raise ProductServiceUnavailable


@pytest.fixture
def api_client(tmp_path):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_path = tmp_path / "jwt-public.pem"
    public_key_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    settings = Settings(
        port=8008,
        mongo_host="localhost",
        mongo_port=27017,
        mongo_database="db_resenas_test",
        mongo_username="test",
        mongo_password="test",
        mongo_auth_source="admin",
        mongo_timeout_ms=100,
        jwt_issuer="api-usuarios",
        jwt_audience="tienda-microservicios",
        jwt_public_key_path=str(public_key_path),
        productos_api_url="http://productos.test",
    )
    verifier = FakeProductVerifier()
    app = create_app(
        settings,
        mongo_client=mongomock.MongoClient(),
        product_verifier=verifier,
    )
    with TestClient(app) as client:
        yield client, private_key, verifier


def access_token(private_key, *, subject=None, role="cliente"):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(subject or uuid4()),
            "role": role,
            "iss": "api-usuarios",
            "aud": "tienda-microservicios",
            "iat": now,
            "exp": now + timedelta(minutes=60),
        },
        private_key,
        algorithm="RS256",
    )


def test_health_and_empty_review_list(api_client):
    client, _, _ = api_client
    assert client.get("/health").json() == {"status": "ok", "service": "api-resenas"}

    product_id = str(uuid4())
    response = client.get(f"/api/resenas/producto/{product_id}")

    assert response.status_code == 200
    assert response.json()["data"] == {"items": [], "promedio": None, "total": 0}


def test_create_uses_jwt_subject_and_returns_contract_shape(api_client):
    client, private_key, _ = api_client
    user_id = uuid4()
    product_id = uuid4()
    token = access_token(private_key, subject=user_id)

    response = client.post(
        "/api/resenas",
        headers={"Authorization": f"Bearer {token}"},
        json={"producto_id": str(product_id), "calificacion": 5, "comentario": "Excelente"},
    )

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["producto_id"] == str(product_id)
    assert data["usuario_id"] == str(user_id)
    assert data["calificacion"] == 5
    assert len(data["id"]) == 36
    assert data["creado_en"].endswith("Z") or data["creado_en"].endswith("+00:00")

    listed = client.get(f"/api/resenas/producto/{product_id}").json()["data"]
    assert listed["total"] == 1
    assert listed["promedio"] == 5.0


def test_duplicate_user_product_pair_returns_conflict(api_client):
    client, private_key, _ = api_client
    user_id = uuid4()
    product_id = str(uuid4())
    headers = {"Authorization": f"Bearer {access_token(private_key, subject=user_id)}"}
    body = {"producto_id": product_id, "calificacion": 4, "comentario": "Bien"}

    assert client.post("/api/resenas", headers=headers, json=body).status_code == 201
    response = client.post("/api/resenas", headers=headers, json=body)

    assert response.status_code == 409


def test_post_requires_auth_and_rejects_user_id_from_body(api_client):
    client, private_key, _ = api_client
    body = {"producto_id": str(uuid4()), "calificacion": 4, "comentario": "Bien"}
    assert client.post("/api/resenas", json=body).status_code == 401

    token = access_token(private_key)
    response = client.post(
        "/api/resenas",
        headers={"Authorization": f"Bearer {token}"},
        json={**body, "usuario_id": str(uuid4())},
    )
    assert response.status_code == 422


def test_bad_json_and_non_v4_product_id_use_api_error_envelope(api_client):
    client, private_key, _ = api_client
    token = access_token(private_key)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    malformed = client.post("/api/resenas", headers=headers, content="{")
    assert malformed.status_code == 400
    assert malformed.json()["success"] is False
    assert "errors" in malformed.json()

    non_v4 = client.get("/api/resenas/producto/00000000-0000-1000-8000-000000000000")
    assert non_v4.status_code == 422
    assert non_v4.json()["success"] is False


@pytest.mark.parametrize("rating", [0, 6, True, 3.5])
def test_rating_must_be_integer_between_one_and_five(api_client, rating):
    client, private_key, _ = api_client
    token = access_token(private_key)
    response = client.post(
        "/api/resenas",
        headers={"Authorization": f"Bearer {token}"},
        json={"producto_id": str(uuid4()), "calificacion": rating, "comentario": "Texto"},
    )
    assert response.status_code == 422


def test_product_not_found_and_unavailable_are_reported(api_client):
    client, private_key, verifier = api_client
    token = access_token(private_key)
    headers = {"Authorization": f"Bearer {token}"}
    body = {"producto_id": str(uuid4()), "calificacion": 4, "comentario": "Bien"}

    verifier.result = "missing"
    assert client.post("/api/resenas", headers=headers, json=body).status_code == 404
    verifier.result = "unavailable"
    assert client.post("/api/resenas", headers=headers, json=body).status_code == 503
