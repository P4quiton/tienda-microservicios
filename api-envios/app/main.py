"""Composición de la aplicación: configuración, BD, cliente de Pedidos, rutas y contrato OpenAPI."""
import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import SERVICE_NAME, Settings, load_settings
from app.despacho import Despachador
from app.db import MigradorEnSegundoPlano, SondaListo, create_pool
from app.en_curso import EnCurso
from app.errors import register_error_handlers
from app.limites import LimitesMiddleware
from app.notificaciones import Notificador
from app.pedidos_client import PedidosClient
from app.repositorio import EnviosRepo
from app.routes import router

# Contrato normativo (docs/api/envios.yaml convertido a JSON, OpenAPI 3.0.3).
OPENAPI_SPEC = json.loads((Path(__file__).resolve().parent.parent / "openapi.json").read_text())


def create_app(
    settings: Settings, pool, pedidos=None, close_pool: bool = False,
    migrador: MigradorEnSegundoPlano | None = None, reloj=None,
) -> FastAPI:
    """`migrador=None` asume el esquema ya migrado (pruebas, migración previa explícita)."""
    esquema_listo = migrador.listo if migrador else _evento_activo()
    sonda = SondaListo(pool)

    cliente_pedidos = pedidos or PedidosClient(settings)
    notificador = Notificador(pool, cliente_pedidos, settings.notificacion_intervalo, esquema_listo)

    despachador = Despachador(
        pool, settings.despacho_segundos, settings.despacho_intervalo, esquema_listo,
        entrega_segundos=settings.entrega_segundos,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if migrador:
            migrador.iniciar()
        notificador.iniciar()  # reintenta al arrancar y luego periódicamente
        despachador.iniciar()  # barrido periódico de guías vencidas
        yield
        despachador.detener()
        notificador.detener()
        if migrador:
            migrador.detener()
        if close_pool:
            pool.close()

    app = FastAPI(title="API envios", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.settings = settings
    app.state.pool = pool
    app.state.repo = EnviosRepo(pool)
    app.state.en_curso = EnCurso()
    app.state.pedidos = cliente_pedidos
    app.state.notificador = notificador
    app.state.despachador = despachador
    app.openapi = lambda: OPENAPI_SPEC  # el contrato manda, no el esquema inferido
    register_error_handlers(app)
    app.add_middleware(LimitesMiddleware, settings=settings, **({"reloj": reloj} if reloj else {}))
    app.include_router(router)

    @app.get("/health")
    async def health():  # async: sin I/O y fuera del threadpool, que una BD colgada puede saturar
        return {"status": "ok", "service": SERVICE_NAME}

    @app.get("/ready")
    async def ready():
        if esquema_listo.is_set() and await sonda.lista():
            return {"status": "ok", "service": SERVICE_NAME}
        return JSONResponse({"status": "unavailable", "service": SERVICE_NAME}, status_code=503)

    return app


def _evento_activo() -> threading.Event:
    evento = threading.Event()
    evento.set()
    return evento


def build_app() -> FastAPI:
    """Fábrica para uvicorn: `uvicorn --factory app.main:build_app`.

    No exige BD al arrancar: /health responde siempre; /ready es 503 hasta que la BD
    conteste y las migraciones (reintentadas en segundo plano) estén aplicadas.
    """
    settings = load_settings()
    pool = create_pool(settings.database_url)
    return create_app(settings, pool, close_pool=True, migrador=MigradorEnSegundoPlano(pool))
