"""Despacho y entrega simulados en el mismo barrido periódico.

La BD calcula los plazos desde la creación de la guía y desde el despacho, respectivamente.
El outbox (Notificador) avisa a Pedidos solo del despacho.
"""
import logging
import threading

from psycopg_pool import ConnectionPool

from app.repositorio import EnviosRepo

log = logging.getLogger("api-envios")


class Despachador:
    def __init__(
        self, pool: ConnectionPool, segundos: float, intervalo: float, listo: threading.Event | None = None,
        *, entrega_segundos: int = 60,
    ):
        self._repo = EnviosRepo(pool)
        self._segundos = segundos
        self._entrega_segundos = entrega_segundos
        self._intervalo = intervalo
        self._listo = listo  # esquema migrado
        self._parar = threading.Event()
        self._hilo = threading.Thread(target=self._correr, name="despachador-envios", daemon=True)

    def iniciar(self) -> None:
        self._hilo.start()

    def detener(self) -> None:
        self._parar.set()
        self._hilo.join(timeout=5)

    def despachar_vencidos(self) -> int:
        return self._repo.despachar_vencidos(self._segundos)

    def _correr(self) -> None:
        while not self._parar.is_set():
            if self._listo is None or self._listo.is_set():
                try:
                    n = self.despachar_vencidos()
                    if n:
                        log.info("Despachador: %d envío(s) pasaron a en_transito", n)
                except Exception as exc:  # BD caída: se reintenta en el siguiente barrido
                    log.warning("Despachador: barrido fallido (%s)", type(exc).__name__)
                try:
                    n = self._repo.entregar_vencidos(self._entrega_segundos)
                    if n:
                        log.info("Despachador: %d envío(s) pasaron a entregado", n)
                except Exception as exc:
                    log.warning("Despachador: barrido de entrega fallido (%s)", type(exc).__name__)
            self._parar.wait(self._intervalo)
