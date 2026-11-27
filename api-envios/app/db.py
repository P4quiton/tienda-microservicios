"""Pool de conexiones y migraciones SQL simples (migrations/*.sql en orden)."""
import asyncio
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from psycopg_pool import ConnectionPool

log = logging.getLogger("api-envios")
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
_LOCK_ID = 80030001  # evita carreras si varias réplicas migran a la vez


def create_pool(conninfo: str) -> ConnectionPool:
    pool = ConnectionPool(conninfo, min_size=1, max_size=10, open=False, timeout=3)
    pool.open()
    return pool


def migrate(pool: ConnectionPool) -> None:
    with pool.connection() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_ID,))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (nombre TEXT PRIMARY KEY)"
        )
        aplicadas = {r[0] for r in conn.execute("SELECT nombre FROM schema_migrations")}
        for archivo in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if archivo.name not in aplicadas:
                conn.execute(archivo.read_text())
                conn.execute("INSERT INTO schema_migrations VALUES (%s)", (archivo.name,))


def is_ready(pool: ConnectionPool) -> bool:
    try:
        with pool.connection(timeout=2) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


class MigradorEnSegundoPlano:
    """Migra con reintentos y backoff sin bloquear el arranque (BD caída o aún no lista).

    `listo` se activa solo tras aplicar todas las migraciones; /ready depende de él.
    migrate() es idempotente y serializa réplicas con un advisory lock.
    """

    def __init__(self, pool: ConnectionPool, espera_max: float = 30.0):
        self.listo = threading.Event()
        self._pool = pool
        self._espera_max = espera_max
        self._parar = threading.Event()
        self._hilo = threading.Thread(target=self._correr, name="migrador", daemon=True)

    def iniciar(self) -> None:
        self._hilo.start()

    def detener(self) -> None:
        self._parar.set()
        self._hilo.join(timeout=5)

    def _correr(self) -> None:
        espera = 1.0
        while not self._parar.is_set():
            try:
                migrate(self._pool)
                self.listo.set()
                return
            except Exception as exc:
                log.warning("Migración pendiente (%s); reintento en %.0fs", type(exc).__name__, espera)
                self._parar.wait(espera)
                espera = min(espera * 2, self._espera_max)


class SondaListo:
    """Comprobación de BD acotada en tiempo para /ready, aislada del threadpool de las rutas.

    Con la BD congelada (no caída) una consulta puede no volver nunca: la sonda corre en su propio
    hilo y, si el intento anterior sigue colgado, responde "no listo" sin apilar más hilos.
    """

    def __init__(self, pool: ConnectionPool, espera: float = 3.0):
        self._pool = pool
        self._espera = espera
        self._ejecutor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sonda-ready")
        self._pendiente: Future | None = None

    async def lista(self) -> bool:
        if self._pendiente is not None and not self._pendiente.done():
            return False
        self._pendiente = self._ejecutor.submit(is_ready, self._pool)
        try:
            return await asyncio.wait_for(asyncio.wrap_future(self._pendiente), self._espera)
        except asyncio.TimeoutError:
            return False
