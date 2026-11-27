from uuid import uuid4

import httpx
import pytest

from app.errors import ApiError
from app.pedidos_client import PedidosClient
from tests.conftest import TOKEN_OUT


def _respuesta(status, body):
    return httpx.Response(status, json=body, request=httpx.Request("GET", "http://x"))


def test_consulta_con_identidad_propia_y_parsea(settings, monkeypatch):
    visto = {}
    usuario = str(uuid4())

    def falso(url, headers, timeout):
        visto.update(url=url, headers=headers)
        return _respuesta(200, {"success": True, "data": {"usuario_id": usuario, "estado": "pagado"}})

    monkeypatch.setattr(httpx, "get", falso)
    pedido_id = uuid4()
    info = PedidosClient(settings).obtener(pedido_id)
    assert (info.usuario_id, info.estado) == (usuario, "pagado")
    assert visto["url"].endswith(f"/api/pedidos/{pedido_id}")
    assert visto["headers"] == {"X-Service-Token": TOKEN_OUT}


@pytest.mark.parametrize("status,body,esperado", [
    (404, {"success": False}, 404), (500, {}, 503), (200, {"data": {}}, 503), (200, {"data": {"usuario_id": "x", "estado": "p"}}, 503),
])
def test_respuestas_inesperadas(settings, monkeypatch, status, body, esperado):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _respuesta(status, body))
    with pytest.raises(ApiError) as e:
        PedidosClient(settings).obtener(uuid4())
    assert e.value.status == esperado


def test_error_de_red_es_503(settings, monkeypatch):
    def falla(*a, **k):
        raise httpx.ConnectError("sin red")
    monkeypatch.setattr(httpx, "get", falla)
    with pytest.raises(ApiError) as e:
        PedidosClient(settings).obtener(uuid4())
    assert e.value.status == 503
