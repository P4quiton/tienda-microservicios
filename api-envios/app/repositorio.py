"""Acceso a datos de guías. SQL parametrizado; una transacción por operación."""
import hashlib
import json
import secrets
from uuid import UUID, uuid4

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.errors import ApiError
from app.schemas import GenerarIn

OPERACION = "generar_guia"
COLUMNAS = "id, pedido_id, guia, estado"


def _hash(cuerpo: GenerarIn) -> str:
    canonico = json.dumps(cuerpo.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(canonico.encode()).hexdigest()


def _a_dict(fila: dict) -> dict:
    return {k: str(v) if isinstance(v, UUID) else v for k, v in fila.items()}


class EnviosRepo:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def buscar_por_guia(self, guia: str) -> dict | None:
        if "\x00" in guia:  # ninguna guía puede contenerlo; PostgreSQL lo rechazaría con error
            return None
        with self._pool.connection() as conn:
            fila = conn.cursor(row_factory=dict_row).execute(
                f"SELECT {COLUMNAS} FROM envios WHERE guia = %s", (guia,)
            ).fetchone()
        return _a_dict(fila) if fila else None

    def resultado_previo(self, clave: UUID, solicitante: str, cuerpo: GenerarIn) -> dict | None:
        """Respuesta guardada para esta clave (sin bloqueos: solo lee filas ya confirmadas).

        Permite repetir una solicitud idéntica sin depender de Pedidos. None si la clave es nueva;
        409 si se reutilizó con otro payload.
        """
        with self._pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            previa = cur.execute(
                "SELECT hash_solicitud, envio_id FROM idempotencia "
                "WHERE clave = %s AND solicitante = %s AND operacion = %s",
                (clave, solicitante, OPERACION),
            ).fetchone()
            if previa is None:
                return None
            if previa["hash_solicitud"] != _hash(cuerpo):
                raise ApiError(409, "Idempotency-Key reutilizada con otra solicitud")
            return self._por_id(cur, previa["envio_id"])

    def generar(self, clave: UUID, solicitante: str, cuerpo: GenerarIn) -> dict:
        """Devuelve la guía única del pedido; crea una sola vez aunque se repita o compita.

        - Misma clave + mismo payload: resultado previo. Misma clave + otro payload: 409.
        - Clave nueva para el mismo pedido y dirección: la misma guía (una por pedido).
        - Clave nueva con otra dirección: 409, sin asociarla a la guía anterior.
        """
        hash_solicitud = _hash(cuerpo)
        with self._pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            # Misma clave en curso (otra réplica): 409 sin esperar. Mismo pedido con otra clave:
            # espera breve (solo operaciones de BD) para devolver la misma guía. Orden fijo.
            libre = conn.execute(
                "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))", (f"clave:{clave}",)
            ).fetchone()[0]
            if not libre:
                raise ApiError(409, "Solicitud con la misma Idempotency-Key en curso")
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"pedido:{cuerpo.pedido_id}",)
            )
            previa = cur.execute(
                "SELECT hash_solicitud, envio_id FROM idempotencia "
                "WHERE clave = %s AND solicitante = %s AND operacion = %s",
                (clave, solicitante, OPERACION),
            ).fetchone()
            if previa:
                if previa["hash_solicitud"] != hash_solicitud:
                    raise ApiError(409, "Idempotency-Key reutilizada con otra solicitud")
                return self._por_id(cur, previa["envio_id"])

            envio = cur.execute(
                f"SELECT {COLUMNAS}, codigo_postal, calle, ciudad, estado_region "
                "FROM envios WHERE pedido_id = %s", (cuerpo.pedido_id,)
            ).fetchone()
            d = cuerpo.direccion
            if envio is not None:
                direccion_guardada = tuple(envio.pop(campo) for campo in (
                    "codigo_postal", "calle", "ciudad", "estado_region"
                ))
                if direccion_guardada != (d.codigo_postal, d.calle, d.ciudad, d.estado):
                    raise ApiError(409, "El pedido ya tiene una guía con otra dirección")
            if envio is None:
                envio = cur.execute(
                    f"INSERT INTO envios (id, pedido_id, guia, codigo_postal, calle, ciudad, estado_region) "
                    f"VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING {COLUMNAS}",
                    (uuid4(), cuerpo.pedido_id, _nueva_guia(), d.codigo_postal, d.calle, d.ciudad, d.estado),
                ).fetchone()
            conn.execute(
                "INSERT INTO idempotencia (clave, solicitante, operacion, hash_solicitud, envio_id) "
                "VALUES (%s, %s, %s, %s, %s)",
                (clave, solicitante, OPERACION, hash_solicitud, envio["id"]),
            )
        return _a_dict(envio)

    @staticmethod
    def _por_id(cur, envio_id: UUID) -> dict:
        return _a_dict(cur.execute(f"SELECT {COLUMNAS} FROM envios WHERE id = %s", (envio_id,)).fetchone())


def _nueva_guia() -> str:
    return "ENV" + secrets.token_hex(6).upper()
