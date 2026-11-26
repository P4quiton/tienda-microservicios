"""Sobres de respuesta del contrato y manejo de errores sin stack traces."""
import logging

import psycopg
import psycopg_pool

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("api-envios")


class ApiError(Exception):
    def __init__(self, status: int, message: str, errors: dict | None = None):
        self.status = status
        self.message = message
        self.errors = errors or {}


def ok(data: dict, status: int = 200, message: str = "OK") -> JSONResponse:
    return JSONResponse({"success": True, "message": message, "data": data}, status_code=status)


def error_response(status: int, message: str, errors: dict | None = None) -> JSONResponse:
    body = {"success": False, "message": message, "errors": errors or {}}
    return JSONResponse(body, status_code=status)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return error_response(exc.status, exc.message, exc.errors)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        details = exc.errors()
        if any(d["type"] == "json_invalid" for d in details):
            return error_response(400, "JSON inválido")
        errors: dict[str, list[str]] = {}
        for d in details:
            campo = ".".join(str(p) for p in d["loc"] if p != "body") or "solicitud"
            errors.setdefault(campo, []).append(d["msg"])
        return error_response(422, "Error de validación", errors)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        mensajes = {400: "JSON inválido", 404: "No encontrado", 405: "Método no permitido"}
        return error_response(exc.status_code, mensajes.get(exc.status_code, "Error"))

    @app.exception_handler(psycopg.OperationalError)
    @app.exception_handler(psycopg_pool.PoolTimeout)
    @app.exception_handler(psycopg.errors.UndefinedTable)  # esquema aún sin migrar
    async def _bd_no_disponible(_: Request, exc: Exception):
        log.warning("BD no disponible: %s", type(exc).__name__)
        return error_response(503, "Base de datos no disponible")

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception):
        log.error("Error no controlado: %s", type(exc).__name__)
        return error_response(500, "Error interno")
