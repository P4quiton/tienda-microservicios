"""Escenario 11: invoca la funcion interna EnviosRepo.despachar (el contrato no define disparador HTTP).

Uso (desde api-envios, con el mismo entorno de BD que el servicio): python despachar.py PEDIDO_ID
Imprime JSON con el resultado de despachar y la fila del outbox `notificaciones_pedido`.
"""
import json
import os
import sys
from uuid import UUID

sys.path.insert(0, os.environ["API_ENVIOS_DIR"])
from app.db import create_pool  # noqa: E402
from app.repositorio import EnviosRepo  # noqa: E402

conninfo = (f"host={os.environ['DB_HOST']} port={os.environ['DB_PORT']} dbname={os.environ['DB_DATABASE']} "
            f"user={os.environ['DB_USERNAME']} password={os.environ['DB_PASSWORD']}")
pool = create_pool(conninfo)
pedido = UUID(sys.argv[1])
resultado = EnviosRepo(pool).despachar(pedido)
with pool.connection() as conn:
    cur = conn.execute("select * from notificaciones_pedido where pedido_id = %s", (pedido,))
    cols = [c.name for c in cur.description]
    filas = [dict(zip(cols, f)) for f in cur.fetchall()]
print(json.dumps({"despachar": resultado, "outbox": filas}, default=str))
pool.close()
