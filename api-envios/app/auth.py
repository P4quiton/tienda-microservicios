"""Identidad del llamador: JWT RS256 de usuario o X-Service-Token interno por pares.

Origen: encabezados Authorization / X-Service-Token -> Identidad -> reglas de cada ruta.
"""
import hmac
from dataclasses import dataclass

import jwt
from fastapi import Request

from app.config import Settings
from app.errors import ApiError
from app.ids import uuid_v4

ROLES = {"cliente", "admin"}


@dataclass(frozen=True)
class Identidad:
    tipo: str            # "usuario" | "servicio"
    nombre: str          # sub del usuario o nombre del servicio llamador
    rol: str | None = None

    @property
    def es_admin(self) -> bool:
        return self.tipo == "usuario" and self.rol == "admin"


def _no_autenticado() -> ApiError:
    return ApiError(401, "Credencial inválida")


def _servicio_desde_token(token: str, settings: Settings) -> Identidad:
    # Un secreto por par llamador/destino: cada token identifica a un único llamador.
    permitidos = {"pedidos": settings.token_pedidos_envios}
    for nombre, secreto in permitidos.items():
        if hmac.compare_digest(token.encode(), secreto.encode()):
            return Identidad("servicio", nombre)
    raise _no_autenticado()


def _usuario_desde_jwt(token: str, settings: Settings) -> Identidad:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_public_key,
            algorithms=["RS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
        sub = uuid_v4(claims["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise _no_autenticado() from None
    rol = claims.get("role")
    if rol not in ROLES:
        raise _no_autenticado()
    return Identidad("usuario", sub, rol)


def autenticar(request: Request) -> Identidad:
    """Dependencia: exige identidad válida (usuario o servicio)."""
    settings: Settings = request.app.state.settings
    service_token = request.headers.get("x-service-token")
    if service_token is not None:
        return _servicio_desde_token(service_token, settings)
    esquema, _, token = request.headers.get("authorization", "").partition(" ")
    if esquema.lower() != "bearer" or not token.strip():
        raise _no_autenticado()
    return _usuario_desde_jwt(token.strip(), settings)


def solo_servicio(request: Request) -> Identidad:
    """Dependencia: solo identidad interna (un JWT de usuario recibe 403)."""
    identidad = autenticar(request)
    if identidad.tipo != "servicio":
        raise ApiError(403, "Permiso insuficiente")
    return identidad
