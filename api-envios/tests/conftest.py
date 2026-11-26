"""Fixtures: PostgreSQL 17 real (TEST_DATABASE_URL o contenedor Docker), claves RSA efímeras y Pedidos falso."""
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import create_pool, migrate
from app.errors import ApiError
from app.main import create_app
from app.pedidos_client import PedidoInfo

ISSUER, AUDIENCE = "api-usuarios", "tienda-microservicios"
TOKEN_IN, TOKEN_OUT = "token-pedidos-a-envios-de-prueba", "token-envios-a-pedidos-de-prueba"


def _pem_pair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return private, public


@pytest.fixture(scope="session")
def keys():
    return _pem_pair()


@pytest.fixture(scope="session")
def conninfo():
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        yield url
        return
    try:
        cid = subprocess.run(
            ["docker", "run", "-d", "--rm", "-p", "127.0.0.1::5432", "-e", "POSTGRES_PASSWORD=test",
             "-e", "POSTGRES_DB=db_envios", "postgres:17-alpine"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("Sin TEST_DATABASE_URL ni Docker para levantar PostgreSQL 17")
    try:
        port = subprocess.run(["docker", "port", cid, "5432/tcp"], capture_output=True, text=True,
                              check=True).stdout.split(":")[-1].strip()
        info = f"host=127.0.0.1 port={port} dbname=db_envios user=postgres password=test"
        for _ in range(60):
            try:
                psycopg.connect(info, connect_timeout=2).close()
                break
            except psycopg.OperationalError:
                time.sleep(1)
        else:
            pytest.fail("PostgreSQL de prueba no arrancó")
        yield info
    finally:
        subprocess.run(["docker", "stop", cid], capture_output=True)


@pytest.fixture(scope="session")
def pool(conninfo):
    p = create_pool(conninfo)
    migrate(p)
    yield p
    p.close()


@pytest.fixture
def settings(keys, conninfo):
    return Settings(
        database_url=conninfo, jwt_public_key=keys[1], jwt_issuer=ISSUER, jwt_audience=AUDIENCE,
        token_pedidos_envios=TOKEN_IN, token_envios_pedidos=TOKEN_OUT,
        pedidos_url="http://pedidos.invalid", pedidos_timeout=1,
    )


class PedidosFalso:
    def __init__(self):
        self.pedidos: dict = {}
        self.caido = False
        self.patch_caido = False
        self.patches: list = []  # (pedido_id, clave) de cada intento de PATCH enviado

    def marcar_enviado(self, pedido_id, clave) -> None:
        from app.pedidos_client import NotificacionFallida
        self.patches.append((str(pedido_id), str(clave)))
        if self.patch_caido:
            raise NotificacionFallida("HTTP 503")

    def agregar(self, usuario_id: str, estado: str = "pagado") -> str:
        pedido_id = str(uuid4())
        self.pedidos[pedido_id] = PedidoInfo(usuario_id, estado)
        return pedido_id

    def obtener(self, pedido_id) -> PedidoInfo:
        if self.caido:
            raise ApiError(503, "Pedidos no disponible o respuesta inválida")
        try:
            return self.pedidos[str(pedido_id)]
        except KeyError:
            raise ApiError(404, "Pedido no encontrado") from None


@pytest.fixture
def pedidos():
    return PedidosFalso()


@pytest.fixture
def client(settings, pool, pedidos):
    with pool.connection() as conn:
        conn.execute("TRUNCATE notificaciones_pedido, idempotencia, envios")
    return TestClient(create_app(settings, pool, pedidos), raise_server_exceptions=False)


@pytest.fixture
def make_token(keys):
    def _make(sub=None, role="cliente", **overrides):
        ahora = datetime.now(timezone.utc)
        claims = {"sub": sub or str(uuid4()), "role": role, "iss": ISSUER, "aud": AUDIENCE,
                  "iat": ahora, "exp": ahora + timedelta(minutes=60)}
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, keys[0], algorithm="RS256")
    return _make


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


SERVICIO = {"X-Service-Token": TOKEN_IN}
DIRECCION = {"codigo_postal": "06600", "calle": "Reforma 1", "ciudad": "CDMX", "estado": "CDMX"}
