from concurrent.futures import ThreadPoolExecutor
from shutil import copyfile
from threading import Barrier
from uuid import uuid4

import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app import db


@pytest.fixture
def pool_aislado(pool, conninfo):
    esquema = f"entrega_{uuid4().hex}"
    with pool.connection() as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(esquema)))
    try:
        with db.create_pool(make_conninfo(conninfo, options=f"-c search_path={esquema}")) as aislado:
            yield aislado
    finally:
        with pool.connection() as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(esquema)))


def _sembrar_guias(pool):
    with pool.connection() as conn:
        conn.execute("""
            INSERT INTO envios (id, pedido_id, guia, estado, codigo_postal, calle, ciudad, estado_region,
                                resultado_inicial, despachado_en)
            VALUES
                (gen_random_uuid(), gen_random_uuid(), 'sin-fecha', 'en_transito', '06600', 'Calle', 'CDMX', 'CDMX',
                 '{}', NULL),
                (gen_random_uuid(), gen_random_uuid(), 'con-fecha', 'en_transito', '06600', 'Calle', 'CDMX', 'CDMX',
                 '{}', now() - interval '1 day'),
                (gen_random_uuid(), gen_random_uuid(), 'preparando', 'preparando', '06600', 'Calle', 'CDMX', 'CDMX',
                 '{}', NULL),
                (gen_random_uuid(), gen_random_uuid(), 'entregado', 'entregado', '06600', 'Calle', 'CDMX', 'CDMX',
                 '{}', NULL)
        """)
        return conn.execute("SELECT despachado_en FROM envios WHERE guia = 'con-fecha'").fetchone()[0]


def test_003_sobre_002_con_migradores_paralelos_y_reaplicacion(pool_aislado, tmp_path, monkeypatch):
    originales = db.MIGRATIONS_DIR
    migracion = originales / "003_entrega_automatica.sql"
    for archivo in sorted(originales.glob("00[12]_*.sql")):
        copyfile(archivo, tmp_path / archivo.name)
    monkeypatch.setattr(db, "MIGRATIONS_DIR", tmp_path)
    db.migrate(pool_aislado)
    fecha_existente = _sembrar_guias(pool_aislado)
    with pool_aislado.connection() as conn:
        antes = conn.execute("SELECT now()").fetchone()[0]
    copyfile(migracion, tmp_path / migracion.name)
    barrera = Barrier(2, timeout=5)

    def migrar():
        barrera.wait()
        db.migrate(pool_aislado)

    with ThreadPoolExecutor(2) as ejecutor:
        trabajos = [ejecutor.submit(migrar) for _ in range(2)]
        for trabajo in trabajos:
            trabajo.result(timeout=10)
    db.migrate(pool_aislado)
    with pool_aislado.connection() as conn:
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE nombre = %s", (migracion.name,)
        ).fetchone() == (1,)
        fechas = dict(conn.execute("SELECT guia, despachado_en FROM envios").fetchall())
        assert antes <= fechas["sin-fecha"] <= conn.execute("SELECT now()").fetchone()[0]
        assert fechas["con-fecha"] == fecha_existente
        assert fechas["preparando"] is None and fechas["entregado"] is None
        conn.execute(migracion.read_text())
        assert dict(conn.execute("SELECT guia, despachado_en FROM envios").fetchall()) == fechas
