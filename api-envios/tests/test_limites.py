"""Decisión B: rate limiting en memoria por proceso y tamaño máximo de cuerpo."""
import dataclasses
import json
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import DIRECCION, SERVICIO, bearer

COTIZAR = {"codigo_postal": "06600", "cantidad": 1}


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _app(settings, pool, pedidos, reloj=None, **limites):
    cfg = dataclasses.replace(settings, **limites)
    return TestClient(create_app(cfg, pool, pedidos, reloj=reloj), raise_server_exceptions=False)


def _formato_error(r):
    j = r.json()
    assert j["success"] is False and isinstance(j["message"], str) and isinstance(j["errors"], dict)


def test_consulta_excede_y_devuelve_429_con_retry_after_y_formato(settings, pool, pedidos, make_token):
    reloj = Reloj()
    c = _app(settings, pool, pedidos, reloj, rate_limit_consulta=3)
    h = bearer(make_token(role="admin"))
    assert [c.get("/api/envios/rastreo/X", headers=h).status_code for _ in range(3)] == [404] * 3
    r = c.get("/api/envios/rastreo/X", headers=h)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    _formato_error(r)
    reloj.t += 61  # la ventana pasa
    assert c.get("/api/envios/rastreo/X", headers=h).status_code == 404


def test_mutacion_y_consulta_tienen_cubos_separados(settings, pool, pedidos, make_token):
    c = _app(settings, pool, pedidos, rate_limit_consulta=100, rate_limit_mutacion=2)
    h = bearer(make_token())
    assert [c.post("/api/envios/cotizar", json=COTIZAR, headers=h).status_code for _ in range(2)] == [200, 200]
    assert c.post("/api/envios/cotizar", json=COTIZAR, headers=h).status_code == 429
    assert c.get("/api/envios/rastreo/X", headers=h).status_code == 404


def test_clave_es_el_sub_cada_usuario_su_cubo(settings, pool, pedidos, make_token):
    c = _app(settings, pool, pedidos, rate_limit_mutacion=1)
    a, b = bearer(make_token()), bearer(make_token())
    assert c.post("/api/envios/cotizar", json=COTIZAR, headers=a).status_code == 200
    assert c.post("/api/envios/cotizar", json=COTIZAR, headers=a).status_code == 429
    assert c.post("/api/envios/cotizar", json=COTIZAR, headers=b).status_code == 200


def test_servicio_usa_limite_interno_independiente(settings, pool, pedidos):
    c = _app(settings, pool, pedidos, rate_limit_interna=2, rate_limit_mutacion=1, rate_limit_consulta=1)
    codigos = [c.post("/api/envios/cotizar", json=COTIZAR, headers=SERVICIO).status_code for _ in range(3)]
    assert codigos == [200, 200, 429]


def test_sin_credencial_sigue_siendo_401_y_no_consume_el_cubo_de_nadie(settings, pool, pedidos, make_token):
    # El cubo por IP (3) absorbe los intentos sin credencial; el del usuario autenticado es aparte.
    c = _app(settings, pool, pedidos, rate_limit_mutacion=3)
    assert c.post("/api/envios/cotizar", json=COTIZAR).status_code == 401
    assert c.post("/api/envios/cotizar", json=COTIZAR, headers={"X-Service-Token": "mal"}).status_code == 401
    assert c.post("/api/envios/cotizar", json=COTIZAR, headers=bearer("basura")).status_code == 401
    h = bearer(make_token())
    assert [c.post("/api/envios/cotizar", json=COTIZAR, headers=h).status_code for _ in range(3)] == [200] * 3


def test_sin_autenticar_se_limita_por_ip(settings, pool, pedidos):
    c = _app(settings, pool, pedidos, rate_limit_consulta=2)
    codigos = [c.get("/api/envios/rastreo/X").status_code for _ in range(3)]
    assert codigos == [401, 401, 429]


def test_health_y_ready_exentos(settings, pool, pedidos):
    c = _app(settings, pool, pedidos, rate_limit_consulta=1, rate_limit_mutacion=1, rate_limit_interna=1)
    assert all(c.get(p).status_code == 200 for p in ["/health"] * 5 + ["/ready"] * 5)


def test_cuerpo_mayor_al_maximo_es_413_por_content_length(settings, pool, pedidos):
    c = _app(settings, pool, pedidos, max_json_bytes=200)
    cuerpo = json.dumps({"codigo_postal": "06600", "cantidad": 1, "x": "a" * 300})
    r = c.post("/api/envios/cotizar", content=cuerpo, headers={**SERVICIO, "Content-Type": "application/json"})
    assert r.status_code == 413
    _formato_error(r)


def test_cuerpo_real_mayor_al_maximo_sin_content_length_es_413(settings, pool, pedidos):
    c = _app(settings, pool, pedidos, max_json_bytes=200)

    def trozos():
        yield b'{"codigo_postal":"06600","cantidad":1,"x":"'
        yield b"a" * 150
        yield b"a" * 150
        yield b'"}'

    r = c.post("/api/envios/cotizar", content=trozos(), headers={**SERVICIO, "Content-Type": "application/json"})
    assert r.status_code == 413  # Transfer-Encoding: chunked, sin Content-Length


def test_cuerpo_dentro_del_maximo_pasa(settings, pool, pedidos):
    c = _app(settings, pool, pedidos, max_json_bytes=200)
    assert c.post("/api/envios/cotizar", json=COTIZAR, headers=SERVICIO).status_code == 200


def test_cuerpo_grande_sin_credencial_sigue_siendo_401(settings, pool, pedidos):
    c = _app(settings, pool, pedidos, max_json_bytes=50)
    r = c.post("/api/envios/cotizar", content=b"{" + b" " * 500 + b"}", headers={"Content-Type": "application/json"})
    assert r.status_code == 401


def test_413_aplica_tambien_a_generar(settings, pool, pedidos):
    c = _app(settings, pool, pedidos, max_json_bytes=300)
    cuerpo = {"pedido_id": str(uuid4()), "direccion": {**DIRECCION, "calle": "x" * 500}}
    r = c.post("/api/envios/generar", json=cuerpo, headers={**SERVICIO, "Idempotency-Key": str(uuid4())})
    assert r.status_code == 413
