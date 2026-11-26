"""Rate limiting en memoria y tope de tamaño de cuerpo, como middleware ASGI.

Orden: autentica (sin efectos) -> limita -> acota el cuerpo -> ruta. Sin credencial válida la petición
llega a la ruta, que responde 401; solo consume un cubo por IP.
- Clave: sub del JWT, o nombre del servicio (X-Service-Token válido); sin autenticar, IP del socket
  (no se confía en X-Forwarded-For). Ventana deslizante de 60 s.
- Estado por proceso: con N réplicas el límite efectivo es por instancia.
- /health y /ready quedan exentos.
"""
import math
import threading
import time
from collections import deque

from fastapi import Request

from app.auth import autenticar
from app.errors import ApiError, error_response

VENTANA = 60.0
EXENTAS = {"/health", "/ready"}
METODOS_LECTURA = {"GET", "HEAD", "OPTIONS"}


class LimitadorVentana:
    def __init__(self, reloj=time.monotonic):
        self._reloj = reloj
        self._eventos: dict[tuple, deque] = {}
        self._mutex = threading.Lock()
        self._ultima_limpieza = reloj()

    def consumir(self, clave: tuple, maximo: int) -> int:
        """0 si se permite (y se registra); si no, segundos de espera hasta el siguiente hueco."""
        with self._mutex:
            ahora = self._reloj()
            self._limpiar(ahora)
            cola = self._eventos.setdefault(clave, deque())
            while cola and ahora - cola[0] >= VENTANA:
                cola.popleft()
            if len(cola) >= maximo:
                return max(1, math.ceil(VENTANA - (ahora - cola[0])))
            cola.append(ahora)
            return 0

    def _limpiar(self, ahora: float) -> None:
        """Descarta claves inactivas para acotar la memoria (IPs que ya no llegan)."""
        if ahora - self._ultima_limpieza < VENTANA:
            return
        self._ultima_limpieza = ahora
        for clave in [k for k, c in self._eventos.items() if not c or ahora - c[-1] >= VENTANA]:
            del self._eventos[clave]


class LimitesMiddleware:
    def __init__(self, app, settings, reloj=time.monotonic):
        self.app = app
        self.settings = settings
        self.limitador = LimitadorVentana(reloj)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in EXENTAS:
            return await self.app(scope, receive, send)
        request = Request(scope)
        try:
            identidad = autenticar(request)
        except ApiError:
            identidad = None
        clave, maximo = self._cubo(request, identidad)
        espera = self.limitador.consumir(clave, maximo)
        if espera:
            respuesta = error_response(429, "Demasiadas solicitudes")
            respuesta.headers["Retry-After"] = str(espera)
            return await respuesta(scope, receive, send)

        cuerpo = await self._leer_cuerpo(request, receive)
        if cuerpo is None:  # excede MAX_JSON_BYTES; sin credencial sigue prevaleciendo el 401
            if identidad is None:
                respuesta = error_response(401, "Credencial inválida")
            else:
                respuesta = error_response(413, "Cuerpo demasiado grande")
            return await respuesta(scope, receive, send)
        return await self.app(scope, _reproducir(cuerpo, receive), send)

    def _cubo(self, request: Request, identidad) -> tuple[tuple, int]:
        s = self.settings
        if identidad is not None and identidad.tipo == "servicio":
            return ("interna", identidad.nombre), s.rate_limit_interna
        lectura = request.method in METODOS_LECTURA
        tipo = "consulta" if lectura else "mutacion"
        maximo = s.rate_limit_consulta if lectura else s.rate_limit_mutacion
        if identidad is None:
            return (tipo, "ip", request.client.host if request.client else "desconocida"), maximo
        return (tipo, identidad.nombre), maximo

    async def _leer_cuerpo(self, request: Request, receive) -> list | None:
        """Mensajes del cuerpo leídos hasta el máximo; None si lo excede (Content-Length o bytes reales)."""
        maximo = self.settings.max_json_bytes
        declarado = request.headers.get("content-length", "")
        if declarado.isdigit() and int(declarado) > maximo:
            return None
        if not declarado and "transfer-encoding" not in request.headers:
            return []  # sin cuerpo: nada que acotar
        mensajes, total = [], 0
        while True:
            mensaje = await receive()
            mensajes.append(mensaje)
            if mensaje["type"] != "http.request":
                break
            total += len(mensaje.get("body", b""))
            if total > maximo:
                return None
            if not mensaje.get("more_body", False):
                break
        return mensajes


def _reproducir(mensajes: list, receive):
    pendientes = list(mensajes)

    async def _receive():
        if pendientes:
            return pendientes.pop(0)
        return await receive()
    return _receive
