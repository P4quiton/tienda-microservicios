"""Acceso a datos de guías. SQL parametrizado; una transacción por operación."""
import hashlib
import json
import secrets
from uuid import UUID, uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.errors import ApiError
from app.notificaciones import clave_estable
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
        """Resultado original si la clave ya se usó o el pedido ya tiene guía; None si hay que crearla.

        No consulta a Pedidos: un reintento (o una clave nueva con el mismo payload) recibe lo guardado
        aunque Pedidos esté caído. Payload incompatible: 409, también con otra clave.
        """
        return self._resolver(clave, solicitante, cuerpo, crear=False)

    def generar(self, clave: UUID, solicitante: str, cuerpo: GenerarIn) -> dict:
        """Devuelve la guía única del pedido; el efecto (guía) y la clave se confirman en una transacción.

        - Misma clave + mismo payload: resultado original guardado. Misma clave + otro payload: 409.
        - Clave nueva, mismo pedido y dirección: el mismo resultado original (una guía por pedido).
        - Clave nueva con otra dirección: 409, sin asociarla a la guía anterior.
        """
        return self._resolver(clave, solicitante, cuerpo, crear=True)

    def _resolver(self, clave: UUID, solicitante: str, cuerpo: GenerarIn, crear: bool) -> dict | None:
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
                "SELECT hash_solicitud, resultado FROM idempotencia "
                "WHERE clave = %s AND solicitante = %s AND operacion = %s",
                (clave, solicitante, OPERACION),
            ).fetchone()
            if previa:
                if previa["hash_solicitud"] != hash_solicitud:
                    raise ApiError(409, "Idempotency-Key reutilizada con otra solicitud")
                return previa["resultado"]

            d = cuerpo.direccion
            envio = cur.execute(
                "SELECT id, resultado_inicial, codigo_postal, calle, ciudad, estado_region "
                "FROM envios WHERE pedido_id = %s", (cuerpo.pedido_id,)
            ).fetchone()
            if envio is not None:
                if (envio["codigo_postal"], envio["calle"], envio["ciudad"], envio["estado_region"]) != (
                        d.codigo_postal, d.calle, d.ciudad, d.estado):
                    raise ApiError(409, "El pedido ya tiene una guía con otra dirección")
                resultado, envio_id = envio["resultado_inicial"], envio["id"]
            elif not crear:
                return None
            else:
                envio_id = uuid4()
                resultado = _a_dict({"id": envio_id, "pedido_id": cuerpo.pedido_id, "guia": _nueva_guia(),
                                     "estado": "preparando"})
                conn.execute(
                    "INSERT INTO envios (id, pedido_id, guia, codigo_postal, calle, ciudad, estado_region, "
                    "resultado_inicial) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (envio_id, cuerpo.pedido_id, resultado["guia"], d.codigo_postal, d.calle, d.ciudad,
                     d.estado, Jsonb(resultado)),
                )
            conn.execute(
                "INSERT INTO idempotencia (clave, solicitante, operacion, hash_solicitud, envio_id, pedido_id, resultado) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (clave, solicitante, OPERACION, hash_solicitud, envio_id, cuerpo.pedido_id, Jsonb(resultado)),
            )
        return resultado

    def despachar(self, pedido_id: UUID) -> dict | None:
        """Despacho real: preparando -> en_transito y notificación pendiente, en una sola transacción.

        Idempotente: repetirla no crea otra notificación. None si el pedido no tiene guía.
        """
        with self._pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            envio = cur.execute(
                f"UPDATE envios SET estado = 'en_transito', despachado_en = now() "
                f"WHERE pedido_id = %s AND estado = 'preparando' RETURNING {COLUMNAS}", (pedido_id,)
            ).fetchone()
            if envio is None:
                envio = cur.execute(f"SELECT {COLUMNAS} FROM envios WHERE pedido_id = %s", (pedido_id,)).fetchone()
                return _a_dict(envio) if envio else None
            _encolar_notificacion(conn, envio)
        return _a_dict(envio)

    def despachar_vencidos(self, segundos: float, lote: int = 50) -> int:
        """Despacha las guías en `preparando` creadas hace al menos `segundos` (fecha de la BD).

        FOR UPDATE SKIP LOCKED: réplicas simultáneas toman lotes distintos. Cada envío pasa a en_transito
        y encola su notificación en la misma transacción; el estado `preparando` garantiza que no se repite.
        """
        with self._pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            envios = cur.execute(
                "SELECT id, pedido_id FROM envios WHERE estado = 'preparando' "
                "AND creado_en <= now() - make_interval(secs => %s) "
                "ORDER BY creado_en LIMIT %s FOR UPDATE SKIP LOCKED", (segundos, lote)
            ).fetchall()
            for envio in envios:
                conn.execute("UPDATE envios SET estado = 'en_transito', despachado_en = now() WHERE id = %s",
                             (envio["id"],))
                _encolar_notificacion(conn, envio)
        return len(envios)


def _encolar_notificacion(conn, envio: dict) -> None:
    conn.execute(
        "INSERT INTO notificaciones_pedido (id, pedido_id, envio_id, idempotency_key) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT (pedido_id) DO NOTHING",
        (uuid4(), envio["pedido_id"], envio["id"], clave_estable(envio["pedido_id"])),
    )


def _nueva_guia() -> str:
    return "ENV" + secrets.token_hex(6).upper()
