"""Contrato 1.1.0: estado inicial `preparando`, despacho real -> PATCH a Pedidos con outbox durable."""
from uuid import UUID, uuid4

import httpx
import pytest

from app.notificaciones import Notificador, clave_estable
from app.pedidos_client import NotificacionFallida, PedidosClient
from tests.conftest import DIRECCION, SERVICIO, TOKEN_OUT
from tests.test_guias import contar, generar


@pytest.fixture
def notificador(pool, pedidos):
    return Notificador(pool, pedidos, intervalo=3600)


def _crear(client, pedidos):
    pedido_id = pedidos.agregar(str(uuid4()))
    return pedido_id, generar(client, pedido_id).json()["data"]


def _fila(pool, pedido_id):
    with pool.connection() as conn:
        return conn.execute(
            "SELECT estado, intentos, ultimo_error, proximo_intento > now() FROM notificaciones_pedido "
            "WHERE pedido_id = %s", (pedido_id,)).fetchone()


def _vencer(pool):
    with pool.connection() as conn:
        conn.execute("UPDATE notificaciones_pedido SET proximo_intento = now() - interval '1 second'")


# --- (a) generar: resultado original persistido, 409 por pedido aun con otra clave y sin Pedidos ---

def test_reintento_misma_clave_devuelve_resultado_original_aunque_el_envio_avance(client, pedidos, pool):
    pedido_id, clave = pedidos.agregar(str(uuid4())), str(uuid4())
    a = generar(client, pedido_id, clave)
    with pool.connection() as conn:
        conn.execute("UPDATE envios SET estado = 'en_transito'")
    b = generar(client, pedido_id, clave)
    assert b.status_code == 201 and b.json() == a.json()
    assert b.json()["data"]["estado"] == "preparando"


def test_payload_incompatible_con_otra_clave_es_409_sin_consultar_pedidos(client, pedidos, pool):
    pedido_id = pedidos.agregar(str(uuid4()))
    assert generar(client, pedido_id).status_code == 201
    pedidos.caido = True
    r = generar(client, pedido_id, direccion={**DIRECCION, "calle": "Otra 2"})
    assert r.status_code == 409
    assert contar(pool) == 1


def test_otra_clave_mismo_payload_devuelve_la_guia_sin_depender_de_pedidos(client, pedidos, pool):
    pedido_id = pedidos.agregar(str(uuid4()))
    a = generar(client, pedido_id)
    pedidos.caido = True
    b = generar(client, pedido_id)
    assert b.status_code == 201 and b.json()["data"] == a.json()["data"] and contar(pool) == 1


# --- (b) estado inicial y generar no notifica ---

def test_generar_no_despacha_ni_notifica(client, pedidos, pool):
    pedido_id, envio = _crear(client, pedidos)
    assert envio["estado"] == "preparando"
    assert contar(pool, "notificaciones_pedido") == 0 and pedidos.patches == []


def test_despachar_pasa_a_en_transito_y_encola_una_vez(client, pedidos, pool):
    pedido_id, envio = _crear(client, pedidos)
    repo = client.app.state.repo
    d1 = repo.despachar(UUID(pedido_id))
    d2 = repo.despachar(UUID(pedido_id))
    assert d1["estado"] == "en_transito" and d1["guia"] == envio["guia"]
    assert d2 is not None and d2["estado"] == "en_transito"
    assert contar(pool, "notificaciones_pedido") == 1
    rastreo = client.get(f"/api/envios/rastreo/{envio['guia']}", headers=SERVICIO).json()["data"]
    assert rastreo["estado"] == "en_transito"


def test_despachar_sin_guia_no_hace_nada(client, pool):
    assert client.app.state.repo.despachar(uuid4()) is None
    assert contar(pool, "notificaciones_pedido") == 0


def test_clave_estable_es_uuid_v4_determinista_por_pedido():
    p = uuid4()
    assert clave_estable(p) == clave_estable(str(p))
    assert clave_estable(p) != clave_estable(uuid4())
    assert clave_estable(p).version == 4


# --- outbox: envio, reintento, durabilidad ---

