"""Configuración leída del entorno. Falla al arrancar si falta algo o es un marcador."""
import os
from dataclasses import dataclass
from pathlib import Path

SERVICE_NAME = "api-envios"


@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_public_key: str
    jwt_issuer: str
    jwt_audience: str
    # Identidad que Pedidos presenta ante Envíos (X-Service-Token entrante).
    token_pedidos_envios: str
    # Identidad que Envíos presenta ante Pedidos (X-Service-Token saliente).
    token_envios_pedidos: str
    pedidos_url: str
    pedidos_timeout: float
    notificacion_intervalo: float = 30.0  # segundos entre ciclos del outbox
    # Despacho simulado: segundos desde la generación de la guía y cada cuánto se barre.
    despacho_segundos: float = 60.0
    despacho_intervalo: float = 5.0
    # Rate limiting en memoria, por proceso y por minuto (ver app/limites.py).
    rate_limit_consulta: int = 120
    rate_limit_mutacion: int = 30
    rate_limit_checkout: int = 5  # no aplica a Envíos; se lee por homogeneidad con el resto de servicios
    rate_limit_interna: int = 300
    max_json_bytes: int = 262144
    entrega_segundos: int = 60  # segundos desde el despacho


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or value == "REPLACE_ME":
        raise RuntimeError(f"Variable de entorno obligatoria sin definir: {name}")
    return value


def _numero(name: str, default: str, tipo=float, minimo=0.0):
    raw = os.environ.get(name, default).strip()
    try:
        valor = tipo(raw)
    except ValueError:
        raise RuntimeError(f"{name} debe ser numérica (recibido: {raw!r})") from None
    if valor <= minimo and not (valor == minimo == 0 and name == "ENVIOS_DESPACHO_SEGUNDOS"):
        raise RuntimeError(f"{name} fuera de rango")
    return valor


def load_settings() -> Settings:
    host, port = _required("DB_HOST"), os.environ.get("DB_PORT", "5432")
    database_url = (
        f"host={host} port={port} dbname={_required('DB_DATABASE')} "
        f"user={_required('DB_USERNAME')} password={_required('DB_PASSWORD')}"
    )
    token_in = _required("SERVICE_TOKEN_PEDIDOS_ENVIOS")
    token_out = _required("SERVICE_TOKEN_ENVIOS_PEDIDOS")
    if token_in == token_out:
        raise RuntimeError("Los secretos de cada dirección deben ser distintos")
    return Settings(
        database_url=database_url,
        jwt_public_key=Path(_required("JWT_PUBLIC_KEY_PATH")).read_text(),
        jwt_issuer=_required("JWT_ISSUER"),
        jwt_audience=_required("JWT_AUDIENCE"),
        token_pedidos_envios=token_in,
        token_envios_pedidos=token_out,
        pedidos_url=_required("API_PEDIDOS_URL").rstrip("/"),
        pedidos_timeout=float(os.environ.get("PEDIDOS_TIMEOUT_SECONDS", "3")),
        notificacion_intervalo=float(os.environ.get("NOTIFICACION_INTERVALO_SECONDS", "30")),
        despacho_segundos=_numero("ENVIOS_DESPACHO_SEGUNDOS", "60"),
        despacho_intervalo=_numero("ENVIOS_DESPACHO_INTERVALO_SEGUNDOS", "5"),
        entrega_segundos=_numero("ENVIOS_ENTREGA_SEGUNDOS", "60", int),
        rate_limit_consulta=_numero("RATE_LIMIT_CONSULTA_POR_MIN", "120", int),
        rate_limit_mutacion=_numero("RATE_LIMIT_MUTACION_POR_MIN", "30", int),
        rate_limit_checkout=_numero("RATE_LIMIT_CHECKOUT_POR_MIN", "5", int),
        rate_limit_interna=_numero("RATE_LIMIT_INTERNA_POR_MIN", "300", int),
        max_json_bytes=_numero("MAX_JSON_BYTES", "262144", int),
    )
