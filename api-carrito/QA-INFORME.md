# QA "romper y arreglar": api-carrito (puerto 8005)

Entorno: Node v24.18.1, Express 5.3.0, PostgreSQL 17 temporal (`mojarra-pg-carrito`, puerto 55435, tmpfs, detenido al final).
Suite nueva: `test/qa-hostil.test.js` (21 pruebas). No se cambió `docs/api/*.yaml` ni otros servicios.

## Resultado antes / después

| Momento | Comando | Resultado |
|---|---|---|
| Línea base | `TEST_DATABASE_URL=... npm test` | 9 pruebas, 9 OK |
| Tras escribir la suite, antes de arreglar | `node --test test/qa-hostil.test.js` | 18 pruebas, 13 OK, **5 fallan** (la 6.ª, migración concurrente, se añadió después y falló también) |
| Final con BD | `npm test` | **30 pruebas, 30 OK, 0 fallos** (25 ejecuciones consecutivas sin fallos) |
| Final sin BD | `env -u TEST_DATABASE_URL npm test` | 20 pruebas, 17 OK, 3 omitidas (las que requieren PostgreSQL) |

## Hallazgos

| # | Sev. | Hallazgo (prueba roja) | Arreglo |
|---|---|---|---|
| 1 | Media | Ruta con porcentaje mal codificado (`/api/carrito/%E0%A4%A`) y `Content-Type` con charset desconocido devolvían **500** "Error interno" (errores 4xx de Express/body-parser reclasificados como 500). | `src/app.js`: errores de cliente no-ApiError con status 4xx devuelven 400 "Solicitud incorrecta". |
| 2 | Media | BD colgada/cortada: el error del pool `timeout exceeded when trying to connect` (sin `code`) devolvía **500** en vez de 503. También `Connection terminated...`, 53300, 57P03. | `src/app.js`: `isDatabaseUnavailable` reconoce códigos y mensajes del driver, y `AggregateError` con ECONNREFUSED. |
| 3 | Media | Migración ejecutada en paralelo sobre BD virgen (varias réplicas) fallaba con `duplicate key ... pg_type_typname_nsp_index` (7 de 8). | `migrations/001-carrito.sql`: `pg_advisory_xact_lock` tras `BEGIN`. Dos ejecuciones seguidas y 8 paralelas OK. |
| 4 | Baja | Repetición idempotente devolvía el JSON con otro orden de claves que la primera respuesta (jsonb reordena). | `src/store.js`: `canonical()`/`lines()` reconstruyen la forma del contrato en repetición de `agregar`, `prepararCheckout`, `confirmar` y `cancelar`. |
| 5 | Baja | Con `usuario_id` inválido y sin credencial se respondía 422 antes que 401 (orden validación/autenticación). | `src/app.js`: GET y `agregar` autentican primero (401/403) y validan el UUID después (422). |

## Ataques que NO encontraron fallo (cubiertos por pruebas)

- JSON malformado, arreglos/primitivos/`null`, campos extra (`precio`, `usuario_id`, `__proto__`), tipos erróneos de `cantidad`, `1e400`, 0, negativos, > 2^31-1: 400/422, nunca 5xx.
- UUID v1/v5/nil/con llaves/sin guiones en ruta, cuerpo y `Idempotency-Key`: 422.
- Cuerpo de 20 kB y 5 MB: 400/4xx. Respuestas de error sin stack traces.
- JWT: `alg=none`, HS256 con clave pública como secreto, RS384/PS256, otra clave, payload alterado, expirado, `iat` futuro, vigencia de 2 h, sin `exp`/`sub`, `sub` no v4, rol inválido, emisor/audiencia ajenos, truncado, sin firma, esquema Basic: todos 401.
- Titularidad: usuario A sobre B en GET y `agregar` = 403 sin tocar la BD; admin accede.
- `X-Service-Token` ausente, vacío, parcial, mayúsculas, de otro par, enviado como Bearer; servicio sin token configurado: 401.
- Concurrencia con PostgreSQL real: 30 peticiones misma clave y cuerpo, un solo efecto; misma clave con cuerpos distintos, un 200 y 19 x 409; 40 claves distintas suman 40; tope de disponibilidad 5 con 20 carreras da exactamente 5; misma clave desde dos carritos de un admin, un solo efecto.
- Inyección SQL en ruta, cuerpo y cabeceras: 422; esquema intacto (consultas parametrizadas).
- `/health` 200 y `/ready` 503 con BD caída (puerto cerrado y host que no responde) y sin migración; 200 tras migrar.

## Comandos

```sh
docker run --rm -d --name mojarra-pg-carrito -p 55435:5432 --tmpfs /var/lib/postgresql/data -e POSTGRES_PASSWORD=<aleatoria> postgres:17
DB_HOST=127.0.0.1 DB_PORT=55435 DB_DATABASE=postgres DB_USERNAME=postgres DB_PASSWORD=<aleatoria> node src/migrate.js   # 2 veces seguidas: OK
TEST_DATABASE_URL=postgres://postgres:<aleatoria>@127.0.0.1:55435/postgres npm test
docker stop mojarra-pg-carrito
```

## Pendientes / NO VERIFICADO

- **NO VERIFICADO**: `docker build` del Dockerfile (prohibido por la tarea; disco raíz casi lleno) y despliegue en Compose/Kubernetes.
- **NO VERIFICADO**: el protocolo experimental `/checkout/*` por HTTP bajo ataque concurrente (solo las pruebas existentes; la capa de almacenamiento sí está cubierta).
- Diseño (Media): `available()` (2 llamadas HTTP, 1 s cada una) se ejecuta dentro de la transacción con el candado del carrito; un Productos/Inventario lento retiene conexiones (pool de 10) y degrada a 503. Sacar la consulta de la transacción rompería la garantía de tope bajo carrera; requiere decisión del equipo.
- `DELETE /vaciar` responde 409 si el carrito tiene artículos (comportamiento documentado en README, pendiente de acordar con Pedidos).
- `carrito_adiciones` crece sin límite (sin expiración de claves de idempotencia).
- No hay rate limiting ni longitud mínima exigida para `SERVICE_TOKEN_PEDIDOS_CARRITO` (solo se rechaza vacío/`REPLACE_ME`).
- Un cuerpo > 16 kB devuelve 400 (el contrato no define 413).
- Importes MXN: este servicio no recibe importes; el rechazo de campos extra (`precio`) está probado, pero la validación de decimales MXN no aplica aquí.

## Nota de reverificación
Las pruebas con base de datos exigen aplicar antes `node src/migrate.js` sobre la BD de prueba. Sin migrar, 9 de las 30 fallan (comprobado en una BD vacía); con la migración aplicada pasan las 30.
