import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app import repositorio
from app.db import create_pool
from app.main import create_app
from app.repositorio import EnviosRepo
from tests.conftest import SERVICIO
from tests.test_guias import generar


def _crear(client, pedidos):
    pedido_id = pedidos.agregar(str(uuid4()))
    respuesta = generar(client, pedido_id)
    assert respuesta.status_code == 201
    return UUID(pedido_id), respuesta.json()["data"]["guia"]


def _leer_envio(pool, pedido_id):
    with pool.connection() as conn:
        return conn.execute(
            "SELECT estado, despachado_en FROM envios WHERE pedido_id = %s", (pedido_id,)
        ).fetchone()


def _envejecer_despacho(pool, pedido_id, segundos):
    with pool.connection() as conn:
        return conn.execute(
            "UPDATE envios SET despachado_en = now() - make_interval(secs => %s) "
            "WHERE pedido_id = %s RETURNING despachado_en",
            (segundos, pedido_id),
        ).fetchone()[0]


def _outbox(pool):
    with pool.connection() as conn:
        return conn.execute("SELECT * FROM notificaciones_pedido ORDER BY id").fetchall()


def test_entrega_usa_el_plazo_desde_despacho_y_conserva_el_outbox(client, pedidos, pool):
    pedido_id, _ = _crear(client, pedidos)
    with pool.connection() as conn:
        conn.execute("UPDATE envios SET creado_en = now() - interval '1 hour' WHERE pedido_id = %s", (pedido_id,))
    repo = client.app.state.repo
    repo.despachar(pedido_id)
    outbox = _outbox(pool)
    assert len(outbox) == 1

    reciente = _envejecer_despacho(pool, pedido_id, 10)
    assert repo.entregar_vencidos(60) == 0
    assert _leer_envio(pool, pedido_id) == ("en_transito", reciente)

    vencido = _envejecer_despacho(pool, pedido_id, 61)
    assert repo.entregar_vencidos(60) == 1
    assert _leer_envio(pool, pedido_id) == ("entregado", vencido)
    assert repo.entregar_vencidos(60) == 0
    assert _outbox(pool) == outbox
    assert pedidos.patches == []


def test_envio_en_preparando_no_se_entrega_aunque_tenga_fecha_vencida(client, pedidos, pool):
    pedido_id, _ = _crear(client, pedidos)
    fecha = _envejecer_despacho(pool, pedido_id, 120)
    assert client.app.state.repo.entregar_vencidos(60) == 0
    assert _leer_envio(pool, pedido_id) == ("preparando", fecha)


@pytest.mark.parametrize("automatico", [False, True], ids=["manual", "periodico"])
@pytest.mark.parametrize("con_fecha_previa", [False, True])
def test_despacho_fija_fecha_en_la_bd_y_la_conserva(client, pedidos, pool, automatico, con_fecha_previa):
    pedido_id, _ = _crear(client, pedidos)
    repo = client.app.state.repo
    with pool.connection() as conn:
        antes = conn.execute("SELECT now()").fetchone()[0]
    previa = _envejecer_despacho(pool, pedido_id, 120) if con_fecha_previa else None

    if automatico:
        assert repo.despachar_vencidos(0) == 1
    else:
        assert repo.despachar(pedido_id)["estado"] == "en_transito"
    estado, fecha = _leer_envio(pool, pedido_id)
    assert estado == "en_transito"
    if previa is not None:
        assert fecha == previa
    else:
        with pool.connection() as conn:
            despues = conn.execute("SELECT now()").fetchone()[0]
        assert antes <= fecha <= despues

    assert repo.despachar_vencidos(0) == 0
    assert repo.despachar(pedido_id)["estado"] == "en_transito"
    assert _leer_envio(pool, pedido_id) == ("en_transito", fecha)
    assert len(_outbox(pool)) == 1


