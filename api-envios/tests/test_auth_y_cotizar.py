import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from jsonschema import Draft4Validator

from tests.conftest import SERVICIO, bearer

CUERPO = {"codigo_postal": "06600", "cantidad": 2}


def test_cotizar_con_jwt_valido(client, make_token):
    r = client.post("/api/envios/cotizar", json=CUERPO, headers=bearer(make_token()))
    assert r.status_code == 200
    assert r.json() == {"success": True, "message": "OK", "data": {"costo_envio": "114.00", "dias_estimados": 2}}


def test_cotizar_con_identidad_interna(client):
    assert client.post("/api/envios/cotizar", json=CUERPO, headers=SERVICIO).status_code == 200


def test_cotizar_sin_credencial_401(client):
    r = client.post("/api/envios/cotizar", json=CUERPO)
    assert r.status_code == 401 and r.json()["success"] is False


def test_service_token_incorrecto_401(client):
    r = client.post("/api/envios/cotizar", json=CUERPO, headers={"X-Service-Token": "otro"})
    assert r.status_code == 401


def test_service_token_invalido_no_cae_a_jwt(client, make_token):
    headers = {**bearer(make_token()), "X-Service-Token": "otro"}
    assert client.post("/api/envios/cotizar", json=CUERPO, headers=headers).status_code == 401


@pytest.mark.parametrize("overrides", [
    {"iss": "otro"}, {"aud": "otro"}, {"role": "superadmin"}, {"role": None}, {"sub": "no-uuid"},
    {"exp": datetime.now(timezone.utc) - timedelta(seconds=5)}, {"iat": None}, {"exp": None},
])
def test_jwt_claims_invalidos_401(client, make_token, overrides):
    r = client.post("/api/envios/cotizar", json=CUERPO, headers=bearer(make_token(**overrides)))
    assert r.status_code == 401


def test_jwt_firmado_con_otra_clave_401(client):
    from tests.conftest import _pem_pair, ISSUER, AUDIENCE
    ahora = datetime.now(timezone.utc)
    token = jwt.encode({"sub": str(uuid4()), "role": "cliente", "iss": ISSUER, "aud": AUDIENCE,
                        "iat": ahora, "exp": ahora + timedelta(minutes=5)}, _pem_pair()[0], algorithm="RS256")
    assert client.post("/api/envios/cotizar", json=CUERPO, headers=bearer(token)).status_code == 401


def test_jwt_alg_none_y_hs256_rechazados(client, keys):
    ahora = datetime.now(timezone.utc)
    claims = {"sub": str(uuid4()), "role": "admin", "iss": "api-usuarios", "aud": "tienda-microservicios",
              "iat": ahora, "exp": ahora + timedelta(minutes=5)}
    sin_firma = jwt.encode(claims, None, algorithm="none")
    hs256 = jwt.encode(claims, "secreto-largo-de-prueba-para-hs256-0123456789", algorithm="HS256")
    for token in (sin_firma, hs256):
        assert client.post("/api/envios/cotizar", json=CUERPO, headers=bearer(token)).status_code == 401


@pytest.mark.parametrize("cuerpo", [
    {"codigo_postal": "123", "cantidad": 1}, {"codigo_postal": "06600", "cantidad": 0},
    {"codigo_postal": "06600", "cantidad": "2"}, {"codigo_postal": "06600"},
    {"codigo_postal": "06600", "cantidad": 1, "extra": 1},
])
def test_cotizar_validacion_422(client, cuerpo):
    r = client.post("/api/envios/cotizar", json=cuerpo, headers=SERVICIO)
    assert r.status_code == 422 and r.json()["success"] is False and r.json()["errors"]


def test_json_invalido_400(client):
    r = client.post("/api/envios/cotizar", content="{no", headers={**SERVICIO, "Content-Type": "application/json"})
    assert r.status_code == 400 and r.json() == {"success": False, "message": "JSON inválido", "errors": {}}


def test_respuestas_cumplen_el_contrato(client, make_token):
    spec = client.get("/openapi.json").json()
    ruta = spec["paths"]["/api/envios/cotizar"]["post"]["responses"]
    for status, headers, body in [
        ("200", bearer(make_token()), CUERPO),
        ("401", {}, CUERPO),
        ("422", SERVICIO, {"codigo_postal": "x", "cantidad": 1}),
    ]:
        r = client.post("/api/envios/cotizar", json=body, headers=headers)
        schema = ruta[status]["content"]["application/json"]["schema"]
        root = {"components": spec["components"], **schema}
        Draft4Validator(root).validate(r.json())


def test_jwt_con_sub_no_v4_es_401(client, make_token):
    r = client.post("/api/envios/cotizar", json=CUERPO,
                    headers=bearer(make_token(sub="c232ab00-9414-11ec-b3c8-9f6bdeced846")))
    assert r.status_code == 401
