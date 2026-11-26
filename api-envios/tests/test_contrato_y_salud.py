from pathlib import Path

import yaml
from openapi_spec_validator import validate

from app.main import create_app

RAIZ = Path(__file__).resolve().parents[1]


def test_openapi_json_es_el_contrato_valido(client):
    servido = client.get("/openapi.json").json()
    validate(servido)
    assert servido["openapi"] == "3.0.3"
    contrato = RAIZ.parent / "docs" / "api" / "envios.yaml"
    if contrato.exists():  # en la imagen/CI aislada solo existe api-envios
        assert servido == yaml.safe_load(contrato.read_text())


def test_todas_las_operaciones_del_contrato_estan_implementadas(client):
    """Sin credenciales, una ruta implementada responde algo distinto de 404/405 por ruta faltante."""
    spec = client.get("/openapi.json").json()
    for ruta, ops in spec["paths"].items():
        for metodo in ops:
            r = client.request(metodo.upper(), ruta.replace("{guia}", "ENV000000000000"))
            assert r.status_code not in (404, 405), (metodo, ruta, r.status_code)


def test_health_no_depende_de_bd(settings):
    from psycopg_pool import ConnectionPool
    mala = ConnectionPool("host=127.0.0.1 port=1 dbname=x user=x password=x connect_timeout=1",
                          open=False, timeout=1)
    from fastapi.testclient import TestClient
    c = TestClient(create_app(settings, mala))
    assert c.get("/health").json() == {"status": "ok", "service": "api-envios"}
    r = c.get("/ready")
    assert r.status_code == 503 and r.json() == {"status": "unavailable", "service": "api-envios"}


def test_ready_ok(client):
    r = client.get("/ready")
    assert r.status_code == 200 and r.json() == {"status": "ok", "service": "api-envios"}


def test_arranque_sin_bd_health_ok_ready_503_y_se_recupera(settings, conninfo):
    """BD inaccesible al arrancar: /health 200, /ready 503 y sin 500; al volver migra y /ready 200."""
    import time
    from fastapi.testclient import TestClient
    from app.db import MigradorEnSegundoPlano, create_pool

    # Pool apuntando a un puerto cerrado; se "recupera" cambiando su conninfo no es posible,
    # así que el migrador arranca con un pool malo y luego se le entrega el pool real.
    mala = create_pool("host=127.0.0.1 port=1 dbname=x user=x password=x connect_timeout=1")
    real = create_pool(conninfo)
    migrador = MigradorEnSegundoPlano(mala, espera_max=0.2)
    try:
        with TestClient(create_app(settings, real, migrador=migrador), raise_server_exceptions=False) as c:
            time.sleep(0.5)
            assert c.get("/health").json() == {"status": "ok", "service": "api-envios"}
            assert not migrador.listo.is_set()
            assert c.get("/ready").status_code == 503  # BD real accesible, pero esquema no confirmado
            migrador._pool = real  # la BD "vuelve": el siguiente reintento migra
            for _ in range(50):
                if c.get("/ready").status_code == 200:
                    break
                time.sleep(0.2)
            assert c.get("/ready").status_code == 200
    finally:
        mala.close()
        real.close()


def test_endpoint_con_bd_caida_responde_503_no_500(settings):
    from fastapi.testclient import TestClient
    from psycopg_pool import ConnectionPool
    from tests.conftest import SERVICIO
    mala = ConnectionPool("host=127.0.0.1 port=1 dbname=x user=x password=x connect_timeout=1",
                          open=False, timeout=1)
    c = TestClient(create_app(settings, mala), raise_server_exceptions=False)
    r = c.get("/api/envios/rastreo/ENV1", headers=SERVICIO)
    assert r.status_code == 503 and r.json()["success"] is False
