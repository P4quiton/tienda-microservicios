"""Despacho simulado: pasa preparando -> en_transito cuando pasan N segundos desde la guía.

El tiempo se calcula en la BD desde `envios.creado_en`, así que sobrevive a reinicios y es el mismo para
todas las réplicas (SKIP LOCKED en EnviosRepo.despachar_vencidos evita despachar dos veces). El aviso a
Pedidos lo entrega el outbox (Notificador), que ya existe. No expone endpoints.
"""
import logging
import threading

from psycopg_pool import ConnectionPool

from app.repositorio import EnviosRepo

log = logging.getLogger("api-envios")


class Despachador:
    def __init__(self, pool: ConnectionPool, segundos: float, intervalo: float, listo: threading.Event | None = None):
        self._repo = EnviosRepo(pool)
        self._segundos = segundos
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
            self._parar.wait(self._intervalo)
