"""Decisión A: despacho periódico interno (preparando -> en_transito tras N segundos desde la guía)."""
import dataclasses
import time
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.despacho import Despachador
from app.main import create_app
from tests.conftest import SERVICIO
from tests.test_guias import contar, generar


def _crear(client, pedidos):
    pedido_id = pedidos.agregar(str(uuid4()))
    return pedido_id, generar(client, pedido_id).json()["data"]


def _envejecer(pool, segundos):
    with pool.connection() as conn:
        conn.execute("UPDATE envios SET creado_en = now() - make_interval(secs => %s)", (segundos,))


def _estado(pool, pedido_id):
    with pool.connection() as conn:
        return conn.execute("SELECT estado FROM envios WHERE pedido_id = %s", (pedido_id,)).fetchone()[0]


def test_guia_reciente_no_se_despacha(client, pedidos, pool):
    pedido_id, _ = _crear(client, pedidos)
    assert Despachador(pool, segundos=60, intervalo=3600).despachar_vencidos() == 0
    assert _estado(pool, pedido_id) == "preparando" and contar(pool, "notificaciones_pedido") == 0


def test_guia_vencida_pasa_a_en_transito_y_encola_una_vez(client, pedidos, pool):
    pedido_id, _ = _crear(client, pedidos)
    _envejecer(pool, 61)
    d = Despachador(pool, segundos=60, intervalo=3600)
    assert d.despachar_vencidos() == 1
    assert _estado(pool, pedido_id) == "en_transito" and contar(pool, "notificaciones_pedido") == 1
    assert d.despachar_vencidos() == 0  # ya en transito: no se vuelve a despachar
    assert contar(pool, "notificaciones_pedido") == 1


def test_envio_ya_en_transito_por_despachar_manual_no_duplica(client, pedidos, pool):
    pedido_id, _ = _crear(client, pedidos)
    client.app.state.repo.despachar(UUID(pedido_id))
    _envejecer(pool, 100)
    assert Despachador(pool, segundos=1, intervalo=3600).despachar_vencidos() == 0
    assert contar(pool, "notificaciones_pedido") == 1


def test_reinicio_no_pierde_despachos_pendientes(client, pedidos, pool):
    pedido_id, _ = _crear(client, pedidos)
    Despachador(pool, segundos=3600, intervalo=3600).despachar_vencidos()  # "proceso anterior": nada vencido
    _envejecer(pool, 7200)  # pasa el tiempo mientras nadie corre
    assert Despachador(pool, segundos=3600, intervalo=3600).despachar_vencidos() == 1  # proceso nuevo, solo BD
    assert _estado(pool, pedido_id) == "en_transito"


def test_dos_despachadores_concurrentes_no_duplican(client, pedidos, pool):
    from concurrent.futures import ThreadPoolExecutor
    for _ in range(6):
        _crear(client, pedidos)
    _envejecer(pool, 100)
    with ThreadPoolExecutor(4) as ex:
        totales = list(ex.map(lambda _: Despachador(pool, segundos=1, intervalo=3600).despachar_vencidos(), range(4)))
    assert sum(totales) == 6 and contar(pool, "notificaciones_pedido") == 6


def test_lifespan_despacha_y_el_outbox_se_entrega(settings, pool, pedidos):
    cfg = dataclasses.replace(settings, despacho_segundos=0.3, despacho_intervalo=0.1, notificacion_intervalo=0.1)
    with pool.connection() as conn:
        conn.execute("TRUNCATE notificaciones_pedido, idempotencia, envios")
    with TestClient(create_app(cfg, pool, pedidos)) as c:
        pedido_id, envio = _crear(c, pedidos)
        assert _estado(pool, pedido_id) in ("preparando", "en_transito")
        for _i in range(80):
            if pedidos.patches:
                break
            time.sleep(0.1)
        assert _estado(pool, pedido_id) == "en_transito"
        assert [p for p, _ in pedidos.patches] == [pedido_id]
        guia = c.get(f"/api/envios/rastreo/{envio['guia']}", headers=SERVICIO).json()["data"]
        assert guia["estado"] == "en_transito"
