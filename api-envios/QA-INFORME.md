# QA "romper y arreglar" de api-envios

Fecha: 2026-11-26. Alcance: solo `mojarra3/api-envios`. Sin cambios a `docs/api/*.yaml` ni a otros servicios.
Método: barrido hostil con scripts desechables (en proceso, TestClient + PostgreSQL 17 real), luego prueba de
regresión roja, arreglo y verde.

## Resumen

| | Antes | Después |
|---|---|---|
| Pruebas | 58 pasan (el encargo decía 50) | 68 pasan (10 nuevas en `tests/test_hostil.py`) |
| Bugs | 5 hallados | 5 arreglados |

## Hallazgos

| # | Severidad | Hallazgo | Arreglo |
|---|---|---|---|
| 1 | Alta | Con la BD **colgada** (no caída; p. ej. `docker pause`) las rutas sync llenan el threadpool y `/health` (sync) deja de responder: la sonda de vida falla; `/ready` puede no volver nunca. | `/health` ahora es `async` y sin I/O. `/ready` usa `SondaListo` (`app/db.py`): hilo propio, tope 3 s, y si el intento previo sigue colgado responde 503 sin apilar hilos. |
| 2 | Media | `NUL` (`\u0000`) o sustituto UTF-16 suelto (`\ud800`) en `calle`/`ciudad`/`estado` provocaba 500 al insertar en PostgreSQL. | Validador `_almacenable` en `app/schemas.py`: 422. |
| 3 | Media | `GET /rastreo/a%00b` devolvía 500. | `buscar_por_guia` devuelve `None` (404) si la guía contiene NUL. |
| 4 | Media | `cantidad` grande (p. ej. 10^9) devolvía 200 con `costo_envio` de 11+ dígitos, violando el patrón `^\d{1,10}\.\d{2}$` del contrato. | `cotizar` lanza `CantidadFueraDeRango` si el importe supera 9999999999.99; la ruta responde 422 con error en `cantidad`. |
| 5 | Baja | Entero de miles de dígitos en el JSON: 400 con mensaje genérico "Error". | El 400 de Starlette se mapea a "JSON inválido". |

Cambio a una prueba existente: `test_sin_limites_propios_mas_estrictos_que_el_contrato` fijaba `cantidad=10**12 -> 200`, que
contradice el patrón de importe del contrato (hallazgo 4). Se cambió a `10**6`. README actualizado en las dos reglas afectadas.

## Atacado sin hallazgos

- JSON malformado, UTF-8 inválido, `NaN`, cuerpo array/null, campos extra, `bool` como entero, CP con `\n` o dígitos Unicode: 400/422.
- Idempotency-Key no v4 -> 422; mayúsculas normalizadas.
- JWT: `alg=none`, HS256, clave ajena, expirado, `iss`/`aud`/`role`/`sub` erróneos, `exp` enorme, token de 1 MB, cabeceras no ASCII: 401.
- X-Service-Token vacío, equivocado, no ASCII o del otro par (Envíos->Pedidos): 401; un JWT de usuario en `/generar`: 403.
- Titularidad: cliente A sobre guía de B: 403 (pruebas existentes).
- Concurrencia (80 solicitudes en 40 hilos, misma pedido, mitad con la misma clave): 1 sola guía, 1 fila en `envios`; 200 solicitudes con claves distintas sobre 20 pedidos: 20 filas. Las repetidas en curso reciben 409 (contrato).
- Migraciones: 8 `migrate()` en paralelo y repetidas: una sola fila en `schema_migrations`, sin error.
- BD caída: `/health` 200, `/ready` 503, rutas de negocio 503 (pruebas existentes); BD pausada y reanudada: `/ready` 503 en 3.0 s y luego 200.
- Inyección SQL en `guia` y `calle`: consultas parametrizadas; se guarda literal; la tabla sigue íntegra.

## Comandos y salida

```
docker run --rm -d --name mojarra-pg-envios -p 55433:5432 --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_PASSWORD=<aleatoria local> -e POSTGRES_DB=db_envios postgres:17
export TEST_DATABASE_URL='host=127.0.0.1 port=55433 dbname=db_envios user=postgres password=<local>'
/mnt/disco/desarrollo-local/tienda/envios/api-envios/.venv/bin/python -m pytest -q -p no:cacheprovider
```

