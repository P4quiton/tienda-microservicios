"""Outbox durable: notifica a Pedidos (PATCH estado=enviado) los envíos despachados realmente.

La fila nace en la misma transacción que el paso a en_transito (EnviosRepo.despachar). Un trabajador
(al arrancar y cada `intervalo`) reclama filas vencidas con FOR UPDATE SKIP LOCKED y adelanta
`proximo_intento` (lease) antes de llamar a Pedidos, sin transacción abierta durante el HTTP.
Si el proceso cae a mitad, el lease vence y otro intento repite el PATCH con la misma clave (idempotente).
"""
import hashlib
import logging
import threading
from uuid import UUID

from psycopg_pool import ConnectionPool

from app.pedidos_client import NotificacionFallida

log = logging.getLogger("api-envios")
LEASE_SEGUNDOS = 60
BACKOFF_BASE, BACKOFF_MAX = 5, 900
LOTE = 20


def clave_estable(pedido_id) -> UUID:
    """Idempotency-Key del PATCH: determinista por pedido, con formato UUID v4 (el contrato exige v4)."""
    digest = hashlib.sha256(f"api-envios:pedido-enviado:{UUID(str(pedido_id))}".encode()).digest()
    return UUID(bytes=digest[:16], version=4)


class Notificador:
    def __init__(self, pool: ConnectionPool, pedidos, intervalo: float = 30.0, listo: threading.Event | None = None):
        self._pool = pool
        self._pedidos = pedidos
        self._intervalo = intervalo
        self._listo = listo  # esquema migrado
        self._parar = threading.Event()
        self._hilo = threading.Thread(target=self._correr, name="notificador-pedidos", daemon=True)

    def iniciar(self) -> None:
        self._hilo.start()

    def detener(self) -> None:
        self._parar.set()
        self._hilo.join(timeout=5)

    def _correr(self) -> None:
        while not self._parar.is_set():
            if self._listo is None or self._listo.is_set():
                try:
                    self.procesar_pendientes()
                except Exception as exc:  # BD caída: se reintenta en el siguiente ciclo
                    log.warning("Notificador: ciclo fallido (%s)", type(exc).__name__)
            self._parar.wait(self._intervalo)

    def _reclamar(self) -> list[tuple]:
        with self._pool.connection() as conn:
            filas = conn.execute(
                "SELECT id, pedido_id, idempotency_key FROM notificaciones_pedido "
                "WHERE estado = 'pendiente' AND proximo_intento <= now() "
                "ORDER BY proximo_intento LIMIT %s FOR UPDATE SKIP LOCKED", (LOTE,)
            ).fetchall()
            if filas:
                conn.execute(
                    "UPDATE notificaciones_pedido SET proximo_intento = now() + make_interval(secs => %s), "
                    "intentos = intentos + 1 WHERE id = ANY(%s)", (LEASE_SEGUNDOS, [f[0] for f in filas]))
        return filas

    def procesar_pendientes(self) -> int:
        """Intenta las notificaciones vencidas; devuelve cuántas se confirmaron."""
        confirmadas = 0
        for notif_id, pedido_id, clave in self._reclamar():
            try:
                self._pedidos.marcar_enviado(pedido_id, clave)
            except NotificacionFallida as exc:
                with self._pool.connection() as conn:
                    conn.execute(
                        "UPDATE notificaciones_pedido SET ultimo_error = %s, proximo_intento = now() + "
                        "make_interval(secs => LEAST(%s * power(2, intentos - 1), %s)) WHERE id = %s",
                        (str(exc)[:200], BACKOFF_BASE, BACKOFF_MAX, notif_id))
                continue
            with self._pool.connection() as conn:
                conn.execute(
                    "UPDATE notificaciones_pedido SET estado = 'enviada', enviada_en = now(), ultimo_error = NULL "
                    "WHERE id = %s", (notif_id,))
            confirmadas += 1
        return confirmadas