@pytest.mark.parametrize("automatico", [False, True], ids=["manual", "periodico"])
def test_fallo_al_encolar_revierte_estado_y_fecha_de_despacho(client, pedidos, pool, automatico, monkeypatch):
    pedido_id, _ = _crear(client, pedidos)
    repo = client.app.state.repo
    encolar = repositorio._encolar_notificacion

    def fallar(conn, envio):
        encolar(conn, envio)
        raise RuntimeError("fallo de outbox")

    monkeypatch.setattr("app.repositorio._encolar_notificacion", fallar)
    with pytest.raises(RuntimeError, match="fallo de outbox"):
        if automatico:
            repo.despachar_vencidos(0)
        else:
            repo.despachar(pedido_id)
    assert _leer_envio(pool, pedido_id) == ("preparando", None)
    assert _outbox(pool) == []


def test_varias_replicas_entregan_una_vez_y_saltan_filas_bloqueadas(client, pedidos, pool):
    pedido_id, _ = _crear(client, pedidos)
    client.app.state.repo.despachar(pedido_id)
    _envejecer_despacho(pool, pedido_id, 120)
    barrera = Barrier(3, timeout=5)

    def barrer():
        barrera.wait()
        return EnviosRepo(pool).entregar_vencidos(60)

    with ThreadPoolExecutor(3) as ejecutor:
        with pool.connection() as conn:
            conn.execute("SELECT id FROM envios WHERE pedido_id = %s FOR UPDATE", (pedido_id,))
            assert ejecutor.submit(EnviosRepo(pool).entregar_vencidos, 60).result(timeout=5) == 0
        resultados = list(ejecutor.map(lambda _: barrer(), range(3)))
    assert sorted(resultados) == [0, 0, 1]
    assert _leer_envio(pool, pedido_id)[0] == "entregado"
    assert len(_outbox(pool)) == 1


def test_reinicio_conserva_el_despacho_y_el_hilo_entrega_para_rastreo(client, pedidos, pool, settings):
    pedido_id, guia = _crear(client, pedidos)
    client.app.state.repo.despachar(pedido_id)
    fecha = _envejecer_despacho(pool, pedido_id, 10)
    cfg = replace(settings, entrega_segundos=2, despacho_intervalo=0.05)

    with create_pool(cfg.database_url) as pool_nuevo:
        app_nueva = create_app(cfg, pool_nuevo, pedidos)
        assert _leer_envio(pool_nuevo, pedido_id) == ("en_transito", fecha)
        with TestClient(app_nueva) as nuevo_cliente:
            limite = time.monotonic() + 5
            while True:
                respuesta = nuevo_cliente.get(f"/api/envios/rastreo/{guia}", headers=SERVICIO)
                assert respuesta.status_code == 200
                if respuesta.json()["data"]["estado"] == "entregado" or time.monotonic() >= limite:
                    break
                time.sleep(0.02)
        assert respuesta.json()["data"]["estado"] == "entregado"
        assert _leer_envio(pool_nuevo, pedido_id) == ("entregado", fecha)


def test_fallo_de_entrega_permite_despachar_en_el_siguiente_barrido(client, pedidos, pool, settings, monkeypatch, caplog):
    entregado = Event()
    fallo_entrega = Event()
    entregar = EnviosRepo.entregar_vencidos

    def fallar_una_vez(repo, segundos):
        if not fallo_entrega.is_set():
            fallo_entrega.set()
            raise RuntimeError("fallo de prueba")
        resultado = entregar(repo, segundos)
        if resultado:
            entregado.set()
        return resultado

    monkeypatch.setattr(EnviosRepo, "entregar_vencidos", fallar_una_vez)
    cfg = replace(settings, despacho_segundos=0, despacho_intervalo=0.05)
    with TestClient(create_app(cfg, pool, pedidos)):
        assert fallo_entrega.wait(5)
        pedido_id, _ = _crear(client, pedidos)
        # El reloj de la BD permite vencer la entrega sin esperar el plazo real.
        limite = time.monotonic() + 5
        while _leer_envio(pool, pedido_id)[0] == "preparando" and time.monotonic() < limite:
            time.sleep(0.02)
        assert _leer_envio(pool, pedido_id)[0] == "en_transito"
        _envejecer_despacho(pool, pedido_id, 120)
        assert entregado.wait(5)
    assert _leer_envio(pool, pedido_id)[0] == "entregado"
    assert "barrido de entrega fallido (RuntimeError)" in caplog.text
