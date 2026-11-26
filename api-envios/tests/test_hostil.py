"""Regresiones del barrido QA hostil (ver QA-INFORME.md)."""
import json
import re
from uuid import uuid4

import pytest

from tests.conftest import DIRECCION, SERVICIO, bearer

IMPORTE = re.compile(r"^\d{1,10}\.\d{2}$")  # patrón de costo_envio en docs/api/envios.yaml


@pytest.mark.parametrize("texto", ["a\x00b", "\ud800", "x\udfffy"])
def test_texto_no_representable_en_bd_es_422_no_500(client, pedidos, pool, texto):
    pedido = pedidos.agregar(str(uuid4()))
    for campo in ("calle", "ciudad", "estado"):
        r = client.post(
            "/api/envios/generar",
            content=json.dumps({"pedido_id": pedido, "direccion": {**DIRECCION, campo: texto}}),
            headers={**SERVICIO, "Idempotency-Key": str(uuid4()), "Content-Type": "application/json"},
        )
        assert r.status_code == 422 and r.json()["success"] is False
    with pool.connection() as conn:
        assert conn.execute("SELECT count(*) FROM envios").fetchone()[0] == 0


def test_rastreo_con_nul_en_la_guia_es_404_no_500(client):
    r = client.get("/api/envios/rastreo/a%00b", headers=SERVICIO)
    assert r.status_code == 404


@pytest.mark.parametrize("cantidad", [10**9, 10**12, 10**30])
def test_cantidad_que_rompe_el_formato_del_importe_es_422(client, make_token, cantidad):
    r = client.post("/api/envios/cotizar", json={"codigo_postal": "99999", "cantidad": cantidad},
                    headers=bearer(make_token()))
    assert r.status_code == 422
    assert "cantidad" in r.json()["errors"]


def test_todo_importe_devuelto_cumple_el_patron_del_contrato(client, make_token):
    # Mayor cantidad aceptada en la zona más cara: el importe debe seguir cumpliendo el contrato.
    lo, hi = 1, 10**12
    while lo < hi:  # busca la frontera con la propia API
        mid = (lo + hi + 1) // 2
        r = client.post("/api/envios/cotizar", json={"codigo_postal": "99999", "cantidad": mid},
                        headers=bearer(make_token()))
        lo, hi = (mid, hi) if r.status_code == 200 else (lo, mid - 1)
    r = client.post("/api/envios/cotizar", json={"codigo_postal": "99999", "cantidad": lo},
                    headers=bearer(make_token()))
    assert IMPORTE.match(r.json()["data"]["costo_envio"])


def test_entero_gigante_es_400_con_mensaje_json_invalido(client, make_token):
    cuerpo = b'{"codigo_postal":"06600","cantidad":1' + b"0" * 5000 + b"}"
    r = client.post("/api/envios/cotizar", content=cuerpo,
                    headers={**bearer(make_token()), "Content-Type": "application/json"})
    assert r.status_code == 400 and r.json()["message"] == "JSON inválido"


# --- BD colgada (no caída): las conexiones abiertas no responden ni fallan ---------------------

class PoolColgado:
    """Simula PostgreSQL congelado: toda operación se queda esperando hasta liberar()."""

    def __init__(self):
        import threading
        self._liberar = threading.Event()

    def connection(self, *args, **kwargs):
        self._liberar.wait(timeout=30)
        raise RuntimeError("liberado")

    def liberar(self):
        self._liberar.set()


def test_health_vive_y_ready_falla_rapido_con_bd_colgada(settings):
    import asyncio
    import time

    import httpx

    from app.main import create_app

    pool = PoolColgado()
    app = create_app(settings, pool)

    async def escenario():
        transporte = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transporte, base_url="http://t") as http:
            # Más peticiones bloqueadas que hilos del threadpool de la app (40).
            bloqueadas = [asyncio.create_task(http.get("/api/envios/rastreo/x", headers=SERVICIO))
                          for _ in range(60)]
            await asyncio.sleep(0.5)
            t0 = time.monotonic()
            health = await asyncio.wait_for(http.get("/health"), timeout=3)
            ready = await asyncio.wait_for(http.get("/ready"), timeout=6)
            demora = time.monotonic() - t0
            pool.liberar()
            await asyncio.gather(*bloqueadas, return_exceptions=True)
            return health.status_code, ready.status_code, demora

    try:
        health, ready, demora = asyncio.run(escenario())
    finally:
        pool.liberar()
    assert health == 200
    assert ready == 503
    assert demora < 5