def test_notifica_enviado_con_clave_estable_y_no_repite(client, pedidos, pool, notificador):
    pedido_id, _ = _crear(client, pedidos)
    client.app.state.repo.despachar(UUID(pedido_id))
    assert notificador.procesar_pendientes() == 1
    assert pedidos.patches == [(pedido_id, str(clave_estable(pedido_id)))]
    assert _fila(pool, pedido_id)[0] == "enviada"
    assert notificador.procesar_pendientes() == 0 and len(pedidos.patches) == 1


def test_fallo_conserva_pendiente_con_backoff_y_reintenta_con_la_misma_clave(client, pedidos, pool, notificador):
    pedido_id, _ = _crear(client, pedidos)
    client.app.state.repo.despachar(UUID(pedido_id))
    pedidos.patch_caido = True
    assert notificador.procesar_pendientes() == 0
    estado, intentos, error, futuro = _fila(pool, pedido_id)
    assert (estado, intentos, futuro) == ("pendiente", 1, True) and "503" in error
    assert notificador.procesar_pendientes() == 0 and len(pedidos.patches) == 1  # aun no vence
    _vencer(pool)
    pedidos.patch_caido = False
    assert notificador.procesar_pendientes() == 1
    assert {c for _, c in pedidos.patches} == {str(clave_estable(pedido_id))} and len(pedidos.patches) == 2
    assert _fila(pool, pedido_id)[0] == "enviada"


def test_notificacion_pendiente_sobrevive_al_reinicio(client, pedidos, pool):
    pedido_id, _ = _crear(client, pedidos)
    client.app.state.repo.despachar(UUID(pedido_id))
    pedidos.patch_caido = True
    Notificador(pool, pedidos, intervalo=3600).procesar_pendientes()
    pedidos.patch_caido = False
    _vencer(pool)
    # Proceso nuevo: no comparte memoria con el anterior, solo la BD.
    assert Notificador(pool, pedidos, intervalo=3600).procesar_pendientes() == 1


def test_lease_evita_que_dos_trabajadores_tomen_la_misma_notificacion(client, pedidos, pool):
    pedido_id, _ = _crear(client, pedidos)
    client.app.state.repo.despachar(UUID(pedido_id))
    a = Notificador(pool, pedidos, intervalo=3600)
    tomadas = a._reclamar()
    assert len(tomadas) == 1 and Notificador(pool, pedidos, intervalo=3600)._reclamar() == []


def test_hilo_de_fondo_procesa_al_arrancar(client, pedidos, pool):
    import time
    pedido_id, _ = _crear(client, pedidos)
    client.app.state.repo.despachar(UUID(pedido_id))
    n = Notificador(pool, pedidos, intervalo=0.2)
    n.iniciar()
    try:
        for _ in range(50):
            if pedidos.patches:
                break
            time.sleep(0.1)
    finally:
        n.detener()
    assert len(pedidos.patches) == 1


# --- cliente HTTP ---

def _resp(status):
    return httpx.Response(status, json={}, request=httpx.Request("PATCH", "http://x"))


def test_cliente_envia_patch_con_token_especifico_y_clave(settings, monkeypatch):
    visto = {}

    def falso(url, headers, json, timeout):
        visto.update(url=url, headers=headers, json=json)
        return _resp(200)

    monkeypatch.setattr(httpx, "patch", falso)
    pid, clave = uuid4(), uuid4()
    PedidosClient(settings).marcar_enviado(pid, clave)
    assert visto["url"].endswith(f"/api/pedidos/{pid}/estado") and visto["json"] == {"estado": "enviado"}
    assert visto["headers"] == {"X-Service-Token": TOKEN_OUT, "Idempotency-Key": str(clave)}


@pytest.mark.parametrize("status", [401, 404, 409, 500, 503])
def test_cliente_status_no_200_es_fallo_reintentable(settings, monkeypatch, status):
    monkeypatch.setattr(httpx, "patch", lambda *a, **k: _resp(status))
    with pytest.raises(NotificacionFallida):
        PedidosClient(settings).marcar_enviado(uuid4(), uuid4())


def test_cliente_error_de_red_es_fallo_reintentable(settings, monkeypatch):
    def falla(*a, **k):
        raise httpx.ReadTimeout("timeout")
    monkeypatch.setattr(httpx, "patch", falla)
    with pytest.raises(NotificacionFallida):
        PedidosClient(settings).marcar_enviado(uuid4(), uuid4())
