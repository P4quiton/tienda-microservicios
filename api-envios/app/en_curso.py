"""Registro en memoria de solicitudes en curso (misma Idempotency-Key + solicitante).

Una segunda solicitud idéntica mientras la primera sigue ejecutándose (p. ej. esperando a Pedidos)
recibe 409 al instante, sin repetir efectos. Solo cubre este proceso; entre réplicas lo cubre el
try-lock de PostgreSQL en el repositorio.
"""
import threading
from contextlib import contextmanager

from app.errors import ApiError


class EnCurso:
    def __init__(self):
        self._claves: set[tuple] = set()
        self._mutex = threading.Lock()

    @contextmanager
    def reservar(self, *clave):
        with self._mutex:
            if clave in self._claves:
                raise ApiError(409, "Solicitud con la misma Idempotency-Key en curso")
            self._claves.add(clave)
        try:
            yield
        finally:
            with self._mutex:
                self._claves.discard(clave)