- Línea base: `58 passed, 1 warning in 7.06s`
- Regresiones en rojo (antes de arreglar): `9 failed` en `tests/test_hostil.py` y, tras añadir la de BD colgada, `1 failed` (health sin respuesta en 3 s).
- Final: `68 passed, 1 warning in 12.44s`
- Verificación manual con `docker pause` del contenedor propio: `health 200 ready 503 3.0s`; tras `unpause`, `ready 200`.

## Pendientes y decisiones abiertas

1. **Rutas de negocio con BD colgada**: siguen esperando (psycopg no tiene tiempo límite de consulta del lado cliente si el servidor
   está congelado). Con `/health` ya aislado el proceso no se reinicia por esto, pero las peticiones de negocio se acumulan.
   Mitigar con timeouts del proxy/Kubernetes o un `statement_timeout`/cancelación; requiere decisión.
2. **Tamaño de cuerpo**: una `calle` de 3 MB se acepta (201). El contrato no declara longitudes ni 413; limitar el tamaño lo ve mejor
   el proxy (`client_max_body_size` en Nginx). Decisión del coordinador.
3. **Vida del JWT**: `docs/seguridad.md` dice exp de 60 min, pero Envíos acepta cualquier `exp` futuro firmado correctamente. Rechazar
   `exp - iat > 3600` es defensa en profundidad; no se aplicó para no arriesgar tokens reales de api-usuarios (margen de reloj).
4. `POST /api/envios/cotizar/` (barra final) responde 307 redirect; cosmético.
5. **NO VERIFICADO**: build de imagen Docker (prohibido por el encargo), ejecución con uvicorn real y Pedidos real, y el rate limit 429
   del contrato (no implementado en este servicio).
6. Nota de entorno: el venv indicado (`envios/api-envios/.venv`) se usó sin modificarlo; el scratchpad es compartido y otro agente
   sobrescribió un archivo temporal mío (contraseña), sin otro efecto.

## Contrato 1.1.0

Cambios: `openapi.json` regenerado desde `upstream/docs/checkout-contracts:docs/api/envios.yaml` (v1.1.0); migración `002_contrato_1_1_0.sql`;
`app/notificaciones.py` (outbox + trabajador); `PedidosClient.marcar_enviado`; `EnviosRepo` reescrito alrededor de un solo camino bloqueado.

- **/generar**: antes el resultado guardado era solo una referencia al envío (devolvía el estado actual, no el original) y una clave nueva
  con el mismo pedido consultaba antes a Pedidos (503 si caído, incluso con payload incompatible que debía ser 409). Ahora `resultado` JSONB
  se persiste con la clave y el efecto en una transacción, `pedido_id` queda atado a cada clave, y repetición/payload incompatible se
  resuelven sin Pedidos. Efecto nunca repetido: `UNIQUE(pedido_id)` en `envios` + advisory locks por clave y por pedido.
- **Estado inicial** `preparando`; generar no notifica. **Despacho real** = `EnviosRepo.despachar` (interna). Notificación: outbox en PostgreSQL,
  una por pedido, creada atómicamente con el paso a `en_transito`; PATCH con token propio e Idempotency-Key v4 determinista por pedido;
  reintento al arrancar y periódico, backoff exponencial, lease contra trabajadores simultáneos; sobrevive a reinicios (prueba con un
  `Notificador` nuevo sobre la misma BD). Probado también que la migración rellena datos preexistentes.
- **Pruebas** (PG17 temporal en 55443): línea base `67 passed, 1 failed` (`test_openapi_json_es_el_contrato_valido`: el `openapi.json` de
  1.0.0 difería del YAML 1.1.0 ya presente en `../docs`). Regresiones nuevas (`tests/test_despacho_outbox.py`, 19) en rojo: error de
  colección (módulos/tablas inexistentes). Final: `87 passed, 1 warning`.
- **Pendientes**: (1) el contrato no define el disparador del despacho real: no se inventó endpoint; falta decidir (p. ej. endpoint de
  transportista/admin o evento) y llamar a `despachar`. (2) Un 409/4xx persistente de Pedidos se reintenta indefinidamente (tope 15 min)
  guardando `ultimo_error`; no hay alerta ni estado de revisión manual. (3) NO VERIFICADO contra un Pedidos real (cliente probado con httpx simulado).
  (4) La clave estable es UUID v4 por hash, no uuid5, porque `contratos-api.md` exige v4.
