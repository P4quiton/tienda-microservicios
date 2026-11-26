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


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or value == "REPLACE_ME":
        raise RuntimeError(f"Variable de entorno obligatoria sin definir: {name}")
    return value


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
    )
