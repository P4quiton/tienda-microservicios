"""Cliente mínimo de Pedidos (GET /api/pedidos/{id}) con la identidad propia de Envíos."""
from dataclasses import dataclass
from uuid import UUID

import httpx

from app.config import Settings
from app.errors import ApiError
from app.ids import uuid_v4


class NotificacionFallida(Exception):
    """El PATCH a Pedidos no se confirmó (red, timeout o status distinto de 200): se reintenta."""


@dataclass(frozen=True)
class PedidoInfo:
    usuario_id: str
    estado: str


class PedidosClient:
    def __init__(self, settings: Settings):
        self._url = settings.pedidos_url
        self._token = settings.token_envios_pedidos
        self._timeout = settings.pedidos_timeout

    def obtener(self, pedido_id: UUID) -> PedidoInfo:
        """Devuelve titular y estado. 404 se propaga; cualquier otro fallo es 503:
        sin certeza sobre el titular no se autoriza ni se genera nada."""
        try:
            r = httpx.get(
                f"{self._url}/api/pedidos/{pedido_id}",
                headers={"X-Service-Token": self._token},
                timeout=self._timeout,
            )
            if r.status_code == 404:
                raise ApiError(404, "Pedido no encontrado")
            if r.status_code != 200:
                raise ValueError
            data = r.json()["data"]
            return PedidoInfo(usuario_id=uuid_v4(data["usuario_id"]), estado=str(data["estado"]))
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise ApiError(503, "Pedidos no disponible o respuesta inválida") from None

    def marcar_enviado(self, pedido_id: UUID, clave: UUID) -> None:
        """PATCH /api/pedidos/{id}/estado {estado: enviado}. Solo 200 confirma; todo lo demás se reintenta."""
        try:
            r = httpx.patch(
                f"{self._url}/api/pedidos/{pedido_id}/estado",
                headers={"X-Service-Token": self._token, "Idempotency-Key": str(clave)},
                json={"estado": "enviado"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise NotificacionFallida(type(exc).__name__) from None
        if r.status_code != 200:
            raise NotificacionFallida(f"HTTP {r.status_code}")
